"""Snapshot-bound Agent 4 operator reads over immutable A4-25 roots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, TypeVar

from .campaign_list_query import (
    CampaignListQueryCursor,
    page_campaign_records,
    select_campaign_records,
)
from .contracts import CampaignTimelineStore
from .domain import CampaignStatus, CampaignValidationError, _require_text
from .operator import Agent4CampaignOverview
from .operator_evidence import CampaignEvidenceRecordNotFoundError
from .service import CampaignNotFoundError
from .snapshot_cursor import (
    OperatorSnapshotCursor,
    OperatorSnapshotCursorError,
    SnapshotInnerCursor,
    require_operator_snapshot_id,
)
from .snapshot_store import (
    JsonOperatorSnapshotStore,
    OperatorCampaignSnapshot,
    OperatorRootSnapshot,
    OperatorSnapshotIntegrityError,
)
from .timeline import CampaignTimelineEntry
from .timeline_evidence import (
    CampaignEvidenceRecord,
    CampaignEvidenceRecordStore,
    CampaignEvidenceVerification,
)
from .timeline_evidence_query import (
    CampaignEvidenceQueryCursor,
    CampaignEvidenceQueryPage,
    CampaignEvidenceQueryService,
)
from .timeline_query import (
    CampaignTimelineQueryCursor,
    CampaignTimelineQueryPage,
    CampaignTimelineQueryService,
)


class OperatorSnapshotReadUnavailableError(RuntimeError):
    """No committed root exists for a new logical snapshot-bound read."""


@dataclass(frozen=True, slots=True)
class SnapshotCampaignRead:
    snapshot_id: str
    campaign: Agent4CampaignOverview


@dataclass(frozen=True, slots=True)
class SnapshotCampaignPage:
    snapshot_id: str
    campaigns: tuple[Agent4CampaignOverview, ...]
    start_cursor: OperatorSnapshotCursor
    next_cursor: OperatorSnapshotCursor
    head_cursor: OperatorSnapshotCursor
    has_more: bool


@dataclass(frozen=True, slots=True)
class SnapshotTimelinePage:
    snapshot_id: str
    page: CampaignTimelineQueryPage
    start_cursor: OperatorSnapshotCursor
    next_cursor: OperatorSnapshotCursor
    head_cursor: OperatorSnapshotCursor


@dataclass(frozen=True, slots=True)
class SnapshotEvidencePage:
    snapshot_id: str
    page: CampaignEvidenceQueryPage
    start_cursor: OperatorSnapshotCursor
    next_cursor: OperatorSnapshotCursor
    head_cursor: OperatorSnapshotCursor


@dataclass(frozen=True, slots=True)
class SnapshotEvidenceRead:
    snapshot_id: str
    evidence: CampaignEvidenceRecord


@dataclass(frozen=True, slots=True)
class SnapshotEvidenceVerificationRead:
    snapshot_id: str
    verification: CampaignEvidenceVerification


_CursorT = TypeVar(
    "_CursorT",
    CampaignListQueryCursor,
    CampaignTimelineQueryCursor,
    CampaignEvidenceQueryCursor,
)


class Agent4SnapshotOperatorReadService:
    """Read one logical product flow from exactly one retained immutable root.

    The immutable root/campaign snapshots are the read authority. Timeline and
    evidence stores are append-only history sources and are exposed only through
    the sequence/hash prefixes captured by the selected campaign snapshot.
    """

    def __init__(
        self,
        *,
        snapshots: JsonOperatorSnapshotStore,
        timeline: CampaignTimelineStore,
        evidence: CampaignEvidenceRecordStore,
    ) -> None:
        if not isinstance(snapshots, JsonOperatorSnapshotStore):
            raise CampaignValidationError(
                "snapshots must be a JsonOperatorSnapshotStore"
            )
        if not isinstance(timeline, CampaignTimelineStore):
            raise CampaignValidationError(
                "timeline must implement CampaignTimelineStore"
            )
        if not isinstance(evidence, CampaignEvidenceRecordStore):
            raise CampaignValidationError(
                "evidence must implement CampaignEvidenceRecordStore"
            )
        self._snapshots = snapshots
        self._timeline = timeline
        self._evidence = evidence
        self._timeline_query = CampaignTimelineQueryService(timeline)
        self._evidence_query = CampaignEvidenceQueryService(evidence)

    @property
    def snapshots(self) -> JsonOperatorSnapshotStore:
        return self._snapshots

    def campaign_page(
        self,
        *,
        snapshot_id: str | None = None,
        statuses: CampaignStatus | str | Iterable[CampaignStatus | str] | None = None,
        after: OperatorSnapshotCursor | None = None,
        snapshot_head: OperatorSnapshotCursor | None = None,
        limit: int = 100,
    ) -> SnapshotCampaignPage:
        root = self._root(snapshot_id, after, snapshot_head)
        campaign_snapshots = tuple(
            self._load_campaign(root, campaign_id)
            for campaign_id in root.campaigns
        )
        records = tuple(snapshot.campaign for snapshot in campaign_snapshots)
        normalized_statuses, selected_records = select_campaign_records(
            records,
            statuses,
        )
        by_id = {
            snapshot.campaign_id: snapshot for snapshot in campaign_snapshots
        }
        overviews = {
            record.spec.campaign_id: self._overview(
                by_id[record.spec.campaign_id]
            )
            for record in selected_records
        }
        inner_after = self._inner_cursor(
            after,
            root.snapshot_id,
            CampaignListQueryCursor,
        )
        inner_head = self._inner_cursor(
            snapshot_head,
            root.snapshot_id,
            CampaignListQueryCursor,
        )
        page = page_campaign_records(
            selected_records,
            summaries={
                campaign_id: overview.snapshot_summary()
                for campaign_id, overview in overviews.items()
            },
            statuses=normalized_statuses,
            after=inner_after,
            limit=limit,
            snapshot_head=inner_head,
        )
        return SnapshotCampaignPage(
            snapshot_id=root.snapshot_id,
            campaigns=tuple(
                overviews[record.spec.campaign_id] for record in page.records
            ),
            start_cursor=self._wrap(root, page.start_cursor),
            next_cursor=self._wrap(root, page.next_cursor),
            head_cursor=self._wrap(root, page.head_cursor),
            has_more=page.has_more,
        )

    def campaign(
        self,
        campaign_id: str,
        *,
        snapshot_id: str | None = None,
    ) -> SnapshotCampaignRead:
        root = self._root(snapshot_id)
        snapshot = self._load_campaign(root, campaign_id)
        return SnapshotCampaignRead(
            snapshot_id=root.snapshot_id,
            campaign=self._overview(snapshot),
        )

    def timeline_page(
        self,
        campaign_id: str,
        *,
        snapshot_id: str | None = None,
        after: OperatorSnapshotCursor | None = None,
        limit: int = 100,
    ) -> SnapshotTimelinePage:
        root = self._root(snapshot_id, after)
        snapshot = self._load_campaign(root, campaign_id)
        self._timeline_prefix(snapshot)
        head = CampaignTimelineQueryCursor(
            campaign_id=snapshot.campaign_id,
            sequence=snapshot.timeline_head_sequence,
            entry_hash=snapshot.timeline_head_sha256,
        )
        inner_after = self._inner_cursor(
            after,
            root.snapshot_id,
            CampaignTimelineQueryCursor,
        )
        page = self._timeline_query.page(
            snapshot.campaign_id,
            after=inner_after,
            limit=limit,
            snapshot_head=head,
        )
        return SnapshotTimelinePage(
            snapshot_id=root.snapshot_id,
            page=page,
            start_cursor=self._wrap(root, page.start_cursor),
            next_cursor=self._wrap(root, page.next_cursor),
            head_cursor=self._wrap(root, page.head_cursor),
        )

    def evidence_page(
        self,
        campaign_id: str,
        *,
        snapshot_id: str | None = None,
        after: OperatorSnapshotCursor | None = None,
        limit: int = 100,
    ) -> SnapshotEvidencePage:
        root = self._root(snapshot_id, after)
        snapshot = self._load_campaign(root, campaign_id)
        self._evidence_prefix(snapshot)
        head = CampaignEvidenceQueryCursor(
            campaign_id=snapshot.campaign_id,
            sequence=snapshot.evidence_head_sequence,
            record_hash=snapshot.evidence_head_sha256,
        )
        inner_after = self._inner_cursor(
            after,
            root.snapshot_id,
            CampaignEvidenceQueryCursor,
        )
        page = self._evidence_query.page(
            snapshot.campaign_id,
            after=inner_after,
            limit=limit,
            snapshot_head=head,
        )
        return SnapshotEvidencePage(
            snapshot_id=root.snapshot_id,
            page=page,
            start_cursor=self._wrap(root, page.start_cursor),
            next_cursor=self._wrap(root, page.next_cursor),
            head_cursor=self._wrap(root, page.head_cursor),
        )

    def evidence(
        self,
        campaign_id: str,
        evidence_id: str,
        *,
        snapshot_id: str | None = None,
    ) -> SnapshotEvidenceRead:
        campaign_id = _require_text(campaign_id, "campaign_id")
        evidence_id = _require_text(evidence_id, "evidence_id")
        root = self._root(snapshot_id)
        snapshot = self._load_campaign(root, campaign_id)
        records = self._evidence_prefix(snapshot)
        record = next(
            (item for item in records if item.evidence_id == evidence_id),
            None,
        )
        if record is None:
            raise CampaignEvidenceRecordNotFoundError(
                f"evidence record {evidence_id!r} was not present in snapshot "
                f"{root.snapshot_id!r}"
            )
        return SnapshotEvidenceRead(
            snapshot_id=root.snapshot_id,
            evidence=record,
        )

    def verification(
        self,
        campaign_id: str,
        *,
        snapshot_id: str | None = None,
    ) -> SnapshotEvidenceVerificationRead:
        root = self._root(snapshot_id)
        snapshot = self._load_campaign(root, campaign_id)
        records = self._evidence_prefix(snapshot)
        verification = CampaignEvidenceVerification(
            campaign_id=snapshot.campaign_id,
            record_count=len(records),
            head_hash=(records[-1].record_hash if records else None),
            latest_timeline_head_hash=(
                records[-1].timeline_head_hash if records else None
            ),
        )
        return SnapshotEvidenceVerificationRead(
            snapshot_id=root.snapshot_id,
            verification=verification,
        )

    def _root(
        self,
        snapshot_id: str | None,
        *cursors: OperatorSnapshotCursor | None,
    ) -> OperatorRootSnapshot:
        for cursor in cursors:
            if cursor is not None and not isinstance(cursor, OperatorSnapshotCursor):
                raise CampaignValidationError(
                    "snapshot cursor must be an OperatorSnapshotCursor or None"
                )
        explicit = (
            require_operator_snapshot_id(snapshot_id)
            if snapshot_id is not None
            else None
        )
        cursor_ids = {
            cursor.snapshot_id for cursor in cursors if cursor is not None
        }
        if len(cursor_ids) > 1:
            raise OperatorSnapshotCursorError(
                "snapshot-bound cursors refer to different immutable roots"
            )
        cursor_id = next(iter(cursor_ids), None)
        if explicit is not None and cursor_id is not None and explicit != cursor_id:
            raise OperatorSnapshotCursorError(
                "explicit snapshot_id differs from snapshot-bound cursor"
            )
        selected = explicit or cursor_id
        if selected is not None:
            return self._snapshots.load_root(selected)
        current = self._snapshots.load_current()
        if current is None:
            raise OperatorSnapshotReadUnavailableError(
                "no committed operator snapshot is available"
            )
        return current

    def _load_campaign(
        self,
        root: OperatorRootSnapshot,
        campaign_id: str,
    ) -> OperatorCampaignSnapshot:
        campaign_id = _require_text(campaign_id, "campaign_id")
        campaign_snapshot_id = root.campaigns.get(campaign_id)
        if campaign_snapshot_id is None:
            raise CampaignNotFoundError(
                f"campaign {campaign_id!r} is not present in selected snapshot"
            )
        snapshot = self._snapshots.load_campaign(campaign_snapshot_id)
        if snapshot.campaign_id != campaign_id:
            raise OperatorSnapshotIntegrityError(
                "root campaign identity differs from immutable campaign snapshot"
            )
        return snapshot

    def _overview(self, snapshot: OperatorCampaignSnapshot) -> Agent4CampaignOverview:
        entries = self._timeline_prefix(snapshot)
        return Agent4CampaignOverview(
            record=snapshot.campaign,
            timeline_entries=len(entries),
            event_entries=len(entries),
            evidence_entries=sum(len(entry.evidence) for entry in entries),
            latest_timeline_hash=(entries[-1].entry_hash if entries else None),
        )

    def _timeline_prefix(
        self,
        snapshot: OperatorCampaignSnapshot,
    ) -> tuple[CampaignTimelineEntry, ...]:
        entries = self._timeline.list(snapshot.campaign_id)
        sequence = snapshot.timeline_head_sequence
        if len(entries) < sequence:
            raise OperatorSnapshotIntegrityError(
                "timeline history no longer reaches immutable snapshot head"
            )
        prefix = entries[:sequence]
        actual_head = prefix[-1].entry_hash if prefix else None
        if actual_head != snapshot.timeline_head_sha256:
            raise OperatorSnapshotIntegrityError(
                "timeline history does not match immutable snapshot head"
            )
        return prefix

    def _evidence_prefix(
        self,
        snapshot: OperatorCampaignSnapshot,
    ) -> tuple[CampaignEvidenceRecord, ...]:
        records = self._evidence.list(snapshot.campaign_id)
        sequence = snapshot.evidence_head_sequence
        if len(records) < sequence:
            raise OperatorSnapshotIntegrityError(
                "evidence history no longer reaches immutable snapshot head"
            )
        prefix = records[:sequence]
        actual_head = prefix[-1].record_hash if prefix else None
        actual_timeline_head = prefix[-1].timeline_head_hash if prefix else None
        if actual_head != snapshot.evidence_head_sha256:
            raise OperatorSnapshotIntegrityError(
                "evidence history does not match immutable snapshot head"
            )
        if actual_timeline_head != snapshot.latest_evidence_timeline_head_sha256:
            raise OperatorSnapshotIntegrityError(
                "evidence history timeline binding differs from immutable snapshot"
            )
        return prefix

    @staticmethod
    def _wrap(
        root: OperatorRootSnapshot,
        cursor: SnapshotInnerCursor,
    ) -> OperatorSnapshotCursor:
        return OperatorSnapshotCursor(
            snapshot_id=root.snapshot_id,
            cursor=cursor,
        )

    @staticmethod
    def _inner_cursor(
        cursor: OperatorSnapshotCursor | None,
        snapshot_id: str,
        cursor_type: type[_CursorT],
    ) -> _CursorT | None:
        if cursor is None:
            return None
        inner = cursor.require_snapshot(snapshot_id)
        if not isinstance(inner, cursor_type):
            raise OperatorSnapshotCursorError(
                "snapshot-bound cursor type does not match requested resource"
            )
        return inner
