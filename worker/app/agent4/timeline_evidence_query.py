"""Verified, bounded and caller-driven query paging for A4 evidence records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .domain import CampaignValidationError, JsonValue, _require_text
from .timeline import _require_sha256
from .timeline_evidence import (
    CampaignEvidenceRecord,
    CampaignEvidenceRecordStore,
)

MAX_EVIDENCE_QUERY_PAGE_SIZE = 1_000
_EVIDENCE_QUERY_CURSOR_SCHEMA = (
    "modelrig-agent4/campaign-evidence-query-cursor/v1"
)


class CampaignEvidenceQueryError(RuntimeError):
    """Base error for verified evidence query operations."""


class CampaignEvidenceQueryCursorError(CampaignEvidenceQueryError):
    """Raised when a cursor does not bind to the verified evidence chain."""


def _require_limit(value: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > MAX_EVIDENCE_QUERY_PAGE_SIZE
    ):
        raise CampaignValidationError(
            "limit must be an integer between 1 and "
            f"{MAX_EVIDENCE_QUERY_PAGE_SIZE}"
        )
    return value


@dataclass(frozen=True, slots=True)
class CampaignEvidenceQueryCursor:
    """Hash-bound position immediately after one verified evidence record."""

    campaign_id: str
    sequence: int
    record_hash: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "campaign_id",
            _require_text(self.campaign_id, "campaign_id"),
        )
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
        ):
            raise CampaignValidationError(
                "evidence query cursor sequence must be a non-negative integer"
            )
        if self.sequence == 0:
            if self.record_hash is not None:
                raise CampaignValidationError(
                    "genesis evidence query cursor must not declare record_hash"
                )
            return
        if self.record_hash is None:
            raise CampaignValidationError(
                "non-genesis evidence query cursor requires record_hash"
            )
        object.__setattr__(
            self,
            "record_hash",
            _require_sha256(self.record_hash, "record_hash"),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": _EVIDENCE_QUERY_CURSOR_SCHEMA,
            "campaign_id": self.campaign_id,
            "sequence": self.sequence,
            "record_hash": (
                f"sha256:{self.record_hash}"
                if self.record_hash is not None
                else None
            ),
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "CampaignEvidenceQueryCursor":
        if not isinstance(value, Mapping):
            raise CampaignValidationError(
                "campaign evidence query cursor must be an object"
            )
        if value.get("schema") != _EVIDENCE_QUERY_CURSOR_SCHEMA:
            raise CampaignValidationError(
                "campaign evidence query cursor schema is not supported"
            )
        campaign_id = value.get("campaign_id")
        sequence = value.get("sequence")
        record_hash = value.get("record_hash")
        if not isinstance(campaign_id, str):
            raise CampaignValidationError(
                "campaign evidence query cursor campaign_id must be text"
            )
        if isinstance(sequence, bool) or not isinstance(sequence, int):
            raise CampaignValidationError(
                "campaign evidence query cursor sequence must be an integer"
            )
        if record_hash is not None and not isinstance(record_hash, str):
            raise CampaignValidationError(
                "campaign evidence query cursor record_hash must be text or null"
            )
        return cls(
            campaign_id=campaign_id,
            sequence=sequence,
            record_hash=record_hash,
        )


@dataclass(frozen=True, slots=True)
class CampaignEvidenceQueryPage:
    """One bounded page from a fully verified, stable evidence snapshot."""

    campaign_id: str
    records: tuple[CampaignEvidenceRecord, ...]
    start_cursor: CampaignEvidenceQueryCursor
    next_cursor: CampaignEvidenceQueryCursor
    head_cursor: CampaignEvidenceQueryCursor
    has_more: bool

    def __post_init__(self) -> None:
        campaign_id = _require_text(self.campaign_id, "campaign_id")
        records = tuple(self.records)
        if any(not isinstance(item, CampaignEvidenceRecord) for item in records):
            raise CampaignValidationError(
                "evidence query page records must be CampaignEvidenceRecord instances"
            )
        for field_name, cursor in (
            ("start_cursor", self.start_cursor),
            ("next_cursor", self.next_cursor),
            ("head_cursor", self.head_cursor),
        ):
            if not isinstance(cursor, CampaignEvidenceQueryCursor):
                raise CampaignValidationError(
                    f"{field_name} must be CampaignEvidenceQueryCursor"
                )
            if cursor.campaign_id != campaign_id:
                raise CampaignValidationError(
                    f"{field_name} campaign_id differs from page campaign_id"
                )
        if not isinstance(self.has_more, bool):
            raise CampaignValidationError("has_more must be boolean")
        if not (
            self.start_cursor.sequence
            <= self.next_cursor.sequence
            <= self.head_cursor.sequence
        ):
            raise CampaignValidationError(
                "evidence query page cursor sequences must be ordered"
            )
        expected_sequences = tuple(
            range(
                self.start_cursor.sequence + 1,
                self.next_cursor.sequence + 1,
            )
        )
        if tuple(item.sequence for item in records) != expected_sequences:
            raise CampaignValidationError(
                "evidence query page records must be contiguous after start_cursor"
            )
        if records:
            if self.next_cursor.record_hash != records[-1].record_hash:
                raise CampaignValidationError(
                    "next_cursor must bind the final evidence query record"
                )
        elif self.next_cursor != self.start_cursor:
            raise CampaignValidationError(
                "empty evidence query page must preserve the start cursor"
            )
        if self.has_more != (
            self.next_cursor.sequence < self.head_cursor.sequence
        ):
            raise CampaignValidationError(
                "has_more must match next_cursor and head_cursor"
            )
        object.__setattr__(self, "campaign_id", campaign_id)
        object.__setattr__(self, "records", records)


class CampaignEvidenceQueryService:
    """Read verified evidence snapshots through bounded hash-bound cursors."""

    def __init__(self, records: CampaignEvidenceRecordStore) -> None:
        if not isinstance(records, CampaignEvidenceRecordStore):
            raise TypeError(
                "records must implement CampaignEvidenceRecordStore"
            )
        self._records = records

    @property
    def records(self) -> CampaignEvidenceRecordStore:
        return self._records

    @staticmethod
    def genesis_cursor(campaign_id: str) -> CampaignEvidenceQueryCursor:
        return CampaignEvidenceQueryCursor(
            campaign_id=campaign_id,
            sequence=0,
            record_hash=None,
        )

    def cursor_at(
        self,
        campaign_id: str,
        sequence: int,
    ) -> CampaignEvidenceQueryCursor:
        campaign_id = _require_text(campaign_id, "campaign_id")
        records = self._records.list(campaign_id)
        if (
            isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence < 0
        ):
            raise CampaignValidationError(
                "evidence query cursor sequence must be a non-negative integer"
            )
        if sequence > len(records):
            raise CampaignEvidenceQueryCursorError(
                f"cursor sequence {sequence} exceeds evidence head {len(records)}"
            )
        return self._cursor_for(records, campaign_id, sequence)

    def page(
        self,
        campaign_id: str,
        *,
        after: CampaignEvidenceQueryCursor | None = None,
        limit: int = 100,
        snapshot_head: CampaignEvidenceQueryCursor | None = None,
    ) -> CampaignEvidenceQueryPage:
        campaign_id = _require_text(campaign_id, "campaign_id")
        limit = _require_limit(limit)
        records = self._records.list(campaign_id)
        start = self._validate_cursor(
            records,
            campaign_id,
            after,
            field_name="after",
        )
        if snapshot_head is None:
            head = self._cursor_for(records, campaign_id, len(records))
        else:
            head = self._validate_cursor(
                records,
                campaign_id,
                snapshot_head,
                field_name="snapshot_head",
            )
        if start.sequence > head.sequence:
            raise CampaignEvidenceQueryCursorError(
                "after cursor is beyond the requested snapshot head"
            )
        stop = min(start.sequence + limit, head.sequence)
        page_records = records[start.sequence:stop]
        next_cursor = self._cursor_for(records, campaign_id, stop)
        return CampaignEvidenceQueryPage(
            campaign_id=campaign_id,
            records=page_records,
            start_cursor=start,
            next_cursor=next_cursor,
            head_cursor=head,
            has_more=next_cursor.sequence < head.sequence,
        )

    def _validate_cursor(
        self,
        records: tuple[CampaignEvidenceRecord, ...],
        campaign_id: str,
        cursor: CampaignEvidenceQueryCursor | None,
        *,
        field_name: str,
    ) -> CampaignEvidenceQueryCursor:
        if cursor is None:
            return self.genesis_cursor(campaign_id)
        if not isinstance(cursor, CampaignEvidenceQueryCursor):
            raise TypeError(
                f"{field_name} must be CampaignEvidenceQueryCursor or None"
            )
        if cursor.campaign_id != campaign_id:
            raise CampaignEvidenceQueryCursorError(
                f"{field_name} cursor campaign_id differs"
            )
        if cursor.sequence > len(records):
            raise CampaignEvidenceQueryCursorError(
                f"{field_name} cursor sequence {cursor.sequence} exceeds "
                f"evidence head {len(records)}"
            )
        expected = self._cursor_for(records, campaign_id, cursor.sequence)
        if cursor.record_hash != expected.record_hash:
            raise CampaignEvidenceQueryCursorError(
                f"{field_name} cursor hash does not match evidence history"
            )
        return cursor

    @staticmethod
    def _cursor_for(
        records: tuple[CampaignEvidenceRecord, ...],
        campaign_id: str,
        sequence: int,
    ) -> CampaignEvidenceQueryCursor:
        return CampaignEvidenceQueryCursor(
            campaign_id=campaign_id,
            sequence=sequence,
            record_hash=(records[sequence - 1].record_hash if sequence else None),
        )
