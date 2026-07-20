from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import replace

from app.data_sharing import DataSharingDenied, DataSharingLedger, DataSharingPolicy
from app.research_data_sharing import ResearchSharingIntent
from app.research_egress import EgressPlan
from app.research_sharing_boundary import (
    ResearchSharingBoundary,
    ResearchSharingBoundaryContractError,
    ResearchSharingBoundaryDenied,
    ResearchSharingLease,
    policy_digest,
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


RAW_PURPOSE = "Use one selected private excerpt for controlled web research"
RAW_SUMMARY = "A bounded excerpt selected by the user."
RAW_PAYLOAD = b"private research payload sentinel"
PLAN = EgressPlan(
    destination="browser-use",
    purpose=RAW_PURPOSE,
    payload_sha256=hashlib.sha256(RAW_PAYLOAD).hexdigest(),
    sensitivity="private",
    allowed_domains=("*.example.com", "example.com"),
    max_bytes=4096,
)
INTENT = ResearchSharingIntent(plan=PLAN, summary=RAW_SUMMARY)

rejects(
    lambda: ResearchSharingBoundary(DataSharingLedger(), mode="automatic"),
    ResearchSharingBoundaryContractError,
    "unknown boundary mode is rejected",
)
rejects(
    lambda: policy_digest("not-a-policy"),
    ResearchSharingBoundaryContractError,
    "policy digest requires the exact policy type",
)

# Observe mode is a read-only migration view and can never authorize bytes.
observe_ledger = DataSharingLedger(uuid_factory=UUIDs())
observe = ResearchSharingBoundary(observe_ledger, mode="observe")
inspection = observe.inspect(INTENT)
check(inspection["mode"] == "observe", "inspection reports observe mode")
check(inspection["may_send"] is False, "inspection is never a send authorization")
check(inspection["migration"]["legacy_decision"] == "confirmation_required", "inspection reports legacy decision")
check(inspection["migration"]["common_decision"] == "confirmation_required", "inspection reports common decision")
check(len(inspection["policy_sha256"]) == 64, "inspection hash-binds the active policy")
observe_lease = observe.prepare(INTENT, now=100)
check(observe_lease.mode == "observe", "observe prepare creates an observe lease")
check(observe_lease.may_send is False, "observe lease cannot send")
check(observe_lease.receipt is None, "observe lease has no receipt")
check(observe_lease.request_digest == INTENT.to_request().digest, "observe lease binds exact request")
check(observe_lease.plan_digest == PLAN.digest, "observe lease binds exact legacy plan")
check(observe_ledger.recent_events(20) == [], "observe prepare is ledger side-effect free")
rejects(
    lambda: observe.prepare(INTENT, permission_id="dsp_unrelated", now=101),
    ResearchSharingBoundaryContractError,
    "observe mode refuses permission ids",
)
rejects(
    lambda: observe.claim(observe_lease, INTENT, now=102),
    ResearchSharingBoundaryDenied,
    "observe lease cannot be claimed",
)
rejects(
    lambda: observe.complete(observe_lease, INTENT, outcome="completed", bytes_sent=1, now=103),
    ResearchSharingBoundaryDenied,
    "observe lease cannot be completed",
)
rejects(
    lambda: observe.record_local_fallback(INTENT, reason_code="not_enabled", now=104),
    ResearchSharingBoundaryDenied,
    "observe rollback remains side-effect free",
)
check(observe_ledger.recent_events(20) == [], "observe failures leave no audit events")
observe_ledger.close()

# Public research can use an automatic common receipt, but only after an explicit claim.
ledger = DataSharingLedger(uuid_factory=UUIDs())
enforce = ResearchSharingBoundary(ledger, mode="enforce")
public_intent = replace(
    INTENT,
    plan=replace(
        PLAN,
        sensitivity="public",
        purpose="Retrieve one public release-note fixture",
        payload_sha256=hashlib.sha256(b"public query").hexdigest(),
    ),
    summary="A public research query without local document content.",
)
public_lease = enforce.prepare(public_intent, now=200, receipt_ttl_seconds=20)
check(public_lease.may_send is True, "enforced public lease may cross the boundary")
check(public_lease.decision == "automatic", "public lease uses automatic policy")
check(public_lease.receipt is not None and public_lease.receipt.authorization == "automatic", "public lease contains automatic receipt")
check(public_lease.to_dict()["receipt"]["request_digest"] == public_intent.to_request().digest, "serialized lease keeps exact receipt binding")
rejects(
    lambda: enforce.complete(public_lease, public_intent, outcome="completed", bytes_sent=10, now=201),
    DataSharingDenied,
    "unclaimed lease cannot complete",
)
enforce.claim(public_lease, public_intent, now=201)
rejects(
    lambda: enforce.claim(public_lease, public_intent, now=202),
    DataSharingDenied,
    "lease claim is one use",
)
rejects(
    lambda: enforce.complete(public_lease, public_intent, outcome="completed", bytes_sent=4097, now=203),
    DataSharingDenied,
    "real byte count cannot exceed request budget",
)
enforce.complete(public_lease, public_intent, outcome="completed", bytes_sent=128, now=204)
rejects(
    lambda: enforce.complete(public_lease, public_intent, outcome="completed", bytes_sent=1, now=205),
    DataSharingDenied,
    "terminal completion is one way",
)

# Operational and private plans require exact one-use permissions under common v1.
operational_intent = replace(
    INTENT,
    plan=replace(
        PLAN,
        sensitivity="operational",
        purpose="Summarize current rig service health with one external model",
        payload_sha256=hashlib.sha256(b"service health").hexdigest(),
    ),
    summary="Service names and health states without document content.",
)
check(operational_intent.preview()["legacy_decision"] == "automatic", "adapter exposes legacy operational automatic path")
check(operational_intent.preview()["common_decision"] == "confirmation_required", "adapter exposes stricter common operational path")
rejects(
    lambda: enforce.prepare(operational_intent, now=300),
    DataSharingDenied,
    "operational execution requires common permission",
)
op_request = operational_intent.to_request()
op_permission = ledger.propose(op_request, now=301, ttl_seconds=30)
ledger.approve(op_permission.permission_id, actor="Anders", now=302)
op_lease = enforce.prepare(operational_intent, permission_id=op_permission.permission_id, now=303)
check(op_lease.receipt is not None and op_lease.receipt.authorization == "permission", "operational lease consumes exact permission")
enforce.claim(op_lease, operational_intent, now=304)
enforce.complete(op_lease, operational_intent, outcome="failed", bytes_sent=12, error_code="fixture_failure", now=305)

private_request = INTENT.to_request()
private_permission = ledger.propose(private_request, now=400, ttl_seconds=30)
ledger.approve(private_permission.permission_id, actor="Anders", now=401)
private_lease = enforce.prepare(INTENT, permission_id=private_permission.permission_id, now=402)
check(private_lease.receipt is not None and private_lease.receipt.permission_id == private_permission.permission_id, "private lease links exact permission")

# Every security-relevant mutation invalidates the lease before the external boundary.
for changed, name in (
    (replace(INTENT, summary=RAW_SUMMARY + " changed"), "changed summary"),
    (replace(INTENT, provider="other-provider"), "changed provider"),
    (replace(INTENT, plan=replace(PLAN, purpose=PLAN.purpose + " changed")), "changed purpose"),
    (replace(INTENT, plan=replace(PLAN, allowed_domains=("example.org",))), "changed domain scope"),
    (replace(INTENT, plan=replace(PLAN, max_bytes=4097)), "changed byte budget"),
    (
        replace(INTENT, plan=replace(PLAN, payload_sha256=hashlib.sha256(b"changed").hexdigest())),
        "changed payload",
    ),
):
    rejects(
        lambda value=changed: enforce.claim(private_lease, value, now=403),
        ResearchSharingBoundaryDenied,
        f"{name} cannot reuse lease",
    )

# A lease cannot cross policy or rollback-mode boundaries.
weaker_policy = DataSharingPolicy(operational="automatic")
other_policy_boundary = ResearchSharingBoundary(ledger, mode="enforce", policy=weaker_policy)
rejects(
    lambda: other_policy_boundary.claim(private_lease, INTENT, now=404),
    ResearchSharingBoundaryDenied,
    "lease cannot cross policy digest",
)
rollback_boundary = ResearchSharingBoundary(ledger, mode="observe")
rejects(
    lambda: rollback_boundary.claim(private_lease, INTENT, now=404),
    ResearchSharingBoundaryDenied,
    "rollback observe mode cannot claim an enforced lease",
)

enforce.claim(private_lease, INTENT, now=405)
enforce.complete(private_lease, INTENT, outcome="blocked", bytes_sent=0, error_code="peer_mismatch", now=406)

# Revocation after receipt issuance atomically blocks a not-yet-claimed lease.
revocation_permission = ledger.propose(private_request, now=500, ttl_seconds=30)
ledger.approve(revocation_permission.permission_id, actor="Anders", now=501)
revoked_lease = enforce.prepare(INTENT, permission_id=revocation_permission.permission_id, now=502)
ledger.revoke(revocation_permission.permission_id, actor="Anders", now=503)
rejects(
    lambda: enforce.claim(revoked_lease, INTENT, now=504),
    DataSharingDenied,
    "revoked permission invalidates issued unclaimed lease",
)

secret_intent = replace(INTENT, plan=replace(PLAN, sensitivity="secret"))
check(enforce.inspect(secret_intent)["migration"]["common_decision"] == "forbidden", "secret inspection is explicit")
rejects(
    lambda: enforce.prepare(secret_intent, permission_id="dsp_any", now=600),
    DataSharingDenied,
    "secret research is absolutely forbidden",
)

enforce.record_local_fallback(INTENT, reason_code="provider_unavailable", now=700)
events = ledger.recent_events(500)
serialized_events = json.dumps(events, ensure_ascii=False)
serialized_leases = json.dumps(
    [public_lease.to_dict(), op_lease.to_dict(), private_lease.to_dict()],
    ensure_ascii=False,
)
check(any(event["event_type"] == "claimed" for event in events), "audit records real boundary claim")
check(any(event["outcome"] == "completed" and event["bytes_sent"] == 128 for event in events), "audit records measured bytes")
check(any(event["outcome"] == "local_fallback" and event["bytes_sent"] == 0 for event in events), "audit records zero-byte fallback")
check(any(event["event_type"] == "permission_revoked" for event in events), "audit records revocation")
for forbidden, name in (
    (RAW_PURPOSE, "raw purpose"),
    (RAW_SUMMARY, "raw summary"),
    (RAW_PAYLOAD.decode(), "raw payload"),
):
    check(forbidden not in serialized_events, f"audit excludes {name}")
    check(forbidden not in serialized_leases, f"lease serialization excludes {name}")
ledger.close()

# Lease construction itself is fail closed.
rejects(
    lambda: ResearchSharingLease(
        mode="observe",
        plan_digest=PLAN.digest,
        request_digest=INTENT.to_request().digest,
        policy_sha256=policy_digest(DataSharingPolicy()),
        decision="confirmation_required",
        receipt=public_lease.receipt,
    ),
    ResearchSharingBoundaryContractError,
    "observe lease cannot smuggle an enforced receipt",
)
rejects(
    lambda: replace(public_lease, policy_sha256="ABC"),
    ResearchSharingBoundaryContractError,
    "invalid policy digest is rejected",
)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
