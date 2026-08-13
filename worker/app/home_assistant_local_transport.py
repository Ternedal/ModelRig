"""Concrete but unmounted local Home Assistant transport for T-038.

The transport accepts no URL/host from a model or request plan.  Its endpoint is
operator-owned construction-time configuration and v1 requires an IP literal in
an explicitly local address range, eliminating DNS/rebinding from this boundary.
Redirects and retries are not implemented.  The bearer is acquired just-in-time
from an injected provider, used for one GET, never returned/logged/persisted,
and the local reference is discarded in ``finally``.

Plain HTTP is allowed by default only for loopback.  Using HTTP for another
allowed local address requires the operator to set ``allow_insecure_http=True``
when constructing the endpoint.  HTTPS uses the standard validating SSL context
unless the host explicitly injects another context for a controlled fixture.

This module is not imported by ToolGate/routes/startup and has no env/config
lookup, so merely shipping it does not activate Home Assistant access.
"""
from __future__ import annotations

import http.client
import ipaddress
import ssl
import time
from dataclasses import dataclass
from typing import Literal, Protocol

from .home_assistant_state_execution import HomeAssistantStateTransportResult
from .home_assistant_state_request import HomeAssistantStateRequestPlan
from .home_rig_connector_contract import HomeRigContractError

TRANSPORT_CONFIG_SCHEMA = "kaliv-home-assistant-local-transport/v1"
PRODUCTION_ACTIVATION = False

Scheme = Literal["http", "https"]
_LOCAL_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "100.64.0.0/10",
        "::1/128",
        "fc00::/7",
    )
)
_MAX_BEARER_CHARS = 8192
_MAX_TIMEOUT_SECONDS = 30.0


class HomeAssistantLocalTransportError(HomeRigContractError):
    pass


def _local_ip(value: str) -> tuple[str, bool]:
    if not isinstance(value, str) or not value.strip():
        raise HomeAssistantLocalTransportError("Home Assistant endpoint address must be an IP literal")
    try:
        parsed = ipaddress.ip_address(value.strip())
    except ValueError as exc:
        raise HomeAssistantLocalTransportError("Home Assistant endpoint address must be an IP literal") from exc
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        raise HomeAssistantLocalTransportError("IPv4-mapped IPv6 endpoints are not accepted")
    if not any(parsed in network for network in _LOCAL_NETWORKS):
        raise HomeAssistantLocalTransportError("Home Assistant endpoint must be explicitly local")
    return parsed.compressed, parsed.is_loopback


def _port(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise HomeAssistantLocalTransportError("Home Assistant endpoint port is invalid")
    return value


def _timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HomeAssistantLocalTransportError("Home Assistant timeout must be numeric")
    result = float(value)
    if not 0 < result <= _MAX_TIMEOUT_SECONDS:
        raise HomeAssistantLocalTransportError("Home Assistant timeout must be within 0..30 seconds")
    return result


def _bearer(value: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= _MAX_BEARER_CHARS:
        raise HomeAssistantLocalTransportError("Home Assistant bearer is invalid")
    if any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise HomeAssistantLocalTransportError("Home Assistant bearer is invalid")
    return value


@dataclass(frozen=True)
class HomeAssistantLocalEndpoint:
    address: str
    port: int = 8123
    scheme: Scheme = "http"
    allow_insecure_http: bool = False
    schema: str = TRANSPORT_CONFIG_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != TRANSPORT_CONFIG_SCHEMA:
            raise HomeAssistantLocalTransportError("unsupported Home Assistant endpoint schema")
        if self.production_activation is not False:
            raise HomeAssistantLocalTransportError("Home Assistant endpoint activation must remain false")
        if self.scheme not in {"http", "https"}:
            raise HomeAssistantLocalTransportError("Home Assistant endpoint scheme must be http or https")
        if not isinstance(self.allow_insecure_http, bool):
            raise HomeAssistantLocalTransportError("allow_insecure_http must be boolean")
        address, loopback = _local_ip(self.address)
        object.__setattr__(self, "address", address)
        object.__setattr__(self, "port", _port(self.port))
        if self.scheme == "http" and not loopback and not self.allow_insecure_http:
            raise HomeAssistantLocalTransportError(
                "plain HTTP outside loopback requires explicit operator opt-in"
            )

    @property
    def authority(self) -> str:
        address = f"[{self.address}]" if ":" in self.address else self.address
        return f"{address}:{self.port}"

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "scheme": self.scheme,
            "address": self.address,
            "port": self.port,
            "authority": self.authority,
            "allow_insecure_http": self.allow_insecure_http,
            "production_activation": False,
        }


class HomeAssistantBearerProvider(Protocol):
    """Host-owned credential seam; implementations own secure token storage."""

    def bearer_for_execution(self) -> str:
        ...


class HomeAssistantLocalTransport:
    """One-shot stdlib transport to one operator-pinned local IP endpoint."""

    def __init__(
        self,
        *,
        endpoint: HomeAssistantLocalEndpoint,
        bearer_provider: HomeAssistantBearerProvider,
        timeout_seconds: float = 10.0,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        if not isinstance(endpoint, HomeAssistantLocalEndpoint):
            raise HomeAssistantLocalTransportError("transport requires HomeAssistantLocalEndpoint")
        if not hasattr(bearer_provider, "bearer_for_execution") or not callable(
            bearer_provider.bearer_for_execution
        ):
            raise HomeAssistantLocalTransportError("transport requires bearer provider")
        if ssl_context is not None and not isinstance(ssl_context, ssl.SSLContext):
            raise HomeAssistantLocalTransportError("ssl_context must be SSLContext")
        self._endpoint = endpoint
        self._bearer_provider = bearer_provider
        self._timeout_seconds = _timeout(timeout_seconds)
        self._ssl_context = ssl_context

    @property
    def endpoint(self) -> HomeAssistantLocalEndpoint:
        return self._endpoint

    @staticmethod
    def _shared_request_bytes(plan: HomeAssistantStateRequestPlan) -> int:
        """Logical T-032 payload size: exact externally disclosed request path.

        Credential bytes are deliberately not counted into data-sharing content;
        their value/length belongs to the credential boundary, not connector data.
        """
        size = len(plan.path.encode("utf-8"))
        if not 1 <= size <= 4096:
            raise HomeAssistantLocalTransportError("Home Assistant request path byte size is invalid")
        return size

    def _connection(self):
        if self._endpoint.scheme == "https":
            context = self._ssl_context or ssl.create_default_context()
            return http.client.HTTPSConnection(
                self._endpoint.address,
                self._endpoint.port,
                timeout=self._timeout_seconds,
                context=context,
            )
        return http.client.HTTPConnection(
            self._endpoint.address,
            self._endpoint.port,
            timeout=self._timeout_seconds,
        )

    def execute(self, plan: HomeAssistantStateRequestPlan) -> HomeAssistantStateTransportResult:
        if not isinstance(plan, HomeAssistantStateRequestPlan):
            raise HomeAssistantLocalTransportError("transport requires HomeAssistantStateRequestPlan")
        if plan.production_activation is not False or plan.would_execute is not False:
            raise HomeAssistantLocalTransportError("request plan must remain qualified and non-self-executing")
        if plan.method != "GET" or plan.service != "home_assistant":
            raise HomeAssistantLocalTransportError("transport accepts Home Assistant GET plans only")

        shared_bytes = self._shared_request_bytes(plan)
        bearer = ""
        connection = None
        try:
            bearer = _bearer(self._bearer_provider.bearer_for_execution())
            connection = self._connection()
            connection.request(
                "GET",
                plan.path,
                headers={
                    "Authorization": f"Bearer {bearer}",
                    "Accept": "application/json",
                },
            )
            response = connection.getresponse()
            body = response.read(plan.max_response_bytes + 1)
            received_at = int(time.time())
            if len(body) > plan.max_response_bytes:
                return HomeAssistantStateTransportResult(
                    request_plan_sha256=plan.digest,
                    entity_id=plan.entity_id,
                    request_bytes_sent=shared_bytes,
                    received_at=received_at,
                    error_code="response_too_large",
                )
            return HomeAssistantStateTransportResult(
                request_plan_sha256=plan.digest,
                entity_id=plan.entity_id,
                request_bytes_sent=shared_bytes,
                received_at=received_at,
                status_code=response.status,
                content_type=response.getheader("Content-Type") or "application/octet-stream",
                body=body,
            )
        except (TimeoutError, OSError, http.client.HTTPException, ssl.SSLError):
            return HomeAssistantStateTransportResult(
                request_plan_sha256=plan.digest,
                entity_id=plan.entity_id,
                request_bytes_sent=shared_bytes,
                received_at=int(time.time()),
                error_code="transport_io",
            )
        finally:
            bearer = ""
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
