"""Crash-safe JSON persistence for Agent 4 campaign records and intents."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Iterable, Mapping

from .domain import CampaignRecord, CampaignValidationError, JsonValue
from .handoff import (
    CampaignDispatchAcknowledgement,
    CampaignSignalAcknowledgement,
)
from .handoff_persistence import CampaignHandoffIntent, CampaignHandoffPhase
from .projection import CampaignProjectionIntent

_ENVELOPE_SCHEMA_V2 = "modelrig-agent4/campaign-envelope/v2"
_ENVELOPE_SCHEMA_V3 = "modelrig-agent4/campaign-envelope/v3"


class CampaignRepositoryError(RuntimeError):
    """Raised when persisted campaign data cannot be read or written safely."""


class JsonCampaignRepository:
    """Filesystem repository with atomic replacement and dual intent lifecycles."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._lock = RLock()

    @property
    def root(self) -> Path:
        return self._root

    def save(self, record: CampaignRecord) -> None:
        """Save a record without discarding either pending intent collection."""

        with self._lock:
            path = self._path_for(record.spec.campaign_id)
            projections: tuple[CampaignProjectionIntent, ...] = ()
            handoffs: tuple[CampaignHandoffIntent, ...] = ()
            if path.exists():
                _, projections, handoffs = self._read_envelope(
                    path,
                    expected_campaign_id=record.spec.campaign_id,
                )
            self._write(record, projections, handoffs)

    def save_with_projections(
        self,
        record: CampaignRecord,
        intents: Iterable[CampaignProjectionIntent],
    ) -> None:
        """Atomically publish state and audit intents, preserving handoffs."""

        self.save_with_intents(record, projection_intents=intents)

    def save_with_handoffs(
        self,
        record: CampaignRecord,
        intents: Iterable[CampaignHandoffIntent],
    ) -> None:
        """Atomically publish state and requested handoff intents."""

        self.save_with_intents(record, handoff_intents=intents)

    def save_with_intents(
        self,
        record: CampaignRecord,
        *,
        projection_intents: Iterable[CampaignProjectionIntent] = (),
        handoff_intents: Iterable[CampaignHandoffIntent] = (),
    ) -> None:
        """Atomically publish state with either or both typed intent sets."""

        incoming_projections = tuple(projection_intents)
        incoming_handoffs = tuple(handoff_intents)
        self._validate_projection_intents(record, incoming_projections)
        self._validate_handoff_intents(record, incoming_handoffs)

        with self._lock:
            path = self._path_for(record.spec.campaign_id)
            existing_projections: tuple[CampaignProjectionIntent, ...] = ()
            existing_handoffs: tuple[CampaignHandoffIntent, ...] = ()
            if path.exists():
                _, existing_projections, existing_handoffs = self._read_envelope(
                    path,
                    expected_campaign_id=record.spec.campaign_id,
                )
            merged_projections = self._merge_projections(
                existing_projections,
                incoming_projections,
            )
            merged_handoffs = self._merge_handoffs(
                existing_handoffs,
                incoming_handoffs,
            )
            self._write(record, merged_projections, merged_handoffs)

    def pending_projections(
        self,
        campaign_id: str | None = None,
    ) -> tuple[CampaignProjectionIntent, ...]:
        with self._lock:
            if campaign_id is not None:
                path = self._path_for(campaign_id)
                if not path.exists():
                    return ()
                _, pending, _ = self._read_envelope(
                    path,
                    expected_campaign_id=campaign_id,
                )
                return pending
            if not self._root.exists():
                return ()
            pending_all: list[CampaignProjectionIntent] = []
            for path in sorted(self._root.glob("*.campaign.json")):
                _, pending, _ = self._read_envelope(path)
                pending_all.extend(pending)
            return tuple(pending_all)

    def pending_handoffs(
        self,
        campaign_id: str | None = None,
    ) -> tuple[CampaignHandoffIntent, ...]:
        with self._lock:
            if campaign_id is not None:
                path = self._path_for(campaign_id)
                if not path.exists():
                    return ()
                _, _, pending = self._read_envelope(
                    path,
                    expected_campaign_id=campaign_id,
                )
                return pending
            if not self._root.exists():
                return ()
            pending_all: list[CampaignHandoffIntent] = []
            for path in sorted(self._root.glob("*.campaign.json")):
                _, _, pending = self._read_envelope(path)
                pending_all.extend(pending)
            return tuple(pending_all)

    def acknowledge_projection(self, campaign_id: str, event_id: str) -> bool:
        """Remove only one matching audit intent; handoffs are preserved."""

        with self._lock:
            path = self._path_for(campaign_id)
            if not path.exists():
                return False
            record, pending, handoffs = self._read_envelope(
                path,
                expected_campaign_id=campaign_id,
            )
            remaining = tuple(
                intent for intent in pending if intent.event_id != event_id
            )
            if len(remaining) == len(pending):
                return False
            self._write(record, remaining, handoffs)
            return True

    def acknowledge_handoff(
        self,
        campaign_id: str,
        intent_id: str,
        acknowledgement: (
            CampaignDispatchAcknowledgement | CampaignSignalAcknowledgement
        ),
        *,
        projection_intents: Iterable[CampaignProjectionIntent] = (),
    ) -> bool:
        """Atomically persist one handoff ack and any resulting audit intents."""

        if not isinstance(
            acknowledgement,
            (CampaignDispatchAcknowledgement, CampaignSignalAcknowledgement),
        ):
            raise CampaignValidationError(
                "handoff acknowledgement type is not supported"
            )
        if not isinstance(intent_id, str) or not intent_id.strip():
            raise CampaignValidationError("intent_id must not be empty")
        incoming_projections = tuple(projection_intents)

        with self._lock:
            path = self._path_for(campaign_id)
            if not path.exists():
                return False
            record, projections, handoffs = self._read_envelope(
                path,
                expected_campaign_id=campaign_id,
            )
            self._validate_projection_intents(record, incoming_projections)
            merged_projections = self._merge_projections(
                projections,
                incoming_projections,
            )
            matching_index = next(
                (
                    index
                    for index, intent in enumerate(handoffs)
                    if intent.intent_id == intent_id
                ),
                None,
            )
            if matching_index is None:
                return False
            previous = handoffs[matching_index]
            updated = previous.acknowledge(acknowledgement)
            if updated == previous and merged_projections == projections:
                return False
            rewritten = list(handoffs)
            rewritten[matching_index] = updated
            self._write(record, merged_projections, tuple(rewritten))
            return True

    def get(self, campaign_id: str) -> CampaignRecord | None:
        with self._lock:
            path = self._path_for(campaign_id)
            if not path.exists():
                return None
            record, _, _ = self._read_envelope(
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

    def _validate_projection_intents(
        self,
        record: CampaignRecord,
        intents: tuple[CampaignProjectionIntent, ...],
    ) -> None:
        for intent in intents:
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

    def _validate_handoff_intents(
        self,
        record: CampaignRecord,
        intents: tuple[CampaignHandoffIntent, ...],
    ) -> None:
        for intent in intents:
            if not isinstance(intent, CampaignHandoffIntent):
                raise CampaignValidationError(
                    "handoff intents must be CampaignHandoffIntent instances"
                )
            if intent.phase is not CampaignHandoffPhase.REQUESTED:
                raise CampaignRepositoryError(
                    "new handoff intents must start in requested phase"
                )
            if intent.campaign_id != record.spec.campaign_id:
                raise CampaignValidationError(
                    "handoff intent must use the record campaign_id"
                )
            if intent.state_revision != record.state.revision:
                raise CampaignValidationError(
                    "handoff intent revision must match record revision"
                )

    def _merge_projections(
        self,
        existing: tuple[CampaignProjectionIntent, ...],
        incoming: tuple[CampaignProjectionIntent, ...],
    ) -> tuple[CampaignProjectionIntent, ...]:
        merged = list(existing)
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
        return tuple(merged)

    def _merge_handoffs(
        self,
        existing: tuple[CampaignHandoffIntent, ...],
        incoming: tuple[CampaignHandoffIntent, ...],
    ) -> tuple[CampaignHandoffIntent, ...]:
        merged = list(existing)
        by_id = {intent.intent_id: intent for intent in existing}
        for intent in incoming:
            previous = by_id.get(intent.intent_id)
            if previous is not None:
                if previous != intent:
                    raise CampaignRepositoryError(
                        f"handoff intent {intent.intent_id!r} has conflicting content"
                    )
                continue
            by_id[intent.intent_id] = intent
            merged.append(intent)
        return tuple(merged)

    def _read_envelope(
        self,
        path: Path,
        *,
        expected_campaign_id: str | None = None,
    ) -> tuple[
        CampaignRecord,
        tuple[CampaignProjectionIntent, ...],
        tuple[CampaignHandoffIntent, ...],
    ]:
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
            schema = raw.get("schema")
            if schema == _ENVELOPE_SCHEMA_V3:
                raw_record = raw.get("record")
                raw_projections = raw.get("projection_intents")
                raw_handoffs = raw.get("handoff_intents")
                if (
                    not isinstance(raw_record, Mapping)
                    or not isinstance(raw_projections, list)
                    or not isinstance(raw_handoffs, list)
                ):
                    raise CampaignValidationError(
                        "v3 campaign envelope must contain record, "
                        "projection_intents and handoff_intents"
                    )
                record = CampaignRecord.from_dict(raw_record)
                projections = self._parse_projections(raw_projections)
                handoffs = self._parse_handoffs(raw_handoffs)
            elif schema == _ENVELOPE_SCHEMA_V2:
                raw_record = raw.get("record")
                raw_projections = raw.get("projection_intents")
                if not isinstance(raw_record, Mapping) or not isinstance(
                    raw_projections,
                    list,
                ):
                    raise CampaignValidationError(
                        "v2 campaign envelope must contain record and projection_intents"
                    )
                record = CampaignRecord.from_dict(raw_record)
                projections = self._parse_projections(raw_projections)
                handoffs = ()
            else:
                record = CampaignRecord.from_dict(raw)
                projections = ()
                handoffs = ()
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
        for intent in projections:
            if intent.campaign_id != record.spec.campaign_id:
                raise CampaignRepositoryError(
                    f"campaign record {path.name!r} contains a foreign projection"
                )
            if intent.state_revision > record.state.revision:
                raise CampaignRepositoryError(
                    f"campaign record {path.name!r} contains a future projection"
                )
        for intent in handoffs:
            if intent.campaign_id != record.spec.campaign_id:
                raise CampaignRepositoryError(
                    f"campaign record {path.name!r} contains a foreign handoff"
                )
            if intent.state_revision > record.state.revision:
                raise CampaignRepositoryError(
                    f"campaign record {path.name!r} contains a future handoff"
                )
        if len({intent.event_id for intent in projections}) != len(projections):
            raise CampaignRepositoryError(
                f"campaign record {path.name!r} contains duplicate projections"
            )
        if len({intent.intent_id for intent in handoffs}) != len(handoffs):
            raise CampaignRepositoryError(
                f"campaign record {path.name!r} contains duplicate handoffs"
            )
        return record, projections, handoffs

    def _parse_projections(
        self,
        raw: list[object],
    ) -> tuple[CampaignProjectionIntent, ...]:
        if not all(isinstance(item, Mapping) for item in raw):
            raise CampaignValidationError(
                "projection_intents must contain objects"
            )
        return tuple(
            CampaignProjectionIntent.from_dict(item)
            for item in raw
            if isinstance(item, Mapping)
        )

    def _parse_handoffs(
        self,
        raw: list[object],
    ) -> tuple[CampaignHandoffIntent, ...]:
        if not all(isinstance(item, Mapping) for item in raw):
            raise CampaignValidationError("handoff_intents must contain objects")
        return tuple(
            CampaignHandoffIntent.from_dict(item)
            for item in raw
            if isinstance(item, Mapping)
        )

    def _validate_write_contents(
        self,
        record: CampaignRecord,
        projections: tuple[CampaignProjectionIntent, ...],
        handoffs: tuple[CampaignHandoffIntent, ...],
    ) -> None:
        for intent in projections:
            if not isinstance(intent, CampaignProjectionIntent):
                raise CampaignRepositoryError(
                    "campaign envelope contains an invalid projection intent"
                )
            if intent.campaign_id != record.spec.campaign_id:
                raise CampaignRepositoryError(
                    "campaign envelope contains a foreign projection intent"
                )
            if intent.state_revision > record.state.revision:
                raise CampaignRepositoryError(
                    "campaign envelope contains a future projection intent"
                )
        for intent in handoffs:
            if not isinstance(intent, CampaignHandoffIntent):
                raise CampaignRepositoryError(
                    "campaign envelope contains an invalid handoff intent"
                )
            if intent.campaign_id != record.spec.campaign_id:
                raise CampaignRepositoryError(
                    "campaign envelope contains a foreign handoff intent"
                )
            if intent.state_revision > record.state.revision:
                raise CampaignRepositoryError(
                    "campaign envelope contains a future handoff intent"
                )
        if len({intent.event_id for intent in projections}) != len(projections):
            raise CampaignRepositoryError(
                "campaign envelope contains duplicate projection intents"
            )
        if len({intent.intent_id for intent in handoffs}) != len(handoffs):
            raise CampaignRepositoryError(
                "campaign envelope contains duplicate handoff intents"
            )

    def _write(
        self,
        record: CampaignRecord,
        projections: tuple[CampaignProjectionIntent, ...],
        handoffs: tuple[CampaignHandoffIntent, ...],
    ) -> None:
        self._validate_write_contents(record, projections, handoffs)
        self._root.mkdir(parents=True, exist_ok=True)
        destination = self._path_for(record.spec.campaign_id)
        value: Mapping[str, JsonValue]
        if projections or handoffs:
            value = {
                "schema": _ENVELOPE_SCHEMA_V3,
                "record": record.to_dict(),
                "projection_intents": [
                    intent.to_dict() for intent in projections
                ],
                "handoff_intents": [intent.to_dict() for intent in handoffs],
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
