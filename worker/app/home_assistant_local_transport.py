"""Concrete but unmounted local Home Assistant transport for T-038.

The transport accepts no URL/host from a model or request plan. Its endpoint is
operator-owned construction-time configuration and v1 requires an IP literal in
an explicitly local address range, eliminating DNS/rebinding from this boundary.
Redirects and retries are not implemented. The bearer is acquired just-in-time
from an injected provider, used for one GET, never returned/logged/persisted,
and the local reference is discarded in ``finally``.

Plain HTTP is allowed by default only for loopback. Using HTTP for another
allowed local address requires the operator to set ``allow_insecure_http=True``.
HTTPS uses the standard validating SSL context unless a controlled host injects
another context.

T-032 accounting is exact rather than estimated: this module builds the one
HTTP/1.1 request itself and sends it in a counted ``socket.send`` loop. If a
send fails midway, ``request_bytes_sent`` is the number of bytes the socket
actually accepted before the failure. There is no DNS lookup because the socket
family and literal peer are selected directly from ``ipaddress``.

This module is not imported by ToolGate/routes/startup and has no env/config
lookup, so shipping it alone does not activate Home Assistant access.
"""
from __future__ import annotations

import http.client
import ipaddress
import socket
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
_MAX_REQUEST_BYTES = 4096


class HomeAssistantLocalTransportError(HomeRigContractError):
    pass


def _local_ip(value: str) -> tuple[str, bool, int]:
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
    return parsed.compressed, parsed.is_loopback, parsed.version


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
        address, loopback, version = _local_ip(self.address)
        object.__setattr__(self, "address", address)
        object.__setattr__(self, "port", _port(self.port))
        object.__setattr__(self, "_ip_version", version)
        if self.scheme == "http" and not loopback and not self.allow_insecure_http:
            raise HomeAssistantLocalTransportError(
                "plain HTTP outside loopback requires explicit operator opt-in"
            )

    @property
    def authority(self) -> str:
        address = f"[{self.address}]" if ":" in self.address else self.address
        return f"{address}:{self.port}"

    @property
    def socket_family(self) -> int:
        return socket.AF_INET6 if self._ip_version == 6 else socket.AF_INET

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
    """Host-owned credential seam; implementations own protected token storage."""

    def bearer_for_execution(self) -> str:
        ...


class HomeAssistantLocalTransport:
    """One-shot raw HTTP/1.1 transport to one operator-pinned local IP peer."""

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

    def _request_bytes(self, plan: HomeAssistantStateRequestPlan, bearer: str) -> bytes:
        try:
            request = (
                f"GET {plan.path} HTTP/1.1\r\n"
                f"Host: {self._endpoint.authority}\r\n"
                f"Authorization: Bearer {bearer}\r\n"
                "Accept: application/json\r\n"
                "Connection: close\r\n"
                "\r\n"
            ).encode("ascii")
        except UnicodeEncodeError as exc:
            raise HomeAssistantLocalTransportError("Home Assistant request is not ASCII-safe") from exc
        if not 1 <= len(request) <= _MAX_REQUEST_BYTES:
            raise HomeAssistantLocalTransportError("Home Assistant request exceeds T-032 byte budget")
        return request

    def _connect(self):
        peer = (
            (self._endpoint.address, self._endpoint.port, 0, 0)
            if self._endpoint.socket_family == socket.AF_INET6
            else (self._endpoint.address, self._endpoint.port)
        )
        raw = socket.socket(self._endpoint.socket_family, socket.SOCK_STREAM)
        raw.settimeout(self._timeout_seconds)
        try:
            raw.connect(peer)
            if self._endpoint.scheme == "https":
                context = self._ssl_context or ssl.create_default_context()
                wrapped = context.wrap_socket(raw, server_hostname=self._endpoint.address)
                raw = None
                return wrapped
            return raw
        except Exception:
            try:
                if raw is not None:
                    raw.close()
            finally:
                pass
            raise

    @staticmethod
    def _send_counted(sock, payload: bytes) -> int:
        sent = 0
        view = memoryview(payload)
        while sent < len(payload):
            count = sock.send(view[sent:])
            if not count:
                raise OSError("socket closed while sending request")
            sent += count
        return sent

    def execute(self, plan: HomeAssistantStateRequestPlan) -> HomeAssistantStateTransportResult:
        if not isinstance(plan, HomeAssistantStateRequestPlan):
            raise HomeAssistantLocalTransportError("transport requires HomeAssistantStateRequestPlan")
        if plan.production_activation is not False or plan.would_execute is not False:
            raise HomeAssistantLocalTransportError("request plan must remain qualified and non-self-executing")
        if plan.method != "GET" or plan.service != "home_assistant":
            raise HomeAssistantLocalTransportError("transport accepts Home Assistant GET plans only")

        bearer = ""
        sock = None
        response = None
        sent = 0
        try:
            bearer = _bearer(self._bearer_provider.bearer_for_execution())
            wire_request = self._request_bytes(plan, bearer)
            sock = self._connect()
            sent = self._send_counted(sock, wire_request)
            response = http.client.HTTPResponse(sock)
            response.begin()
            body = response.read(plan.max_response_bytes + 1)
            received_at = int(time.time())
            if len(body) > plan.max_response_bytes:
                return HomeAssistantStateTransportResult(
                    request_plan_sha256=plan.digest,
                    entity_id=plan.entity_id,
                    request_bytes_sent=sent,
                    received_at=received_at,
                    error_code="response_too_large",
                )
            return HomeAssistantStateTransportResult(
                request_plan_sha256=plan.digest,
                entity_id=plan.entity_id,
                request_bytes_sent=sent,
                received_at=received_at,
                status_code=response.status,
                content_type=response.getheader("Content-Type") or "application/octet-stream",
                body=body,
            )
        except (TimeoutError, OSError, http.client.HTTPException, ssl.SSLError):
            return HomeAssistantStateTransportResult(
                request_plan_sha256=plan.digest,
                entity_id=plan.entity_id,
                request_bytes_sent=sent,
                received_at=int(time.time()),
                error_code="transport_io",
            )
        finally:
            bearer = ""
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
