"""Fail-closed CDP request guard for the optional Browser Use runtime.

Browser Use 0.13.4 checks NavigateToUrlEvent in a separate event handler from
its core Page.navigate handler. Those handlers run concurrently, so a rejected
navigation can still reach the network. This module installs the enforcement at
Chrome's Fetch request stage instead. It intentionally imports no Browser Use or
cdp-use modules so the base worker remains dependency-free.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from .research_contract import ReadOnlyBrowserPolicy, ResearchContractError

_ALLOWED_METHODS = frozenset({"GET", "HEAD"})
_SENSITIVE_REQUEST_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie"})
_INTERCEPTED_TARGET_TYPES = frozenset(
    {"page", "tab", "iframe", "worker", "shared_worker", "service_worker"}
)
_MAX_RECORDED_REQUESTS = 200


class BrowserEgressUnavailable(RuntimeError):
    """The pinned browser runtime cannot expose the required CDP safety seam."""


@dataclass(frozen=True)
class BrowserEgressRecord:
    url: str
    method: str
    allowed: bool
    reason: str


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class BrowserUseEgressGuard:
    """Intercept every browser request before it leaves Chrome.

    The guard is deliberately exact-runtime code. It validates the private seams
    used by Browser Use 0.13.4 and fails closed if they drift. New targets start
    paused, receive Fetch interception, and are resumed only after the guard is
    active. URL allowlisting is still separate from public-DNS pinning; the
    latter remains a required activation gate for public browsing.
    """

    def __init__(self, policy: ReadOnlyBrowserPolicy) -> None:
        if not isinstance(policy, ReadOnlyBrowserPolicy):
            raise TypeError("policy must be ReadOnlyBrowserPolicy")
        self._policy = policy
        self._root: Any = None
        self._manager: Any = None
        self._event_registry: Any = None
        self._enabled_session_ids: set[str] = set()
        self._records: list[BrowserEgressRecord] = []
        self._installed = False

    @property
    def records(self) -> tuple[BrowserEgressRecord, ...]:
        return tuple(self._records)

    @property
    def blocked_urls(self) -> tuple[str, ...]:
        return tuple(record.url for record in self._records if not record.allowed)

    def _record(self, record: BrowserEgressRecord) -> None:
        if len(self._records) < _MAX_RECORDED_REQUESTS:
            self._records.append(record)

    @staticmethod
    def _runtime_parts(browser_session: Any) -> tuple[Any, Any, Any, dict[str, Any]]:
        root = getattr(browser_session, "_cdp_client_root", None)
        manager = getattr(browser_session, "session_manager", None)
        register = getattr(root, "register", None)
        target_registration = getattr(register, "Target", None)
        fetch_registration = getattr(register, "Fetch", None)
        event_registry = getattr(target_registration, "_registry", None)
        fetch_registry = getattr(fetch_registration, "_registry", None)
        handlers = getattr(event_registry, "_handlers", None)
        if (
            root is None
            or manager is None
            or target_registration is None
            or fetch_registration is None
            or event_registry is None
            or fetch_registry is not event_registry
            or not isinstance(handlers, dict)
        ):
            raise BrowserEgressUnavailable("browser CDP event registry is unavailable")
        if not callable(getattr(manager, "_handle_target_attached", None)):
            raise BrowserEgressUnavailable("browser target attachment seam is unavailable")
        if not callable(getattr(manager, "get_all_sessions", None)):
            raise BrowserEgressUnavailable("browser session inventory is unavailable")
        if not callable(getattr(manager, "get_target", None)):
            raise BrowserEgressUnavailable("browser target inventory is unavailable")
        if not callable(getattr(manager, "get_session", None)):
            raise BrowserEgressUnavailable("browser session lookup is unavailable")
        return root, manager, event_registry, handlers

    async def attach(self, browser_session: Any) -> None:
        if self._installed:
            return
        root, manager, event_registry, handlers = self._runtime_parts(browser_session)
        if "Fetch.requestPaused" in handlers:
            raise BrowserEgressUnavailable("browser request interception is already owned")
        if "Target.attachedToTarget" not in handlers:
            raise BrowserEgressUnavailable("browser target attachment handler is unavailable")

        self._root = root
        self._manager = manager
        self._event_registry = event_registry

        root.register.Fetch.requestPaused(self._on_request_paused)

        for cdp_session in tuple(manager.get_all_sessions().values()):
            target = manager.get_target(getattr(cdp_session, "target_id", ""))
            target_type = getattr(target, "target_type", None)
            if target_type in _INTERCEPTED_TARGET_TYPES:
                await self._enable_session(cdp_session)

        async def guarded_target_attached(event: Any, _parent_session_id: str | None = None) -> None:
            await self._attach_new_target(event)

        handlers["Target.attachedToTarget"] = guarded_target_attached
        await root.send.Target.setAutoAttach(
            params={"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True}
        )
        self._installed = True

    async def _enable_session(self, cdp_session: Any) -> None:
        session_id = getattr(cdp_session, "session_id", None)
        if not isinstance(session_id, str) or not session_id:
            raise BrowserEgressUnavailable("browser CDP session id is unavailable")
        if session_id in self._enabled_session_ids:
            return
        await self._root.send.Fetch.enable(
            params={
                "patterns": [{"urlPattern": "*", "requestStage": "Request"}],
                "handleAuthRequests": False,
            },
            session_id=session_id,
        )
        self._enabled_session_ids.add(session_id)

    async def _attach_new_target(self, event: Any) -> None:
        if not isinstance(event, dict):
            raise BrowserEgressUnavailable("browser target event is invalid")
        target_info = event.get("targetInfo")
        session_id = event.get("sessionId")
        if not isinstance(target_info, dict) or not isinstance(session_id, str) or not session_id:
            raise BrowserEgressUnavailable("browser target event is incomplete")

        waiting = event.get("waitingForDebugger") is True
        safe_event = dict(event)
        safe_event["targetInfo"] = dict(target_info)
        safe_event["waitingForDebugger"] = False

        await _maybe_await(self._manager._handle_target_attached(safe_event))
        cdp_session = self._manager.get_session(session_id)
        target_type = target_info.get("type")
        if target_type in _INTERCEPTED_TARGET_TYPES:
            if cdp_session is None:
                raise BrowserEgressUnavailable("new browser target has no CDP session")
            await self._enable_session(cdp_session)

        if waiting:
            await self._root.send.Runtime.runIfWaitingForDebugger(session_id=session_id)

    @staticmethod
    def _sanitized_headers(raw_headers: Any) -> list[dict[str, str]]:
        if not isinstance(raw_headers, dict):
            raise BrowserEgressUnavailable("browser request headers are invalid")
        sanitized: list[dict[str, str]] = []
        for raw_name, raw_value in raw_headers.items():
            if not isinstance(raw_name, str) or not isinstance(raw_value, str):
                raise BrowserEgressUnavailable("browser request header is invalid")
            if raw_name.lower() in _SENSITIVE_REQUEST_HEADERS:
                continue
            sanitized.append({"name": raw_name, "value": raw_value})
        return sanitized

    def _decision(self, raw_url: Any, raw_method: Any) -> tuple[bool, str, str, str]:
        method = raw_method.upper() if isinstance(raw_method, str) else ""
        display_url = raw_url if isinstance(raw_url, str) else "<invalid-url>"
        if method not in _ALLOWED_METHODS:
            return False, display_url, method or "<invalid-method>", "method_not_read_only"
        try:
            canonical = self._policy.require_allowed_url(display_url)
        except ResearchContractError:
            return False, display_url, method, "url_not_allowed"
        return True, canonical, method, "allowed"

    async def _on_request_paused(self, event: Any, session_id: str | None = None) -> None:
        if not isinstance(event, dict):
            raise BrowserEgressUnavailable("browser request event is invalid")
        request_id = event.get("requestId")
        request = event.get("request")
        if not isinstance(request_id, str) or not request_id:
            raise BrowserEgressUnavailable("browser request id is unavailable")
        if not isinstance(session_id, str) or not session_id:
            raise BrowserEgressUnavailable("browser request session is unavailable")
        if not isinstance(request, dict):
            await self._fail_request(request_id, session_id)
            raise BrowserEgressUnavailable("browser request payload is invalid")

        allowed, url, method, reason = self._decision(request.get("url"), request.get("method"))
        if not allowed:
            await self._fail_request(request_id, session_id)
            self._record(BrowserEgressRecord(url=url, method=method, allowed=False, reason=reason))
            return

        try:
            headers = self._sanitized_headers(request.get("headers", {}))
        except BrowserEgressUnavailable:
            await self._fail_request(request_id, session_id)
            self._record(
                BrowserEgressRecord(url=url, method=method, allowed=False, reason="invalid_headers")
            )
            return

        await self._root.send.Fetch.continueRequest(
            params={"requestId": request_id, "headers": headers},
            session_id=session_id,
        )
        self._record(BrowserEgressRecord(url=url, method=method, allowed=True, reason="allowed"))

    async def _fail_request(self, request_id: str, session_id: str) -> None:
        await self._root.send.Fetch.failRequest(
            params={"requestId": request_id, "errorReason": "BlockedByClient"},
            session_id=session_id,
        )
