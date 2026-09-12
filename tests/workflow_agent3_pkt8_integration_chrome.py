#!/usr/bin/env python3
"""#1278 integration guard for authority-aware desktop chrome adapters.

This is intentionally separate from current-main's light-theme authority gate:
it proves only the reconciliation boundary introduced by the Agent 3 pkt. 8
integration candidate. It must fail if the adapter starts inventing telemetry,
loses light-theme role usage, or turns the unbound computer-use overload into a
simulated execution surface.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "desktop" / "composeApp" / "src" / "main" / "kotlin" / "dk" / "ternedal" / "modelrig" / "desktop" / "KalivPkt8IntegrationChrome.kt"

src = code_of(ADAPTER)

checks = {
    "authority-aware sidebar overload": "status: KalivSidebarStatus" in src and "vram: KalivVramTelemetry" in src,
    "VRAM presentation remains evidence-driven": "presentVram(vram)" in src and "VRAM ikke målt" not in src,
    "performance presentation remains evidence-driven": "presentPerformance(performance)" in src,
    "no reference-rig VRAM numbers": "6.2" not in src and "12.0" not in src,
    "light rail derives from theme surface": "if (c.isDark) Color(0x8C14110E) else c.Surface" in src,
    "light active state derives from Signal": "c.Signal.copy(alpha = 0.12f)" in src,
    "light borders derive from Border": "else c.Border" in src,
    "unbound computer-use is forced inactive": "LaunchedEffect(Unit) { onRunningChange(false) }" in src,
    "unbound computer-use does not expose live viewport": "LiveViewport(" not in src,
    "unbound computer-use does not expose approval action": "onApprove" not in src and "Godkend" not in src,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"  {'PASS' if ok else 'FAIL'}: {name}")

if failed:
    raise SystemExit("Agent 3 pkt. 8 integration chrome failed: " + ", ".join(failed))

print(f"\nAgent 3 pkt. 8 integration chrome: {len(checks)} passed")
