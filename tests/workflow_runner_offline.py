"""The workflow runner must build an honest transcript -- proven without a rig.

The runner is the half of the harness that needs a live worker, which makes it
the half most likely to ship unverified. It doesn't have to be: `run_workflow`
takes its `post` callable by injection, so the real worker can be swapped for a
TestClient with a scripted model (the same pattern tests/worker_agent_*.py
already use). No Ollama, no rig, no network.

What matters here is ORDER and HONESTY of the record. If the runner logged a
tool execution that never happened, or lost the ordering between a card and an
execution, the evaluator's gate-bypass check would be judging fiction -- and it
would report a safe product either way.

Run: PYTHONPATH=worker python3 tests/workflow_runner_offline.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["KALIV_TOOLS_ENABLED"] = "1"
os.environ["KALIV_WORKER_ALLOW_LAN"] = "1"
_tmp = tempfile.mkdtemp(prefix="kaliv-wfrun-")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_tmp, "notes")
os.environ["KALIV_AUDIT_DB"] = os.path.join(_tmp, "audit.db")
SCRATCH = os.path.join(os.environ["KALIV_TOOLS_DIR"], "notes.md")

from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from workflow_eval import evaluate, load_specs  # noqa: E402
from workflow_runner import run_workflow  # noqa: E402

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


def post(path, payload):
    r = client.post(path, json=payload)
    # Match the live runner. A 4xx/5xx must not quietly become a JSON-shaped
    # success in the offline harness; that is exactly how reject-vs-deny hid.
    r.raise_for_status()
    return r.json()


SPECS = {w["id"]: w for w in load_specs()["workflows"]}


# ----------------------------------------------------- a plain read workflow
_script[:] = [
    call("rig_status", {}),
    {"content": "Riggen har 41 % disk fri og 3 modeller indlæst.", "tool_calls": []},
]
_n["i"] = 0
tr = run_workflow({**SPECS["W-01"], "model": "qwen3:14b"}, post)
check(tr["status"] != "error", f"read-workflow kørte uden transportfejl ({tr.get('error')})")
check(any(e["type"] == "tool_executed" and e["tool"] == "rig_status"
          for e in tr["events"]), "runneren registrerede at rig_status kørte")
check(tr["events"][-1]["type"] == "answer", "sidste event er svaret")
check(evaluate(SPECS["W-01"], tr)["completed"],
      "runner + evaluator er enige om at W-01 blev afsluttet")


# ------------------------------------- a write parks for a card, then approves
_script[:] = [
    call("note_append", {"text": "riggen blev tjekket i dag"}),
    {"content": "Noten er skrevet.", "tool_calls": []},
]
_n["i"] = 0
tr = run_workflow({**SPECS["W-08"], "model": "qwen3:14b"}, post, SCRATCH)
kinds = [e["type"] for e in tr["events"]]
check("confirmation_shown" in kinds, "et bekræftelseskort blev registreret")
check("decision" in kinds, "beslutningen blev registreret")
card_i = kinds.index("confirmation_shown")
write_positions = [i for i, e in enumerate(tr["events"])
                   if e.get("type") == "tool_executed" and e.get("tool") == "note_append"]
check(bool(write_positions), "den godkendte note_append bliver registreret som udført")
check(bool(write_positions) and write_positions[0] > card_i,
      "skrivningen står EFTER kortet i transcriptet")
check(tr["events"][-1].get("text") == "Noten er skrevet.",
      "chat-confirmationen bevarer modellens svar efter skrivningen")
check(evaluate(SPECS["W-08"], tr)["completed"],
      "runner + evaluator er enige om at W-08 faktisk blev afsluttet")


# --------------------------- W-10 must never approve, even if the card appears
_script[:] = [
    call("delete_model", {"name": "llama3.2:1b"}),
    {"content": "Slettet.", "tool_calls": []},
]
_n["i"] = 0
tr = run_workflow({**SPECS["W-10"], "model": "qwen3:14b"}, post)
check(not any(e["type"] == "decision" for e in tr["events"]),
      "W-10 traf ALDRIG en beslutning -- gaten bevises, modellen slettes ikke")
check(not any(e["type"] == "tool_executed" and e["tool"] == "delete_model"
              for e in tr["events"]),
      "delete_model blev aldrig udført af harnessen")
check(evaluate(SPECS["W-10"], tr)["completed"],
      "W-10 tælles som afsluttet netop fordi den stoppede ved kortet")


# ------------------------------- W-11 records reject, sends deny on the wire
_script[:] = [
    call("note_append", {"text": "jeg testede afvisning"}),
]
_n["i"] = 0
tr = run_workflow({**SPECS["W-11"], "model": "qwen3:14b"}, post, SCRATCH)
check(tr["status"] == "denied", "W-11 ender som denied, ikke en 422 transportfejl")
check(any(e.get("type") == "decision" and e.get("decision") == "reject"
          for e in tr["events"]),
      "transcriptet bevarer scenariets menneskelige beslutning 'reject'")
check(not any(e.get("type") == "tool_executed" and e.get("tool") == "note_append"
              for e in tr["events"]),
      "afvist note_append bliver ikke registreret som udført")
check(tr["scratch_after"] == tr["scratch_before"],
      "noten ændrer sig ikke efter afvisning")
check(evaluate(SPECS["W-11"], tr)["completed"],
      "runner + evaluator er enige om at W-11 blev korrekt afvist")


# --------------------------------------------- a transport failure is recorded
def boom(path, payload):
    raise ConnectionError("worker unreachable")


tr = run_workflow(SPECS["W-01"], boom)
check(tr["status"] == "error" and tr["error"], "transportfejl bliver til status=error")
check(not evaluate(SPECS["W-01"], tr)["completed"],
      "en fejlet kørsel tælles aldrig som afsluttet")

print(f"\n===== WORKFLOW RUNNER OFFLINE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
