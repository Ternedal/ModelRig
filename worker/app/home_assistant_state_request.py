"""Pure Home Assistant entity-state request plan for dormant T-038 reads.

The plan is built only from an already-authorized T-038 read claim. It fixes
method/path/response expectations and keeps host/base URL plus credential
injection outside this module. No request is sent here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .home_rig_connector_contract import HomeRigContractError
from .home_rig_read_boundary import HomeRigReadClaim

REQUEST_SCHEMA = "kaliv-home-assistant-state-request/v1"
PRODUCTION_ACTIVATION = False
_MAX_RESPONSE_BYTES = 128 * 1024
_ENTITY_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


def _entity_id(value: str) -> str:
    if not isinstance(value, str):
        raise HomeRigContractError("Home Assistant request entity_id must be a string")
    normalized = value.strip().lower()
    if not _ENTITY_ID.fullmatch(normalized) or len(normalized) > 255:
        raise HomeRigContractError("Home Assistant request entity_id is invalid")
    return normalized


@dataclass(frozen=True)
class HomeAssistantStateRequestPlan:
    grant_id: str
    scope_sha256: str
    entity_id: str
    method: Literal["GET"] = "GET"
    service: Literal["home_assistant"] = "home_assistant"
    response_kind: Literal["json"] = "json"
    expected_content_type: Literal["application/json"] = "application/json"
    max_response_bytes: int = _MAX_RESPONSE_BYTES
    follow_redirects: bool = False
    schema: str = REQUEST_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != REQUEST_SCHEMA:
            raise HomeRigContractError("unsupported Home Assistant request schema")
        if self.production_activation is not False:
            raise HomeRigContractError("Home Assistant request activation must remain false")
        if self.method != "GET" or self.service != "home_assistant":
            raise HomeRigContractError("Home Assistant request method/service is fixed")
        if self.response_kind != "json" or self.expected_content_type != "application/json":
            raise HomeRigContractError("Home Assistant request response contract is fixed")
        if self.max_response_bytes != _MAX_RESPONSE_BYTES:
            raise HomeRigContractError("Home Assistant request response limit is fixed")
        if self.follow_redirects is not False:
            raise HomeRigContractError("Home Assistant request redirects are forbidden")
        object.__setattr__(self, "entity_id", _entity_id(self.entity_id))

    @property
    def path(self) -> str:
        return f"/api/states/{self.entity_id}"

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "grant_id": self.grant_id,
            "scope_sha256": self.scope_sha256,
            "entity_id": self.entity_id,
            "method": "GET",
            "service": "home_assistant",
            "path": self.path,
            "response_kind": "json",
            "expected_content_type": "application/json",
            "max_response_bytes": self.max_response_bytes,
            "follow_redirects": False,
            "production_activation": False,
        }


def build_home_assistant_state_request(
    claim: HomeRigReadClaim,
) -> HomeAssistantStateRequestPlan:
    """Convert one exact entity-state claim into a non-executing request plan."""
    if not isinstance(claim, HomeRigReadClaim):
        raise HomeRigContractError("Home Assistant request requires HomeRigReadClaim")
    if claim.target_kind != "entity" or claim.operation != "entity_state":
        raise HomeRigContractError("Home Assistant state request requires entity_state claim")
    entity_id = _entity_id(claim.target_id)
    return HomeAssistantStateRequestPlan(
        grant_id=claim.grant_id,
        scope_sha256=claim.scope_sha256,
        entity_id=entity_id,
    )
