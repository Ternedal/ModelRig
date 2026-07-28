from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .memory import MemoryRecord
from .memory_context import ContextTarget, MemoryContext, MemoryContextCompiler
from .memory_protected_reader import (
    MemoryReadAccess,
    ProtectedMemoryReadError,
    ProtectedMemoryReader,
)

PROTECTED_CONTEXT_SCHEMA = "kaliv-agent3-protected-memory-context/v1"
_MAX_SUBJECTS = 20
_MAX_CHARS = 12_000
_MAX_RECORDS = 50
_MAX_CANDIDATES = 200
_MAX_CANDIDATE_CHARS = 50_000


class ProtectedMemoryContextError(RuntimeError):
    """Protected memory cannot be compiled without weakening local boundaries."""


@dataclass(frozen=True)
class ProtectedMemoryContextResult:
    context: MemoryContext
    candidate_count: int
    private_candidates: int

    def receipt(self) -> dict[str, Any]:
        text = self.context.text
        return {
            "schema": PROTECTED_CONTEXT_SCHEMA,
            "requested": True,
            "sent_to_model": bool(text),
            "target": self.context.target.value,
            "included_ids": list(self.context.included_ids),
            "excluded_ids": list(self.context.excluded_ids),
            "candidate_count": self.candidate_count,
            "private_candidates": self.private_candidates,
            "character_count": self.context.character_count,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None,
            "source_provenance_included": False,
            "secret_included": False,
            "production_activation": False,
        }


class ProtectedMemoryContextCompiler:
    """Bounded local-only compiler over the explicit protected reader.

    The reader filters secret rows in SQL and decrypts only the bounded candidate
    set. The generic renderer then applies the final record/character budget and
    escapes marker-looking value content. This class is intentionally not mounted
    by production startup in this slice.
    """

    def __init__(
        self,
        reader: ProtectedMemoryReader,
        *,
        renderer: MemoryContextCompiler | None = None,
        candidate_multiplier: int = 4,
    ):
        if not isinstance(reader, ProtectedMemoryReader):
            raise ProtectedMemoryContextError(
                "protected context compiler requires a ProtectedMemoryReader"
            )
        if isinstance(candidate_multiplier, bool):
            raise ProtectedMemoryContextError("candidate_multiplier must be an integer")
        try:
            multiplier = int(candidate_multiplier)
        except (TypeError, ValueError) as exc:
            raise ProtectedMemoryContextError(
                "candidate_multiplier must be an integer"
            ) from exc
        if multiplier < 1 or multiplier > 8:
            raise ProtectedMemoryContextError(
                "candidate_multiplier must be between 1 and 8"
            )
        self.reader = reader
        self.renderer = renderer or MemoryContextCompiler()
        self.candidate_multiplier = multiplier

    def compile(
        self,
        *,
        subjects: Iterable[str] | None = None,
        target: ContextTarget | str = ContextTarget.LOCAL,
        max_chars: int = 4_000,
        max_records: int = 25,
    ) -> ProtectedMemoryContextResult:
        try:
            selected_target = ContextTarget(target)
        except (TypeError, ValueError) as exc:
            raise ProtectedMemoryContextError("protected context target is invalid") from exc
        if selected_target is not ContextTarget.LOCAL:
            raise ProtectedMemoryContextError(
                "protected memory context is local-only"
            )

        budget = self._bounded_int("max_chars", max_chars, minimum=0, maximum=_MAX_CHARS)
        record_limit = self._bounded_int(
            "max_records", max_records, minimum=0, maximum=_MAX_RECORDS
        )
        selected_subjects = self._subjects(subjects)
        if budget == 0 or record_limit == 0:
            return ProtectedMemoryContextResult(
                context=MemoryContext(
                    text="",
                    included_ids=(),
                    excluded_ids=(),
                    target=ContextTarget.LOCAL,
                    character_count=0,
                ),
                candidate_count=0,
                private_candidates=0,
            )

        candidate_limit = min(record_limit * self.candidate_multiplier, _MAX_CANDIDATES)
        candidate_budget = min(
            max(budget * self.candidate_multiplier, budget),
            _MAX_CANDIDATE_CHARS,
        )
        try:
            candidates = self.reader.context_records(
                access=MemoryReadAccess.LOCAL_CONTEXT,
                subjects=selected_subjects,
                include_private=True,
                limit=candidate_limit,
                max_chars=candidate_budget,
            )
        except ProtectedMemoryReadError as exc:
            raise ProtectedMemoryContextError(
                f"protected context read failed closed: {type(exc).__name__}"
            ) from exc

        self._validate_candidates(candidates)
        compiled = self.renderer.compile(
            candidates,
            target=ContextTarget.LOCAL,
            allow_private_cloud=False,
            max_chars=budget,
            max_records=record_limit,
        )
        if compiled.target is not ContextTarget.LOCAL:
            raise ProtectedMemoryContextError(
                "protected context renderer changed the target"
            )
        candidate_ids = {record.id for record in candidates}
        if not set(compiled.included_ids).issubset(candidate_ids):
            raise ProtectedMemoryContextError(
                "protected context renderer introduced an unknown record"
            )
        return ProtectedMemoryContextResult(
            context=compiled,
            candidate_count=len(candidates),
            private_candidates=sum(
                1 for record in candidates if record.sensitivity == "private"
            ),
        )

    @staticmethod
    def _bounded_int(name: str, value: Any, *, minimum: int, maximum: int) -> int:
        if isinstance(value, bool):
            raise ProtectedMemoryContextError(f"{name} must be an integer")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ProtectedMemoryContextError(f"{name} must be an integer") from exc
        if parsed < minimum or parsed > maximum:
            raise ProtectedMemoryContextError(
                f"{name} must be between {minimum} and {maximum}"
            )
        return parsed

    @staticmethod
    def _subjects(subjects: Iterable[str] | None) -> list[str] | None:
        if subjects is None:
            return None
        if isinstance(subjects, (str, bytes)):
            raise ProtectedMemoryContextError("subjects must be a sequence")
        selected = list(subjects)
        if len(selected) > _MAX_SUBJECTS:
            raise ProtectedMemoryContextError(
                f"subjects may contain at most {_MAX_SUBJECTS} items"
            )
        cleaned: list[str] = []
        for subject in selected:
            if not isinstance(subject, str):
                raise ProtectedMemoryContextError("subjects must contain strings")
            value = subject.strip()
            if not value or value != subject or len(value) > 200:
                raise ProtectedMemoryContextError("subject is not canonical")
            cleaned.append(value)
        if len(cleaned) != len(set(cleaned)):
            raise ProtectedMemoryContextError("subjects must be unique")
        return cleaned

    @staticmethod
    def _validate_candidates(records: list[MemoryRecord]) -> None:
        seen: set[str] = set()
        for record in records:
            if not isinstance(record, MemoryRecord):
                raise ProtectedMemoryContextError(
                    "protected context reader returned an invalid record"
                )
            if record.id in seen:
                raise ProtectedMemoryContextError(
                    "protected context reader returned duplicate records"
                )
            seen.add(record.id)
            if record.sensitivity == "secret":
                raise ProtectedMemoryContextError(
                    "protected context reader returned a secret record"
                )
            if record.sensitivity not in {"public", "operational", "private"}:
                raise ProtectedMemoryContextError(
                    "protected context reader returned an unsupported sensitivity"
                )
            if record.source_ref is not None:
                raise ProtectedMemoryContextError(
                    "protected context reader exposed source provenance"
                )
            if record.lifecycle_status != "active" or record.review_status != "confirmed":
                raise ProtectedMemoryContextError(
                    "protected context reader returned an ineligible record"
                )
