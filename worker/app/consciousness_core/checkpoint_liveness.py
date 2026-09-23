"""C29-B committed-checkpoint runtime liveness recorder.

This adapter records liveness only after an already-successful C27-C durable
SelfState checkpoint. It never retries or replays the checkpoint itself.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .cycle import self_state_ref
from .liveness import (
    RuntimeLivenessStore,
    RuntimeLivenessWitness,
    build_runtime_liveness_witness,
    runtime_liveness_witness_ref,
)
from .self_state_checkpoint_runtime import RuntimeSelfStateCheckpointResult
from .session_lifecycle import ProductionCognitiveSession


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]


class CheckpointLivenessError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class CommittedCheckpointLivenessReceipt(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/committed-checkpoint-liveness/v1"
    ]
    outcome: Literal["RECORDED", "ALREADY_RECORDED"]
    checkpoint_plan_ref: NonEmptyRef
    checkpoint_store_receipt_ref: NonEmptyRef
    durable_self_state_ref: NonEmptyRef
    durable_self_state_revision: Annotated[int, Field(ge=1, strict=True)]
    liveness_witness_ref: NonEmptyRef
    liveness_store_write_applied: bool
    trusted_clock_sampled: bool
    checkpoint_retry_authority: Literal[False]
    model_calls: Literal[0]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "CommittedCheckpointLivenessReceipt":
        if self.outcome == "RECORDED":
            if (
                not self.liveness_store_write_applied
                or not self.trusted_clock_sampled
            ):
                raise ValueError(
                    "RECORDED liveness receipt must prove clock + write"
                )
        else:
            if (
                self.liveness_store_write_applied
                or self.trusted_clock_sampled
            ):
                raise ValueError(
                    "ALREADY_RECORDED cannot claim clock sampling or write"
                )
        return self


class CommittedCheckpointLivenessRecorder:
    """Bind one exact successful C27-C checkpoint to one liveness witness."""

    def __init__(
        self,
        *,
        session: ProductionCognitiveSession,
        store: RuntimeLivenessStore,
    ) -> None:
        if not isinstance(session, ProductionCognitiveSession):
            raise TypeError("session must be ProductionCognitiveSession")
        if not isinstance(store, RuntimeLivenessStore):
            raise TypeError("store must be RuntimeLivenessStore")
        self._session = session
        self._store = store

    @staticmethod
    def _require_committed(
        checkpoint: RuntimeSelfStateCheckpointResult,
    ) -> None:
        if not isinstance(
            checkpoint,
            RuntimeSelfStateCheckpointResult,
        ):
            raise TypeError(
                "checkpoint must be RuntimeSelfStateCheckpointResult"
            )
        if checkpoint.outcome != "COMMITTED":
            raise CheckpointLivenessError(
                "liveness requires a committed SelfState checkpoint"
            )
        if (
            checkpoint.plan_ref is None
            or checkpoint.store_receipt_ref is None
            or checkpoint.revision_after is None
            or not checkpoint.self_state_store_write_applied
            or not checkpoint.ledger_reanchored
        ):
            raise CheckpointLivenessError(
                "committed checkpoint result is incomplete"
            )

    def _exact_live_state(
        self,
        checkpoint: RuntimeSelfStateCheckpointResult,
    ):
        if self._session.closed:
            raise CheckpointLivenessError(
                "cannot record liveness for closed cognitive session"
            )
        if self._session.self_state_checkpoint_plan is not None:
            raise CheckpointLivenessError(
                "session has pending SelfState transitions after checkpoint"
            )
        if self._session.pending_self_state_checkpoint_states():
            raise CheckpointLivenessError(
                "session checkpoint ledger was not fully reanchored"
            )

        state = self._session.live_state.state
        if state.revision != checkpoint.revision_after:
            raise CheckpointLivenessError(
                "live SelfState revision differs from committed checkpoint"
            )
        return state

    @staticmethod
    def _same_durable_state(
        witness: RuntimeLivenessWitness,
        *,
        state_ref: str,
        revision: int,
    ) -> bool:
        return (
            witness.durable_self_state_ref == state_ref
            and witness.durable_self_state_revision == revision
        )

    def record_once(
        self,
        checkpoint: RuntimeSelfStateCheckpointResult,
    ) -> CommittedCheckpointLivenessReceipt:
        self._require_committed(checkpoint)
        state = self._exact_live_state(checkpoint)
        state_ref = self_state_ref(state)

        current = self._store.read()
        if (
            current is not None
            and self._same_durable_state(
                current,
                state_ref=state_ref,
                revision=state.revision,
            )
            and current.self_id == state.self_id
            and current.person_id == state.person_id
            and current.person_revision == state.person_revision
            and current.source_ref == checkpoint.store_receipt_ref
        ):
            return CommittedCheckpointLivenessReceipt(
                schema=(
                    "kaliv-consciousness-core/"
                    "committed-checkpoint-liveness/v1"
                ),
                outcome="ALREADY_RECORDED",
                checkpoint_plan_ref=checkpoint.plan_ref,
                checkpoint_store_receipt_ref=(
                    checkpoint.store_receipt_ref
                ),
                durable_self_state_ref=state_ref,
                durable_self_state_revision=state.revision,
                liveness_witness_ref=(
                    runtime_liveness_witness_ref(current)
                ),
                liveness_store_write_applied=False,
                trusted_clock_sampled=False,
                checkpoint_retry_authority=False,
                model_calls=0,
                durable_memory_write_authority=False,
                execution_authority=False,
                scheduling_authority=False,
                production_activation=False,
            )

        # The existing C18/C11 clock is sampled only after all checkpoint/live
        # state validation and duplicate detection have succeeded.
        anchor = self._session.trusted_clock.anchor(
            event_ref=(
                "runtime-liveness:"
                + checkpoint.store_receipt_ref
            )
        )
        witness = build_runtime_liveness_witness(
            state=state,
            anchor=anchor,
            source_ref=checkpoint.store_receipt_ref,
        )
        try:
            write = self._store.write_next(witness)
        except Exception as exc:
            raise CheckpointLivenessError(
                "runtime liveness witness write failed after committed checkpoint"
            ) from exc

        return CommittedCheckpointLivenessReceipt(
            schema=(
                "kaliv-consciousness-core/"
                "committed-checkpoint-liveness/v1"
            ),
            outcome="RECORDED",
            checkpoint_plan_ref=checkpoint.plan_ref,
            checkpoint_store_receipt_ref=checkpoint.store_receipt_ref,
            durable_self_state_ref=state_ref,
            durable_self_state_revision=state.revision,
            liveness_witness_ref=runtime_liveness_witness_ref(witness),
            liveness_store_write_applied=write.store_write_applied,
            trusted_clock_sampled=True,
            checkpoint_retry_authority=False,
            model_calls=0,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )
