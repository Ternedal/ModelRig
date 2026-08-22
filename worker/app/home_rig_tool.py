"""Default-off ToolGate/runtime composition for T-038 home/rig reads.

This layer composes the qualified T-038 authority, T-032 one-use sharing gate,
pinned Home Assistant/RigGate transports and freshness/audit boundary. It
exposes read-only provider access plus side-effect-free wake/control previews;
there is no wake/control execution path in this module.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from . import paths as _paths
from . import tools as _tools
from .data_sharing import DataSharingContractError, DataSharingDenied, DataSharingLedger
from .home_assistant_provider_transport import (
    HomeAssistantConnection,
    HomeAssistantTransportError,
    execute_home_assistant_state_read,
)
from .home_rig_connector_contract import (
    HomeRigAuditLog,
    HomeRigContractError,
    HomeRigDenied,
    HomeRigGrant,
    HomeRigGrantStore,
    build_control_preview,
)
from .home_rig_operator import build_home_rig_operator_router
from .home_rig_provider_gate import (
    authorize_home_assistant_state_request,
    finish_home_assistant_state_request,
    prepare_home_assistant_state_sharing_request,
)
from .home_rig_read_boundary import HomeRigReadClaim, fulfill_read, prepare_read
from .netguard import is_loopback
from .riggate_provider_transport import (
    RigGateConnection,
    RigGateTransportError,
    execute_riggate_status_read,
)
from .riggate_v1_contract import (
    authorize_riggate_request,
    finish_riggate_request,
    prepare_riggate_sharing_request,
)

_FEATURE_ENV = "KALIV_HOME_RIG_PILOT"
_GRANTS_DB = _paths.resolve("./kaliv-home-rig-grants.db", env="KALIV_HOME_RIG_GRANTS_DB")
_AUDIT_DB = _paths.resolve("./kaliv-home-rig-audit.db", env="KALIV_HOME_RIG_AUDIT_DB")
_SHARING_DB = _paths.resolve("./kaliv-data-sharing.db", env="KALIV_DATA_SHARING_DB")
_OPERATOR_ACTOR = "loopback-operator"
_REGISTER_LOCK = threading.Lock()
_DEFAULT_LOCK = threading.Lock()
PRODUCTION_ACTIVATION = False

_PREVIEW_TOOL = "home_rig_preview"
_APP_MOUNT_MARKER = "_kaliv_home_rig_pilot_mounted"


def home_rig_pilot_enabled() -> bool:
    return os.getenv(_FEATURE_ENV, "0").strip().lower() in {"1", "true", "on"}


def _env_text(name: str) -> str:
    """Read deployment settings without presenting them as readiness switches."""
    return os.getenv(name, "").strip()


def _env_bool(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "on"}


def _now() -> int:
    return int(time.time())


def _operator_allowed(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host == "testclient" or is_loopback(host)


def _require_operator(request: Request) -> None:
    if not _operator_allowed(request):
        raise HTTPException(status_code=403, detail="home/rig sharing administration is loopback-only")


def _home_assistant_connection() -> HomeAssistantConnection:
    origin = _env_text("KALIV_HOME_ASSISTANT_ORIGIN")
    token_file = _env_text("KALIV_HOME_ASSISTANT_TOKEN_FILE")
    if not origin or not token_file:
        raise HomeAssistantTransportError("Home Assistant deployment configuration is incomplete")
    return HomeAssistantConnection(
        origin=origin,
        token_file=Path(token_file),
        allow_insecure_http=_env_bool("KALIV_HOME_ASSISTANT_ALLOW_INSECURE_HTTP"),
    )


def _riggate_connection() -> RigGateConnection:
    origin = _env_text("KALIV_RIGGATE_ORIGIN")
    token_file = _env_text("KALIV_RIGGATE_TOKEN_FILE")
    if not origin or not token_file:
        raise RigGateTransportError("RigGate deployment configuration is incomplete")
    return RigGateConnection(
        origin=origin,
        token_file=Path(token_file),
        allow_insecure_http=_env_bool("KALIV_RIGGATE_ALLOW_INSECURE_HTTP"),
    )


def _purpose(target_kind: Literal["rig", "entity"], operation: str) -> tuple[str, str, str]:
    if target_kind == "rig":
        label = "health" if operation == "rig_health" else "power/readiness"
        return "operational", "status_brief", f"Read {label} for one explicitly scoped rig."
    return "private", "status_brief", "Read one explicitly scoped Home Assistant entity state."


@dataclass
class HomeRigRuntime:
    grants: HomeRigGrantStore
    audit: HomeRigAuditLog
    sharing: DataSharingLedger
    now: Callable[[], int] = _now
    max_freshness_seconds: int = 120

    def _matching_grants(
        self,
        *,
        target_kind: Literal["rig", "entity"],
        target_id: str,
        operation: str,
    ) -> tuple[HomeRigGrant, ...]:
        return tuple(
            grant
            for grant in self.grants.list_grants()
            if grant.scope.allows(
                target_kind=target_kind,
                target_id=target_id,
                operation=operation,
            )
        )

    def _exact_grant(
        self,
        *,
        target_kind: Literal["rig", "entity"],
        target_id: str,
        operation: str,
        audit_block: bool = True,
    ) -> HomeRigGrant:
        matches = self._matching_grants(
            target_kind=target_kind,
            target_id=target_id,
            operation=operation,
        )
        if len(matches) == 1:
            return matches[0]
        if audit_block:
            try:
                self.audit.record(
                    target_kind=target_kind,
                    target_id=target_id,
                    operation=operation,
                    outcome="blocked",
                    detail="no_exact_grant" if not matches else "ambiguous_exact_grants",
                    now=self.now(),
                )
            except HomeRigContractError:
                pass
        if not matches:
            raise HomeRigDenied("no active exact home/rig grant")
        raise HomeRigDenied("multiple active home/rig grants match the same read")

    def prepare_claim(
        self,
        *,
        target_kind: Literal["rig", "entity"],
        target_id: str,
        operation: str,
    ) -> HomeRigReadClaim:
        grant = self._exact_grant(
            target_kind=target_kind,
            target_id=target_id,
            operation=operation,
        )
        return prepare_read(
            self.grants,
            grant.grant_id,
            target_kind=target_kind,
            target_id=target_id,
            operation=operation,
            now=self.now(),
        )

    def sharing_request(self, claim: HomeRigReadClaim):
        category, purpose_code, purpose = _purpose(claim.target_kind, claim.operation)
        summary = (
            "Scoped RigGate status read"
            if claim.target_kind == "rig"
            else "Scoped Home Assistant entity-state read"
        )
        if claim.target_kind == "rig":
            return prepare_riggate_sharing_request(
                self.grants,
                claim,
                data_category=category,
                purpose_code=purpose_code,
                purpose=purpose,
                summary=summary,
            )
        return prepare_home_assistant_state_sharing_request(
            self.grants,
            claim,
            data_category=category,
            purpose_code=purpose_code,
            purpose=purpose,
            summary=summary,
        )

    def _finish_config_failure(
        self,
        authorized,
        *,
        target_kind: Literal["rig", "entity"],
        now: int,
    ) -> None:
        if target_kind == "rig":
            finish_riggate_request(
                self.sharing,
                authorized,
                outcome="failed",
                bytes_sent=0,
                error_code="provider_config_failed",
                now=now,
            )
        else:
            finish_home_assistant_state_request(
                self.sharing,
                authorized,
                outcome="failed",
                bytes_sent=0,
                error_code="provider_config_failed",
                now=now,
            )

    def read(
        self,
        *,
        target_kind: Literal["rig", "entity"],
        target_id: str,
        operation: str,
        permission_id: str,
    ) -> str:
        """Perform one exact read; provider unavailability normalizes to unknown."""
        try:
            claim = self.prepare_claim(
                target_kind=target_kind,
                target_id=target_id,
                operation=operation,
            )
            category, purpose_code, purpose = _purpose(target_kind, operation)
            summary = (
                "Scoped RigGate status read"
                if target_kind == "rig"
                else "Scoped Home Assistant entity-state read"
            )
            authorized_at = self.now()

            if target_kind == "rig":
                authorized = authorize_riggate_request(
                    self.grants,
                    self.sharing,
                    claim,
                    data_category=category,
                    purpose_code=purpose_code,
                    purpose=purpose,
                    summary=summary,
                    permission_id=permission_id,
                    now=authorized_at,
                )
                try:
                    connection = _riggate_connection()
                except RigGateTransportError:
                    self._finish_config_failure(authorized, target_kind="rig", now=self.now())
                    raise
                try:
                    evidence = execute_riggate_status_read(
                        self.grants,
                        self.sharing,
                        authorized,
                        connection,
                        now=self.now(),
                    )
                except RigGateTransportError:
                    # The transport already closed the one-use T-032 receipt as
                    # failed. T-038 still owes the caller a safe status: no
                    # trustworthy provider evidence is exactly "unavailable".
                    source_state = None
                    observed_at = None
                else:
                    source_state = evidence.state
                    observed_at = evidence.observed_at
            else:
                authorized = authorize_home_assistant_state_request(
                    self.grants,
                    self.sharing,
                    claim,
                    data_category=category,
                    purpose_code=purpose_code,
                    purpose=purpose,
                    summary=summary,
                    permission_id=permission_id,
                    now=authorized_at,
                )
                try:
                    connection = _home_assistant_connection()
                except HomeAssistantTransportError:
                    self._finish_config_failure(authorized, target_kind="entity", now=self.now())
                    raise
                try:
                    evidence = execute_home_assistant_state_read(
                        self.grants,
                        self.sharing,
                        authorized,
                        connection,
                        now=self.now(),
                    )
                except HomeAssistantTransportError:
                    source_state = None
                    observed_at = None
                else:
                    source_state = evidence.state
                    observed_at = evidence.observed_at

            receipt = fulfill_read(
                self.grants,
                self.audit,
                claim,
                source_state=source_state,
                observed_at=observed_at,
                now=self.now(),
                max_freshness_seconds=self.max_freshness_seconds,
            )
            return json.dumps(
                receipt.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (DataSharingDenied, HomeRigDenied) as exc:
            raise _tools.ToolDenied("home/rig-læsningen mangler præcis aktiv tilladelse") from exc
        except (DataSharingContractError, HomeRigContractError) as exc:
            raise _tools.ToolDenied("home/rig-læsningens scope eller delingstilladelse er ugyldig") from exc
        except (HomeAssistantTransportError, RigGateTransportError) as exc:
            # These are deployment/configuration failures. Actual provider
            # unavailability after a valid request boundary is normalized above.
            try:
                self.audit.record(
                    target_kind=target_kind,
                    target_id=target_id,
                    operation=operation,
                    outcome="error",
                    detail="provider_configuration_failed",
                    now=self.now(),
                )
            except HomeRigContractError:
                pass
            raise _tools.ToolError("home/rig-providerkonfigurationen fejlede") from exc

    def preview(
        self,
        *,
        target_kind: Literal["rig", "entity"],
        target_id: str,
        action: str,
    ) -> str:
        operation = "wake_preview" if target_kind == "rig" else "control_preview"
        try:
            grant = self._exact_grant(
                target_kind=target_kind,
                target_id=target_id,
                operation=operation,
            )
            preview = build_control_preview(
                self.grants,
                grant.grant_id,
                target_kind=target_kind,
                target_id=target_id,
                action=action,
                now=self.now(),
            )
        except (HomeRigDenied, HomeRigContractError) as exc:
            raise _tools.ToolDenied("home/rig-preview er uden for aktivt exact scope") from exc
        return json.dumps(
            preview.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def _read_tool(name: str, runtime: HomeRigRuntime) -> _tools.Tool:
    rig = name == "riggate_read"
    properties = (
        {
            "rig_id": {"type": "string"},
            "operation": {
                "type": "string",
                "enum": ["rig_health", "rig_power_readiness"],
            },
            "permission_id": {
                "type": "string",
                "pattern": "^dsp_[0-9a-f]{32}$",
            },
        }
        if rig
        else {
            "entity_id": {"type": "string"},
            "permission_id": {
                "type": "string",
                "pattern": "^dsp_[0-9a-f]{32}$",
            },
        }
    )
    required = ["rig_id", "operation", "permission_id"] if rig else ["entity_id", "permission_id"]

    if rig:
        runner = lambda args: runtime.read(
            target_kind="rig",
            target_id=args.get("rig_id", ""),
            operation=args.get("operation", ""),
            permission_id=args.get("permission_id", ""),
        )
    else:
        runner = lambda args: runtime.read(
            target_kind="entity",
            target_id=args.get("entity_id", ""),
            operation="entity_state",
            permission_id=args.get("permission_id", ""),
        )

    return _tools.Tool(
        name=name,
        risk="read",
        impact="read",
        idempotent=False,
        schedulable=False,
        unschedulable_because="T-032 delingstilladelsen er exact-request og one-use",
        network="configured_service",
        network_destinations=("riggate",) if rig else ("home_assistant",),
        sensitivity="operational" if rig else "private",
        description=(
            "Læs health eller power/readiness fra én eksplicit scoped RigGate-rig."
            if rig
            else "Læs state fra ét eksplicit scoped Home Assistant entity-id."
        ),
        params={
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
        run=runner,
    )


def _preview_tool(runtime: HomeRigRuntime) -> _tools.Tool:
    return _tools.Tool(
        name=_PREVIEW_TOOL,
        risk="read",
        impact="read",
        idempotent=True,
        schedulable=False,
        unschedulable_because="preview er bundet til et aktuelt, tilbagekaldeligt home/rig scope",
        network="none",
        sensitivity="private",
        description="Vis præcis wake/control-preview uden at udføre nogen side effect.",
        params={
            "type": "object",
            "properties": {
                "target_kind": {"type": "string", "enum": ["rig", "entity"]},
                "target_id": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": ["wake", "turn_on", "turn_off", "toggle"],
                },
            },
            "required": ["target_kind", "target_id", "action"],
            "additionalProperties": False,
        },
        run=lambda args: runtime.preview(
            target_kind=args.get("target_kind", ""),
            target_id=args.get("target_id", ""),
            action=args.get("action", ""),
        ),
    )


class SharingReadReq(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_kind: Literal["rig", "entity"]
    target_id: str = Field(min_length=1, max_length=255)
    operation: Literal["rig_health", "rig_power_readiness", "entity_state"]


class SharingProposalReq(SharingReadReq):
    expected_request_digest: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )


class PermissionDecisionReq(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: Literal[True]


def _sharing_claim(runtime: HomeRigRuntime, req: SharingReadReq) -> HomeRigReadClaim:
    if (req.target_kind == "rig") != (req.operation in {"rig_health", "rig_power_readiness"}):
        raise HTTPException(status_code=422, detail="target kind and read operation do not match")
    try:
        return runtime.prepare_claim(
            target_kind=req.target_kind,
            target_id=req.target_id,
            operation=req.operation,
        )
    except (HomeRigContractError, HomeRigDenied) as exc:
        raise HTTPException(status_code=409, detail="no unique active exact home/rig grant") from exc


def build_home_rig_runtime_router(runtime: HomeRigRuntime) -> APIRouter:
    root = APIRouter()
    root.include_router(build_home_rig_operator_router(grants=runtime.grants, audit=runtime.audit))
    sharing = APIRouter(prefix="/home-rig/sharing", tags=["home-rig-sharing"])

    @sharing.post("/preview")
    def sharing_preview(request: Request, req: SharingReadReq) -> dict:
        _require_operator(request)
        claim = _sharing_claim(runtime, req)
        try:
            sharing_request = runtime.sharing_request(claim)
        except (DataSharingContractError, HomeRigContractError, HomeRigDenied) as exc:
            raise HTTPException(status_code=422, detail="invalid exact sharing request") from exc
        return {
            "request": sharing_request.preview(),
            "grant_id": claim.grant_id,
            "scope_sha256": claim.scope_sha256,
            "permission_persisted": False,
            "production_activation": False,
        }

    @sharing.post("/permissions")
    def propose_permission(request: Request, req: SharingProposalReq) -> dict:
        _require_operator(request)
        claim = _sharing_claim(runtime, req)
        sharing_request = runtime.sharing_request(claim)
        if sharing_request.digest != req.expected_request_digest:
            raise HTTPException(status_code=409, detail="sharing request changed since preview")
        try:
            proposal = runtime.sharing.propose(sharing_request, now=runtime.now())
        except (DataSharingDenied, DataSharingContractError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"proposal": proposal.to_dict(), "production_activation": False}

    @sharing.post("/permissions/{permission_id}/approve")
    def approve_permission(request: Request, permission_id: str, req: PermissionDecisionReq) -> dict:
        _require_operator(request)
        try:
            runtime.sharing.approve(permission_id, actor=_OPERATOR_ACTOR, now=runtime.now())
        except (DataSharingDenied, DataSharingContractError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"permission_id": permission_id, "status": "approved", "production_activation": False}

    @sharing.post("/permissions/{permission_id}/revoke")
    def revoke_permission(request: Request, permission_id: str, req: PermissionDecisionReq) -> dict:
        _require_operator(request)
        try:
            runtime.sharing.revoke(permission_id, actor=_OPERATOR_ACTOR, now=runtime.now())
        except (DataSharingDenied, DataSharingContractError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"permission_id": permission_id, "status": "revoked", "production_activation": False}

    @sharing.get("/audit")
    def sharing_audit(request: Request, limit: int = 50) -> dict:
        _require_operator(request)
        try:
            rows = runtime.sharing.recent_events(limit=limit)
        except DataSharingContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"events": rows, "production_activation": False}

    root.include_router(sharing)
    return root


_DEFAULT_RUNTIME: HomeRigRuntime | None = None


def _default_runtime() -> HomeRigRuntime:
    global _DEFAULT_RUNTIME
    with _DEFAULT_LOCK:
        if _DEFAULT_RUNTIME is None:
            _DEFAULT_RUNTIME = HomeRigRuntime(
                grants=HomeRigGrantStore(_GRANTS_DB),
                audit=HomeRigAuditLog(_AUDIT_DB),
                sharing=DataSharingLedger(_SHARING_DB),
            )
        return _DEFAULT_RUNTIME


def _prepared_tools(runtime: HomeRigRuntime) -> tuple[tuple[str, _tools.Tool], ...]:
    return (
        ("riggate_read", _read_tool("riggate_read", runtime)),
        ("home_assistant_read", _read_tool("home_assistant_read", runtime)),
        (_PREVIEW_TOOL, _preview_tool(runtime)),
    )


def _route_collection(app):
    router = getattr(app, "router", None)
    routes = getattr(router, "routes", None)
    if routes is not None:
        return routes
    return getattr(app, "routes", ())


def _iter_route_paths(routes, seen: set[int] | None = None):
    seen = set() if seen is None else seen
    for route in routes:
        path = getattr(route, "path", None)
        if isinstance(path, str):
            yield path
        nested = getattr(route, "original_router", None)
        nested_routes = getattr(nested, "routes", None)
        if nested_routes is not None and id(nested) not in seen:
            seen.add(id(nested))
            yield from _iter_route_paths(nested_routes, seen)


def _routes_mounted(app) -> bool:
    state = getattr(app, "state", None)
    if state is not None and bool(getattr(state, _APP_MOUNT_MARKER, False)):
        return True
    return any(path.startswith("/home-rig") for path in _iter_route_paths(_route_collection(app)))


def _recognized(existing: _tools.Tool, expected: _tools.Tool) -> bool:
    fields = (
        "name",
        "risk",
        "description",
        "params",
        "sensitivity",
        "isolate",
        "env_allow",
        "network",
        "network_destinations",
        "impact",
        "cancellation",
        "idempotent",
        "schedulable",
        "unschedulable_because",
    )
    return all(getattr(existing, field) == getattr(expected, field) for field in fields) and (
        getattr(existing.run, "__module__", None) == __name__
    )


def _mount_routes(app, runtime: HomeRigRuntime) -> None:
    routes = _route_collection(app)
    before = len(routes) if hasattr(routes, "__len__") else None
    try:
        app.include_router(build_home_rig_runtime_router(runtime))
        state = getattr(app, "state", None)
        if state is not None:
            setattr(state, _APP_MOUNT_MARKER, True)
    except Exception:
        if before is not None:
            current = _route_collection(app)
            try:
                del current[before:]
            except (AttributeError, TypeError):
                pass
        state = getattr(app, "state", None)
        if state is not None:
            setattr(state, _APP_MOUNT_MARKER, False)
        raise


def register_home_rig_pilot(app) -> bool:
    """Atomically compose default-off T-038 tools plus loopback operator surface."""
    if not home_rig_pilot_enabled():
        return False

    with _REGISTER_LOCK:
        runtime = _default_runtime()
        prepared = _prepared_tools(runtime)
        present = []
        for name, expected in prepared:
            existing = _tools.REGISTRY.get(name)
            if existing is None:
                continue
            if not _recognized(existing, expected):
                raise RuntimeError(f"{name} is already registered by another capability")
            present.append(name)

        routes_mounted = _routes_mounted(app)
        if present:
            if len(present) != len(prepared):
                raise RuntimeError("T-038 home/rig registry is partially populated")
            if routes_mounted:
                return False
            _mount_routes(app, runtime)
            return True
        if routes_mounted:
            raise RuntimeError("T-038 home/rig routes are mounted without registry tools")

        _mount_routes(app, runtime)
        for name, tool in prepared:
            _tools.REGISTRY[name] = tool
        return True
