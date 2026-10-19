"""Optional, fail-closed ComfyUI adapter for future Wan video jobs.

This module is deliberately NOT mounted as an HTTP route and never starts ComfyUI.
The caller must supply a trusted, prebuilt workflow; never forward user-supplied
ComfyUI node graphs. Runtime video generation is not enabled by this module.
"""
from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class VideoBackendError(RuntimeError):
    """A local video backend request failed."""


def _base_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("ComfyUI endpoint must be a plain loopback HTTP URL")
    if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("ComfyUI must be on loopback")
    if not parsed.port or parsed.path not in ("", "/"):
        raise ValueError("ComfyUI endpoint must specify a port and no path")
    return f"http://127.0.0.1:{parsed.port}" if parsed.hostname != "::1" else f"http://[::1]:{parsed.port}"


class ComfyVideoClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8188", timeout: float = 10.0):
        self.base_url = _base_url(base_url)
        if not 0 < timeout <= 120:
            raise ValueError("Invalid timeout")
        self.timeout = timeout
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with self._opener.open(req, timeout=self.timeout) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise VideoBackendError("Backend response too large")
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise VideoBackendError("Invalid backend response")
                return result
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise VideoBackendError("Local ComfyUI backend unavailable or returned invalid JSON") from exc

    def submit_trusted_workflow(self, workflow: dict[str, Any]) -> str:
        """Only call with an allowlisted server-owned graph, never client input."""
        if not isinstance(workflow, dict) or not workflow:
            raise ValueError("Trusted workflow is required")
        result = self._request("POST", "/prompt", {"prompt": workflow})
        prompt_id = result.get("prompt_id")
        if not isinstance(prompt_id, str) or not prompt_id or len(prompt_id) > 128:
            raise VideoBackendError("ComfyUI returned no valid prompt ID")
        return prompt_id

    def history(self, prompt_id: str) -> dict[str, Any]:
        if not isinstance(prompt_id, str) or not (1 <= len(prompt_id) <= 128):
            raise ValueError("Invalid prompt ID")
        if not all(c.isalnum() or c in "-_" for c in prompt_id):
            raise ValueError("Invalid prompt ID")
        return self._request("GET", "/history/" + urllib.parse.quote(prompt_id, safe=""))

    def interrupt(self) -> None:
        """Global ComfyUI interrupt: caller must enforce single-tenant ownership."""
        self._request("POST", "/interrupt", {})
