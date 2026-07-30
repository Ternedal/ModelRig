"""Dormant, host-neutral operator read model for Agent 4.

The service in this module exposes bounded status and timeline reads over one
explicitly composed Agent 4 runtime. It mounts no API route, starts no thread and
performs no lifecycle mutation. A future Kaliv or RigGate adapter may translate
these typed values to its own transport contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .domain import CampaignRecord, CampaignStatus, CampaignValidationError
from .service import CampaignSchedulerService
from .timeline import (
    GENESIS_HASH,
    CampaignTimelineEntry,
    JsonlCampaignTimelineStore,
)


MAX_OPERATOR_CAMPAIGNS = 1_000
MAX_OPERATOR_TIMELINE_ENTRIES = 1_000


@dataclass(frozen=True, slots=True)
class Agent4CampaignOverview:
    """One verified campaign summary for an operator-facing adapter."""

    record: CampaignRecord
    timeline_entries: int
    event_entries: int
    evidence_entries: int
    latest_timeline_hash: str

    @property
    def campaign_id(self) -> str:
        return self.record.spec.campaign_id

    @property
    def status(self) -> CampaignStatus:
        return self.record.state.status


@dataclass(frozen=True, slots=True)
class Agent4TimelinePage:
    """One bounded page from a stable append-only timeline snapshot."""

    campaign_id: str
    entries: tuple[CampaignTimelineEntry, ...]
    after_sequence: int
    next_sequence: int
    snapshot_sequence: int

    @property
    def has_more(self) -> bool:
        return self.next_sequence < self.snapshot_sequence

    @property
    def remaining(self) -> int:
        return self.snapshot_sequence - self.next_sequence


class Agent4OperatorReadService:
    """Explicit bounded reads over the shared Agent 4 object graph."""

    def __init__(
        self,
        *,
        scheduler: CampaignSchedulerService,
        timeline: JsonlCampaignTimelineStore,
    ) -> None:
        if not isinstance(scheduler, CampaignSchedulerService):
            raise CampaignValidationError(
                "scheduler must implement CampaignSchedulerService"
            )
        if not isinstance(timeline, JsonlCampaignTimelineStore):
            raise CampaignValidationError(
                "timeline must be a JsonlCampaignTimelineStore"
            )
        self._scheduler = scheduler
        self._timeline = timeline

    @property
    def scheduler(self) -> CampaignSchedulerService:
        return self._scheduler

    @property
    def timeline(self) -> JsonlCampaignTimelineStore:
        return self._timeline

    def campaign(self, campaign_id: str) -> Agent4CampaignOverview:
        """Return one campaign plus verified timeline counters and head hash."""

        return self._overview(self._scheduler.get(campaign_id))

    def list_campaigns(
        self,
        *,
        statuses: CampaignStatus | str | Iterable[CampaignStatus | str] | None = None,
        limit: int = 100,
    ) -> tuple[Agent4CampaignOverview, ...]:
        """Return newest campaigns first, optionally filtered by status."""

        bounded_limit = self._bounded_limit(
            limit,
            field_name="limit",
            maximum=MAX_OPERATOR_CAMPAIGNS,
        )
        accepted = self._statuses(statuses)
        records = self._scheduler.list()
        selected = (
            record
            for record in reversed(records)
            if accepted is None or record.state.status in accepted
        )
        return tuple(
            self._overview(record)
            for _, record in zip(range(bounded_limit), selected, strict=False)
        )

    def timeline_page(
        self,
        campaign_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
        snapshot_sequence: int | None = None,
    ) -> Agent4TimelinePage:
        """Read a bounded page from one verified, stable append-only snapshot.

        ``after_sequence`` is the last timeline sequence already observed. The first
        call may omit ``snapshot_sequence``; the returned snapshot value can then be
        reused while clean appends continue, so later entries remain outside that
        operator read until a new explicit snapshot is requested.
        """

        self._scheduler.get(campaign_id)
        after = self._non_negative_int(after_sequence, "after_sequence")
        bounded_limit = self._bounded_limit(
            limit,
            field_name="limit",
            maximum=MAX_OPERATOR_TIMELINE_ENTRIES,
        )
        history = self._timeline.history(campaign_id)
        current_head = len(history)
        if snapshot_sequence is None:
            snapshot = current_head
        else:
            snapshot = self._non_negative_int(
                snapshot_sequence,
                "snapshot_sequence",
            )
            if snapshot > current_head:
                raise CampaignValidationError(
                    "snapshot_sequence is beyond the verified timeline head"
                )
        if after > snapshot:
            raise CampaignValidationError(
                "after_sequence must not exceed snapshot_sequence"
            )

        stop = min(snapshot, after + bounded_limit)
        entries = history[after:stop]
        next_sequence = entries[-1].timeline_sequence if entries else after
        return Agent4TimelinePage(
            campaign_id=campaign_id,
            entries=entries,
            after_sequence=after,
            next_sequence=next_sequence,
            snapshot_sequence=snapshot,
        )

    def _overview(self, record: CampaignRecord) -> Agent4CampaignOverview:
        history = self._timeline.history(record.spec.campaign_id)
        event_entries = sum(1 for entry in history if entry.entry_type.value == "event")
        evidence_entries = len(history) - event_entries
        return Agent4CampaignOverview(
            record=record,
            timeline_entries=len(history),
            event_entries=event_entries,
            evidence_entries=evidence_entries,
            latest_timeline_hash=(
                history[-1].content_hash if history else GENESIS_HASH
            ),
        )

    @staticmethod
    def _statuses(
        values: CampaignStatus | str | Iterable[CampaignStatus | str] | None,
    ) -> frozenset[CampaignStatus] | None:
        if values is None:
            return None
        if isinstance(values, (CampaignStatus, str)):
            candidates: tuple[CampaignStatus | str, ...] = (values,)
        else:
            try:
                candidates = tuple(values)
            except TypeError as exc:
                raise CampaignValidationError("statuses must be iterable") from exc
        normalized: set[CampaignStatus] = set()
        try:
            for value in candidates:
                normalized.add(CampaignStatus(value))
        except (TypeError, ValueError) as exc:
            raise CampaignValidationError("statuses contain an unsupported value") from exc
        return frozenset(normalized)

    @staticmethod
    def _bounded_limit(value: int, *, field_name: str, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
            raise CampaignValidationError(
                f"{field_name} must be an integer from 1 through {maximum}"
            )
        return value

    @staticmethod
    def _non_negative_int(value: int, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CampaignValidationError(
                f"{field_name} must be a non-negative integer"
            )
        return value
