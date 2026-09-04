"""Contract tests for the BodyRig bootstrap.

Run: python3 tests/workflow_bodyrig_contracts.py
"""
from __future__ import annotations

from io import BytesIO
import hashlib
import json
import math
import struct
import sys
import tempfile
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
from bodyrig.tracking import (  # noqa: E402
    BackendFrame,
    Landmark,
    MediaFacts,
    TrackingContractError,
    build_tracking_timeline,
    canonical_tracking_json,
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

# ---------------------------------------------------------------------------
# M1.1 video tracking contract. Tiny source bytes + deterministic fake backend;
# this proves the stable normalized boundary without pulling an ML model into CI.
# ---------------------------------------------------------------------------
def track_lm(x: float, y: float, confidence: float = 0.9, z: float = 0.0) -> Landmark:
    return Landmark(x=x, y=y, z=z, confidence=confidence)


class FakeTrackingBackend:
    backend_id = "fixture-tracker"
    backend_version = "1.0"
    model_revision = "fixture-r1"

    def __init__(self, frames: list[BackendFrame]) -> None:
        self.frames = tuple(frames)
        self.inspect_calls: list[str] = []
        self.extract_calls: list[str] = []

    def inspect(self, source_path) -> MediaFacts:
        self.inspect_calls.append(Path(source_path).name)
        return MediaFacts("h264", 1920, 1080, 1_000_000, 30.0)

    def extract(self, source_path):
        self.extract_calls.append(Path(source_path).name)
        return iter(self.frames)


class MutatingTrackingBackend(FakeTrackingBackend):
    def inspect(self, source_path) -> MediaFacts:
        facts = super().inspect(source_path)
        Path(source_path).write_bytes(b"different-source-bytes")
        return facts


class ReplacingTrackingBackend(FakeTrackingBackend):
    def extract(self, source_path):
        path = Path(source_path)
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(b"replacement-source-bytes")
        replacement.replace(path)
        return super().extract(source_path)


full_track_frame = BackendFrame(
    timestamp_us=0,
    body={
        "left_shoulder": track_lm(0.4, 0.3, 0.94),
        "right_shoulder": track_lm(0.6, 0.3, 0.92),
        "left_hip": track_lm(0.45, 0.65, 0.91),
        "right_hip": track_lm(0.55, 0.65, 0.90),
    },
    left_hand={"wrist": track_lm(0.35, 0.55, 0.82), "index_tip": track_lm(0.31, 0.48, 0.78)},
    right_hand={"wrist": track_lm(0.65, 0.55, 0.84), "index_tip": track_lm(0.69, 0.48, 0.80)},
    face={"nose_tip": track_lm(0.5, 0.18, 0.96), "mouth_left": track_lm(0.47, 0.23, 0.93)},
    expressions={"jaw_open": 0.2, "blink_left": 0.0, "blink_right": 0.0},
)
body_only_track_frame = BackendFrame(
    timestamp_us=33333,
    body={
        "left_shoulder": track_lm(0.41, 0.3, 0.88),
        "right_shoulder": track_lm(0.61, 0.3, 0.87),
    },
)
loss_track_frame = BackendFrame(timestamp_us=66666)
expression_track_frame = BackendFrame(
    timestamp_us=99999,
    expressions={"jaw_open": 0.6, "blink_left": 0.1},
)

with tempfile.TemporaryDirectory(prefix="bodyrig-m11-") as td:
    td_path = Path(td)
    first = td_path / "subject-a.mp4"
    second = td_path / "subject-b.mp4"
    first.write_bytes(b"synthetic-mp4-h264-a")
    second.write_bytes(b"synthetic-mp4-h264-b")

    tracking_backend = FakeTrackingBackend([
        full_track_frame, body_only_track_frame, loss_track_frame, expression_track_frame
    ])
    timeline = build_tracking_timeline(
        first,
        backend=tracking_backend,
        permission_assertion="user-supplied local source with permission",
    )
    check(timeline["schema"] == "bodyrig.tracking/v1", "M1.1 tracking schema id is stable")
    check(timeline["source"]["sha256"] == hashlib.sha256(first.read_bytes()).hexdigest(),
          "tracking provenance binds exact source bytes")
    serialized = canonical_tracking_json(timeline)
    check(str(first) not in serialized and first.name not in serialized,
          "tracking receipt does not leak source path/name")
    check([frame["timestamp_us"] for frame in timeline["frames"]] == [0, 33333, 99999],
          "total detection loss produces a truthful timeline gap")
    check(timeline["coverage"]["body"]["coverage"] == 0.5,
          "detection-loss frame still counts against body coverage")
    check(timeline["coverage"]["hands"]["coverage"] == 0.25,
          "hand coverage degrades independently")
    check(timeline["coverage"]["face"]["coverage"] == 0.5
          and timeline["coverage"]["face"]["confidence_frames"] == 1,
          "expression-only face presence does not fabricate detector confidence")
    check(timeline["production_activation"] is False,
          "M1.1 contract cannot activate BodyRig production")

    reordered = BackendFrame(
        timestamp_us=0,
        body={
            "right_hip": track_lm(0.55, 0.65, 0.90),
            "left_hip": track_lm(0.45, 0.65, 0.91),
            "right_shoulder": track_lm(0.6, 0.3, 0.92),
            "left_shoulder": track_lm(0.4, 0.3, 0.94),
        },
        right_hand={"index_tip": track_lm(0.69, 0.48, 0.80), "wrist": track_lm(0.65, 0.55, 0.84)},
        left_hand={"index_tip": track_lm(0.31, 0.48, 0.78), "wrist": track_lm(0.35, 0.55, 0.82)},
        face={"mouth_left": track_lm(0.47, 0.23, 0.93), "nose_tip": track_lm(0.5, 0.18, 0.96)},
        expressions={"blink_right": 0.0, "blink_left": 0.0, "jaw_open": 0.2},
    )
    one_a = build_tracking_timeline(first, backend=FakeTrackingBackend([full_track_frame]), permission_assertion="ok")
    one_b = build_tracking_timeline(first, backend=FakeTrackingBackend([reordered]), permission_assertion="ok")
    check(canonical_tracking_json(one_a) == canonical_tracking_json(one_b),
          "normalized tracking serialization is deterministic")

    second_timeline = build_tracking_timeline(second, backend=tracking_backend, permission_assertion="ok")
    check(second_timeline["source"]["sha256"] != timeline["source"]["sha256"],
          "separate tracking jobs have separate source identity")
    check(timeline["source"]["sha256"] not in canonical_tracking_json(second_timeline),
          "tracking jobs do not leak previous source identity")

    try:
        build_tracking_timeline(
            first,
            backend=FakeTrackingBackend([
                BackendFrame(timestamp_us=0, body={"engine_joint_42": track_lm(0.5, 0.5)})
            ]),
            permission_assertion="ok",
        )
    except TrackingContractError:
        check(True, "extractor-native landmark ids fail closed")
    else:
        check(False, "extractor-native landmark ids fail closed")

    first.write_bytes(b"original-source-bytes")
    try:
        build_tracking_timeline(
            first,
            backend=MutatingTrackingBackend([full_track_frame]),
            permission_assertion="ok",
        )
    except TrackingContractError:
        check(True, "source byte mutation during extraction invalidates provenance")
    else:
        check(False, "source byte mutation during extraction invalidates provenance")

    first.write_bytes(b"original-source-bytes")
    try:
        build_tracking_timeline(
            first,
            backend=ReplacingTrackingBackend([full_track_frame]),
            permission_assertion="ok",
        )
    except TrackingContractError:
        check(True, "source path replacement during extraction invalidates provenance")
    else:
        check(False, "source path replacement during extraction invalidates provenance")

schema = json.loads((root / "docs/bodyrig/schemas/tracking.schema.json").read_text("utf-8"))
defs = schema["$defs"]
body_ids = set(defs["body_landmarks"]["propertyNames"]["enum"])
hand_ids = set(defs["hand_landmarks"]["propertyNames"]["enum"])
face_ids = set(defs["face_landmarks"]["propertyNames"]["enum"])
expression_ids = set(defs["expressions"]["propertyNames"]["enum"])
check("engine_joint_42" not in body_ids | hand_ids | face_ids,
      "JSON schema rejects extractor-native landmark ids")
check("nose" in body_ids and "index_tip" not in body_ids,
      "JSON schema keeps body ids distinct from hand ids")
check("index_tip" in hand_ids and "nose_tip" not in hand_ids,
      "JSON schema keeps hand ids distinct from face ids")
check("nose_tip" in face_ids and "jaw_open" not in face_ids,
      "JSON schema keeps face geometry distinct from expression coefficients")
check("jaw_open" in expression_ids,
      "JSON schema pins canonical expression coefficients")

print(f"BodyRig contracts: {passed} passed, {failed} failed")
raise SystemExit(0 if failed == 0 else 1)
