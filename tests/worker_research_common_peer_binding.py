from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import replace

from app.research_claim_evidence import (
    VerifiableDataSharingLedger,
    VerifiableResearchSharingBoundary,
)
from app.research_common_peer_binding import (
    BoundOutboundByteMeter,
    PEER_BINDING_SCHEMA,
    PEER_CLAIM_SCHEMA,
    ResearchCommonPeerContractError,
    ResearchCommonPeerDenied,
    ResearchCommonPeerLedger,
)
from app.research_data_sharing import ResearchSharingIntent
from app.research_egress import EgressPlan
from app.research_peer_authorization import ResearchPeerAuthorizationBridge
from app.research_sharing_execution import OutboundByteMeter, ResearchExternalBlocked

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


class Resolver:
    def __init__(self, values=None, error: Exception | None = None) -> None:
        self.values = ["8.8.8.8", "1.1.1.1", "1.1.1.1"] if values is None else values
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def __call__(self, host: str, port: int):
        self.calls.append((host, port))
        if self.error is not None:
            raise self.error
        return self.values


RAW_PURPOSE = "Retrieve one public release-note fixture"
RAW_SUMMARY = "A public research query without local document content."
RAW_PAYLOAD = b"public connected-peer sentinel"
RAW_URL = "https://example.com/releases/common-peer?channel=stable#section"
PLAN = EgressPlan(
    destination="browser-use",
    purpose=RAW_PURPOSE,
    payload_sha256=hashlib.sha256(RAW_PAYLOAD).hexdigest(),
    sensitivity="public",
    allowed_domains=("example.com",),
    max_bytes=4096,
)
INTENT = ResearchSharingIntent(plan=PLAN, summary=RAW_SUMMARY)


def context(*, resolver: Resolver | None = None, now: int = 100, receipt_ttl: int = 90):
    common = VerifiableDataSharingLedger(uuid_factory=UUIDs())
    boundary = VerifiableResearchSharingBoundary(common, mode="enforce")
    bridge = ResearchPeerAuthorizationBridge(boundary)
    lease = boundary.prepare(INTENT, now=now, receipt_ttl_seconds=receipt_ttl)
    evidence = boundary.claim(lease, INTENT, now=now + 1)
    authorization = bridge.prepare(evidence, lease, INTENT, RAW_URL, now=now + 2)
    dns = resolver or Resolver()
    peers = ResearchCommonPeerLedger(dns, bridge, uuid_factory=UUIDs())
    return common, boundary, lease, evidence, authorization, dns, peers


rejects(
    lambda: ResearchCommonPeerLedger(object(), object()),
    ResearchCommonPeerContractError,
    "ledger requires callable resolver and exact bridge",
)

# Happy path: active common claim -> injected DNS -> one-use claim -> exact peer ->
# bounded byte meter -> terminal privacy-safe audit.
common, boundary, lease, evidence, authorization, resolver, peers = context()
binding = peers.issue(
    authorization, evidence, lease, INTENT, RAW_URL, now=103, ttl_seconds=30
)
check(binding.schema == PEER_BINDING_SCHEMA, "binding is versioned")
check(binding.binding_id.startswith("rpb_"), "binding has stable id")
check(binding.authorization_id == authorization.authorization_id, "binding owns exact authorization")
check(binding.authorization_digest == authorization.digest, "binding owns authorization digest")
check(binding.claim_receipt_id == evidence.receipt_id, "binding owns common claim receipt")
check(binding.request_digest == INTENT.to_request().digest, "binding owns common request")
check(binding.host == "example.com" and binding.port == 443, "binding owns exact host and port")
check(binding.addresses == ("1.1.1.1", "8.8.8.8"), "DNS answers are normalized and sorted")
check(binding.selected_address == "1.1.1.1", "selected peer is deterministic")
check(binding.max_bytes == PLAN.max_bytes, "binding owns exact byte ceiling")
check(binding.expires_at == 133, "binding TTL cannot exceed authorization")
check(resolver.calls == [("example.com", 443)], "resolver sees host and port only")

serialized = json.dumps(binding.to_dict(), ensure_ascii=False)
events_text = json.dumps(peers.events(), ensure_ascii=False)
for secret in (
    RAW_PURPOSE,
    RAW_SUMMARY,
    RAW_PAYLOAD.decode(),
    "/releases/common-peer",
    "channel=stable",
):
    check(secret not in serialized and secret not in events_text, f"audit excludes {secret!r}")

rejects(
    lambda: peers.issue(
        authorization, evidence, lease, INTENT, RAW_URL, now=104, ttl_seconds=30
    ),
    ResearchCommonPeerDenied,
    "one authorization cannot issue two bindings",
)
check(len(resolver.calls) == 1, "reused authorization is rejected before another DNS lookup")

rejects(
    lambda: peers.claim(
        binding,
        authorization,
        evidence,
        lease,
        INTENT,
        RAW_URL,
        OutboundByteMeter(4095),
        now=104,
    ),
    ResearchCommonPeerDenied,
    "claim rejects mismatched meter ceiling",
)
used_meter = OutboundByteMeter(4096)
used_meter.record_sent(1)
rejects(
    lambda: peers.claim(
        binding,
        authorization,
        evidence,
        lease,
        INTENT,
        RAW_URL,
        used_meter,
        now=104,
    ),
    ResearchCommonPeerDenied,
    "claim rejects bytes recorded before peer proof",
)

meter = OutboundByteMeter(4096)
claim = peers.claim(
    binding, authorization, evidence, lease, INTENT, RAW_URL, meter, now=104
)
check(claim.schema == PEER_CLAIM_SCHEMA, "peer claim is versioned")
check(claim.binding_id == binding.binding_id, "claim owns exact binding")
check(claim.authorization_digest == authorization.digest, "claim owns authorization digest")
check(claim.selected_address == binding.selected_address, "claim owns selected peer")
rejects(
    lambda: peers.claim(
        binding, authorization, evidence, lease, INTENT, RAW_URL, meter, now=105
    ),
    ResearchCommonPeerDenied,
    "binding claim is one-use",
)

bound = peers.connect(
    claim,
    binding,
    authorization,
    evidence,
    lease,
    INTENT,
    RAW_URL,
    meter,
    "1.1.1.1",
    now=105,
)
check(isinstance(bound, BoundOutboundByteMeter), "exact connected peer unlocks bound meter")
check(bound.max_bytes == 4096 and bound.bytes_sent == 0, "bound meter preserves ceiling")
check(bound.record_sent(512) == 512, "transport-confirmed bytes are delegated")
rejects(
    lambda: bound.record_sent(4096),
    ResearchExternalBlocked,
    "bound meter retains outer byte ceiling",
)
peers.complete(
    binding,
    authorization,
    evidence,
    lease,
    INTENT,
    RAW_URL,
    bound,
    outcome="completed",
    now=106,
)
last = peers.events()[-1]
check(last["event_type"] == "finished", "peer binding becomes terminal")
check(last["outcome"] == "completed" and last["bytes_sent"] == 512, "audit owns measured bytes")
check(last["peer_address"] == "1.1.1.1", "audit owns verified peer address")
rejects(
    lambda: bound.record_sent(1),
    ResearchCommonPeerDenied,
    "terminal peer meter is sealed",
)
rejects(
    lambda: peers.complete(
        binding,
        authorization,
        evidence,
        lease,
        INTENT,
        RAW_URL,
        bound,
        outcome="completed",
        now=107,
    ),
    ResearchCommonPeerDenied,
    "terminal peer binding cannot complete twice",
)
common.close()
peers.close()

# Wrong connected peer terminalizes as blocked before a byte meter is exposed.
common, boundary, lease, evidence, authorization, resolver, peers = context(now=200)
binding = peers.issue(authorization, evidence, lease, INTENT, RAW_URL, now=203)
meter = OutboundByteMeter(4096)
claim = peers.claim(binding, authorization, evidence, lease, INTENT, RAW_URL, meter, now=204)
rejects(
    lambda: peers.connect(
        claim,
        binding,
        authorization,
        evidence,
        lease,
        INTENT,
        RAW_URL,
        meter,
        "8.8.8.8",
        now=205,
    ),
    ResearchCommonPeerDenied,
    "wrong connected peer is blocked",
)
last = peers.events()[-1]
check(last["outcome"] == "blocked" and last["error_code"] == "peer_mismatch", "peer mismatch is audited")
check(last["bytes_sent"] == 0, "peer mismatch cannot authorize bytes")
common.close()
peers.close()

# A connection failure may terminalize from claimed state, but never as success.
common, boundary, lease, evidence, authorization, resolver, peers = context(now=300)
binding = peers.issue(authorization, evidence, lease, INTENT, RAW_URL, now=303)
meter = OutboundByteMeter(4096)
peers.claim(binding, authorization, evidence, lease, INTENT, RAW_URL, meter, now=304)
rejects(
    lambda: peers.complete(
        binding,
        authorization,
        evidence,
        lease,
        INTENT,
        RAW_URL,
        meter,
        outcome="completed",
        now=305,
    ),
    ResearchCommonPeerDenied,
    "pre-connect state cannot report success",
)
peers.complete(
    binding,
    authorization,
    evidence,
    lease,
    INTENT,
    RAW_URL,
    meter,
    outcome="failed",
    error_code="connect_failed",
    now=305,
)
last = peers.events()[-1]
check(last["outcome"] == "failed" and last["bytes_sent"] == 0, "connect failure is zero-byte terminal")
common.close()
peers.close()

# Context is re-verified before DNS and terminal completion.
resolver = Resolver()
common, boundary, lease, evidence, authorization, resolver, peers = context(
    resolver=resolver, now=400
)
forged = replace(authorization, host="other.example.com")
rejects(
    lambda: peers.issue(forged, evidence, lease, INTENT, RAW_URL, now=403),
    ResearchCommonPeerDenied,
    "forged authorization is rejected before DNS",
)
check(resolver.calls == [], "invalid authorization cannot reach resolver")
binding = peers.issue(authorization, evidence, lease, INTENT, RAW_URL, now=403)
meter = OutboundByteMeter(4096)
claim = peers.claim(binding, authorization, evidence, lease, INTENT, RAW_URL, meter, now=404)
bound = peers.connect(
    claim,
    binding,
    authorization,
    evidence,
    lease,
    INTENT,
    RAW_URL,
    meter,
    binding.selected_address,
    now=405,
)
boundary.complete(
    lease,
    INTENT,
    outcome="blocked",
    bytes_sent=bound.bytes_sent,
    error_code="common_stopped",
    now=406,
)
rejects(
    lambda: peers.complete(
        binding,
        authorization,
        evidence,
        lease,
        INTENT,
        RAW_URL,
        bound,
        outcome="failed",
        error_code="operation_failed",
        now=407,
    ),
    ResearchCommonPeerDenied,
    "terminal common receipt invalidates peer completion",
)
common.close()
peers.close()

# DNS is fail closed and contains no implicit system resolver.
for values, label in (
    ([], "empty DNS"),
    (["127.0.0.1"], "loopback DNS"),
    (["10.0.0.1"], "private DNS"),
    (["1.1.1.1"] * 33, "oversized DNS answer"),
):
    resolver = Resolver(values=values)
    common, boundary, lease, evidence, authorization, resolver, peers = context(
        resolver=resolver, now=500
    )
    rejects(
        lambda: peers.issue(authorization, evidence, lease, INTENT, RAW_URL, now=503),
        ResearchCommonPeerDenied,
        f"{label} is rejected",
    )
    common.close()
    peers.close()

resolver = Resolver(error=RuntimeError("resolver details must not escape"))
common, boundary, lease, evidence, authorization, resolver, peers = context(
    resolver=resolver, now=600
)
rejects(
    lambda: peers.issue(authorization, evidence, lease, INTENT, RAW_URL, now=603),
    ResearchCommonPeerDenied,
    "resolver exception is normalized",
)
common.close()
peers.close()

# Binding expiry is shorter than the common receipt and is terminally audited.
common, boundary, lease, evidence, authorization, resolver, peers = context(now=700)
binding = peers.issue(
    authorization, evidence, lease, INTENT, RAW_URL, now=703, ttl_seconds=2
)
rejects(
    lambda: peers.claim(
        binding,
        authorization,
        evidence,
        lease,
        INTENT,
        RAW_URL,
        OutboundByteMeter(4096),
        now=705,
    ),
    ResearchCommonPeerDenied,
    "expired binding cannot be claimed",
)
last = peers.events()[-1]
check(last["outcome"] == "blocked" and last["error_code"] == "expired", "expiry is terminally audited")
common.close()
peers.close()

# Malformed standalone objects fail as contract errors, not authorization errors.
common, boundary, lease, evidence, authorization, resolver, peers = context(now=800)
binding = peers.issue(authorization, evidence, lease, INTENT, RAW_URL, now=803)
rejects(
    lambda: replace(binding, schema="unknown"),
    ResearchCommonPeerContractError,
    "unknown binding schema is rejected",
)
rejects(
    lambda: replace(binding, addresses=("127.0.0.1",)),
    ResearchCommonPeerContractError,
    "non-public serialized binding address is rejected",
)
rejects(
    lambda: replace(binding, port=True),
    ResearchCommonPeerContractError,
    "boolean binding port is rejected",
)
common.close()
peers.close()

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
