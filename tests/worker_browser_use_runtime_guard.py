from __future__ import annotations

import asyncio
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.browser_host import BrowserBackendError, BrowserBackendUnavailable
from app.browser_use_adapter import (
    READ_ONLY_EXCLUDED_ACTIONS,
    SUPPORTED_BROWSER_USE_VERSION,
    BrowserUseBackend,
    BrowserUseBindings,
)
from app.research_contract import ReadOnlyBrowserPolicy, ResearchRequest, SourceReceipt
from app.web_fetch import FetchTrace

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
    allowed_domains=("example.com",),
    max_steps=3,
    max_pages=2,
    timeout_seconds=10,
    max_source_bytes=4096,
)
REQUEST = ResearchRequest(query="fixture", policy=POLICY, max_sources=1)
RAW = b"verified"
RECEIPT = SourceReceipt.from_content(
    url="https://example.com/report",
    title="Report",
    content=RAW,
    excerpt="Verified report.",
    media_type="text/plain",
    adapter="deterministic-web-fetch",
    retrieved_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
)
TRACE = FetchTrace(
    requested_url="https://example.com/report",
    final_url="https://example.com/report",
    visited_urls=("https://example.com/report",),
    resolved_addresses=(("https://example.com/report", ("1.1.1.1",)),),
    receipt=RECEIPT,
)


class History:
    structured_output = {
        "answer": "Verified [1].",
        "citations": [
            {
                "marker": "1",
                "statement": "Verified.",
                "urls": ["https://example.com/report"],
            }
        ],
    }

    def urls(self):
        return ["https://example.com/report"]

    def number_of_steps(self):
        return 1

    def is_successful(self):
        return True

    def has_errors(self):
        return False


class Fetcher:
    def __init__(self) -> None:
        self.calls = 0

    def fetch(self, url, policy):
        self.calls += 1
        return TRACE


class Agent:
    def __init__(
        self,
        download_path: Path,
        *,
        write_download: bool,
        fail_close: bool = False,
    ) -> None:
        self.download_path = download_path
        self.write_download = write_download
        self.fail_close = fail_close
        self.browser_session = SimpleNamespace(closed=False)
        self.closed = 0

    async def run(self, **kwargs):
        if self.write_download:
            (self.download_path / "forbidden.bin").write_bytes(b"forbidden")
        return History()

    async def close(self):
        self.closed += 1
        if self.fail_close:
            raise RuntimeError("simulated browser close failure")
        self.browser_session.closed = True


class FakeNetworkGuard:
    def __init__(self, browser_session, allowed_domains) -> None:
        self.browser_session = browser_session
        self.allowed_domains = tuple(allowed_domains)
        self.installed = 0
        self.health_checks = 0
        self.closed = 0
        self.browser_was_closed_on_close = False

    async def install(self) -> None:
        self.installed += 1

    async def assert_healthy(self) -> None:
        self.health_checks += 1

    async def close(self) -> None:
        await self.assert_healthy()
        self.closed += 1
        self.browser_was_closed_on_close = bool(
            getattr(self.browser_session, "closed", False)
        )


class GuardFactory:
    def __init__(self) -> None:
        self.instances: list[FakeNetworkGuard] = []

    def __call__(self, browser_session, allowed_domains):
        guard = FakeNetworkGuard(browser_session, allowed_domains)
        self.instances.append(guard)
        return guard


class Runtime:
    def __init__(
        self,
        *,
        write_download: bool,
        unsafe_path: Path | None = None,
        fail_close: bool = False,
    ) -> None:
        self.write_download = write_download
        self.unsafe_path = unsafe_path
        self.fail_close = fail_close
        self.download_path: Path | None = None
        self.user_data_path: Path | None = None
        self.agent: Agent | None = None
        self.profile_kwargs = None
        self.profile_object = None
        self.tools_kwargs = None

    def profile(self, **kwargs):
        self.profile_kwargs = kwargs
        if self.unsafe_path is not None:
            download_path = self.unsafe_path
            download_path.mkdir(parents=True, exist_ok=True)
        else:
            download_path = Path(tempfile.mkdtemp(prefix="browser-use-downloads-"))
        user_data_path = Path(tempfile.mkdtemp(prefix="browser-use-user-data-dir-"))
        self.download_path = download_path
        self.user_data_path = user_data_path
        profile_fields = dict(kwargs)
        profile_fields.update(
            downloads_path=download_path,
            user_data_dir=user_data_path,
        )
        profile = SimpleNamespace(**profile_fields)
        self.profile_object = profile
        return profile

    def tools(self, **kwargs):
        self.tools_kwargs = kwargs
        actions = {
            "navigate": SimpleNamespace(param_model=object),
            "go_back": SimpleNamespace(param_model=object),
            "wait": SimpleNamespace(param_model=object),
            "scroll": SimpleNamespace(param_model=object),
            "extract": SimpleNamespace(param_model=object),
            "done": SimpleNamespace(param_model=object),
        }
        return SimpleNamespace(
            registry=SimpleNamespace(
                registry=SimpleNamespace(actions=actions),
            )
        )

    def create_agent(self, **kwargs):
        assert self.download_path is not None
        self.agent = Agent(
            self.download_path,
            write_download=self.write_download,
            fail_close=self.fail_close,
        )
        return self.agent

    def bindings(self):
        return BrowserUseBindings(
            agent_factory=self.create_agent,
            profile_factory=self.profile,
            tools_factory=self.tools,
            version=SUPPORTED_BROWSER_USE_VERSION,
            runtime_validated=True,
        )


optional_requirements = Path("worker/requirements-browser-use.txt").read_text(encoding="utf-8")
check("-r requirements.txt" not in optional_requirements, "browser runtime does not inherit worker dependencies")
check(
    f"browser-use[core]=={SUPPORTED_BROWSER_USE_VERSION}" in optional_requirements.splitlines(),
    "browser runtime keeps the exact Browser Use pin",
)

# Clean Browser Use temp directories are accepted and removed during cleanup.
clean_runtime = Runtime(write_download=False)
clean_fetcher = Fetcher()
clean_guards = GuardFactory()
clean_backend = BrowserUseBackend(
    fetcher=clean_fetcher,
    llm_factory=lambda: object(),
    bindings_loader=clean_runtime.bindings,
    network_guard_factory=clean_guards,
)
clean_result = run(clean_backend.research(REQUEST))
clean_download_path = clean_runtime.download_path
clean_user_data_path = clean_runtime.user_data_path
check(clean_result.answer == "Verified [1].", "empty download quarantine permits research")
check(clean_fetcher.calls == 1, "clean run reaches deterministic citation re-fetch")
check(len(clean_guards.instances) == 1, "validated runtime receives one browser request guard")
clean_guard = clean_guards.instances[0]
check(clean_guard.browser_session is clean_runtime.agent.browser_session, "guard binds to the agent browser session")
check(clean_guard.allowed_domains == POLICY.allowed_domains, "guard receives the exact research allowlist")
check(clean_guard.installed == 1, "guard installs before agent execution")
check(clean_guard.health_checks == 1, "guard health is checked after agent execution")
check(clean_runtime.profile_kwargs["downloads_path"] is None, "Browser Use owns download temp path creation")
check(clean_runtime.profile_kwargs["user_data_dir"] is None, "Browser Use owns profile temp path creation")
check(clean_runtime.profile_kwargs["proxy"] is None, "Browser Use proxy handling is explicitly disabled")
check(clean_runtime.profile_kwargs["accept_downloads"] is False, "browser context refuses downloads")
check(clean_runtime.profile_kwargs["permissions"] == [], "validated runtime grants no browser permissions")
check(clean_runtime.profile_kwargs["cross_origin_iframes"] is False, "cross-origin iframe traversal is disabled")
check(clean_runtime.profile_kwargs["use_cloud"] is False, "cloud browser fallback is disabled")
check(clean_runtime.profile_kwargs["disable_security"] is False, "browser security remains enabled")
check(clean_runtime.profile_kwargs["record_har_path"] is None, "HAR recording is disabled")
check(clean_runtime.profile_kwargs["record_video_dir"] is None, "video recording is disabled")
check(clean_runtime.profile_kwargs["traces_dir"] is None, "trace recording is disabled")
check(
    "--disable-popup-blocking" in clean_runtime.profile_object.ignore_default_args,
    "validated profile restores Chromium popup blocking",
)
check(clean_runtime.profile_kwargs["auto_download_pdfs"] is False, "automatic PDF downloads are disabled")
check(clean_runtime.profile_kwargs["captcha_solver"] is False, "captcha side-effect service is disabled")
excluded = set(clean_runtime.tools_kwargs["exclude_actions"])
check(
    {"click", "input", "upload_file", "send_keys", "save_as_pdf", "download_file", "screenshot"} <= excluded,
    "interactive and file-producing actions are excluded",
)
run(clean_backend.close())
check(
    clean_download_path is not None and not clean_download_path.exists(),
    "clean download quarantine is deleted during cleanup",
)
check(
    clean_user_data_path is not None and not clean_user_data_path.exists(),
    "ephemeral browser profile is deleted during cleanup",
)
check(clean_runtime.agent is not None and clean_runtime.agent.closed == 1, "agent closes before quarantine cleanup")
check(clean_guard.closed == 1, "request guard closes during cleanup")
check(
    clean_guard.browser_was_closed_on_close,
    "browser closes while request interception is still active",
)
check(clean_guard.health_checks == 3, "guard is checked after run and around cleanup")

# Any file written to the download quarantine fails before evidence is returned.
dirty_runtime = Runtime(write_download=True)
dirty_fetcher = Fetcher()
dirty_guards = GuardFactory()
dirty_backend = BrowserUseBackend(
    fetcher=dirty_fetcher,
    llm_factory=lambda: object(),
    bindings_loader=dirty_runtime.bindings,
    network_guard_factory=dirty_guards,
)
try:
    run(dirty_backend.research(REQUEST))
except BrowserBackendError as exc:
    check("forbidden download" in str(exc), "runtime-created downloads fail closed")
else:
    check(False, "runtime-created downloads fail closed")
dirty_download_path = dirty_runtime.download_path
dirty_user_data_path = dirty_runtime.user_data_path
check(dirty_fetcher.calls == 0, "forbidden download stops before citation re-fetch")
check(len(dirty_guards.instances) == 1, "dirty run is still guarded at the network boundary")
dirty_guard = dirty_guards.instances[0]
check(dirty_guard.installed == 1 and dirty_guard.health_checks == 1, "dirty run guard stays healthy")
run(dirty_backend.close())
check(dirty_guard.closed == 1, "dirty run guard closes during cleanup")
check(dirty_guard.browser_was_closed_on_close, "dirty browser closes before interception is disabled")

# If browser close fails, the request interceptor must remain armed. Disabling
# Fetch would reopen the exact cleanup race this contract is meant to close.
failed_close_runtime = Runtime(write_download=False, fail_close=True)
failed_close_guards = GuardFactory()
failed_close_backend = BrowserUseBackend(
    fetcher=Fetcher(),
    llm_factory=lambda: object(),
    bindings_loader=failed_close_runtime.bindings,
    network_guard_factory=failed_close_guards,
)
run(failed_close_backend.research(REQUEST))
failed_close_guard = failed_close_guards.instances[0]
try:
    run(failed_close_backend.close())
except RuntimeError as exc:
    check("simulated browser close failure" in str(exc), "browser close failure is surfaced")
else:
    check(False, "browser close failure is surfaced")
check(failed_close_guard.closed == 0, "guard remains armed when browser close is unproven")
check(
    not failed_close_guard.browser_was_closed_on_close,
    "cleanup never claims the failed browser close completed",
)

check(
    dirty_download_path is not None and not dirty_download_path.exists(),
    "dirty download quarantine is deleted during cleanup",
)
check(
    dirty_user_data_path is not None and not dirty_user_data_path.exists(),
    "dirty run profile is deleted during cleanup",
)

# A validated runtime may only hand the adapter Browser Use's system-temp paths.
unsafe_root = Path.cwd() / ".unsafe-browser-downloads"
unsafe_runtime = Runtime(write_download=False, unsafe_path=unsafe_root)
unsafe_guards = GuardFactory()
unsafe_backend = BrowserUseBackend(
    fetcher=Fetcher(),
    llm_factory=lambda: object(),
    bindings_loader=unsafe_runtime.bindings,
    network_guard_factory=unsafe_guards,
)
try:
    run(unsafe_backend.research(REQUEST))
except BrowserBackendUnavailable:
    check(True, "paths outside the Browser Use system-temp convention are rejected")
else:
    check(False, "paths outside the Browser Use system-temp convention are rejected")
finally:
    shutil.rmtree(unsafe_root, ignore_errors=True)
    if unsafe_runtime.user_data_path is not None:
        shutil.rmtree(unsafe_runtime.user_data_path, ignore_errors=True)
run(unsafe_backend.close())
check(not unsafe_guards.instances, "unsafe quarantine fails before a network guard is created")

check("click" in READ_ONLY_EXCLUDED_ACTIONS, "generic clicking is outside read-only v1")
check("save_as_pdf" in READ_ONLY_EXCLUDED_ACTIONS, "PDF file creation is outside read-only v1")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
