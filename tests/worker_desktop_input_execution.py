"""Contracts for the dormant, physically gated desktop input coordinator."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.desktop_action_plan import DesktopActionPlanner  # noqa: E402
from app.desktop_contract import (  # noqa: E402
    DesktopAction,
    DesktopSessionGuard,
    ScreenProofCodec,
    WindowTarget,
)
from app.desktop_input_execution import (  # noqa: E402
    DesktopInputApproval,
    DesktopInputContractError,
    DesktopInputExecutionCoordinator,
    PhysicalDesktopGateEvidence,
    action_sha256,
    plan_token_sha256,
    session_sha256,
)
from app.desktop_policy import (  # noqa: E402
    DesktopDenied,
    RateLimiter,
    TargetAllowlist,
)
from app.desktop_win32 import Win32DesktopBackend  # noqa: E402

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
    except (DesktopDenied, DesktopInputContractError) as exc:
        return str(exc)
    return None


class FakeNative:
    def __init__(self):
        self.target = WindowTarget(
            hwnd=777,
            process="notepad.exe",
            title="Execution test - Notepad",
            left=100,
            top=200,
            width=4,
            height=2,
        )
        self.bgra = bytes(
            [
                0, 0, 0, 255,
                10, 10, 10, 255,
                20, 20, 20, 255,
                30, 30, 30, 255,
                40, 40, 40, 255,
                50, 50, 50, 255,
                60, 60, 60, 255,
                70, 70, 70, 255,
            ]
        )
        self.capture_calls = 0
        self.cursor = None
        self.clicks = 0
        self.units = []

    def foreground_target(self):
        return self.target

    def capture_bgra(self, target):
        assert target == self.target
        self.capture_calls += 1
        return self.bgra

    def set_cursor_pos(self, x, y):
        self.cursor = (x, y)

    def send_left_click(self):
        self.clicks += 1

    def send_unicode_units(self, units):
        self.units.extend(units)


clock = [1000.0]
allowlist = TargetAllowlist(rules={"notepad.exe": ["*Notepad*"]})
native = FakeNative()

print("dormancy and physical gate are prerequisites:")
dormant_backend = Win32DesktopBackend(
    allowlist,
    native=native,
    input_enabled=False,
)
placeholder_guard = DesktopSessionGuard(
    allowlist,
    codec=ScreenProofCodec(secret=b"S" * 32, clock=lambda: clock[0]),
    limiter=RateLimiter(limit=10, window_s=60),
)
placeholder_planner = DesktopActionPlanner(
    placeholder_guard,
    secret=b"P" * 32,
    clock=lambda: clock[0],
)
gate = PhysicalDesktopGateEvidence(
    candidate_sha="a" * 40,
    evidence_sha256="b" * 64,
    tested_at_ms=900_000,
    expires_at_ms=2_000_000,
    low_integrity_verified=True,
    uipi_verified=True,
    kill_switch_verified=True,
)
check(
    denied(
        DesktopInputExecutionCoordinator,
        placeholder_planner,
        dormant_backend,
        candidate_sha="a" * 40,
        physical_gate=gate,
        physical_gate_verifier=lambda _value: True,
        approval_verifier=lambda _value: True,
        clock=lambda: clock[0],
    )
    is not None,
    "a normal input-disabled Win32 backend cannot construct the coordinator",
)
check(
    "desktop_input_execution" not in (ROOT / "worker/app/main.py").read_text(encoding="utf-8"),
    "worker startup does not import or register the execution boundary",
)
check(
    "os.getenv" not in (ROOT / "worker/app/desktop_input_execution.py").read_text(encoding="utf-8"),
    "there is no environment-variable escape hatch",
)

print("exact approval + plan + fresh capture execute once:")
active_backend = Win32DesktopBackend(
    allowlist,
    native=native,
    input_enabled=True,
)
initial = active_backend.capture_foreground()
codec = ScreenProofCodec(
    secret=b"C" * 32,
    ttl_s=20,
    clock=lambda: clock[0],
    nonce_factory=lambda size: b"N" * size,
)
limiter = RateLimiter(limit=10, window_s=60)
guard = DesktopSessionGuard(allowlist, codec=codec, limiter=limiter, tolerance=6)
snapshot = guard.snapshot(
    initial,
    session_id="desktop_session_1",
    origin="local",
    now=clock[0],
)
planner = DesktopActionPlanner(
    guard,
    secret=b"Q" * 32,
    ttl_s=10,
    clock=lambda: clock[0],
    nonce_factory=lambda size: b"R" * size,
)
click = DesktopAction(
    kind="click",
    screen_token=snapshot.screen_token,
    x=2,
    y=1,
    button="left",
)
clock[0] = 1001.0
preview = planner.preview(
    click,
    initial,
    session_id="desktop_session_1",
    origin="local",
    now=clock[0],
)
approval = DesktopInputApproval(
    confirmation_id="confirm_click_1",
    plan_token_sha256=plan_token_sha256(preview.plan_token),
    action_sha256=action_sha256(click),
    session_sha256=session_sha256("desktop_session_1"),
    issued_at_ms=1_001_000,
    expires_at_ms=1_020_000,
    nonce="approval_nonce_click_0001",
)
verified_gate = []
verified_approval = []
coordinator = DesktopInputExecutionCoordinator(
    planner,
    active_backend,
    candidate_sha="a" * 40,
    physical_gate=gate,
    physical_gate_verifier=lambda value: verified_gate.append(value) is None,
    approval_verifier=lambda value: verified_approval.append(value) is None,
    clock=lambda: clock[0],
)
clock[0] = 1002.0
before_capture = native.capture_calls
receipt = coordinator.execute(
    preview.plan_token,
    click,
    approval,
    session_id="desktop_session_1",
)
value = receipt.to_dict()
check(len(verified_gate) == 1 and len(verified_approval) == 1, "both independent proofs are verified")
check(native.capture_calls == before_capture + 1, "execution performs exactly one fresh foreground capture")
check(native.cursor == (102, 201) and native.clicks == 1, "only the authorized absolute click is injected")
check(len(limiter._hits) == 1, "the final planner consume runs the shared rate limiter once")
serialized = json.dumps(value, ensure_ascii=False)
check(value["input_executed"] is True and value["production_activation"] is False, "receipt states local execution without production activation")
check(preview.plan_token not in serialized and snapshot.screen_token not in serialized, "receipt contains hashes, never reusable tokens")
check("Execution test - Notepad" not in serialized and value["title_sha256"], "receipt hashes the window title")
check(denied(
    coordinator.execute,
    preview.plan_token,
    click,
    approval,
    session_id="desktop_session_1",
) is not None and native.clicks == 1, "human approval and plan cannot be replayed")

print("proof failures stop before capture or token consumption:")
clock[0] = 1003.0
preview2 = planner.preview(click, initial, session_id="desktop_session_1", origin="local", now=clock[0])
approval2 = DesktopInputApproval(
    confirmation_id="confirm_click_2",
    plan_token_sha256=plan_token_sha256(preview2.plan_token),
    action_sha256=action_sha256(click),
    session_sha256=session_sha256("desktop_session_1"),
    issued_at_ms=1_003_000,
    expires_at_ms=1_020_000,
    nonce="approval_nonce_click_0002",
)
blocked = DesktopInputExecutionCoordinator(
    planner,
    active_backend,
    candidate_sha="a" * 40,
    physical_gate=gate,
    physical_gate_verifier=lambda _value: False,
    approval_verifier=lambda _value: True,
    clock=lambda: clock[0],
)
before_capture = native.capture_calls
check(denied(
    blocked.execute,
    preview2.plan_token,
    click,
    approval2,
    session_id="desktop_session_1",
) is not None and native.capture_calls == before_capture, "unverified physical evidence blocks before capture")
check(denied(
    coordinator.execute,
    preview2.plan_token,
    click,
    approval2,
    session_id="desktop_session_1",
    origin="cloud",
) is not None and native.capture_calls == before_capture, "cloud origin is refused before capture")
changed_click = DesktopAction(
    kind="click",
    screen_token=snapshot.screen_token,
    x=1,
    y=1,
    button="left",
)
check(denied(
    coordinator.execute,
    preview2.plan_token,
    changed_click,
    approval2,
    session_id="desktop_session_1",
) is not None and native.capture_calls == before_capture, "approval digest prevents coordinate changes before capture")

print("a changed desktop spends the human approval fail-closed:")
clock[0] = 1004.0
preview3 = planner.preview(click, initial, session_id="desktop_session_1", origin="local", now=clock[0])
approval3 = DesktopInputApproval(
    confirmation_id="confirm_click_3",
    plan_token_sha256=plan_token_sha256(preview3.plan_token),
    action_sha256=action_sha256(click),
    session_sha256=session_sha256("desktop_session_1"),
    issued_at_ms=1_004_000,
    expires_at_ms=1_020_000,
    nonce="approval_nonce_click_0003",
)
original_target = native.target
native.target = WindowTarget(
    hwnd=778,
    process="notepad.exe",
    title="Changed - Notepad",
    left=100,
    top=200,
    width=4,
    height=2,
)
check(denied(
    coordinator.execute,
    preview3.plan_token,
    click,
    approval3,
    session_id="desktop_session_1",
) is not None, "changed foreground identity blocks the signed plan")
native.target = original_target
before_capture = native.capture_calls
check(denied(
    coordinator.execute,
    preview3.plan_token,
    click,
    approval3,
    session_id="desktop_session_1",
) is not None and native.capture_calls == before_capture, "failed attempt cannot reuse the same human approval")

print("typed text is exact on input and redacted from receipt:")
clock[0] = 1005.0
fresh = active_backend.capture_foreground()
snapshot2 = guard.snapshot(fresh, session_id="desktop_session_1", origin="local", now=clock[0])
typed = "præcis hemmelig tekst"
type_action = DesktopAction(kind="type_text", screen_token=snapshot2.screen_token, text=typed)
type_preview = planner.preview(type_action, fresh, session_id="desktop_session_1", origin="local", now=clock[0])
type_approval = DesktopInputApproval(
    confirmation_id="confirm_type_1",
    plan_token_sha256=plan_token_sha256(type_preview.plan_token),
    action_sha256=action_sha256(type_action),
    session_sha256=session_sha256("desktop_session_1"),
    issued_at_ms=1_005_000,
    expires_at_ms=1_020_000,
    nonce="approval_nonce_type_00001",
)
type_receipt = coordinator.execute(
    type_preview.plan_token,
    type_action,
    type_approval,
    session_id="desktop_session_1",
).to_dict()
encoded_units = b"".join(unit.to_bytes(2, "little") for unit in native.units)
check(encoded_units.decode("utf-16-le") == typed, "the exact immutable Unicode text reaches the native adapter")
check(typed not in json.dumps(type_receipt, ensure_ascii=False), "plaintext typed text never enters the receipt")
check(type_receipt["text_chars"] == len(typed) and type_receipt["text_sha256"], "receipt retains bounded text evidence")

from app import tools as T  # noqa: E402
check("desktop_click" not in T.REGISTRY and "desktop_type" not in T.REGISTRY, "no click or type model tool is registered")
check(not hasattr(DesktopInputExecutionCoordinator, "register"), "execution boundary exposes no registration shortcut")

print(f"\n===== DESKTOP INPUT EXECUTION: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
