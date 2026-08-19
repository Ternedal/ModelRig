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
# The released predecessor of the target. See stage_b_one_click_v2 for the full
# reason: 1.58.150 was bumped but never published -- no release, tag or draft
# exists -- so a source appliance could never be installed from it.
EXPECTED_SOURCE_VERSION = "2.0.10"
EXPECTED_TARGET_VERSION = "2.0.11"
UPDATER_ASSET = "modelrig-updater-windows-x64.exe"
EXPECTED_SOURCE_REF = f"refs/tags/v{EXPECTED_TARGET_VERSION}"
EXPECTED_SIGNER_WORKFLOW = "Ternedal/ModelRig/.github/workflows/build-and-release.yml"
DEFAULT_LIFECYCLE = Path("validation/appliance-lifecycle-observations.json")
DEFAULT_STATE = Path("validation/stage-b-easy-state.json")
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
        raise StrictEvidenceError(f"path is a symlink: {raw}")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise StrictEvidenceError(f"path escapes repository: {raw}") from exc
    return resolved


def _reject_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise StrictEvidenceError(
                f"JSON evidence contains duplicate key: {key}"
            )
        value[key] = item
    return value


def _load_json(root: Path, raw: Path) -> tuple[dict[str, Any], bytes, Path]:
    path = _resolve_under(root, raw)
    if not path.is_file() or path.is_symlink():
        raise StrictEvidenceError(f"JSON evidence is missing or irregular: {raw}")
    body = path.read_bytes()
    if not body or len(body) > MAX_BYTES:
        raise StrictEvidenceError(f"JSON evidence size is invalid: {raw}")
    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_object,
        )
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


def _trial(
    report: Mapping[str, Any],
    name: str,
    errors: list[str],
) -> dict[str, Any]:
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
        errors.append(
            f"{label}.evidence_path is outside the lifecycle evidence directory"
        )
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


def _require_markers(
    label: str,
    text: str,
    markers: tuple[str, ...],
    errors: list[str],
) -> list[str]:
    # Every required key is authority-bearing. Exact-line membership alone is
    # insufficient because a self-hashed log could include both the expected
    # value and a contradictory duplicate. Require each key exactly once.
    lines = [
        line.strip().lower()
        for line in text.splitlines()
        if line.strip()
    ]
    missing: list[str] = []
    for marker in markers:
        expected = marker.strip().lower()
        if "=" in expected:
            key = expected.split("=", 1)[0]
            matches = [
                line
                for line in lines
                if "=" in line and line.split("=", 1)[0] == key
            ]
        else:
            matches = [line for line in lines if line == expected]
        if len(matches) != 1:
            errors.append(
                f"{label} log must contain exactly one required marker key: "
                f"{marker} (found {len(matches)})"
            )
            missing.append(marker)
        elif matches[0] != expected:
            errors.append(
                f"{label} log marker value does not match: {marker}"
            )
            missing.append(marker)
    return missing

def evaluate(
    root: Path,
    lifecycle_path: Path,
    *,
    candidate: Mapping[str, Any],
    now: datetime,
) -> tuple[dict[str, Any], int]:
    errors: list[str] = []
    lifecycle, raw, path = _load_json(root, lifecycle_path)
    if lifecycle.get("schema") != LIFECYCLE_SCHEMA:
        errors.append("lifecycle schema mismatch")

    state_raw = b""
    state_path = _resolve_under(root, DEFAULT_STATE)
    bootstrap_state: dict[str, Any] = {}
    try:
        bootstrap_state, state_raw, state_path = _load_json(root, DEFAULT_STATE)
    except StrictEvidenceError as exc:
        errors.append(f"bootstrap checkpoint is invalid: {exc}")
    else:
        if bootstrap_state.get("updater_bootstrap_done") is not True:
            errors.append("bootstrap checkpoint is not complete")

    version = str(candidate.get("version") or "")
    candidate_sha = str(candidate.get("git_sha") or "")
    if version != EXPECTED_TARGET_VERSION:
        errors.append(f"candidate version must be {EXPECTED_TARGET_VERSION}")
    if _SHA40.fullmatch(candidate_sha) is None:
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
        errors.append(
            f"good_update.source_version must be {EXPECTED_SOURCE_VERSION}"
        )
    source_git_sha = str(good.get("source_git_sha") or "")
    if _SHA40.fullmatch(source_git_sha) is None:
        errors.append("good_update.source_git_sha is invalid")
    if good.get("target_version") != EXPECTED_TARGET_VERSION:
        errors.append(
            f"good_update.target_version must be {EXPECTED_TARGET_VERSION}"
        )
    if good.get("target_git_sha") != candidate_sha:
        errors.append("good_update.target_git_sha mismatch")

    bootstrap = _trial(lifecycle, "updater_bootstrap", errors)
    bootstrap_meta, bootstrap_text = _load_log(
        root,
        "updater_bootstrap",
        bootstrap,
        errors,
    )
    expected_hash = str(bootstrap.get("expected_sha256") or "")
    actual_hash = str(bootstrap.get("actual_sha256") or "")
    source_digest = str(bootstrap.get("source_digest") or "")
    source_ref = str(bootstrap.get("source_ref") or "")
    signer_workflow = str(bootstrap.get("signer_workflow") or "")
    if bootstrap.get("performed") is not True:
        errors.append("updater_bootstrap.performed is not true")
    if bootstrap.get("release_version") != EXPECTED_TARGET_VERSION:
        errors.append("updater_bootstrap.release_version mismatch")
    if bootstrap.get("release_git_sha") != candidate_sha:
        errors.append("updater_bootstrap.release_git_sha mismatch")
    if bootstrap.get("asset_name") != UPDATER_ASSET:
        errors.append("updater_bootstrap.asset_name mismatch")
    if _SHA64.fullmatch(expected_hash) is None or expected_hash != actual_hash:
        errors.append(
            "updater_bootstrap expected and actual hashes do not match"
        )
    if source_digest != candidate_sha:
        errors.append("updater_bootstrap.source_digest mismatch")
    if source_ref != EXPECTED_SOURCE_REF:
        errors.append("updater_bootstrap.source_ref mismatch")
    if signer_workflow != EXPECTED_SIGNER_WORKFLOW:
        errors.append("updater_bootstrap.signer_workflow mismatch")
    if bootstrap.get("provenance_verified") is not True:
        errors.append("updater_bootstrap provenance was not verified")
    bootstrap_missing = _require_markers(
        "updater_bootstrap",
        bootstrap_text,
        (
            f"release_version={EXPECTED_TARGET_VERSION}",
            f"release_git_sha={candidate_sha}",
            f"asset_name={UPDATER_ASSET}",
            f"expected_sha256={expected_hash}",
            f"actual_sha256={actual_hash}",
            f"source_digest={candidate_sha}",
            f"source_ref={EXPECTED_SOURCE_REF}",
            f"signer_workflow={EXPECTED_SIGNER_WORKFLOW}",
            "provenance_verified=true",
        ),
        errors,
    )

    interruption = _trial(lifecycle, "appliance_interruption", errors)
    interruption_meta, interruption_text = _load_log(
        root,
        "appliance_interruption",
        interruption,
        errors,
    )
    transaction_id = str(
        interruption.get("observed_transaction_id") or ""
    )
    revision = interruption.get("observed_revision")
    process_pid = interruption.get("updater_process_pid")
    journal_from = str(interruption.get("observed_journal_from") or "")
    journal_to = str(interruption.get("observed_journal_to") or "")
    swapped_count = interruption.get("observed_swapped_count")
    swapped_assets = interruption.get("observed_swapped_assets")

    if interruption.get("performed") is not True:
        errors.append("appliance_interruption.performed is not true")
    if interruption.get("source_version") != EXPECTED_SOURCE_VERSION:
        errors.append("appliance_interruption.source_version mismatch")
    if not transaction_id:
        errors.append("appliance_interruption transaction id is missing")
    if (
        not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 1
    ):
        errors.append("appliance_interruption revision is invalid")
    if (
        not isinstance(process_pid, int)
        or isinstance(process_pid, bool)
        or process_pid < 1
    ):
        errors.append(
            "appliance_interruption updater process id is invalid"
        )
    if journal_from != EXPECTED_SOURCE_VERSION:
        errors.append("appliance_interruption journal source mismatch")
    if journal_to.lstrip("v") != EXPECTED_TARGET_VERSION:
        errors.append("appliance_interruption journal target mismatch")
    if interruption.get("observed_journal_state") != "swapping":
        errors.append(
            "appliance_interruption did not observe journal state swapping"
        )
    if (
        not isinstance(swapped_count, int)
        or isinstance(swapped_count, bool)
        or swapped_count < 1
    ):
        errors.append(
            "appliance_interruption did not observe a completed live swap"
        )
    if (
        not isinstance(swapped_assets, list)
        or not swapped_assets
        or not all(
            isinstance(asset, str) and asset
            for asset in swapped_assets
        )
    ):
        errors.append(
            "appliance_interruption swapped asset list is invalid"
        )
        normalized_assets: list[str] = []
    else:
        normalized_assets = list(swapped_assets)
    if (
        isinstance(swapped_count, int)
        and not isinstance(swapped_count, bool)
        and swapped_count != len(normalized_assets)
    ):
        errors.append(
            "appliance_interruption swap count does not match asset list"
        )

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
        errors.append(
            "appliance_interruption recovery exit code is not zero"
        )
    if interruption.get("backend_version") != EXPECTED_SOURCE_VERSION:
        errors.append(
            "appliance_interruption backend did not recover to source"
        )
    if interruption.get("worker_version") != EXPECTED_SOURCE_VERSION:
        errors.append(
            "appliance_interruption worker did not recover to source"
        )

    interruption_missing = _require_markers(
        "appliance_interruption",
        interruption_text,
        (
            f"observed_transaction_id={transaction_id}",
            f"observed_revision={revision}",
            f"observed_journal_from={EXPECTED_SOURCE_VERSION}",
            f"observed_journal_to={journal_to}",
            "observed_journal_state=swapping",
            f"observed_swapped_count={swapped_count}",
            f"observed_swapped_assets={','.join(normalized_assets)}",
            f"updater_process_pid={process_pid}",
            "updater_process_killed=true",
            "recovery_exit_code=0",
            "recovery_succeeded=true",
            "live_executables_present=true",
            "journal_absent=true",
        ),
        errors,
    )

    if (
        bootstrap_meta
        and interruption_meta
        and bootstrap_meta.get("path") == interruption_meta.get("path")
    ):
        errors.append(
            "bootstrap and interruption evidence must use different logs"
        )

    report = {
        "schema": SCHEMA,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "candidate": dict(candidate),
        "source": {
            "path": str(path.relative_to(root.resolve())),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "schema": lifecycle.get("schema"),
            "bootstrap_state": {
                "path": str(state_path.relative_to(root.resolve())),
                "sha256": hashlib.sha256(state_raw).hexdigest() if state_raw else "",
                "bytes": len(state_raw),
                "updater_bootstrap_done": bootstrap_state.get(
                    "updater_bootstrap_done"
                ),
            },
        },
        "evidence": {
            "updater_bootstrap": {
                **bootstrap_meta,
                "missing_markers": bootstrap_missing,
            },
            "appliance_interruption": {
                **interruption_meta,
                "missing_markers": interruption_missing,
            },
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
    parser.add_argument(
        "--lifecycle-report",
        type=Path,
        default=DEFAULT_LIFECYCLE,
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help=(
            "checkout hvis evidens skal vurderes (default: dette repo). "
            "Brug den udcheckede release, naar gaten koeres fra en nyere "
            "worktree."
        ),
    )
    args = parser.parse_args(argv)
    # A candidate is frozen before this gate can be corrected, so the contract
    # a release is judged by is not always the copy shipped inside it. That is
    # not hypothetical: 1.58.151 was frozen while this file still required
    # source 1.58.150 -- a release that was never published -- so the released
    # copy could not judge its own evidence. stage_b_one_click_v2 and the
    # campaign already take --root for exactly this reason.
    #
    # Candidate identity still comes from the checkout under test, never from
    # this repo, so what is measured does not change -- only which contract it
    # is measured against.
    root = (args.root.resolve() if args.root is not None else ROOT)
    now = datetime.now(timezone.utc)
    try:
        candidate = _candidate_identity(root)
        report, code = evaluate(
            root,
            args.lifecycle_report,
            candidate=candidate,
            now=now,
        )
    except Exception as exc:
        report = {
            "schema": SCHEMA,
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "summary": {"errors": [str(exc)[:500]]},
            "gate": {
                "passed": False,
                "strict_evidence_complete": False,
                "production_activation": False,
            },
        }
        code = 2
    destination = _resolve_under(root, args.report)
    try:
        destination.relative_to((root / "validation").resolve())
    except ValueError:
        parser.error("--report must remain under validation/")
    _write_json_atomic(destination, report)
    print(f"report: {destination.relative_to(root)}")
    print(
        "gate: "
        + (
            "PASS"
            if report.get("gate", {}).get("passed")
            else "BLOCKED"
        )
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
