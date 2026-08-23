#!/usr/bin/env python3
"""Independent, receipt-only verifier for one A4-18R physical Pixel receipt.

Authority boundary:
- reads exactly the JSON receipt named by --receipt;
- uses only the explicit immutable --expected-sha as external authority;
- performs no Git/repository lookup, network access, subprocess execution or writes;
- verifies receipt self-digests, exact-SHA binding, physical trial semantics,
  fixture/mutation consistency, artifact metadata, cleanup and credential hygiene.

This is deliberately narrower than scripts/agent4_a4_18r_audit.py. The canonical
auditor additionally re-hashes repository/output artifacts and scans the complete
runtime evidence tree. Both proofs are required for physical acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

REPORT_SCHEMA = "modelrig-agent4/a4-18r-offline-receipt-verification/v1"
RECEIPT_SCHEMA = "modelrig-agent4/a4-18r-physical-read-receipt/v1"
FIXTURE_SCHEMA = "modelrig-agent4/a4-18r-physical-fixture/v1"
MUTATION_SCHEMA = "modelrig-agent4/a4-18r-physical-mutation/v1"
PIXEL_SCHEMA = "modelrig-agent4/a4-18r-pixel/v1"
FILE_SCHEMA = "modelrig-file-receipt/v1"

SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
RAW_64_RE = re.compile(r"\b[0-9a-f]{64}\b")
PAIRING_RE = re.compile(r"\b[A-Z0-9]{4}-[A-Z0-9]{4}\b")

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
EXPECTED_HTTP = {
    "default_off_feature_locked": 404,
    "paired_without_grant_403": 403,
    "grant_same_token_200": 200,
    "campaign_paging_no_loss": 200,
    "timeline_paging_no_loss": 200,
    "evidence_paging_no_loss": 200,
    "detail_verification_matches": 200,
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
PAYLOAD_REQUIRED = {
    "grant_same_token_200",
    "campaign_paging_no_loss",
    "timeline_paging_no_loss",
    "evidence_paging_no_loss",
    "detail_verification_matches",
}
CURSOR_REQUIRED = {
    "campaign_paging_no_loss",
    "timeline_paging_no_loss",
    "evidence_paging_no_loss",
    "stale_campaign_record_422",
    "stale_summary_422",
}

CRITICAL_REPOSITORY_ARTIFACTS = {
    "backend/internal/httpapi/agent4_operator.go",
    "backend/internal/httpapi/agent4_grants_admin.go",
    "worker/app/entrypoint.py",
    "worker/app/agent4/production_bootstrap.py",
    "worker/app/agent4/operator_api.py",
    "worker/app/agent4/campaign_list_query.py",
    "android/app/src/main/java/dk/ternedal/modelrig/net/Agent4OperatorClient.kt",
    "android/app/src/main/java/dk/ternedal/modelrig/ui/Agent4OperatorScreen.kt",
    "android/app/src/main/java/dk/ternedal/modelrig/ui/Agent4CampaignDetailScreen.kt",
    "android/app/build.gradle.kts",
}
CRITICAL_OUTPUT_ARTIFACTS = {
    "bin/modelrig-a4-18r-backend.exe",
    "bin/modelrig-a4-18r-grants.exe",
    "bin/modelrig-a4-18r.apk",
    "fixture-manifest.json",
}

FORBIDDEN_KEY_TERMS = (
    "authorization",
    "bearer",
    "token",
    "pairingcode",
    "adminkey",
    "password",
    "secret",
    "clientsecret",
    "privatekey",
)
TEXT_PATTERNS = (
    re.compile(r"(?i)\bauthorization\s*:\s*(?:bearer\s+)?[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\bMODELRIG_ADMIN_KEY\s*=\s*(?!<redacted>|\[redacted\])\S{4,}"),
    re.compile(r"(?i)\bpairing[_ -]?code\s*[:=]\s*(?!<redacted>|\[redacted\])\S{4,}"),
    re.compile(r"(?i)\bdevice[_ -]?token\s*[:=]\s*(?!<redacted>|\[redacted\])\S{4,}"),
    PAIRING_RE,
    RAW_64_RE,
)


class VerificationError(ValueError):
    """The receipt failed a fail-closed verification rule."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def reject_duplicate_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def require_sha256(value: Any, label: str) -> str:
    require(
        isinstance(value, str) and SHA256_RE.fullmatch(value) is not None,
        f"{label} must be lowercase sha256:<64-hex>",
    )
    return value


def require_git_sha(value: Any, label: str) -> str:
    require(
        isinstance(value, str) and GIT_SHA_RE.fullmatch(value) is not None,
        f"{label} must be a full lowercase Git SHA",
    )
    return value


def safe_relative_path(value: Any, label: str) -> str:
    require(isinstance(value, str) and value != "", f"{label} must be non-empty text")
    require("\\" not in value and not value.startswith("/"), f"{label} must be POSIX-relative")
    parts = PurePosixPath(value).parts
    require(".." not in parts and "." not in parts, f"{label} must not traverse")
    return value


def forbidden_key(name: str) -> bool:
    compact = re.sub(r"[^a-z0-9]", "", name.lower())
    return any(term in compact for term in FORBIDDEN_KEY_TERMS)


def allowed_structural_key(path: str, name: str) -> bool:
    return path == "root.trials" and name in REQUIRED_TRIALS


def canonical_hash_slot(
    parent: Mapping[str, Any],
    path: str,
    name: str,
    value: Any,
    schema_context: str | None,
) -> bool:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        return False
    own_schema = parent.get("schema")
    active_schema = own_schema if isinstance(own_schema, str) else schema_context
    if active_schema == RECEIPT_SCHEMA and name == "receipt_sha256":
        return True
    if active_schema == FIXTURE_SCHEMA and name in {
        "latest_timeline_hash",
        "evidence_head_hash",
        "first_payload_sha256",
        "last_payload_sha256",
    }:
        return True
    if (
        active_schema == FIXTURE_SCHEMA
        and name == "sha256"
        and path.startswith("root.fixture.persisted_files[")
        and {"path", "size_bytes", "sha256"}.issubset(parent.keys())
    ):
        return True
    if active_schema == MUTATION_SCHEMA and name in {
        "receipt_sha256",
        "timeline_head_before",
        "timeline_head_after",
        "evidence_head_before",
        "evidence_head_after",
    }:
        return True
    if active_schema == PIXEL_SCHEMA and name == "serial_sha256":
        return True
    if active_schema == FILE_SCHEMA and name == "sha256":
        return True
    if path.startswith("root.trials."):
        trial_name = path.removeprefix("root.trials.")
        if trial_name in REQUIRED_TRIALS and name in {"payload_sha256", "cursor_sha256"}:
            return True
    return False


def scan_text(value: str, label: str) -> None:
    for pattern in TEXT_PATTERNS:
        require(pattern.search(value) is None, f"credential-like value at {label}")


def scan_value(
    value: Any,
    path: str = "root",
    *,
    schema_context: str | None = None,
) -> None:
    if isinstance(value, Mapping):
        own_schema = value.get("schema")
        active_schema = own_schema if isinstance(own_schema, str) else schema_context
        for key, child in value.items():
            name = str(key)
            require(
                allowed_structural_key(path, name) or not forbidden_key(name),
                f"forbidden credential field at {path}.{name}",
            )
            if canonical_hash_slot(value, path, name, child, active_schema):
                continue
            scan_value(child, f"{path}.{name}", schema_context=active_schema)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            scan_value(child, f"{path}[{index}]", schema_context=schema_context)
        return
    if isinstance(value, str):
        scan_text(value, path)


def validate_self_digest(value: Mapping[str, Any], label: str) -> None:
    claimed = require_sha256(value.get("receipt_sha256"), f"{label}.receipt_sha256")
    body = dict(value)
    del body["receipt_sha256"]
    actual = "sha256:" + hashlib.sha256(canonical_json(body)).hexdigest()
    require(actual == claimed, f"{label} self-digest mismatch")


def validate_trials(trials: Any) -> None:
    require(isinstance(trials, Mapping), "trials must be an object")
    require(
        set(trials) == set(REQUIRED_TRIALS),
        "physical trial set is incomplete or contains unknown trials",
    )
    for name in REQUIRED_TRIALS:
        entry = trials[name]
        require(isinstance(entry, Mapping), f"trial {name} must be an object")
        require(entry.get("status") == "pass", f"trial {name} did not pass")
        expected = EXPECTED_HTTP.get(name)
        if expected is not None:
            require(entry.get("http_status") == expected, f"trial {name} has wrong HTTP status")
        route = entry.get("route")
        if route is not None:
            require(
                isinstance(route, str)
                and route.startswith("/api/")
                and "?" not in route
                and "#" not in route
                and "://" not in route,
                f"trial {name} has unsafe route",
            )
        if name in PAYLOAD_REQUIRED:
            require_sha256(entry.get("payload_sha256"), f"trial.{name}.payload_sha256")
        if name in CURSOR_REQUIRED:
            require_sha256(entry.get("cursor_sha256"), f"trial.{name}.cursor_sha256")
        require(
            "screenshot" not in entry and "screenshot_path" not in entry,
            f"trial {name} may not use screenshot acceptance",
        )


def validate_fixture(fixture: Any, expected_sha: str) -> None:
    require(isinstance(fixture, Mapping), "fixture must be an object")
    require(fixture.get("schema") == FIXTURE_SCHEMA, "wrong fixture schema")
    require(fixture.get("repository_sha") == expected_sha, "fixture exact SHA mismatch")
    require(
        fixture.get("selected_campaign_id") == "a4-18r-physical-primary",
        "wrong selected fixture campaign",
    )
    for name in ("campaign_count", "timeline_count", "evidence_count"):
        require(
            type(fixture.get(name)) is int and int(fixture[name]) > 25,
            f"fixture {name} does not cross the page boundary",
        )
    require(
        fixture.get("evidence_count") == fixture.get("evidence_verification_count"),
        "fixture evidence count mismatch",
    )
    for name in (
        "latest_timeline_hash",
        "evidence_head_hash",
        "first_payload_sha256",
        "last_payload_sha256",
    ):
        require_sha256(fixture.get(name), f"fixture.{name}")
    persisted = fixture.get("persisted_files")
    require(isinstance(persisted, list) and persisted, "fixture persisted_files are missing")
    seen_paths: set[str] = set()
    for index, entry in enumerate(persisted):
        require(isinstance(entry, Mapping), f"fixture persisted_files[{index}] must be an object")
        rel = safe_relative_path(entry.get("path"), f"fixture.persisted_files[{index}].path")
        require(rel not in seen_paths, f"duplicate fixture persisted path: {rel}")
        seen_paths.add(rel)
        size = entry.get("size_bytes")
        require(type(size) is int and size >= 0, f"fixture persisted_files[{index}] size is invalid")
        require_sha256(entry.get("sha256"), f"fixture.persisted_files[{index}].sha256")
    for name in (
        "external_dispatch",
        "background_runtime",
        "public_network",
        "production_activation",
    ):
        require(fixture.get(name) is False, f"fixture {name} must be false")


def validate_mutations(values: Any, expected_sha: str) -> None:
    items = list(values) if isinstance(values, list) else []
    require(len(items) == 2, "exactly two A4-18R snapshot mutations are required")
    by_mode: dict[str, Mapping[str, Any]] = {}
    for item in items:
        require(isinstance(item, Mapping), "mutation must be an object")
        require(item.get("schema") == MUTATION_SCHEMA, "wrong mutation schema")
        require(item.get("repository_sha") == expected_sha, "mutation exact SHA mismatch")
        validate_self_digest(item, "mutation")
        mode = item.get("mode")
        require(
            mode in {"campaign-record", "summary"} and str(mode) not in by_mode,
            "mutation modes are invalid or duplicated",
        )
        by_mode[str(mode)] = item
        for name in (
            "external_dispatch",
            "background_runtime",
            "public_network",
            "production_activation",
        ):
            require(item.get(name) is False, f"mutation {mode} {name} must be false")

    require(set(by_mode) == {"campaign-record", "summary"}, "both mutation modes are required")
    campaign = by_mode["campaign-record"]
    for name in ("campaign_count_before", "campaign_count_after", "evidence_count_before", "evidence_count_after"):
        require(type(campaign.get(name)) is int, f"campaign mutation {name} is invalid")
    require(
        campaign.get("campaign_count_after") == campaign.get("campaign_count_before") + 1,
        "campaign mutation did not add exactly one campaign",
    )
    require(
        campaign.get("evidence_count_after") == campaign.get("evidence_count_before"),
        "campaign mutation changed evidence count",
    )
    require(
        campaign.get("timeline_head_after") == campaign.get("timeline_head_before"),
        "campaign mutation changed timeline summary",
    )
    require(
        campaign.get("evidence_head_after") == campaign.get("evidence_head_before"),
        "campaign mutation changed evidence summary",
    )
    summary = by_mode["summary"]
    for name in ("campaign_count_before", "campaign_count_after", "evidence_count_before", "evidence_count_after"):
        require(type(summary.get(name)) is int, f"summary mutation {name} is invalid")
    require(
        summary.get("campaign_count_after") == summary.get("campaign_count_before"),
        "summary mutation changed campaign count",
    )
    require(
        summary.get("evidence_count_after") == summary.get("evidence_count_before") + 1,
        "summary mutation did not add one evidence record",
    )
    require(
        summary.get("timeline_head_after") != summary.get("timeline_head_before"),
        "summary mutation did not change timeline head",
    )
    require(
        summary.get("evidence_head_after") != summary.get("evidence_head_before"),
        "summary mutation did not change evidence head",
    )


def validate_pixel(pixel: Any) -> None:
    require(
        isinstance(pixel, Mapping) and pixel.get("schema") == PIXEL_SCHEMA,
        "physical Pixel identity is missing",
    )
    require(pixel.get("manufacturer") == "Google", "physical device is not a Google Pixel")
    require(
        isinstance(pixel.get("model"), str) and str(pixel["model"]).startswith("Pixel"),
        "physical device model is not Pixel",
    )
    model = str(pixel["model"]).lower()
    require(
        not any(term in model for term in ("emulator", "qemu", "sdk_gphone", "generic")),
        "emulator-like Pixel model rejected",
    )
    require_sha256(pixel.get("serial_sha256"), "pixel.serial_sha256")
    require(
        pixel.get("package_name") == "dk.ternedal.modelrig.a425f",
        "wrong isolated product package",
    )
    require(isinstance(pixel.get("android_release"), str) and pixel["android_release"] != "", "Pixel Android release is missing")
    require(isinstance(pixel.get("sdk"), str) and pixel["sdk"].isdigit(), "Pixel SDK is invalid")
    require(
        isinstance(pixel.get("version_name_line"), str)
        and str(pixel["version_name_line"]).startswith("versionName="),
        "Pixel versionName identity is missing",
    )
    require(
        isinstance(pixel.get("version_code_line"), str)
        and re.search(r"\bversionCode=\d+\b", str(pixel["version_code_line"])) is not None,
        "Pixel versionCode identity is invalid",
    )


def validate_artifacts(artifacts: Any) -> None:
    require(isinstance(artifacts, list) and artifacts, "artifact list is missing")
    seen: set[tuple[str, str]] = set()
    repository_paths: set[str] = set()
    output_paths: set[str] = set()
    for index, entry in enumerate(artifacts):
        require(
            isinstance(entry, Mapping) and entry.get("schema") == FILE_SCHEMA,
            f"artifact[{index}] has wrong schema",
        )
        scope = entry.get("scope")
        require(scope in {"output", "repository"}, f"artifact[{index}] scope is invalid")
        rel = safe_relative_path(entry.get("path"), f"artifact[{index}].path")
        identity = (str(scope), rel)
        require(identity not in seen, f"duplicate artifact: {scope}:{rel}")
        seen.add(identity)
        size = entry.get("size_bytes")
        require(type(size) is int and size >= 0, f"artifact[{index}] size is invalid")
        require_sha256(entry.get("sha256"), f"artifact[{index}].sha256")
        (repository_paths if scope == "repository" else output_paths).add(rel)
    require(
        CRITICAL_REPOSITORY_ARTIFACTS.issubset(repository_paths),
        "critical current-product repository artifact receipts are missing",
    )
    require(
        CRITICAL_OUTPUT_ARTIFACTS.issubset(output_paths),
        "critical output artifact receipts are missing",
    )


def validate_cleanup(cleanup: Any) -> None:
    require(isinstance(cleanup, Mapping), "cleanup evidence is missing")
    for name in (
        "backend_stopped",
        "worker_stopped",
        "firewall_removed",
        "ports_free",
        "credential_file_deleted",
        "pairing_store_deleted",
        "test_package_uninstalled",
    ):
        require(cleanup.get(name) is True, f"cleanup did not prove {name}")
    require(
        cleanup.get("unknown_process_preserved") is False,
        "cleanup encountered an unknown listener",
    )


def verify_receipt(receipt: Any, *, expected_sha: str) -> dict[str, object]:
    expected_sha = require_git_sha(expected_sha, "verifier expected SHA")
    require(isinstance(receipt, Mapping), "receipt must be a JSON object")
    require(receipt.get("schema") == RECEIPT_SCHEMA, "unsupported receipt schema")
    require(
        receipt.get("expected_sha") == expected_sha
        and receipt.get("observed_head") == expected_sha,
        "receipt exact SHA mismatch",
    )
    require(
        receipt.get("public_network") is False
        and receipt.get("production_activation") is False,
        "receipt widened authority",
    )
    require(
        receipt.get("credential_data_included") is False,
        "receipt claims credential material",
    )
    require(
        receipt.get("all_required_observations_passed") is True,
        "physical observations are incomplete",
    )
    require(receipt.get("human_decision") == "GO", "human_decision must be GO")
    validate_self_digest(receipt, "receipt")
    validate_trials(receipt.get("trials"))
    validate_fixture(receipt.get("fixture"), expected_sha)
    validate_mutations(receipt.get("mutations"), expected_sha)
    validate_pixel(receipt.get("pixel"))
    validate_artifacts(receipt.get("artifacts"))
    validate_cleanup(receipt.get("cleanup"))
    scan_value(receipt)
    return {
        "schema": REPORT_SCHEMA,
        "result": "PASS",
        "expected_sha": expected_sha,
        "receipt_only": True,
        "network_used": False,
        "repository_lookup_used": False,
        "subprocess_used": False,
        "mutation_performed": False,
        "physical_receipt_semantics_valid": True,
        "credential_hygiene_verified": True,
        "artifact_metadata_verified": True,
        "artifact_bytes_verified": False,
        "canonical_runtime_audit_still_required": True,
        "human_decision": "GO",
        "public_network": False,
        "production_activation": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    try:
        raw = args.receipt.read_text(encoding="utf-8-sig")
        receipt = json.loads(raw, object_pairs_hook=reject_duplicate_object_pairs)
        report = verify_receipt(receipt, expected_sha=args.expected_sha)
    except (OSError, json.JSONDecodeError, VerificationError, ValueError, TypeError) as exc:
        print(
            json.dumps(
                {
                    "schema": REPORT_SCHEMA,
                    "result": "FAIL",
                    "expected_sha": args.expected_sha,
                    "receipt_only": True,
                    "network_used": False,
                    "repository_lookup_used": False,
                    "subprocess_used": False,
                    "mutation_performed": False,
                    "finding": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
