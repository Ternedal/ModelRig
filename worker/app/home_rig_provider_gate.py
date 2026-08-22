"""Dormant T-038 Home Assistant provider-plan gate.

This module closes the two authority edges that must exist before a live Home
Assistant read can be introduced:

* an exact T-038 read claim is bound to T-032's one-use permission/receipt
  lifecycle; and
* the durable T-038 grant/scope is re-authorized after that receipt is claimed,
  immediately before a provider request plan is constructed.

It is deliberately not a transport. No provider origin, credential, socket,
HTTP client, ToolGate registration or production activation exists here.
RigGate transport remains undefined.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from urllib.parse import quote

from .data_sharing import (
    DEFAULT_POLICY,
    DataSharingLedger,
    DataSharingPolicy,
    DataSharingReceipt,
    DataSharingRequest,
    Outcome,
)
from .home_rig_connector_contract import (
    HomeRigContractError,
    HomeRigDenied,
    HomeRigGrantStore,
    build_home_rig_sharing_request,
)
from .home_rig_read_boundary import HomeRigReadClaim

PLAN_SCHEMA = "kaliv-home-assistant-state-request-plan/v1"
AUTHORIZED_SCHEMA = "kaliv-home-assistant-authorized-read/v1"
PRODUCTION_ACTIVATION = False
_MAX_RESPONSE_BYTES = 256 * 1024


def _time(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HomeRigContractError("now must be a non-negative integer")
    return value


def _authorize_exact(grants: HomeRigGrantStore, claim: HomeRigReadClaim):
    if not isinstance(grants, HomeRigGrantStore):
        raise HomeRigContractError("provider gate requires HomeRigGrantStore")
    if not isinstance(claim, HomeRigReadClaim):
        raise HomeRigContractError("provider gate requires HomeRigReadClaim")
    if claim.target_kind != "entity" or claim.operation != "entity_state":
        raise HomeRigContractError("provider gate supports Home Assistant entity_state reads only")
    grant = grants.authorize(
        claim.grant_id,
        target_kind=claim.target_kind,
        target_id=claim.target_id,
        operation=claim.operation,
    )
    if grant.scope.digest != claim.scope_sha256:
        raise HomeRigDenied("home/rig scope changed before provider request")
    return grant


def _outbound_identity(*, claim: HomeRigReadClaim, entity_id: str) -> bytes:
    return json.dumps(
        {
            "schema": "kaliv-home-assistant-outbound-identity/v1",
            "grant_id": claim.grant_id,
            "scope_sha256": claim.scope_sha256,
            "target_kind": "entity",
            "entity_id": entity_id,
            "operation": "entity_state",
            "provider_path": f"/api/states/{quote(entity_id, safe='')}",
            "production_activation": False,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def prepare_home_assistant_state_sharing_request(
    grants: HomeRigGrantStore,
    claim: HomeRigReadClaim,
    *,
    data_category: str,
    purpose_code: str,
    purpose: str,
    summary: str,
) -> DataSharingRequest:
    """Build the exact T-032 request used for preview/proposal and later consume."""
    grant = _authorize_exact(grants, claim)
    entity_id = claim.target_id.strip().lower()
    if entity_id not in grant.scope.entity_ids:
        raise HomeRigDenied("Home Assistant entity is outside exact durable scope")
    outbound = _outbound_identity(claim=claim, entity_id=entity_id)
    return build_home_rig_sharing_request(
        grant.scope,
        target_kind="entity",
        data_category=data_category,
        purpose_code=purpose_code,
        purpose=purpose,
        summary=summary,
        content_sha256=hashlib.sha256(outbound).hexdigest(),
        max_bytes=len(outbound),
    )


@dataclass(frozen=True)
class HomeAssistantStateRequestPlan:
    grant_id: str
    scope_sha256: str
    entity_id: str
    sharing_request_digest: str
    sharing_receipt_id: str
    constructed_at: int
    schema: str = PLAN_SCHEMA
    provider: str = "home_assistant"
    method: str = "GET"
    path: str = ""
    response_kind: str = "json"
    max_response_bytes: int = _MAX_RESPONSE_BYTES
    credential_mode: str = "bearer_injected_at_execute"
    origin_mode: str = "home_assistant_origin_injected_at_execute"
    follow_redirects: bool = False
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != PLAN_SCHEMA:
            raise HomeRigContractError("unsupported Home Assistant provider plan schema")
        if self.production_activation is not False or self.follow_redirects is not False:
            raise HomeRigContractError("provider plan must remain dormant with redirects disabled")
        if self.provider != "home_assistant" or self.method != "GET":
            raise HomeRigContractError("provider plan is not a Home Assistant GET")
        if self.response_kind != "json" or self.max_response_bytes != _MAX_RESPONSE_BYTES:
            raise HomeRigContractError("provider response contract drifted")
        if self.credential_mode != "bearer_injected_at_execute":
            raise HomeRigContractError("provider plan cannot carry credential material")
        if self.origin_mode != "home_assistant_origin_injected_at_execute":
            raise HomeRigContractError("provider origin must remain deployment-injected")
        expected_path = f"/api/states/{quote(self.entity_id, safe='')}"
        if self.path != expected_path:
            raise HomeRigContractError("provider path is not bound to the exact entity")
        _time(self.constructed_at)

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "provider": self.provider,
            "grant_id": self.grant_id,
            "scope_sha256": self.scope_sha256,
            "entity_id": self.entity_id,
            "method": self.method,
            "path": self.path,
            "response_kind": self.response_kind,
            "max_response_bytes": self.max_response_bytes,
            "credential_mode": self.credential_mode,
            "origin_mode": self.origin_mode,
            "follow_redirects": False,
            "sharing_request_digest": self.sharing_request_digest,
            "sharing_receipt_id": self.sharing_receipt_id,
            "constructed_at": self.constructed_at,
            "production_activation": False,
        }


@dataclass(frozen=True)
class AuthorizedHomeAssistantRead:
    plan: HomeAssistantStateRequestPlan
    sharing_request: DataSharingRequest
    sharing_receipt: DataSharingReceipt
    schema: str = AUTHORIZED_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != AUTHORIZED_SCHEMA or self.production_activation is not False:
            raise HomeRigContractError("authorized provider read must remain dormant")
        if self.plan.sharing_request_digest != self.sharing_request.digest:
            raise HomeRigContractError("provider plan/request digest mismatch")
        if self.plan.sharing_receipt_id != self.sharing_receipt.receipt_id:
            raise HomeRigContractError("provider plan/receipt mismatch")
        if self.sharing_receipt.request_digest != self.sharing_request.digest:
            raise HomeRigContractError("sharing receipt does not bind exact request")

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "plan": self.plan.to_dict(),
            "sharing_receipt": self.sharing_receipt.to_dict(),
            "production_activation": False,
        }


def authorize_home_assistant_state_request(
    grants: HomeRigGrantStore,
    ledger: DataSharingLedger,
    claim: HomeRigReadClaim,
    *,
    data_category: str,
    purpose_code: str,
    purpose: str,
    summary: str,
    permission_id: str | None = None,
    policy: DataSharingPolicy = DEFAULT_POLICY,
    now: int,
    receipt_ttl_seconds: int = 60,
) -> AuthorizedHomeAssistantRead:
    """Claim T-032 authority, re-authorize T-038, then construct the request plan."""
    if not isinstance(ledger, DataSharingLedger):
        raise HomeRigContractError("provider gate requires DataSharingLedger")
    now = _time(now)

    # Rebuild the exact preview/proposal request only after a fresh durable check.
    sharing_request = prepare_home_assistant_state_sharing_request(
        grants,
        claim,
        data_category=data_category,
        purpose_code=purpose_code,
        purpose=purpose,
        summary=summary,
    )

    # T-032 consumes an exact approved permission when policy requires one and
    # emits a short-lived receipt. Claiming the receipt is atomic and one-use.
    receipt = ledger.authorize(
        sharing_request,
        policy=policy,
        permission_id=permission_id,
        now=now,
        receipt_ttl_seconds=receipt_ttl_seconds,
    )
    ledger.claim(receipt, sharing_request, now=now)

    # Final durable check happens AFTER the one-use T-032 claim and immediately
    # before the provider plan is instantiated. A revoke in this window cannot
    # yield an executable-looking request plan.
    try:
        final_grant = _authorize_exact(grants, claim)
    except HomeRigDenied:
        ledger.complete(
            receipt,
            sharing_request,
            outcome="blocked",
            bytes_sent=0,
            error_code="authority_revoked",
            now=now,
        )
        raise

    entity_id = claim.target_id.strip().lower()
    plan = HomeAssistantStateRequestPlan(
        grant_id=final_grant.grant_id,
        scope_sha256=final_grant.scope.digest,
        entity_id=entity_id,
        sharing_request_digest=sharing_request.digest,
        sharing_receipt_id=receipt.receipt_id,
        constructed_at=now,
        path=f"/api/states/{quote(entity_id, safe='')}",
    )
    return AuthorizedHomeAssistantRead(plan, sharing_request, receipt)


def finish_home_assistant_state_request(
    ledger: DataSharingLedger,
    authorized: AuthorizedHomeAssistantRead,
    *,
    outcome: Outcome,
    bytes_sent: int,
    error_code: str | None = None,
    now: int,
) -> None:
    """Finish the already-claimed T-032 receipt after a later transport attempt."""
    if not isinstance(ledger, DataSharingLedger):
        raise HomeRigContractError("provider gate requires DataSharingLedger")
    if not isinstance(authorized, AuthorizedHomeAssistantRead):
        raise HomeRigContractError("finish requires AuthorizedHomeAssistantRead")
    ledger.complete(
        authorized.sharing_receipt,
        authorized.sharing_request,
        outcome=outcome,
        bytes_sent=bytes_sent,
        error_code=error_code,
        now=_time(now),
    )
