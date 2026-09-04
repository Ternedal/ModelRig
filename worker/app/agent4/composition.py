"""Explicit dormant composition of the Agent 4 single-process runtime.

The factory in this module only wires objects. It creates no directories,
performs no recovery, dispatches no campaign and starts no background work.
A host must explicitly call the returned services.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from threading import RLock
from typing import Mapping
from weakref import WeakValueDictionary

from .campaign_queue import CampaignQueue
from .checkpoint import CampaignCheckpointService, JsonCheckpointStore
from .contracts import CampaignResourceResolver, Clock
from .domain import CampaignValidationError
from .failure_handling import CampaignFailureHandlingService
from .handoff import CampaignHandoffExecutor
from .handoff_runtime import (
    CampaignHandoffRecoveryReport,
    ResourceAwareCampaignHandoffSchedulerService,
)
from .health import CampaignHealthPolicy
from .health_intervention import CampaignHealthInterventionCoordinator
from .health_intervention_adapters import (
    CampaignHealthFailClosedService,
    CheckpointPayloadProvider,
    HealthInterventionServiceAdapters,
)
from .operator import Agent4OperatorReadService
from .operator_evidence import Agent4OperatorEvidenceReadService
from .projected_services import (
    ProjectedCampaignCheckpointService,
    ProjectedCampaignFailureHandlingService,
    ProjectedCampaignHealthFailClosedService,
)
from .projection import (
    CampaignProjectionReconciler,
    CampaignProjectionReport,
    CampaignStateProjectionService,
)
from .repository import JsonCampaignRepository
from .resources import InMemoryResourceLeaseManager
from .retry import CampaignRetryPlanner, RetryPolicy
from .service import SystemClock
from .snapshot_publisher import Agent4OperatorSnapshotPublisher
from .snapshot_store import JsonOperatorSnapshotStore, OperatorRootSnapshot
from .timeline import JsonCampaignTimelineStore
from .timeline_batches import CampaignTimelineBatchDeliveryService
from .timeline_delivery import (
    CampaignTimelineDeliveryService,
    JsonCampaignTimelineCursorStore,
)
from .timeline_delivery_flights import (
    InMemoryCampaignTimelineDeliverySingleFlight,
    SingleFlightCampaignTimelineDeliveryService,
)
from .timeline_evidence import (
    CampaignEvidenceRecordService,
    JsonCampaignEvidenceRecordStore,
)
from .timeline_evidence_query import CampaignEvidenceQueryService
from .timeline_query import CampaignTimelineQueryService
from .timeline_recorder import TimelineCampaignEventRecorder

_WRITER_ROOTS: WeakValueDictionary[str, JsonCampaignRepository] = WeakValueDictionary()
_WRITER_ROOTS_LOCK = RLock()


def _canonical_root(root: Path) -> str:
    return os.path.normcase(str(root.resolve(strict=False)))


@dataclass(frozen=True, slots=True)
class Agent4RuntimePaths:
    """Filesystem locations owned by one composed Agent 4 runtime."""

    root: Path
    campaigns: Path
    checkpoints: Path
    timeline: Path
    evidence: Path
    delivery_cursors: Path
    operator_snapshots: Path

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
            evidence=normalized / "evidence",
            delivery_cursors=normalized / "delivery-cursors",
            operator_snapshots=normalized / "operator-snapshots",
        )


@dataclass(frozen=True, slots=True)
class Agent4RuntimeContext:
    """One explicit, caller-driven Agent 4 object graph for a process."""

    paths: Agent4RuntimePaths
    repository: JsonCampaignRepository
    checkpoint_store: JsonCheckpointStore
    timeline: JsonCampaignTimelineStore
    evidence_records: JsonCampaignEvidenceRecordStore
    evidence_recorder: CampaignEvidenceRecordService
    event_recorder: TimelineCampaignEventRecorder
    reconciliation: CampaignProjectionReconciler
    projections: CampaignStateProjectionService
    delivery_cursor_store: JsonCampaignTimelineCursorStore
    queue: CampaignQueue
    resources: InMemoryResourceLeaseManager
    clock: Clock
    scheduler: ResourceAwareCampaignHandoffSchedulerService
    checkpoints: CampaignCheckpointService
    retry_planner: CampaignRetryPlanner
    failures: CampaignFailureHandlingService
    health_fail_closed: CampaignHealthFailClosedService
    delivery_flights: InMemoryCampaignTimelineDeliverySingleFlight
    delivery: CampaignTimelineDeliveryService
    guarded_delivery: SingleFlightCampaignTimelineDeliveryService
    batches: CampaignTimelineBatchDeliveryService
    query: CampaignTimelineQueryService
    evidence_query: CampaignEvidenceQueryService
    operator: Agent4OperatorReadService
    evidence_operator: Agent4OperatorEvidenceReadService
    snapshot_store: JsonOperatorSnapshotStore
    snapshot_publisher: Agent4OperatorSnapshotPublisher

    def recover(self) -> CampaignHandoffRecoveryReport:
        """Explicitly run startup recovery; composition never calls it."""

        return self.scheduler.recover()

    def reconcile_projections(self) -> CampaignProjectionReport:
        """Explicitly repair pending audit projections; composition never calls it."""

        return self.reconciliation.reconcile()

    def publish_operator_snapshot(self) -> OperatorRootSnapshot:
        """Explicitly publish one immutable operator read root."""

        return self.snapshot_publisher.publish()

    def prune_operator_snapshots(self) -> tuple[str, ...]:
        """Explicitly run retention/GC after publication."""

        return self.snapshot_publisher.prune()

    def health_intervention(
        self,
        *,
        policy: CampaignHealthPolicy | None = None,
        checkpoint_payload: CheckpointPayloadProvider | None = None,
    ) -> CampaignHealthInterventionCoordinator:
        """Build an intervention coordinator only when a caller requests one."""

        adapters = HealthInterventionServiceAdapters(
            lifecycle=self.scheduler,
            fail_closed_service=self.health_fail_closed,
            checkpoints=(
                self.checkpoints if checkpoint_payload is not None else None
            ),
            checkpoint_payload=checkpoint_payload,
        )
        return CampaignHealthInterventionCoordinator(
            repository=self.repository,
            policy=policy,
            handlers=adapters.handlers(),
        )


def compose_agent4_runtime(
    root: Path | str,
    *,
    executor: CampaignHandoffExecutor,
    resource_capacities: Mapping[str, int],
    resource_resolver: CampaignResourceResolver,
    clock: Clock | None = None,
    resource_lease_ttl: timedelta = timedelta(minutes=15),
    retry_policy: RetryPolicy | None = None,
) -> Agent4RuntimeContext:
    """Wire the dormant B-reference runtime around the typed handoff boundary."""

    if not isinstance(executor, CampaignHandoffExecutor):
        raise CampaignValidationError(
            "executor must implement the CampaignHandoffExecutor contract"
        )
    if not callable(resource_resolver):
        raise CampaignValidationError("resource_resolver must be callable")
    if retry_policy is not None and not isinstance(retry_policy, RetryPolicy):
        raise CampaignValidationError("retry_policy must be a RetryPolicy")

    paths = Agent4RuntimePaths.under(root)
    runtime_clock = clock if clock is not None else SystemClock()
    if not isinstance(runtime_clock, Clock):
        raise CampaignValidationError("clock must implement the Clock contract")

    canonical_root = _canonical_root(paths.root)
    repository = JsonCampaignRepository(paths.campaigns)
    with _WRITER_ROOTS_LOCK:
        if _WRITER_ROOTS.get(canonical_root) is not None:
            raise CampaignValidationError(
                "an Agent 4 writer context already owns this canonical dataroot"
            )
        _WRITER_ROOTS[canonical_root] = repository

    checkpoint_store = JsonCheckpointStore(paths.checkpoints)
    timeline = JsonCampaignTimelineStore(paths.timeline)
    evidence_records = JsonCampaignEvidenceRecordStore(paths.evidence)
    evidence_recorder = CampaignEvidenceRecordService(
        timeline=timeline,
        records=evidence_records,
    )
    event_recorder = TimelineCampaignEventRecorder(timeline)
    reconciliation = CampaignProjectionReconciler(
        repository=repository,
        timeline=timeline,
    )
    projections = CampaignStateProjectionService(
        repository=repository,
        reconciler=reconciliation,
    )
    delivery_cursor_store = JsonCampaignTimelineCursorStore(
        paths.delivery_cursors
    )
    queue = CampaignQueue()
    resources = InMemoryResourceLeaseManager(resource_capacities)
    scheduler = ResourceAwareCampaignHandoffSchedulerService(
        repository=repository,
        executor=executor,
        events=event_recorder,
        clock=runtime_clock,
        queue=queue,
        projections=projections,
        reconciler=reconciliation,
        resource_leases=resources,
        resource_resolver=resource_resolver,
        resource_lease_ttl=resource_lease_ttl,
    )
    checkpoints = ProjectedCampaignCheckpointService(
        repository=repository,
        checkpoints=checkpoint_store,
        events=event_recorder,
        clock=runtime_clock,
        projections=projections,
    )
    retry_planner = CampaignRetryPlanner(policy=retry_policy)
    failures = ProjectedCampaignFailureHandlingService(
        repository=repository,
        queue=queue,
        events=event_recorder,
        clock=runtime_clock,
        planner=retry_planner,
        release_resources=resources.release_campaign,
        projections=projections,
    )
    health_fail_closed = ProjectedCampaignHealthFailClosedService(
        repository=repository,
        events=event_recorder,
        clock=runtime_clock,
        release_resources=resources.release_campaign,
        projections=projections,
    )
    delivery_flights = InMemoryCampaignTimelineDeliverySingleFlight()
    delivery = CampaignTimelineDeliveryService(
        timeline=timeline,
        cursors=delivery_cursor_store,
    )
    guarded_delivery = SingleFlightCampaignTimelineDeliveryService(
        delivery,
        delivery_flights,
    )
    batches = CampaignTimelineBatchDeliveryService(
        delivery,
        delivery_flights,
    )
    query = CampaignTimelineQueryService(timeline)
    evidence_query = CampaignEvidenceQueryService(evidence_records)
    operator = Agent4OperatorReadService(
        scheduler=scheduler,
        timeline=timeline,
        query=query,
    )
    evidence_operator = Agent4OperatorEvidenceReadService(
        scheduler=scheduler,
        records=evidence_records,
        query=evidence_query,
    )
    snapshot_store = JsonOperatorSnapshotStore(
        paths.operator_snapshots,
        clock=runtime_clock.now,
    )
    snapshot_publisher = Agent4OperatorSnapshotPublisher(
        repository=repository,
        timeline=timeline,
        evidence=evidence_records,
        snapshots=snapshot_store,
        clock=runtime_clock,
    )

    return Agent4RuntimeContext(
        paths=paths,
        repository=repository,
        checkpoint_store=checkpoint_store,
        timeline=timeline,
        evidence_records=evidence_records,
        evidence_recorder=evidence_recorder,
        event_recorder=event_recorder,
        reconciliation=reconciliation,
        projections=projections,
        delivery_cursor_store=delivery_cursor_store,
        queue=queue,
        resources=resources,
        clock=runtime_clock,
        scheduler=scheduler,
        checkpoints=checkpoints,
        retry_planner=retry_planner,
        failures=failures,
        health_fail_closed=health_fail_closed,
        delivery_flights=delivery_flights,
        delivery=delivery,
        guarded_delivery=guarded_delivery,
        batches=batches,
        query=query,
        evidence_query=evidence_query,
        operator=operator,
        evidence_operator=evidence_operator,
        snapshot_store=snapshot_store,
        snapshot_publisher=snapshot_publisher,
    )
