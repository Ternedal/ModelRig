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
