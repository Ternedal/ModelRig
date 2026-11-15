#!/usr/bin/env python3
"""The in-app "Medier" entry must stay wired (#2275 C6 G1).

A Kotlin test proves MediaEntry builds the right intent. It does not prove the
overflow menu uses it: delete the menu item and the Kotlin test stays green,
and the generate screen and the gallery are back to ADB only. So this checks
the call site, as workflow_client_capability_gates does for its gates:

- AppUi.kt has exactly one menu item labelled MediaEntry.LABEL that starts
  MediaEntry.intent(context);
- it sits inside the paired-rig block (`if (mode == "rig" && store.hasRig)`),
  next to "Opgaver" and "Personer";
- MainActivity still routes EXTRA_MEDIA_GENERATE to MediaGenerateScreen.

Source is read through tests/support/source_code.code_of, so a commented-out
item does not count (workflow_gates_read_code).

Run: python3 tests/workflow_android_media_entry.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "support"))
from source_code import code_of  # noqa: E402  comments removed: a commented-out item must fail
APP = ROOT / "android/app/src/main/java/dk/ternedal/modelrig"
APP_UI = APP / "ui/AppUi.kt"
MAIN = APP / "MainActivity.kt"
ENTRY = APP / "ui/MediaEntry.kt"

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(("PASS: " if ok else "FAIL: ") + message)
    if not ok:
        failures.append(message)


ui = code_of(APP_UI)
items = [m.start() for m in re.finditer(r"DropdownMenuItem\(text = \{ Text\(MediaEntry\.LABEL\) \}", ui)]
check(len(items) == 1, f"exactly one 'Medier' overflow item in AppUi.kt (found {len(items)})")
if items:
    start = items[0]
    body = ui[start:start + 400]
    check("context.startActivity(MediaEntry.intent(context))" in body,
          "the item starts MediaEntry.intent(context)")
    gate = ui.rfind('if (mode == "rig" && store.hasRig) {', 0, start)
    check(gate != -1, "the item is inside the paired-rig block")
    if gate != -1:
        between = ui[gate:start]
        depth = between.count("{") - between.count("}")
        check(depth >= 1, "the paired-rig block is still open at the item (it is not after the block)")
        check('"Opgaver"' in between and '"Personer"' in between,
              "it sits with the other rig-only entries (Opgaver, Personer)")

entry = code_of(ENTRY)
check('const val LABEL = "Medier"' in entry, 'the label is "Medier"')
check("putExtra(MainActivity.EXTRA_MEDIA_GENERATE, true)" in entry, "MediaEntry opens the generate screen")

main = code_of(MAIN)
check(re.search(r"openMediaGenerate\s*=\s*intent\?\.getBooleanExtra\(EXTRA_MEDIA_GENERATE, false\)", main) is not None,
      "MainActivity reads EXTRA_MEDIA_GENERATE")
route = main.find("openMediaGenerate -> {")
check(route != -1 and "MediaGenerateScreen(" in main[route:route + 400],
      "MainActivity routes it to MediaGenerateScreen")

print(f"\n{len(failures)} failed")
sys.exit(1 if failures else 0)
