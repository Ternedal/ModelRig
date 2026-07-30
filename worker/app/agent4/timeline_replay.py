"""Verified, caller-driven replay and paging for Agent 4 timelines.

The service reads one fully verified A4-06 timeline snapshot and exposes stable
hash-bound cursors. It starts no background work and never mutates the timeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .domain import CampaignValidationError
from .timeline import (
    GENESIS_HASH,
    CampaignTimelineEntry,
    JsonlCampaignTimelineStore,
)


MAX_TIMELINE_PAGE_SIZE = 1_000


class CampaignTimelineReplayError(RuntimeError):
    """Base error for verified timeline replay operations."""


class CampaignTimelineCursorError(CampaignTimelineReplayError):
    """Raised when a replay cursor does not bind to the verified timeline."""


class CampaignTimelineReplayHandlerError(CampaignTimelineReplayError):
    """Raised after a replay handler fails for one verified timeline entry."""

    def __init__(
        self,
        *,
        failed_entry: CampaignTimelineEntry,
        last_successful_cursor: "CampaignTimelineCursor",
        head_cursor: "CampaignTimelineCursor",
        cause: Exception,
    ) -> None:
        super().__init__(
            "timeline replay handler failed at sequence "
            f"{failed_entry.timeline_sequence}: {cause}"
        )
        self.failed_entry = failed_entry
        self.last_successful_cursor = last_successful_cursor
        self.head_cursor = head_cursor
        self.cause = cause


def _require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CampaignValidationError(f"{field_name} must not be empty")
    return value.strip()


def _require_sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise CampaignValidationError(f"{field_name} must be a lowercase SHA-256 digest")
    normalized = value.lower()
    if value != normalized or any(character not in "0123456789abcdef" for character in value):
        raise CampaignValidationError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _require_limit(value: int, field_name: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > MAX_TIMELINE_PAGE_SIZE
    ):
        raise CampaignValidationError(
            f"{field_name} must be an integer between 1 and {MAX_TIMELINE_PAGE_SIZE}"
        )
    return value


@dataclass(frozen=True, slots=True)
class CampaignTimelineCursor:
    """Hash-bound position immediately after one verified timeline entry."""

    campaign_id: str
    timeline_sequence: int
    content_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "campaign_id", _require_text(self.campaign_id, "campaign_id")
        )
        if (
            isinstance(self.timeline_sequence, bool)
            or not isinstance(self.timeline_sequence, int)
            or self.timeline_sequence < 0
        ):
            raise CampaignValidationError(
                "timeline_sequence must be a non-negative integer"
            )
        object.__setattr__(
            self, "content_hash", _require_sha256(self.content_hash, "content_hash")
        )
        if self.timeline_sequence == 0 and self.content_hash != GENESIS_HASH:
            raise CampaignValidationError("genesis cursor must use GENESIS_HASH")
        if self.timeline_sequence > 0 and self.content_hash == GENESIS_HASH:
            raise CampaignValidationError("non-genesis cursor cannot use GENESIS_HASH")


@dataclass(frozen=True, slots=True)
class CampaignTimelinePage:
    """One verified page from a stable timeline snapshot."""

    campaign_id: str
    entries: tuple[CampaignTimelineEntry, ...]
    start_cursor: CampaignTimelineCursor
    next_cursor: CampaignTimelineCursor
    head_cursor: CampaignTimelineCursor
    has_more: bool


@dataclass(frozen=True, slots=True)
class CampaignTimelineReplayResult:
    """Outcome of one explicit replay call against a verified snapshot."""

    replayed_count: int
    last_cursor: CampaignTimelineCursor
    head_cursor: CampaignTimelineCursor
    completed: bool


class CampaignTimelineReplayService:
    """Verified paging and synchronous replay over an A4-06 timeline store."""

    def __init__(self, timeline: JsonlCampaignTimelineStore) -> None:
        if not isinstance(timeline, JsonlCampaignTimelineStore):
            raise TypeError("timeline must be JsonlCampaignTimelineStore")
        self._timeline = timeline

    @staticmethod
    def genesis_cursor(campaign_id: str) -> CampaignTimelineCursor:
        return CampaignTimelineCursor(
            campaign_id=campaign_id,
            timeline_sequence=0,
            content_hash=GENESIS_HASH,
        )

    def cursor_at(
        self, campaign_id: str, timeline_sequence: int
    ) -> CampaignTimelineCursor:
        history = self._timeline.history(campaign_id)
        if (
            isinstance(timeline_sequence, bool)
            or not isinstance(timeline_sequence, int)
            or timeline_sequence < 0
        ):
            raise CampaignValidationError(
                "timeline_sequence must be a non-negative integer"
            )
        if timeline_sequence > len(history):
            raise CampaignTimelineCursorError(
                f"cursor sequence {timeline_sequence} exceeds timeline head {len(history)}"
            )
        return self._cursor_for(history, campaign_id, timeline_sequence)

    def page(
        self,
        campaign_id: str,
        *,
        after: CampaignTimelineCursor | None = None,
        limit: int = 100,
    ) -> CampaignTimelinePage:
        limit = _require_limit(limit, "limit")
        history = self._timeline.history(campaign_id)
        start = self._validate_cursor(history, campaign_id, after)
        head = self._cursor_for(history, campaign_id, len(history))
        entries = history[
            start.timeline_sequence : start.timeline_sequence + limit
        ]
        next_cursor = (
            self._cursor_for(
                history,
                campaign_id,
                entries[-1].timeline_sequence,
            )
            if entries
            else start
        )
        return CampaignTimelinePage(
            campaign_id=campaign_id,
            entries=entries,
            start_cursor=start,
            next_cursor=next_cursor,
            head_cursor=head,
            has_more=next_cursor.timeline_sequence < head.timeline_sequence,
        )

    def replay(
        self,
        campaign_id: str,
        handler: Callable[[CampaignTimelineEntry], None],
        *,
        after: CampaignTimelineCursor | None = None,
        max_entries: int | None = None,
    ) -> CampaignTimelineReplayResult:
        if not callable(handler):
            raise TypeError("replay handler must be callable")
        history = self._timeline.history(campaign_id)
        start = self._validate_cursor(history, campaign_id, after)
        head = self._cursor_for(history, campaign_id, len(history))
        if max_entries is None:
            entries = history[start.timeline_sequence :]
        else:
            maximum = _require_limit(max_entries, "max_entries")
            entries = history[
                start.timeline_sequence : start.timeline_sequence + maximum
            ]

        cursor = start
        replayed = 0
        for entry in entries:
            try:
                handler(entry)
            except Exception as exc:
                raise CampaignTimelineReplayHandlerError(
                    failed_entry=entry,
                    last_successful_cursor=cursor,
                    head_cursor=head,
                    cause=exc,
                ) from exc
            replayed += 1
            cursor = self._cursor_for(
                history,
                campaign_id,
                entry.timeline_sequence,
            )

        return CampaignTimelineReplayResult(
            replayed_count=replayed,
            last_cursor=cursor,
            head_cursor=head,
            completed=cursor.timeline_sequence == head.timeline_sequence,
        )

    def _validate_cursor(
        self,
        history: tuple[CampaignTimelineEntry, ...],
        campaign_id: str,
        cursor: CampaignTimelineCursor | None,
    ) -> CampaignTimelineCursor:
        expected_campaign = _require_text(campaign_id, "campaign_id")
        if cursor is None:
            return self.genesis_cursor(expected_campaign)
        if not isinstance(cursor, CampaignTimelineCursor):
            raise TypeError("after must be CampaignTimelineCursor or None")
        if cursor.campaign_id != expected_campaign:
            raise CampaignTimelineCursorError("cursor campaign_id differs")
        if cursor.timeline_sequence > len(history):
            raise CampaignTimelineCursorError(
                f"cursor sequence {cursor.timeline_sequence} exceeds timeline head "
                f"{len(history)}"
            )
        expected = self._cursor_for(
            history,
            expected_campaign,
            cursor.timeline_sequence,
        )
        if cursor.content_hash != expected.content_hash:
            raise CampaignTimelineCursorError("cursor hash does not match timeline history")
        return cursor

    @staticmethod
    def _cursor_for(
        history: tuple[CampaignTimelineEntry, ...],
        campaign_id: str,
        timeline_sequence: int,
    ) -> CampaignTimelineCursor:
        if timeline_sequence == 0:
            content_hash = GENESIS_HASH
        else:
            content_hash = history[timeline_sequence - 1].content_hash
        return CampaignTimelineCursor(
            campaign_id=campaign_id,
            timeline_sequence=timeline_sequence,
            content_hash=content_hash,
        )
