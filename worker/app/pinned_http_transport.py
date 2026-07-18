"""Pinned stdlib HTTP transport for the dormant deterministic web fetcher.

The transport bypasses proxy/environment discovery and never resolves the URL
host itself. It opens one socket to the exact IP selected by the fetch engine,
preserves the original host for HTTP Host and TLS SNI/certificate verification,
never follows redirects, and enforces a wire-byte ceiling.
"""
from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
from collections.abc import Callable, Mapping
from urllib.parse import quote, urlsplit

from .web_fetch import TransportResponse, WebFetchError

_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_FORBIDDEN_REQUEST_HEADERS = frozenset({
    "authorization", "connection", "content-length", "cookie", "expect",
    "host", "proxy-authorization", "proxy-connection", "te", "trailer",
    "transfer-encoding", "upgrade",
})
_SINGLETON_RESPONSE_HEADERS = frozenset({
    "content-disposition", "content-encoding", "content-length",
    "content-type", "location", "transfer-encoding",
})
_MAX_HEADER_BYTES = 64 * 1024
_READ_CHUNK = 64 * 1024

SocketFactory = Callable[[int, int], socket.socket]
SSLContextFactory = Callable[[], ssl.SSLContext]
ResponseFactory = Callable[..., http.client.HTTPResponse]


def _request_target(url: str) -> tuple[str, str, int, str, str]:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise WebFetchError("transport URL has an invalid port") from exc
    if parsed.scheme not in {"http", "https"}:
        raise WebFetchError("transport only supports http/https")
    if parsed.username is not None or parsed.password is not None:
        raise WebFetchError("transport URL credentials are forbidden")
    host = parsed.hostname
    if not host:
        raise WebFetchError("transport URL is missing a host")
    try:
        host = host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise WebFetchError("transport URL host is invalid") from exc
    effective_port = port or (443 if parsed.scheme == "https" else 80)
    path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = quote(parsed.query, safe="=&?/:;+,%@!$'()*-._~")
    target = path + (f"?{query}" if query else "")
    default_port = (parsed.scheme == "https" and effective_port == 443) or (
        parsed.scheme == "http" and effective_port == 80
    )
    host_header = host if default_port else f"{host}:{effective_port}"
    return parsed.scheme, host, effective_port, target, host_header


def _validated_headers(headers: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    clean: list[tuple[str, str]] = []
    for raw_name, raw_value in headers.items():
        if not isinstance(raw_name, str) or not isinstance(raw_value, str):
            raise WebFetchError("transport headers must be strings")
        name = raw_name.strip().lower()
        value = raw_value.strip()
        if not _HEADER_NAME_RE.fullmatch(name):
            raise WebFetchError("transport header name is invalid")
        if name in _FORBIDDEN_REQUEST_HEADERS:
            raise WebFetchError(f"transport header {name!r} is forbidden")
        if "\r" in value or "\n" in value or "\x00" in value:
            raise WebFetchError("transport header value is invalid")
        clean.append((name, value))
    clean.sort()
    return tuple(clean)


def _normalize_response_headers(pairs: list[tuple[str, str]]) -> dict[str, str]:
    grouped: dict[str, list[str]] = {}
    total = 0
    for raw_name, raw_value in pairs:
        name = raw_name.strip().lower()
        value = raw_value.strip()
        total += len(name) + len(value) + 4
        if total > _MAX_HEADER_BYTES:
            raise WebFetchError("HTTP response headers exceed the transport limit")
        if not _HEADER_NAME_RE.fullmatch(name):
            raise WebFetchError("HTTP response header name is invalid")
        if "\r" in value or "\n" in value or "\x00" in value:
            raise WebFetchError("HTTP response header value is invalid")
        grouped.setdefault(name, []).append(value)

    for name in _SINGLETON_RESPONSE_HEADERS:
        if len(grouped.get(name, ())) > 1:
            raise WebFetchError(f"HTTP response repeated singleton header {name}")

    content_length = grouped.get("content-length", ())
    transfer_encoding = grouped.get("transfer-encoding", ())
    if content_length and transfer_encoding:
        raise WebFetchError("HTTP response mixed Content-Length and Transfer-Encoding")
    if transfer_encoding:
        codings = [part.strip().lower() for part in transfer_encoding[0].split(",")]
        if codings != ["chunked"]:
            raise WebFetchError("HTTP response used unsupported Transfer-Encoding")

    return {name: ", ".join(values) for name, values in grouped.items()}


class PinnedHttpTransport:
    """One-request transport pinned to an already validated numeric peer."""

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
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_wire_bytes: int,
    ) -> TransportResponse:
        if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise WebFetchError("transport timeout must be positive")
        if not isinstance(max_wire_bytes, int) or max_wire_bytes < 1:
            raise WebFetchError("transport max_wire_bytes must be positive")

        scheme, host, port, target, host_header = _request_target(url)
        try:
            numeric = ipaddress.ip_address(connect_address)
        except ValueError as exc:
            raise WebFetchError("transport connect_address must be a numeric IP") from exc
        clean_headers = _validated_headers(headers)
        family = socket.AF_INET6 if numeric.version == 6 else socket.AF_INET
        sockaddr = (
            (numeric.compressed, port, 0, 0)
            if family == socket.AF_INET6
            else (numeric.compressed, port)
        )

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
            request_lines = [
                f"GET {target} HTTP/1.1",
                f"Host: {host_header}",
                "Connection: close",
            ]
            request_lines.extend(f"{name}: {value}" for name, value in clean_headers)
            active_socket.sendall(("\r\n".join(request_lines) + "\r\n\r\n").encode("ascii"))

            response = self._response_factory(active_socket, method="GET")
            response.begin()
            response_headers = _normalize_response_headers(response.getheaders())

            body = bytearray()
            while True:
                remaining = max_wire_bytes + 1 - len(body)
                if remaining <= 0:
                    raise WebFetchError("transport exceeded max_wire_bytes")
                chunk = response.read(min(_READ_CHUNK, remaining))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > max_wire_bytes:
                    raise WebFetchError("transport exceeded max_wire_bytes")

            return TransportResponse(
                status=response.status,
                headers=response_headers,
                body=bytes(body),
                connected_address=peer,
            )
        except WebFetchError:
            raise
        except ssl.SSLCertVerificationError as exc:
            raise WebFetchError("TLS certificate verification failed") from exc
        except ssl.SSLError as exc:
            raise WebFetchError("TLS handshake failed") from exc
        except (socket.timeout, TimeoutError) as exc:
            raise WebFetchError("transport timeout") from exc
        except (http.client.HTTPException, ValueError) as exc:
            raise WebFetchError("invalid HTTP response") from exc
        except OSError as exc:
            raise WebFetchError("transport connection failed") from exc
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
