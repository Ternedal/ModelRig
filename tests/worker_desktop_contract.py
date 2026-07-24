#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.desktop_contract import (  # noqa: E402
    CapturedWindow,
    DesktopAction,
    DesktopContractError,
    DesktopSessionGuard,
    ScreenProofCodec,
    WindowTarget,
)
from app.desktop_policy import DesktopDenied, RateLimiter, TargetAllowlist  # noqa: E402

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def denied(fn, *args, contains: str = "", **kwargs) -> str | None:
    try:
        fn(*args, **kwargs)
    except DesktopDenied as exc:
        message = str(exc)
        check(not contains or contains in message, f"denial names reason: {contains or message}")
        return message
    else:
        check(False, f"operation should be denied: {contains or fn}")
        return None


def malformed(fn, *args, contains: str = "", **kwargs) -> str | None:
    try:
        fn(*args, **kwargs)
    except DesktopContractError as exc:
        message = str(exc)
        check(not contains or contains in message, f"contract rejects malformed input: {contains or message}")
        return message
    else:
        check(False, f"malformed input should fail: {contains or fn}")
        return None


SECRET = b"s" * 32
codec = ScreenProofCodec(
    SECRET,
    ttl_s=20,
    nonce_factory=lambda count: b"n" * count,
)
allowlist = TargetAllowlist(rules={"notepad.exe": ["*"]})
guard = DesktopSessionGuard(
    allowlist,
    codec=codec,
    limiter=RateLimiter(limit=20, window_s=60),
    tolerance=6,
)
target = WindowTarget(
    hwnd=101,
    process="NOTEPAD.EXE",
    title="Untitled - Notepad",
    left=100,
    top=200,
    width=800,
    height=600,
)
capture = CapturedWindow(
    target=target,
    image=b"\x89PNG\r\nsynthetic-window",
    media_type="image/png",
    phash="ff00ff00ff00ff00",
)

receipt = guard.snapshot(
    capture,
    session_id="session-1",
    origin="local",
    now=1000.0,
)
rendered = receipt.to_dict()
check(rendered["schema"] == "kaliv-desktop-snapshot/v1", "snapshot is versioned")
check(rendered["production_activation"] is False, "snapshot cannot activate production")
check(receipt.target.process == "notepad.exe", "Windows process identity is canonicalized")
check(base64.b64decode(receipt.image_base64) == capture.image, "snapshot carries exact image bytes")
check(receipt.image_sha256 == capture.image_sha256, "snapshot binds exact image digest")
check(receipt.screen_token.count(".") == 1, "snapshot returns an opaque signed token")

payload_part = receipt.screen_token.split(".", 1)[0]
payload = base64.urlsafe_b64decode(payload_part + "=" * (-len(payload_part) % 4))
proof_json = json.loads(payload)
check("image" not in proof_json and "image_base64" not in proof_json, "proof contains digest, never raw pixels")
check(proof_json["session_id"] == "session-1", "proof binds the exact session")
check(proof_json["origin"] == "local", "proof binds the planner origin")
check(proof_json["target"]["hwnd"] == 101, "proof binds the exact foreground window")
check(proof_json["image_sha256"] == capture.image_sha256, "proof binds screenshot content hash")

click = DesktopAction(
    kind="click",
    screen_token=receipt.screen_token,
    x=25,
    y=40,
)
authorized = guard.authorize(
    click,
    capture,
    session_id="session-1",
    origin="local",
    now=1005.0,
)
check(authorized.kind == "click", "unchanged window authorizes click")
check((authorized.absolute_x, authorized.absolute_y) == (125, 240), "relative click maps to bound window geometry")
check(authorized.button == "left", "v1 click is left-button only")
check(authorized.to_dict()["production_activation"] is False, "authorized action cannot activate production")

type_action = DesktopAction(
    kind="type_text",
    screen_token=receipt.screen_token,
    text="Hej Anders\n",
)
typed = guard.authorize(
    type_action,
    capture,
    session_id="session-1",
    origin="local",
    now=1006.0,
)
check(typed.kind == "type_text" and typed.text == "Hej Anders\n", "unchanged proof authorizes bounded Unicode text")

caret = CapturedWindow(
    target=target,
    image=b"different bytes are independently hashed",
    media_type="image/png",
    phash="ff00ff00ff00ff01",
)
check(
    guard.authorize(
        click,
        caret,
        session_id="session-1",
        origin="local",
        now=1007.0,
    ).kind
    == "click",
    "one-bit caret change stays inside calibrated tolerance",
)

dialog = CapturedWindow(
    target=target,
    image=b"dialog",
    media_type="image/png",
    phash="ff00ff00ffff0f0f",
)
denied(
    guard.authorize,
    click,
    dialog,
    session_id="session-1",
    origin="local",
    now=1008.0,
    contains="ændret",
)

moved = CapturedWindow(
    target=WindowTarget(
        hwnd=101,
        process="notepad.exe",
        title="Untitled - Notepad",
        left=101,
        top=200,
        width=800,
        height=600,
    ),
    image=capture.image,
    media_type="image/png",
    phash=capture.phash,
)
denied(
    guard.authorize,
    click,
    moved,
    session_id="session-1",
    origin="local",
    now=1008.0,
    contains="geometri",
)

other_title = CapturedWindow(
    target=WindowTarget(
        hwnd=101,
        process="notepad.exe",
        title="Save As",
        left=100,
        top=200,
        width=800,
        height=600,
    ),
    image=capture.image,
    media_type="image/png",
    phash=capture.phash,
)
denied(
    guard.authorize,
    click,
    other_title,
    session_id="session-1",
    origin="local",
    now=1008.0,
    contains="forgrundsvinduet",
)

other_hwnd = CapturedWindow(
    target=WindowTarget(
        hwnd=202,
        process="notepad.exe",
        title="Untitled - Notepad",
        left=100,
        top=200,
        width=800,
        height=600,
    ),
    image=capture.image,
    media_type="image/png",
    phash=capture.phash,
)
denied(
    guard.authorize,
    click,
    other_hwnd,
    session_id="session-1",
    origin="local",
    now=1008.0,
    contains="forgrundsvinduet",
)

denied(
    guard.authorize,
    click,
    capture,
    session_id="session-2",
    origin="local",
    now=1005.0,
    contains="anden session",
)
denied(
    guard.authorize,
    click,
    capture,
    session_id="session-1",
    origin="cloud",
    cloud_consent=True,
    now=1005.0,
    contains="anden model-origin",
)
denied(
    guard.authorize,
    click,
    capture,
    session_id="session-1",
    origin="local",
    now=1020.001,
    contains="gammelt",
)
denied(
    guard.authorize,
    click,
    capture,
    session_id="session-1",
    origin="local",
    now=998.0,
    contains="fremtiden",
)

parts = receipt.screen_token.split(".")
tampered_signature = parts[0] + "." + ("A" if parts[1][0] != "A" else "B") + parts[1][1:]
denied(
    guard.authorize,
    DesktopAction(kind="click", screen_token=tampered_signature, x=1, y=1),
    capture,
    session_id="session-1",
    origin="local",
    now=1005.0,
    contains="signatur",
)

mutated_payload = dict(proof_json)
mutated_payload["target"] = dict(mutated_payload["target"])
mutated_payload["target"]["title"] = "Netbank"
mutated_raw = json.dumps(mutated_payload, sort_keys=True, separators=(",", ":")).encode()
mutated_token = base64.urlsafe_b64encode(mutated_raw).decode().rstrip("=") + "." + parts[1]
denied(
    guard.authorize,
    DesktopAction(kind="click", screen_token=mutated_token, x=1, y=1),
    capture,
    session_id="session-1",
    origin="local",
    now=1005.0,
    contains="signatur",
)

different_codec_guard = DesktopSessionGuard(
    allowlist,
    codec=ScreenProofCodec(b"x" * 32, ttl_s=20),
)
denied(
    different_codec_guard.authorize,
    click,
    capture,
    session_id="session-1",
    origin="local",
    now=1005.0,
    contains="signatur",
)

denied(
    guard.authorize,
    DesktopAction(
        kind="click",
        screen_token=receipt.screen_token,
        x=800,
        y=1,
    ),
    capture,
    session_id="session-1",
    origin="local",
    now=1005.0,
    contains="uden for",
)

empty_guard = DesktopSessionGuard(TargetAllowlist(), codec=codec)
denied(
    empty_guard.snapshot,
    capture,
    session_id="session-empty",
    origin="local",
    now=1000.0,
    contains="allowlisten",
)

restricted_guard = DesktopSessionGuard(
    TargetAllowlist(rules={"notepad.exe": ["*ModelRig*"]}),
    codec=codec,
)
denied(
    restricted_guard.snapshot,
    capture,
    session_id="session-title",
    origin="local",
    now=1000.0,
    contains="allowlisten",
)

denied(
    guard.snapshot,
    capture,
    session_id="session-cloud",
    origin="cloud",
    cloud_consent=False,
    now=1000.0,
    contains="LOKAL",
)
cloud_receipt = guard.snapshot(
    capture,
    session_id="session-cloud",
    origin="cloud",
    cloud_consent=True,
    now=1000.0,
)
cloud_action = DesktopAction(
    kind="click",
    screen_token=cloud_receipt.screen_token,
    x=1,
    y=1,
)
check(
    guard.authorize(
        cloud_action,
        capture,
        session_id="session-cloud",
        origin="cloud",
        cloud_consent=True,
        now=1001.0,
    ).kind
    == "click",
    "separate cloud consent permits only that cloud session",
)
denied(
    guard.authorize,
    cloud_action,
    capture,
    session_id="session-cloud",
    origin="cloud",
    cloud_consent=False,
    now=1001.0,
    contains="LOKAL",
)

limited = DesktopSessionGuard(
    allowlist,
    codec=ScreenProofCodec(SECRET, ttl_s=20, nonce_factory=lambda n: b"r" * n),
    limiter=RateLimiter(limit=2, window_s=60),
)
limited_receipt = limited.snapshot(
    capture,
    session_id="rate-session",
    origin="local",
    now=2000.0,
)
limited_action = DesktopAction(
    kind="click",
    screen_token=limited_receipt.screen_token,
    x=1,
    y=1,
)
for offset in (1.0, 2.0):
    limited.authorize(
        limited_action,
        capture,
        session_id="rate-session",
        origin="local",
        now=2000.0 + offset,
    )
denied(
    limited.authorize,
    limited_action,
    capture,
    session_id="rate-session",
    origin="local",
    now=2003.0,
    contains="for mange",
)

malformed(
    WindowTarget,
    hwnd=1,
    process="C:\\Windows\\notepad.exe",
    title="x",
    left=0,
    top=0,
    width=10,
    height=10,
    contains="basename",
)
malformed(
    DesktopAction,
    kind="click",
    screen_token="x",
    x=1,
    y=1,
    button="right",
    contains="left",
)
malformed(
    DesktopAction,
    kind="type_text",
    screen_token="x",
    text="bad\x00text",
    contains="control",
)
malformed(
    DesktopAction,
    kind="type_text",
    screen_token="x",
    text="",
    contains="1..1000",
)
malformed(
    ScreenProofCodec,
    b"short",
    contains="32 bytes",
)

denied(
    guard.authorize,
    DesktopAction(kind="click", screen_token="not-a-proof", x=1, y=1),
    capture,
    session_id="session-1",
    origin="local",
    now=1005.0,
    contains="ugyldigt",
)

print(f"\nDesktop signed contract: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
