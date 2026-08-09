#!/usr/bin/env python3
"""Fail-closed pre-audit for A4-18 physical receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

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
SHA_PREFIX = "sha256:"


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_value(value: Any) -> str:
    return SHA_PREFIX + hashlib.sha256(canonical_json(value)).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def require_sha(value: Any, label: str) -> str:
    require(isinstance(value, str), f"{label} mangler")
    require(len(value) == 71 and value.startswith(SHA_PREFIX), f"{label} har forkert format")
    int(value[len(SHA_PREFIX) :], 16)
    require(value == value.lower(), f"{label} skal være lowercase")
    return value


def safe_repo_path(repo_root: Path, value: Any, label: str) -> Path:
    require(isinstance(value, str) and value, f"{label} mangler")
    require("\\" not in value and not value.startswith("/"), f"{label} er ikke relativ")
    require(".." not in Path(value).parts, f"{label} indeholder parent traversal")
    candidate = (repo_root / value).resolve()
    candidate.relative_to(repo_root.resolve())
    return candidate


def validate_mutations(receipt: dict[str, Any]) -> None:
    mutations = receipt.get("mutations")
    require(isinstance(mutations, list) and len(mutations) == 2, "præcis to mutation receipts kræves")
    modes: set[str] = set()
    for mutation in mutations:
        require(isinstance(mutation, dict), "mutation receipt skal være et objekt")
        mode = mutation.get("mode")
        require(mode in {"campaign-record", "summary"}, "ukendt mutation mode")
        require(mode not in modes, "dublet mutation mode")
        modes.add(mode)
        claimed = require_sha(mutation.get("receipt_sha256"), f"mutation {mode} digest")
        unsigned = {key: value for key, value in mutation.items() if key != "receipt_sha256"}
        require(sha256_value(unsigned) == claimed, f"mutation {mode} digest matcher ikke indholdet")


def validate_trial_set(receipt: dict[str, Any]) -> dict[str, Any]:
    trials = receipt.get("trials")
    require(isinstance(trials, dict), "trials mangler")
    actual = set(trials)
    require(actual == REQUIRED_TRIALS, "trials skal indeholde præcis de 21 kendte checkpoints")
    return trials


def validate_file_receipt(repo_root: Path, value: Any, label: str) -> None:
    require(isinstance(value, dict), f"{label} mangler")
    path = safe_repo_path(repo_root, value.get("path"), f"{label}.path")
    require(path.is_file(), f"{label} fil mangler")
    require(path.stat().st_size == value.get("size_bytes"), f"{label} størrelse afviger")
    claimed = require_sha(value.get("sha256"), f"{label}.sha256")
    actual = SHA_PREFIX + hashlib.sha256(path.read_bytes()).hexdigest()
    require(actual == claimed, f"{label} hash afviger")


def validate_ui_evidence(repo_root: Path, trials: dict[str, Any]) -> None:
    for name in UI_OBSERVATION_TRIALS:
        entry = trials[name]
        require(isinstance(entry, dict), f"{name} skal være et objekt")
        note = entry.get("note")
        screenshot = entry.get("screenshot")
        if screenshot is not None:
            validate_file_receipt(repo_root, screenshot, f"{name}.screenshot")
            path = str(screenshot.get("path", ""))
            require(
                path.startswith("validation/agent4-physical-runtime/"),
                f"{name} screenshot ligger uden for validation runtime",
            )
        require(
            screenshot is not None or isinstance(note, str) and note.strip(),
            f"{name} mangler både screenshot og menneskelig UI-observation",
        )


def validate_safety(repo_root: Path, receipt: dict[str, Any]) -> None:
    safety = receipt.get("safety_hardening")
    require(isinstance(safety, dict), "safety_hardening mangler")
    require(
        safety.get("schema") == "modelrig-agent4/physical-read-safety-evidence/v1",
        "forkert safety schema",
    )
    for key in ("physical_pixel", "artifacts_hashed_after_prestop"):
        require(safety.get(key) is True, f"safety_hardening.{key} skal være true")
    for key in ("wildcard_binding", "public_network", "production_activation"):
        require(safety.get(key) is False, f"safety_hardening.{key} skal være false")
    require(safety.get("pixel_manufacturer") == "Google", "safety hardware er ikke Google")
    model = safety.get("pixel_model")
    require(isinstance(model, str) and model.startswith("Pixel"), "safety hardware er ikke Pixel")
    require(not any(term in model.lower() for term in ("emulator", "qemu", "sdk_gphone", "generic")), "emulator-model afvist")
    require_sha(safety.get("pixel_serial_sha256"), "pixel serial hash")
    require(safety.get("backend_bound_address") == safety.get("lan_address"), "backend bind matcher ikke LAN")
    require(safety.get("worker_bound_address") == "127.0.0.1", "worker er ikke loopback-only")
    require(safety.get("firewall_remote_scope") == "LocalSubnet", "firewall scope er ikke LocalSubnet")
    require(safety.get("network_profile") != "Public", "Public netværksprofil afvist")
    binding = safety.get("binding_file")
    require(isinstance(binding, dict), "safety binding receipt mangler")
    require(
        binding.get("path") == "validation/agent4-physical-runtime/safety-binding.json",
        "forkert safety binding path",
    )
    validate_file_receipt(repo_root, binding, "safety binding")
    pixel = receipt.get("pixel")
    require(isinstance(pixel, dict) and pixel.get("model") == model, "Pixel-model matcher ikke safety evidence")


def validate(receipt_path: Path, repo_root: Path) -> None:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    require(isinstance(receipt, dict), "receipt skal være et JSON-objekt")
    trials = validate_trial_set(receipt)
    validate_mutations(receipt)
    validate_safety(repo_root, receipt)
    validate_ui_evidence(repo_root, trials)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        require(len(REQUIRED_TRIALS) == 21, "checkpoint count self-test fejlede")
        require_sha(SHA_PREFIX + "0" * 64, "self-test hash")
        print("A4-18 receipt hardening self-test: PASS")
        return 0
    repo_root = (args.repo_root or Path(__file__).resolve().parents[1]).resolve()
    receipt = args.receipt or repo_root / "validation" / "agent4-physical-read-latest.json"
    try:
        validate(receipt.resolve(), repo_root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"A4-18 RECEIPT HARDENING: FAIL: {exc}")
        return 2
    print("A4-18 RECEIPT HARDENING: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
