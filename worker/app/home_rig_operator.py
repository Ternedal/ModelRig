"""Dormant loopback operator surface for the T-038 authority contract.

The router manages exact scope authority only. It has no source client, no
wake/control execution, no ToolGate registration, no environment discovery and
is not mounted by normal worker startup in this slice.
"""
from __future__ import annotations

import re
import threading
from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .home_rig_connector_contract import (
    HomeRigAuditLog,
    HomeRigContractError,
    HomeRigDenied,
    HomeRigGrant,
    HomeRigGrantStore,
    HomeRigScope,
)
from .netguard import is_loopback

OPERATOR_SCHEMA = "kaliv-home-rig-operator/v1"
PRODUCTION_ACTIVATION = False
_OPERATOR_ACTOR = "loopback-operator"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MUTATION_LOCK = threading.Lock()
_RIG_OPS = {"rig_health", "rig_power_readiness", "wake_preview"}
_ENTITY_OPS = {"entity_state", "control_preview"}


class HomeRigScopeReq(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rig_ids: list[str] = Field(default_factory=list, max_length=100)
    entity_ids: list[str] = Field(default_factory=list, max_length=100)
    operations: list[
        Literal[
            "rig_health",
            "rig_power_readiness",
            "entity_state",
            "wake_preview",
            "control_preview",
        ]
    ] = Field(min_length=1, max_length=5)


class CreateHomeRigGrantReq(HomeRigScopeReq):
    expected_scope_sha256: str = Field(min_length=64, max_length=64)


class RevokeHomeRigGrantReq(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_scope_sha256: str = Field(min_length=64, max_length=64)
    confirm_revoke: Literal[True]


def _operator_allowed(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host == "testclient" or is_loopback(host)


def _require_operator(request: Request, allowed: Callable[[Request], bool]) -> None:
    try:
        accepted = bool(allowed(request))
    except Exception:
        accepted = False
    if not accepted:
        raise HTTPException(
            status_code=403,
            detail="home/rig administration is loopback-only",
        )


def _scope(req: HomeRigScopeReq) -> HomeRigScope:
    try:
        return HomeRigScope(
            rig_ids=tuple(req.rig_ids),
            entity_ids=tuple(req.entity_ids),
            operations=tuple(req.operations),
        )
    except HomeRigContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _require_digest(expected: str, actual: str, *, action: str) -> None:
    if not _SHA256.fullmatch(expected):
        raise HTTPException(
            status_code=422,
            detail="expected_scope_sha256 must be lowercase SHA-256",
        )
    if expected != actual:
        raise HTTPException(
            status_code=409,
            detail=f"home/rig {action} scope changed since preview",
        )


def _overlaps(left: HomeRigScope, right: HomeRigScope) -> bool:
    common_ops = set(left.operations).intersection(right.operations)
    rig_overlap = bool(
        common_ops.intersection(_RIG_OPS)
        and set(left.rig_ids).intersection(right.rig_ids)
    )
    entity_overlap = bool(
        common_ops.intersection(_ENTITY_OPS)
        and set(left.entity_ids).intersection(right.entity_ids)
    )
    return rig_overlap or entity_overlap


def _active_overlap(store: HomeRigGrantStore, scope: HomeRigScope) -> HomeRigGrant | None:
    for grant in store.list_grants():
        if _overlaps(grant.scope, scope):
            return grant
    return None


def build_home_rig_operator_router(
    *,
    grants: HomeRigGrantStore,
    audit: HomeRigAuditLog,
    operator_allowed: Callable[[Request], bool] = _operator_allowed,
) -> APIRouter:
    """Build the unmounted operator router from explicitly injected stores."""
    if not isinstance(grants, HomeRigGrantStore):
        raise HomeRigContractError("operator grants must be HomeRigGrantStore")
    if not isinstance(audit, HomeRigAuditLog):
        raise HomeRigContractError("operator audit must be HomeRigAuditLog")
    if not callable(operator_allowed):
        raise HomeRigContractError("operator_allowed must be callable")

    router = APIRouter(prefix="/home-rig", tags=["home-rig-operator"])

    @router.post("/grants/preview")
    def preview_grant(request: Request, req: HomeRigScopeReq) -> dict:
        _require_operator(request, operator_allowed)
        scope = _scope(req)
        return {
            "schema": OPERATOR_SCHEMA,
            "scope": scope.to_dict(),
            "scope_sha256": scope.digest,
            "grant_persisted": False,
            "production_activation": False,
        }

    @router.post("/grants")
    def create_grant(request: Request, req: CreateHomeRigGrantReq) -> dict:
        _require_operator(request, operator_allowed)
        scope = _scope(req)
        _require_digest(req.expected_scope_sha256, scope.digest, action="grant")
        with _MUTATION_LOCK:
            overlap = _active_overlap(grants, scope)
            if overlap is not None:
                raise HTTPException(
                    status_code=409,
                    detail="home/rig scope overlaps an active grant",
                )
            try:
                grant = grants.create(scope, actor=_OPERATOR_ACTOR)
            except HomeRigContractError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "schema": OPERATOR_SCHEMA,
            "grant": grant.to_dict(),
            "production_activation": False,
        }

    @router.get("/grants")
    def list_grants(request: Request, include_revoked: bool = False) -> dict:
        _require_operator(request, operator_allowed)
        try:
            visible = grants.list_grants(include_revoked=include_revoked)
        except HomeRigContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "schema": OPERATOR_SCHEMA,
            "grants": [grant.to_dict() for grant in visible],
            "production_activation": False,
        }

    @router.post("/grants/{grant_id}/revoke")
    def revoke_grant(
        request: Request,
        grant_id: str,
        req: RevokeHomeRigGrantReq,
    ) -> dict:
        _require_operator(request, operator_allowed)
        with _MUTATION_LOCK:
            try:
                current = grants.get(grant_id)
            except HomeRigContractError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            if current is None:
                raise HTTPException(status_code=404, detail="unknown home/rig grant")
            _require_digest(
                req.expected_scope_sha256,
                current.scope.digest,
                action="revocation",
            )
            was_active = current.active
            try:
                revoked = grants.revoke(
                    grant_id,
                    expected_scope_sha256=current.scope.digest,
                    actor=_OPERATOR_ACTOR,
                )
            except HomeRigDenied as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except HomeRigContractError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "schema": OPERATOR_SCHEMA,
            "grant": revoked.to_dict(),
            "revoked_now": was_active,
            "production_activation": False,
        }

    @router.get("/audit")
    def recent_audit(request: Request, limit: int = 50) -> dict:
        _require_operator(request, operator_allowed)
        try:
            rows = audit.recent(limit=limit)
        except HomeRigContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "schema": OPERATOR_SCHEMA,
            "audit": rows,
            "production_activation": False,
        }

    return router
