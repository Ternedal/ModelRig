#!/usr/bin/env python3
"""Combine the six-proof physical campaign with physical T-032 peer evidence.

This script performs no network request. It validates the existing campaign
receipt, the interactive-Windows attestation and the exact underlying browser
peer receipt against one current clean candidate, then writes a seventh-proof
final receipt with production_activation=false.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import ipaddress
import json
import platform
import re
import socket
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "kaliv-physical-validation-final/v1"
CAMPAIGN_SCHEMA = "kaliv-physical-validation-campaign/v1"
ATTESTATION_SCHEMA = "kaliv-browser-peer-public-validation-physical/v1"
PUBLIC_SCHEMA = "kaliv-browser-peer-public-validation/v1"
DEFAULT_CAMPAIGN = Path("validation/physical-validation-campaign-latest.json")
DEFAULT_ATTESTATION = Path(
    "validation/browser-peer-public-validation-physical-latest.json"
)
DEFAULT_REPORT = Path("validation/physical-validation-final-latest.json")
MAX_EVIDENCE_BYTES = 32 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GITSHA = re.compile(r"^[0-9a-f]{40}$")


class FinalGateError(RuntimeError):
    """Final physical evidence is incomplete or untrustworthy."""


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
        temporary = Path(handle.name)
    temporary.replace(path)


def _resolve_under(root: Path, raw: Path) -> Path:
    unresolved = raw if raw.is_absolute() else root / raw
    if unresolved.is_symlink():
        raise FinalGateError(f"evidence path is a symlink: {raw}")
    resolved = unresolved.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise FinalGateError(f"evidence path escapes repository: {raw}") from exc
    return resolved


def _load_json(root: Path, raw_path: Path) -> tuple[dict[str, Any], bytes, Path]:
    path = _resolve_under(root, raw_path)
    if not path.exists() or not path.is_file() or path.is_symlink():
        raise FinalGateError(f"evidence file is missing or irregular: {raw_path}")
    size = path.stat().st_size
    if size <= 0 or size > MAX_EVIDENCE_BYTES:
        raise FinalGateError(f"evidence file size is invalid: {raw_path}")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinalGateError(f"evidence is not valid UTF-8 JSON: {raw_path}") from exc
    if not isinstance(value, dict):
        raise FinalGateError(f"evidence is not a JSON object: {raw_path}")
    return value, raw, path


def _nested(value: Mapping[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _fresh(errors: list[str], label: str, value: Any, now: datetime, hours: float) -> None:
    observed = _timestamp(value)
    if observed is None:
        errors.append(f"{label} is not a timezone-aware timestamp")
        return
    age = (now - observed).total_seconds() / 3600
    if age < -0.25:
        errors.append(f"{label} is in the future")
    elif age > hours:
        errors.append(f"{label} is {age:.1f}h old; max is {hours:.1f}h")


def _load_candidate_identity(root: Path) -> dict[str, Any]:
    path = root / "scripts" / "physical_validation_campaign.py"
    spec = importlib.util.spec_from_file_location("physical_campaign_identity", path)
    if spec is None or spec.loader is None:
        raise FinalGateError("physical campaign module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    candidate = module.candidate_identity(root)
    if not isinstance(candidate, dict):
        raise FinalGateError("candidate identity is invalid")
    return candidate


def _same_candidate(
    errors: list[str], label: str, actual: Any, expected: Mapping[str, Any]
) -> None:
    if not isinstance(actual, Mapping):
        errors.append(f"{label} candidate is missing")
        return
    for key in ("version", "git_sha", "code_sha256"):
        if actual.get(key) != expected.get(key):
            errors.append(f"{label} candidate.{key} mismatch")


def _digest(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _public_ip(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


def validate_campaign(
    report: Mapping[str, Any], candidate: Mapping[str, Any], errors: list[str]
) -> dict[str, Any]:
    if report.get("schema") != CAMPAIGN_SCHEMA:
        errors.append("campaign schema mismatch")
    if report.get("mode") != "verify":
        errors.append("campaign was not produced in verify mode")
    _same_candidate(errors, "campaign", report.get("candidate"), candidate)
    if _nested(report, "gate", "passed") is not True:
        errors.append("campaign gate.passed is not true")
    if _nested(report, "gate", "physical_campaign_complete") is not True:
        errors.append("six-proof physical campaign is incomplete")
    if _nested(report, "gate", "production_activation") is not False:
        errors.append("campaign did not preserve production_activation=false")
    summary = report.get("summary")
    if not isinstance(summary, Mapping):
        errors.append("campaign summary is missing")
        summary = {}
    if summary.get("failed") not in ([], None):
        errors.append("campaign contains failed evidence")
    if summary.get("missing") not in ([], None):
        errors.append("campaign contains missing evidence")
    if summary.get("candidate_errors") not in ([], None):
        errors.append("campaign contains candidate errors")
    passed = summary.get("passed")
    total = summary.get("total")
    if not isinstance(passed, list) or not isinstance(total, int) or len(passed) != total:
        errors.append("campaign pass count does not equal total")
    return {"total": total, "passed": passed}


def validate_public_receipt(
    receipt: Mapping[str, Any], candidate: Mapping[str, Any], errors: list[str]
) -> dict[str, Any]:
    if receipt.get("schema") != PUBLIC_SCHEMA:
        errors.append("browser receipt schema mismatch")
    _same_candidate(errors, "browser receipt", receipt.get("candidate"), candidate)
    if receipt.get("passed") is not True:
        errors.append("browser receipt passed is not true")
    if receipt.get("public_network_contacted") is not True:
        errors.append("browser receipt did not contact the public network")
    if receipt.get("validation_only") is not True:
        errors.append("browser receipt is not validation-only")
    if receipt.get("production_activation") is not False:
        errors.append("browser receipt activated production")
    if receipt.get("redirects_followed") is not False:
        errors.append("browser receipt followed redirects")
    if receipt.get("error") not in {None, ""}:
        errors.append("browser receipt contains an error")

    target = receipt.get("target") if isinstance(receipt.get("target"), Mapping) else {}
    dns = receipt.get("dns") if isinstance(receipt.get("dns"), Mapping) else {}
    transport = (
        receipt.get("transport") if isinstance(receipt.get("transport"), Mapping) else {}
    )
    citation = (
        receipt.get("citation") if isinstance(receipt.get("citation"), Mapping) else {}
    )
    evidence = (
        receipt.get("evidence") if isinstance(receipt.get("evidence"), Mapping) else {}
    )
    limits = receipt.get("limits") if isinstance(receipt.get("limits"), Mapping) else {}
    plan = receipt.get("plan") if isinstance(receipt.get("plan"), Mapping) else {}

    if target.get("port") != 443 or not _digest(target.get("url_sha256")):
        errors.append("browser target is not hashed HTTPS/443")
    addresses = dns.get("addresses")
    if not isinstance(addresses, list) or not addresses:
        errors.append("browser DNS answer set is missing")
        addresses = []
    if dns.get("answer_count") != len(addresses):
        errors.append("browser DNS answer_count mismatch")
    if any(not _public_ip(value) for value in addresses):
        errors.append("browser DNS answer set contains a non-public address")
    selected = dns.get("selected_address")
    if selected not in addresses or not _public_ip(selected):
        errors.append("browser selected peer is not a public DNS answer")
    if selected != transport.get("connected_address"):
        errors.append("browser selected peer differs from connected peer")
    if transport.get("connected_port") != 443:
        errors.append("browser transport did not use port 443")
    if not isinstance(transport.get("response_status"), int) or not (
        200 <= transport["response_status"] < 400
    ):
        errors.append("browser response status is not successful")

    max_outbound = limits.get("max_outbound_bytes")
    max_response = limits.get("max_response_bytes")
    sent = transport.get("bytes_sent")
    body_bytes = transport.get("response_body_bytes")
    if limits.get("method") != "GET" or limits.get("redirects_followed") is not False:
        errors.append("browser limits are not GET-only/no-redirect")
    if not isinstance(max_outbound, int) or not isinstance(sent, int) or not (
        0 < sent <= max_outbound
    ):
        errors.append("browser outbound byte accounting is invalid")
    if not isinstance(max_response, int) or not isinstance(body_bytes, int) or not (
        0 < body_bytes <= max_response
    ):
        errors.append("browser response byte accounting is invalid")

    body_hash = transport.get("response_body_sha256")
    if not _digest(body_hash):
        errors.append("browser response digest is invalid")
    if body_hash != citation.get("content_sha256") or body_hash != evidence.get(
        "response_body_sha256"
    ):
        errors.append("browser response/evidence/citation digest mismatch")
    if citation.get("bytes_read") != body_bytes:
        errors.append("browser citation byte count mismatch")
    if citation.get("adapter") != "deterministic-web-fetch":
        errors.append("browser citation adapter mismatch")
    if evidence.get("selected_address") != selected:
        errors.append("browser committed evidence peer mismatch")
    if evidence.get("bytes_sent") != sent:
        errors.append("browser committed evidence outbound bytes mismatch")
    if evidence.get("response_body_bytes") != body_bytes:
        errors.append("browser committed evidence response bytes mismatch")
    if evidence.get("status") != transport.get("response_status"):
        errors.append("browser committed evidence status mismatch")
    if evidence.get("production_activation") is not False:
        errors.append("browser committed evidence activated production")
    if not isinstance(plan.get("consumed_path"), str) or ".consumed-" not in plan.get(
        "consumed_path", ""
    ):
        errors.append("browser one-use plan was not consumed")
    if not _digest(plan.get("consumed_sha256")):
        errors.append("browser consumed-plan digest is invalid")

    return {
        "target_host": target.get("host"),
        "target_url_sha256": target.get("url_sha256"),
        "selected_address": selected,
        "connected_address": transport.get("connected_address"),
        "response_status": transport.get("response_status"),
        "bytes_sent": sent,
        "response_body_bytes": body_bytes,
        "content_sha256": body_hash,
        "citation_adapter": citation.get("adapter"),
    }


def validate_attestation(
    root: Path,
    attestation: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    now: datetime,
    max_age_hours: float,
    errors: list[str],
) -> tuple[dict[str, Any], bytes, Path]:
    if attestation.get("schema") != ATTESTATION_SCHEMA:
        errors.append("physical browser attestation schema mismatch")
    _fresh(errors, "attestation.generated_at", attestation.get("generated_at"), now, max_age_hours)
    _same_candidate(errors, "physical browser attestation", attestation.get("candidate"), candidate)
    host = attestation.get("host") if isinstance(attestation.get("host"), Mapping) else {}
    operator = (
        attestation.get("operator")
        if isinstance(attestation.get("operator"), Mapping)
        else {}
    )
    gate = attestation.get("gate") if isinstance(attestation.get("gate"), Mapping) else {}
    if host.get("system") != "Windows":
        errors.append("physical browser attestation was not produced on Windows")
    if operator.get("interactive_terminal") is not True or operator.get(
        "typed_confirmation"
    ) is not True:
        errors.append("physical browser attestation lacks interactive confirmation")
    if operator.get("github_actions") is not False or operator.get("ci") is not False:
        errors.append("physical browser attestation came from CI")
    for key in (
        "passed",
        "windows_host",
        "interactive_operator",
        "candidate_bound",
        "receipt_integrity",
        "public_network_contacted",
    ):
        if gate.get(key) is not True:
            errors.append(f"physical browser gate.{key} is not true")
    if gate.get("production_activation") is not False:
        errors.append("physical browser gate activated production")

    receipt_meta = (
        attestation.get("receipt")
        if isinstance(attestation.get("receipt"), Mapping)
        else {}
    )
    receipt_path_value = receipt_meta.get("path")
    if not isinstance(receipt_path_value, str) or not receipt_path_value:
        raise FinalGateError("physical browser receipt path is missing")
    receipt, raw, path = _load_json(root, Path(receipt_path_value))
    actual_hash = hashlib.sha256(raw).hexdigest()
    if actual_hash != receipt_meta.get("sha256"):
        errors.append("physical browser receipt hash does not match attestation")
    _fresh(errors, "browser receipt.generated_at", receipt.get("generated_at"), now, max_age_hours)
    summary = validate_public_receipt(receipt, candidate, errors)
    for section in ("target", "transport", "citation", "plan"):
        expected = receipt_meta.get(section)
        actual = receipt.get(section)
        if section == "target" and expected != actual:
            errors.append("attested browser target differs from receipt")
        elif section == "transport" and expected != actual:
            errors.append("attested browser transport differs from receipt")
        elif section == "citation" and expected != actual:
            errors.append("attested browser citation differs from receipt")
        elif section == "plan" and expected != actual:
            errors.append("attested browser plan differs from receipt")
    return summary, raw, path


def evaluate_final_gate(
    root: Path,
    campaign_path: Path,
    attestation_path: Path,
    *,
    candidate: Mapping[str, Any],
    now: datetime,
    max_age_hours: float,
) -> tuple[dict[str, Any], int]:
    errors: list[str] = []
    campaign, campaign_raw, campaign_file = _load_json(root, campaign_path)
    attestation, attestation_raw, attestation_file = _load_json(root, attestation_path)
    _fresh(errors, "campaign.generated_at", campaign.get("generated_at"), now, max_age_hours)
    campaign_summary = validate_campaign(campaign, candidate, errors)
    browser_summary, browser_raw, browser_file = validate_attestation(
        root,
        attestation,
        candidate,
        now=now,
        max_age_hours=max_age_hours,
        errors=errors,
    )
    base_passed = campaign_summary.get("passed")
    passed_names = list(base_passed) if isinstance(base_passed, list) else []
    if not errors:
        passed_names.append("browser_peer_physical")
    total = campaign_summary.get("total")
    final_total = total + 1 if isinstance(total, int) else None
    report = {
        "schema": SCHEMA,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "candidate": dict(candidate),
        "host": {
            "hostname": socket.gethostname(),
            "system": platform.system(),
            "platform": platform.platform(),
        },
        "configuration": {"max_age_hours": max_age_hours},
        "evidence": {
            "physical_campaign": {
                "path": str(campaign_file.relative_to(root.resolve())),
                "sha256": hashlib.sha256(campaign_raw).hexdigest(),
                "bytes": len(campaign_raw),
                "status": "pass" if not any(e.startswith("campaign") or "campaign" in e for e in errors) else "fail",
                "summary": campaign_summary,
            },
            "browser_peer_physical_attestation": {
                "path": str(attestation_file.relative_to(root.resolve())),
                "sha256": hashlib.sha256(attestation_raw).hexdigest(),
                "bytes": len(attestation_raw),
                "receipt_path": str(browser_file.relative_to(root.resolve())),
                "receipt_sha256": hashlib.sha256(browser_raw).hexdigest(),
                "receipt_bytes": len(browser_raw),
                "status": "pass" if not errors else "fail",
                "summary": browser_summary,
            },
        },
        "summary": {
            "total": final_total,
            "passed": passed_names,
            "errors": errors,
        },
        "gate": {
            "passed": not errors,
            "physical_campaign_complete": not errors,
            "browser_peer_physical_complete": not errors,
            "all_physical_evidence_complete": not errors,
            "production_activation": False,
        },
    }
    return report, 0 if not errors else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-report", type=Path, default=DEFAULT_CAMPAIGN)
    parser.add_argument("--browser-attestation", type=Path, default=DEFAULT_ATTESTATION)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-age-hours", type=float, default=168.0)
    args = parser.parse_args(argv)
    if args.max_age_hours <= 0 or args.max_age_hours > 720:
        parser.error("--max-age-hours must be greater than 0 and at most 720")
    now = datetime.now(timezone.utc)
    try:
        candidate = _load_candidate_identity(ROOT)
        if candidate.get("working_tree_clean") is not True:
            raise FinalGateError("current candidate working tree is not clean")
        if candidate.get("version_stamps_consistent") is not True:
            raise FinalGateError("current candidate version stamps are inconsistent")
        if _GITSHA.fullmatch(str(candidate.get("git_sha", ""))) is None:
            raise FinalGateError("current candidate git SHA is invalid")
        if _SHA256.fullmatch(str(candidate.get("code_sha256", ""))) is None:
            raise FinalGateError("current candidate worker fingerprint is invalid")
        report, exit_code = evaluate_final_gate(
            ROOT,
            args.campaign_report,
            args.browser_attestation,
            candidate=candidate,
            now=now,
            max_age_hours=args.max_age_hours,
        )
    except Exception as exc:
        report = {
            "schema": SCHEMA,
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "error": {
                "type": type(exc).__name__,
                "message": str(exc).replace("\r", " ").replace("\n", " ")[:500],
            },
            "summary": {"total": 0, "passed": [], "errors": [str(exc)[:500]]},
            "gate": {
                "passed": False,
                "physical_campaign_complete": False,
                "browser_peer_physical_complete": False,
                "all_physical_evidence_complete": False,
                "production_activation": False,
            },
        }
        exit_code = 2
    report_path = _resolve_under(ROOT, args.report)
    _write_json_atomic(report_path, report)
    print(f"report: {report_path.relative_to(ROOT)}")
    print("gate: " + ("PASS" if report.get("gate", {}).get("passed") else "BLOCKED"))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
