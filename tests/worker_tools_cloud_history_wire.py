"""Text cloud privacy at the wire: earlier turns never reach a cloud LLM.

Anders' decision (2026-10-26, #2275): only the current user message may be sent
to Ollama Cloud, for text as for voice. The rig enforces it for every text turn
that passes through it: /tools/chat and /tools/chat/stream (the phone's and the
desktop's tools mode, and cloud+tools always routes through the rig).

The worker's endpoint, _tools_chat_turn() and oc.chat_tools() run unmodified;
httpx gets a MockTransport, so the test records the JSON body that would leave
the rig. A local control turn proves the test sees history when it is sent.

Out of scope here and covered elsewhere: voice (worker_voice_cloud_history_wire),
RAG document content (worker_rag_cloud, D4 consent), and the clients' direct
cloud calls, which never touch the rig (Android CloudClient, desktop ChatRouter).
"""
import json
import os
import sys
import tempfile

os.environ["KALIV_TOOLS_ENABLED"] = "1"
os.environ["KALIV_WORKER_ALLOW_LAN"] = "1"  # let TestClient past the loopback guard
# The SSRF guard resolves the cloud host via DNS: unrelated here, unavailable offline.
os.environ["KALIV_CLOUD_ALLOW_PRIVATE"] = "1"
_tmp = tempfile.mkdtemp(prefix="kaliv-tools-cloud-history-")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_tmp, "notes")
os.environ["KALIV_AUDIT_DB"] = os.path.join(_tmp, "audit.db")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main_impl as MAIN  # noqa: E402
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


CLOUD = "https://ollama.com"
SECRET = "blå elefant 7731"
CURRENT = "hvad er klokken"
HISTORY = [
    {"role": "user", "content": f"Mit lokale kodeord er {SECRET}"},
    {"role": "assistant", "content": f"Jeg husker {SECRET}."},
    {"role": "system", "content": "REPLAYED MID-CONVERSATION SYSTEM"},
    {"role": "user", "content": "og så noget mere privat"},
]

sent: list[dict] = []


def _handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content.decode("utf-8"))
    sent.append({"url": str(request.url), "body": body})
    if body.get("stream"):
        lines = [json.dumps({"message": {"content": "Klokken er tolv."}, "done": True})]
        return httpx.Response(200, content=("\n".join(lines) + "\n").encode())
    return httpx.Response(200, json={"message": {"content": "Klokken er tolv."}, "done": True})


real_client = oc.httpx.AsyncClient
transport = httpx.MockTransport(_handler)


def client_factory(*args, **kwargs):
    kwargs.pop("transport", None)
    return real_client(*args, transport=transport, **kwargs)


def non_system(body):
    return [m for m in body.get("messages", []) if m.get("role") != "system"]


def run():
    oc.httpx.AsyncClient = client_factory
    try:
        client = TestClient(MAIN.app)
        cases = [
            ("cloud URL + key", {"cloud_base_url": CLOUD, "cloud_key": "test-only-key"}),
            ("cloud URL without key", {"cloud_base_url": CLOUD}),
        ]
        for route in ("/tools/chat", "/tools/chat/stream"):
            print(f"== {route}")
            for label, extra in cases:
                sent.clear()
                resp = client.post(route, json={"message": CURRENT, "history": HISTORY,
                                                "model": "kimi-k2.6", **extra})
                _ = resp.content  # drain a stream
                check(resp.status_code == 200, f"{label}: turn succeeds ({resp.status_code})")
                check(len(sent) >= 1, f"{label}: an upstream request was made ({len(sent)})")
                for i, req in enumerate(sent):
                    check(req["url"].startswith(CLOUD + "/"), f"{label}: request {i} goes to the cloud")
                    check(non_system(req["body"]) == [{"role": "user", "content": CURRENT}],
                          f"{label}: request {i} carries only the current user message")
                    dumped = json.dumps(req["body"], ensure_ascii=False)
                    check(SECRET not in dumped and "privat" not in dumped,
                          f"{label}: request {i} has no earlier turn text anywhere")
                    check("REPLAYED" not in dumped,
                          f"{label}: request {i} has no replayed system text")

            # A legacy persona at the head of history is an instruction, not a turn.
            sent.clear()
            resp = client.post(route, json={
                "message": CURRENT, "model": "kimi-k2.6", "cloud_base_url": CLOUD,
                "cloud_key": "k",
                "history": [{"role": "system", "content": "LEGACY PERSONA"}] + HISTORY,
            })
            _ = resp.content
            if sent:
                msgs = sent[0]["body"]["messages"]
                check(any(m["role"] == "system" and m["content"] == "LEGACY PERSONA" for m in msgs),
                      "cloud: a leading legacy persona is kept as an instruction")
                check(non_system(sent[0]["body"]) == [{"role": "user", "content": CURRENT}],
                      "cloud: still only the current user message besides instructions")
            else:
                check(False, "cloud with legacy persona reached the upstream")

            # Control: a local turn keeps history, so the checks above are not vacuous.
            sent.clear()
            resp = client.post(route, json={"message": CURRENT, "history": HISTORY,
                                            "model": "hermes3:8b"})
            _ = resp.content
            if sent:
                check(not sent[0]["url"].startswith(CLOUD), "local turn stays on the rig")
                turns = non_system(sent[0]["body"])
                check(len(turns) == 5 and turns[-1]["content"] == CURRENT,
                      f"local turn keeps earlier turns (control, {len(turns)} turns)")
            else:
                check(False, "local turn reached the upstream")
    finally:
        oc.httpx.AsyncClient = real_client


if __name__ == "__main__":
    run()
    print(f"\n===== TOOLS CLOUD HISTORY WIRE: {passed} passed, {failed} failed =====")
    sys.exit(1 if failed else 0)
