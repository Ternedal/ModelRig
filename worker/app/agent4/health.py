"""Pure health assessment and watchdog decisions for Agent 4 campaigns."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from .domain import CampaignStatus, CampaignValidationError


class HealthLevel(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNRESPONSIVE = "unresponsive"
    UNSAFE = "unsafe"
    NOT_APPLICABLE = "not_applicable"


class WatchdogAction(StrEnum):
    NONE = "none"
    RENEW_RESOURCES = "renew_resources"
    REQUEST_CHECKPOINT = "request_checkpoint"
    REQUEST_PAUSE = "request_pause"
    FAIL_CLOSED = "fail_closed"


@dataclass(frozen=True, slots=True)
class CampaignHealthObservation:
    campaign_id: str
    status: CampaignStatus
    observed_at: datetime
    runtime_started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    progress_at: datetime | None = None
    resource_lease_expires_at: datetime | None = None
    consecutive_failures: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.campaign_id, str) or not self.campaign_id.strip():
            raise CampaignValidationError("campaign_id must not be empty")
        object.__setattr__(self, "campaign_id", self.campaign_id.strip())
        try:
            object.__setattr__(self, "status", CampaignStatus(self.status))
        except ValueError as exc:
            raise CampaignValidationError("status is not supported") from exc
        object.__setattr__(self, "observed_at", _aware_utc(self.observed_at, "observed_at"))
        for name in (
            "runtime_started_at",
            "heartbeat_at",
            "progress_at",
            "resource_lease_expires_at",
        ):
            value = getattr(self, name)
            if value is not None:
                value = _aware_utc(value, name)
                if name != "resource_lease_expires_at" and value > self.observed_at:
                    raise CampaignValidationError(f"{name} cannot be in the future")
                object.__setattr__(self, name, value)
        if (
            isinstance(self.consecutive_failures, bool)
            or not isinstance(self.consecutive_failures, int)
            or self.consecutive_failures < 0
        ):
            raise CampaignValidationError(
                "consecutive_failures must be a non-negative integer"
            )


@dataclass(frozen=True, slots=True)
class WatchdogPolicy:
    heartbeat_timeout: timedelta = timedelta(minutes=2)
    progress_timeout: timedelta = timedelta(minutes=15)
    resource_renewal_window: timedelta = timedelta(minutes=1)
    max_consecutive_failures: int = 3

    def __post_init__(self) -> None:
        for name in (
            "heartbeat_timeout",
            "progress_timeout",
            "resource_renewal_window",
        ):
            value = getattr(self, name)
            if not isinstance(value, timedelta) or value <= timedelta(0):
                raise CampaignValidationError(f"{name} must be a positive timedelta")
        if (
            isinstance(self.max_consecutive_failures, bool)
            or not isinstance(self.max_consecutive_failures, int)
            or self.max_consecutive_failures < 1
        ):
            raise CampaignValidationError(
                "max_consecutive_failures must be an integer of at least 1"
            )


@dataclass(frozen=True, slots=True)
class WatchdogDecision:
    level: HealthLevel
    action: WatchdogAction
    reason: str
    heartbeat_age: timedelta | None = None
    progress_age: timedelta | None = None
    resource_time_remaining: timedelta | None = None

    @property
    def actionable(self) -> bool:
        return self.action is not WatchdogAction.NONE


class CampaignWatchdogPolicy:
    """Deterministically assess one observation without performing side effects."""

    _ACTIVE = frozenset(
        {
            CampaignStatus.RUNNING,
            CampaignStatus.PAUSING,
            CampaignStatus.CANCELLING,
        }
    )

    def __init__(self, policy: WatchdogPolicy | None = None) -> None:
        self._policy = policy if policy is not None else WatchdogPolicy()

    def assess(self, observation: CampaignHealthObservation) -> WatchdogDecision:
        if not isinstance(observation, CampaignHealthObservation):
            raise CampaignValidationError(
                "observation must be a CampaignHealthObservation"
            )
        if observation.status not in self._ACTIVE:
            return WatchdogDecision(
                level=HealthLevel.NOT_APPLICABLE,
                action=WatchdogAction.NONE,
                reason=f"{observation.status.value} campaigns are not actively watched",
            )

        heartbeat_reference = observation.heartbeat_at or observation.runtime_started_at
        heartbeat_age = (
            observation.observed_at - heartbeat_reference
            if heartbeat_reference is not None
            else None
        )
        if heartbeat_age is None:
            return WatchdogDecision(
                level=HealthLevel.UNRESPONSIVE,
                action=WatchdogAction.FAIL_CLOSED,
                reason="active campaign has no runtime start or heartbeat evidence",
            )
        if heartbeat_age >= self._policy.heartbeat_timeout:
            return WatchdogDecision(
                level=HealthLevel.UNRESPONSIVE,
                action=WatchdogAction.FAIL_CLOSED,
                reason="runtime heartbeat is stale",
                heartbeat_age=heartbeat_age,
            )

        if observation.consecutive_failures >= self._policy.max_consecutive_failures:
            return WatchdogDecision(
                level=HealthLevel.DEGRADED,
                action=WatchdogAction.REQUEST_PAUSE,
                reason="consecutive health failures reached the policy threshold",
                heartbeat_age=heartbeat_age,
            )

        progress_age = (
            observation.observed_at - observation.progress_at
            if observation.progress_at is not None
            else None
        )
        if progress_age is not None and progress_age >= self._policy.progress_timeout:
            return WatchdogDecision(
                level=HealthLevel.DEGRADED,
                action=WatchdogAction.REQUEST_CHECKPOINT,
                reason="campaign progress is stalled while heartbeat remains live",
                heartbeat_age=heartbeat_age,
                progress_age=progress_age,
            )

        resource_remaining = (
            observation.resource_lease_expires_at - observation.observed_at
            if observation.resource_lease_expires_at is not None
            else None
        )
        if resource_remaining is not None and resource_remaining <= timedelta(0):
            return WatchdogDecision(
                level=HealthLevel.UNSAFE,
                action=WatchdogAction.FAIL_CLOSED,
                reason="resource lease has expired",
                heartbeat_age=heartbeat_age,
                progress_age=progress_age,
                resource_time_remaining=resource_remaining,
            )
        if (
            resource_remaining is not None
            and resource_remaining <= self._policy.resource_renewal_window
        ):
            return WatchdogDecision(
                level=HealthLevel.DEGRADED,
                action=WatchdogAction.RENEW_RESOURCES,
                reason="resource lease is inside the renewal window",
                heartbeat_age=heartbeat_age,
                progress_age=progress_age,
                resource_time_remaining=resource_remaining,
            )

        return WatchdogDecision(
            level=HealthLevel.HEALTHY,
            action=WatchdogAction.NONE,
            reason="runtime heartbeat and progress are within policy",
            heartbeat_age=heartbeat_age,
            progress_age=progress_age,
            resource_time_remaining=resource_remaining,
        )


def _aware_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CampaignValidationError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)
