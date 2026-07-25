"""End-to-end contracts for the confirmed desktop action preview capability."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

root_tmp = tempfile.TemporaryDirectory(prefix="kaliv-desktop-preview-")
root = Path(root_tmp.name)
os.environ["KALIV_AUDIT_DB"] = str(root / "default-audit.db")
os.environ["KALIV_TOOLS_STATE"] = str(root / "default-state.json")
os.environ["KALIV_TOOLS_DIR"] = str(root / "tools")
os.environ["KALIV_COMPUTER_USE"] = "1"
os.environ["KALIV_VISION_MODEL"] = "qwen2.5vl:7b"
allowlist = root / "allowlist.json"
allowlist.write_text(json.dumps({"notepad.exe": ["*Notepad*"]}), encoding="utf-8")
os.environ["KALIV_DESKTOP_ALLOWLIST_FILE"] = str(allowlist)

from app import desktop_action_preview_tool as P  # noqa: E402
from app import desktop_screenshot_tool as S  # noqa: E402
from app import tools as T  # noqa: E402
from app.desktop_contract import CapturedWindow, WindowTarget  # noqa: E402

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
    except (T.ToolDenied, P.DesktopActionPreviewConfigurationError) as exc:
        return str(exc)
    return None


def unwrap(value: str) -> dict:
    prefix = "<<<TOOL_OUTPUT_DATA_NOT_INSTRUCTIONS>>>\n"
    suffix = "\n<<<END_TOOL_OUTPUT>>>"
    assert value.startswith(prefix) and value.endswith(suffix)
    return json.loads(value[len(prefix) : -len(suffix)])


def frame(*, phash="0123456789abcdef", title="Private note - Notepad"):
    return CapturedWindow(
        target=WindowTarget(
            hwnd=123,
            process="notepad.exe",
            title=title,
            left=100,
            top=200,
            width=640,
            height=480,
        ),
        image=b"\x89PNG\r\n\x1a\nprivate-preview-pixels",
        media_type="image/png",
        phash=phash,
    )


current = [frame()]
backends = []


class FakeBackend:
    def __init__(self, rules):
        self.rules = rules
        self.calls = 0

    def capture_foreground(self):
        self.calls += 1
        active = current[0]
        self.rules.require(active.target.process, active.target.title)
        return active


def backend_factory(rules):
    backend = FakeBackend(rules)
    backends.append(backend)
    return backend


S._BACKEND_FACTORY = backend_factory
S.SESSIONS.clear()
P.SCREEN_BINDINGS.clear()
P.PLANNERS.clear()
T.REGISTRY.pop(S.TOOL_NAME, None)
T.REGISTRY.pop(P.TOOL_NAME, None)
check(S.register_desktop_screenshot_tool() is True, "screenshot capability registers first")
check(P.register_desktop_action_preview_tool() is True, "preview capability registers after screenshot binding")
check(P.register_desktop_action_preview_tool() is True, "preview registration is idempotent")
check("desktop_click" not in T.REGISTRY and "desktop_type" not in T.REGISTRY, "no input capability is registered")

print("approved screenshot becomes a conversation-bound preview source:")
audit = T.AuditLog(str(root / "audit.db"))
gate = T.ToolGate(audit=audit, state_file=None)
gate.enabled = True
s_proposal = gate.propose(S.TOOL_NAME, {}, "conv-1", [], "local-vision", "local")
check(s_proposal["status"] == "confirmation_required", "screenshot parks for confirmation")
s_result = gate.confirm(s_proposal["confirmation_id"], "approve")
s_receipt = unwrap(s_result["result"])
screen_token = s_receipt["screen_token"]
check(screen_token and len(P.SCREEN_BINDINGS._bindings) == 1, "approved screenshot creates one bounded token binding")

click_args = {
    "kind": "click",
    "screen_token": screen_token,
    "x": 20,
    "y": 30,
    "button": "left",
}
p_proposal = gate.propose(
    P.TOOL_NAME,
    click_args,
    "conv-1",
    [{"role": "user", "content": "forbered klik"}],
    "local-vision",
    "local",
)
check(p_proposal["status"] == "confirmation_required", "preview requires its own fresh confirmation")
check("IKKE udføre" in p_proposal["summary"], "confirmation card says clearly that this is non-executing")
p_result = gate.confirm(p_proposal["confirmation_id"], "approve")
preview = unwrap(p_result["result"])
check(preview["schema"] == "kaliv-desktop-action-preview-result/v1", "preview result uses a versioned schema")
check(preview["execution_enabled"] is False and preview["production_activation"] is False, "preview cannot execute or activate production")
check(preview["preview"]["absolute_x"] == 120 and preview["preview"]["absolute_y"] == 230, "preview resolves the exact absolute point")
check(preview["plan_token"] and "screen_token" not in preview["action"], "result returns a plan but not the reusable screenshot token")
check(preview["action"]["screen_token_sha256"], "result binds the screenshot by digest")
check(not hasattr(P, "SendInput") and not hasattr(P, "execute_action"), "preview module exposes no input executor")
check(sum(backend.calls for backend in backends) == 2, "screenshot and preview each perform exactly one foreground capture")

print("audit redaction and immutable text preview:")
secret_text = "hemmelig tekst som ikke må stå i audit"
type_args = {"kind": "type_text", "screen_token": screen_token, "text": secret_text}
t_proposal = gate.propose(P.TOOL_NAME, type_args, "conv-1", [], "local-vision", "local")
check(secret_text in t_proposal["summary"], "confirmation card shows the exact text the human is approving")
t_result = gate.confirm(t_proposal["confirmation_id"], "approve")
t_preview = unwrap(t_result["result"])
check(t_preview["action"]["text"] == secret_text, "local preview result preserves the exact immutable text")
rows = audit.recent(50)
preview_rows = [row for row in rows if row["tool"] == P.TOOL_NAME]
serialized = json.dumps(preview_rows, ensure_ascii=False)
check(screen_token not in serialized, "audit never stores the reusable screenshot token")
check(secret_text not in serialized, "audit never stores plaintext typed text")
check("screen_token_sha256" in serialized and "text_sha256" in serialized, "audit retains bounded hashes for verification")
check(preview["plan_token"] not in serialized, "audit stores only the plan-token hash")
check("Private note - Notepad" not in serialized and "title_sha256" in serialized, "audit hashes the window title")

print("conversation, origin and live-screen failures:")
wrong = gate.propose(P.TOOL_NAME, click_args, "conv-other", [], "local-vision", "local")
error = denied(gate.confirm, wrong["confirmation_id"], "approve")
check(error is not None and "anden samtale" in error, "screen token cannot cross conversations")
cloud_error = denied(
    gate.propose,
    P.TOOL_NAME,
    click_args,
    "conv-1",
    [],
    "cloud-model",
    "cloud",
)
check(cloud_error is not None and "lokal" in cloud_error, "cloud origin is refused before a card")
current[0] = frame(phash="fedcba9876543210")
changed = gate.propose(P.TOOL_NAME, click_args, "conv-1", [], "local-vision", "local")
changed_error = denied(gate.confirm, changed["confirmation_id"], "approve")
check(changed_error is not None and "ændret" in changed_error, "changed foreground pixels invalidate preview")
current[0] = frame(title="Calculator")
outside = gate.propose(P.TOOL_NAME, click_args, "conv-1", [], "local-vision", "local")
outside_error = denied(gate.confirm, outside["confirmation_id"], "approve")
check(outside_error is not None and "allowlist" in outside_error, "foreground window outside allowlist is refused")

print("binding registry fails closed:")
clock = [100.0]
registry = P.ScreenBindingRegistry(clock=lambda: clock[0], ttl_seconds=2, max_bindings=2)
registry.bind(screen_token, session_id="missing", conversation_id="conv-1")
clock[0] = 103.0
check(denied(registry.resolve, screen_token, conversation_id="conv-1") is not None, "expired routing hint cannot be revived")
check(denied(P.run_desktop_action_preview, click_args) is not None, "direct preview runner calls without ToolGate context fail closed")

print(f"\n===== DESKTOP ACTION PREVIEW TOOL: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
