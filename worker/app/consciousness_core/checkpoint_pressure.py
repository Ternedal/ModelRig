"""C27-E deterministic SelfState checkpoint pressure policy.

Pure Core policy only. It never reads/writes the C14 store, owns no cadence,
and grants no scheduling or execution authority.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .self_state_ledger import RuntimeSelfStateCheckpointPlan


Decision = Literal["IDLE", "HOLD", "CHECKPOINT", "REQUIRED"]
Reason = Literal[
    "no_pending_transitions",
    "below_threshold",
    "completed_cognitive_cycle",
    "transition_threshold",
    "capacity_reserve_exhausted",
]

_MAX_LEDGER_TRANSITIONS = 128


class CheckpointPressurePolicyError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class CheckpointPressurePolicy(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/checkpoint-pressure-policy/v1"
    ]
    checkpoint_transition_count: Annotated[
        int,
        Field(ge=1, le=_MAX_LEDGER_TRANSITIONS, strict=True),
    ] = 8
    reserve_transition_slots: Annotated[
        int,
        Field(ge=0, le=_MAX_LEDGER_TRANSITIONS, strict=True),
    ] = 2
    checkpoint_after_post_cycle: bool = True
    production_activation: Literal[False] = False

    @model_validator(mode="after")
    def viable(self) -> "CheckpointPressurePolicy":
        if (
            self.checkpoint_transition_count
            + self.reserve_transition_slots
            > _MAX_LEDGER_TRANSITIONS + 1
        ):
            raise ValueError(
                "checkpoint threshold/reserve combination is not viable"
            )
        return self


DEFAULT_CHECKPOINT_PRESSURE_POLICY = CheckpointPressurePolicy(
    schema="kaliv-consciousness-core/checkpoint-pressure-policy/v1",
    checkpoint_transition_count=8,
    reserve_transition_slots=2,
    checkpoint_after_post_cycle=True,
    production_activation=False,
)


class CheckpointPressureDecision(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/checkpoint-pressure-decision/v1"
    ]
    decision_id: Annotated[
        str,
        Field(pattern=r"^ckptpress-[a-f0-9]{32}$"),
    ]
    decision: Decision
    reason: Reason
    pending_transition_count: Annotated[
        int,
        Field(ge=0, le=_MAX_LEDGER_TRANSITIONS, strict=True),
    ]
    remaining_transition_capacity: Annotated[
        int,
        Field(ge=0, le=_MAX_LEDGER_TRANSITIONS, strict=True),
    ]
    final_state_ref: Annotated[
        str,
        Field(min_length=1, max_length=256),
    ] | None
    transition_kinds: Annotated[
        list[
            Literal[
                "session_bootstrap",
                "world_evidence",
                "supervisor_orientation",
                "post_cycle_reduction",
            ]
        ],
        Field(max_length=_MAX_LEDGER_TRANSITIONS),
    ]
    self_state_store_write_applied: Literal[False]
    model_calls: Literal[0]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "CheckpointPressureDecision":
        if self.decision == "IDLE":
            if (
                self.pending_transition_count != 0
                or self.final_state_ref is not None
                or self.transition_kinds
            ):
                raise ValueError("IDLE pressure decision carries pending state")
        elif (
            self.pending_transition_count < 1
            or self.final_state_ref is None
            or len(self.transition_kinds) != self.pending_transition_count
        ):
            raise ValueError(
                "non-IDLE pressure decision is missing pending-state metadata"
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


def checkpoint_pressure_policy_ref(
    policy: CheckpointPressurePolicy,
) -> str:
    if not isinstance(policy, CheckpointPressurePolicy):
        raise TypeError("policy must be CheckpointPressurePolicy")
    return "checkpoint-pressure-policy:" + hashlib.sha256(
        _canonical_json(policy)
    ).hexdigest()


def _decision_id(
    *,
    plan: RuntimeSelfStateCheckpointPlan | None,
    policy: CheckpointPressurePolicy,
    decision: Decision,
    reason: Reason,
) -> str:
    payload = {
        "plan": (
            None
            if plan is None
            else plan.model_dump(mode="json")
        ),
        "policy": policy.model_dump(mode="json"),
        "decision": decision,
        "reason": reason,
    }
    return "ckptpress-" + hashlib.sha256(
        _canonical_json(payload)
    ).hexdigest()[:32]


def evaluate_checkpoint_pressure(
    *,
    plan: RuntimeSelfStateCheckpointPlan | None,
    policy: CheckpointPressurePolicy = DEFAULT_CHECKPOINT_PRESSURE_POLICY,
) -> CheckpointPressureDecision:
    """Map one exact C27-B plan to bounded checkpoint pressure."""
    if plan is not None and not isinstance(
        plan,
        RuntimeSelfStateCheckpointPlan,
    ):
        raise TypeError(
            "plan must be RuntimeSelfStateCheckpointPlan or None"
        )
    if not isinstance(policy, CheckpointPressurePolicy):
        raise TypeError("policy must be CheckpointPressurePolicy")

    if plan is None:
        decision: Decision = "IDLE"
        reason: Reason = "no_pending_transitions"
        return CheckpointPressureDecision(
            schema=(
                "kaliv-consciousness-core/"
                "checkpoint-pressure-decision/v1"
            ),
            decision_id=_decision_id(
                plan=None,
                policy=policy,
                decision=decision,
                reason=reason,
            ),
            decision=decision,
            reason=reason,
            pending_transition_count=0,
            remaining_transition_capacity=_MAX_LEDGER_TRANSITIONS,
            final_state_ref=None,
            transition_kinds=[],
            self_state_store_write_applied=False,
            model_calls=0,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )

    count = plan.transition_count
    remaining = _MAX_LEDGER_TRANSITIONS - count
    kinds = [transition.kind for transition in plan.transitions]

    if remaining < policy.reserve_transition_slots:
        decision = "REQUIRED"
        reason = "capacity_reserve_exhausted"
    elif (
        policy.checkpoint_after_post_cycle
        and "post_cycle_reduction" in kinds
    ):
        decision = "CHECKPOINT"
        reason = "completed_cognitive_cycle"
    elif count >= policy.checkpoint_transition_count:
        decision = "CHECKPOINT"
        reason = "transition_threshold"
    else:
        decision = "HOLD"
        reason = "below_threshold"

    return CheckpointPressureDecision(
        schema=(
            "kaliv-consciousness-core/"
            "checkpoint-pressure-decision/v1"
        ),
        decision_id=_decision_id(
            plan=plan,
            policy=policy,
            decision=decision,
            reason=reason,
        ),
        decision=decision,
        reason=reason,
        pending_transition_count=count,
        remaining_transition_capacity=remaining,
        final_state_ref=plan.final_state_ref,
        transition_kinds=kinds,
        self_state_store_write_applied=False,
        model_calls=0,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        production_activation=False,
    )
