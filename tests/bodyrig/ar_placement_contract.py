#!/usr/bin/env python3
"""Software contract for Slice-D AR placement on the #846 renderer stack.

This is structural/software proof only. It does not claim an Android build,
ARCore runtime proof, visual placement acceptance, or production activation.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "support"))
from source_code import code_of  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "renderers" / "bodyrig-unity" / "Assets" / "BodyRig" / "Runtime"

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


ar_path = RUNTIME / "BodyRigArPlacement.cs"
meta_path = RUNTIME / "BodyRigArPlacement.cs.meta"
check(ar_path.is_file() and meta_path.is_file(),
      "AR source and committed Unity metadata both exist")

ar = code_of(ar_path)
bootstrap = code_of(RUNTIME / "BodyRigDemoBootstrap.cs")
loader = code_of(RUNTIME / "BodyRigVrmLoader.cs")

check(
    "#if BODYRIG_AR" in ar
    and ar.index("#if BODYRIG_AR") < ar.index("using UnityEngine.XR.ARFoundation;"),
    "AR Foundation dependency is compile-bounded behind BODYRIG_AR",
)
check(
    "TrackableType.PlaneWithinPolygon" in ar
    and "raycastManager.Raycast(" in ar
    and "Input.GetTouch(0)" in ar,
    "placement comes only from an explicit touch hit on a detected plane",
)
check(
    "avatarRoot.SetPositionAndRotation(" in ar
    and "HumanBodyBones" not in ar
    and "VRM10" not in ar
    and "renderer.Apply" not in ar,
    "AR placement moves only the loaded avatar root and never owns animation semantics",
)
check(
    "avatarRoot.gameObject.SetActive(false);" in ar
    and "avatarRoot.gameObject.SetActive(true);" in ar
    and "hasPendingPose = true;" in ar,
    "avatar stays hidden until placement and a tap during async load is retained",
)
check(
    "placement.Loader = loader;" in bootstrap
    and "placement.AvatarRoot" not in bootstrap
    and "root.SetActive(false)" not in bootstrap,
    "bootstrap keeps the controller root active and hands placement the loader, not itself",
)

bind = loader.index("renderer.Bind(instance, gazeTarget);")
bound = loader.index("if (!renderer.IsBound)")
handoff = loader.index("arPlacement?.BindAvatarRoot(instance.transform);")
check(
    "#if BODYRIG_AR" in loader
    and bind < bound < handoff,
    "loader hands over the actual VRM child only after renderer binding succeeds",
)
check(
    "production_activation = false" in loader,
    "AR wiring does not change runtime proof production authority",
)

meta = meta_path.read_text(encoding="utf-8").splitlines()
check(
    meta[:1] == ["fileFormatVersion: 2"]
    and len(meta) >= 2
    and meta[1].startswith("guid: ")
    and len(meta[1].removeprefix("guid: ")) == 32,
    "AR source has stable committed Unity GUID metadata",
)

print(f"\nBodyRig AR placement software contract: {passed} passed, {failed} failed")
raise SystemExit(0 if failed == 0 else 1)
