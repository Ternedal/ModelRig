"""Loopback-only operator administration for T-036 GitHub grants.

This module is intentionally not a ToolGate capability. A model can use the
read-only ``github_read`` tool only after a grant exists; it cannot create,
expand, or revoke its own standing authority.

The route follows the existing schedule-admin boundary: local worker admission
is loopback-only even when the worker is otherwise LAN-exposed, while the
authenticated Go backend remains the remote operator boundary.
"""
from __future__ import annotations

import re
import threading
from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .github_connector_contract import (
    GitHubConnectorContractError,
    GitHubConnectorDenied,
    GitHubConnectorGrant,
    GitHubConnectorGrantStore,
    GitHubConnectorScope,
)
from .github_connector_transport import (
    EnvironmentFileGitHubCredentialProvider,
    GitHubCredentialError,
)
from .netguard import is_loopback

GitHubReadOperation = Literal["repository", "issue", "pull_request", "workflow_run"]
_SCOPE_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_OPERATOR_ACTOR = "loopback-operator"
_MUTATION_LOCK = threading.Lock()


class GitHubGrantScopeReq(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repositories: list[str] = Field(min_length=1, max_length=25)
    operations: list[GitHubReadOperation] = Field(min_length=1, max_length=4)


class CreateGitHubGrantReq(GitHubGrantScopeReq):
    expected_scope_sha256: str = Field(min_length=64, max_length=64)


class RevokeGitHubGrantReq(BaseModel):
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
                "GitHub connector administration is loopback-only, even when "
                "KALIV_WORKER_ALLOW_LAN=1"
            ),
        )


def _credential_account() -> str:
    """Return configured account without reading the token file itself."""
    return EnvironmentFileGitHubCredentialProvider().account


def _scope(
    req: GitHubGrantScopeReq,
    account_provider: Callable[[], str],
) -> GitHubConnectorScope:
    try:
        account = account_provider()
        return GitHubConnectorScope(
            account=account,
            repositories=tuple(req.repositories),
            operations=tuple(req.operations),
        )
    except GitHubCredentialError as exc:
        raise HTTPException(
            status_code=409,
            detail="GitHub credential account/token-file configuration is missing or invalid",
        ) from exc
    except GitHubConnectorContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _require_digest(value: str, actual: str, *, action: str) -> None:
    if not _SCOPE_DIGEST.fullmatch(value):
        raise HTTPException(status_code=422, detail="expected_scope_sha256 must be lowercase SHA-256")
    if value != actual:
        raise HTTPException(
            status_code=409,
            detail=f"GitHub {action} scope changed since preview; preview the exact scope again",
        )


def _overlaps(a: GitHubConnectorScope, b: GitHubConnectorScope) -> bool:
    if a.account != b.account:
        return False
    return bool(set(a.repositories).intersection(b.repositories)) and bool(
        set(a.operations).intersection(b.operations)
    )


def _active_overlap(
    store: GitHubConnectorGrantStore,
    scope: GitHubConnectorScope,
) -> GitHubConnectorGrant | None:
    for grant in store.list_grants():
        if _overlaps(grant.scope, scope):
            return grant
    return None


def build_github_connector_admin_router(
    *,
    grant_factory: Callable[[], GitHubConnectorGrantStore] = GitHubConnectorGrantStore,
    account_provider: Callable[[], str] = _credential_account,
    operator_allowed: Callable[[Request], bool] = _operator_allowed,
) -> APIRouter:
    router = APIRouter(prefix="/github-connector", tags=["github-connector-admin"])

    @router.post("/grants/preview")
    def preview_grant(request: Request, req: GitHubGrantScopeReq) -> dict:
        _require_operator(request, operator_allowed)
        scope = _scope(req, account_provider)
        return {
            "connector": "github",
            "scope": scope.to_dict(),
            "scope_sha256": scope.digest,
            "grant_persisted": False,
            "production_activation": False,
        }

    @router.post("/grants")
    def create_grant(request: Request, req: CreateGitHubGrantReq) -> dict:
        _require_operator(request, operator_allowed)
        scope = _scope(req, account_provider)
        _require_digest(req.expected_scope_sha256, scope.digest, action="grant")

        # Worker deployment is a single process. Serialise local operator writes
        # so preview-bound create cannot race another create in this process.
        # If a DB is modified externally or by another process, the read runtime
        # still fails closed on ambiguous grants rather than choosing one.
        with _MUTATION_LOCK:
            store = grant_factory()
            try:
                overlap = _active_overlap(store, scope)
                if overlap is not None:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "GitHub scope overlaps an active grant; revoke or narrow the existing "
                            f"grant first ({overlap.grant_id})"
                        ),
                    )
                grant = store.create(scope, actor=_OPERATOR_ACTOR)
            except GitHubConnectorDenied as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except GitHubConnectorContractError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            finally:
                store.close()
        return {
            "connector": "github",
            "grant": grant.to_dict(),
            "production_activation": False,
        }

    @router.post("/grants/{grant_id}/revoke")
    def revoke_grant(
        request: Request,
        grant_id: str,
        req: RevokeGitHubGrantReq,
    ) -> dict:
        _require_operator(request, operator_allowed)
        if not _SCOPE_DIGEST.fullmatch(req.expected_scope_sha256):
            raise HTTPException(
                status_code=422,
                detail="expected_scope_sha256 must be lowercase SHA-256",
            )
        with _MUTATION_LOCK:
            store = grant_factory()
            try:
                try:
                    current = store.get(grant_id)
                except GitHubConnectorContractError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
                if current is None:
                    raise HTTPException(status_code=404, detail="unknown GitHub connector grant")
                _require_digest(
                    req.expected_scope_sha256,
                    current.scope.digest,
                    action="revocation",
                )
                was_active = current.active
                try:
                    revoked = store.revoke(
                        grant_id,
                        actor=_OPERATOR_ACTOR,
                    )
                except GitHubConnectorDenied as exc:
                    raise HTTPException(status_code=404, detail=str(exc)) from exc
            finally:
                store.close()
        return {
            "connector": "github",
            "grant": revoked.to_dict(),
            "revoked_now": was_active,
            "production_activation": False,
        }

    return router
