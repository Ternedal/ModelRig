from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "tests/support/workflow_desktop_light_theme.py"


def once(src: str, old: str, new: str, label: str) -> str:
    count = src.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, got {count}")
    return src.replace(old, new, 1)

src = GATE.read_text(encoding="utf-8")
src = once(
    src,
    "import json\nfrom pathlib import Path\n",
    "import json\nfrom pathlib import Path\n\nfrom source_code import code_of\n",
    "code_of import",
)
src = once(src, 'brand = BRAND.read_text(encoding="utf-8")', 'brand = code_of(BRAND)', "brand source")
src = once(src, 'app = APP.read_text(encoding="utf-8")', 'app = code_of(APP)', "app source")
src = once(src, 'shell = SHELL.read_text(encoding="utf-8") if SHELL.exists() else ""', 'shell = code_of(SHELL) if SHELL.exists() else ""', "shell source")
src = once(src, 'screens = SCREENS.read_text(encoding="utf-8")', 'screens = code_of(SCREENS)', "screens source")

# code_of strips comments by design, so block boundaries must be executable source.
src = once(
    src,
    'icon_item = _block("private fun IconRailItem(", "/**\\n * The 246dp left navigation rail")',
    'icon_item = _block("private fun IconRailItem(", "@Composable\\nfun KalivNavRail(")',
    "icon block boundary",
)
src = once(
    src,
    'status = _block("internal fun StatusCircle(", "/**\\n * The inline approval card")',
    'status = _block("internal fun StatusCircle(", "@Composable\\ninternal fun ApprovalCard(")',
    "status block boundary",
)
src = once(
    src,
    'status_small = _block("private fun StatusCircleSmall(", "/**\\n * The live viewport")',
    'status_small = _block("private fun StatusCircleSmall(", "@Composable\\nprivate fun LiveViewport(")',
    "small status block boundary",
)
src = once(
    src,
    'live = _block("private fun LiveViewport(", "/** Approval bar for computer-use")',
    'live = _block("private fun LiveViewport(", "@Composable\\nprivate fun ComputerApprovalBar(")',
    "live viewport boundary",
)

# Use the same predicate for the positive assertion and sabotage proof.
marker = '# L2b: Agent/Computer application chrome is theme-aware. The simulated\n# browser/page in LiveViewport is intentionally outside this authority.\n'
insert = marker + '''\ndef icon_light_boundary(src: str) -> bool:\n    return "if (c.isDark) Color(0x8C14110E) else c.Surface" in src\n\n'''
src = once(src, marker, insert, "icon predicate")
src = once(
    src,
    '''check(\n    "if (c.isDark) Color(0x8C14110E) else c.Surface" in icon,\n    "L2b icon rail bevarer dark literal men bruger Surface i light",\n)''',
    '''check(\n    icon_light_boundary(icon),\n    "L2b icon rail bevarer dark literal men bruger Surface i light",\n)''',
    "icon positive check",
)
src = once(
    src,
    '''check(\n    "if (c.isDark) Color(0x8C14110E) else c.Surface" not in sabotaged_icon,\n    "L2b unconditional icon-rail sabotage fanges",\n)''',
    '''check(\n    not icon_light_boundary(sabotaged_icon),\n    "L2b unconditional icon-rail sabotage fanges",\n)''',
    "icon sabotage check",
)

GATE.write_text(src, encoding="utf-8")
print("code-aware L2b gate correction applied")
