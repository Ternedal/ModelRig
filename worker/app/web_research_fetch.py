"""One ToolGate web fetch with a verified source receipt (T-034, D7 step 2).

The production caller is ``web_research_tool.py`` behind the existing
``KALIV_WEB_RESEARCH_ENABLED`` + ToolGate confirmation boundary. This module
owns one direct, pinned GET after that confirmation; it does not create a
second route, retry, browser session or background worker.

D7 step 2 closes the old evidence asymmetry without pretending the direct tool
has a Chromium/CDP commit point. The pinned network response is re-verified
*in memory* through the same ``DeterministicWebFetcher`` / ``SourceReceipt``
contract used by citation-producing research. That verifier opens no second
socket: its transport is the response already returned by the exact selected
peer. Redirects are fail-closed here (``max_redirects=0``), so one human
confirmation still authorizes exactly one outbound request.

Lifecycle order remains:

    intent   = build_intent(url, purpose)
    lease    = boundary.prepare(intent)
    evidence = boundary.claim(lease, intent)
    auth     = bridge.prepare(evidence, lease, intent, url)
    binding  = peer.issue(auth, evidence, lease, intent, url)
    pin      = transport.pin(binding, ...)
    prepared = transport.prepare(pin, url, "GET", (), max_response_bytes)
    response = transport.execute(pin, prepared, timeout)
    receipt  = deterministic in-memory verification of that SAME response
    boundary.complete(lease, intent, outcome=..., bytes_sent=...)

``complete()`` is in ``finally``. Unknown failures remain ``failed``; our own
contract/policy denials are ``blocked``. The direct tool never follows a
redirect or silently retries because either would be a second external request
under one approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .browser_peer_fulfillment import BrowserPinnedTransportError
from .research_contract import ReadOnlyBrowserPolicy, SourceReceipt, canonicalize_url
from .research_data_sharing import ResearchSharingIntent
from .web_fetch import DeterministicWebFetcher, TransportResponse, WebFetchError
from .web_research_intent import WebResearchIntentError, build_intent

#: An upper bound, not an expectation. The intent owns the response byte cap.
DEFAULT_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class WebResearchResult:
    """Verified result returned to the ToolGate caller.

    ``body`` is retained for compatibility/debugging inside this process, but
    callers should expose ``source_receipt`` / its verified excerpt rather than
    treating undecoded wire bytes as citation text.
    """

    url: str
    status: int
    body: bytes
    bytes_received: int
    binding_id: str
    selected_address: str
    resolved_addresses: tuple[str, ...]
    source_receipt: SourceReceipt


class _CommittedPinnedResponseTransport:
    """Replay exactly one already-fetched response into the source verifier.

    This object has no socket/resolver capability. It exists to reuse the
    deterministic content/media/receipt checks without performing a second
    network request just to make a citation.
    """

    def __init__(self, *, url: str, selected_address: str, response: Any) -> None:
        self._url = canonicalize_url(url)
        self._selected = selected_address
        self._response = response
        self.calls = 0

    def request(
        self,
        url: str,
        *,
        connect_address: str,
        headers,
        timeout_seconds: float,
        max_wire_bytes: int,
    ) -> TransportResponse:
        del headers, timeout_seconds
        self.calls += 1
        canonical = canonicalize_url(url)
        if self.calls != 1:
            raise WebFetchError("committed response is one-use")
        if canonical != self._url:
            raise WebFetchError("committed response URL changed")
        if connect_address != self._selected:
            raise WebFetchError("committed response peer changed")
        body = getattr(self._response, "body", None)
        if not isinstance(body, bytes):
            raise WebFetchError("committed response body is invalid")
        if len(body) > max_wire_bytes:
            raise WebFetchError("committed response exceeds verifier wire budget")
        connected = getattr(self._response, "connected_address", None)
        if connected != self._selected:
            raise WebFetchError("committed response connected peer changed")
        raw_headers = getattr(self._response, "headers", ())
        try:
            response_headers = dict(raw_headers)
        except (TypeError, ValueError) as exc:
            raise WebFetchError("committed response headers are invalid") from exc
        return TransportResponse(
            status=int(getattr(self._response, "status", 0)),
            headers=response_headers,
            body=body,
            connected_address=connected,
        )


def _outcome_for(exc: BaseException) -> tuple[str, str]:
    """Translate an exception to ``(outcome, error_code)`` after D7 no. 3."""
    name = type(exc).__name__
    # Our own denials first, by name. BrowserPeerAdapterDenied inherits from
    # PermissionError/OSError; type-first classification would stamp our SSRF
    # refusal as a peer failure.
    if isinstance(exc, (WebResearchIntentError, WebFetchError)):
        return "blocked", name
    if name.endswith("Denied") or name.endswith("ContractError"):
        return "blocked", name
    if isinstance(exc, (BrowserPinnedTransportError, OSError, TimeoutError)):
        return "failed", name
    return "failed", name


class WebResearchFetcher:
    """Orchestrate one pinned GET and emit one verified source receipt."""

    def __init__(
        self,
        *,
        boundary: Any,
        bridge: Any,
        peer_ledger: Any,
        transport: Any,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        id_factory: Callable[[str], str] | None = None,
        receipt_ttl_seconds: int = 120,
        binding_ttl_seconds: int = 30,
    ) -> None:
        self._boundary = boundary
        self._bridge = bridge
        self._peer = peer_ledger
        self._transport = transport
        self._timeout = float(timeout_seconds)
        self._ids = id_factory or (lambda prefix: f"{prefix}-1")
        self._receipt_ttl = int(receipt_ttl_seconds)
        self._binding_ttl = int(binding_ttl_seconds)

    def _verify_source(
        self,
        *,
        target: str,
        intent: ResearchSharingIntent,
        binding: Any,
        response: Any,
    ) -> SourceReceipt:
        addresses = tuple(getattr(binding, "addresses", ()) or ())
        selected = getattr(binding, "selected_address", None)
        if not isinstance(selected, str) or not selected:
            raise WebFetchError("peer binding has no selected address")
        if selected not in addresses:
            raise WebFetchError("selected peer is absent from DNS binding")

        # Direct ToolGate v1 is exactly one approved outbound request. We use
        # the deterministic verifier with max_redirects=0 over an in-memory
        # replay of that response: content/status/media/peer/source receipt are
        # checked without a second socket.
        policy = ReadOnlyBrowserPolicy(
            allowed_domains=tuple(intent.plan.allowed_domains),
            max_steps=1,
            max_pages=1,
            timeout_seconds=max(1, min(300, int(self._timeout))),
            max_source_bytes=int(intent.plan.max_bytes),
        )
        replay = _CommittedPinnedResponseTransport(
            url=target,
            selected_address=selected,
            response=response,
        )
        trace = DeterministicWebFetcher(
            replay,
            resolver=lambda _host, _port: (selected,),
            max_redirects=0,
        ).fetch(target, policy)
        if replay.calls != 1:
            raise WebFetchError("source verification did not use exactly one in-memory response")
        return trace.receipt

    def fetch(
        self,
        url: str,
        *,
        purpose: str,
        max_bytes: int | None = None,
        now: int | None = None,
    ) -> WebResearchResult:
        # Intent is built before a lease. An illegal URL therefore creates no
        # authorization state and nothing needs cleanup.
        kwargs = {} if max_bytes is None else {"max_bytes": max_bytes}
        intent: ResearchSharingIntent = build_intent(url, purpose=purpose, **kwargs)
        target = intent.plan.destination_url if hasattr(intent.plan, "destination_url") else None
        target = target or _target_from(intent, url)

        lease = self._boundary.prepare(
            intent, now=now, receipt_ttl_seconds=self._receipt_ttl
        )

        outcome = "failed"
        error_code: str | None = "unfinished"
        bytes_sent = 0
        pin = None
        try:
            evidence = self._boundary.claim(lease, intent, now=now)
            authorization = self._bridge.prepare(evidence, lease, intent, target, now=now)
            binding = self._peer.issue(
                authorization,
                evidence,
                lease,
                intent,
                target,
                now=now,
                ttl_seconds=self._binding_ttl,
            )
            pin = self._transport.pin(
                binding,
                cdp_request_id=self._ids("direct"),
                network_request_id=self._ids("net"),
            )
            prepared = self._transport.prepare(
                pin,
                url=target,
                method="GET",
                headers=(),
                max_response_bytes=intent.plan.max_bytes,
            )
            response = self._transport.execute(
                pin, prepared, timeout_seconds=self._timeout
            )
            # Bytes have already left the machine even if verification below
            # rejects the response. Audit must record that truth.
            bytes_sent = int(response.bytes_sent)
            receipt = self._verify_source(
                target=target,
                intent=intent,
                binding=binding,
                response=response,
            )
            outcome, error_code = "completed", None
            return WebResearchResult(
                url=target,
                status=int(response.status),
                body=response.body,
                bytes_received=len(response.body),
                binding_id=binding.binding_id,
                selected_address=binding.selected_address,
                resolved_addresses=tuple(binding.addresses),
                source_receipt=receipt,
            )
        except BaseException as exc:  # noqa: BLE001 - outcome must cover every path
            outcome, error_code = _outcome_for(exc)
            raise
        finally:
            if pin is not None:
                try:
                    self._transport.release(pin)
                except Exception:  # noqa: BLE001
                    pass
            self._boundary.complete(
                lease,
                intent,
                outcome=outcome,
                bytes_sent=bytes_sent,
                error_code=error_code,
                now=now,
            )


def _target_from(intent: ResearchSharingIntent, fallback: str) -> str:
    """Read the canonical URL from the intent summary if the plan lacks it."""
    summary = getattr(intent, "summary", "") or ""
    for token in summary.split():
        if token.startswith("https://"):
            return token
    return fallback
