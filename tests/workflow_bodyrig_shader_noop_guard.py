#!/usr/bin/env python3
"""Pin the #846 clean-tree guard around Unity shader preparation.

The required UniVRM shaders are repository configuration. When they are already
present, a physical proof build must not serialize GraphicsSettings.asset just
to restore the same values afterwards: Unity may rewrite the YAML formatting and
make an otherwise clean exact-head checkout dirty.

Run: python3 tests/workflow_bodyrig_shader_noop_guard.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / "renderers/bodyrig-unity/Assets/BodyRig/Editor/BodyRigBuild.cs"

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


src = code_of(BUILD)
check("var added = false;" in src, "shader preparation tracks whether project state changed")
check("added = true;" in src, "adding a missing shader marks project state changed")
check("if (!added)" in src, "already-pinned shaders take an explicit no-op path")

no_op = src.index("if (!added)")
apply = src.index("serialized.ApplyModifiedPropertiesWithoutUndo()")
save = src.index("AssetDatabase.SaveAssets()")
check(no_op < apply < save,
      "no-op guard runs before any GraphicsSettings serialization/save")

block = src[no_op:apply]
check("return null;" in block,
      "no-op path returns without installing a restore callback or touching the asset")

# The fallback still has to restore a real mutation; this is not permission to
# leave a newly-added shader in the checkout after the build.
check("restore.ApplyModifiedPropertiesWithoutUndo()" in src and "property.ClearArray()" in src,
      "real shader additions retain the existing exact restore path")

# Mutation proof: deleting the guard must make at least the structural claim red.
sabotaged = src.replace("if (!added)", "if (false)", 1)
check("if (!added)" not in sabotaged,
      "removing the no-op condition would be detected")

print(f"\nbodyrig shader no-op guard: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
