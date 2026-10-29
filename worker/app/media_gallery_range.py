"""Strict single-range parser for authenticated gallery streaming.

The caller must authenticate and authorize the media ID before using this.
No filesystem access or HTTP route registration occurs in this module.
"""
from __future__ import annotations

import re

_RANGE = re.compile(r"bytes=(\d*)-(\d*)\Z")
_MAX_INT = (1 << 63) - 1


class RangeNotSatisfiable(ValueError):
    pass


def select_range(header: str | None, size: int, *, max_chunk: int = 8 * 1024 * 1024) -> tuple[int, int, int]:
    """Return (start, end inclusive, status) for one bounded byte range.

    A missing Range header returns a 200 full response; the HTTP adapter must
    stream it in bounded buffers rather than materializing it in memory.
    """
    if type(size) is not int or not 0 <= size <= _MAX_INT:
        raise ValueError("invalid_size")
    if type(max_chunk) is not int or not 1 <= max_chunk <= _MAX_INT:
        raise ValueError("invalid_chunk_limit")
    if header is None:
        return (0, size - 1, 200)
    if not isinstance(header, str) or len(header) > 128:
        raise RangeNotSatisfiable("invalid_range")
    match = _RANGE.fullmatch(header)
    if match is None:
        raise RangeNotSatisfiable("unsupported_range")
    left, right = match.groups()
    if not left and not right:
        raise RangeNotSatisfiable("empty_range")
    if size == 0:
        raise RangeNotSatisfiable("empty_asset")
    try:
        if left:
            start = int(left)
            end = int(right) if right else min(size - 1, start + max_chunk - 1)
            if start >= size or end < start:
                raise RangeNotSatisfiable("out_of_bounds")
            end = min(end, size - 1)
            if end - start + 1 > max_chunk:
                raise RangeNotSatisfiable("range_too_large")
        else:
            suffix = int(right)
            if suffix == 0:
                raise RangeNotSatisfiable("invalid_suffix")
            start = max(0, size - suffix)
            end = size - 1
            if end - start + 1 > max_chunk:
                raise RangeNotSatisfiable("range_too_large")
    except (ValueError, OverflowError) as exc:
        raise RangeNotSatisfiable("invalid_range") from exc
    return (start, end, 206)
