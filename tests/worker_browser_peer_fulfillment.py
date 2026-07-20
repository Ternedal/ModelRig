from __future__ import annotations

import base64
import hashlib
import io
import json
import socket
import ssl
import uuid

from app.browser_peer_adapter import BrowserPeerAdapterDenied
from app.browser_peer_fulfillment import (
    BROWSER_FULFILLMENT_SCHEMA,
    BrowserPeerFulfillmentContractError,
    BrowserPeerFulfillmentController,
    BrowserPeerFulfillmentDenied,
    BrowserPinnedTransportError,
    PendingBrowserFulfillment,
    PinnedBrowserPeerTransport,
)
from app.research_claim_evidence import (
    VerifiableDataSharingLedger,
    VerifiableResearchSharingBoundary,
)
from app.research_data_sharing import ResearchSharingIntent
from app.research_egress import EgressPlan
from app.research_peer_authorization import ResearchPeerAuthorizationBridge
from app.research_peer_transfer import ResearchPeerTransferLedger

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
    def __init__(
        self,
        wire: bytes,
        *,
        peer: str = "93.184.216.34",
        send_plan: list[object] | None = None,
        connect_error: Exception | None = None,
    ) -> None:
        self.wire = wire
        self.peer = peer
        self.send_plan = list(send_plan or [])
        self.connect_error = connect_error
        self.timeout = None
        self.sockaddr = None
        self.sent = b""
        self.closed = False

    def settimeout(self, value) -> None:
        self.timeout = value

    def connect(self, sockaddr) -> None:
        self.sockaddr = sockaddr
        if self.connect_error is not None:
            raise self.connect_error

    def getpeername(self):
        return (self.peer, self.sockaddr[1])

    def send(self, data: bytes) -> int:
        if self.send_plan:
            step = self.send_plan.pop(0)
            if isinstance(step, Exception):
                raise step
            count = min(int(step), len(data))
        else:
            count = len(data)
        self.sent += data[:count]
        return count

    def makefile(self, mode, buffering=None):
        assert mode == "rb"
        return io.BytesIO(self.wire)

    def close(self) -> None:
        self.closed = True


class SocketFactory:
    def __init__(self, *sockets: FakeSocket) -> None:
        self.sockets = list(sockets)
        self.calls = []

    def __call__(self, family, kind):
        self.calls.append((family, kind))
        if not self.sockets:
            raise AssertionError("unexpected public socket attempt")
        return self.sockets.pop(0)


class FakeTLSContext:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.server_names: list[str] = []

    def wrap_socket(self, sock, *, server_hostname):
        self.server_names.append(server_hostname)
        if self.error is not None:
            raise self.error
        return sock


def wire(status="200 OK", headers=(), body=b"") -> bytes:
    lines = [f"HTTP/1.1 {status}"]
    lines.extend(f"{name}: {value}" for name, value in headers)
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body


RAW_PURPOSE = "Retrieve public release-note fixtures"
RAW_SUMMARY = "A public research query without local document content."
RAW_PAYLOAD = b"pinned browser fulfillment sentinel"
PUBLIC_V4 = "93.184.216.34"
PUBLIC_V6 = "2606:2800:220:1:248:1893:25c8:1946"
URL_A = "https://example.com/releases/a?channel=stable#section"
URL_B = "https://example.com/releases/b?channel=stable#section"


def request_event(
    url: str,
    *,
    request_id: str,
    network_id: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
):
    return {
        "requestId": request_id,
        "networkId": network_id,
        "request": {
            "url": url,
            "method": method,
            "headers": headers or {},
            "hasPostData": False,
        },
        "resourceType": "Document",
    }


def make_context(
    *sockets: FakeSocket,
    now: int,
    max_bytes: int = 4096,
    max_response_bytes: int = 4096,
    tls: FakeTLSContext | None = None,
):
    intent = ResearchSharingIntent(
        plan=EgressPlan(
            destination="browser-use",
            purpose=RAW_PURPOSE,
            payload_sha256=hashlib.sha256(RAW_PAYLOAD).hexdigest(),
            sensitivity="public",
            allowed_domains=("example.com",),
            max_bytes=max_bytes,
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
    active_tls = tls or FakeTLSContext()
    transport = PinnedBrowserPeerTransport(
        socket_factory=factory,
        ssl_context_factory=lambda: active_tls,
        uuid_factory=UUIDs(),
    )
    controller = BrowserPeerFulfillmentController.create(
        bridge,
        peer,
        evidence,
        lease,
        intent,
        timeout_seconds=5,
        max_response_bytes=max_response_bytes,
        transport=transport,
    )
    return (
        intent,
        common,
        boundary,
        lease,
        evidence,
        peer,
        factory,
        active_tls,
        transport,
        controller,
    )


rejects(
    lambda: PendingBrowserFulfillment(None, None, None, token=object()),
    BrowserPeerFulfillmentContractError,
    "pending fulfillment cannot be forged",
)
rejects(
    lambda: PinnedBrowserPeerTransport().prepare(
        None,
        url=URL_A,
        method="POST",
        headers=(),
        max_response_bytes=1,
    ),
    (BrowserPeerFulfillmentContractError, BrowserPeerFulfillmentDenied),
    "transport cannot prepare without an active pin",
)

# A successful pinned GET is fetched outside Chromium and committed only after
# the caller has successfully sent Fetch.fulfillRequest.
sock = FakeSocket(
    wire(
        headers=(
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", "5"),
            ("Set-Cookie", "secret=forbidden"),
            ("Connection", "keep-alive"),
        ),
        body=b"hello",
    ),
    send_plan=[7, 11, 10_000],
)
(
    intent,
    common,
    boundary,
    lease,
    evidence,
    peer,
    factory,
    tls,
    transport,
    controller,
) = make_context(sock, now=100)
pending = controller.prepare(
    request_event(
        URL_A,
        request_id="fetch-a",
        network_id="network-a",
        headers={
            "Accept": "text/html",
            "User-Agent": "TestBrowser/1.0",
            "Cookie": "",
            "X-Ignored": "not-forwarded",
        },
    ),
    now=103,
)
check(pending.payload.schema == BROWSER_FULFILLMENT_SCHEMA, "fulfillment is versioned")
check(factory.calls == [(socket.AF_INET, socket.SOCK_STREAM)], "IPv4 socket is selected")
check(sock.sockaddr == (PUBLIC_V4, 443), "transport connects to the selected numeric peer")
check(tls.server_names == ["example.com"], "TLS SNI preserves canonical hostname")
check(sock.sent.startswith(b"GET /releases/a?channel=stable HTTP/1.1\r\n"), "canonical request target is sent")
check(b"Host: example.com\r\n" in sock.sent, "HTTP Host preserves canonical hostname")
check(b"Connection: close\r\n" in sock.sent, "transport is single-request")
check(b"x-ignored" not in sock.sent.lower(), "arbitrary browser headers are not forwarded")
check(b"cookie" not in sock.sent.lower(), "cookies are never forwarded")
check(pending.payload.bytes_sent == len(sock.sent), "only confirmed socket writes are counted")
check(controller.bytes_sent == len(sock.sent), "aggregate common meter records confirmed writes")
params = pending.cdp_params()
check(params["requestId"] == "fetch-a" and params["responseCode"] == 200, "CDP fulfillment targets paused request")
check(base64.b64decode(params["body"]) == b"hello", "CDP body is the pinned response body")
response_names = {item["name"] for item in params["responseHeaders"]}
check("set-cookie" not in response_names and "connection" not in response_names, "credentials and hop headers are stripped")
check("content-length" in response_names, "fulfilled body has deterministic content length")
check(peer.events()[-1]["event_type"] == "claimed", "peer transfer remains in flight before CDP commit")
pending.commit(now=104)
check(
    peer.events()[-1]["outcome"] == "connected"
    and peer.events()[-1]["peer_address"] == PUBLIC_V4
    and peer.events()[-1]["bytes_sent"] == len(sock.sent),
    "successful CDP commit terminalizes exact peer and request bytes",
)
rejects(
    lambda: pending.cdp_params(),
    BrowserPeerFulfillmentDenied,
    "committed fulfillment cannot be reused",
)
check(sock.closed, "public socket closes before fulfillment is returned")
audit = json.dumps(pending.payload.audit_dict(), ensure_ascii=False)
check(RAW_PURPOSE not in audit, "fulfillment audit excludes raw purpose")
check(RAW_SUMMARY not in audit, "fulfillment audit excludes raw summary")
check(RAW_PAYLOAD.decode() not in audit, "fulfillment audit excludes shared content")
check("/releases/a" not in audit and "channel=stable" not in audit, "fulfillment audit excludes URL path/query")
boundary.complete(
    lease,
    intent,
    outcome="completed",
    bytes_sent=controller.bytes_sent,
    now=105,
)
peer.close()
common.close()

# HEAD preserves response metadata without exposing a response body.
head_sock = FakeSocket(
    wire(
        headers=(
            ("Content-Type", "text/plain"),
            ("Content-Length", "123"),
        )
    )
)
(
    intent,
    common,
    boundary,
    lease,
    evidence,
    peer,
    factory,
    tls,
    transport,
    controller,
) = make_context(head_sock, now=200)
pending = controller.prepare(
    request_event(
        URL_A,
        request_id="fetch-head",
        network_id="network-head",
        method="HEAD",
    ),
    now=203,
)
check(head_sock.sent.startswith(b"HEAD "), "HEAD method reaches pinned transport")
check(pending.payload.body == b"", "HEAD fulfillment has no response body")
check(dict(pending.payload.response_headers)["content-length"] == "123", "HEAD preserves declared entity length")
pending.commit(now=204)
boundary.complete(
    lease,
    intent,
    outcome="completed",
    bytes_sent=controller.bytes_sent,
    now=205,
)
peer.close()
common.close()

# Multiple exact URLs share one aggregate common budget. The second request is
# refused before another socket exists, rather than receiving a fresh full meter.
first = FakeSocket(wire(headers=(("Content-Length", "1"),), body=b"a"))
(
    intent,
    common,
    boundary,
    lease,
    evidence,
    peer,
    factory,
    tls,
    transport,
    controller,
) = make_context(first, now=300, max_bytes=300)
pending = controller.prepare(
    request_event(URL_A, request_id="fetch-1", network_id="network-1"),
    now=303,
)
pending.commit(now=304)
check(0 < controller.bytes_sent <= 300, "first request consumes the shared budget")
rejects(
    lambda: controller.prepare(
        request_event(URL_B, request_id="fetch-2", network_id="network-2"),
        now=305,
    ),
    BrowserPeerFulfillmentDenied,
    "second request cannot multiply the common byte ceiling",
    "aggregate",
)
check(len(factory.calls) == 1, "aggregate budget is checked before a second public socket")
check(peer.events()[-1]["error_code"] == "byte_budget_exceeded", "budget refusal terminalizes second peer claim")
boundary.complete(
    lease,
    intent,
    outcome="blocked",
    bytes_sent=controller.bytes_sent,
    error_code="byte_budget_exceeded",
    now=306,
)
peer.close()
common.close()

# Partial writes are counted exactly and terminalized even when the response is
# never available.
partial = FakeSocket(
    b"",
    send_plan=[13, socket.timeout("private detail")],
)
(
    intent,
    common,
    boundary,
    lease,
    evidence,
    peer,
    factory,
    tls,
    transport,
    controller,
) = make_context(partial, now=400)
rejects(
    lambda: controller.prepare(
        request_event(URL_A, request_id="fetch-partial", network_id="network-partial"),
        now=403,
    ),
    BrowserPeerFulfillmentDenied,
    "partial request write fails closed",
    "request_send_failed",
)
check(controller.bytes_sent == 13, "aggregate meter records exact partial send progress")
check(
    peer.events()[-1]["bytes_sent"] == 13
    and peer.events()[-1]["error_code"] == "request_send_failed",
    "partial send is retained in terminal peer audit",
)
boundary.complete(
    lease,
    intent,
    outcome="blocked",
    bytes_sent=controller.bytes_sent,
    error_code="request_send_failed",
    now=404,
)
peer.close()
common.close()

# A socket that reaches another public address is rejected before application
# bytes are sent.
wrong_peer = FakeSocket(wire(), peer="1.1.1.1")
(
    intent,
    common,
    boundary,
    lease,
    evidence,
    peer,
    factory,
    tls,
    transport,
    controller,
) = make_context(wrong_peer, now=500)
rejects(
    lambda: controller.prepare(
        request_event(URL_A, request_id="fetch-peer", network_id="network-peer"),
        now=503,
    ),
    BrowserPeerFulfillmentDenied,
    "actual socket peer must equal the selected address",
    "connected_peer_mismatch",
)
check(wrong_peer.sent == b"" and controller.bytes_sent == 0, "peer mismatch sends no application bytes")
boundary.complete(
    lease,
    intent,
    outcome="blocked",
    bytes_sent=0,
    error_code="connected_peer_mismatch",
    now=504,
)
peer.close()
common.close()

# TLS verification and response-size failures are normalized and preserve any
# request bytes that were actually sent.
tls_sock = FakeSocket(b"")
cert_error = ssl.SSLCertVerificationError("private certificate detail")
(
    intent,
    common,
    boundary,
    lease,
    evidence,
    peer,
    factory,
    tls,
    transport,
    controller,
) = make_context(
    tls_sock,
    now=600,
    tls=FakeTLSContext(error=cert_error),
)
rejects(
    lambda: controller.prepare(
        request_event(URL_A, request_id="fetch-tls", network_id="network-tls"),
        now=603,
    ),
    BrowserPeerFulfillmentDenied,
    "TLS certificate failure is normalized",
    "tls_certificate_failed",
)
check(controller.bytes_sent == 0, "TLS failure occurs before application bytes")
boundary.complete(
    lease,
    intent,
    outcome="blocked",
    bytes_sent=0,
    error_code="tls_certificate_failed",
    now=604,
)
peer.close()
common.close()

oversized = FakeSocket(
    wire(headers=(("Content-Length", "6"),), body=b"abcdef")
)
(
    intent,
    common,
    boundary,
    lease,
    evidence,
    peer,
    factory,
    tls,
    transport,
    controller,
) = make_context(oversized, now=700, max_response_bytes=5)
rejects(
    lambda: controller.prepare(
        request_event(URL_A, request_id="fetch-large", network_id="network-large"),
        now=703,
    ),
    BrowserPeerFulfillmentDenied,
    "oversized browser response is stopped",
    "response_body_too_large",
)
check(controller.bytes_sent == len(oversized.sent) > 0, "request bytes remain measured after response overflow")
check(peer.events()[-1]["error_code"] == "response_body_too_large", "response overflow is terminally audited")
boundary.complete(
    lease,
    intent,
    outcome="blocked",
    bytes_sent=controller.bytes_sent,
    error_code="response_body_too_large",
    now=704,
)
peer.close()
common.close()

# If Fetch.fulfillRequest itself fails, the already-performed public request is
# blocked with its measured bytes rather than falsely reported as connected.
cdp_fail = FakeSocket(wire(headers=(("Content-Length", "2"),), body=b"ok"))
(
    intent,
    common,
    boundary,
    lease,
    evidence,
    peer,
    factory,
    tls,
    transport,
    controller,
) = make_context(cdp_fail, now=800)
pending = controller.prepare(
    request_event(URL_A, request_id="fetch-cdp", network_id="network-cdp"),
    now=803,
)
rejects(
    lambda: pending.abort(error_code="cdp_fulfill_failed", now=804),
    BrowserPeerAdapterDenied,
    "CDP fulfillment failure terminalizes pending request",
    "cdp_fulfill_failed",
)
check(
    peer.events()[-1]["outcome"] == "blocked"
    and peer.events()[-1]["bytes_sent"] == len(cdp_fail.sent)
    and peer.events()[-1]["error_code"] == "cdp_fulfill_failed",
    "CDP failure audit retains actual outbound bytes",
)
rejects(
    lambda: pending.commit(now=805),
    BrowserPeerFulfillmentDenied,
    "aborted fulfillment cannot later commit",
)
boundary.complete(
    lease,
    intent,
    outcome="blocked",
    bytes_sent=controller.bytes_sent,
    error_code="cdp_fulfill_failed",
    now=805,
)
peer.close()
common.close()

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
