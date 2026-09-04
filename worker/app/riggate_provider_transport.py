"""Dormant concrete RigGate v1 read transport for T-038.

The RigGate contract already binds one exact rig/status read to durable T-038
scope and one-use T-032 authority. This module performs the deployment-local
execution step without registering RigGate as a normal runtime capability:

* origin and bearer-file location are deployment injected, never model supplied;
* the exact T-038 grant/scope is checked again immediately before DNS/file/network;
* DNS is pinned to one validated numeric peer and the connected peer must match;
* plaintext HTTP requires explicit deployment opt-in and may not target a global peer;
* one GET is issued to the already-authorized fixed RigGate v1 path;
* redirects are never followed, response headers/body are bounded, JSON is exact;
* the claimed T-032 receipt always finishes completed, failed, or blocked.

There is no ToolGate/runtime registration, wake/control execution, environment
discovery, provider-origin discovery, or production activation in this slice.
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
from .home_rig_connector_contract import HomeRigContractError, HomeRigDenied, HomeRigGrantStore
from .riggate_v1_contract import (
    AuthorizedRigGateRead,
    RigGateStatusEvidence,
    finish_riggate_request,
    parse_riggate_status_response,
)
from .web_fetch import TransportResponse

PRODUCTION_ACTIVATION = False
_MAX_BEARER_BYTES = 4_096
_MAX_RESPONSE_BYTES = 64 * 1024
_MAX_HEADER_BYTES = 32 * 1024
_READ_CHUNK = 32 * 1024

Resolver = Callable[[str, int], Sequence[str]]
SocketFactory = Callable[[int, int], socket.socket]
SSLContextFactory = Callable[[], ssl.SSLContext]
ResponseFactory = Callable[..., http.client.HTTPResponse]


class RigGateTransportError(RuntimeError):
    """Execution failed without producing trustworthy RigGate evidence."""


class RigGateStatusTransport(Protocol):
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
        raise RigGateTransportError("RigGate origin must be a string")
    try:
        parsed = urlsplit(value.strip())
        explicit_port = parsed.port
    except ValueError as exc:
        raise RigGateTransportError("RigGate origin has an invalid port") from exc
    if parsed.scheme not in {"http", "https"}:
        raise RigGateTransportError("RigGate origin must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise RigGateTransportError("RigGate origin credentials are forbidden")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise RigGateTransportError("RigGate origin must not contain path/query/fragment")
    host = parsed.hostname
    if not host:
        raise RigGateTransportError("RigGate origin is missing a host")
    try:
        host = host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise RigGateTransportError("RigGate origin host is invalid") from exc
    port = explicit_port or (443 if parsed.scheme == "https" else 80)
    if not 1 <= port <= 65535:
        raise RigGateTransportError("RigGate origin port is invalid")
    host_literal = f"[{host}]" if ":" in host else host
    default = (parsed.scheme == "https" and port == 443) or (parsed.scheme == "http" and port == 80)
    canonical = f"{parsed.scheme}://{host_literal}" + ("" if default else f":{port}")
    return parsed.scheme, host, port, canonical


@dataclass(frozen=True)
class RigGateConnection:
    """Deployment-owned RigGate endpoint and credential-file reference."""

    origin: str
    token_file: Path
    allow_insecure_http: bool = False
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.production_activation is not False:
            raise RigGateTransportError("RigGate production activation must remain false")
        scheme, _, _, canonical = _origin(self.origin)
        token_path = Path(self.token_file)
        if not token_path.is_absolute():
            raise RigGateTransportError("RigGate token file must be an absolute path")
        if scheme == "http" and self.allow_insecure_http is not True:
            raise RigGateTransportError("plaintext RigGate origin requires explicit opt-in")
        object.__setattr__(self, "origin", canonical)
        object.__setattr__(self, "token_file", token_path)


def default_resolver(host: str, port: int) -> tuple[str, ...]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise RigGateTransportError("RigGate DNS resolution failed") from exc
    addresses = tuple(dict.fromkeys(info[4][0] for info in infos))
    if not addresses:
        raise RigGateTransportError("RigGate DNS returned no addresses")
    return addresses


def _resolve_connection(connection: RigGateConnection, resolver: Resolver) -> tuple[str, str, int, str]:
    scheme, host, port, _ = _origin(connection.origin)
    try:
        raw = tuple(resolver(host, port))
    except RigGateTransportError:
        raise
    except Exception as exc:
        raise RigGateTransportError("RigGate DNS resolution failed") from exc
    if not raw:
        raise RigGateTransportError("RigGate DNS returned no addresses")

    normalized: list[str] = []
    for value in raw:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise RigGateTransportError("RigGate DNS returned a non-IP address") from exc
        if address.is_unspecified or address.is_multicast:
            raise RigGateTransportError("RigGate DNS returned an unusable address")
        if scheme == "http" and address.is_global:
            raise RigGateTransportError("plaintext RigGate bearer cannot target a global peer")
        item = address.compressed
        if item not in normalized:
            normalized.append(item)

    normalized.sort(key=lambda item: (ipaddress.ip_address(item).version, ipaddress.ip_address(item).packed))
    return scheme, host, port, normalized[0]


def _load_bearer(path: Path) -> str:
    try:
        info = path.stat()
    except OSError as exc:
        raise RigGateTransportError("RigGate credential file is unavailable") from exc
    if not stat.S_ISREG(info.st_mode):
        raise RigGateTransportError("RigGate credential path must be a regular file")
    if info.st_size < 1 or info.st_size > _MAX_BEARER_BYTES + 2:
        raise RigGateTransportError("RigGate credential file size is invalid")
    if os.name == "posix" and (info.st_mode & 0o077):
        raise RigGateTransportError("RigGate credential file permissions are too broad")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RigGateTransportError("RigGate credential file could not be read") from exc
    token_bytes = raw[:-2] if raw.endswith(b"\r\n") else raw[:-1] if raw.endswith(b"\n") else raw
    if raw not in {token_bytes, token_bytes + b"\n", token_bytes + b"\r\n"}:
        raise RigGateTransportError("RigGate credential file format is invalid")
    try:
        token = token_bytes.decode("ascii")
    except UnicodeDecodeError as exc:
        raise RigGateTransportError("RigGate bearer format is invalid") from exc
    if not 20 <= len(token) <= _MAX_BEARER_BYTES:
        raise RigGateTransportError("RigGate bearer length is invalid")
    if token != token.strip() or any(ord(ch) < 0x21 or ord(ch) > 0x7E for ch in token):
        raise RigGateTransportError("RigGate bearer format is invalid")
    return token


def _response_headers(pairs: list[tuple[str, str]]) -> dict[str, str]:
    grouped: dict[str, list[str]] = {}
    total = 0
    for raw_name, raw_value in pairs:
        name = raw_name.strip().lower()
        value = raw_value.strip()
        total += len(name) + len(value) + 4
        if total > _MAX_HEADER_BYTES:
            raise RigGateTransportError("RigGate response headers exceed limit")
        if "\r" in value or "\n" in value or "\x00" in value:
            raise RigGateTransportError("RigGate response header is invalid")
        grouped.setdefault(name, []).append(value)
    for name in ("content-length", "content-type", "content-encoding", "location", "transfer-encoding"):
        if len(grouped.get(name, ())) > 1:
            raise RigGateTransportError(f"RigGate repeated singleton header {name}")
    if grouped.get("content-length") and grouped.get("transfer-encoding"):
        raise RigGateTransportError("RigGate mixed response framing")
    return {name: ", ".join(values) for name, values in grouped.items()}


def _request_target(url: str) -> tuple[str, str, int, str]:
    try:
        parsed = urlsplit(url)
        explicit_port = parsed.port
    except ValueError as exc:
        raise RigGateTransportError("RigGate request URL is invalid") from exc
    if parsed.scheme not in {"http", "https"} or parsed.username is not None or parsed.password is not None:
        raise RigGateTransportError("RigGate request URL origin is invalid")
    if parsed.query or parsed.fragment:
        raise RigGateTransportError("RigGate request URL must not contain query or fragment")
    host = parsed.hostname
    if not host:
        raise RigGateTransportError("RigGate request URL is missing a host")
    try:
        host = host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise RigGateTransportError("RigGate request URL host is invalid") from exc
    port = explicit_port or (443 if parsed.scheme == "https" else 80)
    if not 1 <= port <= 65535:
        raise RigGateTransportError("RigGate request URL port is invalid")
    parts = parsed.path.split("/")
    if len(parts) != 5 or parts[:3] != ["", "v1", "rigs"] or not parts[3]:
        raise RigGateTransportError("RigGate request path is not a v1 rig read")
    if parts[4] not in {"health", "power-readiness"}:
        raise RigGateTransportError("RigGate request path is not an allowed status operation")
    if "/" in parts[3] or "?" in parts[3] or "#" in parts[3]:
        raise RigGateTransportError("RigGate request rig path segment is invalid")
    return parsed.scheme, host, port, parsed.path


class PinnedRigGateTransport:
    """One-request bearer GET pinned to the already validated RigGate peer."""

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
            raise RigGateTransportError("RigGate timeout must be positive")
        if isinstance(max_wire_bytes, bool) or not isinstance(max_wire_bytes, int) or not 1 <= max_wire_bytes <= _MAX_RESPONSE_BYTES:
            raise RigGateTransportError("RigGate response byte limit is invalid")

        scheme, host, port, target = _request_target(url)
        if scheme == "http" and allow_insecure_http is not True:
            raise RigGateTransportError("plaintext RigGate transport is not enabled")

        try:
            numeric = ipaddress.ip_address(connect_address)
        except ValueError as exc:
            raise RigGateTransportError("RigGate connect address must be numeric") from exc
        if numeric.is_unspecified or numeric.is_multicast:
            raise RigGateTransportError("RigGate connect address is unusable")
        if scheme == "http" and numeric.is_global:
            raise RigGateTransportError("plaintext RigGate bearer cannot target a global peer")
        if not isinstance(bearer_token, str) or not 20 <= len(bearer_token) <= _MAX_BEARER_BYTES:
            raise RigGateTransportError("RigGate bearer is invalid")
        if bearer_token != bearer_token.strip() or not bearer_token.isascii() or any(
            ord(ch) < 0x21 or ord(ch) > 0x7E for ch in bearer_token
        ):
            raise RigGateTransportError("RigGate bearer is invalid")

        family = socket.AF_INET6 if numeric.version == 6 else socket.AF_INET
        sockaddr = (numeric.compressed, port, 0, 0) if family == socket.AF_INET6 else (numeric.compressed, port)
        host_literal = f"[{host}]" if ":" in host else host
        default = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
        host_header = host_literal if default else f"{host_literal}:{port}"

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
                raise RigGateTransportError("RigGate connected peer drifted")
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
                    raise RigGateTransportError("RigGate response exceeded byte limit")
                chunk = response.read(min(_READ_CHUNK, remaining))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > max_wire_bytes:
                    raise RigGateTransportError("RigGate response exceeded byte limit")
            return TransportResponse(response.status, headers, bytes(body), peer)
        except RigGateTransportError:
            raise
        except ssl.SSLCertVerificationError as exc:
            raise RigGateTransportError("RigGate TLS certificate verification failed") from exc
        except ssl.SSLError as exc:
            raise RigGateTransportError("RigGate TLS handshake failed") from exc
        except (socket.timeout, TimeoutError) as exc:
            raise RigGateTransportError("RigGate transport timed out") from exc
        except (http.client.HTTPException, ValueError) as exc:
            raise RigGateTransportError("RigGate returned an invalid HTTP response") from exc
        except OSError as exc:
            raise RigGateTransportError("RigGate connection failed") from exc
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


def execute_riggate_status_read(
    grants: HomeRigGrantStore,
    ledger: DataSharingLedger,
    authorized: AuthorizedRigGateRead,
    connection: RigGateConnection,
    *,
    now: int,
    resolver: Resolver = default_resolver,
    transport: RigGateStatusTransport | None = None,
    timeout_seconds: float = 5.0,
) -> RigGateStatusEvidence:
    """Execute one already-authorized RigGate GET and close its T-032 receipt."""
    now = _time(now, "received_at")
    if not isinstance(grants, HomeRigGrantStore):
        raise HomeRigContractError("RigGate execution requires HomeRigGrantStore")
    if not isinstance(ledger, DataSharingLedger):
        raise HomeRigContractError("RigGate execution requires DataSharingLedger")
    if not isinstance(authorized, AuthorizedRigGateRead):
        raise HomeRigContractError("RigGate execution requires AuthorizedRigGateRead")
    if not isinstance(connection, RigGateConnection):
        raise RigGateTransportError("RigGate execution requires explicit connection config")

    plan = authorized.plan
    try:
        grant = grants.authorize(
            plan.grant_id,
            target_kind="rig",
            target_id=plan.rig_id,
            operation=plan.operation,
        )
        if grant.scope.digest != plan.scope_sha256:
            raise HomeRigDenied("home/rig scope changed before RigGate execution")
    except HomeRigDenied:
        finish_riggate_request(
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
        response = (transport or PinnedRigGateTransport()).request(
            url,
            connect_address=selected,
            bearer_token=bearer,
            allow_insecure_http=connection.allow_insecure_http,
            timeout_seconds=timeout_seconds,
            max_wire_bytes=plan.max_response_bytes,
        )
        if response.connected_address != selected:
            raise RigGateTransportError("RigGate response peer did not match selected address")
        if response.status != 200:
            raise RigGateTransportError("RigGate status request did not return HTTP 200")
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise RigGateTransportError("RigGate status response is not application/json")
        content_encoding = response.headers.get("content-encoding", "").strip().lower()
        if content_encoding not in {"", "identity"}:
            raise RigGateTransportError("RigGate response content encoding is unsupported")
        evidence = parse_riggate_status_response(
            response.body,
            expected_rig_id=plan.rig_id,
            expected_operation=plan.operation,
        )
    except Exception:
        finish_riggate_request(
            ledger,
            authorized,
            outcome="failed",
            bytes_sent=0,
            error_code="riggate_read_failed",
            now=now,
        )
        raise

    finish_riggate_request(
        ledger,
        authorized,
        outcome="completed",
        bytes_sent=authorized.sharing_request.max_bytes,
        now=now,
    )
    return evidence
