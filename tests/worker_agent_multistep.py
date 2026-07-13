"""Multi-step agent loop (Agent v2, 2026-07-13).

The turn may now CHAIN read tools -- but the boundary that must not move is that
a WRITE tool still stops the turn for a confirmation card, never executing inside
the loop. These tests drive /tools/chat with a scripted model (oc.chat_tools
stubbed) so no Ollama is needed, and assert:

  1. read tools chain: two reads run, then the model answers.
  2. a write parks: delete_model returns confirmation_required and is NOT run.
  3. the loop is bounded: a model that only ever calls a tool stops after
     TOOL_MAX_STEPS and still terminates with an answer.

Run: PYTHONPATH=worker python3 tests/worker_agent_multistep.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["KALIV_TOOLS_ENABLED"] = "1"
os.environ["KALIV_WORKER_ALLOW_LAN"] = "1"  # let TestClient past the loopback guard
os.environ.pop("KALIV_ALLOW_RAG_CLOUD", None)
_tmp = tempfile.mkdtemp(prefix="kaliv-multistep-")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_tmp, "notes")
os.environ["KALIV_AUDIT_DB"] = os.path.join(_tmp, "audit.db")

from fastapi.testclient import TestClient  # noqa: E402
from app import main  # noqa: E402

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


def call(name, args=None):
    return {"tool_calls": [{"function": {"name": name, "arguments": args or {}}}], "content": ""}


def answer(text):
    return {"tool_calls": [], "content": text}


def script(responses):
    """Make oc.chat_tools return each response in turn (then default to an answer)."""
    seq = list(responses)

    async def _mock(*a, **k):
        return seq.pop(0) if seq else answer("done")

    main.oc.chat_tools = _mock


def chat(msg="hej"):
    return client.post("/tools/chat", json={"message": msg, "model": "qwen3:14b"})


# 1. Read tools chain: current_datetime -> list_models -> answer.
script([call("current_datetime"), call("list_models"), answer("her er svaret")])
d = chat().json()
check(d.get("tools_used") == ["current_datetime", "list_models"],
      f"chains two read tools in order (got {d.get('tools_used')})")
check(d.get("status") == "answered", "ends 'answered' after the read chain")

# 2. A write parks: delete_model must return a confirmation card, not run.
script([call("delete_model", {"name": "qwen3:14b"})])
d = chat().json()
check(d.get("status") == "confirmation_required", "write tool parks for confirmation")
check("delete_model" not in (d.get("tools_used") or []),
      "parked write is NOT counted as executed")

# 3. Bounded loop: a model that always calls a read stops at TOOL_MAX_STEPS.
async def _always_read(*a, **k):
    return call("current_datetime")


main.oc.chat_tools = _always_read
d = chat().json()
check(d.get("steps_exhausted") is True, "loop is bounded by TOOL_MAX_STEPS")
check(len(d.get("tools_used") or []) == main.TOOL_MAX_STEPS,
      f"ran exactly TOOL_MAX_STEPS ({main.TOOL_MAX_STEPS}) reads, then stopped")
check(d.get("status") == "answered", "still terminates with an answer")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
