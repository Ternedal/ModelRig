"""Pure authorized Home Assistant state request plan for dormant T-038.

The plan is non-executing. It can only be built from an exact T-038 read claim
plus a permission-authorized T-032 read lease, and the durable grant is checked
again at construction time. Host/base URL, credentials, headers, sockets and
HTTP execution are deliberately outside this module.

A future transport still has to claim the lease immediately before I/O; this
module only proves which immutable request that transport would be allowed to
send.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal

from .home_rig_connector_contract import (
    HomeRigContractError,
    HomeRigDenied,
    HomeRigGrantStore,
    build_home_rig_sharing_request,
)
from .home_rig_read_boundary import HomeRigReadClaim
from .home_rig_read_lease import HomeRigReadLease, claim_digest

REQUEST_SCHEMA = "kaliv-home-assistant-state-request/v1"
PRODUCTION_ACTIVATION = False
_MAX_RESPONSE_BYTES = 128 * 1024
_MAX_REQUEST_ATTEMPTS = 1
_ENTITY_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
_GRANT_ID = re.compile(r"^hrg_[0-9a-f]{32}$")
_RECEIPT_ID = re.compile(r"^dsr_[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class HomeAssistantStateRequestError(HomeRigContractError):
    pass


class HomeAssistantStateRequestDenied(HomeRigDenied):
    pass


def _time(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HomeAssistantStateRequestError(f"{name} must be a non-negative integer")
    return value


def _entity_id(value: str) -> str:
    if not isinstance(value, str):
        raise HomeAssistantStateRequestError("entity_id must be a string")
    normalized = value.strip().lower()
    if not _ENTITY_ID.fullmatch(normalized) or len(normalized) > 255:
        raise HomeAssistantStateRequestError("entity_id is invalid")
    return normalized


def _canonical(value: dict) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sharing_request(grant, claim: HomeRigReadClaim):
    """Rebuild the exact T-032 identity used by the lease, without I/O."""
    digest = claim_digest(claim)
    return build_home_rig_sharing_request(
        grant.scope,
        target_kind="entity",
        data_category="private",
        purpose_code="status_read",
        purpose=f"Read explicitly scoped Home Assistant state for {claim.target_id}",
        summary=f"Home Assistant state: {claim.target_id}",
        content_sha256=digest,
        max_bytes=4096,
    )


@dataclass(frozen=True)
class HomeAssistantStateRequestPlan:
    grant_id: str
    scope_sha256: str
    claim_sha256: str
    sharing_request_digest: str
    sharing_receipt_id: str
    entity_id: str
    authorized_at: int
    expires_at: int
    method: Literal["GET"] = "GET"
    service: Literal["home_assistant"] = "home_assistant"
    response_kind: Literal["json"] = "json"
    expected_content_type: Literal["application/json"] = "application/json"
    max_response_bytes: int = _MAX_RESPONSE_BYTES
    max_attempts: int = _MAX_REQUEST_ATTEMPTS
    follow_redirects: bool = False
    would_execute: bool = False
    schema: str = REQUEST_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != REQUEST_SCHEMA:
            raise HomeAssistantStateRequestError("unsupported Home Assistant request schema")
        if self.production_activation is not False or self.would_execute is not False:
            raise HomeAssistantStateRequestError("request plan must remain dormant and non-executing")
        if self.method != "GET" or self.service != "home_assistant":
            raise HomeAssistantStateRequestError("request method/service is fixed")
        if self.response_kind != "json" or self.expected_content_type != "application/json":
            raise HomeAssistantStateRequestError("response contract is fixed")
        if self.max_response_bytes != _MAX_RESPONSE_BYTES:
            raise HomeAssistantStateRequestError("response byte budget is fixed")
        if self.max_attempts != 1 or self.follow_redirects is not False:
            raise HomeAssistantStateRequestError("request retries/redirects are forbidden")
        if not isinstance(self.grant_id, str) or not _GRANT_ID.fullmatch(self.grant_id):
            raise HomeAssistantStateRequestError("grant_id is invalid")
        for value, name in (
            (self.scope_sha256, "scope_sha256"),
            (self.claim_sha256, "claim_sha256"),
            (self.sharing_request_digest, "sharing_request_digest"),
        ):
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise HomeAssistantStateRequestError(f"{name} must be lowercase SHA-256")
        if not isinstance(self.sharing_receipt_id, str) or not _RECEIPT_ID.fullmatch(self.sharing_receipt_id):
            raise HomeAssistantStateRequestError("sharing_receipt_id is invalid")
        object.__setattr__(self, "entity_id", _entity_id(self.entity_id))
        authorized_at = _time(self.authorized_at, "authorized_at")
        expires_at = _time(self.expires_at, "expires_at")
        if expires_at <= authorized_at:
            raise HomeAssistantStateRequestError("request authorization is already expired")

    @property
    def path(self) -> str:
        return f"/api/states/{self.entity_id}"

    def digest_payload(self) -> dict:
        return {
            "schema": self.schema,
            "grant_id": self.grant_id,
            "scope_sha256": self.scope_sha256,
            "claim_sha256": self.claim_sha256,
            "sharing_request_digest": self.sharing_request_digest,
            "sharing_receipt_id": self.sharing_receipt_id,
            "entity_id": self.entity_id,
            "authorized_at": self.authorized_at,
            "expires_at": self.expires_at,
            "method": "GET",
            "service": "home_assistant",
            "path": self.path,
            "response_kind": "json",
            "expected_content_type": "application/json",
            "max_response_bytes": self.max_response_bytes,
            "max_attempts": 1,
            "follow_redirects": False,
            "would_execute": False,
            "production_activation": False,
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.digest_payload())).hexdigest()

    def to_dict(self) -> dict:
        return {**self.digest_payload(), "request_plan_sha256": self.digest}


def build_home_assistant_state_request(
    grants: HomeRigGrantStore,
    lease: HomeRigReadLease,
    claim: HomeRigReadClaim,
    *,
    now: int,
) -> HomeAssistantStateRequestPlan:
    """Re-authorize exact authority, then build one non-executing request plan."""
    if not isinstance(grants, HomeRigGrantStore):
        raise HomeAssistantStateRequestError("request builder requires HomeRigGrantStore")
    if not isinstance(lease, HomeRigReadLease):
        raise HomeAssistantStateRequestError("request builder requires HomeRigReadLease")
    if not isinstance(claim, HomeRigReadClaim):
        raise HomeAssistantStateRequestError("request builder requires HomeRigReadClaim")
    if claim.target_kind != "entity" or claim.operation != "entity_state":
        raise HomeAssistantStateRequestDenied("Home Assistant request requires entity_state claim")
    authorized_at = _time(now, "authorized_at")
    if authorized_at >= lease.receipt.expires_at:
        raise HomeAssistantStateRequestDenied("sharing receipt expired before request construction")
    exact_claim_digest = claim_digest(claim)
    if lease.claim_sha256 != exact_claim_digest:
        raise HomeAssistantStateRequestDenied("read lease does not match exact request claim")
    try:
        grant = grants.authorize(
            claim.grant_id,
            target_kind="entity",
            target_id=claim.target_id,
            operation="entity_state",
        )
    except HomeRigDenied as exc:
        raise HomeAssistantStateRequestDenied(str(exc)) from exc
    if grant.scope.digest != claim.scope_sha256:
        raise HomeAssistantStateRequestDenied("read scope changed before request construction")
    sharing = _sharing_request(grant, claim)
    if sharing.digest != lease.request_digest:
        raise HomeAssistantStateRequestDenied("sharing lease does not match exact provider request")
    if lease.receipt.request_digest != sharing.digest:
        raise HomeAssistantStateRequestDenied("sharing receipt does not match exact provider request")
    entity_id = _entity_id(claim.target_id)
    return HomeAssistantStateRequestPlan(
        grant_id=grant.grant_id,
        scope_sha256=grant.scope.digest,
        claim_sha256=exact_claim_digest,
        sharing_request_digest=sharing.digest,
        sharing_receipt_id=lease.receipt.receipt_id,
        entity_id=entity_id,
        authorized_at=authorized_at,
        expires_at=lease.receipt.expires_at,
    )
