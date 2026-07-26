"""A client that walks away mid-stream must not crash the request.

Found on the rig, 26/07: every voice turn that got interrupted -- a stop tap, a
barge-in, a phone losing wifi -- tore down with

    RuntimeError: Unexpected message received: http.request

and the phone showed "stemmesvaret blev afbrudt: forbindelsen lukkede før
riggen var færdig". The stream died on the server, so the user got nothing.
Voice stop/barge-in could not be validated at all.

The cause is in our own middleware, not Starlette's. `HardenedWorkerApp` reads
the whole request body up front (to enforce the upload limit) and then replays
it downstream through `replay_receive`. Replaying the body once is correct. The
bug was what happened afterwards: every later call returned ANOTHER
`http.request` frame, immediately.

That is fine for an ordinary request -- nobody calls receive again. It is fatal
for a StreamingResponse, because Starlette then parks a task on `receive()`
waiting for `http.disconnect` so it can notice the client leaving. Handing it
`http.request` instead is a protocol violation, Starlette raises, the task
group unwinds, and the stream is aborted.

So the rule this file pins: **once the replayed body is exhausted, the wrapper
must get out of the way and let real client events through.** A disconnect is
not something to invent or swallow -- it is the one message a streaming
response is listening for.

Run: PYTHONPATH=worker python3 tests/worker_hardening_stream_disconnect.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

os.environ.setdefault("KALIV_TOOLS_ENABLED", "1")
os.environ.setdefault("KALIV_WORKER_ALLOW_LAN", "1")
_tmp = tempfile.mkdtemp(prefix="kaliv-hardening-")
os.environ.setdefault("KALIV_TOOLS_DIR", os.path.join(_tmp, "notes"))
os.environ.setdefault("KALIV_AUDIT_DB", os.path.join(_tmp, "audit.db"))

from app.hardening import harden  # noqa: E402

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


SCOPE = {
    "type": "http",
    "method": "POST",
    "path": "/voice/converse/stream",
    "headers": [(b"content-type", b"application/json")],
    "client": ("127.0.0.1", 1234),
    "server": ("127.0.0.1", 8099),
    "query_string": b"",
}


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------
# 1. The body still arrives. Replaying it is the whole point of the wrapper.
# --------------------------------------------------------------------------
async def body_is_replayed() -> bytes:
    seen = bytearray()

    async def app(scope, receive, send):
        while True:
            msg = await receive()
            if msg["type"] != "http.request":
                break
            seen.extend(msg.get("body", b""))
            if not msg.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    sent = [
        {"type": "http.request", "body": b'{"a":', "more_body": True},
        {"type": "http.request", "body": b'1}', "more_body": False},
    ]
    idx = {"i": 0}

    async def receive():
        i = idx["i"]
        idx["i"] += 1
        return sent[i] if i < len(sent) else {"type": "http.disconnect"}

    async def send(_msg):
        return None

    await harden(app)(SCOPE, receive, send)
    return bytes(seen)


check(run(body_is_replayed()) == b'{"a":1}',
      "kroppen leveres uafkortet til app'en (wrapperens egentlige opgave)")


# --------------------------------------------------------------------------
# 2. THE REGRESSION. A streaming response parks on receive() to hear about the
#    client leaving. It must get http.disconnect -- never another http.request.
# --------------------------------------------------------------------------
async def disconnect_reaches_the_stream() -> str:
    outcome = {"value": "never returned"}

    async def app(scope, receive, send):
        # Consume the body exactly as a real route does.
        while True:
            msg = await receive()
            if msg["type"] != "http.request" or not msg.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        # Now behave like StreamingResponse: listen for the client leaving.
        msg = await receive()
        outcome["value"] = msg["type"]

    async def receive():
        # The real client sent its body, then walked away.
        if not hasattr(receive, "_done"):
            receive._done = True  # type: ignore[attr-defined]
            return {"type": "http.request", "body": b"{}", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(_msg):
        return None

    await asyncio.wait_for(harden(app)(SCOPE, receive, send), timeout=10)
    return outcome["value"]

kind = run(disconnect_reaches_the_stream())
check(kind == "http.disconnect",
      f"en streaming-respons faar http.disconnect naar klienten gaar "
      f"(fik {kind!r} -- 'http.request' er praecis rig-fejlen)")


# --------------------------------------------------------------------------
# 3. The wrapper must not invent a disconnect either. While the client is still
#    there, a stream should stay parked -- not be told to shut down.
# --------------------------------------------------------------------------
async def no_phantom_disconnect() -> bool:
    parked = asyncio.Event()
    got = {"msg": None}

    async def app(scope, receive, send):
        while True:
            msg = await receive()
            if msg["type"] != "http.request" or not msg.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        parked.set()
        got["msg"] = await receive()

    async def receive():
        if not hasattr(receive, "_done"):
            receive._done = True  # type: ignore[attr-defined]
            return {"type": "http.request", "body": b"{}", "more_body": False}
        await asyncio.sleep(3600)   # a client that is still listening
        return {"type": "http.disconnect"}

    async def send(_msg):
        return None

    task = asyncio.create_task(harden(app)(SCOPE, receive, send))
    await asyncio.wait_for(parked.wait(), timeout=10)
    await asyncio.sleep(0.3)
    still_waiting = got["msg"] is None
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    return still_waiting


check(run(no_phantom_disconnect()),
      "wrapperen opfinder ikke en frakobling mens klienten stadig lytter")

print(f"\n===== HARDENING STREAM DISCONNECT: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
