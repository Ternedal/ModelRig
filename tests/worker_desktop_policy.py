"""Tests for the Tier B desktop policy (ISOLATION_DESIGN §4.2-4.4).

These rules are what stands between "the agent can use my PC" and "the agent
did something I did not authorise on my PC". None of them can be verified by
reading the code once and believing it, so each one is driven at its edge.

Run: PYTHONPATH=worker python3 tests/worker_desktop_policy.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app import tools as T  # noqa: E402
from app.desktop_policy import (  # noqa: E402
    DesktopDenied,
    RateLimiter,
    ScreenRegistry,
    TargetAllowlist,
    require_local_origin,
)

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def denied(fn, *a, **k) -> str | None:
    try:
        fn(*a, **k)
        return None
    except DesktopDenied as e:
        return str(e)


# --- screenshot binding: the core mechanism ---------------------------------

reg = ScreenRegistry(ttl_s=20.0, tolerance=6)
ref = reg.issue("phash-abc", now=1000.0)

check(reg.verify(ref.screen_id, "phash-abc", distance=0, now=1005.0) is None,
      "an unchanged screen inside the TTL is actionable")
check(reg.verify(ref.screen_id, "phash-abc", distance=6, now=1005.0) is None,
      "a blinking caret (distance == tolerance) does not invalidate a plan")

msg = denied(reg.verify, ref.screen_id, "phash-xyz", 7, 1005.0)
check(msg is not None and "ændret sig" in msg,
      "a screen that moved beyond tolerance REFUSES the action (a dialog appeared)")

msg = denied(reg.verify, ref.screen_id, "phash-abc", 0, 1031.0)
check(msg is not None and "gammelt" in msg,
      "a plan older than the TTL is refused even if the screen looks identical")

msg = denied(reg.verify, "never-issued", "phash-abc", 0, 1005.0)
check(msg is not None and "ukendt" in msg,
      "an action quoting an unknown screen id is refused (no acting from memory)")

# The same screenshot may drive several clicks in one plan -- freshness is
# re-checked against the LIVE screen each time, which is stronger than rationing.
r2 = reg.issue("phash-def", now=2000.0)
ok = all(reg.verify(r2.screen_id, "phash-def", 0, 2000.0 + i) is None for i in range(3))
check(ok, "one screenshot can back a multi-step plan, re-verified at every step")

# --- allowlist: fail-closed by construction ---------------------------------

empty = TargetAllowlist()
check(not empty.allows("notepad.exe", "Untitled"),
      "an empty allowlist allows NOTHING -- computer-use is off until Anders says otherwise")

al = TargetAllowlist(rules={"notepad.exe": ["*"], "chrome.exe": ["*ModelRig*"]})
check(al.allows("notepad.exe", "hvadsomhelst.txt"), "an allowlisted process with * matches any title")
check(al.allows("NOTEPAD.EXE", "x"), "process matching is case-insensitive (Windows)")
check(al.allows("chrome.exe", "ModelRig — Chrome"), "a title pattern matches its window")
check(not al.allows("chrome.exe", "Netbank — Chrome"),
      "the SAME process is refused on a non-matching title (this is the point)")
check(not al.allows("cmd.exe", "C:\\"), "a process outside the list is refused")

msg = denied(al.require, "cmd.exe", "C:\\Windows")
check(msg is not None and "allowlisten" in msg, "require() names the refused window")

# --- rate limit -------------------------------------------------------------

rl = RateLimiter(limit=3, window_s=60.0)
for i in range(3):
    rl.require(now=100.0 + i)
msg = denied(rl.require, 103.0)
check(msg is not None and "for mange" in msg, "a model in a loop is stopped at the limit")
check(rl.require(now=200.0) is None, "the window slides -- the limit is not a permanent ban")

# --- the cloud-origin rule: the most important one --------------------------

check(require_local_origin("local", consent=False) is None,
      "a local model may plan desktop actions with no ceremony")

msg = denied(require_local_origin, "cloud", False)
check(msg is not None and "LOKAL" in msg,
      "a CLOUD model may not plan desktop actions by default -- a screenshot is your whole screen")
check("samtykke" in (msg or ""), "the refusal tells the person how to change it, if they mean to")

check(require_local_origin("cloud", consent=True) is None,
      "explicit per-session consent is the only way out, and it is a separate promise")

# --- the gate learns the new class, and nothing uses it yet -----------------

check("desktop" in getattr(T, "Risk").__args__,
      "the gate knows the desktop risk class")
fake = T.Tool(name="click", description="", risk="desktop", run=lambda a: "")
check(T.requires_confirmation(fake, "local") and T.requires_confirmation(fake, "cloud"),
      "a desktop action ALWAYS needs confirmation -- from either origin, like a write")
reader = T.Tool(name="peek", description="", risk="read", run=lambda a: "")
check(not T.requires_confirmation(reader, "cloud"),
      "the new class did not disturb the read rule (risk decides, not origin)")
check(all(t.risk != "desktop" for t in T.REGISTRY.values()),
      "no tool declares desktop yet -- the rules land before the plumbing")

print(f"\n===== DESKTOP POLICY: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
