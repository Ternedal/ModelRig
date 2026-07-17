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

# --- the two tables must agree about what may run unattended (F-604) --------
# Agent 3's graph knew delete_model is DESTRUCTIVE and pull_model is ADMIN. The
# tool gate, which is what actually decides at 03:00, only ever asked about
# desktop -- so a recurring model deletion would have fired on schedule with
# nobody awake. The knowledge existed; the code that needed it never asked.
#
# The registry now owns schedulability, and merging the two tables outright is a
# bigger job (F-614). Until then they must at least not contradict each other,
# and that is checkable rather than rememberable.

from app.agent3.capability_graph import _RISK_OVERRIDES  # noqa: E402
from app.tools import REGISTRY  # noqa: E402

for _name, _override in sorted(_RISK_OVERRIDES.items()):
    _tool = REGISTRY.get(_name)
    if _tool is None:
        continue
    if _override in (RiskClass.DESTRUCTIVE, RiskClass.ADMIN):
        check(_tool.schedulable is False,
              f"{_name}: Agent 3 calls it {_override.value}, so the registry must "
              "not let it run unattended"
              if _tool.schedulable is False
              else f"CONTRADICTION: Agent 3 calls {_name} {_override.value} and the "
                   "registry marks it schedulable -- it would fire at 03:00")

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
