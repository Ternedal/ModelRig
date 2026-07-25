"""Contracts for dormant signed desktop action preview plans."""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.desktop_action_plan import (  # noqa: E402
    ACTION_PLAN_SCHEMA,
    ACTION_PREVIEW_SCHEMA,
    DesktopActionPlanner,
)
from app.desktop_contract import (  # noqa: E402
    CapturedWindow,
    DesktopAction,
    DesktopSessionGuard,
    ScreenProofCodec,
    WindowTarget,
)
from app.desktop_policy import DesktopDenied, RateLimiter, TargetAllowlist  # noqa: E402

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
    except DesktopDenied as exc:
        return str(exc)
    return None


def decode_payload(token: str) -> dict:
    encoded = token.split(".", 1)[0]
    raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    return json.loads(raw)


def capture(*, phash: str = "0123456789abcdef", title: str = "Test - Notepad") -> CapturedWindow:
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
        image=b"\x89PNG\r\n\x1a\npreview-pixels",
        media_type="image/png",
        phash=phash,
    )


clock = [1000.0]
limiter = RateLimiter(limit=3, window_s=60.0)
codec = ScreenProofCodec(
    secret=b"S" * 32,
    ttl_s=20,
    clock=lambda: clock[0],
    nonce_factory=lambda size: b"N" * size,
)
allowlist = TargetAllowlist(rules={"notepad.exe": ["*Notepad*"]})
guard = DesktopSessionGuard(allowlist, codec=codec, limiter=limiter, tolerance=6)
initial = capture()
snapshot = guard.snapshot(
    initial,
    session_id="desktop_session_1",
    origin="local",
    now=clock[0],
)
planner = DesktopActionPlanner(
    guard,
    secret=b"P" * 32,
    ttl_s=10,
    clock=lambda: clock[0],
    nonce_factory=lambda size: b"Q" * size,
)
click = DesktopAction(
    kind="click",
    screen_token=snapshot.screen_token,
    x=20,
    y=30,
    button="left",
)

print("preview is signed but non-executing:")
clock[0] = 1002.0
preview = planner.preview(
    click,
    initial,
    session_id="desktop_session_1",
    origin="local",
    now=clock[0],
)
value = preview.to_dict()
check(value["schema"] == ACTION_PREVIEW_SCHEMA, "preview uses a versioned schema")
check(value["execution_enabled"] is False and value["production_activation"] is False, "preview cannot claim execution or activation")
check(value["preview"]["absolute_x"] == 120 and value["preview"]["absolute_y"] == 230, "preview resolves window-relative coordinates deterministically")
check(len(limiter._hits) == 0, "preview does not consume the execution rate limiter")
plan = decode_payload(preview.plan_token)
check(plan["schema"] == ACTION_PLAN_SCHEMA, "plan token carries the exact action-plan schema")
check(plan["action"]["x"] == 20 and plan["action"]["y"] == 30, "plan token binds the exact requested coordinates")
check(plan["screen_token_sha256"] and "screen_token" in plan["action"], "plan binds the original signed screenshot proof")
check(plan["production_activation"] is False, "signed payload remains dormant")
check("desktop_win32" not in sys.modules and "desktop_win32_v2" not in sys.modules, "plan substrate imports no Windows input adapter")

print("\nconsume revalidates and spends once:")
clock[0] = 1003.0
authorized = planner.consume(
    preview.plan_token,
    click,
    initial,
    session_id="desktop_session_1",
    origin="local",
    now=clock[0],
)
check(authorized.absolute_x == 120 and authorized.absolute_y == 230, "consume returns only an authorized data structure")
check(len(limiter._hits) == 1, "final consume runs the authoritative guard and rate limiter exactly once")
check(denied(
    planner.consume,
    preview.plan_token,
    click,
    initial,
    session_id="desktop_session_1",
    origin="local",
    now=clock[0],
) is not None, "plan token is one-shot and cannot be replayed")
check(len(limiter._hits) == 1, "replay refusal does not execute the guard again")

print("\nexact binding and freshness:")
clock[0] = 1004.0
preview2 = planner.preview(click, initial, session_id="desktop_session_1", origin="local", now=clock[0])
changed_action = DesktopAction(
    kind="click",
    screen_token=snapshot.screen_token,
    x=21,
    y=30,
    button="left",
)
check(denied(
    planner.consume,
    preview2.plan_token,
    changed_action,
    initial,
    session_id="desktop_session_1",
    origin="local",
    now=clock[0],
) is not None, "coordinates cannot change after preview")
check(denied(
    planner.consume,
    preview2.plan_token,
    click,
    capture(phash="fedcba9876543210"),
    session_id="desktop_session_1",
    origin="local",
    now=clock[0],
) is not None, "changed pixels are refused before the final guard")
check(denied(
    planner.consume,
    preview2.plan_token,
    click,
    initial,
    session_id="other_session",
    origin="local",
    now=clock[0],
) is not None, "plan cannot cross sessions")
check(denied(
    planner.consume,
    preview2.plan_token[:-1] + ("A" if preview2.plan_token[-1] != "A" else "B"),
    click,
    initial,
    session_id="desktop_session_1",
    origin="local",
    now=clock[0],
) is not None, "tampered plan signature is refused")
clock[0] = 1015.0
check(denied(
    planner.consume,
    preview2.plan_token,
    click,
    initial,
    session_id="desktop_session_1",
    origin="local",
    now=clock[0],
) is not None, "expired plan cannot be consumed")

print("\norigin, text and absence of input:")
clock[0] = 1005.0
check(denied(
    planner.preview,
    click,
    initial,
    session_id="desktop_session_1",
    origin="cloud",
    cloud_consent=False,
    now=clock[0],
) is not None, "cloud-origin planning remains denied without separate consent")
type_action = DesktopAction(
    kind="type_text",
    screen_token=snapshot.screen_token,
    text="præcis tekst",
)
type_preview = planner.preview(
    type_action,
    initial,
    session_id="desktop_session_1",
    origin="local",
    now=clock[0],
)
check(type_preview.to_dict()["preview"]["text"] == "præcis tekst", "type preview shows the exact immutable text")
check(type_preview.to_dict()["preview"]["absolute_x"] is None, "type preview cannot smuggle click coordinates")
from app import tools as T  # noqa: E402
check("desktop_click" not in T.REGISTRY and "desktop_type" not in T.REGISTRY, "no click or type tool is registered")
check(not hasattr(planner, "click") and not hasattr(planner, "type_text"), "planner exposes no input injection method")

print(f"\n===== DESKTOP ACTION PLAN: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
