"""Durable, transport-neutral ADR-A4-008 handoff intent values.

This module is deliberately dormant. It stores immutable request and
acknowledgement facts only; it never invokes an executor, queries outcomes,
starts background work, or mutates campaign state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, TypeAlias

from .domain import CampaignValidationError, JsonValue, _require_text
from .handoff import (
    CampaignDispatchAcknowledgement,
    CampaignDispatchRequest,
    CampaignSignalAcknowledgement,
    CampaignSignalRequest,
)

_HANDOFF_INTENT_SCHEMA = "modelrig-agent4/handoff-intent/v1"

CampaignHandoffRequest: TypeAlias = (
    CampaignDispatchRequest | CampaignSignalRequest
)
CampaignHandoffAcknowledgement: TypeAlias = (
    CampaignDispatchAcknowledgement | CampaignSignalAcknowledgement
)


class CampaignHandoffKind(StrEnum):
    DISPATCH = "dispatch"
    SIGNAL = "signal"


class CampaignHandoffPhase(StrEnum):
    REQUESTED = "requested"
    ACKNOWLEDGED = "acknowledged"


@dataclass(frozen=True, slots=True)
class CampaignHandoffIntent:
    """One durable handoff request and, optionally, its authoritative ack."""

    campaign_id: str
    state_revision: int
    request: CampaignHandoffRequest
    phase: CampaignHandoffPhase = CampaignHandoffPhase.REQUESTED
    acknowledgement: CampaignHandoffAcknowledgement | None = None
    intent_id: str = ""

    def __post_init__(self) -> None:
        campaign_id = _require_text(self.campaign_id, "campaign_id")
        if (
            isinstance(self.state_revision, bool)
            or not isinstance(self.state_revision, int)
            or self.state_revision < 0
        ):
            raise CampaignValidationError(
                "state_revision must be a non-negative integer"
            )
        try:
            phase = CampaignHandoffPhase(self.phase)
        except ValueError as exc:
            raise CampaignValidationError(
                "handoff intent phase is not supported"
            ) from exc

        request = self.request
        acknowledgement = self.acknowledgement
        if isinstance(request, CampaignDispatchRequest):
            expected_kind = CampaignHandoffKind.DISPATCH
            expected_id = request.dispatch_id
            request_revision = request.campaign_revision
            acknowledgement_type = CampaignDispatchAcknowledgement
            acknowledgement_id = (
                acknowledgement.dispatch_id
                if isinstance(acknowledgement, CampaignDispatchAcknowledgement)
                else None
            )
        elif isinstance(request, CampaignSignalRequest):
            expected_kind = CampaignHandoffKind.SIGNAL
            expected_id = request.signal_id
            request_revision = request.resulting_revision
            acknowledgement_type = CampaignSignalAcknowledgement
            acknowledgement_id = (
                acknowledgement.signal_id
                if isinstance(acknowledgement, CampaignSignalAcknowledgement)
                else None
            )
        else:
            raise CampaignValidationError(
                "request must be a dispatch or signal request"
            )

        if request.campaign_id != campaign_id:
            raise CampaignValidationError(
                "handoff request must use the intent campaign_id"
            )
        if request_revision != self.state_revision:
            raise CampaignValidationError(
                "handoff request revision must match state_revision"
            )
        if self.intent_id and self.intent_id != expected_id:
            raise CampaignValidationError(
                "handoff intent_id does not match its request identity"
            )

        if phase is CampaignHandoffPhase.REQUESTED:
            if acknowledgement is not None:
                raise CampaignValidationError(
                    "requested handoff intent must not carry an acknowledgement"
                )
        else:
            if not isinstance(acknowledgement, acknowledgement_type):
                raise CampaignValidationError(
                    f"{expected_kind.value} handoff requires a matching acknowledgement type"
                )
            if acknowledgement_id != expected_id:
                raise CampaignValidationError(
                    "handoff acknowledgement identity does not match its request"
                )

        object.__setattr__(self, "campaign_id", campaign_id)
        object.__setattr__(self, "phase", phase)
        object.__setattr__(self, "intent_id", expected_id)

    @property
    def kind(self) -> CampaignHandoffKind:
        if isinstance(self.request, CampaignDispatchRequest):
            return CampaignHandoffKind.DISPATCH
        return CampaignHandoffKind.SIGNAL

    def acknowledge(
        self,
        acknowledgement: CampaignHandoffAcknowledgement,
    ) -> "CampaignHandoffIntent":
        """Return an acknowledged copy; identical retries are idempotent."""

        if self.phase is CampaignHandoffPhase.ACKNOWLEDGED:
            if self.acknowledgement == acknowledgement:
                return self
            raise CampaignValidationError(
                "handoff intent already has a conflicting acknowledgement"
            )
        return CampaignHandoffIntent(
            campaign_id=self.campaign_id,
            state_revision=self.state_revision,
            request=self.request,
            phase=CampaignHandoffPhase.ACKNOWLEDGED,
            acknowledgement=acknowledgement,
            intent_id=self.intent_id,
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": _HANDOFF_INTENT_SCHEMA,
            "kind": self.kind.value,
            "phase": self.phase.value,
            "campaign_id": self.campaign_id,
            "state_revision": self.state_revision,
            "intent_id": self.intent_id,
            "request": self.request.to_dict(),
            "acknowledgement": (
                self.acknowledgement.to_dict()
                if self.acknowledgement is not None
                else None
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignHandoffIntent":
        if value.get("schema") != _HANDOFF_INTENT_SCHEMA:
            raise CampaignValidationError("handoff intent schema is not supported")
        try:
            kind = CampaignHandoffKind(value["kind"])
        except (KeyError, ValueError) as exc:
            raise CampaignValidationError(
                "handoff intent kind is not supported"
            ) from exc
        raw_request = value.get("request")
        if not isinstance(raw_request, Mapping):
            raise CampaignValidationError("handoff intent request must be an object")
        raw_acknowledgement = value.get("acknowledgement")
        if raw_acknowledgement is not None and not isinstance(
            raw_acknowledgement,
            Mapping,
        ):
            raise CampaignValidationError(
                "handoff intent acknowledgement must be an object or null"
            )

        if kind is CampaignHandoffKind.DISPATCH:
            request: CampaignHandoffRequest = CampaignDispatchRequest.from_dict(
                raw_request
            )
            acknowledgement: CampaignHandoffAcknowledgement | None = (
                CampaignDispatchAcknowledgement.from_dict(raw_acknowledgement)
                if raw_acknowledgement is not None
                else None
            )
        else:
            request = CampaignSignalRequest.from_dict(raw_request)
            acknowledgement = (
                CampaignSignalAcknowledgement.from_dict(raw_acknowledgement)
                if raw_acknowledgement is not None
                else None
            )

        return cls(
            campaign_id=value["campaign_id"],
            state_revision=value["state_revision"],
            request=request,
            phase=value["phase"],
            acknowledgement=acknowledgement,
            intent_id=value["intent_id"],
        )


__all__ = [
    "CampaignHandoffAcknowledgement",
    "CampaignHandoffIntent",
    "CampaignHandoffKind",
    "CampaignHandoffPhase",
    "CampaignHandoffRequest",
]
