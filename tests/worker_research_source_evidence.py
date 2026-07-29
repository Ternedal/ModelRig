#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.research_claim_evidence import DataSharingClaimEvidence  # noqa: E402
from app.research_contract import (  # noqa: E402
    Citation,
    ResearchResult,
    SourceReceipt,
    canonicalize_url,
)
from app.research_peer_transfer import ResearchPeerBinding  # noqa: E402
from app.research_source_evidence import (  # noqa: E402
    SOURCE_EVIDENCE_SCHEMA,
    VerifiedCitationBundle,
    VerifiedResearchSourceReceipt,
    ResearchSourceEvidenceError,
)
from app.web_fetch import FetchTrace  # noqa: E402


def canonical_json(value) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha(value: bytes | str) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def url_hash(url: str) -> str:
    return sha(canonicalize_url(url))


def dns_hash(host: str, port: int, addresses: tuple[str, ...]) -> str:
    return sha(canonical_json({"host": host, "port": port, "addresses": list(addresses)}))


CLAIM = DataSharingClaimEvidence(
    receipt_id="dsr_t034_test_receipt",
    request_digest="a" * 64,
    max_bytes=4096,
    claimed_at=100,
    expires_at=300,
)
START_URL = "https://example.com/start?campaign=1"
FINAL_URL = "https://www.example.org/article?id=7"
START_ADDRESSES = ("93.184.216.34",)
FINAL_ADDRESSES = ("93.184.216.35", "2606:2800:220:1:248:1893:25c8:1946")
CONTENT = b"Verified T-034 source body"
SOURCE = SourceReceipt.from_content(
    url=FINAL_URL,
    title="Verified article",
    content=CONTENT,
    excerpt="Verified T-034 source body",
    media_type="text/html",
    adapter="pinned-http",
    retrieved_at=datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc),
)
TRACE = FetchTrace(
    requested_url=canonicalize_url(START_URL),
    final_url=canonicalize_url(FINAL_URL),
    visited_urls=(canonicalize_url(START_URL), canonicalize_url(FINAL_URL)),
    resolved_addresses=(
        (canonicalize_url(START_URL), START_ADDRESSES),
        (canonicalize_url(FINAL_URL), FINAL_ADDRESSES),
    ),
    receipt=SOURCE,
)


def binding(url: str, addresses: tuple[str, ...], index: int) -> ResearchPeerBinding:
    canonical = canonicalize_url(url)
    parsed = urlsplit(canonical)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    authorization_digest = sha(f"authorization-{index}")
    return ResearchPeerBinding(
        binding_id=f"rpt_hop_{index}",
        authorization_id=f"rpa_{authorization_digest}",
        authorization_digest=authorization_digest,
        claim_receipt_id=CLAIM.receipt_id,
        request_digest=CLAIM.request_digest,
        url_sha256=url_hash(canonical),
        host=host,
        port=port,
        addresses=addresses,
        selected_address=addresses[0],
        dns_sha256=dns_hash(host, port, addresses),
        max_bytes=CLAIM.max_bytes,
        issued_at=110 + index * 20,
        expires_at=250 + index * 10,
    )


BINDINGS = (
    binding(START_URL, START_ADDRESSES, 0),
    binding(FINAL_URL, FINAL_ADDRESSES, 1),
)


def binding_events(value: ResearchPeerBinding) -> list[dict]:
    common = {
        "binding_id": value.binding_id,
        "authorization_id": value.authorization_id,
        "authorization_digest": value.authorization_digest,
        "claim_receipt_id": value.claim_receipt_id,
        "request_digest": value.request_digest,
        "url_sha256": value.url_sha256,
        "host": value.host,
        "port": value.port,
        "dns_sha256": value.dns_sha256,
        "selected_address": value.selected_address,
    }
    return [
        {**common, "ts": value.issued_at, "event_type": "issued", "peer_address": None, "bytes_sent": None, "outcome": None, "error_code": None},
        {**common, "ts": value.issued_at + 1, "event_type": "claimed", "peer_address": None, "bytes_sent": None, "outcome": None, "error_code": None},
        {
            **common,
            "ts": value.issued_at + 2,
            "event_type": "finished",
            "peer_address": value.selected_address,
            "bytes_sent": 256 + value.issued_at,
            "outcome": "connected",
            "error_code": None,
        },
    ]


EVENTS = tuple(event for item in BINDINGS for event in binding_events(item))

checks: list[tuple[str, bool]] = []


def check(label: str, condition: object) -> None:
    checks.append((label, bool(condition)))


def expect_error(label: str, fn, contains: str | None = None) -> None:
    try:
        fn()
    except ResearchSourceEvidenceError as exc:
        check(label, contains is None or contains in str(exc))
    except Exception:
        check(label, False)
    else:
        check(label, False)


verified = VerifiedResearchSourceReceipt.from_execution(
    trace=TRACE,
    claim=CLAIM,
    bindings=BINDINGS,
    peer_events=EVENTS,
)
check("verified source schema is exact", verified.schema == SOURCE_EVIDENCE_SCHEMA)
check(
    "verified source binds both redirect hops and the common claim",
    len(verified.hops) == 2
    and all(hop.claim_receipt_id == CLAIM.receipt_id for hop in verified.hops)
    and all(hop.request_digest == CLAIM.request_digest for hop in verified.hops),
)
check(
    "verified source id and digests are deterministic",
    verified.verified_source_id.startswith("vsrc_")
    and verified == VerifiedResearchSourceReceipt.from_execution(
        trace=TRACE,
        claim=CLAIM,
        bindings=BINDINGS,
        peer_events=EVENTS,
    ),
)
serialized = json.dumps(verified.to_dict(), sort_keys=True)
check(
    "hop evidence omits raw redirect URL and remains non-activating",
    START_URL not in serialized
    and "campaign=1" not in serialized
    and verified.to_dict()["production_activation"] is False,
)
check(
    "final public citation URL and content digest remain visible",
    canonicalize_url(FINAL_URL) in serialized
    and SOURCE.content_sha256 in serialized,
)

result = ResearchResult(
    answer="The verified article supports the claim. [1]",
    sources=(SOURCE,),
    citations=(
        Citation(
            marker="1",
            statement="The verified article supports the claim.",
            source_ids=(SOURCE.source_id,),
        ),
    ),
)
bundle = VerifiedCitationBundle.from_result(result, (verified,))
check(
    "citation bundle maps source ids to verified source ids",
    bundle.citations[0].source_ids == (SOURCE.source_id,)
    and bundle.citations[0].verified_source_ids == (verified.verified_source_id,),
)
check(
    "citation audit stores answer and statement hashes, not raw text",
    result.answer not in json.dumps(bundle.to_dict(), sort_keys=True)
    and result.citations[0].statement not in json.dumps(bundle.to_dict(), sort_keys=True)
    and bundle.to_dict()["production_activation"] is False,
)

forged_peer = [dict(event) for event in EVENTS]
forged_peer[-1]["peer_address"] = "93.184.216.36"
expect_error(
    "forged connected peer fails closed",
    lambda: VerifiedResearchSourceReceipt.from_execution(
        trace=TRACE, claim=CLAIM, bindings=BINDINGS, peer_events=forged_peer
    ),
    "selected address",
)

missing_claim = [dict(event) for event in EVENTS if not (
    event["binding_id"] == BINDINGS[0].binding_id and event["event_type"] == "claimed"
)]
expect_error(
    "missing peer claim event fails closed",
    lambda: VerifiedResearchSourceReceipt.from_execution(
        trace=TRACE, claim=CLAIM, bindings=BINDINGS, peer_events=missing_claim
    ),
    "issued/claimed/finished",
)

extra_event = [dict(event) for event in EVENTS]
extra_event.append({**binding_events(BINDINGS[0])[-1], "event_type": "finished"})
expect_error(
    "duplicate terminal event fails closed",
    lambda: VerifiedResearchSourceReceipt.from_execution(
        trace=TRACE, claim=CLAIM, bindings=BINDINGS, peer_events=extra_event
    ),
    "issued/claimed/finished",
)

unknown_event = [dict(event) for event in EVENTS]
unknown_event.append({**binding_events(BINDINGS[0])[0], "binding_id": "rpt_unknown"})
expect_error(
    "unknown peer event inventory fails closed",
    lambda: VerifiedResearchSourceReceipt.from_execution(
        trace=TRACE, claim=CLAIM, bindings=BINDINGS, peer_events=unknown_event
    ),
    "unknown or missing bindings",
)

wrong_claim = DataSharingClaimEvidence(
    receipt_id=CLAIM.receipt_id,
    request_digest="f" * 64,
    max_bytes=CLAIM.max_bytes,
    claimed_at=CLAIM.claimed_at,
    expires_at=CLAIM.expires_at,
)
expect_error(
    "changed T-032 request digest fails closed",
    lambda: VerifiedResearchSourceReceipt.from_execution(
        trace=TRACE, claim=wrong_claim, bindings=BINDINGS, peer_events=EVENTS
    ),
    "exact common claim",
)

changed_trace = FetchTrace(
    requested_url=TRACE.requested_url,
    final_url=TRACE.final_url,
    visited_urls=TRACE.visited_urls,
    resolved_addresses=(
        TRACE.resolved_addresses[0],
        (TRACE.resolved_addresses[1][0], ("93.184.216.35",)),
    ),
    receipt=TRACE.receipt,
)
expect_error(
    "DNS answer-set drift fails closed",
    lambda: VerifiedResearchSourceReceipt.from_execution(
        trace=changed_trace, claim=CLAIM, bindings=BINDINGS, peer_events=EVENTS
    ),
    "DNS answers",
)

reversed_trace = FetchTrace(
    requested_url=TRACE.final_url,
    final_url=TRACE.requested_url,
    visited_urls=tuple(reversed(TRACE.visited_urls)),
    resolved_addresses=tuple(reversed(TRACE.resolved_addresses)),
    receipt=TRACE.receipt,
)
expect_error(
    "redirect-chain order drift fails closed",
    lambda: VerifiedResearchSourceReceipt.from_execution(
        trace=reversed_trace, claim=CLAIM, bindings=tuple(reversed(BINDINGS)), peer_events=EVENTS
    ),
    "source receipt URL",
)

expired_binding = copy.copy(BINDINGS[1])
object.__setattr__(expired_binding, "expires_at", expired_binding.issued_at + 1)
expect_error(
    "peer completion outside binding lifetime fails closed",
    lambda: VerifiedResearchSourceReceipt.from_execution(
        trace=TRACE,
        claim=CLAIM,
        bindings=(BINDINGS[0], expired_binding),
        peer_events=EVENTS,
    ),
    "binding lifetime",
)

over_budget = [dict(event) for event in EVENTS]
over_budget[-1]["bytes_sent"] = CLAIM.max_bytes + 1
expect_error(
    "outbound byte ceiling drift fails closed",
    lambda: VerifiedResearchSourceReceipt.from_execution(
        trace=TRACE, claim=CLAIM, bindings=BINDINGS, peer_events=over_budget
    ),
    "authorized ceiling",
)

failed_outcome = [dict(event) for event in EVENTS]
failed_outcome[-1]["outcome"] = "failed"
failed_outcome[-1]["error_code"] = "transport_error"
expect_error(
    "failed terminal peer outcome cannot create a source receipt",
    lambda: VerifiedResearchSourceReceipt.from_execution(
        trace=TRACE, claim=CLAIM, bindings=BINDINGS, peer_events=failed_outcome
    ),
    "connected outcome",
)

duplicate_bindings = (BINDINGS[0], BINDINGS[0])
expect_error(
    "reused peer binding across redirect hops fails closed",
    lambda: VerifiedResearchSourceReceipt.from_execution(
        trace=TRACE, claim=CLAIM, bindings=duplicate_bindings, peer_events=EVENTS[:3]
    ),
)

other_source = SourceReceipt.from_content(
    url="https://example.net/other",
    title="Other",
    content=b"other",
    excerpt="other",
    media_type="text/plain",
    adapter="pinned-http",
    retrieved_at=datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc),
)
result_with_unverified = ResearchResult(
    answer="Two sources. [1] [2]",
    sources=(SOURCE, other_source),
    citations=(
        Citation(marker="1", statement="First", source_ids=(SOURCE.source_id,)),
        Citation(marker="2", statement="Second", source_ids=(other_source.source_id,)),
    ),
)
expect_error(
    "citation result with an unverified source fails closed",
    lambda: VerifiedCitationBundle.from_result(result_with_unverified, (verified,)),
    "every result source",
)

mismatched_source = SourceReceipt.from_content(
    url=FINAL_URL,
    title="Different title",
    content=CONTENT,
    excerpt="Different excerpt",
    media_type="text/html",
    adapter="pinned-http",
    retrieved_at=datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc),
)
mismatched_result = ResearchResult(
    answer="Claim. [1]",
    sources=(mismatched_source,),
    citations=(
        Citation(
            marker="1",
            statement="Claim.",
            source_ids=(mismatched_source.source_id,),
        ),
    ),
)
expect_error(
    "citation source metadata drift fails closed",
    lambda: VerifiedCitationBundle.from_result(mismatched_result, (verified,)),
    "does not match",
)

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== RESEARCH SOURCE EVIDENCE: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
