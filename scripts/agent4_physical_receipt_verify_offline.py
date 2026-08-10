#!/usr/bin/env python3
"""Offline, receipt-only verifier for the A4-18 physical Pixel acceptance receipt.

This verifier deliberately has a narrower authority than the repository audit
wrapper: it reads exactly one JSON receipt, performs no network or repository
lookup, writes nothing, and validates the receipt's cryptographic and semantic
self-consistency against an explicit immutable expected Git SHA.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

REPORT_SCHEMA = "modelrig-agent4/offline-receipt-verification/v1"
RECEIPT_SCHEMA = "modelrig-agent4/physical-read-receipt/v2"
SAFETY_SCHEMA = "modelrig-agent4/physical-read-safety-evidence/v1"
FIXTURE_SCHEMA = "modelrig-agent4/physical-read-fixture/v1"
MUTATION_SCHEMA = "modelrig-agent4/physical-read-mutation/v1"
EXPECTED_BRANCH = "agent/a4-18-physical-read-product"
EXPECTED_VERSION = "1.58.151"
EXPECTED_APP_PACKAGE = "dk.ternedal.modelrig"
SHA_PREFIX = "sha256:"
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

REQUIRED_TRIALS = (
    "default_off_feature_locked",
    "default_off_no_worker_fallback",
    "paired_without_grant_403",
    "paired_without_grant_locked_no_stale",
    "grant_same_token_200",
    "campaign_paging_no_loss",
    "timeline_paging_no_loss",
    "evidence_paging_no_loss",
    "detail_verification_matches",
    "no_write_controls",
    "stale_campaign_record_422",
    "stale_summary_422",
    "revoke_same_token_403",
    "revoke_clears_data",
    "restart_does_not_restore_grant",
    "regrant_same_token_200",
    "backend_restart_recovery",
    "worker_restart_recovery",
    "network_recovery",
    "malformed_schema_fail_closed",
    "not_found_fail_closed",
)

EXPECTED_HTTP_STATUS = {
    "default_off_feature_locked": 404,
    "paired_without_grant_403": 403,
    "grant_same_token_200": 200,
    "stale_campaign_record_422": 422,
    "stale_summary_422": 422,
    "revoke_same_token_403": 403,
    "restart_does_not_restore_grant": 403,
    "regrant_same_token_200": 200,
    "backend_restart_recovery": 200,
    "worker_restart_recovery": 200,
    "network_recovery": 200,
    "malformed_schema_fail_closed": 200,
    "not_found_fail_closed": 404,
}

PAYLOAD_HASH_TRIALS = {
    "grant_same_token_200",
    "campaign_paging_no_loss",
    "timeline_paging_no_loss",
    "evidence_paging_no_loss",
    "detail_verification_matches",
}
CURSOR_HASH_TRIALS = {
    "campaign_paging_no_loss",
    "timeline_paging_no_loss",
    "evidence_paging_no_loss",
    "stale_campaign_record_422",
    "stale_summary_422",
}
UI_OBSERVATION_TRIALS = {
    "default_off_feature_locked",
    "default_off_no_worker_fallback",
    "paired_without_grant_locked_no_stale",
    "campaign_paging_no_loss",
    "timeline_paging_no_loss",
    "evidence_paging_no_loss",
    "detail_verification_matches",
    "no_write_controls",
    "stale_campaign_record_422",
    "stale_summary_422",
    "revoke_clears_data",
    "malformed_schema_fail_closed",
}

# Receipt extensions are untrusted too. Normalize key spellings before testing
# sensitivity so camelCase, kebab-case and attacker-chosen aliases cannot hide
# credentials merely by bypassing the canonical snake_case names.
FORBIDDEN_CREDENTIAL_KEY_TERMS = (
    "authorization",
    "bearer",
    "token",
    "pairingcode",
    "adminkey",
    "modelrigadminkey",
    "password",
    "secret",
    "clientsecret",
    "privatekey",
)
CREDENTIAL_VALUE_PATTERNS = (
    re.compile(r"(?i)\bauthorization\s*:\s*(?:bearer\s+)?[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\bMODELRIG_ADMIN_KEY\s*=\s*\S+"),
    re.compile(r"(?i)\bpairing[_ -]?code\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bdevice[_ -]?token\s*[:=]\s*\S+"),
    re.compile(r"(?i)\badmin[_ -]?key\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b[A-Z0-9]{4}-[A-Z0-9]{4}\b"),
)
RFC1918 = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)


class VerificationError(ValueError):
    """Receipt failed one or more fail-closed verification checks."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def _canonical_json(value: Any) -> bytes:
    # PowerShell creates the receipt from ordered objects and hashes the compact
    # JSON before adding receipt_sha256. json.load preserves object order, so no
    # key sorting is performed here.
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return SHA_PREFIX + hashlib.sha256(_canonical_json(value)).hexdigest()


def _require_sha256(value: Any, label: str) -> str:
    _require(isinstance(value, str) and bool(SHA256_RE.fullmatch(value)), f"{label} must be lowercase sha256:<64-hex>")
    return value


def _require_git_sha(value: Any, label: str) -> str:
    _require(isinstance(value, str) and bool(GIT_SHA_RE.fullmatch(value)), f"{label} must be a full lowercase Git SHA")
    return value


def _require_bool(value: Any, expected: bool, label: str) -> None:
    _require(type(value) is bool and value is expected, f"{label} must be {str(expected).lower()}")


def _require_nonempty_text(value: Any, label: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()), f"{label} must be non-empty text")
    return value


def _require_safe_relative_path(value: Any, label: str) -> str:
    path = _require_nonempty_text(value, label)
    _require("\\" not in path and not path.startswith("/"), f"{label} must be POSIX-relative")
    parts = PurePosixPath(path).parts
    _require(".." not in parts and "." not in parts, f"{label} must not traverse")
    return path


def _require_rfc1918(value: Any, label: str) -> str:
    text = _require_nonempty_text(value, label)
    try:
        address = ipaddress.ip_address(text)
    except ValueError as exc:
        raise VerificationError(f"{label} must be an IPv4 address") from exc
    _require(address.version == 4 and any(address in network for network in RFC1918), f"{label} must be RFC1918 IPv4")
    return text


def _validate_generated_at(value: Any) -> None:
    text = _require_nonempty_text(value, "generated_at")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VerificationError("generated_at must be ISO-8601") from exc
    _require(parsed.tzinfo is not None, "generated_at must include timezone")
    _require(parsed.astimezone(timezone.utc).utcoffset().total_seconds() == 0, "generated_at must be convertible to UTC")


def _credential_key_is_forbidden(name: str) -> bool:
    compact = re.sub(r"[^a-z0-9]", "", name.lower())
    return any(term in compact for term in FORBIDDEN_CREDENTIAL_KEY_TERMS)


def _scan_credentials(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key)
            _require(not _credential_key_is_forbidden(name), f"forbidden credential field at {path}.{name}")
            _scan_credentials(child, f"{path}.{name}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _scan_credentials(child, f"{path}[{index}]")
        return
    if isinstance(value, str):
        for pattern in CREDENTIAL_VALUE_PATTERNS:
            _require(pattern.search(value) is None, f"credential-like value at {path}")


def _validate_all_named_hashes(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).endswith("_sha256") and child is not None:
                _require_sha256(child, child_path)
            _validate_all_named_hashes(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_all_named_hashes(child, f"{path}[{index}]")


def _validate_main_digest(receipt: dict[str, Any]) -> None:
    claimed = _require_sha256(receipt.get("receipt_sha256"), "receipt_sha256")
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    _require(_sha256_json(unsigned) == claimed, "receipt_sha256 does not match receipt content")


def _validate_identity(receipt: dict[str, Any], expected_sha: str) -> None:
    _require(receipt.get("schema") == RECEIPT_SCHEMA, "unsupported receipt schema")
    _validate_generated_at(receipt.get("generated_at"))
    _require(receipt.get("branch") == EXPECTED_BRANCH, "receipt branch is not the physical candidate branch")
    _require(_require_git_sha(receipt.get("expected_sha"), "expected_sha") == expected_sha, "expected_sha does not match verifier authority")
    _require(_require_git_sha(receipt.get("observed_head"), "observed_head") == expected_sha, "observed_head does not match verifier authority")
    _require(receipt.get("backend_version") == EXPECTED_VERSION, "backend_version does not match qualified product version")
    _require(receipt.get("worker_version") == EXPECTED_VERSION, "worker_version does not match qualified product version")

    pixel = receipt.get("pixel")
    _require(isinstance(pixel, dict), "pixel identity is missing")
    model = _require_nonempty_text(pixel.get("model"), "pixel.model")
    _require(bool(re.fullmatch(r"Pixel\b.*", model)), "pixel.model is not a Google Pixel model")
    _require(not any(term in model.lower() for term in ("emulator", "qemu", "sdk_gphone", "generic")), "emulator-like Pixel model rejected")
    _require_nonempty_text(pixel.get("android_release"), "pixel.android_release")
    sdk = _require_nonempty_text(pixel.get("sdk"), "pixel.sdk")
    _require(sdk.isdigit(), "pixel.sdk must be numeric")
    _require(pixel.get("app_package") == EXPECTED_APP_PACKAGE, "pixel.app_package does not match ModelRig/Kaliv app identity")
    version_name = _require_nonempty_text(pixel.get("version_name_line"), "pixel.version_name_line")
    _require(re.search(rf"\bversionName={re.escape(EXPECTED_VERSION)}\b", version_name) is not None, "Pixel app versionName does not match qualified product version")
    version_code = _require_nonempty_text(pixel.get("version_code_line"), "pixel.version_code_line")
    _require(re.search(r"\bversionCode=\d+\b", version_code) is not None, "pixel.version_code_line is malformed")


def _validate_fixture(fixture: Any) -> None:
    _require(isinstance(fixture, dict), "fixture is missing")
    _require(fixture.get("schema") == FIXTURE_SCHEMA, "fixture schema is invalid")
    for name in ("campaign_count", "timeline_count", "evidence_count"):
        value = fixture.get(name)
        _require(type(value) is int and value > 25, f"fixture.{name} must cross the physical paging boundary")
    _require(fixture.get("evidence_count") == fixture.get("evidence_verification_count"), "fixture evidence counts disagree")
    _require(fixture.get("selected_campaign_id") == "a4-18-physical-primary", "fixture selected campaign is unexpected")
    for name in ("latest_timeline_hash", "evidence_head_hash", "first_payload_sha256", "last_payload_sha256"):
        _require_sha256(fixture.get(name), f"fixture.{name}")
    for name in ("external_dispatch", "background_runtime", "production_activation"):
        _require_bool(fixture.get(name), False, f"fixture.{name}")


def _validate_mutations(mutations: Any) -> None:
    _require(isinstance(mutations, list) and len(mutations) == 2, "exactly two mutation receipts are required")
    seen: set[str] = set()
    for mutation in mutations:
        _require(isinstance(mutation, dict), "mutation receipt must be an object")
        _require(mutation.get("schema") == MUTATION_SCHEMA, "mutation schema is invalid")
        mode = mutation.get("mode")
        _require(mode in {"campaign-record", "summary"} and mode not in seen, "mutation modes must be unique campaign-record and summary")
        seen.add(mode)
        claimed = _require_sha256(mutation.get("receipt_sha256"), f"mutation.{mode}.receipt_sha256")
        unsigned = {key: value for key, value in mutation.items() if key != "receipt_sha256"}
        _require(_sha256_json(unsigned) == claimed, f"mutation {mode} digest does not match content")
        for name in ("external_dispatch", "background_runtime", "production_activation"):
            _require_bool(mutation.get(name), False, f"mutation.{mode}.{name}")

        cb = mutation.get("campaign_count_before")
        ca = mutation.get("campaign_count_after")
        eb = mutation.get("evidence_count_before")
        ea = mutation.get("evidence_count_after")
        tb = mutation.get("timeline_head_before")
        ta = mutation.get("timeline_head_after")
        hb = mutation.get("evidence_head_before")
        ha = mutation.get("evidence_head_after")
        for label, number in (("campaign_count_before", cb), ("campaign_count_after", ca), ("evidence_count_before", eb), ("evidence_count_after", ea)):
            _require(type(number) is int and number >= 0, f"mutation.{mode}.{label} is invalid")
        for label, digest in (("timeline_head_before", tb), ("timeline_head_after", ta), ("evidence_head_before", hb), ("evidence_head_after", ha)):
            _require_sha256(digest, f"mutation.{mode}.{label}")
        if mode == "campaign-record":
            _require(ca == cb + 1 and ea == eb and ta == tb and ha == hb, "campaign-record mutation effect is inconsistent")
        else:
            _require(ca == cb and ea == eb + 1 and ta != tb and ha != hb, "summary mutation effect is inconsistent")
    _require(seen == {"campaign-record", "summary"}, "both mutation modes are required")


def _validate_trials(trials: Any) -> None:
    _require(isinstance(trials, dict), "trials are missing")
    _require(set(trials) == set(REQUIRED_TRIALS), "trials must contain exactly the 21 known checkpoints")
    for name in REQUIRED_TRIALS:
        entry = trials[name]
        _require(isinstance(entry, dict), f"trial {name} must be an object")
        _require(entry.get("status") == "pass", f"trial {name} is not pass")
        if name in EXPECTED_HTTP_STATUS:
            _require(entry.get("http_status") == EXPECTED_HTTP_STATUS[name], f"trial {name} has unexpected HTTP status")
        route = entry.get("route")
        if route is not None:
            _require(isinstance(route, str) and route.startswith("/api/") and "?" not in route and "#" not in route, f"trial {name} contains unsafe route")
        if name in PAYLOAD_HASH_TRIALS:
            _require_sha256(entry.get("payload_sha256"), f"trial.{name}.payload_sha256")
        if name in CURSOR_HASH_TRIALS:
            _require_sha256(entry.get("cursor_sha256"), f"trial.{name}.cursor_sha256")
        screenshot = entry.get("screenshot")
        if screenshot is not None:
            _require_sha256(screenshot, f"trial.{name}.screenshot")
        if name in UI_OBSERVATION_TRIALS:
            _require_nonempty_text(entry.get("note"), f"trial.{name}.note")


def _validate_artifacts(artifacts: Any) -> None:
    _require(isinstance(artifacts, list) and artifacts, "artifact receipts are missing")
    seen: set[str] = set()
    for index, artifact in enumerate(artifacts):
        _require(isinstance(artifact, dict), f"artifact[{index}] must be an object")
        path = _require_safe_relative_path(artifact.get("path"), f"artifact[{index}].path")
        _require(path not in seen, f"duplicate artifact path: {path}")
        seen.add(path)
        size = artifact.get("size_bytes")
        _require(type(size) is int and size >= 0, f"artifact[{index}].size_bytes is invalid")
        _require_sha256(artifact.get("sha256"), f"artifact[{index}].sha256")


def _validate_cleanup(cleanup: Any) -> None:
    _require(isinstance(cleanup, dict), "cleanup is missing")
    for name in ("backend_stopped", "worker_stopped", "firewall_removed", "ports_free", "admin_key_deleted", "pairing_store_deleted", "passed"):
        _require_bool(cleanup.get(name), True, f"cleanup.{name}")
    _require_bool(cleanup.get("unknown_process_preserved"), False, "cleanup.unknown_process_preserved")


def _validate_safety(safety: Any, receipt: dict[str, Any], expected_sha: str) -> None:
    _require(isinstance(safety, dict), "safety_hardening is missing")
    _require(safety.get("schema") == SAFETY_SCHEMA, "safety_hardening schema is invalid")
    for name in ("physical_pixel", "artifacts_hashed_after_prestop"):
        _require_bool(safety.get(name), True, f"safety_hardening.{name}")
    for name in ("wildcard_binding", "public_network", "production_activation"):
        _require_bool(safety.get(name), False, f"safety_hardening.{name}")
    _require(safety.get("pixel_manufacturer") == "Google", "safety Pixel manufacturer must be Google")
    model = _require_nonempty_text(safety.get("pixel_model"), "safety_hardening.pixel_model")
    _require(bool(re.fullmatch(r"Pixel\b.*", model)), "safety Pixel model is invalid")
    _require(model == receipt["pixel"]["model"], "safety and top-level Pixel model disagree")
    _require_sha256(safety.get("pixel_serial_sha256"), "safety_hardening.pixel_serial_sha256")
    lan = _require_rfc1918(safety.get("lan_address"), "safety_hardening.lan_address")
    _require(safety.get("backend_bound_address") == lan, "backend bind does not match safety LAN address")
    _require(safety.get("worker_bound_address") == "127.0.0.1", "worker is not loopback-only")
    _require(safety.get("firewall_local_address") == lan, "firewall local address does not match safety LAN address")
    _require(safety.get("firewall_remote_scope") == "LocalSubnet", "firewall remote scope must be LocalSubnet")
    _require(safety.get("network_profile") in {"Private", "DomainAuthenticated"}, "network profile is not private/domain authenticated")
    binding = safety.get("binding_file")
    _require(isinstance(binding, dict), "safety binding receipt is missing")
    _require(binding.get("path") == "validation/agent4-physical-runtime/safety-binding.json", "safety binding path is unexpected")
    size = binding.get("size_bytes")
    _require(type(size) is int and size > 0, "safety binding size is invalid")
    _require_sha256(binding.get("sha256"), "safety_hardening.binding_file.sha256")
    _require(receipt.get("expected_sha") == expected_sha, "safety authority does not match expected receipt SHA")


def verify_receipt(receipt: Any, *, expected_sha: str) -> None:
    expected_sha = _require_git_sha(expected_sha, "verifier expected SHA")
    _require(isinstance(receipt, dict), "receipt must be a JSON object")
    _validate_identity(receipt, expected_sha)
    _validate_main_digest(receipt)
    _validate_all_named_hashes(receipt)
    _scan_credentials(receipt)
    _validate_fixture(receipt.get("fixture"))
    _validate_mutations(receipt.get("mutations"))
    _validate_trials(receipt.get("trials"))
    _validate_artifacts(receipt.get("artifacts"))
    _validate_cleanup(receipt.get("cleanup"))
    _validate_safety(receipt.get("safety_hardening"), receipt, expected_sha)
    _require_bool(receipt.get("all_required_observations_passed"), True, "all_required_observations_passed")
    _require(receipt.get("human_decision") == "GO", "human_decision must be GO")
    _require_bool(receipt.get("credential_data_included"), False, "credential_data_included")
    _require_bool(receipt.get("public_network"), False, "public_network")
    _require_bool(receipt.get("production_activation"), False, "production_activation")


def _report(result: str, *, receipt_path: Path, expected_sha: str, finding: str | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "result": result,
        "receipt": str(receipt_path),
        "expected_sha": expected_sha,
        "network_used": False,
        "mutation_performed": False,
    }
    if finding is not None:
        report["finding"] = finding
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, default=Path("validation/agent4-physical-read-latest.json"))
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()

    receipt_path = args.receipt
    try:
        expected_sha = _require_git_sha(args.expected_sha, "--expected-sha")
        raw = receipt_path.read_text(encoding="utf-8-sig")
        receipt = json.loads(raw)
        verify_receipt(receipt, expected_sha=expected_sha)
    except (OSError, json.JSONDecodeError, VerificationError, ValueError) as exc:
        expected = args.expected_sha if isinstance(args.expected_sha, str) else ""
        print(json.dumps(_report("FAIL", receipt_path=receipt_path, expected_sha=expected, finding=str(exc)), separators=(",", ":")))
        print(f"A4-20 offline physical receipt verifier: FAIL — {exc}")
        return 2

    print(json.dumps(_report("PASS", receipt_path=receipt_path, expected_sha=expected_sha), separators=(",", ":")))
    print("A4-20 offline physical receipt verifier: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
