from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence

Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class RecoveryFrame:
    timestamp_ms: int
    joints: Mapping[str, Vec3]
    confidence: float = 1.0


@dataclass(frozen=True)
class RecoveredTrack:
    track_id: str
    frames: Sequence[RecoveryFrame]


@dataclass(frozen=True)
class RecoveryResult:
    tracks: Sequence[RecoveredTrack]
    adapter: str
    revision: str


class RecoveryAdapter(Protocol):
    name: str
    revision: str

    def recover(self, sources: Sequence[Path]) -> RecoveryResult: ...


class RecoveryError(RuntimeError):
    pass


def _finite_vec(value: object, field: str) -> Vec3:
    if not isinstance(value, list) or len(value) != 3:
        raise RecoveryError(f"{field}: expected [x,y,z]")
    out = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            raise RecoveryError(f"{field}: coordinates must be finite numbers")
        out.append(float(item))
    return out[0], out[1], out[2]


def parse_recovery_result(payload: object, *, expected_adapter: str | None = None) -> RecoveryResult:
    if not isinstance(payload, dict):
        raise RecoveryError("recovery result must be an object")
    if set(payload) != {"format", "version", "adapter", "revision", "tracks"}:
        raise RecoveryError("recovery result fields must match v1 exactly")
    if payload["format"] != "bodyrig-recovery" or payload["version"] != 1:
        raise RecoveryError("unsupported recovery format/version")
    adapter = payload["adapter"]
    revision = payload["revision"]
    if not isinstance(adapter, str) or not adapter or len(adapter) > 80:
        raise RecoveryError("invalid adapter id")
    if expected_adapter is not None and adapter != expected_adapter:
        raise RecoveryError("adapter identity mismatch")
    if not isinstance(revision, str) or len(revision) > 160 or not revision:
        raise RecoveryError("invalid adapter revision")

    raw_tracks = payload["tracks"]
    if not isinstance(raw_tracks, list) or not 1 <= len(raw_tracks) <= 64:
        raise RecoveryError("tracks must contain 1..64 tracks")
    tracks: list[RecoveredTrack] = []
    ids: set[str] = set()
    for track_index, raw_track in enumerate(raw_tracks):
        if not isinstance(raw_track, dict) or set(raw_track) != {"track_id", "frames"}:
            raise RecoveryError(f"tracks[{track_index}]: invalid object")
        track_id = raw_track["track_id"]
        if not isinstance(track_id, str) or not track_id or len(track_id) > 160:
            raise RecoveryError(f"tracks[{track_index}]: invalid track_id")
        if track_id in ids:
            raise RecoveryError("duplicate track_id")
        ids.add(track_id)
        raw_frames = raw_track["frames"]
        if not isinstance(raw_frames, list) or not 2 <= len(raw_frames) <= 1_000_000:
            raise RecoveryError(f"tracks[{track_index}]: frames must contain at least two frames")
        frames: list[RecoveryFrame] = []
        previous_ts = -1
        for frame_index, raw_frame in enumerate(raw_frames):
            if not isinstance(raw_frame, dict) or set(raw_frame) - {"timestamp_ms", "confidence", "joints"} or not {"timestamp_ms", "joints"} <= set(raw_frame):
                raise RecoveryError(f"tracks[{track_index}].frames[{frame_index}]: invalid object")
            timestamp = raw_frame["timestamp_ms"]
            if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0 or timestamp <= previous_ts:
                raise RecoveryError(f"tracks[{track_index}]: timestamps must be strictly increasing non-negative integers")
            previous_ts = timestamp
            confidence = raw_frame.get("confidence", 1.0)
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(float(confidence)) or not 0.0 <= float(confidence) <= 1.0:
                raise RecoveryError(f"tracks[{track_index}].frames[{frame_index}]: invalid confidence")
            raw_joints = raw_frame["joints"]
            if not isinstance(raw_joints, dict) or not raw_joints or len(raw_joints) > 256:
                raise RecoveryError(f"tracks[{track_index}].frames[{frame_index}]: invalid joints")
            joints: dict[str, Vec3] = {}
            for joint_name, point in raw_joints.items():
                if not isinstance(joint_name, str) or not joint_name or len(joint_name) > 80:
                    raise RecoveryError("invalid joint name")
                joints[joint_name] = _finite_vec(point, f"joint {joint_name}")
            frames.append(RecoveryFrame(timestamp_ms=timestamp, joints=joints, confidence=float(confidence)))
        tracks.append(RecoveredTrack(track_id=track_id, frames=tuple(frames)))
    return RecoveryResult(tracks=tuple(tracks), adapter=adapter, revision=revision)


class JsonCommandRecoveryAdapter:
    """Runs a recovery engine in a separate process/environment.

    The command receives a JSON request on stdin and must return the canonical
    BodyRig recovery v1 JSON on stdout. This keeps HMR2/SMPL-family runtime and
    licensing dependencies outside the stable BodyRig service environment.
    """

    def __init__(self, command: Sequence[str], *, name: str, revision: str, timeout_seconds: int = 3600) -> None:
        if not command:
            raise ValueError("command is required")
        self.command = tuple(command)
        self.name = name
        self.revision = revision
        self.timeout_seconds = timeout_seconds

    def recover(self, sources: Sequence[Path]) -> RecoveryResult:
        if not 1 <= len(sources) <= 10:
            raise RecoveryError("BodyRig V1 accepts 1..10 source clips")
        request = {
            "format": "bodyrig-recovery-request",
            "version": 1,
            "sources": [str(path.resolve()) for path in sources],
        }
        try:
            completed = subprocess.run(
                self.command,
                input=json.dumps(request),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RecoveryError("recovery adapter failed to execute") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip()[-2000:]
            raise RecoveryError(f"recovery adapter exited {completed.returncode}: {detail}")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RecoveryError("recovery adapter returned invalid JSON") from exc
        result = parse_recovery_result(payload, expected_adapter=self.name)
        if result.revision != self.revision:
            raise RecoveryError("recovery adapter revision mismatch")
        return result


def _distance(a: Vec3, b: Vec3) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _midpoint(a: Vec3, b: Vec3) -> Vec3:
    return tuple((a[i] + b[i]) / 2.0 for i in range(3))  # type: ignore[return-value]


def _angle_xy(a: Vec3, b: Vec3) -> float:
    return math.atan2(b[1] - a[1], b[0] - a[0])


def _wrap_angle(delta: float) -> float:
    while delta > math.pi:
        delta -= 2 * math.pi
    while delta < -math.pi:
        delta += 2 * math.pi
    return delta


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


class BodyprintExtractor:
    """Extracts portable, model-neutral observed body/motion metrics from joints."""

    SHAPE_JOINTS = {
        "head",
        "left_shoulder",
        "right_shoulder",
        "left_hip",
        "right_hip",
        "left_wrist",
        "right_wrist",
        "left_ankle",
        "right_ankle",
    }

    def extract(self, track: RecoveredTrack) -> dict:
        if len(track.frames) < 2:
            raise RecoveryError("track needs at least two frames")
        bodyprint: dict = {"format": "modelrig-bodyprint", "version": 1}
        shape = self._shape(track)
        motion = self._motion(track)
        if shape:
            bodyprint["shape"] = shape
        if motion:
            bodyprint["motion"] = motion
        if len(bodyprint) == 2:
            raise RecoveryError("track contains insufficient joints for a bodyprint")
        return bodyprint

    def _shape(self, track: RecoveredTrack) -> dict[str, float]:
        samples = []
        for frame in track.frames:
            if frame.confidence < 0.5 or not self.SHAPE_JOINTS <= set(frame.joints):
                continue
            j = frame.joints
            ankle_mid = _midpoint(j["left_ankle"], j["right_ankle"])
            height = _distance(j["head"], ankle_mid)
            if height <= 1e-6:
                continue
            shoulder = _distance(j["left_shoulder"], j["right_shoulder"]) / height
            hip = _distance(j["left_hip"], j["right_hip"]) / height
            arm = (
                _distance(j["left_shoulder"], j["left_wrist"])
                + _distance(j["right_shoulder"], j["right_wrist"])
            ) / (2.0 * height)
            hip_mid = _midpoint(j["left_hip"], j["right_hip"])
            leg = (
                _distance(hip_mid, j["left_ankle"])
                + _distance(hip_mid, j["right_ankle"])
            ) / (2.0 * height)
            samples.append((shoulder, hip, arm, leg))
        if not samples:
            return {}
        samples.sort(key=lambda x: sum(x))
        middle = samples[len(samples) // 2]
        return {
            "shoulder_to_height": _clamp01(middle[0]),
            "hip_to_height": _clamp01(middle[1]),
            "arm_to_height": _clamp01(middle[2]),
            "leg_to_height": _clamp01(middle[3]),
        }

    def _motion(self, track: RecoveredTrack) -> dict[str, float]:
        velocity_samples: list[float] = []
        head_samples: list[float] = []
        wrist_amplitudes: list[float] = []
        shoulder_turn_rates: list[float] = []
        gesture_events = 0
        gesture_active = False
        usable_duration_ms = 0

        for prev, curr in zip(track.frames, track.frames[1:]):
            dt = (curr.timestamp_ms - prev.timestamp_ms) / 1000.0
            if dt <= 0:
                continue
            shared = set(prev.joints) & set(curr.joints)
            if not shared:
                continue
            height = self._frame_height(curr)
            if height is None or height <= 1e-6:
                continue
            usable_duration_ms += curr.timestamp_ms - prev.timestamp_ms
            speeds = [_distance(prev.joints[name], curr.joints[name]) / dt / height for name in shared]
            velocity_samples.append(sum(speeds) / len(speeds))

            if "head" in shared:
                head_samples.append(_distance(prev.joints["head"], curr.joints["head"]) / dt / height)

            wrists = []
            if {"left_wrist", "left_shoulder", "right_shoulder"} <= set(curr.joints):
                shoulder_mid = _midpoint(curr.joints["left_shoulder"], curr.joints["right_shoulder"])
                wrists.append(_distance(curr.joints["left_wrist"], shoulder_mid) / height)
            if {"right_wrist", "left_shoulder", "right_shoulder"} <= set(curr.joints):
                shoulder_mid = _midpoint(curr.joints["left_shoulder"], curr.joints["right_shoulder"])
                wrists.append(_distance(curr.joints["right_wrist"], shoulder_mid) / height)
            if wrists:
                amplitude = sum(wrists) / len(wrists)
                wrist_amplitudes.append(amplitude)
                active = amplitude > 0.35 and (velocity_samples[-1] if velocity_samples else 0.0) > 0.15
                if active and not gesture_active:
                    gesture_events += 1
                gesture_active = active

            if {"left_shoulder", "right_shoulder"} <= shared:
                prev_angle = _angle_xy(prev.joints["left_shoulder"], prev.joints["right_shoulder"])
                curr_angle = _angle_xy(curr.joints["left_shoulder"], curr.joints["right_shoulder"])
                shoulder_turn_rates.append(abs(_wrap_angle(curr_angle - prev_angle)) / dt)

        result: dict[str, float] = {}
        if velocity_samples:
            result["energy"] = _clamp01(sum(velocity_samples) / len(velocity_samples))
        if wrist_amplitudes:
            result["gesture_amplitude"] = _clamp01((sum(wrist_amplitudes) / len(wrist_amplitudes)) / 0.75)
        if usable_duration_ms >= 1000:
            per_second = gesture_events / (usable_duration_ms / 1000.0)
            result["gesture_frequency"] = _clamp01(per_second / 1.5)
        if head_samples:
            result["head_motion"] = _clamp01((sum(head_samples) / len(head_samples)) / 0.5)
        if shoulder_turn_rates:
            avg_radians_second = sum(shoulder_turn_rates) / len(shoulder_turn_rates)
            result["turn_speed"] = _clamp01(avg_radians_second / math.pi)
        return result

    @staticmethod
    def _frame_height(frame: RecoveryFrame) -> float | None:
        required = {"head", "left_ankle", "right_ankle"}
        if not required <= set(frame.joints):
            return None
        ankle_mid = _midpoint(frame.joints["left_ankle"], frame.joints["right_ankle"])
        return _distance(frame.joints["head"], ankle_mid)
