from __future__ import annotations

import hashlib
import uuid

from app.research_claim_evidence import VerifiableDataSharingLedger, VerifiableResearchSharingBoundary
from app.research_common_peer_binding import BoundOutboundByteMeter, ResearchCommonPeerDenied, ResearchCommonPeerLedger
from app.research_data_sharing import ResearchSharingIntent
from app.research_egress import EgressPlan
from app.research_peer_authorization import ResearchPeerAuthorizationBridge
from app.research_sharing_execution import OutboundByteMeter

passed = failed = 0


def check(value: bool, label: str) -> None:
    global passed, failed
    if value:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def denied(call, label: str) -> None:
    try:
        call()
    except ResearchCommonPeerDenied:
        check(True, label)
    else:
        check(False, label)


class UUIDs:
    def __init__(self) -> None:
        self.n = 0

    def __call__(self) -> uuid.UUID:
        self.n += 1
        return uuid.UUID(int=self.n)


PLAN = EgressPlan(
    destination="browser-use",
    purpose="Check peer meter consistency",
    payload_sha256=hashlib.sha256(b"peer meter consistency").hexdigest(),
    sensitivity="public",
    allowed_domains=("example.com",),
    max_bytes=1024,
)
INTENT = ResearchSharingIntent(plan=PLAN, summary="A public consistency fixture.")
URL = "https://example.com/consistency"


def setup(now: int):
    common = VerifiableDataSharingLedger(uuid_factory=UUIDs())
    boundary = VerifiableResearchSharingBoundary(common, mode="enforce")
    bridge = ResearchPeerAuthorizationBridge(boundary)
    lease = boundary.prepare(INTENT, now=now, receipt_ttl_seconds=60)
    evidence = boundary.claim(lease, INTENT, now=now + 1)
    authorization = bridge.prepare(evidence, lease, INTENT, URL, now=now + 2)
    peers = ResearchCommonPeerLedger(lambda host, port: ("1.1.1.1",), bridge, uuid_factory=UUIDs())
    binding = peers.issue(authorization, evidence, lease, INTENT, URL, now=now + 3)
    return common, lease, evidence, authorization, peers, binding


common, lease, evidence, authorization, peers, binding = setup(100)
original = OutboundByteMeter(1024)
claim = peers.claim(binding, authorization, evidence, lease, INTENT, URL, original, now=104)
replacement = OutboundByteMeter(1024)
denied(
    lambda: peers.connect(claim, binding, authorization, evidence, lease, INTENT, URL, replacement, binding.selected_address, now=105),
    "connect requires the same meter object that was claimed",
)
bound = peers.connect(claim, binding, authorization, evidence, lease, INTENT, URL, original, binding.selected_address, now=105)
check(bound.record_sent(17) == 17, "the claimed meter records bytes after peer proof")
other_bound = BoundOutboundByteMeter(
    OutboundByteMeter(1024),
    binding_id=binding.binding_id,
    authorization_digest=authorization.digest,
    peer_address=binding.selected_address,
)
denied(
    lambda: peers.complete(binding, authorization, evidence, lease, INTENT, URL, other_bound, outcome="completed", now=106),
    "completion requires the bound meter returned by this ledger",
)
peers.complete(binding, authorization, evidence, lease, INTENT, URL, bound, outcome="completed", now=106)
check(peers.events()[-1]["bytes_sent"] == 17, "terminal audit uses the original meter")
common.close()
peers.close()

common, lease, evidence, authorization, peers, binding = setup(200)
original = OutboundByteMeter(1024)
peers.claim(binding, authorization, evidence, lease, INTENT, URL, original, now=204)
denied(
    lambda: peers.complete(binding, authorization, evidence, lease, INTENT, URL, OutboundByteMeter(1024), outcome="failed", error_code="connect_failed", now=205),
    "pre-connect completion requires the claimed meter",
)
peers.complete(binding, authorization, evidence, lease, INTENT, URL, original, outcome="failed", error_code="connect_failed", now=205)
check(peers.events()[-1]["bytes_sent"] == 0, "zero-byte pre-connect audit uses the claimed meter")
common.close()
peers.close()

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
