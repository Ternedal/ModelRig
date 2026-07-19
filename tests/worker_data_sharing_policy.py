from __future__ import annotations

import hashlib
import json
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path

from app.data_sharing import (
    DEFAULT_POLICY,
    DataSharingContractError,
    DataSharingDenied,
    DataSharingLedger,
    DataSharingPolicy,
    DataSharingRequest,
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


payload = b"local document excerpt"
request = DataSharingRequest(
    surface="agent3",
    destination_type="cloud_model",
    provider="openai",
    destination="openai.responses",
    data_category="private",
    purpose_code="answer_user",
    purpose="Use the selected excerpt to answer the current user question",
    summary="A limited excerpt from one selected local document.",
    content_sha256=hashlib.sha256(payload).hexdigest(),
    max_bytes=4096,
)

check(DEFAULT_POLICY.public == "automatic", "public data is automatic in v1")
check(DEFAULT_POLICY.operational == "confirmation_required", "operational data requires confirmation")
check(DEFAULT_POLICY.private == "confirmation_required", "private data requires confirmation")
check(DEFAULT_POLICY.secret == "forbidden", "secret data is forbidden")
check(request.preview()["provider"] == "openai", "preview names provider")
check(request.preview()["destination"] == "openai.responses", "preview names destination")
check(request.preview()["data_category"] == "private", "preview names data category")
check(request.preview()["purpose"] == request.purpose, "preview explains purpose")
check(request.preview()["summary"] == request.summary, "preview includes limited summary")
check(request.purpose not in request.digest_payload().values(), "digest excludes raw purpose")
check(request.summary not in request.digest_payload().values(), "digest excludes raw summary")
check(replace(request, destination="anthropic.messages").digest != request.digest, "destination changes digest")
check(replace(request, provider="anthropic").digest != request.digest, "provider changes digest")
check(
    replace(request, content_sha256=hashlib.sha256(b"changed").hexdigest()).digest != request.digest,
    "content changes digest",
)
check(replace(request, purpose=request.purpose + " changed").digest != request.digest, "purpose changes digest")
check(replace(request, summary=request.summary + " changed").digest != request.digest, "summary changes digest")
check(replace(request, surface="agent_v2").digest != request.digest, "surface changes digest")

rejects(
    lambda: DataSharingPolicy(secret="confirmation_required"),
    DataSharingContractError,
    "secret cannot be made consentable",
)
rejects(
    lambda: DataSharingPolicy(private="automatic"),
    DataSharingContractError,
    "private cannot become automatic",
)
rejects(
    lambda: replace(request, provider="Open AI"),
    DataSharingContractError,
    "provider must be a stable slug",
)
rejects(
    lambda: replace(request, destination="https://api.example.com?q=secret"),
    DataSharingContractError,
    "destination cannot contain query data",
)
rejects(lambda: replace(request, summary=" "), DataSharingContractError, "blank summary is rejected")
rejects(lambda: replace(request, content_sha256="ABC"), DataSharingContractError, "invalid content digest is rejected")
rejects(lambda: replace(request, max_bytes=True), DataSharingContractError, "boolean byte budget is rejected")

ledger = DataSharingLedger(uuid_factory=UUIDs())
proposal = ledger.propose(request, now=100, ttl_seconds=30)
check(proposal.request_digest == request.digest, "proposal binds exact request")
check(proposal.expires_at == 130, "permission is time limited")
check(proposal.preview["provider"] == "openai", "proposal carries human preview")
ledger.approve(proposal.permission_id, actor="Anders", now=101)

changed_destination = replace(request, destination="anthropic.messages")
rejects(
    lambda: ledger.authorize(changed_destination, permission_id=proposal.permission_id, now=102),
    DataSharingDenied,
    "changed destination cannot reuse permission",
)
receipt = ledger.authorize(request, permission_id=proposal.permission_id, now=103)
check(receipt.authorization == "permission", "private request uses permission")
check(receipt.permission_id == proposal.permission_id, "receipt links permission")
rejects(
    lambda: ledger.authorize(request, permission_id=proposal.permission_id, now=104),
    DataSharingDenied,
    "permission is one use",
)
rejects(
    lambda: ledger.claim(receipt, changed_destination, now=104),
    DataSharingDenied,
    "changed request cannot claim receipt",
)
ledger.claim(receipt, request, now=104)
rejects(lambda: ledger.claim(receipt, request, now=105), DataSharingDenied, "receipt claim is one use")
ledger.complete(receipt, request, outcome="completed", bytes_sent=512, now=106)
rejects(
    lambda: ledger.complete(receipt, request, outcome="completed", bytes_sent=1, now=107),
    DataSharingDenied,
    "receipt completion is final",
)

revoked = ledger.propose(request, now=200, ttl_seconds=30)
ledger.approve(revoked.permission_id, actor="Anders", now=201)
ledger.revoke(revoked.permission_id, actor="Anders", now=202)
rejects(
    lambda: ledger.authorize(request, permission_id=revoked.permission_id, now=203),
    DataSharingDenied,
    "revoked permission cannot authorize",
)

denied = ledger.propose(request, now=300, ttl_seconds=30)
ledger.deny(denied.permission_id, actor="Anders", now=301)
rejects(
    lambda: ledger.authorize(request, permission_id=denied.permission_id, now=302),
    DataSharingDenied,
    "denied permission cannot authorize",
)

expired = ledger.propose(request, now=400, ttl_seconds=5)
rejects(
    lambda: ledger.approve(expired.permission_id, actor="Anders", now=405),
    DataSharingDenied,
    "permission timeout is denial",
)
rejects(lambda: ledger.authorize(request, now=500), DataSharingDenied, "private request without permission is denied")

secret = replace(request, data_category="secret")
rejects(lambda: ledger.propose(secret, now=500), DataSharingDenied, "secret request cannot be proposed")
rejects(
    lambda: ledger.authorize(secret, permission_id="anything", now=500),
    DataSharingDenied,
    "secret request cannot be authorized",
)

public_request = replace(
    request,
    surface="research",
    destination_type="public_web",
    provider="browser-use",
    destination="example.com",
    data_category="public",
    purpose_code="research",
    purpose="Retrieve a public fixture",
    summary="A public search query with no local content.",
)
public_receipt = ledger.authorize(public_request, now=600)
check(public_receipt.authorization == "automatic", "public request is automatic")
rejects(
    lambda: ledger.authorize(public_request, permission_id=proposal.permission_id, now=601),
    DataSharingContractError,
    "automatic request rejects unrelated permission",
)
ledger.claim(public_receipt, public_request, now=601)
ledger.complete(public_receipt, public_request, outcome="blocked", bytes_sent=0, error_code="peer_mismatch", now=602)

operational = replace(
    request,
    surface="agent_v2",
    data_category="operational",
    purpose_code="service_status",
    purpose="Ask the configured provider to summarize current rig status",
    summary="GPU model and service health without document contents.",
)
rejects(lambda: ledger.authorize(operational, now=700), DataSharingDenied, "operational data requires permission")
op_proposal = ledger.propose(operational, now=701)
ledger.approve(op_proposal.permission_id, actor="Anders", now=702)
op_receipt = ledger.authorize(operational, permission_id=op_proposal.permission_id, now=703, receipt_ttl_seconds=5)
rejects(lambda: ledger.claim(op_receipt, operational, now=708), DataSharingDenied, "receipt timeout is denial")

ledger.record_local_fallback(request, reason_code="permission_missing", now=800)
local_proposal = ledger.propose(request, now=810)
ledger.approve(local_proposal.permission_id, actor="Anders", now=811)
local_receipt = ledger.authorize(request, permission_id=local_proposal.permission_id, now=812)
ledger.claim(local_receipt, request, now=813)
rejects(
    lambda: ledger.complete(
        local_receipt,
        request,
        outcome="local_fallback",
        bytes_sent=1,
        error_code="provider_unavailable",
        now=814,
    ),
    DataSharingContractError,
    "local fallback cannot send bytes",
)
ledger.complete(
    local_receipt,
    request,
    outcome="local_fallback",
    bytes_sent=0,
    error_code="provider_unavailable",
    now=815,
)

events = ledger.recent_events(500)
serialized = json.dumps(events, ensure_ascii=False)
check(len(events) >= 18, "state changes append audit events")
check(request.purpose not in serialized, "audit excludes raw purpose")
check(request.summary not in serialized, "audit excludes raw summary")
check(payload.decode() not in serialized, "audit excludes shared content")
check(request.purpose_sha256 in serialized, "audit includes purpose digest")
check(request.summary_sha256 in serialized, "audit includes summary digest")
check(request.content_sha256 in serialized, "audit includes content digest")
check(any(e["provider"] == "openai" for e in events), "audit explains provider")
check(any(e["destination"] == "openai.responses" for e in events), "audit explains destination")
check(any(e["purpose_code"] == "answer_user" for e in events), "audit explains purpose code")
check(any(e["event_type"] == "permission_revoked" for e in events), "audit records revocation")
check(
    any(e["outcome"] == "local_fallback" and e["bytes_sent"] == 0 for e in events),
    "audit records zero-byte local fallback",
)
ledger.close()

with tempfile.TemporaryDirectory() as temp:
    path = Path(temp) / "sharing.db"
    first = DataSharingLedger(str(path), uuid_factory=UUIDs())
    durable = first.propose(request, now=900)
    first.approve(durable.permission_id, actor="Anders", now=901)
    first.close()
    reopened = DataSharingLedger(str(path), uuid_factory=UUIDs())
    durable_receipt = reopened.authorize(request, permission_id=durable.permission_id, now=902)
    reopened.claim(durable_receipt, request, now=903)
    reopened.complete(
        durable_receipt,
        request,
        outcome="failed",
        bytes_sent=0,
        error_code="fixture_failure",
        now=904,
    )
    durable_events = reopened.recent_events(20)
    check(any(e["event_type"] == "permission_approved" for e in durable_events), "approval survives reopen")
    check(any(e["error_code"] == "fixture_failure" for e in durable_events), "terminal receipt survives reopen")
    reopened.close()

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
