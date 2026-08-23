"""Contract tests for the BodyRig bootstrap.

Run: python3 tests/bodyrig_contracts.py
"""
from __future__ import annotations

import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from bodyrig import (  # noqa: E402
    BodyprintValidationError,
    BodyRigRuntime,
    BodyState,
    EventRejected,
    validate_manifest,
)

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


manifest = {
    "format": "bodyrig.bodyprint",
    "version": "0.1.0",
    "id": "bp_test",
    "created_at": "2026-08-23T12:00:00Z",
    "display_name": "Test bodyprint",
    "capabilities": ["motion_style", "face_behavior", "gaze", "gestures"],
    "avatar": {"path": "avatar/avatar.vrm", "format": "vrm-1.0", "optional": True},
    "confidence": {
        "appearance": 0.7,
        "body_shape": 0.8,
        "motion": 0.9,
        "face_behavior": 0.8,
        "hands": 0.6,
        "gaze": 0.75,
    },
}
validate_manifest(manifest)
check(True, "valid bodyprint v0.1 manifest is accepted")

invalid = dict(manifest)
invalid["confidence"] = dict(manifest["confidence"])
invalid["confidence"]["motion"] = 1.1
try:
    validate_manifest(invalid)
except BodyprintValidationError:
    check(True, "confidence outside 0..1 fails closed")
else:
    check(False, "confidence outside 0..1 fails closed")

runtime = BodyRigRuntime(session_id="s_test", bodyprint_id="bp_test")
check(runtime.snapshot.state == BodyState.IDLE, "runtime starts idle")

runtime.apply_state(sequence=1, state="listening")
check(runtime.snapshot.state == BodyState.LISTENING, "runtime enters listening")

runtime.apply_state(sequence=2, state="thinking")
check(runtime.snapshot.state == BodyState.THINKING, "runtime enters thinking")

runtime.start_speech(sequence=3, utterance_id="u_1")
check(
    runtime.snapshot.state == BodyState.SPEAKING
    and runtime.snapshot.active_utterance_id == "u_1",
    "speech start activates utterance and speaking state",
)

accepted = runtime.accept_speech_frame(sequence=4, utterance_id="u_1")
check(accepted, "active utterance accepts streaming viseme/prosody frame")

runtime.apply_expression_plan(
    sequence=5,
    plan={
        "state": "speaking",
        "emotion": {"name": "amused", "intensity": 0.4},
        "gesture": {"intent": "explain", "intensity": 0.5, "optional": True},
        "gaze": {"target": "user"},
    },
)
check(runtime.snapshot.active_gesture == "explain", "semantic gesture intent reaches runtime")

runtime.cancel(sequence=6, scope="utterance", utterance_id="u_1")
check(
    runtime.snapshot.state == BodyState.INTERRUPTED
    and runtime.snapshot.active_utterance_id is None
    and runtime.snapshot.active_gesture is None,
    "utterance cancellation clears speech and gesture and enters interrupted",
)

accepted = runtime.accept_speech_frame(sequence=7, utterance_id="u_1")
check(not accepted, "queued frame from cancelled utterance cannot reactivate speech")

try:
    runtime.start_speech(sequence=8, utterance_id="u_1")
except EventRejected:
    check(True, "cancelled utterance id cannot be restarted")
else:
    check(False, "cancelled utterance id cannot be restarted")

runtime.apply_state(sequence=9, state="listening")
check(runtime.snapshot.state == BodyState.LISTENING, "interrupted runtime returns cleanly to listening")

try:
    runtime.apply_state(sequence=8, state="thinking")
except EventRejected:
    check(True, "stale/out-of-order event is rejected")
else:
    check(False, "stale/out-of-order event is rejected")

runtime.set_health(sequence=10, health="error")
check(
    runtime.snapshot.health == "error" and runtime.snapshot.state == BodyState.ERROR,
    "runtime health error forces visible error state",
)

print(f"BodyRig contracts: {passed} passed, {failed} failed")
raise SystemExit(0 if failed == 0 else 1)
