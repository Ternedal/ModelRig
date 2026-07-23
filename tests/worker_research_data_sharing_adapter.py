from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import replace

from app.data_sharing import DataSharingDenied, DataSharingLedger
from app.research_data_sharing import (
    ADAPTER_SCHEMA,
    ResearchSharingIntent,
    legacy_research_decision,
)
from app.research_egress import EgressPlan

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
        self.value = 1000

    def __call__(self) -> uuid.UUID:
        self.value += 1
        return uuid.UUID(int=self.value)


payload = b"research query containing selected local context"
plan = EgressPlan(
    destination="browser-use",
    purpose="Research a public source for the current answer",
    payload_sha256=hashlib.sha256(payload).hexdigest(),
    sensitivity="private",
    allowed_domains=("example.com", "*.example.org"),
    max_bytes=8192,
)
intent = ResearchSharingIntent(
    plan=plan,
    summary="Selected private context used only for this scoped web research request.",
)
request = intent.to_request()
preview = intent.preview()

check(intent.schema == ADAPTER_SCHEMA, "adapter schema is explicit")
check(request.surface == "research", "request names research surface")
check(request.destination_type == "public_web", "request names public-web destination type")
check(request.provider == "browser-use", "request names Browser Use provider")
check(request.data_category == "private", "legacy sensitivity maps to data category")
check(request.purpose == plan.purpose, "legacy purpose remains human-readable")
check(request.content_sha256 == plan.payload_sha256, "legacy payload hash is preserved")
check(request.max_bytes == plan.max_bytes, "legacy byte budget is preserved")
check(intent.domain_scope_sha256 in request.destination, "domain scope binds destination")
check(preview["allowed_domains"] == ["*.example.org", "example.com"], "preview shows normalized scope")
check(preview["legacy_plan_digest"] == plan.digest, "preview links legacy plan")
check(preview["request"]["request_digest"] == request.digest, "preview links common request")
check(preview["legacy_decision"] == "confirmation_required", "private legacy rule is represented")
check(preview["common_decision"] == "confirmation_required", "private common rule matches")

changed_domains = ResearchSharingIntent(
    replace(plan, allowed_domains=("example.net",)),
    summary=intent.summary,
)
check(changed_domains.domain_scope_sha256 != intent.domain_scope_sha256, "domain change changes scope digest")
check(changed_domains.to_request().digest != request.digest, "domain change requires new permission")
check(
    ResearchSharingIntent(replace(plan, purpose=plan.purpose + " changed"), intent.summary).to_request().digest
    != request.digest,
    "purpose change requires new permission",
)
check(
    ResearchSharingIntent(replace(plan, payload_sha256=hashlib.sha256(b"changed").hexdigest()), intent.summary)
    .to_request().digest
    != request.digest,
    "payload change requires new permission",
)
check(
    ResearchSharingIntent(replace(plan, max_bytes=8193), intent.summary).to_request().digest != request.digest,
    "byte-budget change requires new permission",
)
check(
    ResearchSharingIntent(plan, intent.summary + " changed").to_request().digest != request.digest,
    "preview-summary change requires new permission",
)
check(
    ResearchSharingIntent(plan, intent.summary, provider="other-browser").to_request().digest != request.digest,
    "provider change requires new permission",
)

public_plan = replace(plan, sensitivity="public", purpose="Retrieve a public fixture")
operational_plan = replace(plan, sensitivity="operational", purpose="Retrieve public service status")
secret_plan = replace(plan, sensitivity="secret", purpose="Send a secret fixture")
check(legacy_research_decision(public_plan) == "automatic", "legacy public rule is automatic")
check(legacy_research_decision(operational_plan) == "automatic", "legacy operational rule is automatic")
check(legacy_research_decision(secret_plan) == "forbidden", "legacy secret rule is forbidden")
check(
    ResearchSharingIntent(operational_plan, "Operational rig state for scoped research.").preview()["common_decision"]
    == "confirmation_required",
    "adapter exposes stricter operational common policy",
)
check(
    ResearchSharingIntent(public_plan, "Public query without local private context.").preview()["common_decision"]
    == "automatic",
    "public common policy remains automatic",
)
check(
    ResearchSharingIntent(secret_plan, "Secret content must not leave the rig.").preview()["common_decision"]
    == "forbidden",
    "secret common policy remains absolute",
)

ledger = DataSharingLedger(uuid_factory=UUIDs())
proposal = ledger.propose(request, now=100, ttl_seconds=30)
ledger.approve(proposal.permission_id, actor="Anders", now=101)
receipt = ledger.authorize(request, permission_id=proposal.permission_id, now=102)
ledger.claim(receipt, request, now=103)
ledger.complete(receipt, request, outcome="completed", bytes_sent=256, now=104)
check(receipt.request_digest == request.digest, "common receipt binds adapted request")

operational_intent = ResearchSharingIntent(
    operational_plan,
    "Operational rig state for scoped research.",
)
operational_request = operational_intent.to_request()
rejects(
    lambda: ledger.authorize(operational_request, now=200),
    DataSharingDenied,
    "operational research cannot retain legacy automatic authorization",
)
op_proposal = ledger.propose(operational_request, now=201)
ledger.approve(op_proposal.permission_id, actor="Anders", now=202)
op_receipt = ledger.authorize(operational_request, permission_id=op_proposal.permission_id, now=203)
ledger.claim(op_receipt, operational_request, now=204)
ledger.complete(op_receipt, operational_request, outcome="blocked", bytes_sent=0, error_code="fixture", now=205)

public_request = ResearchSharingIntent(
    public_plan,
    "Public query without local private context.",
).to_request()
public_receipt = ledger.authorize(public_request, now=300)
ledger.claim(public_receipt, public_request, now=301)
ledger.complete(public_receipt, public_request, outcome="completed", bytes_sent=64, now=302)
check(public_receipt.authorization == "automatic", "adapted public request is automatically receipted")

secret_request = ResearchSharingIntent(
    secret_plan,
    "Secret content must not leave the rig.",
).to_request()
rejects(lambda: ledger.authorize(secret_request, now=400), DataSharingDenied, "adapted secret request is denied")

events = ledger.recent_events(100)
serialized = json.dumps(events, ensure_ascii=False)
check(plan.purpose not in serialized, "common audit excludes raw legacy purpose")
check(intent.summary not in serialized, "common audit excludes raw adapter summary")
check(payload.decode() not in serialized, "common audit excludes raw research payload")
check(request.content_sha256 in serialized, "common audit retains payload digest")
check(any(event["surface"] == "research" for event in events), "common audit identifies research surface")
check(any(event["destination"].endswith(intent.domain_scope_sha256) for event in events), "audit binds domain scope")
ledger.close()

rejects(
    lambda: ResearchSharingIntent(plan, " "),
    ValueError,
    "blank adapter summary fails at construction",
)
rejects(
    lambda: ResearchSharingIntent(plan, intent.summary, schema="future"),
    ValueError,
    "unknown adapter schema fails closed",
)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
