#!/usr/bin/env python3
"""Verify an A4-18 physical Agent 4 read receipt without network or mutation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "modelrig-agent4/physical-read-receipt/v2"
DEFAULT_RECEIPT = Path("validation/agent4-physical-read-latest.json")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")

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

SENSITIVE_KEY_RE = re.compile(
    r"(?:^|_)(?:token|bearer|authorization|pairing_code|admin_key|password|secret)(?:$|_)",
    re.IGNORECASE,
)
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"Authorization\s*:", re.IGNORECASE),
    re.compile(r"X-Admin-Key\s*:", re.IGNORECASE),
    re.compile(r"MODELRIG_ADMIN_KEY", re.IGNORECASE),
)
ALLOWED_SECURITY_KEYS = {"credential_data_included", "admin_key_deleted"}


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    receipt_sha256: str | None
    expected_sha: str | None
    pixel_model: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "modelrig-agent4/physical-read-verification/v1",
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "receipt_sha256": self.receipt_sha256,
            "expected_sha": self.expected_sha,
            "pixel_model": self.pixel_model,
        }


class ReceiptVerifier:
    def __init__(self, receipt: Any, expected_sha: str | None = None) -> None:
        self.receipt = receipt
        self.required_sha = expected_sha
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.error(message)

    def verify(self) -> VerificationResult:
        if not isinstance(self.receipt, dict):
            self.error("receipt root must be an object")
            return self.result()

        self.verify_top_level()
        self.verify_digest()
        self.verify_identity()
        self.verify_pixel()
        self.verify_trials()
        self.verify_artifacts()
        self.verify_mutations()
        self.verify_cleanup()
        self.verify_no_credentials()
        return self.result()

    def result(self) -> VerificationResult:
        receipt = self.receipt if isinstance(self.receipt, dict) else {}
        pixel = receipt.get("pixel") if isinstance(receipt.get("pixel"), dict) else {}
        return VerificationResult(
            ok=not self.errors,
            errors=tuple(self.errors),
            warnings=tuple(self.warnings),
            receipt_sha256=_string_or_none(receipt.get("receipt_sha256")),
            expected_sha=_string_or_none(receipt.get("expected_sha")),
            pixel_model=_string_or_none(pixel.get("model")),
        )

    def verify_top_level(self) -> None:
        receipt = self.receipt
        self.require(receipt.get("schema") == SCHEMA, f"schema must be {SCHEMA}")
        self.require(receipt.get("human_decision") == "GO", "human_decision must be GO")
        self.require(receipt.get("all_required_observations_passed") is True,
                     "all_required_observations_passed must be true")
        self.require(receipt.get("credential_data_included") is False,
                     "credential_data_included must be false")
        self.require(receipt.get("public_network") is False, "public_network must be false")
        self.require(receipt.get("production_activation") is False,
                     "production_activation must be false")
        generated_at = receipt.get("generated_at")
        self.require(isinstance(generated_at, str) and bool(ISO_UTC_RE.fullmatch(generated_at)),
                     "generated_at must be an ISO-8601 UTC timestamp")

    def verify_digest(self) -> None:
        receipt = self.receipt
        recorded = receipt.get("receipt_sha256")
        self.require(isinstance(recorded, str) and bool(SHA256_RE.fullmatch(recorded)),
                     "receipt_sha256 must be sha256:<64 lowercase hex>")
        if not isinstance(recorded, str):
            return
        without_digest = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        canonical = json.dumps(without_digest, ensure_ascii=False, separators=(",", ":"))
        calculated = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        self.require(recorded == calculated, "receipt_sha256 does not match canonical receipt content")

    def verify_identity(self) -> None:
        receipt = self.receipt
        expected_sha = receipt.get("expected_sha")
        observed_head = receipt.get("observed_head")
        self.require(isinstance(expected_sha, str) and bool(GIT_SHA_RE.fullmatch(expected_sha)),
                     "expected_sha must be a full lowercase Git SHA")
        self.require(observed_head == expected_sha, "observed_head must equal expected_sha")
        if self.required_sha is not None:
            self.require(expected_sha == self.required_sha,
                         "receipt expected_sha does not match --expected-sha")
        branch = receipt.get("branch")
        self.require(isinstance(branch, str) and branch == "agent/a4-18-physical-read-product",
                     "branch must be agent/a4-18-physical-read-product")
        for field in ("backend_version", "worker_version"):
            value = receipt.get(field)
            self.require(isinstance(value, str) and bool(value.strip()), f"{field} must be non-empty")

    def verify_pixel(self) -> None:
        pixel = self.receipt.get("pixel")
        if not isinstance(pixel, dict):
            self.error("pixel must be an object")
            return
        model = pixel.get("model")
        self.require(isinstance(model, str) and "pixel" in model.lower(),
                     "pixel.model must identify a Google Pixel")
        if isinstance(model, str):
            lowered = model.lower()
            self.require(not any(marker in lowered for marker in ("sdk", "emulator", "qemu")),
                         "pixel.model must not identify an emulator")
        self.require(pixel.get("app_package") == "dk.ternedal.modelrig",
                     "pixel.app_package must be dk.ternedal.modelrig")
        for field in ("android_release", "sdk", "version_name_line", "version_code_line"):
            value = pixel.get(field)
            self.require(isinstance(value, str) and bool(value.strip()), f"pixel.{field} must be non-empty")

    def verify_trials(self) -> None:
        trials = self.receipt.get("trials")
        if not isinstance(trials, dict):
            self.error("trials must be an object")
            return
        names = set(trials)
        required = set(REQUIRED_CHECKPOINTS)
        missing = sorted(required - names)
        unknown = sorted(names - required)
        self.require(not missing, f"missing required checkpoints: {', '.join(missing)}")
        self.require(not unknown, f"unknown checkpoints present: {', '.join(unknown)}")
        for name in REQUIRED_CHECKPOINTS:
            entry = trials.get(name)
            if not isinstance(entry, dict):
                self.error(f"trial {name} must be an object")
                continue
            self.require(entry.get("status") == "pass", f"trial {name} status must be pass")
            observed_at = entry.get("observed_at")
            self.require(isinstance(observed_at, str) and bool(ISO_UTC_RE.fullmatch(observed_at)),
                         f"trial {name} observed_at must be ISO-8601 UTC")
            expected_http = EXPECTED_HTTP.get(name)
            if expected_http is not None:
                self.require(entry.get("http_status") == expected_http,
                             f"trial {name} http_status must be {expected_http}")
                route = entry.get("route")
                self.require(isinstance(route, str) and route.startswith("/api/v1/agent4/") and "?" not in route,
                             f"trial {name} route must be a redacted /api/v1/agent4 path")
            for field in ("payload_sha256", "cursor_sha256"):
                value = entry.get(field)
                if value is not None:
                    self.require(isinstance(value, str) and bool(SHA256_RE.fullmatch(value)),
                                 f"trial {name} {field} must be sha256:<64 lowercase hex>")
            screenshot = entry.get("screenshot")
            if screenshot is not None:
                self.verify_file_receipt(screenshot, f"trial {name} screenshot")

        for name in ("campaign_paging_no_loss", "timeline_paging_no_loss", "evidence_paging_no_loss"):
            entry = trials.get(name)
            if isinstance(entry, dict):
                self.require(bool(SHA256_RE.fullmatch(str(entry.get("payload_sha256", "")))),
                             f"trial {name} requires payload_sha256")
                self.require(bool(SHA256_RE.fullmatch(str(entry.get("cursor_sha256", "")))),
                             f"trial {name} requires cursor_sha256")

    def verify_file_receipt(self, value: Any, label: str) -> None:
        if not isinstance(value, dict):
            self.error(f"{label} must be an object")
            return
        path = value.get("path")
        self.require(isinstance(path, str) and bool(path) and not Path(path).is_absolute() and ".." not in Path(path).parts,
                     f"{label}.path must be a relative repository path")
        size = value.get("size_bytes")
        self.require(type(size) is int and size >= 0, f"{label}.size_bytes must be a non-negative integer")
        digest = value.get("sha256")
        self.require(isinstance(digest, str) and bool(SHA256_RE.fullmatch(digest)),
                     f"{label}.sha256 must be sha256:<64 lowercase hex>")

    def verify_artifacts(self) -> None:
        artifacts = self.receipt.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            self.error("artifacts must be a non-empty list")
            return
        paths: set[str] = set()
        for index, artifact in enumerate(artifacts):
            self.verify_file_receipt(artifact, f"artifacts[{index}]")
            if isinstance(artifact, dict) and isinstance(artifact.get("path"), str):
                path = artifact["path"]
                self.require(path not in paths, f"duplicate artifact path: {path}")
                paths.add(path)
        required_suffixes = (
            "worker/app/entrypoint.py",
            "worker/app/agent4/production_bootstrap.py",
            "worker/app/agent4/operator_api.py",
            "android/app/src/main/java/dk/ternedal/modelrig/net/Agent4OperatorClient.kt",
        )
        for suffix in required_suffixes:
            self.require(any(path.endswith(suffix) for path in paths), f"required artifact missing: {suffix}")

    def verify_mutations(self) -> None:
        mutations = self.receipt.get("mutations")
        self.require(isinstance(mutations, list) and len(mutations) >= 2,
                     "mutations must contain both physical stale-snapshot mutations")
        fixture = self.receipt.get("fixture")
        self.require(isinstance(fixture, dict), "fixture must be an object")

    def verify_cleanup(self) -> None:
        cleanup = self.receipt.get("cleanup")
        if not isinstance(cleanup, dict):
            self.error("cleanup must be an object")
            return
        for field in ("backend_stopped", "worker_stopped", "firewall_removed", "ports_free", "admin_key_deleted", "passed"):
            self.require(cleanup.get(field) is True, f"cleanup.{field} must be true")
        self.require(cleanup.get("unknown_process_preserved") is False,
                     "cleanup.unknown_process_preserved must be false")

    def verify_no_credentials(self) -> None:
        for path, key, value in walk(self.receipt):
            if key is not None and key not in ALLOWED_SECURITY_KEYS and SENSITIVE_KEY_RE.search(key):
                self.error(f"sensitive key is forbidden at {path}: {key}")
            if isinstance(value, str):
                for pattern in SENSITIVE_VALUE_PATTERNS:
                    if pattern.search(value):
                        self.error(f"credential-like material is forbidden at {path}")
                        break


def walk(value: Any, path: str = "$", key: str | None = None) -> Iterable[tuple[str, str | None, Any]]:
    yield path, key, value
    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from walk(child, f"{path}.{child_key}", str(child_key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]", None)


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def load_receipt(path: Path) -> Any:
    raw = path.read_text(encoding="utf-8-sig")
    return json.loads(raw)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", nargs="?", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--expected-sha", help="Require one exact 40-character repository SHA")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Emit only JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.expected_sha is not None and not GIT_SHA_RE.fullmatch(args.expected_sha):
        print("--expected-sha must be a full lowercase Git SHA", file=sys.stderr)
        return 2
    try:
        receipt = load_receipt(args.receipt)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        payload = {
            "schema": "modelrig-agent4/physical-read-verification/v1",
            "ok": False,
            "errors": [f"could not read receipt: {exc}"],
            "warnings": [],
            "receipt_sha256": None,
            "expected_sha": None,
            "pixel_model": None,
        }
        print(json.dumps(payload, ensure_ascii=False) if args.json_output else payload["errors"][0])
        return 2

    result = ReceiptVerifier(receipt, args.expected_sha).verify()
    if args.json_output:
        print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
    else:
        status = "PASS" if result.ok else "FAIL"
        print(f"A4-20 receipt verification: {status}")
        if result.expected_sha:
            print(f"Exact SHA: {result.expected_sha}")
        if result.pixel_model:
            print(f"Pixel: {result.pixel_model}")
        for warning in result.warnings:
            print(f"WARNING: {warning}")
        for error in result.errors:
            print(f"ERROR: {error}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
