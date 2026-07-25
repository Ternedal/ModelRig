"""A confirmation card must say what KIND of thing it is asking to do.

The card already carried `risk`, and `risk` is too coarse to warn with:
note_append, delete_model and pull_model are all risk=write. Only `impact`
separates "append a line to a note" from "irreversibly remove a model" from
"pull gigabytes over the network".

This was found by measuring, not by reading: the workflow-success harness tried
to assert that a delete_model card announced itself as destructive, and the
field was not on the response at all. The desktop client had been compensating
with a tool-name -> impact table (`riskOf` in KalivScreens.kt), which is a copy
of what the registry already knows and goes stale the moment a tool is added.
A stale copy of a risk classification fails in the direction of "probably
harmless" -- the same failure mode as the `desktop` class that once made a
screenshot look like a READ (see tests/worker_agent3_risk_parity.py).

Run: PYTHONPATH=worker python3 tests/worker_confirmation_impact.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["KALIV_TOOLS_ENABLED"] = "1"
os.environ["KALIV_WORKER_ALLOW_LAN"] = "1"
_tmp = tempfile.mkdtemp(prefix="kaliv-impact-")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_tmp, "notes")
os.environ["KALIV_AUDIT_DB"] = os.path.join(_tmp, "audit.db")

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app import tools as t  # noqa: E402

_script: list = []
_n = {"i": 0}


async def _fake_chat_tools(messages, tools, model=None, base_url=None, api_key=None):
    i = _n["i"]
    _n["i"] += 1
    return _script[i] if i < len(_script) else {"content": "Færdig.", "tool_calls": []}


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


def card_for(tool_name, args):
    _script[:] = [call(tool_name, args)]
    _n["i"] = 0
    r = client.post("/tools/chat", json={"message": "gør det", "rag": False,
                                         "model": "qwen3:14b"})
    return r.json()


# Every tool that can raise a card must state its impact on that card.
registry = {name: tool for name, tool in t.GATE.tools.items()} \
    if hasattr(t.GATE, "tools") else {}

d = card_for("delete_model", {"name": "llama3.2:1b"})
check(d.get("status") == "confirmation_required", "delete_model parkerer for et kort")
check("impact" in d, "kortet BÆRER et impact-felt")
check(d.get("impact") == "destructive",
      f"delete_model annoncerer sig som destructive (fik {d.get('impact')!r})")
check(d.get("risk") == "write", "risk er stadig med og uændret (write)")

d = card_for("pull_model", {"name": "qwen3:14b"})
check(d.get("impact") == "admin",
      f"pull_model annoncerer sig som admin (fik {d.get('impact')!r})")

d = card_for("note_append", {"text": "hej"})
check(d.get("status") == "confirmation_required", "note_append parkerer for et kort")
check(d.get("impact") == "write",
      f"note_append er en almindelig write, ikke destructive (fik {d.get('impact')!r})")

# The point of the field: a client can now tell these apart WITHOUT knowing
# tool names. Three cards, three different impacts, same risk.
impacts = {
    card_for("note_append", {"text": "x"}).get("impact"),
    card_for("delete_model", {"name": "llama3.2:1b"}).get("impact"),
    card_for("pull_model", {"name": "qwen3:14b"}).get("impact"),
}
check(len(impacts) == 3,
      f"tre skrivninger giver tre forskellige impacts -- kortet kan skelnes uden "
      f"værktøjsnavne (fik {sorted(x or '?' for x in impacts)})")

# And it must never be absent, whatever the tool: __post_init__ falls back to risk.
missing = [name for name, tool in (registry or {}).items() if tool.impact is None]
check(not missing, f"intet værktøj i registret har impact=None (fandt {missing})")

print(f"\n===== CONFIRMATION IMPACT: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
