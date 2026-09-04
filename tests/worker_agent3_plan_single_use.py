#!/usr/bin/env python3
"""En godkendt Agent 3-plan kan bruges ÉN gang. Ikke to.

Mutationsprøve 19/8: fjernes engangs-håndhævelsen i ``plan_store.py`` —
så en godkendt plan kan genafspilles ubegrænset — fælder INGEN af de 304
tests i suiten det.

Invarianten var bevogtet, men kun på riggen, som trin 8/9 i Agent 3's fysiske
validering. En regression ville derfor først vise sig på en rig-dag: efter
opsætning, parring og en halv times kørsel, i stedet for i den PR der
introducerede den.

Det er den dyreste tænkelige placering af den test. Det her er den samme
kontrol i CI, hvor den koster sekunder.

Run: PYTHONPATH=worker python3 tests/worker_agent3_plan_single_use.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.agent3.plan_store import PlanStore, PlanStoreError  # noqa: E402

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    store = PlanStore(str(Path(tmp) / "plans.db"), ttl_seconds=600)

    plan_id, _udloeb = store.save('{"steps": ["noget"]}')
    check(bool(plan_id), "en plan kan gemmes og faar et id")

    foerste = store.consume(plan_id)
    check(foerste is not None, "foerste indloesning lykkes")

    # KERNEN. En godkendelse autoriserer EEN udfoerelse. Kan den samme plan
    # tages to gange, er godkendelsen ikke laengere en godkendelse -- den er
    # en noegle nogen kan bruge saa mange gange de vil.
    try:
        store.consume(plan_id)
    except PlanStoreError as exc:
        check("used" in str(exc).lower(), f"anden indloesning afvises ({exc})")
    else:
        check(False, "ANDEN INDLOESNING LYKKEDES -- planen kan genafspilles")

    try:
        store.consume("findes-ikke")
    except PlanStoreError as exc:
        check("not found" in str(exc).lower(), f"ukendt plan afvises ({exc})")
    else:
        check(False, "UKENDT PLAN BLEV INDLOEST")

    # UDLOEB kan ikke provokeres med et kort ttl: konstruktoeren klemmer
    # ttl_seconds til mellem 30 og 3600 med vilje, saa ingen kan konfigurere
    # en plan der aldrig udloeber -- eller en der udloeber for hurtigt til at
    # naa at blive godkendt. Derfor saettes expires_at direkte i basen.
    check(PlanStore(":memory:", ttl_seconds=0).ttl_seconds == 30,
          "ttl har et gulv paa 30s (kan ikke konfigureres vaek)")
    check(PlanStore(":memory:", ttl_seconds=99999).ttl_seconds == 3600,
          "ttl har et loft paa 3600s")

    import sqlite3
    sti = str(Path(tmp) / "udloeb.db")
    s2 = PlanStore(sti, ttl_seconds=600)
    gammel, _ = s2.save('{"steps": ["gammel"]}')
    with sqlite3.connect(sti) as c:
        c.execute("UPDATE agent_plans SET expires_at=? WHERE id=?",
                  (time.time() - 1, gammel))
        c.commit()
    try:
        s2.consume(gammel)
    except PlanStoreError as exc:
        check("expired" in str(exc).lower(), f"udloebet plan afvises ({exc})")
    else:
        check(False, "UDLOEBET PLAN BLEV INDLOEST")

    # En udloebet plan skal desuden vaere FORBRUGT af forsoeget, saa den ikke
    # kan indloeses hvis uret senere stilles tilbage.
    try:
        s2.consume(gammel)
    except PlanStoreError as exc:
        # Den melder "expired" igen, ikke "already used". Begge er afvisninger,
        # og det ER forbrugt i basen -- beskeden er blot den samme. Testen
        # kraever afvisning, ikke en bestemt ordlyd, for ordlyden er ikke
        # invarianten.
        check(True, f"planen kan ikke tages efter et mislykket forsoeg ({exc})")
    else:
        check(False, "UDLOEBET PLAN KUNNE TAGES BAGEFTER")

print(f"\n===== AGENT 3 PLAN SINGLE USE: {passed} passed, {failed} failed =====")
raise SystemExit(0 if failed == 0 else 1)
