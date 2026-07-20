#!/usr/bin/env python3
"""Prepare and execute one explicitly approved public peer-validation request.

This script is the final *validation* gate for the dormant claim-bound browser
transport. It is deliberately not a runtime feature and is never called by CI,
BrowserHost, ToolGate or an API route.

``prepare`` performs no DNS lookup and opens no socket. It binds a short-lived,
one-use plan to the exact clean candidate and a SHA-256 of one HTTPS URL, then
prints a random challenge and a candidate-bound approval phrase. Neither secret
is written to the plan.

``run`` refuses to proceed unless all of the following are simultaneously true:

* the original candidate is still the clean checked-out HEAD;
* the plan is fresh, regular, repository-local and still unconsumed;
* the exact URL and random challenge match the plan;
* ``--execute-public-network`` is present; and
* ``MODELRIG_PUBLIC_NETWORK_VALIDATION`` equals the printed approval phrase.

The plan is moved atomically to a unique consumed filename and re-read byte for
byte *before* DNS. A successful run performs exactly one GET through the real
common claim, public DNS/peer binding, numeric-IP TLS transport, aggregate byte
meter and committed-response evidence path. Redirects are not followed. Reports
contain hashes and bounded network metadata, never the URL path/query, challenge,
response body, research purpose or summary.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "worker"
if str(WORKER) not in sys.path:
    sys.path.insert(0, str(WORKER))

from app.browser_peer_fulfillment import (  # noqa: E402
    BrowserPeerFulfillmentController,
    PinnedBrowserPeerTransport,
)
from app.browser_peer_runtime import ClaimBoundBrowserEvidence  # noqa: E402
from app.browser_use_network_guard import browser_request_allowed  # noqa: E402
from app.build_identity import code_fingerprint  # noqa: E402
from app.research_claim_evidence import (  # noqa: E402
    VerifiableDataSharingLedger,
    VerifiableResearchSharingBoundary,
)
from app.research_contract import (  # noqa: E402
    ReadOnlyBrowserPolicy,
    ResearchContractError,
    canonicalize_url,
)
from app.research_data_sharing import ResearchSharingIntent  # noqa: E402
from app.research_egress import EgressPlan  # noqa: E402
from app.research_peer_authorization import ResearchPeerAuthorizationBridge  # noqa: E402
from app.research_peer_transfer import ResearchPeerTransferLedger  # noqa: E402
from app.web_fetch import default_resolver  # noqa: E402

PLAN_SCHEMA = "kaliv-browser-peer-public-validation-plan/v1"
REPORT_SCHEMA = "kaliv-browser-peer-public-validation/v1"
APPROVAL_ENV = "MODELRIG_PUBLIC_NETWORK_VALIDATION"
DEFAULT_PLAN = Path("validation/browser-peer-public-validation-plan.json")
DEFAULT_REPORT = Path("validation/browser-peer-public-validation-latest.json")
PLAN_TTL_SECONDS = 10 * 60
MAX_PLAN_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
MAX_OUTBOUND_BYTES = 4096
TIMEOUT_SECONDS = 15.0
_CHALLENGE = re.compile(r"^bpv1_[a-f0-9]{32}$")
_PLAN_ID = re.compile(r"^bpv_[a-f0-9]{32}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")

IdentityProvider = Callable[[Path], dict[str, Any]]
NonceFactory = Callable[[], str]
Resolver = Callable[[str, int], Sequence[str]]


class PublicValidationError(RuntimeError):
    """The validation command cannot produce trustworthy evidence."""


def _iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _safe_error(exc: Exception) -> dict[str, str]:
    return {
        "type": type(exc).__name__,
        "message": str(exc).replace("\r", " ").replace("\n", " ")[:500],
    }


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def _run(root: Path, *args: str) -> tuple[int, str]:
    try:
        process = subprocess.run(
            args,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    output = (process.stdout or process.stderr or "").strip()
    return process.returncode, output


def candidate_identity(root: Path) -> dict[str, Any]:
    try:
        version = (root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise PublicValidationError("VERSION cannot be read") from exc
    if not version:
        raise PublicValidationError("VERSION is empty")
    rc, git_sha = _run(root, "git", "rev-parse", "HEAD")
    if rc != 0 or re.fullmatch(r"[a-f0-9]{40}", git_sha) is None:
        raise PublicValidationError("git HEAD is unavailable or malformed")
    _, branch = _run(root, "git", "branch", "--show-current")
    _, dirty = _run(root, "git", "status", "--porcelain")
    version_rc, version_detail = _run(
        root,
        sys.executable,
        "scripts/version_tool.py",
        "check",
    )
    fingerprint = code_fingerprint()
    if _SHA256.fullmatch(fingerprint) is None:
        raise PublicValidationError("worker code fingerprint is invalid")
    return {
        "version": version,
        "git_sha": git_sha,
        "code_sha256": fingerprint,
        "branch": branch or None,
        "working_tree_clean": not bool(dirty),
        "dirty_entries": len(dirty.splitlines()) if dirty else 0,
        "version_stamps_consistent": version_rc == 0,
        "version_check_detail": None if version_rc == 0 else version_detail[-500:],
    }


def _require_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise PublicValidationError("candidate identity is invalid")
    if not candidate.get("working_tree_clean"):
        raise PublicValidationError("candidate working tree is not clean")
    if not candidate.get("version_stamps_consistent"):
        raise PublicValidationError("candidate version stamps are inconsistent")
    if re.fullmatch(r"[a-f0-9]{40}", str(candidate.get("git_sha", ""))) is None:
        raise PublicValidationError("candidate git SHA is invalid")
    if _SHA256.fullmatch(str(candidate.get("code_sha256", ""))) is None:
        raise PublicValidationError("candidate code fingerprint is invalid")
    if not isinstance(candidate.get("version"), str) or not candidate["version"]:
        raise PublicValidationError("candidate version is invalid")
    return candidate


def _validation_path(root: Path, raw: Path, *, must_exist: bool) -> Path:
    candidate = raw if raw.is_absolute() else root / raw
    if candidate.is_symlink():
        raise PublicValidationError("validation path must not be a symlink")
    resolved = candidate.resolve()
    validation_root = (root / "validation").resolve()
    try:
        resolved.relative_to(validation_root)
    except ValueError as exc:
        raise PublicValidationError(
            "validation path must be under the repository validation directory"
        ) from exc
    if must_exist:
        if not resolved.exists() or not resolved.is_file():
            raise PublicValidationError("validation plan is missing")
        if resolved.is_symlink():
            raise PublicValidationError("validation plan must not be a symlink")
    return resolved


def _target(raw_url: str) -> tuple[str, str, int, str]:
    if not isinstance(raw_url, str) or not raw_url.strip():
        raise PublicValidationError("validation URL is required")
    try:
        canonical = canonicalize_url(raw_url.strip())
        parsed = urlsplit(canonical)
        port = parsed.port or 443
    except (ResearchContractError, ValueError) as exc:
        raise PublicValidationError("validation URL is outside the web contract") from exc
    host = parsed.hostname or ""
    if parsed.scheme != "https" or port != 443:
        raise PublicValidationError("validation URL must use HTTPS on port 443")
    if not host or parsed.username is not None or parsed.password is not None:
        raise PublicValidationError("validation URL authority is invalid")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise PublicValidationError("validation URL must use a DNS hostname")
    lowered = host.lower().rstrip(".")
    if lowered == "localhost" or lowered.endswith(_LOCAL_SUFFIXES):
        raise PublicValidationError("validation URL must use a public hostname")
    if not browser_request_allowed(canonical, (lowered,)):
        raise PublicValidationError("validation URL is outside the browser policy")
    return canonical, lowered, port, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _approval_phrase(plan: dict[str, Any]) -> str:
    return (
        "EXECUTE-ONE-MODELRIG-PUBLIC-GET:"
        f"{plan['plan_id']}:{plan['candidate']['git_sha'][:12]}"
    )


def _default_nonce() -> str:
    return secrets.token_hex(16)


def prepare_plan(
    raw_url: str,
    plan_path: Path,
    *,
    root: Path = ROOT,
    now: int | None = None,
    identity_provider: IdentityProvider = candidate_identity,
    nonce_factory: NonceFactory = _default_nonce,
) -> tuple[dict[str, Any], str, str]:
    timestamp = int(time.time()) if now is None else now
    if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
        raise PublicValidationError("prepare timestamp is invalid")
    path = _validation_path(root, plan_path, must_exist=False)
    if path.exists():
        raise PublicValidationError("an unconsumed validation plan already exists")
    canonical, host, port, url_sha256 = _target(raw_url)
    del canonical
    candidate = _require_candidate(identity_provider(root))
    nonce = nonce_factory()
    if not isinstance(nonce, str) or re.fullmatch(r"[a-f0-9]{32}", nonce) is None:
        raise PublicValidationError("nonce factory returned an invalid value")
    challenge = f"bpv1_{nonce}"
    plan = {
        "schema": PLAN_SCHEMA,
        "state": "prepared",
        "plan_id": f"bpv_{uuid.uuid4().hex}",
        "generated_at": _iso(timestamp),
        "generated_at_unix": timestamp,
        "expires_at": _iso(timestamp + PLAN_TTL_SECONDS),
        "expires_at_unix": timestamp + PLAN_TTL_SECONDS,
        "candidate": candidate,
        "target": {
            "host": host,
            "port": port,
            "url_sha256": url_sha256,
        },
        "challenge_sha256": hashlib.sha256(challenge.encode("ascii")).hexdigest(),
        "limits": {
            "method": "GET",
            "max_outbound_bytes": MAX_OUTBOUND_BYTES,
            "max_response_bytes": MAX_RESPONSE_BYTES,
            "timeout_seconds": TIMEOUT_SECONDS,
            "redirects_followed": False,
        },
        "public_network_contacted": False,
        "production_activation": False,
    }
    _write_json_atomic(path, plan)
    return plan, challenge, _approval_phrase(plan)


def _load_plan(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink():
        raise PublicValidationError("validation plan must not be a symlink")
    size = path.stat().st_size
    if size <= 0 or size > MAX_PLAN_BYTES:
        raise PublicValidationError("validation plan size is invalid")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicValidationError("validation plan is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise PublicValidationError("validation plan must be a JSON object")
    return value, raw


def _validate_plan(
    plan: dict[str, Any],
    raw_url: str,
    challenge: str,
    *,
    root: Path,
    now: int,
    identity_provider: IdentityProvider,
    execute_public_network: bool,
    approval_value: str | None,
) -> str:
    if execute_public_network is not True:
        raise PublicValidationError("--execute-public-network is required")
    if plan.get("schema") != PLAN_SCHEMA or plan.get("state") != "prepared":
        raise PublicValidationError("validation plan schema or state is invalid")
    if not isinstance(plan.get("plan_id"), str) or _PLAN_ID.fullmatch(plan["plan_id"]) is None:
        raise PublicValidationError("validation plan id is invalid")
    if not isinstance(challenge, str) or _CHALLENGE.fullmatch(challenge) is None:
        raise PublicValidationError("validation challenge is invalid")
    if hashlib.sha256(challenge.encode("ascii")).hexdigest() != plan.get(
        "challenge_sha256"
    ):
        raise PublicValidationError("validation challenge does not match the plan")
    expected_approval = _approval_phrase(plan)
    if approval_value != expected_approval:
        raise PublicValidationError(
            f"{APPROVAL_ENV} does not contain the candidate-bound approval phrase"
        )
    expires_at = plan.get("expires_at_unix")
    generated_at = plan.get("generated_at_unix")
    if (
        isinstance(expires_at, bool)
        or not isinstance(expires_at, int)
        or isinstance(generated_at, bool)
        or not isinstance(generated_at, int)
        or expires_at <= generated_at
    ):
        raise PublicValidationError("validation plan timestamps are invalid")
    if now < generated_at - 15 or now > expires_at:
        raise PublicValidationError("validation plan is not currently fresh")
    canonical, host, port, url_sha256 = _target(raw_url)
    target = plan.get("target")
    if not isinstance(target, dict) or target != {
        "host": host,
        "port": port,
        "url_sha256": url_sha256,
    }:
        raise PublicValidationError("validation URL does not match the plan")
    planned_candidate = _require_candidate(plan.get("candidate"))
    current_candidate = _require_candidate(identity_provider(root))
    for key in ("version", "git_sha", "code_sha256", "branch"):
        if current_candidate.get(key) != planned_candidate.get(key):
            raise PublicValidationError(f"candidate {key} changed after plan preparation")
    limits = plan.get("limits")
    if limits != {
        "method": "GET",
        "max_outbound_bytes": MAX_OUTBOUND_BYTES,
        "max_response_bytes": MAX_RESPONSE_BYTES,
        "timeout_seconds": TIMEOUT_SECONDS,
        "redirects_followed": False,
    }:
        raise PublicValidationError("validation plan limits changed")
    return canonical


def _consume_plan(path: Path, plan: dict[str, Any], raw: bytes) -> Path:
    consumed = path.with_name(
        f"{path.stem}.consumed-{plan['plan_id']}{path.suffix}"
    )
    if consumed.exists() or consumed.is_symlink():
        raise PublicValidationError("consumed validation plan already exists")
    try:
        os.replace(path, consumed)
    except OSError as exc:
        raise PublicValidationError("validation plan could not be consumed") from exc
    try:
        moved = consumed.read_bytes()
    except OSError as exc:
        raise PublicValidationError("consumed validation plan cannot be read") from exc
    if moved != raw:
        raise PublicValidationError("validation plan changed while being consumed")
    return consumed


def _event(canonical_url: str, plan_id: str) -> dict[str, Any]:
    suffix = hashlib.sha256(plan_id.encode("ascii")).hexdigest()[:16]
    return {
        "requestId": f"public-validation-fetch-{suffix}",
        "networkId": f"public-validation-network-{suffix}",
        "request": {
            "url": canonical_url,
            "method": "GET",
            "headers": {
                "Accept": "text/html,application/xhtml+xml,text/plain,application/json",
                "User-Agent": "ModelRig-Public-Validation/1.0",
            },
            "hasPostData": False,
        },
        "resourceType": "Document",
    }


def execute_plan(
    raw_url: str,
    challenge: str,
    plan_path: Path,
    report_path: Path,
    *,
    execute_public_network: bool,
    approval_value: str | None,
    root: Path = ROOT,
    now: int | None = None,
    identity_provider: IdentityProvider = candidate_identity,
    resolver: Resolver = default_resolver,
    transport: PinnedBrowserPeerTransport | None = None,
) -> dict[str, Any]:
    timestamp = int(time.time()) if now is None else now
    if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
        raise PublicValidationError("run timestamp is invalid")
    path = _validation_path(root, plan_path, must_exist=True)
    report = _validation_path(root, report_path, must_exist=False)
    plan, raw_plan = _load_plan(path)
    canonical = _validate_plan(
        plan,
        raw_url,
        challenge,
        root=root,
        now=timestamp,
        identity_provider=identity_provider,
        execute_public_network=execute_public_network,
        approval_value=approval_value,
    )
    consumed = _consume_plan(path, plan, raw_plan)

    network_contacted = False
    common = boundary = peer = evidence_store = None
    intent = lease = None
    pending = None
    claim_terminal = False
    result: dict[str, Any] | None = None

    def gated_resolver(host: str, port: int) -> Sequence[str]:
        nonlocal network_contacted
        network_contacted = True
        return resolver(host, port)

    try:
        intent = ResearchSharingIntent(
            plan=EgressPlan(
                destination="browser-use",
                purpose="Validate one explicitly approved public peer transfer",
                payload_sha256=hashlib.sha256(
                    _canonical_json(
                        {
                            "plan_id": plan["plan_id"],
                            "url_sha256": plan["target"]["url_sha256"],
                        }
                    )
                ).hexdigest(),
                sensitivity="public",
                allowed_domains=(plan["target"]["host"],),
                max_bytes=MAX_OUTBOUND_BYTES,
            ),
            summary="One bounded GET-only public transport validation.",
        )
        common = VerifiableDataSharingLedger()
        boundary = VerifiableResearchSharingBoundary(common, mode="enforce")
        bridge = ResearchPeerAuthorizationBridge(boundary)
        lease = boundary.prepare(intent, now=timestamp, receipt_ttl_seconds=120)
        claim = boundary.claim(lease, intent, now=timestamp + 1)
        peer = ResearchPeerTransferLedger(bridge, gated_resolver)
        controller = BrowserPeerFulfillmentController.create(
            bridge,
            peer,
            claim,
            lease,
            intent,
            timeout_seconds=TIMEOUT_SECONDS,
            max_response_bytes=MAX_RESPONSE_BYTES,
            transport=transport,
        )
        evidence_store = ClaimBoundBrowserEvidence(
            controller,
            max_evidence_bytes=MAX_RESPONSE_BYTES,
            max_evidence_responses=1,
        )
        pending = evidence_store.prepare(
            _event(canonical, plan["plan_id"]),
            now=timestamp + 2,
            ttl_seconds=30,
        )
        binding = pending.permit.binding
        payload = pending.payload
        pending.commit(now=timestamp + 3)
        pending = None
        policy = ReadOnlyBrowserPolicy(
            allowed_domains=(plan["target"]["host"],),
            max_steps=1,
            max_pages=1,
            timeout_seconds=int(TIMEOUT_SECONDS),
            max_source_bytes=MAX_RESPONSE_BYTES,
        )
        trace = evidence_store.fetch(canonical, policy)
        audit = evidence_store.audit()
        if len(audit) != 1:
            raise PublicValidationError("committed evidence audit is incomplete")
        boundary.complete(
            lease,
            intent,
            outcome="completed",
            bytes_sent=controller.bytes_sent,
            now=timestamp + 4,
        )
        claim_terminal = True
        result = {
            "schema": REPORT_SCHEMA,
            "generated_at": _iso(timestamp + 4),
            "passed": True,
            "candidate": plan["candidate"],
            "plan": {
                "plan_id": plan["plan_id"],
                "consumed_path": str(consumed.relative_to(root.resolve())),
                "consumed_sha256": hashlib.sha256(raw_plan).hexdigest(),
            },
            "target": plan["target"],
            "dns": {
                "answer_count": len(binding.addresses),
                "addresses": list(binding.addresses),
                "dns_sha256": binding.dns_sha256,
                "selected_address": binding.selected_address,
            },
            "transport": {
                "connected_address": payload.connected_address,
                "connected_port": payload.connected_port,
                "bytes_sent": controller.bytes_sent,
                "response_status": payload.response_code,
                "response_body_bytes": len(payload.body),
                "response_body_sha256": hashlib.sha256(payload.body).hexdigest(),
            },
            "citation": {
                "adapter": trace.receipt.adapter,
                "content_sha256": trace.receipt.content_sha256,
                "bytes_read": trace.receipt.bytes_read,
                "media_type": trace.receipt.media_type,
            },
            "evidence": audit[0],
            "limits": plan["limits"],
            "public_network_contacted": network_contacted,
            "redirects_followed": False,
            "validation_only": True,
            "production_activation": False,
            "error": None,
        }
        _write_json_atomic(report, result)
        return result
    except Exception as exc:
        if pending is not None:
            try:
                pending.abort(
                    error_code="public_validation_failed",
                    now=timestamp + 3,
                )
            except Exception:
                pass
        if (
            boundary is not None
            and lease is not None
            and intent is not None
            and not claim_terminal
        ):
            try:
                bytes_sent = (
                    evidence_store.bytes_sent if evidence_store is not None else 0
                )
                boundary.complete(
                    lease,
                    intent,
                    outcome="blocked",
                    bytes_sent=bytes_sent,
                    error_code="public_validation_failed",
                    now=timestamp + 4,
                )
                claim_terminal = True
            except Exception:
                pass
        failure = {
            "schema": REPORT_SCHEMA,
            "generated_at": _iso(timestamp),
            "passed": False,
            "candidate": plan.get("candidate"),
            "plan": {
                "plan_id": plan.get("plan_id"),
                "consumed_path": str(consumed.relative_to(root.resolve())),
                "consumed_sha256": hashlib.sha256(raw_plan).hexdigest(),
            },
            "target": plan.get("target"),
            "public_network_contacted": network_contacted,
            "validation_only": True,
            "production_activation": False,
            "error": _safe_error(exc),
        }
        _write_json_atomic(report, failure)
        raise PublicValidationError("public validation failed") from exc
    finally:
        if evidence_store is not None:
            evidence_store.close()
        if peer is not None:
            peer.close()
        if common is not None:
            common.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("prepare", "run"), required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--challenge")
    parser.add_argument("--execute-public-network", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "prepare":
        plan, challenge, approval = prepare_plan(args.url, args.plan)
        print(
            json.dumps(
                {
                    "schema": PLAN_SCHEMA,
                    "plan_id": plan["plan_id"],
                    "expires_at": plan["expires_at"],
                    "challenge": challenge,
                    "approval_environment": APPROVAL_ENV,
                    "approval_value": approval,
                    "next_command": (
                        f"python scripts/browser_peer_public_validation.py --mode run "
                        f"--url <SAME_URL> --plan {args.plan} --report {args.report} "
                        "--challenge <CHALLENGE> --execute-public-network"
                    ),
                    "public_network_contacted": False,
                    "production_activation": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if not args.challenge:
        raise SystemExit("--challenge is required in run mode")
    try:
        result = execute_plan(
            args.url,
            args.challenge,
            args.plan,
            args.report,
            execute_public_network=args.execute_public_network,
            approval_value=os.getenv(APPROVAL_ENV),
        )
    except PublicValidationError as exc:
        print(f"public validation refused or failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
