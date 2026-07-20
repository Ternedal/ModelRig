#!/usr/bin/env python3
"""Exercise the claim-bound Browser Use runtime with real Chromium and no public I/O.

The optional Browser Use package and Chromium/CDP are real. The paused navigation is
fulfilled through the production claim/peer/evidence composition, but the final
numeric-IP socket is an injected in-memory fixture. This proves the installed
``Fetch.requestPaused -> pinned prepare -> Fetch.fulfillRequest -> commit ->
verified citation`` path without contacting the public destination, creating an
LLM client, exposing a ToolGate route or activating BrowserHost research.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import shutil
import socket
import threading
import uuid
from pathlib import Path
from typing import Any

from app.browser_peer_fulfillment import (
    BrowserPeerFulfillmentController,
    PinnedBrowserPeerTransport,
)
from app.browser_peer_runtime import build_claim_bound_browser_use_runtime
from app.browser_use_adapter import (
    _BROWSER_USE_DOWNLOAD_PREFIX,
    _BROWSER_USE_USER_DATA_PREFIX,
    build_read_only_browser_profile,
    load_browser_use_bindings,
)
from app.research_claim_evidence import (
    VerifiableDataSharingLedger,
    VerifiableResearchSharingBoundary,
)
from app.research_contract import ReadOnlyBrowserPolicy
from app.research_data_sharing import ResearchSharingIntent
from app.research_egress import EgressPlan
from app.research_peer_authorization import ResearchPeerAuthorizationBridge
from app.research_peer_transfer import ResearchPeerTransferLedger

REPORT = Path(
    os.getenv(
        "MODELRIG_BROWSER_PEER_FIXTURE_REPORT",
        "browser-peer-runtime-live-fixture.json",
    )
)
PUBLIC_V4 = "93.184.216.34"
PUBLIC_V6 = "2606:2800:220:1:248:1893:25c8:1946"
FIXTURE_URL = "https://example.com/modelrig-claim-bound-fixture"
TITLE = "ModelRig claim-bound browser fixture"
BODY = (
    b"<!doctype html><html><head><title>"
    + TITLE.encode("utf-8")
    + b"</title><link rel='icon' href='data:,'></head>"
    + b"<body><main id='fixture'>committed-pinned-evidence</main></body></html>"
)
RAW_PURPOSE = "Validate one bounded public Browser Use response"
RAW_SUMMARY = "Controlled installed-runtime validation without public I/O."
RAW_PAYLOAD = b"claim-bound installed runtime validation"


class UUIDs:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value = 0

    def __call__(self) -> uuid.UUID:
        with self._lock:
            self._value += 1
            return uuid.UUID(int=self._value)


class ValidationClock:
    def __init__(self, start: int) -> None:
        self._lock = threading.Lock()
        self._value = start

    def __call__(self) -> int:
        with self._lock:
            value = self._value
            self._value += 1
            return value


class FixtureSocket:
    def __init__(self, wire: bytes) -> None:
        self.wire = wire
        self.timeout: float | None = None
        self.sockaddr: tuple[Any, ...] | None = None
        self.sent = bytearray()
        self.closed = False

    def settimeout(self, value: float) -> None:
        self.timeout = value

    def connect(self, sockaddr: tuple[Any, ...]) -> None:
        self.sockaddr = sockaddr

    def getpeername(self) -> tuple[str, int]:
        if self.sockaddr is None:
            raise RuntimeError("fixture socket was not connected")
        return PUBLIC_V4, int(self.sockaddr[1])

    def send(self, data: bytes) -> int:
        self.sent.extend(data)
        return len(data)

    def makefile(self, mode: str, buffering: int | None = None):
        del buffering
        if mode != "rb":
            raise RuntimeError("fixture socket only supports binary reads")
        return io.BytesIO(self.wire)

    def close(self) -> None:
        self.closed = True


class FixtureSocketFactory:
    def __init__(self, fixture: FixtureSocket) -> None:
        self.fixture = fixture
        self.calls: list[tuple[int, int]] = []

    def __call__(self, family: int, kind: int) -> FixtureSocket:
        self.calls.append((family, kind))
        if len(self.calls) != 1:
            raise AssertionError("unexpected second public socket attempt")
        if family != socket.AF_INET or kind != socket.SOCK_STREAM:
            raise AssertionError("unexpected socket family or type")
        return self.fixture


class FixtureTLSContext:
    def __init__(self) -> None:
        self.server_names: list[str] = []

    def wrap_socket(self, sock: FixtureSocket, *, server_hostname: str) -> FixtureSocket:
        self.server_names.append(server_hostname)
        return sock


def response_wire() -> bytes:
    headers = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        f"Content-Length: {len(BODY)}\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    return headers + BODY


def browser_executable() -> str:
    configured = os.getenv("MODELRIG_BROWSER_EXECUTABLE", "").strip()
    candidates = [configured] if configured else []
    candidates.extend(
        candidate
        for candidate in (
            shutil.which("google-chrome-stable"),
            shutil.which("google-chrome"),
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
        )
        if candidate
    )
    for candidate in candidates:
        path = Path(candidate).expanduser().resolve()
        if path.is_file():
            return str(path)
    raise RuntimeError("no controlled Chrome/Chromium executable is available")


def remove_quarantine(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        return


async def dispatch(
    session: Any,
    event: Any,
    *,
    result_required: bool = False,
) -> Any:
    pending = session.event_bus.dispatch(event)
    await pending
    return await pending.event_result(
        raise_if_any=True,
        raise_if_none=result_required,
    )


def check(condition: bool, name: str, results: dict[str, bool]) -> None:
    results[name] = bool(condition)
    print(f"  {'PASS' if condition else 'FAIL'}: {name}")
    if not condition:
        raise AssertionError(name)


async def run_fixture() -> dict[str, Any]:
    from browser_use import BrowserSession
    from browser_use.browser.events import BrowserStateRequestEvent, NavigateToUrlEvent

    common = VerifiableDataSharingLedger(uuid_factory=UUIDs())
    boundary = VerifiableResearchSharingBoundary(common, mode="enforce")
    intent = ResearchSharingIntent(
        plan=EgressPlan(
            destination="browser-use",
            purpose=RAW_PURPOSE,
            payload_sha256=hashlib.sha256(RAW_PAYLOAD).hexdigest(),
            sensitivity="public",
            allowed_domains=("example.com",),
            max_bytes=8192,
        ),
        summary=RAW_SUMMARY,
    )
    lease = boundary.prepare(intent, now=100, receipt_ttl_seconds=120)
    claim = boundary.claim(lease, intent, now=101)
    bridge = ResearchPeerAuthorizationBridge(boundary)
    peer = ResearchPeerTransferLedger(
        bridge,
        lambda host, port: (
            (PUBLIC_V6, PUBLIC_V4)
            if host == "example.com" and port == 443
            else ()
        ),
        uuid_factory=UUIDs(),
    )
    fixture_socket = FixtureSocket(response_wire())
    socket_factory = FixtureSocketFactory(fixture_socket)
    tls = FixtureTLSContext()
    transport = PinnedBrowserPeerTransport(
        socket_factory=socket_factory,
        ssl_context_factory=lambda: tls,
        uuid_factory=UUIDs(),
    )
    controller = BrowserPeerFulfillmentController.create(
        bridge,
        peer,
        claim,
        lease,
        intent,
        timeout_seconds=5,
        max_response_bytes=4096,
        transport=transport,
    )
    clock = ValidationClock(103)
    runtime = build_claim_bound_browser_use_runtime(
        controller,
        llm_factory=lambda: object(),
        bindings_loader=load_browser_use_bindings,
        max_evidence_bytes=4096,
        max_evidence_responses=4,
        now_factory=clock,
    )
    bindings = load_browser_use_bindings()
    profile = build_read_only_browser_profile(bindings, ["example.com"])
    profile.executable_path = browser_executable()
    download_path = Path(profile.downloads_path).resolve(strict=True)
    user_data_path = Path(profile.user_data_dir).resolve(strict=True)
    session = BrowserSession(browser_profile=profile)
    guard = runtime.backend._network_guard_factory(session, ("example.com",))
    policy = ReadOnlyBrowserPolicy(
        allowed_domains=("example.com",),
        max_steps=4,
        max_pages=4,
        timeout_seconds=10,
        max_source_bytes=4096,
    )
    results: dict[str, bool] = {}
    guard_installed = False
    claim_terminalized = False

    try:
        check(bindings.runtime_validated, "installed Browser Use bindings are validated", results)
        check(
            download_path.name.startswith(_BROWSER_USE_DOWNLOAD_PREFIX),
            "download quarantine has expected prefix",
            results,
        )
        check(
            user_data_path.name.startswith(_BROWSER_USE_USER_DATA_PREFIX),
            "profile quarantine has expected prefix",
            results,
        )
        check(profile.accept_downloads is False, "downloads are refused before launch", results)
        check(profile.permissions == [], "no browser permissions are granted", results)
        check(
            runtime.backend._fetcher is runtime.evidence,
            "Browser Use citation seam uses claim-bound evidence",
            results,
        )
        check(
            guard.fulfillment_controller is runtime.evidence,
            "Browser Use request seam uses the same claim-bound evidence",
            results,
        )

        await asyncio.wait_for(guard.install(), timeout=30)
        guard_installed = True
        check(session.is_cdp_connected, "Chromium starts and CDP connects", results)

        await dispatch(
            session,
            NavigateToUrlEvent(
                url=FIXTURE_URL,
                wait_until="load",
                timeout_ms=8_000,
                event_timeout=12.0,
            ),
        )
        await guard.assert_healthy()
        state = await dispatch(
            session,
            BrowserStateRequestEvent(
                include_dom=False,
                include_screenshot=False,
                include_recent_events=False,
                event_timeout=10.0,
            ),
            result_required=True,
        )
        page = await session.must_get_current_page()
        observed_title = await page.evaluate("() => document.title")
        observed_text = await page.evaluate(
            "() => document.querySelector('#fixture')?.textContent || ''"
        )
        check(state.url == FIXTURE_URL, "fulfilled public URL is active in Chromium", results)
        check(observed_title == TITLE, "Chromium renders the pinned response title", results)
        check(
            observed_text == "committed-pinned-evidence",
            "Chromium renders the pinned response body",
            results,
        )
        check(socket_factory.calls == [(socket.AF_INET, socket.SOCK_STREAM)], "one injected socket is used", results)
        check(
            fixture_socket.sockaddr == (PUBLIC_V4, 443),
            "pinned transport targets the selected numeric peer",
            results,
        )
        check(tls.server_names == ["example.com"], "TLS SNI preserves the canonical hostname", results)
        check(
            bytes(fixture_socket.sent).startswith(
                b"GET /modelrig-claim-bound-fixture HTTP/1.1\r\n"
            ),
            "transport sends the exact canonical request target",
            results,
        )
        check(fixture_socket.closed, "injected transport closes before CDP delivery", results)

        trace = runtime.evidence.fetch(FIXTURE_URL, policy)
        check(socket_factory.calls == [(socket.AF_INET, socket.SOCK_STREAM)], "citation verification opens no second socket", results)
        check(
            trace.receipt.adapter == "deterministic-web-fetch",
            "committed response receives trusted deterministic provenance",
            results,
        )
        check(
            trace.receipt.content_sha256 == hashlib.sha256(BODY).hexdigest(),
            "citation receipt hashes the exact fulfilled bytes",
            results,
        )
        check(trace.receipt.title == TITLE, "citation parser sees the fulfilled title", results)
        check(trace.receipt.bytes_read == len(BODY), "citation receipt records exact body size", results)
        check(
            trace.resolved_addresses[0][1] == (PUBLIC_V4, PUBLIC_V6),
            "citation trace retains the full validated DNS set",
            results,
        )
        check(controller.bytes_sent == len(fixture_socket.sent), "common meter records confirmed request bytes", results)
        check(
            peer.events()[-1]["outcome"] == "connected"
            and peer.events()[-1]["peer_address"] == PUBLIC_V4,
            "peer audit terminalizes the selected connected address",
            results,
        )
        check(next(download_path.rglob("*"), None) is None, "download quarantine stays empty", results)

        boundary.complete(
            lease,
            intent,
            outcome="completed",
            bytes_sent=controller.bytes_sent,
            now=clock(),
        )
        claim_terminalized = True
    finally:
        try:
            if guard_installed:
                await asyncio.wait_for(guard.close(), timeout=10)
        finally:
            try:
                if session.is_cdp_connected:
                    await asyncio.wait_for(session.kill(), timeout=15)
            finally:
                runtime.close()
                if not claim_terminalized:
                    try:
                        boundary.complete(
                            lease,
                            intent,
                            outcome="blocked",
                            bytes_sent=controller.bytes_sent,
                            error_code="installed_runtime_validation_failed",
                            now=clock(),
                        )
                    except Exception:
                        pass
                peer.close()
                common.close()
                remove_quarantine(download_path)
                remove_quarantine(user_data_path)

    check(not session.is_cdp_connected, "CDP is closed after kill", results)
    check(not download_path.exists(), "download quarantine is removed", results)
    check(not user_data_path.exists(), "profile quarantine is removed", results)
    evidence_audit = runtime.evidence.audit()
    check(evidence_audit == [], "runtime close deletes retained response bodies", results)
    return {
        "schema_version": "modelrig.browser-peer-runtime-live-fixture.v1",
        "browser_use_version": bindings.version,
        "browser_executable": str(profile.executable_path),
        "fixture_url_sha256": hashlib.sha256(FIXTURE_URL.encode("utf-8")).hexdigest(),
        "response_body_sha256": hashlib.sha256(BODY).hexdigest(),
        "selected_peer": PUBLIC_V4,
        "socket_calls": len(socket_factory.calls),
        "bytes_sent": controller.bytes_sent,
        "checks": results,
        "passed": all(results.values()),
        "public_network_contacted": False,
        "production_activation": False,
    }


def main() -> int:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = asyncio.run(run_fixture())
    except Exception as exc:
        report = {
            "schema_version": "modelrig.browser-peer-runtime-live-fixture.v1",
            "passed": False,
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "public_network_contacted": False,
            "production_activation": False,
        }
        REPORT.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise
    REPORT.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"\nreport: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
