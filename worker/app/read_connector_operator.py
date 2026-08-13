"""Dormant loopback-only operator/readiness surface for T-037.

This module exposes no model-visible tool and performs no provider network I/O.
A host must inject the already-owned grant store, audit ledger and credential
provider resolver.  The router can therefore preview/create/revoke exact read
scopes and report readiness without learning bearer material.

The module is intentionally NOT mounted by normal worker startup in this slice.
``PRODUCTION_ACTIVATION`` remains false.
"""
from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .netguard import is_loopback
from .read_connector_credential_binding import (
    ReadConnectorCredentialEvidence,
    ReadConnectorCredentialProvider,
)
from .read_connector_package_contract import (
    AuditOutcome,
    Connector,
    ReadConnectorAuditLog,
    ReadConnectorContractError,
    ReadConnectorDenied,
    ReadConnectorGrant,
    ReadConnectorGrantStore,
    ReadConnectorScope,
    normalize_connector,
    readiness_for,
)

OPERATOR_SCHEMA = "kaliv-read-connector-operator/v1"
PRODUCTION_ACTIVATION = False
_OPERATOR_ACTOR = "loopback-operator"
_SCOPE_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MUTATION_LOCK = threading.Lock()


class ReadConnectorScopeReq(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connector: Literal["google_calendar", "google_drive", "gmail", "notion"]
    account_ref: str = Field(min_length=1, max_length=256)
    workspace_ref: str | None = Field(default=None, min_length=1, max_length=256)
    object_scopes: list[str] = Field(min_length=1, max_length=100)
    operations: list[str] = Field(min_length=1, max_length=8)


class CreateReadConnectorGrantReq(ReadConnectorScopeReq):
    expected_scope_sha256: str = Field(min_length=64, max_length=64)


class RevokeReadConnectorGrantReq(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_scope_sha256: str = Field(min_length=64, max_length=64)
    confirm_revoke: Literal[True]


def _operator_allowed(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host == "testclient" or is_loopback(host)


def _require_operator(
    request: Request,
    allowed: Callable[[Request], bool],
) -> None:
    try:
        ok = bool(allowed(request))
    except Exception:
        ok = False
    if not ok:
        raise HTTPException(
            status_code=403,
            detail=(
                "read connector administration is loopback-only, even when "
                "KALIV_WORKER_ALLOW_LAN=1"
            ),
        )


def _scope(req: ReadConnectorScopeReq) -> ReadConnectorScope:
    try:
        return ReadConnectorScope(
            connector=req.connector,
            account_ref=req.account_ref,
            workspace_ref=req.workspace_ref,
            object_scopes=tuple(req.object_scopes),
            operations=tuple(req.operations),
        )
    except ReadConnectorContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _require_digest(value: str, actual: str, *, action: str) -> None:
    if not _SCOPE_DIGEST.fullmatch(value):
        raise HTTPException(
            status_code=422,
            detail="expected_scope_sha256 must be lowercase SHA-256",
        )
    if value != actual:
        raise HTTPException(
            status_code=409,
            detail=f"read connector {action} scope changed since preview",
        )


def _overlaps(a: ReadConnectorScope, b: ReadConnectorScope) -> bool:
    if (
        a.connector != b.connector
        or a.account_ref != b.account_ref
        or a.workspace_ref != b.workspace_ref
    ):
        return False
    return bool(set(a.object_scopes).intersection(b.object_scopes)) and bool(
        set(a.operations).intersection(b.operations)
    )


def _active_overlap(
    store: ReadConnectorGrantStore,
    scope: ReadConnectorScope,
) -> ReadConnectorGrant | None:
    for grant in store.list_grants(connector=scope.connector):
        if _overlaps(grant.scope, scope):
            return grant
    return None


def _credential_state(
    grant: ReadConnectorGrant,
    *,
    provider_for: Callable[[ReadConnectorGrant], ReadConnectorCredentialProvider],
    checked_at: int,
) -> str:
    try:
        provider = provider_for(grant)
        evidence = provider.evidence(now=checked_at)
    except Exception:
        return "unavailable"
    if not isinstance(evidence, ReadConnectorCredentialEvidence):
        return "invalid_credentials"
    if evidence.checked_at != checked_at:
        return "invalid_credentials"
    if (
        evidence.connector != grant.scope.connector
        or evidence.account_ref != grant.scope.account_ref
        or evidence.workspace_ref != grant.scope.workspace_ref
    ):
        return "invalid_credentials"
    return evidence.state


def build_read_connector_operator_router(
    *,
    grants: ReadConnectorGrantStore,
    audit: ReadConnectorAuditLog,
    credential_provider_for: Callable[
        [ReadConnectorGrant], ReadConnectorCredentialProvider
    ],
    operator_allowed: Callable[[Request], bool] = _operator_allowed,
    clock: Callable[[], int] = lambda: int(time.time()),
) -> APIRouter:
    """Build an unmounted operator surface from explicitly injected authority."""
    if not isinstance(grants, ReadConnectorGrantStore):
        raise ReadConnectorContractError("operator grants must be ReadConnectorGrantStore")
    if not isinstance(audit, ReadConnectorAuditLog):
        raise ReadConnectorContractError("operator audit must be ReadConnectorAuditLog")
    if not callable(credential_provider_for) or not callable(operator_allowed) or not callable(clock):
        raise ReadConnectorContractError("operator dependencies must be callable")

    router = APIRouter(prefix="/read-connectors", tags=["read-connectors-operator"])

    @router.post("/grants/preview")
    def preview_grant(request: Request, req: ReadConnectorScopeReq) -> dict:
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
    def create_grant(request: Request, req: CreateReadConnectorGrantReq) -> dict:
        _require_operator(request, operator_allowed)
        scope = _scope(req)
        _require_digest(req.expected_scope_sha256, scope.digest, action="grant")
        with _MUTATION_LOCK:
            overlap = _active_overlap(grants, scope)
            if overlap is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "read connector scope overlaps an active grant; revoke or narrow "
                        f"the existing grant first ({overlap.grant_id})"
                    ),
                )
            try:
                grant = grants.create_grant(scope, actor=_OPERATOR_ACTOR)
            except ReadConnectorContractError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "schema": OPERATOR_SCHEMA,
            "grant": grant.to_dict(),
            "production_activation": False,
        }

    @router.get("/grants")
    def list_grants(
        request: Request,
        connector: str | None = None,
        include_revoked: bool = False,
    ) -> dict:
        _require_operator(request, operator_allowed)
        try:
            normalized: Connector | None = (
                normalize_connector(connector) if connector is not None else None
            )
            visible = grants.list_grants(
                connector=normalized,
                include_revoked=include_revoked,
            )
        except ReadConnectorContractError as exc:
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
        req: RevokeReadConnectorGrantReq,
    ) -> dict:
        _require_operator(request, operator_allowed)
        with _MUTATION_LOCK:
            try:
                current = grants.get_grant(grant_id)
            except ReadConnectorContractError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            if current is None:
                raise HTTPException(status_code=404, detail="unknown read connector grant")
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
            except ReadConnectorDenied as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except ReadConnectorContractError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "schema": OPERATOR_SCHEMA,
            "grant": revoked.to_dict(),
            "revoked_now": was_active,
            "production_activation": False,
        }

    @router.get("/{connector}/grants/{grant_id}/readiness")
    def readiness(
        request: Request,
        connector: str,
        grant_id: str,
    ) -> dict:
        _require_operator(request, operator_allowed)
        try:
            normalized = normalize_connector(connector)
            checked_at = clock()
            if isinstance(checked_at, bool) or not isinstance(checked_at, int) or checked_at < 0:
                raise ReadConnectorContractError("operator clock returned invalid time")
            grant = grants.get_grant(grant_id)
            credential_state = "unavailable"
            if (
                grant is not None
                and grant.active
                and grant.scope.connector == normalized
            ):
                credential_state = _credential_state(
                    grant,
                    provider_for=credential_provider_for,
                    checked_at=checked_at,
                )
            value = readiness_for(
                grants,
                connector=normalized,
                grant_id=grant_id,
                credential_state=credential_state,
                checked_at=checked_at,
            )
        except ReadConnectorContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return value.to_dict()

    @router.get("/audit")
    def recent_audit(
        request: Request,
        limit: int = 50,
        connector: str | None = None,
        account_ref: str | None = None,
        object_scope: str | None = None,
        operation: str | None = None,
        outcome: AuditOutcome | None = None,
    ) -> dict:
        _require_operator(request, operator_allowed)
        try:
            normalized: Connector | None = (
                normalize_connector(connector) if connector is not None else None
            )
            rows = audit.recent(
                limit=limit,
                connector=normalized,
                account_ref=account_ref,
                object_scope=object_scope,
                operation=operation,
                outcome=outcome,
            )
        except ReadConnectorContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "schema": OPERATOR_SCHEMA,
            "audit": rows,
            "production_activation": False,
        }

    return router
