"""Contracts for the feature-gated foreground screenshot ToolGate capability."""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

_tmp = tempfile.TemporaryDirectory()
root = Path(_tmp.name)
os.environ["KALIV_AUDIT_DB"] = str(root / "default-audit.db")
os.environ["KALIV_TOOLS_STATE"] = str(root / "default-state.json")
os.environ["KALIV_TOOLS_DIR"] = str(root / "tools")
os.environ.pop("KALIV_COMPUTER_USE", None)

from app import desktop_screenshot_tool as D  # noqa: E402
from app import tools as T  # noqa: E402
from app.desktop_contract import CapturedWindow  # noqa: E402
from app.desktop_policy import DesktopDenied  # noqa: E402

passed = failed = 0


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def denied(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except (T.ToolDenied, D.DesktopScreenshotConfigurationError, DesktopDenied) as exc:
        return str(exc)
    return None


print("feature and registration boundary:")
T.REGISTRY.pop(D.TOOL_NAME, None)
check(D.register_desktop_screenshot_tool() is False, "unset feature flag registers nothing")
check(D.TOOL_NAME not in T.REGISTRY, "desktop screenshot is absent from the production registry by default")

allowlist_path = root / "desktop-allowlist.json"
allowlist_path.write_text(
    json.dumps({"notepad.exe": ["*Notepad*"]}), encoding="utf-8"
)
os.environ[D.ALLOWLIST_ENV] = str(allowlist_path)
os.environ[D.FEATURE_ENV] = "1"
check(D.register_desktop_screenshot_tool() is True, "explicit feature flag registers screenshot once")
check(D.register_desktop_screenshot_tool() is True, "registration is idempotent")
tool = T.REGISTRY[D.TOOL_NAME]
check(tool.risk == "desktop" and tool.impact == "desktop", "registry exposes the desktop risk and impact")
check(tool.sensitivity == "secret", "screenshot result is classified as never-cloud secret")
check(not tool.schedulable and tool.network == "none", "screenshot cannot be scheduled and declares no network")
check("desktop_click" not in T.REGISTRY and "desktop_type" not in T.REGISTRY, "no input capability is registered")
check(denied(D.run_desktop_screenshot, {}) is not None, "direct runner calls without ToolGate context fail closed")

print("\nconfirmed local execution:")
secret_png = b"\x89PNG\r\n\x1a\nprivate-pixels-that-must-not-enter-audit"
capture = CapturedWindow(
    target=D.Win32DesktopBackend.__mro__[0].__module__ and __import__(
        "app.desktop_contract", fromlist=["WindowTarget"]
    ).WindowTarget(
        hwnd=123,
        process="notepad.exe",
        title="Private note - Notepad",
        left=10,
        top=20,
        width=640,
        height=480,
    ),
    image=secret_png,
    media_type="image/png",
    phash="0123456789abcdef",
)


class FakeBackend:
    def __init__(self, allowlist):
        self.allowlist = allowlist
        self.calls = 0

    def capture_foreground(self):
        self.calls += 1
        self.allowlist.require(capture.target.process, capture.target.title)
        return capture


backends = []


def backend_factory(allowlist):
    backend = FakeBackend(allowlist)
    backends.append(backend)
    return backend


D._BACKEND_FACTORY = backend_factory
D.SESSIONS.clear()
audit = T.AuditLog(str(root / "test-audit.db"))
gate = T.ToolGate(audit=audit, state_file=None)
gate.enabled = True

cloud_error = denied(
    gate.propose,
    D.TOOL_NAME,
    {},
    "conv-cloud",
    [],
    "cloud-model",
    "cloud",
)
check(cloud_error is not None and "lokal" in cloud_error, "cloud origin is refused before a confirmation card")

proposal = gate.propose(
    D.TOOL_NAME,
    {},
    "conv-local",
    [{"role": "user", "content": "se vinduet"}],
    "local-vision",
    "local",
)
check(proposal["status"] == "confirmation_required", "local screenshot always parks for a fresh card")
check(proposal["risk"] == "desktop", "confirmation card labels the action as desktop")
confirmation_id = proposal["confirmation_id"]
result = gate.confirm(confirmation_id, "approve")
check(result["status"] == "executed", "approved local screenshot executes exactly once")
check(len(backends) == 1 and backends[0].calls == 1, "one approval produces exactly one foreground capture")

envelope = result["result"]
raw_json = envelope.split("\n", 1)[1].rsplit("\n", 1)[0]
receipt = json.loads(raw_json)
check(receipt["schema"] == "kaliv-desktop-snapshot/v1", "result uses the signed snapshot schema")
check(base64.b64decode(receipt["image_base64"]) == secret_png, "local result carries the exact captured PNG")
check(receipt["screen_token"] and receipt["production_activation"] is False, "result carries a dormant signed screen token")

session_id = D._session_id("conv-local", confirmation_id)
runtime = D.SESSIONS.get(session_id)
proof = runtime.guard.codec.verify(
    receipt["screen_token"],
    session_id=session_id,
    origin="local",
    cloud_consent=False,
)
check(proof.image_sha256 == capture.image_sha256, "screen token verifies against the exact image digest")
check(proof.target == capture.target, "screen token binds the exact process, title and geometry")

rows = audit.recent(20)
executed = next(row for row in rows if row["tool"] == D.TOOL_NAME and row["outcome"] == "executed")
summary = executed["result_summary"]
check("image_base64" not in summary and receipt["screen_token"] not in summary, "audit stores neither raw image nor reusable token")
check("private-pixels" not in summary and "Private note" not in summary, "audit stores neither pixels nor plaintext window title")
check("title_sha256" in summary and "image_sha256" in summary, "audit retains bounded verifiable hashes")
check(any(row["outcome"] == "blocked" and row["origin"] == "cloud" for row in rows), "cloud refusal is visible in audit")

print("\nallowlist and lifecycle failures:")
allowlist_path.write_text(json.dumps({"calc.exe": ["*"]}), encoding="utf-8")
proposal2 = gate.propose(D.TOOL_NAME, {}, "conv-2", [], "local-vision", "local")
error = denied(gate.confirm, proposal2["confirmation_id"], "approve")
check(error is not None and "allowlist" in error, "foreground process outside the updated allowlist is refused")
check(denied(gate.confirm, confirmation_id, "approve") is not None, "confirmation cannot be replayed")

print(f"\n===== DESKTOP SCREENSHOT TOOL: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
