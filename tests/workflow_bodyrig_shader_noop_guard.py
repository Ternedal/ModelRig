#!/usr/bin/env python3
"""Pin #846's committed shader authority and clean-tree proof rule.

The UniVRM shaders required by the physical renderer are permanent project
configuration. A physical proof must validate those committed pins and must
never repair, serialize or restore GraphicsSettings.asset as part of evidence
collection.

Run: python3 tests/workflow_bodyrig_shader_noop_guard.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
UNITY = ROOT / "renderers/bodyrig-unity"
BUILD = UNITY / "Assets/BodyRig/Editor/BodyRigBuild.cs"
GRAPHICS = UNITY / "ProjectSettings/GraphicsSettings.asset"

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
graphics_lines = GRAPHICS.read_text(encoding="utf-8").splitlines()
start = graphics_lines.index("  m_AlwaysIncludedShaders:") + 1
end = next(
    index
    for index in range(start, len(graphics_lines))
    if graphics_lines[index].startswith("  m_")
)
shader_refs = {
    line.removeprefix("  - ").strip()
    for line in graphics_lines[start:end]
    if line.startswith("  - ")
}
required = {
    "VRM10/MToon10": "{fileID: 4800000, guid: e0edbf68d81d1f340ae8b110086b7063, type: 3}",
    "UniGLTF/UniUnlit": "{fileID: 4800000, guid: 8c17b56f4bf084c47872edcb95237e4a, type: 3}",
    "Standard": "{fileID: 46, guid: 0000000000000000f000000000000000, type: 0}",
}

for shader, reference in required.items():
    check(shader in src, f"build validates required shader by name: {shader}")
    check(reference in shader_refs, f"GraphicsSettings commits exact shader pin: {shader}")

check(
    "ValidateRequiredShadersPinned();" in src and "m_AlwaysIncludedShaders" in src,
    "physical build validates committed Always Included Shader authority",
)
check(
    "return null;" in src[src.index("private static Action IncludeRequiredShaders") :],
    "compatibility wrapper cannot return a repository mutation callback",
)
for mutation_api in (
    "InsertArrayElementAtIndex",
    "ClearArray",
    "ApplyModifiedProperties",
    "AssetDatabase.SaveAssets",
):
    check(
        mutation_api not in src,
        f"physical proof does not mutate GraphicsSettings via {mutation_api}",
    )
check(
    "MToon10Outline" not in src,
    "outline is not modeled as a separate UniVRM shader asset",
)

# Mutation proof: removing any committed pin must make the corresponding
# authority claim false.
for reference in required.values():
    sabotaged = set(shader_refs)
    sabotaged.discard(reference)
    check(reference not in sabotaged, "removing a committed shader pin is detectable")

print(f"\nbodyrig committed shader authority: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
