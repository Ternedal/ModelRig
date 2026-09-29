#!/usr/bin/env python3
"""Static contract for the Kaliv Body Android physical host qualifier.

This gate proves the operator script is exact-head, fail-closed and bounded.
It does not claim that a device run has happened.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = code_of(ROOT / "scripts" / "run-kaliv-body-android-validation.ps1")
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
    "[Parameter(Mandatory = $true)]",
    "[ValidatePattern('^[0-9a-fA-F]{40}$')]",
    'git -C $repoRoot',
    '"rev-parse", "HEAD"',
    '"status", "--porcelain=v1", "--untracked-files=all"',
    '$requiredUnity = "6000.3.21f1"',
    '"-buildTarget", "Android"',
    '"ModelRig.BodyRig.UnityRenderer.Editor.BodyRigBuild.BuildAndroid"',
    '$appId = "dk.ternedal.kalivbody"',
    "Get-SingleAdbDevice",
    "install -r $apkPath",
    "shell monkey -p $appId",
    "shell pidof $appId",
    "logcat -d -v threadtime",
    'schema = "modelrig.kaliv-body.android-host-qualification/v1"',
    "production_activation = $false",
    "visual_acceptance = $false",
    "release_gate_satisfied = $false",
    "[switch]$ProveRigLink",
    "KALIV_BODY_RIG_URL",
    "KALIV_BODY_RIG_TOKEN",
    "bodyrig_rig_url",
    "bodyrig_rig_token",
    "BodyRig: rig link resolved from intent (",
    "rig_link_token_leak_observed",
):
    check(required in SCRIPT, f"physical host qualifier contains {required}")

check(
    SCRIPT.index("Assert-CleanTree") < SCRIPT.index('"[1/4] Unity package restore'),
    "clean-tree check precedes Unity build",
)
check(
    SCRIPT.count("Assert-CleanTree") >= 2,
    "clean-tree is rechecked after Unity build",
)
check(
    "Expected exactly one authorized ADB device" in SCRIPT,
    "multi-device ambiguity fails closed",
)
check(
    "FATAL EXCEPTION" in SCRIPT and "fatal_package_crash_observed" in SCRIPT,
    "launch evidence rejects a package-scoped fatal crash",
)

for forbidden in (
    "approval_token",
    "production_activation = $true",
    "arcore_runtime_qualified = $true",
    "visual_acceptance = $true",
):
    check(forbidden not in SCRIPT, f"qualifier does not overclaim authority: {forbidden}")

check(
    '$env:KALIV_BODY_RIG_TOKEN' in SCRIPT
    and "rig_link_token_leak_observed = [bool]$rigLinkTokenLeakObserved" in SCRIPT,
    "RigLink token is used only as runtime input and leak-check evidence",
)
check(
    "rig_link_qualified = [bool]$rigLinkResolvedFromIntent" in SCRIPT,
    "RigLink qualification is bound to an observed intent-resolution marker",
)
check(
    "arcore_runtime_qualified = [bool]$arCoreRuntimeQualified" in SCRIPT
    and "arcore_runtime_qualified = $true" not in SCRIPT,
    "ARCore qualification is evidence-bound and cannot be synthesized",
)
check(
    "KALIV_BODY_RIG_TOKEN =" not in SCRIPT
    and "rig_token =" not in SCRIPT
    and "rig_url =" not in SCRIPT,
    "receipt schema does not persist rig token or rig URL values",
)

for ignored in (
    "/validation/kaliv-body-android-latest.json",
    "/validation/kaliv-body-unity-build.log",
    "/validation/kaliv-body-android-logcat.txt",
):
    check(ignored in GITIGNORE, f"rolling evidence is ignored: {ignored}")

print(f"\nKaliv Body Android physical host contract: {passed} passed, {failed} failed")
raise SystemExit(0 if failed == 0 else 1)
