"""V2 and Agent 3 must classify the same tool the same way.

Two layers with their own opinion about what a tool IS will eventually
disagree, and the disagreement will be discovered by a user, not a test. Agent
3 has the finer vocabulary (destructive, admin), which is fine -- refining is
not contradicting. What is not fine is a V2 class that Agent 3 has never heard
of, because the fallback has to guess, and guessing about risk fails in the
direction of "probably harmless".

That already happened. This branch was written before main grew a `desktop`
class in 1.58.52, so integration.py's fallback -- "WRITE if V2 says write, else
READ" -- classified a screenshot as a READ: no confirmation card (core.py only
cards WRITE/DESTRUCTIVE/ADMIN) and allowed inside a proactive background run
(which only refuses non-READ steps). The most dangerous class in the system
became the safest one, in a merge, silently.

Run: PYTHONPATH=worker python3 tests/worker_agent3_risk_parity.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import typing

_tmp = tempfile.mkdtemp(prefix="kaliv-parity-")
os.environ.setdefault("KALIV_AUDIT_DB", os.path.join(_tmp, "a.db"))
os.environ.setdefault("KALIV_TOOLS_STATE", os.path.join(_tmp, "s.json"))
os.environ.setdefault("KALIV_JOBS_DB", os.path.join(_tmp, "j.db"))
os.environ.setdefault("KALIV_TOOLS_DIR", _tmp)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app import tools as V2  # noqa: E402
from app.agent3.core import RiskClass, Sensitivity  # noqa: E402
from app.agent3.integration import _SENSITIVITY, _V2_RISK  # noqa: E402

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


# --- every V2 vocabulary word must exist in Agent 3's ------------------------

v2_risks = set(typing.get_args(V2.Risk))
check(v2_risks == {"read", "write", "desktop"},
      f"V2's risk vocabulary is {sorted(v2_risks)}")
missing = sorted(v2_risks - set(_V2_RISK))
check(not missing,
      "every V2 risk class maps into Agent 3"
      if not missing
      else f"UNMAPPED -- Agent 3 would have to guess: {missing}")

v2_sens = set(typing.get_args(V2.Sensitivity))
a3_sens = {s.value for s in Sensitivity}
missing_s = sorted(v2_sens - a3_sens)
check(not missing_s,
      "every V2 sensitivity class exists in Agent 3"
      if not missing_s
      else f"UNKNOWN TO AGENT 3: {missing_s}")

# Sensitivity was the same disease as risk, one axis over (F-511). It fell back
# to PRIVATE, which LOOKS conservative: secret is stricter, so a tool declared
# secret in V2 and unknown to Agent 3's table would be downgraded to private --
# and private can leave the machine once the egress gate is on.
from app.agent3.integration import _V2_SENSITIVITY  # noqa: E402

unmapped_s = sorted(v2_sens - set(_V2_SENSITIVITY))
check(not unmapped_s,
      "every V2 sensitivity class maps into Agent 3"
      if not unmapped_s
      else f"UNMAPPED -- a fallback would pick one: {unmapped_s}")
check(_V2_SENSITIVITY["secret"] == Sensitivity.SECRET,
      "secret maps to SECRET -- not to PRIVATE, which is what a fallback gave it")
for _name, _s in (("public", Sensitivity.PUBLIC), ("operational", Sensitivity.OPERATIONAL),
                  ("private", Sensitivity.PRIVATE)):
    check(_V2_SENSITIVITY[_name] == _s, f"{_name} maps to {_s.value}")

check(RiskClass.DESKTOP.value == "desktop",
      "Agent 3 knows the desktop class -- it did not, and a click read as a READ")

# --- the mapping must never downgrade ---------------------------------------

check(_V2_RISK["read"] == RiskClass.READ, "read maps to READ")
check(_V2_RISK["write"] == RiskClass.WRITE, "write maps to WRITE")
check(_V2_RISK["desktop"] == RiskClass.DESKTOP,
      "desktop maps to DESKTOP -- not to READ, which is what it did")

# --- and the classification must not contradict the registry ----------------

for name, tool in sorted(V2.REGISTRY.items()):
    declared = _SENSITIVITY.get(name)
    if declared is not None:
        check(declared.value == tool.sensitivity,
              f"{name}: Agent 3 and the registry agree it is {tool.sensitivity}")

# --- the consequences, driven directly --------------------------------------

from app.agent3.core import AgentStep  # noqa: E402

step = AgentStep(tool="_probe_click", args={}, risk=RiskClass.DESKTOP,
                 sensitivity=Sensitivity.PRIVATE, summary="klik")
carded = step.risk in {RiskClass.WRITE, RiskClass.DESTRUCTIVE, RiskClass.ADMIN,
                       RiskClass.DESKTOP}
check(carded, "a DESKTOP step requires a confirmation card, like a write")
check(step.risk != RiskClass.READ,
      "a DESKTOP step is refused in a proactive run (that check refuses non-READ)")

# --- every classifier, not just the one I edited ---------------------------
# The 1.58.66 fix changed integration.py and declared F-303 closed.
# capability_graph.py carried the identical downgrade, untouched, because this
# test had exactly the same blind spot as the fix: it read one table. The graph
# is what tells a planner and a human what an action IS, so a desktop tool
# reading as a READ there is the same bug in a more visible place.

from app.agent3.capability_graph import ToolCapability  # noqa: E402

for declared, expected in (("read", RiskClass.READ), ("write", RiskClass.WRITE),
                           ("desktop", RiskClass.DESKTOP)):
    cap = ToolCapability(name=f"probe_{declared}", enabled=True,
                         declared_risk=declared, description="")
    check(cap.risk == expected,
          f"capability graph: a {declared!r} tool is {expected.value}"
          if cap.risk == expected
          else f"capability graph DOWNGRADES {declared!r} to {cap.risk.value}")

try:
    ToolCapability(name="p", enabled=True, declared_risk="teleport", description="").risk
    check(False, "the graph must refuse a class it does not know, not guess")
except ValueError as exc:
    check("gætter ikke" in str(exc),
          "an unknown risk class STOPS the graph rather than becoming a READ")

# One table, not one per file.
import inspect  # noqa: E402

from app.agent3 import capability_graph as _cg  # noqa: E402

src = inspect.getsource(_cg)
check("_V2_RISK" in src,
      "the graph reads the shared mapping instead of keeping its own opinion")
check("if self.declared_risk ==" not in src,
      "and the inline 'write else read' guess is gone from the graph")

# --- there is one owner, and no second table may appear (F-614) ------------
# Three hours ago this block required two tables to agree. That was a bandage:
# the truth about delete_model lived in tools.py (coarse), in integration.py
# (a name-keyed table), and in capability_graph.py (a byte-identical copy of the
# same name-keyed table) -- and the gate that decides at 03:00 consulted none of
# them, which is how a model deletion became schedulable (F-604).
#
# Now the tool declares it. The copies are gone. So this test no longer checks
# agreement -- it checks that there is nothing left to agree WITH, because the
# next name-keyed table will be added by someone who has a good reason and does
# not know this history.

import pathlib as _pl  # noqa: E402

from app.tools import REGISTRY  # noqa: E402

_AGENT3 = _pl.Path(__file__).resolve().parents[1] / "worker" / "app" / "agent3"
for _src in sorted(_AGENT3.rglob("*.py")):
    _text = _src.read_text(encoding="utf-8")
    check("_RISK_OVERRIDES" not in _text,
          f"{_src.name}: no name-keyed risk table -- the tool declares what it does"
          if "_RISK_OVERRIDES" not in _text
          else f"{_src.name} has grown a second owner for tool risk; that is how "
               "delete_model became schedulable")

# The registry's vocabulary and Agent 3's must stay in step: every Impact value
# must map, or a class the registry grows becomes unclassifiable at runtime
# rather than at import.
import typing as _ty  # noqa: E402

from app.agent3.integration import _V2_RISK  # noqa: E402
from app.tools import Impact as _Impact  # noqa: E402

for _member in _ty.get_args(_Impact):
    check(_member in _V2_RISK,
          f"Agent 3 can name the registry's '{_member}'"
          if _member in _V2_RISK
          else f"the registry declares '{_member}' and Agent 3 cannot name it -- "
               "a plan using it would stop at runtime")

# What each dangerous tool IS, asserted here and nowhere else.
#
# The version of this block I wrote three hours ago iterated _RISK_OVERRIDES and
# therefore asserted, as a side effect, that delete_model is destructive. When I
# deleted that table I replaced the loop with "no second table exists" and
# dropped the claim about CONTENT without noticing. A mutation caught it:
# removing impact="destructive" from the registry failed zero tests, and
# delete_model quietly became a plain write.
#
# That is the same move as fixing one file of three and calling the finding
# closed, performed on a test whose entire job is to catch that move. Hence:
# state the facts, not the shape of the code that holds them.
for _name, _want in (("delete_model", "destructive"), ("pull_model", "admin")):
    _t = REGISTRY[_name]
    check(_t.impact == _want,
          f"{_name} declares impact={_want}"
          if _t.impact == _want
          else f"{_name} declares impact={_t.impact!r}, not {_want!r} -- Agent 3 "
               "would classify it as an ordinary write")

# The contradiction must be unrepresentable, not merely absent.
from app.tools import Tool as _Tool  # noqa: E402

try:
    _Tool(name="probe", risk="write", description="x",
          impact="destructive", schedulable=True)
    check(False, "a destructive schedulable tool could be CONSTRUCTED")
except ValueError:
    check(True, "a destructive tool cannot be constructed schedulable -- the "
                "policy is not a check someone remembers to run")

check(REGISTRY["note_append"].schedulable is True,
      "the tool the scheduler exists FOR is still schedulable -- a policy that "
      "blocks everything is not a policy")
check(REGISTRY["delete_model"].schedulable is False, "delete_model cannot be scheduled")
check(REGISTRY["pull_model"].schedulable is False, "pull_model cannot be scheduled")
check(REGISTRY["cancel_job"].schedulable is False, "cancel_job cannot be scheduled")

for _n, _t in REGISTRY.items():
    if not _t.schedulable:
        check(bool(_t.unschedulable_because),
              f"{_n}: says WHY it cannot be scheduled, so the refusal is actionable")

print(f"\n===== AGENT3 RISK PARITY: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
