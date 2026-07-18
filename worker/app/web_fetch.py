"""Deterministic read-only web retrieval under the research contract.

This module owns navigation mechanics, not network access. A production transport
is injected later; tests use an in-memory transport. Keeping the transport seam
explicit makes redirects, DNS pinning, byte limits and receipts testable without
granting CI or the worker live network access.
"""
from __future__ import annotations

import ipaddress
import re
import socket
import time
import zlib
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable, Mapping, Protocol, Sequence
from urllib.parse import urljoin, urlsplit

from .research_contract import (
    ReadOnlyBrowserPolicy,
    ResearchContractError,
    SourceReceipt,
)

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_ALLOWED_MEDIA_TYPES = frozenset({
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "application/json",
})
_MAX_REDIRECTS = 5
_USER_AGENT = "ModelRig-WebFetch/1.0"
_WS_RE = re.compile(r"\s+")


class WebFetchError(RuntimeError):
    """Retrieval failed without producing a trustworthy source receipt."""


@dataclass(frozen=True)
class TransportResponse:
    """One non-following HTTP response from an injected transport.

    ``body`` is the entity body after transfer framing but before content
    decoding. ``connected_address`` is the exact peer IP used for the socket;
    the adapter rejects a response that does not match the address selected
    from its validated DNS answers.
    """

    status: int
    headers: Mapping[str, str]
    body: bytes
    connected_address: str

    def __post_init__(self) -> None:
        if not isinstance(self.status, int) or not 100 <= self.status <= 599:
            raise ValueError("status must be an HTTP status code")
        if not isinstance(self.body, bytes):
            raise TypeError("body must be bytes")
        try:
            normalized = ipaddress.ip_address(self.connected_address).compressed
        except ValueError as exc:
            raise ValueError("connected_address must be an IP address") from exc
        object.__setattr__(self, "connected_address", normalized)
        clean_headers: dict[str, str] = {}
        for name, value in self.headers.items():
            if not isinstance(name, str) or not isinstance(value, str):
                raise TypeError("headers must be string pairs")
            clean_headers[name.strip().lower()] = value.strip()
        object.__setattr__(self, "headers", clean_headers)


class FetchTransport(Protocol):
    """Transport that must not follow redirects or change the selected peer."""

    def request(
        self,
        url: str,
        *,
        connect_address: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_wire_bytes: int,
    ) -> TransportResponse:
        ...


Resolver = Callable[[str, int], Sequence[str]]
Clock = Callable[[], float]


@dataclass(frozen=True)
class FetchTrace:
    """Auditable mechanics for one deterministic fetch."""

    requested_url: str
    final_url: str
    visited_urls: tuple[str, ...]
    resolved_addresses: tuple[tuple[str, tuple[str, ...]], ...]
    receipt: SourceReceipt

    def to_dict(self) -> dict:
        return {
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "visited_urls": list(self.visited_urls),
            "resolved_addresses": [
                {"url": url, "addresses": list(addresses)}
                for url, addresses in self.resolved_addresses
            ],
            "receipt": self.receipt.to_dict(),
        }


class _ReadableHTML(HTMLParser):
    _SKIP = frozenset({"script", "style", "noscript", "template", "svg"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        lower = tag.lower()
        if lower in self._SKIP:
            self._skip_depth += 1
        elif lower == "title" and self._skip_depth == 0:
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif lower == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        self.text_parts.append(data)


def default_resolver(host: str, port: int) -> tuple[str, ...]:
    """Resolve all TCP addresses without opening a connection."""

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise WebFetchError("DNS resolution failed") from exc
    addresses = tuple(dict.fromkeys(info[4][0] for info in infos))
    if not addresses:
        raise WebFetchError("DNS resolution returned no addresses")
    return addresses


def _header(response: TransportResponse, name: str) -> str:
    return response.headers.get(name.lower(), "")


def _media_type_and_charset(content_type: str) -> tuple[str, str]:
    parts = [part.strip() for part in content_type.split(";")]
    media_type = (parts[0] or "application/octet-stream").lower()
    charset = "utf-8"
    for part in parts[1:]:
        if part.lower().startswith("charset="):
            charset = part.split("=", 1)[1].strip().strip("\"'").lower()
    return media_type, charset


def _inflate_bounded(body: bytes, *, wbits: int, limit: int) -> bytes:
    """Decompress without ever materializing more than ``limit + 1`` bytes."""

    decoder = zlib.decompressobj(wbits)
    output = bytearray()
    try:
        for offset in range(0, len(body), 64 * 1024):
            pending = body[offset: offset + 64 * 1024]
            while pending:
                remaining = limit + 1 - len(output)
                if remaining <= 0:
                    raise WebFetchError("decoded source exceeds max_source_bytes")
                output.extend(decoder.decompress(pending, remaining))
                if len(output) > limit:
                    raise WebFetchError("decoded source exceeds max_source_bytes")
                pending = decoder.unconsumed_tail
        remaining = limit + 1 - len(output)
        if remaining <= 0 and not decoder.eof:
            raise WebFetchError("decoded source exceeds max_source_bytes")
        output.extend(decoder.flush(max(1, remaining)))
    except zlib.error as exc:
        raise WebFetchError("invalid compressed response") from exc
    if len(output) > limit:
        raise WebFetchError("decoded source exceeds max_source_bytes")
    if not decoder.eof or decoder.unused_data:
        raise WebFetchError("invalid compressed response")
    return bytes(output)


def _bounded_decompress(body: bytes, encoding: str, limit: int) -> bytes:
    normalized = encoding.strip().lower()
    if not normalized or normalized == "identity":
        if len(body) > limit:
            raise WebFetchError("source exceeds max_source_bytes")
        return body
    if normalized == "gzip":
        return _inflate_bounded(body, wbits=zlib.MAX_WBITS | 16, limit=limit)
    if normalized == "deflate":
        return _inflate_bounded(body, wbits=zlib.MAX_WBITS, limit=limit)
    raise WebFetchError("unsupported content encoding")


def _decode_text(body: bytes, charset: str) -> str:
    try:
        return body.decode(charset, errors="replace")
    except LookupError as exc:
        raise WebFetchError("unsupported response charset") from exc


def _fallback_title(url: str) -> str:
    parsed = urlsplit(url)
    tail = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    return tail or parsed.hostname or "Web source"


def _extract_title_excerpt(url: str, body: bytes, media_type: str, charset: str) -> tuple[str, str]:
    text = _decode_text(body, charset)
    if media_type in {"text/html", "application/xhtml+xml"}:
        parser = _ReadableHTML()
        try:
            parser.feed(text)
            parser.close()
        except Exception as exc:
            raise WebFetchError("HTML parsing failed") from exc
        title = _WS_RE.sub(" ", " ".join(parser.title_parts)).strip() or _fallback_title(url)
        readable = _WS_RE.sub(" ", " ".join(parser.text_parts)).strip()
    else:
        title = _fallback_title(url)
        readable = _WS_RE.sub(" ", text).strip()
    if not readable:
        raise WebFetchError("source contained no readable text")
    return title[:500], readable[:2_000]


class DeterministicWebFetcher:
    """Fetch one public, allowlisted source and return its receipt plus trace."""

    def __init__(
        self,
        transport: FetchTransport,
        *,
        resolver: Resolver = default_resolver,
        clock: Clock = time.monotonic,
        max_redirects: int = _MAX_REDIRECTS,
    ) -> None:
        if not isinstance(max_redirects, int) or not 0 <= max_redirects <= _MAX_REDIRECTS:
            raise ValueError(f"max_redirects must be between 0 and {_MAX_REDIRECTS}")
        self._transport = transport
        self._resolver = resolver
        self._clock = clock
        self._max_redirects = max_redirects

    def fetch(self, url: str, policy: ReadOnlyBrowserPolicy) -> FetchTrace:
        requested = policy.require_allowed_url(url)
        current = requested
        visited: list[str] = []
        resolution_trace: list[tuple[str, tuple[str, ...]]] = []
        deadline = self._clock() + policy.timeout_seconds

        for attempt in range(self._max_redirects + 1):
            if len(visited) >= policy.max_steps:
                raise WebFetchError("research step budget exhausted")
            if current in visited:
                raise WebFetchError("redirect loop detected")
            visited.append(current)

            remaining = deadline - self._clock()
            if remaining <= 0:
                raise WebFetchError("research timeout exhausted")

            parsed = urlsplit(current)
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            try:
                raw_addresses = tuple(self._resolver(parsed.hostname or "", port))
            except ResearchContractError:
                raise
            except WebFetchError:
                raise
            except Exception as exc:
                raise WebFetchError("DNS resolution failed") from exc
            if not raw_addresses:
                raise WebFetchError("DNS resolution returned no addresses")

            public: list[str] = []
            for address in raw_addresses:
                try:
                    normalized = policy.require_public_address(address)
                except ResearchContractError as exc:
                    raise WebFetchError("DNS resolved to a non-public address") from exc
                if normalized not in public:
                    public.append(normalized)
            public.sort(
                key=lambda value: (
                    ipaddress.ip_address(value).version,
                    ipaddress.ip_address(value).packed,
                )
            )
            addresses = tuple(public)
            selected = addresses[0]
            resolution_trace.append((current, addresses))

            request_headers = {
                "accept": "text/html, application/xhtml+xml, text/plain, application/json",
                "accept-encoding": "gzip, deflate, identity",
                "user-agent": _USER_AGENT,
            }
            try:
                response = self._transport.request(
                    current,
                    connect_address=selected,
                    headers=request_headers,
                    timeout_seconds=max(0.001, remaining),
                    max_wire_bytes=policy.max_source_bytes + 1,
                )
            except WebFetchError:
                raise
            except Exception as exc:
                raise WebFetchError("transport request failed") from exc

            if len(response.body) > policy.max_source_bytes + 1:
                raise WebFetchError("transport exceeded max_wire_bytes")

            try:
                connected = policy.require_public_address(response.connected_address)
            except ResearchContractError as exc:
                raise WebFetchError("transport connected to a non-public peer") from exc
            if connected != selected:
                raise WebFetchError("transport peer did not match the validated DNS address")
            if self._clock() > deadline:
                raise WebFetchError("research timeout exhausted")

            if response.status in _REDIRECT_STATUSES:
                location = _header(response, "location")
                if not location:
                    raise WebFetchError("redirect response omitted Location")
                if attempt >= self._max_redirects:
                    raise WebFetchError("redirect budget exhausted")
                target = policy.require_allowed_url(urljoin(current, location))
                if urlsplit(current).scheme == "https" and urlsplit(target).scheme != "https":
                    raise WebFetchError("HTTPS redirect downgrade is forbidden")
                current = target
                continue

            if response.status != 200:
                raise WebFetchError(f"unexpected HTTP status {response.status}")

            disposition = _header(response, "content-disposition").lower()
            if "attachment" in disposition:
                raise WebFetchError("download responses are forbidden")

            media_type, charset = _media_type_and_charset(_header(response, "content-type"))
            if media_type not in _ALLOWED_MEDIA_TYPES:
                raise WebFetchError(f"unsupported media type: {media_type}")

            length = _header(response, "content-length")
            if length:
                try:
                    declared_length = int(length)
                except ValueError as exc:
                    raise WebFetchError("invalid Content-Length") from exc
                if declared_length < 0:
                    raise WebFetchError("invalid Content-Length")
                if not _header(response, "content-encoding") and declared_length > policy.max_source_bytes:
                    raise WebFetchError("source exceeds max_source_bytes")

            decoded = _bounded_decompress(
                response.body,
                _header(response, "content-encoding"),
                policy.max_source_bytes,
            )
            title, excerpt = _extract_title_excerpt(current, decoded, media_type, charset)
            receipt = SourceReceipt.from_content(
                url=current,
                title=title,
                content=decoded,
                excerpt=excerpt,
                media_type=media_type,
                adapter="deterministic-web-fetch",
            )
            policy.accept_receipt(receipt)
            return FetchTrace(
                requested_url=requested,
                final_url=current,
                visited_urls=tuple(visited),
                resolved_addresses=tuple(resolution_trace),
                receipt=receipt,
            )

        raise WebFetchError("redirect budget exhausted")
