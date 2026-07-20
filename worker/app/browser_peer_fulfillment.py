"""Dormant pinned HTTP(S) fulfillment for peer-bound browser requests.

Chromium never connects to the public destination in this contract. A caller pauses
one request at ``Fetch.requestPaused``, the common browser-peer adapter claims the
exact URL and selected public address, and this controller performs one numeric-IP
HTTP(S) request itself. The caller may then satisfy Chromium with
``Fetch.fulfillRequest`` and explicitly commit or abort the pending fulfillment.

The transport bypasses proxy and environment discovery, performs no DNS lookup,
preserves the canonical hostname for HTTP Host, TLS SNI and certificate checks,
counts application bytes confirmed by ``socket.send`` and closes every connection.
The controller additionally shares one aggregate ``OutboundByteMeter`` across all
requests under the same common claim, so redirects and subresources cannot each
reuse the full byte ceiling.

Nothing imports this module from BrowserHost, Browser Use, ToolGate or an API route.
It opens sockets only when an injected caller explicitly invokes ``prepare``.
"""
from __future__ import annotations

import base64
import http.client
import ipaddress
import re
import socket
import ssl
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote, urlsplit

from .browser_peer_adapter import (
    BrowserPeerAdapter,
    BrowserPeerAdapterContractError,
    BrowserPeerAdapterDenied,
    BrowserPeerPermit,
    BrowserPeerPinReceipt,
)
from .research_claim_evidence import DataSharingClaimEvidence
from .research_contract import ResearchContractError, canonicalize_url
from .research_data_sharing import ResearchSharingIntent
from .research_peer_authorization import ResearchPeerAuthorizationBridge
from .research_peer_transfer import ResearchPeerBinding, ResearchPeerTransferLedger
from .research_sharing_boundary import ResearchSharingLease
from .research_sharing_execution import OutboundByteMeter, ResearchExternalBlocked

BROWSER_FULFILLMENT_SCHEMA = "kaliv-browser-peer-fulfillment/v1"
_TRANSPORT_SCHEMA = "kaliv-browser-pinned-transport/v1"
_MAX_HEADER_BYTES = 64 * 1024
_MAX_RESPONSE_BYTES = 10_000_000
_READ_CHUNK = 64 * 1024
_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_PIN_ID = re.compile(r"^bpp_[a-f0-9]{32}$")
_ALLOWED_METHODS = frozenset({"GET", "HEAD"})
_ALLOWED_BROWSER_HEADERS = frozenset({"accept", "accept-language", "user-agent"})
_FORBIDDEN_REQUEST_HEADERS = frozenset(
    {
        "authorization",
        "connection",
        "content-length",
        "cookie",
        "expect",
        "host",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
_HOP_RESPONSE_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
_SINGLETON_RESPONSE_HEADERS = frozenset(
    {
        "content-disposition",
        "content-encoding",
        "content-length",
        "content-type",
        "location",
        "transfer-encoding",
    }
)
_PENDING_TOKEN = object()
SocketFactory = Callable[[int, int], socket.socket]
SSLContextFactory = Callable[[], ssl.SSLContext]
ResponseFactory = Callable[..., http.client.HTTPResponse]
Clock = Callable[[], float]


class BrowserPeerFulfillmentContractError(ValueError):
    """A transport, CDP request or fulfillment input is malformed."""


class BrowserPeerFulfillmentDenied(PermissionError):
    """Pinned transport or aggregate byte policy refused the request."""


class BrowserPinnedTransportError(RuntimeError):
    """Normalized transport failure with confirmed application bytes sent."""

    def __init__(self, error_code: str, bytes_sent: int = 0) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.bytes_sent = bytes_sent


def _timestamp(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BrowserPeerFulfillmentContractError(
            f"{name} must be a non-negative integer timestamp"
        )
    return value


def _positive_float(value: float, name: str, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BrowserPeerFulfillmentContractError(f"{name} must be numeric")
    result = float(value)
    if not 0 < result <= maximum:
        raise BrowserPeerFulfillmentContractError(
            f"{name} must be between 0 and {maximum:g}"
        )
    return result


def _response_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BrowserPeerFulfillmentContractError(
            "max_response_bytes must be an integer"
        )
    if not 1 <= value <= _MAX_RESPONSE_BYTES:
        raise BrowserPeerFulfillmentContractError(
            f"max_response_bytes must be between 1 and {_MAX_RESPONSE_BYTES}"
        )
    return value


def _canonical_target(url: str) -> tuple[str, str, int, str, str, str]:
    if not isinstance(url, str):
        raise BrowserPeerFulfillmentContractError("URL must be a string")
    try:
        canonical = canonicalize_url(url)
        parsed = urlsplit(canonical)
        explicit_port = parsed.port
    except (ResearchContractError, ValueError) as exc:
        raise BrowserPeerFulfillmentDenied("URL is outside the web contract") from exc
    if parsed.scheme not in {"http", "https"}:
        raise BrowserPeerFulfillmentDenied("transport only supports HTTP(S)")
    host = parsed.hostname
    if not host:
        raise BrowserPeerFulfillmentContractError("URL is missing a host")
    host = host.lower()
    port = explicit_port or (443 if parsed.scheme == "https" else 80)
    path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = quote(parsed.query, safe="=&?/:;+,%@!$'()*-._~")
    target = path + (f"?{query}" if query else "")
    default_port = (parsed.scheme == "https" and port == 443) or (
        parsed.scheme == "http" and port == 80
    )
    host_header = host if default_port else f"{host}:{port}"
    return canonical, parsed.scheme, host, port, target, host_header


def _header_value(value: str) -> str:
    if not isinstance(value, str):
        raise BrowserPeerFulfillmentContractError("header values must be strings")
    cleaned = value.strip()
    if "\r" in cleaned or "\n" in cleaned or "\x00" in cleaned:
        raise BrowserPeerFulfillmentContractError("header value is invalid")
    try:
        cleaned.encode("ascii")
    except UnicodeEncodeError as exc:
        raise BrowserPeerFulfillmentContractError(
            "header value must be ASCII"
        ) from exc
    return cleaned


def _browser_headers(value: Any) -> tuple[tuple[str, str], ...]:
    if value is None:
        source: Mapping[str, str] = {}
    elif isinstance(value, Mapping):
        source = value
    else:
        raise BrowserPeerFulfillmentContractError(
            "browser request headers must be an object"
        )
    clean: dict[str, str] = {}
    for raw_name, raw_value in source.items():
        if not isinstance(raw_name, str):
            raise BrowserPeerFulfillmentContractError(
                "browser header names must be strings"
            )
        name = raw_name.strip().lower()
        if not _HEADER_NAME.fullmatch(name):
            raise BrowserPeerFulfillmentContractError(
                "browser header name is invalid"
            )
        if name in _FORBIDDEN_REQUEST_HEADERS:
            raise BrowserPeerFulfillmentDenied(
                "credential or framing browser header is forbidden"
            )
        if name in _ALLOWED_BROWSER_HEADERS:
            clean[name] = _header_value(raw_value)
    clean.setdefault("accept", "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.1")
    clean.setdefault("accept-language", "en-US,en;q=0.8")
    clean.setdefault("user-agent", "ModelRig-BrowserPeer/1.0")
    return tuple(sorted(clean.items()))


def _event_request(event: Any) -> tuple[str, str, str, tuple[tuple[str, str], ...]]:
    if not isinstance(event, dict):
        raise BrowserPeerFulfillmentContractError(
            "Fetch.requestPaused event must be an object"
        )
    request_id = event.get("requestId")
    network_id = event.get("networkId")
    request = event.get("request")
    if not isinstance(request_id, str) or not request_id:
        raise BrowserPeerFulfillmentContractError("requestId is invalid")
    if not isinstance(network_id, str) or not network_id:
        raise BrowserPeerFulfillmentContractError("networkId is invalid")
    if not isinstance(request, dict):
        raise BrowserPeerFulfillmentContractError("paused request is missing")
    method = request.get("method")
    if not isinstance(method, str) or method.upper() not in _ALLOWED_METHODS:
        raise BrowserPeerFulfillmentDenied("only GET and HEAD are supported")
    if request.get("hasPostData") is True or request.get("postData") not in {
        None,
        "",
    }:
        raise BrowserPeerFulfillmentDenied("request body is forbidden")
    canonical, *_ = _canonical_target(request.get("url"))
    return request_id, network_id, method.upper(), _browser_headers(
        request.get("headers")
    )


def _normalize_response_headers(
    pairs: list[tuple[str, str]],
    *,
    method: str,
    body_length: int,
) -> tuple[tuple[str, str], ...]:
    grouped: dict[str, list[str]] = {}
    total = 0
    for raw_name, raw_value in pairs:
        name = raw_name.strip().lower()
        value = raw_value.strip()
        total += len(name) + len(value) + 4
        if total > _MAX_HEADER_BYTES:
            raise BrowserPinnedTransportError("response_headers_too_large")
        if not _HEADER_NAME.fullmatch(name):
            raise BrowserPinnedTransportError("response_header_invalid")
        if "\r" in value or "\n" in value or "\x00" in value:
            raise BrowserPinnedTransportError("response_header_invalid")
        if name in _HOP_RESPONSE_HEADERS or name == "set-cookie":
            continue
        grouped.setdefault(name, []).append(value)
    for name in _SINGLETON_RESPONSE_HEADERS:
        if len(grouped.get(name, ())) > 1:
            raise BrowserPinnedTransportError("response_header_ambiguous")
    if grouped.get("content-length") and grouped.get("transfer-encoding"):
        raise BrowserPinnedTransportError("response_framing_ambiguous")
    grouped.pop("transfer-encoding", None)
    if method != "HEAD":
        grouped["content-length"] = [str(body_length)]
    elif "content-length" not in grouped:
        grouped["content-length"] = ["0"]
    result: list[tuple[str, str]] = []
    for name in sorted(grouped):
        result.append((name, ", ".join(grouped[name])))
    return tuple(result)


def _public_numeric(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    if not isinstance(value, str):
        raise BrowserPeerFulfillmentContractError(
            "connect_address must be a string"
        )
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise BrowserPeerFulfillmentContractError(
            "connect_address must be numeric"
        ) from exc
    if not address.is_global:
        raise BrowserPeerFulfillmentDenied(
            "connect_address must be globally routable"
        )
    return address


@dataclass(frozen=True)
class PreparedBrowserRequest:
    canonical_url: str
    scheme: Literal["http", "https"]
    host: str
    port: int
    method: Literal["GET", "HEAD"]
    request_bytes: bytes
    max_response_bytes: int
    pin_id: str
    schema: str = _TRANSPORT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != _TRANSPORT_SCHEMA:
            raise BrowserPeerFulfillmentContractError(
                "unsupported pinned transport schema"
            )
        if self.method not in _ALLOWED_METHODS:
            raise BrowserPeerFulfillmentContractError("method is invalid")
        if not isinstance(self.request_bytes, bytes) or not self.request_bytes:
            raise BrowserPeerFulfillmentContractError(
                "request_bytes must be non-empty bytes"
            )
        _response_limit(self.max_response_bytes)
        if not isinstance(self.pin_id, str) or not _PIN_ID.fullmatch(self.pin_id):
            raise BrowserPeerFulfillmentContractError("pin_id is invalid")


@dataclass(frozen=True)
class BrowserPinnedResponse:
    status: int
    reason: str
    headers: tuple[tuple[str, str], ...]
    body: bytes
    connected_address: str
    connected_port: int
    bytes_sent: int

    def __post_init__(self) -> None:
        if isinstance(self.status, bool) or not isinstance(self.status, int):
            raise BrowserPeerFulfillmentContractError("status is invalid")
        if not 100 <= self.status <= 599:
            raise BrowserPeerFulfillmentContractError("status is invalid")
        if not isinstance(self.reason, str):
            raise BrowserPeerFulfillmentContractError("reason is invalid")
        if not isinstance(self.body, bytes):
            raise BrowserPeerFulfillmentContractError("body must be bytes")
        address = _public_numeric(self.connected_address).compressed
        object.__setattr__(self, "connected_address", address)
        if (
            isinstance(self.connected_port, bool)
            or not isinstance(self.connected_port, int)
            or not 1 <= self.connected_port <= 65535
        ):
            raise BrowserPeerFulfillmentContractError(
                "connected_port is invalid"
            )
        if (
            isinstance(self.bytes_sent, bool)
            or not isinstance(self.bytes_sent, int)
            or self.bytes_sent < 0
        ):
            raise BrowserPeerFulfillmentContractError("bytes_sent is invalid")


class PinnedBrowserPeerTransport:
    """Single-use pin registry plus numeric-IP HTTP(S) transport."""

    def __init__(
        self,
        *,
        socket_factory: SocketFactory = socket.socket,
        ssl_context_factory: SSLContextFactory = ssl.create_default_context,
        response_factory: ResponseFactory = http.client.HTTPResponse,
        uuid_factory: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        self._socket_factory = socket_factory
        self._ssl_context_factory = ssl_context_factory
        self._response_factory = response_factory
        self._uuid_factory = uuid_factory
        self._lock = threading.RLock()
        self._pins: dict[str, BrowserPeerPinReceipt] = {}

    def pin(
        self,
        binding: ResearchPeerBinding,
        *,
        cdp_request_id: str,
        network_request_id: str,
    ) -> BrowserPeerPinReceipt:
        receipt = BrowserPeerPinReceipt(
            pin_id=f"bpp_{self._uuid_factory().hex}",
            binding_id=binding.binding_id,
            cdp_request_id=cdp_request_id,
            network_request_id=network_request_id,
            host=binding.host,
            port=binding.port,
            selected_address=binding.selected_address,
            expires_at=binding.expires_at,
        )
        with self._lock:
            if receipt.pin_id in self._pins:
                raise BrowserPeerFulfillmentDenied("transport pin id was reused")
            self._pins[receipt.pin_id] = receipt
        return receipt

    def release(self, receipt: BrowserPeerPinReceipt) -> None:
        if not isinstance(receipt, BrowserPeerPinReceipt):
            raise BrowserPeerFulfillmentContractError(
                "receipt must be a BrowserPeerPinReceipt"
            )
        with self._lock:
            current = self._pins.get(receipt.pin_id)
            if current != receipt:
                raise BrowserPeerFulfillmentDenied("transport pin is not active")
            del self._pins[receipt.pin_id]

    def _require_pin(self, receipt: BrowserPeerPinReceipt) -> None:
        with self._lock:
            if self._pins.get(receipt.pin_id) != receipt:
                raise BrowserPeerFulfillmentDenied("transport pin is not active")

    def prepare(
        self,
        receipt: BrowserPeerPinReceipt,
        *,
        url: str,
        method: str,
        headers: tuple[tuple[str, str], ...],
        max_response_bytes: int,
    ) -> PreparedBrowserRequest:
        self._require_pin(receipt)
        canonical, scheme, host, port, target, host_header = _canonical_target(url)
        normalized_method = method.upper() if isinstance(method, str) else ""
        if normalized_method not in _ALLOWED_METHODS:
            raise BrowserPeerFulfillmentDenied("transport method is forbidden")
        if host != receipt.host or port != receipt.port:
            raise BrowserPeerFulfillmentDenied(
                "transport target does not match the active pin"
            )
        clean_headers = _browser_headers(dict(headers))
        lines = [
            f"{normalized_method} {target} HTTP/1.1",
            f"Host: {host_header}",
            "Connection: close",
        ]
        lines.extend(f"{name}: {value}" for name, value in clean_headers)
        request_bytes = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")
        return PreparedBrowserRequest(
            canonical_url=canonical,
            scheme=scheme,
            host=host,
            port=port,
            method=normalized_method,
            request_bytes=request_bytes,
            max_response_bytes=_response_limit(max_response_bytes),
            pin_id=receipt.pin_id,
        )

    @staticmethod
    def _send(
        active_socket: socket.socket,
        payload: bytes,
    ) -> int:
        total = 0
        while total < len(payload):
            try:
                sent = active_socket.send(payload[total:])
            except Exception as exc:
                raise BrowserPinnedTransportError(
                    "request_send_failed",
                    bytes_sent=total,
                ) from exc
            if isinstance(sent, bool) or not isinstance(sent, int) or sent <= 0:
                raise BrowserPinnedTransportError(
                    "request_send_failed",
                    bytes_sent=total,
                )
            total += sent
        return total

    def execute(
        self,
        receipt: BrowserPeerPinReceipt,
        prepared: PreparedBrowserRequest,
        *,
        timeout_seconds: float,
    ) -> BrowserPinnedResponse:
        self._require_pin(receipt)
        if prepared.pin_id != receipt.pin_id:
            raise BrowserPeerFulfillmentDenied(
                "prepared request does not match the active pin"
            )
        if prepared.host != receipt.host or prepared.port != receipt.port:
            raise BrowserPeerFulfillmentDenied(
                "prepared target does not match the active pin"
            )
        timeout = _positive_float(timeout_seconds, "timeout_seconds", 900)
        numeric = _public_numeric(receipt.selected_address)
        family = socket.AF_INET6 if numeric.version == 6 else socket.AF_INET
        sockaddr = (
            (numeric.compressed, prepared.port, 0, 0)
            if family == socket.AF_INET6
            else (numeric.compressed, prepared.port)
        )
        raw_socket = active_socket = response = None
        bytes_sent = 0
        try:
            raw_socket = self._socket_factory(family, socket.SOCK_STREAM)
            raw_socket.settimeout(timeout)
            raw_socket.connect(sockaddr)
            active_socket = raw_socket
            if prepared.scheme == "https":
                context = self._ssl_context_factory()
                active_socket = context.wrap_socket(
                    raw_socket,
                    server_hostname=prepared.host,
                )
                active_socket.settimeout(timeout)
            peer_name = active_socket.getpeername()
            peer = _public_numeric(peer_name[0]).compressed
            peer_port = int(peer_name[1])
            if peer != receipt.selected_address or peer_port != receipt.port:
                raise BrowserPinnedTransportError("connected_peer_mismatch")
            bytes_sent = self._send(active_socket, prepared.request_bytes)
            response = self._response_factory(
                active_socket,
                method=prepared.method,
            )
            response.begin()
            body = bytearray()
            if prepared.method != "HEAD":
                while True:
                    remaining = prepared.max_response_bytes + 1 - len(body)
                    if remaining <= 0:
                        raise BrowserPinnedTransportError(
                            "response_body_too_large",
                            bytes_sent=bytes_sent,
                        )
                    chunk = response.read(min(_READ_CHUNK, remaining))
                    if not chunk:
                        break
                    body.extend(chunk)
                    if len(body) > prepared.max_response_bytes:
                        raise BrowserPinnedTransportError(
                            "response_body_too_large",
                            bytes_sent=bytes_sent,
                        )
            headers = _normalize_response_headers(
                response.getheaders(),
                method=prepared.method,
                body_length=len(body),
            )
            reason = str(getattr(response, "reason", "") or "")[:128]
            return BrowserPinnedResponse(
                status=response.status,
                reason=reason,
                headers=headers,
                body=bytes(body),
                connected_address=peer,
                connected_port=peer_port,
                bytes_sent=bytes_sent,
            )
        except BrowserPinnedTransportError as exc:
            if exc.bytes_sent == 0 and bytes_sent:
                exc.bytes_sent = bytes_sent
            raise
        except ssl.SSLCertVerificationError as exc:
            raise BrowserPinnedTransportError(
                "tls_certificate_failed",
                bytes_sent=bytes_sent,
            ) from exc
        except ssl.SSLError as exc:
            raise BrowserPinnedTransportError(
                "tls_handshake_failed",
                bytes_sent=bytes_sent,
            ) from exc
        except (socket.timeout, TimeoutError) as exc:
            raise BrowserPinnedTransportError(
                "transport_timeout",
                bytes_sent=bytes_sent,
            ) from exc
        except (http.client.HTTPException, ValueError) as exc:
            raise BrowserPinnedTransportError(
                "response_invalid",
                bytes_sent=bytes_sent,
            ) from exc
        except OSError as exc:
            raise BrowserPinnedTransportError(
                "transport_connection_failed",
                bytes_sent=bytes_sent,
            ) from exc
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


@dataclass(frozen=True)
class BrowserFulfillmentPayload:
    response_code: int
    response_phrase: str
    response_headers: tuple[tuple[str, str], ...]
    body: bytes
    connected_address: str
    connected_port: int
    bytes_sent: int
    schema: str = BROWSER_FULFILLMENT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != BROWSER_FULFILLMENT_SCHEMA:
            raise BrowserPeerFulfillmentContractError(
                "unsupported browser fulfillment schema"
            )
        BrowserPinnedResponse(
            status=self.response_code,
            reason=self.response_phrase,
            headers=self.response_headers,
            body=self.body,
            connected_address=self.connected_address,
            connected_port=self.connected_port,
            bytes_sent=self.bytes_sent,
        )

    def cdp_params(self, request_id: str) -> dict[str, Any]:
        if not isinstance(request_id, str) or not request_id:
            raise BrowserPeerFulfillmentContractError("request_id is invalid")
        return {
            "requestId": request_id,
            "responseCode": self.response_code,
            "responsePhrase": self.response_phrase,
            "responseHeaders": [
                {"name": name, "value": value}
                for name, value in self.response_headers
            ],
            "body": base64.b64encode(self.body).decode("ascii"),
        }

    def audit_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "response_code": self.response_code,
            "response_header_names": [name for name, _ in self.response_headers],
            "response_body_bytes": len(self.body),
            "connected_address": self.connected_address,
            "connected_port": self.connected_port,
            "bytes_sent": self.bytes_sent,
            "production_activation": False,
        }


class PendingBrowserFulfillment:
    """Fetched response waiting for explicit CDP fulfill success or failure."""

    def __init__(
        self,
        controller: "BrowserPeerFulfillmentController",
        permit: BrowserPeerPermit,
        payload: BrowserFulfillmentPayload,
        *,
        token: object,
    ) -> None:
        if token is not _PENDING_TOKEN:
            raise BrowserPeerFulfillmentContractError(
                "pending fulfillments must be created by the controller"
            )
        self.controller = controller
        self.permit = permit
        self.payload = payload
        self._lock = threading.Lock()
        self._terminal = False

    def cdp_params(self) -> dict[str, Any]:
        with self._lock:
            if self._terminal:
                raise BrowserPeerFulfillmentDenied(
                    "pending fulfillment is terminal"
                )
            return self.payload.cdp_params(self.permit.request_id)

    def commit(self, *, now: int) -> None:
        with self._lock:
            if self._terminal:
                raise BrowserPeerFulfillmentDenied(
                    "pending fulfillment is terminal"
                )
            self.controller._commit(self, now=_timestamp(now, "now"))
            self._terminal = True

    def abort(self, *, error_code: str, now: int) -> None:
        with self._lock:
            if self._terminal:
                raise BrowserPeerFulfillmentDenied(
                    "pending fulfillment is terminal"
                )
            try:
                self.controller._abort(
                    self,
                    error_code=error_code,
                    now=_timestamp(now, "now"),
                )
            finally:
                self._terminal = True


class BrowserPeerFulfillmentController:
    """Compose common peer claims with one aggregate outbound byte ceiling."""

    def __init__(
        self,
        adapter: BrowserPeerAdapter,
        transport: PinnedBrowserPeerTransport,
        evidence: DataSharingClaimEvidence,
        lease: ResearchSharingLease,
        intent: ResearchSharingIntent,
        *,
        timeout_seconds: float,
        max_response_bytes: int,
        clock: Clock = time.monotonic,
    ) -> None:
        if not isinstance(adapter, BrowserPeerAdapter):
            raise BrowserPeerFulfillmentContractError(
                "controller requires BrowserPeerAdapter"
            )
        if not isinstance(transport, PinnedBrowserPeerTransport):
            raise BrowserPeerFulfillmentContractError(
                "controller requires PinnedBrowserPeerTransport"
            )
        if not isinstance(evidence, DataSharingClaimEvidence):
            raise BrowserPeerFulfillmentContractError(
                "evidence must be DataSharingClaimEvidence"
            )
        if not isinstance(lease, ResearchSharingLease):
            raise BrowserPeerFulfillmentContractError(
                "lease must be ResearchSharingLease"
            )
        if not isinstance(intent, ResearchSharingIntent):
            raise BrowserPeerFulfillmentContractError(
                "intent must be ResearchSharingIntent"
            )
        if not callable(clock):
            raise BrowserPeerFulfillmentContractError("clock must be callable")
        self.adapter = adapter
        self.transport = transport
        self.evidence = evidence
        self.lease = lease
        self.intent = intent
        self.timeout_seconds = _positive_float(
            timeout_seconds,
            "timeout_seconds",
            900,
        )
        self.max_response_bytes = _response_limit(max_response_bytes)
        self.clock = clock
        self.meter = OutboundByteMeter(intent.to_request().max_bytes)
        self._lock = threading.RLock()

    @classmethod
    def create(
        cls,
        bridge: ResearchPeerAuthorizationBridge,
        ledger: ResearchPeerTransferLedger,
        evidence: DataSharingClaimEvidence,
        lease: ResearchSharingLease,
        intent: ResearchSharingIntent,
        *,
        timeout_seconds: float,
        max_response_bytes: int,
        transport: PinnedBrowserPeerTransport | None = None,
        clock: Clock = time.monotonic,
    ) -> "BrowserPeerFulfillmentController":
        active_transport = transport or PinnedBrowserPeerTransport()
        adapter = BrowserPeerAdapter(bridge, ledger, active_transport)
        return cls(
            adapter,
            active_transport,
            evidence,
            lease,
            intent,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            clock=clock,
        )

    @property
    def bytes_sent(self) -> int:
        return self.meter.bytes_sent

    def _record_actual(self, permit: BrowserPeerPermit, count: int) -> None:
        if count == 0:
            return
        self.meter.record_sent(count)
        permit.record_sent(count)

    def prepare(
        self,
        event: Any,
        *,
        now: int,
        ttl_seconds: int = 30,
    ) -> PendingBrowserFulfillment:
        timestamp = _timestamp(now, "now")
        request_id, network_id, method, headers = _event_request(event)
        permit = self.adapter.prepare_request(
            event,
            self.evidence,
            self.lease,
            self.intent,
            now=timestamp,
            ttl_seconds=ttl_seconds,
        )
        if permit.request_id != request_id or permit.network_id != network_id:
            try:
                self.adapter.abort_request(
                    permit,
                    self.evidence,
                    self.lease,
                    self.intent,
                    error_code="request_correlation_mismatch",
                    now=timestamp,
                )
            except BrowserPeerAdapterDenied:
                pass
            raise BrowserPeerFulfillmentDenied(
                "request correlation changed during preparation"
            )
        prepared = self.transport.prepare(
            permit.pin,
            url=permit._canonical_url,
            method=method,
            headers=headers,
            max_response_bytes=self.max_response_bytes,
        )
        with self._lock:
            remaining = self.meter.max_bytes - self.meter.bytes_sent
            if len(prepared.request_bytes) > remaining:
                try:
                    self.adapter.abort_request(
                        permit,
                        self.evidence,
                        self.lease,
                        self.intent,
                        error_code="byte_budget_exceeded",
                        now=timestamp,
                    )
                except BrowserPeerAdapterDenied:
                    pass
                raise BrowserPeerFulfillmentDenied(
                    "aggregate outbound byte ceiling would be exceeded"
                )
            try:
                response = self.transport.execute(
                    permit.pin,
                    prepared,
                    timeout_seconds=self.timeout_seconds,
                )
            except BrowserPinnedTransportError as exc:
                try:
                    self._record_actual(permit, exc.bytes_sent)
                except ResearchExternalBlocked:
                    pass
                try:
                    self.adapter.abort_request(
                        permit,
                        self.evidence,
                        self.lease,
                        self.intent,
                        error_code=exc.error_code,
                        now=timestamp,
                    )
                except BrowserPeerAdapterDenied:
                    pass
                raise BrowserPeerFulfillmentDenied(exc.error_code) from exc
            try:
                self._record_actual(permit, response.bytes_sent)
            except ResearchExternalBlocked as exc:
                try:
                    self.adapter.abort_request(
                        permit,
                        self.evidence,
                        self.lease,
                        self.intent,
                        error_code="byte_budget_exceeded",
                        now=timestamp,
                    )
                except BrowserPeerAdapterDenied:
                    pass
                raise BrowserPeerFulfillmentDenied(
                    "aggregate outbound byte ceiling was exceeded"
                ) from exc
        payload = BrowserFulfillmentPayload(
            response_code=response.status,
            response_phrase=response.reason,
            response_headers=response.headers,
            body=response.body,
            connected_address=response.connected_address,
            connected_port=response.connected_port,
            bytes_sent=response.bytes_sent,
        )
        return PendingBrowserFulfillment(
            self,
            permit,
            payload,
            token=_PENDING_TOKEN,
        )

    def _commit(self, pending: PendingBrowserFulfillment, *, now: int) -> None:
        self.adapter.complete_response(
            pending.permit,
            {
                "requestId": pending.permit.network_id,
                "response": {
                    "url": pending.permit._canonical_url,
                    "remoteIPAddress": pending.payload.connected_address,
                    "remotePort": pending.payload.connected_port,
                    "fromDiskCache": False,
                    "fromServiceWorker": False,
                    "fromPrefetchCache": False,
                },
            },
            self.evidence,
            self.lease,
            self.intent,
            now=now,
        )

    def _abort(
        self,
        pending: PendingBrowserFulfillment,
        *,
        error_code: str,
        now: int,
    ) -> None:
        self.adapter.abort_request(
            pending.permit,
            self.evidence,
            self.lease,
            self.intent,
            error_code=error_code,
            now=now,
        )


__all__ = [
    "BROWSER_FULFILLMENT_SCHEMA",
    "BrowserFulfillmentPayload",
    "BrowserPeerFulfillmentContractError",
    "BrowserPeerFulfillmentController",
    "BrowserPeerFulfillmentDenied",
    "BrowserPinnedResponse",
    "BrowserPinnedTransportError",
    "PendingBrowserFulfillment",
    "PinnedBrowserPeerTransport",
    "PreparedBrowserRequest",
]
