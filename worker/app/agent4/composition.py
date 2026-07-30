"""Explicit dormant composition of the Agent 4 single-process runtime.

The factory in this module only wires objects. It creates no directories, performs
no recovery, dispatches no campaign and starts no background work. A host must
explicitly call the returned services.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Mapping

from .checkpoint import CampaignCheckpointService, JsonCheckpointStore
from .contracts import (
    CampaignExecutor,
    CampaignResourceResolver,
    Clock,
)
from .domain import CampaignValidationError
from .health import CampaignWatchdogPolicy
from .operator import Agent4OperatorReadService
from .recovery import CampaignRecoveryReport
from .repository import JsonCampaignRepository
from .resource_admission import ResourceAwareCampaignSchedulerService
from .resources import InMemoryResourceLeaseManager
from .retry import CampaignRetryPlanner, RetryPolicy
from .retry_scheduling import CampaignRetrySchedulingService
from .scheduler import CampaignQueue
from .service import SystemClock
from .timeline import DurableCampaignEventBus, JsonlCampaignTimelineStore
from .watchdog import CampaignWatchdogCoordinator
from .watchdog_adapters import (
    CampaignWatchdogFailClosedService,
    CheckpointPayloadProvider,
    WatchdogServiceAdapters,
)


@dataclass(frozen=True, slots=True)
class Agent4RuntimePaths:
    """Filesystem locations owned by one composed Agent 4 runtime."""

    root: Path
    campaigns: Path
    checkpoints: Path
    timeline: Path

    @classmethod
    def under(cls, root: Path | str) -> "Agent4RuntimePaths":
        if isinstance(root, str) and not root.strip():
            raise CampaignValidationError("root must not be empty")
        try:
            normalized = Path(root)
        except TypeError as exc:
            raise CampaignValidationError("root must be a filesystem path") from exc
        if normalized.exists() and not normalized.is_dir():
            raise CampaignValidationError("root must be a directory path")
        return cls(
            root=normalized,
            campaigns=normalized / "campaigns",
            checkpoints=normalized / "checkpoints",
            timeline=normalized / "timeline",
        )


@dataclass(frozen=True, slots=True)
class Agent4RuntimeContext:
    """Shared, caller-driven Agent 4 components for one process."""

    paths: Agent4RuntimePaths
    repository: JsonCampaignRepository
    checkpoint_store: JsonCheckpointStore
    timeline: JsonlCampaignTimelineStore
    events: DurableCampaignEventBus
    queue: CampaignQueue
    resources: InMemoryResourceLeaseManager
    clock: Clock
    scheduler: ResourceAwareCampaignSchedulerService
    operator: Agent4OperatorReadService
    checkpoints: CampaignCheckpointService
    retry_planner: CampaignRetryPlanner
    retries: CampaignRetrySchedulingService
    watchdog_fail_closed: CampaignWatchdogFailClosedService

    def recover(self) -> CampaignRecoveryReport:
        """Explicitly run startup recovery; composition itself never calls this."""

        return self.scheduler.recover()

    def watchdog(
        self,
        *,
        policy: CampaignWatchdogPolicy | None = None,
        checkpoint_payload: CheckpointPayloadProvider | None = None,
    ) -> CampaignWatchdogCoordinator:
        """Create an explicit watchdog coordinator over the shared runtime services."""

        adapters = WatchdogServiceAdapters(
            lifecycle=self.scheduler,
            fail_closed_service=self.watchdog_fail_closed,
            checkpoints=self.checkpoints if checkpoint_payload is not None else None,
            checkpoint_payload=checkpoint_payload,
        )
        return CampaignWatchdogCoordinator(
            repository=self.repository,
            policy=policy,
            handlers=adapters.handlers(),
        )


def compose_agent4_runtime(
    root: Path | str,
    *,
    executor: CampaignExecutor,
    resource_capacities: Mapping[str, int],
    resource_resolver: CampaignResourceResolver,
    clock: Clock | None = None,
    resource_lease_ttl: timedelta = timedelta(minutes=15),
    retry_policy: RetryPolicy | None = None,
) -> Agent4RuntimeContext:
    """Wire a dormant Agent 4 runtime around one explicit executor boundary."""

    if not isinstance(executor, CampaignExecutor):
        raise CampaignValidationError(
            "executor must implement the CampaignExecutor contract"
        )
    if not callable(resource_resolver):
        raise CampaignValidationError("resource_resolver must be callable")
    if retry_policy is not None and not isinstance(retry_policy, RetryPolicy):
        raise CampaignValidationError("retry_policy must be a RetryPolicy")

    paths = Agent4RuntimePaths.under(root)
    runtime_clock = clock if clock is not None else SystemClock()
    if not isinstance(runtime_clock, Clock):
        raise CampaignValidationError("clock must implement the Clock contract")

    repository = JsonCampaignRepository(paths.campaigns)
    checkpoint_store = JsonCheckpointStore(paths.checkpoints)
    timeline = JsonlCampaignTimelineStore(paths.timeline)
    events = DurableCampaignEventBus(timeline)
    queue = CampaignQueue()
    resources = InMemoryResourceLeaseManager(resource_capacities)
    scheduler = ResourceAwareCampaignSchedulerService(
        repository=repository,
        executor=executor,
        events=events,
        clock=runtime_clock,
        queue=queue,
        resource_leases=resources,
        resource_resolver=resource_resolver,
        resource_lease_ttl=resource_lease_ttl,
    )
    operator = Agent4OperatorReadService(
        scheduler=scheduler,
        timeline=timeline,
    )
    checkpoints = CampaignCheckpointService(
        repository=repository,
        checkpoints=checkpoint_store,
        events=events,
        clock=runtime_clock,
    )
    retry_planner = CampaignRetryPlanner(policy=retry_policy)
    retries = CampaignRetrySchedulingService(
        repository=repository,
        queue=queue,
        events=events,
        clock=runtime_clock,
        planner=retry_planner,
        release_resources=resources.release_campaign,
    )
    watchdog_fail_closed = CampaignWatchdogFailClosedService(
        repository=repository,
        events=events,
        clock=runtime_clock,
        release_resources=resources.release_campaign,
    )
    return Agent4RuntimeContext(
        paths=paths,
        repository=repository,
        checkpoint_store=checkpoint_store,
        timeline=timeline,
        events=events,
        queue=queue,
        resources=resources,
        clock=runtime_clock,
        scheduler=scheduler,
        operator=operator,
        checkpoints=checkpoints,
        retry_planner=retry_planner,
        retries=retries,
        watchdog_fail_closed=watchdog_fail_closed,
    )
