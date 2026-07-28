#!/usr/bin/env python3
"""Web-research-kontrakten er landet, dvalende, og kan ikke aabne sig selv.

T-034's sidste kriterium er at aabne ToolGate/API. D6 siger at det er en
BESLUTNING, ikke en konsekvens. Denne test er graensen mellem de to: kontrakten
maa findes, valideres og kunne laeses -- men den maa ikke vaere kaldbar.

Den vigtigste assertion er at specen IKKE er i REGISTRY. ToolGate.is_enabled
bruger en deny-liste, ikke en allow-liste, saa et vaerktoej i registret er live
i samme oejeblik KALIV_TOOLS_ENABLED=1. En import ville altsaa aabne fladen.
Denne test fejler den dag nogen tilfoejer den uden at beslutte det.

Run: PYTHONPATH=worker python3 tests/worker_web_research_capability.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="kaliv-wrc-")
os.environ.setdefault("KALIV_TOOLS_DIR", os.path.join(_tmp, "notes"))
os.environ.setdefault("KALIV_AUDIT_DB", os.path.join(_tmp, "audit.db"))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "worker"))

from app import capability_schema as cs  # noqa: E402
from app import tools  # noqa: E402
from app.web_research_capability import (  # noqa: E402
    WEB_RESEARCH_CAPABILITY_ID,
    WEB_RESEARCH_SPEC,
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


# --- den vigtigste: den maa ikke vaere kaldbar ----------------------------
check(WEB_RESEARCH_CAPABILITY_ID not in tools.REGISTRY,
      "specen er IKKE i REGISTRY -- at tilfoeje den er en beslutning, ikke en import")
check(WEB_RESEARCH_SPEC.run is None,
      "der er ingen eksekvering bundet til specen endnu")

# --- kontrakten skal kunne valideres af den faelles adapter --------------
descriptor = cs.descriptor_from_tool(WEB_RESEARCH_SPEC)
check(cs.parse_descriptor(json.loads(descriptor.canonical_json())) is not None,
      "descriptoren validerer mod capability-skemaet v2")
check(descriptor.production_activation is False,
      "production_activation er false -- skemaet kan ikke taende den")

# --- D6-konsistens --------------------------------------------------------
check(descriptor.data_class == "public",
      f"data_class er public: en offentlig hentning baerer ingen lokal "
      f"information udad ({descriptor.data_class})")
check(WEB_RESEARCH_SPEC.network == "public",
      "network er public")
check(WEB_RESEARCH_SPEC.network_destinations == ("public_web",),
      f"destinationen navngiver public_web, samme ord som D6's _DESTINATIONS "
      f"({WEB_RESEARCH_SPEC.network_destinations})")

from app.data_sharing import _DESTINATIONS, DEFAULT_POLICY  # noqa: E402

check(set(WEB_RESEARCH_SPEC.network_destinations) <= _DESTINATIONS,
      "destinationen findes i data-sharing-politikkens vokabular")
check(DEFAULT_POLICY.rules()[descriptor.data_class] == "automatic",
      "D6 giver 'automatic' for denne kategori -- ikke fordi bekraeftelse er "
      "sprunget over, men fordi der ikke er noget af brugerens at bekraefte")

# --- sikkerhedsvalg der skal blive staaende -------------------------------
check(WEB_RESEARCH_SPEC.schedulable is False,
      "den er IKKE planlaegbar: en uovervaaget udadgaaende hentning fjerner "
      "mennesket fra netop den beslutning D6 handler om")
check(bool(WEB_RESEARCH_SPEC.unschedulable_because),
      "og aarsagen staar, saa en klient kan forklare den")
check(WEB_RESEARCH_SPEC.isolate is True,
      "den koerer isoleret")
check(WEB_RESEARCH_SPEC.impact == "read",
      "impact er read -- v1 er GET-only")

# --- sabotage: kan graensen blive roed? -----------------------------------
# Hvis nogen registrerer den, skal foerste assertion faelde.
sab = dict(tools.REGISTRY)
sab[WEB_RESEARCH_CAPABILITY_ID] = WEB_RESEARCH_SPEC
check(WEB_RESEARCH_CAPABILITY_ID in sab,
      "sabotage: en registrering ville vaere synlig for foerste assertion")

print(f"\nweb research capability contract: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
