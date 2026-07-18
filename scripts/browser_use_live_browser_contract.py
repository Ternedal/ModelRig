from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.browser_use_adapter import load_browser_use_bindings

FIXTURE_HOST = "fixture.modelrig.test"
BLOCKED_HOST = "blocked.modelrig.test"
READY_TITLE = "ModelRig Fixture Ready"
READY_TEXT = "JavaScript fixture ready"

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


class FixtureHandler(BaseHTTPRequestHandler):
    requests: list[tuple[str, str]] = []
    lock = threading.Lock()

    def do_GET(self) -> None:
        host = (self.headers.get("Host") or "").split(":", 1)[0].lower()
        with self.lock:
            self.requests.append((host, self.path))

        if host == FIXTURE_HOST and self.path == "/":
            body = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>ModelRig Fixture Booting</title></head>
<body>
  <main><h1 id="status">Fixture booting</h1><p>Local-only Browser Use contract.</p></main>
  <script>
    setTimeout(() => {{
      document.title = {READY_TITLE!r};
      document.getElementById('status').textContent = {READY_TEXT!r};
    }}, 100);
  </script>
</body>
</html>""".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        body = b"unexpected request"
        self.send_response(418)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args) -> None:
        return


def browser_executable() -> Path:
    configured = os.environ.get("MODELRIG_BROWSER_EXECUTABLE", "").strip()
    candidates = [
        configured,
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ]
    for raw in candidates:
        if not raw:
            continue
        path = Path(raw).expanduser().resolve()
        if path.is_file() and os.access(path, os.X_OK):
            return path
    raise RuntimeError("no supported local Chromium executable was found")


async def navigate(session, event_type, url: str) -> None:
    event = session.event_bus.dispatch(event_type(url=url, new_tab=False))
    await event
    await event.event_result(raise_if_any=True, raise_if_none=False)


async def rejected_navigation(session, event_type, url: str) -> bool:
    try:
        await navigate(session, event_type, url)
    except Exception as exc:
        text = str(exc).lower()
        return "blocked" in text and "security policy" in text
    return False


async def live_contract(browser: Path, port: int) -> None:
    bindings = load_browser_use_bindings()
    from browser_use import BrowserProfile, BrowserSession
    from browser_use.browser.events import NavigateToUrlEvent

    check(bindings.profile_factory is BrowserProfile, "adapter and live gate use the same BrowserProfile class")

    profile = BrowserProfile(
        executable_path=browser,
        headless=True,
        args=[
            "--host-resolver-rules=MAP * 127.0.0.1",
            "--no-proxy-server",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-sync",
            "--metrics-recording-only",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        allowed_domains=[FIXTURE_HOST],
        block_ip_addresses=True,
        user_data_dir=None,
        storage_state=None,
        keep_alive=False,
        enable_default_extensions=False,
        downloads_path=None,
        accept_downloads=False,
        permissions=[],
        auto_download_pdfs=False,
        captcha_solver=False,
    )
    download_path = Path(profile.downloads_path).expanduser().resolve(strict=True)
    user_data_path = Path(profile.user_data_dir).expanduser().resolve(strict=True)
    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    session = BrowserSession(browser_profile=profile)
    started = False

    try:
        check(profile.accept_downloads is False, "live browser context refuses downloads")
        check(profile.permissions == [], "live browser context grants no permissions")
        check(download_path.parent == temp_root, "live download quarantine is under system temp")
        check(user_data_path.parent == temp_root, "live profile quarantine is under system temp")
        check(next(download_path.iterdir(), None) is None, "live download quarantine starts empty")
        check(next(user_data_path.iterdir(), None) is None, "live profile quarantine starts empty")

        await asyncio.wait_for(session.start(), timeout=30)
        started = True
        check(session.is_cdp_connected, "BrowserSession starts a real CDP connection")

        fixture_url = f"http://{FIXTURE_HOST}:{port}/"
        await asyncio.wait_for(navigate(session, NavigateToUrlEvent, fixture_url), timeout=20)

        state = None
        dom_text = ""
        for _ in range(40):
            state = await session.get_browser_state_summary(include_screenshot=False)
            dom_text = state.dom_state.llm_representation()
            if state.title == READY_TITLE and READY_TEXT in dom_text:
                break
            await asyncio.sleep(0.1)

        check(state is not None and state.url == fixture_url, "browser reaches only the allowlisted fixture URL")
        check(state is not None and state.title == READY_TITLE, "real Chromium executes fixture JavaScript")
        check(READY_TEXT in dom_text, "Browser Use extracts the JavaScript-rendered DOM")
        check(state is not None and state.screenshot is None, "live contract captures no screenshot")

        with FixtureHandler.lock:
            allowed_hits = list(FixtureHandler.requests)
        check((FIXTURE_HOST, "/") in allowed_hits, "fixture server receives the allowlisted document request")

        blocked_url = f"http://{BLOCKED_HOST}:{port}/blocked"
        blocked = await asyncio.wait_for(
            rejected_navigation(session, NavigateToUrlEvent, blocked_url),
            timeout=10,
        )
        await asyncio.sleep(0.2)
        with FixtureHandler.lock:
            blocked_hits = [item for item in FixtureHandler.requests if item[0] == BLOCKED_HOST]
        check(blocked, "Browser Use rejects a domain outside the allowlist")
        check(not blocked_hits, "blocked-domain navigation sends no HTTP request")

        ip_url = f"http://127.0.0.1:{port}/ip"
        ip_blocked = await asyncio.wait_for(
            rejected_navigation(session, NavigateToUrlEvent, ip_url),
            timeout=10,
        )
        await asyncio.sleep(0.2)
        with FixtureHandler.lock:
            ip_hits = [item for item in FixtureHandler.requests if item[1] == "/ip"]
        check(ip_blocked, "Browser Use rejects direct-IP navigation")
        check(not ip_hits, "direct-IP navigation sends no HTTP request")

        final_state = await session.get_browser_state_summary(include_screenshot=False)
        check(final_state.url == fixture_url, "rejected navigation leaves the allowed page focused")
        check(next(download_path.rglob("*"), None) is None, "live session creates no download artifact")
        check(next(user_data_path.rglob("*"), None) is not None, "real Chromium uses only the ephemeral profile quarantine")
    finally:
        if started:
            try:
                await asyncio.wait_for(session.kill(), timeout=20)
            except Exception as exc:
                check(False, f"BrowserSession cleanup succeeds ({type(exc).__name__})")
            else:
                check(not session.is_cdp_connected, "BrowserSession kill closes the CDP connection")
        for path in (download_path, user_data_path):
            shutil.rmtree(path, ignore_errors=False)
        check(not download_path.exists(), "live download quarantine is removable after browser shutdown")
        check(not user_data_path.exists(), "live profile quarantine is removable after browser shutdown")


def main() -> int:
    browser = browser_executable()
    version = subprocess.run(
        [str(browser), "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    check(bool(version), "local Chromium reports a version")
    print(f"  INFO: {version}")

    FixtureHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name="modelrig-browser-fixture", daemon=True)
    thread.start()
    try:
        asyncio.run(asyncio.wait_for(live_contract(browser, server.server_port), timeout=75))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        check(not thread.is_alive(), "local fixture server stops cleanly")

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
