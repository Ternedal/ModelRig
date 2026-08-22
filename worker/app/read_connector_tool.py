"""Default-off ToolGate/runtime composition for T-037 read-first connectors.

This layer mounts the already-qualified authority, credential and pinned-provider
transport behind four separate read-only ToolGate capabilities. It deliberately
adds no provider write operation. Standing grant administration is loopback-only
and never model-visible; every model read still passes ToolGate's public-network
confirmation boundary.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from . import paths as _paths
from . import tools as _tools
from .netguard import is_loopback
from .read_connector_package_contract import (
    Connector,
    ReadConnectorAuditLog,
    ReadConnectorContractError,
    ReadConnectorDenied,
    ReadConnectorGrant,
    ReadConnectorGrantStore,
    ReadConnectorScope,
    allowed_operations,
    capability_id,
    connectors,
    normalize_connector,
    readiness_for,
)
from .read_connector_provider_transport import (
    AccountBoundReadConnectorClient,
    EnvironmentFileReadConnectorCredentialProvider,
    ProviderPinnedTransport,
    ProviderReadRequest,
    ReadConnectorCredentialError,
    ReadConnectorNotFound,
    ReadConnectorRateLimited,
    ReadConnectorRemoteError,
)

_FEATURE_ENV = "KALIV_READ_CONNECTOR_PILOT"
_GRANTS_DB = _paths.resolve(
    "./kaliv-read-connectors.db", env="KALIV_READ_CONNECTOR_GRANTS_DB"
)
_AUDIT_DB = _paths.resolve(
    "./kaliv-read-connector-audit.db", env="KALIV_READ_CONNECTOR_AUDIT_DB"
)
_OPERATOR_ACTOR = "loopback-operator"
_MUTATION_LOCK = threading.Lock()
_REGISTER_LOCK = threading.Lock()
_TOOL_BY_CONNECTOR: dict[Connector, str] = {
    "google_calendar": "google_calendar_read",
    "google_drive": "google_drive_read",
    "gmail": "gmail_read",
    "notion": "notion_read",
}
_NETWORK_DESTINATIONS: dict[Connector, tuple[str, ...]] = {
    "google_calendar": ("www.googleapis.com",),
    "google_drive": ("www.googleapis.com",),
    "gmail": ("www.googleapis.com",),
    "notion": ("api.notion.com",),
}


def read_connector_pilot_enabled() -> bool:
    return os.getenv(_FEATURE_ENV, "0").strip().lower() in {"1", "true", "on"}


def _loopback_allowed(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host == "testclient" or is_loopback(host)


def _require_loopback(request: Request) -> None:
    if not _loopback_allowed(request):
        raise HTTPException(
            status_code=403,
            detail="Read-connector operator surface is loopback-only",
        )


def _credentials(connector: Connector) -> EnvironmentFileReadConnectorCredentialProvider:
    return EnvironmentFileReadConnectorCredentialProvider(connector)


def _store() -> ReadConnectorGrantStore:
    return ReadConnectorGrantStore(_GRANTS_DB)


def _audit() -> ReadConnectorAuditLog:
    return ReadConnectorAuditLog(_AUDIT_DB)


def _iso_now() -> int:
    return int(time.time())


@dataclass
class ReadConnectorRuntime:
    grants: ReadConnectorGrantStore
    audit: ReadConnectorAuditLog
    credential_factory: Callable[[Connector], EnvironmentFileReadConnectorCredentialProvider] = _credentials
    now: Callable[[], int] = _iso_now

    def _matching_grants(
        self,
        *,
        connector: Connector,
        account_ref: str,
        workspace_ref: str | None,
        object_scope: str,
        operation: str,
    ) -> tuple[ReadConnectorGrant, ...]:
        return tuple(
            grant
            for grant in self.grants.list_grants(connector=connector)
            if grant.scope.account_ref == account_ref
            and grant.scope.workspace_ref == workspace_ref
            and grant.scope.allows(object_scope=object_scope, operation=operation)
        )

    def run(self, connector: Connector, args: dict) -> str:
        connector = normalize_connector(connector)
        started = time.monotonic()
        if not isinstance(args, dict):
            raise _tools.ToolDenied("Connector-læsning kræver et objekt med eksplicit scope")

        try:
            request = ProviderReadRequest(
                connector=connector,
                object_scope=args.get("object_scope"),
                operation=args.get("operation"),
                child_ref=args.get("child_ref"),
                query=args.get("query"),
                cursor=args.get("cursor"),
                max_results=args.get("max_results", 50),
            )
        except (ReadConnectorCredentialError, ReadConnectorRemoteError, ReadConnectorContractError) as exc:
            raise _tools.ToolDenied("Connector-læsningens scope/argumenter er ugyldige") from exc

        # ProviderReadRequest validates provider-safe shapes, while the authority
        # contract owns the closed operation set. Enforce that set before any
        # credential metadata, DNS or transport can be touched.
        if request.operation not in allowed_operations(connector):
            raise _tools.ToolDenied("Connector-læsningens operation er ikke tilladt")

        try:
            credentials = self.credential_factory(connector)
        except ReadConnectorCredentialError as exc:
            raise _tools.ToolError("Connector-konfiguration mangler eller er ugyldig") from exc

        matches = self._matching_grants(
            connector=connector,
            account_ref=credentials.account_ref,
            workspace_ref=credentials.workspace_ref,
            object_scope=request.object_scope,
            operation=request.operation,
        )
        if len(matches) != 1:
            detail = "no_active_exact_grant" if not matches else "ambiguous_active_exact_grants"
            self.audit.record(
                connector=connector,
                account_ref=credentials.account_ref,
                workspace_ref=credentials.workspace_ref,
                object_scope=request.object_scope,
                operation=request.operation,
                outcome="blocked",
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                detail=detail,
            )
            if not matches:
                raise _tools.ToolDenied(
                    "Connector-læsningen har ingen aktiv tilladelse til præcis dette scope og denne operation"
                )
            raise _tools.ToolDenied(
                "Connector-læsningen har flere aktive tilladelser til samme scope; ryd scope op først"
            )

        selected = matches[0]
        transport = ProviderPinnedTransport(credentials=credentials)
        reader = AccountBoundReadConnectorClient(grants=self.grants, transport=transport)
        try:
            result = reader.read(selected.grant_id, request, now=self.now())
        except ReadConnectorDenied as exc:
            self._record(
                request=request,
                credentials=credentials,
                selected=selected,
                outcome="blocked",
                detail="authority_or_access_denied",
                started=started,
            )
            raise _tools.ToolDenied("Connector-læsningen blev afvist af aktivt scope/adgang") from exc
        except ReadConnectorRateLimited as exc:
            self._record(
                request=request,
                credentials=credentials,
                selected=selected,
                outcome="error",
                detail="rate_limited",
                started=started,
            )
            raise _tools.ToolError("Connector-providerens rate-limit er nået") from exc
        except ReadConnectorNotFound as exc:
            self._record(
                request=request,
                credentials=credentials,
                selected=selected,
                outcome="error",
                detail="object_unavailable",
                started=started,
            )
            raise _tools.ToolError("Connector-objektet er ikke tilgængeligt") from exc
        except ReadConnectorCredentialError as exc:
            self._record(
                request=request,
                credentials=credentials,
                selected=selected,
                outcome="error",
                detail="credential_not_ready",
                started=started,
            )
            raise _tools.ToolError("Connector-credential mangler, er udløbet eller blev afvist") from exc
        except ReadConnectorRemoteError as exc:
            self._record(
                request=request,
                credentials=credentials,
                selected=selected,
                outcome="error",
                detail="provider_execution_failed",
                started=started,
            )
            raise _tools.ToolError("Connector-providerkaldet fejlede") from exc

        self._record(
            request=request,
            credentials=credentials,
            selected=selected,
            outcome="executed",
            detail="fresh_remote_read",
            started=started,
        )
        return json.dumps(
            {
                "schema": "kaliv-read-connector-tool-result/v1",
                "connector": result.connector,
                "capability_id": capability_id(result.connector),
                "operation": result.operation,
                "object_scope": result.object_scope,
                "next_cursor": result.next_cursor,
                "sources": [source.to_dict() for source in result.sources],
                "value": result.value,
                "production_activation": False,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _record(
        self,
        *,
        request: ProviderReadRequest,
        credentials: EnvironmentFileReadConnectorCredentialProvider,
        selected: ReadConnectorGrant,
        outcome: Literal["executed", "blocked", "error"],
        detail: str,
        started: float,
    ) -> None:
        self.audit.record(
            connector=request.connector,
            account_ref=credentials.account_ref,
            workspace_ref=credentials.workspace_ref,
            object_scope=request.object_scope,
            operation=request.operation,
            outcome=outcome,
            grant_id=selected.grant_id,
            scope_sha256=selected.scope.digest,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            detail=detail,
        )


def build_read_connector_tool(connector: Connector, runtime: ReadConnectorRuntime) -> _tools.Tool:
    connector = normalize_connector(connector)
    return _tools.Tool(
        name=_TOOL_BY_CONNECTOR[connector],
        risk="read",
        impact="read",
        idempotent=False,
        schedulable=False,
        unschedulable_because=(
            "Ekstern connector-læsning kræver et frisk ToolGate-bekræftelseskort"
        ),
        network="public",
        network_destinations=_NETWORK_DESTINATIONS[connector],
        sensitivity="private",
        description=(
            f"Læs fra {connector} inden for én aktiv, tilbagekaldelig exact-scope tilladelse. Read-only."
        ),
        params={
            "type": "object",
            "properties": {
                "object_scope": {"type": "string"},
                "operation": {"type": "string", "enum": list(allowed_operations(connector))},
                "child_ref": {"type": "string"},
                "query": {"type": "string", "maxLength": 500},
                "cursor": {"type": "string", "maxLength": 2048},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": ["object_scope", "operation"],
            "additionalProperties": False,
        },
        run=lambda args, c=connector: runtime.run(c, args),
    )


_DEFAULT_RUNTIME: ReadConnectorRuntime | None = None
_DEFAULT_LOCK = threading.Lock()


def _default_runtime() -> ReadConnectorRuntime:
    global _DEFAULT_RUNTIME
    with _DEFAULT_LOCK:
        if _DEFAULT_RUNTIME is None:
            _DEFAULT_RUNTIME = ReadConnectorRuntime(grants=_store(), audit=_audit())
        return _DEFAULT_RUNTIME


def _lazy_tool(connector: Connector) -> _tools.Tool:
    runtime_proxy = type(
        "_RuntimeProxy",
        (),
        {"run": staticmethod(lambda c, args: _default_runtime().run(c, args))},
    )()
    return build_read_connector_tool(connector, runtime_proxy)  # type: ignore[arg-type]


class GrantScopeReq(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connector: Literal["google_calendar", "google_drive", "gmail", "notion"]
    object_scopes: list[str] = Field(min_length=1, max_length=100)
    operations: list[str] = Field(min_length=1, max_length=8)


class CreateGrantReq(GrantScopeReq):
    expected_scope_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )


class RevokeGrantReq(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_scope_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    confirm_revoke: Literal[True]


def _scope_from_req(req: GrantScopeReq) -> ReadConnectorScope:
    connector = normalize_connector(req.connector)
    try:
        credentials = _credentials(connector)
    except ReadConnectorCredentialError as exc:
        raise HTTPException(
            status_code=409,
            detail="Connector account/token-file configuration is missing or invalid",
        ) from exc
    try:
        return ReadConnectorScope(
            connector=connector,
            account_ref=credentials.account_ref,
            workspace_ref=credentials.workspace_ref,
            object_scopes=tuple(req.object_scopes),
            operations=tuple(req.operations),
        )
    except ReadConnectorContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _overlaps(a: ReadConnectorScope, b: ReadConnectorScope) -> bool:
    return (
        a.connector == b.connector
        and a.account_ref == b.account_ref
        and a.workspace_ref == b.workspace_ref
        and bool(set(a.object_scopes).intersection(b.object_scopes))
        and bool(set(a.operations).intersection(b.operations))
    )


def build_read_connector_router() -> APIRouter:
    router = APIRouter(prefix="/read-connectors", tags=["read-connectors"])

    @router.get("/grants")
    def grants_view(
        request: Request,
        connector: Literal["google_calendar", "google_drive", "gmail", "notion"] | None = None,
        include_revoked: bool = False,
    ) -> dict:
        _require_loopback(request)
        store = _store()
        try:
            return {
                "grants": [
                    grant.to_dict()
                    for grant in store.list_grants(
                        connector=normalize_connector(connector) if connector else None,
                        include_revoked=include_revoked,
                    )
                ],
                "production_activation": False,
            }
        finally:
            store.close()

    @router.post("/grants/preview")
    def preview_grant(request: Request, req: GrantScopeReq) -> dict:
        _require_loopback(request)
        scope = _scope_from_req(req)
        return {
            "scope": scope.to_dict(),
            "scope_sha256": scope.digest,
            "grant_persisted": False,
            "production_activation": False,
        }

    @router.post("/grants")
    def create_grant(request: Request, req: CreateGrantReq) -> dict:
        _require_loopback(request)
        scope = _scope_from_req(req)
        if req.expected_scope_sha256 != scope.digest:
            raise HTTPException(status_code=409, detail="Connector scope changed since preview")
        with _MUTATION_LOCK:
            store = _store()
            try:
                overlap = next(
                    (
                        grant
                        for grant in store.list_grants(connector=scope.connector)
                        if _overlaps(grant.scope, scope)
                    ),
                    None,
                )
                if overlap is not None:
                    raise HTTPException(status_code=409, detail="Connector scope overlaps an active grant")
                grant = store.create_grant(scope, actor=_OPERATOR_ACTOR)
            finally:
                store.close()
        return {"grant": grant.to_dict(), "production_activation": False}

    @router.post("/grants/{grant_id}/revoke")
    def revoke_grant(request: Request, grant_id: str, req: RevokeGrantReq) -> dict:
        _require_loopback(request)
        with _MUTATION_LOCK:
            store = _store()
            try:
                try:
                    current = store.get_grant(grant_id)
                except ReadConnectorContractError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
                if current is None:
                    raise HTTPException(status_code=404, detail="Unknown connector grant")
                if req.expected_scope_sha256 != current.scope.digest:
                    raise HTTPException(status_code=409, detail="Connector scope changed since preview")
                try:
                    revoked = store.revoke(
                        grant_id,
                        expected_scope_sha256=req.expected_scope_sha256,
                        actor=_OPERATOR_ACTOR,
                    )
                except ReadConnectorDenied as exc:
                    raise HTTPException(status_code=409, detail=str(exc)) from exc
            finally:
                store.close()
        return {"grant": revoked.to_dict(), "production_activation": False}

    @router.get("/readiness/{connector}/{grant_id}")
    def readiness_view(
        request: Request,
        connector: Literal["google_calendar", "google_drive", "gmail", "notion"],
        grant_id: str,
    ) -> dict:
        _require_loopback(request)
        normalized = normalize_connector(connector)
        store = _store()
        try:
            try:
                credentials = _credentials(normalized)
                state = credentials.credential_state(now=_iso_now())
            except ReadConnectorCredentialError:
                state = "missing_credentials"
            return readiness_for(
                store,
                connector=normalized,
                grant_id=grant_id,
                credential_state=state,
            ).to_dict()
        except ReadConnectorContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            store.close()

    @router.get("/audit")
    def audit_view(
        request: Request,
        limit: int = Query(default=50, ge=1, le=500),
        connector: Literal["google_calendar", "google_drive", "gmail", "notion"] | None = None,
        account_ref: str | None = None,
        object_scope: str | None = None,
        operation: str | None = None,
        outcome: Literal["executed", "blocked", "error"] | None = None,
    ) -> dict:
        _require_loopback(request)
        audit = _audit()
        try:
            try:
                entries = audit.recent(
                    limit=limit,
                    connector=normalize_connector(connector) if connector else None,
                    account_ref=account_ref,
                    object_scope=object_scope,
                    operation=operation,
                    outcome=outcome,
                )
            except ReadConnectorContractError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            return {"entries": entries, "production_activation": False}
        finally:
            audit.close()

    return router


def _recognized_tool(connector: Connector, existing: _tools.Tool) -> bool:
    return (
        existing.name == _TOOL_BY_CONNECTOR[connector]
        and existing.risk == "read"
        and existing.impact == "read"
        and existing.network == "public"
        and existing.network_destinations == _NETWORK_DESTINATIONS[connector]
    )


def register_read_connector_pilot(app) -> bool:
    """Atomically register the four read capabilities under explicit opt-in."""
    if not read_connector_pilot_enabled():
        return False

    with _REGISTER_LOCK:
        present: list[Connector] = []
        for connector in connectors():
            name = _TOOL_BY_CONNECTOR[connector]
            existing = _tools.REGISTRY.get(name)
            if existing is None:
                continue
            if not _recognized_tool(connector, existing):
                raise RuntimeError(f"{name} is already registered by another capability")
            present.append(connector)

        if present:
            if len(present) == len(connectors()):
                return False
            raise RuntimeError("T-037 read connector registry is partially populated")

        # Build all descriptors before mutating the registry so descriptor
        # construction cannot leave a half-registered capability package.
        prepared = tuple(
            (_TOOL_BY_CONNECTOR[connector], _lazy_tool(connector))
            for connector in connectors()
        )
        for name, tool in prepared:
            _tools.REGISTRY[name] = tool
        app.include_router(build_read_connector_router())
        return True
