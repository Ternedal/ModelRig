"""T-037 dormant execution composition for Google/Notion read connectors.

This module composes the already-qualified credential binding, provider request
plan and provider response validator without implementing provider networking.

The host supplies one ``ReadConnectorProviderTransport`` implementation behind a
protocol.  This coordinator:

* re-checks exact grant + credential authority immediately before transport;
* releases the bearer only to that one transport call;
* binds the exchange to a SHA-256 digest of the exact immutable request plan;
* accepts exactly one transport response and rejects request/host/method drift;
* feeds raw bytes into the reviewed provider-response validator;
* returns privacy-minimized execution audit evidence with no bearer, query, body,
  account or workspace material;
* performs no DNS/socket/HTTP/env/file lookup, retry, route registration or
  production activation itself.

A later concrete Google/Notion transport must implement DNS/public-peer/TLS and
wire-byte enforcement. ``PRODUCTION_ACTIVATION`` remains structurally false.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from .read_connector_credential_binding import (
    CredentialBoundProviderRequest,
    ReadConnectorCredentialBinder,
)
from .read_connector_package_contract import ReadConnectorContractError, capability_id
from .read_connector_provider_request import ProviderRequestPlan
from .read_connector_provider_response import (
    ValidatedProviderResponse,
    validate_provider_response,
)

EXECUTION_SCHEMA = "kaliv-read-connector-provider-execution/v1"
TRANSPORT_RESPONSE_SCHEMA = "kaliv-read-connector-transport-response/v1"
PRODUCTION_ACTIVATION = False

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HOST = re.compile(
    r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)
_MAX_TIMEOUT_SECONDS = 120.0


class ProviderExecutionError(ReadConnectorContractError):
    """The dormant execution composition contract was violated."""


def _now(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProviderExecutionError("execution time must be a non-negative integer")
    return value


def _iso(value: int) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderExecutionError("transport timeout must be numeric")
    value = float(value)
    if not 0 < value <= _MAX_TIMEOUT_SECONDS:
        raise ProviderExecutionError("transport timeout must be within 0..120 seconds")
    return value


def _canonical(value: dict) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProviderExecutionError("provider request identity is not canonical JSON") from exc


def exact_request_sha256(plan: ProviderRequestPlan) -> str:
    """Digest the complete non-secret provider request, including query/body.

    The digest can be audited safely; the unhashed query/body values are never
    emitted by this module's audit projection.
    """
    if not isinstance(plan, ProviderRequestPlan):
        raise ProviderExecutionError("execution requires ProviderRequestPlan")
    if plan.production_activation is not False:
        raise ProviderExecutionError("provider request production activation must remain false")
    identity = {
        "schema": plan.schema,
        "connector": plan.connector,
        "authority_operation": plan.authority_operation,
        "provider_operation": plan.provider_operation,
        "object_scope": plan.object_scope,
        "method": plan.method,
        "host": plan.host,
        "path": plan.path,
        "query": [[key, value] for key, value in plan.query],
        "headers": [[name, value] for name, value in plan.headers],
        "body_json": plan.body_json,
        "response_kind": plan.response_kind,
        "expected_content_types": list(plan.expected_content_types),
        "max_response_bytes": plan.max_response_bytes,
        "credential_mode": plan.credential_mode,
        "follow_redirects": plan.follow_redirects,
        "production_activation": False,
    }
    return hashlib.sha256(_canonical(identity)).hexdigest()


@dataclass(frozen=True)
class ProviderTransportResponse:
    """Transient output from one host-owned transport invocation.

    ``body`` intentionally has no serializer/audit method.  It exists only long
    enough for the coordinator to pass it into the provider response validator.
    """
    request_sha256: str
    method: str
    host: str
    status_code: int
    content_type: str
    body: bytes
    schema: str = TRANSPORT_RESPONSE_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != TRANSPORT_RESPONSE_SCHEMA:
            raise ProviderExecutionError("unsupported provider transport response schema")
        if self.production_activation is not False:
            raise ProviderExecutionError("provider transport response activation must remain false")
        if not isinstance(self.request_sha256, str) or not _SHA256.fullmatch(
            self.request_sha256
        ):
            raise ProviderExecutionError("transport response request digest is invalid")
        if self.method not in {"GET", "POST"}:
            raise ProviderExecutionError("transport response method is unsupported")
        if (
            not isinstance(self.host, str)
            or len(self.host) > 253
            or self.host != self.host.strip().lower()
            or not _HOST.fullmatch(self.host)
        ):
            raise ProviderExecutionError("transport response host is invalid")
        if (
            isinstance(self.status_code, bool)
            or not isinstance(self.status_code, int)
            or not 100 <= self.status_code <= 599
        ):
            raise ProviderExecutionError("transport response HTTP status is invalid")
        if not isinstance(self.content_type, str):
            raise ProviderExecutionError("transport response content type must be a string")
        if not isinstance(self.body, bytes):
            raise ProviderExecutionError("transport response body must be bytes")


class ReadConnectorProviderTransport(Protocol):
    """Host-owned one-shot transport seam.

    Implementations may perform network I/O, but they are outside this dormant
    slice.  The bearer must be used only for this call and must never be logged,
    persisted or copied into returned response metadata.
    """

    def execute(
        self,
        plan: ProviderRequestPlan,
        *,
        bearer_token: str,
        request_sha256: str,
        timeout_seconds: float,
    ) -> ProviderTransportResponse:
        ...


@dataclass(frozen=True)
class ProviderExecutionResult:
    request_sha256: str
    executed_at: int
    response: ValidatedProviderResponse
    schema: str = EXECUTION_SCHEMA
    attempts: int = 1
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != EXECUTION_SCHEMA:
            raise ProviderExecutionError("unsupported provider execution schema")
        if self.production_activation is not False:
            raise ProviderExecutionError("provider execution activation must remain false")
        if not isinstance(self.request_sha256, str) or not _SHA256.fullmatch(
            self.request_sha256
        ):
            raise ProviderExecutionError("provider execution request digest is invalid")
        _now(self.executed_at)
        if self.attempts != 1:
            raise ProviderExecutionError("dormant provider execution must be one-shot")
        if not isinstance(self.response, ValidatedProviderResponse):
            raise ProviderExecutionError("provider execution requires validated response")
        if self.response.production_activation is not False:
            raise ProviderExecutionError("validated provider response must remain dormant")

    def to_audit_dict(self) -> dict:
        response = self.response
        return {
            "schema": self.schema,
            "connector": response.connector,
            "capability_id": capability_id(response.connector),
            "authority_operation": response.authority_operation,
            "provider_operation": response.provider_operation,
            "object_scope": response.object_scope,
            "grant_id": response.grant_id,
            "scope_sha256": response.scope_sha256,
            "request_sha256": self.request_sha256,
            "status_code": response.status_code,
            "content_type": response.content_type,
            "response_bytes": response.response_bytes,
            "body_sha256": response.body_sha256,
            "item_count": len(response.items),
            "has_next_cursor": response.next_cursor is not None,
            "attempts": 1,
            "executed_at": _iso(self.executed_at),
            "production_activation": False,
        }


class ReadConnectorProviderExecutor:
    """One-shot dormant composition from prepared authority to validated data."""

    def __init__(
        self,
        *,
        binder: ReadConnectorCredentialBinder,
        transport: ReadConnectorProviderTransport,
    ) -> None:
        if not isinstance(binder, ReadConnectorCredentialBinder):
            raise ProviderExecutionError("executor binder must be ReadConnectorCredentialBinder")
        self._binder = binder
        self._transport = transport

    def execute(
        self,
        binding: CredentialBoundProviderRequest,
        *,
        now: int,
        timeout_seconds: float = 15.0,
    ) -> ProviderExecutionResult:
        if not isinstance(binding, CredentialBoundProviderRequest):
            raise ProviderExecutionError(
                "execution requires CredentialBoundProviderRequest"
            )
        now = _now(now)
        timeout_seconds = _timeout(timeout_seconds)
        if binding.production_activation is not False:
            raise ProviderExecutionError("credential binding activation must remain false")
        if binding.prepared_at > now:
            raise ProviderExecutionError("request binding cannot be prepared in the future")

        request_sha256 = exact_request_sha256(binding.plan)

        # This call re-reads grant + credential state and loads the bearer. Keep
        # it directly adjacent to the single host transport invocation so revoke
        # or credential identity drift after preparation fails before I/O.
        bearer = self._binder.trusted_bearer_for_execution(binding, now=now)
        try:
            exchange = self._transport.execute(
                binding.plan,
                bearer_token=bearer,
                request_sha256=request_sha256,
                timeout_seconds=timeout_seconds,
            )
        except Exception:
            raise ProviderExecutionError("provider transport execution failed") from None
        finally:
            # Python strings cannot be zeroized, but the coordinator deliberately
            # retains no bearer field/cache/reference after this call returns.
            bearer = ""

        if not isinstance(exchange, ProviderTransportResponse):
            raise ProviderExecutionError("provider transport returned invalid response type")
        if exchange.request_sha256 != request_sha256:
            raise ProviderExecutionError("provider transport request digest mismatch")
        if exchange.method != binding.plan.method:
            raise ProviderExecutionError("provider transport method drifted from request plan")
        if exchange.host != binding.plan.host:
            raise ProviderExecutionError("provider transport host drifted from request plan")

        validated = validate_provider_response(
            binding,
            status_code=exchange.status_code,
            content_type=exchange.content_type,
            body=exchange.body,
            retrieved_at=now,
        )
        return ProviderExecutionResult(
            request_sha256=request_sha256,
            executed_at=now,
            response=validated,
        )
