"""Voice cloud privacy at the wire: earlier turns never reach a cloud LLM.

Anders' decision (2026-10-26): only the current user utterance may be sent to
the cloud. Earlier voice history must not be included, and the rule is enforced
in the worker, not only in the Android client.

tests/worker_voice_stream.py checks converse() in isolation. This test goes one
level further on both ends: it calls the HTTP endpoints the phone uses and
records the JSON body that would actually leave the rig for the cloud upstream.
A future endpoint that bypasses converse(), or a change in chat_stream() that
adds context, fails here.

Only ASR and TTS are stubbed. The worker's own endpoint, converse(), and
chat_stream() run unmodified; httpx gets a MockTransport instead of a network.
"""
import base64
import json
import os
import sys
import tempfile
import wave

# The SSRF guard resolves the cloud host via DNS. That is unrelated to what is
# tested here and unavailable offline, so the test bypasses it.
os.environ["KALIV_CLOUD_ALLOW_PRIVATE"] = "1"
os.environ["KALIV_WORKER_ALLOW_LAN"] = "1"  # let TestClient past the loopback guard

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main_impl as MAIN  # noqa: E402
from app import voice_pipeline as vp  # noqa: E402
import app.ollama_client as oc  # noqa: E402

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


TRANSCRIPT = "hvad er klokken"
SECRET = "blå elefant 7731"
CLOUD = "https://ollama.com"
HISTORY = [
    {"role": "user", "content": f"Mit lokale kodeord er {SECRET}"},
    {"role": "assistant", "content": f"Jeg husker {SECRET}."},
    {"role": "system", "content": "UNTRUSTED CLIENT SYSTEM PROMPT"},
]


def _silent_wav_b64() -> str:
    path = os.path.join(tempfile.mkdtemp(prefix="voice_wire_"), "in.wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16)
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _write_silent_wav(path):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16)


sent: list[dict] = []


def _handler(request: httpx.Request) -> httpx.Response:
    sent.append({
        "url": str(request.url),
        "authorization": request.headers.get("authorization"),
        "body": json.loads(request.content.decode("utf-8")),
    })
    lines = [
        json.dumps({"message": {"content": "Klokken er tolv."}, "done": False}),
        json.dumps({"message": {"content": ""}, "done": True}),
    ]
    return httpx.Response(200, content=("\n".join(lines) + "\n").encode())


def _install():
    saved = {
        "asr_avail": vp.voice_asr.is_available,
        "tts_avail": vp.voice_tts.is_available,
        "transcribe": vp.voice_asr.transcribe_wav,
        "synth": vp.voice_tts.synthesize_to_wav,
        "client": oc.httpx.AsyncClient,
    }
    vp.voice_asr.is_available = lambda: True
    vp.voice_tts.is_available = lambda: True
    vp.voice_asr.transcribe_wav = lambda path, lang: {"text": TRANSCRIPT, "language": lang}
    vp.voice_tts.synthesize_to_wav = lambda text, wav: _write_silent_wav(wav)
    real_client = saved["client"]
    transport = httpx.MockTransport(_handler)

    def client_factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_client(*args, transport=transport, **kwargs)

    oc.httpx.AsyncClient = client_factory

    def restore():
        vp.voice_asr.is_available = saved["asr_avail"]
        vp.voice_tts.is_available = saved["tts_avail"]
        vp.voice_asr.transcribe_wav = saved["transcribe"]
        vp.voice_tts.synthesize_to_wav = saved["synth"]
        oc.httpx.AsyncClient = saved["client"]

    return restore


def _post(client, route, **extra):
    body = {"audio_base64": _silent_wav_b64(), "language": "da", "history": HISTORY}
    body.update(extra)
    resp = client.post(route, json=body)
    # Drain the NDJSON stream so the pipeline runs to completion.
    _ = resp.content
    return resp


def run():
    restore = _install()
    try:
        client = TestClient(MAIN.app)
        for route in ("/voice/converse/upload", "/voice/converse/stream"):
            print(f"== {route}")

            sent.clear()
            resp = _post(client, route, llm_base_url=CLOUD, llm_api_key="test-only-key")
            check(resp.status_code == 200, f"cloud turn succeeds ({resp.status_code})")
            check(len(sent) == 1, f"exactly one upstream LLM request ({len(sent)})")
            if sent:
                req = sent[0]
                check(req["url"].startswith(CLOUD + "/"), "request goes to the cloud upstream")
                check(req["body"].get("messages") == [{"role": "user", "content": TRANSCRIPT}],
                      "cloud receives only the current transcript")
                check(SECRET not in json.dumps(req["body"], ensure_ascii=False),
                      "no earlier turn text anywhere in the cloud body")
                check("UNTRUSTED" not in json.dumps(req["body"]),
                      "no client-supplied system text in the cloud body")
                check(set(req["body"]) == {"model", "messages", "stream"},
                      "cloud body carries no other context fields")

            # A cloud URL without a key is still a cloud request: same rule.
            sent.clear()
            _post(client, route, llm_base_url=CLOUD)
            if sent:
                check(sent[0]["body"].get("messages") == [{"role": "user", "content": TRANSCRIPT}],
                      "cloud URL without key also sends only the transcript")
            else:
                check(False, "cloud URL without key reached the upstream")

            # Control: the test must be able to see history when it IS sent,
            # otherwise the assertions above could pass vacuously.
            sent.clear()
            _post(client, route)
            if sent:
                msgs = sent[0]["body"].get("messages", [])
                check(not sent[0]["url"].startswith(CLOUD), "local turn stays on the rig")
                check([m["role"] for m in msgs] == ["user", "assistant", "user"],
                      "local turn keeps allowed earlier turns (control)")
                check(all(m["role"] != "system" for m in msgs),
                      "local turn still drops client-supplied system roles")
            else:
                check(False, "local turn reached the upstream")
    finally:
        restore()


if __name__ == "__main__":
    run()
    print(f"\n===== VOICE CLOUD HISTORY WIRE: {passed} passed, {failed} failed =====")
    sys.exit(1 if failed else 0)
