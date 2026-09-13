#!/usr/bin/env python3
"""#1278 integration guard for authority-aware desktop chrome adapters.

This is intentionally separate from current-main's light-theme authority gate:
it proves only the reconciliation boundary introduced by the Agent 3 pkt. 8
integration candidate. The reconciled tree removed the temporary
KalivPkt8IntegrationChrome.kt shim, so the guard must follow the real split:
authority-aware light chrome lives in KalivLightChrome.kt while the unbound
Computer-use fail-closed boundary lives in KalivScreens.kt.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop" / "composeApp" / "src" / "main" / "kotlin" / "dk" / "ternedal" / "modelrig" / "desktop"
LIGHT_CHROME = DESKTOP / "KalivLightChrome.kt"
SCREENS = DESKTOP / "KalivScreens.kt"
REMOVED_SHIM = DESKTOP / "KalivPkt8IntegrationChrome.kt"

light_src = code_of(LIGHT_CHROME)
screens_src = code_of(SCREENS)
computer_marker = "@Composable\nfun KalivComputerUse("
if computer_marker not in screens_src:
    raise SystemExit("Agent 3 pkt. 8 integration chrome failed: Computer-use boundary not found")
computer_src = screens_src[screens_src.index(computer_marker):]

checks = {
    "removed compatibility shim stays absent": not REMOVED_SHIM.exists(),
    "authority-aware sidebar overload": "status: KalivSidebarStatus" in light_src and "vram: KalivVramTelemetry" in light_src,
    "VRAM presentation remains evidence-driven": "presentVram(vram)" in light_src and "VRAM ikke målt" not in light_src,
    "performance presentation remains evidence-driven": "presentPerformance(performance)" in light_src,
    "no reference-rig VRAM numbers": "6.2" not in light_src and "12.0" not in light_src,
    "light rail derives from theme surface": "if (c.isDark) Color(0x8C14110E) else c.Surface" in light_src,
    "light active state derives from Signal": "c.Signal.copy(alpha = 0.12f)" in light_src,
    "light borders derive from Border": "else c.Border" in light_src,
    "unbound computer-use is forced inactive": "LaunchedEffect(Unit) { onRunningChange(false) }" in computer_src,
    "unbound computer-use does not expose live viewport": "LiveViewport(" not in computer_src,
    "unbound computer-use does not expose approval action": "onApprove" not in computer_src and "Godkend" not in computer_src,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"  {'PASS' if ok else 'FAIL'}: {name}")

if failed:
    raise SystemExit("Agent 3 pkt. 8 integration chrome failed: " + ", ".join(failed))

print(f"\nAgent 3 pkt. 8 integration chrome: {len(checks)} passed")
