#!/usr/bin/env python3
"""ADR-A4-002: storage-laget maa ikke kende subscribers (gate).

Beslutningen er truffet af Anders 30/07-2026 efter en maalt sammenligning af
de to konkurrerende Agent 4-timelines. Fundet var ikke, at den ene
implementering var pænere -- det var at **afhaengighedsretningen** skilte dem:

  gren B (#258):  timeline.py kan append/list/verify/replay. Ikke andet.
                  event_bus.py er et SIDESTILLET modul, som kun __init__.py
                  re-eksporterer. Intet lagringsmodul importerer det.

  gren A (#254):  DurableCampaignEventBus er defineret INDE i timeline.py,
                  med subscribe/publish/_notify, og composition.py wirer den
                  som kampagnens event-vej.

En arkitekturregel i prosa ville have tilladt A at lande. Derfor er retningen
her gjort mekanisk maalbar: `event_bus` MAA importere storage; storage maa
ALDRIG importere `event_bus`, og et lagringsmodul maa ikke selv definere en
abonnementsflade.

**Et lagringsmodul udpeges paa ADFAERD, ikke paa navn** -- et modul der
skriver til disk ER storage, uanset hvad filen hedder. Ellers ville reglen
kunne omgaas ved en omdoebning, og navngivning er netop et aabent punkt i
Agent 4 (ADR-A4-004).

**`worker/app/agent4/` findes ikke paa main endnu**, saa repo-scanningen
passerer tomt i dag. Det er praecis derfor hver detektor ogsaa koeres mod
overtraedende proever nedenfor: en test der kun kan bestaa, er ingen test
(samme mønster som tests/workflow_agent3_dormant.py).

Run: python3 tests/workflow_agent4_storage_boundary.py
"""
from __future__ import annotations

import ast
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENT4 = ROOT / "worker" / "app" / "agent4"

#: Kald der goer et modul til et lagringsmodul. Listen er bevidst konkret:
#: den beskriver hvad Agent 4's stores faktisk bruger til at persistere.
_WRITE_MARKERS = (
    "os.open(",
    "os.link(",
    "os.replace(",
    "NamedTemporaryFile(",
    ".write_text(",
    ".write_bytes(",
)

#: Abonnementsfladen. Et lagringsmodul maa ikke definere nogen af dem.
_SUBSCRIBER_NAMES = frozenset({"subscribe", "publish", "_notify", "notify"})

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


def is_storage(source: str) -> bool:
    """Skriver modulet til disk? Saa er det storage, uanset filnavnet."""
    return any(marker in source for marker in _WRITE_MARKERS)


def imports_event_bus(source: str) -> bool:
    """Importerer modulet event_bus -- i nogen af de former Python tillader?"""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[-1] == "event_bus":
                return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[-1] == "event_bus":
                    return True
    return False


def subscriber_defs(source: str) -> list[str]:
    """Hvilke abonnements-metoder definerer modulet selv?"""
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in _SUBSCRIBER_NAMES:
                found.append(node.name)
    return sorted(set(found))


def violations(name: str, source: str) -> list[str]:
    """ADR-A4-002 anvendt paa een modulkilde. Tom liste = i orden."""
    if not is_storage(source):
        return []
    problems: list[str] = []
    if imports_event_bus(source):
        problems.append(f"{name}: lagringsmodul importerer event_bus")
    defs = subscriber_defs(source)
    if defs:
        problems.append(
            f"{name}: lagringsmodul definerer abonnementsflade ({', '.join(defs)})"
        )
    return problems


# --- Del 1: detektoren virker -- proevet mod OVERTRAEDENDE kilder ----------
# Proeverne gengiver de to konkrete former, gren A havde. De er skrevet ud
# her frem for hentet fra en branch, saa gaten er selvstaendig og stadig
# virker naar branchen forlaengst er lukket.

_A_LIKE_BUS_IN_STORE = '''
"""Ligner gren A: storen skriver til disk OG baerer abonnementsfladen."""
import os


class JsonlCampaignTimelineStore:
    def append(self, entry):
        descriptor = os.open("t.jsonl", os.O_APPEND | os.O_CREAT | os.O_WRONLY)
        os.write(descriptor, b"{}")


class DurableCampaignEventBus:
    def subscribe(self, handler):
        self._handlers.append(handler)

    def publish(self, event):
        self._notify(event)

    def _notify(self, event):
        for handler in self._handlers:
            handler(event)
'''

_STORE_IMPORTS_BUS = '''
"""Den anden retning: storen henter bussen ind."""
import os
from .event_bus import InMemoryCampaignEventBus


class Store:
    def append(self, entry):
        os.link("a", "b")
'''

_STORE_IMPORTS_BUS_ABSOLUTE = '''
"""Samme fejl, anden importform -- en gate der kun kender een form er blind."""
import os
import worker.app.agent4.event_bus as bus


class Store:
    def save(self, path, data):
        path.write_text(data)
'''

_CLEAN_STORE = '''
"""Ligner gren B: storen persisterer og goer intet andet."""
import os
import tempfile


class JsonCampaignTimelineStore:
    def append(self, entry):
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(b"{}")
        os.link(handle.name, "final.json")

    def list(self, campaign_id):
        return ()

    def verify(self, campaign_id):
        return None
'''

_CLEAN_BUS = '''
"""Den tilladte retning: bussen maa kende storen, ikke omvendt."""
from .timeline import JsonCampaignTimelineStore


class InMemoryCampaignEventBus:
    def subscribe(self, handler):
        self._handlers.append(handler)

    def publish(self, event):
        self._notify(event)

    def _notify(self, event):
        for handler in self._handlers:
            handler(event)
'''

found = violations("a_like.py", _A_LIKE_BUS_IN_STORE)
check(any("abonnementsflade" in item for item in found),
      f"detektor: en store MED abonnementsflade i samme modul faelder ({found})")

found = violations("store_imports_bus.py", _STORE_IMPORTS_BUS)
check(any("importerer event_bus" in item for item in found),
      f"detektor: en store der importerer event_bus faelder ({found})")

found = violations("store_imports_bus_abs.py", _STORE_IMPORTS_BUS_ABSOLUTE)
check(any("importerer event_bus" in item for item in found),
      "detektor: ogsaa den absolutte importform fanges -- en gate der kun "
      "kender 'from . import' er blind for halvdelen af Python")

check(violations("clean_store.py", _CLEAN_STORE) == [],
      "kontrol: en ren store (append/list/verify) giver ingen falsk positiv")

check(violations("clean_bus.py", _CLEAN_BUS) == [],
      "kontrol: bussen MAA importere storen og definere subscribe/publish -- "
      "reglen er retningsbestemt, ikke et forbud mod abonnementer")

# --- Del 2: reglen anvendt paa repoet --------------------------------------

if not AGENT4.is_dir():
    check(True,
          "worker/app/agent4/ findes ikke paa main endnu -- scanningen "
          "passerer tomt, og gaten er armeret til den dag laget lander")
else:
    repo_problems: list[str] = []
    scanned = 0
    for path in sorted(AGENT4.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        scanned += 1
        # Comments are not code: a module that mentions os.replace in a note
        # is not writing anything, and the gate should not say it is.
        source = code_of(path)
        repo_problems.extend(
            violations(str(path.relative_to(ROOT)), source)
        )
    check(not repo_problems,
          f"ADR-A4-002 holder i worker/app/agent4/ ({scanned} moduler scannet) "
          f"{repo_problems if repo_problems else ''}")

print(f"\n===== ADR-A4-002 STORAGE BOUNDARY: {PASSED} passed, "
      f"{FAILED} failed =====")
if FAILED:
    raise SystemExit(1)
