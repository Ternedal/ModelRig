#!/usr/bin/env python3
"""Windows-navne der ikke er den fil de ligner (T-035, adversarial path-tests).

read_scope.py's egen docstring siger det: "a path check is exactly the kind of
thing that looks right and is wrong ... Getting it wrong is an
arbitrary-file-read." Den havde ret om sig selv. Maalt 27/07 slap fem varianter
igennem graensen -- reserverede DOS-enhedsnavne, trailing dot og space,
8.3-aliaser og alternate data streams. De er lukket, og navngivet her saa de
ikke kan aabne sig igen.

Testen assereterer KUN paa afvist/tilladt, aldrig paa den resolverede sti.
os.sep er forskellig paa Windows og Linux, og en tidligere test i dette repo
faeldede CI netop fordi den maalte platformadfaerd i stedet for kontrakten.

Run: PYTHONPATH=worker python3 tests/worker_read_scope_windows_aliases.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "worker"))

from app.read_scope import PathDenied, ReadScope  # noqa: E402

scope = ReadScope(root="/srv/kaliv-docs")
passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def denied(value: str, why: str) -> None:
    try:
        scope.resolve(value)
        check(False, f"{value!r} afvises ({why})")
    except PathDenied:
        check(True, f"{value!r} afvises ({why})")


def allowed(value: str, why: str) -> None:
    try:
        scope.resolve(value)
        check(True, f"{value!r} tillades ({why})")
    except PathDenied as exc:
        check(False, f"{value!r} blev afvist: {exc}")


# --- reserverede DOS-enheder ---------------------------------------------
# Windows aabner ENHEDEN, ikke en fil. Ogsaa med endelse, ogsaa i en undermappe.
for name in ("CON", "PRN", "AUX", "NUL", "COM1", "COM9", "LPT1", "LPT9"):
    denied(name, "reserveret DOS-enhedsnavn")
denied("CON.txt", "reserveret navn med endelse er stadig enheden")
denied("docs/NUL", "reserveret navn i en undermappe er stadig enheden")
denied("con", "reserverede navne er ikke versalfoelsomme")

# --- trailing dot og space -----------------------------------------------
# Windows stripper dem, saa to forskellige strenge bliver samme fil. Afvisning
# frem for normalisering: en stille omskrivning ville skjule netop den tvetydighed.
denied("notes.txt ", "trailing space -- Windows stripper den")
denied("notes.txt.", "trailing dot -- Windows stripper den")
denied("docs /a.txt", "trailing space paa en mappekomponent")

# --- 8.3-aliaser ----------------------------------------------------------
denied("PROGRA~1", "8.3-alias kan pege paa et langt navn uden for scope")
denied("docs/LONGNA~2/a.txt", "8.3-alias midt i stien")

# --- alternate data streams ----------------------------------------------
denied("notes.txt:hidden", "alternate data stream")
denied("notes.txt::$DATA", "eksplicit ADS-syntaks")
denied("a/b.txt:secret", "ADS paa en indlejret fil")

# --- kontrol: graensen maa ikke bare afvise alt --------------------------
# Uden disse kunne alt ovenfor bestaa fordi resolve() var brudt.
allowed("index.html", "almindeligt filnavn")
allowed("a/b.txt", "indlejret sti")
allowed("a/b/../c.txt", "'..' der bliver inde i roden")
allowed("note~s.txt", "tilde UDEN ciffer er ikke et 8.3-alias")
allowed("CONTRACT.md", "navn der blot BEGYNDER med et reserveret ord")
allowed("a.b.c.txt", "flere punktummer inde i navnet")

print(f"\nread scope windows aliases: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
