"""C29-E bounded process-local post-wake continuity state.

This is descriptive temporal continuity evidence only. It does not persist a
new memory, invent crash time, schedule cognition, or grant execution authority.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .sleep import WakeReceipt


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
NonNegativeInt = Annotated[int, Field(ge=0, strict=True)]
UnitInterval = Annotated[
    float,
    Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False),
]

ContinuityKnowledge = Literal[
    "PLANNED_EXACT",
    "PLANNED_UNKNOWN",
    "UNPLANNED_BOUNDED",
    "UNPLANNED_UNBOUNDED",
]


class ContinuityStateError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class PostWakeContinuityState(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/post-wake-continuity-state/v1"
    ]
    continuity_id: Annotated[
        str,
        Field(pattern=r"^continuity-[a-f0-9]{32}$"),
    ]
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_revision: Annotated[
        str,
        Field(pattern=r"^person-r[0-9]{4,}$"),
    ]
    wake_receipt_ref: NonEmptyRef
    dormancy_kind: Literal["PLANNED_SLEEP", "UNPLANNED_DORMANCY"]
    knowledge: ContinuityKnowledge
    exact_offline_duration_ms: NonNegativeInt | None
    offline_duration_upper_bound_ms: NonNegativeInt | None
    duration_confidence: UnitInterval
    last_known_alive_witness_ref: NonEmptyRef | None
    last_known_alive_anchor_ref: NonEmptyRef | None
    continuity_preserved: Literal[True]
    cognition_during_gap: Literal[False]
    crash_timestamp_claimed: Literal[False]
    self_state_store_write_applied: Literal[False]
    model_calls: Literal[0]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_semantics(self) -> "PostWakeContinuityState":
        refs = (
            self.last_known_alive_witness_ref is not None,
            self.last_known_alive_anchor_ref is not None,
        )
        if refs[0] != refs[1]:
            raise ValueError(
                "last-known-alive witness/anchor refs must be paired"
            )

        if self.knowledge == "PLANNED_EXACT":
            if (
                self.dormancy_kind != "PLANNED_SLEEP"
                or self.exact_offline_duration_ms is None
                or self.offline_duration_upper_bound_ms is not None
                or any(refs)
            ):
                raise ValueError("PLANNED_EXACT continuity shape is invalid")
        elif self.knowledge == "PLANNED_UNKNOWN":
            if (
                self.dormancy_kind != "PLANNED_SLEEP"
                or self.exact_offline_duration_ms is not None
                or self.offline_duration_upper_bound_ms is not None
                or any(refs)
                or self.duration_confidence != 0.0
            ):
                raise ValueError("PLANNED_UNKNOWN continuity shape is invalid")
        elif self.knowledge == "UNPLANNED_BOUNDED":
            if (
                self.dormancy_kind != "UNPLANNED_DORMANCY"
                or self.exact_offline_duration_ms is not None
                or self.offline_duration_upper_bound_ms is None
                or not all(refs)
                or self.duration_confidence <= 0.0
            ):
                raise ValueError(
                    "UNPLANNED_BOUNDED continuity shape is invalid"
                )
        else:
            if (
                self.dormancy_kind != "UNPLANNED_DORMANCY"
                or self.exact_offline_duration_ms is not None
                or self.offline_duration_upper_bound_ms is not None
                or self.duration_confidence != 0.0
            ):
                raise ValueError(
                    "UNPLANNED_UNBOUNDED continuity shape is invalid"
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


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def post_wake_continuity_state_ref(
    state: PostWakeContinuityState,
) -> str:
    if not isinstance(state, PostWakeContinuityState):
        raise TypeError("state must be PostWakeContinuityState")
    return "post-wake-continuity-state:" + _digest(state)


def _wake_ref(wake: WakeReceipt) -> str:
    return "wake-receipt:" + _digest(wake)


def build_post_wake_continuity_state(
    wake_receipt: WakeReceipt | Mapping[str, Any],
    *,
    expected_self_id: str,
    expected_person_revision: str,
) -> PostWakeContinuityState:
    """Project one authenticated wake into bounded continuity knowledge."""
    try:
        wake = (
            wake_receipt
            if isinstance(wake_receipt, WakeReceipt)
            else WakeReceipt.model_validate(wake_receipt)
        )
    except ValidationError as exc:
        raise ContinuityStateError("invalid WakeReceipt") from exc

    if wake.self_id != expected_self_id:
        raise ContinuityStateError("WakeReceipt belongs to another self")
    if wake.person_revision != expected_person_revision:
        raise ContinuityStateError(
            "WakeReceipt belongs to another Person Revision"
        )
    if wake.cognition_during_gap is not False:
        raise ContinuityStateError(
            "WakeReceipt may not claim cognition during the gap"
        )

    exact_duration = None
    upper_bound = None
    confidence = 0.0

    if wake.dormancy_kind == "PLANNED_SLEEP":
        if wake.duration_known:
            if wake.offline_duration_ms is None:
                raise ContinuityStateError(
                    "known planned duration is missing exact duration"
                )
            knowledge: ContinuityKnowledge = "PLANNED_EXACT"
            exact_duration = wake.offline_duration_ms
            confidence = wake.duration_confidence
        else:
            if wake.offline_duration_ms is not None:
                raise ContinuityStateError(
                    "unknown planned duration cannot carry exact duration"
                )
            knowledge = "PLANNED_UNKNOWN"
    else:
        if wake.duration_known or wake.offline_duration_ms is not None:
            raise ContinuityStateError(
                "unplanned dormancy cannot claim exact offline duration"
            )
        if wake.offline_duration_upper_bound_ms is not None:
            knowledge = "UNPLANNED_BOUNDED"
            upper_bound = wake.offline_duration_upper_bound_ms
            confidence = wake.offline_duration_upper_bound_confidence
        else:
            knowledge = "UNPLANNED_UNBOUNDED"

    wake_ref = _wake_ref(wake)
    seed = {
        "wake_receipt_ref": wake_ref,
        "knowledge": knowledge,
        "exact_offline_duration_ms": exact_duration,
        "offline_duration_upper_bound_ms": upper_bound,
        "kind": "post-wake-continuity-v1",
    }
    return PostWakeContinuityState(
        schema=(
            "kaliv-consciousness-core/post-wake-continuity-state/v1"
        ),
        continuity_id="continuity-" + _digest(seed)[:32],
        self_id=wake.self_id,
        person_revision=wake.person_revision,
        wake_receipt_ref=wake_ref,
        dormancy_kind=wake.dormancy_kind,
        knowledge=knowledge,
        exact_offline_duration_ms=exact_duration,
        offline_duration_upper_bound_ms=upper_bound,
        duration_confidence=confidence,
        last_known_alive_witness_ref=(
            wake.last_known_alive_witness_ref
        ),
        last_known_alive_anchor_ref=wake.last_known_alive_anchor_ref,
        continuity_preserved=True,
        cognition_during_gap=False,
        crash_timestamp_claimed=False,
        self_state_store_write_applied=False,
        model_calls=0,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        production_activation=False,
    )
