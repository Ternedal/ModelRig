"""Stable dependency boundaries for the dormant Agent 4 foundation."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import (
    TYPE_CHECKING,
    Callable,
    Iterable,
    Mapping,
    Protocol,
    runtime_checkable,
)

if TYPE_CHECKING:
    from .checkpoint import CampaignCheckpoint
    from .resources import ResourceLease
    from .timeline import (
        CampaignEvidenceReference,
        CampaignTimelineEntry,
        CampaignTimelineVerification,
    )

from .domain import (
    CampaignEvent,
    CampaignEventKind,
    CampaignRecord,
    CampaignSpec,
    CampaignState,
    JsonValue,
)


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
class CampaignCheckpointStore(Protocol):
    def save(self, checkpoint: "CampaignCheckpoint") -> None:
        """Persist one immutable checkpoint."""

    def get(
        self,
        campaign_id: str,
        checkpoint_id: str,
    ) -> "CampaignCheckpoint | None":
        """Return one checkpoint or none when it does not exist."""

    def list(self, campaign_id: str) -> tuple["CampaignCheckpoint", ...]:
        """Return checkpoints ordered by revision and creation time."""

    def latest(self, campaign_id: str) -> "CampaignCheckpoint | None":
        """Return the latest checkpoint for one campaign."""

    def delete(self, campaign_id: str, checkpoint_id: str) -> bool:
        """Delete one checkpoint and report whether it existed."""


@runtime_checkable
class CampaignTimelineStore(Protocol):
    def append(
        self,
        event: CampaignEvent,
        *,
        evidence: Iterable["CampaignEvidenceReference"] = (),
    ) -> "CampaignTimelineEntry":
        """Append one immutable event and optional evidence references."""

    def list(self, campaign_id: str) -> tuple["CampaignTimelineEntry", ...]:
        """Return a fully validated timeline snapshot."""

    def latest(self, campaign_id: str) -> "CampaignTimelineEntry | None":
        """Return the validated timeline head for one campaign."""

    def verify(self, campaign_id: str) -> "CampaignTimelineVerification":
        """Validate the complete chain and return its summary."""

    def replay(
        self,
        campaign_id: str,
        handler: Callable[["CampaignTimelineEntry"], None],
    ) -> int:
        """Replay a validated timeline and return the delivered entry count."""


CampaignResourceResolver = Callable[[CampaignSpec], Mapping[str, int]]


@runtime_checkable
class CampaignResourceLeaseManager(Protocol):
    def try_acquire(
        self,
        campaign_id: str,
        resources: Mapping[str, int],
        *,
        now: datetime,
        ttl: timedelta,
    ) -> "ResourceLease | None":
        """Atomically acquire all requested resources or return none."""

    def renew(
        self,
        lease_id: str,
        *,
        now: datetime,
        ttl: timedelta,
    ) -> "ResourceLease":
        """Renew one active lease."""

    def for_campaign(
        self,
        campaign_id: str,
        *,
        now: datetime,
    ) -> "ResourceLease | None":
        """Return the active lease for one campaign."""

    def release_campaign(self, campaign_id: str) -> bool:
        """Release resource ownership for one campaign."""


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
class CampaignEventRecorder(Protocol):
    def record(
        self,
        campaign_id: str,
        kind: CampaignEventKind,
        *,
        occurred_at: datetime,
        payload: Mapping[str, JsonValue] | None = None,
    ) -> CampaignEvent:
        """Create and publish the next ordered event for one campaign."""


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
