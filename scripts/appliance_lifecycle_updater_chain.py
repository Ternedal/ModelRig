#!/usr/bin/env python3
"""Fail-closed semantic gate for the Stage B updater lifecycle evidence.

The ordinary physical campaign already validates candidate identity, typed trial
booleans, timestamps and artifact hashes. This additional gate validates what the
updater logs actually prove. A random non-empty file is not updater evidence: the
good-update log must contain the real download -> checksum -> provenance -> swap
-> backend/worker health -> supervisor-heartbeat chain, and the bad-update log
must prove either a pre-swap refusal or a completed rollback.

This command performs no network request, update, restart, merge, release or
activation. It only reads ignored local evidence and writes one ignored receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "kaliv-appliance-lifecycle-updater-chain/v1"
LIFECYCLE_SCHEMA = "kaliv-appliance-lifecycle-observations/v1"
DEFAULT_LIFECYCLE = Path("validation/appliance-lifecycle-observations.json")
DEFAULT_REPORT = Path("validation/appliance-lifecycle-updater-chain-latest.json")
MAX_BYTES = 32 * 1024 * 1024
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
ASSETS = (
    "modelrig-server-windows-x64.exe",
    "modelrig-supervisor-windows-x64.exe",
    "modelrig-worker-windows-x64.exe",
)
BYPASS_MARKERS = (
    "installing without integrity verification",
    "installing without provenance verification",
    "insecure-skip-verify",
    "skip-attestation",
    "no-heartbeat-check",
    "heartbeat verification skipped",
)


class UpdaterChainError(RuntimeError):
    """The Stage B updater evidence cannot support a trustworthy verdict."""


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
    candidate = raw if raw.is_absolute() else root / raw
    if candidate.is_symlink():
        raise UpdaterChainError(f"path is a symlink: {raw}")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise UpdaterChainError(f"path escapes repository: {raw}") from exc
    return resolved


def _load_json(root: Path, raw: Path) -> tuple[dict[str, Any], bytes, Path]:
    path = _resolve_under(root, raw)
    if not path.exists() or not path.is_file() or path.is_symlink():
        raise UpdaterChainError(f"JSON evidence is missing or irregular: {raw}")
    size = path.stat().st_size
    if size <= 0 or size > MAX_BYTES:
        raise UpdaterChainError(f"JSON evidence size is invalid: {raw}")
    body = path.read_bytes()
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdaterChainError(f"JSON evidence is invalid UTF-8 JSON: {raw}") from exc
    if not isinstance(value, dict):
        raise UpdaterChainError(f"JSON evidence must be an object: {raw}")
    return value, body, path


def _load_candidate_identity(root: Path) -> dict[str, Any]:
    path = root / "scripts" / "physical_validation_campaign.py"
    spec = importlib.util.spec_from_file_location("updater_chain_candidate", path)
    if spec is None or spec.loader is None:
        raise UpdaterChainError("candidate identity module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    value = module.candidate_identity(root)
    if not isinstance(value, dict):
        raise UpdaterChainError("candidate identity is invalid")
    return value


def _same_candidate(errors: list[str], actual: Any, expected: Mapping[str, Any]) -> None:
    if not isinstance(actual, Mapping):
        errors.append("lifecycle candidate identity is missing")
        return
    for key in ("version", "git_sha", "code_sha256"):
        if actual.get(key) != expected.get(key):
            errors.append(f"lifecycle candidate.{key} mismatch")


def _trial(report: Mapping[str, Any], name: str, errors: list[str]) -> dict[str, Any]:
    trials = report.get("trials")
    if not isinstance(trials, Mapping):
        errors.append("lifecycle trials are missing")
        return {}
    value = trials.get(name)
    if not isinstance(value, dict):
        errors.append(f"{name} trial is missing")
        return {}
    return value


def _load_log(
    root: Path,
    label: str,
    trial: Mapping[str, Any],
    errors: list[str],
) -> tuple[dict[str, Any], str]:
    raw_path = trial.get("evidence_path")
    digest = trial.get("evidence_sha256")
    if not isinstance(raw_path, str) or not raw_path.strip():
        errors.append(f"{label}.evidence_path is missing")
        return {}, ""
    relative_input = Path(raw_path)
    if relative_input.is_absolute() or ".." in relative_input.parts:
        errors.append(f"{label}.evidence_path must be repository-relative")
        return {}, ""
    try:
        path = _resolve_under(root, relative_input)
        relative = path.relative_to(root.resolve())
    except UpdaterChainError as exc:
        errors.append(f"{label}.evidence_path is invalid: {exc}")
        return {}, ""
    if relative.parts[:2] != ("validation", "appliance-lifecycle-evidence"):
        errors.append(
            f"{label}.evidence_path must be under validation/appliance-lifecycle-evidence"
        )
        return {}, ""
    if not path.exists() or not path.is_file() or path.is_symlink():
        errors.append(f"{label} updater log is missing or irregular")
        return {}, ""
    size = path.stat().st_size
    if size <= 0 or size > MAX_BYTES:
        errors.append(f"{label} updater log size is invalid: {size} bytes")
        return {}, ""
    body = path.read_bytes()
    actual = hashlib.sha256(body).hexdigest()
    if not isinstance(digest, str) or _SHA64.fullmatch(digest) is None:
        errors.append(f"{label}.evidence_sha256 is invalid")
    elif digest != actual:
        errors.append(f"{label}.evidence_sha256 does not match the updater log")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        errors.append(f"{label} updater log is not UTF-8 text")
        text = ""
    return {
        "path": str(relative),
        "sha256": actual,
        "bytes": len(body),
    }, text.lower()


def _missing_markers(text: str, markers: tuple[str, ...]) -> list[str]:
    return [marker for marker in markers if marker.lower() not in text]


def _forbidden_markers(text: str, markers: tuple[str, ...]) -> list[str]:
    return [marker for marker in markers if marker.lower() in text]


def evaluate(
    root: Path,
    lifecycle_path: Path,
    *,
    candidate: Mapping[str, Any],
    now: datetime,
) -> tuple[dict[str, Any], int]:
    errors: list[str] = []
    lifecycle, lifecycle_raw, lifecycle_file = _load_json(root, lifecycle_path)
    if lifecycle.get("schema") != LIFECYCLE_SCHEMA:
        errors.append("lifecycle schema mismatch")
    _same_candidate(errors, lifecycle.get("candidate"), candidate)

    version = str(candidate.get("version") or "").lower()
    if not version:
        errors.append("candidate version is missing")
    if _SHA40.fullmatch(str(candidate.get("git_sha") or "")) is None:
        errors.append("candidate Git SHA is invalid")
    if _SHA64.fullmatch(str(candidate.get("code_sha256") or "")) is None:
        errors.append("candidate worker fingerprint is invalid")
    if candidate.get("identity_source") == "git" and candidate.get("working_tree_clean") is not True:
        errors.append("current candidate working tree is not clean")
    if candidate.get("version_stamps_consistent") is not True:
        errors.append("current candidate version stamps are inconsistent")

    good = _trial(lifecycle, "good_update", errors)
    bad = _trial(lifecycle, "bad_update", errors)
    good_meta, good_text = _load_log(root, "good_update", good, errors)
    bad_meta, bad_text = _load_log(root, "bad_update", bad, errors)
    if good_meta and bad_meta and good_meta.get("path") == bad_meta.get("path"):
        errors.append("good_update and bad_update must use different updater logs")

    source_version = str(good.get("source_version") or "").lower()
    target_version = str(good.get("target_version") or "").lower()
    good_required = (
        "update available:",
        *(f"downloading {asset}" for asset in ASSETS),
        "checksums verified for 3 exe(s)",
        "build provenance verified for 3 exe(s)",
        "stopping supervisor + processes so the exes unlock",
        "supervisor heartbeat advanced past the restart",
        "update ok: backend + worker report",
    )
    missing_good = _missing_markers(good_text, tuple(good_required))
    for marker in missing_good:
        errors.append(f"good_update log is missing required marker: {marker}")
    if source_version and source_version not in good_text:
        errors.append("good_update log does not name source_version")
    if target_version and target_version not in good_text:
        errors.append("good_update log does not name target_version")
    if target_version != version:
        errors.append("good_update target_version does not equal candidate version")
    for marker in _forbidden_markers(
        good_text,
        BYPASS_MARKERS
        + (
            "rolling back",
            "rollback failed",
            "manual_recovery",
            "journal could not be archived",
            "fatal:",
        ),
    ):
        errors.append(f"good_update log contains forbidden marker: {marker}")

    attempted_version = str(bad.get("attempted_version") or "").lower()
    if attempted_version and attempted_version not in bad_text:
        errors.append("bad_update log does not name attempted_version")
    for marker in _forbidden_markers(bad_text, BYPASS_MARKERS + ("rollback failed", "manual_recovery")):
        errors.append(f"bad_update log contains forbidden marker: {marker}")

    rejection_markers = (
        "checksum mismatch",
        "no build provenance",
        "refusing to install unverified",
        "has no sha256sums.txt",
        "has no entry for",
        "cannot check provenance",
        "refusing to install",
    )
    rejected = any(marker in bad_text for marker in rejection_markers)
    stopped_for_swap = "stopping supervisor + processes so the exes unlock" in bad_text
    rollback_start = f"rolling back to {version}" in bad_text if version else False
    rollback_complete = (
        f"rolled back to {version}: backend + worker healthy and the supervisor is looping"
        in bad_text
        if version
        else False
    )
    if rejected and not stopped_for_swap:
        bad_outcome = "rejected_before_swap"
    elif rollback_start and rollback_complete:
        bad_outcome = "rolled_back_and_recovered"
    else:
        bad_outcome = "unproven"
        errors.append(
            "bad_update log proves neither a pre-swap refusal nor a completed healthy rollback"
        )

    journal = root / "update-transaction.json"
    if journal.exists():
        errors.append("update-transaction.json still exists; updater transaction is not terminal")

    report = {
        "schema": SCHEMA,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "candidate": dict(candidate),
        "source": {
            "path": str(lifecycle_file.relative_to(root.resolve())),
            "sha256": hashlib.sha256(lifecycle_raw).hexdigest(),
            "bytes": len(lifecycle_raw),
            "schema": lifecycle.get("schema"),
        },
        "evidence": {
            "good_update": {
                **good_meta,
                "required_markers": list(good_required),
                "missing_markers": missing_good,
                "outcome": "committed_and_healthy" if not missing_good else "unproven",
            },
            "bad_update": {
                **bad_meta,
                "outcome": bad_outcome,
                "attempted_version": bad.get("attempted_version"),
            },
            "transaction_journal": {
                "path": "update-transaction.json",
                "absent": not journal.exists(),
            },
        },
        "summary": {
            "errors": errors,
            "good_update_chain_complete": not missing_good,
            "bad_update_outcome": bad_outcome,
        },
        "gate": {
            "passed": not errors,
            "updater_chain_complete": not errors,
            "production_activation": False,
        },
    }
    return report, 0 if not errors else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lifecycle-report", type=Path, default=DEFAULT_LIFECYCLE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    try:
        candidate = _load_candidate_identity(ROOT)
        report, exit_code = evaluate(
            ROOT,
            args.lifecycle_report,
            candidate=candidate,
            now=now,
        )
    except Exception as exc:
        report = {
            "schema": SCHEMA,
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "error": {
                "type": type(exc).__name__,
                "message": str(exc).replace("\r", " ").replace("\n", " ")[:500],
            },
            "summary": {"errors": [str(exc)[:500]]},
            "gate": {
                "passed": False,
                "updater_chain_complete": False,
                "production_activation": False,
            },
        }
        exit_code = 2
    destination = _resolve_under(ROOT, args.report)
    try:
        destination.relative_to((ROOT / "validation").resolve())
    except ValueError:
        parser.error("--report must remain under validation/")
    _write_json_atomic(destination, report)
    print(f"report: {destination.relative_to(ROOT)}")
    print("gate: " + ("PASS" if report.get("gate", {}).get("passed") else "BLOCKED"))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
