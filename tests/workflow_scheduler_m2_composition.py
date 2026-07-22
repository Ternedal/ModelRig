#!/usr/bin/env python3
"""Cross-branch composition contract for the Scheduler M2 software candidate."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


screen = (ROOT / "android/app/src/main/java/dk/ternedal/modelrig/ui/ScheduleScreen.kt").read_text(encoding="utf-8")
client = (ROOT / "android/app/src/main/java/dk/ternedal/modelrig/net/ScheduleClient.kt").read_text(encoding="utf-8")
api = (ROOT / "worker/app/schedule_api.py").read_text(encoding="utf-8")
runner = (ROOT / "worker/app/schedule_runner.py").read_text(encoding="utf-8")

check("SchedulerToolCatalogLoader" in screen, "Android uses the authoritative scheduler tool catalog")
check("selectedTool?.selectable == true" in screen, "preview remains fail-closed on schedulability")
check("onValueChange = {}" in screen and "readOnly = true" in screen, "free-text tool selection stays disabled")
check("timezone = timezone.trim()" in screen, "selected timezone is sent in preview")
check("authoritativeScheduleTime" in screen, "Android displays server-authoritative local time")
check("misfirePolicy" in client and "dueAtLocal" in client, "Android wire model carries time semantics")
check("max_concurrency" in api and "overlap_rejections" in api, "operator API exposes single-flight state")
check("install_single_flight" in runner, "production runner installs explicit single-flight")
check((ROOT / "worker/app/scheduler_single_flight.py").is_file(), "single-flight implementation is present")
check((ROOT / "tests/worker_scheduler_single_flight_lease.py").is_file(), "cross-process lease composition test is present")
check((ROOT / "tests/workflow_android_scheduler_picker.py").is_file(), "picker surface contract is present")
check((ROOT / "android/app/src/test/java/dk/ternedal/modelrig/ui/ScheduleTimeDisplayTest.kt").is_file(), "time display test is present")

print(f"\n===== SCHEDULER M2 COMPOSITION: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
