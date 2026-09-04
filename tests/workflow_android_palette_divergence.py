#!/usr/bin/env python3
"""Platform-divergens er en BESLUTNING, ikke en fejl — og lige nu er der ingen.

Historik: 30/07-2026 pinnede Anders Androids lyse daempede tekst til #5A4831
(AAA i dagslys) mod tokenets #6F665C, dokumenteret i platformOverrides og
haandhaevet tosidet af denne gate. 13/08-2026 afloeste DDR-001 pinnen:
Theme.kt migrerede til de genererede KalivTokens, redesignets palette overtog,
og platformOverrides-listen blev tom.

Gaten bestaar i sin forenklede form saa mekanismen ikke doer med sagen:
1) En afvigelse der ikke staar i platformOverrides er en fejl — saa naar
   listen er tom, maa Theme.kt ikke baere pin-literalen.
2) Theme.kt skal bevise migreringen ved faktisk at referere tokenet.
Genopstaar et behov for divergens: dokumentér i platformOverrides FOERST og
udvid denne gate i samme PR (moensteret fra 30/07).

Run: python3 tests/workflow_android_palette_divergence.py
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKENS = ROOT / "assets" / "design" / "kaliv-ui-guide" / "kaliv-ui-tokens.json"
THEME = ROOT / "android/app/src/main/java/dk/ternedal/modelrig/ui/theme/Theme.kt"

LEGACY_PIN = "0xFF5A4831"

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


overrides = json.loads(TOKENS.read_text(encoding="utf-8")).get("platformOverrides", {})
android = {k: v for k, v in overrides.items() if k != "_note" and k == "android"}
check(not android,
      "platformOverrides har ingen aktive android-divergenser "
      f"(fandt: {sorted(android) or 'ingen'})")

src = THEME.read_text(encoding="utf-8")
check(LEGACY_PIN not in src,
      f"Theme.kt baerer ikke laengere pin-literalen {LEGACY_PIN} (afloest af DDR-001)")
check("KalivTokens.Light.muted" in src,
      "Theme.kt beviser migreringen: refererer KalivTokens.Light.muted")

# Sabotage: en gate der ikke kan blive roed er dekoration.
sab = src.replace("KalivTokens.Light.muted", f"Color({LEGACY_PIN})", 1)
check(LEGACY_PIN in sab and "KalivTokens.Light.muted" not in sab,
      "en genindfoert pin-literal ville blive fanget")

print(f"\nandroid palette divergence: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
