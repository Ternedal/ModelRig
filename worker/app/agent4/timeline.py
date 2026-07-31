"""Append-only campaign timeline and evidence-reference persistence."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterable, Mapping

from .domain import CampaignEvent, CampaignValidationError, JsonValue, _freeze_json, _require_text, _thaw_json

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA = "modelrig-agent4/campaign-timeline-entry/v1"


class TimelineStoreError(RuntimeError):
    """Raised when timeline data cannot be stored or validated safely."""


class TimelineConflictError(TimelineStoreError):
    """Raised when an immutable timeline identity already exists."""


class TimelineIntegrityError(TimelineStoreError):
    """Raised when an append-only timeline fails integrity validation."""


def _require_sha256(value: str, field_name: str) -> str:
    normalized = _require_text(value, field_name)
    if normalized.startswith("sha256:"):
        normalized = normalized[7:]
    if not _SHA256_PATTERN.fullmatch(normalized):
        raise CampaignValidationError(f"{field_name} must be a lowercase SHA-256 digest")
    return normalized


def _canonical_json(value: Mapping[str, JsonValue]) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _same_logical_event(left: CampaignEvent, right: CampaignEvent) -> bool:
    return (
        left.event_id == right.event_id
        and left.campaign_id == right.campaign_id
        and left.kind is right.kind
        and left.occurred_at == right.occurred_at
        and left.payload == right.payload
    )


@dataclass(frozen=True, slots=True)
class CampaignEvidenceReference:
    evidence_id: str
    media_type: str
    location: str
    sha256: str
    size_bytes: int
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _require_text(self.evidence_id, "evidence_id"))
        object.__setattr__(self, "media_type", _require_text(self.media_type, "media_type"))
        object.__setattr__(self, "location", _require_text(self.location, "location"))
        object.__setattr__(self, "sha256", _require_sha256(self.sha256, "sha256"))
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise CampaignValidationError("size_bytes must be a non-negative integer")
        object.__setattr__(self, "metadata", _freeze_json(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, JsonValue]:
        return {"evidence_id": self.evidence_id, "media_type": self.media_type, "location": self.location, "sha256": f"sha256:{self.sha256}", "size_bytes": self.size_bytes, "metadata": _thaw_json(self.metadata)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignEvidenceReference":
        return cls(evidence_id=str(value["evidence_id"]), media_type=str(value["media_type"]), location=str(value["location"]), sha256=str(value["sha256"]), size_bytes=int(value["size_bytes"]), metadata=value.get("metadata", {}))


@dataclass(frozen=True, slots=True)
class CampaignTimelineEntry:
    event: CampaignEvent
    previous_hash: str | None = None
    evidence: tuple[CampaignEvidenceReference, ...] = ()

    def __post_init__(self) -> None:
        previous_hash = self.previous_hash
        if previous_hash is not None:
            previous_hash = _require_sha256(previous_hash, "previous_hash")
        if self.event.sequence == 1 and previous_hash is not None:
            raise CampaignValidationError("first timeline entry must not declare previous_hash")
        if self.event.sequence > 1 and previous_hash is None:
            raise CampaignValidationError("timeline entries after sequence 1 require previous_hash")
        evidence = tuple(self.evidence)
        if any(not isinstance(item, CampaignEvidenceReference) for item in evidence):
            raise CampaignValidationError("timeline evidence values must be CampaignEvidenceReference instances")
        evidence_ids = [item.evidence_id for item in evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise CampaignValidationError("timeline entry evidence_id values must be unique")
        object.__setattr__(self, "previous_hash", previous_hash)
        object.__setattr__(self, "evidence", evidence)

    def content_dict(self) -> dict[str, JsonValue]:
        return {"schema": _SCHEMA, "event": self.event.to_dict(), "previous_hash": f"sha256:{self.previous_hash}" if self.previous_hash is not None else None, "evidence": [item.to_dict() for item in self.evidence]}

    @property
    def entry_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.content_dict())).hexdigest()

    def to_dict(self) -> dict[str, JsonValue]:
        value = self.content_dict()
        value["entry_hash"] = f"sha256:{self.entry_hash}"
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignTimelineEntry":
        if value.get("schema") != _SCHEMA:
            raise CampaignValidationError("campaign timeline entry schema is not supported")
        raw_event = value.get("event")
        raw_evidence = value.get("evidence", [])
        if not isinstance(raw_event, Mapping):
            raise CampaignValidationError("campaign timeline entry requires an event object")
        if not isinstance(raw_evidence, list):
            raise CampaignValidationError("campaign timeline evidence must be a list")
        previous_hash = value.get("previous_hash")
        entry = cls(event=CampaignEvent.from_dict(raw_event), previous_hash=str(previous_hash) if previous_hash is not None else None, evidence=tuple(CampaignEvidenceReference.from_dict(item) for item in raw_evidence if isinstance(item, Mapping)))
        if len(entry.evidence) != len(raw_evidence):
            raise CampaignValidationError("campaign timeline evidence entries must be objects")
        actual_hash = value.get("entry_hash")
        expected_hash = f"sha256:{entry.entry_hash}"
        if not isinstance(actual_hash, str) or not hmac.compare_digest(actual_hash, expected_hash):
            raise CampaignValidationError("campaign timeline entry hash does not match content")
        return entry


@dataclass(frozen=True, slots=True)
class CampaignTimelineVerification:
    campaign_id: str
    entry_count: int
    evidence_count: int
    head_hash: str | None


class JsonCampaignTimelineStore:
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._lock = RLock()

    @property
    def root(self) -> Path:
        return self._root

    def append(self, event: CampaignEvent, *, evidence: Iterable[CampaignEvidenceReference] = ()) -> CampaignTimelineEntry:
        with self._lock:
            timeline = self.list(event.campaign_id)
            evidence_tuple = tuple(evidence)
            existing = next(
                (item for item in timeline if item.event.event_id == event.event_id),
                None,
            )
            if existing is not None:
                if _same_logical_event(existing.event, event) and existing.evidence == evidence_tuple:
                    return existing
                raise TimelineConflictError(f"event id {event.event_id!r} already exists in the timeline with different content")
            expected_sequence = timeline[-1].event.sequence + 1 if timeline else 1
            if event.sequence != expected_sequence:
                raise TimelineConflictError(f"campaign {event.campaign_id!r} expected event sequence {expected_sequence}, got {event.sequence}")
            entry = CampaignTimelineEntry(event=event, previous_hash=timeline[-1].entry_hash if timeline else None, evidence=evidence_tuple)
            campaign_dir = self._campaign_dir(event.campaign_id)
            campaign_dir.mkdir(parents=True, exist_ok=True)
            destination = self._path_for(entry)
            if destination.exists():
                raise TimelineConflictError(f"timeline entry {event.event_id!r} already exists")
            payload = json.dumps(entry.to_dict(), ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", prefix=f".{destination.name}.", suffix=".tmp", dir=campaign_dir, delete=False) as handle:
                    temporary_path = Path(handle.name)
                    handle.write(payload)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.link(temporary_path, destination)
                try:
                    temporary_path.unlink()
                except OSError:
                    pass
                self._fsync_directory(campaign_dir)
            except FileExistsError as exc:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
                raise TimelineConflictError(f"timeline entry {event.event_id!r} already exists") from exc
            except OSError as exc:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
                raise TimelineStoreError(f"unable to persist timeline event {event.event_id!r}") from exc
            return entry

    def list(self, campaign_id: str) -> tuple[CampaignTimelineEntry, ...]:
        campaign_id = _require_text(campaign_id, "campaign_id")
        with self._lock:
            campaign_dir = self._campaign_dir(campaign_id)
            if not campaign_dir.exists():
                return ()
            entries: list[CampaignTimelineEntry] = []
            event_ids: set[str] = set()
            previous_hash: str | None = None
            for path in sorted(campaign_dir.glob("*.timeline.json")):
                entry = self._read(path)
                if entry.event.campaign_id != campaign_id:
                    raise TimelineIntegrityError("timeline campaign identity does not match directory binding")
                expected_sequence = len(entries) + 1
                if entry.event.sequence != expected_sequence:
                    raise TimelineIntegrityError(f"timeline expected sequence {expected_sequence}, got {entry.event.sequence}")
                if entry.previous_hash != previous_hash:
                    raise TimelineIntegrityError(f"timeline chain mismatch at sequence {entry.event.sequence}")
                if entry.event.event_id in event_ids:
                    raise TimelineIntegrityError(f"duplicate event id {entry.event.event_id!r} in timeline")
                expected_name = self._path_for(entry).name
                if path.name != expected_name:
                    raise TimelineIntegrityError(f"timeline entry {path.name!r} has an invalid filename binding")
                entries.append(entry)
                event_ids.add(entry.event.event_id)
                previous_hash = entry.entry_hash
            return tuple(entries)

    def latest(self, campaign_id: str) -> CampaignTimelineEntry | None:
        entries = self.list(campaign_id)
        return entries[-1] if entries else None

    def verify(self, campaign_id: str) -> CampaignTimelineVerification:
        entries = self.list(campaign_id)
        return CampaignTimelineVerification(campaign_id=_require_text(campaign_id, "campaign_id"), entry_count=len(entries), evidence_count=sum(len(entry.evidence) for entry in entries), head_hash=entries[-1].entry_hash if entries else None)

    def replay(self, campaign_id: str, handler: Callable[[CampaignTimelineEntry], None]) -> int:
        if not callable(handler):
            raise TypeError("timeline replay handler must be callable")
        entries = self.list(campaign_id)
        for entry in entries:
            handler(entry)
        return len(entries)

    def _read(self, path: Path) -> CampaignTimelineEntry:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TimelineStoreError(f"unable to read timeline entry {path.name!r}") from exc
        if not isinstance(raw, Mapping):
            raise TimelineIntegrityError(f"timeline entry {path.name!r} must contain an object")
        try:
            return CampaignTimelineEntry.from_dict(raw)
        except (CampaignValidationError, KeyError, TypeError, ValueError) as exc:
            raise TimelineIntegrityError(f"timeline entry {path.name!r} failed validation") from exc

    def _campaign_dir(self, campaign_id: str) -> Path:
        campaign_id = _require_text(campaign_id, "campaign_id")
        digest = hashlib.sha256(campaign_id.encode("utf-8")).hexdigest()
        return self._root / digest

    def _path_for(self, entry: CampaignTimelineEntry) -> Path:
        event_digest = hashlib.sha256(entry.event.event_id.encode("utf-8")).hexdigest()
        return self._campaign_dir(entry.event.campaign_id) / f"{entry.event.sequence:020d}-{event_digest}.timeline.json"

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if os.name == "nt":
            return
        try:
            descriptor = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
