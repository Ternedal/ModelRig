"""Concrete caller-driven adapters for Agent 4 watchdog actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from threading import RLock
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
    WatchdogAction,
    WatchdogDecision,
)
from .service import CampaignConflictError, CampaignNotFoundError
from .watchdog import WatchdogActionHandler


CheckpointPayloadProvider = Callable[
    [CampaignRecord, CampaignHealthObservation, WatchdogDecision],
    tuple[str, Mapping[str, JsonValue]],
]
ResourceRelease = Callable[[str], object]


@runtime_checkable
class WatchdogLifecycleService(Protocol):
    def renew_resources(self, campaign_id: str) -> object:
        """Renew resource ownership for one active campaign."""

    def request_pause(self, campaign_id: str) -> CampaignRecord:
        """Persist and signal a pause request."""


class WatchdogAdapterCompositionError(RuntimeError):
    """Raised when concrete watchdog adapters cannot be composed safely."""


class CampaignWatchdogFailClosedService:
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
        decision: WatchdogDecision,
    ) -> CampaignRecord:
        if decision.action is not WatchdogAction.FAIL_CLOSED:
            raise CampaignValidationError(
                "fail_closed requires a FAIL_CLOSED watchdog decision"
            )
        with self._lock:
            current = self._repository.get(record.spec.campaign_id)
            if current is None:
                raise CampaignNotFoundError(
                    f"campaign {record.spec.campaign_id!r} does not exist"
                )
            if current != record:
                raise CampaignConflictError(
                    "campaign changed after watchdog evaluation"
                )
            if current.state.status not in self._ACTIVE:
                raise CampaignConflictError(
                    f"campaign {current.spec.campaign_id!r} cannot fail closed from "
                    f"{current.state.status.value}"
                )
            now = self._now()
            if now < observation.observed_at:
                raise CampaignConflictError(
                    "watchdog execution clock predates the observation"
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
class WatchdogServiceAdapters:
    """Bind watchdog actions to existing caller-driven Agent 4 services."""

    lifecycle: WatchdogLifecycleService
    fail_closed_service: CampaignWatchdogFailClosedService
    checkpoints: CampaignCheckpointService | None = None
    checkpoint_payload: CheckpointPayloadProvider | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.lifecycle, WatchdogLifecycleService):
            raise CampaignValidationError(
                "lifecycle must implement the watchdog lifecycle contract"
            )
        if not isinstance(
            self.fail_closed_service,
            CampaignWatchdogFailClosedService,
        ):
            raise CampaignValidationError(
                "fail_closed_service must be a CampaignWatchdogFailClosedService"
            )
        if (self.checkpoints is None) != (self.checkpoint_payload is None):
            raise WatchdogAdapterCompositionError(
                "checkpoints and checkpoint_payload must be configured together"
            )
        if self.checkpoint_payload is not None and not callable(self.checkpoint_payload):
            raise CampaignValidationError("checkpoint_payload must be callable")

    def handlers(self) -> Mapping[WatchdogAction, WatchdogActionHandler]:
        handlers: dict[WatchdogAction, WatchdogActionHandler] = {
            WatchdogAction.RENEW_RESOURCES: self._renew_resources,
            WatchdogAction.REQUEST_PAUSE: self._request_pause,
            WatchdogAction.FAIL_CLOSED: self.fail_closed_service.fail_closed,
        }
        if self.checkpoints is not None:
            handlers[WatchdogAction.REQUEST_CHECKPOINT] = self._checkpoint
        return MappingProxyType(handlers)

    def _renew_resources(
        self,
        record: CampaignRecord,
        observation: CampaignHealthObservation,
        decision: WatchdogDecision,
    ) -> object:
        return self.lifecycle.renew_resources(record.spec.campaign_id)

    def _request_pause(
        self,
        record: CampaignRecord,
        observation: CampaignHealthObservation,
        decision: WatchdogDecision,
    ) -> CampaignRecord:
        return self.lifecycle.request_pause(record.spec.campaign_id)

    def _checkpoint(
        self,
        record: CampaignRecord,
        observation: CampaignHealthObservation,
        decision: WatchdogDecision,
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
