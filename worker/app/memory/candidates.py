from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from typing import Any


CANDIDATE_SCHEMA = "kaliv-memory-candidates/v1"
CONFIRMED_VERBATIM_PREDICATE = "verbatim_user_statement"
MAX_TURN_CHARS = 20_000
MAX_EXTRACTOR_RESPONSE_BYTES = 32 * 1024
MAX_MEMORY_CANDIDATES = 8
MAX_CANDIDATE_VALUE_CHARS = 2_000
MAX_CANDIDATE_EVIDENCE_CHARS = 2_000

_ALLOWED_KINDS = frozenset(
    {"fact", "preference", "project", "relationship", "routine", "constraint", "note"}
)
_ALLOWED_SENSITIVITIES = frozenset({"public", "operational", "private"})
_ALLOWED_SOURCE_TYPES = frozenset(
    {"user_explicit", "tool_observation", "imported", "inferred"}
)
_TOP_LEVEL_KEYS = frozenset({"schema", "candidates"})
_CANDIDATE_KEYS = frozenset(
    {
        "subject",
        "predicate",
        "value",
        "kind",
        "sensitivity",
        "source_type",
        "confidence",
        "evidence",
    }
)


class MemoryCandidateError(ValueError):
    """Extractor input/output failed the Memory 4 candidate authority boundary."""


@dataclass(frozen=True)
class CompletedTurn:
    user_text: str
    assistant_text: str


@dataclass(frozen=True)
class MemoryCandidate:
    subject: str
    predicate: str
    value: str
    kind: str
    sensitivity: str
    source_type: str
    confidence: float
    evidence: str
    review_status: str
    grounding: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateBatch:
    schema: str
    candidates: tuple[MemoryCandidate, ...]

    @property
    def confirmed_count(self) -> int:
        return sum(candidate.review_status == "confirmed" for candidate in self.candidates)

    @property
    def pending_count(self) -> int:
        return sum(candidate.review_status == "pending" for candidate in self.candidates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "confirmed_count": self.confirmed_count,
            "pending_count": self.pending_count,
        }


def prepare_completed_turn(user_text: str, assistant_text: str) -> CompletedTurn:
    """Validate one completed chat turn before any extractor/model call.

    The texts remain exact user/model data after validation. We do not normalize
    whitespace because W01A later proves explicit-memory grounding by exact
    substring membership in the original user turn.
    """
    return CompletedTurn(
        user_text=_bounded_turn_text("user_text", user_text),
        assistant_text=_bounded_turn_text("assistant_text", assistant_text),
    )


def parse_candidate_batch(raw: str | bytes, *, turn: CompletedTurn) -> CandidateBatch:
    """Parse untrusted extractor output and derive review authority server-side.

    The extractor may propose structured semantics, but it never supplies
    ``review_status``. W01A grants confirmed authority only to a canonical,
    complete verbatim user statement. For that case the server deliberately
    discards model-generated predicate/kind/sensitivity/confidence semantics and
    stores a conservative private verbatim note. All structured interpretations
    remain pending for review.
    """
    if not isinstance(turn, CompletedTurn):
        raise MemoryCandidateError("turn must be a validated CompletedTurn")
    if isinstance(raw, str):
        payload = raw.encode("utf-8")
    elif isinstance(raw, bytes):
        payload = raw
    else:
        raise MemoryCandidateError("extractor response must be UTF-8 text")
    if len(payload) > MAX_EXTRACTOR_RESPONSE_BYTES:
        raise MemoryCandidateError("extractor response exceeds byte bound")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MemoryCandidateError("extractor response must be valid UTF-8") from exc

    data = _strict_json_object(text)
    if set(data) != _TOP_LEVEL_KEYS:
        raise MemoryCandidateError("extractor response top-level shape is invalid")
    if data.get("schema") != CANDIDATE_SCHEMA:
        raise MemoryCandidateError("extractor response schema mismatch")
    rows = data.get("candidates")
    if not isinstance(rows, list):
        raise MemoryCandidateError("extractor candidates must be a list")
    if len(rows) > MAX_MEMORY_CANDIDATES:
        raise MemoryCandidateError(
            f"extractor returned more than {MAX_MEMORY_CANDIDATES} candidates"
        )

    candidates: list[MemoryCandidate] = []
    identities: set[tuple[str, str, str, str]] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != _CANDIDATE_KEYS:
            raise MemoryCandidateError(f"candidate {index} shape is invalid")
        candidate = _candidate_from_row(row, turn=turn, index=index)
        identity = (
            candidate.subject,
            candidate.predicate,
            candidate.value,
            candidate.source_type,
        )
        if identity in identities:
            raise MemoryCandidateError("extractor returned duplicate candidates")
        identities.add(identity)
        candidates.append(candidate)

    return CandidateBatch(schema=CANDIDATE_SCHEMA, candidates=tuple(candidates))


def _candidate_from_row(
    row: dict[str, Any], *, turn: CompletedTurn, index: int
) -> MemoryCandidate:
    subject = _clean_text(f"candidate {index} subject", row["subject"], 200)
    proposed_predicate = _clean_text(
        f"candidate {index} predicate", row["predicate"], 200
    )
    value = _clean_text(
        f"candidate {index} value",
        row["value"],
        MAX_CANDIDATE_VALUE_CHARS,
        allow_newlines=True,
    )
    evidence = _clean_text(
        f"candidate {index} evidence",
        row["evidence"],
        MAX_CANDIDATE_EVIDENCE_CHARS,
        allow_newlines=True,
    )
    proposed_kind = _choice(
        f"candidate {index} kind", row["kind"], _ALLOWED_KINDS
    )
    proposed_sensitivity = _choice(
        f"candidate {index} sensitivity",
        row["sensitivity"],
        _ALLOWED_SENSITIVITIES,
    )
    source_type = _choice(
        f"candidate {index} source_type",
        row["source_type"],
        _ALLOWED_SOURCE_TYPES,
    )
    proposed_confidence = _confidence(row["confidence"], index=index)

    # Exact text alone cannot validate model-generated semantics. Without this
    # boundary, "I live in Copenhagen" plus a hallucinated predicate such as
    # "favorite_city" could become a confirmed false fact merely because the
    # value "Copenhagen" was verbatim. Confirmation therefore requires one
    # complete canonical span (value == evidence) copied exactly from the user
    # turn. The server then replaces every semantic/model-owned field that could
    # change the meaning or data classification with conservative constants.
    verbatim_statement = (
        source_type == "user_explicit"
        and subject == "user"
        and row["value"] == value
        and row["evidence"] == evidence
        and value == evidence
        and value in turn.user_text
    )

    if verbatim_statement:
        predicate = CONFIRMED_VERBATIM_PREDICATE
        kind = "note"
        sensitivity = "private"
        confidence = 1.0
        review_status = "confirmed"
        grounding = "verbatim_user"
    else:
        predicate = proposed_predicate
        kind = proposed_kind
        sensitivity = proposed_sensitivity
        confidence = proposed_confidence
        review_status = "pending"
        grounding = "unverified"

    return MemoryCandidate(
        subject=subject,
        predicate=predicate,
        value=value,
        kind=kind,
        sensitivity=sensitivity,
        source_type=source_type,
        confidence=confidence,
        evidence=evidence,
        review_status=review_status,
        grounding=grounding,
    )


def _strict_json_object(text: str) -> dict[str, Any]:
    duplicates: list[str] = []

    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                duplicates.append(key)
            result[key] = value
        return result

    try:
        value = json.loads(text, object_pairs_hook=hook)
    except json.JSONDecodeError as exc:
        raise MemoryCandidateError("extractor response is not strict JSON") from exc
    if duplicates:
        raise MemoryCandidateError("extractor response contains duplicate JSON keys")
    if not isinstance(value, dict):
        raise MemoryCandidateError("extractor response must be a JSON object")
    return value


def _bounded_turn_text(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise MemoryCandidateError(f"{name} must be text")
    if not value.strip():
        raise MemoryCandidateError(f"{name} must not be empty")
    if "\x00" in value:
        raise MemoryCandidateError(f"{name} contains NUL")
    if len(value) > MAX_TURN_CHARS:
        raise MemoryCandidateError(f"{name} exceeds {MAX_TURN_CHARS} characters")
    return value


def _clean_text(
    name: str,
    value: Any,
    maximum: int,
    *,
    allow_newlines: bool = False,
) -> str:
    if not isinstance(value, str):
        raise MemoryCandidateError(f"{name} must be text")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum or "\x00" in cleaned:
        raise MemoryCandidateError(f"{name} is invalid")
    if not allow_newlines and any(character in cleaned for character in ("\r", "\n")):
        raise MemoryCandidateError(f"{name} must be single-line text")
    return cleaned


def _choice(name: str, value: Any, choices: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise MemoryCandidateError(f"{name} is invalid")
    return value


def _confidence(value: Any, *, index: int) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MemoryCandidateError(f"candidate {index} confidence is invalid")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0 or parsed > 1.0:
        raise MemoryCandidateError(f"candidate {index} confidence is invalid")
    return parsed
