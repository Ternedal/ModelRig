"""Optional, fail-closed ComfyUI adapter for future Wan video jobs.

This module is deliberately NOT mounted as an HTTP route and never starts ComfyUI.
The caller must supply a trusted, prebuilt workflow; never forward user-supplied
ComfyUI node graphs. Runtime video generation is not enabled by this module.
"""
from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class VideoBackendError(RuntimeError):
    """A local video backend request failed."""


def _base_url(url: str) -> str:
    if not isinstance(url, str):
        raise ValueError("ComfyUI endpoint must be a URL string")
    try:
        parsed = urllib.parse.urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid ComfyUI endpoint") from exc
    if parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("ComfyUI endpoint must be a plain loopback HTTP URL")
    if hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("ComfyUI must be on loopback")
    if not port or parsed.path not in ("", "/"):
        raise ValueError("ComfyUI endpoint must specify a port and no path")
    return f"http://127.0.0.1:{port}" if hostname != "::1" else f"http://[::1]:{port}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise VideoBackendError("ComfyUI redirects are forbidden")


class ComfyVideoClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8188", timeout: float = 10.0):
        self.base_url = _base_url(base_url)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError("Invalid timeout")
        self.timeout = timeout
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

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
        if not isinstance(prompt_id, str) or not (1 <= len(prompt_id) <= 128) or not all(c.isascii() and (c.isalnum() or c in "-_") for c in prompt_id):
            raise VideoBackendError("ComfyUI returned no valid prompt ID")
        return prompt_id

    def history(self, prompt_id: str) -> dict[str, Any]:
        if not isinstance(prompt_id, str) or not (1 <= len(prompt_id) <= 128):
            raise ValueError("Invalid prompt ID")
        if not all(c.isascii() and (c.isalnum() or c in "-_") for c in prompt_id):
            raise ValueError("Invalid prompt ID")
        return self._request("GET", "/history/" + urllib.parse.quote(prompt_id, safe=""))

    def completed_outputs(self, prompt_id: str) -> dict[str, Any] | None:
        """Return completed ComfyUI output metadata, or None while pending.

        File paths are not trusted here; a separate collector must validate
        every filename against its configured output directory.
        """
        record = self.history(prompt_id).get(prompt_id)
        if not isinstance(record, dict):
            return None
        status = record.get("status")
        if not isinstance(status, dict):
            return None
        if status.get("status_str") == "error":
            raise VideoBackendError("ComfyUI job failed")
        if status.get("completed") is not True or status.get("status_str") != "success":
            return None
        outputs = record.get("outputs")
        if not isinstance(outputs, dict):
            return None
        return outputs

    def interrupt(self) -> None:
        """Global ComfyUI interrupt: caller must enforce single-tenant ownership."""
        self._request("POST", "/interrupt", {})
