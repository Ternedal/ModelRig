"""Dormant prepare/fulfill boundary for T-038 read-only source evidence.

This module contains no source client. A host may prepare an exact scoped read,
obtain source evidence elsewhere, then fulfill it here. Authority is rechecked
at fulfillment so revocation during an in-flight read invalidates the result.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .home_rig_connector_contract import (
    HomeRigAuditLog,
    HomeRigContractError,
    HomeRigDenied,
    HomeRigGrantStore,
    HomeRigObservation,
    TargetKind,
    normalize_observation,
)

CLAIM_SCHEMA = "kaliv-home-rig-read-claim/v1"
RECEIPT_SCHEMA = "kaliv-home-rig-read-receipt/v1"
PRODUCTION_ACTIVATION = False

ReadOperation = Literal["rig_health", "rig_power_readiness", "entity_state"]
_READ_OPERATIONS = {"rig_health", "rig_power_readiness", "entity_state"}


def _time(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HomeRigContractError(f"{name} must be a non-negative integer")
    return value


def _read_operation(target_kind: TargetKind, operation: str) -> ReadOperation:
    if operation not in _READ_OPERATIONS:
        raise HomeRigContractError("read boundary accepts read operations only")
    if target_kind == "rig" and operation not in {"rig_health", "rig_power_readiness"}:
        raise HomeRigContractError("rig read operation is invalid")
    if target_kind == "entity" and operation != "entity_state":
        raise HomeRigContractError("entity read operation is invalid")
    if target_kind not in {"rig", "entity"}:
        raise HomeRigContractError("target_kind must be rig or entity")
    return operation  # type: ignore[return-value]


@dataclass(frozen=True)
class HomeRigReadClaim:
    grant_id: str
    scope_sha256: str
    target_kind: TargetKind
    target_id: str
    operation: ReadOperation
    requested_at: int
    schema: str = CLAIM_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != CLAIM_SCHEMA:
            raise HomeRigContractError("unsupported read claim schema")
        if self.production_activation is not False:
            raise HomeRigContractError("read claim activation must remain false")
        _time(self.requested_at, "requested_at")
        _read_operation(self.target_kind, self.operation)

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "grant_id": self.grant_id,
            "scope_sha256": self.scope_sha256,
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "operation": self.operation,
            "requested_at": self.requested_at,
            "production_activation": False,
        }


@dataclass(frozen=True)
class HomeRigReadReceipt:
    grant_id: str
    scope_sha256: str
    observation: HomeRigObservation
    fulfilled_at: int
    schema: str = RECEIPT_SCHEMA
    authority_rechecked: bool = True
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != RECEIPT_SCHEMA:
            raise HomeRigContractError("unsupported read receipt schema")
        if self.authority_rechecked is not True or self.production_activation is not False:
            raise HomeRigContractError("read receipt must be re-authorized and dormant")
        if not isinstance(self.observation, HomeRigObservation):
            raise HomeRigContractError("read receipt requires normalized observation")
        _time(self.fulfilled_at, "fulfilled_at")

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "grant_id": self.grant_id,
            "scope_sha256": self.scope_sha256,
            "observation": self.observation.to_dict(),
            "fulfilled_at": self.fulfilled_at,
            "authority_rechecked": True,
            "production_activation": False,
        }


def prepare_read(
    grants: HomeRigGrantStore,
    grant_id: str,
    *,
    target_kind: TargetKind,
    target_id: str,
    operation: str,
    now: int,
) -> HomeRigReadClaim:
    """Pin one exact active grant before any source boundary is crossed."""
    if not isinstance(grants, HomeRigGrantStore):
        raise HomeRigContractError("prepare_read requires HomeRigGrantStore")
    operation = _read_operation(target_kind, operation)
    grant = grants.authorize(
        grant_id,
        target_kind=target_kind,
        target_id=target_id,
        operation=operation,
    )
    return HomeRigReadClaim(
        grant_id=grant.grant_id,
        scope_sha256=grant.scope.digest,
        target_kind=target_kind,
        target_id=target_id,
        operation=operation,
        requested_at=_time(now, "requested_at"),
    )


def fulfill_read(
    grants: HomeRigGrantStore,
    audit: HomeRigAuditLog,
    claim: HomeRigReadClaim,
    *,
    source_state: str | None,
    observed_at: int | None,
    now: int,
    max_freshness_seconds: int = 120,
) -> HomeRigReadReceipt:
    """Re-authorize, normalize source evidence and write privacy-minimized audit."""
    if not isinstance(grants, HomeRigGrantStore):
        raise HomeRigContractError("fulfill_read requires HomeRigGrantStore")
    if not isinstance(audit, HomeRigAuditLog):
        raise HomeRigContractError("fulfill_read requires HomeRigAuditLog")
    if not isinstance(claim, HomeRigReadClaim):
        raise HomeRigContractError("fulfill_read requires HomeRigReadClaim")
    fulfilled_at = _time(now, "fulfilled_at")
    if fulfilled_at < claim.requested_at:
        raise HomeRigContractError("fulfillment cannot predate read claim")

    try:
        grant = grants.authorize(
            claim.grant_id,
            target_kind=claim.target_kind,
            target_id=claim.target_id,
            operation=claim.operation,
        )
    except HomeRigDenied:
        audit.record(
            target_kind=claim.target_kind,
            target_id=claim.target_id,
            operation=claim.operation,
            outcome="blocked",
            grant_id=claim.grant_id,
            scope_sha256=claim.scope_sha256,
            detail="authority_revoked_in_flight",
            now=fulfilled_at,
        )
        raise

    if grant.scope.digest != claim.scope_sha256:
        audit.record(
            target_kind=claim.target_kind,
            target_id=claim.target_id,
            operation=claim.operation,
            outcome="blocked",
            grant_id=claim.grant_id,
            scope_sha256=claim.scope_sha256,
            detail="scope_changed_in_flight",
            now=fulfilled_at,
        )
        raise HomeRigDenied("home/rig scope changed before read fulfillment")

    try:
        observation = normalize_observation(
            target_kind=claim.target_kind,
            target_id=claim.target_id,
            operation=claim.operation,
            source_state=source_state,
            observed_at=observed_at,
            checked_at=fulfilled_at,
            max_freshness_seconds=max_freshness_seconds,
        )
    except HomeRigContractError:
        audit.record(
            target_kind=claim.target_kind,
            target_id=claim.target_id,
            operation=claim.operation,
            outcome="error",
            grant_id=claim.grant_id,
            scope_sha256=claim.scope_sha256,
            detail="invalid_source_evidence",
            now=fulfilled_at,
        )
        raise

    audit.record(
        target_kind=claim.target_kind,
        target_id=claim.target_id,
        operation=claim.operation,
        outcome="executed",
        grant_id=claim.grant_id,
        scope_sha256=claim.scope_sha256,
        freshness=observation.freshness,
        detail=(
            "source_unavailable"
            if observation.freshness == "unavailable"
            else "source_read"
        ),
        now=fulfilled_at,
    )
    return HomeRigReadReceipt(
        grant_id=grant.grant_id,
        scope_sha256=grant.scope.digest,
        observation=observation,
        fulfilled_at=fulfilled_at,
    )
