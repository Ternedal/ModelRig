"""Poll bounded ComfyUI history for one submitted prompt.

No network calls happen until an explicit caller invokes poll_history.
"""
from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request

from worker.app.comfy_transport import ComfyTransport, ComfyTransportError

_PROMPT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def poll_history(transport: ComfyTransport, prompt_id: str) -> dict:
    """Return normalized state without trusting arbitrary ComfyUI filenames."""
    if not isinstance(prompt_id, str) or not _PROMPT_ID.fullmatch(prompt_id):
        raise ComfyTransportError("Invalid prompt ID")
    request = Request(transport.base_url + "/history/" + prompt_id, method="GET")
    try:
        with transport._opener.open(request, timeout=transport.timeout_seconds) as response:
            if response.status != 200:
                raise ComfyTransportError("ComfyUI history unavailable")
            raw = response.read(1_000_001)
    except (OSError, URLError) as exc:
        raise ComfyTransportError("ComfyUI history transport unavailable") from exc
    if len(raw) > 1_000_000:
        raise ComfyTransportError("ComfyUI history response too large")
    try:
        history = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ComfyTransportError("Invalid ComfyUI history JSON") from exc
    if not isinstance(history, dict):
        raise ComfyTransportError("Invalid ComfyUI history shape")
    entry = history.get(prompt_id)
    if entry is None:
        return {"state": "pending"}
    if not isinstance(entry, dict):
        raise ComfyTransportError("Invalid ComfyUI history entry")
    status = entry.get("status")
    if not isinstance(status, dict):
        raise ComfyTransportError("Missing ComfyUI status")
    status_str = status.get("status_str")
    if status_str == "error":
        return {"state": "failed", "error_code": "generation_failed"}
    if status_str != "success" or status.get("completed") is not True:
        return {"state": "pending"}
    outputs = entry.get("outputs")
    if not isinstance(outputs, dict):
        raise ComfyTransportError("Missing ComfyUI outputs")
    media = []
    for node in outputs.values():
        if not isinstance(node, dict):
            continue
        for field in ("images", "gifs"):
            assets = node.get(field, [])
            if not isinstance(assets, list):
                raise ComfyTransportError("Invalid output asset list")
            for asset in assets:
                if not isinstance(asset, dict):
                    raise ComfyTransportError("Invalid output asset")
                filename = asset.get("filename")
                subfolder = asset.get("subfolder", "")
                storage_type = asset.get("type")
                if (
                    not isinstance(filename, str) or not filename
                    or "/" in filename or "\\" in filename or filename in {".", ".."}
                    or subfolder != "" or storage_type != "output"
                ):
                    raise ComfyTransportError("Unsafe ComfyUI output descriptor")
                media.append(filename)
                if len(media) > 32:
                    raise ComfyTransportError("Too many ComfyUI outputs")
    if not media:
        raise ComfyTransportError("Completed prompt has no supported outputs")
    return {"state": "succeeded", "filenames": media}
