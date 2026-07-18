from __future__ import annotations

import gzip
import hashlib
from dataclasses import dataclass

from app.research_contract import ReadOnlyBrowserPolicy, ResearchContractError
from app.web_fetch import DeterministicWebFetcher, TransportResponse, WebFetchError

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def rejects(fn, name: str, contains: str = "") -> None:
    try:
        fn()
    except (WebFetchError, ResearchContractError) as exc:
        check(not contains or contains in str(exc), name)
    else:
        check(False, name)


@dataclass
class Planned:
    url: str
    address: str
    response: TransportResponse | Exception


class FakeTransport:
    def __init__(self, *plans: Planned) -> None:
        self.plans = list(plans)
        self.calls: list[dict] = []

    def request(self, url, *, connect_address, headers, timeout_seconds, max_wire_bytes):
        self.calls.append({
            "url": url,
            "connect_address": connect_address,
            "headers": dict(headers),
            "timeout_seconds": timeout_seconds,
            "max_wire_bytes": max_wire_bytes,
        })
        if not self.plans:
            raise AssertionError("unexpected transport call")
        plan = self.plans.pop(0)
        assert (plan.url, plan.address) == (url, connect_address)
        if isinstance(plan.response, Exception):
            raise plan.response
        return plan.response


def response(status=200, headers=None, body=b"", peer="1.1.1.1"):
    return TransportResponse(status, headers or {}, body, peer)


def plan(url, response_value, address="1.1.1.1"):
    return Planned(url, address, response_value)


def fetch_with(
    transport,
    *,
    url="https://example.com/a",
    policy=None,
    resolver=None,
    clock=None,
    max_redirects=5,
):
    kwargs = {
        "resolver": resolver or (lambda host, port: ("1.1.1.1",)),
        "max_redirects": max_redirects,
    }
    if clock is not None:
        kwargs["clock"] = clock
    return DeterministicWebFetcher(transport, **kwargs).fetch(
        url,
        policy or POLICY,
    )


POLICY = ReadOnlyBrowserPolicy(
    allowed_domains=("example.com", "*.example.com"),
    max_steps=6,
    max_pages=4,
    timeout_seconds=10,
    max_source_bytes=4096,
)

html = (
    b"<!doctype html><html><head><title> Example report </title>"
    b"<style>hidden</style></head><body><h1>Release</h1>"
    b"<p>Version 7 is live.</p><script>ignore()</script></body></html>"
)
transport = FakeTransport(plan(
    "https://example.com/report",
    response(headers={"Content-Type": "text/html; charset=utf-8"}, body=html),
))
trace = fetch_with(
    transport,
    url="https://EXAMPLE.com:443/report#top",
    resolver=lambda host, port: ("8.8.8.8", "1.1.1.1", "1.1.1.1"),
)
check(trace.requested_url == "https://example.com/report", "request URL is canonicalized")
check(trace.final_url == "https://example.com/report", "final URL is recorded")
check(trace.visited_urls == ("https://example.com/report",), "visit trace is stable")
check(
    trace.resolved_addresses
    == (("https://example.com/report", ("1.1.1.1", "8.8.8.8")),),
    "DNS answers are deduplicated and sorted",
)
check(transport.calls[0]["connect_address"] == "1.1.1.1", "transport is pinned to selected DNS address")
check(transport.calls[0]["headers"]["user-agent"] == "ModelRig-WebFetch/1.0", "fixed user agent is used")
check(trace.receipt.title == "Example report", "HTML title is extracted")
check("Release Version 7 is live." in trace.receipt.excerpt, "readable HTML text is extracted")
check("hidden" not in trace.receipt.excerpt and "ignore" not in trace.receipt.excerpt, "hidden HTML is excluded")
check(trace.receipt.content_sha256 == hashlib.sha256(html).hexdigest(), "receipt hashes decoded entity bytes")
check(trace.receipt.adapter == "deterministic-web-fetch", "receipt names the adapter")

answers = iter([("1.1.1.1",), ("8.8.8.8",)])
redirect = FakeTransport(
    plan("https://example.com/start", response(302, {"Location": "/final"})),
    plan(
        "https://example.com/final",
        response(headers={"Content-Type": "text/plain"}, body=b"done", peer="8.8.8.8"),
        "8.8.8.8",
    ),
)
redirect_trace = fetch_with(
    redirect,
    url="https://example.com/start",
    resolver=lambda host, port: next(answers),
)
check(
    redirect_trace.visited_urls
    == ("https://example.com/start", "https://example.com/final"),
    "relative redirects are followed and audited",
)
check(redirect_trace.receipt.url == "https://example.com/final", "receipt binds the final URL")

outside = FakeTransport(plan(
    "https://example.com/start",
    response(302, {"Location": "https://evil.test/x"}),
))
rejects(
    lambda: fetch_with(outside, url="https://example.com/start"),
    "outside redirect is rejected before a second request",
)
check(len(outside.calls) == 1, "outside redirect never reaches transport")

CASES = [
    (
        "HTTPS downgrade is rejected",
        FakeTransport(plan("https://example.com/a", response(301, {"Location": "http://example.com/b"}))),
        {},
        "downgrade",
    ),
    (
        "redirect without Location is rejected",
        FakeTransport(plan("https://example.com/a", response(302))),
        {},
        "Location",
    ),
    (
        "private DNS answer rejects the whole resolution",
        FakeTransport(),
        {"resolver": lambda host, port: ("1.1.1.1", "10.0.0.1")},
        "non-public",
    ),
    (
        "empty DNS answers fail closed",
        FakeTransport(),
        {"resolver": lambda host, port: ()},
        "no addresses",
    ),
    (
        "transport must prove it used the validated peer",
        FakeTransport(plan(
            "https://example.com/a",
            response(headers={"Content-Type": "text/plain"}, body=b"x", peer="8.8.8.8"),
        )),
        {},
        "did not match",
    ),
    (
        "transport cannot report a private peer",
        FakeTransport(plan(
            "https://example.com/a",
            response(headers={"Content-Type": "text/plain"}, body=b"x", peer="127.0.0.1"),
        )),
        {},
        "non-public peer",
    ),
    (
        "transport wire-byte cap is enforced",
        FakeTransport(plan(
            "https://example.com/a",
            response(headers={"Content-Type": "text/plain", "Content-Encoding": "gzip"}, body=b"x" * 4098),
        )),
        {},
        "max_wire_bytes",
    ),
    (
        "oversized Content-Length is rejected",
        FakeTransport(plan(
            "https://example.com/a",
            response(headers={"Content-Type": "text/plain", "Content-Length": "4097"}, body=b"x"),
        )),
        {},
        "max_source_bytes",
    ),
    (
        "actual body size is enforced",
        FakeTransport(plan(
            "https://example.com/a",
            response(headers={"Content-Type": "text/plain"}, body=b"x" * 4097),
        )),
        {},
        "max_source_bytes",
    ),
    (
        "unknown content encodings are rejected",
        FakeTransport(plan(
            "https://example.com/a",
            response(headers={"Content-Type": "text/plain", "Content-Encoding": "br"}, body=b"x"),
        )),
        {},
        "encoding",
    ),
    (
        "download responses are rejected",
        FakeTransport(plan(
            "https://example.com/a",
            response(headers={"Content-Type": "text/plain", "Content-Disposition": "attachment"}, body=b"x"),
        )),
        {},
        "download",
    ),
    (
        "binary media types are rejected",
        FakeTransport(plan(
            "https://example.com/a",
            response(headers={"Content-Type": "application/octet-stream"}, body=b"\0"),
        )),
        {},
        "media type",
    ),
    (
        "unknown charsets are rejected",
        FakeTransport(plan(
            "https://example.com/a",
            response(headers={"Content-Type": "text/plain; charset=not-a-codec"}, body=b"x"),
        )),
        {},
        "charset",
    ),
    (
        "sources without readable text are rejected",
        FakeTransport(plan(
            "https://example.com/a",
            response(headers={"Content-Type": "text/html"}, body=b"<script>hidden</script>"),
        )),
        {},
        "readable",
    ),
    (
        "non-success status is rejected",
        FakeTransport(plan(
            "https://example.com/a",
            response(404, {"Content-Type": "text/plain"}, b"no"),
        )),
        {},
        "404",
    ),
]
for name, transport_case, kwargs, message in CASES:
    rejects(lambda t=transport_case, k=kwargs: fetch_with(t, **k), name, message)

loop = FakeTransport(
    plan("https://example.com/a", response(302, {"Location": "/b"})),
    plan("https://example.com/b", response(302, {"Location": "/a"})),
)
rejects(lambda: fetch_with(loop), "redirect loops are rejected", "loop")

step_policy = ReadOnlyBrowserPolicy(
    allowed_domains=("example.com",),
    max_steps=1,
    max_pages=1,
    timeout_seconds=10,
    max_source_bytes=4096,
)
step = FakeTransport(plan("https://example.com/a", response(302, {"Location": "/b"})))
rejects(lambda: fetch_with(step, policy=step_policy), "redirects consume the step budget", "step budget")

decoded = b"compressed source"
compressed = FakeTransport(plan(
    "https://example.com/a",
    response(
        headers={"Content-Type": "text/plain", "Content-Encoding": "gzip"},
        body=gzip.compress(decoded),
    ),
))
compressed_trace = fetch_with(compressed)
check(compressed_trace.receipt.bytes_read == len(decoded), "receipt byte count uses decoded content")
check(
    compressed_trace.receipt.content_sha256 == hashlib.sha256(decoded).hexdigest(),
    "gzip receipt hashes decoded content",
)

bomb_policy = ReadOnlyBrowserPolicy(
    allowed_domains=("example.com",),
    max_steps=2,
    max_pages=1,
    timeout_seconds=10,
    max_source_bytes=1024,
)
bomb = FakeTransport(plan(
    "https://example.com/a",
    response(
        headers={"Content-Type": "text/plain", "Content-Encoding": "gzip"},
        body=gzip.compress(b"x" * 1025),
    ),
))
rejects(lambda: fetch_with(bomb, policy=bomb_policy), "decompressed byte budget is enforced", "decoded source")

transport_error = FakeTransport(plan(
    "https://example.com/a",
    RuntimeError("secret socket detail"),
))
try:
    fetch_with(transport_error)
except WebFetchError as exc:
    check("secret socket detail" not in str(exc), "transport exception details are not leaked")
else:
    check(False, "transport exceptions become WebFetchError")

times = iter([0.0, 0.0, 11.0])
late = FakeTransport(plan(
    "https://example.com/a",
    response(headers={"Content-Type": "text/plain"}, body=b"x"),
))
rejects(
    lambda: fetch_with(late, clock=lambda: next(times)),
    "overall deadline is checked after transport",
    "timeout",
)

plain = FakeTransport(plan(
    "https://example.com/path/report.txt",
    response(headers={"Content-Type": "text/plain"}, body=b" plain   text "),
))
plain_trace = fetch_with(plain, url="https://example.com/path/report.txt")
check(plain_trace.receipt.title == "report.txt", "plain text uses a deterministic URL title")
check(plain_trace.receipt.excerpt == "plain text", "plain text whitespace is normalized")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
