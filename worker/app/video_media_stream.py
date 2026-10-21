"""File-backed media response builder for an authenticated parent API.

Not mounted. Caller must authenticate and authorize the catalog item first.
Supports HEAD and bounded streaming of GET/Range without loading a video into RAM.
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from .video_media_ranges import UnsatisfiableRange, parse_single_range


def iter_media_bytes(path: Path, start: int, length: int, chunk_size: int = 256 * 1024) -> Iterator[bytes]:
    """Stream at most length bytes from a validated media file."""
    if any(type(value) is not int for value in (start, length, chunk_size)) or start < 0 or length < 0 or chunk_size <= 0:
        raise ValueError("Invalid stream bounds")
    with Path(path).open("rb") as source:
        source.seek(start)
        remaining = length
        while remaining:
            block = source.read(min(chunk_size, remaining))
            if not block:
                break
            remaining -= len(block)
            yield block


def media_response_plan(*, size: int, mime_type: str, range_header: str | None = None,
                        method: str = "GET") -> tuple[int, dict[str, str], int, int]:
    """Return status, headers, byte offset, length for an authenticated file.

    The caller must map 416 and send its headers; HEAD must send no body.
    """
    if type(method) is not str or method not in ("GET", "HEAD"):
        raise ValueError("Unsupported method")
    if type(size) is not int or size < 0:
        raise ValueError("Invalid file size")
    if type(mime_type) is not str or mime_type not in ("video/mp4", "image/png", "image/jpeg", "image/webp"):
        raise ValueError("Unsupported media MIME")
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": mime_type,
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    try:
        byte_range = parse_single_range(range_header, size)
    except UnsatisfiableRange:
        headers["Content-Range"] = f"bytes */{size}"
        headers["Content-Length"] = "0"
        return 416, headers, 0, 0
    if byte_range is None:
        headers["Content-Length"] = str(size)
        return 200, headers, 0, size
    headers["Content-Range"] = byte_range.content_range
    headers["Content-Length"] = str(byte_range.length)
    return 206, headers, byte_range.start, byte_range.length
