from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


KINDS = {"fact", "preference", "project", "relationship", "routine", "constraint", "note"}
SENSITIVITIES = {"public", "operational", "private", "secret"}
SOURCE_TYPES = {"user_explicit", "tool_observation", "imported", "inferred"}
REVIEW_STATES = {"pending", "confirmed", "rejected"}
LIFECYCLE_STATES = {"active", "superseded", "deleted"}


class MemoryStoreError(RuntimeError):
    pass


class MemoryNotFound(MemoryStoreError):
    pass


class MemoryConflict(MemoryStoreError):
    pass


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    subject: str
    predicate: str
    value: str
    kind: str
    sensitivity: str
    source_type: str
    source_ref: str | None
    confidence: float
    review_status: str
    lifecycle_status: str
    supersedes_id: str | None
    created_at: float
    updated_at: float
    expires_at: float | None
    deleted_at: float | None
    schema_version: int = 1

    def to_dict(self, *, include_value: bool = True) -> dict[str, Any]:
        data = asdict(self)
        if not include_value:
            data["value"] = "[redacted]"
            data["source_ref"] = None
        return data


class MemoryStore:
    """Local, user-controlled Agent 3.0 memory with provenance and versioning.

    Storage only: this module does not call an LLM, build prompts, expose HTTP,
    or send data to cloud.

    - explicit user memories default to confirmed;
    - inferred/imported/tool-observed memories default to pending;
    - corrections create a new row and supersede the old row atomically;
    - deletion erases value/source provenance and leaves a tombstone;
    - normal context excludes pending, rejected, expired, deleted and secret rows.
    """

    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_memories (
                id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                value TEXT NOT NULL,
                kind TEXT NOT NULL,
                sensitivity TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_ref TEXT,
                confidence REAL NOT NULL,
                review_status TEXT NOT NULL,
                lifecycle_status TEXT NOT NULL,
                supersedes_id TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                expires_at REAL,
                deleted_at REAL,
                schema_version INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(supersedes_id) REFERENCES agent_memories(id)
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_memories_lookup "
            "ON agent_memories(subject,predicate,lifecycle_status,review_status)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_memories_updated "
            "ON agent_memories(updated_at DESC)"
        )
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create(
        self,
        *,
        subject: str,
        predicate: str,
        value: str,
        kind: str = "fact",
        sensitivity: str = "private",
        source_type: str = "user_explicit",
        source_ref: str | None = None,
        confidence: float = 1.0,
        review_status: str | None = None,
        expires_at: float | None = None,
    ) -> MemoryRecord:
        fields = self._validate_fields(
            subject=subject,
            predicate=predicate,
            value=value,
            kind=kind,
            sensitivity=sensitivity,
            source_type=source_type,
            source_ref=source_ref,
            confidence=confidence,
            review_status=review_status,
            expires_at=expires_at,
        )
        with self._transaction():
            return self._insert_locked(**fields)

    def get(self, memory_id: str, *, include_deleted: bool = False) -> MemoryRecord:
        row = self._row_by_id(memory_id)
        if row is None or (row["lifecycle_status"] == "deleted" and not include_deleted):
            raise MemoryNotFound("memory not found")
        return self._record(row)

    def confirm(self, memory_id: str) -> MemoryRecord:
        return self._set_review(memory_id, expected="pending", target="confirmed")

    def reject(self, memory_id: str) -> MemoryRecord:
        return self._set_review(memory_id, expected="pending", target="rejected")

    def _set_review(self, memory_id: str, *, expected: str, target: str) -> MemoryRecord:
        memory_id = self._clean_id(memory_id)
        with self._transaction():
            row = self._conn.execute(
                "SELECT * FROM agent_memories WHERE id=?", (memory_id,)
            ).fetchone()
            if row is None or row["lifecycle_status"] != "active":
                raise MemoryNotFound("active memory not found")
            if row["review_status"] != expected:
                raise MemoryConflict(f"memory is {row['review_status']}, not {expected}")
            self._conn.execute(
                "UPDATE agent_memories SET review_status=?,updated_at=? WHERE id=?",
                (target, time.time(), memory_id),
            )
            return self._record(
                self._conn.execute(
                    "SELECT * FROM agent_memories WHERE id=?", (memory_id,)
                ).fetchone()
            )

    def correct(
        self,
        memory_id: str,
        *,
        value: str,
        source_ref: str | None = None,
        sensitivity: str | None = None,
        confidence: float = 1.0,
        expires_at: float | None = None,
    ) -> MemoryRecord:
        """Create a confirmed user correction and supersede the old version."""
        old_id = self._clean_id(memory_id)
        with self._transaction():
            row = self._conn.execute(
                "SELECT * FROM agent_memories WHERE id=?", (old_id,)
            ).fetchone()
            if row is None or row["lifecycle_status"] != "active":
                raise MemoryNotFound("active memory not found")
            fields = self._validate_fields(
                subject=row["subject"],
                predicate=row["predicate"],
                value=value,
                kind=row["kind"],
                sensitivity=sensitivity or row["sensitivity"],
                source_type="user_explicit",
                source_ref=source_ref,
                confidence=confidence,
                review_status="confirmed",
                expires_at=expires_at,
            )
            replacement = self._insert_locked(**fields, supersedes_id=old_id)
            changed = self._conn.execute(
                "UPDATE agent_memories SET lifecycle_status='superseded',updated_at=? "
                "WHERE id=? AND lifecycle_status='active'",
                (time.time(), old_id),
            ).rowcount
            if changed != 1:
                raise MemoryConflict("memory changed while correction was being created")
            return replacement

    def delete(self, memory_id: str) -> MemoryRecord:
        """Erase value/source provenance and retain a content-free lifecycle tombstone."""
        memory_id = self._clean_id(memory_id)
        now = time.time()
        with self._transaction():
            changed = self._conn.execute(
                "UPDATE agent_memories SET value='',source_ref=NULL,review_status='rejected',"
                "lifecycle_status='deleted',updated_at=?,deleted_at=? "
                "WHERE id=? AND lifecycle_status!='deleted'",
                (now, now, memory_id),
            ).rowcount
            if changed != 1:
                raise MemoryNotFound("memory not found")
            return self._record(
                self._conn.execute(
                    "SELECT * FROM agent_memories WHERE id=?", (memory_id,)
                ).fetchone()
            )

    def list(
        self,
        *,
        subject: str | None = None,
        predicate: str | None = None,
        review_status: str | None = None,
        lifecycle_status: str | None = "active",
        include_expired: bool = False,
        include_secret: bool = False,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if subject is not None:
            clauses.append("subject=?")
            params.append(self._clean_text("subject", subject, 200))
        if predicate is not None:
            clauses.append("predicate=?")
            params.append(self._clean_text("predicate", predicate, 200))
        if review_status is not None:
            clauses.append("review_status=?")
            params.append(self._choice("review_status", review_status, REVIEW_STATES))
        if lifecycle_status is not None:
            clauses.append("lifecycle_status=?")
            params.append(self._choice("lifecycle_status", lifecycle_status, LIFECYCLE_STATES))
        if not include_expired:
            clauses.append("(expires_at IS NULL OR expires_at>?)")
            params.append(time.time())
        if not include_secret:
            clauses.append("sensitivity!='secret'")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM agent_memories" + where + " ORDER BY updated_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [self._record(row) for row in rows]

    def search(
        self,
        query: str,
        *,
        confirmed_only: bool = True,
        include_secret: bool = False,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        q = self._clean_text("query", query, 300)
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped.lower()}%"
        clauses = [
            "lifecycle_status='active'",
            "(expires_at IS NULL OR expires_at>?)",
            "(lower(subject) LIKE ? ESCAPE '\\' OR lower(predicate) LIKE ? ESCAPE '\\' "
            "OR lower(value) LIKE ? ESCAPE '\\')",
        ]
        params: list[Any] = [time.time(), pattern, pattern, pattern]
        if confirmed_only:
            clauses.append("review_status='confirmed'")
        if not include_secret:
            clauses.append("sensitivity!='secret'")
        params.append(max(1, min(int(limit), 200)))
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM agent_memories WHERE " + " AND ".join(clauses)
                + " ORDER BY updated_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [self._record(row) for row in rows]

    def context_records(
        self,
        *,
        subjects: Iterable[str] | None = None,
        include_private: bool = True,
        include_secret: bool = False,
        limit: int = 50,
        max_chars: int = 12_000,
    ) -> list[MemoryRecord]:
        """Return bounded active/confirmed/unexpired records for local context.

        Records are returned as typed values rather than prompt text. Oversized
        records are skipped; even the first candidate may never break max_chars.
        """
        budget = max(0, int(max_chars))
        if budget == 0:
            return []
        clauses = [
            "lifecycle_status='active'",
            "review_status='confirmed'",
            "(expires_at IS NULL OR expires_at>?)",
        ]
        params: list[Any] = [time.time()]
        if not include_secret:
            clauses.append("sensitivity!='secret'")
        if not include_private:
            clauses.append("sensitivity NOT IN ('private','secret')")
        if subjects is not None:
            cleaned = [self._clean_text("subject", subject, 200) for subject in subjects]
            if not cleaned:
                return []
            clauses.append("subject IN (" + ",".join("?" for _ in cleaned) + ")")
            params.extend(cleaned)
        params.append(max(1, min(int(limit), 200)))
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM agent_memories WHERE " + " AND ".join(clauses)
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

    def history(self, subject: str, predicate: str) -> list[MemoryRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM agent_memories WHERE subject=? AND predicate=? "
                "ORDER BY created_at ASC",
                (
                    self._clean_text("subject", subject, 200),
                    self._clean_text("predicate", predicate, 200),
                ),
            ).fetchall()
        return [self._record(row) for row in rows]

    def _insert_locked(
        self,
        *,
        subject: str,
        predicate: str,
        value: str,
        kind: str,
        sensitivity: str,
        source_type: str,
        source_ref: str | None,
        confidence: float,
        review_status: str,
        expires_at: float | None,
        supersedes_id: str | None = None,
    ) -> MemoryRecord:
        memory_id = str(uuid.uuid4())
        now = time.time()
        self._conn.execute(
            "INSERT INTO agent_memories("
            "id,subject,predicate,value,kind,sensitivity,source_type,source_ref,confidence,"
            "review_status,lifecycle_status,supersedes_id,created_at,updated_at,expires_at,"
            "deleted_at,schema_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
            (
                memory_id,
                subject,
                predicate,
                value,
                kind,
                sensitivity,
                source_type,
                source_ref,
                confidence,
                review_status,
                "active",
                supersedes_id,
                now,
                now,
                expires_at,
                None,
            ),
        )
        return self._record(
            self._conn.execute(
                "SELECT * FROM agent_memories WHERE id=?", (memory_id,)
            ).fetchone()
        )

    def _validate_fields(
        self,
        *,
        subject: str,
        predicate: str,
        value: str,
        kind: str,
        sensitivity: str,
        source_type: str,
        source_ref: str | None,
        confidence: float,
        review_status: str | None,
        expires_at: float | None,
    ) -> dict[str, Any]:
        kind = self._choice("kind", kind, KINDS)
        sensitivity = self._choice("sensitivity", sensitivity, SENSITIVITIES)
        source_type = self._choice("source_type", source_type, SOURCE_TYPES)
        if review_status is None:
            review_status = "confirmed" if source_type == "user_explicit" else "pending"
        review_status = self._choice("review_status", review_status, REVIEW_STATES)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError) as exc:
            raise MemoryStoreError("confidence must be a number") from exc
        if not 0.0 <= confidence <= 1.0:
            raise MemoryStoreError("confidence must be between 0 and 1")
        if expires_at is not None:
            try:
                expires_at = float(expires_at)
            except (TypeError, ValueError) as exc:
                raise MemoryStoreError("expires_at must be a timestamp") from exc
        return {
            "subject": self._clean_text("subject", subject, 200),
            "predicate": self._clean_text("predicate", predicate, 200),
            "value": self._clean_text("value", value, 20_000),
            "kind": kind,
            "sensitivity": sensitivity,
            "source_type": source_type,
            "source_ref": None if source_ref is None else self._clean_text("source_ref", source_ref, 1000),
            "confidence": confidence,
            "review_status": review_status,
            "expires_at": expires_at,
        }

    def _row_by_id(self, memory_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM agent_memories WHERE id=?", (self._clean_id(memory_id),)
            ).fetchone()

    class _Transaction:
        def __init__(self, store: "MemoryStore"):
            self.store = store

        def __enter__(self):
            self.store._lock.acquire()
            self.store._conn.execute("BEGIN IMMEDIATE")
            return self

        def __exit__(self, exc_type, _exc, _tb):
            try:
                if exc_type is None:
                    self.store._conn.commit()
                else:
                    self.store._conn.rollback()
            finally:
                self.store._lock.release()
            return False

    def _transaction(self) -> "MemoryStore._Transaction":
        return self._Transaction(self)

    @staticmethod
    def _clean_text(name: str, value: Any, maximum: int) -> str:
        if not isinstance(value, str):
            raise MemoryStoreError(f"{name} must be text")
        cleaned = value.strip()
        if not cleaned:
            raise MemoryStoreError(f"{name} must not be empty")
        if len(cleaned) > maximum:
            raise MemoryStoreError(f"{name} exceeds {maximum} characters")
        return cleaned

    @staticmethod
    def _clean_id(value: Any) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > 100:
            raise MemoryStoreError("invalid memory id")
        return value.strip()

    @staticmethod
    def _choice(name: str, value: Any, allowed: set[str]) -> str:
        if not isinstance(value, str) or value not in allowed:
            raise MemoryStoreError(f"invalid {name}: {value!r}")
        return value

    @staticmethod
    def _record(row: sqlite3.Row | None) -> MemoryRecord:
        if row is None:
            raise MemoryNotFound("memory not found")
        return MemoryRecord(**dict(row))
