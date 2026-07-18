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
    def __init__(self, download_path: Path, *, write_download: bool) -> None:
        self.download_path = download_path
        self.write_download = write_download
        self.closed = 0

    async def run(self, **kwargs):
        if self.write_download:
            (self.download_path / "forbidden.bin").write_bytes(b"forbidden")
        return History()

    async def close(self):
        self.closed += 1


class Runtime:
    def __init__(self, *, write_download: bool, unsafe_path: Path | None = None) -> None:
        self.write_download = write_download
        self.unsafe_path = unsafe_path
        self.download_path: Path | None = None
        self.user_data_path: Path | None = None
        self.agent: Agent | None = None
        self.profile_kwargs = None
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
        return SimpleNamespace(**profile_fields)

    def tools(self, **kwargs):
        self.tools_kwargs = kwargs
        return object()

    def create_agent(self, **kwargs):
        assert self.download_path is not None
        self.agent = Agent(self.download_path, write_download=self.write_download)
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
clean_backend = BrowserUseBackend(
    fetcher=clean_fetcher,
    llm_factory=lambda: object(),
    bindings_loader=clean_runtime.bindings,
)
clean_result = run(clean_backend.research(REQUEST))
clean_download_path = clean_runtime.download_path
clean_user_data_path = clean_runtime.user_data_path
check(clean_result.answer == "Verified [1].", "empty download quarantine permits research")
check(clean_fetcher.calls == 1, "clean run reaches deterministic citation re-fetch")
check(clean_runtime.profile_kwargs["downloads_path"] is None, "Browser Use owns download temp path creation")
check(clean_runtime.profile_kwargs["user_data_dir"] is None, "Browser Use owns profile temp path creation")
check(clean_runtime.profile_kwargs["accept_downloads"] is False, "browser context refuses downloads")
check(clean_runtime.profile_kwargs["permissions"] == [], "validated runtime grants no browser permissions")
check(clean_runtime.profile_kwargs["cross_origin_iframes"] is False, "cross-origin iframe traversal is disabled")
check(clean_runtime.profile_kwargs["use_cloud"] is False, "cloud browser fallback is disabled")
check(clean_runtime.profile_kwargs["disable_security"] is False, "browser security remains enabled")
check(clean_runtime.profile_kwargs["record_har_path"] is None, "HAR recording is disabled")
check(clean_runtime.profile_kwargs["record_video_dir"] is None, "video recording is disabled")
check(clean_runtime.profile_kwargs["traces_dir"] is None, "trace recording is disabled")
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

# Any file written to the download quarantine fails before evidence is returned.
dirty_runtime = Runtime(write_download=True)
dirty_fetcher = Fetcher()
dirty_backend = BrowserUseBackend(
    fetcher=dirty_fetcher,
    llm_factory=lambda: object(),
    bindings_loader=dirty_runtime.bindings,
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
run(dirty_backend.close())
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
unsafe_backend = BrowserUseBackend(
    fetcher=Fetcher(),
    llm_factory=lambda: object(),
    bindings_loader=unsafe_runtime.bindings,
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

check("click" in READ_ONLY_EXCLUDED_ACTIONS, "generic clicking is outside read-only v1")
check("save_as_pdf" in READ_ONLY_EXCLUDED_ACTIONS, "PDF file creation is outside read-only v1")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
