from __future__ import annotations

import inspect
import json
import math
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


MEMORY_CANDIDATE_SCHEMA = "kaliv-memory-candidates/v1"
MAX_COMPLETED_TURN_CHARS = 16_000
MAX_SOURCE_REF_CHARS = 1_000
MAX_MODEL_OUTPUT_CHARS = 64_000
MAX_MEMORY_CANDIDATES = 16
MAX_CANDIDATE_SUBJECT_CHARS = 200
MAX_CANDIDATE_PREDICATE_CHARS = 200
MAX_CANDIDATE_VALUE_CHARS = 4_000
MAX_CANDIDATE_EVIDENCE_CHARS = 4_000

KINDS = {"fact", "preference", "project", "relationship", "routine", "constraint", "note"}
SENSITIVITIES = {"public", "operational", "private", "secret"}
SOURCE_TYPES = {"user_explicit", "tool_observation", "imported", "inferred"}


class MemoryExtractionError(RuntimeError):
    """A completed turn could not produce a bounded trustworthy candidate batch."""


@dataclass(frozen=True)
class CompletedMemoryTurn:
    user_text: str
    assistant_text: str
    source_ref: str


@dataclass(frozen=True)
class MemoryCandidate:
    subject: str
    predicate: str
    value: str
    kind: str
    sensitivity: str
    source_type: str
    source_ref: str
    confidence: float
    review_status: str
    evidence: str

    def store_fields(self) -> dict[str, Any]:
        """Project only fields accepted by the existing create-only memory path.

        W01 deliberately has no id, supersede target, correction token or delete
        authority. A later persistence composition may pass this mapping to the
        existing create operation, but cannot use it to overwrite durable state.
        """
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "value": self.value,
            "kind": self.kind,
            "sensitivity": self.sensitivity,
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "confidence": self.confidence,
            "review_status": self.review_status,
        }


ExtractorCall = Callable[[CompletedMemoryTurn], Awaitable[str]]


class MemoryCandidateExtractor:
    """Model-independent authority boundary for Memory 4.0 candidate extraction.

    The supplied extractor may propose data only. This class owns all authority
    fields that matter to durable memory: provenance is validated, source_ref is
    supplied by the caller, and review_status is derived locally. The extractor
    cannot return ids, supersede targets or a write/correction/delete operation.
    """

    _TOP_LEVEL_KEYS = {"schema", "candidates"}
    _CANDIDATE_KEYS = {
        "subject",
        "predicate",
        "value",
        "kind",
        "sensitivity",
        "source_type",
        "confidence",
        "evidence",
    }

    def __init__(self, *, extract: ExtractorCall):
        if not callable(extract):
            raise MemoryExtractionError("candidate extractor must be callable")
        self._extract = extract

    async def extract(self, turn: CompletedMemoryTurn) -> tuple[MemoryCandidate, ...]:
        bounded_turn = self._validate_turn(turn)
        try:
            response = self._extract(bounded_turn)
            if not inspect.isawaitable(response):
                raise MemoryExtractionError("candidate extractor must be async")
            raw = await response
        except MemoryExtractionError:
            raise
        except Exception as exc:
            raise MemoryExtractionError("candidate extraction failed") from exc
        return self._parse_output(raw, bounded_turn)

    @classmethod
    def _validate_turn(cls, turn: CompletedMemoryTurn) -> CompletedMemoryTurn:
        if not isinstance(turn, CompletedMemoryTurn):
            raise MemoryExtractionError("completed turn has invalid type")
        user_text = cls._clean_text(
            "user_text",
            turn.user_text,
            MAX_COMPLETED_TURN_CHARS,
        )
        assistant_text = cls._clean_text(
            "assistant_text",
            turn.assistant_text,
            MAX_COMPLETED_TURN_CHARS,
        )
        source_ref = cls._clean_text(
            "source_ref",
            turn.source_ref,
            MAX_SOURCE_REF_CHARS,
        )
        return CompletedMemoryTurn(
            user_text=user_text,
            assistant_text=assistant_text,
            source_ref=source_ref,
        )

    @classmethod
    def _parse_output(
        cls,
        raw: Any,
        turn: CompletedMemoryTurn,
    ) -> tuple[MemoryCandidate, ...]:
        if not isinstance(raw, str):
            raise MemoryExtractionError("candidate extractor returned non-text output")
        if len(raw) > MAX_MODEL_OUTPUT_CHARS:
            raise MemoryExtractionError("candidate extractor output exceeds hard bound")
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MemoryExtractionError("candidate extractor returned invalid JSON") from exc
        if not isinstance(document, dict) or set(document) != cls._TOP_LEVEL_KEYS:
            raise MemoryExtractionError("candidate document has invalid fields")
        if document.get("schema") != MEMORY_CANDIDATE_SCHEMA:
            raise MemoryExtractionError("candidate document has unsupported schema")
        rows = document.get("candidates")
        if not isinstance(rows, list):
            raise MemoryExtractionError("candidate document candidates must be a list")
        if len(rows) > MAX_MEMORY_CANDIDATES:
            raise MemoryExtractionError(
                f"candidate document exceeds {MAX_MEMORY_CANDIDATES} candidates"
            )

        result: list[MemoryCandidate] = []
        seen: set[tuple[str, str, str, str]] = set()
        for row in rows:
            candidate = cls._candidate(row, turn)
            identity = (
                candidate.subject.casefold(),
                candidate.predicate.casefold(),
                candidate.value,
                candidate.source_type,
            )
            if identity in seen:
                raise MemoryExtractionError("candidate document contains duplicate candidates")
            seen.add(identity)
            result.append(candidate)
        return tuple(result)

    @classmethod
    def _candidate(cls, raw: Any, turn: CompletedMemoryTurn) -> MemoryCandidate:
        if not isinstance(raw, dict) or set(raw) != cls._CANDIDATE_KEYS:
            raise MemoryExtractionError("candidate has invalid fields")
        subject = cls._clean_text(
            "candidate subject",
            raw.get("subject"),
            MAX_CANDIDATE_SUBJECT_CHARS,
        )
        predicate = cls._clean_text(
            "candidate predicate",
            raw.get("predicate"),
            MAX_CANDIDATE_PREDICATE_CHARS,
        )
        value = cls._clean_text(
            "candidate value",
            raw.get("value"),
            MAX_CANDIDATE_VALUE_CHARS,
        )
        kind = cls._choice("candidate kind", raw.get("kind"), KINDS)
        sensitivity = cls._choice(
            "candidate sensitivity",
            raw.get("sensitivity"),
            SENSITIVITIES,
        )
        source_type = cls._choice(
            "candidate source_type",
            raw.get("source_type"),
            SOURCE_TYPES,
        )
        confidence = cls._confidence(raw.get("confidence"))
        evidence = cls._evidence(raw.get("evidence"))

        # The model never decides review authority. A user_explicit candidate can
        # be confirmed only when both its evidence and exact value are literal
        # substrings of the completed user turn. This intentionally sacrifices
        # recall for authority: normalized/paraphrased/model-inferred values stay
        # pending. Secret candidates are also review-pending even when explicit.
        review_status = "pending"
        if source_type == "user_explicit":
            if not evidence:
                raise MemoryExtractionError(
                    "user_explicit candidate requires exact user evidence"
                )
            if evidence not in turn.user_text:
                raise MemoryExtractionError(
                    "user_explicit evidence is not present in the completed user turn"
                )
            if value not in evidence:
                raise MemoryExtractionError(
                    "user_explicit value is not present in its exact user evidence"
                )
            if sensitivity != "secret":
                review_status = "confirmed"

        return MemoryCandidate(
            subject=subject,
            predicate=predicate,
            value=value,
            kind=kind,
            sensitivity=sensitivity,
            source_type=source_type,
            source_ref=turn.source_ref,
            confidence=confidence,
            review_status=review_status,
            evidence=evidence,
        )

    @staticmethod
    def _clean_text(name: str, value: Any, maximum: int) -> str:
        if not isinstance(value, str):
            raise MemoryExtractionError(f"{name} must be text")
        cleaned = value.strip()
        if not cleaned:
            raise MemoryExtractionError(f"{name} must not be empty")
        if len(cleaned) > maximum:
            raise MemoryExtractionError(f"{name} exceeds {maximum} characters")
        return cleaned

    @staticmethod
    def _evidence(value: Any) -> str:
        if not isinstance(value, str):
            raise MemoryExtractionError("candidate evidence must be text")
        cleaned = value.strip()
        if len(cleaned) > MAX_CANDIDATE_EVIDENCE_CHARS:
            raise MemoryExtractionError(
                f"candidate evidence exceeds {MAX_CANDIDATE_EVIDENCE_CHARS} characters"
            )
        return cleaned

    @staticmethod
    def _choice(name: str, value: Any, allowed: set[str]) -> str:
        if not isinstance(value, str) or value not in allowed:
            raise MemoryExtractionError(f"invalid {name}: {value!r}")
        return value

    @staticmethod
    def _confidence(value: Any) -> float:
        if isinstance(value, bool):
            raise MemoryExtractionError("candidate confidence must be numeric")
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise MemoryExtractionError("candidate confidence must be numeric") from exc
        if not math.isfinite(parsed) or not 0.0 <= parsed <= 1.0:
            raise MemoryExtractionError("candidate confidence must be finite and between 0 and 1")
        return parsed
