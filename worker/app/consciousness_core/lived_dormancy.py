"""C31-D reference-only dormancy -> wake-reorientation bridge.

This seam binds existing C12/C29 dormancy evidence to the explicit continuity
reorientation path. It does not create a new sleep state machine, run a model,
schedule cognition, persist memory, or claim cognition happened while the
process was not alive.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .continuity import (
    ContinuityKnowledge,
    PostWakeContinuityState,
    post_wake_continuity_state_ref,
)
from .continuity_horizon import ContinuityReorientationWindow
from .continuity_orientation import (
    ContinuityOrientationState,
    continuity_orientation_state_ref,
)
from .continuity_recovery import (
    ContinuityRecoveryCompletionReceipt,
    continuity_recovery_completion_ref,
)
from .continuity_reorientation import ContinuityReorientationDecision
from .sleep import SleepRecord, WakeReceipt


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]


class LivedDormancyBridgeError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class LivedDormancyBridgeReceipt(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/lived-dormancy-bridge/v1"
    ]
    bridge_id: Annotated[
        str,
        Field(pattern=r"^lived-dormancy-[a-f0-9]{32}$"),
    ]
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    dormancy_kind: Literal["PLANNED_SLEEP", "UNPLANNED_DORMANCY"]
    knowledge: ContinuityKnowledge
    sleep_record_ref: NonEmptyRef | None
    wake_receipt_ref: NonEmptyRef
    continuity_state_ref: NonEmptyRef
    reorientation_decision_ref: NonEmptyRef
    reorientation_window_ref: NonEmptyRef
    orientation_state_ref: NonEmptyRef
    recovery_completion_ref: NonEmptyRef | None
    reorientation_phase: Literal["REORIENTING", "ORIENTED"]
    explicit_reorientation_required: Literal[True]
    reorientation_complete: bool
    continuity_preserved: Literal[True]
    cognition_during_gap: Literal[False]
    hidden_cognition_claimed: Literal[False]
    crash_timestamp_claimed: Literal[False]
    model_calls: Literal[0]
    persistent_state_authority: Literal[False]
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    automatic_cognition_authority: Literal[False]
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


def _ref(kind: str, value: Any) -> str:
    return f"{kind}:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def _parse(
    value: Any,
    model: type[BaseModel],
    label: str,
) -> BaseModel:
    try:
        return value if isinstance(value, model) else model.model_validate(value)
    except ValidationError as exc:
        raise LivedDormancyBridgeError(
            f"invalid {label}"
        ) from exc


def build_lived_dormancy_bridge(
    *,
    wake_receipt: WakeReceipt | Mapping[str, Any],
    continuity_state: PostWakeContinuityState | Mapping[str, Any],
    reorientation_decision: ContinuityReorientationDecision | Mapping[str, Any],
    reorientation_window: ContinuityReorientationWindow | Mapping[str, Any],
    orientation_state: ContinuityOrientationState | Mapping[str, Any],
    sleep_record: SleepRecord | Mapping[str, Any] | None = None,
    recovery_completion: (
        ContinuityRecoveryCompletionReceipt | Mapping[str, Any] | None
    ) = None,
) -> LivedDormancyBridgeReceipt:
    """Bind one real dormancy gap to its explicit wake-reorientation state."""
    wake = _parse(wake_receipt, WakeReceipt, "WakeReceipt")
    continuity = _parse(
        continuity_state,
        PostWakeContinuityState,
        "PostWakeContinuityState",
    )
    decision = _parse(
        reorientation_decision,
        ContinuityReorientationDecision,
        "ContinuityReorientationDecision",
    )
    window = _parse(
        reorientation_window,
        ContinuityReorientationWindow,
        "ContinuityReorientationWindow",
    )
    orientation = _parse(
        orientation_state,
        ContinuityOrientationState,
        "ContinuityOrientationState",
    )
    sleep = (
        None
        if sleep_record is None
        else _parse(sleep_record, SleepRecord, "SleepRecord")
    )
    completion = (
        None
        if recovery_completion is None
        else _parse(
            recovery_completion,
            ContinuityRecoveryCompletionReceipt,
            "ContinuityRecoveryCompletionReceipt",
        )
    )

    wake_ref = _ref("wake-receipt", wake)
    continuity_ref = post_wake_continuity_state_ref(continuity)

    if continuity.self_id != wake.self_id:
        raise LivedDormancyBridgeError(
            "continuity state belongs to another self"
        )
    if continuity.person_revision != wake.person_revision:
        raise LivedDormancyBridgeError(
            "continuity state belongs to another Person Revision"
        )
    if continuity.wake_receipt_ref != wake_ref:
        raise LivedDormancyBridgeError(
            "continuity state belongs to another wake receipt"
        )
    if continuity.dormancy_kind != wake.dormancy_kind:
        raise LivedDormancyBridgeError(
            "continuity dormancy kind does not match wake receipt"
        )
    if continuity.cognition_during_gap is not False:
        raise LivedDormancyBridgeError(
            "continuity may not claim cognition during dormancy"
        )
    if continuity.crash_timestamp_claimed is not False:
        raise LivedDormancyBridgeError(
            "continuity may not invent a crash timestamp"
        )

    if (
        continuity.exact_offline_duration_ms
        != wake.offline_duration_ms
        or continuity.offline_duration_upper_bound_ms
        != wake.offline_duration_upper_bound_ms
        or continuity.last_known_alive_witness_ref
        != wake.last_known_alive_witness_ref
        or continuity.last_known_alive_anchor_ref
        != wake.last_known_alive_anchor_ref
    ):
        raise LivedDormancyBridgeError(
            "continuity duration/liveness evidence does not match wake receipt"
        )

    sleep_ref = None
    if wake.dormancy_kind == "PLANNED_SLEEP":
        if not isinstance(sleep, SleepRecord):
            raise LivedDormancyBridgeError(
                "planned dormancy requires the exact SleepRecord"
            )
        if sleep.self_id != wake.self_id:
            raise LivedDormancyBridgeError(
                "sleep record belongs to another self"
            )
        if sleep.person_revision != wake.person_revision:
            raise LivedDormancyBridgeError(
                "sleep record belongs to another Person Revision"
            )
        if wake.sleep_id != sleep.sleep_id:
            raise LivedDormancyBridgeError(
                "wake receipt does not bind the supplied SleepRecord"
            )
        if (
            wake.entry_anchor_ref
            != "temporal-anchor:" + sleep.entry_anchor.anchor_id
        ):
            raise LivedDormancyBridgeError(
                "wake entry anchor does not match SleepRecord"
            )
        if (
            wake.durable_self_state_ref != sleep.durable_self_state_ref
            or wake.durable_self_state_revision
            != sleep.durable_self_state_revision
        ):
            raise LivedDormancyBridgeError(
                "wake durable SelfState binding does not match SleepRecord"
            )
        if wake.resume_goal_refs != sleep.open_goal_refs:
            raise LivedDormancyBridgeError(
                "wake goal refs do not match SleepRecord"
            )
        if wake.resume_open_loop_refs != sleep.open_loop_refs:
            raise LivedDormancyBridgeError(
                "wake loop refs do not match SleepRecord"
            )
        if wake.pending_review_refs != sleep.pending_review_refs:
            raise LivedDormancyBridgeError(
                "wake review refs do not match SleepRecord"
            )
        if sleep.cognition_continues is not False:
            raise LivedDormancyBridgeError(
                "SleepRecord may not claim cognition continues"
            )
        sleep_ref = _ref("sleep-record", sleep)
    else:
        if sleep is not None:
            raise LivedDormancyBridgeError(
                "unplanned dormancy cannot carry a SleepRecord"
            )
        if wake.sleep_id is not None or wake.entry_anchor_ref is not None:
            raise LivedDormancyBridgeError(
                "unplanned dormancy cannot claim a planned sleep boundary"
            )
        if wake.duration_known or wake.offline_duration_ms is not None:
            raise LivedDormancyBridgeError(
                "unplanned dormancy cannot claim exact offline duration"
            )

    if decision.continuity_state_ref != continuity_ref:
        raise LivedDormancyBridgeError(
            "reorientation decision belongs to another continuity state"
        )
    if decision.knowledge != continuity.knowledge:
        raise LivedDormancyBridgeError(
            "reorientation decision knowledge mismatch"
        )
    if window.continuity_state_ref != continuity_ref:
        raise LivedDormancyBridgeError(
            "reorientation window belongs to another continuity state"
        )
    if window.knowledge != continuity.knowledge:
        raise LivedDormancyBridgeError(
            "reorientation window knowledge mismatch"
        )
    if orientation.continuity_state_ref != continuity_ref:
        raise LivedDormancyBridgeError(
            "orientation belongs to another continuity state"
        )
    if orientation.knowledge != continuity.knowledge:
        raise LivedDormancyBridgeError(
            "orientation knowledge mismatch"
        )

    completion_ref = None
    if orientation.phase == "REORIENTING":
        if window.state != "ACTIVE":
            raise LivedDormancyBridgeError(
                "REORIENTING bridge requires active reorientation window"
            )
        if completion is not None:
            raise LivedDormancyBridgeError(
                "REORIENTING bridge cannot carry recovery completion"
            )
        reorientation_complete = False
    else:
        if window.state != "CONSUMED":
            raise LivedDormancyBridgeError(
                "ORIENTED bridge requires consumed reorientation window"
            )
        if not isinstance(completion, ContinuityRecoveryCompletionReceipt):
            raise LivedDormancyBridgeError(
                "ORIENTED bridge requires recovery completion"
            )
        if completion.self_id != wake.self_id:
            raise LivedDormancyBridgeError(
                "recovery completion belongs to another self"
            )
        if completion.person_revision != wake.person_revision:
            raise LivedDormancyBridgeError(
                "recovery completion belongs to another Person Revision"
            )
        if completion.continuity_state_ref != continuity_ref:
            raise LivedDormancyBridgeError(
                "recovery completion belongs to another continuity state"
            )
        if completion.wake_receipt_ref != wake_ref:
            raise LivedDormancyBridgeError(
                "recovery completion belongs to another wake receipt"
            )
        if completion.knowledge != continuity.knowledge:
            raise LivedDormancyBridgeError(
                "recovery completion knowledge mismatch"
            )
        if (
            completion.accepted_cycle_id != window.consumed_cycle_id
            or orientation.completed_cycle_id != window.consumed_cycle_id
        ):
            raise LivedDormancyBridgeError(
                "reorientation completion cycle mismatch"
            )
        completion_ref = continuity_recovery_completion_ref(completion)
        if orientation.recovery_completion_ref != completion_ref:
            raise LivedDormancyBridgeError(
                "orientation recovery completion binding mismatch"
            )
        reorientation_complete = True

    decision_ref = _ref("continuity-reorientation-decision", decision)
    window_ref = _ref("continuity-reorientation-window", window)
    orientation_ref = continuity_orientation_state_ref(orientation)
    seed = {
        "wake_receipt_ref": wake_ref,
        "continuity_state_ref": continuity_ref,
        "reorientation_decision_ref": decision_ref,
        "reorientation_window_ref": window_ref,
        "orientation_state_ref": orientation_ref,
        "recovery_completion_ref": completion_ref,
        "dormancy_kind": wake.dormancy_kind,
    }

    return LivedDormancyBridgeReceipt(
        schema="kaliv-consciousness-core/lived-dormancy-bridge/v1",
        bridge_id=(
            "lived-dormancy-"
            + hashlib.sha256(_canonical_json(seed)).hexdigest()[:32]
        ),
        self_id=wake.self_id,
        person_revision=wake.person_revision,
        dormancy_kind=wake.dormancy_kind,
        knowledge=continuity.knowledge,
        sleep_record_ref=sleep_ref,
        wake_receipt_ref=wake_ref,
        continuity_state_ref=continuity_ref,
        reorientation_decision_ref=decision_ref,
        reorientation_window_ref=window_ref,
        orientation_state_ref=orientation_ref,
        recovery_completion_ref=completion_ref,
        reorientation_phase=orientation.phase,
        explicit_reorientation_required=True,
        reorientation_complete=reorientation_complete,
        continuity_preserved=True,
        cognition_during_gap=False,
        hidden_cognition_claimed=False,
        crash_timestamp_claimed=False,
        model_calls=0,
        persistent_state_authority=False,
        self_state_store_write_applied=False,
        durable_memory_write_authority=False,
        automatic_cognition_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        timer_authority=False,
        production_activation=False,
    )
