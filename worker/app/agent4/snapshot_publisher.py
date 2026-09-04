"""Caller-driven publication of immutable Agent 4 operator snapshots (A4-25c)."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from .contracts import Clock
from .domain import CampaignRecord
from .repository import JsonCampaignRepository
from .snapshot_store import (
    JsonOperatorSnapshotStore,
    OperatorCampaignSnapshot,
    OperatorRootSnapshot,
)
from .timeline import JsonCampaignTimelineStore
from .timeline_evidence import JsonCampaignEvidenceRecordStore


class OperatorSnapshotPublicationError(RuntimeError):
    """Base error for writer-owned snapshot publication failures."""


class OperatorSnapshotPublicationBlockedError(OperatorSnapshotPublicationError):
    """Publication is blocked because durable projections are still pending."""


class OperatorSnapshotPublicationConflictError(OperatorSnapshotPublicationError):
    """Mutable writer state changed while one immutable view was captured."""


class OperatorSnapshotPublicationIntegrityError(OperatorSnapshotPublicationError):
    """Verified mutable stores cannot form one self-consistent product view."""


@dataclass(frozen=True, slots=True)
class _CapturedCampaign:
    record: CampaignRecord
    timeline_sequence: int
    timeline_head_sha256: str | None
    evidence_sequence: int
    evidence_head_sha256: str | None
    latest_evidence_timeline_head_sha256: str | None

    @property
    def campaign_id(self) -> str:
        return self.record.spec.campaign_id

    def snapshot(self) -> OperatorCampaignSnapshot:
        return OperatorCampaignSnapshot.create(
            self.record,
            timeline_head_sequence=self.timeline_sequence,
            timeline_head_sha256=self.timeline_head_sha256,
            evidence_head_sequence=self.evidence_sequence,
            evidence_head_sha256=self.evidence_head_sha256,
            latest_evidence_timeline_head_sha256=(
                self.latest_evidence_timeline_head_sha256
            ),
        )


class Agent4OperatorSnapshotPublisher:
    """Serialize caller-driven immutable projections of one writer runtime.

    The publisher never mutates campaign/timeline/evidence state, never starts a
    timer or thread, and never runs retention inside the publication commit
    path. Callers first finish/reconcile the product-visible writer mutation,
    then explicitly call :meth:`publish`.
    """

    def __init__(
        self,
        *,
        repository: JsonCampaignRepository,
        timeline: JsonCampaignTimelineStore,
        evidence: JsonCampaignEvidenceRecordStore,
        snapshots: JsonOperatorSnapshotStore,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._timeline = timeline
        self._evidence = evidence
        self._snapshots = snapshots
        self._clock = clock
        self._lock = RLock()

    @property
    def snapshots(self) -> JsonOperatorSnapshotStore:
        return self._snapshots

    def publish(self) -> OperatorRootSnapshot:
        """Publish one complete, verified immutable operator root.

        A publication captures all campaigns so creation/update/deletion are
        represented by one complete root. Existing content-addressed campaign
        snapshots are reused. If nothing changed, the current root is returned
        without manufacturing a new sequence.
        """

        with self._lock:
            self._reject_pending_projections()
            records = self._repository.list()
            captures = tuple(self._capture(record) for record in records)
            self._assert_capture_still_stable(records, captures)

            campaign_snapshots = tuple(capture.snapshot() for capture in captures)
            mapping = {
                snapshot.campaign_id: snapshot.snapshot_id
                for snapshot in campaign_snapshots
            }

            # Writing every captured blob is deliberate. Existing blobs are
            # verified by the immutable store and returned idempotently; missing
            # or conflicting objects fail closed before a root can reference them.
            for snapshot in campaign_snapshots:
                self._snapshots.write_campaign_snapshot(snapshot)

            # Campaign blob writes can take long enough for the mutable writer
            # stores to advance. Re-check immediately before selecting the parent
            # and publishing the immutable root so no change inside the complete
            # capture/publication preparation window can be silently omitted.
            self._assert_capture_still_stable(records, captures)

            current = self._snapshots.load_current()
            if current is not None and dict(current.campaigns) == mapping:
                return current

            parent = current.snapshot_id if current is not None else None
            root = OperatorRootSnapshot.create(
                root_sequence=(current.root_sequence + 1 if current else 1),
                parent_snapshot_id=parent,
                published_at=self._clock.now(),
                campaigns=mapping,
            )
            return self._snapshots.publish_root(root, expected_parent=parent)

    def prune(self) -> tuple[str, ...]:
        """Run explicit retention/GC after publication, never inside commit."""

        return self._snapshots.prune(now=self._clock.now())

    def _capture(self, record: CampaignRecord) -> _CapturedCampaign:
        campaign_id = record.spec.campaign_id
        self._reject_pending_projections(campaign_id)

        timeline_entries = self._timeline.list(campaign_id)
        evidence_records = self._evidence.list(campaign_id)

        timeline_heads = {
            entry.entry_hash: entry.event.sequence for entry in timeline_entries
        }
        timeline_events = {
            entry.event.event_id: entry.event.sequence for entry in timeline_entries
        }
        for evidence_record in evidence_records:
            bound_sequence = timeline_heads.get(evidence_record.timeline_head_hash)
            if bound_sequence is None:
                raise OperatorSnapshotPublicationIntegrityError(
                    "evidence record references a timeline head outside the "
                    f"captured campaign timeline: {campaign_id!r}"
                )
            if evidence_record.related_event_id is not None:
                related_sequence = timeline_events.get(evidence_record.related_event_id)
                if related_sequence is None or related_sequence > bound_sequence:
                    raise OperatorSnapshotPublicationIntegrityError(
                        "evidence record relates to an event outside its captured "
                        f"timeline head: {campaign_id!r}"
                    )

        # Re-read the replaceable campaign envelope after the append-only stores.
        # If it changed during capture, mixing those values would create exactly
        # the cross-store contradiction this projection exists to prevent.
        if self._repository.get(campaign_id) != record:
            raise OperatorSnapshotPublicationConflictError(
                f"campaign {campaign_id!r} changed while snapshot was captured"
            )
        self._reject_pending_projections(campaign_id)

        timeline_head = timeline_entries[-1] if timeline_entries else None
        evidence_head = evidence_records[-1] if evidence_records else None
        return _CapturedCampaign(
            record=record,
            timeline_sequence=(timeline_head.event.sequence if timeline_head else 0),
            timeline_head_sha256=(timeline_head.entry_hash if timeline_head else None),
            evidence_sequence=(evidence_head.sequence if evidence_head else 0),
            evidence_head_sha256=(evidence_head.record_hash if evidence_head else None),
            latest_evidence_timeline_head_sha256=(
                evidence_head.timeline_head_hash if evidence_head else None
            ),
        )

    def _assert_capture_still_stable(
        self,
        records: tuple[CampaignRecord, ...],
        captures: tuple[_CapturedCampaign, ...],
    ) -> None:
        self._reject_pending_projections()
        if self._repository.list() != records:
            raise OperatorSnapshotPublicationConflictError(
                "campaign repository changed while snapshot root was captured"
            )

        for capture in captures:
            timeline = self._timeline.verify(capture.campaign_id)
            if (
                timeline.entry_count != capture.timeline_sequence
                or timeline.head_hash != capture.timeline_head_sha256
            ):
                raise OperatorSnapshotPublicationConflictError(
                    f"campaign {capture.campaign_id!r} timeline changed during capture"
                )
            evidence = self._evidence.verify(capture.campaign_id)
            if (
                evidence.record_count != capture.evidence_sequence
                or evidence.head_hash != capture.evidence_head_sha256
                or evidence.latest_timeline_head_hash
                != capture.latest_evidence_timeline_head_sha256
            ):
                raise OperatorSnapshotPublicationConflictError(
                    f"campaign {capture.campaign_id!r} evidence changed during capture"
                )

        self._reject_pending_projections()

    def _reject_pending_projections(self, campaign_id: str | None = None) -> None:
        pending = self._repository.pending_projections(campaign_id)
        if pending:
            scope = f" for campaign {campaign_id!r}" if campaign_id else ""
            raise OperatorSnapshotPublicationBlockedError(
                "operator snapshot publication requires reconciled projections"
                + scope
            )
