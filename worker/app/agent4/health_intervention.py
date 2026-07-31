"""Caller-driven execution boundary for Agent 4 health interventions."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping

from .contracts import CampaignRepository
from .domain import CampaignRecord, CampaignValidationError
from .health import (
    CampaignHealthObservation,
    CampaignHealthPolicy,
    HealthDecision,
    HealthInterventionAction,
)
from .service import CampaignConflictError, CampaignNotFoundError


HealthInterventionHandler = Callable[
    [CampaignRecord, CampaignHealthObservation, HealthDecision], object
]


class HealthInterventionCompositionError(RuntimeError):
    """Raised when an actionable decision has no configured handler."""


class HealthInterventionExecutionError(RuntimeError):
    """Raised when a configured health intervention handler fails."""


@dataclass(frozen=True, slots=True)
class HealthInterventionResult:
    record: CampaignRecord
    observation: CampaignHealthObservation
    decision: HealthDecision
    executed: bool
    handler_result: object | None = None


class CampaignHealthInterventionCoordinator:
    """Validate durable state and explicitly route one health intervention."""

    def __init__(
        self,
        *,
        repository: CampaignRepository,
        policy: CampaignHealthPolicy | None = None,
        handlers: Mapping[HealthInterventionAction, HealthInterventionHandler]
        | None = None,
    ) -> None:
        if repository is None:
            raise CampaignValidationError("repository is required")
        self._repository = repository
        self._policy = policy if policy is not None else CampaignHealthPolicy()
        normalized: dict[HealthInterventionAction, HealthInterventionHandler] = {}
        for raw_action, handler in (handlers or {}).items():
            try:
                action = HealthInterventionAction(raw_action)
            except ValueError as exc:
                raise CampaignValidationError(
                    "health intervention handler action is unsupported"
                ) from exc
            if action is HealthInterventionAction.NONE:
                raise CampaignValidationError(
                    "HealthInterventionAction.NONE cannot have a handler"
                )
            if not callable(handler):
                raise CampaignValidationError(
                    "health intervention handlers must be callable"
                )
            normalized[action] = handler
        self._handlers = MappingProxyType(normalized)

    def evaluate(
        self,
        observation: CampaignHealthObservation,
    ) -> HealthInterventionResult:
        record = self._validated_record(observation)
        decision = self._policy.assess(observation)
        return HealthInterventionResult(
            record=record,
            observation=observation,
            decision=decision,
            executed=False,
        )

    def execute(
        self,
        observation: CampaignHealthObservation,
    ) -> HealthInterventionResult:
        evaluated = self.evaluate(observation)
        action = evaluated.decision.action
        if action is HealthInterventionAction.NONE:
            return evaluated
        handler = self._handlers.get(action)
        if handler is None:
            raise HealthInterventionCompositionError(
                f"no handler is configured for health intervention {action.value}"
            )
        try:
            handler_result = handler(
                evaluated.record,
                observation,
                evaluated.decision,
            )
        except Exception as exc:
            raise HealthInterventionExecutionError(
                f"health intervention {action.value} failed: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        return HealthInterventionResult(
            record=evaluated.record,
            observation=observation,
            decision=evaluated.decision,
            executed=True,
            handler_result=handler_result,
        )

    def _validated_record(
        self,
        observation: CampaignHealthObservation,
    ) -> CampaignRecord:
        if not isinstance(observation, CampaignHealthObservation):
            raise CampaignValidationError(
                "observation must be a CampaignHealthObservation"
            )
        record = self._repository.get(observation.campaign_id)
        if record is None:
            raise CampaignNotFoundError(
                f"campaign {observation.campaign_id!r} does not exist"
            )
        if record.state.status is not observation.status:
            raise CampaignConflictError(
                f"health observation state {observation.status.value} does not match "
                f"durable state {record.state.status.value}"
            )
        if observation.observed_at < record.state.updated_at:
            raise CampaignConflictError(
                "health observation predates the durable campaign state"
            )
        return record
