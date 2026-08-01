"""First-class, directly addressable Agent 4 evidence records.

A4-12 implements ADR-A4-001a without rewriting the landed A4-06 event schema.
Evidence records form their own append-only file-per-record chain and bind to a
fully validated A4-06 timeline head. The module is caller-driven and mounts no
route, timer, thread or background cadence.
"""

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
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from .contracts import CampaignTimelineStore
from .domain import (
    CampaignValidationError,
    JsonValue,
    _format_datetime,
    _parse_datetime,
    _require_aware,
    _require_text,
)
from .timeline import CampaignEvidenceReference, _canonical_json, _require_sha256

_SCHEMA = "modelrig-agent4/campaign-evidence-record/v1"


class EvidenceRecordStoreError(RuntimeError):
    """Raised when evidence records cannot be stored or read safely."""


class EvidenceRecordConflictError(EvidenceRecordStoreError):
    """Raised when an immutable evidence identity or sequence conflicts."""


class EvidenceRecordIntegrityError(EvidenceRecordStoreError):
    """Raised when an evidence record chain fails validation."""


@dataclass(frozen=True, slots=True)
class CampaignEvidenceRecord:
    """One immutable evidence record bound to a validated campaign timeline."""

    campaign_id: str
    sequence: int
    recorded_at: datetime
    evidence: CampaignEvidenceReference
    timeline_head_hash: str
    related_event_id: str | None = None
    previous_hash: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "campaign_id",
            _require_text(self.campaign_id, "campaign_id"),
        )
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 1
        ):
            raise CampaignValidationError("sequence must be an integer of at least 1")
        object.__setattr__(
            self,
            "recorded_at",
            _require_aware(self.recorded_at, "recorded_at"),
        )
        if not isinstance(self.evidence, CampaignEvidenceReference):
            raise CampaignValidationError(
                "evidence must be a CampaignEvidenceReference"
            )
        object.__setattr__(
            self,
            "timeline_head_hash",
            _require_sha256(self.timeline_head_hash, "timeline_head_hash"),
        )
        related_event_id = self.related_event_id
        if related_event_id is not None:
            related_event_id = _require_text(related_event_id, "related_event_id")
        object.__setattr__(self, "related_event_id", related_event_id)
        previous_hash = self.previous_hash
        if previous_hash is not None:
            previous_hash = _require_sha256(previous_hash, "previous_hash")
        if self.sequence == 1 and previous_hash is not None:
            raise CampaignValidationError(
                "first evidence record must not declare previous_hash"
            )
        if self.sequence > 1 and previous_hash is None:
            raise CampaignValidationError(
                "evidence records after sequence 1 require previous_hash"
            )
        object.__setattr__(self, "previous_hash", previous_hash)

    @property
    def evidence_id(self) -> str:
        return self.evidence.evidence_id

    def content_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": _SCHEMA,
            "campaign_id": self.campaign_id,
            "sequence": self.sequence,
            "recorded_at": _format_datetime(self.recorded_at),
            "evidence": self.evidence.to_dict(),
            "timeline_head_hash": f"sha256:{self.timeline_head_hash}",
            "related_event_id": self.related_event_id,
            "previous_hash": (
                f"sha256:{self.previous_hash}"
                if self.previous_hash is not None
                else None
            ),
        }

    @property
    def record_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.content_dict())).hexdigest()

    def to_dict(self) -> dict[str, JsonValue]:
        value = self.content_dict()
        value["record_hash"] = f"sha256:{self.record_hash}"
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignEvidenceRecord":
        if value.get("schema") != _SCHEMA:
            raise CampaignValidationError(
                "campaign evidence record schema is not supported"
            )
        raw_evidence = value.get("evidence")
        if not isinstance(raw_evidence, Mapping):
            raise CampaignValidationError(
                "campaign evidence record requires an evidence object"
            )
        previous_hash = value.get("previous_hash")
        related_event_id = value.get("related_event_id")
        record = cls(
            campaign_id=str(value["campaign_id"]),
            sequence=int(value["sequence"]),
            recorded_at=_parse_datetime(str(value["recorded_at"]), "recorded_at"),
            evidence=CampaignEvidenceReference.from_dict(raw_evidence),
            timeline_head_hash=str(value["timeline_head_hash"]),
            related_event_id=(
                str(related_event_id) if related_event_id is not None else None
            ),
            previous_hash=(
                str(previous_hash) if previous_hash is not None else None
            ),
        )
        actual_hash = value.get("record_hash")
        expected_hash = f"sha256:{record.record_hash}"
        if not isinstance(actual_hash, str) or not hmac.compare_digest(
            actual_hash,
            expected_hash,
        ):
            raise CampaignValidationError(
                "campaign evidence record hash does not match content"
            )
        return record


@dataclass(frozen=True, slots=True)
class CampaignEvidenceVerification:
    campaign_id: str
    record_count: int
    head_hash: str | None
    latest_timeline_head_hash: str | None


@runtime_checkable
class CampaignEvidenceRecordStore(Protocol):
    def append(self, record: CampaignEvidenceRecord) -> CampaignEvidenceRecord:
        """Append one immutable evidence record."""

    def get(
        self,
        campaign_id: str,
        evidence_id: str,
    ) -> CampaignEvidenceRecord | None:
        """Return one directly addressed evidence record."""

    def list(self, campaign_id: str) -> tuple[CampaignEvidenceRecord, ...]:
        """Return a fully validated evidence record chain."""

    def latest(self, campaign_id: str) -> CampaignEvidenceRecord | None:
        """Return the validated evidence chain head."""

    def verify(self, campaign_id: str) -> CampaignEvidenceVerification:
        """Validate the complete evidence chain and return its summary."""


class JsonCampaignEvidenceRecordStore:
    """Append-only file-per-record evidence storage following the B model."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._lock = RLock()

    @property
    def root(self) -> Path:
        return self._root

    def append(self, record: CampaignEvidenceRecord) -> CampaignEvidenceRecord:
        if not isinstance(record, CampaignEvidenceRecord):
            raise TypeError("record must be a CampaignEvidenceRecord")
        with self._lock:
            records = self.list(record.campaign_id)
            existing = next(
                (
                    item
                    for item in records
                    if item.evidence_id == record.evidence_id
                ),
                None,
            )
            if existing is not None:
                if existing == record:
                    return existing
                raise EvidenceRecordConflictError(
                    f"evidence id {record.evidence_id!r} already exists with different content"
                )
            expected_sequence = records[-1].sequence + 1 if records else 1
            if record.sequence != expected_sequence:
                raise EvidenceRecordConflictError(
                    f"campaign {record.campaign_id!r} expected evidence sequence "
                    f"{expected_sequence}, got {record.sequence}"
                )
            expected_previous = records[-1].record_hash if records else None
            if record.previous_hash != expected_previous:
                raise EvidenceRecordConflictError(
                    "evidence record previous_hash does not match the current head"
                )

            campaign_dir = self._campaign_dir(record.campaign_id)
            campaign_dir.mkdir(parents=True, exist_ok=True)
            destination = self._path_for(record)
            if destination.exists():
                raise EvidenceRecordConflictError(
                    f"evidence record {record.evidence_id!r} already exists"
                )
            payload = json.dumps(
                record.to_dict(),
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
                    dir=campaign_dir,
                    delete=False,
                ) as handle:
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
                raise EvidenceRecordConflictError(
                    f"evidence record {record.evidence_id!r} already exists"
                ) from exc
            except OSError as exc:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
                raise EvidenceRecordStoreError(
                    f"unable to persist evidence record {record.evidence_id!r}"
                ) from exc
            return record

    def get(
        self,
        campaign_id: str,
        evidence_id: str,
    ) -> CampaignEvidenceRecord | None:
        campaign_id = _require_text(campaign_id, "campaign_id")
        evidence_id = _require_text(evidence_id, "evidence_id")
        for record in self.list(campaign_id):
            if record.evidence_id == evidence_id:
                return record
        return None

    def list(self, campaign_id: str) -> tuple[CampaignEvidenceRecord, ...]:
        campaign_id = _require_text(campaign_id, "campaign_id")
        with self._lock:
            campaign_dir = self._campaign_dir(campaign_id)
            if not campaign_dir.exists():
                return ()
            records: list[CampaignEvidenceRecord] = []
            evidence_ids: set[str] = set()
            previous_hash: str | None = None
            for path in sorted(campaign_dir.glob("*.evidence.json")):
                record = self._read(path)
                if record.campaign_id != campaign_id:
                    raise EvidenceRecordIntegrityError(
                        "evidence campaign identity does not match directory binding"
                    )
                expected_sequence = len(records) + 1
                if record.sequence != expected_sequence:
                    raise EvidenceRecordIntegrityError(
                        f"evidence chain expected sequence {expected_sequence}, "
                        f"got {record.sequence}"
                    )
                if record.previous_hash != previous_hash:
                    raise EvidenceRecordIntegrityError(
                        f"evidence chain mismatch at sequence {record.sequence}"
                    )
                if record.evidence_id in evidence_ids:
                    raise EvidenceRecordIntegrityError(
                        f"duplicate evidence id {record.evidence_id!r} in chain"
                    )
                if path.name != self._path_for(record).name:
                    raise EvidenceRecordIntegrityError(
                        f"evidence record {path.name!r} has an invalid filename binding"
                    )
                records.append(record)
                evidence_ids.add(record.evidence_id)
                previous_hash = record.record_hash
            return tuple(records)

    def latest(self, campaign_id: str) -> CampaignEvidenceRecord | None:
        records = self.list(campaign_id)
        return records[-1] if records else None

    def verify(self, campaign_id: str) -> CampaignEvidenceVerification:
        campaign_id = _require_text(campaign_id, "campaign_id")
        records = self.list(campaign_id)
        return CampaignEvidenceVerification(
            campaign_id=campaign_id,
            record_count=len(records),
            head_hash=records[-1].record_hash if records else None,
            latest_timeline_head_hash=(
                records[-1].timeline_head_hash if records else None
            ),
        )

    def replay(
        self,
        campaign_id: str,
        handler: Callable[[CampaignEvidenceRecord], None],
    ) -> int:
        if not callable(handler):
            raise TypeError("evidence replay handler must be callable")
        records = self.list(campaign_id)
        for record in records:
            handler(record)
        return len(records)

    def _read(self, path: Path) -> CampaignEvidenceRecord:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EvidenceRecordStoreError(
                f"unable to read evidence record {path.name!r}"
            ) from exc
        if not isinstance(raw, Mapping):
            raise EvidenceRecordIntegrityError(
                f"evidence record {path.name!r} must contain an object"
            )
        try:
            return CampaignEvidenceRecord.from_dict(raw)
        except (CampaignValidationError, KeyError, TypeError, ValueError) as exc:
            raise EvidenceRecordIntegrityError(
                f"evidence record {path.name!r} failed validation"
            ) from exc

    def _campaign_dir(self, campaign_id: str) -> Path:
        campaign_id = _require_text(campaign_id, "campaign_id")
        digest = hashlib.sha256(campaign_id.encode("utf-8")).hexdigest()
        return self._root / digest

    def _path_for(self, record: CampaignEvidenceRecord) -> Path:
        evidence_digest = hashlib.sha256(
            record.evidence_id.encode("utf-8")
        ).hexdigest()
        return self._campaign_dir(record.campaign_id) / (
            f"{record.sequence:020d}-{evidence_digest}.evidence.json"
        )

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


class CampaignEvidenceRecordService:
    """Bind new evidence records to an already validated A4-06 timeline head."""

    def __init__(
        self,
        *,
        timeline: CampaignTimelineStore,
        records: CampaignEvidenceRecordStore,
    ) -> None:
        if not isinstance(timeline, CampaignTimelineStore):
            raise TypeError("timeline must implement CampaignTimelineStore")
        if not isinstance(records, CampaignEvidenceRecordStore):
            raise TypeError("records must implement CampaignEvidenceRecordStore")
        self._timeline = timeline
        self._records = records
        self._lock = RLock()

    def record(
        self,
        campaign_id: str,
        evidence: CampaignEvidenceReference,
        *,
        recorded_at: datetime,
        related_event_id: str | None = None,
    ) -> CampaignEvidenceRecord:
        campaign_id = _require_text(campaign_id, "campaign_id")
        if not isinstance(evidence, CampaignEvidenceReference):
            raise TypeError("evidence must be a CampaignEvidenceReference")
        recorded_at = _require_aware(recorded_at, "recorded_at")
        if related_event_id is not None:
            related_event_id = _require_text(
                related_event_id,
                "related_event_id",
            )

        with self._lock:
            existing = self._records.get(campaign_id, evidence.evidence_id)
            if existing is not None:
                if (
                    existing.evidence == evidence
                    and existing.recorded_at == recorded_at
                    and existing.related_event_id == related_event_id
                ):
                    return existing
                raise EvidenceRecordConflictError(
                    f"evidence id {evidence.evidence_id!r} already exists with different content"
                )

            timeline = self._timeline.list(campaign_id)
            if not timeline:
                raise EvidenceRecordConflictError(
                    "first-class evidence requires an existing validated campaign timeline"
                )
            if related_event_id is not None and not any(
                entry.event.event_id == related_event_id for entry in timeline
            ):
                raise EvidenceRecordConflictError(
                    f"related event {related_event_id!r} is not present in the validated timeline"
                )

            latest_record = self._records.latest(campaign_id)
            record = CampaignEvidenceRecord(
                campaign_id=campaign_id,
                sequence=(latest_record.sequence + 1 if latest_record else 1),
                recorded_at=recorded_at,
                evidence=evidence,
                timeline_head_hash=timeline[-1].entry_hash,
                related_event_id=related_event_id,
                previous_hash=(
                    latest_record.record_hash if latest_record is not None else None
                ),
            )
            return self._records.append(record)
