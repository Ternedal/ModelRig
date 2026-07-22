#!/usr/bin/env python3
"""Apply only the T-044 desktop Control Center navigation changes."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/App.kt"


def replace_once(old: str, new: str) -> None:
    text = TARGET.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"App.kt: expected one match, found {count}: {old[:180]!r}")
    TARGET.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "        var showAudit by remember { mutableStateOf(false) }\n",
    "        var showAudit by remember { mutableStateOf(false) }\n"
    "        var showControlCenter by remember { mutableStateOf(false) }\n",
)
replace_once(
    "                ToolbarChip(\"Handlingslog\", filled = false) { showAudit = true }\n"
    "                Spacer(Modifier.width(8.dp))\n",
    "                ToolbarChip(\n"
    "                    \"Control Center\",\n"
    "                    enabled = deviceToken.isNotBlank(),\n"
    "                    filled = false,\n"
    "                ) { showControlCenter = true }\n"
    "                Spacer(Modifier.width(8.dp))\n"
    "                ToolbarChip(\"Handlingslog\", filled = false) { showAudit = true }\n"
    "                Spacer(Modifier.width(8.dp))\n",
)
replace_once(
    "        if (showAudit) {\n",
    "        if (showControlCenter) {\n"
    "            DesktopControlCenterDialog(\n"
    "                baseUrl = localUrl,\n"
    "                token = deviceToken,\n"
    "                onDismiss = { showControlCenter = false },\n"
    "            )\n"
    "        }\n\n"
    "        if (showAudit) {\n",
)
print("T-044 desktop Control Center navigation patch applied")
