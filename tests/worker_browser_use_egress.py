from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.browser_use_egress import BrowserEgressUnavailable, BrowserUseEgressGuard
from app.research_contract import ReadOnlyBrowserPolicy

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
    max_steps=3,
    max_pages=3,
    timeout_seconds=10,
    max_source_bytes=4096,
)


class FakeRegistry:
    def __init__(self) -> None:
        self._handlers = {"Target.attachedToTarget": lambda *_args: None}


class Registration:
    def __init__(self, registry: FakeRegistry, domain: str) -> None:
        self._registry = registry
        self.domain = domain

    def requestPaused(self, callback) -> None:
        self._registry._handlers["Fetch.requestPaused"] = callback


class FetchSend:
    def __init__(self, calls: list) -> None:
        self.calls = calls

    async def enable(self, params=None, session_id=None):
        self.calls.append(("enable", session_id, params))

    async def continueRequest(self, params, session_id=None):
        self.calls.append(("continue", session_id, params))

    async def failRequest(self, params, session_id=None):
        self.calls.append(("fail", session_id, params))


class TargetSend:
    def __init__(self, calls: list) -> None:
        self.calls = calls

    async def setAutoAttach(self, params=None, session_id=None):
        self.calls.append(("autoattach", session_id, params))


class RuntimeSend:
    def __init__(self, calls: list) -> None:
        self.calls = calls

    async def runIfWaitingForDebugger(self, params=None, session_id=None):
        self.calls.append(("resume", session_id, params))


class FakeRoot:
    def __init__(self, registry: FakeRegistry, calls: list) -> None:
        self.register = SimpleNamespace(
            Fetch=Registration(registry, "Fetch"),
            Target=Registration(registry, "Target"),
        )
        self.send = SimpleNamespace(
            Fetch=FetchSend(calls),
            Target=TargetSend(calls),
            Runtime=RuntimeSend(calls),
        )


class FakeManager:
    def __init__(self, calls: list) -> None:
        self.calls = calls
        self.sessions = {
            "session-page": SimpleNamespace(session_id="session-page", target_id="target-page")
        }
        self.targets = {
            "target-page": SimpleNamespace(target_id="target-page", target_type="page")
        }

    def get_all_sessions(self):
        return self.sessions

    def get_target(self, target_id):
        return self.targets.get(target_id)

    def get_session(self, session_id):
        return self.sessions.get(session_id)

    async def _handle_target_attached(self, event):
        target_info = event["targetInfo"]
        session_id = event["sessionId"]
        target_id = target_info["targetId"]
        self.calls.append(("manager-attach", session_id, event.get("waitingForDebugger")))
        self.targets[target_id] = SimpleNamespace(
            target_id=target_id,
            target_type=target_info["type"],
        )
        self.sessions[session_id] = SimpleNamespace(session_id=session_id, target_id=target_id)


class FakeBrowserSession:
    def __init__(self) -> None:
        self.calls = []
        registry = FakeRegistry()
        self._cdp_client_root = FakeRoot(registry, self.calls)
        self.session_manager = FakeManager(self.calls)
        self.registry = registry


session = FakeBrowserSession()
guard = BrowserUseEgressGuard(POLICY)
run(guard.attach(session))
check(
    session.calls[0][0] == "enable" and session.calls[0][1] == "session-page",
    "existing page session is intercepted before auto-attach changes",
)
check(
    session.calls[1] == (
        "autoattach",
        None,
        {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True},
    ),
    "future targets start paused",
)

paused = session.registry._handlers["Fetch.requestPaused"]
run(
    paused(
        {
            "requestId": "allow-1",
            "request": {
                "url": "https://EXAMPLE.com:443/report#fragment",
                "method": "GET",
                "headers": {
                    "Accept": "text/html",
                    "Cookie": "secret=1",
                    "Authorization": "Bearer secret",
                    "Proxy-Authorization": "Basic secret",
                },
            },
        },
        "session-page",
    )
)
continue_call = session.calls[-1]
check(continue_call[0] == "continue", "allowlisted GET request continues")
check(
    continue_call[2]["headers"] == [{"name": "Accept", "value": "text/html"}],
    "cookie and authorization headers are removed",
)
check(guard.records[-1].url == "https://example.com/report", "allowed request URL is canonicalized")

for request_id, url, method, reason in (
    ("host-1", "https://blocked.example.net/", "GET", "url_not_allowed"),
    ("ip-1", "http://127.0.0.1/private", "GET", "url_not_allowed"),
    ("post-1", "https://example.com/form", "POST", "method_not_read_only"),
):
    before = len(session.calls)
    run(
        paused(
            {
                "requestId": request_id,
                "request": {"url": url, "method": method, "headers": {}},
            },
            "session-page",
        )
    )
    check(len(session.calls) == before + 1 and session.calls[-1][0] == "fail", f"{request_id} fails at CDP")
    check(guard.records[-1].reason == reason, f"{request_id} records bounded denial reason")

run(
    paused(
        {
            "requestId": "headers-1",
            "request": {"url": "https://example.com/", "method": "GET", "headers": ["bad"]},
        },
        "session-page",
    )
)
check(session.calls[-1][0] == "fail", "invalid headers fail closed")
check(guard.records[-1].reason == "invalid_headers", "invalid headers are classified without raw details")

attached = session.registry._handlers["Target.attachedToTarget"]
before = len(session.calls)
run(
    attached(
        {
            "sessionId": "session-worker",
            "targetInfo": {
                "targetId": "target-worker",
                "type": "service_worker",
                "url": "https://example.com/sw.js",
                "title": "",
            },
            "waitingForDebugger": True,
        },
        None,
    )
)
new_calls = session.calls[before:]
check([call[0] for call in new_calls] == ["manager-attach", "enable", "resume"], "new target is guarded before resume")
check(new_calls[0][2] is False, "Browser Use sees the new target as not waiting and cannot resume early")
check(new_calls[1][1] == "session-worker", "worker session receives request interception")

try:
    run(guard.attach(session))
except Exception:
    check(False, "guard attach is idempotent")
else:
    check(True, "guard attach is idempotent")

owned = FakeBrowserSession()
owned.registry._handlers["Fetch.requestPaused"] = lambda *_args: None
try:
    run(BrowserUseEgressGuard(POLICY).attach(owned))
except BrowserEgressUnavailable:
    check(True, "guard refuses to clobber an existing request interceptor")
else:
    check(False, "guard refuses to clobber an existing request interceptor")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
