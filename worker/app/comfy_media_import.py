"""Read-only ComfyUI output fetch with bounded, fail-closed storage.

The caller must authorize the job and select the filename from validated
ComfyUI history. This module never exposes ComfyUI's output directory.
"""
from __future__ import annotations

from urllib.parse import urlencode
from urllib.request import Request
from urllib.error import URLError

from worker.app.comfy_transport import ComfyTransport, ComfyTransportError
from worker.app.media_storage_policy import write_media_exclusive
from pathlib import Path


def import_comfy_output(
    transport: ComfyTransport,
    source_filename: str,
    external_root: Path,
    destination_filename: str,
    *,
    max_bytes: int = 100_000_000,
) -> Path:
    """Copy one ComfyUI output into the external media store, never internal."""
    if (
        not isinstance(source_filename, str) or not source_filename
        or source_filename in {".", ".."}
        or "/" in source_filename or "\\" in source_filename
    ):
        raise ComfyTransportError("Unsafe source filename")
    if not isinstance(max_bytes, int) or not 0 < max_bytes <= 500_000_000:
        raise ComfyTransportError("Invalid output size limit")
    url = transport.base_url + "/view?" + urlencode(
        {"filename": source_filename, "subfolder": "", "type": "output"}
    )
    request = Request(url, method="GET")
    try:
        with transport._opener.open(request, timeout=transport.timeout_seconds) as response:
            if response.status != 200:
                raise ComfyTransportError("ComfyUI output unavailable")
            payload = response.read(max_bytes + 1)
    except (OSError, URLError) as exc:
        raise ComfyTransportError("ComfyUI output transport unavailable") from exc
    if not payload or len(payload) > max_bytes:
        raise ComfyTransportError("ComfyUI output empty or too large")
    return write_media_exclusive(
        external_root, destination_filename, payload, max_bytes=max_bytes
    )
