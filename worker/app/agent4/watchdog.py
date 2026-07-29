"""Caller-driven execution boundary for Agent 4 watchdog decisions."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping

from .contracts import CampaignRepository
from .domain import CampaignRecord, CampaignValidationError
from .health import (
    CampaignHealthObservation,
    CampaignWatchdogPolicy,
    WatchdogAction,
    WatchdogDecision,
)
from .service import CampaignConflictError, CampaignNotFoundError


WatchdogActionHandler = Callable[
    [CampaignRecord, CampaignHealthObservation, WatchdogDecision], object
]


class WatchdogCompositionError(RuntimeError):
    """Raised when an actionable decision has no configured handler."""


class WatchdogExecutionError(RuntimeError):
    """Raised when a configured watchdog handler fails."""


@dataclass(frozen=True, slots=True)
class WatchdogExecutionResult:
    record: CampaignRecord
    observation: CampaignHealthObservation
    decision: WatchdogDecision
    executed: bool
    handler_result: object | None = None


class CampaignWatchdogCoordinator:
    """Validate durable state and explicitly route one watchdog decision."""

    def __init__(
        self,
        *,
        repository: CampaignRepository,
        policy: CampaignWatchdogPolicy | None = None,
        handlers: Mapping[WatchdogAction, WatchdogActionHandler] | None = None,
    ) -> None:
        if repository is None:
            raise CampaignValidationError("repository is required")
        self._repository = repository
        self._policy = policy if policy is not None else CampaignWatchdogPolicy()
        normalized: dict[WatchdogAction, WatchdogActionHandler] = {}
        for raw_action, handler in (handlers or {}).items():
            try:
                action = WatchdogAction(raw_action)
            except ValueError as exc:
                raise CampaignValidationError("watchdog handler action is unsupported") from exc
            if action is WatchdogAction.NONE:
                raise CampaignValidationError("WatchdogAction.NONE cannot have a handler")
            if not callable(handler):
                raise CampaignValidationError("watchdog handlers must be callable")
            normalized[action] = handler
        self._handlers = MappingProxyType(normalized)

    def evaluate(
        self,
        observation: CampaignHealthObservation,
    ) -> WatchdogExecutionResult:
        record = self._validated_record(observation)
        decision = self._policy.assess(observation)
        return WatchdogExecutionResult(
            record=record,
            observation=observation,
            decision=decision,
            executed=False,
        )

    def execute(
        self,
        observation: CampaignHealthObservation,
    ) -> WatchdogExecutionResult:
        evaluated = self.evaluate(observation)
        action = evaluated.decision.action
        if action is WatchdogAction.NONE:
            return evaluated
        handler = self._handlers.get(action)
        if handler is None:
            raise WatchdogCompositionError(
                f"no handler is configured for watchdog action {action.value}"
            )
        try:
            handler_result = handler(
                evaluated.record,
                observation,
                evaluated.decision,
            )
        except Exception as exc:
            raise WatchdogExecutionError(
                f"watchdog action {action.value} failed: {type(exc).__name__}: {exc}"
            ) from exc
        return WatchdogExecutionResult(
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
