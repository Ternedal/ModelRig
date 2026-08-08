#!/usr/bin/env python3
"""Fail-closed gate for source, bootstrap and interruption Stage B evidence."""
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
SCHEMA = "kaliv-stage-b-strict-evidence/v1"
LIFECYCLE_SCHEMA = "kaliv-appliance-lifecycle-observations/v1"
EXPECTED_SOURCE_VERSION = "1.58.150"
EXPECTED_TARGET_VERSION = "1.58.151"
UPDATER_ASSET = "modelrig-updater-windows-x64.exe"
DEFAULT_LIFECYCLE = Path("validation/appliance-lifecycle-observations.json")
DEFAULT_REPORT = Path("validation/stage-b-strict-evidence-latest.json")
MAX_BYTES = 32 * 1024 * 1024
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")


class StrictEvidenceError(RuntimeError):
    pass


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=path.name + ".",
        suffix=".tmp", delete=False,
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(path)


def _resolve_under(root: Path, raw: Path) -> Path:
    candidate = raw if raw.is_absolute() else root / raw
    if candidate.is_symlink():
        raise StrictEvidenceError(f"path is a symlink: {raw}")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise StrictEvidenceError(f"path escapes repository: {raw}") from exc
    return resolved


def _load_json(root: Path, raw: Path) -> tuple[dict[str, Any], bytes, Path]:
    path = _resolve_under(root, raw)
    if not path.is_file() or path.is_symlink():
        raise StrictEvidenceError(f"JSON evidence is missing or irregular: {raw}")
    body = path.read_bytes()
    if not body or len(body) > MAX_BYTES:
        raise StrictEvidenceError(f"JSON evidence size is invalid: {raw}")
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StrictEvidenceError(f"JSON evidence is invalid: {raw}") from exc
    if not isinstance(value, dict):
        raise StrictEvidenceError(f"JSON evidence must be an object: {raw}")
    return value, body, path


def _candidate_identity(root: Path) -> dict[str, Any]:
    path = root / "scripts" / "physical_validation_campaign.py"
    spec = importlib.util.spec_from_file_location("strict_stage_b_candidate", path)
    if spec is None or spec.loader is None:
        raise StrictEvidenceError("candidate identity module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    value = module.candidate_identity(root)
    if not isinstance(value, dict):
        raise StrictEvidenceError("candidate identity is invalid")
    return value


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


def _load_log(root: Path, label: str, trial: Mapping[str, Any], errors: list[str]) -> tuple[dict[str, Any], str]:
    raw = trial.get("evidence_path")
    digest = trial.get("evidence_sha256")
    if not isinstance(raw, str) or not raw:
        errors.append(f"{label}.evidence_path is missing")
        return {}, ""
    p = Path(raw)
    if p.is_absolute() or ".." in p.parts:
        errors.append(f"{label}.evidence_path must be repository-relative")
        return {}, ""
    try:
        path = _resolve_under(root, p)
        rel = path.relative_to(root.resolve())
    except (StrictEvidenceError, ValueError) as exc:
        errors.append(f"{label}.evidence_path is invalid: {exc}")
        return {}, ""
    if rel.parts[:2] != ("validation", "appliance-lifecycle-evidence"):
        errors.append(f"{label}.evidence_path is outside the lifecycle evidence directory")
        return {}, ""
    if not path.is_file() or path.is_symlink():
        errors.append(f"{label} evidence log is missing or irregular")
        return {}, ""
    body = path.read_bytes()
    if not body or len(body) > MAX_BYTES:
        errors.append(f"{label} evidence log size is invalid")
        return {}, ""
    actual = hashlib.sha256(body).hexdigest()
    if not isinstance(digest, str) or _SHA64.fullmatch(digest) is None:
        errors.append(f"{label}.evidence_sha256 is invalid")
    elif digest != actual:
        errors.append(f"{label}.evidence_sha256 does not match its log")
    try:
        text = body.decode("utf-8").lower()
    except UnicodeDecodeError:
        errors.append(f"{label} evidence log is not UTF-8")
        text = ""
    return {"path": str(rel), "sha256": actual, "bytes": len(body)}, text


def _require_markers(label: str, text: str, markers: tuple[str, ...], errors: list[str]) -> list[str]:
    missing = [marker for marker in markers if marker.lower() not in text]
    errors.extend(f"{label} log is missing required marker: {marker}" for marker in missing)
    return missing


def evaluate(root: Path, lifecycle_path: Path, *, candidate: Mapping[str, Any], now: datetime) -> tuple[dict[str, Any], int]:
    errors: list[str] = []
    lifecycle, raw, path = _load_json(root, lifecycle_path)
    if lifecycle.get("schema") != LIFECYCLE_SCHEMA:
        errors.append("lifecycle schema mismatch")

    version = str(candidate.get("version") or "")
    if version != EXPECTED_TARGET_VERSION:
        errors.append(f"candidate version must be {EXPECTED_TARGET_VERSION}")
    if _SHA40.fullmatch(str(candidate.get("git_sha") or "")) is None:
        errors.append("candidate Git SHA is invalid")
    lifecycle_candidate = lifecycle.get("candidate")
    if not isinstance(lifecycle_candidate, Mapping):
        errors.append("lifecycle candidate identity is missing")
    else:
        for key in ("version", "git_sha", "code_sha256"):
            if lifecycle_candidate.get(key) != candidate.get(key):
                errors.append(f"lifecycle candidate.{key} mismatch")

    good = _trial(lifecycle, "good_update", errors)
    if good.get("source_version") != EXPECTED_SOURCE_VERSION:
        errors.append(f"good_update.source_version must be {EXPECTED_SOURCE_VERSION}")
    if good.get("target_version") != EXPECTED_TARGET_VERSION:
        errors.append(f"good_update.target_version must be {EXPECTED_TARGET_VERSION}")

    bootstrap = _trial(lifecycle, "updater_bootstrap", errors)
    bootstrap_meta, bootstrap_text = _load_log(root, "updater_bootstrap", bootstrap, errors)
    expected_hash = str(bootstrap.get("expected_sha256") or "")
    actual_hash = str(bootstrap.get("actual_sha256") or "")
    if bootstrap.get("performed") is not True:
        errors.append("updater_bootstrap.performed is not true")
    if bootstrap.get("release_version") != EXPECTED_TARGET_VERSION:
        errors.append("updater_bootstrap.release_version mismatch")
    if bootstrap.get("release_git_sha") != candidate.get("git_sha"):
        errors.append("updater_bootstrap.release_git_sha mismatch")
    if bootstrap.get("asset_name") != UPDATER_ASSET:
        errors.append("updater_bootstrap.asset_name mismatch")
    if _SHA64.fullmatch(expected_hash) is None or expected_hash != actual_hash:
        errors.append("updater_bootstrap expected and actual hashes do not match")
    if bootstrap.get("provenance_verified") is not True:
        errors.append("updater_bootstrap provenance was not verified")
    bootstrap_missing = _require_markers(
        "updater_bootstrap",
        bootstrap_text,
        (
            f"release_version={EXPECTED_TARGET_VERSION}",
            f"asset_name={UPDATER_ASSET}",
            f"expected_sha256={expected_hash}",
            f"actual_sha256={actual_hash}",
            "provenance_verified=true",
        ),
        errors,
    )

    interruption = _trial(lifecycle, "appliance_interruption", errors)
    interruption_meta, interruption_text = _load_log(
        root, "appliance_interruption", interruption, errors
    )
    if interruption.get("performed") is not True:
        errors.append("appliance_interruption.performed is not true")
    if interruption.get("source_version") != EXPECTED_SOURCE_VERSION:
        errors.append("appliance_interruption.source_version mismatch")
    if interruption.get("observed_journal_state") != "swapping":
        errors.append("appliance_interruption did not observe journal state swapping")
    swapped_count = interruption.get("observed_swapped_count")
    if not isinstance(swapped_count, int) or isinstance(swapped_count, bool) or swapped_count < 1:
        errors.append("appliance_interruption did not observe a completed live swap")
    for key in (
        "updater_process_killed",
        "recovery_succeeded",
        "live_executables_present",
        "journal_absent",
        "ready",
    ):
        if interruption.get(key) is not True:
            errors.append(f"appliance_interruption.{key} is not true")
    if interruption.get("recovery_exit_code") != 0:
        errors.append("appliance_interruption recovery exit code is not zero")
    if interruption.get("backend_version") != EXPECTED_SOURCE_VERSION:
        errors.append("appliance_interruption backend did not recover to source")
    if interruption.get("worker_version") != EXPECTED_SOURCE_VERSION:
        errors.append("appliance_interruption worker did not recover to source")
    interruption_missing = _require_markers(
        "appliance_interruption",
        interruption_text,
        (
            "observed_journal_state=swapping",
            "observed_swapped_count=",
            "updater_process_killed=true",
            "recovery_exit_code=0",
            "recovery_succeeded=true",
            "live_executables_present=true",
            "journal_absent=true",
        ),
        errors,
    )

    if bootstrap_meta and interruption_meta and bootstrap_meta.get("path") == interruption_meta.get("path"):
        errors.append("bootstrap and interruption evidence must use different logs")

    report = {
        "schema": SCHEMA,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "candidate": dict(candidate),
        "source": {
            "path": str(path.relative_to(root.resolve())),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "schema": lifecycle.get("schema"),
        },
        "evidence": {
            "updater_bootstrap": {**bootstrap_meta, "missing_markers": bootstrap_missing},
            "appliance_interruption": {**interruption_meta, "missing_markers": interruption_missing},
        },
        "summary": {
            "errors": errors,
            "expected_source_version": EXPECTED_SOURCE_VERSION,
            "expected_target_version": EXPECTED_TARGET_VERSION,
        },
        "gate": {
            "passed": not errors,
            "strict_evidence_complete": not errors,
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
        candidate = _candidate_identity(ROOT)
        report, code = evaluate(ROOT, args.lifecycle_report, candidate=candidate, now=now)
    except Exception as exc:
        report = {
            "schema": SCHEMA,
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "summary": {"errors": [str(exc)[:500]]},
            "gate": {"passed": False, "strict_evidence_complete": False, "production_activation": False},
        }
        code = 2
    destination = _resolve_under(ROOT, args.report)
    try:
        destination.relative_to((ROOT / "validation").resolve())
    except ValueError:
        parser.error("--report must remain under validation/")
    _write_json_atomic(destination, report)
    print(f"report: {destination.relative_to(ROOT)}")
    print("gate: " + ("PASS" if report.get("gate", {}).get("passed") else "BLOCKED"))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
