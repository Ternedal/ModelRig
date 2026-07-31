"""Projection-aware variants of existing caller-driven Agent 4 services."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from .campaign_queue import DuplicateCampaignError
from .checkpoint import (
    CampaignCheckpoint,
    CampaignCheckpointService,
    CheckpointLifecycleError,
)
from .domain import (
    CampaignEventKind,
    CampaignRecord,
    CampaignStatus,
    CampaignValidationError,
    transition_campaign,
)
from .failure_handling import (
    CampaignFailureHandlingService,
    FailureHandlingResult,
)
from .health import (
    CampaignHealthObservation,
    HealthDecision,
    HealthInterventionAction,
)
from .health_intervention_adapters import CampaignHealthFailClosedService
from .projection import (
    CampaignProjectionError,
    CampaignProjectionSpec,
    CampaignStateProjectionService,
)
from .retry import FailureDescriptor, RetryDecision
from .service import CampaignConflictError, CampaignNotFoundError


class ProjectedCampaignCheckpointService(CampaignCheckpointService):
    """Persist checkpoint state and its audit intent through one durable envelope."""

    def __init__(
        self,
        *,
        projections: CampaignStateProjectionService,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._projections = projections

    def checkpoint(self, campaign_id, checkpoint_id, payload):
        with self._lock:
            current = self._require_record(campaign_id)
            if current.state.status not in {
                CampaignStatus.RUNNING,
                CampaignStatus.PAUSING,
                CampaignStatus.PAUSED,
            }:
                raise CheckpointLifecycleError(
                    f"campaign {campaign_id!r} cannot checkpoint from "
                    f"{current.state.status.value}"
                )
            now = self._now()
            revision = current.state.revision + 1
            checkpoint = CampaignCheckpoint(
                checkpoint_id=checkpoint_id,
                campaign_id=campaign_id,
                campaign_revision=revision,
                created_at=now,
                payload=payload,
            )
            self._checkpoints.save(checkpoint)
            updated = CampaignRecord(
                spec=current.spec,
                state=replace(
                    current.state,
                    revision=revision,
                    updated_at=now,
                    checkpoint_id=checkpoint.checkpoint_id,
                ),
            )
            try:
                self._projections.persist(
                    updated,
                    (
                        CampaignProjectionSpec(
                            kind=CampaignEventKind.CHECKPOINTED,
                            occurred_at=now,
                            payload={
                                "checkpoint_id": checkpoint.checkpoint_id,
                                "revision": revision,
                            },
                            producer_id="checkpoint",
                        ),
                    ),
                )
            except CampaignProjectionError:
                raise
            except Exception:
                self._checkpoints.delete(campaign_id, checkpoint.checkpoint_id)
                raise
            return updated


class ProjectedCampaignFailureHandlingService(CampaignFailureHandlingService):
    """Persist retry/failure state and audit intent through one durable envelope."""

    def __init__(
        self,
        *,
        projections: CampaignStateProjectionService,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._projections = projections

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
                failed = self._terminal_failure(current, failure, decision, now=now)
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
            durable = False
            try:
                self._projections.persist(
                    scheduled,
                    (
                        CampaignProjectionSpec(
                            kind=CampaignEventKind.RETRY_SCHEDULED,
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
                            producer_id="failure",
                        ),
                    ),
                )
                durable = True
                self._queue.remove(campaign_id)
                try:
                    self._queue.enqueue(retry_spec)
                except DuplicateCampaignError as exc:
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
                    raise CampaignConflictError(str(exc)) from exc
                return FailureHandlingResult(record=scheduled, decision=decision)
            finally:
                if durable:
                    self._release(campaign_id)

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
        self._projections.persist(
            failed,
            (
                CampaignProjectionSpec(
                    kind=CampaignEventKind.FAILED,
                    occurred_at=failed_state.updated_at,
                    payload={
                        "error": error,
                        "phase": failure.phase,
                        "category": decision.category.value,
                        "reason": decision.reason,
                    },
                    producer_id="failure",
                ),
            ),
        )
        return failed


class ProjectedCampaignHealthFailClosedService(CampaignHealthFailClosedService):
    """Fail health interventions closed with durable audit projection intent."""

    def __init__(
        self,
        *,
        projections: CampaignStateProjectionService,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._projections = projections

    def fail_closed(
        self,
        record: CampaignRecord,
        observation: CampaignHealthObservation,
        decision: HealthDecision,
    ) -> CampaignRecord:
        if decision.action is not HealthInterventionAction.FAIL_CLOSED:
            raise CampaignValidationError(
                "fail_closed requires a FAIL_CLOSED health decision"
            )
        with self._lock:
            current = self._repository.get(record.spec.campaign_id)
            if current is None:
                raise CampaignNotFoundError(
                    f"campaign {record.spec.campaign_id!r} does not exist"
                )
            if current != record:
                raise CampaignConflictError(
                    "campaign changed after health intervention evaluation"
                )
            if current.state.status not in self._ACTIVE:
                raise CampaignConflictError(
                    f"campaign {current.spec.campaign_id!r} cannot fail closed from "
                    f"{current.state.status.value}"
                )
            now = self._now()
            if now < observation.observed_at:
                raise CampaignConflictError(
                    "health intervention clock predates the observation"
                )
            error = f"watchdog: {decision.reason}"
            failed_state = transition_campaign(
                current.state,
                CampaignStatus.FAILED,
                occurred_at=now,
                error=error,
            )
            failed = CampaignRecord(spec=current.spec, state=failed_state)
            self._projections.persist(
                failed,
                (
                    CampaignProjectionSpec(
                        kind=CampaignEventKind.FAILED,
                        occurred_at=failed_state.updated_at,
                        payload={
                            "error": error,
                            "phase": "watchdog",
                            "health_level": decision.level.value,
                            "watchdog_action": decision.action.value,
                        },
                        producer_id="health",
                    ),
                ),
            )
            if self._release_resources is not None:
                self._release_resources(current.spec.campaign_id)
            return failed
