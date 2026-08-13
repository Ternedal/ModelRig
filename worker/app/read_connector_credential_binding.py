"""T-037 dormant credential binding for Google/Notion read connectors.

This module is deliberately *not* a provider HTTP transport and does not own
credential storage.  It closes the authority gap between the landed exact
connector grant and the landed provider request plan before any live provider
adapter is allowed to exist:

* one credential provider is bound to one exact connector/account/workspace;
* credential state is explicit and fail-closed without exposing secret bytes;
* preparing a request re-authorizes the exact object + operation grant;
* obtaining the bearer re-authorizes again, so revoke between prepare/execute
  stops the request before credential material is released;
* request host, redirect policy and execute-time credential mode are rechecked;
* bearer material is never cached, serialized or projected into audit;
* no socket, HTTP client, environment lookup, file store, ToolGate or route is
  imported here.

A later transport/secure-storage slice must inject implementations behind the
protocol below. ``production_activation`` remains structurally false.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Protocol

from .read_connector_package_contract import (
    Connector,
    CredentialState,
    ReadConnectorDenied,
    ReadConnectorGrantStore,
    capability_id,
    normalize_connector,
)
from .read_connector_provider_request import ProviderRequestPlan

CREDENTIAL_SCHEMA = "kaliv-read-connector-credential-evidence/v1"
BINDING_SCHEMA = "kaliv-read-connector-credential-binding/v1"
PRODUCTION_ACTIVATION = False

CredentialKind = Literal["google_oauth_bearer", "notion_integration_bearer"]

_CREDENTIAL_KIND: dict[str, CredentialKind] = {
    "google_calendar": "google_oauth_bearer",
    "google_drive": "google_oauth_bearer",
    "gmail": "google_oauth_bearer",
    "notion": "notion_integration_bearer",
}
_EXPECTED_HOST = {
    "google_calendar": "www.googleapis.com",
    "google_drive": "www.googleapis.com",
    "gmail": "gmail.googleapis.com",
    "notion": "api.notion.com",
}
_ALLOWED_STATES = frozenset(
    {
        "ready",
        "missing_credentials",
        "expired_credentials",
        "invalid_credentials",
        "unavailable",
    }
)
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=+-]{0,255}$")
_GRANT_ID = re.compile(r"^rcg_[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_BEARER_BYTES = 4_096


class ReadConnectorCredentialError(RuntimeError):
    """Credential evidence/material is invalid without exposing secret data."""


def _now(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReadConnectorCredentialError("credential time must be a non-negative integer")
    return value


def _ref(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise ReadConnectorCredentialError(f"{name} must be a string")
    value = value.strip()
    if not _REF.fullmatch(value):
        raise ReadConnectorCredentialError(f"{name} must be an exact stable provider identifier")
    return value


def _iso(value: int) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_plan_shape(plan: ProviderRequestPlan) -> None:
    if not isinstance(plan, ProviderRequestPlan):
        raise ReadConnectorCredentialError("request plan must be ProviderRequestPlan")
    expected_host = _EXPECTED_HOST.get(plan.connector)
    if expected_host is None or plan.host != expected_host:
        raise ReadConnectorCredentialError("provider request host does not match connector authority")
    if plan.credential_mode != "bearer_injected_at_execute":
        raise ReadConnectorCredentialError("provider request does not use trusted execute-time bearer mode")
    if plan.follow_redirects is not False:
        raise ReadConnectorCredentialError("provider request redirects must remain disabled")
    if plan.production_activation is not False:
        raise ReadConnectorCredentialError("provider request production activation must remain false")


def _validated_bearer(value: str) -> str:
    if not isinstance(value, str):
        raise ReadConnectorCredentialError("connector bearer token must be a string")
    if not 20 <= len(value) <= _MAX_BEARER_BYTES:
        raise ReadConnectorCredentialError("connector bearer token length is invalid")
    if value != value.strip() or not value.isascii():
        raise ReadConnectorCredentialError("connector bearer token format is invalid")
    if any(ord(ch) < 0x21 or ord(ch) > 0x7E for ch in value):
        raise ReadConnectorCredentialError("connector bearer token format is invalid")
    return value


@dataclass(frozen=True)
class ReadConnectorCredentialEvidence:
    """Non-secret identity/readiness evidence supplied by a host credential owner."""

    connector: Connector
    account_ref: str
    workspace_ref: str | None
    credential_kind: CredentialKind
    state: CredentialState
    checked_at: int
    expires_at: int | None = None
    schema: str = CREDENTIAL_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != CREDENTIAL_SCHEMA:
            raise ReadConnectorCredentialError("unsupported credential evidence schema")
        if self.production_activation is not False:
            raise ReadConnectorCredentialError("credential production activation must remain false")
        connector = normalize_connector(self.connector)
        account_ref = _ref(self.account_ref, "credential account_ref")
        workspace_ref = (
            _ref(self.workspace_ref, "credential workspace_ref")
            if self.workspace_ref is not None
            else None
        )
        if connector == "notion":
            if workspace_ref is None:
                raise ReadConnectorCredentialError("Notion credential evidence requires workspace_ref")
        elif workspace_ref is not None:
            raise ReadConnectorCredentialError("Google credential evidence cannot carry workspace_ref")
        if self.credential_kind != _CREDENTIAL_KIND[connector]:
            raise ReadConnectorCredentialError("credential kind does not match connector")
        if self.state not in _ALLOWED_STATES:
            raise ReadConnectorCredentialError("credential state is unsupported")
        checked_at = _now(self.checked_at)
        if self.expires_at is not None:
            expires_at = _now(self.expires_at)
            if self.state == "ready" and expires_at <= checked_at:
                raise ReadConnectorCredentialError("ready credential evidence is already expired")
            if self.state == "expired_credentials" and expires_at > checked_at:
                raise ReadConnectorCredentialError("expired credential evidence has a future expiry")
        elif self.state == "expired_credentials":
            raise ReadConnectorCredentialError("expired credential evidence requires expires_at")
        object.__setattr__(self, "connector", connector)
        object.__setattr__(self, "account_ref", account_ref)
        object.__setattr__(self, "workspace_ref", workspace_ref)

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "connector": self.connector,
            "capability_id": capability_id(self.connector),
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "credential_kind": self.credential_kind,
            "state": self.state,
            "checked_at": _iso(self.checked_at),
            "expires_at": _iso(self.expires_at) if self.expires_at is not None else None,
            "production_activation": False,
        }


class ReadConnectorCredentialProvider(Protocol):
    """Host-owned credential source. Implementations are outside this slice."""

    def evidence(self, *, now: int) -> ReadConnectorCredentialEvidence:
        ...

    def bearer_token(self) -> str:
        ...


@dataclass(frozen=True)
class CredentialBoundProviderRequest:
    """Prepared non-secret authority binding; it never contains the bearer."""

    grant_id: str
    scope_sha256: str
    account_ref: str
    workspace_ref: str | None
    credential_kind: CredentialKind
    plan: ProviderRequestPlan
    prepared_at: int
    schema: str = BINDING_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != BINDING_SCHEMA:
            raise ReadConnectorCredentialError("unsupported credential binding schema")
        if self.production_activation is not False:
            raise ReadConnectorCredentialError("credential binding production activation must remain false")
        if not isinstance(self.grant_id, str) or not _GRANT_ID.fullmatch(self.grant_id):
            raise ReadConnectorCredentialError("credential binding grant_id has invalid format")
        if not isinstance(self.scope_sha256, str) or not _SHA256.fullmatch(self.scope_sha256):
            raise ReadConnectorCredentialError("credential binding scope digest is invalid")
        _validate_plan_shape(self.plan)
        connector = normalize_connector(self.plan.connector)
        account_ref = _ref(self.account_ref, "binding account_ref")
        workspace_ref = (
            _ref(self.workspace_ref, "binding workspace_ref")
            if self.workspace_ref is not None
            else None
        )
        if connector == "notion":
            if workspace_ref is None:
                raise ReadConnectorCredentialError("Notion credential binding requires workspace_ref")
        elif workspace_ref is not None:
            raise ReadConnectorCredentialError("Google credential binding cannot carry workspace_ref")
        if self.credential_kind != _CREDENTIAL_KIND[connector]:
            raise ReadConnectorCredentialError("credential binding kind does not match connector")
        _now(self.prepared_at)
        object.__setattr__(self, "account_ref", account_ref)
        object.__setattr__(self, "workspace_ref", workspace_ref)

    def to_audit_dict(self) -> dict:
        value = self.plan.to_audit_dict()
        value.update(
            {
                "binding_schema": self.schema,
                "grant_id": self.grant_id,
                "scope_sha256": self.scope_sha256,
                "account_ref": self.account_ref,
                "workspace_ref": self.workspace_ref,
                "credential_kind": self.credential_kind,
                "prepared_at": _iso(self.prepared_at),
                "production_activation": False,
            }
        )
        return value


class ReadConnectorCredentialBinder:
    """Two-stage TOCTOU-safe binding from grant + credential to request plan."""

    def __init__(
        self,
        *,
        grants: ReadConnectorGrantStore,
        credentials: ReadConnectorCredentialProvider,
    ) -> None:
        self._grants = grants
        self._credentials = credentials

    def _ready_evidence(self, *, now: int) -> ReadConnectorCredentialEvidence:
        now = _now(now)
        try:
            evidence = self._credentials.evidence(now=now)
        except ReadConnectorCredentialError:
            raise
        except Exception:
            raise ReadConnectorCredentialError("connector credential evidence is unavailable") from None
        if not isinstance(evidence, ReadConnectorCredentialEvidence):
            raise ReadConnectorCredentialError("credential provider returned invalid evidence")
        if evidence.checked_at != now:
            raise ReadConnectorCredentialError("credential evidence is not bound to current check time")
        if evidence.state != "ready":
            raise ReadConnectorDenied(f"connector credential state is {evidence.state}")
        if evidence.expires_at is not None and evidence.expires_at <= now:
            raise ReadConnectorDenied("connector credentials are expired")
        return evidence

    def prepare(
        self,
        grant_id: str,
        plan: ProviderRequestPlan,
        *,
        now: int,
    ) -> CredentialBoundProviderRequest:
        """Bind a plan without loading bearer material."""
        _validate_plan_shape(plan)
        evidence = self._ready_evidence(now=now)
        if evidence.connector != plan.connector:
            raise ReadConnectorDenied("credential connector does not match request connector")
        grant = self._grants.authorize(
            grant_id,
            connector=evidence.connector,
            account_ref=evidence.account_ref,
            workspace_ref=evidence.workspace_ref,
            object_scope=plan.object_scope,
            operation=plan.authority_operation,
        )
        return CredentialBoundProviderRequest(
            grant_id=grant.grant_id,
            scope_sha256=grant.scope.digest,
            account_ref=evidence.account_ref,
            workspace_ref=evidence.workspace_ref,
            credential_kind=evidence.credential_kind,
            plan=plan,
            prepared_at=now,
        )

    def trusted_bearer_for_execution(
        self,
        binding: CredentialBoundProviderRequest,
        *,
        now: int,
    ) -> str:
        """Re-check grant + credential at execution time, then release one bearer.

        The returned secret is intentionally an in-memory transport seam only.
        Callers must not log, persist, hash or place it into normal header maps.
        """
        if not isinstance(binding, CredentialBoundProviderRequest):
            raise ReadConnectorCredentialError("binding must be CredentialBoundProviderRequest")
        _validate_plan_shape(binding.plan)
        evidence = self._ready_evidence(now=now)
        if (
            evidence.connector != binding.plan.connector
            or evidence.account_ref != binding.account_ref
            or evidence.workspace_ref != binding.workspace_ref
            or evidence.credential_kind != binding.credential_kind
        ):
            raise ReadConnectorDenied("credential identity changed after request preparation")
        grant = self._grants.authorize(
            binding.grant_id,
            connector=evidence.connector,
            account_ref=evidence.account_ref,
            workspace_ref=evidence.workspace_ref,
            object_scope=binding.plan.object_scope,
            operation=binding.plan.authority_operation,
        )
        if grant.scope.digest != binding.scope_sha256:
            raise ReadConnectorDenied("connector scope changed after request preparation")
        try:
            token = self._credentials.bearer_token()
        except Exception:
            raise ReadConnectorCredentialError("connector credential material is unavailable") from None
        return _validated_bearer(token)
