"""The scheduler pilot must be able to recognise the plan it asked for.

Found on the rig 26/07 after five attempts: the pilot printed

    Android: godkend den ene kanoniske write-plan
      note_append · {"text":"pilot"} · every:60 · max_runs=2 · ttl_days=1

waited fifteen minutes, and gave up -- every single time. The operator created
exactly that plan. It was approved, it ran both of its two permitted runs, and
it disabled itself when the budget was spent. Textbook T-019 behaviour.

The pilot could not see it, and never could have. `matches_manifest` required

    int(row.get("ttl_days") or -1) == int(spec["ttl_days"])

but `ttl_days` is not part of a schedule. It is a CREATION ARGUMENT: the store
uses it once to compute `expires_at = now + ttl_days * 86400` and then forgets
it (`scheduler.py:447`). No schedule row has ever carried the field, so
`row.get("ttl_days")` returned None, `-1 == 1` was False, and the match failed
for every plan that could ever exist.

The fix checks what is actually observable. `expires_at` is the thing that
matters operationally anyway: it is when the standing write grant dies. A plan
that expires a day out is the one the pilot asked for; one that expires in
ninety days is a materially different grant, and that is the confusion worth
catching.

Run: PYTHONPATH=worker python3 tests/worker_scheduler_pilot_manifest.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import importlib.util  # noqa: E402
import types  # noqa: E402

# The wizard lives as a .retained file, so spec_from_file_location will not
# infer a loader from the suffix. Name it explicitly.
_src = (ROOT / "scripts" / "scheduler_pilot_wizard.retained").read_text(encoding="utf-8")
pilot = types.ModuleType("pilot_wizard")
pilot.__dict__["__file__"] = str(ROOT / "scripts" / "scheduler_pilot_wizard.retained")
exec(compile(_src, "scheduler_pilot_wizard.retained", "exec"), pilot.__dict__)

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


NOW = time.time()


def row(**over):
    """A schedule row exactly as the worker serialises it -- no ttl_days."""
    base = {
        "schedule_id": "18cd6b9e9beb",
        "tool": "note_append",
        "args": {"text": "pilot"},
        "cadence": "every:60",
        "timezone": "Europe/Copenhagen",
        "misfire_policy": "run_once",
        "max_runs": 2,
        "runs_used": 2,
        "expires_at": NOW + 86400,      # ttl_days=1, as created
        "enabled": False,               # budget spent, disabled itself
    }
    base.update(over)
    return base


# --------------------------------------------------- THE REGRESSION
check(pilot.matches_manifest(row(), pilot.WRITE_SPEC),
      "den kanoniske plan GENKENDES -- den kunne ikke foer, fordi matcheren "
      "kraevede et ttl_days-felt som ingen schedule har baaret")

check(pilot.matches_manifest(row(runs_used=0, enabled=True), pilot.WRITE_SPEC),
      "en frisk, aktiv plan genkendes ogsaa -- budgettet er ikke en del af "
      "identiteten")


# ------------------------------------------- it must still reject the wrong plan
check(not pilot.matches_manifest(row(tool="rig_status"), pilot.WRITE_SPEC),
      "forkert vaerktoej afvises")
check(not pilot.matches_manifest(row(args={"text": "andet"}), pilot.WRITE_SPEC),
      "forkerte argumenter afvises")
check(not pilot.matches_manifest(row(cadence="daily:08:00"), pilot.WRITE_SPEC),
      "forkert kadence afvises")
check(not pilot.matches_manifest(row(max_runs=99), pilot.WRITE_SPEC),
      "forkert budget afvises")
check(not pilot.matches_manifest(row(timezone="UTC"), pilot.WRITE_SPEC),
      "forkert tidszone afvises")
check(not pilot.matches_manifest(row(misfire_policy="skip"), pilot.WRITE_SPEC),
      "forkert misfire-politik afvises")


# ---------------------------------- the point of the TTL check, kept meaningful
check(not pilot.matches_manifest(row(expires_at=NOW + 90 * 86400), pilot.WRITE_SPEC),
      "en 90-DAGES staaende skrivetilladelse afvises -- det er en materielt "
      "anden bevilling end den piloten bad om, og praecis den forveksling "
      "TTL-tjekket findes for at fange")

check(not pilot.matches_manifest(row(expires_at=NOW - 3600), pilot.WRITE_SPEC),
      "en allerede udloebet bevilling afvises")

check(pilot.matches_manifest(row(expires_at=NOW + 82000), pilot.WRITE_SPEC),
      "lidt slop accepteres -- planen oprettes foer den maales, saa vinduet "
      "maa ikke vaere paa sekundet")

print(f"\n===== SCHEDULER PILOT MANIFEST: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
