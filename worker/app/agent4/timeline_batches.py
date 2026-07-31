"""Bounded caller-driven batches over Agent 4 durable timeline delivery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .domain import CampaignValidationError, _require_text
from .timeline import CampaignTimelineEntry
from .timeline_delivery import (
    CampaignTimelineCursor,
    CampaignTimelineDeliveryService,
)
from .timeline_delivery_flights import (
    InMemoryCampaignTimelineDeliverySingleFlight,
)

MAX_TIMELINE_DELIVERY_BATCH_SIZE = 1_000


def _require_batch_size(value: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > MAX_TIMELINE_DELIVERY_BATCH_SIZE
    ):
        raise CampaignValidationError(
            "max_entries must be an integer between 1 and "
            f"{MAX_TIMELINE_DELIVERY_BATCH_SIZE}"
        )
    return value


@dataclass(frozen=True, slots=True)
class CampaignTimelineBatchDeliveryResult:
    """One bounded at-least-once delivery attempt for a consumer/campaign key."""

    consumer_id: str
    campaign_id: str
    entries: tuple[CampaignTimelineEntry, ...]
    cursor: CampaignTimelineCursor | None
    remaining: int

    def __post_init__(self) -> None:
        consumer_id = _require_text(self.consumer_id, "consumer_id")
        campaign_id = _require_text(self.campaign_id, "campaign_id")
        entries = tuple(self.entries)
        if any(not isinstance(entry, CampaignTimelineEntry) for entry in entries):
            raise CampaignValidationError(
                "batch entries must be CampaignTimelineEntry instances"
            )
        if (
            isinstance(self.remaining, bool)
            or not isinstance(self.remaining, int)
            or self.remaining < 0
        ):
            raise CampaignValidationError("remaining must be a non-negative integer")
        if self.cursor is not None:
            if not isinstance(self.cursor, CampaignTimelineCursor):
                raise CampaignValidationError(
                    "cursor must be CampaignTimelineCursor or none"
                )
            if (
                self.cursor.consumer_id != consumer_id
                or self.cursor.campaign_id != campaign_id
            ):
                raise CampaignValidationError(
                    "batch cursor identity differs from the result identity"
                )
        if entries:
            if self.cursor is None:
                raise CampaignValidationError(
                    "a non-empty batch requires a durable cursor"
                )
            sequences = tuple(entry.event.sequence for entry in entries)
            if sequences != tuple(range(sequences[0], sequences[-1] + 1)):
                raise CampaignValidationError(
                    "batch entries must form one contiguous timeline range"
                )
            if (
                self.cursor.sequence != entries[-1].event.sequence
                or self.cursor.entry_hash != entries[-1].entry_hash
            ):
                raise CampaignValidationError(
                    "batch cursor must bind the final delivered entry"
                )
        object.__setattr__(self, "consumer_id", consumer_id)
        object.__setattr__(self, "campaign_id", campaign_id)
        object.__setattr__(self, "entries", entries)

    @property
    def delivered_count(self) -> int:
        return len(self.entries)

    @property
    def completed(self) -> bool:
        return self.remaining == 0


class CampaignTimelineBatchDeliveryService:
    """Deliver a bounded batch while holding one shared process-local flight."""

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

    def deliver_batch(
        self,
        consumer_id: str,
        campaign_id: str,
        handler: Callable[[CampaignTimelineEntry], None],
        *,
        acknowledged_at: datetime,
        max_entries: int = 100,
    ) -> CampaignTimelineBatchDeliveryResult:
        if not callable(handler):
            raise TypeError("timeline batch handler must be callable")
        consumer_id = _require_text(consumer_id, "consumer_id")
        campaign_id = _require_text(campaign_id, "campaign_id")
        max_entries = _require_batch_size(max_entries)
        return self._flights.run(
            consumer_id,
            campaign_id,
            lambda: self._deliver_locked_batch(
                consumer_id,
                campaign_id,
                handler,
                acknowledged_at=acknowledged_at,
                max_entries=max_entries,
            ),
        )

    def _deliver_locked_batch(
        self,
        consumer_id: str,
        campaign_id: str,
        handler: Callable[[CampaignTimelineEntry], None],
        *,
        acknowledged_at: datetime,
        max_entries: int,
    ) -> CampaignTimelineBatchDeliveryResult:
        entries: list[CampaignTimelineEntry] = []
        cursor: CampaignTimelineCursor | None = None
        remaining = 0
        for _ in range(max_entries):
            result = self._delivery.deliver_next(
                consumer_id,
                campaign_id,
                handler,
                acknowledged_at=acknowledged_at,
            )
            cursor = result.cursor
            remaining = result.remaining
            if not result.delivered:
                break
            assert result.entry is not None
            entries.append(result.entry)
            if remaining == 0:
                break
        return CampaignTimelineBatchDeliveryResult(
            consumer_id=consumer_id,
            campaign_id=campaign_id,
            entries=tuple(entries),
            cursor=cursor,
            remaining=remaining,
        )
