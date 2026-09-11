from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from .memory import MemoryRecord, MemoryStoreError


class LegacyMemoryReadError(MemoryStoreError):
    """The plaintext compatibility store cannot be opened read-only safely."""


_REQUIRED_COLUMNS = {
    "id",
    "subject",
    "predicate",
    "value",
    "kind",
    "sensitivity",
    "source_type",
    "confidence",
    "review_status",
    "lifecycle_status",
    "created_at",
    "updated_at",
    "expires_at",
    "schema_version",
}


class LegacyMemoryReader:
    """Query-only compatibility reader for the existing plaintext memory DB.

    Unlike ``MemoryStore`` this class never creates a directory, database,
    table, index or WAL mode and exposes no create/correct/delete methods. It is
    intentionally narrow: R04 only needs bounded reviewed context candidates.
    Source provenance is not selected and therefore cannot cross this boundary.
    """

    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 5_000):
        self.path = Path(path)
        self.busy_timeout_ms = max(1, min(int(busy_timeout_ms), 120_000))
        self._closed = False
        self._conn: sqlite3.Connection | None = None
        self._validate_path()
        uri = f"file:{self.path.resolve().as_posix()}?mode=ro"
        try:
            self._conn = sqlite3.connect(
                uri,
                uri=True,
                check_same_thread=False,
                timeout=self.busy_timeout_ms / 1000.0,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            self._conn.execute("PRAGMA query_only=ON")
            self._validate_schema()
        except (sqlite3.Error, LegacyMemoryReadError) as exc:
            self._close_connection()
            if isinstance(exc, LegacyMemoryReadError):
                raise
            raise LegacyMemoryReadError(
                f"legacy memory reader failed closed: {type(exc).__name__}"
            ) from exc

    def close(self) -> None:
        self._close_connection()
        self._closed = True

    def __enter__(self) -> "LegacyMemoryReader":
        self._require_open()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()

    def context_records(
        self,
        *,
        subjects: Iterable[str] | None = None,
        include_private: bool = True,
        limit: int = 50,
        max_chars: int = 12_000,
    ) -> list[MemoryRecord]:
        """Return only active/confirmed/unexpired/non-secret context rows."""
        self._require_open()
        if not isinstance(include_private, bool):
            raise LegacyMemoryReadError("include_private must be boolean")
        bounded_limit = self._bounded_int("limit", limit, minimum=1, maximum=200)
        budget = self._bounded_int("max_chars", max_chars, minimum=0, maximum=50_000)
        if budget == 0:
            return []

        clauses = [
            "lifecycle_status='active'",
            "review_status='confirmed'",
            "(expires_at IS NULL OR expires_at>?)",
            "sensitivity!='secret'",
        ]
        params: list[Any] = [time.time()]
        if not include_private:
            clauses.append("sensitivity NOT IN ('private','secret')")

        if subjects is not None:
            if isinstance(subjects, (str, bytes)):
                raise LegacyMemoryReadError("subjects must be an iterable of text values")
            cleaned: list[str] = []
            seen: set[str] = set()
            try:
                iterator = iter(subjects)
            except TypeError as exc:
                raise LegacyMemoryReadError("subjects must be iterable") from exc
            for subject in iterator:
                value = self._clean_text("subject", subject, 200)
                if value in seen:
                    raise LegacyMemoryReadError("subjects must be unique")
                seen.add(value)
                cleaned.append(value)
                if len(cleaned) > 64:
                    raise LegacyMemoryReadError("subject filter exceeds 64 values")
            if not cleaned:
                return []
            clauses.append("subject IN (" + ",".join("?" for _ in cleaned) + ")")
            params.extend(cleaned)

        params.append(bounded_limit)
        rows = self._execute(
            "SELECT id,subject,predicate,value,kind,sensitivity,source_type,"
            "confidence,review_status,lifecycle_status,created_at,updated_at,"
            "expires_at,schema_version FROM agent_memories WHERE "
            + " AND ".join(clauses)
            + " ORDER BY updated_at DESC LIMIT ?",
            tuple(params),
        ).fetchall()

        result: list[MemoryRecord] = []
        used = 0
        for row in rows:
            record = self._record(row)
            size = len(record.subject) + len(record.predicate) + len(record.value)
            if used + size > budget:
                continue
            result.append(record)
            used += size
        return result

    def _validate_path(self) -> None:
        if self.path.is_symlink():
            raise LegacyMemoryReadError("legacy memory database must not be a symlink")
        if not self.path.is_file():
            raise LegacyMemoryReadError("legacy memory database does not exist")
        parent = self.path.parent
        if parent.is_symlink() or not parent.is_dir():
            raise LegacyMemoryReadError("legacy memory database parent is invalid")

    def _validate_schema(self) -> None:
        rows = self._execute("PRAGMA table_info(agent_memories)").fetchall()
        columns = {str(row["name"]) for row in rows}
        missing = _REQUIRED_COLUMNS - columns
        if missing:
            raise LegacyMemoryReadError(
                "legacy memory database schema is incomplete: "
                + ",".join(sorted(missing))
            )

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        self._require_open()
        connection = self._conn
        if connection is None:
            raise LegacyMemoryReadError("legacy memory reader is closed")
        try:
            return connection.execute(sql, params)
        except sqlite3.Error as exc:
            raise LegacyMemoryReadError(
                f"legacy memory query failed closed: {type(exc).__name__}"
            ) from exc

    def _require_open(self) -> None:
        if self._closed or self._conn is None:
            raise LegacyMemoryReadError("legacy memory reader is closed")

    def _close_connection(self) -> None:
        connection = self._conn
        self._conn = None
        if connection is not None:
            connection.close()

    @staticmethod
    def _clean_text(name: str, value: Any, maximum: int) -> str:
        if not isinstance(value, str):
            raise LegacyMemoryReadError(f"{name} must be text")
        cleaned = value.strip()
        if not cleaned or cleaned != value:
            raise LegacyMemoryReadError(f"{name} must be canonical non-empty text")
        if len(cleaned) > maximum:
            raise LegacyMemoryReadError(f"{name} exceeds {maximum} characters")
        return cleaned

    @staticmethod
    def _bounded_int(name: str, value: Any, *, minimum: int, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise LegacyMemoryReadError(f"{name} must be an integer")
        if value < minimum or value > maximum:
            raise LegacyMemoryReadError(
                f"{name} must be between {minimum} and {maximum}"
            )
        return value

    @staticmethod
    def _record(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            id=str(row["id"]),
            subject=str(row["subject"]),
            predicate=str(row["predicate"]),
            value=str(row["value"]),
            kind=str(row["kind"]),
            sensitivity=str(row["sensitivity"]),
            source_type=str(row["source_type"]),
            source_ref=None,
            confidence=float(row["confidence"]),
            review_status=str(row["review_status"]),
            lifecycle_status=str(row["lifecycle_status"]),
            supersedes_id=None,
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            expires_at=(
                None if row["expires_at"] is None else float(row["expires_at"])
            ),
            deleted_at=None,
            schema_version=int(row["schema_version"]),
        )
