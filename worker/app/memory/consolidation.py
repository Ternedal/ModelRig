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


class MemoryConsolidationError(RuntimeError):
    """A Memory 4 candidate batch cannot be planned safely and deterministically."""


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
        if self.decision in {"dedupe", "supersede"} and not self.existing_id:
            raise MemoryConsolidationError(
                "dedupe and supersede actions require a trusted existing id"
            )
        if self.decision in {"create", "skip"} and self.existing_id is not None:
            raise MemoryConsolidationError(
                "create and skip actions cannot carry an existing id"
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
        # Deliberately omit values, evidence and source_ref. The writer consumes
        # the in-process candidate objects; a receipt/debug projection must not
        # become a second memory-value or provenance leak surface.
        return {
            "actions": [
                {
                    "decision": action.decision,
                    "subject": action.candidate.subject,
                    "predicate": action.candidate.predicate,
                    "review_status": action.candidate.review_status,
                    "existing_id": action.existing_id,
                    "reason": action.reason,
                }
                for action in self.actions
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
    if "\x00" in cleaned or len(cleaned) > maximum:
        raise MemoryConsolidationError(f"{name} is outside its hard bound")
    return cleaned


def _bounded_items(values: Iterable[Any], maximum: int, name: str) -> tuple[Any, ...]:
    try:
        rows = tuple(islice(iter(values), maximum + 1))
    except TypeError as exc:
        raise MemoryConsolidationError(f"{name} must be iterable") from exc
    if len(rows) > maximum:
        raise MemoryConsolidationError(f"{name} exceeds {maximum} items")
    return rows


def _validated_candidate(value: Any) -> MemoryCandidate:
    if not isinstance(value, MemoryCandidate):
        raise MemoryConsolidationError(
            "W02 accepts validated MemoryCandidate objects only"
        )

    _clean_text("candidate subject", value.subject, MAX_CANDIDATE_SUBJECT_CHARS)
    _clean_text(
        "candidate predicate", value.predicate, MAX_CANDIDATE_PREDICATE_CHARS
    )
    _clean_text("candidate value", value.value, MAX_CANDIDATE_VALUE_CHARS)
    _clean_text("candidate source_ref", value.source_ref, MAX_SOURCE_REF_CHARS)

    if not isinstance(value.evidence, str):
        raise MemoryConsolidationError("candidate evidence must be text")
    if value.evidence != value.evidence.strip() or "\x00" in value.evidence:
        raise MemoryConsolidationError(
            "candidate evidence must be canonical trimmed text"
        )
    if len(value.evidence) > MAX_CANDIDATE_EVIDENCE_CHARS:
        raise MemoryConsolidationError(
            "candidate evidence exceeds its hard bound"
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
        raise MemoryConsolidationError(
            "candidate review_status is outside the W02 contract"
        )
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

    if value.sensitivity == "secret" and value.review_status != "pending":
        raise MemoryConsolidationError("secret W01 candidates must remain pending")

    if value.review_status == "confirmed":
        # After #1202, this is the *only* automatic confirmed W01 shape. W02
        # revalidates it rather than accepting a dataclass carrying fabricated
        # semantic authority. Structured subject/predicate interpretations remain
        # pending until a separate trusted review boundary exists.
        canonical_confirmed = (
            value.source_type == "user_explicit"
            and value.subject == VERBATIM_USER_SUBJECT
            and value.predicate == VERBATIM_USER_PREDICATE
            and value.kind == "note"
            and value.sensitivity == "private"
            and confidence == 1.0
            and bool(value.evidence)
            and value.value == value.evidence
        )
        if not canonical_confirmed:
            raise MemoryConsolidationError(
                "confirmed candidate violates the W01 verbatim authority shape"
            )
    elif value.source_type == "user_explicit":
        # Partial literal evidence is a valid W01 proposal, but #1202 deliberately
        # keeps it pending because it cannot prove model-generated semantics.
        if not value.evidence or value.value not in value.evidence:
            raise MemoryConsolidationError(
                "pending user_explicit candidate violates the W01 evidence shape"
            )

    return value


def _validated_record(value: Any) -> ExistingMemory:
    try:
        record = ExistingMemory(
            id=_clean_text("existing id", value.id, MAX_RECORD_ID_CHARS),
            subject=_clean_text("existing subject", value.subject, 200),
            predicate=_clean_text("existing predicate", value.predicate, 200),
            value=_clean_text("existing value", value.value, 20_000),
            kind=_clean_text("existing kind", value.kind, 64),
            sensitivity=_clean_text("existing sensitivity", value.sensitivity, 64),
            source_type=_clean_text("existing source_type", value.source_type, 64),
            review_status=_clean_text(
                "existing review_status", value.review_status, 64
            ),
            lifecycle_status=_clean_text(
                "existing lifecycle_status", value.lifecycle_status, 64
            ),
        )
    except AttributeError as exc:
        raise MemoryConsolidationError(
            "existing memory does not implement the record contract"
        ) from exc

    if record.kind not in KINDS:
        raise MemoryConsolidationError("existing memory has invalid kind")
    if record.sensitivity not in SENSITIVITIES:
        raise MemoryConsolidationError("existing memory has invalid sensitivity")
    if record.source_type not in SOURCE_TYPES:
        raise MemoryConsolidationError("existing memory has invalid source_type")
    if record.lifecycle_status != "active":
        raise MemoryConsolidationError(
            "consolidation snapshot may contain active records only"
        )
    if record.review_status not in _REVIEW_STATES:
        raise MemoryConsolidationError(
            "consolidation snapshot may contain pending or confirmed records only"
        )
    if record.sensitivity == "secret":
        raise MemoryConsolidationError(
            "secret memory is outside the W02 consolidation snapshot"
        )
    return record


def _key(subject: str, predicate: str) -> tuple[str, str]:
    # Storage keys are exact strings. Case normalization would be semantic merge
    # authority and cannot be reproduced by the bounded indexed storage lookup
    # without scanning unrelated durable rows.
    return (subject, predicate)


def _candidate_identity(candidate: MemoryCandidate) -> tuple[str, str, str, str, str]:
    return (
        candidate.subject,
        candidate.predicate,
        candidate.value,
        candidate.source_type,
        candidate.review_status,
    )


def _candidate_sort_key(candidate: MemoryCandidate) -> tuple[str, str, str, int, str, str]:
    return (
        candidate.subject,
        candidate.predicate,
        candidate.value,
        0 if candidate.review_status == "confirmed" else 1,
        candidate.source_type,
        candidate.source_ref,
    )


def _is_verbatim_slot(subject: str, predicate: str) -> bool:
    return (
        subject == VERBATIM_USER_SUBJECT
        and predicate == VERBATIM_USER_PREDICATE
    )


class MemoryConsolidator:
    """Build a bounded deterministic W02-A plan without mutating storage.

    W02-A consumes W01 candidates and a trusted active-record snapshot only. It
    may plan create/dedupe/skip plus one narrow supersede: an exact pending copy
    of a canonical W01 verbatim statement may be replaced by that same statement
    at confirmed authority. It never treats different verbatim user turns as
    stale versions of one semantic fact.

    That restriction is intentional. After #1202, W01's only automatically
    confirmed representation is the neutral ``user/verbatim_user_statement``
    note. A generic subject/predicate key can therefore no longer prove that two
    different user utterances are revisions of the same fact. Semantic stale-fact
    replacement requires a later trusted review authority, not another model
    guess.
    """

    def plan(
        self,
        candidates: Iterable[MemoryCandidate],
        existing: Iterable[Any],
    ) -> ConsolidationPlan:
        raw_candidates = _bounded_items(
            candidates,
            MAX_CONSOLIDATION_CANDIDATES,
            "candidate batch",
        )
        raw_existing = _bounded_items(
            existing,
            MAX_CONSOLIDATION_EXISTING,
            "existing snapshot",
        )
        candidate_rows = tuple(
            sorted(
                (_validated_candidate(item) for item in raw_candidates),
                key=_candidate_sort_key,
            )
        )
        existing_rows = tuple(_validated_record(item) for item in raw_existing)
        self._validate_text_budget(candidate_rows, existing_rows)
        self._validate_existing_snapshot(existing_rows)

        by_key: dict[tuple[str, str], list[ExistingMemory]] = {}
        for record in existing_rows:
            by_key.setdefault(_key(record.subject, record.predicate), []).append(record)
        for records in by_key.values():
            records.sort(key=lambda item: item.id)

        actions: list[ConsolidationAction] = []
        seen_candidates: set[tuple[str, str, str, str, str]] = set()

        for candidate in candidate_rows:
            identity = _candidate_identity(candidate)
            if identity in seen_candidates:
                actions.append(
                    ConsolidationAction(
                        decision="skip",
                        candidate=candidate,
                        existing_id=None,
                        reason="duplicate_in_batch",
                    )
                )
                continue
            seen_candidates.add(identity)

            if candidate.sensitivity == "secret":
                actions.append(
                    ConsolidationAction(
                        decision="skip",
                        candidate=candidate,
                        existing_id=None,
                        reason="secret_candidate",
                    )
                )
                continue

            current = by_key.get(_key(candidate.subject, candidate.predicate), [])
            exact = [item for item in current if item.value == candidate.value]
            if exact:
                # W01 non-secret candidates are private. Reusing a less-restrictive
                # public/operational row would silently declassify the new memory.
                if any(item.sensitivity != "private" for item in exact):
                    raise MemoryConsolidationError(
                        "exact durable value is less restrictive than the W01 candidate"
                    )
                exact_confirmed = [
                    item for item in exact if item.review_status == "confirmed"
                ]
                if exact_confirmed:
                    actions.append(
                        ConsolidationAction(
                            decision="dedupe",
                            candidate=candidate,
                            existing_id=exact_confirmed[0].id,
                            reason="existing_confirmed_exact_value",
                        )
                    )
                    continue

                exact_pending = [
                    item for item in exact if item.review_status == "pending"
                ]
                if candidate.review_status == "confirmed":
                    if len(exact_pending) != 1:
                        raise MemoryConsolidationError(
                            "multiple pending exact matches require explicit review"
                        )
                    previous = exact_pending[0]
                    if not _is_verbatim_slot(candidate.subject, candidate.predicate):
                        raise MemoryConsolidationError(
                            "structured pending memory cannot gain confirmed authority in W02"
                        )
                    actions.append(
                        ConsolidationAction(
                            decision="supersede",
                            candidate=candidate,
                            existing_id=previous.id,
                            reason="exact_verbatim_authority_promotion",
                        )
                    )
                    continue

                actions.append(
                    ConsolidationAction(
                        decision="dedupe",
                        candidate=candidate,
                        existing_id=exact_pending[0].id,
                        reason="existing_pending_exact_value",
                    )
                )
                continue

            # No exact durable value exists. Pending structured proposals may be
            # stored later for review. Canonical confirmed statements may also be
            # stored, but a different verbatim statement is NOT a stale value of
            # the same semantic fact merely because it shares the generic slot.
            actions.append(
                ConsolidationAction(
                    decision="create",
                    candidate=candidate,
                    existing_id=None,
                    reason=(
                        "new_confirmed_verbatim_statement"
                        if candidate.review_status == "confirmed"
                        else "new_pending_candidate"
                    ),
                )
            )

        return ConsolidationPlan(
            actions=tuple(actions),
            receipt=self._receipt(actions),
        )

    @staticmethod
    def _validate_text_budget(
        candidates: tuple[MemoryCandidate, ...],
        existing: tuple[ExistingMemory, ...],
    ) -> None:
        used = 0
        for candidate in candidates:
            used += (
                len(candidate.subject)
                + len(candidate.predicate)
                + len(candidate.value)
                + len(candidate.source_ref)
                + len(candidate.evidence)
            )
        for record in existing:
            used += len(record.subject) + len(record.predicate) + len(record.value)
        if used > MAX_CONSOLIDATION_TEXT_CHARS:
            raise MemoryConsolidationError(
                "consolidation input exceeds the hard text budget"
            )

    @staticmethod
    def _validate_existing_snapshot(existing: tuple[ExistingMemory, ...]) -> None:
        ids: set[str] = set()
        by_key: dict[tuple[str, str], list[ExistingMemory]] = {}
        for record in existing:
            if record.id in ids:
                raise MemoryConsolidationError(
                    "consolidation snapshot contains duplicate record ids"
                )
            ids.add(record.id)
            by_key.setdefault(_key(record.subject, record.predicate), []).append(record)

        for key, records in by_key.items():
            # Many distinct confirmed verbatim notes are expected: this key is a
            # statement log, not a semantic singleton slot. For every other key,
            # multiple active confirmed values mean storage is already ambiguous
            # and W02 must not pick a winner.
            if key == _key(VERBATIM_USER_SUBJECT, VERBATIM_USER_PREDICATE):
                continue
            confirmed_values = {
                item.value for item in records if item.review_status == "confirmed"
            }
            if len(confirmed_values) > 1:
                raise MemoryConsolidationError(
                    "existing snapshot has ambiguous confirmed semantic state"
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
