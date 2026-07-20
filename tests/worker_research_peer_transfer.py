from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import replace

from app.research_claim_evidence import (
    VerifiableDataSharingLedger,
    VerifiableResearchSharingBoundary,
)
from app.research_data_sharing import ResearchSharingIntent
from app.research_egress import EgressPlan
from app.research_peer_authorization import ResearchPeerAuthorizationBridge
from app.research_peer_transfer import (
    PEER_TRANSFER_SCHEMA,
    ResearchPeerTransfer,
    ResearchPeerTransferContractError,
    ResearchPeerTransferDenied,
    ResearchPeerTransferLedger,
)
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


RAW_PURPOSE = "Retrieve one public release-note fixture"
RAW_SUMMARY = "A public research query without local document content."
RAW_PAYLOAD = b"peer-bound byte meter sentinel"
RAW_URL = "https://example.com/releases/peer-transfer?channel=stable#section"
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


def claimed_context(*, max_bytes: int = 4096, now: int = 100):
    common = VerifiableDataSharingLedger(uuid_factory=UUIDs())
    boundary = VerifiableResearchSharingBoundary(common, mode="enforce")
    bridge = ResearchPeerAuthorizationBridge(boundary)
    intent = make_intent(max_bytes)
    lease = boundary.prepare(intent, now=now, receipt_ttl_seconds=60)
    evidence = boundary.claim(lease, intent, now=now + 1)
    authorization = bridge.prepare(
        evidence,
        lease,
        intent,
        RAW_URL,
        now=now + 2,
    )
    return common, boundary, bridge, intent, lease, evidence, authorization


common, boundary, bridge, intent, lease, evidence, authorization = claimed_context()
rejects(
    lambda: ResearchPeerTransferLedger(object(), lambda _host, _port: [PUBLIC_V4]),
    ResearchPeerTransferContractError,
    "ledger requires the common authorization bridge",
)
rejects(
    lambda: ResearchPeerTransferLedger(bridge, object()),
    ResearchPeerTransferContractError,
    "ledger requires an injected resolver",
)
rejects(
    lambda: ResearchPeerTransfer(object(), token=object()),
    ResearchPeerTransferContractError,
    "transfer cannot be forged outside the ledger",
)

peer = ResearchPeerTransferLedger(
    bridge,
    lambda _host, _port: [PUBLIC_V6, PUBLIC_V4, PUBLIC_V4],
    uuid_factory=UUIDs(),
)
binding = peer.issue(
    authorization,
    evidence,
    lease,
    intent,
    RAW_URL,
    now=103,
    ttl_seconds=20,
)

check(binding.schema == PEER_TRANSFER_SCHEMA, "binding is versioned")
check(binding.binding_id.startswith("rpt_"), "binding has a one-use id")
check(
    binding.authorization_id == authorization.authorization_id
    and binding.authorization_digest == authorization.digest,
    "binding is tied to the exact common peer authorization",
)
check(
    binding.claim_receipt_id == evidence.receipt_id
    and binding.request_digest == intent.to_request().digest,
    "binding preserves common receipt and request identity",
)
check(
    binding.host == "example.com"
    and binding.port == 443
    and binding.addresses == (PUBLIC_V4, PUBLIC_V6),
    "DNS answers are public, deduplicated and deterministic",
)
check(
    binding.selected_address == PUBLIC_V4,
    "the caller receives one exact connected-peer target",
)
check(
    binding.max_bytes == intent.to_request().max_bytes,
    "binding carries the exact common byte ceiling",
)
check(
    binding.expires_at <= authorization.expires_at,
    "DNS binding cannot outlive the common claim",
)

serialized = json.dumps(binding.to_dict(), ensure_ascii=False)
check(RAW_PURPOSE not in serialized, "binding excludes raw purpose")
check(RAW_SUMMARY not in serialized, "binding excludes raw summary")
check(RAW_PAYLOAD.decode() not in serialized, "binding excludes raw content")
check("/releases/peer-transfer" not in serialized, "binding excludes URL path")
check("channel=stable" not in serialized, "binding excludes URL query")

rejects(
    lambda: peer.issue(
        authorization,
        evidence,
        lease,
        intent,
        RAW_URL,
        now=104,
    ),
    ResearchPeerTransferDenied,
    "one authorization cannot create a second DNS binding",
)
rejects(
    lambda: peer.claim(
        binding,
        authorization,
        evidence,
        lease,
        intent,
        "https://example.com/changed",
        now=104,
    ),
    ResearchPeerTransferDenied,
    "changed URL cannot claim the binding",
)

transfer = peer.claim(
    binding,
    authorization,
    evidence,
    lease,
    intent,
    RAW_URL,
    now=104,
)
check(
    transfer.selected_address == binding.selected_address,
    "claim exposes only the selected DNS peer",
)
check(transfer.record_sent(64) == 64, "meter records confirmed outbound progress")
check(transfer.record_sent(32) == 96, "meter accumulates exact sent bytes")
rejects(
    lambda: peer.claim(
        binding,
        authorization,
        evidence,
        lease,
        intent,
        RAW_URL,
        now=105,
    ),
    ResearchPeerTransferDenied,
    "peer binding is atomically claimable once",
)
peer.complete(
    transfer,
    authorization,
    evidence,
    lease,
    intent,
    RAW_URL,
    outcome="connected",
    peer_address=PUBLIC_V4,
    now=106,
)
rejects(
    lambda: transfer.record_sent(1),
    ResearchPeerTransferDenied,
    "terminal transfer cannot record more bytes",
)

events = peer.events()
check(
    [event["event_type"] for event in events] == ["issued", "claimed", "finished"],
    "audit records the exact one-use lifecycle",
)
check(
    events[-1]["outcome"] == "connected"
    and events[-1]["bytes_sent"] == 96
    and events[-1]["peer_address"] == PUBLIC_V4,
    "terminal audit binds actual peer and measured bytes",
)
event_json = json.dumps(events, ensure_ascii=False)
check(RAW_PURPOSE not in event_json, "audit excludes raw purpose")
check(RAW_SUMMARY not in event_json, "audit excludes raw summary")
check(RAW_PAYLOAD.decode() not in event_json, "audit excludes raw content")
check("/releases/peer-transfer" not in event_json, "audit excludes URL path")
peer.close()
boundary.complete(
    lease,
    intent,
    outcome="completed",
    bytes_sent=96,
    now=107,
)
common.close()

# Every DNS answer must be public. A mixed answer cannot smuggle a private peer.
common, boundary, bridge, intent, lease, evidence, authorization = claimed_context(
    now=200
)
peer = ResearchPeerTransferLedger(
    bridge,
    lambda _host, _port: [PUBLIC_V4, "127.0.0.1"],
)
rejects(
    lambda: peer.issue(
        authorization,
        evidence,
        lease,
        intent,
        RAW_URL,
        now=203,
    ),
    ResearchPeerTransferDenied,
    "mixed public and private DNS answers fail closed",
)
peer.close()
boundary.complete(
    lease,
    intent,
    outcome="blocked",
    bytes_sent=0,
    error_code="dns_private_answer",
    now=204,
)
common.close()

# The actual connected peer must equal the selected address.
common, boundary, bridge, intent, lease, evidence, authorization = claimed_context(
    now=300
)
peer = ResearchPeerTransferLedger(
    bridge,
    lambda _host, _port: [PUBLIC_V4, PUBLIC_V6],
    uuid_factory=UUIDs(),
)
binding = peer.issue(
    authorization,
    evidence,
    lease,
    intent,
    RAW_URL,
    now=303,
)
transfer = peer.claim(
    binding,
    authorization,
    evidence,
    lease,
    intent,
    RAW_URL,
    now=304,
)
transfer.record_sent(12)
rejects(
    lambda: peer.complete(
        transfer,
        authorization,
        evidence,
        lease,
        intent,
        RAW_URL,
        outcome="connected",
        peer_address=PUBLIC_V6,
        now=305,
    ),
    ResearchPeerTransferDenied,
    "transport cannot substitute another resolved public peer",
)
check(
    peer.events()[-1]["outcome"] == "blocked"
    and peer.events()[-1]["error_code"] == "peer_mismatch"
    and peer.events()[-1]["bytes_sent"] == 12,
    "peer mismatch is terminal and retains measured progress",
)
peer.close()
boundary.complete(
    lease,
    intent,
    outcome="blocked",
    bytes_sent=12,
    error_code="peer_mismatch",
    now=306,
)
common.close()

# Byte budget is enforced by the transfer created after the one-use claim.
common, boundary, bridge, intent, lease, evidence, authorization = claimed_context(
    max_bytes=16,
    now=400,
)
peer = ResearchPeerTransferLedger(
    bridge,
    lambda _host, _port: [PUBLIC_V4],
    uuid_factory=UUIDs(),
)
binding = peer.issue(
    authorization,
    evidence,
    lease,
    intent,
    RAW_URL,
    now=403,
)
transfer = peer.claim(
    binding,
    authorization,
    evidence,
    lease,
    intent,
    RAW_URL,
    now=404,
)
check(transfer.record_sent(16) == 16, "meter permits the exact byte ceiling")
rejects(
    lambda: transfer.record_sent(1),
    ResearchExternalBlocked,
    "meter blocks the first byte above the common ceiling",
)
rejects(
    lambda: peer.complete(
        transfer,
        authorization,
        evidence,
        lease,
        intent,
        RAW_URL,
        outcome="blocked",
        peer_address=PUBLIC_V4,
        error_code="byte_budget_exceeded",
        now=405,
    ),
    ResearchPeerTransferDenied,
    "blocked byte-budget outcome remains fail-closed",
)
check(
    peer.events()[-1]["bytes_sent"] == 16
    and peer.events()[-1]["error_code"] == "byte_budget_exceeded",
    "audit uses measured bytes rather than payload estimates",
)
peer.close()
boundary.complete(
    lease,
    intent,
    outcome="blocked",
    bytes_sent=16,
    error_code="byte_budget_exceeded",
    now=406,
)
common.close()

# A terminal common receipt invalidates an issued peer binding before claim.
common, boundary, bridge, intent, lease, evidence, authorization = claimed_context(
    now=500
)
peer = ResearchPeerTransferLedger(
    bridge,
    lambda _host, _port: [PUBLIC_V4],
    uuid_factory=UUIDs(),
)
binding = peer.issue(
    authorization,
    evidence,
    lease,
    intent,
    RAW_URL,
    now=503,
)
boundary.complete(
    lease,
    intent,
    outcome="blocked",
    bytes_sent=0,
    error_code="cancelled_before_connect",
    now=504,
)
rejects(
    lambda: peer.claim(
        binding,
        authorization,
        evidence,
        lease,
        intent,
        RAW_URL,
        now=505,
    ),
    ResearchPeerTransferDenied,
    "terminal common receipt invalidates issued peer binding",
)
peer.close()
common.close()

# Expired DNS binding is terminal and cannot be revived.
common, boundary, bridge, intent, lease, evidence, authorization = claimed_context(
    now=600
)
peer = ResearchPeerTransferLedger(
    bridge,
    lambda _host, _port: [PUBLIC_V4],
    uuid_factory=UUIDs(),
)
binding = peer.issue(
    authorization,
    evidence,
    lease,
    intent,
    RAW_URL,
    now=603,
    ttl_seconds=1,
)
rejects(
    lambda: peer.claim(
        binding,
        authorization,
        evidence,
        lease,
        intent,
        RAW_URL,
        now=604,
    ),
    ResearchPeerTransferDenied,
    "expired DNS binding cannot be claimed",
)
check(
    peer.events()[-1]["event_type"] == "expired"
    and peer.events()[-1]["error_code"] == "expired",
    "binding expiry is recorded as a terminal blocked event",
)
peer.close()
boundary.complete(
    lease,
    intent,
    outcome="blocked",
    bytes_sent=0,
    error_code="peer_binding_expired",
    now=604,
)
common.close()

rejects(
    lambda: replace(binding, schema="unknown"),
    ResearchPeerTransferContractError,
    "unknown peer-transfer schema is rejected",
)
rejects(
    lambda: replace(binding, selected_address="127.0.0.1"),
    ResearchPeerTransferContractError,
    "forged private selected peer is rejected",
)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
