"""Durable append-only timeline and evidence contracts for Agent 4.

The store is caller-driven and process-local. It creates no files until the first
explicit append, performs no background work, and never mutates an existing
line. Each campaign owns one JSONL file whose entries form a SHA-256 hash chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import math
import os
from pathlib import Path
from threading import RLock
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .domain import CampaignEvent, CampaignEventKind, CampaignValidationError, JsonValue


TIMELINE_SCHEMA = "modelrig-agent4/timeline-entry/v1"
GENESIS_HASH = "0" * 64


class CampaignTimelineError(RuntimeError):
    """Base error for durable Agent 4 timeline operations."""


class CampaignTimelineConflictError(CampaignTimelineError):
    """Raised when an append contradicts existing timeline identity or order."""


class CampaignTimelineIntegrityError(CampaignTimelineError):
    """Raised when persisted timeline bytes fail validation."""


class CampaignTimelineEntryType(StrEnum):
    EVENT = "event"
    EVIDENCE = "evidence"


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
        raise CampaignTimelineIntegrityError(f"{field_name} must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CampaignTimelineIntegrityError(f"{field_name} is not a valid datetime") from exc
    try:
        return _require_aware(parsed, field_name)
    except CampaignValidationError as exc:
        raise CampaignTimelineIntegrityError(str(exc)) from exc


def _freeze_json(value: Any, path: str = "value") -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CampaignValidationError(f"{path} must contain finite numbers")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CampaignValidationError(f"{path} keys must be strings")
            frozen[key] = _freeze_json(item, f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, f"{path}[]") for item in value)
    raise CampaignValidationError(
        f"{path} contains unsupported JSON value {type(value).__name__}"
    )


def _thaw_json(value: Any) -> JsonValue:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CampaignTimelineIntegrityError("timeline value is not canonical JSON") from exc
    return encoded.encode("utf-8")


def _require_sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise CampaignValidationError(f"{field_name} must be a lowercase SHA-256 digest")
    normalized = value.lower()
    if value != normalized or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise CampaignValidationError(f"{field_name} must be a lowercase SHA-256 digest")
    return normalized


@dataclass(frozen=True, slots=True)
class CampaignEvidenceArtifact:
    """Immutable reference to evidence bytes stored outside the timeline."""

    uri: str
    sha256: str
    size_bytes: int
    media_type: str = "application/octet-stream"

    def __post_init__(self) -> None:
        object.__setattr__(self, "uri", _require_text(self.uri, "uri"))
        object.__setattr__(self, "sha256", _require_sha256(self.sha256, "sha256"))
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 0
        ):
            raise CampaignValidationError("size_bytes must be a non-negative integer")
        object.__setattr__(
            self, "media_type", _require_text(self.media_type, "media_type")
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "uri": self.uri,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignEvidenceArtifact":
        expected = {"uri", "sha256", "size_bytes", "media_type"}
        if set(value) != expected:
            raise CampaignTimelineIntegrityError("evidence artifact fields differ")
        try:
            return cls(
                uri=value["uri"],
                sha256=value["sha256"],
                size_bytes=value["size_bytes"],
                media_type=value["media_type"],
            )
        except (CampaignValidationError, TypeError) as exc:
            raise CampaignTimelineIntegrityError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class CampaignEvidence:
    """JSON-safe evidence metadata plus immutable external artifact references."""

    evidence_id: str
    campaign_id: str
    category: str
    source: str
    recorded_at: datetime
    payload: Mapping[str, JsonValue] = field(default_factory=dict)
    artifacts: tuple[CampaignEvidenceArtifact, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_id", _require_text(self.evidence_id, "evidence_id")
        )
        object.__setattr__(
            self, "campaign_id", _require_text(self.campaign_id, "campaign_id")
        )
        object.__setattr__(self, "category", _require_text(self.category, "category"))
        object.__setattr__(self, "source", _require_text(self.source, "source"))
        object.__setattr__(
            self, "recorded_at", _require_aware(self.recorded_at, "recorded_at")
        )
        object.__setattr__(self, "payload", _freeze_json(self.payload, "payload"))
        artifacts = tuple(self.artifacts)
        if any(not isinstance(item, CampaignEvidenceArtifact) for item in artifacts):
            raise CampaignValidationError(
                "artifacts must contain CampaignEvidenceArtifact values"
            )
        uris = [item.uri for item in artifacts]
        if len(uris) != len(set(uris)):
            raise CampaignValidationError("artifacts contain duplicate uri values")
        object.__setattr__(self, "artifacts", artifacts)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "evidence_id": self.evidence_id,
            "campaign_id": self.campaign_id,
            "category": self.category,
            "source": self.source,
            "recorded_at": _format_datetime(self.recorded_at),
            "payload": _thaw_json(self.payload),
            "artifacts": [item.to_dict() for item in self.artifacts],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignEvidence":
        expected = {
            "evidence_id",
            "campaign_id",
            "category",
            "source",
            "recorded_at",
            "payload",
            "artifacts",
        }
        if set(value) != expected:
            raise CampaignTimelineIntegrityError("evidence fields differ")
        artifacts = value["artifacts"]
        if not isinstance(artifacts, list):
            raise CampaignTimelineIntegrityError("artifacts must be an array")
        payload = value["payload"]
        if not isinstance(payload, dict):
            raise CampaignTimelineIntegrityError("payload must be an object")
        try:
            return cls(
                evidence_id=value["evidence_id"],
                campaign_id=value["campaign_id"],
                category=value["category"],
                source=value["source"],
                recorded_at=_parse_datetime(value["recorded_at"], "recorded_at"),
                payload=payload,
                artifacts=tuple(CampaignEvidenceArtifact.from_dict(item) for item in artifacts),
            )
        except (CampaignValidationError, TypeError) as exc:
            raise CampaignTimelineIntegrityError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class CampaignTimelineEntry:
    campaign_id: str
    timeline_sequence: int
    entry_type: CampaignTimelineEntryType
    recorded_at: datetime
    item: CampaignEvent | CampaignEvidence
    previous_hash: str
    content_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "campaign_id", _require_text(self.campaign_id, "campaign_id")
        )
        if (
            isinstance(self.timeline_sequence, bool)
            or not isinstance(self.timeline_sequence, int)
            or self.timeline_sequence < 1
        ):
            raise CampaignValidationError(
                "timeline_sequence must be an integer of at least 1"
            )
        try:
            entry_type = CampaignTimelineEntryType(self.entry_type)
        except ValueError as exc:
            raise CampaignValidationError("entry_type is not supported") from exc
        object.__setattr__(self, "entry_type", entry_type)
        object.__setattr__(
            self, "recorded_at", _require_aware(self.recorded_at, "recorded_at")
        )
        if entry_type is CampaignTimelineEntryType.EVENT:
            if not isinstance(self.item, CampaignEvent):
                raise CampaignValidationError("event entry must contain CampaignEvent")
            item_time = self.item.occurred_at
        else:
            if not isinstance(self.item, CampaignEvidence):
                raise CampaignValidationError(
                    "evidence entry must contain CampaignEvidence"
                )
            item_time = self.item.recorded_at
        if self.item.campaign_id != self.campaign_id:
            raise CampaignValidationError("timeline and item campaign_id differ")
        if item_time != self.recorded_at:
            raise CampaignValidationError("timeline recorded_at must match item timestamp")
        object.__setattr__(
            self, "previous_hash", _require_sha256(self.previous_hash, "previous_hash")
        )
        object.__setattr__(
            self, "content_hash", _require_sha256(self.content_hash, "content_hash")
        )

    @property
    def item_id(self) -> str:
        if isinstance(self.item, CampaignEvent):
            return self.item.event_id
        return self.item.evidence_id

    def _unsigned_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": TIMELINE_SCHEMA,
            "campaign_id": self.campaign_id,
            "timeline_sequence": self.timeline_sequence,
            "entry_type": self.entry_type.value,
            "recorded_at": _format_datetime(self.recorded_at),
            "item": self.item.to_dict(),
            "previous_hash": self.previous_hash,
        }

    def expected_content_hash(self) -> str:
        return hashlib.sha256(_canonical_bytes(self._unsigned_dict())).hexdigest()

    def to_dict(self) -> dict[str, JsonValue]:
        value = self._unsigned_dict()
        value["content_hash"] = self.content_hash
        return value

    def canonical_line(self) -> bytes:
        return _canonical_bytes(self.to_dict()) + b"\n"

    @classmethod
    def create(
        cls,
        *,
        timeline_sequence: int,
        item: CampaignEvent | CampaignEvidence,
        previous_hash: str,
    ) -> "CampaignTimelineEntry":
        entry_type = (
            CampaignTimelineEntryType.EVENT
            if isinstance(item, CampaignEvent)
            else CampaignTimelineEntryType.EVIDENCE
        )
        recorded_at = (
            item.occurred_at if isinstance(item, CampaignEvent) else item.recorded_at
        )
        unsigned = {
            "schema": TIMELINE_SCHEMA,
            "campaign_id": item.campaign_id,
            "timeline_sequence": timeline_sequence,
            "entry_type": entry_type.value,
            "recorded_at": _format_datetime(recorded_at),
            "item": item.to_dict(),
            "previous_hash": previous_hash,
        }
        content_hash = hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()
        return cls(
            campaign_id=item.campaign_id,
            timeline_sequence=timeline_sequence,
            entry_type=entry_type,
            recorded_at=recorded_at,
            item=item,
            previous_hash=previous_hash,
            content_hash=content_hash,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignTimelineEntry":
        expected = {
            "schema",
            "campaign_id",
            "timeline_sequence",
            "entry_type",
            "recorded_at",
            "item",
            "previous_hash",
            "content_hash",
        }
        if set(value) != expected:
            raise CampaignTimelineIntegrityError("timeline entry fields differ")
        if value["schema"] != TIMELINE_SCHEMA:
            raise CampaignTimelineIntegrityError("unsupported timeline schema")
        item_value = value["item"]
        if not isinstance(item_value, dict):
            raise CampaignTimelineIntegrityError("timeline item must be an object")
        try:
            entry_type = CampaignTimelineEntryType(value["entry_type"])
            item: CampaignEvent | CampaignEvidence
            if entry_type is CampaignTimelineEntryType.EVENT:
                item = CampaignEvent.from_dict(item_value)
            else:
                item = CampaignEvidence.from_dict(item_value)
            entry = cls(
                campaign_id=value["campaign_id"],
                timeline_sequence=value["timeline_sequence"],
                entry_type=entry_type,
                recorded_at=_parse_datetime(value["recorded_at"], "recorded_at"),
                item=item,
                previous_hash=value["previous_hash"],
                content_hash=value["content_hash"],
            )
        except (CampaignValidationError, TypeError, ValueError) as exc:
            raise CampaignTimelineIntegrityError(str(exc)) from exc
        if entry.content_hash != entry.expected_content_hash():
            raise CampaignTimelineIntegrityError("timeline content hash mismatch")
        return entry


class JsonlCampaignTimelineStore:
    """Per-campaign append-only JSONL timeline with hash-chain verification."""

    def __init__(self, directory: Path | str) -> None:
        self._directory = Path(directory)
        self._lock = RLock()

    @staticmethod
    def _campaign_key(campaign_id: str) -> str:
        normalized = _require_text(campaign_id, "campaign_id")
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _path(self, campaign_id: str) -> Path:
        return self._directory / f"{self._campaign_key(campaign_id)}.jsonl"

    def history(self, campaign_id: str) -> tuple[CampaignTimelineEntry, ...]:
        with self._lock:
            return self._read_verified(campaign_id)

    def events(self, campaign_id: str) -> tuple[CampaignEvent, ...]:
        return tuple(
            entry.item
            for entry in self.history(campaign_id)
            if entry.entry_type is CampaignTimelineEntryType.EVENT
            and isinstance(entry.item, CampaignEvent)
        )

    def evidence(self, campaign_id: str) -> tuple[CampaignEvidence, ...]:
        return tuple(
            entry.item
            for entry in self.history(campaign_id)
            if entry.entry_type is CampaignTimelineEntryType.EVIDENCE
            and isinstance(entry.item, CampaignEvidence)
        )

    def latest_timeline_sequence(self, campaign_id: str) -> int:
        history = self.history(campaign_id)
        return history[-1].timeline_sequence if history else 0

    def latest_event_sequence(self, campaign_id: str) -> int:
        events = self.events(campaign_id)
        return events[-1].sequence if events else 0

    def append_event(self, event: CampaignEvent) -> CampaignTimelineEntry:
        with self._lock:
            entries = self._read_verified(event.campaign_id)
            self._require_new_identity(entries, event.event_id)
            previous_event_sequence = 0
            for entry in reversed(entries):
                if isinstance(entry.item, CampaignEvent):
                    previous_event_sequence = entry.item.sequence
                    break
            expected = previous_event_sequence + 1
            if event.sequence != expected:
                raise CampaignTimelineConflictError(
                    f"campaign {event.campaign_id!r} expected event sequence "
                    f"{expected}, got {event.sequence}"
                )
            return self._append_locked(entries, event)

    def record_event(
        self,
        campaign_id: str,
        kind: CampaignEventKind,
        *,
        occurred_at: datetime,
        payload: Mapping[str, JsonValue] | None = None,
    ) -> CampaignEvent:
        with self._lock:
            entries = self._read_verified(campaign_id)
            previous_event_sequence = 0
            for entry in reversed(entries):
                if isinstance(entry.item, CampaignEvent):
                    previous_event_sequence = entry.item.sequence
                    break
            sequence = previous_event_sequence + 1
            event = CampaignEvent(
                event_id=f"{campaign_id}:{sequence}",
                campaign_id=campaign_id,
                kind=kind,
                sequence=sequence,
                occurred_at=occurred_at,
                payload=payload or {},
            )
            self._require_new_identity(entries, event.event_id)
            self._append_locked(entries, event)
            return event

    def append_evidence(self, evidence: CampaignEvidence) -> CampaignTimelineEntry:
        with self._lock:
            entries = self._read_verified(evidence.campaign_id)
            self._require_new_identity(entries, evidence.evidence_id)
            return self._append_locked(entries, evidence)

    def verify(self, campaign_id: str) -> tuple[CampaignTimelineEntry, ...]:
        return self.history(campaign_id)

    @staticmethod
    def _require_new_identity(
        entries: tuple[CampaignTimelineEntry, ...], item_id: str
    ) -> None:
        if any(entry.item_id == item_id for entry in entries):
            raise CampaignTimelineConflictError(
                f"timeline item id {item_id!r} already exists"
            )

    def _append_locked(
        self,
        entries: tuple[CampaignTimelineEntry, ...],
        item: CampaignEvent | CampaignEvidence,
    ) -> CampaignTimelineEntry:
        entry = CampaignTimelineEntry.create(
            timeline_sequence=len(entries) + 1,
            item=item,
            previous_hash=entries[-1].content_hash if entries else GENESIS_HASH,
        )
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self._path(item.campaign_id)
        data = entry.canonical_line()
        try:
            descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            try:
                view = memoryview(data)
                written = 0
                while written < len(view):
                    count = os.write(descriptor, view[written:])
                    if count <= 0:
                        raise OSError("append wrote zero bytes")
                    written += count
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise CampaignTimelineError(f"append timeline {path.name}: {exc}") from exc
        return entry

    def _read_verified(self, campaign_id: str) -> tuple[CampaignTimelineEntry, ...]:
        path = self._path(campaign_id)
        if not path.exists():
            return ()
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise CampaignTimelineError(f"read timeline {path.name}: {exc}") from exc
        if not raw:
            return ()
        if not raw.endswith(b"\n"):
            raise CampaignTimelineIntegrityError("timeline has a truncated final line")

        entries: list[CampaignTimelineEntry] = []
        item_ids: set[str] = set()
        event_sequence = 0
        previous_hash = GENESIS_HASH
        for index, line in enumerate(raw.splitlines(), start=1):
            try:
                decoded = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise CampaignTimelineIntegrityError(
                    f"timeline line {index} is not valid UTF-8 JSON"
                ) from exc
            if not isinstance(decoded, dict):
                raise CampaignTimelineIntegrityError(
                    f"timeline line {index} must be an object"
                )
            entry = CampaignTimelineEntry.from_dict(decoded)
            if entry.campaign_id != campaign_id:
                raise CampaignTimelineIntegrityError(
                    f"timeline line {index} campaign_id differs from filename binding"
                )
            if entry.timeline_sequence != index:
                raise CampaignTimelineIntegrityError(
                    f"timeline line {index} has sequence {entry.timeline_sequence}"
                )
            if entry.previous_hash != previous_hash:
                raise CampaignTimelineIntegrityError(
                    f"timeline line {index} breaks the hash chain"
                )
            if entry.item_id in item_ids:
                raise CampaignTimelineIntegrityError(
                    f"timeline line {index} repeats item id {entry.item_id!r}"
                )
            if isinstance(entry.item, CampaignEvent):
                event_sequence += 1
                if entry.item.sequence != event_sequence:
                    raise CampaignTimelineIntegrityError(
                        f"timeline line {index} breaks event ordering"
                    )
            entries.append(entry)
            item_ids.add(entry.item_id)
            previous_hash = entry.content_hash
        return tuple(entries)


class DurableCampaignEventBus:
    """Synchronous event bus whose accepted events are durable before callbacks."""

    def __init__(self, timeline: JsonlCampaignTimelineStore) -> None:
        if not isinstance(timeline, JsonlCampaignTimelineStore):
            raise TypeError("timeline must be JsonlCampaignTimelineStore")
        self._timeline = timeline
        self._handlers: dict[int, Callable[[CampaignEvent], None]] = {}
        self._next_handler_id = 0
        self._lock = RLock()

    def subscribe(self, handler: Callable[[CampaignEvent], None]) -> Callable[[], None]:
        if not callable(handler):
            raise TypeError("event handler must be callable")
        with self._lock:
            self._next_handler_id += 1
            handler_id = self._next_handler_id
            self._handlers[handler_id] = handler

        def unsubscribe() -> None:
            with self._lock:
                self._handlers.pop(handler_id, None)

        return unsubscribe

    def record(
        self,
        campaign_id: str,
        kind: CampaignEventKind,
        *,
        occurred_at: datetime,
        payload: Mapping[str, JsonValue] | None = None,
    ) -> CampaignEvent:
        event = self._timeline.record_event(
            campaign_id,
            kind,
            occurred_at=occurred_at,
            payload=payload,
        )
        self._notify(event)
        return event

    def publish(self, event: CampaignEvent) -> None:
        self._timeline.append_event(event)
        self._notify(event)

    def history(self, campaign_id: str) -> tuple[CampaignEvent, ...]:
        return self._timeline.events(campaign_id)

    def latest_sequence(self, campaign_id: str) -> int:
        return self._timeline.latest_event_sequence(campaign_id)

    def _notify(self, event: CampaignEvent) -> None:
        with self._lock:
            handlers = tuple(self._handlers.values())
        for handler in handlers:
            handler(event)
