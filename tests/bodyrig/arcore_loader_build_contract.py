#!/usr/bin/env python3
"""Static contract for temporary ARCore loader activation in Kaliv Body builds.

No physical Android build, ARCore runtime success, visual acceptance or
production activation is claimed here.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "renderers" / "bodyrig-unity"
BUILD = code_of(PROJECT / "Assets" / "BodyRig" / "Editor" / "BodyRigBuild.cs")
SETTINGS = (PROJECT / "ProjectSettings" / "ProjectSettings.asset").read_text(encoding="utf-8")

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


check(
    "scriptingDefineSymbols:\n    Android: BODYRIG_AR" in SETTINGS,
    "Android build explicitly compiles the BODYRIG_AR slice",
)
for required in (
    "ConfigureTemporaryAndroidArCore()",
    "XRGeneralSettings.k_SettingsKey",
    "BuildTargetGroup.Android",
    "ScriptableObject.CreateInstance<XRGeneralSettingsPerBuildTarget>()",
    "CreateDefaultSettingsForBuildTarget(BuildTargetGroup.Android)",
    "CreateDefaultManagerSettingsForBuildTarget(",
    "ScriptableObject.CreateInstance<ARCoreLoader>()",
    "manager.TryAddLoader(loader)",
    "EditorBuildSettings.AddConfigObject(",
    "EditorBuildSettings.RemoveConfigObject(",
    "AssetDatabase.DeleteAsset(TemporaryAndroidXrSettingsPath)",
):
    check(required in BUILD, f"Android ARCore build contract contains {required}")

existing = BUILD[BUILD.index("if (EditorBuildSettings.TryGetConfigObject") : BUILD.index("if (AssetDatabase.LoadAssetAtPath")]
check(
    "if (loader is ARCoreLoader)" in existing
    and "ARCoreLoader is not active" in existing,
    "pre-existing XR settings are accepted only when ARCore is already active",
)
check(
    "return null;" in existing,
    "pre-existing valid XR settings are preserved instead of replaced",
)

android_start = BUILD.index("public static void BuildAndroid()")
android_end = BUILD.index("/// <summary>\n        /// Ensure an Android ARCore loader", android_start)
android = BUILD[android_start:android_end]
check(
    android.index("ConfigureTemporaryAndroidArCore()") < android.index("BuildPipeline.BuildPlayer(options)"),
    "ARCore loader is configured before the Android build starts",
)
check(
    "if (restoreAndroidXr != null)" in android
    and "restoreAndroidXr();" in android
    and android.index("restoreAndroidXr();") > android.index("finally"),
    "temporary XR settings are restored in BuildAndroid finally",
)

check(
    not (PROJECT / "Assets" / "BodyRig" / "XRGeneralSettingsPerBuildTarget.generated.asset").exists(),
    "temporary XR settings asset is not committed",
)
check(
    not (PROJECT / "ProjectSettings" / "XRGeneralSettingsPerBuildTarget.asset").exists(),
    "no hand-authored persistent XR settings asset is committed",
)

print(f"\nBodyRig ARCore loader build contract: {passed} passed, {failed} failed")
raise SystemExit(0 if failed == 0 else 1)
