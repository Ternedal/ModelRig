#!/usr/bin/env python3
"""Fail-closed auditor for one A4-18R Windows + Pixel physical campaign.

The auditor is evidence-only: it performs no network access, starts no process,
and writes nothing. It validates exact-SHA binding, fixture/mutation semantics,
current-product artifact digests, cleanup, and credential hygiene. SHA-looking
strings are trusted only in explicitly schema/path-bound digest slots.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]

RECEIPT_SCHEMA = "modelrig-agent4/a4-18r-physical-read-receipt/v1"
FIXTURE_SCHEMA = "modelrig-agent4/a4-18r-physical-fixture/v1"
MUTATION_SCHEMA = "modelrig-agent4/a4-18r-physical-mutation/v1"
STATE_SCHEMA = "modelrig-agent4/a4-18r-operator-state/v1"
OBSERVATIONS_SCHEMA = "modelrig-agent4/a4-18r-observations/v1"
PIXEL_SCHEMA = "modelrig-agent4/a4-18r-pixel/v1"
FILE_SCHEMA = "modelrig-file-receipt/v1"
MARKER_SCHEMA = "modelrig-agent4/a4-18r-output/v1"

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

SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
RAW_64_RE = re.compile(r"\b[0-9a-f]{64}\b")
PAIRING_RE = re.compile(r"\b[A-Z0-9]{4}-[A-Z0-9]{4}\b")
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

SCHEMA_HASH_FIELDS: dict[str, frozenset[str]] = {
    RECEIPT_SCHEMA: frozenset({"receipt_sha256"}),
    FIXTURE_SCHEMA: frozenset(
        {"latest_timeline_hash", "evidence_head_hash", "first_payload_sha256", "last_payload_sha256"}
    ),
    MUTATION_SCHEMA: frozenset(
        {"receipt_sha256", "timeline_head_before", "timeline_head_after", "evidence_head_before", "evidence_head_after"}
    ),
    STATE_SCHEMA: frozenset({"adb_serial_sha256", "apk_sha256"}),
    PIXEL_SCHEMA: frozenset({"serial_sha256"}),
    FILE_SCHEMA: frozenset({"sha256"}),
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


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def reject_duplicate_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    require(path.is_file() and not path.is_symlink(), f"missing or unsafe JSON evidence: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=reject_duplicate_object_pairs)


def safe_relative_path(value: Any) -> str:
    require(isinstance(value, str) and value != "", "artifact path must be non-empty text")
    require("\\" not in value and not value.startswith("/"), f"unsafe artifact path: {value}")
    require(not re.search(r"(^|/)\.\.(/|$)", value), f"unsafe artifact traversal: {value}")
    return value


def safe_output_root(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    require(path.exists() and path.is_dir() and not path.is_symlink(), "A4-18R output root is missing or unsafe")
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("A4-18R output root must be outside the repository")
    require(resolved != Path(resolved.anchor), "A4-18R output root may not be a filesystem root")
    return resolved


def forbidden_key(name: str) -> bool:
    compact = re.sub(r"[^a-z0-9]", "", name.lower())
    return any(term in compact for term in FORBIDDEN_KEY_TERMS)


def canonical_hash_slot(parent: Mapping[str, Any], path: str, name: str, value: Any) -> bool:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        return False
    schema = parent.get("schema")
    if isinstance(schema, str) and name in SCHEMA_HASH_FIELDS.get(schema, frozenset()):
        return True
    if path.startswith("root.trials.") and name in {"payload_sha256", "cursor_sha256"}:
        return path.removeprefix("root.trials.") in REQUIRED_TRIALS
    return False


def scan_text(value: str, *, label: str) -> None:
    for pattern in TEXT_PATTERNS:
        require(pattern.search(value) is None, f"credential-like value at {label}")


def scan_value(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key)
            require(not forbidden_key(name), f"forbidden credential field at {path}.{name}")
            if canonical_hash_slot(value, path, name, child):
                continue
            scan_value(child, f"{path}.{name}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            scan_value(child, f"{path}[{index}]")
        return
    if isinstance(value, str):
        scan_text(value, label=path)


def validate_self_digest(value: Mapping[str, Any], *, label: str) -> None:
    claimed = value.get("receipt_sha256")
    require(isinstance(claimed, str) and SHA256_RE.fullmatch(claimed) is not None, f"{label} digest missing")
    body = dict(value)
    del body["receipt_sha256"]
    actual = "sha256:" + hashlib.sha256(canonical_json(body)).hexdigest()
    require(actual == claimed, f"{label} self-digest mismatch")


def validate_trials(trials: Any) -> None:
    require(isinstance(trials, Mapping), "trials must be an object")
    require(set(trials) == set(REQUIRED_TRIALS), "physical trial set is incomplete or contains unknown trials")
    for name in REQUIRED_TRIALS:
        entry = trials[name]
        require(isinstance(entry, Mapping), f"trial {name} must be an object")
        require(entry.get("status") == "pass", f"trial {name} did not pass")
        expected = EXPECTED_HTTP.get(name)
        if expected is not None:
            require(entry.get("http_status") == expected, f"trial {name} has wrong HTTP status")
        route = entry.get("route")
        if route is not None:
            require(isinstance(route, str) and route.startswith("/api/"), f"trial {name} has unsafe route")
            require("?" not in route and "#" not in route and "://" not in route, f"trial {name} route leaks request context")
        if name in PAYLOAD_REQUIRED:
            require(isinstance(entry.get("payload_sha256"), str) and SHA256_RE.fullmatch(entry["payload_sha256"]) is not None, f"trial {name} lacks payload digest")
        if name in CURSOR_REQUIRED:
            require(isinstance(entry.get("cursor_sha256"), str) and SHA256_RE.fullmatch(entry["cursor_sha256"]) is not None, f"trial {name} lacks cursor digest")
        require("screenshot" not in entry and "screenshot_path" not in entry, f"trial {name} may not use screenshot acceptance")


def validate_fixture(fixture: Any, expected_sha: str) -> None:
    require(isinstance(fixture, Mapping), "fixture must be an object")
    require(fixture.get("schema") == FIXTURE_SCHEMA, "wrong fixture schema")
    require(fixture.get("repository_sha") == expected_sha, "fixture exact SHA mismatch")
    require(fixture.get("selected_campaign_id") == "a4-18r-physical-primary", "wrong selected fixture campaign")
    for name in ("campaign_count", "timeline_count", "evidence_count"):
        require(type(fixture.get(name)) is int and int(fixture[name]) > 25, f"fixture {name} does not cross the page boundary")
    require(fixture.get("evidence_count") == fixture.get("evidence_verification_count"), "fixture evidence count mismatch")
    for name in ("latest_timeline_hash", "evidence_head_hash", "first_payload_sha256", "last_payload_sha256"):
        require(isinstance(fixture.get(name), str) and SHA256_RE.fullmatch(fixture[name]) is not None, f"fixture {name} is not a digest")
    for name in ("external_dispatch", "background_runtime", "public_network", "production_activation"):
        require(fixture.get(name) is False, f"fixture {name} must be false")


def validate_mutations(values: Any, expected_sha: str) -> None:
    items = list(values) if isinstance(values, list) else []
    require(len(items) == 2, "exactly two A4-18R snapshot mutations are required")
    by_mode: dict[str, Mapping[str, Any]] = {}
    for item in items:
        require(isinstance(item, Mapping), "mutation must be an object")
        require(item.get("schema") == MUTATION_SCHEMA, "wrong mutation schema")
        require(item.get("repository_sha") == expected_sha, "mutation exact SHA mismatch")
        validate_self_digest(item, label="mutation")
        mode = item.get("mode")
        require(mode in {"campaign-record", "summary"} and mode not in by_mode, "mutation modes are invalid or duplicated")
        by_mode[str(mode)] = item
        for name in ("external_dispatch", "background_runtime", "public_network", "production_activation"):
            require(item.get(name) is False, f"mutation {mode} {name} must be false")
    require(set(by_mode) == {"campaign-record", "summary"}, "both mutation modes are required")

    campaign = by_mode["campaign-record"]
    require(campaign["campaign_count_after"] == campaign["campaign_count_before"] + 1, "campaign mutation did not add exactly one campaign")
    require(campaign["evidence_count_after"] == campaign["evidence_count_before"], "campaign mutation changed evidence count")
    require(campaign["timeline_head_after"] == campaign["timeline_head_before"], "campaign mutation changed timeline summary")
    require(campaign["evidence_head_after"] == campaign["evidence_head_before"], "campaign mutation changed evidence summary")

    summary = by_mode["summary"]
    require(summary["campaign_count_after"] == summary["campaign_count_before"], "summary mutation changed campaign count")
    require(summary["evidence_count_after"] == summary["evidence_count_before"] + 1, "summary mutation did not add one evidence record")
    require(summary["timeline_head_after"] != summary["timeline_head_before"], "summary mutation did not change timeline head")
    require(summary["evidence_head_after"] != summary["evidence_head_before"], "summary mutation did not change evidence head")


def validate_artifacts(artifacts: Any, output_root: Path, repo_root: Path) -> None:
    require(isinstance(artifacts, list) and artifacts, "artifact list is missing")
    seen: set[tuple[str, str]] = set()
    repository_paths: set[str] = set()
    output_paths: set[str] = set()
    for entry in artifacts:
        require(isinstance(entry, Mapping) and entry.get("schema") == FILE_SCHEMA, "artifact receipt has wrong schema")
        scope = entry.get("scope")
        require(scope in {"output", "repository"}, "artifact scope is invalid")
        rel = safe_relative_path(entry.get("path"))
        identity = (str(scope), rel)
        require(identity not in seen, f"duplicate artifact: {scope}:{rel}")
        seen.add(identity)
        base = output_root if scope == "output" else repo_root
        path = (base / rel).resolve()
        try:
            path.relative_to(base.resolve())
        except ValueError as exc:
            raise ValueError(f"artifact escaped {scope} root: {rel}") from exc
        require(path.is_file() and not path.is_symlink(), f"artifact missing or unsafe: {scope}:{rel}")
        require(entry.get("size_bytes") == path.stat().st_size, f"artifact size mismatch: {scope}:{rel}")
        require(entry.get("sha256") == sha256_file(path), f"artifact digest mismatch: {scope}:{rel}")
        (repository_paths if scope == "repository" else output_paths).add(rel)
    require(CRITICAL_REPOSITORY_ARTIFACTS.issubset(repository_paths), "critical current-product repository artifacts are missing")
    for suffix in ("bin/modelrig-a4-18r-backend.exe", "bin/modelrig-a4-18r-grants.exe", "bin/modelrig-a4-18r.apk", "fixture-manifest.json"):
        require(suffix in output_paths, f"critical output artifact missing: {suffix}")


def scan_output_tree(output_root: Path) -> None:
    for path in sorted(output_root.rglob("*")):
        require(not path.is_symlink(), f"A4-18R evidence tree may not contain symlink: {path}")
        if not path.is_file() or path.suffix.lower() not in {".json", ".log", ".txt"}:
            continue
        relative = path.relative_to(output_root).as_posix()
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        if path.suffix.lower() == ".json":
            value = json.loads(text, object_pairs_hook=reject_duplicate_object_pairs)
            scan_value(value, path=f"runtime.{relative}")
        else:
            scan_text(text, label=f"runtime.{relative}")


def audit_evidence(output_root: Path, *, expected_sha: str, repo_root: Path = ROOT) -> dict[str, object]:
    require(re.fullmatch(r"[0-9a-f]{40}", expected_sha) is not None, "expected SHA must be 40 lowercase hex")
    root = safe_output_root(output_root)
    marker = load_json(root / ".modelrig-a4-18r-output.json")
    require(isinstance(marker, Mapping) and marker.get("schema") == MARKER_SCHEMA, "A4-18R output marker is invalid")
    require(marker.get("repository_sha") == expected_sha, "output marker exact SHA mismatch")
    require(marker.get("public_network") is False and marker.get("production_activation") is False, "output marker widened authority")
    require(not (root / "admin-key.txt").exists(), "ephemeral admin key still exists after cleanup")
    require(not (root / "modelrig-data.json").exists(), "pairing/device store still exists after cleanup")

    receipt = load_json(root / "a4-18r-physical-read-receipt.json")
    require(isinstance(receipt, Mapping), "receipt must be an object")
    require(receipt.get("schema") == RECEIPT_SCHEMA, "wrong receipt schema")
    require(receipt.get("expected_sha") == expected_sha and receipt.get("observed_head") == expected_sha, "receipt exact SHA mismatch")
    require(receipt.get("public_network") is False and receipt.get("production_activation") is False, "receipt widened authority")
    require(receipt.get("credential_data_included") is False, "receipt claims credential material")
    require(receipt.get("all_required_observations_passed") is True, "physical observations are incomplete")
    require(receipt.get("human_decision") in {"GO", "NO-GO"}, "human decision is invalid")
    validate_self_digest(receipt, label="receipt")
    validate_trials(receipt.get("trials"))
    validate_fixture(receipt.get("fixture"), expected_sha)
    validate_mutations(receipt.get("mutations"), expected_sha)
    validate_artifacts(receipt.get("artifacts"), root, repo_root.resolve())

    pixel = receipt.get("pixel")
    require(isinstance(pixel, Mapping) and pixel.get("schema") == PIXEL_SCHEMA, "physical Pixel identity is missing")
    require(pixel.get("manufacturer") == "Google", "physical device is not a Google Pixel")
    require(isinstance(pixel.get("model"), str) and str(pixel["model"]).startswith("Pixel"), "physical device model is not Pixel")
    require(isinstance(pixel.get("serial_sha256"), str) and SHA256_RE.fullmatch(pixel["serial_sha256"]) is not None, "Pixel serial digest is invalid")
    require(pixel.get("package_name") == "dk.ternedal.modelrig.a425f", "wrong isolated product package")

    cleanup = receipt.get("cleanup")
    require(isinstance(cleanup, Mapping), "cleanup evidence is missing")
    for name in ("backend_stopped", "worker_stopped", "firewall_removed", "ports_free", "credential_file_deleted", "pairing_store_deleted", "test_package_uninstalled"):
        require(cleanup.get(name) is True, f"cleanup did not prove {name}")
    require(cleanup.get("unknown_process_preserved") is False, "cleanup encountered an unknown listener")

    scan_value(receipt)
    scan_output_tree(root)
    return {
        "schema": "modelrig-agent4/a4-18r-audit/v1",
        "expected_sha": expected_sha,
        "physical_qualification_evidence_valid": True,
        "credential_hygiene_verified": True,
        "artifact_hashes_verified": True,
        "human_decision": receipt["human_decision"],
        "public_network": False,
        "production_activation": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    try:
        result = audit_evidence(args.output_root, expected_sha=args.expected_sha)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"A4-18R PHYSICAL AUDIT: FAIL: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
