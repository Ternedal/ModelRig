#!/usr/bin/env python3
"""#1278 integration guard for authority-aware desktop chrome.

The reconciliation candidate no longer carries the temporary
KalivPkt8IntegrationChrome.kt adapter. The same product guarantees now live in
current-main's real light-chrome and computer-use surfaces, so this gate follows
those production sources instead of requiring the obsolete bridge to exist.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop" / "composeApp" / "src" / "main" / "kotlin" / "dk" / "ternedal" / "modelrig" / "desktop"
LIGHT_CHROME = DESKTOP / "KalivLightChrome.kt"
SCREENS = DESKTOP / "KalivScreens.kt"

chrome_src = code_of(LIGHT_CHROME)
screens_src = code_of(SCREENS)


def kotlin_function(src: str, marker: str) -> str:
    """Return one Kotlin function body, ignoring braces inside quoted strings."""
    start = src.index(marker)
    body_start = src.index("{", start)
    depth = 0
    quote = ""
    escaped = False
    for index in range(body_start, len(src)):
        char = src[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in ('"', "'"):
            quote = char
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return src[start:index + 1]
    raise AssertionError(f"unterminated Kotlin function: {marker}")


computer_use_src = kotlin_function(screens_src, "fun KalivComputerUse(")

checks = {
    "authority-aware sidebar overload": "status: KalivSidebarStatus" in chrome_src and "vram: KalivVramTelemetry" in chrome_src,
    "VRAM presentation remains evidence-driven": "presentVram(vram)" in chrome_src and "VRAM ikke målt" not in chrome_src,
    "performance presentation remains evidence-driven": "presentPerformance(performance)" in chrome_src,
    "no reference-rig VRAM numbers": "6.2" not in chrome_src and "12.0" not in chrome_src,
    "light rail derives from theme surface": "if (c.isDark) Color(0x8C14110E) else c.Surface" in chrome_src,
    "light active state derives from Signal": "c.Signal.copy(alpha = 0.12f)" in chrome_src,
    "light borders derive from Border": "else c.Border" in chrome_src,
    "unbound computer-use is forced inactive": "LaunchedEffect(Unit) { onRunningChange(false) }" in computer_use_src,
    "unbound computer-use does not expose live viewport": "LiveViewport(" not in computer_use_src,
    "unbound computer-use does not expose approval action": "onApprove" not in computer_use_src and "Godkend" not in computer_use_src,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"  {'PASS' if ok else 'FAIL'}: {name}")

if failed:
    raise SystemExit("Agent 3 pkt. 8 integration chrome failed: " + ", ".join(failed))

print(f"\nAgent 3 pkt. 8 integration chrome: {len(checks)} passed")
