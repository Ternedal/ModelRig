from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "tests/support/workflow_desktop_light_theme.py"


def ensure(src: str, old: str, new: str, label: str) -> str:
    if new in src:
        return src
    count = src.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one old match or final form, got {count}")
    return src.replace(old, new, 1)


src = GATE.read_text(encoding="utf-8")
if "from source_code import code_of" not in src:
    raise SystemExit("code_of import missing from support gate")

for old, new, label in (
    ('brand = BRAND.read_text(encoding="utf-8")', 'brand = code_of(BRAND)', "brand source"),
    ('app = APP.read_text(encoding="utf-8")', 'app = code_of(APP)', "app source"),
    ('shell = SHELL.read_text(encoding="utf-8") if SHELL.exists() else ""', 'shell = code_of(SHELL) if SHELL.exists() else ""', "shell source"),
    ('screens = SCREENS.read_text(encoding="utf-8")', 'screens = code_of(SCREENS)', "screens source"),
    ('icon_item = _block("private fun IconRailItem(", "/**\\n * The 246dp left navigation rail")', 'icon_item = _block("private fun IconRailItem(", "@Composable\\nfun KalivNavRail(")', "icon block boundary"),
    ('status = _block("internal fun StatusCircle(", "/**\\n * The inline approval card")', 'status = _block("internal fun StatusCircle(", "@Composable\\ninternal fun ApprovalCard(")', "status block boundary"),
    ('status_small = _block("private fun StatusCircleSmall(", "/**\\n * The live viewport")', 'status_small = _block("private fun StatusCircleSmall(", "@Composable\\nprivate fun LiveViewport(")', "small status block boundary"),
    ('live = _block("private fun LiveViewport(", "/** Approval bar for computer-use")', 'live = _block("private fun LiveViewport(", "@Composable\\nprivate fun ComputerApprovalBar(")', "live viewport boundary"),
):
    src = ensure(src, old, new, label)

marker = '# L2b: source assertions operate on comments-stripped Kotlin so a commented-out\n# binding cannot satisfy the gate. Boundaries therefore use Kotlin symbols only.\n'
predicate = '''def icon_light_boundary(src: str) -> bool:\n    return "if (c.isDark) Color(0x8C14110E) else c.Surface" in src\n\n\n'''
if predicate not in src:
    if marker not in src:
        raise SystemExit("L2b predicate marker missing")
    src = src.replace(marker, marker + predicate, 1)

src = ensure(
    src,
    '''check(\n    "if (c.isDark) Color(0x8C14110E) else c.Surface" in icon,\n    "L2b icon rail bevarer dark literal men bruger Surface i light",\n)''',
    '''check(\n    icon_light_boundary(icon),\n    "L2b icon rail bevarer dark literal men bruger Surface i light",\n)''',
    "icon positive check",
)
src = ensure(
    src,
    '''check(\n    "if (c.isDark) Color(0x8C14110E) else c.Surface" not in sabotaged_icon,\n    "L2b unconditional icon-rail sabotage fanges",\n)''',
    '''check(\n    not icon_light_boundary(sabotaged_icon),\n    "L2b unconditional icon-rail sabotage fanges",\n)''',
    "icon sabotage check",
)

GATE.write_text(src, encoding="utf-8")
print("code-aware L2b gate correction applied")
