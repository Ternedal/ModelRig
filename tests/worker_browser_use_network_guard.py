from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.browser_use_network_guard import (
    BrowserUseNetworkGuard,
    BrowserUseNetworkGuardError,
    browser_request_allowed,
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


def run(coro):
    return asyncio.run(coro)


# Pure URL policy: exact and wildcard rules work; local/IP/credential schemes fail closed.
check(browser_request_allowed("https://example.com/a", ("example.com",)), "exact domain is allowed")
check(
    browser_request_allowed("https://docs.example.com/a", ("*.example.com",)),
    "explicit wildcard subdomain is allowed",
)
check(
    not browser_request_allowed("https://example.com/a", ("*.example.com",)),
    "wildcard does not silently include the apex",
)
check(
    not browser_request_allowed("https://evil-example.com/a", ("*.example.com",)),
    "suffix lookalike is rejected",
)
check(
    not browser_request_allowed("https://user:pass@example.com/a", ("example.com",)),
    "URL credentials are rejected",
)
check(
    not browser_request_allowed("http://127.0.0.1/a", ("example.com",)),
    "IPv4 literals are rejected",
)
check(
    not browser_request_allowed("http://[::1]/a", ("example.com",)),
    "IPv6 literals are rejected",
)
check(
    not browser_request_allowed("http://service.internal/a", ("service.internal",)),
    "internal host suffix is rejected",
)
check(
    not browser_request_allowed("ftp://example.com/a", ("example.com",)),
    "non-web schemes are rejected",
)
check(browser_request_allowed("about:blank", ("example.com",)), "about:blank remains available")
check(browser_request_allowed("data:text/plain,ok", ("example.com",)), "data documents remain local")
check(
    not browser_request_allowed("http://localhost/a", ("localhost",)),
    "localhost is unavailable to production policy",
)
check(
    browser_request_allowed(
        "http://localhost/a",
        ("localhost",),
        allow_localhost=True,
    ),
    "localhost is available only to the explicit test fixture",
)


class FakeRegisterFetch:
    def __init__(self) -> None:
        self.callback = None

    def requestPaused(self, callback) -> None:  # noqa: N802
        self.callback = callback


class FakeRegister:
    def __init__(self) -> None:
        self.Fetch = FakeRegisterFetch()


class FakeSendFetch:
    def __init__(
        self,
        *,
        fail_fail_request: bool = False,
        fail_fulfill_request: bool = False,
    ) -> None:
        self.fail_fail_request = fail_fail_request
        self.fail_fulfill_request = fail_fulfill_request
        self.enabled: list[tuple[dict, str | None]] = []
        self.continued: list[tuple[dict, str | None]] = []
        self.failed: list[tuple[dict, str | None]] = []
        self.fulfilled: list[tuple[dict, str | None]] = []
        self.disabled: list[str | None] = []

    async def enable(self, *, params, session_id=None) -> None:
        self.enabled.append((params, session_id))

    async def continueRequest(self, *, params, session_id=None) -> None:  # noqa: N802
        self.continued.append((params, session_id))

    async def failRequest(self, *, params, session_id=None) -> None:  # noqa: N802
        if self.fail_fail_request:
            raise RuntimeError("simulated CDP failure")
        self.failed.append((params, session_id))

    async def fulfillRequest(self, *, params, session_id=None) -> None:  # noqa: N802
        if self.fail_fulfill_request:
            raise RuntimeError("simulated fulfillment failure")
        self.fulfilled.append((params, session_id))

    async def disable(self, *, session_id=None) -> None:
        self.disabled.append(session_id)


class FakeSend:
    def __init__(
        self,
        *,
        fail_fail_request: bool = False,
        fail_fulfill_request: bool = False,
    ) -> None:
        self.Fetch = FakeSendFetch(
            fail_fail_request=fail_fail_request,
            fail_fulfill_request=fail_fulfill_request,
        )


class FakeClient:
    def __init__(
        self,
        *,
        fail_fail_request: bool = False,
        fail_fulfill_request: bool = False,
    ) -> None:
        self.register = FakeRegister()
        self.send = FakeSend(
            fail_fail_request=fail_fail_request,
            fail_fulfill_request=fail_fulfill_request,
        )


class FakeSession:
    def __init__(
        self,
        *,
        fail_fail_request: bool = False,
        fail_fulfill_request: bool = False,
        target: bool = True,
    ) -> None:
        self.started = 0
        self.agent_focus_target_id = "target-1" if target else None
        self.client = FakeClient(
            fail_fail_request=fail_fail_request,
            fail_fulfill_request=fail_fulfill_request,
        )
        self.cdp_session = SimpleNamespace(
            cdp_client=self.client,
            session_id="session-1",
        )

    async def start(self) -> None:
        self.started += 1

    async def must_get_current_page(self):
        return SimpleNamespace(target_id=self.agent_focus_target_id)

    async def get_or_create_cdp_session(self, target_id, focus=False):
        assert target_id == "target-1"
        assert focus is False
        return self.cdp_session


class FakePendingFulfillment:
    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self.committed: list[int] = []
        self.aborted: list[tuple[str, int]] = []

    def cdp_params(self) -> dict:
        return {
            "requestId": self.request_id,
            "responseCode": 200,
            "responsePhrase": "OK",
            "responseHeaders": [{"name": "content-length", "value": "2"}],
            "body": "b2s=",
        }

    def commit(self, *, now: int) -> None:
        self.committed.append(now)

    def abort(self, *, error_code: str, now: int) -> None:
        self.aborted.append((error_code, now))


class FakeFulfillmentController:
    def __init__(self, *, fail_prepare: bool = False) -> None:
        self.fail_prepare = fail_prepare
        self.calls: list[tuple[dict, int]] = []
        self.pending: list[FakePendingFulfillment] = []

    def prepare(self, event, *, now: int, ttl_seconds: int = 30):
        self.calls.append((event, now))
        if self.fail_prepare:
            raise RuntimeError("simulated prepare failure")
        pending = FakePendingFulfillment(event["requestId"])
        self.pending.append(pending)
        return pending


async def exercise_guard() -> tuple[BrowserUseNetworkGuard, FakeSession]:
    session = FakeSession()
    guard = BrowserUseNetworkGuard(session, ("example.com",))
    await guard.install()
    callback = session.client.register.Fetch.callback
    assert callback is not None
    callback(
        {
            "requestId": "allowed-1",
            "request": {"url": "https://example.com/report"},
        },
        "session-1",
    )
    callback(
        {
            "requestId": "blocked-1",
            "request": {"url": "https://other.example/report"},
        },
        "session-1",
    )
    callback(
        {
            "requestId": "blocked-2",
            "request": {"url": "http://127.0.0.1/secret"},
        },
        "session-1",
    )
    await guard.assert_healthy()
    return guard, session


guard, session = run(exercise_guard())
fetch = session.client.send.Fetch
check(session.started == 1, "guard starts BrowserSession exactly once")
check(len(fetch.enabled) == 1, "Fetch interception is enabled once")
check(
    fetch.enabled[0][0] == {
        "patterns": [{"urlPattern": "*", "requestStage": "Request"}]
    },
    "every request is paused at request stage",
)
check(
    [entry[0]["requestId"] for entry in fetch.continued] == ["allowed-1"],
    "default mode continues only allowlisted request",
)
check(
    [entry[0]["requestId"] for entry in fetch.failed] == ["blocked-1", "blocked-2"],
    "disallowed domain and IP requests fail in Chromium",
)
check(
    all(entry[0]["errorReason"] == "BlockedByClient" for entry in fetch.failed),
    "blocked requests use explicit BlockedByClient reason",
)
check(
    guard.blocked_urls == [
        "https://other.example/report",
        "http://127.0.0.1/secret",
    ],
    "guard records bounded policy-block evidence",
)
run(guard.close())
check(fetch.disabled == ["session-1"], "guard disables Fetch during cleanup")


async def exercise_fulfillment() -> tuple[BrowserUseNetworkGuard, FakeSession, FakeFulfillmentController]:
    session = FakeSession()
    controller = FakeFulfillmentController()
    guard = BrowserUseNetworkGuard(
        session,
        ("example.com",),
        fulfillment_controller=controller,
        now_factory=lambda: 123,
    )
    await guard.install()
    callback = session.client.register.Fetch.callback
    assert callback is not None
    event = {
        "requestId": "fulfilled-1",
        "networkId": "network-1",
        "request": {
            "url": "https://example.com/report",
            "method": "GET",
            "headers": {},
            "hasPostData": False,
        },
    }
    callback(event, "session-1")
    callback(
        {
            "requestId": "internal-1",
            "request": {"url": "about:blank"},
        },
        "session-1",
    )
    await guard.assert_healthy()
    return guard, session, controller


guard, session, controller = run(exercise_fulfillment())
fetch = session.client.send.Fetch
check(len(controller.calls) == 1, "HTTP request is delegated to injected controller")
check(controller.calls[0][1] == 123, "controller receives validated timestamp")
check(
    [entry[0]["requestId"] for entry in fetch.fulfilled] == ["fulfilled-1"],
    "controller response is delivered through Fetch.fulfillRequest",
)
check(
    [entry[0]["requestId"] for entry in fetch.continued] == ["internal-1"],
    "internal browser schemes remain local and are continued",
)
check(controller.pending[0].committed == [123], "peer fulfillment commits only after CDP success")
check(controller.pending[0].aborted == [], "successful fulfillment is not aborted")
run(guard.close())


async def exercise_fulfillment_failure() -> tuple[bool, FakeSession, FakeFulfillmentController]:
    session = FakeSession(fail_fulfill_request=True)
    controller = FakeFulfillmentController()
    guard = BrowserUseNetworkGuard(
        session,
        ("example.com",),
        fulfillment_controller=controller,
        now_factory=lambda: 456,
    )
    await guard.install()
    callback = session.client.register.Fetch.callback
    callback(
        {
            "requestId": "fulfill-failure",
            "networkId": "network-failure",
            "request": {
                "url": "https://example.com/report",
                "method": "GET",
                "headers": {},
                "hasPostData": False,
            },
        },
        "session-1",
    )
    try:
        await guard.assert_healthy()
    except BrowserUseNetworkGuardError:
        return True, session, controller
    return False, session, controller


unhealthy, session, controller = run(exercise_fulfillment_failure())
check(unhealthy, "CDP fulfillment failure makes guard unhealthy")
check(
    controller.pending[0].aborted == [("cdp_fulfill_failed", 456)],
    "failed CDP fulfillment aborts pending peer receipt",
)
check(
    [entry[0]["requestId"] for entry in session.client.send.Fetch.failed]
    == ["fulfill-failure"],
    "failed fulfillment explicitly fails paused request",
)


async def exercise_prepare_failure() -> tuple[bool, FakeSession]:
    session = FakeSession()
    guard = BrowserUseNetworkGuard(
        session,
        ("example.com",),
        fulfillment_controller=FakeFulfillmentController(fail_prepare=True),
        now_factory=lambda: 789,
    )
    await guard.install()
    callback = session.client.register.Fetch.callback
    callback(
        {
            "requestId": "prepare-failure",
            "networkId": "network-prepare",
            "request": {
                "url": "https://example.com/report",
                "method": "GET",
                "headers": {},
                "hasPostData": False,
            },
        },
        "session-1",
    )
    try:
        await guard.assert_healthy()
    except BrowserUseNetworkGuardError:
        return True, session
    return False, session


unhealthy, session = run(exercise_prepare_failure())
check(unhealthy, "controller preparation failure makes guard unhealthy")
check(
    [entry[0]["requestId"] for entry in session.client.send.Fetch.failed]
    == ["prepare-failure"],
    "prepare failure sends no permissive fallback",
)


async def exercise_guard_failure() -> bool:
    session = FakeSession(fail_fail_request=True)
    guard = BrowserUseNetworkGuard(session, ("example.com",))
    await guard.install()
    callback = session.client.register.Fetch.callback
    callback(
        {
            "requestId": "blocked-failure",
            "request": {"url": "https://evil.example/"},
        },
        "session-1",
    )
    try:
        await guard.assert_healthy()
    except BrowserUseNetworkGuardError:
        return True
    return False


check(run(exercise_guard_failure()), "CDP response failure makes guard unhealthy")


async def exercise_missing_target() -> bool:
    session = FakeSession(target=False)
    guard = BrowserUseNetworkGuard(session, ("example.com",))
    try:
        await guard.install()
    except BrowserUseNetworkGuardError:
        return True
    return False


check(run(exercise_missing_target()), "guard fails closed when browser target is absent")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
