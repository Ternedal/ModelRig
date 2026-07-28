#!/usr/bin/env python3
"""Web-research-fladen findes ikke uden eksplicit opt-in (T-034, trin 2).

Vagten er skrevet FOER henteren, med vilje. Man skriver ikke det der sender data
udad og tilfoejer vagten bagefter -- saa er der et vindue hvor rækkefølgen af to
commits er det eneste der beskytter noget.

Testen daekker begge retninger: at ruten er fravaerende naar flaget er slukket,
OG at den dukker op naar det er taendt. Uden den anden ville en vagt der bare
afviste alt bestaa.

Run: PYTHONPATH=worker python3 tests/worker_web_research_mount.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="kaliv-wrm-")
os.environ.setdefault("KALIV_TOOLS_DIR", os.path.join(_tmp, "notes"))
os.environ.setdefault("KALIV_AUDIT_DB", os.path.join(_tmp, "audit.db"))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "worker"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.web_research_mount import (  # noqa: E402
    WEB_RESEARCH_FLAG,
    mount_web_research,
    web_research_enabled,
)

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def fresh_app() -> FastAPI:
    return FastAPI()


def paths(app: FastAPI) -> set[str]:
    """Ruter kan vaere pakket ind af FastAPI; spoerg OpenAPI-fladen i stedet.

    En tidligere version laeste r.path direkte og braekkede paa
    _IncludedRouter. Den serverede flade er det der betyder noget her, ikke
    den interne repraesentation.
    """
    try:
        return set(app.openapi().get("paths", {}))
    except Exception:  # noqa: BLE001
        return {getattr(r, "path", "") for r in app.routes}


saved = os.environ.get(WEB_RESEARCH_FLAG)
try:
    # --- slukket: fladen findes ikke ---------------------------------------
    os.environ.pop(WEB_RESEARCH_FLAG, None)
    check(web_research_enabled() is False, "uden flag er fladen slukket")
    app = fresh_app()
    check(mount_web_research(app) is False, "mount naegter uden opt-in")
    check(not any(p.startswith("/research") for p in paths(app)),
          "ingen /research-rute er registreret")
    with TestClient(app) as c:
        check(c.post("/research/fetch").status_code == 404,
              "ruten svarer 404 -- den findes ikke, den afviser ikke")

    # Alt andet end praecis "1" er slukket. En vagt der accepterer "true",
    # "yes" eller "0 " er en vagt man kan komme til at aabne.
    for value in ("", "0", "true", "yes", "on", " 1 x", "TRUE"):
        os.environ[WEB_RESEARCH_FLAG] = value
        check(web_research_enabled() is False,
              f"flag={value!r} taeller ikke som opt-in")

    # --- taendt: fladen dukker op ------------------------------------------
    os.environ[WEB_RESEARCH_FLAG] = "1"
    check(web_research_enabled() is True, "flag='1' er opt-in")
    app = fresh_app()
    check(mount_web_research(app) is True, "mount lykkes med opt-in")
    check(any(p.startswith("/research") for p in paths(app)),
          "/research-ruten er registreret")

    # --- idempotens ---------------------------------------------------------
    before = len(app.routes)
    check(mount_web_research(app) is True, "gentaget mount er stadig True")
    check(len(app.routes) == before,
          "gentaget mount tilfoejer ikke ruter igen")

    # --- og den henter intet endnu -----------------------------------------
    with TestClient(app) as c:
        r = c.post("/research/fetch")
        check(r.status_code == 501,
              f"ruten svarer 501: aabnet, men henteren mangler ({r.status_code})")
        check("not_implemented" in r.text,
              "svaret siger hvorfor, saa det ikke ligner en stavefejl i URL'en")
finally:
    if saved is None:
        os.environ.pop(WEB_RESEARCH_FLAG, None)
    else:
        os.environ[WEB_RESEARCH_FLAG] = saved

print(f"\nweb research mount guard: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
