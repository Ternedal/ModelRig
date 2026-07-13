"""Agent v2 continuation (#5, 2026-07-13): an approved write no longer dead-ends
the turn -- the model keeps going in the same loop. Two behaviours matter:

  1. After an approved write, the model may CONTINUE (read a tool, then answer).
     The response reports the write it ran AND the tools it used afterwards, so
     the turn stays honest about what happened.
  2. If the continuation proposes ANOTHER write, that write gets its OWN card --
     one approval never authorises a second write. The invariant is preserved
     inside the continuation, not just at the first step.

The model is scripted (oc.chat_tools is replaced), so no Ollama is needed.

Run: PYTHONPATH=worker python3 tests/worker_agent_continue.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["KALIV_TOOLS_ENABLED"] = "1"
os.environ["KALIV_WORKER_ALLOW_LAN"] = "1"  # let TestClient past the loopback middleware
_tmp = tempfile.mkdtemp(prefix="kaliv-continue-")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_tmp, "notes")
os.environ["KALIV_AUDIT_DB"] = os.path.join(_tmp, "audit.db")

from fastapi.testclient import TestClient  # noqa: E402
from app import main  # noqa: E402

_script: list = []
_n = {"i": 0}


async def _fake_chat_tools(messages, tools, model=None, base_url=None, api_key=None):
    i = _n["i"]
    _n["i"] += 1
    if i < len(_script):
        return _script[i]
    return {"content": "Færdig.", "tool_calls": []}


main.oc.chat_tools = _fake_chat_tools
client = TestClient(main.app)

passed = failed = 0


def check(cond, name):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def call(name, args):
    return {"content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


# --- Scenario 1: read AFTER an approved write, then answer ---
_script[:] = [
    call("note_append", {"text": "hej"}),        # /tools/chat: a write -> card
    call("current_datetime", {}),                # continuation: a read
    {"content": "Datoen er noteret.", "tool_calls": []},  # continuation: answer
]
_n["i"] = 0
r1 = client.post("/tools/chat", json={"message": "gem en note og sig mig datoen", "rag": False, "model": "qwen3:14b"})
d1 = r1.json()
check(d1.get("status") == "confirmation_required", "the write parks for a confirmation card")
cid = d1.get("confirmation_id")
check(bool(cid), "the card carries a confirmation_id")

r2 = client.post("/tools/confirm/chat", json={"confirmation_id": cid, "decision": "approve"})
d2 = r2.json()
check(d2.get("status") == "executed", f"approved write ends 'executed' (got {d2.get('status')!r})")
check(d2.get("executed_write") == "note_append", "the executed write is reported")
check("current_datetime" in (d2.get("tools_used") or []),
      f"the chain CONTINUED with a read after the write (tools_used={d2.get('tools_used')})")
check("noteret" in (d2.get("answer") or ""), "and the model produced a final answer")

# --- Scenario 2: a SECOND write in the continuation gets its OWN card ---
_script[:] = [
    call("note_append", {"text": "en"}),   # /tools/chat: first write -> card
    call("note_append", {"text": "to"}),   # continuation: a SECOND write -> must card again
]
_n["i"] = 0
r3 = client.post("/tools/chat", json={"message": "tilføj to noter", "rag": False, "model": "qwen3:14b"})
cid2 = r3.json().get("confirmation_id")
r4 = client.post("/tools/confirm/chat", json={"confirmation_id": cid2, "decision": "approve"})
d4 = r4.json()
check(d4.get("status") == "confirmation_required",
      f"a second write in the continuation gets its OWN card (got {d4.get('status')!r})")
check(d4.get("confirmation_id") and d4.get("confirmation_id") != cid2,
      "it is a new confirmation, not the already-approved one")
check(d4.get("executed_write") == "note_append", "the first, approved write is still reported")

# --- Scenario 3: denial still stops cleanly (no continuation) ---
_script[:] = [call("note_append", {"text": "x"})]
_n["i"] = 0
r5 = client.post("/tools/chat", json={"message": "skriv en note", "rag": False, "model": "qwen3:14b"})
cid3 = r5.json().get("confirmation_id")
r6 = client.post("/tools/confirm/chat", json={"confirmation_id": cid3, "decision": "deny"})
d6 = r6.json()
check(d6.get("status") == "denied", "a denied write does not continue the chain")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
