from __future__ import annotations

import hashlib
import json
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path

from app.research_egress import EgressContractError, EgressDenied, EgressLedger, EgressPlan

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


payload = b"sample research request"
plan = EgressPlan(
    destination="browser-use",
    purpose="Retrieve the current public fixture for this request",
    payload_sha256=hashlib.sha256(payload).hexdigest(),
    sensitivity="private",
    allowed_domains=("*.Example.com.", "example.com", "example.com"),
    max_bytes=4096,
)
check(plan.allowed_domains == ("*.example.com", "example.com"), "domains normalize deterministically")
check(plan.purpose_sha256 == hashlib.sha256(plan.purpose.encode()).hexdigest(), "purpose is hash-bound")
check(len(plan.digest) == 64, "plan digest is SHA-256")
check("purpose" not in plan.digest_payload(), "digest payload excludes raw purpose")
check(plan.confirmation_payload()["purpose"] == plan.purpose, "confirmation payload remains human-readable")
check(replace(plan, max_bytes=4097).digest != plan.digest, "byte budget changes digest")
check(replace(plan, purpose=plan.purpose + " updated").digest != plan.digest, "purpose changes digest")
check(replace(plan, allowed_domains=("example.org",)).digest != plan.digest, "domain scope changes digest")

rejects(lambda: replace(plan, destination="Bad Destination"), EgressContractError, "invalid destination is rejected")
rejects(lambda: replace(plan, purpose=" "), EgressContractError, "empty purpose is rejected")
rejects(lambda: replace(plan, payload_sha256="ABC"), EgressContractError, "invalid payload hash is rejected")
rejects(lambda: replace(plan, sensitivity="unknown"), EgressContractError, "unknown sensitivity is rejected")
rejects(lambda: replace(plan, allowed_domains=()), EgressContractError, "empty domain scope is rejected")
rejects(lambda: replace(plan, allowed_domains=("localhost",)), EgressContractError, "local domain is rejected")
rejects(lambda: replace(plan, allowed_domains=("127.0.0.1",)), EgressContractError, "IP rule is rejected")
rejects(lambda: replace(plan, max_bytes=True), EgressContractError, "boolean byte budget is rejected")

ledger = EgressLedger(uuid_factory=UUIDs())
proposal = ledger.propose(plan, now=100, ttl_seconds=30)
check(proposal.status == "pending", "proposal starts pending")
check(proposal.plan_digest == plan.digest, "proposal binds the exact plan")
check(proposal.expires_at == 130, "proposal expiry is bounded")
rejects(lambda: ledger.approve("missing", actor="Anders", now=101), EgressDenied, "unknown proposal is rejected")
ledger.approve(proposal.proposal_id, actor="Anders", now=102)
rejects(lambda: ledger.approve(proposal.proposal_id, actor="Anders", now=103), EgressDenied, "approval is one-way")

receipt = ledger.authorize(plan, consent_id=proposal.proposal_id, now=104, receipt_ttl_seconds=20)
check(receipt.authorization == "consented", "private plan uses approved consent")
check(receipt.consent_id == proposal.proposal_id, "receipt links its consent")
check(receipt.plan_digest == plan.digest, "receipt binds exact plan digest")
rejects(lambda: ledger.authorize(plan, consent_id=proposal.proposal_id, now=105), EgressDenied, "consent is one-use")
rejects(lambda: ledger.claim(receipt, replace(plan, purpose=plan.purpose + " changed"), now=106), EgressDenied, "changed plan cannot claim receipt")
ledger.claim(receipt, plan, now=106)
rejects(lambda: ledger.claim(receipt, plan, now=107), EgressDenied, "receipt claim is one-use")
rejects(lambda: ledger.complete(receipt, plan, outcome="completed", bytes_sent=4097, now=108), EgressDenied, "byte ceiling is enforced")
rejects(lambda: ledger.complete(receipt, plan, outcome="completed", bytes_sent=1, error_code="network", now=108), EgressContractError, "successful outcome has no error code")
ledger.complete(receipt, plan, outcome="completed", bytes_sent=512, now=109)
rejects(lambda: ledger.complete(receipt, plan, outcome="completed", bytes_sent=512, now=110), EgressDenied, "completion is final")

second = ledger.propose(plan, now=200, ttl_seconds=30)
ledger.approve(second.proposal_id, actor="Anders", now=201)
rejects(lambda: ledger.authorize(replace(plan, allowed_domains=("example.org",)), consent_id=second.proposal_id, now=202), EgressDenied, "approval cannot authorize a changed domain set")
check(ledger.authorize(plan, consent_id=second.proposal_id, now=203).authorization == "consented", "failed mismatch does not consume approval")

pending = ledger.propose(plan, now=300, ttl_seconds=30)
rejects(lambda: ledger.authorize(plan, consent_id=pending.proposal_id, now=301), EgressDenied, "pending proposal cannot authorize")
ledger.deny(pending.proposal_id, now=302)
rejects(lambda: ledger.authorize(plan, consent_id=pending.proposal_id, now=303), EgressDenied, "denied proposal cannot authorize")
expired = ledger.propose(plan, now=400, ttl_seconds=5)
rejects(lambda: ledger.approve(expired.proposal_id, actor="Anders", now=405), EgressDenied, "proposal expires at boundary")
rejects(lambda: ledger.authorize(plan, now=500), EgressDenied, "private plan requires consent")

restricted = replace(plan, sensitivity="secret")
rejects(lambda: ledger.propose(restricted, now=500), EgressDenied, "restricted sensitivity cannot be proposed")
rejects(lambda: ledger.authorize(restricted, consent_id="any", now=500), EgressDenied, "restricted sensitivity cannot be authorized")

public_plan = replace(plan, sensitivity="public", purpose="Retrieve public release notes")
public_receipt = ledger.authorize(public_plan, now=600, receipt_ttl_seconds=10)
check(public_receipt.authorization == "automatic", "public plan uses automatic authorization")
rejects(lambda: ledger.authorize(public_plan, consent_id=proposal.proposal_id, now=600), EgressContractError, "automatic authorization rejects unrelated consent")
ledger.claim(public_receipt, public_plan, now=601)
ledger.complete(public_receipt, public_plan, outcome="blocked", bytes_sent=0, error_code="peer_mismatch", now=602)

operational = replace(plan, sensitivity="operational", purpose="Retrieve public service status")
operational_receipt = ledger.authorize(operational, now=700)
check(operational_receipt.authorization == "automatic", "operational plan follows existing sensitivity rule")
late = ledger.authorize(public_plan, now=800, receipt_ttl_seconds=5)
rejects(lambda: ledger.claim(late, public_plan, now=805), EgressDenied, "receipt expires at boundary")
rejects(lambda: ledger.complete(late, public_plan, outcome="failed", bytes_sent=0, now=806), EgressDenied, "unclaimed receipt cannot finish")
rejects(lambda: ledger.complete(operational_receipt, operational, outcome="unknown", bytes_sent=0), EgressContractError, "invalid outcome is rejected")
rejects(lambda: ledger.recent_events(0), EgressContractError, "invalid audit limit is rejected")

events = ledger.recent_events(500)
serialized = json.dumps(events, ensure_ascii=False)
check(len(events) >= 12, "state transitions append audit events")
check(plan.purpose not in serialized, "audit excludes raw purpose")
check(payload.decode() not in serialized, "audit excludes raw payload")
check(plan.purpose_sha256 in serialized, "audit includes purpose digest")
check(plan.payload_sha256 in serialized, "audit includes payload digest")
check(any(event["event_type"] == "claimed" for event in events), "audit records boundary claim")
check(any(event["outcome"] == "completed" and event["bytes_sent"] == 512 for event in events), "audit records completed byte count")
check(any(event["outcome"] == "blocked" and event["error_code"] == "peer_mismatch" for event in events), "audit records blocked reason")
ledger.close()

with tempfile.TemporaryDirectory() as temp:
    path = Path(temp) / "egress.db"
    first = EgressLedger(str(path), uuid_factory=UUIDs())
    durable = first.propose(plan, now=900, ttl_seconds=30)
    first.approve(durable.proposal_id, actor="Anders", now=901)
    first.close()
    reopened = EgressLedger(str(path), uuid_factory=UUIDs())
    durable_receipt = reopened.authorize(plan, consent_id=durable.proposal_id, now=902)
    reopened.claim(durable_receipt, plan, now=903)
    reopened.complete(durable_receipt, plan, outcome="failed", bytes_sent=12, error_code="fixture_failure", now=904)
    durable_events = reopened.recent_events(20)
    check(any(event["event_type"] == "approved" for event in durable_events), "approval survives reopen")
    check(any(event["error_code"] == "fixture_failure" for event in durable_events), "completion survives reopen")
    reopened.close()

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
