#!/usr/bin/env python3
"""#1278 integration guard for authority-aware desktop chrome adapters.

This is intentionally separate from current-main's light-theme authority gate:
it proves only the reconciliation boundary introduced by the Agent 3 pkt. 8
integration candidate. The retired compatibility shim must stay absent. Shell
telemetry/theme authority lives in KalivLightChrome.kt, while the unbound
Computer-use fail-closed boundary lives in KalivScreens.kt.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop" / "composeApp" / "src" / "main" / "kotlin" / "dk" / "ternedal" / "modelrig" / "desktop"
SHELL = DESKTOP / "KalivLightChrome.kt"
SCREENS = DESKTOP / "KalivScreens.kt"
RETIRED = DESKTOP / "KalivPkt8IntegrationChrome.kt"

shell = code_of(SHELL)
screens = code_of(SCREENS)
computer_start = screens.index("fun KalivComputerUse(")
computer = screens[computer_start:]

checks = {
    "retired integration shim stays absent": not RETIRED.exists(),
    "authority-aware sidebar overload": "status: KalivSidebarStatus" in shell and "vram: KalivVramTelemetry" in shell,
    "VRAM presentation remains evidence-driven": "presentVram(vram)" in shell and "VRAM ikke målt" not in shell,
    "performance presentation remains evidence-driven": "presentPerformance(performance)" in shell,
    "no reference-rig VRAM numbers": "6.2" not in shell and "12.0" not in shell,
    "light rail derives from theme surface": "if (c.isDark) Color(0x8C14110E) else c.Surface" in shell,
    "light active state derives from Signal": "c.Signal.copy(alpha = 0.12f)" in shell,
    "light borders derive from Border": "else c.Border" in shell,
    "unbound computer-use uses fail-closed presentation": "val presentation = presentComputerUse()" in computer,
    "unbound computer-use is forced inactive": "LaunchedEffect(Unit) { onRunningChange(false) }" in computer,
    "unbound computer-use does not expose live viewport": "LiveViewport(" not in computer,
    "unbound computer-use does not expose approval action": "onApprove" not in computer and "Godkend" not in computer,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"  {'PASS' if ok else 'FAIL'}: {name}")

if failed:
    raise SystemExit("Agent 3 pkt. 8 integration chrome failed: " + ", ".join(failed))

print(f"\nAgent 3 pkt. 8 integration chrome: {len(checks)} passed")
