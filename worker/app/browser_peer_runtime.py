"""Dormant claim-bound Browser Use composition and verified response evidence.

The existing Browser Use adapter historically re-fetched every cited URL through a
separate deterministic fetcher. Once browser navigation is fulfilled by ModelRig's
pinned transport, a second public request would be both unnecessary and a separate
egress path. This module instead captures the exact response bytes that ModelRig
fetched and successfully delivered through ``Fetch.fulfillRequest``. The committed,
bounded in-memory evidence store implements the adapter's ``VerifiedFetcher`` seam.

No BrowserHost, ToolGate, API route or active Browser Use factory imports this
module. Constructing a runtime opens no socket. Public traffic remains possible only
when an injected caller later starts Browser Use with an already-claimed common
receipt and the pinned fulfillment controller from the preceding slices.
"""
from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable

from .browser_peer_fulfillment import (
    BrowserFulfillmentPayload,
    BrowserPeerFulfillmentController,
    BrowserPeerFulfillmentDenied,
    PendingBrowserFulfillment,
)
from .browser_use_adapter import (
    BindingsLoader,
    BrowserUseBackend,
    LlmFactory,
    load_browser_use_bindings,
)
from .browser_use_network_guard import (
    BrowserUseNetworkGuard,
    BrowserUseNetworkGuardError,
)
from .research_contract import (
    ReadOnlyBrowserPolicy,
    ResearchContractError,
    canonicalize_url,
)
from .research_data_sharing import ResearchSharingIntent
from .web_fetch import (
    DeterministicWebFetcher,
    FetchTrace,
    TransportResponse,
    WebFetchError,
)

BROWSER_PEER_RUNTIME_SCHEMA = "kaliv-browser-peer-runtime/v1"
_MAX_EVIDENCE_BYTES = 100_000_000
_MAX_EVIDENCE_RESPONSES = 1_000
_ERROR_CODE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_EVIDENCE_TOKEN = object()


class BrowserPeerRuntimeContractError(ValueError):
    """The runtime, evidence budget or injected dependency is malformed."""


class BrowserPeerRuntimeDenied(PermissionError):
    """Evidence storage or claim-bound runtime composition was refused."""


def _positive_int(value: int, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BrowserPeerRuntimeContractError(f"{name} must be an integer")
    if not 1 <= value <= maximum:
        raise BrowserPeerRuntimeContractError(
            f"{name} must be between 1 and {maximum}"
        )
    return value


def _error_code(value: str) -> str:
    if not isinstance(value, str) or not _ERROR_CODE.fullmatch(value):
        raise BrowserPeerRuntimeContractError("error_code is invalid")
    return value


def _canonical(value: str) -> str:
    if not isinstance(value, str):
        raise BrowserPeerRuntimeContractError("URL must be a string")
    try:
        return canonicalize_url(value)
    except ResearchContractError as exc:
        raise BrowserPeerRuntimeDenied("URL is outside the web contract") from exc


@dataclass(frozen=True)
class CommittedBrowserEvidence:
    canonical_url: str
    status: int
    reason: str
    headers: tuple[tuple[str, str], ...]
    body: bytes
    addresses: tuple[str, ...]
    selected_address: str
    connected_address: str
    connected_port: int
    bytes_sent: int
    schema: str = BROWSER_PEER_RUNTIME_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != BROWSER_PEER_RUNTIME_SCHEMA:
            raise BrowserPeerRuntimeContractError(
                "unsupported browser peer runtime schema"
            )
        canonical = _canonical(self.canonical_url)
        object.__setattr__(self, "canonical_url", canonical)
        BrowserFulfillmentPayload(
            response_code=self.status,
            response_phrase=self.reason,
            response_headers=self.headers,
            body=self.body,
            connected_address=self.connected_address,
            connected_port=self.connected_port,
            bytes_sent=self.bytes_sent,
        )
        if not isinstance(self.addresses, tuple) or not self.addresses:
            raise BrowserPeerRuntimeContractError(
                "evidence addresses must be a non-empty tuple"
            )
        if self.selected_address not in self.addresses:
            raise BrowserPeerRuntimeContractError(
                "selected_address must be present in evidence addresses"
            )
        if self.connected_address != self.selected_address:
            raise BrowserPeerRuntimeContractError(
                "committed evidence peer must equal selected address"
            )

    @property
    def url_sha256(self) -> str:
        return hashlib.sha256(self.canonical_url.encode("utf-8")).hexdigest()

    @property
    def body_sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()

    def audit_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "url_sha256": self.url_sha256,
            "status": self.status,
            "response_body_bytes": len(self.body),
            "response_body_sha256": self.body_sha256,
            "selected_address": self.selected_address,
            "connected_port": self.connected_port,
            "bytes_sent": self.bytes_sent,
            "production_activation": False,
        }


class _CommittedResponseTransport:
    def __init__(self, evidence: CommittedBrowserEvidence) -> None:
        self.evidence = evidence

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
        try:
            canonical = canonicalize_url(url)
        except ResearchContractError as exc:
            raise WebFetchError("stored evidence URL is invalid") from exc
        if canonical != self.evidence.canonical_url:
            raise WebFetchError("stored evidence URL does not match request")
        if connect_address != self.evidence.selected_address:
            raise WebFetchError("stored evidence peer does not match request")
        if len(self.evidence.body) > max_wire_bytes:
            raise WebFetchError("stored evidence exceeds max_wire_bytes")
        return TransportResponse(
            status=self.evidence.status,
            headers=dict(self.evidence.headers),
            body=self.evidence.body,
            connected_address=self.evidence.connected_address,
        )


class ClaimBoundEvidencePending:
    """Reservation wrapper that stores evidence only after CDP commit succeeds."""

    def __init__(
        self,
        owner: "ClaimBoundBrowserEvidence",
        pending: PendingBrowserFulfillment,
        canonical_url: str,
        reserved_bytes: int,
        *,
        token: object,
    ) -> None:
        if token is not _EVIDENCE_TOKEN:
            raise BrowserPeerRuntimeContractError(
                "claim-bound evidence pending objects cannot be forged"
            )
        self.owner = owner
        self.pending = pending
        self.canonical_url = canonical_url
        self.reserved_bytes = reserved_bytes
        self._lock = threading.Lock()
        self._terminal = False

    @property
    def payload(self) -> BrowserFulfillmentPayload:
        return self.pending.payload

    @property
    def permit(self):
        return self.pending.permit

    def cdp_params(self) -> dict[str, Any]:
        with self._lock:
            if self._terminal:
                raise BrowserPeerRuntimeDenied("evidence pending object is terminal")
            return self.pending.cdp_params()

    def commit(self, *, now: int) -> None:
        with self._lock:
            if self._terminal:
                raise BrowserPeerRuntimeDenied("evidence pending object is terminal")
            try:
                self.pending.commit(now=now)
            except Exception:
                self.owner._release(self.canonical_url, self.reserved_bytes)
                self._terminal = True
                raise
            self.owner._store(self)
            self._terminal = True

    def abort(self, *, error_code: str, now: int) -> None:
        with self._lock:
            if self._terminal:
                raise BrowserPeerRuntimeDenied("evidence pending object is terminal")
            code = _error_code(error_code)
            try:
                self.pending.abort(error_code=code, now=now)
            finally:
                self.owner._release(self.canonical_url, self.reserved_bytes)
                self._terminal = True


class ClaimBoundBrowserEvidence:
    """Bounded committed-response store and BrowserUse VerifiedFetcher seam."""

    def __init__(
        self,
        controller: BrowserPeerFulfillmentController,
        *,
        max_evidence_bytes: int,
        max_evidence_responses: int,
    ) -> None:
        if not isinstance(controller, BrowserPeerFulfillmentController):
            raise BrowserPeerRuntimeContractError(
                "evidence store requires BrowserPeerFulfillmentController"
            )
        self.controller = controller
        self.max_evidence_bytes = _positive_int(
            max_evidence_bytes,
            "max_evidence_bytes",
            _MAX_EVIDENCE_BYTES,
        )
        self.max_evidence_responses = _positive_int(
            max_evidence_responses,
            "max_evidence_responses",
            _MAX_EVIDENCE_RESPONSES,
        )
        self._lock = threading.RLock()
        self._reserved_bytes = 0
        self._reserved_urls: set[str] = set()
        self._records: dict[str, CommittedBrowserEvidence] = {}
        self._committed_bytes = 0
        self._closed = False

    @property
    def intent(self) -> ResearchSharingIntent:
        return self.controller.intent

    @property
    def bytes_sent(self) -> int:
        return self.controller.bytes_sent

    def _reserve(self, canonical_url: str, body_bytes: int) -> None:
        with self._lock:
            if self._closed:
                raise BrowserPeerRuntimeDenied("evidence store is closed")
            if canonical_url in self._records or canonical_url in self._reserved_urls:
                raise BrowserPeerRuntimeDenied(
                    "exact URL already has claim-bound evidence"
                )
            if len(self._records) + len(self._reserved_urls) >= self.max_evidence_responses:
                raise BrowserPeerRuntimeDenied("evidence response budget exceeded")
            if self._committed_bytes + self._reserved_bytes + body_bytes > self.max_evidence_bytes:
                raise BrowserPeerRuntimeDenied("evidence byte budget exceeded")
            self._reserved_urls.add(canonical_url)
            self._reserved_bytes += body_bytes

    def _release(self, canonical_url: str, body_bytes: int) -> None:
        with self._lock:
            if canonical_url in self._reserved_urls:
                self._reserved_urls.remove(canonical_url)
                self._reserved_bytes -= body_bytes

    def _store(self, wrapped: ClaimBoundEvidencePending) -> None:
        pending = wrapped.pending
        binding = pending.permit.binding
        evidence = CommittedBrowserEvidence(
            canonical_url=wrapped.canonical_url,
            status=pending.payload.response_code,
            reason=pending.payload.response_phrase,
            headers=pending.payload.response_headers,
            body=pending.payload.body,
            addresses=binding.addresses,
            selected_address=binding.selected_address,
            connected_address=pending.payload.connected_address,
            connected_port=pending.payload.connected_port,
            bytes_sent=pending.payload.bytes_sent,
        )
        with self._lock:
            if wrapped.canonical_url not in self._reserved_urls:
                raise BrowserPeerRuntimeDenied(
                    "evidence reservation disappeared before commit"
                )
            self._reserved_urls.remove(wrapped.canonical_url)
            self._reserved_bytes -= wrapped.reserved_bytes
            self._records[wrapped.canonical_url] = evidence
            self._committed_bytes += len(evidence.body)

    def prepare(
        self,
        event: Any,
        *,
        now: int,
        ttl_seconds: int = 30,
    ) -> ClaimBoundEvidencePending:
        pending = self.controller.prepare(
            event,
            now=now,
            ttl_seconds=ttl_seconds,
        )
        try:
            if not isinstance(pending, PendingBrowserFulfillment):
                raise BrowserPeerRuntimeContractError(
                    "controller returned an invalid pending fulfillment"
                )
            canonical = _canonical(pending.permit._canonical_url)
            body_bytes = len(pending.payload.body)
            self._reserve(canonical, body_bytes)
        except Exception as exc:
            try:
                pending.abort(error_code="evidence_budget_exceeded", now=now)
            except Exception:
                pass
            if isinstance(exc, (BrowserPeerRuntimeContractError, BrowserPeerRuntimeDenied)):
                raise
            raise BrowserPeerRuntimeDenied(
                "claim-bound evidence could not be reserved"
            ) from exc
        return ClaimBoundEvidencePending(
            self,
            pending,
            canonical,
            body_bytes,
            token=_EVIDENCE_TOKEN,
        )

    def fetch(self, url: str, policy: ReadOnlyBrowserPolicy) -> FetchTrace:
        if not isinstance(policy, ReadOnlyBrowserPolicy):
            raise WebFetchError("policy must be ReadOnlyBrowserPolicy")
        try:
            canonical = policy.require_allowed_url(url)
        except ResearchContractError as exc:
            raise WebFetchError("evidence URL is forbidden") from exc
        with self._lock:
            if self._closed:
                raise WebFetchError("claim-bound evidence store is closed")
            evidence = self._records.get(canonical)
        if evidence is None:
            raise WebFetchError("no committed claim-bound evidence exists for URL")
        fetcher = DeterministicWebFetcher(
            _CommittedResponseTransport(evidence),
            resolver=lambda _host, _port: evidence.addresses,
            max_redirects=0,
        )
        return fetcher.fetch(canonical, policy)

    def audit(self) -> list[dict[str, Any]]:
        with self._lock:
            records = tuple(self._records.values())
        return [record.audit_dict() for record in records]

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._records.clear()
            self._reserved_urls.clear()
            self._reserved_bytes = 0
            self._committed_bytes = 0


@dataclass(frozen=True)
class ClaimBoundBrowserUseRuntime:
    backend: BrowserUseBackend
    evidence: ClaimBoundBrowserEvidence
    schema: str = BROWSER_PEER_RUNTIME_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != BROWSER_PEER_RUNTIME_SCHEMA:
            raise BrowserPeerRuntimeContractError(
                "unsupported browser peer runtime schema"
            )
        if not isinstance(self.backend, BrowserUseBackend):
            raise BrowserPeerRuntimeContractError(
                "runtime backend must be BrowserUseBackend"
            )
        if not isinstance(self.evidence, ClaimBoundBrowserEvidence):
            raise BrowserPeerRuntimeContractError(
                "runtime evidence store is invalid"
            )

    def close(self) -> None:
        self.evidence.close()


def build_claim_bound_browser_use_runtime(
    controller: BrowserPeerFulfillmentController,
    *,
    llm_factory: LlmFactory,
    bindings_loader: BindingsLoader = load_browser_use_bindings,
    max_evidence_bytes: int,
    max_evidence_responses: int,
    now_factory: Callable[[], int],
) -> ClaimBoundBrowserUseRuntime:
    """Build a dormant BrowserUse backend where both network seams share one claim."""

    if not callable(llm_factory):
        raise BrowserPeerRuntimeContractError("llm_factory must be callable")
    if not callable(bindings_loader):
        raise BrowserPeerRuntimeContractError("bindings_loader must be callable")
    if not callable(now_factory):
        raise BrowserPeerRuntimeContractError("now_factory must be callable")
    evidence = ClaimBoundBrowserEvidence(
        controller,
        max_evidence_bytes=max_evidence_bytes,
        max_evidence_responses=max_evidence_responses,
    )
    expected_domains = controller.intent.plan.allowed_domains

    def guard_factory(browser_session: Any, allowed_domains) -> BrowserUseNetworkGuard:
        domains = tuple(str(value) for value in allowed_domains)
        if domains != expected_domains:
            raise BrowserUseNetworkGuardError(
                "BrowserUse domain scope does not match the common claim"
            )
        return BrowserUseNetworkGuard(
            browser_session,
            domains,
            fulfillment_controller=evidence,
            now_factory=now_factory,
        )

    backend = BrowserUseBackend(
        fetcher=evidence,
        llm_factory=llm_factory,
        bindings_loader=bindings_loader,
        network_guard_factory=guard_factory,
    )
    return ClaimBoundBrowserUseRuntime(
        backend=backend,
        evidence=evidence,
    )


__all__ = [
    "BROWSER_PEER_RUNTIME_SCHEMA",
    "BrowserPeerRuntimeContractError",
    "BrowserPeerRuntimeDenied",
    "ClaimBoundBrowserEvidence",
    "ClaimBoundBrowserUseRuntime",
    "ClaimBoundEvidencePending",
    "CommittedBrowserEvidence",
    "build_claim_bound_browser_use_runtime",
]
