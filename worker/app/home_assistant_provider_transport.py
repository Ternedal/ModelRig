"""Dormant concrete Home Assistant read transport for T-038.

The provider-plan gate already binds an exact Home Assistant entity read to both
T-038 durable scope and one-use T-032 authority.  This module performs the
remaining deployment-local execution step without making the connector a normal
runtime capability:

* origin and bearer-file location are deployment injected, never model supplied;
* the exact T-038 grant/scope is checked again immediately before DNS/file/network;
* DNS is pinned to one validated numeric peer and the connected peer must match;
* plaintext HTTP is allowed only by an explicit deployment flag and only to
  non-global peers; HTTPS remains the default;
* one GET is issued, redirects are never followed, response bytes are bounded;
* only the strict Home Assistant state projection is returned; attributes and
  context never cross this boundary;
* the already-claimed T-032 receipt is always finished as completed/failed/blocked.

There is still no ToolGate/runtime registration, RigGate transport, wake/control
execution, environment discovery, or production activation in this slice.
"""
from __future__ import annotations

import http.client
import ipaddress
import os
import socket
import ssl
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, Sequence
from urllib.parse import urlsplit

from .data_sharing import DataSharingLedger
from .home_assistant_state_contract import HomeAssistantStateEvidence, parse_home_assistant_state
from .home_rig_connector_contract import (
    HomeRigContractError,
    HomeRigDenied,
    HomeRigGrantStore,
)
from .home_rig_provider_gate import (
    AuthorizedHomeAssistantRead,
    finish_home_assistant_state_request,
)
from .web_fetch import TransportResponse

PRODUCTION_ACTIVATION = False
_MAX_BEARER_BYTES = 4_096
_MAX_RESPONSE_BYTES = 128 * 1024
_MAX_HEADER_BYTES = 64 * 1024
_READ_CHUNK = 64 * 1024

Resolver = Callable[[str, int], Sequence[str]]
SocketFactory = Callable[[int, int], socket.socket]
SSLContextFactory = Callable[[], ssl.SSLContext]
ResponseFactory = Callable[..., http.client.HTTPResponse]


class HomeAssistantTransportError(RuntimeError):
    """Execution failed without producing trustworthy Home Assistant evidence."""


class HomeAssistantStateTransport(Protocol):
    def request(
        self,
        url: str,
        *,
        connect_address: str,
        bearer_token: str,
        allow_insecure_http: bool,
        timeout_seconds: float,
        max_wire_bytes: int,
    ) -> TransportResponse:
        ...


def _time(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HomeRigContractError(f"{name} must be a non-negative integer")
    return value


def _origin(value: str) -> tuple[str, str, int, str]:
    if not isinstance(value, str):
        raise HomeAssistantTransportError("Home Assistant origin must be a string")
    try:
        parsed = urlsplit(value.strip())
        explicit_port = parsed.port
    except ValueError as exc:
        raise HomeAssistantTransportError("Home Assistant origin has an invalid port") from exc
    if parsed.scheme not in {"http", "https"}:
        raise HomeAssistantTransportError("Home Assistant origin must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise HomeAssistantTransportError("Home Assistant origin credentials are forbidden")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise HomeAssistantTransportError("Home Assistant origin must not contain path/query/fragment")
    host = parsed.hostname
    if not host:
        raise HomeAssistantTransportError("Home Assistant origin is missing a host")
    try:
        host = host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise HomeAssistantTransportError("Home Assistant origin host is invalid") from exc
    port = explicit_port or (443 if parsed.scheme == "https" else 80)
    if not 1 <= port <= 65535:
        raise HomeAssistantTransportError("Home Assistant origin port is invalid")
    host_literal = f"[{host}]" if ":" in host else host
    default = (parsed.scheme == "https" and port == 443) or (parsed.scheme == "http" and port == 80)
    canonical = f"{parsed.scheme}://{host_literal}" + ("" if default else f":{port}")
    return parsed.scheme, host, port, canonical


@dataclass(frozen=True)
class HomeAssistantConnection:
    """Deployment-owned Home Assistant endpoint and credential-file reference."""

    origin: str
    token_file: Path
    allow_insecure_http: bool = False
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.production_activation is not False:
            raise HomeAssistantTransportError("Home Assistant production activation must remain false")
        scheme, _, _, canonical = _origin(self.origin)
        token_path = Path(self.token_file)
        if not token_path.is_absolute():
            raise HomeAssistantTransportError("Home Assistant token file must be an absolute path")
        if scheme == "http" and self.allow_insecure_http is not True:
            raise HomeAssistantTransportError("plaintext Home Assistant origin requires explicit opt-in")
        object.__setattr__(self, "origin", canonical)
        object.__setattr__(self, "token_file", token_path)


def default_resolver(host: str, port: int) -> tuple[str, ...]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise HomeAssistantTransportError("Home Assistant DNS resolution failed") from exc
    addresses = tuple(dict.fromkeys(info[4][0] for info in infos))
    if not addresses:
        raise HomeAssistantTransportError("Home Assistant DNS returned no addresses")
    return addresses


def _resolve_connection(connection: HomeAssistantConnection, resolver: Resolver) -> tuple[str, str, int, str]:
    scheme, host, port, _ = _origin(connection.origin)
    try:
        raw = tuple(resolver(host, port))
    except HomeAssistantTransportError:
        raise
    except Exception as exc:
        raise HomeAssistantTransportError("Home Assistant DNS resolution failed") from exc
    if not raw:
        raise HomeAssistantTransportError("Home Assistant DNS returned no addresses")

    normalized: list[str] = []
    for value in raw:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise HomeAssistantTransportError("Home Assistant DNS returned a non-IP address") from exc
        if address.is_unspecified or address.is_multicast:
            raise HomeAssistantTransportError("Home Assistant DNS returned an unusable address")
        if scheme == "http" and address.is_global:
            raise HomeAssistantTransportError("plaintext Home Assistant bearer cannot target a global peer")
        item = address.compressed
        if item not in normalized:
            normalized.append(item)

    normalized.sort(key=lambda item: (ipaddress.ip_address(item).version, ipaddress.ip_address(item).packed))
    return scheme, host, port, normalized[0]


def _load_bearer(path: Path) -> str:
    try:
        info = path.stat()
    except OSError as exc:
        raise HomeAssistantTransportError("Home Assistant credential file is unavailable") from exc
    if not stat.S_ISREG(info.st_mode):
        raise HomeAssistantTransportError("Home Assistant credential path must be a regular file")
    if info.st_size < 1 or info.st_size > _MAX_BEARER_BYTES + 2:
        raise HomeAssistantTransportError("Home Assistant credential file size is invalid")
    if os.name == "posix" and (info.st_mode & 0o077):
        raise HomeAssistantTransportError("Home Assistant credential file permissions are too broad")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise HomeAssistantTransportError("Home Assistant credential file could not be read") from exc
    token_bytes = raw[:-2] if raw.endswith(b"\r\n") else raw[:-1] if raw.endswith(b"\n") else raw
    if raw not in {token_bytes, token_bytes + b"\n", token_bytes + b"\r\n"}:
        raise HomeAssistantTransportError("Home Assistant credential file format is invalid")
    try:
        token = token_bytes.decode("ascii")
    except UnicodeDecodeError as exc:
        raise HomeAssistantTransportError("Home Assistant bearer format is invalid") from exc
    if not 20 <= len(token) <= _MAX_BEARER_BYTES:
        raise HomeAssistantTransportError("Home Assistant bearer length is invalid")
    if token != token.strip() or any(ord(ch) < 0x21 or ord(ch) > 0x7E for ch in token):
        raise HomeAssistantTransportError("Home Assistant bearer format is invalid")
    return token


def _response_headers(pairs: list[tuple[str, str]]) -> dict[str, str]:
    grouped: dict[str, list[str]] = {}
    total = 0
    for raw_name, raw_value in pairs:
        name = raw_name.strip().lower()
        value = raw_value.strip()
        total += len(name) + len(value) + 4
        if total > _MAX_HEADER_BYTES:
            raise HomeAssistantTransportError("Home Assistant response headers exceed limit")
        if "\r" in value or "\n" in value or "\x00" in value:
            raise HomeAssistantTransportError("Home Assistant response header is invalid")
        grouped.setdefault(name, []).append(value)
    for name in ("content-length", "content-type", "content-encoding", "location", "transfer-encoding"):
        if len(grouped.get(name, ())) > 1:
            raise HomeAssistantTransportError(f"Home Assistant repeated singleton header {name}")
    if grouped.get("content-length") and grouped.get("transfer-encoding"):
        raise HomeAssistantTransportError("Home Assistant mixed response framing")
    return {name: ", ".join(values) for name, values in grouped.items()}


class PinnedHomeAssistantTransport:
    """One-request bearer GET pinned to the already validated Home Assistant peer."""

    def __init__(
        self,
        *,
        socket_factory: SocketFactory = socket.socket,
        ssl_context_factory: SSLContextFactory = ssl.create_default_context,
        response_factory: ResponseFactory = http.client.HTTPResponse,
    ) -> None:
        self._socket_factory = socket_factory
        self._ssl_context_factory = ssl_context_factory
        self._response_factory = response_factory

    def request(
        self,
        url: str,
        *,
        connect_address: str,
        bearer_token: str,
        allow_insecure_http: bool,
        timeout_seconds: float,
        max_wire_bytes: int,
    ) -> TransportResponse:
        if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
            raise HomeAssistantTransportError("Home Assistant timeout must be positive")
        if isinstance(max_wire_bytes, bool) or not isinstance(max_wire_bytes, int) or not 1 <= max_wire_bytes <= _MAX_RESPONSE_BYTES:
            raise HomeAssistantTransportError("Home Assistant response byte limit is invalid")
        if "/api/states/" not in url:
            raise HomeAssistantTransportError("Home Assistant request URL is not an entity-state read")
        origin_text, encoded_entity = url.rsplit("/api/states/", 1)
        scheme, host, port, canonical = _origin(origin_text)
        expected_prefix = canonical + "/api/states/"
        if not url.startswith(expected_prefix):
            raise HomeAssistantTransportError("Home Assistant request URL origin drifted")
        if not encoded_entity or "/" in encoded_entity or "?" in encoded_entity or "#" in encoded_entity:
            raise HomeAssistantTransportError("Home Assistant request path is invalid")
        if scheme == "http" and allow_insecure_http is not True:
            raise HomeAssistantTransportError("plaintext Home Assistant transport is not enabled")

        try:
            numeric = ipaddress.ip_address(connect_address)
        except ValueError as exc:
            raise HomeAssistantTransportError("Home Assistant connect address must be numeric") from exc
        if numeric.is_unspecified or numeric.is_multicast:
            raise HomeAssistantTransportError("Home Assistant connect address is unusable")
        if scheme == "http" and numeric.is_global:
            raise HomeAssistantTransportError("plaintext Home Assistant bearer cannot target a global peer")
        if not isinstance(bearer_token, str) or not 20 <= len(bearer_token) <= _MAX_BEARER_BYTES:
            raise HomeAssistantTransportError("Home Assistant bearer is invalid")
        if bearer_token != bearer_token.strip() or not bearer_token.isascii() or any(
            ord(ch) < 0x21 or ord(ch) > 0x7E for ch in bearer_token
        ):
            raise HomeAssistantTransportError("Home Assistant bearer is invalid")

        family = socket.AF_INET6 if numeric.version == 6 else socket.AF_INET
        sockaddr = (numeric.compressed, port, 0, 0) if family == socket.AF_INET6 else (numeric.compressed, port)
        host_literal = f"[{host}]" if ":" in host else host
        default = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
        host_header = host_literal if default else f"{host_literal}:{port}"
        target = "/api/states/" + encoded_entity

        raw_socket = active_socket = response = None
        try:
            raw_socket = self._socket_factory(family, socket.SOCK_STREAM)
            raw_socket.settimeout(float(timeout_seconds))
            raw_socket.connect(sockaddr)
            active_socket = raw_socket
            if scheme == "https":
                context = self._ssl_context_factory()
                active_socket = context.wrap_socket(raw_socket, server_hostname=host)
                active_socket.settimeout(float(timeout_seconds))

            peer = ipaddress.ip_address(active_socket.getpeername()[0]).compressed
            if peer != numeric.compressed:
                raise HomeAssistantTransportError("Home Assistant connected peer drifted")
            request_lines = [
                f"GET {target} HTTP/1.1",
                f"Host: {host_header}",
                "Accept: application/json",
                "Accept-Encoding: identity",
                "Connection: close",
                f"Authorization: Bearer {bearer_token}",
            ]
            active_socket.sendall(("\r\n".join(request_lines) + "\r\n\r\n").encode("ascii"))

            response = self._response_factory(active_socket, method="GET")
            response.begin()
            headers = _response_headers(response.getheaders())
            body = bytearray()
            while True:
                remaining = max_wire_bytes + 1 - len(body)
                if remaining <= 0:
                    raise HomeAssistantTransportError("Home Assistant response exceeded byte limit")
                chunk = response.read(min(_READ_CHUNK, remaining))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > max_wire_bytes:
                    raise HomeAssistantTransportError("Home Assistant response exceeded byte limit")
            return TransportResponse(response.status, headers, bytes(body), peer)
        except HomeAssistantTransportError:
            raise
        except ssl.SSLCertVerificationError as exc:
            raise HomeAssistantTransportError("Home Assistant TLS certificate verification failed") from exc
        except ssl.SSLError as exc:
            raise HomeAssistantTransportError("Home Assistant TLS handshake failed") from exc
        except (socket.timeout, TimeoutError) as exc:
            raise HomeAssistantTransportError("Home Assistant transport timed out") from exc
        except (http.client.HTTPException, ValueError) as exc:
            raise HomeAssistantTransportError("Home Assistant returned an invalid HTTP response") from exc
        except OSError as exc:
            raise HomeAssistantTransportError("Home Assistant connection failed") from exc
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
            if active_socket is not None:
                try:
                    active_socket.close()
                except Exception:
                    pass
            if raw_socket is not None and raw_socket is not active_socket:
                try:
                    raw_socket.close()
                except Exception:
                    pass


def execute_home_assistant_state_read(
    grants: HomeRigGrantStore,
    ledger: DataSharingLedger,
    authorized: AuthorizedHomeAssistantRead,
    connection: HomeAssistantConnection,
    *,
    now: int,
    resolver: Resolver = default_resolver,
    transport: HomeAssistantStateTransport | None = None,
    timeout_seconds: float = 5.0,
) -> HomeAssistantStateEvidence:
    """Execute one already-authorized Home Assistant GET and close T-032 receipt."""
    now = _time(now, "received_at")
    if not isinstance(grants, HomeRigGrantStore):
        raise HomeRigContractError("Home Assistant execution requires HomeRigGrantStore")
    if not isinstance(ledger, DataSharingLedger):
        raise HomeRigContractError("Home Assistant execution requires DataSharingLedger")
    if not isinstance(authorized, AuthorizedHomeAssistantRead):
        raise HomeRigContractError("Home Assistant execution requires AuthorizedHomeAssistantRead")
    if not isinstance(connection, HomeAssistantConnection):
        raise HomeAssistantTransportError("Home Assistant execution requires explicit connection config")

    plan = authorized.plan
    try:
        grant = grants.authorize(
            plan.grant_id,
            target_kind="entity",
            target_id=plan.entity_id,
            operation="entity_state",
        )
        if grant.scope.digest != plan.scope_sha256:
            raise HomeRigDenied("home/rig scope changed before Home Assistant execution")
    except HomeRigDenied:
        finish_home_assistant_state_request(
            ledger,
            authorized,
            outcome="blocked",
            bytes_sent=0,
            error_code="authority_revoked_execute",
            now=now,
        )
        raise

    try:
        _, _, _, selected = _resolve_connection(connection, resolver)
        bearer = _load_bearer(connection.token_file)
        url = connection.origin + plan.path
        response = (transport or PinnedHomeAssistantTransport()).request(
            url,
            connect_address=selected,
            bearer_token=bearer,
            allow_insecure_http=connection.allow_insecure_http,
            timeout_seconds=timeout_seconds,
            max_wire_bytes=_MAX_RESPONSE_BYTES,
        )
        if response.connected_address != selected:
            raise HomeAssistantTransportError("Home Assistant response peer did not match selected address")
        if response.status != 200:
            raise HomeAssistantTransportError("Home Assistant state request did not return HTTP 200")
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise HomeAssistantTransportError("Home Assistant state response is not application/json")
        content_encoding = response.headers.get("content-encoding", "").strip().lower()
        if content_encoding not in {"", "identity"}:
            raise HomeAssistantTransportError("Home Assistant response content encoding is unsupported")
        evidence = parse_home_assistant_state(
            response.body,
            expected_entity_id=plan.entity_id,
            received_at=now,
        )
    except Exception:
        finish_home_assistant_state_request(
            ledger,
            authorized,
            outcome="failed",
            bytes_sent=0,
            error_code="home_assistant_read_failed",
            now=now,
        )
        raise

    finish_home_assistant_state_request(
        ledger,
        authorized,
        outcome="completed",
        bytes_sent=authorized.sharing_request.max_bytes,
        now=now,
    )
    return evidence
