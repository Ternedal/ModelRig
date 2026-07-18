#!/usr/bin/env python3
from pathlib import Path


def exact(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one target, found {count}")
    return text.replace(old, new)


adapter_path = Path("worker/app/browser_use_adapter.py")
adapter = adapter_path.read_text(encoding="utf-8")
old = '''            if agent is not None:
                close = getattr(agent, "close", None)
                if close is None:
                    browser_session = getattr(agent, "browser_session", None)
                    close = getattr(browser_session, "close", None)
                if close is not None:
                    try:
                        await _maybe_await(close())
                    except Exception as exc:
                        if close_error is None:
                            close_error = exc
            # Keep interception active until the browser is closed. Fetch.disable
            # may release paused requests, so disabling it first creates a cleanup
            # window where a rejected request can leave Chromium.
            if guard is not None:
                try:
                    await guard.close()
                except BrowserUseNetworkGuardError:
                    if close_error is None:
                        close_error = BrowserBackendError(
                            "browser request guard cleanup failed"
                        )'''
new = '''            browser_closed = agent is None and guard is None
            if agent is not None:
                close = getattr(agent, "close", None)
                if close is None:
                    browser_session = getattr(agent, "browser_session", None)
                    close = getattr(browser_session, "close", None)
                if close is None:
                    if close_error is None:
                        close_error = BrowserBackendError(
                            "browser runtime has no close operation"
                        )
                else:
                    try:
                        await _maybe_await(close())
                        browser_closed = True
                    except Exception as exc:
                        if close_error is None:
                            close_error = exc
            # Keep interception active until the browser is proven closed.
            # Fetch.disable may release paused requests; if browser close fails,
            # leave interception armed and let the isolated BrowserHost process
            # boundary terminate the remaining browser tree.
            if guard is not None and browser_closed:
                try:
                    await guard.close()
                except BrowserUseNetworkGuardError:
                    if close_error is None:
                        close_error = BrowserBackendError(
                            "browser request guard cleanup failed"
                        )'''
adapter = exact(adapter, old, new, "fail-closed browser cleanup")
adapter_path.write_text(adapter, encoding="utf-8")

runtime_path = Path("tests/worker_browser_use_runtime_guard.py")
runtime = runtime_path.read_text(encoding="utf-8")
runtime = exact(
    runtime,
    '''class Agent:
    def __init__(self, download_path: Path, *, write_download: bool) -> None:
        self.download_path = download_path
        self.write_download = write_download
        self.browser_session = SimpleNamespace(closed=False)
        self.closed = 0''',
    '''class Agent:
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
        self.closed = 0''',
    "fake agent close failure input",
)
runtime = exact(
    runtime,
    '''    async def close(self):
        self.closed += 1
        self.browser_session.closed = True''',
    '''    async def close(self):
        self.closed += 1
        if self.fail_close:
            raise RuntimeError("simulated browser close failure")
        self.browser_session.closed = True''',
    "fake agent close failure",
)
runtime = exact(
    runtime,
    '''class Runtime:
    def __init__(self, *, write_download: bool, unsafe_path: Path | None = None) -> None:
        self.write_download = write_download
        self.unsafe_path = unsafe_path''',
    '''class Runtime:
    def __init__(
        self,
        *,
        write_download: bool,
        unsafe_path: Path | None = None,
        fail_close: bool = False,
    ) -> None:
        self.write_download = write_download
        self.unsafe_path = unsafe_path
        self.fail_close = fail_close''',
    "runtime close failure option",
)
runtime = exact(
    runtime,
    '''        self.agent = Agent(self.download_path, write_download=self.write_download)''',
    '''        self.agent = Agent(
            self.download_path,
            write_download=self.write_download,
            fail_close=self.fail_close,
        )''',
    "agent close failure wiring",
)
anchor = '''check(dirty_guard.browser_was_closed_on_close, "dirty browser closes before interception is disabled")
check(
    dirty_download_path is not None and not dirty_download_path.exists(),'''
insert = '''check(dirty_guard.browser_was_closed_on_close, "dirty browser closes before interception is disabled")

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
    dirty_download_path is not None and not dirty_download_path.exists(),'''
runtime = exact(runtime, anchor, insert, "failed browser close regression")
runtime_path.write_text(runtime, encoding="utf-8")

Path("scripts/_patch_browser_close_failure.py").unlink()
print("patched fail-closed browser close handling")
