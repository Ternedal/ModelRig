"""Fail-closed image decoding and re-encoding boundary.

Pillow is optional and deliberately not imported by the normal ModelRig worker.
Install a pinned, reviewed Pillow version in the isolated image worker before
enabling this pipeline. Never pass original ComfyUI bytes to artifact storage.
"""
from __future__ import annotations

import io

from .image_validation import InvalidImage


def sanitize_to_png(
    payload: bytes, *, max_input_bytes: int = 16_000_000,
    max_dimension: int = 4096, max_pixels: int = 16_000_000,
) -> bytes:
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= max_input_bytes:
        raise InvalidImage("Invalid input size")
    if not 1 <= max_dimension <= 8192 or not 1 <= max_pixels <= 64_000_000:
        raise ValueError("Invalid image limits")
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RuntimeError("Isolated image decoder is not installed") from exc

    try:
        with Image.open(io.BytesIO(payload)) as source:
            if source.format not in {"PNG", "JPEG", "WEBP"}:
                raise InvalidImage("Unsupported image format")
            width, height = source.size
            if (
                width < 1 or height < 1 or width > max_dimension
                or height > max_dimension or width * height > max_pixels
            ):
                raise InvalidImage("Image dimensions exceed limits")
            # Pillow may emit a warning (rather than an exception) for
            # decompression bombs. Reject both before pixel allocation.
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                source.load()
            # Rebuild pixels into a fresh image. Do not preserve EXIF, comments,
            # ICC, ancillary chunks, or embedded metadata.
            oriented = ImageOps.exif_transpose(source)
            if (oriented.width > max_dimension or oriented.height > max_dimension
                    or oriented.width * oriented.height > max_pixels):
                raise InvalidImage("Oriented image exceeds limits")
            if oriented.mode not in {"RGB", "RGBA"}:
                oriented = oriented.convert("RGBA" if "A" in oriented.getbands() else "RGB")
            clean = Image.new(oriented.mode, oriented.size)
            clean.paste(oriented)
            output = io.BytesIO()
            clean.save(output, format="PNG", optimize=False)
            result = output.getvalue()
            if len(result) > max_input_bytes:
                raise InvalidImage("Sanitized image exceeds output size limit")
            return result
    except (OSError, ValueError, DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise InvalidImage("Unable to decode image safely") from exc


try:
    from PIL.Image import DecompressionBombError
except ImportError:
    class DecompressionBombError(Exception):
        pass
