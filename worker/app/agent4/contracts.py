"""Stable dependency boundaries for the dormant Agent 4 foundation."""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Protocol, runtime_checkable

from .domain import CampaignEvent, CampaignRecord, CampaignSpec, CampaignState


@runtime_checkable
class CampaignRepository(Protocol):
    def save(self, record: CampaignRecord) -> None:
        """Atomically create or replace a campaign record."""

    def get(self, campaign_id: str) -> CampaignRecord | None:
        """Return one campaign record, or none when it does not exist."""

    def list(self) -> tuple[CampaignRecord, ...]:
        """Return a stable snapshot of all campaign records."""

    def delete(self, campaign_id: str) -> bool:
        """Delete one record and report whether it existed."""


@runtime_checkable
class CampaignExecutor(Protocol):
    def dispatch(self, spec: CampaignSpec, state: CampaignState) -> str:
        """Delegate one campaign attempt and return its runtime reference."""

    def signal(self, campaign_id: str, command: str) -> None:
        """Forward a lifecycle command to the delegated runtime."""


CampaignEventHandler = Callable[[CampaignEvent], None]


@runtime_checkable
class CampaignEventPublisher(Protocol):
    def publish(self, event: CampaignEvent) -> None:
        """Publish one validated, ordered campaign event."""


@runtime_checkable
class CampaignEventSubscriber(Protocol):
    def subscribe(self, handler: CampaignEventHandler) -> Callable[[], None]:
        """Register a handler and return an idempotent unsubscribe callback."""


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """Return a timezone-aware current timestamp."""


@runtime_checkable
class IdGenerator(Protocol):
    def new_id(self) -> str:
        """Return a new non-empty identifier."""
