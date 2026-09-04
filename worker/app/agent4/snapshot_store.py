"""Dormant immutable snapshot authority for Agent 4 operator reads (A4-25b)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from threading import RLock
import tempfile
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .domain import CampaignRecord, CampaignValidationError, JsonValue

CAMPAIGN_SNAPSHOT_SCHEMA = "modelrig-agent4/operator-campaign-snapshot/v1"
ROOT_SNAPSHOT_SCHEMA = "modelrig-agent4/operator-root-snapshot/v1"
CURRENT_POINTER_SCHEMA = "modelrig-agent4/operator-snapshot-pointer/v1"
DEFAULT_MAX_ROOTS = 256
DEFAULT_MAX_AGE = timedelta(minutes=15)
_HEX = frozenset("0123456789abcdef")


class OperatorSnapshotError(RuntimeError):
    """Base error for durable snapshot authority failures."""


class OperatorSnapshotIntegrityError(OperatorSnapshotError):
    """Persisted snapshot content failed schema/hash validation."""


class OperatorSnapshotConflictError(OperatorSnapshotError):
    """Publication attempted from a stale/conflicting root."""


class OperatorSnapshotNotFoundError(OperatorSnapshotError):
    """Requested snapshot is unknown, uncommitted, stale, or expired."""


def _require_id(value: object, field: str = "snapshot_id") -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _HEX for character in value)
    ):
        raise CampaignValidationError(f"{field} must be 64 lowercase hex characters")
    return value


def _require_uint(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        qualifier = "positive" if minimum == 1 else "non-negative"
        raise CampaignValidationError(f"{field} must be a {qualifier} integer")
    return value


def _require_aware(value: object, field: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise CampaignValidationError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _format_time(value: datetime) -> str:
    return _require_aware(value, "published_at").isoformat().replace("+00:00", "Z")


def _parse_time(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise CampaignValidationError(f"{field} must be a datetime string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CampaignValidationError(f"{field} is not a valid datetime") from exc
    return _require_aware(parsed, field)


def _head_hash(sequence: int, value: object, field: str) -> str | None:
    """Bind an append-only head hash to its sequence without synthetic sentinels."""

    if sequence == 0:
        if value is not None:
            raise CampaignValidationError(f"{field} must be null when sequence is 0")
        return None
    return _require_id(value, field)


def _canonical(value: Mapping[str, JsonValue]) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CampaignValidationError("snapshot content must be canonical JSON") from exc


def _digest(value: Mapping[str, JsonValue]) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _record_digest(record: CampaignRecord) -> str:
    return _digest(record.to_dict())


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise OperatorSnapshotIntegrityError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _campaign_map(value: Mapping[str, str]) -> Mapping[str, str]:
    normalized: dict[str, str] = {}
    for raw_campaign_id, raw_snapshot_id in value.items():
        if not isinstance(raw_campaign_id, str) or not raw_campaign_id.strip():
            raise CampaignValidationError("campaign mapping keys must not be empty")
        campaign_id = raw_campaign_id.strip()
        if campaign_id in normalized:
            raise CampaignValidationError("campaign mapping has duplicate identities")
        normalized[campaign_id] = _require_id(
            raw_snapshot_id, "campaign snapshot_id"
        )
    return MappingProxyType(dict(sorted(normalized.items())))


@dataclass(frozen=True, slots=True)
class OperatorCampaignSnapshot:
    campaign: CampaignRecord
    timeline_head_sequence: int
    timeline_head_sha256: str | None
    evidence_head_sequence: int
    evidence_head_sha256: str | None
    latest_evidence_timeline_head_sha256: str | None
    snapshot_id: str

    @classmethod
    def create(
        cls,
        campaign: CampaignRecord,
        *,
        timeline_head_sequence: int,
        timeline_head_sha256: str | None,
        evidence_head_sequence: int,
        evidence_head_sha256: str | None,
        latest_evidence_timeline_head_sha256: str | None,
    ) -> "OperatorCampaignSnapshot":
        if not isinstance(campaign, CampaignRecord):
            raise CampaignValidationError("campaign must be a CampaignRecord")
        timeline_sequence = _require_uint(
            timeline_head_sequence, "timeline_head_sequence"
        )
        evidence_sequence = _require_uint(
            evidence_head_sequence, "evidence_head_sequence"
        )
        timeline_hash = _head_hash(
            timeline_sequence,
            timeline_head_sha256,
            "timeline_head_sha256",
        )
        evidence_hash = _head_hash(
            evidence_sequence,
            evidence_head_sha256,
            "evidence_head_sha256",
        )
        evidence_timeline_hash = _head_hash(
            evidence_sequence,
            latest_evidence_timeline_head_sha256,
            "latest_evidence_timeline_head_sha256",
        )
        unsigned: dict[str, JsonValue] = {
            "schema": CAMPAIGN_SNAPSHOT_SCHEMA,
            "campaign_id": campaign.spec.campaign_id,
            "state_revision": campaign.state.revision,
            "campaign_record_sha256": _record_digest(campaign),
            "campaign": campaign.to_dict(),
            "timeline_head": {
                "sequence": timeline_sequence,
                "sha256": timeline_hash,
            },
            "evidence_head": {
                "sequence": evidence_sequence,
                "sha256": evidence_hash,
            },
            "latest_evidence_timeline_head_sha256": evidence_timeline_hash,
        }
        return cls(
            campaign=campaign,
            timeline_head_sequence=timeline_sequence,
            timeline_head_sha256=timeline_hash,
            evidence_head_sequence=evidence_sequence,
            evidence_head_sha256=evidence_hash,
            latest_evidence_timeline_head_sha256=evidence_timeline_hash,
            snapshot_id=_digest(unsigned),
        )

    @property
    def campaign_id(self) -> str:
        return self.campaign.spec.campaign_id

    @property
    def state_revision(self) -> int:
        return self.campaign.state.revision

    def _unsigned(self) -> dict[str, JsonValue]:
        return {
            "schema": CAMPAIGN_SNAPSHOT_SCHEMA,
            "campaign_id": self.campaign_id,
            "state_revision": self.state_revision,
            "campaign_record_sha256": _record_digest(self.campaign),
            "campaign": self.campaign.to_dict(),
            "timeline_head": {
                "sequence": self.timeline_head_sequence,
                "sha256": self.timeline_head_sha256,
            },
            "evidence_head": {
                "sequence": self.evidence_head_sequence,
                "sha256": self.evidence_head_sha256,
            },
            "latest_evidence_timeline_head_sha256": (
                self.latest_evidence_timeline_head_sha256
            ),
        }

    def to_dict(self) -> dict[str, JsonValue]:
        value = self._unsigned()
        value["snapshot_id"] = self.snapshot_id
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperatorCampaignSnapshot":
        if value.get("schema") != CAMPAIGN_SNAPSHOT_SCHEMA:
            raise CampaignValidationError("campaign snapshot schema is not supported")
        raw_campaign = value.get("campaign")
        timeline = value.get("timeline_head")
        evidence = value.get("evidence_head")
        if not isinstance(raw_campaign, Mapping):
            raise CampaignValidationError("campaign snapshot must contain campaign")
        if not isinstance(timeline, Mapping) or not isinstance(evidence, Mapping):
            raise CampaignValidationError("campaign snapshot must contain both heads")
        campaign = CampaignRecord.from_dict(raw_campaign)
        if value.get("campaign_id") != campaign.spec.campaign_id:
            raise CampaignValidationError(
                "campaign snapshot identity does not match record"
            )
        if value.get("state_revision") != campaign.state.revision:
            raise CampaignValidationError(
                "campaign snapshot revision does not match record"
            )
        if value.get("campaign_record_sha256") != _record_digest(campaign):
            raise CampaignValidationError("campaign record hash does not match content")
        snapshot = cls.create(
            campaign,
            timeline_head_sequence=_require_uint(
                timeline.get("sequence"), "timeline_head_sequence"
            ),
            timeline_head_sha256=timeline.get("sha256"),
            evidence_head_sequence=_require_uint(
                evidence.get("sequence"), "evidence_head_sequence"
            ),
            evidence_head_sha256=evidence.get("sha256"),
            latest_evidence_timeline_head_sha256=value.get(
                "latest_evidence_timeline_head_sha256"
            ),
        )
        claimed = _require_id(value.get("snapshot_id"))
        if claimed != snapshot.snapshot_id:
            raise CampaignValidationError("campaign snapshot_id does not match content")
        return snapshot


@dataclass(frozen=True, slots=True)
class OperatorRootSnapshot:
    root_sequence: int
    parent_snapshot_id: str | None
    published_at: datetime
    campaigns: Mapping[str, str]
    snapshot_id: str

    @classmethod
    def create(
        cls,
        *,
        root_sequence: int,
        parent_snapshot_id: str | None,
        published_at: datetime,
        campaigns: Mapping[str, str],
    ) -> "OperatorRootSnapshot":
        sequence = _require_uint(root_sequence, "root_sequence", minimum=1)
        parent = (
            _require_id(parent_snapshot_id, "parent_snapshot_id")
            if parent_snapshot_id is not None
            else None
        )
        if sequence == 1 and parent is not None:
            raise CampaignValidationError("genesis root must not declare a parent")
        if sequence > 1 and parent is None:
            raise CampaignValidationError("non-genesis root must declare a parent")
        timestamp = _require_aware(published_at, "published_at")
        frozen_campaigns = _campaign_map(campaigns)
        unsigned: dict[str, JsonValue] = {
            "schema": ROOT_SNAPSHOT_SCHEMA,
            "root_sequence": sequence,
            "parent_snapshot_id": parent,
            "published_at": _format_time(timestamp),
            "campaigns": dict(frozen_campaigns),
        }
        return cls(
            root_sequence=sequence,
            parent_snapshot_id=parent,
            published_at=timestamp,
            campaigns=frozen_campaigns,
            snapshot_id=_digest(unsigned),
        )

    def _unsigned(self) -> dict[str, JsonValue]:
        return {
            "schema": ROOT_SNAPSHOT_SCHEMA,
            "root_sequence": self.root_sequence,
            "parent_snapshot_id": self.parent_snapshot_id,
            "published_at": _format_time(self.published_at),
            "campaigns": dict(self.campaigns),
        }

    def to_dict(self) -> dict[str, JsonValue]:
        value = self._unsigned()
        value["snapshot_id"] = self.snapshot_id
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperatorRootSnapshot":
        if value.get("schema") != ROOT_SNAPSHOT_SCHEMA:
            raise CampaignValidationError("root snapshot schema is not supported")
        raw_campaigns = value.get("campaigns")
        if not isinstance(raw_campaigns, Mapping):
            raise CampaignValidationError("root snapshot campaigns must be an object")
        parent_raw = value.get("parent_snapshot_id")
        if parent_raw is not None and not isinstance(parent_raw, str):
            raise CampaignValidationError("parent_snapshot_id must be a string or null")
        campaign_map: dict[str, str] = {}
        for campaign_id, campaign_snapshot_id in raw_campaigns.items():
            if not isinstance(campaign_id, str) or not isinstance(
                campaign_snapshot_id, str
            ):
                raise CampaignValidationError(
                    "root snapshot campaign mapping must contain string ids"
                )
            campaign_map[campaign_id] = campaign_snapshot_id
        snapshot = cls.create(
            root_sequence=_require_uint(
                value.get("root_sequence"), "root_sequence", minimum=1
            ),
            parent_snapshot_id=parent_raw,
            published_at=_parse_time(value.get("published_at"), "published_at"),
            campaigns=campaign_map,
        )
        claimed = _require_id(value.get("snapshot_id"))
        if claimed != snapshot.snapshot_id:
            raise CampaignValidationError("root snapshot_id does not match content")
        return snapshot


class JsonOperatorSnapshotStore:
    """Content-addressed immutable blobs with one atomic current commit point."""

    def __init__(
        self,
        root: Path | str,
        *,
        max_roots: int = DEFAULT_MAX_ROOTS,
        max_age: timedelta = DEFAULT_MAX_AGE,
        clock: Callable[[], datetime] | None = None,
        failure_injector: Callable[[str], None] | None = None,
    ) -> None:
        self._max_roots = _require_uint(max_roots, "max_roots", minimum=1)
        if not isinstance(max_age, timedelta) or max_age <= timedelta(0):
            raise CampaignValidationError("max_age must be positive")
        self._root = Path(root)
        self._campaign_root = self._root / "campaigns"
        self._roots_root = self._root / "roots"
        self._current_path = self._root / "current.json"
        self._max_age = max_age
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._failure_injector = failure_injector
        self._lock = RLock()

    @property
    def root(self) -> Path:
        return self._root

    def write_campaign_snapshot(
        self, snapshot: OperatorCampaignSnapshot
    ) -> OperatorCampaignSnapshot:
        if not isinstance(snapshot, OperatorCampaignSnapshot):
            raise CampaignValidationError(
                "snapshot must be an OperatorCampaignSnapshot"
            )
        with self._lock:
            self._ensure_layout()
            self._write_immutable(
                self._campaign_path(snapshot.snapshot_id),
                snapshot.to_dict(),
                "campaign snapshot",
            )
            self._inject("after_campaign_write")
            return snapshot

    def publish_root(
        self,
        snapshot: OperatorRootSnapshot,
        *,
        expected_parent: str | None,
    ) -> OperatorRootSnapshot:
        """Commit one root; current-pointer replacement is the only commit point.

        Retention/GC is deliberately separate. Once ``current.json`` is replaced,
        this publication is committed and cleanup must not be able to turn that
        committed result into an apparent publication failure.
        """

        if not isinstance(snapshot, OperatorRootSnapshot):
            raise CampaignValidationError("snapshot must be an OperatorRootSnapshot")
        if expected_parent is not None:
            expected_parent = _require_id(expected_parent, "expected_parent")
        with self._lock:
            self._ensure_layout()
            current = self._read_current_id()
            if current != expected_parent or snapshot.parent_snapshot_id != current:
                raise OperatorSnapshotConflictError(
                    "snapshot publication parent is stale"
                )
            expected_sequence = 1
            if current is not None:
                parent = self._load_root_file(current)
                expected_sequence = parent.root_sequence + 1
                if snapshot.published_at < parent.published_at:
                    raise OperatorSnapshotConflictError(
                        "root snapshot published_at precedes its parent"
                    )
            if snapshot.root_sequence != expected_sequence:
                raise OperatorSnapshotConflictError(
                    "root snapshot sequence does not extend current authority"
                )
            for campaign_id, campaign_snapshot_id in snapshot.campaigns.items():
                campaign_snapshot = self.load_campaign(campaign_snapshot_id)
                if campaign_snapshot.campaign_id != campaign_id:
                    raise OperatorSnapshotIntegrityError(
                        "root campaign identity does not match campaign snapshot"
                    )

            self._write_immutable(
                self._root_path(snapshot.snapshot_id),
                snapshot.to_dict(),
                "root snapshot",
            )
            self._inject("after_root_write")
            self._inject("before_current_replace")
            self._write_current(snapshot.snapshot_id)
            self._inject("after_current_replace")
            return snapshot

    def current_snapshot_id(self) -> str | None:
        with self._lock:
            return self._read_current_id()

    def load_current(self) -> OperatorRootSnapshot | None:
        with self._lock:
            snapshot_id = self._read_current_id()
            return self._load_root_file(snapshot_id) if snapshot_id else None

    def load_campaign(self, snapshot_id: str) -> OperatorCampaignSnapshot:
        snapshot_id = _require_id(snapshot_id)
        with self._lock:
            value = self._read_json(
                self._campaign_path(snapshot_id), "campaign snapshot"
            )
            try:
                snapshot = OperatorCampaignSnapshot.from_dict(value)
            except (CampaignValidationError, KeyError, TypeError, ValueError) as exc:
                raise OperatorSnapshotIntegrityError(
                    "campaign snapshot failed validation"
                ) from exc
            if snapshot.snapshot_id != snapshot_id:
                raise OperatorSnapshotIntegrityError(
                    "campaign snapshot filename does not match content"
                )
            return snapshot

    def load_root(
        self,
        snapshot_id: str,
        *,
        now: datetime | None = None,
    ) -> OperatorRootSnapshot:
        snapshot_id = _require_id(snapshot_id)
        with self._lock:
            instant = _require_aware(now or self._clock(), "now")
            retained = {
                item.snapshot_id: item for item in self._retained_roots(instant)
            }
            try:
                return retained[snapshot_id]
            except KeyError as exc:
                raise OperatorSnapshotNotFoundError(
                    "root snapshot is unknown, uncommitted, stale, or expired"
                ) from exc

    def prune(self, *, now: datetime | None = None) -> tuple[str, ...]:
        """Apply retention/GC after publication; never part of the commit point."""

        with self._lock:
            self._ensure_layout()
            instant = _require_aware(now or self._clock(), "now")
            keep_roots = self._retained_roots(instant)
            keep_ids = {snapshot.snapshot_id for snapshot in keep_roots}
            removed: list[str] = []

            for path in sorted(self._roots_root.glob("*.json")):
                if path.stem not in keep_ids:
                    self._unlink(path)
                    removed.append(path.stem)

            referenced_campaigns = {
                campaign_snapshot_id
                for root_snapshot in keep_roots
                for campaign_snapshot_id in root_snapshot.campaigns.values()
            }
            for path in sorted(self._campaign_root.glob("*.json")):
                if path.stem not in referenced_campaigns:
                    self._unlink(path)

            self._fsync_directory(self._roots_root)
            self._fsync_directory(self._campaign_root)
            return tuple(removed)

    def _retained_roots(self, now: datetime) -> tuple[OperatorRootSnapshot, ...]:
        current_id = self._read_current_id()
        if current_id is None:
            return ()
        chain: list[OperatorRootSnapshot] = []
        seen: set[str] = set()
        next_id: str | None = current_id
        while next_id is not None and len(chain) < self._max_roots:
            if next_id in seen:
                raise OperatorSnapshotIntegrityError(
                    "root snapshot chain contains a cycle"
                )
            seen.add(next_id)
            try:
                snapshot = self._load_root_file(next_id)
            except OperatorSnapshotNotFoundError:
                if next_id == current_id:
                    raise OperatorSnapshotIntegrityError(
                        "current pointer references a missing root"
                    )
                break
            if chain:
                child = chain[-1]
                if snapshot.root_sequence != child.root_sequence - 1:
                    raise OperatorSnapshotIntegrityError(
                        "root snapshot chain sequence is not contiguous"
                    )
                if snapshot.published_at > child.published_at:
                    raise OperatorSnapshotIntegrityError(
                        "root snapshot chain published_at is not monotonic"
                    )
            if next_id != current_id and now - snapshot.published_at > self._max_age:
                break
            chain.append(snapshot)
            next_id = snapshot.parent_snapshot_id
        return tuple(chain)

    def _load_root_file(self, snapshot_id: str) -> OperatorRootSnapshot:
        snapshot_id = _require_id(snapshot_id)
        value = self._read_json(self._root_path(snapshot_id), "root snapshot")
        try:
            snapshot = OperatorRootSnapshot.from_dict(value)
        except (CampaignValidationError, KeyError, TypeError, ValueError) as exc:
            raise OperatorSnapshotIntegrityError(
                "root snapshot failed validation"
            ) from exc
        if snapshot.snapshot_id != snapshot_id:
            raise OperatorSnapshotIntegrityError(
                "root snapshot filename does not match content"
            )
        return snapshot

    def _read_current_id(self) -> str | None:
        if not self._current_path.exists():
            return None
        value = self._read_json(self._current_path, "current pointer")
        if value.get("schema") != CURRENT_POINTER_SCHEMA:
            raise OperatorSnapshotIntegrityError(
                "current pointer schema is not supported"
            )
        try:
            snapshot_id = _require_id(value["snapshot_id"])
        except (CampaignValidationError, KeyError) as exc:
            raise OperatorSnapshotIntegrityError(
                "current pointer failed validation"
            ) from exc
        if not self._root_path(snapshot_id).exists():
            raise OperatorSnapshotIntegrityError(
                "current pointer references a missing root"
            )
        return snapshot_id

    def _write_current(self, snapshot_id: str) -> None:
        self._write_replace(
            self._current_path,
            {
                "schema": CURRENT_POINTER_SCHEMA,
                "snapshot_id": _require_id(snapshot_id),
            },
        )

    def _write_immutable(
        self,
        path: Path,
        value: Mapping[str, JsonValue],
        label: str,
    ) -> None:
        """Create an immutable blob without ever replacing an existing path."""

        path.parent.mkdir(parents=True, exist_ok=True)
        canonical = _canonical(value)
        payload = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8") + b"\n"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError:
            existing = self._read_json(path, label)
            if _canonical(existing) != canonical:
                raise OperatorSnapshotIntegrityError(
                    f"{label} conflicts with existing immutable blob"
                )
            return
        except OSError as exc:
            raise OperatorSnapshotError(
                f"unable to create immutable {label}"
            ) from exc

        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            self._fsync_directory(path.parent)
        except OSError as exc:
            try:
                path.unlink()
            except OSError:
                pass
            raise OperatorSnapshotError(
                f"unable to persist immutable {label}"
            ) from exc

    def _write_replace(self, path: Path, value: Mapping[str, JsonValue]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=path.parent,
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            self._fsync_directory(path.parent)
        except OSError as exc:
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass
            raise OperatorSnapshotError(
                f"unable to persist snapshot path {path.name!r}"
            ) from exc

    def _read_json(self, path: Path, label: str) -> dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle, object_pairs_hook=_strict_pairs)
        except FileNotFoundError as exc:
            raise OperatorSnapshotNotFoundError(f"{label} is unknown") from exc
        except OperatorSnapshotIntegrityError:
            raise
        except (OSError, json.JSONDecodeError) as exc:
            raise OperatorSnapshotIntegrityError(
                f"{label} cannot be decoded"
            ) from exc
        if not isinstance(value, dict):
            raise OperatorSnapshotIntegrityError(f"{label} must contain an object")
        return value

    def _ensure_layout(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        self._campaign_root.mkdir(parents=True, exist_ok=True)
        self._roots_root.mkdir(parents=True, exist_ok=True)

    def _campaign_path(self, snapshot_id: str) -> Path:
        return self._campaign_root / f"{snapshot_id}.json"

    def _root_path(self, snapshot_id: str) -> Path:
        return self._roots_root / f"{snapshot_id}.json"

    def _inject(self, point: str) -> None:
        if self._failure_injector is not None:
            self._failure_injector(point)

    def _unlink(self, path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise OperatorSnapshotError(
                f"unable to prune snapshot {path.name!r}"
            ) from exc

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
