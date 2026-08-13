"""Dormant T-038 data-sharing lease for exact provider reads.

No network I/O lives here. The boundary binds one prepared ``HomeRigReadClaim``
to the common T-032 permission/receipt lifecycle and re-authorizes the durable
home/rig grant immediately before a receipt may be claimed for provider I/O.

T-038 v1 never auto-shares. Home Assistant entity state is classified as
private; RigGate health/readiness is operational. Both require an exact
permission-authorized, one-use T-032 receipt. Completion remains possible after
a later revoke/policy change so an in-flight receipt can always reach a truthful
terminal state.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .data_sharing import (
    DEFAULT_POLICY,
    DataSharingContractError,
    DataSharingDenied,
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

LEASE_SCHEMA = "kaliv-home-rig-read-lease/v1"
PRODUCTION_ACTIVATION = False
_REQUEST_MAX_BYTES = 4096


class HomeRigReadLeaseError(HomeRigContractError):
    pass


class HomeRigReadLeaseDenied(HomeRigDenied):
    pass


def _canonical(value: dict) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: dict) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def claim_digest(claim: HomeRigReadClaim) -> str:
    if not isinstance(claim, HomeRigReadClaim):
        raise HomeRigReadLeaseError("sharing lease requires HomeRigReadClaim")
    return _digest(claim.to_dict())


def policy_digest(policy: DataSharingPolicy) -> str:
    if not isinstance(policy, DataSharingPolicy):
        raise HomeRigReadLeaseError("sharing lease requires DataSharingPolicy")
    return _digest(policy.to_dict())


def _grant_for_claim(
    grants: HomeRigGrantStore,
    claim: HomeRigReadClaim,
    *,
    require_active: bool,
):
    if not isinstance(grants, HomeRigGrantStore):
        raise HomeRigReadLeaseError("sharing lease requires HomeRigGrantStore")
    if not isinstance(claim, HomeRigReadClaim):
        raise HomeRigReadLeaseError("sharing lease requires HomeRigReadClaim")
    if require_active:
        try:
            grant = grants.authorize(
                claim.grant_id,
                target_kind=claim.target_kind,
                target_id=claim.target_id,
                operation=claim.operation,
            )
        except HomeRigDenied as exc:
            raise HomeRigReadLeaseDenied(str(exc)) from exc
    else:
        grant = grants.get(claim.grant_id)
        if grant is None:
            raise HomeRigReadLeaseDenied("read claim grant no longer exists")
        if not grant.scope.allows(
            target_kind=claim.target_kind,
            target_id=claim.target_id,
            operation=claim.operation,
        ):
            raise HomeRigReadLeaseDenied("read claim is outside its durable scope")
    if grant.scope.digest != claim.scope_sha256:
        raise HomeRigReadLeaseDenied("read claim scope changed before sharing boundary")
    return grant


def _request_for(
    grants: HomeRigGrantStore,
    claim: HomeRigReadClaim,
    *,
    require_active: bool = True,
) -> DataSharingRequest:
    grant = _grant_for_claim(grants, claim, require_active=require_active)
    digest = claim_digest(claim)
    if claim.target_kind == "entity":
        data_category = "private"
        purpose = f"Read explicitly scoped Home Assistant state for {claim.target_id}"
        summary = f"Home Assistant state: {claim.target_id}"
    elif claim.target_kind == "rig":
        data_category = "operational"
        purpose = f"Read explicitly scoped RigGate status for {claim.target_id}"
        summary = f"RigGate status: {claim.target_id}"
    else:
        raise HomeRigReadLeaseError("sharing lease target kind is invalid")
    return build_home_rig_sharing_request(
        grant.scope,
        target_kind=claim.target_kind,
        data_category=data_category,
        purpose_code="status_read",
        purpose=purpose,
        summary=summary,
        content_sha256=digest,
        max_bytes=_REQUEST_MAX_BYTES,
    )


def _require_explicit_confirmation(
    policy: DataSharingPolicy,
    request: DataSharingRequest,
) -> None:
    decision = policy.decision(request)
    if decision == "forbidden":
        raise HomeRigReadLeaseDenied("active data-sharing policy forbids provider read")
    if decision != "confirmation_required":
        raise HomeRigReadLeaseDenied("T-038 provider reads require explicit permission")


@dataclass(frozen=True)
class HomeRigReadLease:
    claim_sha256: str
    request_digest: str
    policy_sha256: str
    receipt: DataSharingReceipt
    schema: str = LEASE_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != LEASE_SCHEMA:
            raise HomeRigReadLeaseError("unsupported T-038 read lease schema")
        if self.production_activation is not False:
            raise HomeRigReadLeaseError("T-038 read lease activation must remain false")
        for value, name in (
            (self.claim_sha256, "claim_sha256"),
            (self.request_digest, "request_digest"),
            (self.policy_sha256, "policy_sha256"),
        ):
            if not isinstance(value, str) or len(value) != 64:
                raise HomeRigReadLeaseError(f"{name} must be a SHA-256 digest")
            try:
                int(value, 16)
            except ValueError as exc:
                raise HomeRigReadLeaseError(f"{name} must be lowercase hexadecimal") from exc
            if value.lower() != value:
                raise HomeRigReadLeaseError(f"{name} must be lowercase hexadecimal")
        if not isinstance(self.receipt, DataSharingReceipt):
            raise HomeRigReadLeaseError("T-038 read lease requires common sharing receipt")
        if self.receipt.request_digest != self.request_digest:
            raise HomeRigReadLeaseError("sharing receipt does not match lease request")
        if self.receipt.authorization != "permission" or not self.receipt.permission_id:
            raise HomeRigReadLeaseError("T-038 read lease requires permission-authorized receipt")

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "claim_sha256": self.claim_sha256,
            "request_digest": self.request_digest,
            "policy_sha256": self.policy_sha256,
            "receipt": self.receipt.to_dict(),
            "may_send": True,
            "production_activation": False,
        }


class HomeRigReadSharingBoundary:
    """Exact T-032 lifecycle around one T-038 provider read."""

    def __init__(
        self,
        grants: HomeRigGrantStore,
        ledger: DataSharingLedger,
        *,
        policy: DataSharingPolicy = DEFAULT_POLICY,
    ) -> None:
        if not isinstance(grants, HomeRigGrantStore):
            raise HomeRigReadLeaseError("sharing boundary requires HomeRigGrantStore")
        if not isinstance(ledger, DataSharingLedger):
            raise HomeRigReadLeaseError("sharing boundary requires DataSharingLedger")
        if not isinstance(policy, DataSharingPolicy):
            raise HomeRigReadLeaseError("sharing boundary requires DataSharingPolicy")
        self.grants = grants
        self.ledger = ledger
        self.policy = policy
        self.policy_sha256 = policy_digest(policy)

    def inspect(self, claim: HomeRigReadClaim) -> dict:
        request = _request_for(self.grants, claim)
        _require_explicit_confirmation(self.policy, request)
        return {
            "schema": LEASE_SCHEMA,
            "claim_sha256": claim_digest(claim),
            "policy_sha256": self.policy_sha256,
            "may_send": False,
            "request": request.preview(self.policy),
            "production_activation": False,
        }

    def propose(
        self,
        claim: HomeRigReadClaim,
        *,
        now: int | None = None,
        ttl_seconds: int = 300,
    ):
        request = _request_for(self.grants, claim)
        _require_explicit_confirmation(self.policy, request)
        return self.ledger.propose(
            request,
            policy=self.policy,
            now=now,
            ttl_seconds=ttl_seconds,
        )

    def prepare(
        self,
        claim: HomeRigReadClaim,
        *,
        permission_id: str,
        now: int | None = None,
        receipt_ttl_seconds: int = 60,
    ) -> HomeRigReadLease:
        request = _request_for(self.grants, claim)
        _require_explicit_confirmation(self.policy, request)
        if not isinstance(permission_id, str) or not permission_id:
            raise HomeRigReadLeaseError("T-038 provider read requires permission_id")
        try:
            receipt = self.ledger.authorize(
                request,
                policy=self.policy,
                permission_id=permission_id,
                now=now,
                receipt_ttl_seconds=receipt_ttl_seconds,
            )
        except (DataSharingDenied, DataSharingContractError) as exc:
            raise HomeRigReadLeaseDenied(str(exc)) from exc
        return HomeRigReadLease(
            claim_sha256=claim_digest(claim),
            request_digest=request.digest,
            policy_sha256=self.policy_sha256,
            receipt=receipt,
        )

    def _bound(
        self,
        lease: HomeRigReadLease,
        claim: HomeRigReadClaim,
        *,
        require_active: bool,
        require_current_policy: bool,
    ) -> tuple[DataSharingReceipt, DataSharingRequest]:
        if not isinstance(lease, HomeRigReadLease):
            raise HomeRigReadLeaseError("boundary requires HomeRigReadLease")
        request = _request_for(self.grants, claim, require_active=require_active)
        if require_current_policy:
            _require_explicit_confirmation(self.policy, request)
            if lease.policy_sha256 != self.policy_sha256:
                raise HomeRigReadLeaseDenied("read lease was created under a different policy")
        if lease.claim_sha256 != claim_digest(claim):
            raise HomeRigReadLeaseDenied("read lease does not match exact read claim")
        if lease.request_digest != request.digest:
            raise HomeRigReadLeaseDenied("read lease does not match exact sharing request")
        if lease.receipt.request_digest != request.digest:
            raise HomeRigReadLeaseDenied("read lease receipt does not match exact request")
        return lease.receipt, request

    def claim(
        self,
        lease: HomeRigReadLease,
        claim: HomeRigReadClaim,
        *,
        now: int | None = None,
    ) -> None:
        receipt, request = self._bound(
            lease,
            claim,
            require_active=True,
            require_current_policy=True,
        )
        try:
            self.ledger.claim(receipt, request, now=now)
        except (DataSharingDenied, DataSharingContractError) as exc:
            raise HomeRigReadLeaseDenied(str(exc)) from exc

    def complete(
        self,
        lease: HomeRigReadLease,
        claim: HomeRigReadClaim,
        *,
        outcome: Outcome,
        bytes_sent: int,
        error_code: str | None = None,
        now: int | None = None,
    ) -> None:
        # Terminal accounting is not a new authorization decision. A revoke or
        # policy change after I/O began must not strand the common receipt in
        # ``in_flight``. Exact claim/request/receipt binding is still checked.
        receipt, request = self._bound(
            lease,
            claim,
            require_active=False,
            require_current_policy=False,
        )
        try:
            self.ledger.complete(
                receipt,
                request,
                outcome=outcome,
                bytes_sent=bytes_sent,
                error_code=error_code,
                now=now,
            )
        except (DataSharingDenied, DataSharingContractError) as exc:
            raise HomeRigReadLeaseDenied(str(exc)) from exc
