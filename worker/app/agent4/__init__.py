"""Agent 4 autonomous campaign orchestration foundation."""

from .contracts import (
    CampaignEventHandler,
    CampaignEventPublisher,
    CampaignEventSubscriber,
    CampaignExecutor,
    CampaignRepository,
    Clock,
    IdGenerator,
)
from .domain import (
    CampaignEvent,
    CampaignEventKind,
    CampaignPriority,
    CampaignRecord,
    CampaignSpec,
    CampaignState,
    CampaignStatus,
    CampaignTransitionError,
    CampaignValidationError,
    transition_campaign,
    utc_now,
)
from .event_bus import CampaignEventOrderError, InMemoryCampaignEventBus
from .repository import CampaignRepositoryError, JsonCampaignRepository
from .scheduler import CampaignQueue, DuplicateCampaignError

__all__ = [
    "CampaignEvent",
    "CampaignEventHandler",
    "CampaignEventKind",
    "CampaignEventOrderError",
    "CampaignEventPublisher",
    "CampaignEventSubscriber",
    "CampaignExecutor",
    "CampaignPriority",
    "CampaignQueue",
    "CampaignRecord",
    "CampaignRepository",
    "CampaignRepositoryError",
    "CampaignSpec",
    "CampaignState",
    "CampaignStatus",
    "CampaignTransitionError",
    "CampaignValidationError",
    "Clock",
    "DuplicateCampaignError",
    "IdGenerator",
    "InMemoryCampaignEventBus",
    "JsonCampaignRepository",
    "transition_campaign",
    "utc_now",
]
