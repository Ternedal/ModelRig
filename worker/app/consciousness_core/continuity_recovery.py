"""C29-J process-local recovery completion receipt.

The receipt proves that the one-RUN post-wake reorientation horizon was
successfully consumed by an accepted cognitive cycle. It grants no authority
and is not durable autobiographical memory.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .continuity import (
    ContinuityKnowledge,
    PostWakeContinuityState,
    post_wake_continuity_state_ref,
)
from .continuity_horizon import ContinuityReorientationWindow


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
CycleId = Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]


class ContinuityRecoveryError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class ContinuityRecoveryCompletionReceipt(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/continuity-recovery-completion/v1"
    ]
    receipt_id: Annotated[
        str,
        Field(pattern=r"^recovery-[a-f0-9]{32}$"),
    ]
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_revision: Annotated[
        str,
        Field(pattern=r"^person-r[0-9]{4,}$"),
    ]
    continuity_state_ref: NonEmptyRef
    wake_receipt_ref: NonEmptyRef
    knowledge: ContinuityKnowledge
    accepted_cycle_id: CycleId
    transition_receipt_ref: NonEmptyRef
    completion_kind: Literal["FIRST_ACCEPTED_RUN"]
    reorientation_complete: Literal[True]
    continuity_context_consumed: Literal[True]
    cognition_during_gap: Literal[False]
    crash_timestamp_claimed: Literal[False]
    model_calls: Literal[0]
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    timer_authority: Literal[False]
    production_activation: Literal[False]


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


def continuity_recovery_completion_ref(
    receipt: ContinuityRecoveryCompletionReceipt,
) -> str:
    if not isinstance(receipt, ContinuityRecoveryCompletionReceipt):
        raise TypeError(
            "receipt must be ContinuityRecoveryCompletionReceipt"
        )
    return "continuity-recovery-completion:" + _digest(receipt)


def build_continuity_recovery_completion(
    *,
    continuity_state: PostWakeContinuityState,
    consumed_window: ContinuityReorientationWindow,
    transition_receipt_ref: str,
    expected_self_id: str,
    expected_person_revision: str,
) -> ContinuityRecoveryCompletionReceipt:
    """Bind exact wake continuity to the first accepted post-wake RUN."""
    if not isinstance(continuity_state, PostWakeContinuityState):
        raise TypeError("continuity_state must be PostWakeContinuityState")
    if not isinstance(consumed_window, ContinuityReorientationWindow):
        raise TypeError(
            "consumed_window must be ContinuityReorientationWindow"
        )
    if continuity_state.self_id != expected_self_id:
        raise ContinuityRecoveryError(
            "continuity state belongs to another self"
        )
    if continuity_state.person_revision != expected_person_revision:
        raise ContinuityRecoveryError(
            "continuity state belongs to another Person Revision"
        )
    if consumed_window.state != "CONSUMED":
        raise ContinuityRecoveryError(
            "recovery completion requires consumed continuity window"
        )
    if consumed_window.consumed_cycle_id is None:
        raise ContinuityRecoveryError(
            "consumed continuity window has no cycle id"
        )

    continuity_ref = post_wake_continuity_state_ref(continuity_state)
    if consumed_window.continuity_state_ref != continuity_ref:
        raise ContinuityRecoveryError(
            "continuity window belongs to another continuity state"
        )
    if consumed_window.knowledge != continuity_state.knowledge:
        raise ContinuityRecoveryError(
            "continuity window knowledge does not match continuity state"
        )
    if (
        not isinstance(transition_receipt_ref, str)
        or not transition_receipt_ref.strip()
    ):
        raise ContinuityRecoveryError(
            "transition_receipt_ref is required"
        )

    seed = {
        "continuity_state_ref": continuity_ref,
        "wake_receipt_ref": continuity_state.wake_receipt_ref,
        "accepted_cycle_id": consumed_window.consumed_cycle_id,
        "transition_receipt_ref": transition_receipt_ref,
        "kind": "first-accepted-run",
    }
    return ContinuityRecoveryCompletionReceipt(
        schema=(
            "kaliv-consciousness-core/"
            "continuity-recovery-completion/v1"
        ),
        receipt_id="recovery-" + _digest(seed)[:32],
        self_id=continuity_state.self_id,
        person_revision=continuity_state.person_revision,
        continuity_state_ref=continuity_ref,
        wake_receipt_ref=continuity_state.wake_receipt_ref,
        knowledge=continuity_state.knowledge,
        accepted_cycle_id=consumed_window.consumed_cycle_id,
        transition_receipt_ref=transition_receipt_ref,
        completion_kind="FIRST_ACCEPTED_RUN",
        reorientation_complete=True,
        continuity_context_consumed=True,
        cognition_during_gap=False,
        crash_timestamp_claimed=False,
        model_calls=0,
        self_state_store_write_applied=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        timer_authority=False,
        production_activation=False,
    )
