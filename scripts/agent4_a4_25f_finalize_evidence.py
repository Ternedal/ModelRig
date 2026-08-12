#!/usr/bin/env python3
"""Complete A4-25f physical evidence after the fail-closed integrity audit.

The finalizer binds the redacted physical HTTP trace plus Android/rig platform
identity to the already-audited receipt chain. It never records a human GO and
never authorizes production activation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import agent4_a4_25f_audit as audit

SCHEMA = "modelrig-agent4/a4-25f-qualification-evidence/v1"
HTTP_TRACE_SCHEMA = "modelrig-agent4/a4-25f-http-trial/v1"
DEVICE_INFO_SCHEMA = "modelrig-agent4/a4-25f-device-info/v1"
MEDIA_TYPE = "application/vnd.modelrig.agent4.operator+json"
EXPECTED_TRIALS = (
    ("list-start", "campaign-list", 200),
    ("list-continue", "campaign-list", 200),
    ("detail-capture", "campaign-detail", 200),
    ("timeline-start", "timeline-list", 200),
    ("timeline-continue", "timeline-list", 200),
    ("evidence-start", "evidence-list", 200),
    ("evidence-continue", "evidence-list", 200),
    ("verification", "evidence-verification", 200),
    ("selected-root-404", "campaign-detail", 404),
    ("server-422", "campaign-list", 422),
    ("current-unavailable-503", "campaign-list", 503),
    ("fresh-root", "campaign-detail", 200),
    ("unknown-root", "campaign-detail", 410),
    ("expired-retained-410", "campaign-detail", 410),
)


def _read_json_lines(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise RuntimeError(f"required A4-25f HTTP evidence trace is missing: {path.name}")
    entries: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        value = json.loads(raw, object_pairs_hook=audit._reject_duplicate_keys)
        if not isinstance(value, dict):
            raise RuntimeError(f"HTTP trace line {line_number} is not an object")
        entries.append(value)
    return entries


def _require_text(value: Any, label: str, *, max_length: int = 500) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"{label} must be text")
    text = value.strip()
    if not text or len(text) > max_length or "\n" in text or "\r" in text:
        raise RuntimeError(f"{label} is missing or unsafe")
    return text


def _collect_rig_environment() -> dict[str, Any]:
    if platform.system() != "Windows":
        raise RuntimeError("A4-25f qualification evidence must be finalized on the physical Windows rig")
    go_version = subprocess.check_output(
        ["go", "version"],
        text=True,
        stderr=subprocess.STDOUT,
        timeout=10,
    ).strip()
    if not go_version.startswith("go version go"):
        raise RuntimeError("could not record a valid Go version")
    win_release, win_version, win_csd, win_ptype = platform.win32_ver()
    windows_version = win_version.strip() or platform.version().strip()
    windows_release = win_release.strip() or platform.release().strip()
    if not windows_version or not windows_release:
        raise RuntimeError("could not record Windows version/build identity")
    python_executable = Path(sys.executable).resolve()
    if not python_executable.is_file():
        raise RuntimeError("audit Python executable could not be identified")
    return {
        "os": "Windows",
        "windows_release": windows_release,
        "windows_version": windows_version,
        "windows_service_pack": win_csd.strip(),
        "windows_product_type": win_ptype.strip(),
        "architecture": platform.machine().strip(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable_sha256": audit._sha256_file(python_executable),
        "go_version": go_version,
    }


def _validate_device_info(value: dict[str, Any], matrix: dict[str, Any]) -> dict[str, Any]:
    if value.get("schema") != DEVICE_INFO_SCHEMA or value.get("stage") != "device-info":
        raise RuntimeError("A425f device-info receipt schema/stage mismatch")
    audit._require_bool(value.get("success"), True, "device_info.success")
    audit._require_bool(value.get("credential_in_receipt"), False, "device_info.credential_in_receipt")
    audit._require_bool(value.get("production_activation"), False, "device_info.production_activation")
    if value.get("route_kind") != "device-status":
        raise RuntimeError("device-info route kind mismatch")
    if value.get("expected_http_status") != 200 or value.get("actual_http_status") != 200:
        raise RuntimeError("device-info did not prove HTTP 200")
    if value.get("app_package_name") != audit.PACKAGE_NAME:
        raise RuntimeError("device-info package identity mismatch")
    audit._require_bool(value.get("app_debuggable"), True, "device_info.app_debuggable")
    if matrix.get("package_name") != audit.PACKAGE_NAME:
        raise RuntimeError("matrix package identity mismatch")
    apk_sha = audit._require_sha256(matrix.get("apk_sha256"), "matrix.apk_sha256")
    sdk = value.get("android_sdk_int")
    version_code = value.get("app_version_code")
    if not isinstance(sdk, int) or isinstance(sdk, bool) or sdk <= 0:
        raise RuntimeError("device-info Android SDK is invalid")
    if not isinstance(version_code, int) or isinstance(version_code, bool) or version_code <= 0:
        raise RuntimeError("device-info app versionCode is invalid")
    result = {
        "manufacturer": _require_text(value.get("android_manufacturer"), "device_info.android_manufacturer"),
        "model": _require_text(value.get("android_model"), "device_info.android_model"),
        "android_version_release": _require_text(value.get("android_version_release"), "device_info.android_version_release"),
        "android_sdk_int": sdk,
        "package_name": audit.PACKAGE_NAME,
        "app_version_name": _require_text(value.get("app_version_name"), "device_info.app_version_name"),
        "app_version_code": version_code,
        "apk_sha256": apk_sha,
        "device_status_http": 200,
    }
    return result


def _validate_http_trace(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(entries) != len(EXPECTED_TRIALS):
        raise RuntimeError(
            f"A4-25f HTTP trace must contain exactly {len(EXPECTED_TRIALS)} physical Agent 4 requests; got {len(entries)}"
        )
    trials: list[dict[str, Any]] = []
    for index, (entry, expected) in enumerate(zip(entries, EXPECTED_TRIALS), start=1):
        stage, route_kind, expected_status = expected
        if entry.get("schema") != HTTP_TRACE_SCHEMA or entry.get("method") != "GET":
            raise RuntimeError(f"HTTP trace entry {index} identity mismatch")
        if entry.get("route_kind") != route_kind:
            raise RuntimeError(f"HTTP trace stage {stage} route mismatch")
        if entry.get("http_status") != expected_status:
            raise RuntimeError(
                f"HTTP trace stage {stage} status mismatch: got {entry.get('http_status')} want {expected_status}"
            )
        if entry.get("response_media_type") != MEDIA_TYPE:
            raise RuntimeError(f"HTTP trace stage {stage} media type mismatch")
        query_hash = audit._require_sha256(entry.get("raw_query_sha256"), f"http_trace[{index}].raw_query_sha256")
        body_hash = audit._require_sha256(entry.get("response_body_sha256"), f"http_trace[{index}].response_body_sha256")
        body_size = entry.get("response_body_size")
        if not isinstance(body_size, int) or isinstance(body_size, bool) or body_size <= 0:
            raise RuntimeError(f"HTTP trace stage {stage} has no response body evidence")
        query_keys = entry.get("query_keys")
        if not isinstance(query_keys, list) or any(not isinstance(key, str) or not key for key in query_keys):
            raise RuntimeError(f"HTTP trace stage {stage} query-key evidence is invalid")
        if query_keys != sorted(set(query_keys)):
            raise RuntimeError(f"HTTP trace stage {stage} query keys are not canonical")
        for key in ("credential_in_receipt", "raw_cursor_in_receipt", "public_network", "production_activation"):
            audit._require_bool(entry.get(key), False, f"http_trace[{index}].{key}")
        audit._assert_no_secrets(entry, f"http_trace[{index}]")
        trials.append(
            {
                "ordinal": index,
                "stage": stage,
                "route_kind": route_kind,
                "expected_http_status": expected_status,
                "actual_http_status": expected_status,
                "query_keys": query_keys,
                "raw_query_sha256": query_hash,
                "response_media_type": MEDIA_TYPE,
                "response_body_sha256": body_hash,
                "response_body_size": body_size,
            }
        )
    return trials


def finalize_evidence(
    output_root: Path,
    *,
    expected_sha: str,
    rig_environment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output = audit._resolve_output(output_root)
    target = output / "a4-25f-qualification-evidence.json"
    if target.exists():
        raise RuntimeError("A4-25f qualification evidence is immutable; use a fresh output directory for a new attempt")

    integrity_receipt = audit.audit_evidence(output, expected_sha=expected_sha)
    audit_path = output / "a4-25f-physical-audit.json"
    audit._verify_self_digest(integrity_receipt, "audit_sha256", "physical_audit")
    audit._require_bool(
        integrity_receipt.get("physical_qualification_evidence_valid"),
        True,
        "physical_audit.physical_qualification_evidence_valid",
    )
    audit._require_bool(integrity_receipt.get("human_go_authorized"), False, "physical_audit.human_go_authorized")
    audit._require_bool(integrity_receipt.get("production_activation"), False, "physical_audit.production_activation")

    matrix_path = output / "a4-25f-physical-matrix.json"
    matrix = audit._load_json(matrix_path)
    if matrix.get("schema") != audit.MATRIX_SCHEMA or matrix.get("repository_sha") != expected_sha:
        raise RuntimeError("physical matrix authority mismatch during evidence finalization")

    device_info_path = output / "phone-receipts" / "a4-25f-device-info.json"
    device_info = audit._load_json(device_info_path)
    android_environment = _validate_device_info(device_info, matrix)

    trace_path = output / "backend-device-store.json.agent4-evidence.jsonl"
    trace_entries = _read_json_lines(trace_path)
    trials = _validate_http_trace(trace_entries)

    rig = dict(rig_environment) if rig_environment is not None else _collect_rig_environment()
    if rig.get("os") != "Windows":
        raise RuntimeError("qualification rig evidence must identify Windows")
    for field in ("windows_release", "windows_version", "architecture", "python_version", "python_implementation", "go_version"):
        _require_text(rig.get(field), f"rig_environment.{field}")
    audit._require_sha256(rig.get("python_executable_sha256"), "rig_environment.python_executable_sha256")
    audit._assert_no_secrets(rig, "rig_environment")

    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "repository_sha": expected_sha,
        "package_name": audit.PACKAGE_NAME,
        "audit_file_sha256": audit._sha256_file(audit_path),
        "audit_sha256": integrity_receipt.get("audit_sha256"),
        "physical_matrix_sha256": audit._sha256_file(matrix_path),
        "http_trace_sha256": audit._sha256_file(trace_path),
        "http_trial_count": len(trials),
        "trials": trials,
        "android_environment": android_environment,
        "rig_environment": rig,
        "proxy_preservation_contract": "backend/internal/httpapi/agent4_operator_test.go::TestAgent4OperatorPreservesSnapshotQueryStatusBodyAndMediaType",
        "all_expected_http_trials_verified": True,
        "android_build_identity_verified": True,
        "rig_platform_identity_recorded": True,
        "physical_qualification_evidence_complete": True,
        "human_go_recorded": False,
        "human_go_authorized": False,
        "credential_in_receipt": False,
        "raw_cursor_in_receipt": False,
        "public_network": False,
        "production_activation": False,
    }
    audit._assert_no_secrets(receipt, "qualification_evidence")
    receipt["qualification_evidence_sha256"] = "sha256:" + hashlib.sha256(audit._canonical_json(receipt)).hexdigest()
    target.write_text(
        json.dumps(receipt, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    finalize_evidence(args.output_root, expected_sha=args.expected_sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
