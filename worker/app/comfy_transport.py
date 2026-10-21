"""Constrained ComfyUI transport adapter for future media worker integration.

No HTTP endpoints or worker loops are activated by importing this module.
Only loopback ComfyUI URLs are permitted; callers own auth and job admission.
"""
from __future__ import annotations

import ipaddress
import json
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import URLError


class ComfyTransportError(RuntimeError):
    pass


def validate_comfy_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ComfyTransportError("ComfyUI must use plain HTTP loopback without credentials or query")
    if parsed.path not in {"", "/"} or parsed.hostname is None:
        raise ComfyTransportError("Invalid ComfyUI base URL")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise ComfyTransportError("ComfyUI requires numeric loopback address") from exc
    if not address.is_loopback:
        raise ComfyTransportError("ComfyUI must be loopback-only")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ComfyTransportError("Invalid ComfyUI port") from exc
    if port is None or not (1 <= port <= 65535):
        raise ComfyTransportError("Explicit ComfyUI port required")
    return f"http://{parsed.netloc}"


class ComfyTransport:
    def __init__(self, base_url: str, *, timeout_seconds: float = 15.0):
        self.base_url = validate_comfy_url(base_url)
        if not 0 < timeout_seconds <= 120:
            raise ComfyTransportError("Invalid transport timeout")
        self.timeout_seconds = timeout_seconds
        self._opener = build_opener(ProxyHandler({}))

    def submit_prompt(self, workflow: dict, client_id: str) -> str:
        if not isinstance(workflow, dict) or not workflow or not isinstance(client_id, str) or not client_id:
            raise ComfyTransportError("Invalid workflow or client ID")
        payload = json.dumps({"prompt": workflow, "client_id": client_id}, allow_nan=False).encode("utf-8")
        if len(payload) > 2_000_000:
            raise ComfyTransportError("Workflow payload too large")
        request = Request(
            self.base_url + "/prompt", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                if response.status != 200:
                    raise ComfyTransportError("ComfyUI rejected prompt")
                raw = response.read(65537)
        except (OSError, URLError) as exc:
            raise ComfyTransportError("ComfyUI transport unavailable") from exc
        if len(raw) > 65536:
            raise ComfyTransportError("ComfyUI response too large")
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ComfyTransportError("Invalid ComfyUI response") from exc
        prompt_id = result.get("prompt_id") if isinstance(result, dict) else None
        if not isinstance(prompt_id, str) or not prompt_id or len(prompt_id) > 128:
            raise ComfyTransportError("ComfyUI response missing prompt ID")
        return prompt_id
