"""Concrete caller-driven adapters for Agent 4 health interventions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from types import MappingProxyType
from typing import Callable, Mapping, Protocol, runtime_checkable

from .checkpoint import CampaignCheckpointService
from .contracts import CampaignEventRecorder, CampaignRepository, Clock
from .domain import (
    CampaignEventKind,
    CampaignRecord,
    CampaignStatus,
    CampaignValidationError,
    JsonValue,
    transition_campaign,
)
from .health import (
    CampaignHealthObservation,
    HealthDecision,
    HealthInterventionAction,
)
from .health_intervention import HealthInterventionHandler
from .service import CampaignConflictError, CampaignNotFoundError


CheckpointPayloadProvider = Callable[
    [CampaignRecord, CampaignHealthObservation, HealthDecision],
    tuple[str, Mapping[str, JsonValue]],
]
ResourceRelease = Callable[[str], object]


@runtime_checkable
class HealthInterventionLifecycleService(Protocol):
    def renew_resources(self, campaign_id: str) -> object:
        """Renew resource ownership for one active campaign."""

    def request_pause(self, campaign_id: str) -> CampaignRecord:
        """Persist and signal a pause request."""


class HealthInterventionAdapterCompositionError(RuntimeError):
    """Raised when concrete health intervention adapters cannot be composed."""


class CampaignHealthFailClosedService:
    """Durably fail an active campaign after revalidating coordinator state."""

    _ACTIVE = frozenset(
        {
            CampaignStatus.RUNNING,
            CampaignStatus.PAUSING,
            CampaignStatus.CANCELLING,
        }
    )

    def __init__(
        self,
        *,
        repository: CampaignRepository,
        events: CampaignEventRecorder,
        clock: Clock,
        release_resources: ResourceRelease | None = None,
    ) -> None:
        if repository is None or events is None or clock is None:
            raise CampaignValidationError(
                "repository, events and clock are required"
            )
        if release_resources is not None and not callable(release_resources):
            raise CampaignValidationError("release_resources must be callable")
        self._repository = repository
        self._events = events
        self._clock = clock
        self._release_resources = release_resources
        self._lock = RLock()

    def fail_closed(
        self,
        record: CampaignRecord,
        observation: CampaignHealthObservation,
        decision: HealthDecision,
    ) -> CampaignRecord:
        if decision.action is not HealthInterventionAction.FAIL_CLOSED:
            raise CampaignValidationError(
                "fail_closed requires a FAIL_CLOSED health decision"
            )
        with self._lock:
            current = self._repository.get(record.spec.campaign_id)
            if current is None:
                raise CampaignNotFoundError(
                    f"campaign {record.spec.campaign_id!r} does not exist"
                )
            if current != record:
                raise CampaignConflictError(
                    "campaign changed after health intervention evaluation"
                )
            if current.state.status not in self._ACTIVE:
                raise CampaignConflictError(
                    f"campaign {current.spec.campaign_id!r} cannot fail closed from "
                    f"{current.state.status.value}"
                )
            now = self._now()
            if now < observation.observed_at:
                raise CampaignConflictError(
                    "health intervention clock predates the observation"
                )
            error = f"watchdog: {decision.reason}"
            failed_state = transition_campaign(
                current.state,
                CampaignStatus.FAILED,
                occurred_at=now,
                error=error,
            )
            failed = CampaignRecord(spec=current.spec, state=failed_state)
            self._repository.save(failed)
            try:
                self._events.record(
                    current.spec.campaign_id,
                    CampaignEventKind.FAILED,
                    occurred_at=failed_state.updated_at,
                    payload={
                        "error": error,
                        "phase": "watchdog",
                        "health_level": decision.level.value,
                        "watchdog_action": decision.action.value,
                    },
                )
            finally:
                if self._release_resources is not None:
                    self._release_resources(current.spec.campaign_id)
            return failed

    def _now(self) -> datetime:
        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise CampaignValidationError(
                "clock must return a timezone-aware datetime"
            )
        return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class HealthInterventionServiceAdapters:
    """Bind health interventions to existing caller-driven Agent 4 services."""

    lifecycle: HealthInterventionLifecycleService
    fail_closed_service: CampaignHealthFailClosedService
    checkpoints: CampaignCheckpointService | None = None
    checkpoint_payload: CheckpointPayloadProvider | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.lifecycle, HealthInterventionLifecycleService):
            raise CampaignValidationError(
                "lifecycle must implement the health intervention lifecycle contract"
            )
        if not isinstance(
            self.fail_closed_service,
            CampaignHealthFailClosedService,
        ):
            raise CampaignValidationError(
                "fail_closed_service must be a CampaignHealthFailClosedService"
            )
        if (self.checkpoints is None) != (self.checkpoint_payload is None):
            raise HealthInterventionAdapterCompositionError(
                "checkpoints and checkpoint_payload must be configured together"
            )
        if self.checkpoint_payload is not None and not callable(self.checkpoint_payload):
            raise CampaignValidationError("checkpoint_payload must be callable")

    def handlers(
        self,
    ) -> Mapping[HealthInterventionAction, HealthInterventionHandler]:
        handlers: dict[HealthInterventionAction, HealthInterventionHandler] = {
            HealthInterventionAction.RENEW_RESOURCES: self._renew_resources,
            HealthInterventionAction.REQUEST_PAUSE: self._request_pause,
            HealthInterventionAction.FAIL_CLOSED: self.fail_closed_service.fail_closed,
        }
        if self.checkpoints is not None:
            handlers[HealthInterventionAction.REQUEST_CHECKPOINT] = self._checkpoint
        return MappingProxyType(handlers)

    def _renew_resources(
        self,
        record: CampaignRecord,
        observation: CampaignHealthObservation,
        decision: HealthDecision,
    ) -> object:
        return self.lifecycle.renew_resources(record.spec.campaign_id)

    def _request_pause(
        self,
        record: CampaignRecord,
        observation: CampaignHealthObservation,
        decision: HealthDecision,
    ) -> CampaignRecord:
        return self.lifecycle.request_pause(record.spec.campaign_id)

    def _checkpoint(
        self,
        record: CampaignRecord,
        observation: CampaignHealthObservation,
        decision: HealthDecision,
    ) -> CampaignRecord:
        assert self.checkpoints is not None
        assert self.checkpoint_payload is not None
        checkpoint_id, payload = self.checkpoint_payload(
            record,
            observation,
            decision,
        )
        if not isinstance(checkpoint_id, str) or not checkpoint_id.strip():
            raise CampaignValidationError(
                "checkpoint payload provider must return a non-empty checkpoint id"
            )
        if not isinstance(payload, Mapping):
            raise CampaignValidationError(
                "checkpoint payload provider must return a mapping payload"
            )
        return self.checkpoints.checkpoint(
            record.spec.campaign_id,
            checkpoint_id.strip(),
            payload,
        )
