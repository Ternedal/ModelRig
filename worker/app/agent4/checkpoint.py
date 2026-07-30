"""Immutable checkpoint envelopes and atomic filesystem persistence."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

from .contracts import (
    CampaignCheckpointStore,
    CampaignEventRecorder,
    CampaignRepository,
    Clock,
)
from .domain import (
    CampaignEventKind,
    CampaignRecord,
    CampaignStatus,
    CampaignValidationError,
    JsonValue,
    _format_datetime,
    _freeze_json,
    _parse_datetime,
    _require_aware,
    _require_text,
    _thaw_json,
)


class CheckpointStoreError(RuntimeError):
    """Raised when checkpoint data cannot be stored or validated safely."""


class CheckpointConflictError(CheckpointStoreError):
    """Raised when immutable checkpoint identity already exists."""


@dataclass(frozen=True, slots=True)
class CampaignCheckpoint:
    checkpoint_id: str
    campaign_id: str
    campaign_revision: int
    created_at: datetime
    payload: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "checkpoint_id",
            _require_text(self.checkpoint_id, "checkpoint_id"),
        )
        object.__setattr__(
            self,
            "campaign_id",
            _require_text(self.campaign_id, "campaign_id"),
        )
        if (
            isinstance(self.campaign_revision, bool)
            or not isinstance(self.campaign_revision, int)
            or self.campaign_revision < 1
        ):
            raise CampaignValidationError(
                "campaign_revision must be an integer of at least 1"
            )
        object.__setattr__(
            self,
            "created_at",
            _require_aware(self.created_at, "created_at"),
        )
        object.__setattr__(self, "payload", _freeze_json(self.payload, "payload"))

    def content_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": "modelrig-agent4/checkpoint/v1",
            "checkpoint_id": self.checkpoint_id,
            "campaign_id": self.campaign_id,
            "campaign_revision": self.campaign_revision,
            "created_at": _format_datetime(self.created_at),
            "payload": _thaw_json(self.payload),
        }

    @property
    def checksum(self) -> str:
        return hashlib.sha256(_canonical_json(self.content_dict())).hexdigest()

    def to_dict(self) -> dict[str, JsonValue]:
        value = self.content_dict()
        value["checksum"] = f"sha256:{self.checksum}"
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignCheckpoint":
        if value.get("schema") != "modelrig-agent4/checkpoint/v1":
            raise CampaignValidationError("checkpoint schema is not supported")
        checkpoint = cls(
            checkpoint_id=str(value["checkpoint_id"]),
            campaign_id=str(value["campaign_id"]),
            campaign_revision=int(value["campaign_revision"]),
            created_at=_parse_datetime(str(value["created_at"]), "created_at"),
            payload=value.get("payload", {}),
        )
        checksum = value.get("checksum")
        expected = f"sha256:{checkpoint.checksum}"
        if not isinstance(checksum, str) or not hmac.compare_digest(checksum, expected):
            raise CampaignValidationError("checkpoint checksum does not match content")
        return checkpoint


def _canonical_json(value: Mapping[str, JsonValue]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class JsonCheckpointStore:
    """Immutable atomic checkpoint store with content and filename validation."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._lock = RLock()

    @property
    def root(self) -> Path:
        return self._root

    def save(self, checkpoint: CampaignCheckpoint) -> None:
        with self._lock:
            self._root.mkdir(parents=True, exist_ok=True)
            destination = self._path_for(
                checkpoint.campaign_id,
                checkpoint.checkpoint_id,
            )
            if destination.exists():
                raise CheckpointConflictError(
                    f"checkpoint {checkpoint.checkpoint_id!r} already exists for "
                    f"campaign {checkpoint.campaign_id!r}"
                )
            payload = json.dumps(
                checkpoint.to_dict(),
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
                raise CheckpointStoreError(
                    f"unable to persist checkpoint {checkpoint.checkpoint_id!r}"
                ) from exc

    def get(
        self,
        campaign_id: str,
        checkpoint_id: str,
    ) -> CampaignCheckpoint | None:
        with self._lock:
            path = self._path_for(campaign_id, checkpoint_id)
            if not path.exists():
                return None
            return self._read(
                path,
                expected_campaign_id=campaign_id,
                expected_checkpoint_id=checkpoint_id,
            )

    def list(self, campaign_id: str) -> tuple[CampaignCheckpoint, ...]:
        with self._lock:
            if not self._root.exists():
                return ()
            checkpoints = []
            for path in sorted(self._root.glob("*.checkpoint.json")):
                checkpoint = self._read(path)
                if checkpoint.campaign_id == campaign_id:
                    checkpoints.append(checkpoint)
            return tuple(
                sorted(
                    checkpoints,
                    key=lambda checkpoint: (
                        checkpoint.campaign_revision,
                        checkpoint.created_at,
                        checkpoint.checkpoint_id,
                    ),
                )
            )

    def latest(self, campaign_id: str) -> CampaignCheckpoint | None:
        checkpoints = self.list(campaign_id)
        return checkpoints[-1] if checkpoints else None

    def delete(self, campaign_id: str, checkpoint_id: str) -> bool:
        with self._lock:
            path = self._path_for(campaign_id, checkpoint_id)
            try:
                path.unlink()
            except FileNotFoundError:
                return False
            except OSError as exc:
                raise CheckpointStoreError(
                    f"unable to delete checkpoint {checkpoint_id!r}"
                ) from exc
            self._fsync_directory()
            return True

    def _read(
        self,
        path: Path,
        *,
        expected_campaign_id: str | None = None,
        expected_checkpoint_id: str | None = None,
    ) -> CampaignCheckpoint:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CheckpointStoreError(
                f"unable to read checkpoint {path.name!r}"
            ) from exc
        if not isinstance(raw, Mapping):
            raise CheckpointStoreError(
                f"checkpoint {path.name!r} must contain an object"
            )
        try:
            checkpoint = CampaignCheckpoint.from_dict(raw)
        except (CampaignValidationError, KeyError, TypeError, ValueError) as exc:
            raise CheckpointStoreError(
                f"checkpoint {path.name!r} failed validation"
            ) from exc
        if (
            expected_campaign_id is not None
            and checkpoint.campaign_id != expected_campaign_id
        ):
            raise CheckpointStoreError("checkpoint campaign identity mismatch")
        if (
            expected_checkpoint_id is not None
            and checkpoint.checkpoint_id != expected_checkpoint_id
        ):
            raise CheckpointStoreError("checkpoint identity mismatch")
        expected_name = self._path_for(
            checkpoint.campaign_id,
            checkpoint.checkpoint_id,
        ).name
        if path.name != expected_name:
            raise CheckpointStoreError(
                f"checkpoint {path.name!r} has an invalid filename binding"
            )
        return checkpoint

    def _path_for(self, campaign_id: str, checkpoint_id: str) -> Path:
        campaign_id = _require_text(campaign_id, "campaign_id")
        checkpoint_id = _require_text(checkpoint_id, "checkpoint_id")
        digest = hashlib.sha256(
            f"{campaign_id}\0{checkpoint_id}".encode("utf-8")
        ).hexdigest()
        return self._root / f"{digest}.checkpoint.json"

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


class CheckpointLifecycleError(RuntimeError):
    """Raised when checkpoint operations conflict with durable campaign state."""


class CampaignCheckpointService:
    """Bind immutable checkpoint payloads to durable campaign revisions."""

    def __init__(
        self,
        *,
        repository: CampaignRepository,
        checkpoints: CampaignCheckpointStore,
        events: CampaignEventRecorder,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._checkpoints = checkpoints
        self._events = events
        self._clock = clock
        self._lock = RLock()

    def checkpoint(
        self,
        campaign_id: str,
        checkpoint_id: str,
        payload: Mapping[str, JsonValue],
    ) -> CampaignRecord:
        with self._lock:
            current = self._require_record(campaign_id)
            if current.state.status not in {
                CampaignStatus.RUNNING,
                CampaignStatus.PAUSING,
                CampaignStatus.PAUSED,
            }:
                raise CheckpointLifecycleError(
                    f"campaign {campaign_id!r} cannot checkpoint from "
                    f"{current.state.status.value}"
                )
            now = self._now()
            revision = current.state.revision + 1
            checkpoint = CampaignCheckpoint(
                checkpoint_id=checkpoint_id,
                campaign_id=campaign_id,
                campaign_revision=revision,
                created_at=now,
                payload=payload,
            )
            self._checkpoints.save(checkpoint)
            updated = CampaignRecord(
                spec=current.spec,
                state=replace(
                    current.state,
                    revision=revision,
                    updated_at=now,
                    checkpoint_id=checkpoint.checkpoint_id,
                ),
            )
            try:
                self._repository.save(updated)
            except Exception:
                self._checkpoints.delete(campaign_id, checkpoint.checkpoint_id)
                raise
            self._events.record(
                campaign_id,
                CampaignEventKind.CHECKPOINTED,
                occurred_at=now,
                payload={
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "revision": revision,
                },
            )
            return updated

    def load(self, campaign_id: str) -> CampaignCheckpoint | None:
        with self._lock:
            record = self._require_record(campaign_id)
            checkpoint_id = record.state.checkpoint_id
            if checkpoint_id is None:
                return None
            checkpoint = self._checkpoints.get(campaign_id, checkpoint_id)
            if checkpoint is None:
                raise CheckpointLifecycleError(
                    f"campaign {campaign_id!r} references missing checkpoint "
                    f"{checkpoint_id!r}"
                )
            if checkpoint.campaign_revision > record.state.revision:
                raise CheckpointLifecycleError(
                    f"checkpoint {checkpoint_id!r} is newer than campaign state"
                )
            return checkpoint

    def _require_record(self, campaign_id: str) -> CampaignRecord:
        record = self._repository.get(campaign_id)
        if record is None:
            raise CheckpointLifecycleError(f"campaign {campaign_id!r} was not found")
        return record

    def _now(self) -> datetime:
        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise CampaignValidationError("clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)
