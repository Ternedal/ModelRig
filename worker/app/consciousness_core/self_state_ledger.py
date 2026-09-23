"""C27-B bounded runtime SelfState transition ledger.

The ledger retains the exact in-memory +1 SelfState chain since the current
C14 durable anchor. It performs no persistence. C27-A remains the atomic store
primitive and a later slice may explicitly connect the two.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cycle import self_state_ref
from .self_state import (
    PersistentSelfState,
    SelfStateCheckpointReceipt,
)


TransitionKind = Literal[
    "session_bootstrap",
    "world_evidence",
    "supervisor_orientation",
    "post_cycle_reduction",
]
NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
_MAX_PENDING_TRANSITIONS = 128


class RuntimeSelfStateLedgerError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class RuntimeSelfStateTransition(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/runtime-self-state-transition/v1"
    ]
    kind: TransitionKind
    state_ref: NonEmptyRef
    revision: Annotated[int, Field(ge=2, strict=True)]
    source_ref: NonEmptyRef
    production_activation: Literal[False]


class RuntimeSelfStateCheckpointPlan(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/runtime-self-state-checkpoint-plan/v1"
    ]
    anchor_state_ref: NonEmptyRef
    final_state_ref: NonEmptyRef
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_id: Annotated[str, Field(pattern=r"^person-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    revision_before: Annotated[int, Field(ge=1, strict=True)]
    revision_after: Annotated[int, Field(ge=2, strict=True)]
    transitions: Annotated[
        list[RuntimeSelfStateTransition],
        Field(min_length=1, max_length=128),
    ]
    transition_count: Annotated[int, Field(ge=1, le=128, strict=True)]
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "RuntimeSelfStateCheckpointPlan":
        if len(self.transitions) != self.transition_count:
            raise ValueError("checkpoint-plan transition count mismatch")
        if self.transitions[-1].state_ref != self.final_state_ref:
            raise ValueError("checkpoint-plan final state ref mismatch")
        expected = self.revision_before + 1
        for transition in self.transitions:
            if transition.revision != expected:
                raise ValueError(
                    "checkpoint-plan revisions are not contiguous"
                )
            expected += 1
        if self.revision_after != expected - 1:
            raise ValueError("checkpoint-plan final revision mismatch")
        return self


class RuntimeSelfStateLedger:
    """Process-local chain anchored to one exact durable SelfState."""

    def __init__(
        self,
        *,
        anchor_state: PersistentSelfState | Mapping[str, Any],
        initial_state: PersistentSelfState | Mapping[str, Any],
        initial_source_ref: str,
    ) -> None:
        try:
            anchor = (
                anchor_state
                if isinstance(anchor_state, PersistentSelfState)
                else PersistentSelfState.model_validate(anchor_state)
            )
            initial = (
                initial_state
                if isinstance(initial_state, PersistentSelfState)
                else PersistentSelfState.model_validate(initial_state)
            )
        except ValidationError as exc:
            raise RuntimeSelfStateLedgerError(
                "invalid SelfState ledger bootstrap input"
            ) from exc
        self._validate_source_ref(initial_source_ref)
        self._anchor = anchor
        self._states: list[PersistentSelfState] = []
        self._transitions: list[RuntimeSelfStateTransition] = []
        entry = self.prepare(
            state=initial,
            kind="session_bootstrap",
            source_ref=initial_source_ref,
        )
        self.commit(state=initial, transition=entry)

    @staticmethod
    def _validate_source_ref(source_ref: str) -> None:
        if (
            not isinstance(source_ref, str)
            or not source_ref.strip()
            or source_ref != source_ref.strip()
            or len(source_ref) > 256
        ):
            raise RuntimeSelfStateLedgerError(
                "SelfState ledger transition source_ref is invalid"
            )

    @property
    def anchor_state(self) -> PersistentSelfState:
        return self._anchor

    @property
    def pending_count(self) -> int:
        return len(self._states)

    @property
    def remaining_capacity(self) -> int:
        return _MAX_PENDING_TRANSITIONS - len(self._states)

    @property
    def current_state(self) -> PersistentSelfState:
        return self._states[-1] if self._states else self._anchor

    def require_capacity(self, count: int) -> None:
        if isinstance(count, bool) or not isinstance(count, int):
            raise RuntimeSelfStateLedgerError(
                "SelfState ledger capacity count must be integer"
            )
        if count < 0 or count > _MAX_PENDING_TRANSITIONS:
            raise RuntimeSelfStateLedgerError(
                "SelfState ledger capacity count is invalid"
            )
        if self.remaining_capacity < count:
            raise RuntimeSelfStateLedgerError(
                "SelfState checkpoint required before more state transitions"
            )

    def assert_current(
        self,
        state: PersistentSelfState | Mapping[str, Any],
    ) -> None:
        try:
            value = (
                state
                if isinstance(state, PersistentSelfState)
                else PersistentSelfState.model_validate(state)
            )
        except ValidationError as exc:
            raise RuntimeSelfStateLedgerError(
                "invalid live SelfState for ledger alignment"
            ) from exc
        if value != self.current_state:
            raise RuntimeSelfStateLedgerError(
                "live SelfState is not aligned with transition ledger"
            )

    def _validate_next(self, state: PersistentSelfState) -> None:
        previous = self.current_state
        if state.revision != previous.revision + 1:
            raise RuntimeSelfStateLedgerError(
                "ledger SelfState revision must advance exactly by one"
            )
        if state.self_id != self._anchor.self_id:
            raise RuntimeSelfStateLedgerError(
                "ledger transition cannot change self identity"
            )
        if state.person_id != self._anchor.person_id:
            raise RuntimeSelfStateLedgerError(
                "ledger transition cannot change person identity"
            )
        if state.person_revision != self._anchor.person_revision:
            raise RuntimeSelfStateLedgerError(
                "ledger transition cannot change Person Revision"
            )

    def prepare(
        self,
        *,
        state: PersistentSelfState | Mapping[str, Any],
        kind: TransitionKind,
        source_ref: str,
    ) -> RuntimeSelfStateTransition:
        self.require_capacity(1)
        self._validate_source_ref(source_ref)
        try:
            value = (
                state
                if isinstance(state, PersistentSelfState)
                else PersistentSelfState.model_validate(state)
            )
        except ValidationError as exc:
            raise RuntimeSelfStateLedgerError(
                "invalid SelfState ledger transition"
            ) from exc
        if kind not in {
            "session_bootstrap",
            "world_evidence",
            "supervisor_orientation",
            "post_cycle_reduction",
        }:
            raise RuntimeSelfStateLedgerError(
                "unsupported SelfState ledger transition kind"
            )
        self._validate_next(value)
        return RuntimeSelfStateTransition(
            schema=(
                "kaliv-consciousness-core/"
                "runtime-self-state-transition/v1"
            ),
            kind=kind,
            state_ref=self_state_ref(value),
            revision=value.revision,
            source_ref=source_ref,
            production_activation=False,
        )

    def commit(
        self,
        *,
        state: PersistentSelfState | Mapping[str, Any],
        transition: RuntimeSelfStateTransition,
    ) -> None:
        if not isinstance(transition, RuntimeSelfStateTransition):
            raise TypeError(
                "transition must be RuntimeSelfStateTransition"
            )
        try:
            value = (
                state
                if isinstance(state, PersistentSelfState)
                else PersistentSelfState.model_validate(state)
            )
        except ValidationError as exc:
            raise RuntimeSelfStateLedgerError(
                "invalid SelfState ledger commit"
            ) from exc
        self.require_capacity(1)
        self._validate_next(value)
        if transition.revision != value.revision:
            raise RuntimeSelfStateLedgerError(
                "prepared transition revision changed before commit"
            )
        if transition.state_ref != self_state_ref(value):
            raise RuntimeSelfStateLedgerError(
                "prepared transition state changed before commit"
            )
        self._states.append(value)
        self._transitions.append(transition)

    def append(
        self,
        *,
        state: PersistentSelfState | Mapping[str, Any],
        kind: TransitionKind,
        source_ref: str,
    ) -> RuntimeSelfStateTransition:
        transition = self.prepare(
            state=state,
            kind=kind,
            source_ref=source_ref,
        )
        self.commit(state=state, transition=transition)
        return transition

    def checkpoint_states(self) -> list[PersistentSelfState]:
        return list(self._states)

    def plan(self) -> RuntimeSelfStateCheckpointPlan:
        if not self._states:
            raise RuntimeSelfStateLedgerError(
                "no pending SelfState transitions to checkpoint"
            )
        final = self._states[-1]
        return RuntimeSelfStateCheckpointPlan(
            schema=(
                "kaliv-consciousness-core/"
                "runtime-self-state-checkpoint-plan/v1"
            ),
            anchor_state_ref=self_state_ref(self._anchor),
            final_state_ref=self_state_ref(final),
            self_id=self._anchor.self_id,
            person_id=self._anchor.person_id,
            person_revision=self._anchor.person_revision,
            revision_before=self._anchor.revision,
            revision_after=final.revision,
            transitions=list(self._transitions),
            transition_count=len(self._transitions),
            self_state_store_write_applied=False,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )

    def mark_checkpointed(
        self,
        receipt: SelfStateCheckpointReceipt,
    ) -> None:
        if not isinstance(receipt, SelfStateCheckpointReceipt):
            raise TypeError("receipt must be SelfStateCheckpointReceipt")
        plan = self.plan()
        expected_refs = [
            transition.state_ref
            for transition in plan.transitions
        ]
        if receipt.previous_self_state_ref != plan.anchor_state_ref:
            raise RuntimeSelfStateLedgerError(
                "checkpoint receipt durable anchor mismatch"
            )
        if receipt.final_self_state_ref != plan.final_state_ref:
            raise RuntimeSelfStateLedgerError(
                "checkpoint receipt final state mismatch"
            )
        if receipt.transition_state_refs != expected_refs:
            raise RuntimeSelfStateLedgerError(
                "checkpoint receipt transition chain mismatch"
            )
        if (
            receipt.self_id != plan.self_id
            or receipt.person_id != plan.person_id
            or receipt.person_revision != plan.person_revision
        ):
            raise RuntimeSelfStateLedgerError(
                "checkpoint receipt identity mismatch"
            )
        if (
            receipt.revision_before != plan.revision_before
            or receipt.revision_after != plan.revision_after
            or receipt.transition_count != plan.transition_count
        ):
            raise RuntimeSelfStateLedgerError(
                "checkpoint receipt revision/count mismatch"
            )

        final = self._states[-1]
        self._anchor = final
        self._states = []
        self._transitions = []
