#!/usr/bin/env python3
"""Static contract for evidence-bound BodyRig ARCore runtime qualification.

This validates software wiring and operator-proof semantics only. It does not
claim that a physical Android/ARCore run has happened.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "support"))
from source_code import code_of  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "renderers" / "bodyrig-unity" / "Assets" / "BodyRig" / "Runtime"
PROBE_PATH = RUNTIME / "BodyRigArRuntimeProbe.cs"
META_PATH = RUNTIME / "BodyRigArRuntimeProbe.cs.meta"

probe = code_of(PROBE_PATH)
bootstrap = code_of(RUNTIME / "BodyRigDemoBootstrap.cs")
operator = code_of(ROOT / "scripts" / "run-kaliv-body-android-validation.ps1")

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


check(PROBE_PATH.is_file() and META_PATH.is_file(),
      "ARCore runtime probe and Unity metadata both exist")
check(
    "#if BODYRIG_AR" in probe
    and "using UnityEngine.XR.ARCore;" in probe
    and "using UnityEngine.XR.ARFoundation;" in probe
    and "using UnityEngine.XR.Management;" in probe,
    "runtime probe is compile-bounded and uses pinned XR APIs",
)
for required in (
    "manager.activeLoader is ARCoreLoader",
    "ARSession.state != ARSessionState.SessionTracking",
    "CameraManager.subsystem == null",
    "!CameraManager.subsystem.running",
    "PlaneManager.subsystem == null",
    "!PlaneManager.subsystem.running",
    "RaycastManager.subsystem == null",
    "!RaycastManager.subsystem.running",
    "!CameraBackground.backgroundRenderingEnabled",
    "Qualified = true;",
    "BodyRig: ARCore runtime qualified ",
    "(loader+session-tracking+camera-background+planes+raycast).",
):
    check(required in probe, f"runtime probe contains {required}")

check(
    "var runtimeProbe = root.AddComponent<BodyRigArRuntimeProbe>();" in bootstrap
    and "runtimeProbe.CameraManager = camera.GetComponent<ARCameraManager>();" in bootstrap
    and "runtimeProbe.CameraBackground = camera.GetComponent<ARCameraBackground>();" in bootstrap
    and "FindFirstObjectByType<ARPlaneManager>()" in bootstrap
    and "runtimeProbe.RaycastManager = raycastManager;" in bootstrap,
    "bootstrap wires the probe to the exact live AR managers",
)

for required in (
    "[switch]$ProveArCore",
    'throw "-ProveArCore requires -Launch."',
    "$arCoreRuntimeQualified = $false",
    "BodyRig: ARCore runtime qualified (loader+session-tracking+camera-background+planes+raycast).",
    "arcore_runtime_qualified = [bool]$arCoreRuntimeQualified",
):
    check(required in operator, f"operator qualifier contains {required}")

check(
    operator.index("if ($ProveArCore)") < operator.index("arcore_runtime_qualified = [bool]$arCoreRuntimeQualified"),
    "ARCore receipt value is downstream of observed log evidence",
)
check(
    "arcore_runtime_qualified = $true" not in operator
    and "visual_acceptance = $true" not in operator
    and "release_gate_satisfied = $true" not in operator
    and "production_activation = $true" not in operator,
    "operator proof cannot synthesize stronger authority",
)

meta = META_PATH.read_text(encoding="utf-8").splitlines()
check(
    meta[:1] == ["fileFormatVersion: 2"]
    and len(meta) >= 2
    and meta[1].startswith("guid: ")
    and len(meta[1].removeprefix("guid: ")) == 32,
    "ARCore runtime probe has stable committed Unity GUID metadata",
)

print(f"\nBodyRig ARCore runtime contract: {passed} passed, {failed} failed")
raise SystemExit(0 if failed == 0 else 1)
