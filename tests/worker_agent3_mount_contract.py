"""Kontraktpunkt 1 efter T-021-convergence, som Sol formulerede den 29/07.

    production_mount.mount_agent3(app) er eneste ejer af hele Agent 3-
    routeoverfladen. Den er dormant uden eksplicit flag og saetter foerst
    app.state.agent3_mounted, naar hele produktionsoverfladen er monteret.
    Core-mountet er privat og kan ikke opfylde denne kontrakt alene.

Testen beviser de seks punkter Sol kraevede, i hans raekkefoelge. Den kalder
funktionerne -- den taeller ikke forekomster af navne (HANDOFF lektie 32).
"""
from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "worker"))

from fastapi import FastAPI  # noqa: E402

import app.agent3.api as core_api  # noqa: E402
from app.agent3.production_mount import mount_agent3  # noqa: E402

PASSED = 0
FAILED = 0


def check(condition: bool, label: str) -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS: {label}")
    else:
        FAILED += 1
        print(f"  FAIL: {label}")


def _flag(value: str | None) -> None:
    if value is None:
        os.environ.pop("KALIV_AGENT3_ENABLED", None)
    else:
        os.environ["KALIV_AGENT3_ENABLED"] = value


def _agent3_routes(app: FastAPI) -> list[tuple[str, str]]:
    """Ruterne som de FAKTISK serveres, laest af OpenAPI-overfladen.

    Ikke ``app.routes``: i denne FastAPI-version optraeder inkluderede routere
    som ``_IncludedRouter`` uden ``path``, saa en optaelling dér giver nul og
    ser ud som en tom overflade. Sols krav taler ogsaa om OpenAPI-overfladen.
    """
    app.openapi_schema = None  # cachen skal ikke skjule en aendring
    paths = app.openapi().get("paths", {})
    return sorted(
        (method.upper(), path)
        for path, operations in paths.items()
        if "/experimental/agent3" in path
        for method in operations
    )


def _fresh() -> FastAPI:
    return FastAPI()


# 1. Dormans: unset og "0" er fail-closed, og HVERKEN full- eller core-kontrakten
#    fremstaar monteret. Nul ruter -- ikke "faa".
for value in (None, "0"):
    _flag(value)
    app = _fresh()
    result = mount_agent3(app)
    label = "unset" if value is None else f'"{value}"'
    check(result is False, f"flag {label}: mount_agent3 returnerer False")
    check(_agent3_routes(app) == [], f"flag {label}: nul /experimental/agent3-ruter")
    check(
        getattr(app.state, "agent3_mounted", False) is False,
        f"flag {label}: agent3_mounted fremstaar ikke monteret",
    )
    check(
        getattr(app.state, "agent3_core_mounted", False) is False,
        f"flag {label}: core-markoeren fremstaar ikke monteret",
    )

# 2. Flag "1": komplet overflade, agent3_mounted sat, core-markoeren er intern.
_flag("1")
full = _fresh()
check(mount_agent3(full) is True, 'flag "1": mount_agent3 returnerer True')
routes_full = _agent3_routes(full)
check(len(routes_full) > 0, 'flag "1": produktionsoverfladen er til stede')
check(
    getattr(full.state, "agent3_mounted", False) is True,
    'flag "1": agent3_mounted er autoritativt sat',
)
check(
    getattr(full.state, "agent3_core_mounted", False) is True,
    'flag "1": core-markoeren er sat internt af core-mountet',
)

# 3. Andet kald er idempotent: ingen dublerede (method, path) og samme stores.
store_before = full.state.agent3_memory_store
orchestrator_before = full.state.agent3_orchestrator
check(mount_agent3(full) is True, "andet kald returnerer True")
routes_again = _agent3_routes(full)
check(routes_again == routes_full, "andet kald tilfoejer ingen ruter")
check(len(routes_again) == len(set(routes_again)), "ingen dublerede (method, path)-par")
check(
    full.state.agent3_memory_store is store_before
    and full.state.agent3_orchestrator is orchestrator_before,
    "andet kald udskifter hverken stores eller orchestrator",
)

# 4. En direkte core-mount kan IKKE opfylde den offentlige full-surface-kontrakt.
core_only = _fresh()
check(
    core_api._mount_agent3_core(core_only) is True,
    "core-mountet kan kaldes direkte (privat, men importerbart for denne test)",
)
check(
    getattr(core_only.state, "agent3_mounted", False) is False,
    "core alene saetter IKKE agent3_mounted -- flaget kan aldrig betyde 'kun kernen'",
)
check(
    getattr(core_only.state, "agent3_task_readiness_mounted", False) is False,
    "core alene monterer ikke task-readiness-fladen",
)
check(
    len(_agent3_routes(core_only)) < len(routes_full),
    "core alene serverer faerre ruter end produktionskontrakten",
)

# 5. Navnet mount_agent3 er entydigt: kernen eksponerer det ikke laengere.
check(
    not hasattr(core_api, "mount_agent3"),
    "agent3/api.py eksponerer ikke laengere et offentligt mount_agent3",
)
check(
    hasattr(core_api, "_mount_agent3_core"),
    "kernen findes som privat _mount_agent3_core",
)

# 6. Launchere importerer kun fra production_mount, og ingen har en parallel
#    precheck mod den udfasede markoer.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAUNCHERS = (
    "worker/app/entrypoint.py",
    "worker/run_worker.py",
    "worker/run_worker_agent3.py",
)
for rel in LAUNCHERS:
    # Read as code: the positive claim below ("this launcher imports the
    # production mount") was satisfied by a commented-out import -- 33/33
    # green with agent3 not mounted through the production path at all.
    source = code_of(ROOT / rel)
    check(
        "from .agent3.production_mount import mount_agent3" in source
        or "from app.agent3.production_mount import mount_agent3" in source,
        f"{rel} importerer mount fra production_mount",
    )
    check(
        "agent3.api import mount_agent3" not in source
        and "from .api import mount_agent3" not in source,
        f"{rel} importerer ikke kernen direkte",
    )
    check(
        "state.agent3_full_surface_mounted" not in source,
        f"{rel} har ingen parallel precheck mod den udfasede markoer",
    )

# 7. Den udfasede markoer har ingen consumers tilbage i produktionskoden.
for rel in (
    "worker/app/agent3/production_mount.py",
    "worker/app/agent3/api.py",
):
    source = code_of(ROOT / rel)
    check(
        "state.agent3_full_surface_mounted" not in source,
        f"{rel} saetter/laeser ikke agent3_full_surface_mounted (omtale i en"
        " kommentar er ikke en consumer)",
    )

_flag(None)
print(f"\n===== AGENT3 MOUNT CONTRACT: {PASSED} passed, {FAILED} failed =====")
if FAILED:
    raise SystemExit(1)
