#!/usr/bin/env python3
"""WCAG-kontrast og desktop theme-binding for designtokens -- maalt, ikke antaget.

Guidens tilgaengelighedsafsnit kraever "WCAG AA for al almindelig tekst og
interaktive kontroller" og navngiver en kontrasttest paa user bubble, muted meta
og disabled controls. Det er ren udregning paa tokenvaerdier, saa det behoever
ingen skaerm og hoerer til i CI.

Fire par er under AA i dag, alle i lyst tema. De er IKKE godkendt her -- de er
laast fast, saa de ikke kan glide videre ubemaerket og saa en rettelse ogsaa
bliver synlig. Testen fejler i BEGGE retninger: et nyt par under AA er en
regression, og et rettet par er en aendring der skal afspejles i listen.

#779/#910 binder desuden desktop shell/chrome til de maalte tema-roller. Det er
ikke nok at have korrekte light tokens, hvis titelbar, rails eller sidepaneler
stadig bypasser temaet med dark-only literals. #925 fjernede den illustrative
Computer-use browser/page-mock, saa den gamle lokale farveundtagelse findes ikke.

Run: python3 tests/workflow_design_token_contrast.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "assets" / "design" / "kaliv-ui-guide" / "kaliv-ui-tokens.json"
DESKTOP_BRAND = ROOT / "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/Brand.kt"
DESKTOP_SCREENS = ROOT / "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/KalivScreens.kt"

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


def function_block(src: str, name: str) -> str:
    marker = f"fun {name}("
    check(marker in src, f"desktop function exists: {name}")
    if marker not in src:
        return ""
    start = src.index(marker)
    next_fun = src.find("\n@Composable", start + len(marker))
    return src[start:] if next_fun < 0 else src[start:next_fun]


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

# #779 pkt. 5 / #907: desktop light mode used the deprecated global
# brand/semantic colours as actual foreground/status roles. Bind it to the
# theme-specific roles that this same test measures. Read code rather than
# comments so a commented-out mapping cannot satisfy the gate.
desktop = code_of(DESKTOP_BRAND)
dark_block = desktop.split("val KalivDark = KalivColors(", 1)[1].split("val KalivLight = KalivColors(", 1)[0]
light_block = desktop.split("val KalivLight = KalivColors(", 1)[1].split("val LocalKalivColors", 1)[0]
for role, ref in {
    "Signal": "KalivTokens.Light.accent",
    "Amber": "KalivTokens.Light.accent",
    "Highlight": "KalivTokens.Light.accentSoft",
    "Success": "KalivTokens.Light.ok",
    "Warning": "KalivTokens.Light.warn",
    "Danger": "KalivTokens.Light.danger",
}.items():
    check(f"{role} = {ref}" in light_block, f"desktop light {role} uses {ref}")
check("KalivTokens.Brand." not in light_block,
      "desktop light palette does not reuse deprecated global brand colours")
check("KalivTokens.Semantic." not in light_block,
      "desktop light palette does not reuse deprecated global semantic colours")
for required in (
    "surfaceVariant = c.SurfaceHigh",
    "onSurfaceVariant = c.TextMuted",
    "outline = c.Border",
    "surfaceContainerLowest = c.Graphite",
):
    check(required in desktop, f"desktop light Material3 mapping pins {required}")

# #910: shell/chrome itself must consume the light palette rather than keeping
# high-area dark literals. Dark mode is explicitly not redesigned, so its old
# pixels are pinned here while ownership moves into KalivColors.
for role, value in {
    "ShellTitleBar": "Color(0x990B0A09)",
    "ShellRail": "Color(0x8C14110E)",
    "ShellPanel": "Color(0x8014110E)",
    "ShellTitleText": "Color(0xFFE9DFCE)",
    "ShellSubtitleText": "KalivTokens.Light.muted",
    "ShellInactiveText": "Color(0xFFC3B8A8)",
    "ShellLiveText": "Color(0xFFD09A55)",
}.items():
    check(f"{role} = {value}" in dark_block, f"dark {role} preserves via {value}")
check(color["light"]["muted"].upper() == "#6F665C",
      "Light.muted token still owns the preserved dark subtitle bytes #6F665C")

for role, ref in {
    "ShellTitleBar": "KalivTokens.Light.surfaceDim",
    "ShellRail": "KalivTokens.Light.surface",
    "ShellPanel": "KalivTokens.Light.surface",
    "ShellTitleText": "KalivTokens.Light.text",
    "ShellSubtitleText": "KalivTokens.Light.muted",
    "ShellInactiveText": "KalivTokens.Light.muted",
    "ShellLiveText": "KalivTokens.Light.warn",
}.items():
    check(f"{role} = {ref}" in light_block, f"light {role} uses {ref}")

for literal in (
    "Color(0x990B0A09)",
    "Color(0x8C14110E)",
    "Color(0x8014110E)",
    "Color(0xFFE9DFCE)",
    "Color(0xFFC3B8A8)",
):
    check(literal not in light_block, f"light palette has no copied dark shell literal {literal}")

screens = code_of(DESKTOP_SCREENS)
component_contracts = {
    "KalivTitleBar": (
        ("ShellTitleBar", "ShellTitleText", "ShellSubtitleText", "ShellLiveText"),
        ("Color(0x990B0A09)", "Color(0xFFE9DFCE)"),
    ),
    "KalivIconRail": (("ShellRail",), ("Color(0x8C14110E)",)),
    "IconRailItem": (("ShellInactiveText",), ("Color(0xFFC3B8A8)",)),
    "KalivNavRail": (("ShellRail",), ("Color(0x8C14110E)",)),
    "NavRow": (("ShellInactiveText",), ("Color(0xFFC3B8A8)",)),
    "PrivacySeal": (("ShellTitleText",), ("Color(0xFFE9DFCE)",)),
    "KalivContextPanel": (("ShellPanel",), ("Color(0x8014110E)",)),
    "KalivAgentCockpit": (("ShellPanel",), ("Color(0x8014110E)",)),
    "AgentIdlePrompt": (("ShellInactiveText",), ("Color(0xFFC3B8A8)",)),
}
for name, (required, forbidden) in component_contracts.items():
    body = function_block(screens, name)
    for role in required:
        check(f"KalivTheme.colors.{role}" in body, f"{name} consumes theme role {role}")
    for literal in forbidden:
        check(literal not in body, f"{name} does not hard-code old shell literal {literal}")

for literal in ("Color(0x990B0A09)", "Color(0x8C14110E)", "Color(0x8014110E)"):
    check(literal not in screens, f"Screens.kt has no old high-area shell literal {literal}")

# #925 removed the illustrative Computer-use browser/page mock entirely. Its
# old local-colour exception must therefore not remain as a required component.
check("fun LiveViewport(" not in screens,
      "removed Computer-use LiveViewport mock remains absent")

# Text-like roles used on the light canvas must clear AA normal-text contrast.
# light.warn is a semantic UI indicator and is already measured at AA_UI above.
for role in ("accent", "muted", "ok", "danger"):
    ratio = contrast(color["light"][role], color["light"]["canvas"])
    check(ratio >= AA_TEXT,
          f"light.{role} vs light.canvas contrast >= {AA_TEXT:.1f} (got {ratio:.2f})")
old_ratio = contrast(color["brand"]["gold"], color["light"]["canvas"])
check(old_ratio < AA_TEXT,
      f"deprecated brand.gold remains a valid light-text regression fixture ({old_ratio:.2f})")

# Sabotage: en gate der ikke kan blive roed er dekoration.
sab = json.loads(TOKENS.read_text(encoding="utf-8"))["color"]
sab["dark"]["text"] = sab["dark"]["canvas"]          # tekst = baggrund -> ratio 1.0
sab_below = {n for n, fg, bg, need in pairs(sab) if contrast(fg, bg) < need}
check("dark.text on dark.canvas" in sab_below,
      "tekst i baggrundsfarve fanges som under AA")
sabotaged_desktop = light_block.replace("KalivTokens.Light.accent", "KalivTokens.Brand.gold", 1)
check("Signal = KalivTokens.Light.accent" not in sabotaged_desktop,
      "desktop regression: brand.gold for Signal would make the mapping gate red")
context = function_block(screens, "KalivContextPanel")
sabotaged_context = context.replace("KalivTheme.colors.ShellPanel", "Color(0x8014110E)", 1)
check("KalivTheme.colors.ShellPanel" not in sabotaged_context and "Color(0x8014110E)" in sabotaged_context,
      "desktop shell regression: context-panel dark literal is detectable")

print(f"\ndesign token contrast: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
