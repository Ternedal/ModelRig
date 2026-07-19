from __future__ import annotations

import hashlib
import json
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path

from app.research_egress import EgressPlan, EgressReceipt
from app.research_peer_binding import (
    PeerBindingContractError,
    PeerBindingDenied,
    PublicPeerLedger,
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


def rejects(fn, expected, name: str, contains: str = "") -> None:
    try:
        fn()
    except expected as exc:
        check(not contains or contains in str(exc), name)
    else:
        check(False, name)


class UUIDs:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> uuid.UUID:
        self.value += 1
        return uuid.UUID(int=self.value)


RAW_PURPOSE = "Retrieve private fixture purpose sentinel"
RAW_PAYLOAD = b"private outbound payload sentinel"
RAW_URL = "https://Sub.Example.com:443/report?q=raw-url-sentinel#fragment"
CANONICAL_URL = "https://sub.example.com/report?q=raw-url-sentinel"
PLAN = EgressPlan(
    destination="browser-use",
    purpose=RAW_PURPOSE,
    payload_sha256=hashlib.sha256(RAW_PAYLOAD).hexdigest(),
    sensitivity="private",
    allowed_domains=("*.example.com", "example.com"),
    max_bytes=4096,
)
RECEIPT = EgressReceipt(
    receipt_id="egr_test_receipt",
    plan_digest=PLAN.digest,
    authorized_at=100,
    expires_at=200,
    authorization="consented",
    consent_id="egc_test_consent",
    max_bytes=PLAN.max_bytes,
)


class Resolver:
    def __init__(self, answers=None, error=None) -> None:
        self.answers = ("2606:4700:4700::1111", "1.1.1.1", "1.1.1.1") if answers is None else answers
        self.error = error
        self.calls = []

    def __call__(self, host: str, port: int):
        self.calls.append((host, port))
        if self.error:
            raise self.error
        return self.answers


resolver = Resolver()
ledger = PublicPeerLedger(resolver, uuid_factory=UUIDs())
binding = ledger.issue(PLAN, RECEIPT, RAW_URL, now=110, ttl_seconds=30)
check(resolver.calls == [("sub.example.com", 443)], "resolver receives canonical host and port")
check(binding.binding_id == "pbr_00000000000000000000000000000001", "binding id is deterministic")
check(binding.addresses == ("1.1.1.1", "2606:4700:4700::1111"), "addresses deduplicate and sort deterministically")
check(binding.selected_address == "1.1.1.1", "first deterministic public address is selected")
check(binding.host == "sub.example.com" and binding.port == 443, "binding records canonical authority")
check(binding.url_sha256 == hashlib.sha256(CANONICAL_URL.encode()).hexdigest(), "binding stores URL hash only")
check(binding.expires_at == 140, "binding TTL is bounded")
check(len(binding.dns_sha256) == 64, "DNS answer set is hash-bound")
serialized = json.dumps(binding.to_dict(), sort_keys=True)
check(RAW_URL not in serialized and "raw-url-sentinel" not in serialized, "binding serialization excludes raw URL")
check("issued_at" in binding.to_dict() and binding.to_dict()["addresses"][0] == "1.1.1.1", "binding serialization remains auditable")

selected = ledger.claim(binding, PLAN, RECEIPT, RAW_URL, now=111)
check(selected == "1.1.1.1", "claim returns the exact peer to connect")
rejects(
    lambda: ledger.claim(binding, PLAN, RECEIPT, RAW_URL, now=112),
    PeerBindingDenied,
    "binding claim is one-use",
)
ledger.complete(
    binding,
    PLAN,
    RECEIPT,
    RAW_URL,
    outcome="connected",
    peer_address="1.1.1.1",
    now=113,
)
rejects(
    lambda: ledger.complete(
        binding,
        PLAN,
        RECEIPT,
        RAW_URL,
        outcome="connected",
        peer_address="1.1.1.1",
        now=114,
    ),
    PeerBindingDenied,
    "completion is final",
)
events = ledger.events()
check([event["event_type"] for event in events] == ["issued", "claimed", "finished"], "audit records ordered lifecycle")
check(events[-1]["outcome"] == "connected" and events[-1]["peer_address"] == "1.1.1.1", "audit records verified peer outcome")
for forbidden in (RAW_PURPOSE, RAW_PAYLOAD.decode(), RAW_URL, "raw-url-sentinel"):
    check(forbidden not in json.dumps(events), f"audit excludes {forbidden[:20]}")
ledger.close()

# One egress receipt may authorize only one peer binding.
duplicate_ledger = PublicPeerLedger(Resolver(), uuid_factory=UUIDs())
duplicate_ledger.issue(PLAN, RECEIPT, RAW_URL, now=110)
rejects(
    lambda: duplicate_ledger.issue(PLAN, RECEIPT, "https://example.com/other", now=111),
    PeerBindingDenied,
    "egress receipt creates only one peer binding",
)
duplicate_ledger.close()

# Domain, receipt and DNS failures fail closed before any claimable binding exists.
for answers, name in (
    (("1.1.1.1", "127.0.0.1"), "mixed public/private DNS is rejected"),
    (("10.0.0.1",), "private DNS is rejected"),
    (("not-an-ip",), "invalid DNS answer is rejected"),
    ((), "empty DNS answer is rejected"),
    (tuple("1.1.1.1" for _ in range(33)), "DNS answer budget is enforced"),
):
    candidate = PublicPeerLedger(Resolver(answers=answers), uuid_factory=UUIDs())
    rejects(lambda c=candidate: c.issue(PLAN, RECEIPT, RAW_URL, now=110), PeerBindingDenied, name)
    check(candidate.events() == [], f"{name} leaves no issued event")
    candidate.close()

error_ledger = PublicPeerLedger(Resolver(error=RuntimeError("private resolver detail")), uuid_factory=UUIDs())
rejects(
    lambda: error_ledger.issue(PLAN, RECEIPT, RAW_URL, now=110),
    PeerBindingDenied,
    "resolver failures are normalized",
    "DNS resolution failed",
)
check("private resolver detail" not in json.dumps(error_ledger.events()), "resolver details are not audited")
error_ledger.close()

scope_ledger = PublicPeerLedger(Resolver(), uuid_factory=UUIDs())
rejects(
    lambda: scope_ledger.issue(PLAN, RECEIPT, "https://evil.test/report", now=110),
    PeerBindingDenied,
    "out-of-scope domain is rejected",
)
rejects(
    lambda: scope_ledger.issue(PLAN, RECEIPT, "https://127.0.0.1/report", now=110),
    PeerBindingDenied,
    "direct IP URL is rejected",
)
rejects(
    lambda: scope_ledger.issue(PLAN, RECEIPT, "https://user:pass@example.com/report", now=110),
    PeerBindingDenied,
    "URL credentials are rejected",
)
wrong_plan = replace(PLAN, purpose=PLAN.purpose + " changed")
rejects(
    lambda: scope_ledger.issue(wrong_plan, RECEIPT, RAW_URL, now=110),
    PeerBindingDenied,
    "receipt cannot authorize a changed plan",
)
wrong_limit = replace(RECEIPT, max_bytes=4097)
rejects(
    lambda: scope_ledger.issue(PLAN, wrong_limit, RAW_URL, now=110),
    PeerBindingDenied,
    "receipt byte ceiling must match plan",
)
expired_receipt = replace(RECEIPT, expires_at=110)
rejects(
    lambda: scope_ledger.issue(PLAN, expired_receipt, RAW_URL, now=110),
    PeerBindingDenied,
    "expired egress receipt is rejected",
)
rejects(
    lambda: scope_ledger.issue(PLAN, RECEIPT, RAW_URL, now=110, ttl_seconds=True),
    PeerBindingContractError,
    "boolean TTL is rejected",
)
scope_ledger.close()

# Receipt expiry clips a longer requested peer-binding lifetime.
clip_ledger = PublicPeerLedger(Resolver(), uuid_factory=UUIDs())
clipped = clip_ledger.issue(PLAN, replace(RECEIPT, expires_at=120), RAW_URL, now=110, ttl_seconds=100)
check(clipped.expires_at == 120, "binding cannot outlive egress receipt")
clip_ledger.close()

# Claim validates exact URL and plan, then records expiry fail-closed.
claim_ledger = PublicPeerLedger(Resolver(), uuid_factory=UUIDs())
claim_binding = claim_ledger.issue(PLAN, RECEIPT, RAW_URL, now=110, ttl_seconds=5)
rejects(
    lambda: claim_ledger.claim(claim_binding, PLAN, RECEIPT, "https://sub.example.com/other", now=111),
    PeerBindingDenied,
    "changed URL cannot claim binding",
)
rejects(
    lambda: claim_ledger.claim(claim_binding, wrong_plan, RECEIPT, RAW_URL, now=111),
    PeerBindingDenied,
    "changed plan cannot claim binding",
)
rejects(
    lambda: claim_ledger.claim(claim_binding, PLAN, RECEIPT, RAW_URL, now=115),
    PeerBindingDenied,
    "expired binding cannot be claimed",
)
check(claim_ledger.events()[-1]["error_code"] == "expired", "claim expiry is audited")
claim_ledger.close()

# Actual peer mismatch or non-public peer atomically blocks and finalizes the binding.
for peer, name in (
    ("8.8.8.8", "different public peer is blocked"),
    ("127.0.0.1", "non-public connected peer is blocked"),
):
    mismatch_ledger = PublicPeerLedger(Resolver(), uuid_factory=UUIDs())
    mismatch = mismatch_ledger.issue(PLAN, RECEIPT, RAW_URL, now=110)
    mismatch_ledger.claim(mismatch, PLAN, RECEIPT, RAW_URL, now=111)
    rejects(
        lambda m=mismatch_ledger, b=mismatch, p=peer: m.complete(
            b,
            PLAN,
            RECEIPT,
            RAW_URL,
            outcome="connected",
            peer_address=p,
            now=112,
        ),
        PeerBindingDenied,
        name,
    )
    final = mismatch_ledger.events()[-1]
    check(final["outcome"] == "blocked" and final["error_code"] == "peer_mismatch", f"{name} is audited")
    rejects(
        lambda m=mismatch_ledger, b=mismatch: m.complete(
            b,
            PLAN,
            RECEIPT,
            RAW_URL,
            outcome="failed",
            error_code="retry",
            now=113,
        ),
        PeerBindingDenied,
        f"{name} cannot be retried with same binding",
    )
    mismatch_ledger.close()

# Failed transport completion is allowed only with a bounded normalized error code.
failed_ledger = PublicPeerLedger(Resolver(), uuid_factory=UUIDs())
failed_binding = failed_ledger.issue(PLAN, RECEIPT, RAW_URL, now=110)
failed_ledger.claim(failed_binding, PLAN, RECEIPT, RAW_URL, now=111)
rejects(
    lambda: failed_ledger.complete(
        failed_binding,
        PLAN,
        RECEIPT,
        RAW_URL,
        outcome="failed",
        now=112,
    ),
    PeerBindingContractError,
    "failed outcome requires error code",
)
failed_ledger.complete(
    failed_binding,
    PLAN,
    RECEIPT,
    RAW_URL,
    outcome="failed",
    error_code="connect_timeout",
    now=112,
)
check(failed_ledger.events()[-1]["error_code"] == "connect_timeout", "normalized failure is audited")
failed_ledger.close()

# Binding and lifecycle survive a process restart without storing raw URL/query/payload.
with tempfile.TemporaryDirectory() as temp_dir:
    database = Path(temp_dir) / "peer-binding.db"
    persistent = PublicPeerLedger(Resolver(), str(database), uuid_factory=UUIDs())
    persisted_binding = persistent.issue(PLAN, RECEIPT, RAW_URL, now=110)
    persistent.close()

    reopened = PublicPeerLedger(Resolver(error=AssertionError("resolver must not run during claim")), str(database))
    check(reopened.claim(persisted_binding, PLAN, RECEIPT, RAW_URL, now=111) == "1.1.1.1", "binding claim survives restart")
    reopened.complete(
        persisted_binding,
        PLAN,
        RECEIPT,
        RAW_URL,
        outcome="connected",
        peer_address="1.1.1.1",
        now=112,
    )
    reopened.close()
    database_bytes = database.read_bytes()
    for secret in (RAW_PURPOSE.encode(), RAW_PAYLOAD, RAW_URL.encode(), b"raw-url-sentinel"):
        check(secret not in database_bytes, "SQLite audit contains no raw purpose, payload or URL query")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
