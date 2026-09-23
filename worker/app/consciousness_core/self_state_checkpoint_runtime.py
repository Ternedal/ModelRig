"""C27-C explicit durable SelfState checkpoint coordinator.

Caller-driven only. No lifecycle hook, scheduler, timer, route or automatic
checkpoint is introduced here.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .cycle import self_state_ref
from .self_state import (
    SelfStateCheckpointReceipt,
    SelfStateStore,
)
from .self_state_ledger import RuntimeSelfStateCheckpointPlan
from .session_lifecycle import ProductionCognitiveSession


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]


class RuntimeSelfStateCheckpointError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class RuntimeSelfStateCheckpointResult(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/runtime-self-state-checkpoint-result/v1"
    ]
    outcome: Literal["IDLE", "COMMITTED"]
    plan_ref: NonEmptyRef | None
    store_receipt_ref: NonEmptyRef | None
    transition_count: Annotated[int, Field(ge=0, le=128, strict=True)]
    revision_before: Annotated[int | None, Field(ge=1, strict=True)]
    revision_after: Annotated[int | None, Field(ge=2, strict=True)]
    self_state_store_write_applied: bool
    ledger_reanchored: bool
    intermediate_history_persisted: Literal[False]
    model_calls: Literal[0]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "RuntimeSelfStateCheckpointResult":
        if self.outcome == "IDLE":
            if (
                self.plan_ref is not None
                or self.store_receipt_ref is not None
                or self.transition_count != 0
                or self.revision_before is not None
                or self.revision_after is not None
                or self.self_state_store_write_applied
                or self.ledger_reanchored
            ):
                raise ValueError("IDLE checkpoint result carries commit claims")
        else:
            if (
                self.plan_ref is None
                or self.store_receipt_ref is None
                or self.transition_count < 1
                or self.revision_before is None
                or self.revision_after is None
                or not self.self_state_store_write_applied
                or not self.ledger_reanchored
            ):
                raise ValueError("COMMITTED checkpoint result is incomplete")
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


def _ref(prefix: str, value: Any) -> str:
    return prefix + ":" + hashlib.sha256(_canonical_json(value)).hexdigest()


def runtime_checkpoint_plan_ref(
    plan: RuntimeSelfStateCheckpointPlan,
) -> str:
    if not isinstance(plan, RuntimeSelfStateCheckpointPlan):
        raise TypeError("plan must be RuntimeSelfStateCheckpointPlan")
    return _ref("runtime-self-state-checkpoint-plan", plan)


def self_state_checkpoint_receipt_ref(
    receipt: SelfStateCheckpointReceipt,
) -> str:
    if not isinstance(receipt, SelfStateCheckpointReceipt):
        raise TypeError("receipt must be SelfStateCheckpointReceipt")
    return _ref("self-state-checkpoint-receipt", receipt)


class ExplicitSelfStateCheckpointCoordinator:
    """Synchronously commit one exact pending C27-B chain through C27-A."""

    def __init__(
        self,
        *,
        session: ProductionCognitiveSession,
        store: SelfStateStore,
    ) -> None:
        if not isinstance(session, ProductionCognitiveSession):
            raise TypeError("session must be ProductionCognitiveSession")
        if not isinstance(store, SelfStateStore):
            raise TypeError("store must be SelfStateStore")
        self._session = session
        self._store = store

    def checkpoint_once(self) -> RuntimeSelfStateCheckpointResult:
        if self._session.closed:
            raise RuntimeSelfStateCheckpointError(
                "cannot checkpoint a closed cognitive session"
            )

        plan = self._session.self_state_checkpoint_plan
        states = self._session.pending_self_state_checkpoint_states()

        if plan is None:
            if states:
                raise RuntimeSelfStateCheckpointError(
                    "checkpoint states exist without checkpoint plan"
                )
            return RuntimeSelfStateCheckpointResult(
                schema=(
                    "kaliv-consciousness-core/"
                    "runtime-self-state-checkpoint-result/v1"
                ),
                outcome="IDLE",
                plan_ref=None,
                store_receipt_ref=None,
                transition_count=0,
                revision_before=None,
                revision_after=None,
                self_state_store_write_applied=False,
                ledger_reanchored=False,
                intermediate_history_persisted=False,
                model_calls=0,
                durable_memory_write_authority=False,
                execution_authority=False,
                scheduling_authority=False,
                production_activation=False,
            )

        if len(states) != plan.transition_count:
            raise RuntimeSelfStateCheckpointError(
                "checkpoint plan/state count mismatch"
            )
        state_refs = [self_state_ref(state) for state in states]
        transition_refs = [
            transition.state_ref
            for transition in plan.transitions
        ]
        if state_refs != transition_refs:
            raise RuntimeSelfStateCheckpointError(
                "checkpoint plan/state ref chain mismatch"
            )
        if not states or self_state_ref(states[-1]) != plan.final_state_ref:
            raise RuntimeSelfStateCheckpointError(
                "checkpoint final state mismatch"
            )

        durable = self._store.read()
        if durable is None:
            raise RuntimeSelfStateCheckpointError(
                "durable SelfState is missing"
            )
        if self_state_ref(durable) != plan.anchor_state_ref:
            raise RuntimeSelfStateCheckpointError(
                "durable SelfState no longer matches ledger anchor"
            )
        if (
            durable.self_id != plan.self_id
            or durable.person_id != plan.person_id
            or durable.person_revision != plan.person_revision
            or durable.revision != plan.revision_before
        ):
            raise RuntimeSelfStateCheckpointError(
                "durable SelfState identity/revision mismatch"
            )

        try:
            receipt = self._store.write_chain(states)
        except Exception as exc:
            raise RuntimeSelfStateCheckpointError(
                "durable SelfState checkpoint failed"
            ) from exc

        # Verify the store receipt before asking C19 to re-anchor.
        if receipt.previous_self_state_ref != plan.anchor_state_ref:
            raise RuntimeSelfStateCheckpointError(
                "store receipt durable anchor mismatch"
            )
        if receipt.final_self_state_ref != plan.final_state_ref:
            raise RuntimeSelfStateCheckpointError(
                "store receipt final state mismatch"
            )
        if receipt.transition_state_refs != transition_refs:
            raise RuntimeSelfStateCheckpointError(
                "store receipt transition chain mismatch"
            )
        if (
            receipt.revision_before != plan.revision_before
            or receipt.revision_after != plan.revision_after
            or receipt.transition_count != plan.transition_count
        ):
            raise RuntimeSelfStateCheckpointError(
                "store receipt revision/count mismatch"
            )

        try:
            self._session.mark_self_state_checkpointed(receipt)
        except Exception as exc:
            # Durable commit already happened. Never retry the store write here:
            # a retry would be stale. Surface the split outcome so a caller may
            # fail the session/process and restart from the new durable anchor.
            raise RuntimeSelfStateCheckpointError(
                "durable checkpoint committed but session acknowledgement failed"
            ) from exc

        return RuntimeSelfStateCheckpointResult(
            schema=(
                "kaliv-consciousness-core/"
                "runtime-self-state-checkpoint-result/v1"
            ),
            outcome="COMMITTED",
            plan_ref=runtime_checkpoint_plan_ref(plan),
            store_receipt_ref=self_state_checkpoint_receipt_ref(receipt),
            transition_count=plan.transition_count,
            revision_before=plan.revision_before,
            revision_after=plan.revision_after,
            self_state_store_write_applied=True,
            ledger_reanchored=True,
            intermediate_history_persisted=False,
            model_calls=0,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )
