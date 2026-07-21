#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
screen = (root / "android/app/src/main/java/dk/ternedal/modelrig/ui/ScheduleScreen.kt").read_text(encoding="utf-8")
contract = (root / "android/app/src/main/java/dk/ternedal/modelrig/net/SchedulerToolCatalog.kt").read_text(encoding="utf-8")
loader = (root / "android/app/src/main/java/dk/ternedal/modelrig/net/SchedulerToolCatalogLoader.kt").read_text(encoding="utf-8")

checks = {
    "screen uses authoritative scheduler catalog": "SchedulerToolCatalogLoader(base, token).load()" in screen,
    "picker chips are disabled from server-owned eligibility": "enabled = !busy && info.selectable" in screen,
    "preview rechecks selected tool": "selectedTool?.selectable != true" in screen,
    "preview button requires selectable tool": "selectedTool?.selectable == true" in screen,
    "tool field is read only": "readOnly = true" in screen,
    "manual tool text editing is absent": "onValueChange = { tool = it" not in screen,
    "blocked tools show a reason": "info.disabledReason" in screen,
    "contract has no local allowlist": "setOf(" not in contract and "listOf(\"current_datetime\"" not in contract,
    "missing metadata fails closed": "metadataError == null" in contract and "schedulable == true" in contract,
    "loader reads existing tools endpoint": '"/api/v1/tools"' in loader,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"  {'PASS' if ok else 'FAIL'}: {name}")

print(f"android scheduler picker contract: {len(checks) - len(failed)} passed, {len(failed)} failed")
if failed:
    raise SystemExit(1)
