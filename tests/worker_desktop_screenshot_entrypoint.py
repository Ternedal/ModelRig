"""Fresh-process wiring contract for dormant Computer Use see/preview capabilities."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "worker"
passed = failed = 0


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def probe(env: dict[str, str]) -> dict:
    script = f"""
import json,sys
sys.path.insert(0,{str(WORKER)!r})
import app.main
from app import tools
print('DESKTOP_ENTRYPOINT=' + json.dumps({{
    'screenshot': 'desktop_screenshot' in tools.REGISTRY,
    'preview': 'desktop_action_preview' in tools.REGISTRY,
    'click': 'desktop_click' in tools.REGISTRY,
    'type': 'desktop_type' in tools.REGISTRY,
    'screenshot_module': 'app.desktop_screenshot_tool' in sys.modules,
    'preview_module': 'app.desktop_action_preview_tool' in sys.modules,
    'plan_module': 'app.desktop_action_plan' in sys.modules,
    'vision_module': 'app.desktop_vision_bridge' in sys.modules,
    'vision_wrapped': bool(getattr(app.main._run_tool_loop, '_kaliv_desktop_vision_bridge', False)),
    'win32_module': 'app.desktop_win32' in sys.modules or 'app.desktop_win32_v2' in sys.modules,
}}, sort_keys=True))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        return {"process_failed": True}
    lines = [line for line in result.stdout.splitlines() if line.startswith("DESKTOP_ENTRYPOINT=")]
    if len(lines) != 1:
        return {"protocol_failed": True, "stdout": result.stdout[-500:]}
    return json.loads(lines[0].split("=", 1)[1])


with tempfile.TemporaryDirectory(prefix="kaliv-desktop-entrypoint-") as tmp:
    root = Path(tmp)
    base = dict(os.environ)
    base.update(
        {
            "KALIV_AUDIT_DB": str(root / "audit.db"),
            "KALIV_TOOLS_STATE": str(root / "state.json"),
            "KALIV_JOBS_DB": str(root / "jobs.db"),
            "KALIV_TOOLS_DIR": str(root / "tools"),
        }
    )
    base.pop("KALIV_COMPUTER_USE", None)
    off = probe(base)

    allowlist = root / "allowlist.json"
    allowlist.write_text(json.dumps({"notepad.exe": ["*"]}), encoding="utf-8")
    enabled = dict(base)
    enabled["KALIV_COMPUTER_USE"] = "1"
    enabled["KALIV_DESKTOP_ALLOWLIST_FILE"] = str(allowlist)
    enabled["KALIV_VISION_MODEL"] = "qwen2.5vl:7b"
    on = probe(enabled)

check(not off.get("process_failed") and not off.get("protocol_failed"), "default worker starts cleanly")
check(off.get("screenshot") is False and off.get("preview") is False, "feature-off startup registers no desktop capability")
check(off.get("screenshot_module") is False, "feature-off startup does not import the screenshot module")
check(off.get("preview_module") is False and off.get("plan_module") is False, "feature-off startup imports neither preview nor action-plan substrate")
check(off.get("vision_module") is False and off.get("vision_wrapped") is False, "feature-off startup does not import or install the vision bridge")
check(off.get("win32_module") is False, "feature-off startup does not bind or import the Win32 adapter")
check(not on.get("process_failed") and not on.get("protocol_failed"), "feature-on worker starts cleanly")
check(on.get("screenshot") is True and on.get("preview") is True, "explicit flag registers screenshot and non-executing preview")
check(on.get("screenshot_module") is True and on.get("preview_module") is True and on.get("plan_module") is True, "feature-on startup loads the intended see/preview boundary")
check(on.get("win32_module") is True, "feature-on startup loads the foreground capture adapter")
check(on.get("vision_module") is True and on.get("vision_wrapped") is True, "feature-on startup installs the local vision continuation")
check(on.get("click") is False and on.get("type") is False, "startup still registers no click or type capability")

print(f"\n===== DESKTOP SCREENSHOT ENTRYPOINT: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
