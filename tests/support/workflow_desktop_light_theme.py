#!/usr/bin/env python3
"""Focused desktop light-theme authority for #779 pkt. 5 / #1270 / #1274 / #1277.

This support gate measures product boundaries that the generic token contrast
gate cannot see: which token roles desktop Brand.kt binds to its light palette,
and whether the default CHAT shell actually selects theme-aware application
chrome. It is invoked by the existing top-level workflow_design_token_contrast.py
gate so focused desktop slices do not silently change CURRENT_STATE's top-level
test inventory authority.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "desktop" / "composeApp" / "src" / "main" / "kotlin" / "dk" / "ternedal" / "modelrig" / "desktop"
BRAND = DESKTOP / "Brand.kt"
SHELL = DESKTOP / "KalivLightChrome.kt"
APP = DESKTOP / "App.kt"
SCREENS = DESKTOP / "KalivScreens.kt"
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
elevated = color["light"]["elevated"]
light_text = color["light"]["text"]
light_warn = color["light"]["warn"]
ivory = "#F7F4EF"
primary_ink = "#FFF6E9"
bronze = color["brand"]["bronze"]
old_gradient_top = "#A87B3B"

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

historical = contrast(bronze, canvas)
check(
    historical < AA_TEXT,
    f"historical brand.bronze paa light canvas demonstrerer defekten ({historical:.2f}:1)",
)

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

sabotaged = shell.replace(
    "if (c.isDark) Color(0x990B0A09) else c.Surface",
    "Color(0x990B0A09)",
    1,
)
check(not shell_light_boundary(sabotaged), "unconditional dark titlebar sabotage fanges")


# L2b source assertions operate on comments-stripped Kotlin so commented-out
# bindings cannot satisfy the gate. Boundaries therefore use Kotlin symbols.
screens = code_of(SCREENS)


def _block(start: str, end: str | None = None) -> str:
    a = screens.index(start)
    b = screens.index(end, a) if end is not None else len(screens)
    return screens[a:b]


icon = _block("fun KalivIconRail(", "@Composable\nprivate fun IconRailItem")
icon_item = _block("private fun IconRailItem(", "@Composable\nfun KalivNavRail(")
agent = _block("fun KalivAgentCockpit(", "@Composable\nprivate fun AgentIdlePrompt")
agent_idle = _block("private fun AgentIdlePrompt()", "@Composable\nprivate fun AgentBubble")
agent_bubble = _block("private fun AgentBubble(", "@Composable\ninternal fun AgentComposer")
plan_row = _block("private fun PlanRow(", "@Composable\ninternal fun StatusCircle")
status = _block("internal fun StatusCircle(", "@Composable\ninternal fun ApprovalCard")
approval = _block("internal fun ApprovalCard(", "@Composable\nprivate fun LogEntry")
computer = _block("fun KalivComputerUse(", "@Composable\nprivate fun UseStepRow")
use_row = _block("private fun UseStepRow(", "@Composable\nprivate fun StatusCircleSmall")
status_small = _block("private fun StatusCircleSmall(", "@Composable\nprivate fun LiveViewport")
live = _block("private fun LiveViewport(", "@Composable\nprivate fun ComputerApprovalBar(")
computer_approval = _block("private fun ComputerApprovalBar(", "@Composable\nprivate fun ResultBar")
result_bar = _block("private fun ResultBar(")

check(
    "if (c.isDark) Color(0x8C14110E) else c.Surface" in icon,
    "L2b icon rail bevarer dark literal men bruger Surface i light",
)
check(
    "c.Signal.copy(alpha = 0.14f)" in icon_item and "else c.TextMuted" in icon_item,
    "L2b icon-state chrome bruger Signal/TextMuted i light",
)
check(
    "if (c.isDark) Color(0x8014110E) else c.Surface" in agent,
    "L2b Agent handlingslog bruger Surface i light",
)
check(
    "else c.Border" in agent_bubble and "else c.TextMuted" in agent_idle,
    "L2b Agent bubble/forslag bruger theme border/ink",
)
check(
    "else c.Border" in plan_row and "c.Danger.copy(alpha = 0.08f)" in status,
    "L2b Agent timeline/status bruger theme roller",
)
check(
    "Brush.verticalGradient(listOf(c.SurfaceHigh, c.Surface))" in approval
    and "Brush.verticalGradient(listOf(c.Signal, c.Signal))" in approval
    and "else c.Graphite" in approval,
    "L2b Agent approval surface/code/approve er theme-aware",
)
check(
    "if (c.isDark) Color(0x8014110E) else c.Surface" in computer
    and "c.Danger.copy(alpha = 0.10f)" in computer,
    "L2b Computer sidepanel/Stop bruger theme Surface/Danger",
)
check(
    "val runningInk = if (c.isDark) c.Warning else c.TextHigh" in computer,
    "L2b Computer running-status bruger AA tekstink i light",
)
check(
    'RiskLevel.WRITE -> Triple(c.Warning.copy(alpha = 0.12f), c.TextHigh, "WRITE")' in screens
    and 'RiskLevel.DESTRUCTIVE -> Triple(c.Danger.copy(alpha = 0.12f), c.TextHigh, "DESTRUCTIVE")' in screens,
    "L2b sma risk-badges bruger TextHigh-ink over semantiske washes i light",
)
check(
    "else c.Border" in use_row and "c.Danger.copy(alpha = 0.08f)" in status_small,
    "L2b Computer timeline/status bruger theme roller",
)
check(
    "Brush.verticalGradient(listOf(c.SurfaceHigh, c.Surface))" in computer_approval
    and "else c.Border" in computer_approval,
    "L2b Computer approval surface/border er theme-aware",
)
check(
    "c.Success.copy(alpha = 0.10f)" in result_bar
    and "c.Danger.copy(alpha = 0.10f)" in result_bar,
    "L2b Computer resultatbar bruger Success/Danger roller",
)

text_on_elevated = contrast(light_text, elevated)
warn_on_elevated = contrast(light_warn, elevated)
check(
    text_on_elevated >= AA_TEXT,
    f"light TextHigh paa elevated er AA for sma status/badge labels ({text_on_elevated:.2f}:1)",
)
check(
    warn_on_elevated < AA_TEXT,
    f"light Warning paa elevated demonstrerer small-text sabotage ({warn_on_elevated:.2f}:1)",
)
primary_on_accent = contrast(primary_ink, accent)
primary_on_old_top = contrast(primary_ink, old_gradient_top)
check(
    primary_on_accent >= AA_TEXT,
    f"light approve Signal + primary ink er AA ({primary_on_accent:.2f}:1)",
)
check(
    primary_on_old_top < AA_TEXT,
    f"gammel gradient-top demonstrerer approve-sabotage ({primary_on_old_top:.2f}:1)",
)

l2b_application = "\n".join(
    [icon, icon_item, agent, agent_idle, agent_bubble, plan_row, status, approval,
     computer, use_row, status_small, computer_approval, result_bar]
)
for forbidden in (
    ".background(Color(0x8C14110E))",
    ".background(Color(0x8014110E))",
    ".background(Color(0xFF100C09))",
    ".border(1.dp, Color(0x4D785A37)",
):
    check(forbidden not in l2b_application, f"L2b app chrome har ingen unconditional {forbidden}")

for literal in (
    "Color(0xFFFBF9F5)",
    "Color(0xFFEDE8E0)",
    "Color(0xFFE06C5A)",
    "Color(0xCC0B0A09)",
):
    check(literal in live, f"LiveViewport exemption bevarer {literal}")

sabotaged_icon = icon.replace(
    "if (c.isDark) Color(0x8C14110E) else c.Surface",
    "Color(0x8C14110E)",
    1,
)
check(
    "if (c.isDark) Color(0x8C14110E) else c.Surface" not in sabotaged_icon,
    "L2b unconditional icon-rail sabotage fanges",
)

print(f"\ndesktop light theme: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
