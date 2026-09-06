"""Static/semantic software checks for the BodyRig Unity/VRM proof renderer.

Run: python3 tests/bodyrig/renderer_contracts.py

These checks prove renderer-wire/software boundaries only. They do not prove a
Unity build, a real VRM load, visual quality or physical acceptance.
"""
from __future__ import annotations

import subprocess
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))

from bodyrig import (  # noqa: E402
    RenderFrameValidationError,
    render_frame_from_mapping,
    render_frame_to_mapping,
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


unity = root / "renderers" / "bodyrig-unity"
project_version_lines = [
    line.strip() for line in
    (unity / "ProjectSettings" / "ProjectVersion.txt").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
# Unity rewrites this file on first import and adds m_EditorVersionWithRevision.
# The pin is the editor version; an exact whole-file match called the editor's
# own bookkeeping a violation.
check(
    "m_EditorVersion: 6000.3.21f1" in project_version_lines
    and all(line.startswith(("m_EditorVersion:", "m_EditorVersionWithRevision:"))
            for line in project_version_lines)
    and all("6000.3.21f1" in line for line in project_version_lines),
    "Unity renderer is pinned to 6000.3.21f1",
)

packages = json.loads(
    (unity / "Packages" / "manifest.json").read_text(encoding="utf-8")
)["dependencies"]
check(
    packages
    == {
        "com.vrmc.gltf": "https://github.com/vrm-c/UniVRM.git?path=/Packages/UniGLTF#v0.131.2",
        "com.vrmc.vrm": "https://github.com/vrm-c/UniVRM.git?path=/Packages/VRM10#v0.131.2",
    },
    "Unity renderer pins only the required VRM 1.0 UniVRM packages",
)

schema = json.loads(
    (root / "docs" / "bodyrig" / "schemas" / "render-frame.schema.json").read_text(
        encoding="utf-8"
    )
)
required = set(schema["required"])
current_personalization_fields = {
    "face_profile_id",
    "face_channels",
    "face_channel_sources",
    "body_motion_profile_id",
    "body_motion_source",
    "head_motion_scale",
    "micro_motion_scale",
    "posture_lean_x",
    "posture_source",
    "resolved_gesture",
    "gesture_resolution_source",
    "dominant_side_hint",
    "gesture_frequency_per_minute",
}
check(
    current_personalization_fields.issubset(required),
    "render-frame schema requires every current M2.2/M2.3 personalization field",
)
check(
    schema.get("additionalProperties") is False,
    "render-frame schema remains fail-closed for unknown top-level renderer controls",
)

fixture_path = unity / "Assets" / "BodyRig" / "Resources" / "bodyrig-demo.json"
fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
frames = fixture.get("frames")
check(
    isinstance(frames, list) and len(frames) >= 8,
    "deterministic renderer fixture contains a useful state sequence",
)

parsed = []
roundtrip_ok = True
for payload in frames:
    frame = render_frame_from_mapping(payload)
    parsed.append(frame)
    roundtrip_ok = roundtrip_ok and render_frame_to_mapping(frame) == payload
check(
    roundtrip_ok,
    "every canned renderer frame roundtrips through the complete canonical Python wire contract",
)

check(
    all(parsed[i].timestamp_ms < parsed[i + 1].timestamp_ms for i in range(len(parsed) - 1)),
    "renderer fixture timestamps are strictly increasing",
)
states = {frame.state.value for frame in parsed}
check(
    {"idle", "listening", "thinking", "speaking", "interrupted"}.issubset(states),
    "renderer fixture covers all M0 proof interaction states",
)
check(
    {frame.speech_timing_mode.value for frame in parsed if frame.speech_timing_mode}
    == {"audio_envelope", "timed"},
    "renderer fixture proves approximate VoiceRig and future timed-viseme modes separately",
)

personalized = next((frame for frame in parsed if frame.body_motion_source == "profile"), None)
check(
    personalized is not None
    and personalized.face_profile_id == "face-demo"
    and personalized.body_motion_profile_id == "motion-demo"
    and personalized.resolved_gesture == "bodyprint:gesture-demo"
    and personalized.gesture_resolution_source == "profile_replay"
    and personalized.dominant_side_hint == "right"
    and personalized.gesture_frequency_per_minute == 12.0,
    "renderer wire retains profile identities, resolved source gesture and motion priors",
)
check(
    personalized is not None
    and dict(personalized.face_channels).get("jaw_open") == 0.72
    and dict(personalized.face_channel_sources).get("jaw_open") == "speech"
    and dict(personalized.face_channel_sources).get("smile") == "profile_semantic",
    "renderer wire retains M2.2 facial channels and their evidence sources",
)

interrupted_index = next(
    (index for index, frame in enumerate(parsed) if frame.state.value == "interrupted"),
    None,
)
check(
    interrupted_index is not None
    and interrupted_index > 0
    and parsed[interrupted_index - 1].gesture == "explain"
    and parsed[interrupted_index].gesture is None
    and parsed[interrupted_index].mouth_open == 0.0
    and parsed[interrupted_index].visemes == (),
    "interruption fixture cancels an active explain gesture and reaches neutral mouth",
)

bad = dict(frames[0])
bad["unexpected_renderer_control"] = "LeftEyeBone"
try:
    render_frame_from_mapping(bad)
except RenderFrameValidationError:
    check(True, "canonical render-frame contract rejects renderer-specific extra controls")
else:
    check(False, "canonical render-frame contract rejects renderer-specific extra controls")

bad_sources = json.loads(json.dumps(frames[4]))
bad_sources["face_channel_sources"][0]["id"] = "wrong_channel"
try:
    render_frame_from_mapping(bad_sources)
except RenderFrameValidationError:
    check(True, "facial channel/source mismatch fails closed instead of guessing")
else:
    check(False, "facial channel/source mismatch fails closed instead of guessing")

bad_frequency = json.loads(json.dumps(frames[0]))
bad_frequency["gesture_frequency_per_minute"] = {"present": False, "value": 1.0}
try:
    render_frame_from_mapping(bad_frequency)
except RenderFrameValidationError:
    check(True, "missing gesture-frequency evidence cannot be silently converted into numeric zero/nonzero")
else:
    check(False, "missing gesture-frequency evidence cannot be silently converted into numeric zero/nonzero")

runtime_dir = unity / "Assets" / "BodyRig" / "Runtime"
required_sources = {
    "BodyRigRenderFrame.cs",
    "BodyRigVrmRenderer.cs",
    "BodyRigVrmLoader.cs",
    "BodyRigFixturePlayer.cs",
    "BodyRigGestureRouter.cs",
    "BodyRigProceduralGestureDriver.cs",
    "BodyRigDemoBootstrap.cs",
}
check(
    required_sources.issubset({path.name for path in runtime_dir.glob("*.cs")}),
    "Unity proof contains wire, loader, renderer, gesture, fixture and bootstrap components",
)

wire_source = (runtime_dir / "BodyRigRenderFrame.cs").read_text(encoding="utf-8")
check(
    all(
        token in wire_source
        for token in (
            "face_channels",
            "face_channel_sources",
            "body_motion_profile_id",
            "resolved_gesture",
            "gesture_frequency_per_minute",
        )
    ),
    "Unity wire object retains all current personalized renderer-neutral surfaces",
)
check(
    "face channel/source counts must match" in wire_source
    and "GestureResolutionSources" in wire_source
    and "Absent gesture_frequency_per_minute" in wire_source,
    "Unity wire validation preserves channel/source and unknown-vs-zero boundaries",
)

renderer_source = (runtime_dir / "BodyRigVrmRenderer.cs").read_text(encoding="utf-8")
check(
    "ExpressionPreset.blink" in renderer_source
    and "ExpressionPreset.aa" in renderer_source
    and "ExpressionPreset.oh" in renderer_source,
    "VRM preset translation lives in the renderer adapter",
)
check(
    'frame.state != "speaking"' in renderer_source
    and "ClearFace();" in renderer_source,
    "renderer fail-safe clears mouth output outside speaking state",
)
check(
    'frame.state == "interrupted"' in renderer_source
    and "gestureRouter.Cancel();" in renderer_source
    and "proceduralGestureDriver.Cancel();" in renderer_source,
    "renderer interruption explicitly cancels authored and procedural gesture paths",
)
check(
    "HumanBodyBones.Head" in renderer_source
    and "HumanBodyBones.LeftEye" in renderer_source
    and "HumanBodyBones.RightEye" in renderer_source,
    "humanoid head/eye resolution is confined to the Unity adapter",
)
check(
    "frame.resolved_gesture" not in renderer_source,
    "draft Unity renderer does not reinterpret bodyprint replay ids as Animator or VRMA controls",
)

loader_source = (runtime_dir / "BodyRigVrmLoader.cs").read_text(encoding="utf-8")
check(
    "Vrm10.LoadPathAsync" in loader_source
    and "canLoadVrm0X: false" in loader_source
    and "FirstPerson.SetupAsync" in loader_source,
    "loader is explicitly VRM 1.0-only and performs UniVRM first-person setup",
)

player_source = (runtime_dir / "BodyRigFixturePlayer.cs").read_text(encoding="utf-8")
check(
    "if (!renderer.IsBound)" in player_source
    and player_source.index("if (!renderer.IsBound)") < player_source.index("var elapsedMs"),
    "demo timeline cannot consume frames before async VRM binding completes",
)
check(
    "timestamp_ms + loopHoldMs" in player_source,
    "looping demo keeps the final fixture pose reachable before rewind",
)

# The runtime needs an assembly definition. Without one the code lands in
# Assembly-CSharp, which references UniGLTF and VRM10 but NOT UniGLTF.Utils
# -- UniVRM marks that one not auto-referenced. Measured on the rig 6/9:
# IAwaitCaller is defined in UniGLTF.Utils, and the first compilation any of
# this code ever saw failed on exactly that (CS0012).
import json as _json  # noqa: E402
_asmdef = _json.loads((runtime_dir / "BodyRig.Runtime.asmdef").read_text(encoding="utf-8"))
check("UniGLTF.Utils" in _asmdef["references"],
      "the runtime assembly references UniGLTF.Utils, where IAwaitCaller lives")
check({"UniGLTF", "VRM10"} <= set(_asmdef["references"]),
      "the runtime assembly references the UniVRM assemblies it loads through")
check(_asmdef.get("autoReferenced") is True,
      "the editor build assembly can still see the runtime")

# The proof scene is generated build input. BodyRigBuild deletes it in its
# finally block, so if it is ever tracked the next proof run starts with a
# dirty tree and refuses -- which is what happened on the rig 6/9.
_tracked = subprocess.run(
    ["git", "ls-files", "renderers/bodyrig-unity/Assets/BodyRig/Scenes"],
    cwd=root, capture_output=True, text=True).stdout.split()
check(not _tracked, f"the generated proof scene is not tracked {_tracked or ''}")

# UniVRM finds its shaders by name at load time, and a player build strips
# what no scene references. The first run of the built proof died on
# "ArgumentNullException: Parameter name: Shader" inside MaterialFactory,
# after a successful build and a successful VRM parse.
_build_source = (runtime_dir.parent / "Editor" / "BodyRigBuild.cs").read_text(encoding="utf-8")
for _shader in ("VRM10/MToon10", "UniGLTF/UniUnlit"):
    check(_shader in _build_source, f"the build pins the shader UniVRM loads by name: {_shader}")
check("m_AlwaysIncludedShaders" in _build_source,
      "the shaders are pinned through Always Included Shaders, which is what a player build honours")
check(_build_source.index("restoreShaders") < _build_source.index("IncludeRequiredShaders()")
      or "restoreShaders()" in _build_source,
      "the graphics settings change is restored, so the repository stays clean for the next proof")

router_source = (runtime_dir / "BodyRigGestureRouter.cs").read_text(encoding="utf-8")
check(
    "public void Cancel()" in router_source
    and "cancelTrigger" in router_source
    and "CrossFadeInFixedTime" in router_source,
    "authored gesture adapter has an explicit cancellation path",
)

procedural_source = (
    runtime_dir / "BodyRigProceduralGestureDriver.cs"
).read_text(encoding="utf-8")
check(
    "HumanBodyBones.LeftUpperArm" in procedural_source
    and "HumanBodyBones.RightUpperArm" in procedural_source
    and 'state != "speaking" || intent != "explain"' in procedural_source,
    "procedural explain fallback is renderer-local and only active while speaking",
)
check(
    "public void Cancel()" in procedural_source
    and "leftUpperArm.localRotation = leftUpperBase" in procedural_source
    and "rightUpperArm.localRotation = rightUpperBase" in procedural_source,
    "procedural gesture cancellation restores the humanoid arm baseline",
)

core_sources = "\n".join(
    path.read_text(encoding="utf-8") for path in (root / "bodyrig").glob("*.py")
)
check(
    "HumanBodyBones" not in core_sources and "ExpressionPreset" not in core_sources,
    "BodyRig core remains renderer-independent",
)

readme = (unity / "README.md").read_text(encoding="utf-8")
check(
    "BODYRIG_VRM_PATH" in readme
    and "BodyRigBuild.BuildWindows" in readme
    and "audio_envelope" in readme,
    "renderer proof documents reproducible run/build steps and timing fidelity",
)
check(
    "bodyrig_prepare_renderer_profile.py" in readme,
    "renderer proof documents the M2.7 current-profile digest-bound preparation path",
)

print(f"BodyRig Unity renderer software contracts: {passed} passed, {failed} failed")
raise SystemExit(0 if failed == 0 else 1)
