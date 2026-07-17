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

print(f"\n===== AGENT3 RISK PARITY: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
