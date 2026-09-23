"""C26-C privacy-safe Memory 4 recall attention.

A validated MemoryContextSnapshot may become one bounded memory_recall event.
The event never carries recalled text or individual memory ids.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .experience import MemoryContextSnapshot
from .supervisor import CognitionEvent, clock_sample_ref
from .temporal import ClockSample


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
MEMORY_RECALL_SALIENCE = 0.90


class MemoryRecallAttentionError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class MemoryRecallPlan(StrictModel):
    schema: Literal["kaliv-consciousness-core/memory-recall-plan/v1"]
    snapshot_ref: NonEmptyRef
    context_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    included_count: Annotated[int, Field(ge=0, le=50, strict=True)]
    clock_sample_ref: NonEmptyRef | None
    cognition_event: CognitionEvent | None
    model_calls: Literal[0]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "MemoryRecallPlan":
        if self.included_count == 0:
            if self.cognition_event is not None or self.clock_sample_ref is not None:
                raise ValueError(
                    "empty memory recall cannot create attention or consume clock binding"
                )
        else:
            if self.cognition_event is None or self.clock_sample_ref is None:
                raise ValueError(
                    "non-empty memory recall requires clock-bound attention"
                )
            if self.cognition_event.kind != "memory_recall":
                raise ValueError("memory recall attention has wrong event kind")
        return self


class MemoryRecallAdmissionResult(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/memory-recall-admission/v1"
    ]
    plan: MemoryRecallPlan
    cognition_event_admitted: bool
    supervisor_revision_before: Annotated[int, Field(ge=1, strict=True)]
    supervisor_revision_after: Annotated[int, Field(ge=1, strict=True)]
    model_calls: Literal[0]
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def admission_shape(self) -> "MemoryRecallAdmissionResult":
        has_event = self.plan.cognition_event is not None
        if self.cognition_event_admitted != has_event:
            raise ValueError("memory recall admission/event presence mismatch")
        delta = self.supervisor_revision_after - self.supervisor_revision_before
        if has_event:
            if delta not in {0, 1}:
                raise ValueError(
                    "memory recall admission may be idempotent or advance once"
                )
        elif delta != 0:
            raise ValueError(
                "empty memory recall cannot change supervisor revision"
            )
        return self


def _canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _validate_snapshot(
    snapshot: MemoryContextSnapshot | Mapping[str, Any],
) -> MemoryContextSnapshot:
    try:
        value = (
            snapshot
            if isinstance(snapshot, MemoryContextSnapshot)
            else MemoryContextSnapshot.model_validate(snapshot)
        )
    except ValidationError as exc:
        raise MemoryRecallAttentionError(
            "invalid MemoryContextSnapshot"
        ) from exc

    context_bytes = value.context.encode("utf-8")
    digest = hashlib.sha256(context_bytes).hexdigest()
    if digest != value.context_sha256:
        raise MemoryRecallAttentionError(
            "MemoryContextSnapshot context hash mismatch"
        )
    if len(value.context) != value.character_count:
        raise MemoryRecallAttentionError(
            "MemoryContextSnapshot character count mismatch"
        )
    if len(context_bytes) != value.byte_count:
        raise MemoryRecallAttentionError(
            "MemoryContextSnapshot byte count mismatch"
        )
    if value.source_ref != f"memory4-context:{value.context_sha256}":
        raise MemoryRecallAttentionError(
            "MemoryContextSnapshot source ref/hash mismatch"
        )

    has_ids = bool(value.included_ids)
    has_context = bool(value.context)
    if has_ids != has_context:
        raise MemoryRecallAttentionError(
            "MemoryContextSnapshot ids/context emptiness mismatch"
        )
    return value


def memory_context_snapshot_ref(
    snapshot: MemoryContextSnapshot | Mapping[str, Any],
) -> str:
    value = _validate_snapshot(snapshot)
    return "memory-context-snapshot:" + hashlib.sha256(
        _canonical_json(value)
    ).hexdigest()


def memory_recall_snapshot_has_items(
    snapshot: MemoryContextSnapshot | Mapping[str, Any],
) -> bool:
    return bool(_validate_snapshot(snapshot).included_ids)


def _memory_recall_source_ref(
    *,
    snapshot_ref: str,
    clock_ref: str,
) -> str:
    return "memory-recall:" + hashlib.sha256(
        _canonical_json(
            {
                "snapshot_ref": snapshot_ref,
                "clock_sample_ref": clock_ref,
            }
        )
    ).hexdigest()


def plan_memory_recall(
    *,
    snapshot: MemoryContextSnapshot | Mapping[str, Any],
    clock: ClockSample | Mapping[str, Any] | None = None,
) -> MemoryRecallPlan:
    """Create bounded attention metadata; never copy recalled text into event."""
    value = _validate_snapshot(snapshot)
    snapshot_ref = memory_context_snapshot_ref(value)
    included_count = len(value.included_ids)

    if included_count == 0:
        if clock is not None:
            raise MemoryRecallAttentionError(
                "empty memory recall must be planned without clock sample"
            )
        return MemoryRecallPlan(
            schema="kaliv-consciousness-core/memory-recall-plan/v1",
            snapshot_ref=snapshot_ref,
            context_sha256=value.context_sha256,
            included_count=0,
            clock_sample_ref=None,
            cognition_event=None,
            model_calls=0,
            production_activation=False,
        )

    if clock is None:
        raise MemoryRecallAttentionError(
            "non-empty memory recall requires trusted ClockSample"
        )
    try:
        sample = (
            clock
            if isinstance(clock, ClockSample)
            else ClockSample.model_validate(clock)
        )
    except ValidationError as exc:
        raise MemoryRecallAttentionError("invalid ClockSample") from exc

    clock_ref = clock_sample_ref(sample)
    source_ref = _memory_recall_source_ref(
        snapshot_ref=snapshot_ref,
        clock_ref=clock_ref,
    )
    event_id = "cevt-" + hashlib.sha256(
        ("memory-recall-v1|" + source_ref).encode("utf-8")
    ).hexdigest()[:32]
    event = CognitionEvent(
        schema="kaliv-consciousness-core/cognition-event/v1",
        event_id=event_id,
        kind="memory_recall",
        source_ref=source_ref,
        summary=(
            f"Memory 4 returned {included_count} verified reference-data "
            f"item(s) for {value.target} recall; recalled text and item ids "
            "remain outside this attention event and were not sent to the model."
        ),
        salience=MEMORY_RECALL_SALIENCE,
        observed_sequence=sample.sampled_sequence,
        production_activation=False,
    )
    return MemoryRecallPlan(
        schema="kaliv-consciousness-core/memory-recall-plan/v1",
        snapshot_ref=snapshot_ref,
        context_sha256=value.context_sha256,
        included_count=included_count,
        clock_sample_ref=clock_ref,
        cognition_event=event,
        model_calls=0,
        production_activation=False,
    )
