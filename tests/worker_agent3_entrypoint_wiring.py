"""The PRODUCTION entrypoint must own agent3's wiring -- proven from outside.

Found by the sandbox rehearsal: mount_agent3 existed and was suite-tested by
DIRECT calls, while nothing the documented entrypoint (uvicorn
app.entrypoint:app) runs ever called it. The live probe answered 404 with the
feature flag set -- which would have killed the campaign's agent3 and
model_eval slots on rig day. The trap was paper validation: every suite
exercised the router by constructing it in-process, so no test noticed that
production never mounted it.

These checks therefore run the entrypoint IMPORT in a fresh subprocess, the
same way uvicorn does, and ask the app's route table -- never mount_agent3
directly. If someone unwires the entrypoint again, this suite goes red.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

passed = 0
failed = 0


def check(cond: bool, label: str) -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


# The app's route list holds _IncludedRouter CONTAINERS (a local include
# mechanism), so naive .path iteration sees nothing inside them -- the first
# probe draft "proved" mounted routes absent. openapi() flattens everything
# and is the same truth the live /openapi.json serves.
PROBE = (
    "import app.entrypoint as e;"
    "paths = sorted(e.fastapi_app.openapi()['paths']);"
    "print('\\n'.join(paths))"
)

# F-1510: openapi() collapses duplicate (method, path) pairs, so it CANNOT
# reveal FastAPI first-match shadowing -- exactly the failure where the bare
# planner (131) silently shadowed the rich one. It also cannot show whether
# the mounted planner actually received its plan_store / memory_store /
# graph provider, or is running on silent :memory: defaults. This probe
# walks the REAL route table (not openapi) for duplicate method+path pairs,
# and reads app.state for the concrete injected dependencies mount installs.
SEMANTIC_PROBE = r"""
import json
import app.entrypoint as e
app = e.fastapi_app

# This FastAPI version stores includes as _IncludedRouter CONTAINERS in
# app.routes -- the real routes live in each container's original_router.
# openapi() flattens them (and collapses duplicates), so to SEE first-match
# shadowing we must walk the containers ourselves and count (method, path).
def all_pairs(application):
    pairs = []
    for rt in application.routes:
        if type(rt).__name__ == "_IncludedRouter":
            orig = getattr(rt, "original_router", None)
            if orig is not None:
                for sub in getattr(orig, "routes", []):
                    p = getattr(sub, "path", None)
                    for m in (getattr(sub, "methods", None) or set()):
                        if p is not None:
                            pairs.append(m + " " + p)
        else:
            p = getattr(rt, "path", None)
            for m in (getattr(rt, "methods", None) or set()):
                if p is not None:
                    pairs.append(m + " " + p)
    return pairs

pairs = all_pairs(app)
seen = {}
dups = []
for k in pairs:
    if k in seen:
        dups.append(k)
    seen[k] = 1

st = app.state
mem = getattr(st, "agent3_memory_store", None)
orch = getattr(st, "agent3_orchestrator", None)
replan = getattr(st, "agent3_replan_preview_service", None)
paths = set(app.openapi()["paths"])
print(json.dumps({
    "duplicate_pairs": sorted(set(dups)),
    "total_pairs": len(pairs),
    "has_memory_store": type(mem).__name__ if mem is not None else None,
    "has_orchestrator": type(orch).__name__ if orch is not None else None,
    "has_replan_service": type(replan).__name__ if replan is not None else None,
    "plan_start_route": "/experimental/agent3/plans/{plan_id}/start" in paths,
    "capability_receipt_route":
        "/experimental/agent3/runs/{run_id}/capability-receipt" in paths,
}))
"""


def entrypoint_routes(agent3_flag: str, tmp: str) -> list[str]:
    """Import the production entrypoint in a clean interpreter; return paths."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "worker")
    env["KALIV_AGENT3_ENABLED"] = agent3_flag
    # Explicit opt-in owns its resources; the probe must not touch real stores.
    for var, name in (("KALIV_AGENT3_DB", "a3.db"),
                      ("KALIV_AGENT3_REVIEW_DB", "a3r.db"),
                      ("KALIV_AGENT3_REPLAN_DB", "a3p.db"),
                      ("KALIV_SCHEDULES_DB", "s.db"),
                      ("MODELRIG_JOBS_DB", "j.db"),
                      ("KALIV_AUDIT_DB", "au.db")):
        env[var] = str(Path(tmp) / name)
    env.pop("KALIV_SCHEDULER", None)  # the lifespan hook must stay inert here
    proc = subprocess.run(
        [sys.executable, "-c", PROBE],
        capture_output=True, text=True, timeout=120, env=env, cwd=tmp,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"entrypoint import failed (flag={agent3_flag}):\n{proc.stderr[-800:]}")
    return proc.stdout.splitlines()


with tempfile.TemporaryDirectory() as td:
    routes_on = entrypoint_routes("1", td)
    check(all(p in routes_on for p in (
        "/experimental/agent3/memory",
        "/experimental/agent3/memory/context-preview",
        "/experimental/agent3/memory/{memory_id}")),
          "the memory surface the rig-evidence harness calls is mounted by "
          "the production entrypoint -- third orphaned router (mount -> "
          "planner -> memory), found by auditing the harness' complete "
          "route contract")
    check(all(p in routes_on for p in (
        "/experimental/agent3/capabilities",
        "/experimental/agent3/runs/{run_id}/replan-preview",
        "/experimental/agent3/replan-previews/{preview_id}/apply",
        "/experimental/agent3/runs/{run_id}/answer-preview",
        "/experimental/agent3/runs/{run_id}/capability-receipt")),
      "the full Android-app contract plus runner parity is mounted -- "
      "fourth/fifth orphans: the capabilities screen and the replan-preview "
      "flow 404'ed in production while dev's richer includes worked, and "
      "the bare planner (131) silently shadowed the rich one in dev; the "
      "mount is now the ONE owner, so dev serves exactly what production "
      "serves")
    check("/experimental/agent3/status" in routes_on,
          "with the flag ON, the documented entrypoint serves agent3 status "
          "-- the exact route the campaign's model_eval slot calls through "
          "the backend")
    check("/experimental/agent3/runs" in routes_on,
          "and the runs surface production agent3 lives on")
    check("/experimental/agent3/plan" in routes_on
          and "/experimental/agent3/plans/{plan_id}/start" in routes_on,
          "and the DOCUMENTED production creation path (/plan followed by "
          "the single-use /plans/{id}/start) -- an earlier version of this "
          "check asserted /plan's ABSENCE, encoding a misdiagnosis: the "
          "planner router existed with exactly these routes and was simply "
          "never included by anything, the same orphaned-wiring failure as "
          "the mount itself. Client-authored plans (POST /runs) remain the "
          "F-608 fixture and stay unmounted here")
    check("/schedules" in routes_on,
          "the schedule admin API is mounted alongside (harness sanity)")

    # F-1510: semantic wiring, not just URL presence. Run the semantic probe
    # through the SAME production entrypoint and assert on the route table
    # and the concrete injected dependencies.
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "worker")
    env["KALIV_AGENT3_ENABLED"] = "1"
    for var, name in (("KALIV_AGENT3_DB", "a3.db"),
                      ("KALIV_AGENT3_REVIEW_DB", "a3r.db"),
                      ("KALIV_AGENT3_REPLAN_DB", "a3p.db"),
                      ("KALIV_AGENT3_MEMORY_DB", "a3m.db"),
                      ("KALIV_AGENT3_PLAN_DB", "a3pl.db"),
                      ("KALIV_SCHEDULES_DB", "s.db"),
                      ("MODELRIG_JOBS_DB", "j.db"),
                      ("KALIV_AUDIT_DB", "au.db")):
        env[var] = str(Path(td) / name)
    env.pop("KALIV_SCHEDULER", None)
    _p = subprocess.run([sys.executable, "-c", SEMANTIC_PROBE],
                        capture_output=True, text=True, timeout=120,
                        env=env, cwd=td)
    if _p.returncode != 0:
        raise AssertionError(f"semantic probe failed:\n{_p.stderr[-800:]}")
    import json as _json
    facts = _json.loads(_p.stdout.strip().splitlines()[-1])
    check(not facts["duplicate_pairs"] and facts["total_pairs"] > 10,
          "no duplicate (method, path) pair in the REAL route table, walked "
          "through the _IncludedRouter containers openapi flattens -- this "
          "is the ONLY lens that catches the first-match shadowing that hid "
          "the bare planner over the rich one in 135 (F-1510)")
    # Self-test: the detector must be able to FAIL, or "no duplicates" proves
    # nothing. Include the same route twice and confirm it is caught.
    _selftest = subprocess.run(
        [sys.executable, "-c",
         "from fastapi import FastAPI, APIRouter\n"
         "a=FastAPI()\n"
         "r1=APIRouter(prefix='/z')\n"
         "@r1.post('/dup')\n"
         "def f1(): return {}\n"
         "r2=APIRouter(prefix='/z')\n"
         "@r2.post('/dup')\n"
         "def f2(): return {}\n"
         "a.include_router(r1); a.include_router(r2)\n"
         "pairs=[]\n"
         "for rt in a.routes:\n"
         "    if type(rt).__name__=='_IncludedRouter':\n"
         "        o=getattr(rt,'original_router',None)\n"
         "        if o:\n"
         "            for s in getattr(o,'routes',[]):\n"
         "                p=getattr(s,'path',None)\n"
         "                for m in (getattr(s,'methods',None) or set()):\n"
         "                    if p: pairs.append(m+' '+p)\n"
         "seen={}; dups=[]\n"
         "for k in pairs:\n"
         "    if k in seen: dups.append(k)\n"
         "    seen[k]=1\n"
         "print('DUP' if dups else 'NONE')\n"],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, 'PYTHONPATH': str(ROOT / 'worker')})
    check(_selftest.returncode == 0 and "DUP" in _selftest.stdout,
          "the shadowing detector itself catches a deliberately duplicated "
          "route -- so a clean result above is meaningful, not vacuous "
          "(F-1510 self-test)")
    check(facts["has_memory_store"] == "MemoryStore"
          and facts["has_orchestrator"] is not None
          and facts["has_replan_service"] is not None,
          "the mount installs the CONCRETE dependencies on app.state (real "
          "MemoryStore, orchestrator, replan service) -- URL presence alone "
          "cannot prove the handlers got their stores (F-1510)")
    check(facts["plan_start_route"] and facts["capability_receipt_route"],
          "the rich planner's plan-persistence and capability-receipt routes "
          "are present -- they exist ONLY when build_planner_router received "
          "its plan_store and graph provider, so this proves the rich "
          "planner won, not the bare default (F-1510)")

with tempfile.TemporaryDirectory() as td:
    routes_off = entrypoint_routes("0", td)
    check(not any(p.startswith("/experimental/agent3") for p in routes_off),
          "with the flag OFF, no agent3 route exists -- the mount is a "
          "no-op, exactly the explicit-opt-in contract the entrypoint "
          "documents")
    check("/schedules" in routes_off,
          "while the rest of the entrypoint is untouched")

print(f"\n===== AGENT3 ENTRYPOINT WIRING: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
