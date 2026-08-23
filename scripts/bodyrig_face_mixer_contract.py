#!/usr/bin/env python3
"""Dependency-free contract proof for BodyRig M2.2 personalized face mixing."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bodyrig.face_behavior import build_face_behavior  # noqa: E402
from bodyrig.face_mixer import FaceBehaviorMixer, FaceMixerError  # noqa: E402
from bodyrig.runtime import BodyRigRuntime  # noqa: E402
from bodyrig.scheduler import EmbodimentScheduler, SchedulerError  # noqa: E402
from bodyrig.tracking import COORDINATE_SPACE, SCHEMA as TRACKING_SCHEMA  # noqa: E402
from bodyrig.voicerig_adapter import timed_track  # noqa: E402

passed = failed = 0


def check(ok: bool, label: str) -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def face_point() -> dict:
    return {"x": 0.5, "y": 0.4, "z": 0.0, "confidence": 0.9}


def tracking_fixture(
    name: str,
    *,
    smile: float | None,
    left_blinks: set[int],
    right_blinks: set[int],
    jaw: float | None = 0.2,
) -> dict:
    frames = []
    for index in range(21):
        expressions: dict[str, float] = {
            "blink_left": 0.9 if index in left_blinks else 0.0,
            "blink_right": 0.9 if index in right_blinks else 0.0,
        }
        if smile is not None:
            expressions["mouth_smile_left"] = smile
            expressions["mouth_smile_right"] = smile
            expressions["mouth_frown_left"] = 0.05
            expressions["mouth_frown_right"] = 0.05
            expressions["brow_inner_up"] = 0.1
            expressions["brow_down_left"] = 0.05
            expressions["brow_down_right"] = 0.05
        if jaw is not None:
            expressions["jaw_open"] = jaw
        frames.append(
            {
                "timestamp_us": index * 500_000,
                "body": None,
                "left_hand": None,
                "right_hand": None,
                "face": {"nose_tip": face_point()},
                "expressions": expressions,
            }
        )
    count = len(frames)
    return {
        "schema": TRACKING_SCHEMA,
        "coordinate_space": COORDINATE_SPACE,
        "source": {
            "sha256": hashlib.sha256(name.encode("utf-8")).hexdigest(),
            "bytes": 12345,
            "permission_assertion": "synthetic licensed fixture",
            "media": {
                "codec": "h264",
                "width": 640,
                "height": 360,
                "duration_us": 10_000_000,
                "nominal_fps": 2.0,
            },
        },
        "backend": {
            "id": "synthetic-face-mixer",
            "version": "1.0.0",
            "model_revision": "fixture-v1",
        },
        "frames": frames,
        "coverage": {
            "body": {
                "observed_frames": 0,
                "total_frames": count,
                "coverage": 0.0,
                "confidence_frames": 0,
                "mean_confidence": 0.0,
            },
            "hands": {
                "observed_frames": 0,
                "total_frames": count,
                "coverage": 0.0,
                "confidence_frames": 0,
                "mean_confidence": 0.0,
            },
            "face": {
                "observed_frames": count,
                "total_frames": count,
                "coverage": 1.0,
                "confidence_frames": count,
                "mean_confidence": 0.9,
            },
        },
        "recommendations": ["need_more_full_body", "more_visible_hands"],
        "production_activation": False,
    }


def runtime_for(*, session: str, emotion: str, intensity: float, state: str = "idle") -> BodyRigRuntime:
    runtime = BodyRigRuntime(session_id=session, bodyprint_id="bp-face")
    runtime.apply_expression_plan(
        sequence=1,
        plan={
            "state": state,
            "emotion": {"name": emotion, "intensity": intensity},
            "energy": 0.5,
        },
    )
    return runtime


low_profile = build_face_behavior(
    tracking_fixture(
        "low-smile-low-blink",
        smile=0.0,
        left_blinks={5},
        right_blinks={5},
    )
)
high_profile = build_face_behavior(
    tracking_fixture(
        "high-smile-fast-asymmetric-blink",
        smile=1.0,
        left_blinks={1, 3, 5, 7, 9, 11, 13, 15, 17, 19},
        right_blinks={2, 6, 10, 14, 18},
    )
)
missing_smile_profile = build_face_behavior(
    tracking_fixture(
        "missing-smile",
        smile=None,
        jaw=None,
        left_blinks={5},
        right_blinks={5},
    )
)
zero_blink_profile = build_face_behavior(
    tracking_fixture(
        "zero-blink",
        smile=0.4,
        left_blinks=set(),
        right_blinks=set(),
    )
)

low_mixer = FaceBehaviorMixer(
    session_id="s-face",
    bodyprint_id="bp-face",
    face_behavior=low_profile,
)
high_mixer = FaceBehaviorMixer(
    session_id="s-face",
    bodyprint_id="bp-face",
    face_behavior=high_profile,
)
missing_mixer = FaceBehaviorMixer(
    session_id="s-face",
    bodyprint_id="bp-face",
    face_behavior=missing_smile_profile,
)
zero_blink_mixer = FaceBehaviorMixer(
    session_id="s-face",
    bodyprint_id="bp-face",
    face_behavior=zero_blink_profile,
)
generic_mixer = FaceBehaviorMixer(session_id="s-face", bodyprint_id="bp-face")

amused = runtime_for(session="s-face", emotion="amused", intensity=0.8)
low_frame = low_mixer.render(amused.snapshot, timestamp_ms=1234)
high_frame = high_mixer.render(amused.snapshot, timestamp_ms=1234)
missing_frame = missing_mixer.render(amused.snapshot, timestamp_ms=1234)

check(low_frame.profile_id == low_profile["id"], "runtime frame binds the validated M2.1 profile id")
check(
    high_frame.value("smile") > low_frame.value("smile"),
    "same semantic emotion yields different output for distinct source smile priors",
)
check(
    missing_frame.source("smile") == "semantic",
    "missing smile prior uses explicit generic semantic fallback",
)
check(
    low_frame.source("smile") == "profile_semantic" and low_frame.value("smile") < missing_frame.value("smile"),
    "observed zero smile remains distinct from missing evidence",
)
check(
    high_mixer.blink_period_ms("left") < low_mixer.blink_period_ms("left"),
    "higher observed blink rate produces shorter deterministic cadence",
)
check(
    high_mixer.blink_period_ms("left") < high_mixer.blink_period_ms("right"),
    "left/right observed blink-rate differences remain independently observable",
)
check(
    high_mixer.blink_source("left") == "profile" and high_mixer.blink_source("right") == "profile",
    "profile-derived blink cadence is explicitly labelled",
)
check(
    missing_mixer.blink_source("left") == "profile",
    "missing expression priors do not erase independently observed blink evidence",
)
check(
    zero_blink_mixer.blink_period_ms("left") is None,
    "observed zero blink rate remains a source-specific zero cadence",
)
check(
    generic_mixer.blink_period_ms("left") is not None and generic_mixer.blink_source("left") == "generic",
    "missing blink profile uses deterministic generic fallback instead of source-specific zero",
)

repeat = high_mixer.render(amused.snapshot, timestamp_ms=1234)
check(repeat == high_frame, "same session/profile/state/time is dataclass-equivalent and deterministic")
check(
    all(0.0 <= channel.value <= 1.0 for channel in high_frame.channels),
    "all renderer-neutral facial channels remain bounded",
)
check(
    all(term not in channel.name.lower() for channel in high_frame.channels for term in ("vrm", "blendshape", "morph")),
    "M2.2 emits no renderer-specific VRM/blendshape/morph identifiers",
)

speaking = runtime_for(session="s-face", emotion="surprised", intensity=1.0, state="speaking")
speech_frame = high_mixer.render(speaking.snapshot, timestamp_ms=1300, speech_mouth_open=0.73)
check(
    speech_frame.value("jaw_open") == 0.73 and speech_frame.source("jaw_open") == "speech",
    "VoiceRig mouth timing is authoritative over source/semantic jaw tendency while speaking",
)

surprised_idle = runtime_for(session="s-face", emotion="surprised", intensity=1.0)
idle_face = high_mixer.render(surprised_idle.snapshot, timestamp_ms=1300, speech_mouth_open=0.99)
check(
    idle_face.source("jaw_open") == "profile_semantic" and idle_face.value("jaw_open") != 0.99,
    "non-speaking runtime cannot be driven by stale speech mouth input",
)

foreign = runtime_for(session="other-session", emotion="amused", intensity=0.8)
try:
    high_mixer.render(foreign.snapshot, timestamp_ms=1)
except FaceMixerError:
    check(True, "face mixer rejects cross-session snapshot injection")
else:
    check(False, "face mixer rejects cross-session snapshot injection")

mutated = copy.deepcopy(high_profile)
mutated["expression_priors"]["smile"]["mean"] = 0.5
try:
    FaceBehaviorMixer(
        session_id="s-face",
        bodyprint_id="bp-face",
        face_behavior=mutated,
    )
except FaceMixerError:
    check(True, "tampered M2.1 content-addressed profile fails closed before runtime use")
else:
    check(False, "tampered M2.1 content-addressed profile fails closed before runtime use")

# Scheduler integration is optional. No profile must preserve the old generic
# surface; with a profile it exposes additional renderer-neutral face channels.
generic_scheduler = EmbodimentScheduler(session_id="s-face", bodyprint_id="bp-face")
generic_render = generic_scheduler.render(amused.snapshot, timestamp_ms=1234)
check(
    generic_render.face_profile_id is None
    and generic_render.face_channels == ()
    and generic_render.face_channel_sources == (),
    "scheduler without M2.1 profile preserves backward-compatible generic surface",
)
check(
    generic_render.blink
    == max(
        generic_mixer.render(amused.snapshot, timestamp_ms=1234).value("blink_left"),
        generic_mixer.render(amused.snapshot, timestamp_ms=1234).value("blink_right"),
    ),
    "generic scheduler blink cadence remains byte-for-byte equivalent to M2.2 generic fallback",
)

personal_scheduler = EmbodimentScheduler(
    session_id="s-face",
    bodyprint_id="bp-face",
    face_behavior=high_profile,
)
personal_render = personal_scheduler.render(amused.snapshot, timestamp_ms=1234)
channel_map = dict(personal_render.face_channels)
source_map = dict(personal_render.face_channel_sources)
check(
    personal_render.face_profile_id == high_profile["id"]
    and channel_map["smile"] == high_frame.value("smile")
    and source_map["smile"] == "profile_semantic",
    "scheduler exposes personalized renderer-neutral face channels from M2.1",
)

speech_runtime = BodyRigRuntime(session_id="s-speech", bodyprint_id="bp-face")
speech_runtime.start_speech(sequence=1, utterance_id="u-1")
speech_runtime.apply_expression_plan(
    sequence=2,
    plan={
        "state": "speaking",
        "emotion": {"name": "amused", "intensity": 0.4},
        "energy": 0.5,
    },
)
track = timed_track(
    utterance_id="u-1",
    duration_ms=400,
    sample_rate=24000,
    frames=[
        {"offset_ms": 0, "mouth_open": 0.15, "visemes": []},
        {"offset_ms": 100, "mouth_open": 0.82, "visemes": [{"id": "oh", "weight": 0.82}]},
        {"offset_ms": 300, "mouth_open": 0.10, "visemes": []},
    ],
)
speech_scheduler = EmbodimentScheduler(
    session_id="s-speech",
    bodyprint_id="bp-face",
    face_behavior=high_profile,
)
speech_scheduler.attach_speech(track, started_at_ms=1000)
during = speech_scheduler.render(speech_runtime.snapshot, timestamp_ms=1120)
during_channels = dict(during.face_channels)
during_sources = dict(during.face_channel_sources)
check(
    during.mouth_open == 0.82
    and during_channels["jaw_open"] == 0.82
    and during_sources["jaw_open"] == "speech",
    "scheduler keeps VoiceRig timed mouth output authoritative in personalized face mix",
)

speech_scheduler.cancel_utterance("u-1")
speech_runtime.cancel(sequence=3, scope="utterance", utterance_id="u-1")
after_cancel = speech_scheduler.render(speech_runtime.snapshot, timestamp_ms=1140)
after_channels = dict(after_cancel.face_channels)
after_sources = dict(after_cancel.face_channel_sources)
check(
    after_cancel.mouth_open == 0.0
    and after_channels["jaw_open"] == 0.0
    and after_sources["jaw_open"] != "speech",
    "speech cancellation immediately releases speech-driven mouth/jaw output",
)

try:
    EmbodimentScheduler(
        session_id="s-bad",
        bodyprint_id="bp-face",
        face_behavior=mutated,
    )
except SchedulerError:
    check(True, "scheduler rejects tampered M2.1 profile before rendering")
else:
    check(False, "scheduler rejects tampered M2.1 profile before rendering")

print(f"\n===== BODYRIG M2.2 FACE MIXER: {passed} passed, {failed} failed =====")
if failed:
    raise SystemExit(1)
