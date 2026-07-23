#!/usr/bin/env python3
"""Run the one-use browser peer public validation on an interactive Windows rig.

The underlying validator remains the authority for URL policy, candidate identity,
one-use authorization, DNS/peer binding, TLS transport, byte ceilings and the
redacted receipt. This operator wrapper adds the physical-host boundary:

* Windows only;
* interactive terminal only;
* refuses GitHub Actions and generic CI environments;
* never prints the transient challenge or approval value;
* requires a typed confirmation after the offline prepare phase;
* records a local, candidate-bound physical attestation over the exact receipt.

No BrowserHost, ToolGate, API route or production feature is activated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "browser_peer_public_validation.py"
DEFAULT_PLAN = Path("validation/browser-peer-public-validation-plan.json")
DEFAULT_REPORT = Path("validation/browser-peer-public-validation-latest.json")
DEFAULT_ATTESTATION = Path(
    "validation/browser-peer-public-validation-physical-latest.json"
)
ATTESTATION_SCHEMA = "kaliv-browser-peer-public-validation-physical/v1"
REPORT_SCHEMA = "kaliv-browser-peer-public-validation/v1"
APPROVAL_ENV = "MODELRIG_PUBLIC_NETWORK_VALIDATION"
CONFIRMATION = "EXECUTE ONE PUBLIC GET"
MAX_JSON_BYTES = 1024 * 1024


class OperatorValidationError(RuntimeError):
    """The operator flow cannot produce trustworthy physical evidence."""


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
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


def _validation_path(root: Path, raw: Path, *, must_exist: bool) -> Path:
    candidate = raw if raw.is_absolute() else root / raw
    if candidate.is_symlink():
        raise OperatorValidationError("validation path must not be a symlink")
    resolved = candidate.resolve()
    validation_root = (root / "validation").resolve()
    try:
        resolved.relative_to(validation_root)
    except ValueError as exc:
        raise OperatorValidationError(
            "validation path must remain under the repository validation directory"
        ) from exc
    if must_exist and (not resolved.exists() or not resolved.is_file()):
        raise OperatorValidationError("required validation file is missing")
    return resolved


def _load_json(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.exists() or not path.is_file():
        raise OperatorValidationError(f"validation JSON is unavailable: {path.name}")
    size = path.stat().st_size
    if size <= 0 or size > MAX_JSON_BYTES:
        raise OperatorValidationError(f"validation JSON size is invalid: {path.name}")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OperatorValidationError(
            f"validation JSON is malformed: {path.name}"
        ) from exc
    if not isinstance(value, dict):
        raise OperatorValidationError(f"validation JSON is not an object: {path.name}")
    return value, raw


def _run(
    args: Sequence[str],
    *,
    root: Path,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    try:
        process = subprocess.run(
            list(args),
            cwd=root,
            env=dict(env) if env is not None else None,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OperatorValidationError("validator process could not complete") from exc
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "validator failed").strip()
        detail = detail.replace("\r", " ").replace("\n", " ")[:500]
        raise OperatorValidationError(detail)
    try:
        value = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise OperatorValidationError("validator did not return JSON") from exc
    if not isinstance(value, dict):
        raise OperatorValidationError("validator result is not a JSON object")
    return value


def _require_physical_operator(
    *,
    environ: Mapping[str, str],
    system_name: str,
    stdin_isatty: bool,
    stdout_isatty: bool,
) -> None:
    if system_name != "Windows":
        raise OperatorValidationError("physical browser validation must run on Windows")
    if environ.get("GITHUB_ACTIONS", "").lower() == "true":
        raise OperatorValidationError("GitHub Actions cannot create physical rig evidence")
    if environ.get("CI", "").lower() in {"1", "true", "yes"}:
        raise OperatorValidationError("CI cannot create physical rig evidence")
    if not stdin_isatty or not stdout_isatty:
        raise OperatorValidationError(
            "physical browser validation requires an interactive terminal"
        )


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _validate_result(result: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if result.get("schema") != REPORT_SCHEMA:
        errors.append("unexpected public validation schema")
    if result.get("passed") is not True:
        errors.append("public validation did not pass")
    if result.get("public_network_contacted") is not True:
        errors.append("public network was not contacted")
    if result.get("validation_only") is not True:
        errors.append("receipt is not marked validation_only")
    if result.get("production_activation") is not False:
        errors.append("receipt did not preserve production_activation=false")
    if result.get("redirects_followed") is not False:
        errors.append("receipt followed a redirect")
    if result.get("error") not in {None, ""}:
        errors.append("receipt contains an error")

    candidate = result.get("candidate")
    if not isinstance(candidate, dict):
        errors.append("candidate identity is missing")
        candidate = {}
    if candidate.get("working_tree_clean") is not True:
        errors.append("candidate was not clean")
    if candidate.get("version_stamps_consistent") is not True:
        errors.append("candidate version stamps were inconsistent")
    if not isinstance(candidate.get("git_sha"), str) or len(candidate["git_sha"]) != 40:
        errors.append("candidate git SHA is invalid")
    if not _sha256(candidate.get("code_sha256")):
        errors.append("candidate worker fingerprint is invalid")

    target = result.get("target")
    dns = result.get("dns")
    transport = result.get("transport")
    citation = result.get("citation")
    evidence = result.get("evidence")
    limits = result.get("limits")
    plan = result.get("plan")
    for label, value in (
        ("target", target),
        ("dns", dns),
        ("transport", transport),
        ("citation", citation),
        ("evidence", evidence),
        ("limits", limits),
        ("plan", plan),
    ):
        if not isinstance(value, dict):
            errors.append(f"{label} section is missing")

    target = target if isinstance(target, dict) else {}
    dns = dns if isinstance(dns, dict) else {}
    transport = transport if isinstance(transport, dict) else {}
    citation = citation if isinstance(citation, dict) else {}
    evidence = evidence if isinstance(evidence, dict) else {}
    limits = limits if isinstance(limits, dict) else {}
    plan = plan if isinstance(plan, dict) else {}

    if target.get("port") != 443 or not _sha256(target.get("url_sha256")):
        errors.append("target is not a hashed HTTPS/443 destination")
    if not isinstance(target.get("host"), str) or not target["host"]:
        errors.append("target host is missing")
    if dns.get("selected_address") != transport.get("connected_address"):
        errors.append("selected DNS peer differs from connected peer")
    if transport.get("connected_port") != 443:
        errors.append("transport did not connect to port 443")
    if transport.get("response_status") != evidence.get("status"):
        errors.append("transport/evidence status mismatch")
    if transport.get("bytes_sent") != evidence.get("bytes_sent"):
        errors.append("transport/evidence byte count mismatch")
    if transport.get("response_body_bytes") != citation.get("bytes_read"):
        errors.append("transport/citation response size mismatch")
    if transport.get("response_body_bytes") != evidence.get("response_body_bytes"):
        errors.append("transport/evidence response size mismatch")
    body_hash = transport.get("response_body_sha256")
    if not _sha256(body_hash):
        errors.append("response body digest is invalid")
    if body_hash != citation.get("content_sha256") or body_hash != evidence.get(
        "response_body_sha256"
    ):
        errors.append("response/evidence/citation digests do not match")
    if citation.get("adapter") != "deterministic-web-fetch":
        errors.append("unexpected citation adapter")
    if evidence.get("production_activation") is not False:
        errors.append("committed evidence activated production")
    if limits.get("method") != "GET" or limits.get("redirects_followed") is not False:
        errors.append("receipt limits are not GET-only/no-redirect")
    if not isinstance(plan.get("consumed_path"), str) or ".consumed-" not in plan.get(
        "consumed_path", ""
    ):
        errors.append("one-use plan was not consumed")
    if not _sha256(plan.get("consumed_sha256")):
        errors.append("consumed plan digest is invalid")

    if errors:
        raise OperatorValidationError("; ".join(errors))
    return {
        "candidate": candidate,
        "target": target,
        "dns": dns,
        "transport": transport,
        "citation": citation,
        "evidence": evidence,
        "limits": limits,
        "plan": plan,
    }


def _cancel_plan(path: Path, expected_plan_id: str | None) -> None:
    try:
        plan, _ = _load_json(path)
    except Exception:
        return
    if expected_plan_id and plan.get("plan_id") != expected_plan_id:
        return
    try:
        path.unlink()
    except OSError:
        pass


def run_guided(
    raw_url: str,
    *,
    root: Path = ROOT,
    plan_path: Path = DEFAULT_PLAN,
    report_path: Path = DEFAULT_REPORT,
    attestation_path: Path = DEFAULT_ATTESTATION,
    input_fn: Callable[[str], str] = input,
) -> dict[str, Any]:
    _require_physical_operator(
        environ=os.environ,
        system_name=platform.system(),
        stdin_isatty=sys.stdin.isatty(),
        stdout_isatty=sys.stdout.isatty(),
    )
    plan = _validation_path(root, plan_path, must_exist=False)
    report = _validation_path(root, report_path, must_exist=False)
    attestation = _validation_path(root, attestation_path, must_exist=False)
    if plan.exists():
        raise OperatorValidationError(
            "an unconsumed validation plan already exists; review it before retrying"
        )
    if not VALIDATOR.exists():
        raise OperatorValidationError("public validation command is missing")

    prepared: dict[str, Any] | None = None
    try:
        prepared = _run(
            (
                sys.executable,
                str(VALIDATOR),
                "--mode",
                "prepare",
                "--url",
                raw_url,
                "--plan",
                str(plan),
                "--report",
                str(report),
            ),
            root=root,
        )
        challenge = prepared.get("challenge")
        approval = prepared.get("approval_value")
        plan_id = prepared.get("plan_id")
        if not all(isinstance(value, str) and value for value in (challenge, approval, plan_id)):
            raise OperatorValidationError("prepare output is incomplete")
        plan_value, _ = _load_json(plan)
        candidate = plan_value.get("candidate") if isinstance(plan_value, dict) else None
        target = plan_value.get("target") if isinstance(plan_value, dict) else None
        if not isinstance(candidate, dict) or not isinstance(target, dict):
            raise OperatorValidationError("prepared plan lacks candidate or target identity")

        print("\nFysisk browser-peer-validering er klar:")
        print(f"  Host:        {target.get('host')}:{target.get('port')}")
        print(f"  URL SHA-256: {target.get('url_sha256')}")
        print(f"  Kandidat:    {candidate.get('git_sha')}")
        print(f"  Udløber:     {prepared.get('expires_at')}")
        print("  Netværk:     endnu ikke kontaktet")
        typed = input_fn(f"\nSkriv præcis '{CONFIRMATION}' for at udføre ét GET: ")
        if typed != CONFIRMATION:
            _cancel_plan(plan, plan_id)
            raise OperatorValidationError("operator confirmation did not match; no DNS was used")

        child_env = os.environ.copy()
        child_env[APPROVAL_ENV] = approval
        try:
            result = _run(
                (
                    sys.executable,
                    str(VALIDATOR),
                    "--mode",
                    "run",
                    "--url",
                    raw_url,
                    "--plan",
                    str(plan),
                    "--report",
                    str(report),
                    "--challenge",
                    challenge,
                    "--execute-public-network",
                ),
                root=root,
                env=child_env,
            )
        finally:
            child_env.pop(APPROVAL_ENV, None)
            approval = ""
            challenge = ""

        selected = _validate_result(result)
        report_value, report_raw = _load_json(report)
        if _canonical_json(report_value) != _canonical_json(result):
            raise OperatorValidationError("printed result and persisted receipt differ")

        now = datetime.now(timezone.utc)
        physical = {
            "schema": ATTESTATION_SCHEMA,
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "candidate": selected["candidate"],
            "host": {
                "hostname": socket.gethostname(),
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "machine": platform.machine(),
                "platform": platform.platform(),
                "python": platform.python_version(),
            },
            "operator": {
                "interactive_terminal": True,
                "typed_confirmation": True,
                "github_actions": False,
                "ci": False,
            },
            "receipt": {
                "path": str(report.relative_to(root.resolve())),
                "sha256": hashlib.sha256(report_raw).hexdigest(),
                "schema": result.get("schema"),
                "generated_at": result.get("generated_at"),
                "target": selected["target"],
                "dns": {
                    "answer_count": selected["dns"].get("answer_count"),
                    "dns_sha256": selected["dns"].get("dns_sha256"),
                    "selected_address": selected["dns"].get("selected_address"),
                },
                "transport": selected["transport"],
                "citation": selected["citation"],
                "plan": selected["plan"],
            },
            "gate": {
                "passed": True,
                "windows_host": True,
                "interactive_operator": True,
                "candidate_bound": True,
                "receipt_integrity": True,
                "public_network_contacted": True,
                "production_activation": False,
            },
        }
        _write_json_atomic(attestation, physical)
        print("\nPASS — fysisk browser-peer-validering gennemført")
        print(f"  Peer:        {selected['transport'].get('connected_address')}:443")
        print(f"  HTTP:        {selected['transport'].get('response_status')}")
        print(f"  Sendt:       {selected['transport'].get('bytes_sent')} bytes")
        print(f"  Modtaget:    {selected['transport'].get('response_body_bytes')} bytes")
        print(f"  Receipt:     {report.relative_to(root.resolve())}")
        print(f"  Attestation: {attestation.relative_to(root.resolve())}")
        return physical
    except Exception:
        if prepared is not None:
            _cancel_plan(plan, prepared.get("plan_id"))
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--attestation", type=Path, default=DEFAULT_ATTESTATION)
    args = parser.parse_args(argv)
    try:
        run_guided(
            args.url,
            plan_path=args.plan,
            report_path=args.report,
            attestation_path=args.attestation,
        )
    except OperatorValidationError as exc:
        print(f"BLOCKED — {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
