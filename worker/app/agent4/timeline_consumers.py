"""Durable, caller-driven consumer offsets for Agent 4 timeline replay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping

from .domain import CampaignValidationError, JsonValue
from .timeline import CampaignTimelineEntry
from .timeline_replay import (
    CampaignTimelineCursor,
    CampaignTimelineReplayService,
)


CONSUMER_OFFSET_SCHEMA = "modelrig-agent4/timeline-consumer-offset/v1"


class CampaignTimelineConsumerError(RuntimeError):
    """Base error for Agent 4 durable consumer operations."""


class CampaignTimelineConsumerConflictError(CampaignTimelineConsumerError):
    """Raised when an offset would regress or contradict durable progress."""


class CampaignTimelineConsumerStoreError(CampaignTimelineConsumerError):
    """Raised when durable offset bytes cannot be read or replaced safely."""


class CampaignTimelineConsumerHandlerError(CampaignTimelineConsumerError):
    """Raised when a handler rejects one entry before offset advancement."""

    def __init__(
        self,
        *,
        failed_entry: CampaignTimelineEntry,
        durable_cursor: CampaignTimelineCursor,
        head_cursor: CampaignTimelineCursor,
        cause: Exception,
    ) -> None:
        super().__init__(
            "timeline consumer handler failed at sequence "
            f"{failed_entry.timeline_sequence}: {cause}"
        )
        self.failed_entry = failed_entry
        self.durable_cursor = durable_cursor
        self.head_cursor = head_cursor
        self.cause = cause


class CampaignTimelineConsumerCommitError(CampaignTimelineConsumerError):
    """Raised after handler acceptance when the new offset was not durable."""

    def __init__(
        self,
        *,
        accepted_entry: CampaignTimelineEntry,
        durable_cursor: CampaignTimelineCursor,
        attempted_cursor: CampaignTimelineCursor,
        head_cursor: CampaignTimelineCursor,
        cause: Exception,
    ) -> None:
        super().__init__(
            "timeline consumer offset commit failed after accepting sequence "
            f"{accepted_entry.timeline_sequence}: {cause}"
        )
        self.accepted_entry = accepted_entry
        self.durable_cursor = durable_cursor
        self.attempted_cursor = attempted_cursor
        self.head_cursor = head_cursor
        self.cause = cause


def _require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CampaignValidationError(f"{field_name} must not be empty")
    return value.strip()


def _require_aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CampaignValidationError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _format_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise CampaignTimelineConsumerStoreError(f"{field_name} must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return _require_aware(parsed, field_name)
    except (TypeError, ValueError, CampaignValidationError) as exc:
        raise CampaignTimelineConsumerStoreError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class CampaignTimelineConsumerOffset:
    consumer_id: str
    campaign_id: str
    cursor: CampaignTimelineCursor
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "consumer_id", _require_text(self.consumer_id, "consumer_id"))
        object.__setattr__(self, "campaign_id", _require_text(self.campaign_id, "campaign_id"))
        if not isinstance(self.cursor, CampaignTimelineCursor):
            raise CampaignValidationError("cursor must be CampaignTimelineCursor")
        if self.cursor.campaign_id != self.campaign_id:
            raise CampaignValidationError("offset and cursor campaign_id differ")
        object.__setattr__(self, "updated_at", _require_aware(self.updated_at, "updated_at"))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": CONSUMER_OFFSET_SCHEMA,
            "consumer_id": self.consumer_id,
            "campaign_id": self.campaign_id,
            "cursor": {
                "campaign_id": self.cursor.campaign_id,
                "timeline_sequence": self.cursor.timeline_sequence,
                "content_hash": self.cursor.content_hash,
            },
            "updated_at": _format_datetime(self.updated_at),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignTimelineConsumerOffset":
        expected = {"schema", "consumer_id", "campaign_id", "cursor", "updated_at"}
        if set(value) != expected or value.get("schema") != CONSUMER_OFFSET_SCHEMA:
            raise CampaignTimelineConsumerStoreError("consumer offset fields or schema differ")
        cursor = value.get("cursor")
        if not isinstance(cursor, dict) or set(cursor) != {
            "campaign_id",
            "timeline_sequence",
            "content_hash",
        }:
            raise CampaignTimelineConsumerStoreError("consumer cursor fields differ")
        try:
            return cls(
                consumer_id=value["consumer_id"],
                campaign_id=value["campaign_id"],
                cursor=CampaignTimelineCursor(
                    campaign_id=cursor["campaign_id"],
                    timeline_sequence=cursor["timeline_sequence"],
                    content_hash=cursor["content_hash"],
                ),
                updated_at=_parse_datetime(value["updated_at"], "updated_at"),
            )
        except (CampaignValidationError, TypeError) as exc:
            raise CampaignTimelineConsumerStoreError(str(exc)) from exc


class JsonCampaignTimelineConsumerStore:
    """Atomic per-consumer timeline offsets with monotonic progress checks."""

    def __init__(self, directory: Path | str) -> None:
        self._directory = Path(directory)
        self._lock = RLock()

    @staticmethod
    def _key(campaign_id: str, consumer_id: str) -> str:
        campaign = _require_text(campaign_id, "campaign_id")
        consumer = _require_text(consumer_id, "consumer_id")
        return hashlib.sha256(f"{campaign}\0{consumer}".encode("utf-8")).hexdigest()

    def _path(self, campaign_id: str, consumer_id: str) -> Path:
        return self._directory / f"{self._key(campaign_id, consumer_id)}.json"

    def get(
        self, campaign_id: str, consumer_id: str
    ) -> CampaignTimelineConsumerOffset | None:
        with self._lock:
            return self._read_locked(campaign_id, consumer_id)

    def save(self, offset: CampaignTimelineConsumerOffset) -> None:
        if not isinstance(offset, CampaignTimelineConsumerOffset):
            raise TypeError("offset must be CampaignTimelineConsumerOffset")
        with self._lock:
            current = self._read_locked(offset.campaign_id, offset.consumer_id)
            if current is not None:
                if offset.cursor.timeline_sequence < current.cursor.timeline_sequence:
                    raise CampaignTimelineConsumerConflictError("consumer offset cannot regress")
                if (
                    offset.cursor.timeline_sequence == current.cursor.timeline_sequence
                    and offset.cursor.content_hash != current.cursor.content_hash
                ):
                    raise CampaignTimelineConsumerConflictError(
                        "consumer offset hash contradicts durable progress"
                    )
                if offset.cursor == current.cursor:
                    return
            self._write_locked(offset)

    def delete(self, campaign_id: str, consumer_id: str) -> bool:
        with self._lock:
            path = self._path(campaign_id, consumer_id)
            try:
                path.unlink()
            except FileNotFoundError:
                return False
            except OSError as exc:
                raise CampaignTimelineConsumerStoreError(
                    f"delete consumer offset {path.name}: {exc}"
                ) from exc
            return True

    def _read_locked(
        self, campaign_id: str, consumer_id: str
    ) -> CampaignTimelineConsumerOffset | None:
        path = self._path(campaign_id, consumer_id)
        if not path.exists():
            return None
        try:
            decoded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CampaignTimelineConsumerStoreError(
                f"read consumer offset {path.name}: {exc}"
            ) from exc
        if not isinstance(decoded, dict):
            raise CampaignTimelineConsumerStoreError("consumer offset must be an object")
        offset = CampaignTimelineConsumerOffset.from_dict(decoded)
        if offset.campaign_id != campaign_id or offset.consumer_id != consumer_id:
            raise CampaignTimelineConsumerStoreError(
                "consumer offset identity differs from filename binding"
            )
        return offset

    def _write_locked(self, offset: CampaignTimelineConsumerOffset) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self._path(offset.campaign_id, offset.consumer_id)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        data = (
            json.dumps(
                offset.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        try:
            descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                view = memoryview(data)
                written = 0
                while written < len(view):
                    count = os.write(descriptor, view[written:])
                    if count <= 0:
                        raise OSError("offset write returned zero bytes")
                    written += count
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(temporary, path)
        except OSError as exc:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise CampaignTimelineConsumerStoreError(
                f"write consumer offset {path.name}: {exc}"
            ) from exc


@dataclass(frozen=True, slots=True)
class CampaignTimelineConsumerBatchResult:
    consumer_id: str
    campaign_id: str
    accepted_count: int
    durable_cursor: CampaignTimelineCursor
    head_cursor: CampaignTimelineCursor
    completed: bool


class CampaignTimelineConsumerService:
    """Explicit at-least-once consumption with durable progress after each entry."""

    def __init__(
        self,
        replay: CampaignTimelineReplayService,
        offsets: JsonCampaignTimelineConsumerStore,
    ) -> None:
        if not isinstance(replay, CampaignTimelineReplayService):
            raise TypeError("replay must be CampaignTimelineReplayService")
        if not isinstance(offsets, JsonCampaignTimelineConsumerStore):
            raise TypeError("offsets must be JsonCampaignTimelineConsumerStore")
        self._replay = replay
        self._offsets = offsets

    def consume_batch(
        self,
        campaign_id: str,
        consumer_id: str,
        handler: Callable[[CampaignTimelineEntry], None],
        *,
        updated_at: datetime,
        max_entries: int = 100,
    ) -> CampaignTimelineConsumerBatchResult:
        if not callable(handler):
            raise TypeError("consumer handler must be callable")
        consumer = _require_text(consumer_id, "consumer_id")
        timestamp = _require_aware(updated_at, "updated_at")
        saved = self._offsets.get(campaign_id, consumer)
        durable = (
            saved.cursor
            if saved is not None
            else self._replay.genesis_cursor(campaign_id)
        )
        page = self._replay.page(campaign_id, after=durable, limit=max_entries)
        accepted = 0
        for entry in page.entries:
            try:
                handler(entry)
            except Exception as exc:
                raise CampaignTimelineConsumerHandlerError(
                    failed_entry=entry,
                    durable_cursor=durable,
                    head_cursor=page.head_cursor,
                    cause=exc,
                ) from exc
            attempted = CampaignTimelineCursor(
                campaign_id=campaign_id,
                timeline_sequence=entry.timeline_sequence,
                content_hash=entry.content_hash,
            )
            try:
                self._offsets.save(
                    CampaignTimelineConsumerOffset(
                        consumer_id=consumer,
                        campaign_id=campaign_id,
                        cursor=attempted,
                        updated_at=timestamp,
                    )
                )
            except Exception as exc:
                raise CampaignTimelineConsumerCommitError(
                    accepted_entry=entry,
                    durable_cursor=durable,
                    attempted_cursor=attempted,
                    head_cursor=page.head_cursor,
                    cause=exc,
                ) from exc
            durable = attempted
            accepted += 1

        return CampaignTimelineConsumerBatchResult(
            consumer_id=consumer,
            campaign_id=campaign_id,
            accepted_count=accepted,
            durable_cursor=durable,
            head_cursor=page.head_cursor,
            completed=durable.timeline_sequence == page.head_cursor.timeline_sequence,
        )
