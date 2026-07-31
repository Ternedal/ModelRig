#!/usr/bin/env python3
"""Androids afvigelse fra `color.light.muted` er en BESLUTNING, ikke en fejl.

Situationen 30/07-2026: `KalivTokens.kt` genereres fra token-JSON'en og ligger
allerede i Android-temaets pakke, men `Theme.kt` bruger stadig haandskrevne
`Color(0x...)`-vaerdier. Ingen test sammenlignede de to. Det betyder at
divergensen paa den daempede lyse tekst var **usynlig**: en velmenende
oprydning -- "migrer Theme.kt til KalivTokens" -- ville aendre udtrykket uden
at noget blev roedt.

Maalingen der goer den til en beslutning:

    Android  #5A4831 paa #F7F4EF  ->  7,96:1   (AAA, >= 7,0)
    tokenet  #6F665C paa #F7F4EF  ->  5,13:1   (AA,  >= 4,5)

Begge bestaar AA. Kun Androids bestaar AAA. Telefonen laeses i dagslys,
desktoppen sjaeldent -- saa et "loeft" ville koste laesbarhed praecis der hvor
den betyder mest. Anders pinnede divergensen 30/7 som et bevidst platformsvalg;
det AESTETISKE valg (loeft tokenet / saenk Android / behold divergensen)
traeffes paa rig-dagen med begge apps foran sig.

Gaten er tosidet med vilje. Den faelder BAADE hvis nogen migrerer Theme.kt til
tokenets vaerdi, OG hvis nogen aendrer tokenet til Androids -- for det sidste
ville aendre desktoppens udtryk uden at nogen bad om det. Naar valget er
truffet, opdateres `platformOverrides` i JSON'en og denne test sammen; de
laeser den samme kilde, saa de kan ikke glide fra hinanden.

Run: python3 tests/workflow_android_palette_divergence.py
"""
from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKENS = ROOT / "assets" / "design" / "kaliv-ui-guide" / "kaliv-ui-tokens.json"
THEME = ROOT / "android/app/src/main/java/dk/ternedal/modelrig/ui/theme/Theme.kt"

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def _luminance(hexv: str) -> float:
    h = hexv.lstrip("#")
    parts = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
           for c in parts]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def light_palette_color(name: str) -> str | None:
    """Laes een farve ud af KalivLightColors -- ikke ud af den moerke blok.

    `textMuted` findes i begge paletter, saa et naivt regex over hele filen
    ville ramme den forkerte og bestaa af de forkerte grunde.
    """
    src = THEME.read_text(encoding="utf-8")
    start = src.find("val KalivLightColors")
    if start < 0:
        return None
    end = src.find("\n)", start)
    block = src[start:end if end > 0 else len(src)]
    m = re.search(rf"\b{name}\s*=\s*Color\(0x[0-9A-Fa-f]{{2}}([0-9A-Fa-f]{{6}})\)",
                  block)
    return f"#{m.group(1).upper()}" if m else None


tokens = json.loads(TOKENS.read_text(encoding="utf-8"))
overrides = tokens.get("platformOverrides", {}).get("android", {})
pin = overrides.get("color.light.muted")

check(isinstance(pin, dict),
      "afvigelsen er DOKUMENTERET i token-lagets platformOverrides -- en "
      "afvigelse uden en post her ville vaere en fejl, ikke et valg")

if not isinstance(pin, dict):
    print("\nandroid palette divergence: kan ikke fortsaette uden pinnen")
    raise SystemExit(1)

check(bool(pin.get("reason")) and bool(pin.get("revisit")),
      "pinnen baerer baade begrundelse og et genbesoegs-kriterium")

actual = light_palette_color("textMuted")
check(actual == pin["value"],
      f"Theme.kt's lyse textMuted er stadig overriden {pin['value']} "
      f"(maalt: {actual}). Faelder den her, er Theme.kt sandsynligvis "
      f"migreret til KalivTokens -- det er en AESTETISK beslutning der "
      f"hoerer til rig-dagen, ikke en oprydning")

token_value = tokens["color"]["light"]["muted"]
check(token_value == pin["tokenValue"],
      f"tokenet color.light.muted er uaendret {pin['tokenValue']} "
      f"(maalt: {token_value}). Faelder den her, er tokenet 'loeftet' til "
      f"Androids vaerdi -- hvilket ogsaa ville aendre DESKTOPPENS udtryk")

check(actual != token_value,
      "divergensen findes stadig -- naar den forsvinder, er valget truffet "
      "og BAADE denne test og platformOverrides skal opdateres sammen")

background = light_palette_color("background")
if actual and background:
    ratio_android = contrast(actual, background)
    ratio_token = contrast(token_value, background)
    check(ratio_android >= 7.0,
          f"Androids vaerdi bestaar AAA paa sin egen baggrund "
          f"({ratio_android:.2f}:1 >= 7,0)")
    check(ratio_token < 7.0 <= ratio_android,
          f"og et 'loeft' til tokenet ville koste AAA "
          f"({ratio_token:.2f}:1) -- det er MAALINGEN der goer divergensen "
          f"til et valg og ikke en smagssag")
else:
    check(False, "kunne ikke laese baade textMuted og background fra Theme.kt")

print(f"\nandroid palette divergence: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
