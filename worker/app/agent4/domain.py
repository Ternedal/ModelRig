"""Agent 4 campaign domain primitives.

The module is deliberately independent from Agent 3. Agent 4 owns orchestration
state and delegates execution through contracts defined in ``contracts.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import IntEnum, StrEnum
import math
from types import MappingProxyType
from typing import Any, Mapping, TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class CampaignValidationError(ValueError):
    """Raised when a campaign value cannot satisfy the Agent 4 contract."""


class CampaignTransitionError(ValueError):
    """Raised when a campaign state transition is not allowed."""


class CampaignPriority(IntEnum):
    LOW = 10
    NORMAL = 20
    HIGH = 30
    CRITICAL = 40


class CampaignStatus(StrEnum):
    QUEUED = "queued"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    PAUSING = "pausing"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @property
    def terminal(self) -> bool:
        return self in {
            CampaignStatus.CANCELLED,
            CampaignStatus.SUCCEEDED,
            CampaignStatus.FAILED,
        }


class CampaignEventKind(StrEnum):
    CREATED = "created"
    SCHEDULED = "scheduled"
    STARTED = "started"
    PAUSE_REQUESTED = "pause_requested"
    PAUSED = "paused"
    RESUMED = "resumed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    CHECKPOINTED = "checkpointed"
    RETRY_SCHEDULED = "retry_scheduled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RECOVERED = "recovered"


_ALLOWED_TRANSITIONS: Mapping[CampaignStatus, frozenset[CampaignStatus]] = {
    CampaignStatus.QUEUED: frozenset(
        {
            CampaignStatus.SCHEDULED,
            CampaignStatus.RUNNING,
            CampaignStatus.CANCELLED,
        }
    ),
    CampaignStatus.SCHEDULED: frozenset(
        {
            CampaignStatus.QUEUED,
            CampaignStatus.RUNNING,
            CampaignStatus.CANCELLED,
        }
    ),
    CampaignStatus.RUNNING: frozenset(
        {
            CampaignStatus.PAUSING,
            CampaignStatus.CANCELLING,
            CampaignStatus.SUCCEEDED,
            CampaignStatus.FAILED,
        }
    ),
    CampaignStatus.PAUSING: frozenset(
        {
            CampaignStatus.PAUSED,
            CampaignStatus.CANCELLING,
            CampaignStatus.FAILED,
        }
    ),
    CampaignStatus.PAUSED: frozenset(
        {
            CampaignStatus.QUEUED,
            CampaignStatus.SCHEDULED,
            CampaignStatus.RUNNING,
            CampaignStatus.CANCELLING,
            CampaignStatus.CANCELLED,
        }
    ),
    CampaignStatus.CANCELLING: frozenset(
        {
            CampaignStatus.CANCELLED,
            CampaignStatus.FAILED,
        }
    ),
    CampaignStatus.CANCELLED: frozenset(),
    CampaignStatus.SUCCEEDED: frozenset(),
    CampaignStatus.FAILED: frozenset(),
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise CampaignValidationError(f"{field_name} must not be empty")
    return normalized


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CampaignValidationError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


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


def _format_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CampaignValidationError(f"{field_name} is not a valid datetime") from exc
    return _require_aware(parsed, field_name)


@dataclass(frozen=True, slots=True)
class CampaignSpec:
    campaign_id: str
    name: str
    workflow: str
    created_at: datetime = field(default_factory=utc_now)
    priority: CampaignPriority = CampaignPriority.NORMAL
    scheduled_for: datetime | None = None
    max_attempts: int = 1
    parameters: Mapping[str, JsonValue] = field(default_factory=dict)
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "campaign_id", _require_text(self.campaign_id, "campaign_id")
        )
        object.__setattr__(self, "name", _require_text(self.name, "name"))
        object.__setattr__(self, "workflow", _require_text(self.workflow, "workflow"))
        object.__setattr__(
            self, "created_at", _require_aware(self.created_at, "created_at")
        )
        if self.scheduled_for is not None:
            object.__setattr__(
                self,
                "scheduled_for",
                _require_aware(self.scheduled_for, "scheduled_for"),
            )
        try:
            priority = CampaignPriority(self.priority)
        except ValueError as exc:
            raise CampaignValidationError("priority is not supported") from exc
        object.__setattr__(self, "priority", priority)
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or self.max_attempts < 1
        ):
            raise CampaignValidationError("max_attempts must be an integer of at least 1")
        object.__setattr__(
            self, "parameters", _freeze_json(self.parameters, "parameters")
        )
        object.__setattr__(self, "metadata", _freeze_json(self.metadata, "metadata"))

    @property
    def ready_at(self) -> datetime:
        return self.scheduled_for or self.created_at

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "campaign_id": self.campaign_id,
            "name": self.name,
            "workflow": self.workflow,
            "created_at": _format_datetime(self.created_at),
            "priority": int(self.priority),
            "scheduled_for": (
                _format_datetime(self.scheduled_for)
                if self.scheduled_for is not None
                else None
            ),
            "max_attempts": self.max_attempts,
            "parameters": _thaw_json(self.parameters),
            "metadata": _thaw_json(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignSpec":
        scheduled_for = value.get("scheduled_for")
        return cls(
            campaign_id=str(value["campaign_id"]),
            name=str(value["name"]),
            workflow=str(value["workflow"]),
            created_at=_parse_datetime(str(value["created_at"]), "created_at"),
            priority=CampaignPriority(int(value.get("priority", CampaignPriority.NORMAL))),
            scheduled_for=(
                _parse_datetime(str(scheduled_for), "scheduled_for")
                if scheduled_for is not None
                else None
            ),
            max_attempts=int(value.get("max_attempts", 1)),
            parameters=value.get("parameters", {}),
            metadata=value.get("metadata", {}),
        )


@dataclass(frozen=True, slots=True)
class CampaignState:
    campaign_id: str
    status: CampaignStatus = CampaignStatus.QUEUED
    revision: int = 0
    attempt: int = 0
    updated_at: datetime = field(default_factory=utc_now)
    checkpoint_id: str | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "campaign_id", _require_text(self.campaign_id, "campaign_id")
        )
        try:
            status = CampaignStatus(self.status)
        except ValueError as exc:
            raise CampaignValidationError("status is not supported") from exc
        object.__setattr__(self, "status", status)
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
        ):
            raise CampaignValidationError("revision must be a non-negative integer")
        if (
            isinstance(self.attempt, bool)
            or not isinstance(self.attempt, int)
            or self.attempt < 0
        ):
            raise CampaignValidationError("attempt must be a non-negative integer")
        object.__setattr__(
            self, "updated_at", _require_aware(self.updated_at, "updated_at")
        )
        if self.checkpoint_id is not None:
            object.__setattr__(
                self,
                "checkpoint_id",
                _require_text(self.checkpoint_id, "checkpoint_id"),
            )
        if self.last_error is not None:
            object.__setattr__(
                self, "last_error", _require_text(self.last_error, "last_error")
            )
        if self.status is CampaignStatus.FAILED and self.last_error is None:
            raise CampaignValidationError("failed state requires last_error")
        if self.status is not CampaignStatus.FAILED and self.last_error is not None:
            raise CampaignValidationError("last_error is only valid for failed state")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "campaign_id": self.campaign_id,
            "status": self.status.value,
            "revision": self.revision,
            "attempt": self.attempt,
            "updated_at": _format_datetime(self.updated_at),
            "checkpoint_id": self.checkpoint_id,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignState":
        return cls(
            campaign_id=str(value["campaign_id"]),
            status=CampaignStatus(str(value["status"])),
            revision=int(value.get("revision", 0)),
            attempt=int(value.get("attempt", 0)),
            updated_at=_parse_datetime(str(value["updated_at"]), "updated_at"),
            checkpoint_id=(
                str(value["checkpoint_id"])
                if value.get("checkpoint_id") is not None
                else None
            ),
            last_error=(
                str(value["last_error"])
                if value.get("last_error") is not None
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class CampaignEvent:
    event_id: str
    campaign_id: str
    kind: CampaignEventKind
    sequence: int
    occurred_at: datetime = field(default_factory=utc_now)
    payload: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _require_text(self.event_id, "event_id"))
        object.__setattr__(
            self, "campaign_id", _require_text(self.campaign_id, "campaign_id")
        )
        try:
            kind = CampaignEventKind(self.kind)
        except ValueError as exc:
            raise CampaignValidationError("event kind is not supported") from exc
        object.__setattr__(self, "kind", kind)
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 1
        ):
            raise CampaignValidationError("sequence must be an integer of at least 1")
        object.__setattr__(
            self, "occurred_at", _require_aware(self.occurred_at, "occurred_at")
        )
        object.__setattr__(self, "payload", _freeze_json(self.payload, "payload"))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "event_id": self.event_id,
            "campaign_id": self.campaign_id,
            "kind": self.kind.value,
            "sequence": self.sequence,
            "occurred_at": _format_datetime(self.occurred_at),
            "payload": _thaw_json(self.payload),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignEvent":
        return cls(
            event_id=str(value["event_id"]),
            campaign_id=str(value["campaign_id"]),
            kind=CampaignEventKind(str(value["kind"])),
            sequence=int(value["sequence"]),
            occurred_at=_parse_datetime(str(value["occurred_at"]), "occurred_at"),
            payload=value.get("payload", {}),
        )


@dataclass(frozen=True, slots=True)
class CampaignRecord:
    spec: CampaignSpec
    state: CampaignState

    def __post_init__(self) -> None:
        if self.spec.campaign_id != self.state.campaign_id:
            raise CampaignValidationError(
                "campaign spec and state must use the same campaign_id"
            )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": "modelrig-agent4/campaign-record/v1",
            "spec": self.spec.to_dict(),
            "state": self.state.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignRecord":
        if value.get("schema") != "modelrig-agent4/campaign-record/v1":
            raise CampaignValidationError("campaign record schema is not supported")
        spec = value.get("spec")
        state = value.get("state")
        if not isinstance(spec, Mapping) or not isinstance(state, Mapping):
            raise CampaignValidationError("campaign record must contain spec and state")
        return cls(
            spec=CampaignSpec.from_dict(spec),
            state=CampaignState.from_dict(state),
        )


def transition_campaign(
    state: CampaignState,
    target: CampaignStatus,
    *,
    occurred_at: datetime | None = None,
    checkpoint_id: str | None = None,
    error: str | None = None,
) -> CampaignState:
    """Return the next immutable state or reject an illegal transition."""

    target = CampaignStatus(target)
    if target not in _ALLOWED_TRANSITIONS[state.status]:
        raise CampaignTransitionError(
            f"cannot transition campaign from {state.status.value} to {target.value}"
        )
    if target is CampaignStatus.FAILED:
        if error is None or not error.strip():
            raise CampaignTransitionError("failed transition requires an error")
        last_error = error.strip()
    else:
        if error is not None:
            raise CampaignTransitionError("error is only valid for failed transition")
        last_error = None

    next_attempt = state.attempt
    if target is CampaignStatus.RUNNING and state.status is not CampaignStatus.RUNNING:
        next_attempt += 1

    return replace(
        state,
        status=target,
        revision=state.revision + 1,
        attempt=next_attempt,
        updated_at=_require_aware(occurred_at or utc_now(), "occurred_at"),
        checkpoint_id=checkpoint_id if checkpoint_id is not None else state.checkpoint_id,
        last_error=last_error,
    )
