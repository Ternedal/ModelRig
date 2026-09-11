from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import islice
from typing import Any, Iterable

from .extraction import (
    KINDS,
    MAX_CANDIDATE_EVIDENCE_CHARS,
    MAX_CANDIDATE_PREDICATE_CHARS,
    MAX_CANDIDATE_SUBJECT_CHARS,
    MAX_CANDIDATE_VALUE_CHARS,
    MAX_SOURCE_REF_CHARS,
    SENSITIVITIES,
    SOURCE_TYPES,
    VERBATIM_USER_PREDICATE,
    VERBATIM_USER_SUBJECT,
    MemoryCandidate,
)

MAX_CONSOLIDATION_CANDIDATES = 16
MAX_CONSOLIDATION_EXISTING = 128
MAX_CONSOLIDATION_TEXT_CHARS = 64_000
MAX_RECORD_ID_CHARS = 100

_DECISIONS = frozenset({"create", "dedupe", "supersede", "skip"})
_REVIEW_STATES = frozenset({"pending", "confirmed"})
_VERBATIM_KEY = (VERBATIM_USER_SUBJECT.casefold(), VERBATIM_USER_PREDICATE.casefold())


class MemoryConsolidationError(RuntimeError):
    """A W02 candidate batch cannot be planned deterministically."""


@dataclass(frozen=True)
class ExistingMemory:
    id: str
    subject: str
    predicate: str
    value: str
    kind: str
    sensitivity: str
    source_type: str
    review_status: str
    lifecycle_status: str


@dataclass(frozen=True)
class ConsolidationAction:
    decision: str
    candidate: MemoryCandidate
    existing_id: str | None
    reason: str

    def __post_init__(self) -> None:
        if self.decision not in _DECISIONS:
            raise MemoryConsolidationError("invalid consolidation decision")
        has_existing = self.existing_id is not None
        if self.decision in {"dedupe", "supersede"} and not has_existing:
            raise MemoryConsolidationError(
                "dedupe and supersede require a trusted existing id"
            )
        if self.decision in {"create", "skip"} and has_existing:
            raise MemoryConsolidationError(
                "create and skip cannot carry an existing id"
            )


@dataclass(frozen=True)
class ConsolidationReceipt:
    considered_count: int
    create_count: int
    dedupe_count: int
    supersede_count: int
    skip_count: int
    touched_existing_ids: tuple[str, ...]
    sent_to_store: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "considered_count": self.considered_count,
            "create_count": self.create_count,
            "dedupe_count": self.dedupe_count,
            "supersede_count": self.supersede_count,
            "skip_count": self.skip_count,
            "touched_existing_ids": list(self.touched_existing_ids),
            "sent_to_store": self.sent_to_store,
        }


@dataclass(frozen=True)
class ConsolidationPlan:
    actions: tuple[ConsolidationAction, ...]
    receipt: ConsolidationReceipt

    def to_dict(self) -> dict[str, Any]:
        # Deliberately omit value/evidence/source_ref. W02-A is a planning receipt,
        # not a new log surface for private candidate content.
        return {
            "actions": [
                {
                    "index": index,
                    "decision": action.decision,
                    "existing_id": action.existing_id,
                    "reason": action.reason,
                }
                for index, action in enumerate(self.actions)
            ],
            "receipt": self.receipt.to_dict(),
        }


def _clean_text(name: str, value: Any, maximum: int) -> str:
    if not isinstance(value, str):
        raise MemoryConsolidationError(f"{name} must be text")
    cleaned = value.strip()
    if not cleaned:
        raise MemoryConsolidationError(f"{name} must not be empty")
    if value != cleaned:
        raise MemoryConsolidationError(f"{name} must be canonical trimmed text")
    if len(cleaned) > maximum:
        raise MemoryConsolidationError(f"{name} exceeds {maximum} characters")
    return cleaned


def _bounded_items(values: Iterable[Any], maximum: int, name: str) -> tuple[Any, ...]:
    try:
        rows = tuple(islice(iter(values), maximum + 1))
    except TypeError as exc:
        raise MemoryConsolidationError(f"{name} must be iterable") from exc
    if len(rows) > maximum:
        raise MemoryConsolidationError(f"{name} exceeds {maximum} items")
    return rows


def _candidate(value: Any) -> MemoryCandidate:
    if not isinstance(value, MemoryCandidate):
        raise MemoryConsolidationError("W02 accepts MemoryCandidate objects only")

    _clean_text("candidate subject", value.subject, MAX_CANDIDATE_SUBJECT_CHARS)
    _clean_text("candidate predicate", value.predicate, MAX_CANDIDATE_PREDICATE_CHARS)
    _clean_text("candidate value", value.value, MAX_CANDIDATE_VALUE_CHARS)
    _clean_text("candidate source_ref", value.source_ref, MAX_SOURCE_REF_CHARS)

    if not isinstance(value.evidence, str):
        raise MemoryConsolidationError("candidate evidence must be text")
    if value.evidence != value.evidence.strip():
        raise MemoryConsolidationError("candidate evidence must be canonical trimmed text")
    if len(value.evidence) > MAX_CANDIDATE_EVIDENCE_CHARS:
        raise MemoryConsolidationError(
            f"candidate evidence exceeds {MAX_CANDIDATE_EVIDENCE_CHARS} characters"
        )
    if value.kind not in KINDS:
        raise MemoryConsolidationError("candidate has invalid kind")
    if value.sensitivity not in SENSITIVITIES:
        raise MemoryConsolidationError("candidate has invalid sensitivity")
    if value.sensitivity not in {"private", "secret"}:
        raise MemoryConsolidationError(
            "candidate sensitivity does not preserve the W01 conservative boundary"
        )
    if value.source_type not in SOURCE_TYPES:
        raise MemoryConsolidationError("candidate has invalid source_type")
    if value.review_status not in _REVIEW_STATES:
        raise MemoryConsolidationError("candidate has invalid review_status")

    if isinstance(value.confidence, bool):
        raise MemoryConsolidationError("candidate confidence must be numeric")
    try:
        confidence = float(value.confidence)
    except (TypeError, ValueError) as exc:
        raise MemoryConsolidationError("candidate confidence must be numeric") from exc
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise MemoryConsolidationError(
            "candidate confidence must be finite and between 0 and 1"
        )

    if value.source_type == "user_explicit":
        if not value.evidence or value.value not in value.evidence:
            raise MemoryConsolidationError(
                "user_explicit candidate does not preserve W01 evidence shape"
            )
    if value.review_status == "confirmed":
        if not (
            value.source_type == "user_explicit"
            and value.sensitivity == "private"
            and value.subject == VERBATIM_USER_SUBJECT
            and value.predicate == VERBATIM_USER_PREDICATE
            and value.kind == "note"
            and value.value == value.evidence
            and confidence == 1.0
        ):
            raise MemoryConsolidationError(
                "confirmed candidate does not preserve hardened W01 authority"
            )
    elif value.sensitivity == "secret" and value.review_status != "pending":
        raise MemoryConsolidationError("secret candidate must remain pending")

    return value


def _record(value: Any) -> ExistingMemory:
    try:
        record = ExistingMemory(
            id=_clean_text("existing id", value.id, MAX_RECORD_ID_CHARS),
            subject=_clean_text("existing subject", value.subject, 200),
            predicate=_clean_text("existing predicate", value.predicate, 200),
            value=_clean_text("existing value", value.value, 20_000),
            kind=_clean_text("existing kind", value.kind, 64),
            sensitivity=_clean_text("existing sensitivity", value.sensitivity, 64),
            source_type=_clean_text("existing source_type", value.source_type, 64),
            review_status=_clean_text("existing review_status", value.review_status, 64),
            lifecycle_status=_clean_text(
                "existing lifecycle_status", value.lifecycle_status, 64
            ),
        )
    except AttributeError as exc:
        raise MemoryConsolidationError(
            "existing memory does not implement the W02 record contract"
        ) from exc

    if record.kind not in KINDS:
        raise MemoryConsolidationError("existing memory has invalid kind")
    if record.sensitivity not in SENSITIVITIES:
        raise MemoryConsolidationError("existing memory has invalid sensitivity")
    if record.source_type not in SOURCE_TYPES:
        raise MemoryConsolidationError("existing memory has invalid source_type")
    if record.review_status not in _REVIEW_STATES:
        raise MemoryConsolidationError(
            "snapshot may contain pending or confirmed records only"
        )
    if record.lifecycle_status != "active":
        raise MemoryConsolidationError("snapshot may contain active records only")
    if record.sensitivity == "secret":
        raise MemoryConsolidationError("secret memory is outside W02 consolidation")
    return record


def _key(subject: str, predicate: str) -> tuple[str, str]:
    return subject.casefold(), predicate.casefold()


def _identity(candidate: MemoryCandidate) -> tuple[str, str, str, str, str]:
    return (
        candidate.subject.casefold(),
        candidate.predicate.casefold(),
        candidate.value,
        candidate.source_type,
        candidate.review_status,
    )


class MemoryConsolidator:
    """Create a bounded, storage-neutral W02 plan.

    Hardened W01 only auto-confirms conservative verbatim-user notes. W02-A
    therefore never interprets two different confirmed verbatim statements as
    versions of one semantic fact. Different confirmed statements are separate
    memories. The only automatic supersede is an authority upgrade where the
    *same* normalized verbatim value already exists as one pending row.

    Structured model semantics remain pending and may be created or exactly
    deduplicated, but cannot supersede confirmed state. A future trusted review
    boundary must approve semantic stale-fact replacement explicitly.
    """

    def plan(
        self,
        candidates: Iterable[MemoryCandidate],
        existing: Iterable[Any],
    ) -> ConsolidationPlan:
        raw_candidates = _bounded_items(
            candidates, MAX_CONSOLIDATION_CANDIDATES, "candidate batch"
        )
        raw_existing = _bounded_items(
            existing, MAX_CONSOLIDATION_EXISTING, "existing snapshot"
        )
        candidate_rows = tuple(_candidate(item) for item in raw_candidates)
        existing_rows = tuple(_record(item) for item in raw_existing)
        self._validate_text_budget(candidate_rows, existing_rows)

        by_key: dict[tuple[str, str], list[ExistingMemory]] = {}
        for record in existing_rows:
            by_key.setdefault(_key(record.subject, record.predicate), []).append(record)
        for rows in by_key.values():
            rows.sort(key=lambda item: item.id)
        self._validate_existing_state(by_key)

        actions: list[ConsolidationAction] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        for candidate in candidate_rows:
            identity = _identity(candidate)
            if identity in seen:
                actions.append(
                    ConsolidationAction("skip", candidate, None, "duplicate_in_batch")
                )
                continue
            seen.add(identity)

            if candidate.sensitivity == "secret":
                actions.append(
                    ConsolidationAction("skip", candidate, None, "secret_candidate")
                )
                continue

            current = by_key.get(_key(candidate.subject, candidate.predicate), [])
            exact = [item for item in current if item.value == candidate.value]
            exact_confirmed = [
                item for item in exact if item.review_status == "confirmed"
            ]
            exact_pending = [item for item in exact if item.review_status == "pending"]

            if candidate.review_status == "pending":
                if exact:
                    actions.append(
                        ConsolidationAction(
                            "dedupe", candidate, exact[0].id, "existing_exact_value"
                        )
                    )
                else:
                    actions.append(
                        ConsolidationAction(
                            "create", candidate, None, "new_pending_candidate"
                        )
                    )
                continue

            # Confirmed W01 output is one exact verbatim statement. Never treat a
            # different statement with the same generic key as a stale-fact update.
            if exact_confirmed:
                trusted = [
                    item
                    for item in exact_confirmed
                    if item.source_type == "user_explicit" and item.kind == "note"
                ]
                if trusted:
                    actions.append(
                        ConsolidationAction(
                            "dedupe",
                            candidate,
                            trusted[0].id,
                            "existing_confirmed_verbatim_value",
                        )
                    )
                    continue

            if exact_pending or exact_confirmed:
                exact_rows = exact_pending + exact_confirmed
                if len(exact_rows) != 1:
                    raise MemoryConsolidationError(
                        "multiple exact rows require explicit review before authority upgrade"
                    )
                previous = exact_rows[0]
                actions.append(
                    ConsolidationAction(
                        "supersede",
                        candidate,
                        previous.id,
                        "normalize_exact_value_to_confirmed_verbatim",
                    )
                )
                continue

            actions.append(
                ConsolidationAction(
                    "create", candidate, None, "new_confirmed_verbatim_statement"
                )
            )

        return ConsolidationPlan(tuple(actions), self._receipt(actions))

    @staticmethod
    def _validate_text_budget(
        candidates: tuple[MemoryCandidate, ...],
        existing: tuple[ExistingMemory, ...],
    ) -> None:
        used = sum(
            len(item.subject)
            + len(item.predicate)
            + len(item.value)
            + len(item.source_ref)
            + len(item.evidence)
            for item in candidates
        )
        used += sum(
            len(item.subject) + len(item.predicate) + len(item.value)
            for item in existing
        )
        if used > MAX_CONSOLIDATION_TEXT_CHARS:
            raise MemoryConsolidationError(
                "consolidation input exceeds the hard text budget"
            )

    @staticmethod
    def _validate_existing_state(
        by_key: dict[tuple[str, str], list[ExistingMemory]],
    ) -> None:
        for key, rows in by_key.items():
            if key == _VERBATIM_KEY:
                # Hardened W01 intentionally stores many independent confirmed
                # statements under this generic key. Different values are valid.
                continue
            confirmed_values = {
                item.value for item in rows if item.review_status == "confirmed"
            }
            if len(confirmed_values) > 1:
                raise MemoryConsolidationError(
                    "structured snapshot has ambiguous confirmed state"
                )

    @staticmethod
    def _receipt(actions: list[ConsolidationAction]) -> ConsolidationReceipt:
        counts = {decision: 0 for decision in _DECISIONS}
        touched: set[str] = set()
        for action in actions:
            counts[action.decision] += 1
            if action.existing_id is not None:
                touched.add(action.existing_id)
        return ConsolidationReceipt(
            considered_count=len(actions),
            create_count=counts["create"],
            dedupe_count=counts["dedupe"],
            supersede_count=counts["supersede"],
            skip_count=counts["skip"],
            touched_existing_ids=tuple(sorted(touched)),
            sent_to_store=False,
        )
