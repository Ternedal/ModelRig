"""Crash-safe JSON persistence for Agent 4 campaign records and projections."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Iterable, Mapping

from .domain import CampaignRecord, CampaignValidationError, JsonValue
from .projection import CampaignProjectionIntent

_ENVELOPE_SCHEMA = "modelrig-agent4/campaign-envelope/v2"


class CampaignRepositoryError(RuntimeError):
    """Raised when persisted campaign data cannot be read or written safely."""


class JsonCampaignRepository:
    """Filesystem repository with atomic replacement and projection envelopes."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._lock = RLock()

    @property
    def root(self) -> Path:
        return self._root

    def save(self, record: CampaignRecord) -> None:
        """Save a record without discarding any already-pending projections."""

        with self._lock:
            path = self._path_for(record.spec.campaign_id)
            pending: tuple[CampaignProjectionIntent, ...] = ()
            if path.exists():
                _, pending = self._read_envelope(
                    path,
                    expected_campaign_id=record.spec.campaign_id,
                )
            self._write(record, pending)

    def save_with_projections(
        self,
        record: CampaignRecord,
        intents: Iterable[CampaignProjectionIntent],
    ) -> None:
        """Atomically publish authoritative state and durable projection intents."""

        incoming = tuple(intents)
        for intent in incoming:
            if not isinstance(intent, CampaignProjectionIntent):
                raise CampaignValidationError(
                    "projection intents must be CampaignProjectionIntent instances"
                )
            if intent.campaign_id != record.spec.campaign_id:
                raise CampaignValidationError(
                    "projection intent must use the record campaign_id"
                )
            if intent.state_revision != record.state.revision:
                raise CampaignValidationError(
                    "projection intent revision must match record revision"
                )

        with self._lock:
            path = self._path_for(record.spec.campaign_id)
            existing: tuple[CampaignProjectionIntent, ...] = ()
            if path.exists():
                _, existing = self._read_envelope(
                    path,
                    expected_campaign_id=record.spec.campaign_id,
                )
            merged: list[CampaignProjectionIntent] = list(existing)
            by_id = {intent.event_id: intent for intent in existing}
            for intent in incoming:
                previous = by_id.get(intent.event_id)
                if previous is not None:
                    if previous != intent:
                        raise CampaignRepositoryError(
                            f"projection event {intent.event_id!r} has conflicting content"
                        )
                    continue
                by_id[intent.event_id] = intent
                merged.append(intent)
            self._write(record, tuple(merged))

    def pending_projections(
        self,
        campaign_id: str | None = None,
    ) -> tuple[CampaignProjectionIntent, ...]:
        with self._lock:
            if campaign_id is not None:
                path = self._path_for(campaign_id)
                if not path.exists():
                    return ()
                _, pending = self._read_envelope(
                    path,
                    expected_campaign_id=campaign_id,
                )
                return pending
            if not self._root.exists():
                return ()
            pending_all: list[CampaignProjectionIntent] = []
            for path in sorted(self._root.glob("*.campaign.json")):
                _, pending = self._read_envelope(path)
                pending_all.extend(pending)
            return tuple(pending_all)

    def acknowledge_projection(self, campaign_id: str, event_id: str) -> bool:
        with self._lock:
            path = self._path_for(campaign_id)
            if not path.exists():
                return False
            record, pending = self._read_envelope(
                path,
                expected_campaign_id=campaign_id,
            )
            remaining = tuple(
                intent for intent in pending if intent.event_id != event_id
            )
            if len(remaining) == len(pending):
                return False
            self._write(record, remaining)
            return True

    def get(self, campaign_id: str) -> CampaignRecord | None:
        with self._lock:
            path = self._path_for(campaign_id)
            if not path.exists():
                return None
            record, _ = self._read_envelope(
                path,
                expected_campaign_id=campaign_id,
            )
            return record

    def list(self) -> tuple[CampaignRecord, ...]:
        with self._lock:
            if not self._root.exists():
                return ()
            records = [
                self._read_envelope(path)[0]
                for path in sorted(self._root.glob("*.campaign.json"))
            ]
            return tuple(
                sorted(
                    records,
                    key=lambda record: (
                        record.spec.created_at,
                        record.spec.campaign_id,
                    ),
                )
            )

    def delete(self, campaign_id: str) -> bool:
        with self._lock:
            path = self._path_for(campaign_id)
            try:
                path.unlink()
            except FileNotFoundError:
                return False
            except OSError as exc:
                raise CampaignRepositoryError(
                    f"unable to delete campaign {campaign_id!r}"
                ) from exc
            self._fsync_directory()
            return True

    def _read_envelope(
        self,
        path: Path,
        *,
        expected_campaign_id: str | None = None,
    ) -> tuple[CampaignRecord, tuple[CampaignProjectionIntent, ...]]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CampaignRepositoryError(
                f"unable to read campaign record {path.name!r}"
            ) from exc
        if not isinstance(raw, Mapping):
            raise CampaignRepositoryError(
                f"campaign record {path.name!r} must contain an object"
            )
        try:
            if raw.get("schema") == _ENVELOPE_SCHEMA:
                raw_record = raw.get("record")
                raw_pending = raw.get("projection_intents", [])
                if not isinstance(raw_record, Mapping) or not isinstance(
                    raw_pending, list
                ):
                    raise CampaignValidationError(
                        "campaign envelope must contain record and projection_intents"
                    )
                record = CampaignRecord.from_dict(raw_record)
                pending = tuple(
                    CampaignProjectionIntent.from_dict(item)
                    for item in raw_pending
                    if isinstance(item, Mapping)
                )
                if len(pending) != len(raw_pending):
                    raise CampaignValidationError(
                        "projection_intents must contain objects"
                    )
            else:
                record = CampaignRecord.from_dict(raw)
                pending = ()
        except (CampaignValidationError, KeyError, TypeError, ValueError) as exc:
            raise CampaignRepositoryError(
                f"campaign record {path.name!r} failed validation"
            ) from exc
        if (
            expected_campaign_id is not None
            and record.spec.campaign_id != expected_campaign_id
        ):
            raise CampaignRepositoryError(
                f"campaign record {path.name!r} does not match requested id"
            )
        if path.name != self._path_for(record.spec.campaign_id).name:
            raise CampaignRepositoryError(
                f"campaign record {path.name!r} has an invalid filename binding"
            )
        for intent in pending:
            if intent.campaign_id != record.spec.campaign_id:
                raise CampaignRepositoryError(
                    f"campaign record {path.name!r} contains a foreign projection"
                )
            if intent.state_revision > record.state.revision:
                raise CampaignRepositoryError(
                    f"campaign record {path.name!r} contains a future projection"
                )
        if len({intent.event_id for intent in pending}) != len(pending):
            raise CampaignRepositoryError(
                f"campaign record {path.name!r} contains duplicate projections"
            )
        return record, pending

    def _write(
        self,
        record: CampaignRecord,
        pending: tuple[CampaignProjectionIntent, ...],
    ) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        destination = self._path_for(record.spec.campaign_id)
        value: Mapping[str, JsonValue]
        if pending:
            value = {
                "schema": _ENVELOPE_SCHEMA,
                "record": record.to_dict(),
                "projection_intents": [intent.to_dict() for intent in pending],
            }
        else:
            value = record.to_dict()
        payload = json.dumps(
            value,
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
            raise CampaignRepositoryError(
                f"unable to persist campaign {record.spec.campaign_id!r}"
            ) from exc

    def _path_for(self, campaign_id: str) -> Path:
        if not isinstance(campaign_id, str) or not campaign_id.strip():
            raise CampaignValidationError("campaign_id must not be empty")
        digest = hashlib.sha256(campaign_id.strip().encode("utf-8")).hexdigest()
        return self._root / f"{digest}.campaign.json"

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
