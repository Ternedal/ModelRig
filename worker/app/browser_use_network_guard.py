"""Browser-level request interception for the dormant Browser Use adapter.

Browser Use 0.13.4 validates NavigateToUrlEvent through an event watchdog, but
that watchdog runs alongside the browser navigation handler. A rejected URL can
therefore reach the network before the event error is observed. This module
moves the decision to Chromium's Fetch.requestPaused boundary: every HTTP(S)
request is paused and must be explicitly continued by ModelRig.

The guard is intentionally domain-only. Public-address pinning and live public
network validation remain activation blockers; this closes the earlier and
narrower leak where an explicitly disallowed URL could leave the browser at all.
"""
from __future__ import annotations

import asyncio
import ipaddress
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit


class BrowserUseNetworkGuardError(RuntimeError):
    """The browser request guard could not be installed or stayed unhealthy."""


_INTERNAL_SCHEMES = frozenset({"about", "blob", "chrome", "data"})
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")


def _canonical_host(host: str) -> str:
    try:
        value = unquote(host).rstrip(".").encode("idna").decode("ascii").lower()
    except (UnicodeError, ValueError):
        return ""
    return value


def _is_ip_literal(host: str) -> bool:
    value = host.strip("[]")
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def browser_request_allowed(
    url: str,
    allowed_domains: Iterable[str],
    *,
    allow_localhost: bool = False,
) -> bool:
    """Return whether Chromium may send one request.

    Only internal browser schemes and explicit HTTP(S) domain rules pass. URL
    credentials, IP literals, local/internal names and malformed hosts fail
    closed. ``allow_localhost`` exists solely for the controlled CI fixture and
    is never enabled by the production adapter.
    """

    if not isinstance(url, str) or not url:
        return False
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    scheme = parsed.scheme.lower()
    if scheme in _INTERNAL_SCHEMES:
        return True
    if scheme not in {"http", "https"}:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    if not parsed.hostname:
        return False

    host = _canonical_host(parsed.hostname)
    if not host or _is_ip_literal(host):
        return False
    if host == "localhost":
        return allow_localhost and any(
            str(rule).lower().rstrip(".") == "localhost"
            for rule in allowed_domains
        )
    if host.endswith(_LOCAL_SUFFIXES):
        return False

    for raw_rule in allowed_domains:
        rule = str(raw_rule).strip().lower().rstrip(".")
        if not rule or "://" in rule or "/" in rule or ":" in rule:
            continue
        if rule.startswith("*."):
            base = _canonical_host(rule[2:])
            if base and host.endswith(f".{base}") and host != base:
                return True
        elif host == _canonical_host(rule):
            return True
    return False


class BrowserUseNetworkGuard:
    """Pause every Chromium request and continue only allowlisted URLs."""

    def __init__(
        self,
        browser_session: Any,
        allowed_domains: Iterable[str],
        *,
        allow_localhost: bool = False,
    ) -> None:
        domains = tuple(str(value) for value in allowed_domains)
        if not domains:
            raise BrowserUseNetworkGuardError("browser request allowlist is empty")
        self.browser_session = browser_session
        self.allowed_domains = domains
        self.allow_localhost = allow_localhost
        self.blocked_urls: list[str] = []
        self._client: Any = None
        self._session_id: Any = None
        self._installed = False
        self._seen: set[tuple[str, str]] = set()
        self._tasks: set[asyncio.Task[Any]] = set()
        self._errors: list[str] = []

    def _track(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _on_request_paused(self, event: Any, session_id: Any = None) -> None:
        request_id = event.get("requestId") or event.get("request_id")
        request = event.get("request") or {}
        url = request.get("url") or ""
        if not request_id:
            self._errors.append("missing_request_id")
            return

        effective_session = session_id or self._session_id
        key = (str(effective_session or ""), str(request_id))
        if key in self._seen:
            return
        self._seen.add(key)
        allowed = browser_request_allowed(
            url,
            self.allowed_domains,
            allow_localhost=self.allow_localhost,
        )
        if not allowed:
            self.blocked_urls.append(url)

        async def respond() -> None:
            try:
                if allowed:
                    await self._client.send.Fetch.continueRequest(
                        params={"requestId": request_id},
                        session_id=effective_session,
                    )
                else:
                    await self._client.send.Fetch.failRequest(
                        params={
                            "requestId": request_id,
                            "errorReason": "BlockedByClient",
                        },
                        session_id=effective_session,
                    )
            except Exception as exc:  # fail closed: a paused request never gets a permissive fallback
                self._errors.append(type(exc).__name__)

        self._track(respond())

    async def install(self) -> None:
        if self._installed:
            return
        try:
            await self.browser_session.start()
            target_id = getattr(self.browser_session, "agent_focus_target_id", None)
            if not target_id:
                page = await self.browser_session.must_get_current_page()
                target_id = getattr(page, "target_id", None)
            if not target_id:
                raise BrowserUseNetworkGuardError("browser has no focused target")
            cdp_session = await self.browser_session.get_or_create_cdp_session(
                target_id,
                focus=False,
            )
            self._client = cdp_session.cdp_client
            self._session_id = cdp_session.session_id
            self._client.register.Fetch.requestPaused(self._on_request_paused)
            await self._client.send.Fetch.enable(
                params={
                    "patterns": [
                        {
                            "urlPattern": "*",
                            "requestStage": "Request",
                        }
                    ]
                },
                session_id=self._session_id,
            )
            self._installed = True
        except BrowserUseNetworkGuardError:
            raise
        except Exception as exc:
            raise BrowserUseNetworkGuardError(
                "browser request guard could not be installed"
            ) from exc

    async def assert_healthy(self) -> None:
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        if self._errors:
            raise BrowserUseNetworkGuardError(
                "browser request guard failed while handling a request"
            )

    async def close(self) -> None:
        await self.assert_healthy()
        if not self._installed:
            return
        self._installed = False
        try:
            await self._client.send.Fetch.disable(session_id=self._session_id)
        except Exception:
            # The browser may already be gone. Disabling is hygiene; the browser
            # process ending is the actual security boundary.
            return
