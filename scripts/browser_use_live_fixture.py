#!/usr/bin/env python3
"""Launch pinned Browser Use Chromium against a controlled loopback fixture.

This is deliberately not an agent or research run: no LLM is created, no
ToolGate route is exposed and no public site is requested. It proves the real
BrowserSession can launch, read one allowlisted localhost page, reject a public
domain and reject the fixture's numeric loopback address, then cleanly stop.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from app.browser_use_adapter import (
    _BROWSER_USE_DOWNLOAD_PREFIX,
    _BROWSER_USE_USER_DATA_PREFIX,
    build_read_only_browser_profile,
    load_browser_use_bindings,
)

REPORT = Path(
    os.getenv(
        "MODELRIG_BROWSER_FIXTURE_REPORT",
        "browser-use-live-fixture.json",
    )
)
TITLE = "ModelRig controlled browser fixture"
BODY = (
    b"<!doctype html><html><head><title>"
    + TITLE.encode("utf-8")
    + b"</title><link rel='icon' href='data:,'></head>"
    + b"<body><main id='fixture'>loopback-only</main></body></html>"
)


class FixtureHandler(BaseHTTPRequestHandler):
    requests: list[str] = []

    def do_GET(self) -> None:  # noqa: N802
        type(self).requests.append(self.path)
        if self.path != "/fixture":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(BODY)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def check(condition: bool, name: str, results: dict[str, bool]) -> None:
    results[name] = bool(condition)
    print(f"  {'PASS' if condition else 'FAIL'}: {name}")
    if not condition:
        raise AssertionError(name)


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


async def expect_denied(session: Any, url: str) -> str:
    from browser_use.browser.events import NavigateToUrlEvent

    try:
        await dispatch(
            session,
            NavigateToUrlEvent(
                url=url,
                wait_until="commit",
                timeout_ms=2_000,
                event_timeout=3.0,
            ),
        )
    except Exception as exc:  # denial type is owned by the pinned runtime
        return type(exc).__name__
    raise AssertionError(f"navigation unexpectedly allowed: {url}")


def remove_quarantine(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        return


async def run_fixture() -> dict[str, Any]:
    from browser_use import BrowserSession
    from browser_use.browser.events import (
        BrowserStateRequestEvent,
        NavigateToUrlEvent,
    )

    FixtureHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    port = int(server.server_address[1])
    fixture_url = f"http://localhost:{port}/fixture"
    numeric_url = f"http://127.0.0.1:{port}/fixture"

    bindings = load_browser_use_bindings()
    profile = build_read_only_browser_profile(bindings, ["localhost"])
    profile.executable_path = browser_executable()
    download_path = Path(profile.downloads_path).resolve(strict=True)
    user_data_path = Path(profile.user_data_dir).resolve(strict=True)
    session = BrowserSession(browser_profile=profile)
    results: dict[str, bool] = {}
    denied: dict[str, str] = {}
    started = False

    try:
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
        check(
            profile.accept_downloads is False,
            "downloads are refused before launch",
            results,
        )
        check(profile.permissions == [], "no browser permissions are granted", results)

        await asyncio.wait_for(session.start(), timeout=30)
        started = True
        check(session.is_cdp_connected, "Chromium starts and CDP connects", results)

        await dispatch(
            session,
            NavigateToUrlEvent(
                url=fixture_url,
                wait_until="load",
                timeout_ms=8_000,
                event_timeout=12.0,
            ),
        )
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
        check(state.url == fixture_url, "allowlisted localhost page is active", results)
        check(
            observed_title == TITLE,
            "fixture title is read through Browser Use's CDP page actor",
            results,
        )
        check(
            FixtureHandler.requests == ["/fixture"],
            "only one loopback request was served",
            results,
        )

        denied["public_domain"] = await expect_denied(
            session,
            "https://example.com/forbidden",
        )
        check(True, "public domain is denied before navigation", results)
        denied["numeric_loopback"] = await expect_denied(session, numeric_url)
        check(True, "numeric IP navigation is denied", results)
        check(
            FixtureHandler.requests == ["/fixture"],
            "denied numeric URL never reaches fixture",
            results,
        )
        check(
            next(download_path.rglob("*"), None) is None,
            "download quarantine stays empty",
            results,
        )
    finally:
        try:
            if started:
                await asyncio.wait_for(session.kill(), timeout=15)
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)
            remove_quarantine(download_path)
            remove_quarantine(user_data_path)

    check(not session.is_cdp_connected, "CDP is closed after kill", results)
    check(not download_path.exists(), "download quarantine is removed", results)
    check(not user_data_path.exists(), "profile quarantine is removed", results)
    check(not server_thread.is_alive(), "fixture server is stopped", results)
    return {
        "schema_version": "modelrig.browser-use-live-fixture.v1",
        "browser_use_version": bindings.version,
        "browser_executable": str(profile.executable_path),
        "fixture_url": fixture_url,
        "denied": denied,
        "checks": results,
        "passed": all(results.values()),
    }


def main() -> int:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = asyncio.run(run_fixture())
    except Exception as exc:
        report = {
            "schema_version": "modelrig.browser-use-live-fixture.v1",
            "passed": False,
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
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
