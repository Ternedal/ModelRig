"""Validated video request contract, independent of runtime and external dependencies.

Only flat 2D is enabled for initial integration. VR metadata must never
claim spatial projection or stereoscopy without a qualified pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

VideoKind = Literal["text_to_video", "image_to_video"]
VideoProfile = Literal["flat_2d", "stereo_sbs", "vr180", "vr360"]


@dataclass(frozen=True)
class VideoRequest:
    kind: VideoKind
    prompt: str
    output_profile: VideoProfile = "flat_2d"
    width: int = 512
    height: int = 320
    fps: int = 16
    duration_seconds: int = 3
    input_image_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("text_to_video", "image_to_video"):
            raise ValueError("Unsupported video kind")
        if self.output_profile != "flat_2d":
            raise ValueError("VR/stereo generation not qualified")
        if not isinstance(self.prompt, str) or not 1 <= len(self.prompt.strip()) <= 2000:
            raise ValueError("Invalid prompt")
        for value, low, high, name in (
            (self.width, 256, 1024, "width"),
            (self.height, 256, 1024, "height"),
            (self.fps, 8, 30, "fps"),
            (self.duration_seconds, 1, 8, "duration_seconds"),
        ):
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"Invalid {name}")
        if self.width % 16 or self.height % 16:
            raise ValueError("Dimensions must be multiples of 16")
        if self.kind == "image_to_video":
            if not isinstance(self.input_image_id, str) or not self.input_image_id or not self.input_image_id.isascii() or not all(
                ch.isalnum() or ch in "-_" for ch in self.input_image_id
            ) or len(self.input_image_id) > 128:
                raise ValueError("Validated image asset ID required")
        elif self.input_image_id is not None:
            raise ValueError("Text-to-video cannot take an image ID")

    def flat_manifest(self, artifact_id: str) -> dict:
        if not isinstance(artifact_id, str) or not artifact_id or len(artifact_id) > 128 or not artifact_id.isascii() or not all(ch.isalnum() or ch in "-_" for ch in artifact_id):
            raise ValueError("Invalid artifact ID")
        return {
            "schema": "kaliv-media/v1",
            "media_type": "video",
            "projection": "flat",
            "stereo": "mono",
            "codec": "h264",
            "container": "mp4",
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "duration_seconds": self.duration_seconds,
            "artifact_id": artifact_id,
        }
