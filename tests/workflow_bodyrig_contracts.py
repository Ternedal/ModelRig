"""Contract tests for the BodyRig bootstrap.

Run: python3 tests/workflow_bodyrig_contracts.py
"""
from __future__ import annotations

from io import BytesIO
import math
import struct
import sys
import wave
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from bodyrig import (  # noqa: E402
    BodyprintValidationError,
    BodyRigRuntime,
    BodyState,
    EmbodimentScheduler,
    EventRejected,
    SchedulerError,
    TimingMode,
    VoiceRigContractError,
    timed_track,
    validate_manifest,
    wav_envelope_track,
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


def demo_wav(*, sample_rate: int = 24000, duration_ms: int = 240) -> bytes:
    """PCM16 mono fixture: silence followed by a deterministic voiced tone."""
    frames = round(sample_rate * duration_ms / 1000)
    samples = []
    for index in range(frames):
        t = index / sample_rate
        amplitude = 0 if index < sample_rate * 0.04 else 12000
        samples.append(int(amplitude * math.sin(2.0 * math.pi * 180.0 * t)))
    payload = b"".join(struct.pack("<h", sample) for sample in samples)
    buffer = BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(payload)
    return buffer.getvalue()


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
        "gaze": {"target": "user", "intensity": 0.8},
        "energy": 0.6,
    },
)
check(runtime.snapshot.active_gesture == "explain", "semantic gesture intent reaches runtime")
check(
    runtime.snapshot.gaze_target == "user"
    and runtime.snapshot.emotion == "amused"
    and runtime.snapshot.emotion_intensity == 0.4
    and runtime.snapshot.energy == 0.6,
    "expression plan retains renderer-neutral gaze, emotion and energy",
)

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

# VoiceRig RC25 compatibility: current endpoint returns complete WAV + metadata,
# not a phoneme/viseme timeline. The fallback must therefore be labelled as
# approximate audio-envelope timing rather than pretending precise lipsync.
wav_bytes = demo_wav()
envelope = wav_envelope_track(
    utterance_id="u_audio",
    wav_bytes=wav_bytes,
    headers={
        "X-VoiceRig-Sample-Rate": "24000",
        "X-VoiceRig-Duration": "0.240",
    },
)
check(envelope.mode == TimingMode.AUDIO_ENVELOPE, "VoiceRig WAV fallback is explicitly approximate")
check(
    envelope.sample_rate == 24000
    and 235 <= envelope.duration_ms <= 245
    and len(envelope.frames) >= 10,
    "VoiceRig WAV geometry becomes a bounded speech timeline",
)
check(
    max(frame.mouth_open for frame in envelope.frames) > 0.5
    and envelope.frames[0].mouth_open == 0.0,
    "audio envelope distinguishes silence from voiced energy",
)

try:
    wav_envelope_track(
        utterance_id="u_bad",
        wav_bytes=wav_bytes,
        headers={"X-VoiceRig-Sample-Rate": "16000"},
    )
except VoiceRigContractError:
    check(True, "VoiceRig metadata/WAV disagreement fails closed")
else:
    check(False, "VoiceRig metadata/WAV disagreement fails closed")

precise = timed_track(
    utterance_id="u_timed",
    duration_ms=300,
    sample_rate=24000,
    frames=[
        {"offset_ms": 0, "visemes": [{"id": "aa", "weight": 0.2}]},
        {"offset_ms": 100, "visemes": [{"id": "oh", "weight": 0.8}]},
        {"offset_ms": 200, "mouth_open": 0.1, "visemes": []},
    ],
)
check(
    precise.mode == TimingMode.TIMED
    and precise.sample(120).visemes == (("oh", 0.8),)
    and precise.sample(120).mouth_open == 0.8,
    "explicit upstream timing preserves precise viseme data",
)

# Headless scheduler: deterministic procedural motion + speech, while retaining
# the runtime's semantic boundary.
render_runtime = BodyRigRuntime(session_id="s_render", bodyprint_id="bp_test")
render_runtime.start_speech(sequence=1, utterance_id="u_audio")
render_runtime.apply_expression_plan(
    sequence=2,
    plan={
        "state": "speaking",
        "emotion": {"name": "curious", "intensity": 0.35},
        "gesture": {"intent": "explain", "intensity": 0.45},
        "gaze": {"target": "user", "intensity": 0.8},
        "energy": 0.5,
    },
)
scheduler = EmbodimentScheduler(session_id="s_render", bodyprint_id="bp_test")
scheduler.attach_speech(envelope, started_at_ms=1000)
frame_a = scheduler.render(render_runtime.snapshot, timestamp_ms=1140)
frame_b = scheduler.render(render_runtime.snapshot, timestamp_ms=1140)
check(frame_a == frame_b, "procedural scheduler is deterministic for identical session/time input")
check(
    frame_a.state == BodyState.SPEAKING
    and frame_a.gaze_target == "user"
    and frame_a.emotion == "curious"
    and frame_a.gesture == "explain",
    "scheduler preserves semantic state instead of renderer-specific controls",
)
check(
    0.0 <= frame_a.blink <= 1.0
    and 0.0 <= frame_a.breath <= 1.0
    and 0.0 <= frame_a.gaze_strength <= 1.0
    and frame_a.mouth_open > 0.0
    and frame_a.speech_timing_mode == TimingMode.AUDIO_ENVELOPE,
    "scheduler mixes bounded procedural motion with current VoiceRig speech",
)

scheduler.cancel_utterance("u_audio")
render_runtime.cancel(sequence=3, scope="utterance", utterance_id="u_audio")
after_cancel = scheduler.render(render_runtime.snapshot, timestamp_ms=1160)
check(
    after_cancel.state == BodyState.INTERRUPTED
    and after_cancel.mouth_open == 0.0
    and after_cancel.visemes == (),
    "scheduler cancellation releases mouth output immediately",
)
try:
    scheduler.attach_speech(envelope, started_at_ms=1200)
except SchedulerError:
    check(True, "scheduler cannot reattach a cancelled utterance")
else:
    check(False, "scheduler cannot reattach a cancelled utterance")

foreign_runtime = BodyRigRuntime(session_id="other", bodyprint_id="bp_test")
try:
    scheduler.render(foreign_runtime.snapshot, timestamp_ms=1200)
except SchedulerError:
    check(True, "scheduler rejects cross-session snapshot injection")
else:
    check(False, "scheduler rejects cross-session snapshot injection")

print(f"BodyRig contracts: {passed} passed, {failed} failed")
raise SystemExit(0 if failed == 0 else 1)
