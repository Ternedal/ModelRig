"""Strict read-only RigGate v1 wire contract for T-038.

This is the first definition of what ModelRig means by ``RigGate``.  It is not
an alias for the local ``rig_status`` tool and it has no wake/control method.
One response represents one exact scoped rig read: health OR power/readiness.
Extra fields are rejected so a future RigGate cannot silently broaden what
crosses the connector boundary.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from .home_rig_connector_contract import HomeRigContractError

WIRE_SCHEMA = "riggate-read/v1"
EVIDENCE_SCHEMA = "kaliv-riggate-state-evidence/v1"
PRODUCTION_ACTIVATION = False
MAX_RESPONSE_BYTES = 64 * 1024

RigGateOperation = Literal["rig_health", "rig_power_readiness"]

_RIG_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_STATE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/+%-]{0,255}$")
_OPERATIONS = {"rig_health", "rig_power_readiness"}
_REQUIRED_KEYS = {"schema", "rig_id", "operation", "state", "observed_at"}


def _time(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HomeRigContractError(f"{name} must be a non-negative integer")
    return value


def _rig_id(value: str) -> str:
    if not isinstance(value, str):
        raise HomeRigContractError("RigGate rig_id must be a string")
    normalized = value.strip().lower()
    if not _RIG_ID.fullmatch(normalized):
        raise HomeRigContractError("RigGate rig_id must be a stable slug")
    return normalized


def _operation(value: str) -> RigGateOperation:
    if value not in _OPERATIONS:
        raise HomeRigContractError("RigGate operation is unsupported")
    return value  # type: ignore[return-value]


def _state(value: str) -> str:
    if not isinstance(value, str) or not _STATE.fullmatch(value):
        raise HomeRigContractError("RigGate state is invalid")
    return value


def _source_time(value: str) -> int:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise HomeRigContractError("RigGate observed_at must be a bounded timestamp")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise HomeRigContractError("RigGate observed_at is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HomeRigContractError("RigGate observed_at must include timezone")
    seconds = parsed.astimezone(timezone.utc).timestamp()
    if not math.isfinite(seconds) or seconds < 0 or seconds != int(seconds):
        raise HomeRigContractError("RigGate observed_at must resolve to whole non-negative seconds")
    return int(seconds)


def _reject_constant(value: str):
    raise HomeRigContractError(f"RigGate JSON constant {value!r} is forbidden")


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise HomeRigContractError("RigGate response contains duplicate JSON keys")
        result[key] = value
    return result


@dataclass(frozen=True)
class RigGateStateEvidence:
    rig_id: str
    operation: RigGateOperation
    state: str
    observed_at: int
    received_at: int
    schema: str = EVIDENCE_SCHEMA
    source: str = "riggate"
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != EVIDENCE_SCHEMA:
            raise HomeRigContractError("unsupported RigGate evidence schema")
        if self.production_activation is not False or self.source != "riggate":
            raise HomeRigContractError("RigGate evidence must remain dormant and source-bound")
        object.__setattr__(self, "rig_id", _rig_id(self.rig_id))
        object.__setattr__(self, "operation", _operation(self.operation))
        object.__setattr__(self, "state", _state(self.state))
        observed = _time(self.observed_at, "observed_at")
        received = _time(self.received_at, "received_at")
        if observed > received:
            raise HomeRigContractError("RigGate observation cannot be from the future")

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "source": self.source,
            "rig_id": self.rig_id,
            "operation": self.operation,
            "state": self.state,
            "observed_at": self.observed_at,
            "received_at": self.received_at,
            "production_activation": False,
        }


def parse_riggate_state(
    body: bytes,
    *,
    expected_rig_id: str,
    expected_operation: RigGateOperation,
    received_at: int,
) -> RigGateStateEvidence:
    """Parse exactly one RigGate v1 status response and reject any scope drift."""
    expected_rig_id = _rig_id(expected_rig_id)
    expected_operation = _operation(expected_operation)
    received_at = _time(received_at, "received_at")
    if not isinstance(body, bytes) or not 1 <= len(body) <= MAX_RESPONSE_BYTES:
        raise HomeRigContractError("RigGate response size is invalid")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HomeRigContractError("RigGate response is not UTF-8") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise HomeRigContractError("RigGate response is not valid JSON") from exc
    if not isinstance(value, dict) or set(value) != _REQUIRED_KEYS:
        raise HomeRigContractError("RigGate response shape is not exact v1")
    if value["schema"] != WIRE_SCHEMA:
        raise HomeRigContractError("RigGate response schema is unsupported")
    rig_id = _rig_id(value["rig_id"])  # type: ignore[arg-type]
    operation = _operation(value["operation"])  # type: ignore[arg-type]
    state = _state(value["state"])  # type: ignore[arg-type]
    observed_at = _source_time(value["observed_at"])  # type: ignore[arg-type]
    if rig_id != expected_rig_id:
        raise HomeRigContractError("RigGate rig_id does not match exact read claim")
    if operation != expected_operation:
        raise HomeRigContractError("RigGate operation does not match exact read claim")
    if observed_at > received_at:
        raise HomeRigContractError("RigGate observation cannot be from the future")
    return RigGateStateEvidence(
        rig_id=rig_id,
        operation=operation,
        state=state,
        observed_at=observed_at,
        received_at=received_at,
    )
