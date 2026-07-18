from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace

from app.browser_host import (
    HOST_PROTOCOL_VERSION,
    BrowserBackendError,
    BrowserBackendRun,
    BrowserCitationDraft,
    BrowserHost,
    BrowserHostRequest,
    BrowserHostResponse,
    BrowserSourceArtifact,
    encode_response,
    handle_payload,
)
from app.research_contract import ReadOnlyBrowserPolicy, ResearchRequest, source_id_for

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def run_async(coro):
    return asyncio.run(coro)


POLICY = ReadOnlyBrowserPolicy(
    allowed_domains=("example.com", "*.example.com"),
    max_steps=4,
    max_pages=2,
    timeout_seconds=1,
    max_source_bytes=1024,
)
RESEARCH = ResearchRequest(
    query="Find the current fixture release",
    policy=POLICY,
    max_sources=1,
)
REQUEST = BrowserHostRequest(request_id="req-001", research=RESEARCH)
CONTENT = b"<html><title>Fixture release</title><body>Version 7 is live.</body></html>"
SOURCE = BrowserSourceArtifact(
    url="https://EXAMPLE.com:443/report#section",
    title="Fixture release",
    content=CONTENT,
    excerpt="Version 7 is live.",
    media_type="text/html",
)
VALID_RUN = BrowserBackendRun(
    answer="Version 7 is live [1].",
    sources=(SOURCE,),
    citations=(
        BrowserCitationDraft(
            marker="1",
            statement="Version 7 is live.",
            source_indexes=(0,),
        ),
    ),
    visited_urls=("https://example.com/report",),
    steps=2,
    warnings=("fixture backend only",),
)


class FixtureBackend:
    def __init__(
        self,
        run=VALID_RUN,
        *,
        adapter_name="fixture-browser",
        error=None,
        delay=False,
        close_error=None,
    ) -> None:
        self.adapter_name = adapter_name
        self.run = run
        self.error = error
        self.delay = delay
        self.close_error = close_error
        self.closed = False
        self.cancelled = False
        self.seen_request = None

    async def research(self, request):
        self.seen_request = request
        if self.delay:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        if self.error is not None:
            raise self.error
        return self.run

    async def close(self):
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


def execute(backend, request=REQUEST):
    return run_async(BrowserHost(backend).execute(request))


backend = FixtureBackend()
response = execute(backend)
check(response.ok, "valid fixture backend succeeds")
check(backend.closed, "backend closes after success")
check(backend.seen_request is RESEARCH, "validated research request reaches backend")
payload = response.to_dict()
research = payload["result"]["research"]
trace = payload["result"]["trace"]
receipt = research["sources"][0]
check(research["answer"] == "Version 7 is live [1].", "answer is preserved")
check(receipt["url"] == "https://example.com/report", "source URL is canonicalized")
check(receipt["content_sha256"] == hashlib.sha256(CONTENT).hexdigest(), "host hashes raw source bytes")
check(
    receipt["source_id"] == source_id_for(receipt["url"], receipt["content_sha256"]),
    "host creates deterministic source id",
)
check(receipt["adapter"] == "browser-host:fixture-browser", "host owns adapter identity")
check(research["citations"][0]["source_ids"] == [receipt["source_id"]], "source indexes become receipt ids")
check(trace["visited_urls"] == ["https://example.com/report"], "visit trace is canonicalized")
check(trace["steps"] == 2 and trace["adapter"] == "fixture-browser", "bounded execution trace is returned")
check(research["warnings"] == ["fixture backend only"], "bounded warnings are preserved")

request_dict = REQUEST.to_dict()
round_trip = BrowserHostRequest.from_dict(request_dict)
check(round_trip == REQUEST, "strict request round-trips")
check(round_trip.protocol_version == HOST_PROTOCOL_VERSION, "host protocol version is explicit")


def invalid_request(mutator, name):
    value = json.loads(json.dumps(request_dict))
    mutator(value)
    result = run_async(handle_payload(json.dumps(value).encode("utf-8"), FixtureBackend()))
    check(not result.ok and result.error_code == "invalid_request", name)


invalid_request(lambda value: value.__setitem__("extra", True), "unknown root fields are rejected")
invalid_request(lambda value: value["research"].pop("query"), "missing research fields are rejected")
invalid_request(lambda value: value["research"]["policy"].__setitem__("max_steps", True), "boolean budgets are rejected")
invalid_request(lambda value: value["research"]["policy"].__setitem__("profile_mode", "persistent"), "persistent profiles are rejected")
invalid_request(lambda value: value["research"]["policy"].__setitem__("credentials", "allow"), "credential access is rejected")
invalid_request(lambda value: value["research"]["policy"].__setitem__("allowed_domains", []), "empty allowlist is rejected")
invalid_request(lambda value: value.__setitem__("request_id", "bad request id"), "invalid request id is rejected")
invalid_request(lambda value: value.__setitem__("protocol_version", "future.v9"), "unknown protocol version is rejected")

malformed = run_async(handle_payload(b"{not-json", FixtureBackend()))
check(not malformed.ok and malformed.error_code == "invalid_request", "malformed JSON is normalized")
non_utf8 = run_async(handle_payload(b"\xff", FixtureBackend()))
check(not non_utf8.ok and non_utf8.error_code == "invalid_request", "non-UTF8 input is normalized")
oversized = run_async(handle_payload(b"x" * (64 * 1024 + 1), FixtureBackend()))
check(not oversized.ok and oversized.error_code == "invalid_request", "input byte cap is enforced")

unavailable = run_async(handle_payload(json.dumps(request_dict).encode("utf-8")))
check(not unavailable.ok and unavailable.error_code == "backend_unavailable", "default process fails closed without adapter")

secret_error_backend = FixtureBackend(error=RuntimeError("supersecret backend detail"))
secret_error = execute(secret_error_backend)
check(not secret_error.ok and secret_error.error_code == "backend_failed", "unexpected backend errors are normalized")
check("supersecret" not in json.dumps(secret_error.to_dict()), "raw backend error details are not leaked")
check(secret_error_backend.closed, "backend closes after unexpected failure")

known_error_backend = FixtureBackend(error=BrowserBackendError("private adapter detail"))
known_error = execute(known_error_backend)
check(not known_error.ok and known_error.error_code == "backend_failed", "known backend errors are normalized")
check("private" not in json.dumps(known_error.to_dict()), "known backend details are not leaked")

timeout_backend = FixtureBackend(delay=True)
timeout = execute(timeout_backend)
check(not timeout.ok and timeout.error_code == "backend_timeout", "backend deadline is enforced")
check(timeout_backend.cancelled, "timed-out backend task is cancelled")
check(timeout_backend.closed, "backend closes after timeout")

cleanup_backend = FixtureBackend(close_error=RuntimeError("private cleanup detail"))
cleanup = execute(cleanup_backend)
check(not cleanup.ok and cleanup.error_code == "cleanup_failed", "cleanup failure invalidates success")
check("private" not in json.dumps(cleanup.to_dict()), "cleanup details are not leaked")


def violates(run, name, *, adapter_name="fixture-browser"):
    result = execute(FixtureBackend(run=run, adapter_name=adapter_name))
    check(not result.ok and result.error_code == "contract_violation", name)


violates(replace(VALID_RUN, steps=0), "zero browser steps are rejected")
violates(replace(VALID_RUN, steps=5), "max_steps is enforced")
violates(replace(VALID_RUN, visited_urls=()), "empty visit trace is rejected")
violates(
    replace(
        VALID_RUN,
        visited_urls=(
            "https://example.com/one",
            "https://example.com/two",
            "https://example.com/three",
        ),
    ),
    "max_pages is enforced",
)
violates(replace(VALID_RUN, visited_urls=("https://evil.test/report",)), "forbidden visited URL is rejected")
violates(replace(VALID_RUN, sources=()), "empty source evidence is rejected")
violates(replace(VALID_RUN, sources=(SOURCE, SOURCE)), "max_sources is enforced")
violates(
    replace(VALID_RUN, sources=(replace(SOURCE, url="https://example.com/not-visited"),)),
    "source must appear in visit trace",
)
violates(
    replace(
        VALID_RUN,
        sources=(replace(SOURCE, url="https://evil.test/report"),),
        visited_urls=("https://example.com/report",),
    ),
    "forbidden source URL is rejected",
)
violates(
    replace(VALID_RUN, sources=(replace(SOURCE, content=b"x" * 1025),)),
    "source byte cap is enforced",
)
violates(
    replace(
        VALID_RUN,
        citations=(replace(VALID_RUN.citations[0], source_indexes=()),),
    ),
    "citation requires source indexes",
)
violates(
    replace(
        VALID_RUN,
        citations=(replace(VALID_RUN.citations[0], source_indexes=(1,)),),
    ),
    "citation source index bounds are enforced",
)
violates(replace(VALID_RUN, citations=()), "research result requires citations")
violates(replace(VALID_RUN, answer="Version 7 is live."), "answer must contain declared marker")
violates(
    replace(
        VALID_RUN,
        citations=(VALID_RUN.citations[0], VALID_RUN.citations[0]),
    ),
    "citation markers must be unique",
)
violates(replace(VALID_RUN, warnings=("x" * 1001,)), "warning length is bounded")
violates(VALID_RUN, "invalid backend adapter name is rejected", adapter_name="Bad Adapter")

large = BrowserHostResponse.success("req-large", {"blob": "x" * (2 * 1024 * 1024)})
large_encoded = json.loads(encode_response(large))
check(not large_encoded["ok"] and large_encoded["error"]["code"] == "response_too_large", "output byte cap fails closed")
check(encode_response(response).endswith(b"\n"), "process output is one newline-terminated JSON object")

process_env = dict(os.environ)
process_env["PYTHONPATH"] = "worker"
process = subprocess.run(
    [sys.executable, "-m", "app.browser_host"],
    input=json.dumps(request_dict).encode("utf-8"),
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    env=process_env,
    timeout=10,
    check=False,
)
process_result = json.loads(process.stdout)
check(process.returncode == 0, "stdio host returns a protocol response")
check(process_result["error"]["code"] == "backend_unavailable", "stdio host remains dormant")
check(process.stderr == b"", "stdio host writes no logs or tracebacks to protocol stderr")
check(process.stdout.count(b"\n") == 1, "stdio host emits exactly one response line")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
