#!/usr/bin/env python3
"""En laesning der forlader maskinen kraever ogsaa kortet (T-034).

requires_confirmation() spurgte "aendrer det tilstand?". Det raekker ikke for et
vaerktoej hvis HANDLING gaar udad: en offentlig hentning skriver intet, men den
roeber til en tredjepart at du spurgte, og den vaelger hvilken vaert riggen
kontakter.

Funktionens egen docstring inviterede til det: "If a future read tool returns
document contents, revisit THIS function." Det her er den revision.

Alternativet var at maerke web_research som en write for at faa kortet frem. Det
ville vaere loegn -- den skriver intet -- og en kontrakt der lyver for at udloese
den rigtige adfaerd holder praecis indtil nogen tror paa den.

Run: PYTHONPATH=worker python3 tests/worker_confirm_outbound_reads.py
"""
from __future__ import annotations

import dataclasses
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="kaliv-cor-")
os.environ.setdefault("KALIV_TOOLS_DIR", os.path.join(_tmp, "notes"))
os.environ.setdefault("KALIV_AUDIT_DB", os.path.join(_tmp, "audit.db"))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "worker"))

from app.tools import REGISTRY, requires_confirmation  # noqa: E402
from app.web_research_capability import WEB_RESEARCH_SPEC  # noqa: E402

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


# --- inert for alt der findes -------------------------------------------
# Maalt foer aendringen: ingen registreret tool har network="public". Hvis den
# antagelse holder op med at passe, skal DENNE test faelde -- ikke produktionen.
public_tools = [n for n, s in REGISTRY.items() if s.network == "public"]
check(not public_tools,
      f"intet registreret vaerktoej har network=public ({public_tools or 'ingen'})")

for name, spec in sorted(REGISTRY.items()):
    expected = spec.risk in ("write", "desktop")
    check(requires_confirmation(spec, "local") is expected,
          f"{name}: uaendret adfaerd (risk={spec.risk} -> {expected})")

# --- den nye regel -------------------------------------------------------
check(requires_confirmation(WEB_RESEARCH_SPEC, "local") is True,
      "web_research kraever kortet, selv om den er en read")
check(WEB_RESEARCH_SPEC.risk == "read",
      "og den er stadig aerligt maerket som en read -- ikke omdoebt til write "
      "for at udloese den rigtige adfaerd")

# --- reglen haenger paa network, ikke paa sensitivity --------------------
# De to akser svarer paa forskellige spoergsmaal (se SECURITY.md). En privat
# LOKAL laesning maa stadig koere frit; det er handlingens rejse der afgoer.
private_local = dataclasses.replace(
    REGISTRY["list_documents"], name="probe_private_local")
check(private_local.sensitivity == "private" and private_local.network == "none",
      "kontrol: probe er privat men rent lokal")
check(requires_confirmation(private_local, "local") is False,
      "en PRIVAT men lokal laesning kraever stadig ikke kortet -- reglen "
      "haenger paa network, ikke paa sensitivity")

# --- sabotage ------------------------------------------------------------
reverted = dataclasses.replace(WEB_RESEARCH_SPEC, network="none",
                               network_destinations=())
check(requires_confirmation(reverted, "local") is False,
      "sabotage: fjernes network=public, forsvinder kravet -- reglen er "
      "aarsagen, ikke et sammentraef")

print(f"\nconfirm outbound reads: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
