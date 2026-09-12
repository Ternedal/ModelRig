#!/usr/bin/env python3
"""Desktop light-theme authority for #779 pkt. 5 / #1270.

This gate deliberately measures the product boundary that the generic token
contrast gate cannot see: which token roles desktop Brand.kt actually binds to
its light palette and Material3 field/container colors.

Run: python3 tests/workflow_desktop_light_theme.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRAND = ROOT / "desktop" / "composeApp" / "src" / "main" / "kotlin" / "dk" / "ternedal" / "modelrig" / "desktop" / "Brand.kt"
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


brand = BRAND.read_text(encoding="utf-8")
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

# Historical/sabotage proof: the exact mapping removed by #1270 must fail the
# boundary this gate is intended to protect. Otherwise this test could turn
# green without proving the operator-visible regression class.
historical = contrast(bronze, canvas)
check(
    historical < AA_TEXT,
    f"historical brand.bronze paa light canvas demonstrerer defekten ({historical:.2f}:1)",
)

print(f"\ndesktop light theme: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
