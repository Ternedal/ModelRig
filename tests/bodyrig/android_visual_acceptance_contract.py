#!/usr/bin/env python3
"""Static contract for human Kaliv Body Android AR visual acceptance."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = code_of(ROOT / "scripts" / "accept-kaliv-body-android-visual.ps1")
GITIGNORE = code_of(ROOT / ".gitignore")

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


for required in (
    "[ValidatePattern('^[0-9a-fA-F]{40}$')]",
    '"rev-parse", "HEAD"',
    '"status", "--porcelain=v1", "--untracked-files=all"',
    '"modelrig.kaliv-body.android-host-qualification/v1"',
    "host_receipt_sha256",
    "installed",
    "launched",
    "arcore_runtime_qualified",
    "plane_placement_qualified",
    "rig_link_token_leak_observed",
    "[switch]$AvatarVisibleAndStable",
    "[switch]$PlacementMatchesTappedPlane",
    "[switch]$CameraBackgroundTracksRoom",
    "[switch]$BodyAnimationContinuesAfterPlacement",
    "[switch]$NoVisibleCredentialOrDebugLeak",
    '"modelrig.kaliv-body.android-visual-acceptance/v1"',
    "visual_acceptance = $true",
    "production_activation = $false",
    "release_gate_satisfied = $false",
    "directly observed on the physical Android Kaliv Body host",
):
    check(required in SCRIPT, f"visual acceptance contains {required}")

check(
    SCRIPT.index("arcore_runtime_qualified") < SCRIPT.index("visual_acceptance = $true"),
    "visual acceptance is downstream of ARCore runtime qualification",
)
check(
    SCRIPT.index("plane_placement_qualified") < SCRIPT.index("visual_acceptance = $true"),
    "visual acceptance is downstream of physical plane placement",
)
check(
    "All five direct-observation switches are required; partial visual acceptance is forbidden." in SCRIPT,
    "partial human acceptance fails closed",
)
check(
    "if ([bool]$host.rig_link_token_leak_observed)" in SCRIPT,
    "known RigLink token leakage blocks visual acceptance",
)
for forbidden in (
    "production_activation = $true",
    "release_gate_satisfied = $true",
    "bodyrig_rig_token",
    "KALIV_BODY_RIG_TOKEN",
):
    check(forbidden not in SCRIPT, f"visual receipt cannot grant/store {forbidden}")

check(
    "/validation/kaliv-body-android-visual-latest.json" in GITIGNORE,
    "rolling visual acceptance receipt is gitignored",
)

print(f"\nKaliv Body Android visual acceptance contract: {passed} passed, {failed} failed")
raise SystemExit(0 if failed == 0 else 1)
