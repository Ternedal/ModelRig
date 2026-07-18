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
from app.browser_use_egress import BrowserUseEgressGuard
from app.research_contract import ReadOnlyBrowserPolicy

FIXTURE_HOST = "fixture.modelrig.test"
BLOCKED_HOST = "blocked.modelrig.test"
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
    requests: list[tuple[str, str, str]] = []
    lock = threading.Lock()

    def _record(self) -> str:
        host = (self.headers.get("Host") or "").split(":", 1)[0].lower()
        with self.lock:
            self.requests.append((host, self.command, self.path))
        return host

    def do_GET(self) -> None:
        host = self._record()
        if host == FIXTURE_HOST and self.path == "/":
            port = self.server.server_port
            body = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>ModelRig Fixture</title></head>
<body>
  <main><h1 id="status">Fixture booting</h1><p>Local-only Browser Use contract.</p></main>
  <script>
    setTimeout(() => {{
      document.getElementById('status').textContent = {READY_TEXT!r};
      fetch('/post', {{method: 'POST', body: 'forbidden'}}).catch(() => {{}});
      const image = new Image();
      image.src = 'http://{BLOCKED_HOST}:{port}/subresource';
      document.body.appendChild(image);
      window.open('http://{BLOCKED_HOST}:{port}/popup', '_blank');
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

        if host == FIXTURE_HOST and self.path == "/redirect":
            self.send_response(302)
            self.send_header(
                "Location",
                f"http://{BLOCKED_HOST}:{self.server.server_port}/redirect-target",
            )
            self.end_headers()
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

    def do_POST(self) -> None:
        self._record()
        body = b"post reached fixture"
        self.send_response(200)
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
        return "blocked" in text or "err_blocked_by_client" in text or "security policy" in text
    return False


def requests_for(*, host: str | None = None, method: str | None = None, path: str | None = None):
    with FixtureHandler.lock:
        rows = list(FixtureHandler.requests)
    return [
        row
        for row in rows
        if (host is None or row[0] == host)
        and (method is None or row[1] == method)
        and (path is None or row[2] == path)
    ]


async def live_contract(browser: Path, port: int) -> None:
    bindings = load_browser_use_bindings()
    from browser_use import BrowserProfile, BrowserSession
    from browser_use.browser.events import NavigateToUrlEvent

    check(bindings.profile_factory is BrowserProfile, "adapter and live gate use the same BrowserProfile class")

    policy = ReadOnlyBrowserPolicy(
        allowed_domains=(FIXTURE_HOST,),
        max_steps=4,
        max_pages=4,
        timeout_seconds=20,
        max_source_bytes=4096,
    )
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
    guard = BrowserUseEgressGuard(policy)
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
        await asyncio.wait_for(guard.attach(session), timeout=10)
        check(not guard.records, "request guard attaches before the first page request")

        fixture_url = f"http://{FIXTURE_HOST}:{port}/"
        await asyncio.wait_for(navigate(session, NavigateToUrlEvent, fixture_url), timeout=20)

        state = None
        dom_text = ""
        for _ in range(50):
            state = await session.get_browser_state_summary(include_screenshot=False)
            dom_text = state.dom_state.llm_representation()
            if READY_TEXT in dom_text:
                break
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.5)

        check(state is not None and state.url == fixture_url, "browser reaches only the allowlisted fixture URL")
        check(READY_TEXT in dom_text, "real Chromium executes and Browser Use extracts fixture JavaScript")
        check(state is not None and state.screenshot is None, "live contract captures no screenshot")
        check(bool(requests_for(host=FIXTURE_HOST, method="GET", path="/")), "fixture receives the allowlisted document GET")
        check(not requests_for(method="POST", path="/post"), "page-authored POST is blocked before the fixture")
        check(not requests_for(host=BLOCKED_HOST), "page-authored subresource and popup cannot reach a blocked host")
        check(any(record.reason == "method_not_read_only" for record in guard.records), "guard records the blocked POST")
        check(any(record.reason == "url_not_allowed" for record in guard.records), "guard records blocked page-authored egress")

        blocked_url = f"http://{BLOCKED_HOST}:{port}/blocked"
        blocked = await asyncio.wait_for(rejected_navigation(session, NavigateToUrlEvent, blocked_url), timeout=10)
        await asyncio.sleep(0.2)
        check(blocked, "blocked-domain navigation returns a browser error")
        check(not requests_for(host=BLOCKED_HOST, path="/blocked"), "blocked-domain navigation sends no HTTP request")
        state_after_block = await session.get_browser_state_summary(include_screenshot=False)
        check(state_after_block.url == fixture_url, "blocked-domain navigation leaves the allowlisted page focused")

        ip_url = f"http://127.0.0.1:{port}/ip"
        ip_blocked = await asyncio.wait_for(rejected_navigation(session, NavigateToUrlEvent, ip_url), timeout=10)
        await asyncio.sleep(0.2)
        check(ip_blocked, "direct-IP navigation returns a browser error")
        check(not requests_for(path="/ip"), "direct-IP navigation sends no HTTP request")
        state_after_ip = await session.get_browser_state_summary(include_screenshot=False)
        check(state_after_ip.url == fixture_url, "direct-IP denial leaves the allowlisted page focused")

        redirect_url = f"http://{FIXTURE_HOST}:{port}/redirect"
        redirect_blocked = await asyncio.wait_for(
            rejected_navigation(session, NavigateToUrlEvent, redirect_url),
            timeout=15,
        )
        await asyncio.sleep(0.2)
        check(bool(requests_for(host=FIXTURE_HOST, method="GET", path="/redirect")), "allowlisted redirect source is requested")
        check(not requests_for(host=BLOCKED_HOST, path="/redirect-target"), "redirect target is blocked before network egress")
        check(redirect_blocked, "blocked redirect is surfaced as a browser error")

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
        asyncio.run(asyncio.wait_for(live_contract(browser, server.server_port), timeout=90))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        check(not thread.is_alive(), "local fixture server stops cleanly")

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
