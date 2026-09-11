from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from itertools import islice
from typing import Any


MAX_MEMORY_READ_CANDIDATES = 200
MAX_MEMORY_READ_CHARS = 50_000
MAX_MEMORY_READ_SUBJECTS = 64

_ALLOWED_MODES = frozenset({"legacy", "protected"})
_ALLOWED_TARGETS = frozenset({"local", "cloud"})
_ALLOWED_SENSITIVITIES = frozenset({"public", "operational", "private"})
_ALLOWED_SOURCE_TYPES = frozenset(
    {"user_explicit", "tool_observation", "imported", "inferred"}
)


class SharedMemoryReadError(RuntimeError):
    """The shared read boundary cannot safely expose memory candidates."""


@dataclass(frozen=True)
class MemoryReadRequest:
    """Bounded, model-independent request for reviewed memory candidates."""

    target: str = "local"
    subjects: tuple[str, ...] = ()
    allow_private_cloud: bool = False
    max_candidates: int = 100
    max_chars: int = MAX_MEMORY_READ_CHARS


@dataclass(frozen=True)
class SharedMemoryRecord:
    """Neutral read projection with storage/provenance locator fields removed.

    The durable Agent 3 row may contain source references, supersede pointers,
    deleted-at metadata or protected envelopes. None of those fields cross this
    shared boundary. This projection contains only data required by retrieval
    and context compilation.
    """

    id: str
    subject: str
    predicate: str
    value: str
    kind: str
    sensitivity: str
    source_type: str
    confidence: float
    review_status: str
    lifecycle_status: str
    created_at: float
    updated_at: float
    expires_at: float | None
    schema_version: int


MemoryContextRead = Callable[..., Iterable[object]]


class SharedMemoryReader:
    """Read-only adapter over an already-authorized memory substrate.

    The shared package never opens SQLite, imports Agent 3 storage classes,
    invokes DPAPI, migrates data or exposes writes. The composition root injects
    one bounded context-reader callback from the selected legacy/protected
    substrate. The adapter then validates the returned rows and projects them to
    storage-neutral records.

    Protected/private policy is enforced twice by design: this adapter asks the
    backend not to reveal private rows for cloud use unless explicit authority is
    present, and the downstream R01 retriever independently repeats that policy.
    Secret rows are never valid at this boundary.
    """

    def __init__(self, *, mode: str, read_context: MemoryContextRead):
        if not isinstance(mode, str) or mode not in _ALLOWED_MODES:
            raise SharedMemoryReadError("memory reader mode must be legacy or protected")
        if not callable(read_context):
            raise SharedMemoryReadError("memory context reader must be callable")
        self._mode = mode
        self._read_context = read_context

    @property
    def mode(self) -> str:
        return self._mode

    def read_candidates(
        self,
        request: MemoryReadRequest,
    ) -> tuple[SharedMemoryRecord, ...]:
        target, subjects, allow_private_cloud, limit, max_chars = self._request(request)
        if limit == 0 or max_chars == 0:
            return ()

        include_private = target == "local" or allow_private_cloud
        try:
            raw_source = self._read_context(
                subjects=subjects or None,
                include_private=include_private,
                limit=limit,
                max_chars=max_chars,
            )
            # Never trust a backend to respect the requested record bound. Read
            # at most one sentinel item beyond the limit so even a generator or
            # future adapter cannot force unbounded materialization here.
            raw_records = tuple(islice(iter(raw_source), limit + 1))
        except SharedMemoryReadError:
            raise
        except Exception as exc:
            raise SharedMemoryReadError(
                f"{self._mode} memory backend read failed"
            ) from exc

        if len(raw_records) > limit:
            raise SharedMemoryReadError("memory backend exceeded candidate limit")

        now = time.time()
        seen: set[str] = set()
        used_chars = 0
        projected: list[SharedMemoryRecord] = []
        for raw in raw_records:
            # Authority is checked before payload projection. Tombstones and
            # pending rows may intentionally have erased/partial payload fields;
            # they should be refused because they lack read authority, not
            # parsed deeply enough to produce a payload-shaped error first.
            if (
                getattr(raw, "lifecycle_status", None) != "active"
                or getattr(raw, "review_status", None) != "confirmed"
            ):
                raise SharedMemoryReadError(
                    "memory backend returned unreviewed or inactive data"
                )

            record = self._project(raw)
            if record.id in seen:
                raise SharedMemoryReadError("memory backend returned duplicate ids")
            seen.add(record.id)

            if record.lifecycle_status != "active" or record.review_status != "confirmed":
                raise SharedMemoryReadError(
                    "memory backend returned unreviewed or inactive data"
                )
            if record.expires_at is not None and record.expires_at <= now:
                raise SharedMemoryReadError("memory backend returned expired data")
            if record.sensitivity not in _ALLOWED_SENSITIVITIES:
                raise SharedMemoryReadError(
                    "memory backend returned an ineligible sensitivity"
                )
            if (
                target == "cloud"
                and record.sensitivity == "private"
                and not allow_private_cloud
            ):
                raise SharedMemoryReadError(
                    "memory backend returned private cloud data without authority"
                )

            size = len(record.subject) + len(record.predicate) + len(record.value)
            if used_chars + size > max_chars:
                raise SharedMemoryReadError("memory backend exceeded character budget")
            used_chars += size
            projected.append(record)

        return tuple(projected)

    @staticmethod
    def _request(
        request: MemoryReadRequest,
    ) -> tuple[str, tuple[str, ...], bool, int, int]:
        if not isinstance(request, MemoryReadRequest):
            raise SharedMemoryReadError("MemoryReadRequest is required")

        target_value = getattr(request.target, "value", request.target)
        if not isinstance(target_value, str):
            raise SharedMemoryReadError("memory target must be text")
        target = target_value.strip().casefold()
        if target not in _ALLOWED_TARGETS:
            raise SharedMemoryReadError("memory target must be local or cloud")

        if not isinstance(request.allow_private_cloud, bool):
            raise SharedMemoryReadError("private cloud authority must be boolean")

        if not isinstance(request.subjects, tuple):
            raise SharedMemoryReadError("memory subjects must be a tuple")
        if len(request.subjects) > MAX_MEMORY_READ_SUBJECTS:
            raise SharedMemoryReadError("memory subject filter is too large")
        subjects: list[str] = []
        seen_subjects: set[str] = set()
        for subject in request.subjects:
            cleaned = _text("subject", subject, 200)
            if cleaned in seen_subjects:
                raise SharedMemoryReadError("memory subjects must be unique")
            seen_subjects.add(cleaned)
            subjects.append(cleaned)

        limit = _integer(
            "max_candidates",
            request.max_candidates,
            minimum=0,
            maximum=MAX_MEMORY_READ_CANDIDATES,
        )
        max_chars = _integer(
            "max_chars",
            request.max_chars,
            minimum=0,
            maximum=MAX_MEMORY_READ_CHARS,
        )
        return target, tuple(subjects), request.allow_private_cloud, limit, max_chars

    @staticmethod
    def _project(raw: object) -> SharedMemoryRecord:
        try:
            memory_id = _text("id", getattr(raw, "id"), 100)
            subject = _text("subject", getattr(raw, "subject"), 200)
            predicate = _text("predicate", getattr(raw, "predicate"), 200)
            value = _text("value", getattr(raw, "value"), 100_000)
            kind = _text("kind", getattr(raw, "kind"), 100)
            sensitivity = _text("sensitivity", getattr(raw, "sensitivity"), 50)
            source_type = _text("source_type", getattr(raw, "source_type"), 50)
            review_status = _text("review_status", getattr(raw, "review_status"), 50)
            lifecycle_status = _text(
                "lifecycle_status", getattr(raw, "lifecycle_status"), 50
            )
            confidence = _number("confidence", getattr(raw, "confidence"))
            created_at = _number("created_at", getattr(raw, "created_at"))
            updated_at = _number("updated_at", getattr(raw, "updated_at"))
            expires_raw = getattr(raw, "expires_at")
            expires_at = (
                None if expires_raw is None else _number("expires_at", expires_raw)
            )
            schema_version = _integer(
                "schema_version",
                getattr(raw, "schema_version"),
                minimum=1,
                maximum=1_000_000,
            )
        except (AttributeError, TypeError) as exc:
            raise SharedMemoryReadError("memory backend returned a malformed record") from exc

        if sensitivity not in _ALLOWED_SENSITIVITIES:
            raise SharedMemoryReadError("memory sensitivity is not shared-readable")
        if source_type not in _ALLOWED_SOURCE_TYPES:
            raise SharedMemoryReadError("memory provenance is invalid")
        if confidence < 0 or confidence > 1:
            raise SharedMemoryReadError("memory confidence must be between 0 and 1")

        return SharedMemoryRecord(
            id=memory_id,
            subject=subject,
            predicate=predicate,
            value=value,
            kind=kind,
            sensitivity=sensitivity,
            source_type=source_type,
            confidence=confidence,
            review_status=review_status,
            lifecycle_status=lifecycle_status,
            created_at=created_at,
            updated_at=updated_at,
            expires_at=expires_at,
            schema_version=schema_version,
        )


def _text(name: str, value: Any, maximum: int) -> str:
    if not isinstance(value, str):
        raise SharedMemoryReadError(f"{name} must be text")
    cleaned = value.strip()
    if not cleaned:
        raise SharedMemoryReadError(f"{name} must not be empty")
    if len(cleaned) > maximum:
        raise SharedMemoryReadError(f"{name} exceeds {maximum} characters")
    return cleaned


def _integer(
    name: str,
    value: Any,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SharedMemoryReadError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise SharedMemoryReadError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return value


def _number(name: str, value: Any) -> float:
    if isinstance(value, bool):
        raise SharedMemoryReadError(f"{name} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SharedMemoryReadError(f"{name} must be numeric") from exc
    if not math.isfinite(parsed):
        raise SharedMemoryReadError(f"{name} must be finite")
    return parsed
