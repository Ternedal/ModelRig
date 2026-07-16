"""Regression tests for the outer worker ASGI hardening boundary."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.hardening import HardenedWorkerApp  # noqa: E402

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


async def invoke(app, chunks, headers=None):
    queue = [
        {"type": "http.request", "body": c, "more_body": i < len(chunks) - 1}
        for i, c in enumerate(chunks)
    ]
    sent = []

    async def receive():
        if queue:
            return queue.pop(0)
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/test",
        "headers": headers or [],
    }
    await app(scope, receive, send)
    return sent


async def run_async():
    called = False
    seen_body = b""

    async def echo_app(scope, receive, send):
        nonlocal called, seen_body
        called = True
        message = await receive()
        seen_body = message.get("body", b"")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": seen_body, "more_body": False})

    guarded = HardenedWorkerApp(echo_app, limit_bytes=5)
    sent = await invoke(guarded, [b"abc", b"def"])
    check(not called, "chunked body over the limit is rejected before the app")
    check(sent[0]["status"] == 413, "oversized chunked body returns 413")

    called = False
    sent = await invoke(guarded, [b"ab", b"cd"])
    check(called and seen_body == b"abcd", "bounded chunked body is replayed exactly once")
    check(sent[0]["status"] == 200, "bounded body reaches the app")

    called = False
    sent = await invoke(
        guarded,
        [b""],
        headers=[(b"content-length", b"99")],
    )
    check(not called and sent[0]["status"] == 413,
          "honest oversized Content-Length fails before reading")

    root = Path(tempfile.mkdtemp(prefix="hardening_test_root_"))
    created = None

    async def temp_app(scope, receive, send):
        nonlocal created
        await receive()
        created = Path(tempfile.mkdtemp(prefix="alva_voice_", dir=root))
        (created / "input.wav").write_bytes(b"private audio")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})

    temp_guard = HardenedWorkerApp(temp_app, limit_bytes=10, temp_root=root)
    await invoke(temp_guard, [b"x"])
    check(created is not None and not created.exists(),
          "voice temp directory is removed after the final response frame")
    try:
        root.rmdir()
    except OSError:
        pass


def run():
    asyncio.run(run_async())
    print(f"\nworker_hardening: {passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    run()
