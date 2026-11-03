"""Bounded PNG container validation before forwarding image bytes to a decoder.

This checks framing, CRC and dimensions, not pixel decoding. A downstream
image adapter must still decode with its own resource limits.
"""
from __future__ import annotations

import struct
import zlib

PNG_SIGNATURE = bytes.fromhex("89504e470d0a1a0a")
MAX_DIMENSION = 8192
MAX_PIXELS = 16_777_216


class InvalidSourcePng(ValueError):
    pass


def validate_png_container(payload: bytes) -> None:
    if not payload.startswith(PNG_SIGNATURE):
        raise InvalidSourcePng("invalid_png_signature")
    pos = len(PNG_SIGNATURE)
    seen_ihdr = seen_idat = seen_iend = seen_plte = False
    idat_finished = False
    color_type = None
    while pos < len(payload):
        if len(payload) - pos < 12:
            raise InvalidSourcePng("truncated_png_chunk")
        length = struct.unpack_from(">I", payload, pos)[0]
        if length > len(payload) - pos - 12:
            raise InvalidSourcePng("truncated_png_chunk")
        kind = payload[pos + 4:pos + 8]
        data = payload[pos + 8:pos + 8 + length]
        crc = struct.unpack_from(">I", payload, pos + 8 + length)[0]
        if zlib.crc32(kind + data) & 0xffffffff != crc:
            raise InvalidSourcePng("invalid_png_crc")
        pos += 12 + length
        if (len(kind) != 4 or not all(65 <= byte <= 90 or 97 <= byte <= 122 for byte in kind)
                or kind[2] & 0x20):
            raise InvalidSourcePng("invalid_png_chunk_type")
        if seen_idat and kind != b"IDAT":
            idat_finished = True
        if not seen_ihdr:
            if kind != b"IHDR" or length != 13:
                raise InvalidSourcePng("missing_png_ihdr")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", data)
            if (not 0 < width <= MAX_DIMENSION or not 0 < height <= MAX_DIMENSION
                    or width * height > MAX_PIXELS or depth not in (1, 2, 4, 8, 16)
                    or color not in (0, 2, 3, 4, 6) or compression or filtering
                    or interlace not in (0, 1)):
                raise InvalidSourcePng("invalid_png_dimensions_or_header")
            valid_depths = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8),
                            4: (8, 16), 6: (8, 16)}
            if depth not in valid_depths[color]:
                raise InvalidSourcePng("invalid_png_color_depth")
            color_type = color
            seen_ihdr = True
        elif kind == b"IHDR":
            raise InvalidSourcePng("duplicate_png_ihdr")
        elif kind == b"PLTE":
            if seen_plte or seen_idat or color_type in (0, 4) or not length or length % 3 or length > 768:
                raise InvalidSourcePng("invalid_png_palette")
            seen_plte = True
        elif kind == b"IDAT":
            if idat_finished or (color_type == 3 and not seen_plte):
                raise InvalidSourcePng("invalid_png_data_order")
            if seen_iend:
                raise InvalidSourcePng("png_data_after_end")
            seen_idat = True
        elif kind == b"IEND":
            if length or not seen_idat or pos != len(payload):
                raise InvalidSourcePng("invalid_png_end")
            seen_iend = True
            break
        elif kind[0] & 0x20 == 0:
            raise InvalidSourcePng("unknown_critical_png_chunk")
    if not seen_iend:
        raise InvalidSourcePng("missing_png_end")
