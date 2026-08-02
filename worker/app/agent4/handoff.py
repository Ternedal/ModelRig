"""Pure ADR-A4-008 side-effect identities and transport-neutral contracts.

This module is deliberately dormant. It defines immutable values only: no
store, runtime, thread, timer, polling loop, route or Agent 3 execution is
created by importing or constructing these objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
from typing import Any, Mapping, Protocol, runtime_checkable

from .domain import (
    CampaignValidationError,
    JsonValue,
    _freeze_json,
    _require_text,
    _thaw_json,
)

_IDENTITY_SCHEMA_VERSION = 1
_DISPATCH_REQUEST_SCHEMA = "modelrig-agent4/dispatch-request/v1"
_DISPATCH_ACK_SCHEMA = "modelrig-agent4/dispatch-acknowledgement/v1"
_SIGNAL_REQUEST_SCHEMA = "modelrig-agent4/signal-request/v1"
_SIGNAL_ACK_SCHEMA = "modelrig-agent4/signal-acknowledgement/v1"
_OUTCOME_SCHEMA = "modelrig-agent4/dispatch-outcome/v1"


class CampaignSignalType(StrEnum):
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"


class DispatchOutcomeKind(StrEnum):
    NOT_DISPATCHED = "not_dispatched"
    UNKNOWN = "unknown"
    ACCEPTED = "accepted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


def _positive_integer(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CampaignValidationError(f"{field_name} must be an integer of at least 1")
    return value


def _optional_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, field_name)


def _canonical_json(value: Mapping[str, JsonValue]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _identity(namespace: str, values: Mapping[str, JsonValue]) -> str:
    digest = hashlib.sha256(_canonical_json(values)).hexdigest()
    return f"{namespace}:v{_IDENTITY_SCHEMA_VERSION}:{digest}"


def campaign_dispatch_id(campaign_id: str, attempt: int) -> str:
    campaign_id = _require_text(campaign_id, "campaign_id")
    attempt = _positive_integer(attempt, "attempt")
    return _identity(
        "agent4-dispatch",
        {
            "campaign_id": campaign_id,
            "attempt": attempt,
            "operation": "dispatch",
            "identity_schema_version": _IDENTITY_SCHEMA_VERSION,
        },
    )


def campaign_signal_id(
    campaign_id: str,
    attempt: int,
    signal_type: CampaignSignalType,
    resulting_revision: int,
) -> str:
    campaign_id = _require_text(campaign_id, "campaign_id")
    attempt = _positive_integer(attempt, "attempt")
    resulting_revision = _positive_integer(resulting_revision, "resulting_revision")
    try:
        signal_type = CampaignSignalType(signal_type)
    except ValueError as exc:
        raise CampaignValidationError("signal_type is not supported") from exc
    return _identity(
        "agent4-signal",
        {
            "campaign_id": campaign_id,
            "attempt": attempt,
            "operation": signal_type.value,
            "resulting_revision": resulting_revision,
            "identity_schema_version": _IDENTITY_SCHEMA_VERSION,
        },
    )


@dataclass(frozen=True, slots=True)
class CampaignDispatchRequest:
    campaign_id: str
    attempt: int
    workflow: str
    campaign_revision: int
    parameters: Mapping[str, JsonValue] = field(default_factory=dict)
    dispatch_id: str = ""

    def __post_init__(self) -> None:
        campaign_id = _require_text(self.campaign_id, "campaign_id")
        attempt = _positive_integer(self.attempt, "attempt")
        workflow = _require_text(self.workflow, "workflow")
        campaign_revision = _positive_integer(
            self.campaign_revision,
            "campaign_revision",
        )
        parameters = _freeze_json(self.parameters, "parameters")
        expected_id = campaign_dispatch_id(campaign_id, attempt)
        if self.dispatch_id and self.dispatch_id != expected_id:
            raise CampaignValidationError(
                "dispatch_id does not match its deterministic identity"
            )
        object.__setattr__(self, "campaign_id", campaign_id)
        object.__setattr__(self, "attempt", attempt)
        object.__setattr__(self, "workflow", workflow)
        object.__setattr__(self, "campaign_revision", campaign_revision)
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "dispatch_id", expected_id)

    @property
    def request_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_dict())).hexdigest()

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": _DISPATCH_REQUEST_SCHEMA,
            "dispatch_id": self.dispatch_id,
            "campaign_id": self.campaign_id,
            "attempt": self.attempt,
            "workflow": self.workflow,
            "campaign_revision": self.campaign_revision,
            "parameters": _thaw_json(self.parameters),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignDispatchRequest":
        if value.get("schema") != _DISPATCH_REQUEST_SCHEMA:
            raise CampaignValidationError("dispatch request schema is not supported")
        return cls(
            dispatch_id=str(value["dispatch_id"]),
            campaign_id=str(value["campaign_id"]),
            attempt=value["attempt"],
            workflow=str(value["workflow"]),
            campaign_revision=value["campaign_revision"],
            parameters=value.get("parameters", {}),
        )


@dataclass(frozen=True, slots=True)
class CampaignDispatchAcknowledgement:
    dispatch_id: str
    runtime_reference: str
    evidence_pointer: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "dispatch_id", _require_text(self.dispatch_id, "dispatch_id"))
        object.__setattr__(
            self,
            "runtime_reference",
            _require_text(self.runtime_reference, "runtime_reference"),
        )
        object.__setattr__(
            self,
            "evidence_pointer",
            _optional_text(self.evidence_pointer, "evidence_pointer"),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": _DISPATCH_ACK_SCHEMA,
            "dispatch_id": self.dispatch_id,
            "runtime_reference": self.runtime_reference,
            "evidence_pointer": self.evidence_pointer,
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "CampaignDispatchAcknowledgement":
        if value.get("schema") != _DISPATCH_ACK_SCHEMA:
            raise CampaignValidationError(
                "dispatch acknowledgement schema is not supported"
            )
        return cls(
            dispatch_id=str(value["dispatch_id"]),
            runtime_reference=str(value["runtime_reference"]),
            evidence_pointer=(
                str(value["evidence_pointer"])
                if value.get("evidence_pointer") is not None
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class CampaignSignalRequest:
    campaign_id: str
    attempt: int
    signal_type: CampaignSignalType
    resulting_revision: int
    signal_id: str = ""

    def __post_init__(self) -> None:
        campaign_id = _require_text(self.campaign_id, "campaign_id")
        attempt = _positive_integer(self.attempt, "attempt")
        resulting_revision = _positive_integer(
            self.resulting_revision,
            "resulting_revision",
        )
        try:
            signal_type = CampaignSignalType(self.signal_type)
        except ValueError as exc:
            raise CampaignValidationError("signal_type is not supported") from exc
        expected_id = campaign_signal_id(
            campaign_id,
            attempt,
            signal_type,
            resulting_revision,
        )
        if self.signal_id and self.signal_id != expected_id:
            raise CampaignValidationError(
                "signal_id does not match its deterministic identity"
            )
        object.__setattr__(self, "campaign_id", campaign_id)
        object.__setattr__(self, "attempt", attempt)
        object.__setattr__(self, "signal_type", signal_type)
        object.__setattr__(self, "resulting_revision", resulting_revision)
        object.__setattr__(self, "signal_id", expected_id)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": _SIGNAL_REQUEST_SCHEMA,
            "signal_id": self.signal_id,
            "campaign_id": self.campaign_id,
            "attempt": self.attempt,
            "signal_type": self.signal_type.value,
            "resulting_revision": self.resulting_revision,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignSignalRequest":
        if value.get("schema") != _SIGNAL_REQUEST_SCHEMA:
            raise CampaignValidationError("signal request schema is not supported")
        return cls(
            signal_id=str(value["signal_id"]),
            campaign_id=str(value["campaign_id"]),
            attempt=value["attempt"],
            signal_type=CampaignSignalType(str(value["signal_type"])),
            resulting_revision=value["resulting_revision"],
        )


@dataclass(frozen=True, slots=True)
class CampaignSignalAcknowledgement:
    signal_id: str
    evidence_pointer: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "signal_id", _require_text(self.signal_id, "signal_id"))
        object.__setattr__(
            self,
            "evidence_pointer",
            _optional_text(self.evidence_pointer, "evidence_pointer"),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": _SIGNAL_ACK_SCHEMA,
            "signal_id": self.signal_id,
            "evidence_pointer": self.evidence_pointer,
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "CampaignSignalAcknowledgement":
        if value.get("schema") != _SIGNAL_ACK_SCHEMA:
            raise CampaignValidationError(
                "signal acknowledgement schema is not supported"
            )
        return cls(
            signal_id=str(value["signal_id"]),
            evidence_pointer=(
                str(value["evidence_pointer"])
                if value.get("evidence_pointer") is not None
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class CampaignDispatchOutcome:
    dispatch_id: str
    kind: DispatchOutcomeKind
    runtime_reference: str | None = None
    evidence_pointer: str | None = None
    error: str | None = None
    resources_released: bool | None = None

    def __post_init__(self) -> None:
        dispatch_id = _require_text(self.dispatch_id, "dispatch_id")
        try:
            kind = DispatchOutcomeKind(self.kind)
        except ValueError as exc:
            raise CampaignValidationError("dispatch outcome is not supported") from exc
        runtime_reference = _optional_text(
            self.runtime_reference,
            "runtime_reference",
        )
        evidence_pointer = _optional_text(
            self.evidence_pointer,
            "evidence_pointer",
        )
        error = _optional_text(self.error, "error")
        if self.resources_released is not None and not isinstance(
            self.resources_released,
            bool,
        ):
            raise CampaignValidationError("resources_released must be a boolean or null")

        if kind is DispatchOutcomeKind.NOT_DISPATCHED:
            if runtime_reference is not None or error is not None:
                raise CampaignValidationError(
                    "not_dispatched must not carry a runtime or execution error"
                )
            if self.resources_released is not True:
                raise CampaignValidationError(
                    "not_dispatched must attest that no runtime holds resources"
                )
        elif kind is DispatchOutcomeKind.UNKNOWN:
            if self.resources_released is not None:
                raise CampaignValidationError(
                    "unknown must not claim a resource disposition"
                )
        elif kind in {DispatchOutcomeKind.ACCEPTED, DispatchOutcomeKind.RUNNING}:
            if runtime_reference is None:
                raise CampaignValidationError(
                    f"{kind.value} requires a runtime_reference"
                )
            if error is not None or self.resources_released is True:
                raise CampaignValidationError(
                    f"{kind.value} cannot claim terminal execution"
                )
        elif kind is DispatchOutcomeKind.COMPLETED:
            if runtime_reference is None or self.resources_released is not True:
                raise CampaignValidationError(
                    "completed requires runtime_reference and released-resource attestation"
                )
            if error is not None:
                raise CampaignValidationError("completed must not carry an error")
        elif kind is DispatchOutcomeKind.FAILED:
            if runtime_reference is None or self.resources_released is not True:
                raise CampaignValidationError(
                    "failed requires runtime_reference and released-resource attestation"
                )
            if error is None:
                raise CampaignValidationError("failed requires an error")

        object.__setattr__(self, "dispatch_id", dispatch_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "runtime_reference", runtime_reference)
        object.__setattr__(self, "evidence_pointer", evidence_pointer)
        object.__setattr__(self, "error", error)

    @property
    def terminal(self) -> bool:
        return self.kind in {
            DispatchOutcomeKind.COMPLETED,
            DispatchOutcomeKind.FAILED,
        }

    @property
    def requires_resource_reconciliation(self) -> bool:
        return self.kind in {
            DispatchOutcomeKind.ACCEPTED,
            DispatchOutcomeKind.RUNNING,
            DispatchOutcomeKind.UNKNOWN,
        }

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": _OUTCOME_SCHEMA,
            "dispatch_id": self.dispatch_id,
            "kind": self.kind.value,
            "runtime_reference": self.runtime_reference,
            "evidence_pointer": self.evidence_pointer,
            "error": self.error,
            "resources_released": self.resources_released,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignDispatchOutcome":
        if value.get("schema") != _OUTCOME_SCHEMA:
            raise CampaignValidationError("dispatch outcome schema is not supported")
        return cls(
            dispatch_id=str(value["dispatch_id"]),
            kind=DispatchOutcomeKind(str(value["kind"])),
            runtime_reference=(
                str(value["runtime_reference"])
                if value.get("runtime_reference") is not None
                else None
            ),
            evidence_pointer=(
                str(value["evidence_pointer"])
                if value.get("evidence_pointer") is not None
                else None
            ),
            error=str(value["error"]) if value.get("error") is not None else None,
            resources_released=value.get("resources_released"),
        )


@runtime_checkable
class CampaignHandoffExecutor(Protocol):
    """The ADR-A4-008 executor contract, introduced before runtime wiring."""

    def dispatch(
        self,
        request: CampaignDispatchRequest,
    ) -> CampaignDispatchAcknowledgement:
        """Idempotently accept one deterministic campaign dispatch."""

    def signal(
        self,
        request: CampaignSignalRequest,
    ) -> CampaignSignalAcknowledgement:
        """Deliver one deterministic lifecycle signal at most once effectively."""

    def query_outcome(self, dispatch_id: str) -> CampaignDispatchOutcome:
        """Return one authoritative or explicitly unknown dispatch outcome."""
