#!/usr/bin/env python3
"""Case lifecycle and compilation for the T-022 append-only journal."""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from agent3_write_pilot_common import (
    NEGATIVE_SCHEMA, _NEGATIVE_CASES, _OPAQUE_ID, _atomic_json, _load_json,
    validate_manifest, validate_negative_evidence,
)
from agent3_write_pilot_journal_store import (
    MAX_RESPONSE_BYTES, RecorderError, _append, _init, _sha_bytes, _state, verify_journal,
    verify_journal_binding,
)

def begin_case(
    *,
    journal: Path,
    manifest_path: Path,
    name: str,
    note_count: int,
    approval_count: int,
    positive_ordinal: int | None = None,
    now: datetime | None = None,
) -> tuple[str, str]:
    if name not in _NEGATIVE_CASES:
        raise RecorderError(f"unsupported case: {name}")
    if min(note_count, approval_count) < 0:
        raise RecorderError("before-counts cannot be negative")
    manifest, raw = _load_json(manifest_path)
    errors = validate_manifest(manifest, require_bound=False)
    if errors:
        raise RecorderError("manifest is invalid: " + "; ".join(errors))
    rows, _final = verify_journal_binding(journal, manifest, raw)
    _meta, cases = _state(rows)
    existing_names = {
        case["begin"]["payload"].get("name")
        for case in cases.values()
        if case["begin"] is not None
    }
    if name in existing_names:
        raise RecorderError(f"case {name} is already started")
    positive_cases = {"replay", "stop_retry_replan"}
    if name in positive_cases:
        if positive_ordinal is None or positive_ordinal < 1 or positive_ordinal > len(manifest["runs"]):
            raise RecorderError(f"{name} requires --positive-ordinal")
        marker = manifest["runs"][positive_ordinal - 1]["marker"]
    else:
        if positive_ordinal is not None:
            raise RecorderError(f"{name} must not use --positive-ordinal")
        marker = f"KALIV-T022:{manifest['pilot_id']}:N:{name}:{secrets.token_hex(16)}"
    case_id = uuid.uuid4().hex
    _append(
        journal,
        kind="case_started",
        case_id=case_id,
        payload={
            "name": name,
            "marker": marker,
            "note_count_before": note_count,
            "approval_use_count_before": approval_count,
        },
        recorded_at=now,
    )
    return case_id, marker


def observe_request(
    *,
    journal: Path,
    case_id: str,
    status: int,
    response_path: Path,
    run_id: str,
    now: datetime | None = None,
) -> str:
    if isinstance(status, bool) or status < 100 or status > 599:
        raise RecorderError("HTTP status must be between 100 and 599")
    if not _OPAQUE_ID.fullmatch(run_id):
        raise RecorderError("run id is invalid")
    if response_path.is_symlink() or not response_path.is_file():
        raise RecorderError(f"response file is not a regular file: {response_path}")
    size = response_path.stat().st_size
    if size < 0 or size > MAX_RESPONSE_BYTES:
        raise RecorderError(f"response body size is invalid: {size}")
    raw = response_path.read_bytes()
    rows, _final = verify_journal(journal)
    _meta, cases = _state(rows)
    case = cases.get(case_id)
    if case is None or case["begin"] is None or case["finish"] is not None:
        raise RecorderError("case is not open")
    return _append(
        journal,
        kind="request_observed",
        case_id=case_id,
        payload={
            "status": status,
            "response_sha256": _sha_bytes(raw),
            "response_bytes": len(raw),
            "run_id": run_id,
        },
        recorded_at=now,
    )


def finish_case(
    *,
    journal: Path,
    case_id: str,
    note_count: int,
    approval_count: int,
    now: datetime | None = None,
) -> str:
    if min(note_count, approval_count) < 0:
        raise RecorderError("after-counts cannot be negative")
    rows, _final = verify_journal(journal)
    _meta, cases = _state(rows)
    case = cases.get(case_id)
    if case is None or case["begin"] is None or not case["observations"] or case["finish"] is not None:
        raise RecorderError("case is not ready to finish")
    return _append(
        journal,
        kind="case_finished",
        case_id=case_id,
        payload={
            "note_count_after": note_count,
            "approval_use_count_after": approval_count,
        },
        recorded_at=now,
    )


def compile_negative(
    rows: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    _meta, cases = _state(rows)
    if any(case["finish"] is None for case in cases.values()):
        raise RecorderError("one or more cases are unfinished")
    compiled = []
    for case_id, case in sorted(
        cases.items(), key=lambda pair: pair[1]["begin"]["seq"]
    ):
        begin = case["begin"]
        finish = case["finish"]
        observations = case["observations"]
        run_ids: list[str] = []
        for observation in observations:
            run_id = observation["payload"]["run_id"]
            if run_id not in run_ids:
                run_ids.append(run_id)
        compiled.append(
            {
                "name": begin["payload"]["name"],
                "observed_at": finish["recorded_at"],
                "marker": begin["payload"]["marker"],
                "request_statuses": [
                    item["payload"]["status"] for item in observations
                ],
                "response_sha256s": [
                    item["payload"]["response_sha256"] for item in observations
                ],
                "note_count_before": begin["payload"]["note_count_before"],
                "note_count_after": finish["payload"]["note_count_after"],
                "approval_use_count_before": begin["payload"][
                    "approval_use_count_before"
                ],
                "approval_use_count_after": finish["payload"][
                    "approval_use_count_after"
                ],
                "run_ids": run_ids,
            }
        )
    negative = {
        "schema": NEGATIVE_SCHEMA,
        "pilot_id": manifest["pilot_id"],
        "generated_at": rows[-1]["recorded_at"],
        "cases": compiled,
    }
    errors = validate_negative_evidence(negative, manifest)
    if errors:
        raise RecorderError(
            "compiled negative evidence is invalid: " + "; ".join(errors)
        )
    positive_markers = {
        item.get("marker")
        for item in manifest.get("runs", [])
        if isinstance(item, dict)
    }
    replay = next(
        (case for case in compiled if case.get("name") == "replay"), None
    )
    if replay is None or replay.get("marker") not in positive_markers:
        raise RecorderError("replay must target one of the 20 positive markers")
    return negative


def finalize(journal: Path, manifest_path: Path) -> dict[str, Any]:
    manifest, raw = _load_json(manifest_path)
    errors = validate_manifest(manifest, require_bound=False)
    if errors:
        raise RecorderError("manifest is invalid: " + "; ".join(errors))
    rows, _final_sha = verify_journal_binding(journal, manifest, raw)
    return compile_negative(rows, manifest)
