#!/usr/bin/env python3
"""Apply only the T-044 Control Center navigation changes to AppUi.kt."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "android/app/src/main/java/dk/ternedal/modelrig/ui/AppUi.kt"


def replace_once(old: str, new: str) -> None:
    text = TARGET.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"AppUi.kt: expected one match, found {count}: {old[:160]!r}")
    TARGET.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "private enum class Screen { Splash, Setup, Chat, Convos, Models, Knowledge, Schedules, CloudPicker, VoiceCloudPicker }",
    "private enum class Screen { Splash, Setup, Chat, Convos, Models, Knowledge, Schedules, ControlCenter, CloudPicker, VoiceCloudPicker }",
)
replace_once(
    "Screen.Setup -> SetupScreen(store, db, onDone = { screen = Screen.Chat })",
    "Screen.Setup -> SetupScreen(\n"
    "                    store,\n"
    "                    db,\n"
    "                    onDone = { screen = Screen.Chat },\n"
    "                    onOpenControlCenter = { screen = Screen.ControlCenter },\n"
    "                )",
)
replace_once(
    "Screen.Schedules -> ScheduleScreen(store = store, onClose = { screen = Screen.Chat })\n",
    "Screen.Schedules -> ScheduleScreen(store = store, onClose = { screen = Screen.Chat })\n"
    "                Screen.ControlCenter -> ControlCenterScreen(\n"
    "                    store = store,\n"
    "                    onClose = { screen = Screen.Setup },\n"
    "                )\n",
)
replace_once(
    "private fun SetupScreen(store: TokenStore, db: ChatDb, onDone: () -> Unit) {",
    "private fun SetupScreen(\n"
    "    store: TokenStore,\n"
    "    db: ChatDb,\n"
    "    onDone: () -> Unit,\n"
    "    onOpenControlCenter: () -> Unit,\n"
    ") {",
)
replace_once(
    "        Text(\"Vælg mindst én kilde\", fontSize = 14.sp, color = KalivTheme.colors.textMuted)\n"
    "        Spacer(Modifier.height(16.dp))\n",
    "        Text(\"Vælg mindst én kilde\", fontSize = 14.sp, color = KalivTheme.colors.textMuted)\n"
    "        if (store.hasRig) {\n"
    "            Spacer(Modifier.height(10.dp))\n"
    "            OutlinedButton(\n"
    "                onClick = onOpenControlCenter,\n"
    "                modifier = Modifier.fillMaxWidth(),\n"
    "            ) {\n"
    "                Text(\"Åbn Control Center\")\n"
    "            }\n"
    "            Text(\n"
    "                \"Read-only drift, routing og freshness fra riggen.\",\n"
    "                color = KalivTheme.colors.textMuted,\n"
    "                fontSize = 11.sp,\n"
    "            )\n"
    "        }\n"
    "        Spacer(Modifier.height(16.dp))\n",
)
print("T-044 Control Center navigation patch applied")
