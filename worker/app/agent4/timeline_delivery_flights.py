"""Shared process-local single-flight guards for A4-06 timeline delivery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Callable, TypeVar

from .domain import CampaignValidationError
from .timeline import CampaignTimelineEntry
from .timeline_delivery import (
    CampaignTimelineDeliveryResult,
    CampaignTimelineDeliveryService,
)

_Result = TypeVar("_Result")


class CampaignTimelineDeliveryFlightError(RuntimeError):
    """Base error for process-local delivery-flight operations."""


class CampaignTimelineDeliveryBusyError(CampaignTimelineDeliveryFlightError):
    """Raised when the same consumer/campaign delivery is already active."""


class CampaignTimelineDeliveryFlightConflictError(
    CampaignTimelineDeliveryFlightError
):
    """Raised when a stale or foreign delivery-flight token is released."""


def _require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CampaignValidationError(f"{field_name} must not be empty")
    return value.strip()


@dataclass(frozen=True, slots=True)
class CampaignTimelineDeliveryFlight:
    """One process-local claim for a consumer/campaign delivery operation."""

    consumer_id: str
    campaign_id: str
    token: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "consumer_id",
            _require_text(self.consumer_id, "consumer_id"),
        )
        object.__setattr__(
            self,
            "campaign_id",
            _require_text(self.campaign_id, "campaign_id"),
        )
        if (
            isinstance(self.token, bool)
            or not isinstance(self.token, int)
            or self.token < 1
        ):
            raise CampaignValidationError("token must be a positive integer")


class InMemoryCampaignTimelineDeliverySingleFlight:
    """Allow one active delivery per consumer/campaign key in one process."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._next_token = 1
        self._active: dict[
            tuple[str, str], CampaignTimelineDeliveryFlight
        ] = {}

    def acquire(
        self,
        consumer_id: str,
        campaign_id: str,
    ) -> CampaignTimelineDeliveryFlight:
        consumer = _require_text(consumer_id, "consumer_id")
        campaign = _require_text(campaign_id, "campaign_id")
        key = (consumer, campaign)
        with self._lock:
            if key in self._active:
                raise CampaignTimelineDeliveryBusyError(
                    f"consumer {consumer!r} is already delivering "
                    f"campaign {campaign!r}"
                )
            flight = CampaignTimelineDeliveryFlight(
                consumer_id=consumer,
                campaign_id=campaign,
                token=self._next_token,
            )
            self._next_token += 1
            self._active[key] = flight
            return flight

    def release(self, flight: CampaignTimelineDeliveryFlight) -> None:
        if not isinstance(flight, CampaignTimelineDeliveryFlight):
            raise TypeError("flight must be CampaignTimelineDeliveryFlight")
        key = (flight.consumer_id, flight.campaign_id)
        with self._lock:
            current = self._active.get(key)
            if current != flight:
                raise CampaignTimelineDeliveryFlightConflictError(
                    "delivery-flight token is stale or foreign"
                )
            del self._active[key]

    def is_active(self, consumer_id: str, campaign_id: str) -> bool:
        key = (
            _require_text(consumer_id, "consumer_id"),
            _require_text(campaign_id, "campaign_id"),
        )
        with self._lock:
            return key in self._active

    def snapshot(self) -> tuple[CampaignTimelineDeliveryFlight, ...]:
        with self._lock:
            return tuple(self._active[key] for key in sorted(self._active))

    def run(
        self,
        consumer_id: str,
        campaign_id: str,
        operation: Callable[[], _Result],
    ) -> _Result:
        if not callable(operation):
            raise TypeError("operation must be callable")
        flight = self.acquire(consumer_id, campaign_id)
        try:
            return operation()
        finally:
            self.release(flight)


class SingleFlightCampaignTimelineDeliveryService:
    """Guard explicit A4-06 delivery across service instances in one process."""

    def __init__(
        self,
        delivery: CampaignTimelineDeliveryService,
        flights: InMemoryCampaignTimelineDeliverySingleFlight,
    ) -> None:
        if not isinstance(delivery, CampaignTimelineDeliveryService):
            raise TypeError("delivery must be CampaignTimelineDeliveryService")
        if not isinstance(
            flights,
            InMemoryCampaignTimelineDeliverySingleFlight,
        ):
            raise TypeError(
                "flights must be InMemoryCampaignTimelineDeliverySingleFlight"
            )
        self._delivery = delivery
        self._flights = flights

    def pending_count(self, consumer_id: str, campaign_id: str) -> int:
        return self._delivery.pending_count(consumer_id, campaign_id)

    def deliver_next(
        self,
        consumer_id: str,
        campaign_id: str,
        handler: Callable[[CampaignTimelineEntry], None],
        *,
        acknowledged_at: datetime,
    ) -> CampaignTimelineDeliveryResult:
        return self._flights.run(
            consumer_id,
            campaign_id,
            lambda: self._delivery.deliver_next(
                consumer_id,
                campaign_id,
                handler,
                acknowledged_at=acknowledged_at,
            ),
        )
