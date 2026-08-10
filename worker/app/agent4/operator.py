"""Dormant, transport-independent operator reads for Agent 4.

The service exposes bounded campaign summaries and delegates timeline paging to
the verified B-reference query service. It mounts no API, starts no background
work and performs no lifecycle mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol, runtime_checkable

from .contracts import CampaignTimelineStore
from .domain import CampaignRecord, CampaignStatus, CampaignValidationError
from .timeline_query import (
    CampaignTimelineQueryCursor,
    CampaignTimelineQueryPage,
    CampaignTimelineQueryService,
)

MAX_OPERATOR_CAMPAIGNS = 1_000


@runtime_checkable
class Agent4CampaignReadSource(Protocol):
    """Minimum campaign authority required by the GET-only operator surface."""

    def get(self, campaign_id: str) -> CampaignRecord:
        """Return one campaign or raise when it does not exist."""

    def list(self) -> tuple[CampaignRecord, ...]:
        """Return the canonical campaign-record snapshot."""


@dataclass(frozen=True, slots=True)
class Agent4CampaignOverview:
    """One verified campaign summary for a future transport adapter."""

    record: CampaignRecord
    timeline_entries: int
    event_entries: int
    evidence_entries: int
    latest_timeline_hash: str | None

    @property
    def campaign_id(self) -> str:
        return self.record.spec.campaign_id

    @property
    def status(self) -> CampaignStatus:
        return self.record.state.status


class Agent4OperatorReadService:
    """Explicit bounded reads over one composed Agent 4 object graph."""

    def __init__(
        self,
        *,
        scheduler: Agent4CampaignReadSource,
        timeline: CampaignTimelineStore,
        query: CampaignTimelineQueryService,
    ) -> None:
        if not isinstance(scheduler, Agent4CampaignReadSource):
            raise CampaignValidationError(
                "scheduler must implement the Agent 4 campaign read source"
            )
        if not isinstance(timeline, CampaignTimelineStore):
            raise CampaignValidationError(
                "timeline must implement CampaignTimelineStore"
            )
        if not isinstance(query, CampaignTimelineQueryService):
            raise CampaignValidationError(
                "query must be a CampaignTimelineQueryService"
            )
        self._scheduler = scheduler
        self._timeline = timeline
        self._query = query

    @property
    def scheduler(self) -> Agent4CampaignReadSource:
        # Retain the established property name for wire/composition compatibility;
        # the dependency contract itself is now read-only get/list authority.
        return self._scheduler

    @property
    def timeline(self) -> CampaignTimelineStore:
        return self._timeline

    @property
    def query(self) -> CampaignTimelineQueryService:
        return self._query

    def campaign(self, campaign_id: str) -> Agent4CampaignOverview:
        """Return one campaign plus verified timeline counters and head hash."""

        return self._overview(self._scheduler.get(campaign_id))

    def list_campaigns(
        self,
        *,
        statuses: CampaignStatus | str | Iterable[CampaignStatus | str] | None = None,
        limit: int = 100,
    ) -> tuple[Agent4CampaignOverview, ...]:
        """Return newest campaigns first, optionally filtered by lifecycle status."""

        bounded_limit = self._bounded_limit(limit)
        accepted = self._statuses(statuses)
        records = sorted(
            self._scheduler.list(),
            key=lambda record: (
                record.spec.created_at,
                record.spec.campaign_id,
            ),
            reverse=True,
        )
        selected: list[Agent4CampaignOverview] = []
        for record in records:
            if accepted is not None and record.state.status not in accepted:
                continue
            selected.append(self._overview(record))
            if len(selected) == bounded_limit:
                break
        return tuple(selected)

    def timeline_page(
        self,
        campaign_id: str,
        *,
        after: CampaignTimelineQueryCursor | None = None,
        limit: int = 100,
        snapshot_head: CampaignTimelineQueryCursor | None = None,
    ) -> CampaignTimelineQueryPage:
        """Return one bounded page using the B-reference hash-bound cursors."""

        self._scheduler.get(campaign_id)
        return self._query.page(
            campaign_id,
            after=after,
            limit=limit,
            snapshot_head=snapshot_head,
        )

    def _overview(self, record: CampaignRecord) -> Agent4CampaignOverview:
        verification = self._timeline.verify(record.spec.campaign_id)
        return Agent4CampaignOverview(
            record=record,
            timeline_entries=verification.entry_count,
            event_entries=verification.entry_count,
            evidence_entries=verification.evidence_count,
            latest_timeline_hash=verification.head_hash,
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
            raise CampaignValidationError(
                "statuses contain an unsupported value"
            ) from exc
        return frozenset(normalized)

    @staticmethod
    def _bounded_limit(value: int) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 1 <= value <= MAX_OPERATOR_CAMPAIGNS
        ):
            raise CampaignValidationError(
                "limit must be an integer from 1 through "
                f"{MAX_OPERATOR_CAMPAIGNS}"
            )
        return value
