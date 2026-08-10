#!/usr/bin/env python3
"""Fail-closed credential guard for A4-18 physical receipt evidence.

This guard runs before the legacy PowerShell receipt auditor. It scans the
receipt recursively and the runtime text evidence for credential field aliases
and credential value shapes that are unsafe to publish as acceptance evidence.
It performs no network access and writes nothing.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping

REQUIRED_TRIALS = {
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
}

RUNTIME_RELATIVE = Path("validation/agent4-physical-runtime")
TEXT_EVIDENCE_SUFFIXES = {".json", ".log", ".txt"}

# Key names are normalized before comparison so camelCase, kebab-case and
# underscore aliases cannot bypass the scanner.
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

# Backend auth.NewToken() emits exactly 64 lowercase hex characters. Any bare
# value of that shape is ambiguous credential material and must be rejected;
# canonical evidence digests remain allowed because they are prefixed sha256:.
RAW_DEVICE_TOKEN_RE = re.compile(r"(?<!sha256:)\b[0-9a-f]{64}\b")
RAW_PAIRING_CODE_RE = re.compile(r"\b[A-Z0-9]{4}-[A-Z0-9]{4}\b")
CREDENTIAL_VALUE_PATTERNS = (
    re.compile(r"(?i)\bauthorization\s*:\s*(?:bearer\s+)?[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\bMODELRIG_ADMIN_KEY\s*=\s*(?!%|<redacted>|\[redacted\])\S{4,}"),
    re.compile(r"(?i)\bpairing[_ -]?code\s*[:=]\s*(?!<redacted>|\[redacted\])\S{4,}"),
    re.compile(r"(?i)\bdevice[_ -]?token\s*[:=]\s*(?!<redacted>|\[redacted\]|sha256:)\S{4,}"),
    re.compile(r"(?i)\badmin[_ -]?key\s*[:=]\s*(?!<redacted>|\[redacted\])\S{4,}"),
    re.compile(r"(?i)\b(?:deviceToken|pairingCode|adminKey|clientSecret|privateKey)\s*[:=]\s*(?!<redacted>|\[redacted\]|sha256:)\S{4,}"),
    RAW_PAIRING_CODE_RE,
    RAW_DEVICE_TOKEN_RE,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def credential_key_is_forbidden(name: str) -> bool:
    compact = re.sub(r"[^a-z0-9]", "", name.lower())
    return any(term in compact for term in FORBIDDEN_CREDENTIAL_KEY_TERMS)


def known_credential_evidence_marker(path: str, name: str, value: Any) -> bool:
    if path == "root.cleanup" and name == "admin_key_deleted" and type(value) is bool:
        return True
    return path == "root.trials" and name in REQUIRED_TRIALS and isinstance(value, Mapping)


def scan_text_credentials(text: str, *, label: str) -> None:
    for pattern in CREDENTIAL_VALUE_PATTERNS:
        require(pattern.search(text) is None, f"credential-lignende værdi ved {label}")


def scan_value_credentials(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key)
            allowed = known_credential_evidence_marker(path, name, child)
            require(
                allowed or not credential_key_is_forbidden(name),
                f"forbudt credential-felt ved {path}.{name}",
            )
            scan_value_credentials(child, f"{path}.{name}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            scan_value_credentials(child, f"{path}[{index}]")
        return
    if isinstance(value, str):
        scan_text_credentials(value, label=path)


def reject_duplicate_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def scan_runtime_evidence(repo_root: Path) -> None:
    runtime = (repo_root / RUNTIME_RELATIVE).resolve()
    require(runtime.is_dir() and not runtime.is_symlink(), "validation runtime mangler eller er et symlink")
    for path in sorted(runtime.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"runtime evidence må ikke indeholde symlink: {path.relative_to(repo_root)}")
        if not path.is_file() or path.suffix.lower() not in TEXT_EVIDENCE_SUFFIXES:
            continue
        relative = path.relative_to(repo_root).as_posix()
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        scan_text_credentials(text, label=f"runtime evidence {relative}")
        if path.suffix.lower() == ".json":
            try:
                value = json.loads(text, object_pairs_hook=reject_duplicate_object_pairs)
            except json.JSONDecodeError as exc:
                raise ValueError(f"runtime JSON evidence er ugyldig: {relative}") from exc
            scan_value_credentials(value, path=f"runtime.{relative}")


def validate(receipt_path: Path, repo_root: Path) -> None:
    raw = receipt_path.read_text(encoding="utf-8-sig")
    receipt = json.loads(raw, object_pairs_hook=reject_duplicate_object_pairs)
    require(isinstance(receipt, dict), "receipt skal være et JSON-objekt")
    scan_value_credentials(receipt)
    scan_runtime_evidence(repo_root)


def self_test() -> None:
    scan_value_credentials({"digest": "sha256:" + "0" * 64})
    scan_value_credentials(
        {
            "cleanup": {"admin_key_deleted": True},
            "trials": {"grant_same_token_200": {"status": "pass"}},
        }
    )
    for unsafe in (
        {"note": "a" * 64},
        {"note": "ABCD" + "-" + "EFGH"},
        {"debug": {"deviceToken": "redacted-value"}},
    ):
        try:
            scan_value_credentials(unsafe)
        except ValueError:
            continue
        raise ValueError("credential guard self-test accepterede unsafe evidence")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    try:
        if args.self_test:
            self_test()
        else:
            repo_root = (args.repo_root or Path(__file__).resolve().parents[1]).resolve()
            receipt = (args.receipt or repo_root / "validation" / "agent4-physical-read-latest.json").resolve()
            validate(receipt, repo_root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"A4-25 PHYSICAL CREDENTIAL GUARD: FAIL: {exc}")
        return 2

    print("A4-25 PHYSICAL CREDENTIAL GUARD: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
