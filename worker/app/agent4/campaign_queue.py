"""Deterministic in-memory queue for Agent 4 campaigns."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock

from .domain import CampaignSpec, CampaignValidationError


class DuplicateCampaignError(ValueError):
    """Raised when a campaign id is enqueued more than once."""


@dataclass(frozen=True, slots=True)
class QueueEntry:
    spec: CampaignSpec
    insertion_sequence: int


class CampaignQueue:
    """Thread-safe deterministic priority queue.

    Only campaigns whose ``ready_at`` timestamp is less than or equal to the
    supplied clock value are eligible. Eligible campaigns are ordered by
    higher priority, earlier ready timestamp, insertion order and campaign id.
    """

    def __init__(self) -> None:
        self._entries: dict[str, QueueEntry] = {}
        self._sequence = 0
        self._lock = RLock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __contains__(self, campaign_id: object) -> bool:
        if not isinstance(campaign_id, str):
            return False
        with self._lock:
            return campaign_id in self._entries

    def enqueue(self, spec: CampaignSpec) -> None:
        with self._lock:
            if spec.campaign_id in self._entries:
                raise DuplicateCampaignError(
                    f"campaign {spec.campaign_id!r} is already queued"
                )
            self._sequence += 1
            self._entries[spec.campaign_id] = QueueEntry(
                spec=spec,
                insertion_sequence=self._sequence,
            )

    def remove(self, campaign_id: str) -> CampaignSpec | None:
        with self._lock:
            entry = self._entries.pop(campaign_id, None)
            return entry.spec if entry is not None else None

    def get(self, campaign_id: str) -> CampaignSpec | None:
        with self._lock:
            entry = self._entries.get(campaign_id)
            return entry.spec if entry is not None else None

    def snapshot(self) -> tuple[CampaignSpec, ...]:
        with self._lock:
            return tuple(
                entry.spec
                for entry in sorted(self._entries.values(), key=self._sort_key)
            )

    def peek_ready(self, now: datetime) -> CampaignSpec | None:
        with self._lock:
            entry = self._select_ready(now)
            return entry.spec if entry is not None else None

    def pop_ready(self, now: datetime) -> CampaignSpec | None:
        with self._lock:
            entry = self._select_ready(now)
            if entry is None:
                return None
            del self._entries[entry.spec.campaign_id]
            return entry.spec

    def _select_ready(self, now: datetime) -> QueueEntry | None:
        now = self._normalize_now(now)
        ready = [
            entry for entry in self._entries.values() if entry.spec.ready_at <= now
        ]
        return min(ready, key=self._sort_key) if ready else None

    @staticmethod
    def _sort_key(entry: QueueEntry) -> tuple[int, datetime, int, str]:
        return (
            -int(entry.spec.priority),
            entry.spec.ready_at,
            entry.insertion_sequence,
            entry.spec.campaign_id,
        )

    @staticmethod
    def _normalize_now(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise CampaignValidationError("scheduler clock must be timezone-aware")
        return value.astimezone(timezone.utc)
