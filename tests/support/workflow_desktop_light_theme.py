#!/usr/bin/env python3
"""Focused desktop light-theme authority for #779 pkt. 5 / #1270 / #1274.

This support gate measures product boundaries that the generic token contrast
gate cannot see: which token roles desktop Brand.kt binds to its light palette,
and whether the default CHAT shell actually selects theme-aware application
chrome. It is invoked by the existing top-level workflow_design_token_contrast.py
gate so focused desktop slices do not silently change CURRENT_STATE's top-level
test inventory authority.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "desktop" / "composeApp" / "src" / "main" / "kotlin" / "dk" / "ternedal" / "modelrig" / "desktop"
BRAND = DESKTOP / "Brand.kt"
SHELL = DESKTOP / "KalivLightChrome.kt"
APP = DESKTOP / "App.kt"
TOKENS = ROOT / "assets" / "design" / "kaliv-ui-guide" / "kaliv-ui-tokens.json"
AA_TEXT = 4.5

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


def shell_light_boundary(src: str) -> bool:
    """Known dark handoff shell colors must be conditional, never light authority."""
    required = (
        "if (c.isDark) Color(0x990B0A09) else c.Surface",
        "if (c.isDark) Color(0x8C14110E) else c.Surface",
        "if (c.isDark) Color(0x8014110E) else c.Surface",
        "if (c.isDark) Color(0xFF100C09) else c.Border.copy(alpha = 0.55f)",
    )
    return all(binding in src for binding in required)


brand = BRAND.read_text(encoding="utf-8")
app = APP.read_text(encoding="utf-8")
color = json.loads(TOKENS.read_text(encoding="utf-8"))["color"]

light_start = brand.index("val KalivLight = KalivColors(")
light_end = brand.index("\n\nval LocalKalivColors", light_start)
light_block = brand[light_start:light_end]

expected_light_bindings = (
    "Signal = KalivTokens.Light.accent,",
    "Amber = KalivTokens.Light.accentSoft,",
    "Highlight = KalivTokens.Light.accentSoft,",
    "Success = KalivTokens.Light.ok,",
    "Warning = KalivTokens.Light.warn,",
    "Danger = KalivTokens.Light.danger,",
)
for binding in expected_light_bindings:
    check(binding in light_block, f"KalivLight binder {binding.removesuffix(',')}")

check(
    "KalivTokens.Brand." not in light_block,
    "KalivLight bruger ikke deprecated theme-invariant brand.* authority",
)
check(
    "KalivTokens.Semantic." not in light_block,
    "KalivLight bruger ikke deprecated theme-invariant semantic.* authority",
)

scheme_start = brand.index(") else lightColorScheme(")
scheme_end = brand.index("\n    )\n    CompositionLocalProvider", scheme_start)
light_scheme = brand[scheme_start:scheme_end]
for binding in (
    "surfaceVariant = c.SurfaceHigh, onSurfaceVariant = c.TextMuted,",
    "outline = c.Border, outlineVariant = c.Border,",
    "surfaceContainer = c.Surface,",
    "surfaceContainerHigh = c.SurfaceHigh,",
    "surfaceContainerLow = c.Graphite,",
):
    check(binding in light_scheme, f"Material3 light scheme ejer {binding.removesuffix(',')}")

accent = color["light"]["accent"]
canvas = color["light"]["canvas"]
surface = color["light"]["surface"]
ivory = "#F7F4EF"
bronze = color["brand"]["bronze"]

accent_canvas = contrast(accent, canvas)
accent_surface = contrast(accent, surface)
ivory_accent = contrast(ivory, accent)
check(
    accent_canvas >= AA_TEXT,
    f"light accent paa canvas er AA ({accent_canvas:.2f}:1)",
)
check(
    accent_surface >= AA_TEXT,
    f"light accent paa surface er AA ({accent_surface:.2f}:1)",
)
check(
    ivory_accent >= AA_TEXT,
    f"onPrimary ivory paa light accent er AA ({ivory_accent:.2f}:1)",
)

# Historical/sabotage proof for L1: the exact mapping removed by #1270 must
# fail the boundary this gate protects.
historical = contrast(bronze, canvas)
check(
    historical < AA_TEXT,
    f"historical brand.bronze paa light canvas demonstrerer defekten ({historical:.2f}:1)",
)

# L2a: default CHAT shell gets exact-arity overloads. App currently supplies
# exactly these argument counts, while the handoff implementations have one
# extra defaulted argument. Kotlin therefore selects this bounded migration;
# desktop compilation is the executable authority for overload resolution.
check(SHELL.exists(), "L2a shell source findes")
shell = SHELL.read_text(encoding="utf-8") if SHELL.exists() else ""
for signature in (
    "fun KalivTitleBar(\n    subtitle: String,\n    live: String?,\n)",
    "fun KalivNavRail(\n    active: KalivScreen,\n    onSelect: (KalivScreen) -> Unit,\n    modelName: String,\n    vramUsedGb: Double,\n    vramTotalGb: Double,\n    modelBackend: String,\n)",
    "fun KalivContextPanel(\n    ragOn: Boolean,\n    onToggleRag: () -> Unit,\n    docs: List<RagDocRow>,\n    onAddDocument: () -> Unit,\n    tokensPerSec: Int,\n    responseSeconds: Double,\n    sparkline: List<Float>,\n)",
):
    check(signature in shell, f"exact-arity shell overload findes: {signature.split('(')[0].split()[-1]}")

check(shell_light_boundary(shell), "L2a dark compatibility-literals er betingede og light bruger theme-roller")
check("else c.TextHigh" in shell and "else c.TextMuted" in shell, "light title/nav tekst bruger theme-ink")
check("else c.Border" in shell, "light shell borders bruger Kaliv Border")
check("c.Signal.copy(alpha = 0.12f)" in shell, "light aktiv navigation bruger themed Signal-wash")
check("LiveViewport" not in shell, "L2a roerer ikke den simulerede browser/page-flade")

# App must keep the arities this migration is designed around. If someone adds
# the legacy optional argument, the support gate fails instead of silently
# switching the product back to the dark-only implementation.
title_start = app.index("KalivTitleBar(")
title_end = app.index("\n        Row(Modifier.fillMaxWidth().weight(1f))", title_start)
title_call = app[title_start:title_end]
check("onClose =" not in title_call, "App titlebar call bliver paa L2a exact arity")

nav_start = app.index("KalivNavRail(")
nav_end = app.index("\n            } else {", nav_start)
nav_call = app[nav_start:nav_end]
check("modifier =" not in nav_call, "App chat-nav call bliver paa L2a exact arity")

context_start = app.index("KalivContextPanel(")
context_end = app.index("\n                )", context_start) + len("\n                )")
context_call = app[context_start:context_end]
check("modifier =" not in context_call, "App context-panel call bliver paa L2a exact arity")

# Sabotage: prove the L2a boundary can turn red if the title bar regresses to
# unconditional dark chrome.
sabotaged = shell.replace(
    "if (c.isDark) Color(0x990B0A09) else c.Surface",
    "Color(0x990B0A09)",
    1,
)
check(not shell_light_boundary(sabotaged), "unconditional dark titlebar sabotage fanges")

print(f"\ndesktop light theme: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
