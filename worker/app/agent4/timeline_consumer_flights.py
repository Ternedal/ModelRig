"""Process-local single-flight guards for Agent 4 timeline consumers."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Callable, TypeVar

from .domain import CampaignValidationError
from .timeline import CampaignTimelineEntry
from .timeline_consumers import (
    CampaignTimelineConsumerBatchResult,
    CampaignTimelineConsumerService,
)


_Result = TypeVar("_Result")


class CampaignTimelineConsumerFlightError(RuntimeError):
    """Base error for process-local timeline consumer single-flight operations."""


class CampaignTimelineConsumerBusyError(CampaignTimelineConsumerFlightError):
    """Raised when the same campaign/consumer batch is already running."""


class CampaignTimelineConsumerFlightConflictError(CampaignTimelineConsumerFlightError):
    """Raised when a stale or foreign flight token is released."""


def _require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CampaignValidationError(f"{field_name} must not be empty")
    return value.strip()


@dataclass(frozen=True, slots=True)
class CampaignTimelineConsumerFlight:
    campaign_id: str
    consumer_id: str
    token: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "campaign_id", _require_text(self.campaign_id, "campaign_id")
        )
        object.__setattr__(
            self, "consumer_id", _require_text(self.consumer_id, "consumer_id")
        )
        if isinstance(self.token, bool) or not isinstance(self.token, int) or self.token < 1:
            raise CampaignValidationError("token must be a positive integer")


class InMemoryCampaignTimelineConsumerSingleFlight:
    """Shared process-local guard for one active batch per consumer key."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._next_token = 1
        self._active: dict[
            tuple[str, str], CampaignTimelineConsumerFlight
        ] = {}

    def acquire(
        self, campaign_id: str, consumer_id: str
    ) -> CampaignTimelineConsumerFlight:
        campaign = _require_text(campaign_id, "campaign_id")
        consumer = _require_text(consumer_id, "consumer_id")
        key = (campaign, consumer)
        with self._lock:
            if key in self._active:
                raise CampaignTimelineConsumerBusyError(
                    f"consumer {consumer!r} is already active for campaign {campaign!r}"
                )
            flight = CampaignTimelineConsumerFlight(
                campaign_id=campaign,
                consumer_id=consumer,
                token=self._next_token,
            )
            self._next_token += 1
            self._active[key] = flight
            return flight

    def release(self, flight: CampaignTimelineConsumerFlight) -> None:
        if not isinstance(flight, CampaignTimelineConsumerFlight):
            raise TypeError("flight must be CampaignTimelineConsumerFlight")
        key = (flight.campaign_id, flight.consumer_id)
        with self._lock:
            current = self._active.get(key)
            if current != flight:
                raise CampaignTimelineConsumerFlightConflictError(
                    "consumer flight token is stale or foreign"
                )
            del self._active[key]

    def is_active(self, campaign_id: str, consumer_id: str) -> bool:
        key = (
            _require_text(campaign_id, "campaign_id"),
            _require_text(consumer_id, "consumer_id"),
        )
        with self._lock:
            return key in self._active

    def snapshot(self) -> tuple[CampaignTimelineConsumerFlight, ...]:
        with self._lock:
            return tuple(
                self._active[key]
                for key in sorted(self._active)
            )

    def run(
        self,
        campaign_id: str,
        consumer_id: str,
        operation: Callable[[], _Result],
    ) -> _Result:
        if not callable(operation):
            raise TypeError("operation must be callable")
        flight = self.acquire(campaign_id, consumer_id)
        try:
            return operation()
        finally:
            self.release(flight)


class SingleFlightCampaignTimelineConsumerService:
    """A4-08 consumer service guarded for same-process overlapping batches."""

    def __init__(
        self,
        consumer: CampaignTimelineConsumerService,
        flights: InMemoryCampaignTimelineConsumerSingleFlight,
    ) -> None:
        if not isinstance(consumer, CampaignTimelineConsumerService):
            raise TypeError("consumer must be CampaignTimelineConsumerService")
        if not isinstance(flights, InMemoryCampaignTimelineConsumerSingleFlight):
            raise TypeError("flights must be InMemoryCampaignTimelineConsumerSingleFlight")
        self._consumer = consumer
        self._flights = flights

    def consume_batch(
        self,
        campaign_id: str,
        consumer_id: str,
        handler: Callable[[CampaignTimelineEntry], None],
        **kwargs,
    ) -> CampaignTimelineConsumerBatchResult:
        return self._flights.run(
            campaign_id,
            consumer_id,
            lambda: self._consumer.consume_batch(
                campaign_id,
                consumer_id,
                handler,
                **kwargs,
            ),
        )
