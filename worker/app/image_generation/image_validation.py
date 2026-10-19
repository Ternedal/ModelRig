"""Bounded image signature and dimensions validation before artifact ingestion.

This is not a full decoder. Decode/re-encode in an isolated image processor
before serving untrusted images to a client.
"""
from __future__ import annotations

import struct


class InvalidImage(ValueError):
    pass


def validate_image_header(data: bytes, *, max_dimension: int = 8192) -> str:
    if not isinstance(data, bytes) or len(data) < 24:
        raise InvalidImage("Invalid image data")
    if not 1 <= max_dimension <= 16384:
        raise ValueError("Invalid dimension limit")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if data[12:16] != b"IHDR":
            raise InvalidImage("Invalid PNG header")
        width, height = struct.unpack(">II", data[16:24])
        kind = "image/png"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        if len(data) < 30 or data[12:16] != b"VP8X":
            raise InvalidImage("Unsupported WebP header")
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        kind = "image/webp"
    else:
        raise InvalidImage("Unsupported image format")
    if not 1 <= width <= max_dimension or not 1 <= height <= max_dimension:
        raise InvalidImage("Image dimensions exceed limits")
    return kind
