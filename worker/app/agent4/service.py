"""Caller-driven Agent 4 lifecycle coordination service.

The service has no background loop. A host must explicitly call ``dispatch_ready``
or one of the lifecycle methods, keeping Agent 4 dormant until it is composed by
an operator-facing runtime in a later milestone.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from threading import RLock

from .campaign_queue import CampaignQueue, DuplicateCampaignError
from .contracts import (
    CampaignEventRecorder,
    CampaignExecutor,
    CampaignRepository,
    Clock,
)
from .domain import (
    CampaignEventKind,
    CampaignRecord,
    CampaignSpec,
    CampaignState,
    CampaignStatus,
    CampaignTransitionError,
    CampaignValidationError,
    transition_campaign,
)


class CampaignNotFoundError(LookupError):
    """Raised when a lifecycle command references an unknown campaign."""


class CampaignConflictError(RuntimeError):
    """Raised when a lifecycle command conflicts with persisted state."""


@dataclass(frozen=True, slots=True)
class DispatchResult:
    record: CampaignRecord
    runtime_reference: str | None
    dispatch_error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.dispatch_error is None


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class CampaignSchedulerService:
    """Deterministic, single-process campaign lifecycle coordinator."""

    def __init__(
        self,
        *,
        repository: CampaignRepository,
        executor: CampaignExecutor,
        events: CampaignEventRecorder,
        clock: Clock | None = None,
        queue: CampaignQueue | None = None,
    ) -> None:
        self._repository = repository
        self._executor = executor
        self._events = events
        self._clock = clock if clock is not None else SystemClock()
        self._queue = queue if queue is not None else CampaignQueue()
        self._lock = RLock()

    @property
    def queued_count(self) -> int:
        return len(self._queue)

    def recover(self):
        """Rehydrate the shared queue and fail interrupted work closed."""

        from .recovery import CampaignRecoveryService

        with self._lock:
            return CampaignRecoveryService(
                repository=self._repository,
                queue=self._queue,
                events=self._events,
                clock=self._clock,
            ).recover()

    def submit(self, spec: CampaignSpec) -> CampaignRecord:
        with self._lock:
            if self._repository.get(spec.campaign_id) is not None:
                raise CampaignConflictError(
                    f"campaign {spec.campaign_id!r} already exists"
                )
            if spec.campaign_id in self._queue:
                raise CampaignConflictError(
                    f"campaign {spec.campaign_id!r} is already queued"
                )
            now = self._now()
            status = (
                CampaignStatus.SCHEDULED
                if spec.ready_at > now
                else CampaignStatus.QUEUED
            )
            record = CampaignRecord(
                spec=spec,
                state=CampaignState(
                    campaign_id=spec.campaign_id,
                    status=status,
                    updated_at=now,
                ),
            )
            self._repository.save(record)
            try:
                self._queue.enqueue(spec)
            except DuplicateCampaignError as exc:
                raise CampaignConflictError(str(exc)) from exc

            self._events.record(
                spec.campaign_id,
                CampaignEventKind.CREATED,
                occurred_at=now,
                payload={"status": status.value},
            )
            if status is CampaignStatus.SCHEDULED:
                self._events.record(
                    spec.campaign_id,
                    CampaignEventKind.SCHEDULED,
                    occurred_at=now,
                    payload={"ready_at": spec.ready_at.isoformat()},
                )
            return record

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

            running_state = transition_campaign(
                current.state,
                CampaignStatus.RUNNING,
                occurred_at=now,
            )
            running = CampaignRecord(spec=current.spec, state=running_state)
            try:
                self._repository.save(running)
            except Exception:
                self._queue.enqueue(spec)
                raise

            try:
                runtime_reference = self._executor.dispatch(
                    running.spec,
                    running.state,
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                failed_state = transition_campaign(
                    running.state,
                    CampaignStatus.FAILED,
                    occurred_at=self._now(),
                    error=error,
                )
                failed = CampaignRecord(spec=running.spec, state=failed_state)
                self._repository.save(failed)
                self._events.record(
                    spec.campaign_id,
                    CampaignEventKind.FAILED,
                    occurred_at=failed_state.updated_at,
                    payload={"error": error, "phase": "dispatch"},
                )
                return DispatchResult(
                    record=failed,
                    runtime_reference=None,
                    dispatch_error=error,
                )

            if not isinstance(runtime_reference, str) or not runtime_reference.strip():
                error = "executor returned an empty runtime reference"
                failed_state = transition_campaign(
                    running.state,
                    CampaignStatus.FAILED,
                    occurred_at=self._now(),
                    error=error,
                )
                failed = CampaignRecord(spec=running.spec, state=failed_state)
                self._repository.save(failed)
                self._events.record(
                    spec.campaign_id,
                    CampaignEventKind.FAILED,
                    occurred_at=failed_state.updated_at,
                    payload={"error": error, "phase": "dispatch"},
                )
                return DispatchResult(
                    record=failed,
                    runtime_reference=None,
                    dispatch_error=error,
                )

            runtime_reference = runtime_reference.strip()
            self._events.record(
                spec.campaign_id,
                CampaignEventKind.STARTED,
                occurred_at=running_state.updated_at,
                payload={
                    "attempt": running_state.attempt,
                    "runtime_reference": runtime_reference,
                },
            )
            return DispatchResult(
                record=running,
                runtime_reference=runtime_reference,
            )

    def request_pause(self, campaign_id: str) -> CampaignRecord:
        with self._lock:
            current = self._require_record(campaign_id)
            if current.state.status is not CampaignStatus.RUNNING:
                raise CampaignConflictError(
                    f"campaign {campaign_id!r} cannot pause from "
                    f"{current.state.status.value}"
                )
            pausing = self._transition(current, CampaignStatus.PAUSING)
            self._repository.save(pausing)
            try:
                self._executor.signal(campaign_id, "pause")
            except Exception as exc:
                return self._fail_signal(pausing, "pause", exc)
            self._events.record(
                campaign_id,
                CampaignEventKind.PAUSE_REQUESTED,
                occurred_at=pausing.state.updated_at,
            )
            return pausing

    def mark_paused(self, campaign_id: str) -> CampaignRecord:
        with self._lock:
            current = self._require_record(campaign_id)
            paused = self._transition(current, CampaignStatus.PAUSED)
            self._repository.save(paused)
            self._events.record(
                campaign_id,
                CampaignEventKind.PAUSED,
                occurred_at=paused.state.updated_at,
            )
            return paused

    def resume(self, campaign_id: str) -> CampaignRecord:
        with self._lock:
            current = self._require_record(campaign_id)
            if current.state.status is not CampaignStatus.PAUSED:
                raise CampaignConflictError(
                    f"campaign {campaign_id!r} cannot resume from "
                    f"{current.state.status.value}"
                )
            resumed = self._transition(current, CampaignStatus.RUNNING)
            if resumed.state.attempt != current.state.attempt:
                resumed = CampaignRecord(
                    spec=resumed.spec,
                    state=replace(resumed.state, attempt=current.state.attempt),
                )
            self._repository.save(resumed)
            try:
                self._executor.signal(campaign_id, "resume")
            except Exception as exc:
                return self._fail_signal(resumed, "resume", exc)
            self._events.record(
                campaign_id,
                CampaignEventKind.RESUMED,
                occurred_at=resumed.state.updated_at,
                payload={"attempt": resumed.state.attempt},
            )
            return resumed

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
                self._repository.save(cancelled)
                self._queue.remove(campaign_id)
                self._events.record(
                    campaign_id,
                    CampaignEventKind.CANCELLED,
                    occurred_at=cancelled.state.updated_at,
                    payload={"immediate": True},
                )
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
            self._repository.save(cancelling)
            try:
                self._executor.signal(campaign_id, "cancel")
            except Exception as exc:
                return self._fail_signal(cancelling, "cancel", exc)
            self._events.record(
                campaign_id,
                CampaignEventKind.CANCEL_REQUESTED,
                occurred_at=cancelling.state.updated_at,
            )
            return cancelling

    def mark_cancelled(self, campaign_id: str) -> CampaignRecord:
        with self._lock:
            current = self._require_record(campaign_id)
            cancelled = self._transition(current, CampaignStatus.CANCELLED)
            self._repository.save(cancelled)
            self._events.record(
                campaign_id,
                CampaignEventKind.CANCELLED,
                occurred_at=cancelled.state.updated_at,
                payload={"immediate": False},
            )
            return cancelled

    def complete(
        self,
        campaign_id: str,
        *,
        succeeded: bool,
        error: str | None = None,
    ) -> CampaignRecord:
        with self._lock:
            current = self._require_record(campaign_id)
            if current.state.status is not CampaignStatus.RUNNING:
                raise CampaignConflictError(
                    f"campaign {campaign_id!r} cannot complete from "
                    f"{current.state.status.value}"
                )
            target = CampaignStatus.SUCCEEDED if succeeded else CampaignStatus.FAILED
            if succeeded and error is not None:
                raise CampaignValidationError(
                    "successful completion must not include an error"
                )
            completed = self._transition(
                current,
                target,
                error=error,
            )
            self._repository.save(completed)
            self._events.record(
                campaign_id,
                (
                    CampaignEventKind.SUCCEEDED
                    if succeeded
                    else CampaignEventKind.FAILED
                ),
                occurred_at=completed.state.updated_at,
                payload={} if succeeded else {"error": completed.state.last_error},
            )
            return completed

    def get(self, campaign_id: str) -> CampaignRecord:
        with self._lock:
            return self._require_record(campaign_id)

    def list(self) -> tuple[CampaignRecord, ...]:
        with self._lock:
            return self._repository.list()

    def _transition(
        self,
        record: CampaignRecord,
        target: CampaignStatus,
        *,
        occurred_at: datetime | None = None,
        error: str | None = None,
    ) -> CampaignRecord:
        try:
            state = transition_campaign(
                record.state,
                target,
                occurred_at=occurred_at or self._now(),
                error=error,
            )
        except CampaignTransitionError as exc:
            raise CampaignConflictError(str(exc)) from exc
        return CampaignRecord(spec=record.spec, state=state)

    def _fail_signal(
        self,
        record: CampaignRecord,
        command: str,
        exc: Exception,
    ) -> CampaignRecord:
        error = f"{type(exc).__name__}: {exc}"
        failed = self._transition(
            record,
            CampaignStatus.FAILED,
            error=error,
        )
        self._repository.save(failed)
        self._events.record(
            record.spec.campaign_id,
            CampaignEventKind.FAILED,
            occurred_at=failed.state.updated_at,
            payload={"error": error, "phase": f"{command}_signal"},
        )
        return failed

    def _require_record(self, campaign_id: str) -> CampaignRecord:
        record = self._repository.get(campaign_id)
        if record is None:
            raise CampaignNotFoundError(f"campaign {campaign_id!r} was not found")
        return record

    def _now(self) -> datetime:
        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise CampaignValidationError("clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)
