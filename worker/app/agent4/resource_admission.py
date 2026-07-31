"""Resource-aware admission for caller-driven Agent 4 lifecycle coordination.

This module is deliberately additive.  It composes the T-030 lifecycle service
with the T-032 lease kernel without activating a background loop or changing the
validated Agent 3 executor contract.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Mapping

from .contracts import CampaignResourceLeaseManager, CampaignResourceResolver
from .domain import (
    CampaignEventKind,
    CampaignRecord,
    CampaignSpec,
    CampaignStatus,
    CampaignValidationError,
    transition_campaign,
)
from .resources import ResourceLease
from .service import (
    CampaignConflictError,
    CampaignSchedulerService,
    DispatchResult,
)


class CampaignResourceBlockedError(CampaignConflictError):
    """Raised when a campaign cannot acquire its complete resource vector."""


@dataclass(frozen=True, slots=True)
class ResourceDispatchResult(DispatchResult):
    """Dispatch result augmented with the admitted resource lease identity."""

    resource_lease_id: str | None = None


class ResourceAwareCampaignSchedulerService(CampaignSchedulerService):
    """Campaign coordinator with atomic resource admission and lease cleanup.

    Admission is caller-driven through :meth:`dispatch_ready`. Ready campaigns
    are inspected in the queue's deterministic order. A blocked campaign stays
    queued while the next admissible campaign may run, preventing head-of-line
    blocking without weakening priority ordering among admissible work.
    """

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

    def dispatch_ready(self) -> ResourceDispatchResult | None:
        with self._lock:
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
                candidate_lease = self._try_acquire(candidate, now=now)
                if candidate_lease is False:
                    continue
                selected = candidate
                lease = candidate_lease
                break

            if selected is None:
                return None

            removed = self._queue.remove(selected.campaign_id)
            if removed is None:
                self._release(selected.campaign_id)
                raise CampaignConflictError(
                    f"campaign {selected.campaign_id!r} disappeared from the queue"
                )

            current = self._require_record(selected.campaign_id)
            running_state = transition_campaign(
                current.state,
                CampaignStatus.RUNNING,
                occurred_at=now,
            )
            running = CampaignRecord(spec=current.spec, state=running_state)
            try:
                self._repository.save(running)
            except Exception:
                self._release(selected.campaign_id)
                self._queue.enqueue(selected)
                raise

            try:
                runtime_reference = self._executor.dispatch(
                    running.spec,
                    running.state,
                )
            except Exception as exc:
                return self._fail_dispatch(running, exc, lease)

            if not isinstance(runtime_reference, str) or not runtime_reference.strip():
                return self._fail_dispatch(
                    running,
                    RuntimeError("executor returned an empty runtime reference"),
                    lease,
                )

            runtime_reference = runtime_reference.strip()
            payload: dict[str, object] = {
                "attempt": running_state.attempt,
                "runtime_reference": runtime_reference,
            }
            if lease is not None:
                payload["resource_lease_id"] = lease.lease_id
                payload["resources"] = dict(lease.resources)
            self._events.record(
                selected.campaign_id,
                CampaignEventKind.STARTED,
                occurred_at=running_state.updated_at,
                payload=payload,
            )
            return ResourceDispatchResult(
                record=running,
                runtime_reference=runtime_reference,
                resource_lease_id=lease.lease_id if lease is not None else None,
            )

    def request_pause(self, campaign_id: str) -> CampaignRecord:
        result = super().request_pause(campaign_id)
        if result.state.status is CampaignStatus.FAILED:
            self._release(campaign_id)
        return result

    def mark_paused(self, campaign_id: str) -> CampaignRecord:
        with self._lock:
            try:
                return super().mark_paused(campaign_id)
            finally:
                current = self._repository.get(campaign_id)
                if current is not None and current.state.status is CampaignStatus.PAUSED:
                    self._release(campaign_id)

    def resume(self, campaign_id: str) -> CampaignRecord:
        with self._lock:
            current = self._require_record(campaign_id)
            if current.state.status is not CampaignStatus.PAUSED:
                raise CampaignConflictError(
                    f"campaign {campaign_id!r} cannot resume from "
                    f"{current.state.status.value}"
                )
            now = self._now()
            lease = self._try_acquire(current.spec, now=now)
            if lease is False:
                raise CampaignResourceBlockedError(
                    f"campaign {campaign_id!r} is waiting for resources"
                )

            resumed = self._transition(
                current,
                CampaignStatus.RUNNING,
                occurred_at=now,
            )
            if resumed.state.attempt != current.state.attempt:
                resumed = CampaignRecord(
                    spec=resumed.spec,
                    state=replace(resumed.state, attempt=current.state.attempt),
                )
            try:
                self._repository.save(resumed)
            except Exception:
                self._release(campaign_id)
                raise
            try:
                self._executor.signal(campaign_id, "resume")
            except Exception as exc:
                failed = self._fail_signal(resumed, "resume", exc)
                self._release(campaign_id)
                return failed

            payload: dict[str, object] = {"attempt": resumed.state.attempt}
            if lease is not None:
                payload["resource_lease_id"] = lease.lease_id
                payload["resources"] = dict(lease.resources)
            self._events.record(
                campaign_id,
                CampaignEventKind.RESUMED,
                occurred_at=resumed.state.updated_at,
                payload=payload,
            )
            return resumed

    def request_cancel(self, campaign_id: str) -> CampaignRecord:
        result = super().request_cancel(campaign_id)
        if result.state.status in {
            CampaignStatus.CANCELLED,
            CampaignStatus.FAILED,
        }:
            self._release(campaign_id)
        return result

    def mark_cancelled(self, campaign_id: str) -> CampaignRecord:
        with self._lock:
            try:
                return super().mark_cancelled(campaign_id)
            finally:
                current = self._repository.get(campaign_id)
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
                current = self._repository.get(campaign_id)
                if current is not None and current.state.status in {
                    CampaignStatus.SUCCEEDED,
                    CampaignStatus.FAILED,
                }:
                    self._release(campaign_id)

    def renew_resources(self, campaign_id: str) -> ResourceLease | None:
        """Renew the lease held by an active delegated campaign."""

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

    def _fail_dispatch(
        self,
        running: CampaignRecord,
        exc: Exception,
        lease: ResourceLease | None,
    ) -> ResourceDispatchResult:
        error = f"{type(exc).__name__}: {exc}"
        failed_state = transition_campaign(
            running.state,
            CampaignStatus.FAILED,
            occurred_at=self._now(),
            error=error,
        )
        failed = CampaignRecord(spec=running.spec, state=failed_state)
        self._repository.save(failed)
        try:
            self._events.record(
                running.spec.campaign_id,
                CampaignEventKind.FAILED,
                occurred_at=failed_state.updated_at,
                payload={"error": error, "phase": "dispatch"},
            )
        finally:
            self._release(running.spec.campaign_id)
        return ResourceDispatchResult(
            record=failed,
            runtime_reference=None,
            dispatch_error=error,
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
