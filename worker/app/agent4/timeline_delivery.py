"""Durable caller-driven delivery cursors for the A4-06 campaign timeline."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping

from .contracts import CampaignTimelineCursorStore, CampaignTimelineStore
from .domain import (
    CampaignValidationError,
    JsonValue,
    _format_datetime,
    _parse_datetime,
    _require_aware,
    _require_text,
)
from .timeline import CampaignTimelineEntry

_CURSOR_SCHEMA = "modelrig-agent4/campaign-timeline-cursor/v1"


class TimelineCursorStoreError(RuntimeError):
    """Raised when a durable delivery cursor cannot be stored or validated."""


class TimelineCursorConflictError(TimelineCursorStoreError):
    """Raised when compare-and-swap cursor advancement fails."""


class TimelineDeliveryIntegrityError(RuntimeError):
    """Raised when a cursor no longer binds the verified timeline it references."""


def _canonical_json(value: Mapping[str, JsonValue]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _require_hash(value: str, field_name: str) -> str:
    normalized = _require_text(value, field_name)
    if normalized.startswith("sha256:"):
        normalized = normalized[7:]
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise CampaignValidationError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    return normalized


@dataclass(frozen=True, slots=True)
class CampaignTimelineCursor:
    """Immutable acknowledgement of one delivered timeline entry."""

    consumer_id: str
    campaign_id: str
    sequence: int
    entry_hash: str
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "consumer_id", _require_text(self.consumer_id, "consumer_id")
        )
        object.__setattr__(
            self, "campaign_id", _require_text(self.campaign_id, "campaign_id")
        )
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 1
        ):
            raise CampaignValidationError(
                "cursor sequence must be an integer of at least 1"
            )
        object.__setattr__(
            self, "entry_hash", _require_hash(self.entry_hash, "entry_hash")
        )
        object.__setattr__(
            self, "updated_at", _require_aware(self.updated_at, "updated_at")
        )

    def content_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": _CURSOR_SCHEMA,
            "consumer_id": self.consumer_id,
            "campaign_id": self.campaign_id,
            "sequence": self.sequence,
            "entry_hash": f"sha256:{self.entry_hash}",
            "updated_at": _format_datetime(self.updated_at),
        }

    @property
    def checksum(self) -> str:
        return hashlib.sha256(_canonical_json(self.content_dict())).hexdigest()

    def to_dict(self) -> dict[str, JsonValue]:
        value = self.content_dict()
        value["checksum"] = f"sha256:{self.checksum}"
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignTimelineCursor":
        if value.get("schema") != _CURSOR_SCHEMA:
            raise CampaignValidationError(
                "campaign timeline cursor schema is not supported"
            )
        cursor = cls(
            consumer_id=str(value["consumer_id"]),
            campaign_id=str(value["campaign_id"]),
            sequence=int(value["sequence"]),
            entry_hash=str(value["entry_hash"]),
            updated_at=_parse_datetime(str(value["updated_at"]), "updated_at"),
        )
        actual = value.get("checksum")
        expected = f"sha256:{cursor.checksum}"
        if not isinstance(actual, str) or not hmac.compare_digest(actual, expected):
            raise CampaignValidationError(
                "campaign timeline cursor checksum does not match content"
            )
        return cursor


class JsonCampaignTimelineCursorStore:
    """Atomic process-local compare-and-swap cursor persistence."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._lock = RLock()

    @property
    def root(self) -> Path:
        return self._root

    def get(
        self,
        consumer_id: str,
        campaign_id: str,
    ) -> CampaignTimelineCursor | None:
        with self._lock:
            path = self._path_for(consumer_id, campaign_id)
            if not path.exists():
                return None
            return self._read(
                path,
                expected_consumer_id=consumer_id,
                expected_campaign_id=campaign_id,
            )

    def save(
        self,
        cursor: CampaignTimelineCursor,
        *,
        expected_sequence: int | None,
    ) -> None:
        if expected_sequence is not None and (
            isinstance(expected_sequence, bool)
            or not isinstance(expected_sequence, int)
            or expected_sequence < 1
        ):
            raise CampaignValidationError(
                "expected_sequence must be an integer of at least 1 or none"
            )
        with self._lock:
            self._root.mkdir(parents=True, exist_ok=True)
            destination = self._path_for(cursor.consumer_id, cursor.campaign_id)
            current = self._read(destination) if destination.exists() else None
            if expected_sequence is None:
                if current is not None:
                    raise TimelineCursorConflictError(
                        "cursor already exists; expected an initial delivery"
                    )
                if cursor.sequence != 1:
                    raise TimelineCursorConflictError(
                        "initial cursor must acknowledge sequence 1"
                    )
            else:
                if current is None or current.sequence != expected_sequence:
                    actual = current.sequence if current is not None else None
                    raise TimelineCursorConflictError(
                        f"cursor expected sequence {expected_sequence}, got {actual}"
                    )
                if (
                    current.consumer_id != cursor.consumer_id
                    or current.campaign_id != cursor.campaign_id
                ):
                    raise TimelineCursorConflictError(
                        "cursor identity changed during advancement"
                    )
                if cursor.sequence != expected_sequence + 1:
                    raise TimelineCursorConflictError(
                        "cursor advancement must move forward exactly one sequence"
                    )
            payload = json.dumps(
                cursor.to_dict(),
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    newline="\n",
                    prefix=f".{destination.name}.",
                    suffix=".tmp",
                    dir=self._root,
                    delete=False,
                ) as handle:
                    temporary_path = Path(handle.name)
                    handle.write(payload)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_path, destination)
                self._fsync_directory()
            except OSError as exc:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
                raise TimelineCursorStoreError(
                    f"unable to persist timeline cursor for {cursor.consumer_id!r}"
                ) from exc

    def _read(
        self,
        path: Path,
        *,
        expected_consumer_id: str | None = None,
        expected_campaign_id: str | None = None,
    ) -> CampaignTimelineCursor:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TimelineCursorStoreError(
                f"unable to read timeline cursor {path.name!r}"
            ) from exc
        if not isinstance(raw, Mapping):
            raise TimelineCursorStoreError(
                f"timeline cursor {path.name!r} must contain an object"
            )
        try:
            cursor = CampaignTimelineCursor.from_dict(raw)
        except (CampaignValidationError, KeyError, TypeError, ValueError) as exc:
            raise TimelineCursorStoreError(
                f"timeline cursor {path.name!r} failed validation"
            ) from exc
        if (
            expected_consumer_id is not None
            and cursor.consumer_id
            != _require_text(expected_consumer_id, "consumer_id")
        ):
            raise TimelineCursorStoreError("timeline cursor consumer identity mismatch")
        if (
            expected_campaign_id is not None
            and cursor.campaign_id
            != _require_text(expected_campaign_id, "campaign_id")
        ):
            raise TimelineCursorStoreError("timeline cursor campaign identity mismatch")
        if path.name != self._path_for(cursor.consumer_id, cursor.campaign_id).name:
            raise TimelineCursorStoreError(
                f"timeline cursor {path.name!r} has an invalid filename binding"
            )
        return cursor

    def _path_for(self, consumer_id: str, campaign_id: str) -> Path:
        consumer_id = _require_text(consumer_id, "consumer_id")
        campaign_id = _require_text(campaign_id, "campaign_id")
        digest = hashlib.sha256(
            f"{consumer_id}\0{campaign_id}".encode("utf-8")
        ).hexdigest()
        return self._root / f"{digest}.timeline-cursor.json"

    def _fsync_directory(self) -> None:
        if os.name == "nt":
            return
        try:
            descriptor = os.open(self._root, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


@dataclass(frozen=True, slots=True)
class CampaignTimelineDeliveryResult:
    consumer_id: str
    campaign_id: str
    delivered: bool
    entry: CampaignTimelineEntry | None
    cursor: CampaignTimelineCursor | None
    remaining: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "consumer_id", _require_text(self.consumer_id, "consumer_id")
        )
        object.__setattr__(
            self, "campaign_id", _require_text(self.campaign_id, "campaign_id")
        )
        if (
            isinstance(self.remaining, bool)
            or not isinstance(self.remaining, int)
            or self.remaining < 0
        ):
            raise CampaignValidationError("remaining must be a non-negative integer")
        if self.delivered != (self.entry is not None):
            raise CampaignValidationError(
                "delivery result must bind delivered status to an entry"
            )


class CampaignTimelineDeliveryService:
    """Deliver verified timeline entries with at-least-once cursor semantics."""

    def __init__(
        self,
        *,
        timeline: CampaignTimelineStore,
        cursors: CampaignTimelineCursorStore,
    ) -> None:
        if not isinstance(timeline, CampaignTimelineStore):
            raise TypeError("timeline must implement CampaignTimelineStore")
        if not isinstance(cursors, CampaignTimelineCursorStore):
            raise TypeError("cursors must implement CampaignTimelineCursorStore")
        self._timeline = timeline
        self._cursors = cursors
        self._lock = RLock()

    def pending_count(self, consumer_id: str, campaign_id: str) -> int:
        consumer_id = _require_text(consumer_id, "consumer_id")
        campaign_id = _require_text(campaign_id, "campaign_id")
        with self._lock:
            entries, cursor = self._snapshot(consumer_id, campaign_id)
            return len(entries) - (cursor.sequence if cursor is not None else 0)

    def deliver_next(
        self,
        consumer_id: str,
        campaign_id: str,
        handler: Callable[[CampaignTimelineEntry], None],
        *,
        acknowledged_at: datetime,
    ) -> CampaignTimelineDeliveryResult:
        if not callable(handler):
            raise TypeError("timeline delivery handler must be callable")
        consumer_id = _require_text(consumer_id, "consumer_id")
        campaign_id = _require_text(campaign_id, "campaign_id")
        acknowledged_at = _require_aware(acknowledged_at, "acknowledged_at")
        with self._lock:
            entries, current = self._snapshot(consumer_id, campaign_id)
            delivered_count = current.sequence if current is not None else 0
            if delivered_count == len(entries):
                return CampaignTimelineDeliveryResult(
                    consumer_id=consumer_id,
                    campaign_id=campaign_id,
                    delivered=False,
                    entry=None,
                    cursor=current,
                    remaining=0,
                )
            entry = entries[delivered_count]
            handler(entry)
            cursor = CampaignTimelineCursor(
                consumer_id=consumer_id,
                campaign_id=campaign_id,
                sequence=entry.event.sequence,
                entry_hash=entry.entry_hash,
                updated_at=acknowledged_at,
            )
            self._cursors.save(
                cursor,
                expected_sequence=(current.sequence if current is not None else None),
            )
            return CampaignTimelineDeliveryResult(
                consumer_id=consumer_id,
                campaign_id=campaign_id,
                delivered=True,
                entry=entry,
                cursor=cursor,
                remaining=len(entries) - cursor.sequence,
            )

    def _snapshot(
        self,
        consumer_id: str,
        campaign_id: str,
    ) -> tuple[tuple[CampaignTimelineEntry, ...], CampaignTimelineCursor | None]:
        entries = self._timeline.list(campaign_id)
        cursor = self._cursors.get(consumer_id, campaign_id)
        if cursor is None:
            return entries, None
        if cursor.sequence > len(entries):
            raise TimelineDeliveryIntegrityError(
                "timeline cursor points beyond the verified timeline head"
            )
        anchor = entries[cursor.sequence - 1]
        if not hmac.compare_digest(cursor.entry_hash, anchor.entry_hash):
            raise TimelineDeliveryIntegrityError(
                "timeline cursor hash does not match its verified entry"
            )
        return entries, cursor
