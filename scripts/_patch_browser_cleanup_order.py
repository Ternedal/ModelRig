#!/usr/bin/env python3
from pathlib import Path


def exact(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one target, found {count}")
    return text.replace(old, new)


adapter_path = Path("worker/app/browser_use_adapter.py")
adapter = adapter_path.read_text(encoding="utf-8")
adapter = exact(
    adapter,
    '''        "storage_state",
        "keep_alive",''',
    '''        "storage_state",
        "proxy",
        "keep_alive",''',
    "profile proxy field contract",
)
adapter = exact(
    adapter,
    '''        storage_state=None,
        keep_alive=False,''',
    '''        storage_state=None,
        proxy=None,
        keep_alive=False,''',
    "explicit proxy lock",
)
adapter = exact(
    adapter,
    '''            "storage_state": None,
            "keep_alive": False,''',
    '''            "storage_state": None,
            "proxy": None,
            "keep_alive": False,''',
    "proxy validation",
)
old_close = '''        guard_error: BrowserBackendError | None = None
        try:
            if guard is not None:
                try:
                    await guard.close()
                except BrowserUseNetworkGuardError:
                    guard_error = BrowserBackendError(
                        "browser request guard cleanup failed"
                    )
            if agent is not None:
                close = getattr(agent, "close", None)
                if close is None:
                    browser_session = getattr(agent, "browser_session", None)
                    close = getattr(browser_session, "close", None)
                if close is not None:
                    await _maybe_await(close())
        finally:
            self._cleanup_runtime_quarantines()
        if guard_error is not None:
            raise guard_error'''
new_close = '''        close_error: Exception | None = None
        try:
            if guard is not None:
                try:
                    await guard.assert_healthy()
                except BrowserUseNetworkGuardError:
                    close_error = BrowserBackendError(
                        "browser request guard cleanup failed"
                    )
            if agent is not None:
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
                        )
        finally:
            self._cleanup_runtime_quarantines()
        if close_error is not None:
            raise close_error'''
adapter = exact(adapter, old_close, new_close, "browser-before-guard cleanup order")
adapter_path.write_text(adapter, encoding="utf-8")

runtime_path = Path("tests/worker_browser_use_runtime_guard.py")
runtime = runtime_path.read_text(encoding="utf-8")
runtime = exact(
    runtime,
    '''        self.browser_session = object()
        self.closed = 0''',
    '''        self.browser_session = SimpleNamespace(closed=False)
        self.closed = 0''',
    "fake browser session state",
)
runtime = exact(
    runtime,
    '''    async def close(self):
        self.closed += 1''',
    '''    async def close(self):
        self.closed += 1
        self.browser_session.closed = True''',
    "fake browser close state",
)
runtime = exact(
    runtime,
    '''        self.health_checks = 0
        self.closed = 0''',
    '''        self.health_checks = 0
        self.closed = 0
        self.browser_was_closed_on_close = False''',
    "guard close observation field",
)
runtime = exact(
    runtime,
    '''    async def close(self) -> None:
        self.closed += 1''',
    '''    async def close(self) -> None:
        self.closed += 1
        self.browser_was_closed_on_close = bool(
            getattr(self.browser_session, "closed", False)
        )''',
    "guard close observation",
)
runtime = exact(
    runtime,
    '''check(clean_runtime.profile_kwargs["user_data_dir"] is None, "Browser Use owns profile temp path creation")
check(clean_runtime.profile_kwargs["accept_downloads"] is False, "browser context refuses downloads")''',
    '''check(clean_runtime.profile_kwargs["user_data_dir"] is None, "Browser Use owns profile temp path creation")
check(clean_runtime.profile_kwargs["proxy"] is None, "Browser Use proxy handling is explicitly disabled")
check(clean_runtime.profile_kwargs["accept_downloads"] is False, "browser context refuses downloads")''',
    "proxy assertion",
)
runtime = exact(
    runtime,
    '''check(clean_runtime.agent is not None and clean_runtime.agent.closed == 1, "agent closes before quarantine cleanup")
check(clean_guard.closed == 1, "request guard closes before browser cleanup")''',
    '''check(clean_runtime.agent is not None and clean_runtime.agent.closed == 1, "agent closes before quarantine cleanup")
check(clean_guard.closed == 1, "request guard closes during cleanup")
check(
    clean_guard.browser_was_closed_on_close,
    "browser closes while request interception is still active",
)
check(clean_guard.health_checks == 3, "guard is checked after run and around cleanup")''',
    "cleanup order assertions",
)
runtime = exact(
    runtime,
    '''check(dirty_guard.closed == 1, "dirty run guard closes during cleanup")''',
    '''check(dirty_guard.closed == 1, "dirty run guard closes during cleanup")
check(dirty_guard.browser_was_closed_on_close, "dirty browser closes before interception is disabled")''',
    "dirty cleanup order assertion",
)
runtime_path.write_text(runtime, encoding="utf-8")

contract_path = Path("scripts/browser_use_runtime_contract.py")
contract = contract_path.read_text(encoding="utf-8")
contract = exact(
    contract,
    '''    check(profile.storage_state is None, "profile imports no cookie or storage state")
    check(profile.keep_alive is False, "profile is single-use")''',
    '''    check(profile.storage_state is None, "profile imports no cookie or storage state")
    check(profile.proxy is None, "profile configures no proxy or proxy credentials")
    check(profile.keep_alive is False, "profile is single-use")''',
    "runtime proxy assertion",
)
contract_path.write_text(contract, encoding="utf-8")

Path("scripts/_patch_browser_cleanup_order.py").unlink()
print("patched browser cleanup order and explicit proxy lock")
