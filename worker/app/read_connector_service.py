"""Dormant T-037 host-owned read service composition.

Composes exact grant authority, injected credential ownership, injected provider
transport, provider response validation and durable audit. Nothing in this module
registers a runtime/API surface, acquires OAuth credentials, or activates a
connector.
"""
from __future__ import annotations

import re
import time
from typing import Callable

from .read_connector_credential_binding import (
    ReadConnectorCredentialBinder,
    ReadConnectorCredentialError,
    ReadConnectorCredentialEvidence,
    ReadConnectorCredentialProvider,
)
from .read_connector_package_contract import (
    Connector,
    CredentialState,
    ReadConnectorAuditLog,
    ReadConnectorContractError,
    ReadConnectorDenied,
    ReadConnectorGrant,
    ReadConnectorGrantStore,
    ReadConnectorReadiness,
    normalize_connector,
    readiness_for,
)
from .read_connector_provider_execution import (
    ProviderExecutionError,
    ProviderExecutionResult,
    ReadConnectorProviderExecutor,
    ReadConnectorProviderTransport,
)
from .read_connector_provider_request import ProviderRequestPlan

SERVICE_SCHEMA = "kaliv-read-connector-service/v1"
PRODUCTION_ACTIVATION = False
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=+-]{0,255}$")


class ReadConnectorServiceError(RuntimeError):
    pass


def _ref(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise ReadConnectorServiceError(f"{name} must be text")
    value = value.strip()
    if not _REF.fullmatch(value):
        raise ReadConnectorServiceError(f"{name} must be an exact stable provider identifier")
    return value


def _uint(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReadConnectorServiceError(f"{name} must be a non-negative integer")
    return value


class ReadConnectorReadService:
    def __init__(
        self,
        *,
        connector: Connector,
        account_ref: str,
        workspace_ref: str | None,
        grants: ReadConnectorGrantStore,
        credentials: ReadConnectorCredentialProvider,
        transport: ReadConnectorProviderTransport,
        audit: ReadConnectorAuditLog,
        monotonic_ms: Callable[[], int] | None = None,
    ) -> None:
        connector = normalize_connector(connector)
        account_ref = _ref(account_ref, "service account_ref")
        if connector == "notion":
            if workspace_ref is None:
                raise ReadConnectorServiceError("Notion read service requires workspace_ref")
            workspace_ref = _ref(workspace_ref, "service workspace_ref")
        elif workspace_ref is not None:
            raise ReadConnectorServiceError("Google read service cannot carry workspace_ref")
        if not isinstance(grants, ReadConnectorGrantStore):
            raise ReadConnectorServiceError("service requires ReadConnectorGrantStore")
        if not isinstance(audit, ReadConnectorAuditLog):
            raise ReadConnectorServiceError("service requires ReadConnectorAuditLog")
        self._connector = connector
        self._account_ref = account_ref
        self._workspace_ref = workspace_ref
        self._grants = grants
        self._credentials = credentials
        self._audit = audit
        self._monotonic_ms = monotonic_ms or (lambda: time.monotonic_ns() // 1_000_000)
        self._binder = ReadConnectorCredentialBinder(grants=grants, credentials=credentials)
        self._executor = ReadConnectorProviderExecutor(binder=self._binder, transport=transport)

    @property
    def connector(self) -> Connector:
        return self._connector

    @property
    def account_ref(self) -> str:
        return self._account_ref

    @property
    def workspace_ref(self) -> str | None:
        return self._workspace_ref

    def readiness(self, grant_id: str, *, now: int) -> ReadConnectorReadiness:
        now = _uint(now, "connector service time")
        state = self._credential_state(now=now)
        try:
            grant = self._grants.get_grant(grant_id)
        except ReadConnectorContractError:
            grant = None
        if grant is None or not self._grant_matches_service(grant):
            return ReadConnectorReadiness(
                connector=self._connector,
                account_ref=None,
                workspace_ref=None,
                grant_id=None,
                scope_sha256=None,
                state="missing_scope",
                checked_at=now,
            )
        return readiness_for(
            self._grants,
            connector=self._connector,
            grant_id=grant.grant_id,
            credential_state=state,
            checked_at=now,
        )

    def execute(
        self,
        grant_id: str,
        plan: ProviderRequestPlan,
        *,
        now: int,
        timeout_seconds: float = 15.0,
    ) -> ProviderExecutionResult:
        now = _uint(now, "connector service time")
        if not isinstance(plan, ProviderRequestPlan):
            raise ReadConnectorServiceError("service read requires ProviderRequestPlan")
        if plan.connector != self._connector:
            raise ReadConnectorServiceError("provider plan connector does not match service identity")
        started = self._clock()
        grant: ReadConnectorGrant | None = None
        try:
            grant = self._grants.authorize(
                grant_id,
                connector=self._connector,
                account_ref=self._account_ref,
                workspace_ref=self._workspace_ref,
                object_scope=plan.object_scope,
                operation=plan.authority_operation,
            )
            binding = self._binder.prepare(grant_id, plan, now=now)
            result = self._executor.execute(binding, now=now, timeout_seconds=timeout_seconds)
        except ReadConnectorDenied:
            self._record_attempt(plan, "blocked", "authority_or_credentials_blocked", started, grant)
            raise
        except ReadConnectorCredentialError:
            self._record_attempt(plan, "error", "credential_boundary_error", started, grant)
            raise ReadConnectorServiceError("connector credential boundary failed") from None
        except ProviderExecutionError:
            self._record_attempt(plan, "error", "provider_execution_error", started, grant)
            raise ReadConnectorServiceError("connector provider execution failed") from None
        except ReadConnectorContractError:
            self._record_attempt(plan, "error", "authority_contract_error", started, grant)
            raise ReadConnectorServiceError("connector authority failed") from None
        assert grant is not None
        self._record_success(plan, result, started, grant)
        return result

    def _credential_state(self, *, now: int) -> CredentialState:
        try:
            evidence = self._credentials.evidence(now=now)
        except Exception:
            return "unavailable"
        if not isinstance(evidence, ReadConnectorCredentialEvidence) or evidence.checked_at != now:
            return "invalid_credentials"
        if (
            evidence.connector != self._connector
            or evidence.account_ref != self._account_ref
            or evidence.workspace_ref != self._workspace_ref
        ):
            return "invalid_credentials"
        if evidence.expires_at is not None and evidence.expires_at <= now:
            return "expired_credentials"
        return evidence.state

    def _grant_matches_service(self, grant: ReadConnectorGrant) -> bool:
        return (
            grant.scope.connector == self._connector
            and grant.scope.account_ref == self._account_ref
            and grant.scope.workspace_ref == self._workspace_ref
        )

    def _clock(self) -> int:
        try:
            return _uint(self._monotonic_ms(), "connector service clock")
        except ReadConnectorServiceError:
            raise
        except Exception:
            raise ReadConnectorServiceError("connector service clock failed") from None

    def _duration(self, started: int) -> int:
        finished = self._clock()
        if finished < started:
            raise ReadConnectorServiceError("connector service clock moved backwards")
        return finished - started

    def _record_attempt(
        self,
        plan: ProviderRequestPlan,
        outcome: str,
        detail: str,
        started: int,
        grant: ReadConnectorGrant | None,
    ) -> None:
        try:
            self._audit.record(
                connector=self._connector,
                account_ref=self._account_ref,
                workspace_ref=self._workspace_ref,
                object_scope=plan.object_scope,
                operation=plan.authority_operation,
                outcome=outcome,  # type: ignore[arg-type]
                duration_ms=self._duration(started),
                detail=detail,
                grant_id=grant.grant_id if grant else None,
                scope_sha256=grant.scope.digest if grant else None,
            )
        except ReadConnectorServiceError:
            raise
        except Exception:
            raise ReadConnectorServiceError("connector audit recording failed") from None

    def _record_success(
        self,
        plan: ProviderRequestPlan,
        result: ProviderExecutionResult,
        started: int,
        grant: ReadConnectorGrant,
    ) -> None:
        duration_ms = self._duration(started)
        receipts = result.response.source_receipts
        try:
            if not receipts:
                self._audit.record(
                    connector=self._connector,
                    account_ref=self._account_ref,
                    workspace_ref=self._workspace_ref,
                    object_scope=plan.object_scope,
                    operation=plan.authority_operation,
                    outcome="executed",
                    duration_ms=duration_ms,
                    detail="provider_read_empty",
                    grant_id=grant.grant_id,
                    scope_sha256=grant.scope.digest,
                )
                return
            for receipt in receipts:
                self._audit.record(
                    connector=self._connector,
                    account_ref=self._account_ref,
                    workspace_ref=self._workspace_ref,
                    object_scope=receipt.object_scope,
                    operation=receipt.operation,
                    outcome="executed",
                    duration_ms=duration_ms,
                    detail="provider_read_source",
                    grant_id=receipt.grant_id,
                    scope_sha256=receipt.scope_sha256,
                    source_id=receipt.source_id,
                    object_id=receipt.object_id,
                    revision=receipt.revision,
                )
        except Exception:
            raise ReadConnectorServiceError("connector audit recording failed") from None
