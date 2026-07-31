#!/usr/bin/env python3
"""Shared exact schemas and candidate binding for the T-022 write pilot."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import secrets
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_SCHEMA = "kaliv-agent3-write-pilot-manifest/v1"
NEGATIVE_SCHEMA = "kaliv-agent3-write-pilot-negative/v1"
REPORT_SCHEMA = "kaliv-agent3-write-pilot/v1"
RUN_COUNT = 20
PILOT_WINDOW_MAX_HOURS = 12.0
REPORT_MAX_AGE_HOURS = 24.0
MAX_JSON_BYTES = 2_000_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_REQUIRED_EVENTS = (
    "run_created", "policy_decision", "confirmation_required",
    "approval_consumed", "confirmation_approved", "policy_decision",
    "step_started", "step_succeeded", "run_completed",
)
_NEGATIVE_CASES = (
    "deny", "timeout", "changed_args", "stale_revision", "replay",
    "concurrent_approval", "stop_retry_replan",
)


class PilotEvidenceError(RuntimeError):
    pass

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _load_json(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink():
        raise PilotEvidenceError(f"symlink is not accepted as evidence: {path}")
    if not path.is_file():
        raise PilotEvidenceError(f"evidence file not found: {path}")
    size = path.stat().st_size
    if size <= 0 or size > MAX_JSON_BYTES:
        raise PilotEvidenceError(f"evidence size is invalid: {path} ({size} bytes)")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PilotEvidenceError(f"evidence is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PilotEvidenceError(f"evidence must be a JSON object: {path}")
    return value, raw


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PilotEvidenceError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def candidate_identity(root: Path = ROOT) -> dict[str, Any]:
    campaign = _load_module(
        root / "scripts" / "physical_validation_campaign.py",
        "t022_candidate_identity",
    )
    try:
        identity = campaign.candidate_identity(root)
    except Exception as exc:
        raise PilotEvidenceError(f"candidate identity cannot be established: {exc}") from exc
    if not isinstance(identity, dict):
        raise PilotEvidenceError("candidate identity is not an object")
    if not _GIT_SHA.fullmatch(str(identity.get("git_sha") or "")):
        raise PilotEvidenceError("candidate identity has no exact git SHA")
    if not _SHA256.fullmatch(str(identity.get("code_sha256") or "")):
        raise PilotEvidenceError("candidate identity has no worker code fingerprint")
    if identity.get("version_stamps_consistent") is not True:
        raise PilotEvidenceError("candidate version stamps are inconsistent")
    if identity.get("identity_source") == "git" and identity.get("working_tree_clean") is not True:
        raise PilotEvidenceError("candidate working tree is not clean")
    return identity


def assess_rig_validation(
    path: Path,
    identity: dict[str, Any],
    *,
    now: float | None = None,
) -> tuple[dict[str, Any], str]:
    report, raw = _load_json(path)
    sys.path.insert(0, str(ROOT / "worker"))
    from app.agent3.validation_gate import assess_report  # noqa: PLC0415

    digest = _sha_bytes(raw)
    assessment = assess_report(
        report,
        current_version=str(identity.get("version") or ""),
        current_code=str(identity.get("code_sha256") or ""),
        report_sha256=digest,
        now=now,
    )
    if assessment.get("eligible_for_write_pilot") is not True:
        reasons = assessment.get("write_pilot_reasons") or assessment.get("reasons") or []
        raise PilotEvidenceError(
            "rig validation is not eligible for the write pilot: " + ", ".join(map(str, reasons))
        )
    return assessment, digest


def _exact_keys(value: dict[str, Any], expected: set[str], label: str, errors: list[str]) -> None:
    actual = set(value)
    if actual != expected:
        errors.append(
            f"{label} keys mismatch: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def validate_manifest(manifest: Any, *, require_bound: bool = True) -> list[str]:
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest must be an object"]
    _exact_keys(
        manifest,
        {"schema", "pilot_id", "created_at", "operator", "target", "marker_prefix", "runs"},
        "manifest",
        errors,
    )
    if manifest.get("schema") != MANIFEST_SCHEMA:
        errors.append("manifest schema mismatch")
    pilot_id = manifest.get("pilot_id")
    if not isinstance(pilot_id, str) or not re.fullmatch(r"[0-9a-f]{32}", pilot_id):
        errors.append("manifest pilot_id is invalid")
    if _parse_time(manifest.get("created_at")) is None:
        errors.append("manifest created_at is invalid")
    if not isinstance(manifest.get("operator"), str) or not manifest["operator"].strip():
        errors.append("manifest operator is missing")
    prefix = manifest.get("marker_prefix")
    if not isinstance(prefix, str) or prefix != f"KALIV-T022:{pilot_id}:P:":
        errors.append("manifest marker_prefix is not bound to pilot_id")

    target = manifest.get("target")
    if not isinstance(target, dict):
        errors.append("manifest target must be an object")
    else:
        _exact_keys(
            target,
            {"version", "git_sha", "code_sha256", "identity_source", "rig_validation_report_sha256"},
            "manifest target",
            errors,
        )
        if not isinstance(target.get("version"), str) or not target["version"].strip():
            errors.append("manifest target version is invalid")
        if not _GIT_SHA.fullmatch(str(target.get("git_sha") or "")):
            errors.append("manifest target git_sha is invalid")
        for name in ("code_sha256", "rig_validation_report_sha256"):
            if not _SHA256.fullmatch(str(target.get(name) or "")):
                errors.append(f"manifest target {name} is invalid")
        if target.get("identity_source") not in {"git", "frozen-candidate-attestation"}:
            errors.append("manifest target identity_source is invalid")

    runs = manifest.get("runs")
    if not isinstance(runs, list) or len(runs) != RUN_COUNT:
        errors.append(f"manifest must contain exactly {RUN_COUNT} runs")
        return errors
    markers: list[str] = []
    run_ids: list[str] = []
    for index, item in enumerate(runs, start=1):
        label = f"manifest run {index}"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        _exact_keys(item, {"ordinal", "marker", "run_id", "bound_at"}, label, errors)
        if item.get("ordinal") != index:
            errors.append(f"{label} ordinal mismatch")
        marker = item.get("marker")
        expected_start = f"{prefix}{index:02d}:" if isinstance(prefix, str) else ""
        if not isinstance(marker, str) or not marker.startswith(expected_start) or len(marker) != len(expected_start) + 32:
            errors.append(f"{label} marker is invalid")
        else:
            markers.append(marker)
        run_id = item.get("run_id")
        bound_at = item.get("bound_at")
        if run_id is None:
            if require_bound:
                errors.append(f"{label} is not bound to a run id")
            if bound_at is not None:
                errors.append(f"{label} has bound_at without run_id")
        else:
            if not isinstance(run_id, str) or not _OPAQUE_ID.fullmatch(run_id):
                errors.append(f"{label} run_id is invalid")
            else:
                run_ids.append(run_id)
            if _parse_time(bound_at) is None:
                errors.append(f"{label} bound_at is invalid")
    if len(markers) != len(set(markers)):
        errors.append("manifest markers are not unique")
    if len(run_ids) != len(set(run_ids)):
        errors.append("manifest run ids are not unique")
    return errors


def prepare_manifest(
    *,
    operator: str,
    rig_validation_path: Path,
    now: datetime | None = None,
    identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(operator, str) or not operator.strip():
        raise PilotEvidenceError("operator must be a non-empty name")
    current = identity or candidate_identity()
    _assessment, validation_sha = assess_rig_validation(
        rig_validation_path, current, now=(now or _utc_now()).timestamp()
    )
    pilot_id = uuid.uuid4().hex
    prefix = f"KALIV-T022:{pilot_id}:P:"
    created = now or _utc_now()
    return {
        "schema": MANIFEST_SCHEMA,
        "pilot_id": pilot_id,
        "created_at": _iso(created),
        "operator": operator.strip(),
        "target": {
            "version": current["version"],
            "git_sha": current["git_sha"],
            "code_sha256": current["code_sha256"],
            "identity_source": current["identity_source"],
            "rig_validation_report_sha256": validation_sha,
        },
        "marker_prefix": prefix,
        "runs": [
            {
                "ordinal": ordinal,
                "marker": f"{prefix}{ordinal:02d}:{secrets.token_hex(16)}",
                "run_id": None,
                "bound_at": None,
            }
            for ordinal in range(1, RUN_COUNT + 1)
        ],
    }


def bind_run(manifest: dict[str, Any], ordinal: int, run_id: str, *, now: datetime | None = None) -> None:
    errors = validate_manifest(manifest, require_bound=False)
    if errors:
        raise PilotEvidenceError("manifest is invalid: " + "; ".join(errors))
    if ordinal < 1 or ordinal > RUN_COUNT:
        raise PilotEvidenceError(f"ordinal must be between 1 and {RUN_COUNT}")
    if not _OPAQUE_ID.fullmatch(run_id):
        raise PilotEvidenceError("run id is invalid")
    existing = {item.get("run_id") for item in manifest["runs"] if item.get("run_id")}
    target = manifest["runs"][ordinal - 1]
    if target.get("run_id") is not None:
        raise PilotEvidenceError(f"ordinal {ordinal} is already bound")
    if run_id in existing:
        raise PilotEvidenceError("run id is already bound to another marker")
    target["run_id"] = run_id
    target["bound_at"] = _iso(now or _utc_now())


def validate_negative_evidence(value: Any, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["negative evidence must be an object"]
    _exact_keys(value, {"schema", "pilot_id", "generated_at", "cases"}, "negative evidence", errors)
    if value.get("schema") != NEGATIVE_SCHEMA:
        errors.append("negative evidence schema mismatch")
    if value.get("pilot_id") != manifest.get("pilot_id"):
        errors.append("negative evidence pilot_id mismatch")
    if _parse_time(value.get("generated_at")) is None:
        errors.append("negative evidence generated_at is invalid")
    cases = value.get("cases")
    if not isinstance(cases, list):
        errors.append("negative evidence cases must be an array")
        return errors
    by_name: dict[str, dict[str, Any]] = {}
    expected_keys = {
        "name",
        "observed_at",
        "marker",
        "request_statuses",
        "response_sha256s",
        "note_count_before",
        "note_count_after",
        "approval_use_count_before",
        "approval_use_count_after",
        "run_ids",
    }
    for index, case in enumerate(cases):
        label = f"negative case {index + 1}"
        if not isinstance(case, dict):
            errors.append(f"{label} must be an object")
            continue
        _exact_keys(case, expected_keys, label, errors)
        name = case.get("name")
        if name not in _NEGATIVE_CASES:
            errors.append(f"{label} has unknown name")
            continue
        if name in by_name:
            errors.append(f"negative case {name} is duplicated")
        by_name[name] = case
        if _parse_time(case.get("observed_at")) is None:
            errors.append(f"negative case {name} observed_at is invalid")
        if not isinstance(case.get("marker"), str) or not case["marker"].strip():
            errors.append(f"negative case {name} marker is invalid")
        statuses = case.get("request_statuses")
        hashes = case.get("response_sha256s")
        if not isinstance(statuses, list) or not statuses or any(
            isinstance(item, bool) or not isinstance(item, int) for item in statuses
        ):
            errors.append(f"negative case {name} request_statuses are invalid")
            statuses = []
        if not isinstance(hashes, list) or len(hashes) != len(statuses) or any(
            not _SHA256.fullmatch(str(item or "")) for item in hashes
        ):
            errors.append(f"negative case {name} response hashes are invalid")
        for field in (
            "note_count_before",
            "note_count_after",
            "approval_use_count_before",
            "approval_use_count_after",
        ):
            if isinstance(case.get(field), bool) or not isinstance(case.get(field), int) or case[field] < 0:
                errors.append(f"negative case {name} {field} is invalid")
        run_ids = case.get("run_ids")
        if not isinstance(run_ids, list) or not run_ids or any(
            not isinstance(item, str) or not _OPAQUE_ID.fullmatch(item) for item in run_ids
        ):
            errors.append(f"negative case {name} run_ids are invalid")

    missing = set(_NEGATIVE_CASES) - set(by_name)
    extra = set(by_name) - set(_NEGATIVE_CASES)
    if missing:
        errors.append("negative cases are missing: " + ", ".join(sorted(missing)))
    if extra:
        errors.append("negative cases are unsupported: " + ", ".join(sorted(extra)))

    positive_markers = {item["marker"] for item in manifest.get("runs", []) if isinstance(item, dict)}
    rules = {
        "deny": ([200], 0, 0),
        "timeout": ([409], 0, 0),
        "changed_args": ([409], 0, 0),
        "stale_revision": ([409], 0, 0),
        "replay": ([409], 0, 0),
    }
    for name, (statuses, note_delta, approval_delta) in rules.items():
        case = by_name.get(name)
        if not case:
            continue
        if case.get("request_statuses") != statuses:
            errors.append(f"negative case {name} status contract failed")
        if case.get("note_count_after", 0) - case.get("note_count_before", 0) != note_delta:
            errors.append(f"negative case {name} changed the note")
        if case.get("approval_use_count_after", 0) - case.get("approval_use_count_before", 0) != approval_delta:
            errors.append(f"negative case {name} consumed an approval")

    concurrent = by_name.get("concurrent_approval")
    if concurrent:
        if sorted(concurrent.get("request_statuses") or []) != [200, 409]:
            errors.append("concurrent approval must produce exactly one success and one conflict")
        if concurrent.get("note_count_after", 0) - concurrent.get("note_count_before", 0) != 1:
            errors.append("concurrent approval did not produce exactly one append")
        if concurrent.get("approval_use_count_after", 0) - concurrent.get("approval_use_count_before", 0) != 1:
            errors.append("concurrent approval did not consume exactly one approval")

    stop = by_name.get("stop_retry_replan")
    if stop:
        statuses = stop.get("request_statuses") or []
        if len(statuses) < 3 or any(code not in {200, 202, 409} for code in statuses):
            errors.append("stop/retry/replan evidence has an invalid request sequence")
        if stop.get("note_count_after") != stop.get("note_count_before"):
            errors.append("stop/retry/replan duplicated the append")
        if stop.get("approval_use_count_after") != stop.get("approval_use_count_before"):
            errors.append("stop/retry/replan consumed another approval")
        if stop.get("marker") not in positive_markers:
            errors.append("stop/retry/replan must target one of the 20 positive markers")
    return errors
