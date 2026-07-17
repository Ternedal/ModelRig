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

# --- egress classes (F-208): where a RESULT may travel ----------------------
# Risk gates the action; sensitivity gates the answer. list_documents is the
# case in one line: a harmless read that hands your document names to whoever
# asked -- including a cloud model, with no card and nothing said out loud.

check(T.may_egress("public"), "public results travel freely")
check(T.may_egress("operational"), "operational results travel (today's documented behaviour)")
check(not T.may_egress("private"), "private needs consent")
check(T.may_egress("private", consent=True), "consent unlocks private")
check(not T.may_egress("secret", consent=True),
      "consent CANNOT unlock a secret -- that is what makes it one")

check(T.REGISTRY["list_documents"].sensitivity == "private",
      "list_documents is private: it returns YOUR document names")
check(T.REGISTRY["current_datetime"].sensitivity == "public", "the clock is public")
check(T.REGISTRY["rig_status"].sensitivity == "operational", "rig state is operational")
check(all(t.sensitivity in ("public", "operational", "private", "secret")
          for t in T.REGISTRY.values()),
      "every registered tool is classified explicitly -- no tool inherits a default nobody chose")

# secret is enforced NOW, though nothing is secret yet: the rule exists before
# the tool that needs it, not after.
vault = T.Tool(name="_audit_probe_vault", description="probe", risk="read",
               sensitivity="secret", run=lambda a: "hunter2")
T.REGISTRY[vault.name] = vault
try:
    g = gate()
    msg = denied(g.propose, vault.name, {}, conversation_id="c9", origin="cloud")
    check(msg is not None and "aldrig" in msg,
          "a secret-returning tool refuses a CLOUD origin, gate flag or not")
    check(last(g).get("outcome") == "blocked", "the refused egress is in the audit")
    out = g.propose(vault.name, {}, conversation_id="c10", origin="local")
    check(out.get("status") == "executed", "the same tool runs fine for a LOCAL model")
finally:
    del T.REGISTRY[vault.name]

# private stays open until Anders decides #6 -- dormant, not silently changed
g = gate()
out = g.propose("list_documents", {}, conversation_id="c11", origin="cloud")
check(out.get("status") == "executed",
      "with the gate off, cloud reads behave exactly as documented today")

os.environ["KALIV_EGRESS_GATE"] = "1"
try:
    g = gate()
    msg = denied(g.propose, "list_documents", {}, conversation_id="c12", origin="cloud")
    check(msg is not None and "samtykke" in msg,
          "with the gate ON, a cloud model is refused your document names")
    check(g.propose("rig_status", {}, conversation_id="c13", origin="cloud").get("status") == "executed",
          "the gate refuses PRIVATE results, not everything -- rig state still answers")
finally:
    os.environ.pop("KALIV_EGRESS_GATE", None)

check(not T.egress_gate_enabled(), "the gate is OFF by default -- #6 is Anders' call, not a quiet default")

# --- pre-approved scheduled writes: the ONE way past a confirmation card ----
# The scheduler cannot park a write for a card at 03:00 -- nobody would answer
# and it would expire before morning. So Anders approves it when he creates the
# schedule, and that approval travels as a fingerprint. This is the narrowest
# door in the system and it gets pushed on from four sides.

from app.scheduler import fingerprint as _fp  # noqa: E402

_args = {"text": "morgenlog"}
_ok = _fp("note_append", _args)

g = gate()
out = g.propose("note_append", _args, conversation_id="sch1", origin="schedule", pre_approved=_ok)
check(out.get("result") is not None,
      "a scheduled write WITH its approval runs -- no card, because there is nobody to show it to")
row = last(g)
check(row.get("outcome") == "executed" and row.get("origin") == "schedule",
      "the run is audited as a scheduled execution")
check(row.get("confirmation_id") == f"schedule:{_ok[:12]}",
      "the audit names the APPROVAL it ran under -- 'who allowed this at 03:00' has an answer")

msg = denied(g.propose, "note_append", {"text": "noget helt andet"},
             conversation_id="sch2", origin="schedule", pre_approved=_ok)
check(msg is not None and "anden handling" in msg,
      "the same approval on different arguments is refused: he approved THAT action")
check(last(g).get("outcome") == "blocked", "and the refused attempt is in the trail")

msg = denied(g.propose, "note_append", _args, conversation_id="sch3",
             origin="cloud", pre_approved=_ok)
check(msg is not None and "planlagte" in msg,
      "a CLOUD model cannot carry a pre-approval -- that would launder a write past its own card")

probe = T.Tool(name="_audit_probe_click2", description="probe", risk="desktop",
               run=lambda a: "clicked")
T.REGISTRY[probe.name] = probe
try:
    msg = denied(g.propose, probe.name, {"x": 1}, conversation_id="sch4",
                 origin="schedule", pre_approved=_fp(probe.name, {"x": 1}))
    check(msg is not None and "forhåndsgodkendes" in msg,
          "a desktop action can never be pre-approved: the screen it would land on does not exist yet")
finally:
    del T.REGISTRY[probe.name]

g.set_enabled(False)
msg = denied(g.propose, "note_append", _args, conversation_id="sch5",
             origin="schedule", pre_approved=_ok)
check(msg is not None, "the kill-switch beats a pre-approval -- schedules are what must stop first")
g.set_enabled(True)

print(f"\n===== WORKER AUDIT: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
