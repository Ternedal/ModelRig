#!/usr/bin/env python3
"""The advertised Stage B paths must use the strict wizard and final gate."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = (ROOT / "START_STAGE_B_TEST.cmd").read_text(encoding="utf-8").lower()
VERIFY = (ROOT / "VERIFY_STAGE_B_EVIDENCE.cmd").read_text(encoding="utf-8").lower()
WIZARD = (ROOT / "scripts" / "stage_b_one_click_v2.py").read_text(encoding="utf-8")
STRICT = (ROOT / "scripts" / "stage_b_strict_evidence.py").read_text(encoding="utf-8")
FINAL = (ROOT / "scripts" / "stage_b_physical_gate_v2.py").read_text(encoding="utf-8")
EXAMPLE = (ROOT / "eval" / "appliance_lifecycle_observations.example.json").read_text(encoding="utf-8")

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


check("stage_b_one_click_v2.py" in START, "double-click path uses the strict wizard")
check("stage_b_physical_gate_v2.py" in VERIFY, "final verifier uses the strict final gate")
check('EXPECTED_SOURCE_VERSION = "1.58.150"' in WIZARD, "wizard pins the executable source release")
check('EXPECTED_TARGET_VERSION = "1.58.151"' in WIZARD, "wizard pins the target release")
check("gh\", \"attestation\", \"verify" in WIZARD, "wizard verifies GitHub build provenance")
check("expected_sha256" in WIZARD and "actual_sha256" in WIZARD, "wizard measures bootstrap checksum identity")
check('observed_state == "swapping" and observed_swapped' in WIZARD, "wizard kills only after a recorded live swap")
check('[str(updater), "-recover"]' in WIZARD, "wizard performs offline whole-set recovery")
check("all_live_executables_present" in WIZARD, "wizard proves every live executable remains present")
check("stage_b_strict_evidence.py" in FINAL, "final wrapper executes the strict semantic gate")
check("strict_stage_b" in FINAL and "strict_evidence_complete" in FINAL, "final receipt hash-binds strict evidence")
check("good_update.source_version must be" in STRICT, "strict gate rejects a non-1.58.150 source")
check("updater_bootstrap provenance was not verified" in STRICT, "strict gate requires measured provenance")
check("did not observe a completed live swap" in STRICT, "strict gate requires a real interrupted swap")
check('"updater_bootstrap"' in EXAMPLE, "observation template carries bootstrap evidence")
check('"appliance_interruption"' in EXAMPLE, "observation template carries interruption evidence")

for text, label in ((START, "start launcher"), (VERIFY, "verify launcher"), (WIZARD.lower(), "strict wizard"), (FINAL.lower(), "strict final gate")):
    for forbidden in ("git push", "git tag", "gh release create", "production_activation=true"):
        check(forbidden not in text, f"{label} has no forbidden authority: {forbidden}")

print(f"strict Stage B entrypoints: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
