"""Dormant minimal RigGate v1 read contract for T-038.

The wire contract is deliberately smaller than a transport/runtime integration:

* exact durable T-038 authority for one rig + one read operation;
* exact one-use T-032 sharing receipt before a request plan exists;
* final durable scope re-authorization immediately before plan construction;
* two fixed GET resources only: rig health and rig power/readiness;
* strict bounded JSON response with exact rig/operation rebinding;
* no origin discovery, credential handling, socket, ToolGate registration,
  wake/control execution or production activation.

A later transport may execute the plan, but may not widen its target, method or
response contract.
"""
from __future__ import annotations

import hashlib
import json
import re
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

WIRE_SCHEMA = "kaliv-riggate-status/v1"
PLAN_SCHEMA = "kaliv-riggate-request-plan/v1"
AUTHORIZED_SCHEMA = "kaliv-riggate-authorized-read/v1"
PRODUCTION_ACTIVATION = False
_MAX_RESPONSE_BYTES = 64 * 1024
_RIG_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_STATE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/+%-]{0,127}$")
_OPERATIONS = {"rig_health", "rig_power_readiness"}


class RigGateProtocolError(HomeRigContractError):
    """RigGate v1 request/response does not satisfy the pinned read contract."""


def _time(value: int, name: str = "time") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RigGateProtocolError(f"{name} must be a non-negative integer")
    return value


def _rig_id(value: str) -> str:
    if not isinstance(value, str):
        raise RigGateProtocolError("rig_id must be a string")
    normalized = value.strip().lower()
    if not _RIG_ID.fullmatch(normalized):
        raise RigGateProtocolError("rig_id must be a stable slug")
    return normalized


def _operation(value: str) -> str:
    if value not in _OPERATIONS:
        raise RigGateProtocolError("RigGate v1 supports read status operations only")
    return value


def _path(rig_id: str, operation: str) -> str:
    rig_id = _rig_id(rig_id)
    operation = _operation(operation)
    suffix = "health" if operation == "rig_health" else "power-readiness"
    return f"/v1/rigs/{quote(rig_id, safe='')}/{suffix}"


def _authorize_exact(grants: HomeRigGrantStore, claim: HomeRigReadClaim):
    if not isinstance(grants, HomeRigGrantStore):
        raise RigGateProtocolError("RigGate provider gate requires HomeRigGrantStore")
    if not isinstance(claim, HomeRigReadClaim):
        raise RigGateProtocolError("RigGate provider gate requires HomeRigReadClaim")
    if claim.target_kind != "rig":
        raise RigGateProtocolError("RigGate v1 reads require target_kind=rig")
    operation = _operation(claim.operation)
    grant = grants.authorize(
        claim.grant_id,
        target_kind="rig",
        target_id=claim.target_id,
        operation=operation,
    )
    if grant.scope.digest != claim.scope_sha256:
        raise HomeRigDenied("home/rig scope changed before RigGate request")
    return grant


def _outbound_identity(*, claim: HomeRigReadClaim, rig_id: str, operation: str) -> bytes:
    return json.dumps(
        {
            "schema": "kaliv-riggate-outbound-identity/v1",
            "grant_id": claim.grant_id,
            "scope_sha256": claim.scope_sha256,
            "target_kind": "rig",
            "rig_id": rig_id,
            "operation": operation,
            "provider_path": _path(rig_id, operation),
            "production_activation": False,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def prepare_riggate_sharing_request(
    grants: HomeRigGrantStore,
    claim: HomeRigReadClaim,
    *,
    data_category: str,
    purpose_code: str,
    purpose: str,
    summary: str,
) -> DataSharingRequest:
    """Build the exact T-032 request later consumed by authorization."""
    grant = _authorize_exact(grants, claim)
    rig_id = _rig_id(claim.target_id)
    operation = _operation(claim.operation)
    if rig_id not in grant.scope.rig_ids:
        raise HomeRigDenied("RigGate rig is outside exact durable scope")
    outbound = _outbound_identity(claim=claim, rig_id=rig_id, operation=operation)
    return build_home_rig_sharing_request(
        grant.scope,
        target_kind="rig",
        data_category=data_category,
        purpose_code=purpose_code,
        purpose=purpose,
        summary=summary,
        content_sha256=hashlib.sha256(outbound).hexdigest(),
        max_bytes=len(outbound),
    )


@dataclass(frozen=True)
class RigGateRequestPlan:
    grant_id: str
    scope_sha256: str
    rig_id: str
    operation: str
    sharing_request_digest: str
    sharing_receipt_id: str
    constructed_at: int
    schema: str = PLAN_SCHEMA
    provider: str = "riggate"
    method: str = "GET"
    path: str = ""
    response_kind: str = "json"
    max_response_bytes: int = _MAX_RESPONSE_BYTES
    credential_mode: str = "credential_injected_at_execute"
    origin_mode: str = "riggate_origin_injected_at_execute"
    follow_redirects: bool = False
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != PLAN_SCHEMA:
            raise RigGateProtocolError("unsupported RigGate request-plan schema")
        if self.production_activation is not False or self.follow_redirects is not False:
            raise RigGateProtocolError("RigGate request plan must remain dormant with redirects disabled")
        if self.provider != "riggate" or self.method != "GET":
            raise RigGateProtocolError("RigGate v1 plan is not a read-only GET")
        rig_id = _rig_id(self.rig_id)
        operation = _operation(self.operation)
        if self.path != _path(rig_id, operation):
            raise RigGateProtocolError("RigGate request path is not bound to exact rig/operation")
        if self.response_kind != "json" or self.max_response_bytes != _MAX_RESPONSE_BYTES:
            raise RigGateProtocolError("RigGate response contract drifted")
        if self.credential_mode != "credential_injected_at_execute":
            raise RigGateProtocolError("RigGate request plan cannot carry credential material")
        if self.origin_mode != "riggate_origin_injected_at_execute":
            raise RigGateProtocolError("RigGate origin must remain deployment-injected")
        _time(self.constructed_at, "constructed_at")
        object.__setattr__(self, "rig_id", rig_id)
        object.__setattr__(self, "operation", operation)

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "provider": self.provider,
            "grant_id": self.grant_id,
            "scope_sha256": self.scope_sha256,
            "rig_id": self.rig_id,
            "operation": self.operation,
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
class AuthorizedRigGateRead:
    plan: RigGateRequestPlan
    sharing_request: DataSharingRequest
    sharing_receipt: DataSharingReceipt
    schema: str = AUTHORIZED_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != AUTHORIZED_SCHEMA or self.production_activation is not False:
            raise RigGateProtocolError("authorized RigGate read must remain dormant")
        if self.plan.sharing_request_digest != self.sharing_request.digest:
            raise RigGateProtocolError("RigGate plan/request digest mismatch")
        if self.plan.sharing_receipt_id != self.sharing_receipt.receipt_id:
            raise RigGateProtocolError("RigGate plan/receipt mismatch")
        if self.sharing_receipt.request_digest != self.sharing_request.digest:
            raise RigGateProtocolError("RigGate sharing receipt does not bind exact request")

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "plan": self.plan.to_dict(),
            "sharing_receipt": self.sharing_receipt.to_dict(),
            "production_activation": False,
        }


def authorize_riggate_request(
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
) -> AuthorizedRigGateRead:
    """Claim T-032 authority, re-authorize T-038, then construct exact RigGate plan."""
    if not isinstance(ledger, DataSharingLedger):
        raise RigGateProtocolError("RigGate provider gate requires DataSharingLedger")
    now = _time(now, "now")
    sharing_request = prepare_riggate_sharing_request(
        grants,
        claim,
        data_category=data_category,
        purpose_code=purpose_code,
        purpose=purpose,
        summary=summary,
    )
    receipt = ledger.authorize(
        sharing_request,
        policy=policy,
        permission_id=permission_id,
        now=now,
        receipt_ttl_seconds=receipt_ttl_seconds,
    )
    ledger.claim(receipt, sharing_request, now=now)

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

    rig_id = _rig_id(claim.target_id)
    operation = _operation(claim.operation)
    plan = RigGateRequestPlan(
        grant_id=final_grant.grant_id,
        scope_sha256=final_grant.scope.digest,
        rig_id=rig_id,
        operation=operation,
        sharing_request_digest=sharing_request.digest,
        sharing_receipt_id=receipt.receipt_id,
        constructed_at=now,
        path=_path(rig_id, operation),
    )
    return AuthorizedRigGateRead(plan, sharing_request, receipt)


def finish_riggate_request(
    ledger: DataSharingLedger,
    authorized: AuthorizedRigGateRead,
    *,
    outcome: Outcome,
    bytes_sent: int,
    error_code: str | None = None,
    now: int,
) -> None:
    if not isinstance(ledger, DataSharingLedger):
        raise RigGateProtocolError("RigGate provider gate requires DataSharingLedger")
    if not isinstance(authorized, AuthorizedRigGateRead):
        raise RigGateProtocolError("finish requires AuthorizedRigGateRead")
    ledger.complete(
        authorized.sharing_receipt,
        authorized.sharing_request,
        outcome=outcome,
        bytes_sent=bytes_sent,
        error_code=error_code,
        now=_time(now, "now"),
    )


@dataclass(frozen=True)
class RigGateStatusEvidence:
    rig_id: str
    operation: str
    state: str
    observed_at: int
    schema: str = WIRE_SCHEMA
    source: str = "riggate"
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != WIRE_SCHEMA or self.source != "riggate":
            raise RigGateProtocolError("unsupported RigGate wire evidence schema")
        if self.production_activation is not False:
            raise RigGateProtocolError("RigGate wire evidence cannot activate production")
        object.__setattr__(self, "rig_id", _rig_id(self.rig_id))
        object.__setattr__(self, "operation", _operation(self.operation))
        if not isinstance(self.state, str) or not _STATE.fullmatch(self.state):
            raise RigGateProtocolError("RigGate state must be a bounded status string")
        _time(self.observed_at, "observed_at")

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "source": self.source,
            "rig_id": self.rig_id,
            "operation": self.operation,
            "state": self.state,
            "observed_at": self.observed_at,
            "production_activation": False,
        }


def parse_riggate_status_response(
    body: bytes,
    *,
    expected_rig_id: str,
    expected_operation: str,
) -> RigGateStatusEvidence:
    """Parse one bounded exact RigGate v1 JSON response with no implicit widening."""
    if not isinstance(body, bytes):
        raise RigGateProtocolError("RigGate response body must be bytes")
    if not body or len(body) > _MAX_RESPONSE_BYTES:
        raise RigGateProtocolError("RigGate response size is invalid")
    try:
        raw = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RigGateProtocolError("RigGate response is not valid UTF-8 JSON") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema", "rig_id", "operation", "state", "observed_at"
    }:
        raise RigGateProtocolError("RigGate response shape is invalid")
    if raw.get("schema") != WIRE_SCHEMA:
        raise RigGateProtocolError("unsupported RigGate response schema")
    evidence = RigGateStatusEvidence(
        rig_id=raw["rig_id"],
        operation=raw["operation"],
        state=raw["state"],
        observed_at=raw["observed_at"],
    )
    if evidence.rig_id != _rig_id(expected_rig_id):
        raise RigGateProtocolError("RigGate response rig_id does not match requested rig")
    if evidence.operation != _operation(expected_operation):
        raise RigGateProtocolError("RigGate response operation does not match requested operation")
    return evidence
