"""Caller-driven ADR-A4-008 Slice 3 dispatch and recovery behavior.

The module changes no host routing and starts no background work.  It composes
Slice 1's transport-neutral handoff contract with Slice 2's durable envelope.
External calls happen only from explicit lifecycle or recovery calls.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Iterable, Mapping

from .campaign_queue import CampaignQueue
from .contracts import (
    CampaignEventRecorder,
    CampaignResourceLeaseManager,
    CampaignResourceResolver,
    Clock,
)
from .domain import (
    CampaignEventKind,
    CampaignRecord,
    CampaignSpec,
    CampaignState,
    CampaignStatus,
    CampaignValidationError,
    JsonValue,
    transition_campaign,
)
from .handoff import (
    CampaignDispatchAcknowledgement,
    CampaignDispatchOutcome,
    CampaignDispatchRequest,
    CampaignHandoffExecutor,
    CampaignSignalAcknowledgement,
    CampaignSignalRequest,
    CampaignSignalType,
    DispatchOutcomeKind,
)
from .handoff_persistence import CampaignHandoffIntent, CampaignHandoffPhase
from .projection import (
    CampaignProjectionError,
    CampaignProjectionIntent,
    CampaignProjectionReconciler,
    CampaignProjectionSpec,
    CampaignStateProjectionService,
)
from .repository import JsonCampaignRepository
from .resource_admission import (
    CampaignResourceBlockedError,
    ResourceDispatchResult,
)
from .resources import ResourceLease
from .service import (
    CampaignConflictError,
    CampaignNotFoundError,
    CampaignSchedulerService,
    DispatchResult,
    SystemClock,
)


RESOURCE_RECONCILIATION_BLOCKED_MESSAGE = (
    "resource admission is blocked by unresolved resource reconciliation"
)


class CampaignHandoffUncertainError(CampaignConflictError):
    """A durable handoff exists, but transport did not prove its outcome."""

    def __init__(self, campaign_id: str, intent_id: str, detail: str) -> None:
        super().__init__(
            f"campaign {campaign_id!r} handoff {intent_id!r} is unresolved: {detail}"
        )
        self.campaign_id = campaign_id
        self.intent_id = intent_id
        self.detail = detail


class CampaignResourceReconciliationBlockedError(CampaignResourceBlockedError):
    """The global persisted reconciliation barrier blocks resource admission."""


class ResourceReconciliationResolutionReason(StrEnum):
    RESOURCES_RESTORED = "resources_restored"
    RUNTIME_VERIFIED_TERMINAL = "runtime_verified_terminal"
    CONFLICT_MANUALLY_HANDLED = "conflict_manually_handled"


class HandoffRecoveryAction(StrEnum):
    REQUEUED = "requeued"
    ALREADY_QUEUED = "already_queued"
    RETAINED_PAUSED = "retained_paused"
    RETAINED_TERMINAL = "retained_terminal"
    LEGACY_MARKED_FAILED = "legacy_marked_failed"
    NOT_DISPATCHED_READY = "not_dispatched_ready"
    ACCEPTED = "accepted"
    RUNNING = "running"
    UNKNOWN_INTERVENTION = "unknown_intervention"
    COMPLETED = "completed"
    FAILED = "failed"
    SIGNAL_INTERVENTION = "signal_intervention"


@dataclass(frozen=True, slots=True)
class CampaignHandoffRecoveryDecision:
    campaign_id: str
    previous_status: CampaignStatus
    resulting_status: CampaignStatus
    action: HandoffRecoveryAction
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class CampaignHandoffRecoveryReport:
    started_at: datetime
    completed_at: datetime
    decisions: tuple[CampaignHandoffRecoveryDecision, ...]

    @property
    def scanned(self) -> int:
        return len(self.decisions)

    def count(self, action: HandoffRecoveryAction) -> int:
        return sum(1 for decision in self.decisions if decision.action is action)

    @property
    def requeued(self) -> int:
        return self.count(HandoffRecoveryAction.REQUEUED)

    @property
    def failed_closed(self) -> int:
        return self.count(HandoffRecoveryAction.LEGACY_MARKED_FAILED)


def _projection_intents(
    record: CampaignRecord,
    projections: Iterable[CampaignProjectionSpec],
) -> tuple[CampaignProjectionIntent, ...]:
    return tuple(
        CampaignProjectionIntent(
            campaign_id=record.spec.campaign_id,
            state_revision=record.state.revision,
            kind=projection.kind,
            occurred_at=projection.occurred_at,
            payload=projection.payload,
            producer_id=projection.producer_id,
        )
        for projection in projections
    )


def _atomic_record_and_handoff_acknowledgement(
    repository: JsonCampaignRepository,
    record: CampaignRecord,
    *,
    intent_id: str,
    acknowledgement: CampaignDispatchAcknowledgement | CampaignSignalAcknowledgement,
    projections: Iterable[CampaignProjectionSpec],
) -> None:
    """Rewrite record, one typed acknowledgement and audit intents once.

    Slice 2 intentionally kept acknowledgement state-neutral. Recovery needs to
    update campaign flags/status in the same replacement as the authoritative
    acknowledgement. This helper remains inside the same JsonCampaignRepository
    lock, parser and _write boundary; it is not a second store or journal.
    """

    incoming = _projection_intents(record, projections)
    repository._validate_projection_intents(record, incoming)
    with repository._lock:
        path = repository._path_for(record.spec.campaign_id)
        if not path.exists():
            raise CampaignNotFoundError(
                f"campaign {record.spec.campaign_id!r} was not found"
            )
        previous_record, existing_projections, handoffs = repository._read_envelope(
            path,
            expected_campaign_id=record.spec.campaign_id,
        )
        if record.state.revision < previous_record.state.revision:
            raise CampaignConflictError("recovery record revision cannot regress")
        matching_index = next(
            (
                index
                for index, intent in enumerate(handoffs)
                if intent.intent_id == intent_id
            ),
            None,
        )
        if matching_index is None:
            raise CampaignConflictError(
                f"handoff intent {intent_id!r} was not found"
            )
        previous = handoffs[matching_index]
        updated = previous.acknowledge(acknowledgement)
        rewritten = list(handoffs)
        rewritten[matching_index] = updated
        merged = repository._merge_projections(existing_projections, incoming)
        repository._write(record, merged, tuple(rewritten))


class CampaignHandoffSchedulerService(CampaignSchedulerService):
    """Ordinary caller-driven scheduler using durable typed handoffs."""

    def __init__(
        self,
        *,
        repository: JsonCampaignRepository,
        executor: CampaignHandoffExecutor,
        events: CampaignEventRecorder,
        clock: Clock | None = None,
        queue: CampaignQueue | None = None,
        projections: CampaignStateProjectionService | None = None,
        reconciler: CampaignProjectionReconciler | None = None,
    ) -> None:
        if not isinstance(repository, JsonCampaignRepository):
            raise CampaignValidationError(
                "repository must be a JsonCampaignRepository for durable handoffs"
            )
        if not isinstance(executor, CampaignHandoffExecutor):
            raise CampaignValidationError(
                "executor must implement CampaignHandoffExecutor"
            )
        if reconciler is not None and not isinstance(
            reconciler,
            CampaignProjectionReconciler,
        ):
            raise CampaignValidationError(
                "reconciler must be a CampaignProjectionReconciler"
            )
        super().__init__(
            repository=repository,
            executor=executor,
            events=events,
            clock=clock,
            queue=queue,
            projections=projections,
        )
        self._handoff_repository = repository
        self._handoff_executor = executor
        self._handoff_reconciler = reconciler

    def recover(self) -> CampaignHandoffRecoveryReport:
        with self._lock:
            return CampaignHandoffRecoveryService(
                repository=self._handoff_repository,
                queue=self._queue,
                events=self._events,
                clock=self._clock,
                executor=self._handoff_executor,
                reconciler=self._handoff_reconciler,
            ).recover()

    def dispatch_ready(self) -> DispatchResult | None:
        with self._lock:
            now = self._now()
            spec = self._queue.pop_ready(now)
            if spec is None:
                return None
            current = self._require_record(spec.campaign_id)
            if current.state.status not in {
                CampaignStatus.QUEUED,
                CampaignStatus.SCHEDULED,
            }:
                raise CampaignConflictError(
                    f"campaign {spec.campaign_id!r} cannot dispatch from "
                    f"{current.state.status.value}"
                )
            try:
                running, request, intent = self._persist_dispatch_request(
                    current,
                    occurred_at=now,
                )
            except Exception:
                self._queue.enqueue(spec)
                raise
            return self._execute_dispatch(running, request, intent)

    def request_pause(self, campaign_id: str) -> CampaignRecord:
        with self._lock:
            current = self._require_record(campaign_id)
            if current.state.status is not CampaignStatus.RUNNING:
                raise CampaignConflictError(
                    f"campaign {campaign_id!r} cannot pause from "
                    f"{current.state.status.value}"
                )
            pausing = self._transition(current, CampaignStatus.PAUSING)
            return self._deliver_signal(pausing, CampaignSignalType.PAUSE)

    def resume(self, campaign_id: str) -> CampaignRecord:
        with self._lock:
            current = self._require_record(campaign_id)
            if current.state.status is not CampaignStatus.PAUSED:
                raise CampaignConflictError(
                    f"campaign {campaign_id!r} cannot resume from "
                    f"{current.state.status.value}"
                )
            resumed = self._transition(current, CampaignStatus.RUNNING)
            resumed = CampaignRecord(
                spec=resumed.spec,
                state=replace(resumed.state, attempt=current.state.attempt),
            )
            return self._deliver_signal(resumed, CampaignSignalType.RESUME)

    def request_cancel(self, campaign_id: str) -> CampaignRecord:
        with self._lock:
            current = self._require_record(campaign_id)
            status = current.state.status
            if status is CampaignStatus.CANCELLED:
                return current
            if status in {
                CampaignStatus.QUEUED,
                CampaignStatus.SCHEDULED,
            }:
                cancelled = self._transition(current, CampaignStatus.CANCELLED)
                self._persist_projection(
                    cancelled,
                    CampaignEventKind.CANCELLED,
                    occurred_at=cancelled.state.updated_at,
                    payload={"immediate": True},
                )
                self._queue.remove(campaign_id)
                return cancelled
            if status not in {
                CampaignStatus.RUNNING,
                CampaignStatus.PAUSING,
                CampaignStatus.PAUSED,
            }:
                raise CampaignConflictError(
                    f"campaign {campaign_id!r} cannot cancel from {status.value}"
                )
            cancelling = self._transition(current, CampaignStatus.CANCELLING)
            return self._deliver_signal(cancelling, CampaignSignalType.CANCEL)

    def resolve_resource_reconciliation(
        self,
        campaign_id: str,
        *,
        reason: ResourceReconciliationResolutionReason,
        evidence_pointer: str,
    ) -> CampaignRecord:
        with self._lock:
            current = self._require_record(campaign_id)
            try:
                reason = ResourceReconciliationResolutionReason(reason)
            except ValueError as exc:
                raise CampaignValidationError(
                    "resource reconciliation reason is not supported"
                ) from exc
            if not isinstance(evidence_pointer, str) or not evidence_pointer.strip():
                raise CampaignValidationError("evidence_pointer must not be empty")
            if not current.state.resource_reconciliation_required:
                raise CampaignConflictError(
                    f"campaign {campaign_id!r} has no resource reconciliation marker"
                )
            now = self._now()
            resolved = CampaignRecord(
                spec=current.spec,
                state=replace(
                    current.state,
                    revision=current.state.revision + 1,
                    updated_at=now,
                    resource_reconciliation_required=False,
                ),
            )
            projection = CampaignProjectionSpec(
                kind=CampaignEventKind.RESOURCE_RECONCILIATION_RESOLVED,
                occurred_at=now,
                payload={
                    "reason": reason.value,
                    "evidence_pointer": evidence_pointer.strip(),
                },
                producer_id="handoff-resolution",
            )
            self._handoff_repository.save_with_intents(
                resolved,
                projection_intents=_projection_intents(resolved, (projection,)),
            )
            self._reconcile(campaign_id)
            return resolved

    def _persist_dispatch_request(
        self,
        current: CampaignRecord,
        *,
        occurred_at: datetime,
    ) -> tuple[CampaignRecord, CampaignDispatchRequest, CampaignHandoffIntent]:
        running_state = transition_campaign(
            current.state,
            CampaignStatus.RUNNING,
            occurred_at=occurred_at,
        )
        running = CampaignRecord(spec=current.spec, state=running_state)
        request = CampaignDispatchRequest(
            campaign_id=running.spec.campaign_id,
            attempt=running.state.attempt,
            workflow=running.spec.workflow,
            campaign_revision=running.state.revision,
            parameters=running.spec.parameters,
        )
        handoff = CampaignHandoffIntent(
            campaign_id=running.spec.campaign_id,
            state_revision=running.state.revision,
            request=request,
        )
        projection = CampaignProjectionSpec(
            kind=CampaignEventKind.DISPATCH_REQUESTED,
            occurred_at=occurred_at,
            payload={
                "attempt": running.state.attempt,
                "dispatch_id": request.dispatch_id,
            },
            producer_id="handoff-dispatch",
        )
        self._handoff_repository.save_with_intents(
            running,
            projection_intents=_projection_intents(running, (projection,)),
            handoff_intents=(handoff,),
        )
        self._reconcile(running.spec.campaign_id)
        return running, request, handoff

    def _execute_dispatch(
        self,
        running: CampaignRecord,
        request: CampaignDispatchRequest,
        intent: CampaignHandoffIntent,
    ) -> DispatchResult:
        self._before_external_dispatch()
        try:
            acknowledgement = self._handoff_executor.dispatch(request)
        except Exception as exc:
            return self._dispatch_uncertain_result(running, intent, exc)
        if not isinstance(acknowledgement, CampaignDispatchAcknowledgement):
            return self._dispatch_uncertain_result(
                running,
                intent,
                TypeError("executor returned an unsupported dispatch acknowledgement"),
            )
        projections = (
            CampaignProjectionSpec(
                kind=CampaignEventKind.DISPATCH_CONFIRMED,
                occurred_at=self._now(),
                payload={
                    "attempt": running.state.attempt,
                    "dispatch_id": request.dispatch_id,
                    "runtime_reference": acknowledgement.runtime_reference,
                    "evidence_pointer": acknowledgement.evidence_pointer,
                },
                producer_id="handoff-dispatch",
            ),
            CampaignProjectionSpec(
                kind=CampaignEventKind.STARTED,
                occurred_at=running.state.updated_at,
                payload={
                    "attempt": running.state.attempt,
                    "runtime_reference": acknowledgement.runtime_reference,
                },
                producer_id="handoff-dispatch",
            ),
        )
        try:
            self._handoff_repository.acknowledge_handoff(
                running.spec.campaign_id,
                intent.intent_id,
                acknowledgement,
                projection_intents=_projection_intents(running, projections),
            )
            self._reconcile(running.spec.campaign_id)
        except Exception as exc:
            return self._dispatch_uncertain_result(running, intent, exc)
        return self._dispatch_result(
            record=running,
            runtime_reference=acknowledgement.runtime_reference,
            dispatch_error=None,
        )

    def _deliver_signal(
        self,
        record: CampaignRecord,
        signal_type: CampaignSignalType,
    ) -> CampaignRecord:
        request = CampaignSignalRequest(
            campaign_id=record.spec.campaign_id,
            attempt=record.state.attempt,
            signal_type=signal_type,
            resulting_revision=record.state.revision,
        )
        handoff = CampaignHandoffIntent(
            campaign_id=record.spec.campaign_id,
            state_revision=record.state.revision,
            request=request,
        )
        requested = CampaignProjectionSpec(
            kind=CampaignEventKind.SIGNAL_REQUESTED,
            occurred_at=record.state.updated_at,
            payload={
                "attempt": record.state.attempt,
                "signal_id": request.signal_id,
                "signal_type": signal_type.value,
            },
            producer_id="handoff-signal",
        )
        self._handoff_repository.save_with_intents(
            record,
            projection_intents=_projection_intents(record, (requested,)),
            handoff_intents=(handoff,),
        )
        self._reconcile(record.spec.campaign_id)
        self._before_external_signal(signal_type)
        try:
            acknowledgement = self._handoff_executor.signal(request)
        except Exception as exc:
            raise CampaignHandoffUncertainError(
                record.spec.campaign_id,
                handoff.intent_id,
                f"{type(exc).__name__}: {exc}",
            ) from exc
        if not isinstance(acknowledgement, CampaignSignalAcknowledgement):
            raise CampaignHandoffUncertainError(
                record.spec.campaign_id,
                handoff.intent_id,
                "executor returned an unsupported signal acknowledgement",
            )
        confirmed = CampaignProjectionSpec(
            kind=CampaignEventKind.SIGNAL_CONFIRMED,
            occurred_at=self._now(),
            payload={
                "signal_id": request.signal_id,
                "signal_type": signal_type.value,
                "evidence_pointer": acknowledgement.evidence_pointer,
            },
            producer_id="handoff-signal",
        )
        try:
            self._handoff_repository.acknowledge_handoff(
                record.spec.campaign_id,
                handoff.intent_id,
                acknowledgement,
                projection_intents=_projection_intents(record, (confirmed,)),
            )
            self._reconcile(record.spec.campaign_id)
        except Exception as exc:
            raise CampaignHandoffUncertainError(
                record.spec.campaign_id,
                handoff.intent_id,
                f"{type(exc).__name__}: {exc}",
            ) from exc
        return record

    def _dispatch_uncertain_result(
        self,
        record: CampaignRecord,
        intent: CampaignHandoffIntent,
        exc: Exception,
    ) -> DispatchResult:
        return self._dispatch_result(
            record=record,
            runtime_reference=None,
            dispatch_error=(
                f"unresolved handoff {intent.intent_id}: "
                f"{type(exc).__name__}: {exc}"
            ),
        )

    def _dispatch_result(
        self,
        *,
        record: CampaignRecord,
        runtime_reference: str | None,
        dispatch_error: str | None,
    ) -> DispatchResult:
        return DispatchResult(
            record=record,
            runtime_reference=runtime_reference,
            dispatch_error=dispatch_error,
        )

    def _before_external_dispatch(self) -> None:
        return None

    def _before_external_signal(self, signal_type: CampaignSignalType) -> None:
        return None

    def _reconcile(self, campaign_id: str) -> None:
        if self._handoff_reconciler is None:
            return
        try:
            self._handoff_reconciler.reconcile(campaign_id)
        except CampaignProjectionError:
            raise
        except Exception as exc:
            raise CampaignProjectionError(
                "campaign state is durable but its audit projection remains pending"
            ) from exc


class ResourceAwareCampaignHandoffSchedulerService(CampaignHandoffSchedulerService):
    """Slice 3 reference scheduler with the persisted global barrier."""

    def __init__(
        self,
        *,
        resource_leases: CampaignResourceLeaseManager,
        resource_resolver: CampaignResourceResolver,
        resource_lease_ttl: timedelta = timedelta(minutes=15),
        **kwargs,
    ) -> None:
        if resource_leases is None or resource_resolver is None:
            raise CampaignValidationError(
                "resource_leases and resource_resolver are required"
            )
        if not callable(resource_resolver):
            raise CampaignValidationError("resource_resolver must be callable")
        if (
            not isinstance(resource_lease_ttl, timedelta)
            or resource_lease_ttl <= timedelta(0)
        ):
            raise CampaignValidationError(
                "resource_lease_ttl must be a positive timedelta"
            )
        super().__init__(**kwargs)
        self._resource_leases = resource_leases
        self._resource_resolver = resource_resolver
        self._resource_lease_ttl = resource_lease_ttl
        self._active_dispatch_lease: ResourceLease | None = None

    def dispatch_ready(self) -> ResourceDispatchResult | None:
        with self._lock:
            self._require_resource_admission_open()
            now = self._now()
            selected: CampaignSpec | None = None
            lease: ResourceLease | None = None
            for candidate in self._queue.snapshot():
                if candidate.ready_at > now:
                    continue
                current = self._require_record(candidate.campaign_id)
                if current.state.status not in {
                    CampaignStatus.QUEUED,
                    CampaignStatus.SCHEDULED,
                }:
                    raise CampaignConflictError(
                        f"campaign {candidate.campaign_id!r} cannot dispatch from "
                        f"{current.state.status.value}"
                    )
                self._require_resource_admission_open()
                candidate_lease = self._try_acquire(candidate, now=now)
                if candidate_lease is False:
                    continue
                selected = candidate
                lease = candidate_lease
                break
            if selected is None:
                return None
            try:
                self._require_resource_admission_open()
            except Exception:
                self._release(selected.campaign_id)
                raise
            removed = self._queue.remove(selected.campaign_id)
            if removed is None:
                self._release(selected.campaign_id)
                raise CampaignConflictError(
                    f"campaign {selected.campaign_id!r} disappeared from the queue"
                )
            current = self._require_record(selected.campaign_id)
            self._require_resource_admission_open()
            try:
                running, request, intent = self._persist_dispatch_request(
                    current,
                    occurred_at=now,
                )
            except Exception:
                self._release(selected.campaign_id)
                self._queue.enqueue(selected)
                raise
            self._active_dispatch_lease = lease
            try:
                return self._execute_dispatch(running, request, intent)
            finally:
                self._active_dispatch_lease = None

    def resume(self, campaign_id: str) -> CampaignRecord:
        with self._lock:
            self._require_resource_admission_open()
            current = self._require_record(campaign_id)
            if current.state.status is not CampaignStatus.PAUSED:
                raise CampaignConflictError(
                    f"campaign {campaign_id!r} cannot resume from "
                    f"{current.state.status.value}"
                )
            now = self._now()
            self._require_resource_admission_open()
            lease = self._try_acquire(current.spec, now=now)
            if lease is False:
                raise CampaignResourceBlockedError(
                    f"campaign {campaign_id!r} is waiting for resources"
                )
            try:
                self._require_resource_admission_open()
            except Exception:
                self._release(campaign_id)
                raise
            resumed = self._transition(
                current,
                CampaignStatus.RUNNING,
                occurred_at=now,
            )
            resumed = CampaignRecord(
                spec=resumed.spec,
                state=replace(resumed.state, attempt=current.state.attempt),
            )
            try:
                return self._deliver_signal(resumed, CampaignSignalType.RESUME)
            except Exception:
                if self._handoff_repository.get(campaign_id) == current:
                    self._release(campaign_id)
                raise

    def mark_paused(self, campaign_id: str) -> CampaignRecord:
        with self._lock:
            try:
                return super().mark_paused(campaign_id)
            finally:
                current = self._handoff_repository.get(campaign_id)
                if current is not None and current.state.status is CampaignStatus.PAUSED:
                    self._release(campaign_id)

    def mark_cancelled(self, campaign_id: str) -> CampaignRecord:
        with self._lock:
            try:
                return super().mark_cancelled(campaign_id)
            finally:
                current = self._handoff_repository.get(campaign_id)
                if current is not None and current.state.status is CampaignStatus.CANCELLED:
                    self._release(campaign_id)

    def complete(
        self,
        campaign_id: str,
        *,
        succeeded: bool,
        error: str | None = None,
    ) -> CampaignRecord:
        with self._lock:
            try:
                return super().complete(
                    campaign_id,
                    succeeded=succeeded,
                    error=error,
                )
            finally:
                current = self._handoff_repository.get(campaign_id)
                if current is not None and current.state.status in {
                    CampaignStatus.SUCCEEDED,
                    CampaignStatus.FAILED,
                }:
                    self._release(campaign_id)

    def renew_resources(self, campaign_id: str) -> ResourceLease | None:
        with self._lock:
            current = self._require_record(campaign_id)
            if current.state.status not in {
                CampaignStatus.RUNNING,
                CampaignStatus.PAUSING,
                CampaignStatus.CANCELLING,
            }:
                raise CampaignConflictError(
                    f"campaign {campaign_id!r} cannot renew resources from "
                    f"{current.state.status.value}"
                )
            now = self._now()
            lease = self._resource_leases.for_campaign(campaign_id, now=now)
            if lease is None:
                if self._requirements(current.spec):
                    raise CampaignConflictError(
                        f"campaign {campaign_id!r} has no active resource lease"
                    )
                return None
            return self._resource_leases.renew(
                lease.lease_id,
                now=now,
                ttl=self._resource_lease_ttl,
            )

    def _before_external_dispatch(self) -> None:
        self._require_resource_admission_open()

    def _before_external_signal(self, signal_type: CampaignSignalType) -> None:
        if signal_type is CampaignSignalType.RESUME:
            self._require_resource_admission_open()

    def _dispatch_result(
        self,
        *,
        record: CampaignRecord,
        runtime_reference: str | None,
        dispatch_error: str | None,
    ) -> ResourceDispatchResult:
        lease = self._active_dispatch_lease
        return ResourceDispatchResult(
            record=record,
            runtime_reference=runtime_reference,
            dispatch_error=dispatch_error,
            resource_lease_id=lease.lease_id if lease is not None else None,
        )

    def _requirements(self, spec: CampaignSpec) -> Mapping[str, int]:
        requirements = self._resource_resolver(spec)
        if not isinstance(requirements, Mapping):
            raise CampaignValidationError(
                "resource_resolver must return a mapping"
            )
        return requirements

    def _try_acquire(
        self,
        spec: CampaignSpec,
        *,
        now: datetime,
    ) -> ResourceLease | bool | None:
        self._require_resource_admission_open()
        requirements = self._requirements(spec)
        if not requirements:
            return None
        lease = self._resource_leases.try_acquire(
            spec.campaign_id,
            requirements,
            now=now,
            ttl=self._resource_lease_ttl,
        )
        return lease if lease is not None else False

    def _release(self, campaign_id: str) -> None:
        self._resource_leases.release_campaign(campaign_id)

    def _require_resource_admission_open(self) -> None:
        blocked = tuple(
            record.spec.campaign_id
            for record in self._handoff_repository.list()
            if record.state.resource_reconciliation_required
        )
        if blocked:
            raise CampaignResourceReconciliationBlockedError(
                RESOURCE_RECONCILIATION_BLOCKED_MESSAGE
            )


class CampaignHandoffRecoveryService:
    """Explicit recovery matrix for requested dispatch and signal handoffs."""

    _INTERRUPTED = frozenset(
        {
            CampaignStatus.RUNNING,
            CampaignStatus.PAUSING,
            CampaignStatus.CANCELLING,
        }
    )

    def __init__(
        self,
        *,
        repository: JsonCampaignRepository,
        queue: CampaignQueue,
        events: CampaignEventRecorder,
        clock: Clock,
        executor: CampaignHandoffExecutor,
        reconciler: CampaignProjectionReconciler | None = None,
    ) -> None:
        self._repository = repository
        self._queue = queue
        self._events = events
        self._clock = clock
        self._executor = executor
        self._reconciler = reconciler

    def recover(self) -> CampaignHandoffRecoveryReport:
        started_at = self._now()
        decisions = tuple(
            self._recover_record(record, recovered_at=started_at)
            for record in self._repository.list()
        )
        return CampaignHandoffRecoveryReport(
            started_at=started_at,
            completed_at=self._now(),
            decisions=decisions,
        )

    def _recover_record(
        self,
        record: CampaignRecord,
        *,
        recovered_at: datetime,
    ) -> CampaignHandoffRecoveryDecision:
        status = record.state.status
        campaign_id = record.spec.campaign_id
        if status in {CampaignStatus.QUEUED, CampaignStatus.SCHEDULED}:
            if campaign_id in self._queue:
                return self._decision(
                    record,
                    record,
                    HandoffRecoveryAction.ALREADY_QUEUED,
                )
            self._queue.enqueue(record.spec)
            self._persist_plain(
                record,
                (
                    CampaignProjectionSpec(
                        kind=CampaignEventKind.RECOVERED,
                        occurred_at=recovered_at,
                        payload={"action": HandoffRecoveryAction.REQUEUED.value},
                        producer_id="handoff-recovery",
                    ),
                ),
            )
            return self._decision(record, record, HandoffRecoveryAction.REQUEUED)
        if status is CampaignStatus.PAUSED:
            return self._decision(
                record,
                record,
                HandoffRecoveryAction.RETAINED_PAUSED,
            )
        if status not in self._INTERRUPTED:
            return self._decision(
                record,
                record,
                HandoffRecoveryAction.RETAINED_TERMINAL,
            )

        requested = tuple(
            intent
            for intent in self._repository.pending_handoffs(campaign_id)
            if intent.phase is CampaignHandoffPhase.REQUESTED
        )
        if not requested:
            return self._legacy_fail_closed(record, recovered_at=recovered_at)
        intent = max(requested, key=lambda item: item.state_revision)
        if isinstance(intent.request, CampaignSignalRequest):
            return self._signal_intervention(
                record,
                intent,
                recovered_at=recovered_at,
            )
        try:
            outcome = self._executor.query_outcome(intent.intent_id)
        except Exception as exc:
            return self._unknown(
                record,
                intent,
                recovered_at=recovered_at,
                detail=f"query_outcome failed: {type(exc).__name__}: {exc}",
            )
        if not isinstance(outcome, CampaignDispatchOutcome):
            return self._unknown(
                record,
                intent,
                recovered_at=recovered_at,
                detail="query_outcome returned an unsupported value",
            )
        if outcome.dispatch_id != intent.intent_id:
            return self._unknown(
                record,
                intent,
                recovered_at=recovered_at,
                detail="query_outcome returned a mismatched dispatch_id",
            )
        if outcome.kind is DispatchOutcomeKind.NOT_DISPATCHED:
            return self._not_dispatched(record, intent, outcome, recovered_at)
        if outcome.kind in {DispatchOutcomeKind.ACCEPTED, DispatchOutcomeKind.RUNNING}:
            return self._accepted_or_running(record, intent, outcome, recovered_at)
        if outcome.kind is DispatchOutcomeKind.UNKNOWN:
            return self._unknown(
                record,
                intent,
                recovered_at=recovered_at,
                detail="adapter reported unknown",
            )
        return self._terminal(record, intent, outcome, recovered_at)

    def _not_dispatched(
        self,
        record: CampaignRecord,
        intent: CampaignHandoffIntent,
        outcome: CampaignDispatchOutcome,
        recovered_at: datetime,
    ) -> CampaignHandoffRecoveryDecision:
        ready = CampaignRecord(
            spec=record.spec,
            state=replace(
                record.state,
                status=CampaignStatus.QUEUED,
                revision=record.state.revision + 1,
                updated_at=recovered_at,
                last_error=None,
                execution_intervention_required=False,
            ),
        )
        projection = CampaignProjectionSpec(
            kind=CampaignEventKind.RECOVERED,
            occurred_at=recovered_at,
            payload={
                "action": HandoffRecoveryAction.NOT_DISPATCHED_READY.value,
                "dispatch_id": intent.intent_id,
                "evidence_pointer": outcome.evidence_pointer,
            },
            producer_id="handoff-recovery",
        )
        self._persist_plain(ready, (projection,))
        self._queue.enqueue(ready.spec)
        return self._decision(
            record,
            ready,
            HandoffRecoveryAction.NOT_DISPATCHED_READY,
        )

    def _accepted_or_running(
        self,
        record: CampaignRecord,
        intent: CampaignHandoffIntent,
        outcome: CampaignDispatchOutcome,
        recovered_at: datetime,
    ) -> CampaignHandoffRecoveryDecision:
        updated = CampaignRecord(
            spec=record.spec,
            state=replace(
                record.state,
                revision=record.state.revision + 1,
                updated_at=recovered_at,
                resource_reconciliation_required=True,
            ),
        )
        acknowledgement = CampaignDispatchAcknowledgement(
            dispatch_id=intent.intent_id,
            runtime_reference=outcome.runtime_reference or "",
            evidence_pointer=outcome.evidence_pointer,
        )
        action = (
            HandoffRecoveryAction.ACCEPTED
            if outcome.kind is DispatchOutcomeKind.ACCEPTED
            else HandoffRecoveryAction.RUNNING
        )
        projections = (
            CampaignProjectionSpec(
                kind=CampaignEventKind.RECOVERED,
                occurred_at=recovered_at,
                payload={"action": action.value, "dispatch_id": intent.intent_id},
                producer_id="handoff-recovery",
            ),
            CampaignProjectionSpec(
                kind=CampaignEventKind.DISPATCH_CONFIRMED,
                occurred_at=recovered_at,
                payload={
                    "dispatch_id": intent.intent_id,
                    "runtime_reference": acknowledgement.runtime_reference,
                    "evidence_pointer": acknowledgement.evidence_pointer,
                },
                producer_id="handoff-recovery",
            ),
            CampaignProjectionSpec(
                kind=CampaignEventKind.RESOURCE_RECONCILIATION_REQUIRED,
                occurred_at=recovered_at,
                payload={"dispatch_id": intent.intent_id, "outcome": action.value},
                producer_id="handoff-recovery",
            ),
        )
        _atomic_record_and_handoff_acknowledgement(
            self._repository,
            updated,
            intent_id=intent.intent_id,
            acknowledgement=acknowledgement,
            projections=projections,
        )
        self._reconcile(record.spec.campaign_id)
        return self._decision(record, updated, action)

    def _unknown(
        self,
        record: CampaignRecord,
        intent: CampaignHandoffIntent,
        *,
        recovered_at: datetime,
        detail: str,
    ) -> CampaignHandoffRecoveryDecision:
        updated = CampaignRecord(
            spec=record.spec,
            state=replace(
                record.state,
                revision=record.state.revision + 1,
                updated_at=recovered_at,
                execution_intervention_required=True,
                resource_reconciliation_required=True,
            ),
        )
        projections = (
            CampaignProjectionSpec(
                kind=CampaignEventKind.RECOVERED,
                occurred_at=recovered_at,
                payload={
                    "action": HandoffRecoveryAction.UNKNOWN_INTERVENTION.value,
                    "dispatch_id": intent.intent_id,
                    "detail": detail,
                },
                producer_id="handoff-recovery",
            ),
            CampaignProjectionSpec(
                kind=CampaignEventKind.RESOURCE_RECONCILIATION_REQUIRED,
                occurred_at=recovered_at,
                payload={"dispatch_id": intent.intent_id, "outcome": "unknown"},
                producer_id="handoff-recovery",
            ),
        )
        self._persist_plain(updated, projections)
        return self._decision(
            record,
            updated,
            HandoffRecoveryAction.UNKNOWN_INTERVENTION,
            detail,
        )

    def _terminal(
        self,
        record: CampaignRecord,
        intent: CampaignHandoffIntent,
        outcome: CampaignDispatchOutcome,
        recovered_at: datetime,
    ) -> CampaignHandoffRecoveryDecision:
        succeeded = outcome.kind is DispatchOutcomeKind.COMPLETED
        target = CampaignStatus.SUCCEEDED if succeeded else CampaignStatus.FAILED
        state = transition_campaign(
            record.state,
            target,
            occurred_at=recovered_at,
            error=None if succeeded else outcome.error,
        )
        terminal = CampaignRecord(spec=record.spec, state=state)
        acknowledgement = CampaignDispatchAcknowledgement(
            dispatch_id=intent.intent_id,
            runtime_reference=outcome.runtime_reference or "",
            evidence_pointer=outcome.evidence_pointer,
        )
        action = HandoffRecoveryAction.COMPLETED if succeeded else HandoffRecoveryAction.FAILED
        terminal_event = CampaignEventKind.SUCCEEDED if succeeded else CampaignEventKind.FAILED
        projections = (
            CampaignProjectionSpec(
                kind=CampaignEventKind.RECOVERED,
                occurred_at=recovered_at,
                payload={"action": action.value, "dispatch_id": intent.intent_id},
                producer_id="handoff-recovery",
            ),
            CampaignProjectionSpec(
                kind=CampaignEventKind.DISPATCH_CONFIRMED,
                occurred_at=recovered_at,
                payload={
                    "dispatch_id": intent.intent_id,
                    "runtime_reference": acknowledgement.runtime_reference,
                    "evidence_pointer": acknowledgement.evidence_pointer,
                },
                producer_id="handoff-recovery",
            ),
            CampaignProjectionSpec(
                kind=terminal_event,
                occurred_at=recovered_at,
                payload={} if succeeded else {"error": outcome.error},
                producer_id="handoff-recovery",
            ),
        )
        _atomic_record_and_handoff_acknowledgement(
            self._repository,
            terminal,
            intent_id=intent.intent_id,
            acknowledgement=acknowledgement,
            projections=projections,
        )
        self._reconcile(record.spec.campaign_id)
        return self._decision(record, terminal, action)

    def _signal_intervention(
        self,
        record: CampaignRecord,
        intent: CampaignHandoffIntent,
        *,
        recovered_at: datetime,
    ) -> CampaignHandoffRecoveryDecision:
        updated = CampaignRecord(
            spec=record.spec,
            state=replace(
                record.state,
                revision=record.state.revision + 1,
                updated_at=recovered_at,
                execution_intervention_required=True,
                resource_reconciliation_required=True,
            ),
        )
        projections = (
            CampaignProjectionSpec(
                kind=CampaignEventKind.RECOVERED,
                occurred_at=recovered_at,
                payload={
                    "action": HandoffRecoveryAction.SIGNAL_INTERVENTION.value,
                    "signal_id": intent.intent_id,
                },
                producer_id="handoff-recovery",
            ),
            CampaignProjectionSpec(
                kind=CampaignEventKind.RESOURCE_RECONCILIATION_REQUIRED,
                occurred_at=recovered_at,
                payload={"signal_id": intent.intent_id, "outcome": "unknown"},
                producer_id="handoff-recovery",
            ),
        )
        self._persist_plain(updated, projections)
        return self._decision(
            record,
            updated,
            HandoffRecoveryAction.SIGNAL_INTERVENTION,
        )

    def _legacy_fail_closed(
        self,
        record: CampaignRecord,
        *,
        recovered_at: datetime,
    ) -> CampaignHandoffRecoveryDecision:
        error = (
            "startup recovery failed closed from interrupted "
            f"{record.state.status.value} state without durable handoff"
        )
        failed_state = transition_campaign(
            record.state,
            CampaignStatus.FAILED,
            occurred_at=recovered_at,
            error=error,
        )
        failed = CampaignRecord(spec=record.spec, state=failed_state)
        projections = (
            CampaignProjectionSpec(
                kind=CampaignEventKind.RECOVERED,
                occurred_at=recovered_at,
                payload={"action": HandoffRecoveryAction.LEGACY_MARKED_FAILED.value},
                producer_id="handoff-recovery",
            ),
            CampaignProjectionSpec(
                kind=CampaignEventKind.FAILED,
                occurred_at=recovered_at,
                payload={"error": error, "phase": "startup_recovery"},
                producer_id="handoff-recovery",
            ),
        )
        self._persist_plain(failed, projections)
        return self._decision(
            record,
            failed,
            HandoffRecoveryAction.LEGACY_MARKED_FAILED,
            error,
        )

    def _persist_plain(
        self,
        record: CampaignRecord,
        projections: Iterable[CampaignProjectionSpec],
    ) -> None:
        self._repository.save_with_intents(
            record,
            projection_intents=_projection_intents(record, projections),
        )
        self._reconcile(record.spec.campaign_id)

    def _reconcile(self, campaign_id: str) -> None:
        if self._reconciler is not None:
            self._reconciler.reconcile(campaign_id)

    @staticmethod
    def _decision(
        previous: CampaignRecord,
        resulting: CampaignRecord,
        action: HandoffRecoveryAction,
        detail: str | None = None,
    ) -> CampaignHandoffRecoveryDecision:
        return CampaignHandoffRecoveryDecision(
            campaign_id=previous.spec.campaign_id,
            previous_status=previous.state.status,
            resulting_status=resulting.state.status,
            action=action,
            detail=detail,
        )

    def _now(self) -> datetime:
        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise CampaignValidationError("clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)
