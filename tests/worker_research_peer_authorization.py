from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import replace

from app.data_sharing import DataSharingDenied
from app.research_claim_evidence import (
    DataSharingClaimEvidence,
    VerifiableDataSharingLedger,
    VerifiableResearchSharingBoundary,
)
from app.research_contract import canonicalize_url
from app.research_data_sharing import ResearchSharingIntent
from app.research_egress import EgressPlan
from app.research_peer_authorization import (
    PEER_AUTHORIZATION_SCHEMA,
    ResearchPeerAuthorization,
    ResearchPeerAuthorizationBridge,
    ResearchPeerAuthorizationContractError,
    ResearchPeerAuthorizationDenied,
)

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
RAW_PAYLOAD = b"public peer authorization sentinel"
RAW_URL = "https://example.com/releases/peer-bridge?channel=stable#section"
PLAN = EgressPlan(
    destination="browser-use",
    purpose=RAW_PURPOSE,
    payload_sha256=hashlib.sha256(RAW_PAYLOAD).hexdigest(),
    sensitivity="public",
    allowed_domains=("example.com",),
    max_bytes=4096,
)
INTENT = ResearchSharingIntent(plan=PLAN, summary=RAW_SUMMARY)


rejects(
    lambda: ResearchPeerAuthorizationBridge(object()),
    ResearchPeerAuthorizationContractError,
    "bridge requires the verifiable boundary",
)

ledger = VerifiableDataSharingLedger(uuid_factory=UUIDs())
boundary = VerifiableResearchSharingBoundary(ledger, mode="enforce")
bridge = ResearchPeerAuthorizationBridge(boundary)
lease = boundary.prepare(INTENT, now=100, receipt_ttl_seconds=30)

# An issued receipt is not enough. A forged-looking claim object cannot bridge
# while the authoritative row is still merely authorized.
preclaim = DataSharingClaimEvidence(
    receipt_id=lease.receipt.receipt_id,
    request_digest=lease.receipt.request_digest,
    max_bytes=lease.receipt.max_bytes,
    claimed_at=101,
    expires_at=lease.receipt.expires_at,
)
rejects(
    lambda: bridge.prepare(preclaim, lease, INTENT, RAW_URL, now=102),
    ResearchPeerAuthorizationDenied,
    "issued receipt without atomic claim evidence is rejected",
)

evidence = boundary.claim(lease, INTENT, now=103)
authorization = bridge.prepare(evidence, lease, INTENT, RAW_URL, now=104)
canonical = canonicalize_url(RAW_URL)

check(authorization.schema == PEER_AUTHORIZATION_SCHEMA, "authorization is versioned")
check(authorization.authorization_id.startswith("rpa_"), "authorization has stable id")
check(len(authorization.digest) == 64, "authorization has canonical digest")
check(authorization.claim_receipt_id == evidence.receipt_id, "authorization binds claim receipt")
check(authorization.request_digest == INTENT.to_request().digest, "authorization binds common request")
check(authorization.legacy_plan_digest == PLAN.digest, "authorization binds legacy plan")
check(
    authorization.domain_scope_sha256 == INTENT.domain_scope_sha256,
    "authorization binds normalized domain scope",
)
check(
    authorization.url_sha256 == hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    "authorization binds canonical URL hash",
)
check(authorization.host == "example.com" and authorization.port == 443, "target host and port are explicit")
check(authorization.max_bytes == PLAN.max_bytes, "authorization binds exact byte ceiling")
check(
    authorization.claimed_at == evidence.claimed_at
    and authorization.expires_at == evidence.expires_at,
    "authorization cannot outlive claim evidence",
)
bridge.verify(authorization, evidence, lease, INTENT, RAW_URL, now=105)
check(True, "active exact authorization verifies")
check(
    bridge.prepare(evidence, lease, INTENT, RAW_URL, now=105) == authorization,
    "same claim and URL derive deterministic authorization",
)

serialized = json.dumps(authorization.to_dict(), ensure_ascii=False)
check(RAW_PURPOSE not in serialized, "serialized authorization excludes raw purpose")
check(RAW_SUMMARY not in serialized, "serialized authorization excludes raw summary")
check(RAW_PAYLOAD.decode() not in serialized, "serialized authorization excludes raw payload")
check("/releases/peer-bridge" not in serialized, "serialized authorization excludes URL path")
check("channel=stable" not in serialized, "serialized authorization excludes URL query")

rejects(
    lambda: bridge.prepare(
        evidence,
        lease,
        INTENT,
        "https://outside.example.net/release",
        now=105,
    ),
    ResearchPeerAuthorizationDenied,
    "off-scope domain is rejected before DNS",
)
rejects(
    lambda: bridge.verify(
        authorization,
        evidence,
        lease,
        INTENT,
        "https://example.com/a-different-path",
        now=105,
    ),
    ResearchPeerAuthorizationDenied,
    "changed URL cannot reuse authorization",
)
rejects(
    lambda: bridge.verify(
        replace(authorization, max_bytes=4095),
        evidence,
        lease,
        INTENT,
        RAW_URL,
        now=105,
    ),
    ResearchPeerAuthorizationDenied,
    "forged byte ceiling is rejected",
)
rejects(
    lambda: bridge.verify(
        replace(authorization, host="evil.example"),
        evidence,
        lease,
        INTENT,
        RAW_URL,
        now=105,
    ),
    ResearchPeerAuthorizationDenied,
    "forged host is rejected",
)
rejects(
    lambda: replace(authorization, schema="unknown"),
    ResearchPeerAuthorizationContractError,
    "unknown authorization schema is rejected",
)
rejects(
    lambda: replace(authorization, port=True),
    ResearchPeerAuthorizationContractError,
    "boolean port is rejected",
)

changed_intent = replace(INTENT, summary=RAW_SUMMARY + " changed")
rejects(
    lambda: bridge.verify(
        authorization,
        evidence,
        lease,
        changed_intent,
        RAW_URL,
        now=105,
    ),
    ResearchPeerAuthorizationDenied,
    "changed common request cannot reuse authorization",
)

ledger.complete(
    lease.receipt,
    INTENT.to_request(),
    outcome="blocked",
    bytes_sent=0,
    error_code="peer_not_started",
    now=106,
)
rejects(
    lambda: bridge.verify(authorization, evidence, lease, INTENT, RAW_URL, now=107),
    ResearchPeerAuthorizationDenied,
    "terminal common receipt invalidates peer authorization",
)
ledger.close()

# Claim expiry is checked through the authoritative ledger before URL handling.
ledger = VerifiableDataSharingLedger(uuid_factory=UUIDs())
boundary = VerifiableResearchSharingBoundary(ledger, mode="enforce")
bridge = ResearchPeerAuthorizationBridge(boundary)
lease = boundary.prepare(INTENT, now=200, receipt_ttl_seconds=5)
evidence = boundary.claim(lease, INTENT, now=201)
rejects(
    lambda: bridge.prepare(evidence, lease, INTENT, RAW_URL, now=205),
    ResearchPeerAuthorizationDenied,
    "expired claim cannot derive peer authorization",
)
ledger.complete(
    lease.receipt,
    INTENT.to_request(),
    outcome="blocked",
    bytes_sent=0,
    error_code="expired_before_peer",
    now=205,
)
ledger.close()

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
