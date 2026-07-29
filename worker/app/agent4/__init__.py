"""Agent 4 autonomous campaign orchestration foundation."""

from .contracts import (
    CampaignEventHandler,
    CampaignEventPublisher,
    CampaignEventRecorder,
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
from .service import (
    CampaignConflictError,
    CampaignNotFoundError,
    CampaignSchedulerService,
    DispatchResult,
    SystemClock,
)

__all__ = [
    "CampaignConflictError",
    "CampaignEvent",
    "CampaignEventHandler",
    "CampaignEventKind",
    "CampaignEventOrderError",
    "CampaignEventPublisher",
    "CampaignEventRecorder",
    "CampaignEventSubscriber",
    "CampaignExecutor",
    "CampaignNotFoundError",
    "CampaignPriority",
    "CampaignQueue",
    "CampaignRecord",
    "CampaignRepository",
    "CampaignRepositoryError",
    "CampaignSchedulerService",
    "CampaignSpec",
    "CampaignState",
    "CampaignStatus",
    "CampaignTransitionError",
    "CampaignValidationError",
    "Clock",
    "DispatchResult",
    "DuplicateCampaignError",
    "IdGenerator",
    "InMemoryCampaignEventBus",
    "JsonCampaignRepository",
    "SystemClock",
    "transition_campaign",
    "utc_now",
]
