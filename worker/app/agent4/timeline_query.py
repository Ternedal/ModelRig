"""Verified, bounded and caller-driven query paging for Agent 4 timelines."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .contracts import CampaignTimelineStore
from .domain import CampaignValidationError, JsonValue, _require_text
from .timeline import CampaignTimelineEntry

MAX_TIMELINE_QUERY_PAGE_SIZE = 1_000
_QUERY_CURSOR_SCHEMA = "modelrig-agent4/campaign-timeline-query-cursor/v1"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class CampaignTimelineQueryError(RuntimeError):
    """Base error for verified timeline query operations."""


class CampaignTimelineQueryCursorError(CampaignTimelineQueryError):
    """Raised when a query cursor does not bind to the verified timeline."""


def _require_hash(value: str, field_name: str) -> str:
    normalized = _require_text(value, field_name)
    if normalized.startswith("sha256:"):
        normalized = normalized[7:]
    if not _SHA256_PATTERN.fullmatch(normalized):
        raise CampaignValidationError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    return normalized


def _require_limit(value: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > MAX_TIMELINE_QUERY_PAGE_SIZE
    ):
        raise CampaignValidationError(
            "limit must be an integer between 1 and "
            f"{MAX_TIMELINE_QUERY_PAGE_SIZE}"
        )
    return value


@dataclass(frozen=True, slots=True)
class CampaignTimelineQueryCursor:
    """Hash-bound position immediately after one verified timeline entry."""

    campaign_id: str
    sequence: int
    entry_hash: str | None

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
                "query cursor sequence must be a non-negative integer"
            )
        if self.sequence == 0:
            if self.entry_hash is not None:
                raise CampaignValidationError(
                    "genesis query cursor must not declare entry_hash"
                )
            return
        if self.entry_hash is None:
            raise CampaignValidationError(
                "non-genesis query cursor requires entry_hash"
            )
        object.__setattr__(
            self,
            "entry_hash",
            _require_hash(self.entry_hash, "entry_hash"),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": _QUERY_CURSOR_SCHEMA,
            "campaign_id": self.campaign_id,
            "sequence": self.sequence,
            "entry_hash": (
                f"sha256:{self.entry_hash}"
                if self.entry_hash is not None
                else None
            ),
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "CampaignTimelineQueryCursor":
        if not isinstance(value, Mapping):
            raise CampaignValidationError(
                "campaign timeline query cursor must be an object"
            )
        if value.get("schema") != _QUERY_CURSOR_SCHEMA:
            raise CampaignValidationError(
                "campaign timeline query cursor schema is not supported"
            )
        campaign_id = value.get("campaign_id")
        sequence = value.get("sequence")
        entry_hash = value.get("entry_hash")
        if not isinstance(campaign_id, str):
            raise CampaignValidationError(
                "campaign timeline query cursor campaign_id must be text"
            )
        if isinstance(sequence, bool) or not isinstance(sequence, int):
            raise CampaignValidationError(
                "campaign timeline query cursor sequence must be an integer"
            )
        if entry_hash is not None and not isinstance(entry_hash, str):
            raise CampaignValidationError(
                "campaign timeline query cursor entry_hash must be text or null"
            )
        return cls(
            campaign_id=campaign_id,
            sequence=sequence,
            entry_hash=entry_hash,
        )


@dataclass(frozen=True, slots=True)
class CampaignTimelineQueryPage:
    """One bounded page from a fully verified, stable timeline snapshot."""

    campaign_id: str
    entries: tuple[CampaignTimelineEntry, ...]
    start_cursor: CampaignTimelineQueryCursor
    next_cursor: CampaignTimelineQueryCursor
    head_cursor: CampaignTimelineQueryCursor
    has_more: bool

    def __post_init__(self) -> None:
        campaign_id = _require_text(self.campaign_id, "campaign_id")
        entries = tuple(self.entries)
        if any(not isinstance(entry, CampaignTimelineEntry) for entry in entries):
            raise CampaignValidationError(
                "query page entries must be CampaignTimelineEntry instances"
            )
        for field_name, cursor in (
            ("start_cursor", self.start_cursor),
            ("next_cursor", self.next_cursor),
            ("head_cursor", self.head_cursor),
        ):
            if not isinstance(cursor, CampaignTimelineQueryCursor):
                raise CampaignValidationError(
                    f"{field_name} must be CampaignTimelineQueryCursor"
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
                "query page cursor sequences must be ordered"
            )
        expected_sequences = tuple(
            range(
                self.start_cursor.sequence + 1,
                self.next_cursor.sequence + 1,
            )
        )
        if tuple(entry.event.sequence for entry in entries) != expected_sequences:
            raise CampaignValidationError(
                "query page entries must be contiguous after start_cursor"
            )
        if entries:
            if self.next_cursor.entry_hash != entries[-1].entry_hash:
                raise CampaignValidationError(
                    "next_cursor must bind the final query page entry"
                )
        elif self.next_cursor != self.start_cursor:
            raise CampaignValidationError(
                "empty query page must preserve the start cursor"
            )
        if self.has_more != (
            self.next_cursor.sequence < self.head_cursor.sequence
        ):
            raise CampaignValidationError(
                "has_more must match next_cursor and head_cursor"
            )
        object.__setattr__(self, "campaign_id", campaign_id)
        object.__setattr__(self, "entries", entries)


class CampaignTimelineQueryService:
    """Read verified timeline snapshots through bounded hash-bound cursors."""

    def __init__(self, timeline: CampaignTimelineStore) -> None:
        if not isinstance(timeline, CampaignTimelineStore):
            raise TypeError("timeline must implement CampaignTimelineStore")
        self._timeline = timeline

    @staticmethod
    def genesis_cursor(campaign_id: str) -> CampaignTimelineQueryCursor:
        return CampaignTimelineQueryCursor(
            campaign_id=campaign_id,
            sequence=0,
            entry_hash=None,
        )

    def cursor_at(
        self,
        campaign_id: str,
        sequence: int,
    ) -> CampaignTimelineQueryCursor:
        campaign_id = _require_text(campaign_id, "campaign_id")
        entries = self._timeline.list(campaign_id)
        if (
            isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence < 0
        ):
            raise CampaignValidationError(
                "query cursor sequence must be a non-negative integer"
            )
        if sequence > len(entries):
            raise CampaignTimelineQueryCursorError(
                f"cursor sequence {sequence} exceeds timeline head {len(entries)}"
            )
        return self._cursor_for(entries, campaign_id, sequence)

    def page(
        self,
        campaign_id: str,
        *,
        after: CampaignTimelineQueryCursor | None = None,
        limit: int = 100,
        snapshot_head: CampaignTimelineQueryCursor | None = None,
    ) -> CampaignTimelineQueryPage:
        campaign_id = _require_text(campaign_id, "campaign_id")
        limit = _require_limit(limit)
        entries = self._timeline.list(campaign_id)
        start = self._validate_cursor(
            entries,
            campaign_id,
            after,
            field_name="after",
        )
        if snapshot_head is None:
            head = self._cursor_for(entries, campaign_id, len(entries))
        else:
            head = self._validate_cursor(
                entries,
                campaign_id,
                snapshot_head,
                field_name="snapshot_head",
            )
        if start.sequence > head.sequence:
            raise CampaignTimelineQueryCursorError(
                "after cursor is beyond the requested snapshot head"
            )
        stop = min(start.sequence + limit, head.sequence)
        page_entries = entries[start.sequence:stop]
        next_cursor = self._cursor_for(
            entries,
            campaign_id,
            stop,
        )
        return CampaignTimelineQueryPage(
            campaign_id=campaign_id,
            entries=page_entries,
            start_cursor=start,
            next_cursor=next_cursor,
            head_cursor=head,
            has_more=next_cursor.sequence < head.sequence,
        )

    def _validate_cursor(
        self,
        entries: tuple[CampaignTimelineEntry, ...],
        campaign_id: str,
        cursor: CampaignTimelineQueryCursor | None,
        *,
        field_name: str,
    ) -> CampaignTimelineQueryCursor:
        if cursor is None:
            return self.genesis_cursor(campaign_id)
        if not isinstance(cursor, CampaignTimelineQueryCursor):
            raise TypeError(
                f"{field_name} must be CampaignTimelineQueryCursor or None"
            )
        if cursor.campaign_id != campaign_id:
            raise CampaignTimelineQueryCursorError(
                f"{field_name} cursor campaign_id differs"
            )
        if cursor.sequence > len(entries):
            raise CampaignTimelineQueryCursorError(
                f"{field_name} cursor sequence {cursor.sequence} exceeds "
                f"timeline head {len(entries)}"
            )
        expected = self._cursor_for(entries, campaign_id, cursor.sequence)
        if cursor.entry_hash != expected.entry_hash:
            raise CampaignTimelineQueryCursorError(
                f"{field_name} cursor hash does not match timeline history"
            )
        return cursor

    @staticmethod
    def _cursor_for(
        entries: tuple[CampaignTimelineEntry, ...],
        campaign_id: str,
        sequence: int,
    ) -> CampaignTimelineQueryCursor:
        return CampaignTimelineQueryCursor(
            campaign_id=campaign_id,
            sequence=sequence,
            entry_hash=(entries[sequence - 1].entry_hash if sequence else None),
        )
