"""BodyRig test fixtures for worker tests: a minimal valid VRM 1.0 GLB, a
1x1 PNG and the tracking fixture an identity bundle is built from.

Copied from scripts/bodyrig_profile_store_contract.py rather than imported:
that script is a self-running contract and executes on import.
"""

from __future__ import annotations

import binascii
import struct
import sys
import zlib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bodyrig.tracking import COORDINATE_SPACE, SCHEMA as TRACKING_SCHEMA  # noqa: E402
import hashlib
import json


def point(x: float, y: float, z: float = 0.0, confidence: float = 0.9) -> dict:
    return {"x": x, "y": y, "z": z, "confidence": confidence}


def tracking_fixture(source_name: str = "private-profile-store-source.mov") -> dict:
    frames = []
    for index in range(8):
        ts = index * 100_000
        swing = 0.12 if index % 2 == 0 else -0.12
        head = 0.018 if index % 2 == 0 else -0.018
        blink = 0.85 if index in {2, 6} else 0.05
        smile = 0.12 + index * 0.04
        frames.append(
            {
                "timestamp_us": ts,
                "body": {
                    "nose": point(0.5 + head, 0.20),
                    "left_shoulder": point(0.40, 0.36),
                    "right_shoulder": point(0.60, 0.36),
                    "left_elbow": point(0.34 + swing * 0.25, 0.50),
                    "right_elbow": point(0.66 - swing * 0.25, 0.50),
                    "left_wrist": point(0.30 + swing, 0.62),
                    "right_wrist": point(0.70 - swing, 0.62),
                    "left_hip": point(0.44, 0.60),
                    "right_hip": point(0.56, 0.60),
                    "left_knee": point(0.44, 0.77),
                    "right_knee": point(0.56, 0.77),
                    "left_ankle": point(0.43, 0.94),
                    "right_ankle": point(0.57, 0.94),
                },
                "left_hand": {"wrist": point(0.30 + swing, 0.62, confidence=0.82)},
                "right_hand": {"wrist": point(0.70 - swing, 0.62, confidence=0.80)},
                "face": {
                    "nose_tip": point(0.5 + head, 0.20, confidence=0.88),
                    "left_eye_inner": point(0.485 + head, 0.185, confidence=0.86),
                    "right_eye_inner": point(0.515 + head, 0.185, confidence=0.86),
                    "mouth_left": point(0.475 + head, 0.235, confidence=0.84),
                    "mouth_right": point(0.525 + head, 0.235, confidence=0.84),
                },
                "expressions": {
                    "blink_left": blink,
                    "blink_right": max(0.0, blink - 0.03),
                    "jaw_open": 0.10 + index * 0.02,
                    "mouth_smile_left": smile,
                    "mouth_smile_right": max(0.0, smile - 0.02),
                    "mouth_frown_left": 0.03,
                    "mouth_frown_right": 0.04,
                    "brow_inner_up": 0.15 + index * 0.01,
                    "brow_down_left": 0.05,
                    "brow_down_right": 0.06,
                },
            }
        )
    return {
        "schema": TRACKING_SCHEMA,
        "coordinate_space": COORDINATE_SPACE,
        "source": {
            "sha256": hashlib.sha256(source_name.encode("utf-8")).hexdigest(),
            "bytes": 24680,
            "permission_assertion": "synthetic local fixture licensed for repository tests",
            "media": {
                "codec": "h264",
                "width": 1280,
                "height": 720,
                "duration_us": 800_000,
                "nominal_fps": 10.0,
            },
        },
        "backend": {
            "id": "profile-store-fixture",
            "version": "1.0.0",
            "model_revision": "profile-store-fixture-r1",
        },
        "frames": frames,
        "coverage": {
            "body": {"observed_frames": 8, "total_frames": 8, "coverage": 1.0, "confidence_frames": 8, "mean_confidence": 0.9},
            "hands": {"observed_frames": 8, "total_frames": 8, "coverage": 1.0, "confidence_frames": 8, "mean_confidence": 0.81},
            "face": {"observed_frames": 8, "total_frames": 8, "coverage": 1.0, "confidence_frames": 8, "mean_confidence": 0.86},
        },
        "recommendations": [],
        "production_activation": False,
    }


def vrm_fixture(marker: str) -> bytes:
    document = {
        "asset": {"version": "2.0", "generator": marker},
        "extensionsUsed": ["VRMC_vrm"],
        "extensions": {"VRMC_vrm": {"specVersion": "1.0"}},
    }
    payload = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload += b" " * ((4 - len(payload) % 4) % 4)
    total = 12 + 8 + len(payload)
    return struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<II", len(payload), 0x4E4F534A) + payload


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    crc = binascii.crc32(kind)
    crc = binascii.crc32(payload, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def png_fixture() -> bytes:
    raw = b"\x00\x00\x00\x00\xff"
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(raw))
        + png_chunk(b"IEND", b"")
    )
