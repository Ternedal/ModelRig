"""Durable, caller-driven handling of Agent 4 retry decisions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from threading import RLock
from typing import Callable

from .campaign_queue import CampaignQueue, DuplicateCampaignError
from .contracts import CampaignEventRecorder, CampaignRepository, Clock
from .domain import (
    CampaignEventKind,
    CampaignRecord,
    CampaignStatus,
    CampaignValidationError,
    transition_campaign,
)
from .retry import CampaignRetryPlanner, FailureDescriptor, RetryDecision
from .service import CampaignConflictError, CampaignNotFoundError


ResourceRelease = Callable[[str], bool]


@dataclass(frozen=True, slots=True)
class FailureHandlingResult:
    record: CampaignRecord
    decision: RetryDecision

    @property
    def scheduled(self) -> bool:
        return self.decision.should_retry


class CampaignFailureHandlingService:
    """Persist one failure decision and optionally return it to the queue.

    The host invokes :meth:`handle_failure` explicitly after a delegated attempt
    has stopped. The service never sleeps or dispatches work itself.
    """

    def __init__(
        self,
        *,
        repository: CampaignRepository,
        queue: CampaignQueue,
        events: CampaignEventRecorder,
        clock: Clock,
        planner: CampaignRetryPlanner | None = None,
        release_resources: ResourceRelease | None = None,
    ) -> None:
        self._repository = repository
        self._queue = queue
        self._events = events
        self._clock = clock
        self._planner = planner if planner is not None else CampaignRetryPlanner()
        self._release_resources = release_resources
        self._lock = RLock()

    def handle_failure(
        self,
        campaign_id: str,
        failure: FailureDescriptor,
    ) -> FailureHandlingResult:
        with self._lock:
            current = self._repository.get(campaign_id)
            if current is None:
                raise CampaignNotFoundError(f"campaign {campaign_id!r} does not exist")
            if current.state.status is not CampaignStatus.RUNNING:
                raise CampaignConflictError(
                    f"campaign {campaign_id!r} cannot handle a runtime failure from "
                    f"{current.state.status.value}"
                )

            now = self._now()
            decision = self._planner.decide(
                current.spec,
                current.state,
                failure,
                occurred_at=now,
            )
            if not decision.should_retry:
                try:
                    failed = self._terminal_failure(current, failure, decision, now=now)
                finally:
                    self._release(campaign_id)
                return FailureHandlingResult(record=failed, decision=decision)

            assert decision.ready_at is not None
            retry_spec = replace(current.spec, scheduled_for=decision.ready_at)
            scheduled_state = replace(
                current.state,
                status=CampaignStatus.SCHEDULED,
                revision=current.state.revision + 1,
                updated_at=now,
                last_error=None,
            )
            scheduled = CampaignRecord(spec=retry_spec, state=scheduled_state)

            # Durable state comes first. A crash before enqueue is recovered by
            # the existing T-031 startup recovery path.
            self._repository.save(scheduled)
            self._queue.remove(campaign_id)
            try:
                self._queue.enqueue(retry_spec)
            except DuplicateCampaignError as exc:
                try:
                    self._terminal_failure(
                        current,
                        FailureDescriptor(
                            error_type=type(exc).__name__,
                            message=str(exc),
                            phase="retry_enqueue",
                        ),
                        decision,
                        now=self._now(),
                    )
                finally:
                    self._release(campaign_id)
                raise CampaignConflictError(str(exc)) from exc

            try:
                self._events.record(
                    campaign_id,
                    CampaignEventKind.RETRY_SCHEDULED,
                    occurred_at=now,
                    payload={
                        "category": decision.category.value,
                        "failed_attempt": decision.failed_attempt,
                        "remaining_attempts": decision.remaining_attempts,
                        "ready_at": decision.ready_at.isoformat(),
                        "delay_seconds": decision.delay.total_seconds()
                        if decision.delay is not None
                        else None,
                        "error_type": failure.error_type,
                        "phase": failure.phase,
                    },
                )
            finally:
                self._release(campaign_id)
            return FailureHandlingResult(record=scheduled, decision=decision)

    def _terminal_failure(
        self,
        current: CampaignRecord,
        failure: FailureDescriptor,
        decision: RetryDecision,
        *,
        now: datetime,
    ) -> CampaignRecord:
        error = f"{failure.error_type}: {failure.message}"
        failed_state = transition_campaign(
            current.state,
            CampaignStatus.FAILED,
            occurred_at=now,
            error=error,
        )
        failed = CampaignRecord(spec=current.spec, state=failed_state)
        self._repository.save(failed)
        self._events.record(
            current.spec.campaign_id,
            CampaignEventKind.FAILED,
            occurred_at=failed_state.updated_at,
            payload={
                "error": error,
                "phase": failure.phase,
                "category": decision.category.value,
                "reason": decision.reason,
            },
        )
        return failed

    def _release(self, campaign_id: str) -> None:
        if self._release_resources is not None:
            self._release_resources(campaign_id)

    def _now(self) -> datetime:
        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise CampaignValidationError("clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)
