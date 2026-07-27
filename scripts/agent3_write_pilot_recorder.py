#!/usr/bin/env python3
"""Append-only operator recorder for the T-022 negative write-pilot cases.

The recorder never sends an HTTP request. It creates a hash-chained SQLite journal
around the operator's real requests: begin captures before-counts, observe hashes
an exact response body and status, finish captures after-counts, and finalize
emits the strict negative evidence JSON consumed by the forensic collector.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from agent3_write_pilot_common import (  # noqa: E402
    NEGATIVE_SCHEMA,
    _NEGATIVE_CASES,
    _OPAQUE_ID,
    _atomic_json,
    _canonical_json,
    _iso,
    _load_json,
    _parse_time,
    _sha_bytes,
    _utc_now,
    validate_manifest,
    validate_negative_evidence,
)

JOURNAL_SCHEMA = "kaliv-agent3-write-pilot-journal/v1"
MAX_RESPONSE_BYTES = 1_048_576
_RECORD_COLUMNS = (
    ("seq", "INTEGER", 0, 1),
    ("recorded_at", "TEXT", 1, 0),
    ("kind", "TEXT", 1, 0),
    ("case_id", "TEXT", 0, 0),
    ("payload", "TEXT", 1, 0),
    ("previous_sha256", "TEXT", 1, 0),
    ("record_sha256", "TEXT", 1, 0),
)


class RecorderError(RuntimeError):
    pass


def _record_hash(
    *,
    seq: int,
    recorded_at: str,
    kind: str,
    case_id: str | None,
    payload: dict[str, Any],
    previous_sha256: str,
) -> str:
    return _sha_bytes(
        _canonical_json(
            {
                "seq": seq,
                "recorded_at": recorded_at,
                "kind": kind,
                "case_id": case_id,
                "payload": payload,
                "previous_sha256": previous_sha256,
            }
        )
    )


def _connect(path: Path, *, create: bool = False, readonly: bool = False) -> sqlite3.Connection:
    if path.is_symlink():
        raise RecorderError(f"journal path is a symlink: {path}")
    if create:
        if path.exists():
            raise RecorderError(f"journal already exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute(
            "CREATE TABLE records("
            "seq INTEGER PRIMARY KEY,"
            "recorded_at TEXT NOT NULL,"
            "kind TEXT NOT NULL,"
            "case_id TEXT,"
            "payload TEXT NOT NULL,"
            "previous_sha256 TEXT NOT NULL,"
            "record_sha256 TEXT NOT NULL UNIQUE)"
        )
        conn.commit()
    elif readonly:
        if not path.is_file():
            raise RecorderError(f"journal not found: {path}")
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        if not path.is_file():
            raise RecorderError(f"journal not found: {path}")
        conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    _verify_schema(conn)
    return conn


def _verify_schema(conn: sqlite3.Connection) -> None:
    tables = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()]
    if tables != ["records"]:
        raise RecorderError(f"journal schema has unexpected tables: {tables}")
    info = conn.execute("PRAGMA table_info(records)").fetchall()
    actual = tuple((row[1], row[2].upper(), row[3], row[5]) for row in info)
    if actual != _RECORD_COLUMNS:
        raise RecorderError("journal record schema mismatch")
    forbidden = conn.execute(
        "SELECT type,name FROM sqlite_master WHERE type IN ('trigger','view') ORDER BY type,name"
    ).fetchall()
    if forbidden:
        raise RecorderError("journal contains triggers or views")


def _rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    previous = "0" * 64
    expected_seq = 1
    for row in conn.execute(
        "SELECT seq,recorded_at,kind,case_id,payload,previous_sha256,record_sha256 "
        "FROM records ORDER BY seq"
    ).fetchall():
        if row["seq"] != expected_seq:
            raise RecorderError("journal sequence has a gap or reorder")
        if row["previous_sha256"] != previous:
            raise RecorderError("journal hash chain is broken")
        try:
            payload = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise RecorderError("journal payload is invalid JSON") from exc
        if not isinstance(payload, dict):
            raise RecorderError("journal payload is not an object")
        if _parse_time(row["recorded_at"]) is None:
            raise RecorderError("journal timestamp is invalid")
        digest = _record_hash(
            seq=row["seq"],
            recorded_at=row["recorded_at"],
            kind=row["kind"],
            case_id=row["case_id"],
            payload=payload,
            previous_sha256=row["previous_sha256"],
        )
        if digest != row["record_sha256"]:
            raise RecorderError("journal record hash mismatch")
        result.append(
            {
                "seq": row["seq"],
                "recorded_at": row["recorded_at"],
                "kind": row["kind"],
                "case_id": row["case_id"],
                "payload": payload,
                "previous_sha256": row["previous_sha256"],
                "record_sha256": row["record_sha256"],
            }
        )
        previous = digest
        expected_seq += 1
    if not result:
        raise RecorderError("journal is empty")
    return result


def verify_journal(path: Path) -> tuple[list[dict[str, Any]], str]:
    conn = _connect(path, readonly=True)
    try:
        rows = _rows(conn)
    finally:
        conn.close()
    return rows, rows[-1]["record_sha256"]


def verify_journal_binding(
    journal: Path,
    manifest: dict[str, Any],
    manifest_raw: bytes,
) -> tuple[list[dict[str, Any]], str]:
    rows, final_sha = verify_journal(journal)
    meta, _cases = _state(rows)
    if (
        meta.get("pilot_id") != manifest.get("pilot_id")
        or meta.get("manifest_sha256") != _sha_bytes(manifest_raw)
    ):
        raise RecorderError("journal is bound to another manifest")
    return rows, final_sha


def _append(
    path: Path,
    *,
    kind: str,
    case_id: str | None,
    payload: dict[str, Any],
    recorded_at: datetime | None = None,
) -> str:
    conn = _connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        rows = _rows(conn)
        last = rows[-1]
        seq = last["seq"] + 1
        stamp = _iso(recorded_at or _utc_now())
        previous = last["record_sha256"]
        digest = _record_hash(
            seq=seq,
            recorded_at=stamp,
            kind=kind,
            case_id=case_id,
            payload=payload,
            previous_sha256=previous,
        )
        conn.execute(
            "INSERT INTO records(seq,recorded_at,kind,case_id,payload,previous_sha256,record_sha256) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                seq,
                stamp,
                kind,
                case_id,
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                previous,
                digest,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return digest


def _init(path: Path, manifest_path: Path, *, now: datetime | None = None) -> None:
    manifest, raw = _load_json(manifest_path)
    errors = validate_manifest(manifest, require_bound=False)
    if errors:
        raise RecorderError("manifest is invalid: " + "; ".join(errors))
    conn = _connect(path, create=True)
    try:
        stamp = _iso(now or _utc_now())
        payload = {
            "schema": JOURNAL_SCHEMA,
            "pilot_id": manifest["pilot_id"],
            "manifest_sha256": _sha_bytes(raw),
        }
        digest = _record_hash(
            seq=1,
            recorded_at=stamp,
            kind="journal_initialized",
            case_id=None,
            payload=payload,
            previous_sha256="0" * 64,
        )
        conn.execute(
            "INSERT INTO records VALUES(?,?,?,?,?,?,?)",
            (
                1,
                stamp,
                "journal_initialized",
                None,
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                "0" * 64,
                digest,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _state(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    init = rows[0]
    if init["kind"] != "journal_initialized" or init["case_id"] is not None:
        raise RecorderError("journal does not begin with initialization")
    meta = init["payload"]
    if meta.get("schema") != JOURNAL_SCHEMA:
        raise RecorderError("journal schema id mismatch")
    cases: dict[str, dict[str, Any]] = {}
    for row in rows[1:]:
        case_id = row["case_id"]
        if not isinstance(case_id, str) or not re.fullmatch(r"[0-9a-f]{32}", case_id):
            raise RecorderError("journal case id is invalid")
        case = cases.setdefault(case_id, {"begin": None, "observations": [], "finish": None})
        if row["kind"] == "case_started":
            if case["begin"] is not None or case["observations"] or case["finish"] is not None:
                raise RecorderError("case_started is duplicated or out of order")
            case["begin"] = row
        elif row["kind"] == "request_observed":
            if case["begin"] is None or case["finish"] is not None:
                raise RecorderError("request observation is out of order")
            case["observations"].append(row)
        elif row["kind"] == "case_finished":
            if case["begin"] is None or not case["observations"] or case["finish"] is not None:
                raise RecorderError("case_finished is duplicated or out of order")
            case["finish"] = row
        else:
            raise RecorderError(f"unknown journal record kind: {row['kind']}")
    return meta, cases


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


def finalize(journal: Path, manifest_path: Path) -> dict[str, Any]:
    manifest, raw = _load_json(manifest_path)
    errors = validate_manifest(manifest, require_bound=False)
    if errors:
        raise RecorderError("manifest is invalid: " + "; ".join(errors))
    rows, final_sha = verify_journal_binding(journal, manifest, raw)
    _meta, cases = _state(rows)
    if any(case["finish"] is None for case in cases.values()):
        raise RecorderError("one or more cases are unfinished")
    compiled = []
    for case_id, case in sorted(cases.items(), key=lambda pair: pair[1]["begin"]["seq"]):
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
                "request_statuses": [item["payload"]["status"] for item in observations],
                "response_sha256s": [item["payload"]["response_sha256"] for item in observations],
                "note_count_before": begin["payload"]["note_count_before"],
                "note_count_after": finish["payload"]["note_count_after"],
                "approval_use_count_before": begin["payload"]["approval_use_count_before"],
                "approval_use_count_after": finish["payload"]["approval_use_count_after"],
                "run_ids": run_ids,
            }
        )
    negative = {
        "schema": NEGATIVE_SCHEMA,
        "pilot_id": manifest["pilot_id"],
        "generated_at": rows[-1]["recorded_at"],
        "journal_final_sha256": final_sha,
        "cases": compiled,
    }
    errors = validate_negative_evidence(negative, manifest)
    if errors:
        raise RecorderError("compiled negative evidence is invalid: " + "; ".join(errors))
    return negative


def _cmd_init(args: argparse.Namespace) -> int:
    _init(Path(args.journal), Path(args.manifest))
    print(f"initialized T-022 journal: {args.journal}")
    return 0


def _cmd_begin(args: argparse.Namespace) -> int:
    case_id, marker = begin_case(
        journal=Path(args.journal),
        manifest_path=Path(args.manifest),
        name=args.case,
        note_count=args.note_count,
        approval_count=args.approval_count,
        positive_ordinal=args.positive_ordinal,
    )
    print(json.dumps({"case_id": case_id, "marker": marker}, ensure_ascii=False))
    return 0


def _cmd_observe(args: argparse.Namespace) -> int:
    digest = observe_request(
        journal=Path(args.journal),
        case_id=args.case_id,
        status=args.status,
        response_path=Path(args.response_file),
        run_id=args.run_id,
    )
    print(f"recorded response: {digest}")
    return 0


def _cmd_finish(args: argparse.Namespace) -> int:
    digest = finish_case(
        journal=Path(args.journal),
        case_id=args.case_id,
        note_count=args.note_count,
        approval_count=args.approval_count,
    )
    print(f"finished case: {digest}")
    return 0


def _cmd_finalize(args: argparse.Namespace) -> int:
    negative = finalize(Path(args.journal), Path(args.manifest))
    _atomic_json(Path(args.output), negative)
    print(f"wrote strict negative evidence: {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("--manifest", required=True)
    init.add_argument("--journal", required=True)
    init.set_defaults(func=_cmd_init)

    begin = sub.add_parser("begin")
    begin.add_argument("--manifest", required=True)
    begin.add_argument("--journal", required=True)
    begin.add_argument("--case", choices=_NEGATIVE_CASES, required=True)
    begin.add_argument("--note-count", type=int, required=True)
    begin.add_argument("--approval-count", type=int, required=True)
    begin.add_argument("--positive-ordinal", type=int)
    begin.set_defaults(func=_cmd_begin)

    observe = sub.add_parser("observe")
    observe.add_argument("--journal", required=True)
    observe.add_argument("--case-id", required=True)
    observe.add_argument("--status", type=int, required=True)
    observe.add_argument("--response-file", required=True)
    observe.add_argument("--run-id", required=True)
    observe.set_defaults(func=_cmd_observe)

    finish = sub.add_parser("finish")
    finish.add_argument("--journal", required=True)
    finish.add_argument("--case-id", required=True)
    finish.add_argument("--note-count", type=int, required=True)
    finish.add_argument("--approval-count", type=int, required=True)
    finish.set_defaults(func=_cmd_finish)

    final = sub.add_parser("finalize")
    final.add_argument("--manifest", required=True)
    final.add_argument("--journal", required=True)
    final.add_argument("--output", required=True)
    final.set_defaults(func=_cmd_finalize)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (RecorderError, OSError, sqlite3.Error) as exc:
        print(f"T-022 recorder error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
