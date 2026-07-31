"""Startup recovery for persisted Agent 4 campaign records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from .campaign_queue import CampaignQueue
from .contracts import CampaignEventRecorder, CampaignRepository, Clock
from .domain import (
    CampaignEventKind,
    CampaignRecord,
    CampaignStatus,
    CampaignValidationError,
    transition_campaign,
)
from .projection import CampaignProjectionSpec, CampaignStateProjectionService


class RecoveryAction(StrEnum):
    REQUEUED = "requeued"
    ALREADY_QUEUED = "already_queued"
    RETAINED_PAUSED = "retained_paused"
    MARKED_FAILED = "marked_failed"
    RETAINED_TERMINAL = "retained_terminal"


@dataclass(frozen=True, slots=True)
class CampaignRecoveryDecision:
    campaign_id: str
    previous_status: CampaignStatus
    resulting_status: CampaignStatus
    action: RecoveryAction
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class CampaignRecoveryReport:
    started_at: datetime
    completed_at: datetime
    decisions: tuple[CampaignRecoveryDecision, ...]

    @property
    def scanned(self) -> int:
        return len(self.decisions)

    def count(self, action: RecoveryAction) -> int:
        return sum(1 for decision in self.decisions if decision.action is action)

    @property
    def requeued(self) -> int:
        return self.count(RecoveryAction.REQUEUED)

    @property
    def failed_closed(self) -> int:
        return self.count(RecoveryAction.MARKED_FAILED)


class CampaignRecoveryService:
    """Rehydrate one process from durable campaign records.

    The policy is intentionally conservative: durable queued work is restored,
    paused work remains paused, terminal work remains terminal, and any record
    that claims an in-flight runtime is failed closed until a future Agent 3
    reconciliation adapter can prove that runtime is still alive.
    """

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
        repository: CampaignRepository,
        queue: CampaignQueue,
        events: CampaignEventRecorder,
        clock: Clock,
        projections: CampaignStateProjectionService | None = None,
    ) -> None:
        self._repository = repository
        self._queue = queue
        self._events = events
        self._clock = clock
        self._projections = projections

    def recover(self) -> CampaignRecoveryReport:
        started_at = self._now()
        decisions: list[CampaignRecoveryDecision] = []
        for record in self._repository.list():
            decisions.append(self._recover_record(record))
        return CampaignRecoveryReport(
            started_at=started_at,
            completed_at=self._now(),
            decisions=tuple(decisions),
        )

    def _recover_record(self, record: CampaignRecord) -> CampaignRecoveryDecision:
        status = record.state.status
        campaign_id = record.spec.campaign_id

        if status in {CampaignStatus.QUEUED, CampaignStatus.SCHEDULED}:
            if campaign_id in self._queue:
                return CampaignRecoveryDecision(
                    campaign_id=campaign_id,
                    previous_status=status,
                    resulting_status=status,
                    action=RecoveryAction.ALREADY_QUEUED,
                )
            self._queue.enqueue(record.spec)
            occurred_at = self._now()
            self._project(
                record,
                CampaignEventKind.RECOVERED,
                occurred_at=occurred_at,
                payload={
                    "action": RecoveryAction.REQUEUED.value,
                    "status": status.value,
                },
            )
            return CampaignRecoveryDecision(
                campaign_id=campaign_id,
                previous_status=status,
                resulting_status=status,
                action=RecoveryAction.REQUEUED,
            )

        if status is CampaignStatus.PAUSED:
            occurred_at = self._now()
            self._project(
                record,
                CampaignEventKind.RECOVERED,
                occurred_at=occurred_at,
                payload={
                    "action": RecoveryAction.RETAINED_PAUSED.value,
                    "status": status.value,
                },
            )
            return CampaignRecoveryDecision(
                campaign_id=campaign_id,
                previous_status=status,
                resulting_status=status,
                action=RecoveryAction.RETAINED_PAUSED,
            )

        if status in self._INTERRUPTED:
            error = f"startup recovery failed closed from interrupted {status.value} state"
            failed_state = transition_campaign(
                record.state,
                CampaignStatus.FAILED,
                occurred_at=self._now(),
                error=error,
            )
            failed = CampaignRecord(spec=record.spec, state=failed_state)
            recovered_payload = {
                "action": RecoveryAction.MARKED_FAILED.value,
                "previous_status": status.value,
            }
            failed_payload = {"error": error, "phase": "startup_recovery"}
            if self._projections is not None:
                self._projections.persist(
                    failed,
                    (
                        CampaignProjectionSpec(
                            kind=CampaignEventKind.RECOVERED,
                            occurred_at=failed_state.updated_at,
                            payload=recovered_payload,
                            producer_id="recovery",
                        ),
                        CampaignProjectionSpec(
                            kind=CampaignEventKind.FAILED,
                            occurred_at=failed_state.updated_at,
                            payload=failed_payload,
                            producer_id="recovery",
                        ),
                    ),
                )
            else:
                self._repository.save(failed)
                self._events.record(
                    campaign_id,
                    CampaignEventKind.RECOVERED,
                    occurred_at=failed_state.updated_at,
                    payload=recovered_payload,
                )
                self._events.record(
                    campaign_id,
                    CampaignEventKind.FAILED,
                    occurred_at=failed_state.updated_at,
                    payload=failed_payload,
                )
            return CampaignRecoveryDecision(
                campaign_id=campaign_id,
                previous_status=status,
                resulting_status=CampaignStatus.FAILED,
                action=RecoveryAction.MARKED_FAILED,
                detail=error,
            )

        return CampaignRecoveryDecision(
            campaign_id=campaign_id,
            previous_status=status,
            resulting_status=status,
            action=RecoveryAction.RETAINED_TERMINAL,
        )

    def _project(
        self,
        record: CampaignRecord,
        kind: CampaignEventKind,
        *,
        occurred_at: datetime,
        payload: dict[str, str],
    ) -> None:
        if self._projections is not None:
            self._projections.persist(
                record,
                (
                    CampaignProjectionSpec(
                        kind=kind,
                        occurred_at=occurred_at,
                        payload=payload,
                        producer_id="recovery",
                    ),
                ),
            )
            return
        self._events.record(
            record.spec.campaign_id,
            kind,
            occurred_at=occurred_at,
            payload=payload,
        )

    def _now(self) -> datetime:
        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise CampaignValidationError("clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)
