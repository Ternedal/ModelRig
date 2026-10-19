"""Pure HTTP byte-range parsing for future authenticated media streaming.

Never expose this helper directly as a public route; the API must first
authenticate, authorize the media ID, and open the validated catalog file.
"""
from __future__ import annotations

from dataclasses import dataclass


class UnsatisfiableRange(ValueError):
    pass


@dataclass(frozen=True)
class ByteRange:
    start: int
    end: int
    total: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    @property
    def content_range(self) -> str:
        return f"bytes {self.start}-{self.end}/{self.total}"


def parse_single_range(header: str | None, size: int) -> ByteRange | None:
    """Parse a single RFC 9110 byte range; reject multipart and invalid ranges.

    None means serve full representation (HTTP 200); a range means HTTP 206.
    UnsatisfiableRange maps to HTTP 416 with Content-Range: bytes */SIZE.
    """
    if type(size) is not int or size < 0:
        raise ValueError("Invalid file size")
    if header is None:
        return None
    if not isinstance(header, str) or not header.startswith("bytes="):
        raise UnsatisfiableRange("Unsupported range unit")
    spec = header[6:]
    if "," in spec or spec.count("-") != 1:
        raise UnsatisfiableRange("Only a single byte range is supported")
    first, last = spec.split("-", 1)
    if not first and not last:
        raise UnsatisfiableRange("Empty range")
    if not all(part.isascii() and part.isdecimal() for part in (first, last) if part):
        raise UnsatisfiableRange("Non-numeric range")
    if size == 0:
        raise UnsatisfiableRange("Empty file")
    if not first:
        suffix = int(last)
        if suffix <= 0:
            raise UnsatisfiableRange("Invalid suffix")
        start = max(0, size - suffix)
        end = size - 1
    else:
        start = int(first)
        end = size - 1 if not last else min(int(last), size - 1)
        if start >= size or end < start:
            raise UnsatisfiableRange("Range not satisfiable")
    return ByteRange(start, end, size)
