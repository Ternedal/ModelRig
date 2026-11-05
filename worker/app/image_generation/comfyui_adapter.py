"""Default-off ComfyUI HTTP adapter.

No workflow construction from untrusted client JSON. Callers supply an audited,
server-owned workflow; ComfyUI must bind to loopback. This module is deliberately
not mounted into the production worker.
"""
from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlsplit

import httpx

from .outputs import ImageDescriptor, select_output_image
from .image_validation import validate_image_header, InvalidImage


class ComfyUIError(RuntimeError):
    """A bounded, sanitized image-engine error."""


def _loopback_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or not parsed.hostname:
        raise ValueError("ComfyUI endpoint must be an HTTP loopback URL")
    try:
        is_loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("ComfyUI endpoint must be an HTTP loopback URL")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid ComfyUI endpoint port") from exc
    if port is None or not 1 <= port <= 65535:
        raise ValueError("ComfyUI endpoint must specify a valid port")
    if parsed.path not in ("", "/"):
        raise ValueError("ComfyUI endpoint cannot contain a path")
    return base_url.rstrip("/")


class ComfyUIAdapter:
    """Small, testable transport for server-owned image workflows.

    The adapter never accepts arbitrary remote URLs, node definitions from
    clients, or filenames for output retrieval. Higher layers must implement
    workflow pinning, user authorization, job ownership and artifact validation.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8188",
        *,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = _loopback_url(base_url)
        if not 0 < timeout_seconds <= 120:
            raise ValueError("timeout_seconds must be within (0, 120]")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout_seconds,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    async def __aenter__(self) -> "ComfyUIAdapter":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self._client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ComfyUIError("Local image engine request failed") from exc

    async def submit(self, workflow: dict[str, Any], client_id: str) -> str:
        if not workflow or not isinstance(workflow, dict):
            raise ValueError("A server-owned workflow is required")
        if not isinstance(client_id, str) or not client_id or len(client_id) > 128:
            raise ValueError("Invalid client ID")
        data = await self._request(
            "POST", "/prompt", json={"prompt": workflow, "client_id": client_id}
        )
        prompt_id = data.get("prompt_id") if isinstance(data, dict) else None
        import uuid
        try:
            prompt_id = str(uuid.UUID(prompt_id))
        except (ValueError, AttributeError, TypeError) as exc:
            raise ComfyUIError("Local image engine returned an invalid prompt ID") from exc
        return prompt_id

    async def history(self, prompt_id: str) -> dict[str, Any]:
        # UUID only: no path injection into ComfyUI route.
        import uuid

        try:
            safe_id = str(uuid.UUID(prompt_id))
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("Invalid prompt ID") from exc
        result = await self._request("GET", f"/history/{safe_id}")
        if not isinstance(result, dict):
            raise ComfyUIError("Invalid image engine history response")
        return result

    async def fetch_output(self, descriptor: ImageDescriptor, *, max_bytes: int = 16_000_000) -> bytes:
        """Fetch a server-selected output with a strict byte limit.

        The returned bytes still require image decoding, dimension limits and
        metadata policy before they may become a client-visible artifact.
        """
        # Revalidate at the HTTP boundary: dataclass instances can be built by
        # arbitrary callers, and the path must never be caller-controlled.
        checked = select_output_image({
            "verified": {"images": [{
                "filename": descriptor.filename,
                "subfolder": descriptor.subfolder,
                "type": descriptor.kind,
            }]}
        })
        if checked != descriptor:
            raise ValueError("Invalid output descriptor")
        if not 1 <= max_bytes <= 32_000_000:
            raise ValueError("Invalid output byte limit")
        try:
            async with self._client.stream(
                "GET", "/view",
                params={"filename": descriptor.filename, "subfolder": "", "type": "output"},
            ) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if content_type not in {"image/png", "image/jpeg", "image/webp"}:
                    raise ComfyUIError("Unexpected image content type")
                result = bytearray()
                async for chunk in response.aiter_bytes():
                    result.extend(chunk)
                    if len(result) > max_bytes:
                        raise ComfyUIError("Image output exceeds byte limit")
                if not result:
                    raise ComfyUIError("Empty image output")
                payload = bytes(result)
                try:
                    detected_type = validate_image_header(payload)
                except InvalidImage as exc:
                    raise ComfyUIError("Invalid image output header") from exc
                if detected_type != content_type:
                    raise ComfyUIError("Image content type does not match payload")
                return payload
        except httpx.HTTPError as exc:
            raise ComfyUIError("Local image output retrieval failed") from exc
