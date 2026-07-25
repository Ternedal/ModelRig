"""The served HTTP surface must not change without someone saying so.

Two things are pinned here, and neither can be checked any other way than by
asking the app what it publishes:

1.  **Route drift.** ROUTE_INVENTORY.md is generated from OpenAPI. A route that
    appears or disappears without regenerating it is a change nobody declared.

2.  **Agent 3 dormancy.** ROADMAP and the readiness page both claim Agent 3 is
    dormant until an operator opts in. That is a claim about the SERVED
    SURFACE, so import graphs and greps cannot verify it -- only the published
    paths can. This test fails if a single `/experimental/agent3` route is
    reachable with the flag off.

Why this file exists at all (Sol, 25/07): "Importgrafer alene kan ikke opdage en
router, som findes men ikke er inkluderet." Measuring the same question three
ways gave three answers -- grep of the decorators in agent3/api.py said 9
routes, walking `app.routes` and reading `.path` said 0 (include_router leaves
`_IncludedRouter` objects with no `.path`), and OpenAPI said 24. Only the last
one is what a client can actually call.

Run: python3 tests/workflow_route_inventory.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "scripts" / "route_inventory.py"
DOC = ROOT / "ROUTE_INVENTORY.md"
sys.path.insert(0, str(ROOT / "scripts"))

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


check(GEN.exists(), "generatoren findes")
check(DOC.exists(), "ROUTE_INVENTORY.md findes")

r = subprocess.run([sys.executable, str(GEN), "--check"],
                   capture_output=True, text=True, cwd=ROOT, timeout=600)
check(r.returncode == 0,
      f"inventaret er ikke driftet fra koden ({r.stderr.strip()[:120]})")

from route_inventory import _surface  # noqa: E402

off = _surface(False)
on = _surface(True)

# --- dormancy: the single most important assertion in this file ------------
leaked = [p for p in off if "agent3" in p or "/experimental/" in p]
check(not leaked,
      f"INGEN agent3/experimental-rute serveres uden flaget (laekket: {leaked[:3]})")

added = sorted(set(on) - set(off))
check(len(added) > 0, f"flaget tilfoejer faktisk ruter ({len(added)})")
check(all(p.startswith("/experimental/") for p in added),
      "hver Agent 3-rute ligger under /experimental/ -- ingen kan rammes ved et uheld")

# The flag must be additive: turning Agent 3 on must not remove or rewrite a
# host route. A dormant draft that mutates the production surface is not dormant.
removed = sorted(set(off) - set(on))
check(not removed,
      f"at taende Agent 3 fjerner ingen host-rute (fjernet: {removed[:3]})")

# --- the surface the desktop/Android clients depend on ---------------------
for p in ("/tools/chat", "/tools/confirm", "/tools/audit", "/healthz"):
    check(p in off, f"{p} serveres i host-overfladen")

# --- the Agent 3 surface the cockpit will be built against ----------------
for p in ("/experimental/agent3/plan",
          "/experimental/agent3/plans/{plan_id}/start",
          "/experimental/agent3/runs/{run_id}/confirm",
          "/experimental/agent3/runs/{run_id}/events"):
    check(p in added, f"{p} findes, naar flaget er sat")

# --- the doc must actually list what was measured --------------------------
text = DOC.read_text(encoding="utf-8")
check(f"{len(off)} ruter" in text, "dokumentet naevner host-antallet der blev maalt")
check(all(f"`{p}`" in text for p in added[:5]),
      "dokumentet lister de foerste Agent 3-ruter der blev maalt")

print(f"\n===== ROUTE INVENTORY: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
