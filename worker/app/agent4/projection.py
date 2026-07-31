"""Durable, caller-driven projection of authoritative campaign state to audit timeline."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping, Protocol, runtime_checkable

from .contracts import CampaignTimelineStore
from .domain import (
    CampaignEvent,
    CampaignEventKind,
    CampaignRecord,
    CampaignValidationError,
    JsonValue,
    _format_datetime,
    _freeze_json,
    _parse_datetime,
    _require_aware,
    _require_text,
    _thaw_json,
)
from .timeline import TimelineConflictError

_PROJECTION_SCHEMA = "modelrig-agent4/projection-intent/v1"
_EVENT_SCHEMA_VERSION = 1


def _canonical_json(value: Mapping[str, JsonValue]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class CampaignProjectionIntent:
    """Durable metadata for one already-decided state transition."""

    campaign_id: str
    state_revision: int
    kind: CampaignEventKind
    occurred_at: datetime
    payload: Mapping[str, JsonValue] = field(default_factory=dict)
    producer_id: str = "lifecycle"
    event_schema_version: int = _EVENT_SCHEMA_VERSION
    event_id: str = ""

    def __post_init__(self) -> None:
        campaign_id = _require_text(self.campaign_id, "campaign_id")
        producer_id = _require_text(self.producer_id, "producer_id")
        if (
            isinstance(self.state_revision, bool)
            or not isinstance(self.state_revision, int)
            or self.state_revision < 0
        ):
            raise CampaignValidationError(
                "state_revision must be a non-negative integer"
            )
        if (
            isinstance(self.event_schema_version, bool)
            or not isinstance(self.event_schema_version, int)
            or self.event_schema_version < 1
        ):
            raise CampaignValidationError(
                "event_schema_version must be an integer of at least 1"
            )
        try:
            kind = CampaignEventKind(self.kind)
        except ValueError as exc:
            raise CampaignValidationError("projection event kind is not supported") from exc
        occurred_at = _require_aware(self.occurred_at, "occurred_at")
        payload = _freeze_json(self.payload, "payload")
        identity = {
            "campaign_id": campaign_id,
            "state_revision": self.state_revision,
            "kind": kind.value,
            "producer_id": producer_id,
            "event_schema_version": self.event_schema_version,
        }
        expected_event_id = "projection:" + hashlib.sha256(
            _canonical_json(identity)
        ).hexdigest()
        if self.event_id and self.event_id != expected_event_id:
            raise CampaignValidationError(
                "projection event_id does not match its deterministic identity"
            )
        object.__setattr__(self, "campaign_id", campaign_id)
        object.__setattr__(self, "producer_id", producer_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "occurred_at", occurred_at)
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "event_id", expected_event_id)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": _PROJECTION_SCHEMA,
            "campaign_id": self.campaign_id,
            "state_revision": self.state_revision,
            "kind": self.kind.value,
            "occurred_at": _format_datetime(self.occurred_at),
            "payload": _thaw_json(self.payload),
            "producer_id": self.producer_id,
            "event_schema_version": self.event_schema_version,
            "event_id": self.event_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignProjectionIntent":
        if value.get("schema") != _PROJECTION_SCHEMA:
            raise CampaignValidationError("projection intent schema is not supported")
        return cls(
            campaign_id=str(value["campaign_id"]),
            state_revision=int(value["state_revision"]),
            kind=CampaignEventKind(str(value["kind"])),
            occurred_at=_parse_datetime(str(value["occurred_at"]), "occurred_at"),
            payload=value.get("payload", {}),
            producer_id=str(value.get("producer_id", "lifecycle")),
            event_schema_version=int(
                value.get("event_schema_version", _EVENT_SCHEMA_VERSION)
            ),
            event_id=str(value["event_id"]),
        )

    def matches_event(self, event: CampaignEvent) -> bool:
        return (
            event.event_id == self.event_id
            and event.campaign_id == self.campaign_id
            and event.kind is self.kind
            and event.occurred_at == self.occurred_at
            and event.payload == self.payload
        )


@runtime_checkable
class CampaignProjectionRepository(Protocol):
    def save_with_projections(
        self,
        record: CampaignRecord,
        intents: Iterable[CampaignProjectionIntent],
    ) -> None:
        """Atomically publish authoritative state and projection intents."""

    def pending_projections(
        self,
        campaign_id: str | None = None,
    ) -> tuple[CampaignProjectionIntent, ...]:
        """Return pending intents in deterministic order."""

    def acknowledge_projection(self, campaign_id: str, event_id: str) -> bool:
        """Remove one verified pending intent."""


class CampaignProjectionError(RuntimeError):
    """Raised when durable state cannot converge to its audit projection."""


@dataclass(frozen=True, slots=True)
class CampaignProjectionReport:
    scanned: int
    appended: int
    already_present: int
    acknowledged: int


class CampaignProjectionReconciler:
    """Explicitly converge durable intents into the immutable timeline."""

    def __init__(
        self,
        *,
        repository: CampaignProjectionRepository,
        timeline: CampaignTimelineStore,
    ) -> None:
        if not isinstance(repository, CampaignProjectionRepository):
            raise TypeError(
                "repository must implement CampaignProjectionRepository"
            )
        if not isinstance(timeline, CampaignTimelineStore):
            raise TypeError("timeline must implement CampaignTimelineStore")
        self._repository = repository
        self._timeline = timeline

    def reconcile(self, campaign_id: str | None = None) -> CampaignProjectionReport:
        intents = self._repository.pending_projections(campaign_id)
        appended = 0
        already_present = 0
        acknowledged = 0
        for intent in intents:
            timeline = self._timeline.list(intent.campaign_id)
            existing = next(
                (
                    entry
                    for entry in timeline
                    if entry.event.event_id == intent.event_id
                ),
                None,
            )
            if existing is not None:
                if not intent.matches_event(existing.event):
                    raise CampaignProjectionError(
                        f"projection event {intent.event_id!r} conflicts with timeline"
                    )
                already_present += 1
            else:
                sequence = timeline[-1].event.sequence + 1 if timeline else 1
                event = CampaignEvent(
                    event_id=intent.event_id,
                    campaign_id=intent.campaign_id,
                    kind=intent.kind,
                    sequence=sequence,
                    occurred_at=intent.occurred_at,
                    payload=intent.payload,
                )
                try:
                    self._timeline.append(event)
                except TimelineConflictError as exc:
                    raise CampaignProjectionError(
                        f"unable to append projection event {intent.event_id!r}"
                    ) from exc
                appended += 1
            if self._repository.acknowledge_projection(
                intent.campaign_id,
                intent.event_id,
            ):
                acknowledged += 1
        return CampaignProjectionReport(
            scanned=len(intents),
            appended=appended,
            already_present=already_present,
            acknowledged=acknowledged,
        )


@dataclass(frozen=True, slots=True)
class CampaignProjectionSpec:
    kind: CampaignEventKind
    occurred_at: datetime
    payload: Mapping[str, JsonValue] = field(default_factory=dict)
    producer_id: str = "lifecycle"


class CampaignStateProjectionService:
    """Atomically persist state+intent, then explicitly reconcile that campaign."""

    def __init__(
        self,
        *,
        repository: CampaignProjectionRepository,
        reconciler: CampaignProjectionReconciler,
    ) -> None:
        self._repository = repository
        self._reconciler = reconciler

    def persist(
        self,
        record: CampaignRecord,
        projections: Iterable[CampaignProjectionSpec],
        *,
        reconcile: bool = True,
    ) -> CampaignRecord:
        intents = tuple(
            CampaignProjectionIntent(
                campaign_id=record.spec.campaign_id,
                state_revision=record.state.revision,
                kind=projection.kind,
                occurred_at=projection.occurred_at,
                payload=projection.payload,
                producer_id=projection.producer_id,
            )
            for projection in projections
        )
        self._repository.save_with_projections(record, intents)
        if reconcile:
            try:
                self._reconciler.reconcile(record.spec.campaign_id)
            except CampaignProjectionError:
                raise
            except Exception as exc:
                raise CampaignProjectionError(
                    "campaign state is durable but its audit projection remains pending"
                ) from exc
        return record
