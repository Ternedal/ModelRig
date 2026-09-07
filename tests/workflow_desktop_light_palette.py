#!/usr/bin/env python3
"""Keep desktop light mode on the contrast-safe token roles (#779 pkt. 5).

The token source explicitly deprecates color.brand.* and color.semantic.* for
new surfaces; Android already consumes theme-specific light roles. Desktop had
kept the old global brand mapping, which made links/actions (notably brand.gold)
low-contrast on the parchment light canvas.

This gate binds the desktop light palette to the generated Light.* roles and
checks the text-like roles whose contrast is part of this fix.

Run: python3 tests/workflow_desktop_light_palette.py
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKENS = ROOT / "assets" / "design" / "kaliv-ui-guide" / "kaliv-ui-tokens.json"
BRAND = ROOT / "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/Brand.kt"

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def relative_luminance(hex_color: str) -> float:
    value = hex_color.removeprefix("#")
    if len(value) == 8:  # ARGB token (scrim); not used by this gate.
        value = value[2:]
    channels = [int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]

    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(channel) for channel in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = relative_luminance(a), relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


tokens = json.loads(TOKENS.read_text(encoding="utf-8"))
colors = tokens["color"]
light = colors["light"]
brand = colors["brand"]
src = code_of(BRAND)
light_block = src.split("val KalivLight = KalivColors(", 1)[1].split("val LocalKalivColors", 1)[0]

expected_refs = {
    "Signal": "KalivTokens.Light.accent",
    "Amber": "KalivTokens.Light.accent",
    "Highlight": "KalivTokens.Light.accentSoft",
    "Success": "KalivTokens.Light.ok",
    "Warning": "KalivTokens.Light.warn",
    "Danger": "KalivTokens.Light.danger",
}
for role, ref in expected_refs.items():
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
    check(required in src, f"light Material3 mapping pins {required}")

# Normal-size text/link contrast. Light.warn is intentionally not asserted here:
# warning is a semantic indicator role, and changing the shared token belongs in
# the design-token source rather than a desktop-only patch.
for role in ("accent", "muted", "ok", "danger"):
    ratio = contrast(light[role], light["canvas"])
    check(ratio >= 4.5, f"light.{role} vs light.canvas contrast >= 4.5 (got {ratio:.2f})")

old_ratio = contrast(brand["gold"], light["canvas"])
check(old_ratio < 4.5,
      f"regression fixture proves deprecated brand.gold is unsafe for light text ({old_ratio:.2f})")

# Sabotage: the mapping contract must actually distinguish the old bad role.
sabotaged = light_block.replace("KalivTokens.Light.accent", "KalivTokens.Brand.gold", 1)
check("Signal = KalivTokens.Light.accent" not in sabotaged,
      "reintroducing brand.gold for Signal would make the gate red")

print(f"\ndesktop light palette: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
