#!/usr/bin/env python3
"""Generate one Kotlin token source per module from the design token JSON.

The design guide ships assets/design/kaliv-ui-guide/kaliv-ui-tokens.json as the
authority. Before this script the values were retyped by hand in three places
(desktop Brand.kt, desktop KalivScreens.kt, android theme/Theme.kt), which is
why a measurement on 27/07-2026 found all 18 colour tokens present on desktop
and only 2 on Android: there was no shared source to inherit from.

This does NOT migrate call sites. It creates the source they can migrate TO,
and a --check that fails when the generated files drift from the JSON, so the
checklist item "semantic dark/light tokens implemented centrally" becomes a
test instead of an agreement.

  python3 scripts/design_tokens.py           # write the Kotlin files
  python3 scripts/design_tokens.py --check   # exit 1 on drift
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKENS = ROOT / "assets" / "design" / "kaliv-ui-guide" / "kaliv-ui-tokens.json"

TARGETS = {
    "dk.ternedal.modelrig.desktop":
        ROOT / "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/KalivTokens.kt",
    "dk.ternedal.modelrig.ui.theme":
        ROOT / "android/app/src/main/java/dk/ternedal/modelrig/ui/theme/KalivTokens.kt",
}

BANNER = (
    "// GENERERET af scripts/design_tokens.py fra\n"
    "// assets/design/kaliv-ui-guide/kaliv-ui-tokens.json -- rediger ikke i haanden.\n"
    "// Aendr JSON'en og koer generatoren; CI fejler paa drift.\n"
)


def _argb(hexv: str) -> str:
    """6-cifret hex er opak (FF-praefiks); 8-cifret baerer sin egen alpha (AARRGGBB)."""
    h = hexv.lstrip("#").upper()
    return "0x" + h if len(h) == 8 else "0xFF" + h


def _ident(key: str) -> str:
    """JSON keys are numeric for spacing (1, 2, 4 ...); Kotlin needs a name."""
    return f"s{key}" if key.isdigit() else key


def render(package: str, tok: dict) -> str:
    out: list[str] = [BANNER, f"package {package}", ""]
    out += [
        "import androidx.compose.ui.graphics.Color",
        "import androidx.compose.ui.unit.Dp",
        "import androidx.compose.ui.unit.TextUnit",
        "import androidx.compose.ui.unit.dp",
        "import androidx.compose.ui.unit.sp",
        "",
        "/** Single source of truth for the Kaliv design tokens. */",
        "object KalivTokens {",
        f"    const val VERSION: String = \"{tok['meta']['version']}\"",
        f"    val BASE_GRID: Dp = {tok['meta']['baseGrid']}.dp",
        "",
    ]

    for group in ("dark", "light", "gold", "brand", "semantic"):
        out.append(f"    object {group.capitalize()} {{")
        for name, hexv in tok["color"][group].items():
            out.append(f"        val {name}: Color = Color({_argb(hexv)})")
        out += ["    }", ""]

    for group, unit in (("spacing", "dp"), ("radius", "dp"), ("layout", "dp")):
        out.append(f"    object {group.capitalize()} {{")
        for name, val in tok[group].items():
            out.append(f"        val {_ident(name)}: Dp = {val}.{unit}")
        out += ["    }", ""]

    out.append("    object Motion {")
    for name, val in tok["motion"].items():
        out.append(f"        const val {name}: Int = {val}")
    out += ["    }", ""]

    out.append("    object Typography {")
    for role, spec in tok["typography"].items():
        out.append(f"        object {role.capitalize()} {{")
        for k, v in spec.items():
            if k == "family":
                out.append(f"            const val {k}: String = \"{v}\"")
            elif k == "size":
                out.append(f"            val {k}: TextUnit = {v}.sp")
            elif isinstance(v, float):
                out.append(f"            const val {k}: Float = {v}f")
            else:
                out.append(f"            const val {k}: Int = {v}")
        out.append("        }")
    out += ["    }", "}", ""]
    return "\n".join(out)


def main() -> int:
    check = "--check" in sys.argv
    if not TOKENS.is_file():
        print(f"token-kilden mangler: {TOKENS}")
        return 1
    tok = json.loads(TOKENS.read_text(encoding="utf-8"))

    drift = []
    for package, path in TARGETS.items():
        want = render(package, tok)
        have = path.read_text(encoding="utf-8") if path.is_file() else None
        if check:
            if have != want:
                drift.append(path.relative_to(ROOT))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(want, encoding="utf-8")
            print(f"skrev {path.relative_to(ROOT)}")

    if check:
        if drift:
            for d in drift:
                print(f"DRIFTET: {d}")
            print("koer: python3 scripts/design_tokens.py")
            return 1
        print("token-kilderne matcher JSON'en")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
