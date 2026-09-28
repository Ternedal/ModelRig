#!/usr/bin/env python3
"""Static contract for the standalone Kaliv Body Android Unity host.

This proves repository configuration only. It does not claim a successful Unity
Android build, ARCore runtime, device launch, networking, or production activation.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "renderers" / "bodyrig-unity"
SETTINGS = (PROJECT / "ProjectSettings" / "ProjectSettings.asset").read_text(encoding="utf-8")
BUILD = code_of(PROJECT / "Assets" / "BodyRig" / "Editor" / "BodyRigBuild.cs")
BRIDGE = code_of(
    ROOT
    / "android"
    / "app"
    / "src"
    / "main"
    / "java"
    / "dk"
    / "ternedal"
    / "modelrig"
    / "KalivBodyBridge.kt"
)

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


check("companyName: Ternedal" in SETTINGS, "Unity host company identity is pinned")
check("productName: Kaliv Body" in SETTINGS, "Unity host product name is pinned")
check(
    "applicationIdentifier:\n    Android: dk.ternedal.kalivbody" in SETTINGS
    and "overrideDefaultApplicationIdentifier: 1" in SETTINGS,
    "Android package id is explicit rather than Unity-generated",
)
check("AndroidMinSdkVersion: 28" in SETTINGS, "Android minimum SDK is explicit")
check("AndroidTargetArchitectures: 2" in SETTINGS, "Android host remains ARM64")
check("AndroidIsGame: 0" in SETTINGS, "Kaliv Body is configured as an app, not a game")

for required in (
    "public static void BuildAndroid()",
    'NamedBuildTarget.Android',
    '"dk.ternedal.kalivbody"',
    '"Kaliv Body"',
    '"BODYRIG_ANDROID_BUILD_PATH"',
    '"Build/Android/KalivBody.apk"',
    "target = BuildTarget.Android",
    "options = BuildOptions.StrictMode",
):
    check(required in BUILD, f"Android batch build contract contains {required}")

check(
    'PACKAGE = "dk.ternedal.kalivbody"' in BRIDGE,
    "Kaliv launch bridge package matches the Unity Android application id",
)
check(
    'EXTRA_RIG_URL = "bodyrig_rig_url"' in BRIDGE
    and 'EXTRA_RIG_TOKEN = "bodyrig_rig_token"' in BRIDGE,
    "Kaliv launch bridge retains the rig-link intent contract",
)

for forbidden in (
    "AndroidKeystorePass",
    "AndroidKeyaliasPass",
    "bodyrig_rig_token=",
):
    check(forbidden not in SETTINGS and forbidden not in BUILD, f"no secret host config is committed: {forbidden}")

print(f"\nBodyRig Android host software contract: {passed} passed, {failed} failed")
raise SystemExit(0 if failed == 0 else 1)
