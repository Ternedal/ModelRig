"""The audit log must record every gate outcome -- especially the refusals.

An audit trail that logs what ran but not what was REFUSED is not an audit
trail; it is a success log. For ordinary writes that is already a gap worth
closing, and for the coming desktop actions it is the whole point: when a
click is blocked, expired, or denied, "what was refused, against what, and
why" is exactly what you need to see afterward.

These tests drive the gate through each outcome and assert a row lands with
the right outcome word, the tool's real risk, and the origin -- and that the
confirmation card shows the tool's own risk rather than a hardcoded one.

Run: PYTHONPATH=worker python3 tests/worker_audit.py
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

_tmp = tempfile.mkdtemp(prefix="kaliv-audit-")
os.environ["KALIV_AUDIT_DB"] = os.path.join(_tmp, "audit.db")
os.environ["KALIV_TOOLS_STATE"] = os.path.join(_tmp, "state.json")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_tmp, "docs")

from app import tools as T  # noqa: E402

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def gate() -> T.ToolGate:
    return T.ToolGate(audit=T.AuditLog(os.environ["KALIV_AUDIT_DB"]))


def last(g: T.ToolGate) -> dict:
    rows = g.audit.recent(limit=1)
    return rows[0] if rows else {}


def denied(fn, *a, **k):
    try:
        fn(*a, **k)
        return None
    except T.ToolDenied as e:
        return str(e)


# --- refusals must leave a trace --------------------------------------------

g = gate()
denied(g.propose, "no_such_tool", {}, conversation_id="c1")
row = last(g)
check(row.get("outcome") == "blocked", "an unknown tool is recorded as blocked, not dropped")
check(row.get("tool") == "no_such_tool", "the refused tool is named in the row")

g.set_enabled(False)
denied(g.propose, "rig_status", {}, conversation_id="c2")
check(last(g).get("outcome") == "blocked", "a proposal to a DISABLED tool layer is recorded")
g.set_enabled(True)

g.set_enabled(False, tool="note_append")
denied(g.propose, "note_append", {"text": "x"}, conversation_id="c3")
row = last(g)
check(row.get("outcome") == "blocked", "a disabled single tool is recorded as blocked")
check(row.get("risk") == "write", "the row carries the tool's REAL risk, not a guess")
g.set_enabled(True, tool="note_append")

# --- the human's decision is the interesting part ---------------------------

g = gate()
p = g.propose("note_append", {"text": "audit probe"}, conversation_id="c4")
check(p.get("status") == "confirmation_required", "a write parks for confirmation")
check(p.get("risk") == "write", "the card shows the tool's own risk (not hardcoded)")

g.confirm(p["confirmation_id"], "deny")
row = last(g)
check(row.get("outcome") == "denied",
      "a REFUSED action is recorded -- the whole point of an audit trail")
check(row.get("conversation_id") == "c4", "the refusal is tied to the conversation it came from")

p = g.propose("note_append", {"text": "audit probe 2"}, conversation_id="c5")
g.confirm(p["confirmation_id"], "approve")
check(last(g).get("outcome") == "executed", "an approved action is recorded as executed")

# --- origin is part of the story --------------------------------------------

g = gate()
p = g.propose("note_append", {"text": "from cloud"}, conversation_id="c7", origin="cloud")
check(p.get("origin") == "cloud", "the card says who asked")
check("Cloud-modellen foreslår" in p.get("summary", ""),
      "a cloud suggestion is labelled as one on the card the human approves")
g.confirm(p["confirmation_id"], "deny")
check(last(g).get("origin") == "cloud", "the audit row keeps the origin of a refused action")

# --- the desktop class rides the same rails ---------------------------------

probe = T.Tool(name="_audit_probe_click", description="probe", risk="desktop",
               run=lambda a: "clicked")
T.REGISTRY[probe.name] = probe
try:
    g = gate()
    p = g.propose(probe.name, {"x": 10, "y": 20}, conversation_id="c8")
    check(p.get("status") == "confirmation_required",
          "a desktop action parks for confirmation like a write")
    check(p.get("risk") == "desktop",
          "the card shows risk=desktop -- a click is NOT a write and must not be labelled one")
    g.confirm(p["confirmation_id"], "deny")
    row = last(g)
    check(row.get("outcome") == "denied" and row.get("risk") == "desktop",
          "a refused desktop action lands in the audit with its own risk class")
finally:
    del T.REGISTRY[probe.name]

check(all(t.risk != "desktop" for t in T.REGISTRY.values()),
      "the probe is gone: no real tool declares desktop yet")

print(f"\n===== WORKER AUDIT: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
