"""Dormant, transport-independent operator reads for Agent 4.

The service exposes bounded campaign summaries, snapshot-bound campaign-list
paging and delegates timeline paging to the verified B-reference query service.
It mounts no API, starts no background work and performs no lifecycle mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol, runtime_checkable

from .campaign_list_query import (
    MAX_CAMPAIGN_LIST_PAGE_SIZE,
    CampaignListQueryCursor,
    CampaignListSnapshotSummary,
    page_campaign_records,
    select_campaign_records,
)
from .contracts import CampaignTimelineStore
from .domain import CampaignRecord, CampaignStatus, CampaignValidationError
from .timeline_query import (
    CampaignTimelineQueryCursor,
    CampaignTimelineQueryPage,
    CampaignTimelineQueryService,
)

MAX_OPERATOR_CAMPAIGNS = MAX_CAMPAIGN_LIST_PAGE_SIZE


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

    def snapshot_summary(self) -> CampaignListSnapshotSummary:
        """Return the exact rendered summary fields bound into list cursors."""

        return CampaignListSnapshotSummary(
            timeline_entries=self.timeline_entries,
            event_entries=self.event_entries,
            evidence_entries=self.evidence_entries,
            latest_timeline_hash=self.latest_timeline_hash,
        )


@dataclass(frozen=True, slots=True)
class Agent4CampaignPage:
    """One bounded page from a filter- and snapshot-bound campaign list."""

    campaigns: tuple[Agent4CampaignOverview, ...]
    start_cursor: CampaignListQueryCursor
    next_cursor: CampaignListQueryCursor
    head_cursor: CampaignListQueryCursor
    has_more: bool


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
        # Retain the established property name for composition compatibility;
        # the dependency itself is constrained to get/list authority.
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

    def campaign_page(
        self,
        *,
        statuses: CampaignStatus | str | Iterable[CampaignStatus | str] | None = None,
        after: CampaignListQueryCursor | None = None,
        limit: int = 100,
        snapshot_head: CampaignListQueryCursor | None = None,
    ) -> Agent4CampaignPage:
        """Return newest campaigns from one stable, hash-bound snapshot.

        Status selection is performed on canonical campaign records before any
        timeline/evidence verification. An excluded campaign therefore cannot
        widen the failure or verification scope of the requested snapshot, while
        every included record remains verified exactly once and hash-bound into
        the cursor digest.
        """

        records = tuple(self._scheduler.list())
        normalized_statuses, selected_records = select_campaign_records(
            records,
            statuses,
        )
        overviews = {
            record.spec.campaign_id: self._overview(record)
            for record in selected_records
        }
        page = page_campaign_records(
            selected_records,
            summaries={
                campaign_id: overview.snapshot_summary()
                for campaign_id, overview in overviews.items()
            },
            statuses=normalized_statuses,
            after=after,
            limit=limit,
            snapshot_head=snapshot_head,
        )
        return Agent4CampaignPage(
            campaigns=tuple(
                overviews[record.spec.campaign_id]
                for record in page.records
            ),
            start_cursor=page.start_cursor,
            next_cursor=page.next_cursor,
            head_cursor=page.head_cursor,
            has_more=page.has_more,
        )

    def list_campaigns(
        self,
        *,
        statuses: CampaignStatus | str | Iterable[CampaignStatus | str] | None = None,
        limit: int = 100,
    ) -> tuple[Agent4CampaignOverview, ...]:
        """Compatibility wrapper for the first campaign-list page."""

        return self.campaign_page(statuses=statuses, limit=limit).campaigns

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
