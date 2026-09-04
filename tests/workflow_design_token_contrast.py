#!/usr/bin/env python3
"""WCAG-kontrast for designtokens -- maalt, ikke antaget.

Guidens tilgaengelighedsafsnit kraever "WCAG AA for al almindelig tekst og
interaktive kontroller" og navngiver en kontrasttest paa user bubble, muted meta
og disabled controls. Det er ren udregning paa tokenvaerdier, saa det behoever
ingen skaerm og hoerer til i CI.

Fire par er under AA i dag, alle i lyst tema. De er IKKE godkendt her -- de er
laast fast, saa de ikke kan glide videre ubemaerket og saa en rettelse ogsaa
bliver synlig. Testen fejler i BEGGE retninger: et nyt par under AA er en
regression, og et rettet par er en aendring der skal afspejles i listen.

At rette dem er en designbeslutning: brand.gold og brand.highlight ER brandet,
og at flytte dem er ikke en oprydning. Se ROADMAP.md.

Run: python3 tests/workflow_design_token_contrast.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "assets" / "design" / "kaliv-ui-guide" / "kaliv-ui-tokens.json"

AA_TEXT = 4.5   # almindelig tekst
AA_UI = 3.0     # stor tekst, ikoner og UI-komponenter

# Maalt 27/07-2026. Hver linje er en KENDT defekt, ikke en accept.
# light.muted er RETTET 27/07 (#776D62 -> #6F665C): en neutral, ikke brandet,
# saa den kunne moerknes til 4,50 uden at roere Kalivs udtryk.
# semantic.warning er RETTET 29/07 (#B9823F -> #AA773A) efter Anders' beslutning:
# samme kuloer (H 33,0) og samme maetning (S 49,2%), kun lysheden fra 48,6% til
# 44,6%. Den er semantik og ikke brand -- en advarsel skal kunne laeses -- saa den
# kunne moerknes med samme indgreb som light.muted fik. Nu 3,11 paa surface,
# 3,51 paa canvas, 3,89 paa elevated.
# De TO der staar tilbage ER brandfarver. Beslutningen 29/07 er at de BLIVER
# staaende, og at guidens egen regel baerer dem: "Farve er aldrig eneste signal."
# gold.fill paa lys canvas er tilfoejet 12/08-2026 med DDR-001: 2,92:1 mod
# graensen 3,0 for non-text. Knappen identificeres af sin TEKST (gold.on paa
# gold.fill, 5,15:1 — maalt som par herunder), ikke af fladens kant mod canvas.
# De to brand-poster er deprecated med DDR-001 og udgaar naar Brand.kt migreres.
KNOWN_BELOW_AA = {
    "brand.gold on light.surface",
    "brand.highlight on light.surface",
    "gold.fill on light.canvas",
}

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def _lin(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hexv: str) -> float:
    h = hexv.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(fg: str, bg: str) -> float:
    a, b = luminance(fg), luminance(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def pairs(color: dict) -> list[tuple[str, str, str, float]]:
    out = []
    for theme in ("dark", "light"):
        t = color[theme]
        for bg in ("canvas", "surface", "elevated"):
            for fg in ("text", "muted"):
                out.append((f"{theme}.{fg} on {theme}.{bg}", t[fg], t[bg], AA_TEXT))
        # DDR-001: nye tekstroller maales HVOR DE BRUGES (svag/caps/accent staar
        # paa canvas; statusfarver paa surface). Roller med egen alpha (scrim,
        # gold.tint) kan ikke maales uden kompositering og indgaar ikke.
        for fg in ("faint", "caps", "accent", "accentSoft"):
            out.append((f"{theme}.{fg} on {theme}.canvas", t[fg], t["canvas"], AA_TEXT))
        out.append((f"{theme}.textSoft on {theme}.surfaceDim", t["textSoft"], t["surfaceDim"], AA_TEXT))
        out.append((f"{theme}.textBody on {theme}.canvas", t["textBody"], t["canvas"], AA_TEXT))
        out.append((f"{theme}.userBubbleText on {theme}.userBubble", t["userBubbleText"], t["userBubble"], AA_TEXT))
        for fg in ("ok", "warn", "danger"):
            out.append((f"{theme}.{fg} on {theme}.surface", t[fg], t["surface"], AA_UI))
        out.append((f"gold.fill on {theme}.canvas", color["gold"]["fill"], t["canvas"], AA_UI))
        for group in ("brand", "semantic"):
            for name, hexv in color[group].items():
                out.append((f"{group}.{name} on {theme}.surface", hexv, t["surface"], AA_UI))
    out.append(("gold.on on gold.fill", color["gold"]["on"], color["gold"]["fill"], AA_TEXT))
    return out


color = json.loads(TOKENS.read_text(encoding="utf-8"))["color"]
all_pairs = pairs(color)
below = {name for name, fg, bg, need in all_pairs if contrast(fg, bg) < need}

check(bool(all_pairs), f"tokenparene kunne beregnes ({len(all_pairs)} par)")

new_failures = sorted(below - KNOWN_BELOW_AA)
check(not new_failures, f"ingen NYE par under AA ({new_failures or 'ingen'})")

fixed = sorted(KNOWN_BELOW_AA - below)
check(not fixed,
      "listen over kendte defekter er aktuel "
      f"(rettet, men stadig paa listen: {fixed or 'ingen'})")

# De kendte defekter skal blive ved med at vaere maalbare, ellers er listen doed vaegt.
for name in sorted(KNOWN_BELOW_AA):
    match = [p for p in all_pairs if p[0] == name]
    check(len(match) == 1, f"kendt defekt findes stadig som et maalt par: {name}")

# Sabotage: en gate der ikke kan blive roed er dekoration.
sab = json.loads(TOKENS.read_text(encoding="utf-8"))["color"]
sab["dark"]["text"] = sab["dark"]["canvas"]          # tekst = baggrund -> ratio 1.0
sab_below = {n for n, fg, bg, need in pairs(sab) if contrast(fg, bg) < need}
check("dark.text on dark.canvas" in sab_below,
      "tekst i baggrundsfarve fanges som under AA")

print(f"\ndesign token contrast: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
