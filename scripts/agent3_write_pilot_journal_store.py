#!/usr/bin/env python3
"""Append-only operator recorder for the T-022 negative write-pilot cases.

The recorder never sends an HTTP request. It creates a hash-chained SQLite journal
around the operator's real requests: begin captures before-counts, observe hashes
an exact response body and status, finish captures after-counts, and finalize
emits the strict negative evidence JSON consumed by the forensic collector.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from agent3_write_pilot_common import (  # noqa: E402
    _canonical_json,
    _iso,
    _load_json,
    _parse_time,
    _sha_bytes,
    _utc_now,
    validate_manifest,
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
