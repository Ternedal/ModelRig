from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import replace

from app.browser_peer_adapter import (
    BROWSER_PEER_ADAPTER_SCHEMA,
    BrowserPeerAdapter,
    BrowserPeerAdapterContractError,
    BrowserPeerAdapterDenied,
    BrowserPeerPermit,
    BrowserPeerPinReceipt,
)
from app.research_claim_evidence import (
    VerifiableDataSharingLedger,
    VerifiableResearchSharingBoundary,
)
from app.research_contract import canonicalize_url
from app.research_data_sharing import ResearchSharingIntent
from app.research_egress import EgressPlan
from app.research_peer_authorization import ResearchPeerAuthorizationBridge
from app.research_peer_transfer import ResearchPeerTransferLedger
from app.research_sharing_execution import ResearchExternalBlocked

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def rejects(fn, expected, name: str) -> None:
    try:
        fn()
    except expected:
        check(True, name)
    else:
        check(False, name)


class UUIDs:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> uuid.UUID:
        self.value += 1
        return uuid.UUID(int=self.value)


class FakeTransport:
    def __init__(
        self,
        *,
        pin_address: str | None = None,
        fail_pin: bool = False,
        fail_release: bool = False,
    ) -> None:
        self.pin_address = pin_address
        self.fail_pin = fail_pin
        self.fail_release = fail_release
        self.pins: list[BrowserPeerPinReceipt] = []
        self.releases: list[str] = []

    def pin(self, binding, *, cdp_request_id: str, network_request_id: str):
        if self.fail_pin:
            raise RuntimeError("pin failed")
        receipt = BrowserPeerPinReceipt(
            pin_id=f"bpp_{len(self.pins) + 1}",
            binding_id=binding.binding_id,
            cdp_request_id=cdp_request_id,
            network_request_id=network_request_id,
            host=binding.host,
            port=binding.port,
            selected_address=self.pin_address or binding.selected_address,
            expires_at=binding.expires_at,
        )
        self.pins.append(receipt)
        return receipt

    def release(self, receipt: BrowserPeerPinReceipt) -> None:
        if self.fail_release:
            raise RuntimeError("release failed")
        self.releases.append(receipt.pin_id)


RAW_PURPOSE = "Retrieve one public release-note fixture"
RAW_SUMMARY = "A public research query without local document content."
RAW_PAYLOAD = b"browser peer adapter sentinel"
RAW_URL = "https://example.com/releases/browser-peer?channel=stable#section"
CANONICAL_URL = canonicalize_url(RAW_URL)
PUBLIC_V4 = "93.184.216.34"
PUBLIC_V6 = "2606:2800:220:1:248:1893:25c8:1946"


def make_intent(max_bytes: int = 4096) -> ResearchSharingIntent:
    return ResearchSharingIntent(
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


def context(
    *,
    now: int,
    max_bytes: int = 4096,
    transport: FakeTransport | None = None,
):
    common = VerifiableDataSharingLedger(uuid_factory=UUIDs())
    boundary = VerifiableResearchSharingBoundary(common, mode="enforce")
    bridge = ResearchPeerAuthorizationBridge(boundary)
    intent = make_intent(max_bytes)
    lease = boundary.prepare(intent, now=now, receipt_ttl_seconds=60)
    evidence = boundary.claim(lease, intent, now=now + 1)
    peer = ResearchPeerTransferLedger(
        bridge,
        lambda _host, _port: [PUBLIC_V6, PUBLIC_V4],
        uuid_factory=UUIDs(),
    )
    active_transport = transport or FakeTransport()
    adapter = BrowserPeerAdapter(bridge, peer, active_transport)
    return (
        common,
        boundary,
        intent,
        lease,
        evidence,
        peer,
        active_transport,
        adapter,
    )


def request_event(
    *,
    request_id: str = "fetch-1",
    network_id: str = "network-1",
    url: str = RAW_URL,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    post_data: str | None = None,
):
    request = {
        "url": url,
        "method": method,
        "headers": headers or {},
        "hasPostData": post_data is not None,
    }
    if post_data is not None:
        request["postData"] = post_data
    return {
        "requestId": request_id,
        "networkId": network_id,
        "request": request,
        "resourceType": "Document",
    }


def response_event(
    *,
    network_id: str = "network-1",
    url: str = CANONICAL_URL,
    address: str = PUBLIC_V4,
    port: int = 443,
    disk_cache: bool = False,
    service_worker: bool = False,
    prefetch_cache: bool = False,
):
    return {
        "requestId": network_id,
        "response": {
            "url": url,
            "remoteIPAddress": address,
            "remotePort": port,
            "fromDiskCache": disk_cache,
            "fromServiceWorker": service_worker,
            "fromPrefetchCache": prefetch_cache,
        },
    }


rejects(
    lambda: BrowserPeerAdapter(object(), object(), object()),
    BrowserPeerAdapterContractError,
    "adapter requires the common bridge and peer ledger",
)
rejects(
    lambda: BrowserPeerPermit(
        request_id="fetch-1",
        network_id="network-1",
        canonical_url=CANONICAL_URL,
        authorization=None,
        binding=None,
        transfer=None,
        pin=None,
        token=object(),
    ),
    BrowserPeerAdapterContractError,
    "permit cannot be forged outside the adapter",
)
rejects(
    lambda: replace(
        BrowserPeerPinReceipt(
            pin_id="bpp_1",
            binding_id="rpt_example",
            cdp_request_id="fetch-1",
            network_request_id="network-1",
            host="example.com",
            port=443,
            selected_address=PUBLIC_V4,
            expires_at=200,
        ),
        production_activation=True,
    ),
    BrowserPeerAdapterContractError,
    "transport pin cannot activate production",
)

# Positive request: transport pin exists before the caller receives a permit.
(
    common,
    boundary,
    intent,
    lease,
    evidence,
    peer,
    transport,
    adapter,
) = context(now=100)
permit = adapter.prepare_request(
    request_event(),
    evidence,
    lease,
    intent,
    now=103,
)
check(permit.to_dict()["schema"] == BROWSER_PEER_ADAPTER_SCHEMA, "permit is versioned")
check(len(transport.pins) == 1, "transport is pinned before permit delivery")
check(
    transport.pins[0].binding_id == permit.binding.binding_id
    and transport.pins[0].selected_address == permit.selected_address,
    "permit carries the exact transport-enforced peer",
)
check(
    permit.pin.transport_enforced is True
    and permit.pin.production_activation is False,
    "pin proof is enforced and dormant",
)
check(permit.record_sent(40) == 40, "claimed permit exposes the measured byte meter")
adapter.complete_response(
    permit,
    response_event(),
    evidence,
    lease,
    intent,
    now=104,
)
check(transport.releases == [permit.pin.pin_id], "transport pin is released at terminal response")
check(
    peer.events()[-1]["outcome"] == "connected"
    and peer.events()[-1]["peer_address"] == PUBLIC_V4
    and peer.events()[-1]["bytes_sent"] == 40,
    "CDP peer evidence terminalizes actual peer and measured bytes",
)
rejects(
    lambda: permit.record_sent(1),
    BrowserPeerAdapterDenied,
    "terminal permit cannot record more bytes",
)
serialized = json.dumps(permit.to_dict(), ensure_ascii=False)
check(RAW_PURPOSE not in serialized, "permit excludes raw purpose")
check(RAW_SUMMARY not in serialized, "permit excludes raw summary")
check(RAW_PAYLOAD.decode() not in serialized, "permit excludes raw content")
check("/releases/browser-peer" not in serialized, "permit excludes URL path")
check("channel=stable" not in serialized, "permit excludes URL query")
boundary.complete(lease, intent, outcome="completed", bytes_sent=40, now=105)
peer.close()
common.close()

# Read-only and correlation checks happen before DNS or transport pinning.
(
    common,
    boundary,
    intent,
    lease,
    evidence,
    peer,
    transport,
    adapter,
) = context(now=200)
rejects(
    lambda: adapter.prepare_request(
        request_event(method="POST", post_data="secret"),
        evidence,
        lease,
        intent,
        now=203,
    ),
    BrowserPeerAdapterDenied,
    "POST and request bodies are rejected before peer preparation",
)
rejects(
    lambda: adapter.prepare_request(
        request_event(headers={"Cookie": "session=secret"}),
        evidence,
        lease,
        intent,
        now=203,
    ),
    BrowserPeerAdapterDenied,
    "credential-bearing headers are rejected before peer preparation",
)
invalid_event = request_event()
del invalid_event["networkId"]
rejects(
    lambda: adapter.prepare_request(
        invalid_event,
        evidence,
        lease,
        intent,
        now=203,
    ),
    BrowserPeerAdapterContractError,
    "missing CDP network correlation fails closed",
)
check(not transport.pins and not peer.events(), "rejected request shapes create no peer state")
boundary.complete(
    lease,
    intent,
    outcome="blocked",
    bytes_sent=0,
    error_code="request_shape_rejected",
    now=204,
)
peer.close()
common.close()

# A transport cannot claim it pinned a different public address.
forged_transport = FakeTransport(pin_address=PUBLIC_V6)
(
    common,
    boundary,
    intent,
    lease,
    evidence,
    peer,
    transport,
    adapter,
) = context(now=300, transport=forged_transport)
rejects(
    lambda: adapter.prepare_request(
        request_event(),
        evidence,
        lease,
        intent,
        now=303,
    ),
    BrowserPeerAdapterDenied,
    "transport pin mismatch blocks before CDP continuation",
)
check(
    peer.events()[-1]["outcome"] == "blocked"
    and peer.events()[-1]["error_code"] == "transport_pin_mismatch",
    "forged transport pin is terminally audited",
)
boundary.complete(
    lease,
    intent,
    outcome="blocked",
    bytes_sent=0,
    error_code="transport_pin_mismatch",
    now=304,
)
peer.close()
common.close()

# Pin failure also terminalizes the already-claimed peer transfer.
failing_transport = FakeTransport(fail_pin=True)
(
    common,
    boundary,
    intent,
    lease,
    evidence,
    peer,
    transport,
    adapter,
) = context(now=400, transport=failing_transport)
rejects(
    lambda: adapter.prepare_request(
        request_event(),
        evidence,
        lease,
        intent,
        now=403,
    ),
    BrowserPeerAdapterDenied,
    "transport pin failure cannot leak a claimed transfer",
)
check(
    peer.events()[-1]["outcome"] == "blocked"
    and peer.events()[-1]["error_code"] == "transport_pin_failed",
    "pin failure is terminally audited",
)
boundary.complete(
    lease,
    intent,
    outcome="blocked",
    bytes_sent=0,
    error_code="transport_pin_failed",
    now=404,
)
peer.close()
common.close()

# Actual remote peer and CDP request identity must match the permit.
(
    common,
    boundary,
    intent,
    lease,
    evidence,
    peer,
    transport,
    adapter,
) = context(now=500)
permit = adapter.prepare_request(
    request_event(),
    evidence,
    lease,
    intent,
    now=503,
)
permit.record_sent(12)
rejects(
    lambda: adapter.complete_response(
        permit,
        response_event(address=PUBLIC_V6),
        evidence,
        lease,
        intent,
        now=504,
    ),
    BrowserPeerAdapterDenied,
    "actual remote peer cannot differ from the pinned peer",
)
check(
    peer.events()[-1]["error_code"] == "peer_mismatch"
    and peer.events()[-1]["bytes_sent"] == 12,
    "peer mismatch retains measured progress",
)
boundary.complete(
    lease,
    intent,
    outcome="blocked",
    bytes_sent=12,
    error_code="peer_mismatch",
    now=505,
)
peer.close()
common.close()

# Cached and service-worker responses have no observable public peer.
for cache_field in ("disk_cache", "service_worker", "prefetch_cache"):
    (
        common,
        boundary,
        intent,
        lease,
        evidence,
        peer,
        transport,
        adapter,
    ) = context(now=600)
    permit = adapter.prepare_request(
        request_event(),
        evidence,
        lease,
        intent,
        now=603,
    )
    kwargs = {cache_field: True}
    rejects(
        lambda kwargs=kwargs: adapter.complete_response(
            permit,
            response_event(**kwargs),
            evidence,
            lease,
            intent,
            now=604,
        ),
        BrowserPeerAdapterDenied,
        f"{cache_field} response is rejected without peer evidence",
    )
    check(
        peer.events()[-1]["error_code"] == "response_peer_unobservable",
        f"{cache_field} response is audited as unobservable",
    )
    boundary.complete(
        lease,
        intent,
        outcome="blocked",
        bytes_sent=0,
        error_code="response_peer_unobservable",
        now=605,
    )
    peer.close()
    common.close()

# Byte ceiling remains the common request ceiling and is measured after pinning.
(
    common,
    boundary,
    intent,
    lease,
    evidence,
    peer,
    transport,
    adapter,
) = context(now=700, max_bytes=16)
permit = adapter.prepare_request(
    request_event(),
    evidence,
    lease,
    intent,
    now=703,
)
check(permit.record_sent(16) == 16, "permit allows the exact common byte ceiling")
rejects(
    lambda: permit.record_sent(1),
    ResearchExternalBlocked,
    "first byte above the common ceiling is blocked",
)
rejects(
    lambda: adapter.abort_request(
        permit,
        evidence,
        lease,
        intent,
        error_code="byte_budget_exceeded",
        now=704,
    ),
    BrowserPeerAdapterDenied,
    "byte budget failure terminalizes the permit",
)
check(
    peer.events()[-1]["bytes_sent"] == 16
    and peer.events()[-1]["error_code"] == "byte_budget_exceeded",
    "terminal audit records actual bytes at the ceiling",
)
boundary.complete(
    lease,
    intent,
    outcome="blocked",
    bytes_sent=16,
    error_code="byte_budget_exceeded",
    now=705,
)
peer.close()
common.close()

# A terminal common receipt invalidates a prepared browser permit.
(
    common,
    boundary,
    intent,
    lease,
    evidence,
    peer,
    transport,
    adapter,
) = context(now=800)
permit = adapter.prepare_request(
    request_event(),
    evidence,
    lease,
    intent,
    now=803,
)
boundary.complete(
    lease,
    intent,
    outcome="blocked",
    bytes_sent=0,
    error_code="cancelled_before_response",
    now=804,
)
rejects(
    lambda: adapter.complete_response(
        permit,
        response_event(),
        evidence,
        lease,
        intent,
        now=805,
    ),
    BrowserPeerAdapterDenied,
    "terminal common claim blocks later CDP completion",
)
check(
    peer.events()[-1]["error_code"] == "claim_inactive",
    "inactive common claim is visible in peer audit",
)
peer.close()
common.close()

# Cleanup is part of the security boundary.
failing_release = FakeTransport(fail_release=True)
(
    common,
    boundary,
    intent,
    lease,
    evidence,
    peer,
    transport,
    adapter,
) = context(now=900, transport=failing_release)
permit = adapter.prepare_request(
    request_event(),
    evidence,
    lease,
    intent,
    now=903,
)
rejects(
    lambda: adapter.complete_response(
        permit,
        response_event(),
        evidence,
        lease,
        intent,
        now=904,
    ),
    BrowserPeerAdapterDenied,
    "transport release failure cannot produce success",
)
check(
    peer.events()[-1]["error_code"] == "transport_release_failed",
    "transport release failure is terminally audited",
)
boundary.complete(
    lease,
    intent,
    outcome="blocked",
    bytes_sent=0,
    error_code="transport_release_failed",
    now=905,
)
peer.close()
common.close()

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
