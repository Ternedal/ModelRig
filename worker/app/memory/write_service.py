from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Awaitable, Callable

from .consolidation import (
    MAX_RECORD_ID_CHARS,
    MemoryConsolidationError,
    MemoryConsolidator,
)
from .extraction import (
    CompletedMemoryTurn,
    MemoryCandidate,
    MemoryCandidateExtractor,
    MemoryExtractionError,
)


TURN_WRITE_RECEIPT_SCHEMA = "kaliv-memory-completed-turn-write-receipt/v1"


class MemoryTurnWriteError(RuntimeError):
    """A completed turn could not be persisted inside the Memory 4 write boundary."""


@dataclass(frozen=True)
class DurableCandidateWrite:
    """Storage-neutral projection of one completed W02-B candidate-batch write.

    Storage adapters construct this only after the existing W02-A/W02-B boundary
    has accepted the candidate batch. It deliberately contains ids/counts only;
    values, evidence, source refs, model output and protected payloads have no
    representation here.
    """

    considered_count: int
    created_ids: tuple[str, ...]
    superseded_ids: tuple[str, ...]
    superseding_ids: tuple[str, ...]
    deduped_ids: tuple[str, ...]
    skipped_count: int
    replayed: bool
    sent_to_store: bool


@dataclass(frozen=True)
class CompletedTurnWriteReceipt:
    schema: str
    candidate_count: int
    considered_count: int
    created_ids: tuple[str, ...]
    superseded_ids: tuple[str, ...]
    superseding_ids: tuple[str, ...]
    deduped_ids: tuple[str, ...]
    skipped_count: int
    replayed: bool
    sent_to_store: bool

    @property
    def created_count(self) -> int:
        return len(self.created_ids)

    @property
    def superseded_count(self) -> int:
        return len(self.superseded_ids)

    @property
    def deduped_count(self) -> int:
        return len(self.deduped_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "candidate_count": self.candidate_count,
            "considered_count": self.considered_count,
            "created_count": self.created_count,
            "superseded_count": self.superseded_count,
            "deduped_count": self.deduped_count,
            "skipped_count": self.skipped_count,
            "created_ids": list(self.created_ids),
            "superseded_ids": list(self.superseded_ids),
            "superseding_ids": list(self.superseding_ids),
            "deduped_ids": list(self.deduped_ids),
            "replayed": self.replayed,
            "sent_to_store": self.sent_to_store,
        }


ExtractCandidates = Callable[
    [CompletedMemoryTurn],
    Awaitable[tuple[MemoryCandidate, ...]],
]
CommitCandidates = Callable[
    [tuple[MemoryCandidate, ...]],
    DurableCandidateWrite | Awaitable[DurableCandidateWrite],
]


class MemoryCompletedTurnWriteService:
    """Neutral W03 composition from one completed turn to a durable W02 result.

    The extractor must be a W01-shaped adapter and the committer must be a
    storage-specific W02 composition. This class owns neither model nor storage
    configuration. It validates the completed turn with W01's exact hard bounds
    before the extractor can see it, revalidates the extracted candidate batch
    through W02-A before the committer can see it, then validates the value-free
    durable receipt before exposing a W03 receipt.
    """

    def __init__(
        self,
        *,
        extract: ExtractCandidates,
        commit: CommitCandidates,
    ):
        if not callable(extract):
            raise MemoryTurnWriteError("completed-turn extractor must be callable")
        if not callable(commit):
            raise MemoryTurnWriteError("candidate committer must be callable")
        self._extract = extract
        self._commit = commit

    async def commit_completed_turn(
        self,
        turn: CompletedMemoryTurn,
    ) -> CompletedTurnWriteReceipt:
        if not isinstance(turn, CompletedMemoryTurn):
            raise MemoryTurnWriteError("completed turn has invalid type")

        # Reuse W01's canonical turn validation before an injected extractor gets
        # access to any completed-turn data. Product extraction validates again;
        # the duplicate check is intentional so a faulty adapter cannot widen
        # W01's user/assistant/source_ref bounds.
        try:
            bounded_turn = MemoryCandidateExtractor._validate_turn(turn)
        except MemoryExtractionError as exc:
            raise MemoryTurnWriteError("completed turn is outside W01 bounds") from exc

        try:
            extracted = self._extract(bounded_turn)
            if not inspect.isawaitable(extracted):
                raise MemoryTurnWriteError("completed-turn extractor must be async")
            candidates = await extracted
        except MemoryTurnWriteError:
            raise
        except MemoryExtractionError as exc:
            raise MemoryTurnWriteError("completed-turn extraction failed closed") from exc
        except Exception as exc:
            raise MemoryTurnWriteError("completed-turn extraction failed") from exc

        if not isinstance(candidates, tuple):
            raise MemoryTurnWriteError("W01 extractor must return a candidate tuple")

        # W02-A is the second authority/bounds check. This validation-only plan
        # sees no durable rows and is intentionally discarded; the storage adapter
        # replans against a fresh bounded snapshot under its existing write lock.
        try:
            MemoryConsolidator().plan(candidates, ())
        except MemoryConsolidationError as exc:
            raise MemoryTurnWriteError(
                "W01 candidates are outside the W02 authority boundary"
            ) from exc

        if not candidates:
            return CompletedTurnWriteReceipt(
                schema=TURN_WRITE_RECEIPT_SCHEMA,
                candidate_count=0,
                considered_count=0,
                created_ids=(),
                superseded_ids=(),
                superseding_ids=(),
                deduped_ids=(),
                skipped_count=0,
                replayed=False,
                sent_to_store=False,
            )

        try:
            durable = self._commit(candidates)
            if inspect.isawaitable(durable):
                durable = await durable
        except MemoryTurnWriteError:
            raise
        except Exception as exc:
            raise MemoryTurnWriteError("candidate batch write failed closed") from exc

        validated = self._validate_durable_write(durable, len(candidates))
        return CompletedTurnWriteReceipt(
            schema=TURN_WRITE_RECEIPT_SCHEMA,
            candidate_count=len(candidates),
            considered_count=validated.considered_count,
            created_ids=validated.created_ids,
            superseded_ids=validated.superseded_ids,
            superseding_ids=validated.superseding_ids,
            deduped_ids=validated.deduped_ids,
            skipped_count=validated.skipped_count,
            replayed=validated.replayed,
            sent_to_store=validated.sent_to_store,
        )

    @classmethod
    def _validate_durable_write(
        cls,
        value: object,
        candidate_count: int,
    ) -> DurableCandidateWrite:
        if not isinstance(value, DurableCandidateWrite):
            raise MemoryTurnWriteError(
                "candidate committer returned an invalid durable receipt"
            )
        if isinstance(value.considered_count, bool) or not isinstance(
            value.considered_count, int
        ):
            raise MemoryTurnWriteError("durable considered_count is invalid")
        if value.considered_count != candidate_count:
            raise MemoryTurnWriteError(
                "durable receipt does not cover the extracted candidate batch"
            )
        if (
            isinstance(value.skipped_count, bool)
            or not isinstance(value.skipped_count, int)
            or value.skipped_count < 0
        ):
            raise MemoryTurnWriteError("durable skipped_count is invalid")
        if not isinstance(value.replayed, bool) or not isinstance(
            value.sent_to_store, bool
        ):
            raise MemoryTurnWriteError("durable receipt boolean fields are invalid")
        if not value.sent_to_store:
            raise MemoryTurnWriteError(
                "non-empty candidate batch must cross the W02 store boundary"
            )

        created = cls._validated_ids("created_ids", value.created_ids)
        superseded = cls._validated_ids("superseded_ids", value.superseded_ids)
        superseding = cls._validated_ids("superseding_ids", value.superseding_ids)
        deduped = cls._validated_ids("deduped_ids", value.deduped_ids)

        if len(superseded) != len(superseding):
            raise MemoryTurnWriteError("durable supersede receipt is unbalanced")
        if not set(superseding).issubset(set(created)):
            raise MemoryTurnWriteError(
                "durable superseding ids must be part of created ids"
            )
        if set(created) & set(superseded):
            raise MemoryTurnWriteError("durable created/superseded ids overlap")
        if set(created) & set(deduped):
            raise MemoryTurnWriteError("durable created/deduped ids overlap")
        if set(superseded) & set(deduped):
            raise MemoryTurnWriteError("durable superseded/deduped ids overlap")
        if value.replayed and (created or superseded or superseding):
            raise MemoryTurnWriteError("replayed durable write cannot report mutations")

        # W02-B counts one supersede action as one created replacement plus a
        # predecessor lifecycle transition. Therefore created+deduped+skipped is
        # the action partition; superseded_count is descriptive, not additive.
        if len(created) + len(deduped) + value.skipped_count != candidate_count:
            raise MemoryTurnWriteError(
                "durable receipt action counts do not cover the candidate batch"
            )

        return DurableCandidateWrite(
            considered_count=value.considered_count,
            created_ids=created,
            superseded_ids=superseded,
            superseding_ids=superseding,
            deduped_ids=deduped,
            skipped_count=value.skipped_count,
            replayed=value.replayed,
            sent_to_store=value.sent_to_store,
        )

    @staticmethod
    def _validated_ids(name: str, value: object) -> tuple[str, ...]:
        if not isinstance(value, tuple):
            raise MemoryTurnWriteError(f"durable {name} must be a tuple")
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            if (
                not isinstance(item, str)
                or not item
                or item != item.strip()
                or "\x00" in item
                or len(item) > MAX_RECORD_ID_CHARS
            ):
                raise MemoryTurnWriteError(f"durable {name} contains an invalid id")
            if item in seen:
                raise MemoryTurnWriteError(f"durable {name} contains duplicate ids")
            seen.add(item)
            result.append(item)
        return tuple(result)
