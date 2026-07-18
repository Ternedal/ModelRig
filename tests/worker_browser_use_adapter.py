from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from app.browser_host import BrowserBackendError, BrowserBackendUnavailable
from app.browser_use_adapter import (
    SUPPORTED_BROWSER_USE_VERSION,
    VERIFIED_SOURCE_MEDIA_TYPE,
    BrowserUseBackend,
    BrowserUseBindings,
    BrowserUseResearchOutput,
)
from app.research_contract import ReadOnlyBrowserPolicy, ResearchRequest, SourceReceipt
from app.web_fetch import FetchTrace, WebFetchError

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def run(coro):
    return asyncio.run(coro)


POLICY = ReadOnlyBrowserPolicy(
    allowed_domains=("example.com", "*.example.com"),
    max_steps=4,
    max_pages=4,
    timeout_seconds=10,
    max_source_bytes=4096,
)
REQUEST = ResearchRequest(
    query="Find the fixture release",
    policy=POLICY,
    max_sources=2,
)
RAW = b"<html><title>Release</title><body>Version 7 is live.</body></html>"
RECEIPT = SourceReceipt.from_content(
    url="https://example.com/final",
    title="Release",
    content=RAW,
    excerpt="Version 7 is live.",
    media_type="text/html",
    adapter="deterministic-web-fetch",
    retrieved_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
)
TRACE = FetchTrace(
    requested_url="https://example.com/report",
    final_url="https://example.com/final",
    visited_urls=("https://example.com/report", "https://example.com/final"),
    resolved_addresses=(("https://example.com/report", ("1.1.1.1",)),),
    receipt=RECEIPT,
)
UNTRUSTED_RECEIPT = SourceReceipt.from_content(
    url="https://example.com/final",
    title="Release",
    content=RAW,
    excerpt="Version 7 is live.",
    media_type="text/html",
    adapter="browser-use",
    retrieved_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
)
UNTRUSTED_TRACE = FetchTrace(
    requested_url="https://example.com/report",
    final_url="https://example.com/final",
    visited_urls=("https://example.com/report", "https://example.com/final"),
    resolved_addresses=(("https://example.com/report", ("1.1.1.1",)),),
    receipt=UNTRUSTED_RECEIPT,
)


class FakeHistory:
    def __init__(
        self,
        *,
        output=None,
        urls=None,
        steps=2,
        successful=True,
        has_errors=False,
    ) -> None:
        self.structured_output = output or {
            "answer": "Version 7 is live [1].",
            "citations": [
                {
                    "marker": "1",
                    "statement": "Version 7 is live.",
                    "urls": ["https://example.com/report"],
                }
            ],
        }
        self._urls = urls or ["about:blank", "https://EXAMPLE.com:443/report#top"]
        self._steps = steps
        self._successful = successful
        self._has_errors = has_errors

    def urls(self):
        return self._urls

    def number_of_steps(self):
        return self._steps

    def is_successful(self):
        return self._successful

    def has_errors(self):
        return self._has_errors


class FakeAgent:
    def __init__(self, history=None, run_error=None, close_error=None) -> None:
        self.history = history or FakeHistory()
        self.run_error = run_error
        self.close_error = close_error
        self.run_calls = []
        self.close_calls = 0

    async def run(self, **kwargs):
        self.run_calls.append(kwargs)
        if self.run_error:
            raise self.run_error
        return self.history

    async def close(self):
        self.close_calls += 1
        if self.close_error:
            raise self.close_error


class FactoryRecorder:
    def __init__(self, agent: FakeAgent) -> None:
        self.agent = agent
        self.profile_kwargs = None
        self.tools_kwargs = None
        self.agent_kwargs = None

    def profile(self, **kwargs):
        self.profile_kwargs = kwargs
        return {"profile": kwargs}

    def tools(self, **kwargs):
        self.tools_kwargs = kwargs
        return {"tools": kwargs}

    def create_agent(self, **kwargs):
        self.agent_kwargs = kwargs
        return self.agent

    def bindings(self, version=SUPPORTED_BROWSER_USE_VERSION):
        return BrowserUseBindings(
            agent_factory=self.create_agent,
            profile_factory=self.profile,
            tools_factory=self.tools,
            version=version,
        )


class FakeFetcher:
    def __init__(self, result=TRACE, error=None) -> None:
        self.result = result
        self.error = error
        self.calls = []

    def fetch(self, url, policy):
        self.calls.append((url, policy))
        if self.error:
            raise self.error
        return self.result


def backend_with(
    *,
    history=None,
    fetcher=None,
    agent_error=None,
    close_error=None,
    llm=object(),
    version=SUPPORTED_BROWSER_USE_VERSION,
):
    agent = FakeAgent(history=history, run_error=agent_error, close_error=close_error)
    recorder = FactoryRecorder(agent)
    backend = BrowserUseBackend(
        fetcher=fetcher or FakeFetcher(),
        llm_factory=lambda: llm,
        bindings_loader=lambda: recorder.bindings(version),
    )
    return backend, agent, recorder


optional_requirements = Path("worker/requirements-browser-use.txt").read_text(encoding="utf-8")
base_requirements = Path("worker/requirements.txt").read_text(encoding="utf-8")
check(
    f"browser-use[core]=={SUPPORTED_BROWSER_USE_VERSION}" in optional_requirements.splitlines(),
    "optional Browser Use version is pinned exactly",
)
check("browser-use" not in base_requirements.lower(), "base worker does not install Browser Use")

backend, agent, recorder = backend_with(history=FakeHistory(has_errors=True))
result = run(backend.research(REQUEST))
check(result.answer == "Version 7 is live [1].", "structured answer is preserved")
check(result.steps == 2, "history step count is preserved")
check(
    result.visited_urls == (
        "https://example.com/report",
        "https://example.com/final",
    ),
    "browser trace is canonicalized and verified redirect is appended",
)
envelope = json.loads(result.sources[0].content)
check(envelope["schema_version"] == "modelrig.verified-web-source.v1", "verified envelope schema is explicit")
check(envelope["url"] == RECEIPT.url, "envelope keeps the pinned fetch final URL")
check(envelope["content_sha256"] == RECEIPT.content_sha256, "original content hash comes from deterministic fetch")
check(envelope["bytes_read"] == RECEIPT.bytes_read, "original content byte count is preserved")
check(envelope["adapter"] == "deterministic-web-fetch", "envelope records trusted fetch provenance")
check(result.sources[0].url == "https://example.com/final", "source uses verified final URL")
check(result.sources[0].title == "Release", "verified source metadata is preserved")
check(result.sources[0].media_type == VERIFIED_SOURCE_MEDIA_TYPE, "verified envelope has a dedicated media type")
check(RECEIPT.content_sha256 in result.sources[0].excerpt, "verified digest is visible in the evidence excerpt")
check(result.citations[0].source_indexes == (0,), "citation URLs map to verified source indexes")
check(result.warnings == ("Browser Use reported one or more recoverable step errors.",), "raw step errors are normalized")
check(agent.run_calls == [{"max_steps": 4}], "Browser Use receives the hard step budget")
check(recorder.profile_kwargs["headless"] is True, "browser profile is headless")
check(recorder.profile_kwargs["allowed_domains"] == ["example.com", "*.example.com"], "browser profile receives exact allowlist")
check(recorder.profile_kwargs["user_data_dir"] is None, "browser profile is ephemeral")
check(recorder.profile_kwargs["storage_state"] is None, "browser profile imports no cookies")
check(recorder.profile_kwargs["keep_alive"] is False, "browser process is single-use")
check(recorder.profile_kwargs["block_ip_addresses"] is True, "direct IP navigation is blocked")
check(recorder.profile_kwargs["downloads_path"] is None, "download quarantine remains runtime-owned")
check(recorder.profile_kwargs["accept_downloads"] is False, "browser context refuses downloads")
check(recorder.profile_kwargs["permissions"] == [], "browser context grants no permissions")
check(recorder.profile_kwargs["cross_origin_iframes"] is False, "cross-origin iframe traversal is disabled")
check(recorder.profile_kwargs["use_cloud"] is False, "cloud browser fallback is disabled")
check(recorder.profile_kwargs["disable_security"] is False, "browser security remains enabled")
check(recorder.profile_kwargs["demo_mode"] is False, "demo overlay is disabled")
check(recorder.profile_kwargs["record_har_path"] is None, "HAR recording is disabled")
check(recorder.profile_kwargs["record_video_dir"] is None, "video recording is disabled")
check(recorder.profile_kwargs["traces_dir"] is None, "trace recording is disabled")
excluded = set(recorder.tools_kwargs["exclude_actions"])
check({"input", "upload_file", "send_keys", "evaluate", "write_file"} <= excluded, "write-capable Browser Use actions are excluded")
check(recorder.agent_kwargs["output_model_schema"] is BrowserUseResearchOutput, "agent output is schema-bound")
check(recorder.agent_kwargs["use_vision"] is False, "vision/screenshot path is disabled")
check(recorder.agent_kwargs["sensitive_data"] is None, "no credentials are supplied")
check(recorder.agent_kwargs["available_file_paths"] == [], "no upload files are exposed")
check(recorder.agent_kwargs["max_actions_per_step"] == 1, "one action per step is enforced")
check("Do not type into forms" in recorder.agent_kwargs["task"], "task repeats read-only restrictions")
run(backend.close())
run(backend.close())
check(agent.close_calls == 1, "backend cleanup is idempotent")

# Duplicate URLs across citations are fetched once and reuse the same source index.
duplicate_history = FakeHistory(output={
    "answer": "Version 7 is live [1] and confirmed [2].",
    "citations": [
        {"marker": "1", "statement": "Version 7 is live.", "urls": ["https://example.com/report"]},
        {"marker": "2", "statement": "The release is confirmed.", "urls": ["https://example.com/report"]},
    ],
})
duplicate_fetcher = FakeFetcher()
duplicate_backend, _, _ = backend_with(history=duplicate_history, fetcher=duplicate_fetcher)
duplicate_result = run(duplicate_backend.research(REQUEST))
check(len(duplicate_fetcher.calls) == 1, "duplicate citation URLs are re-fetched once")
check(len(duplicate_result.sources) == 1, "duplicate citations share one evidence source")
check(duplicate_result.citations[1].source_indexes == (0,), "duplicate citations reuse source index")
run(duplicate_backend.close())


def expect_research_failure(name, *, history=None, fetcher=None, agent_error=None, llm=object(), version=SUPPORTED_BROWSER_USE_VERSION):
    candidate, agent_instance, _ = backend_with(
        history=history,
        fetcher=fetcher,
        agent_error=agent_error,
        llm=llm,
        version=version,
    )
    try:
        run(candidate.research(REQUEST))
    except (BrowserBackendError, BrowserBackendUnavailable):
        check(True, name)
    else:
        check(False, name)
    finally:
        try:
            run(candidate.close())
        except Exception:
            pass
    return agent_instance


expect_research_failure(
    "unsupported Browser Use versions fail closed",
    version="0.13.3",
)
expect_research_failure(
    "missing LLM configuration fails closed",
    llm=None,
)
expect_research_failure(
    "agent execution failures are normalized",
    agent_error=RuntimeError("private agent detail"),
)
expect_research_failure(
    "unsuccessful history is rejected",
    history=FakeHistory(successful=False),
)
expect_research_failure(
    "missing structured output is rejected",
    history=FakeHistory(output={"answer": "x", "citations": []}),
)
expect_research_failure(
    "forbidden browser history is rejected",
    history=FakeHistory(urls=["https://evil.test/report"]),
)
expect_research_failure(
    "non-web browser history is rejected",
    history=FakeHistory(urls=["file:///etc/passwd"]),
)
expect_research_failure(
    "citation must appear in visit trace",
    history=FakeHistory(
        output={
            "answer": "Version 7 is live [1].",
            "citations": [{"marker": "1", "statement": "Version 7 is live.", "urls": ["https://example.com/other"]}],
        }
    ),
)
expect_research_failure(
    "invalid history step count is rejected",
    history=FakeHistory(steps=5),
)
expect_research_failure(
    "deterministic fetch failures reject the citation",
    fetcher=FakeFetcher(error=WebFetchError("private transport detail")),
)
expect_research_failure(
    "invalid deterministic fetch result is rejected",
    fetcher=FakeFetcher(result=object()),
)
expect_research_failure(
    "non-deterministic receipts are rejected",
    fetcher=FakeFetcher(result=UNTRUSTED_TRACE),
)

# More unique citations than max_sources fail before any unbounded evidence set is returned.
limited_request = ResearchRequest(query="fixture", policy=POLICY, max_sources=1)
limited_history = FakeHistory(
    urls=["https://example.com/a", "https://example.com/b"],
    output={
        "answer": "A [1]. B [2].",
        "citations": [
            {"marker": "1", "statement": "A.", "urls": ["https://example.com/a"]},
            {"marker": "2", "statement": "B.", "urls": ["https://example.com/b"]},
        ],
    },
)
limited_backend, _, _ = backend_with(history=limited_history)
try:
    run(limited_backend.research(limited_request))
except BrowserBackendError:
    check(True, "max_sources is enforced before re-fetch")
else:
    check(False, "max_sources is enforced before re-fetch")
run(limited_backend.close())

# Sync close methods are supported because Browser Use lifecycle APIs have changed before.
class SyncCloseAgent(FakeAgent):
    def close(self):
        self.close_calls += 1


sync_agent = SyncCloseAgent()
sync_recorder = FactoryRecorder(sync_agent)
sync_backend = BrowserUseBackend(
    fetcher=FakeFetcher(),
    llm_factory=lambda: object(),
    bindings_loader=lambda: sync_recorder.bindings(),
)
run(sync_backend.research(REQUEST))
run(sync_backend.close())
check(sync_agent.close_calls == 1, "sync Browser Use close is accepted")

# If Agent has no close, the adapter closes the browser session directly.
class Session:
    def __init__(self):
        self.calls = 0

    async def close(self):
        self.calls += 1


class SessionOnlyAgent:
    def __init__(self):
        self.browser_session = Session()
        self.run_calls = []

    async def run(self, **kwargs):
        self.run_calls.append(kwargs)
        return FakeHistory()


session_agent = SessionOnlyAgent()
session_recorder = FactoryRecorder(session_agent)
session_backend = BrowserUseBackend(
    fetcher=FakeFetcher(),
    llm_factory=lambda: object(),
    bindings_loader=lambda: session_recorder.bindings(),
)
run(session_backend.research(REQUEST))
run(session_backend.close())
check(session_agent.browser_session.calls == 1, "browser session closes when Agent has no close")

# Cleanup failures are deliberately visible to BrowserHost as cleanup_failed.
close_backend, close_agent, _ = backend_with(close_error=RuntimeError("private close detail"))
run(close_backend.research(REQUEST))
try:
    run(close_backend.close())
except RuntimeError:
    check(True, "cleanup failure is propagated to BrowserHost")
else:
    check(False, "cleanup failure is propagated to BrowserHost")
check(close_agent.close_calls == 1, "failed cleanup is attempted once")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
