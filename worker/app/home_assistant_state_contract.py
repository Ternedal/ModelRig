"""Pure Home Assistant state response contract for dormant T-038 reads.

The module parses a bounded JSON state object returned by a future adapter. It
performs no HTTP request, reads no credential/configuration, and exposes no
Home Assistant attributes to the caller. Exact entity identity is rebound at
this boundary before the state may enter T-038's authority-safe fulfillment.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .home_rig_connector_contract import HomeRigContractError

STATE_SCHEMA = "kaliv-home-assistant-state/v1"
PRODUCTION_ACTIVATION = False
_MAX_RESPONSE_BYTES = 128 * 1024
_MAX_STATE_CHARS = 255
_ENTITY_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


def _entity_id(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise HomeRigContractError(f"{name} must be a string")
    normalized = value.strip().lower()
    if not _ENTITY_ID.fullmatch(normalized) or len(normalized) > 255:
        raise HomeRigContractError(f"{name} must be an exact Home Assistant entity id")
    return normalized


def _time(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HomeRigContractError(f"{name} must be a non-negative integer")
    return value


def _timestamp(value: str, name: str) -> int:
    if not isinstance(value, str) or not value or len(value) > 80:
        raise HomeRigContractError(f"{name} must be a bounded ISO-8601 timestamp")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise HomeRigContractError(f"{name} is not valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HomeRigContractError(f"{name} must include a timezone")
    seconds = int(parsed.astimezone(timezone.utc).timestamp())
    if seconds < 0:
        raise HomeRigContractError(f"{name} predates supported epoch")
    return seconds


def _strict_object(raw: bytes) -> dict[str, Any]:
    if not isinstance(raw, bytes) or not raw or len(raw) > _MAX_RESPONSE_BYTES:
        raise HomeRigContractError("Home Assistant state response size is invalid")

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise HomeRigContractError("Home Assistant state contains duplicate JSON keys")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(
                HomeRigContractError("Home Assistant state contains a non-finite number")
            ),
        )
    except HomeRigContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HomeRigContractError("Home Assistant state response is invalid JSON") from exc
    if not isinstance(value, dict):
        raise HomeRigContractError("Home Assistant state response must be an object")
    return value


@dataclass(frozen=True)
class HomeAssistantStateEvidence:
    entity_id: str
    state: str
    received_at: int
    entity_last_changed_at: int
    entity_last_updated_at: int
    schema: str = STATE_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != STATE_SCHEMA:
            raise HomeRigContractError("unsupported Home Assistant state schema")
        if self.production_activation is not False:
            raise HomeRigContractError("Home Assistant state activation must remain false")
        entity_id = _entity_id(self.entity_id, "entity_id")
        received_at = _time(self.received_at, "received_at")
        changed_at = _time(self.entity_last_changed_at, "entity_last_changed_at")
        updated_at = _time(self.entity_last_updated_at, "entity_last_updated_at")
        if changed_at > received_at or updated_at > received_at:
            raise HomeRigContractError("Home Assistant entity timestamp cannot follow receipt time")
        if changed_at > updated_at:
            raise HomeRigContractError("Home Assistant last_changed cannot follow last_updated")
        if not isinstance(self.state, str) or len(self.state) > _MAX_STATE_CHARS:
            raise HomeRigContractError("Home Assistant state must be a bounded string")
        object.__setattr__(self, "entity_id", entity_id)

    @property
    def observed_at(self) -> int:
        """The read observed this state when the response was received.

        Entity last_updated is metadata about when Home Assistant last changed
        the state object; a stable entity can legitimately keep that timestamp
        for a long time while a fresh GET still proves Home Assistant is online.
        """
        return self.received_at

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "entity_id": self.entity_id,
            "state": self.state,
            "received_at": self.received_at,
            "entity_last_changed_at": self.entity_last_changed_at,
            "entity_last_updated_at": self.entity_last_updated_at,
            "observed_at": self.observed_at,
            "production_activation": False,
        }


def parse_home_assistant_state(
    raw: bytes,
    *,
    expected_entity_id: str,
    received_at: int,
) -> HomeAssistantStateEvidence:
    """Validate one bounded state object and discard all attributes/context."""
    expected = _entity_id(expected_entity_id, "expected_entity_id")
    received_at = _time(received_at, "received_at")
    value = _strict_object(raw)

    entity_id = _entity_id(value.get("entity_id"), "response entity_id")
    if entity_id != expected:
        raise HomeRigContractError("Home Assistant response entity does not match requested entity")

    state = value.get("state")
    if not isinstance(state, str) or len(state) > _MAX_STATE_CHARS:
        raise HomeRigContractError("Home Assistant response state is invalid")
    attributes = value.get("attributes")
    if not isinstance(attributes, dict):
        raise HomeRigContractError("Home Assistant response attributes must be an object")

    last_changed = _timestamp(value.get("last_changed"), "last_changed")
    last_updated_raw = value.get("last_updated", value.get("last_changed"))
    last_updated = _timestamp(last_updated_raw, "last_updated")

    return HomeAssistantStateEvidence(
        entity_id=entity_id,
        state=state,
        received_at=received_at,
        entity_last_changed_at=last_changed,
        entity_last_updated_at=last_updated,
    )
