"""C27-F explicit policy-driven SelfState checkpoint adapter.

Caller-driven composition only. Existing C19 mutation APIs remain unchanged.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from .checkpoint_pressure import (
    DEFAULT_CHECKPOINT_PRESSURE_POLICY,
    CheckpointPressureDecision,
    CheckpointPressurePolicy,
    evaluate_checkpoint_pressure,
)
from .self_state import SelfStateStore
from .self_state_checkpoint_runtime import (
    ExplicitSelfStateCheckpointCoordinator,
    RuntimeSelfStateCheckpointResult,
    runtime_checkpoint_plan_ref,
)
from .session_lifecycle import ProductionCognitiveSession


class PolicyDrivenCheckpointError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class PolicyDrivenCheckpointResult(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/policy-driven-checkpoint-result/v1"
    ]
    outcome: Literal["IDLE", "HOLD", "COMMITTED"]
    pressure: CheckpointPressureDecision
    evaluated_plan_ref: str | None
    checkpoint: RuntimeSelfStateCheckpointResult | None
    coordinator_invoked: bool
    self_state_store_write_applied: bool
    model_calls: Literal[0]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "PolicyDrivenCheckpointResult":
        wants_commit = self.pressure.decision in {
            "CHECKPOINT",
            "REQUIRED",
        }
        if wants_commit:
            if (
                self.outcome != "COMMITTED"
                or not self.coordinator_invoked
                or self.evaluated_plan_ref is None
                or self.checkpoint is None
                or self.checkpoint.outcome != "COMMITTED"
                or not self.self_state_store_write_applied
            ):
                raise ValueError(
                    "checkpoint pressure must resolve to exact committed result"
                )
            if self.checkpoint.plan_ref != self.evaluated_plan_ref:
                raise ValueError(
                    "committed checkpoint does not bind evaluated plan"
                )
        else:
            expected = (
                "IDLE"
                if self.pressure.decision == "IDLE"
                else "HOLD"
            )
            if (
                self.outcome != expected
                or self.coordinator_invoked
                or self.checkpoint is not None
                or self.self_state_store_write_applied
            ):
                raise ValueError(
                    "non-checkpoint pressure cannot claim persistence"
                )
            if self.pressure.decision == "IDLE":
                if self.evaluated_plan_ref is not None:
                    raise ValueError(
                        "IDLE result cannot bind a checkpoint plan"
                    )
            elif self.evaluated_plan_ref is None:
                raise ValueError(
                    "HOLD result must bind the evaluated pending plan"
                )
        return self


class PolicyDrivenSelfStateCheckpointAdapter:
    """Evaluate C27-E and invoke C27-C at most once when required."""

    def __init__(
        self,
        *,
        session: ProductionCognitiveSession,
        store: SelfStateStore,
        policy: CheckpointPressurePolicy = DEFAULT_CHECKPOINT_PRESSURE_POLICY,
        coordinator_factory=ExplicitSelfStateCheckpointCoordinator,
    ) -> None:
        if not isinstance(session, ProductionCognitiveSession):
            raise TypeError("session must be ProductionCognitiveSession")
        if not isinstance(store, SelfStateStore):
            raise TypeError("store must be SelfStateStore")
        if not isinstance(policy, CheckpointPressurePolicy):
            raise TypeError("policy must be CheckpointPressurePolicy")
        if not callable(coordinator_factory):
            raise TypeError("coordinator_factory must be callable")

        coordinator = coordinator_factory(
            session=session,
            store=store,
        )
        if not isinstance(
            coordinator,
            ExplicitSelfStateCheckpointCoordinator,
        ):
            raise TypeError(
                "coordinator_factory must return "
                "ExplicitSelfStateCheckpointCoordinator"
            )

        self._session = session
        self._policy = policy
        self._coordinator = coordinator

    @property
    def policy(self) -> CheckpointPressurePolicy:
        return self._policy

    def maybe_checkpoint_once(self) -> PolicyDrivenCheckpointResult:
        if self._session.closed:
            raise PolicyDrivenCheckpointError(
                "cannot evaluate checkpoint pressure for closed session"
            )

        plan = self._session.self_state_checkpoint_plan
        pressure = evaluate_checkpoint_pressure(
            plan=plan,
            policy=self._policy,
        )

        if pressure.decision == "IDLE":
            return PolicyDrivenCheckpointResult(
                schema=(
                    "kaliv-consciousness-core/"
                    "policy-driven-checkpoint-result/v1"
                ),
                outcome="IDLE",
                pressure=pressure,
                evaluated_plan_ref=None,
                checkpoint=None,
                coordinator_invoked=False,
                self_state_store_write_applied=False,
                model_calls=0,
                durable_memory_write_authority=False,
                execution_authority=False,
                scheduling_authority=False,
                production_activation=False,
            )

        if plan is None:
            raise PolicyDrivenCheckpointError(
                "non-IDLE pressure decision has no checkpoint plan"
            )
        evaluated_plan_ref = runtime_checkpoint_plan_ref(plan)

        if pressure.decision == "HOLD":
            return PolicyDrivenCheckpointResult(
                schema=(
                    "kaliv-consciousness-core/"
                    "policy-driven-checkpoint-result/v1"
                ),
                outcome="HOLD",
                pressure=pressure,
                evaluated_plan_ref=evaluated_plan_ref,
                checkpoint=None,
                coordinator_invoked=False,
                self_state_store_write_applied=False,
                model_calls=0,
                durable_memory_write_authority=False,
                execution_authority=False,
                scheduling_authority=False,
                production_activation=False,
            )

        # Re-read immediately before persistence. This adapter is intended for
        # the same trusted owner thread/loop as C19. Any already-visible plan
        # drift fails before the C27-C store call.
        current_plan = self._session.self_state_checkpoint_plan
        if (
            current_plan is None
            or runtime_checkpoint_plan_ref(current_plan)
            != evaluated_plan_ref
        ):
            raise PolicyDrivenCheckpointError(
                "SelfState checkpoint plan changed after pressure evaluation"
            )

        try:
            checkpoint = self._coordinator.checkpoint_once()
        except Exception as exc:
            raise PolicyDrivenCheckpointError(
                "policy-driven SelfState checkpoint failed"
            ) from exc

        if checkpoint.outcome != "COMMITTED":
            raise PolicyDrivenCheckpointError(
                "checkpoint pressure requested persistence but coordinator "
                "did not commit"
            )
        if checkpoint.plan_ref != evaluated_plan_ref:
            raise PolicyDrivenCheckpointError(
                "committed checkpoint plan differs from evaluated pressure plan"
            )

        return PolicyDrivenCheckpointResult(
            schema=(
                "kaliv-consciousness-core/"
                "policy-driven-checkpoint-result/v1"
            ),
            outcome="COMMITTED",
            pressure=pressure,
            evaluated_plan_ref=evaluated_plan_ref,
            checkpoint=checkpoint,
            coordinator_invoked=True,
            self_state_store_write_applied=True,
            model_calls=0,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )
