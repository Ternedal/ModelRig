from __future__ import annotations

import hashlib
import io
import json
import socket
import uuid

from app.browser_peer_fulfillment import (
    BrowserPeerFulfillmentController,
    PinnedBrowserPeerTransport,
)
from app.browser_peer_runtime import (
    BROWSER_PEER_RUNTIME_SCHEMA,
    BrowserPeerRuntimeContractError,
    BrowserPeerRuntimeDenied,
    ClaimBoundBrowserEvidence,
    build_claim_bound_browser_use_runtime,
)
from app.browser_use_network_guard import BrowserUseNetworkGuardError
from app.research_claim_evidence import (
    VerifiableDataSharingLedger,
    VerifiableResearchSharingBoundary,
)
from app.research_contract import ReadOnlyBrowserPolicy
from app.research_data_sharing import ResearchSharingIntent
from app.research_egress import EgressPlan
from app.research_peer_authorization import ResearchPeerAuthorizationBridge
from app.research_peer_transfer import ResearchPeerTransferLedger
from app.web_fetch import WebFetchError

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def rejects(fn, expected, name: str, contains: str = "") -> None:
    try:
        fn()
    except expected as exc:
        check(not contains or contains in str(exc), name)
    else:
        check(False, name)


class UUIDs:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> uuid.UUID:
        self.value += 1
        return uuid.UUID(int=self.value)


class FakeSocket:
    def __init__(self, wire: bytes, *, peer: str = "93.184.216.34") -> None:
        self.wire = wire
        self.peer = peer
        self.sockaddr = None
        self.sent = b""
        self.closed = False

    def settimeout(self, value) -> None:
        del value

    def connect(self, sockaddr) -> None:
        self.sockaddr = sockaddr

    def getpeername(self):
        return (self.peer, self.sockaddr[1])

    def send(self, data: bytes) -> int:
        self.sent += data
        return len(data)

    def makefile(self, mode, buffering=None):
        del buffering
        assert mode == "rb"
        return io.BytesIO(self.wire)

    def close(self) -> None:
        self.closed = True


class SocketFactory:
    def __init__(self, *sockets: FakeSocket) -> None:
        self.sockets = list(sockets)
        self.calls = 0

    def __call__(self, family, kind):
        assert family == socket.AF_INET
        assert kind == socket.SOCK_STREAM
        self.calls += 1
        if not self.sockets:
            raise AssertionError("unexpected public socket attempt")
        return self.sockets.pop(0)


class FakeTLSContext:
    def __init__(self) -> None:
        self.server_names: list[str] = []

    def wrap_socket(self, sock, *, server_hostname):
        self.server_names.append(server_hostname)
        return sock


def wire(body: bytes, *, content_type: str = "text/html; charset=utf-8") -> bytes:
    headers = (
        f"HTTP/1.1 200 OK\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    return headers + body


PUBLIC_V4 = "93.184.216.34"
PUBLIC_V6 = "2606:2800:220:1:248:1893:25c8:1946"
URL_A = "https://example.com/releases/a?channel=stable#section"
URL_B = "https://example.com/releases/b?channel=stable#section"
RAW_PURPOSE = "Retrieve public release-note evidence"
RAW_SUMMARY = "A bounded public research request."
RAW_PAYLOAD = b"claim-bound runtime sentinel"
POLICY = ReadOnlyBrowserPolicy(
    allowed_domains=("example.com",),
    max_steps=4,
    max_pages=4,
    timeout_seconds=10,
    max_source_bytes=4096,
)


def event(url: str, suffix: str) -> dict:
    return {
        "requestId": f"fetch-{suffix}",
        "networkId": f"network-{suffix}",
        "request": {
            "url": url,
            "method": "GET",
            "headers": {"Accept": "text/html"},
            "hasPostData": False,
        },
    }


def context(*sockets: FakeSocket, now: int = 100):
    intent = ResearchSharingIntent(
        plan=EgressPlan(
            destination="browser-use",
            purpose=RAW_PURPOSE,
            payload_sha256=hashlib.sha256(RAW_PAYLOAD).hexdigest(),
            sensitivity="public",
            allowed_domains=("example.com",),
            max_bytes=8192,
        ),
        summary=RAW_SUMMARY,
    )
    common = VerifiableDataSharingLedger(uuid_factory=UUIDs())
    boundary = VerifiableResearchSharingBoundary(common, mode="enforce")
    bridge = ResearchPeerAuthorizationBridge(boundary)
    lease = boundary.prepare(intent, now=now, receipt_ttl_seconds=120)
    evidence = boundary.claim(lease, intent, now=now + 1)
    peer = ResearchPeerTransferLedger(
        bridge,
        lambda _host, _port: [PUBLIC_V6, PUBLIC_V4],
        uuid_factory=UUIDs(),
    )
    factory = SocketFactory(*sockets)
    tls = FakeTLSContext()
    transport = PinnedBrowserPeerTransport(
        socket_factory=factory,
        ssl_context_factory=lambda: tls,
        uuid_factory=UUIDs(),
    )
    controller = BrowserPeerFulfillmentController.create(
        bridge,
        peer,
        evidence,
        lease,
        intent,
        timeout_seconds=5,
        max_response_bytes=4096,
        transport=transport,
    )
    return (
        intent,
        common,
        boundary,
        lease,
        peer,
        factory,
        controller,
    )


def finish(intent, common, boundary, lease, peer, controller, *, now: int, outcome: str, error_code=None):
    boundary.complete(
        lease,
        intent,
        outcome=outcome,
        bytes_sent=controller.bytes_sent,
        error_code=error_code,
        now=now,
    )
    peer.close()
    common.close()


rejects(
    lambda: ClaimBoundBrowserEvidence(
        object(),
        max_evidence_bytes=1,
        max_evidence_responses=1,
    ),
    BrowserPeerRuntimeContractError,
    "evidence store requires the real fulfillment controller",
)

# Committed pinned bytes become deterministic source evidence without a second
# public request. Evidence is unavailable before CDP commit.
raw = b"<html><title>Release A</title><body>Version A is live.</body></html>"
sock = FakeSocket(wire(raw))
intent, common, boundary, lease, peer, factory, controller = context(sock)
evidence = ClaimBoundBrowserEvidence(
    controller,
    max_evidence_bytes=4096,
    max_evidence_responses=4,
)
pending = evidence.prepare(event(URL_A, "a"), now=103)
rejects(
    lambda: evidence.fetch(URL_A, POLICY),
    WebFetchError,
    "uncommitted browser response cannot become citation evidence",
)
check(factory.calls == 1, "browser response required exactly one public socket")
pending.commit(now=104)
trace = evidence.fetch(URL_A, POLICY)
check(factory.calls == 1, "citation verification opens no second public socket")
check(trace.receipt.adapter == "deterministic-web-fetch", "stored response uses trusted fetch provenance")
check(trace.receipt.content_sha256 == hashlib.sha256(raw).hexdigest(), "receipt hashes exact committed bytes")
check(trace.receipt.title == "Release A", "deterministic parser extracts committed title")
check(trace.receipt.bytes_read == len(raw), "receipt records exact committed entity size")
check(trace.final_url == trace.requested_url, "stored exact URL has deterministic trace")
check(trace.resolved_addresses[0][1] == (PUBLIC_V4, PUBLIC_V6), "full validated DNS evidence is retained")
audit_json = json.dumps(evidence.audit(), ensure_ascii=False)
check(URL_A not in audit_json, "evidence audit excludes raw URL")
check(raw.decode() not in audit_json, "evidence audit excludes raw response content")
check(RAW_PURPOSE not in audit_json and RAW_SUMMARY not in audit_json, "evidence audit excludes purpose and summary")
check(BROWSER_PEER_RUNTIME_SCHEMA in audit_json, "evidence audit is versioned")
finish(
    intent,
    common,
    boundary,
    lease,
    peer,
    controller,
    now=105,
    outcome="completed",
)

# Evidence budget is reserved before CDP fulfillment. An over-budget response is
# blocked and the peer transfer is terminalized rather than delivered.
large = b"<html><body>too large for evidence</body></html>"
sock = FakeSocket(wire(large))
intent, common, boundary, lease, peer, _, controller = context(sock, now=200)
evidence = ClaimBoundBrowserEvidence(
    controller,
    max_evidence_bytes=8,
    max_evidence_responses=1,
)
rejects(
    lambda: evidence.prepare(event(URL_A, "large"), now=203),
    BrowserPeerRuntimeDenied,
    "evidence byte budget blocks before CDP delivery",
    "budget",
)
check(
    peer.events()[-1]["outcome"] == "blocked"
    and peer.events()[-1]["error_code"] == "evidence_budget_exceeded",
    "evidence budget refusal is terminally audited",
)
finish(
    intent,
    common,
    boundary,
    lease,
    peer,
    controller,
    now=204,
    outcome="blocked",
    error_code="evidence_budget_exceeded",
)

# Aborting a pending response releases the in-memory reservation. Another exact
# URL may then use the same evidence budget under the still-active common claim.
body_a = b"<html><body>A</body></html>"
body_b = b"<html><body>B</body></html>"
first = FakeSocket(wire(body_a))
second = FakeSocket(wire(body_b))
intent, common, boundary, lease, peer, factory, controller = context(
    first,
    second,
    now=300,
)
evidence = ClaimBoundBrowserEvidence(
    controller,
    max_evidence_bytes=max(len(body_a), len(body_b)),
    max_evidence_responses=1,
)
pending = evidence.prepare(event(URL_A, "abort"), now=303)
rejects(
    lambda: pending.abort(error_code="cdp_fulfill_failed", now=304),
    Exception,
    "underlying blocked terminal signal propagates on abort",
)
pending = evidence.prepare(event(URL_B, "b"), now=305)
pending.commit(now=306)
check(factory.calls == 2, "released reservation allows another exact URL")
check(evidence.fetch(URL_B, POLICY).receipt.bytes_read == len(body_b), "second committed response is verifiable")
finish(
    intent,
    common,
    boundary,
    lease,
    peer,
    controller,
    now=307,
    outcome="blocked",
    error_code="cdp_fulfill_failed",
)

# Runtime factory binds both BrowserUse network seams to the same evidence object
# and refuses domain-scope drift before the guard is constructed.
sock = FakeSocket(wire(raw))
intent, common, boundary, lease, peer, _, controller = context(sock, now=400)
runtime = build_claim_bound_browser_use_runtime(
    controller,
    llm_factory=lambda: object(),
    bindings_loader=lambda: None,
    max_evidence_bytes=4096,
    max_evidence_responses=4,
    now_factory=lambda: 403,
)
check(runtime.schema == BROWSER_PEER_RUNTIME_SCHEMA, "claim-bound runtime is versioned")
check(runtime.backend._fetcher is runtime.evidence, "BrowserUse citation seam uses committed evidence")
guard = runtime.backend._network_guard_factory(object(), ("example.com",))
check(guard.fulfillment_controller is runtime.evidence, "BrowserUse request seam uses same claim evidence")
check(guard.now_factory() == 403, "runtime guard uses injected validation clock")
rejects(
    lambda: runtime.backend._network_guard_factory(object(), ("*.example.com",)),
    BrowserUseNetworkGuardError,
    "runtime refuses changed BrowserUse domain scope",
)
runtime.close()
rejects(
    lambda: runtime.evidence.fetch(URL_A, POLICY),
    WebFetchError,
    "closed runtime exposes no retained response evidence",
)
finish(
    intent,
    common,
    boundary,
    lease,
    peer,
    controller,
    now=404,
    outcome="blocked",
    error_code="runtime_not_started",
)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
