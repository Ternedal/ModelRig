#!/usr/bin/env python3
"""Fail-closed validator for Agent 4 A4-18 physical read receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA = "modelrig-agent4/physical-read-receipt/v2"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REQUIRED_CHECKPOINTS = (
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
FORBIDDEN_KEYS = {"token", "bearer", "authorization", "pairing_code", "admin_key", "password", "secret"}


class ReceiptValidationError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReceiptValidationError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def contains_forbidden_key(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in FORBIDDEN_KEYS or any(part in FORBIDDEN_KEYS for part in normalized.split("_")):
                return str(key)
            found = contains_forbidden_key(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = contains_forbidden_key(child)
            if found:
                return found
    return None


def validate_receipt(receipt: dict[str, Any], *, expected_sha: str | None, repo_root: Path | None) -> list[str]:
    require(receipt.get("schema") == SCHEMA, f"schema must be {SCHEMA}")
    observed = receipt.get("observed_head")
    expected = receipt.get("expected_sha")
    require(isinstance(expected, str) and SHA_RE.fullmatch(expected) is not None, "expected_sha must be a full lowercase SHA")
    require(observed == expected, "observed_head must equal expected_sha")
    if expected_sha is not None:
        require(SHA_RE.fullmatch(expected_sha) is not None, "--expected-sha must be a full lowercase SHA")
        require(expected == expected_sha, "receipt SHA does not match --expected-sha")

    require(receipt.get("human_decision") == "GO", "human_decision must be GO")
    require(receipt.get("all_required_observations_passed") is True, "all required observations must pass")
    require(receipt.get("credential_data_included") is False, "credential_data_included must be false")
    require(receipt.get("public_network") is False, "public_network must be false")
    require(receipt.get("production_activation") is False, "production_activation must be false")

    pixel = receipt.get("pixel")
    require(isinstance(pixel, dict), "pixel object is required")
    model = str(pixel.get("model", ""))
    require("pixel" in model.lower(), "physical device model must identify a Pixel")
    require("sdk" in pixel and str(pixel.get("sdk", "")).isdigit(), "Pixel SDK must be numeric")
    require(bool(str(pixel.get("version_name_line", "")).strip()), "installed app versionName is required")
    require(bool(str(pixel.get("version_code_line", "")).strip()), "installed app versionCode is required")

    trials = receipt.get("trials")
    require(isinstance(trials, dict), "trials object is required")
    require(set(trials) == set(REQUIRED_CHECKPOINTS), "trials must contain exactly the 21 required checkpoints")
    for name in REQUIRED_CHECKPOINTS:
        trial = trials[name]
        require(isinstance(trial, dict), f"trial {name} must be an object")
        require(trial.get("status") == "pass", f"trial {name} did not pass")
        if name in EXPECTED_HTTP:
            require(trial.get("http_status") == EXPECTED_HTTP[name], f"trial {name} has wrong HTTP status")
        for hash_key in ("payload_sha256", "cursor_sha256"):
            value = trial.get(hash_key)
            if value is not None:
                require(isinstance(value, str) and HASH_RE.fullmatch(value) is not None, f"trial {name} has invalid {hash_key}")

    cleanup = receipt.get("cleanup")
    require(isinstance(cleanup, dict), "cleanup object is required")
    for field in ("backend_stopped", "worker_stopped", "firewall_removed", "ports_free", "admin_key_deleted", "passed"):
        require(cleanup.get(field) is True, f"cleanup.{field} must be true")
    require(cleanup.get("unknown_process_preserved") is False, "cleanup found an unknown process")

    forbidden = contains_forbidden_key(receipt)
    require(forbidden is None, f"forbidden credential-shaped key present: {forbidden}")

    claimed_digest = receipt.get("receipt_sha256")
    require(isinstance(claimed_digest, str) and HASH_RE.fullmatch(claimed_digest) is not None, "receipt_sha256 is invalid")
    without_digest = dict(receipt)
    without_digest.pop("receipt_sha256", None)
    canonical = json.dumps(without_digest, ensure_ascii=False, separators=(",", ":"))
    actual_digest = f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
    require(claimed_digest == actual_digest, "receipt_sha256 does not match canonical receipt content")

    verified_artifacts: list[str] = []
    artifacts = receipt.get("artifacts")
    require(isinstance(artifacts, list) and artifacts, "artifacts must be a non-empty list")
    seen_paths: set[str] = set()
    for index, artifact in enumerate(artifacts):
        require(isinstance(artifact, dict), f"artifact {index} must be an object")
        path_value = artifact.get("path")
        digest_value = artifact.get("sha256")
        require(isinstance(path_value, str) and path_value and not Path(path_value).is_absolute(), f"artifact {index} path is invalid")
        require(".." not in Path(path_value).parts, f"artifact {index} escapes repo root")
        require(path_value not in seen_paths, f"duplicate artifact path: {path_value}")
        seen_paths.add(path_value)
        require(isinstance(digest_value, str) and HASH_RE.fullmatch(digest_value) is not None, f"artifact {path_value} hash is invalid")
        require(isinstance(artifact.get("size_bytes"), int) and artifact["size_bytes"] >= 0, f"artifact {path_value} size is invalid")
        if repo_root is not None:
            local = (repo_root / path_value).resolve()
            require(local.is_relative_to(repo_root.resolve()), f"artifact {path_value} escapes repo root")
            require(local.is_file(), f"artifact missing: {path_value}")
            require(local.stat().st_size == artifact["size_bytes"], f"artifact size mismatch: {path_value}")
            require(sha256_file(local) == digest_value, f"artifact hash mismatch: {path_value}")
            verified_artifacts.append(path_value)

    return verified_artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--expected-sha")
    parser.add_argument("--repo-root", type=Path)
    args = parser.parse_args()
    try:
        raw = args.receipt.read_text(encoding="utf-8-sig")
        parsed = json.loads(raw)
        require(isinstance(parsed, dict), "receipt root must be an object")
        verified = validate_receipt(parsed, expected_sha=args.expected_sha, repo_root=args.repo_root)
    except (OSError, json.JSONDecodeError, ReceiptValidationError) as exc:
        print(f"A4-18 RECEIPT INVALID: {exc}", file=sys.stderr)
        return 2
    print(f"A4-18 RECEIPT VALID: {args.receipt}")
    print(f"exact_sha={parsed['expected_sha']} checkpoints={len(REQUIRED_CHECKPOINTS)} artifacts_verified={len(verified)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
