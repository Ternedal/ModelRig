from __future__ import annotations

import hashlib
import json
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path

from app.data_sharing import (
    DataSharingContractError,
    DataSharingDenied,
    DataSharingLedger,
)
from app.research_claim_evidence import (
    CLAIM_EVIDENCE_SCHEMA,
    DataSharingClaimEvidence,
    VerifiableDataSharingLedger,
    VerifiableResearchSharingBoundary,
)
from app.research_data_sharing import ResearchSharingIntent
from app.research_egress import EgressPlan
from app.research_sharing_boundary import ResearchSharingBoundaryContractError

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
RAW_PAYLOAD = b"public research claim evidence sentinel"
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
    lambda: VerifiableResearchSharingBoundary(
        DataSharingLedger(),
        mode="enforce",
    ),
    ResearchSharingBoundaryContractError,
    "verifiable boundary rejects a non-verifiable ledger",
)


ledger = VerifiableDataSharingLedger(uuid_factory=UUIDs())
boundary = VerifiableResearchSharingBoundary(ledger, mode="enforce")
lease = boundary.prepare(INTENT, now=100, receipt_ttl_seconds=30)
evidence = boundary.claim(lease, INTENT, now=101)

check(evidence.schema == CLAIM_EVIDENCE_SCHEMA, "claim evidence is versioned")
check(evidence.receipt_id == lease.receipt.receipt_id, "claim binds exact receipt")
check(evidence.request_digest == INTENT.to_request().digest, "claim binds exact request")
check(evidence.max_bytes == PLAN.max_bytes, "claim binds exact byte ceiling")
check(evidence.claimed_at == 101 and evidence.expires_at == 130, "claim binds lifecycle times")
check(evidence.to_dict()["claimed_at"].endswith("Z"), "claim serialization uses UTC")
boundary.verify_claim(evidence, lease, INTENT, now=102)
check(True, "fresh in-flight evidence verifies")

rejects(
    lambda: boundary.claim(lease, INTENT, now=102),
    DataSharingDenied,
    "claim evidence remains one use",
)

changed_intent = replace(INTENT, summary=RAW_SUMMARY + " changed")
rejects(
    lambda: boundary.verify_claim(evidence, lease, changed_intent, now=102),
    DataSharingDenied,
    "changed intent cannot reuse claim evidence",
)
rejects(
    lambda: ledger.verify_claim(
        replace(evidence, claimed_at=102),
        lease.receipt,
        INTENT.to_request(),
        now=102,
    ),
    DataSharingDenied,
    "forged claim time is rejected",
)
rejects(
    lambda: ledger.verify_claim(
        replace(evidence, max_bytes=4095),
        lease.receipt,
        INTENT.to_request(),
        now=102,
    ),
    DataSharingDenied,
    "forged byte ceiling is rejected",
)
rejects(
    lambda: DataSharingClaimEvidence(
        receipt_id=evidence.receipt_id,
        request_digest=evidence.request_digest,
        max_bytes=evidence.max_bytes,
        claimed_at=True,
        expires_at=evidence.expires_at,
    ),
    DataSharingContractError,
    "boolean claim timestamp is rejected",
)
rejects(
    lambda: replace(evidence, schema="unknown"),
    DataSharingContractError,
    "unknown claim schema is rejected",
)

ledger.complete(
    lease.receipt,
    INTENT.to_request(),
    outcome="completed",
    bytes_sent=128,
    now=103,
)
rejects(
    lambda: boundary.verify_claim(evidence, lease, INTENT, now=104),
    DataSharingDenied,
    "terminal receipt invalidates claim evidence",
)

serialized = json.dumps(
    {
        "evidence": evidence.to_dict(),
        "events": ledger.recent_events(50),
    },
    ensure_ascii=False,
)
check(RAW_PURPOSE not in serialized, "claim material excludes raw purpose")
check(RAW_SUMMARY not in serialized, "claim material excludes raw summary")
check(RAW_PAYLOAD.decode() not in serialized, "claim material excludes raw payload")
ledger.close()


# Expiry is fail closed even if the row remains in flight.
ledger = VerifiableDataSharingLedger(uuid_factory=UUIDs())
boundary = VerifiableResearchSharingBoundary(ledger, mode="enforce")
lease = boundary.prepare(INTENT, now=200, receipt_ttl_seconds=5)
evidence = boundary.claim(lease, INTENT, now=201)
rejects(
    lambda: boundary.verify_claim(evidence, lease, INTENT, now=205),
    DataSharingDenied,
    "expired in-flight evidence is rejected",
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


# Revocation before claim cannot mint evidence.
private_intent = replace(
    INTENT,
    plan=replace(
        PLAN,
        sensitivity="private",
        purpose="Use one selected private excerpt for controlled research",
        payload_sha256=hashlib.sha256(b"private excerpt").hexdigest(),
    ),
    summary="A bounded excerpt selected by the user.",
)
ledger = VerifiableDataSharingLedger(uuid_factory=UUIDs())
boundary = VerifiableResearchSharingBoundary(ledger, mode="enforce")
request = private_intent.to_request()
proposal = ledger.propose(request, now=300, ttl_seconds=30)
ledger.approve(proposal.permission_id, actor="Anders", now=301)
lease = boundary.prepare(
    private_intent,
    permission_id=proposal.permission_id,
    now=302,
    receipt_ttl_seconds=20,
)
ledger.revoke(proposal.permission_id, actor="Anders", now=303)
rejects(
    lambda: boundary.claim(lease, private_intent, now=304),
    DataSharingDenied,
    "revocation before claim cannot mint evidence",
)
ledger.close()


# Evidence is durable and independently verifiable after reopening the ledger.
with tempfile.TemporaryDirectory() as temp:
    path = Path(temp) / "sharing.db"
    first = VerifiableDataSharingLedger(str(path), uuid_factory=UUIDs())
    first_boundary = VerifiableResearchSharingBoundary(first, mode="enforce")
    lease = first_boundary.prepare(INTENT, now=400, receipt_ttl_seconds=30)
    evidence = first_boundary.claim(lease, INTENT, now=401)
    first.close()

    reopened = VerifiableDataSharingLedger(str(path), uuid_factory=UUIDs())
    reopened_boundary = VerifiableResearchSharingBoundary(reopened, mode="enforce")
    reopened_boundary.verify_claim(evidence, lease, INTENT, now=402)
    check(True, "claim evidence survives ledger reopen")
    reopened.complete(
        lease.receipt,
        INTENT.to_request(),
        outcome="failed",
        bytes_sent=7,
        error_code="fixture_failure",
        now=403,
    )
    rejects(
        lambda: reopened_boundary.verify_claim(evidence, lease, INTENT, now=404),
        DataSharingDenied,
        "durable terminal transition invalidates evidence",
    )
    reopened.close()


print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
