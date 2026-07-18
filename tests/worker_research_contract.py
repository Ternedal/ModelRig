from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from app.research_contract import (
    Citation,
    ReadOnlyBrowserPolicy,
    ResearchContractError,
    ResearchRequest,
    ResearchResult,
    SourceReceipt,
    canonicalize_url,
    host_allowed,
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


def rejects(fn, name: str) -> None:
    try:
        fn()
    except ResearchContractError:
        check(True, name)
    else:
        check(False, name)


check(
    canonicalize_url("HTTPS://Exämple.COM:443/path?q=1#section")
    == "https://xn--exmple-cua.com/path?q=1",
    "URL canonicalization removes fragments, default ports and normalizes IDNA",
)
rejects(lambda: canonicalize_url("file:///etc/passwd"), "non-web schemes are rejected")
rejects(lambda: canonicalize_url("https://user:pass@example.com/"), "URL credentials are rejected")
rejects(lambda: canonicalize_url("http://127.0.0.1/admin"), "direct IP URLs are rejected")

policy = ReadOnlyBrowserPolicy(
    allowed_domains=("example.com", "*.trusted.example", "EXAMPLE.com."),
    max_steps=10,
    max_pages=6,
)
check(policy.allowed_domains == ("example.com", "*.trusted.example"), "domain rules normalize and deduplicate")
check(host_allowed("https://example.com/a", policy.allowed_domains), "exact host is allowed")
check(not host_allowed("https://www.example.com/a", policy.allowed_domains), "exact rule does not silently include subdomains")
check(host_allowed("https://api.trusted.example/a", policy.allowed_domains), "explicit wildcard allows subdomains")
check(not host_allowed("https://trusted.example/a", policy.allowed_domains), "wildcard does not include the apex host")
rejects(lambda: policy.require_allowed_url("https://evil.example/a"), "policy fails closed outside allowlist")
rejects(lambda: ReadOnlyBrowserPolicy(allowed_domains=()), "empty allowlist is rejected")
rejects(lambda: ReadOnlyBrowserPolicy(allowed_domains=("localhost",)), "local host rules are rejected")
rejects(lambda: ReadOnlyBrowserPolicy(allowed_domains=("127.0.0.1",)), "IP allowlist rules are rejected")
check(policy.require_public_address("8.8.8.8") == "8.8.8.8", "public DNS targets are accepted")
rejects(lambda: policy.require_public_address("127.0.0.1"), "loopback DNS targets are rejected")
rejects(lambda: policy.require_public_address("10.0.0.8"), "private DNS targets are rejected")
rejects(
    lambda: ReadOnlyBrowserPolicy(allowed_domains=("example.com",), profile_mode="persistent"),
    "persistent browser profiles are outside v1",
)
rejects(
    lambda: ReadOnlyBrowserPolicy(allowed_domains=("example.com",), downloads="allow"),
    "downloads are outside the read-only contract",
)

request = ResearchRequest(query="  Find the release notes  ", policy=policy, max_sources=4)
check(request.query == "Find the release notes", "research query is normalized")
check(request.to_dict()["policy"]["credentials"] == "deny", "serialized request keeps credential denial explicit")
rejects(lambda: ResearchRequest(query="x", policy=policy, max_sources=7), "source count cannot exceed page budget")

stamp = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
content = "stable source body"
receipt = SourceReceipt.from_content(
    url="https://example.com:443/report#top",
    title="Report",
    content=content,
    excerpt="A bounded excerpt.",
    media_type="text/html",
    adapter="fixture",
    retrieved_at=stamp,
)
repeat = SourceReceipt.from_content(
    url="https://EXAMPLE.com/report",
    title="Report",
    content=content,
    excerpt="Another excerpt does not change identity.",
    media_type="text/html",
    adapter="fixture",
    retrieved_at=stamp,
)
check(receipt.source_id == repeat.source_id, "source identity is deterministic for URL + content hash")
check(receipt.content_sha256 == hashlib.sha256(content.encode()).hexdigest(), "receipt binds the fetched bytes")
check(receipt.url == "https://example.com/report", "receipt stores canonical URL")
check(policy.accept_receipt(receipt) is receipt, "allowed receipt within byte budget is accepted")
small_policy = ReadOnlyBrowserPolicy(allowed_domains=("example.com",), max_source_bytes=1024)
oversized = SourceReceipt.from_content(
    url="https://example.com/large",
    title="Large",
    content=b"x" * 1025,
    excerpt="x",
    media_type="text/plain",
    adapter="fixture",
    retrieved_at=stamp,
)
rejects(lambda: small_policy.accept_receipt(oversized), "receipt byte budget is enforced")
rejects(
    lambda: SourceReceipt.from_content(
        url="https://example.com/report",
        title="Report",
        content=content,
        excerpt="x",
        media_type="text/html",
        adapter="fixture",
        retrieved_at=datetime.now(),
    ),
    "naive retrieval timestamps are rejected",
)
rejects(
    lambda: SourceReceipt.from_content(
        url="https://example.com/report",
        title="Report",
        content=content,
        excerpt="x",
        media_type="text/html",
        adapter="fixture",
        retrieved_at=stamp.astimezone(timezone(timedelta(hours=2))),
    ),
    "non-UTC retrieval timestamps are rejected",
)

citation = Citation(marker="1", statement="The report exists.", source_ids=(receipt.source_id,))
result = ResearchResult(
    answer="The report exists.[1]",
    sources=(receipt,),
    citations=(citation,),
)
check(result.to_dict()["citations"][0]["source_ids"] == [receipt.source_id], "result serializes stable citation links")
rejects(
    lambda: ResearchResult(answer="Uncited answer", sources=(receipt,), citations=()),
    "research answers cannot silently omit citations",
)
rejects(
    lambda: ResearchResult(answer="The report exists.", sources=(receipt,), citations=(citation,)),
    "answer must contain every declared citation marker",
)
unknown = Citation(marker="1", statement="Unknown source.", source_ids=("src_" + "0" * 20,))
rejects(
    lambda: ResearchResult(answer="Unknown.[1]", sources=(receipt,), citations=(unknown,)),
    "citations cannot reference missing receipts",
)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
