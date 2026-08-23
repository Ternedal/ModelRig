"""Local video decoding boundary for BodyRig M1.1.

The stable tracking contract in :mod:`bodyrig.tracking` must not depend on a
particular media stack.  This module therefore keeps decoded RGB frames behind
a tiny BodyRig-owned type and loads PyAV only when the optional adapter is
actually used.

PyAV is intentionally optional.  Some Windows Application Control policies can
reject bundled native FFmpeg DLLs, so callers must be free to substitute a
different decoder without changing ``bodyrig.tracking/v1``.
"""
from __future__ import annotations

import importlib
import math
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Iterable, Protocol

from .tracking import MediaFacts

PYAV_VERSION = "18.0.0"


class VideoIngestError(RuntimeError):
    """The local decoder cannot truthfully inspect or decode the source."""


@dataclass(frozen=True)
class DecodedVideoFrame:
    """One tightly packed RGB24 frame on the source presentation timeline."""

    timestamp_us: int
    width: int
    height: int
    rgb24: bytes

    def __post_init__(self) -> None:
        if type(self.timestamp_us) is not int or self.timestamp_us < 0:
            raise VideoIngestError("timestamp_us must be a non-negative integer")
        if type(self.width) is not int or self.width <= 0:
            raise VideoIngestError("frame width must be a positive integer")
        if type(self.height) is not int or self.height <= 0:
            raise VideoIngestError("frame height must be a positive integer")
        if not isinstance(self.rgb24, bytes):
            raise VideoIngestError("rgb24 must be immutable bytes")
        expected = self.width * self.height * 3
        if len(self.rgb24) != expected:
            raise VideoIngestError(
                f"rgb24 length mismatch; expected {expected}, got {len(self.rgb24)}"
            )


class VideoDecoder(Protocol):
    """Replaceable local decoder boundary used by tracking backends."""

    decoder_id: str
    decoder_version: str

    def inspect(self, source_path: str | Path) -> MediaFacts: ...

    def decode(self, source_path: str | Path) -> Iterable[DecodedVideoFrame]: ...


def _positive_number(value: object, *, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise VideoIngestError(f"{label} is unavailable") from exc
    if not math.isfinite(number) or number <= 0.0:
        raise VideoIngestError(f"{label} must be positive and finite")
    return number


def _round_fraction_to_int(value: Fraction) -> int:
    """Round a non-negative fraction to nearest integer without float drift."""
    if value < 0:
        raise VideoIngestError("negative presentation timestamp")
    quotient, remainder = divmod(value.numerator, value.denominator)
    if remainder * 2 >= value.denominator:
        quotient += 1
    return quotient


def _timestamp_us(pts_delta: int, time_base: object) -> int:
    if type(pts_delta) is not int:
        raise VideoIngestError("frame PTS must be an integer")
    try:
        base = Fraction(time_base)
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise VideoIngestError("frame time_base is unavailable") from exc
    return _round_fraction_to_int(Fraction(pts_delta) * base * 1_000_000)


def _packed_rgb24(frame: object) -> tuple[int, int, bytes]:
    """Convert a PyAV-like frame to packed RGB24 without requiring NumPy."""
    try:
        rgb = frame.to_rgb()
        width = int(rgb.width)
        height = int(rgb.height)
        planes = tuple(rgb.planes)
    except (AttributeError, TypeError, ValueError) as exc:
        raise VideoIngestError("decoder did not provide a valid RGB frame") from exc
    if width <= 0 or height <= 0 or len(planes) != 1:
        raise VideoIngestError("RGB24 frame geometry is invalid")
    plane = planes[0]
    try:
        line_size = int(plane.line_size)
        raw = bytes(plane)
    except (AttributeError, TypeError, ValueError) as exc:
        raise VideoIngestError("RGB24 plane is unreadable") from exc
    row_bytes = width * 3
    if line_size < row_bytes or len(raw) < line_size * height:
        raise VideoIngestError("RGB24 plane stride/buffer is inconsistent")
    if line_size == row_bytes:
        packed = raw[: row_bytes * height]
    else:
        packed = b"".join(
            raw[row * line_size : row * line_size + row_bytes]
            for row in range(height)
        )
    return width, height, packed


class PyAVVideoDecoder:
    """Pinned PyAV adapter with PTS-derived timestamps and no implicit download."""

    decoder_id = "pyav"
    decoder_version = PYAV_VERSION

    def __init__(self, *, av_module: object | None = None) -> None:
        self._injected_av = av_module

    def _av(self) -> object:
        if self._injected_av is not None:
            module = self._injected_av
        else:
            try:
                module = importlib.import_module("av")
            except (ImportError, OSError) as exc:
                raise VideoIngestError(
                    "PyAV is unavailable; install the optional BodyRig video dependencies "
                    "or select another VideoDecoder"
                ) from exc
        version = getattr(module, "__version__", None)
        if version != PYAV_VERSION:
            raise VideoIngestError(
                f"unsupported PyAV runtime {version!r}; expected exactly {PYAV_VERSION}"
            )
        return module

    @staticmethod
    def _path(source_path: str | Path) -> Path:
        path = Path(source_path)
        if not path.is_file():
            raise VideoIngestError("source video must be an existing regular file")
        if path.is_symlink():
            raise VideoIngestError("source video must not be a symlink")
        return path

    @staticmethod
    def _video_stream(container: object) -> object:
        try:
            streams = tuple(container.streams.video)
        except AttributeError as exc:
            raise VideoIngestError("decoder container has no video stream collection") from exc
        if not streams:
            raise VideoIngestError("source contains no video stream")
        try:
            return min(streams, key=lambda stream: int(stream.index))
        except (AttributeError, TypeError, ValueError) as exc:
            raise VideoIngestError("video stream index is invalid") from exc

    @staticmethod
    def _duration_us(container: object, stream: object, av_module: object) -> int:
        duration = getattr(stream, "duration", None)
        time_base = getattr(stream, "time_base", None)
        if duration is not None and time_base is not None:
            try:
                value = Fraction(int(duration)) * Fraction(time_base) * 1_000_000
            except (TypeError, ValueError, ZeroDivisionError) as exc:
                raise VideoIngestError("video stream duration is invalid") from exc
            result = _round_fraction_to_int(value)
            if result > 0:
                return result

        container_duration = getattr(container, "duration", None)
        av_time_base = getattr(av_module, "time_base", None)
        if container_duration is not None and av_time_base is not None:
            try:
                seconds = Fraction(int(container_duration), int(av_time_base))
            except (TypeError, ValueError, ZeroDivisionError) as exc:
                raise VideoIngestError("container duration is invalid") from exc
            result = _round_fraction_to_int(seconds * 1_000_000)
            if result > 0:
                return result
        raise VideoIngestError("video duration is unavailable")

    @staticmethod
    def _nominal_fps(stream: object) -> float:
        for name in ("average_rate", "base_rate", "guessed_rate"):
            value = getattr(stream, name, None)
            if value is None:
                continue
            try:
                return _positive_number(value, label=f"video {name}")
            except VideoIngestError:
                continue
        raise VideoIngestError("video frame rate metadata is unavailable")

    def inspect(self, source_path: str | Path) -> MediaFacts:
        path = self._path(source_path)
        av_module = self._av()
        try:
            with av_module.open(str(path), mode="r") as container:
                stream = self._video_stream(container)
                context = stream.codec_context
                facts = MediaFacts(
                    codec=str(context.name),
                    width=int(context.width),
                    height=int(context.height),
                    duration_us=self._duration_us(container, stream, av_module),
                    nominal_fps=self._nominal_fps(stream),
                )
                facts.to_dict()
                return facts
        except VideoIngestError:
            raise
        except Exception as exc:
            raise VideoIngestError(f"video inspection failed: {type(exc).__name__}") from exc

    def decode(self, source_path: str | Path) -> Iterable[DecodedVideoFrame]:
        path = self._path(source_path)
        av_module = self._av()
        try:
            with av_module.open(str(path), mode="r") as container:
                stream = self._video_stream(container)
                origin_pts: int | None = None
                previous_timestamp = -1
                for frame in container.decode(stream):
                    pts = getattr(frame, "pts", None)
                    if type(pts) is not int:
                        raise VideoIngestError("decoded video frame has no integer PTS")
                    if origin_pts is None:
                        origin_pts = pts
                    time_base = getattr(frame, "time_base", None) or getattr(stream, "time_base", None)
                    timestamp = _timestamp_us(pts - origin_pts, time_base)
                    if timestamp <= previous_timestamp:
                        raise VideoIngestError(
                            "decoded presentation timestamps must be strictly increasing"
                        )
                    width, height, packed = _packed_rgb24(frame)
                    previous_timestamp = timestamp
                    yield DecodedVideoFrame(timestamp, width, height, packed)
                if origin_pts is None:
                    raise VideoIngestError("video stream decoded zero frames")
        except VideoIngestError:
            raise
        except Exception as exc:
            raise VideoIngestError(f"video decode failed: {type(exc).__name__}") from exc
