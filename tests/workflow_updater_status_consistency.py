"""Fail closed if updater design status regresses behind implemented software.

The generated CURRENT_STATE page intentionally repeats each design document's
own Status header. If UPDATER_DESIGN.md drifts back to claiming self-update is
unimplemented while the implementation-status addendum says code-complete, the
generator would faithfully publish the contradiction. This test makes that
specific source-of-truth split a red build.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "UPDATER_DESIGN.md"
IMPLEMENTATION = ROOT / "UPDATER_IMPLEMENTATION_STATUS.md"

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def status_line(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines()[:12]:
        if line.startswith("**Status:**"):
            return line
    return ""


design = DESIGN.read_text(encoding="utf-8")
implementation = IMPLEMENTATION.read_text(encoding="utf-8")
design_status = status_line(DESIGN)
implementation_status = status_line(IMPLEMENTATION)

check(bool(design_status), "UPDATER_DESIGN declares a machine-readable Status header")
check(bool(implementation_status), "implementation addendum declares a Status header")
check("implementation complete" in design_status.lower(),
      "authoritative design says updater software implementation is complete")
check("ci-verificeret" in design_status.lower(),
      "authoritative design preserves the CI-verified boundary")
check("#401" in design_status,
      "authoritative design points physical signed-release acceptance to #401")
check("self-update UDESTÅR" not in design,
      "the obsolete self-update-unimplemented claim cannot return")
check("IMPLEMENTERET" in design and "4a. Updater self-update" in design,
      "section 4 records self-update as implemented rather than future handoff")
check("4b. Windows-native replace" in design and "IMPLEMENTERET" in design,
      "section 4 records Windows-native replacement as implemented")
check("4d. Recovery ved boot" in design and "IMPLEMENTERET" in design,
      "section 4 records recovery-at-boot as implemented")
check("4c. Proces-level acceptance matrix" in design and "FYSISK UDESTÅR" in design,
      "the real process-level physical acceptance remains explicitly outstanding")
check("code-complete" in implementation_status.lower(),
      "implementation addendum still states code-complete")
check("#401" in implementation_status,
      "implementation addendum and authoritative design share the physical issue")
check("supersedes the outdated" not in implementation.lower(),
      "implementation addendum no longer claims authority over stale design labels")

print(f"\n===== UPDATER STATUS CONSISTENCY: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
