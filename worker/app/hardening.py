"""ASGI hardening that must sit OUTSIDE FastAPI's request parser.

Two bug classes cannot be closed reliably from an ``@app.middleware`` handler:

* FastAPI/Starlette may buffer a chunked JSON request before a handler sees it,
  so a Content-Length-only check is not a real memory bound.
* Streaming voice responses outlive the route function. Temp audio must be
  removed after the LAST response body frame (or cancellation), not merely when
  the route returns its StreamingResponse object.

Wrap the worker app with :func:`harden` at the process entrypoint. The wrapper
reads at most ``KALIV_MAX_UPLOAD_MB`` before handing a replayable body to
FastAPI, and removes every ``alva_voice_*`` temp directory when the last active
HTTP request has fully completed. The active-request counter prevents one
concurrent request from deleting another voice turn's files mid-stream.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable

ASGIApp = Callable[[dict[str, Any], Callable[[], Awaitable[dict[str, Any]]],
                    Callable[[dict[str, Any]], Awaitable[None]]], Awaitable[None]]


def max_upload_bytes() -> int:
    try:
        mb = int(os.getenv("KALIV_MAX_UPLOAD_MB", "25"))
    except ValueError:
        mb = 25
    return max(1, mb) * 1024 * 1024


class HardenedWorkerApp:
    """Outer ASGI guard for bounded bodies and post-stream temp cleanup."""

    def __init__(self, app: ASGIApp, *, limit_bytes: int | None = None,
                 temp_root: str | os.PathLike[str] | None = None) -> None:
        self.app = app
        self.limit_bytes = limit_bytes
        self.temp_root = Path(temp_root or tempfile.gettempdir())
        self._active_http = 0
        self._active_lock = asyncio.Lock()

    async def _enter(self) -> None:
        async with self._active_lock:
            self._active_http += 1

    async def _leave_and_cleanup_if_idle(self) -> None:
        should_clean = False
        async with self._active_lock:
            self._active_http = max(0, self._active_http - 1)
            should_clean = self._active_http == 0
        if not should_clean:
            return
        for path in self.temp_root.glob("alva_voice_*"):
            try:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
            except OSError:
                # Cleanup is best-effort at this boundary. A locked file is
                # retried after the next completed request/startup.
                pass

    @staticmethod
    async def _send_json(send, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body, "more_body": False})

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        await self._enter()
        try:
            limit = self.limit_bytes if self.limit_bytes is not None else max_upload_bytes()

            # Fail before reading when the sender gives an honest Content-Length.
            headers = {k.lower(): v for k, v in scope.get("headers", [])}
            raw_cl = headers.get(b"content-length")
            if raw_cl is not None:
                try:
                    if int(raw_cl) > limit:
                        await self._send_json(send, 413, {
                            "detail": f"request body exceeds the {limit // (1024 * 1024)} MB limit "
                                      "(raise KALIV_MAX_UPLOAD_MB)"
                        })
                        return
                except ValueError:
                    await self._send_json(send, 400, {"detail": "invalid Content-Length"})
                    return

            # Enforce the same bound for chunked/no-length requests BEFORE the
            # FastAPI parser can accumulate an unbounded JSON body.
            body = bytearray()
            disconnected = False
            while True:
                message = await receive()
                if message.get("type") == "http.disconnect":
                    disconnected = True
                    break
                if message.get("type") != "http.request":
                    continue
                body.extend(message.get("body", b""))
                if len(body) > limit:
                    await self._send_json(send, 413, {
                        "detail": f"request body exceeds the {limit // (1024 * 1024)} MB limit "
                                  "(raise KALIV_MAX_UPLOAD_MB)"
                    })
                    return
                if not message.get("more_body", False):
                    break
            if disconnected:
                return

            delivered = False

            async def replay_receive() -> dict[str, Any]:
                nonlocal delivered
                if delivered:
                    return {"type": "http.request", "body": b"", "more_body": False}
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            # ASGI app completion means a StreamingResponse has emitted its final
            # body frame (or the request was cancelled), which is exactly when
            # voice temp files are no longer needed.
            await self.app(scope, replay_receive, send)
        finally:
            await self._leave_and_cleanup_if_idle()


def harden(app: ASGIApp, **kwargs: Any) -> HardenedWorkerApp:
    return HardenedWorkerApp(app, **kwargs)
