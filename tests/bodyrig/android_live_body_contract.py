#!/usr/bin/env python3
"""Static contract for end-to-end Kaliv Body live-body qualification.

This validates evidence semantics only; it does not claim a physical run.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "support"))
from source_code import code_of  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "renderers" / "bodyrig-unity" / "Assets" / "BodyRig" / "Runtime"

frame = code_of(RUNTIME / "BodyRigFrameSource.cs")
avatar = code_of(RUNTIME / "BodyRigRemoteAvatarSource.cs")
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


apply_index = frame.index("renderer.Apply(frame);")
marker_index = frame.index("BodyRig: first authenticated live frame applied ")
check(
    apply_index < marker_index
    and "if (!firstAppliedLogged)" in frame
    and "firstAppliedLogged = true;" in frame,
    "first live-frame evidence is emitted once and only after renderer.Apply",
)
check(
    "frame.Validate();" in frame
    and frame.index("frame.Validate();") < apply_index
    and "if (frame.timestamp_ms <= lastTimestampMs)" in frame
    and frame.index("if (frame.timestamp_ms <= lastTimestampMs)") < apply_index
    and "if (renderer == null || !renderer.IsBound)" in frame
    and frame.index("if (renderer == null || !renderer.IsBound)") < apply_index,
    "live-frame marker remains downstream of validation, monotonicity and renderer binding",
)

check(
    "await loader.LoadAsync(path);" in avatar
    and "BodyRig: active avatar loaded from rig (" in avatar,
    "remote-avatar evidence is emitted only after existing loader completes",
)
check(
    avatar.index("await loader.LoadAsync(path);")
    < avatar.index("BodyRig: active avatar loaded from rig ("),
    "remote-avatar evidence follows VRM load/bind completion",
)

for required in (
    "[switch]$ProveLiveBody",
    'throw "-ProveLiveBody requires -Launch."',
    "$useRigLinkIntent = $ProveRigLink -or $ProveLiveBody",
    "BodyRig: active avatar loaded from rig (",
    "BodyRig: first authenticated live frame applied (",
    "avatar_from_rig_qualified = [bool]$avatarFromRigQualified",
    "live_frame_qualified = [bool]$liveFrameQualified",
    "live_body_qualified = [bool]($avatarFromRigQualified -and $liveFrameQualified -and $rigLinkResolvedFromIntent)",
):
    check(required in operator, f"live-body operator contains {required}")

check(
    "$useRigLinkIntent" in operator
    and "KALIV_BODY_RIG_URL" in operator
    and "KALIV_BODY_RIG_TOKEN" in operator,
    "live-body proof uses the same explicit RigLink authority inputs",
)
check(
    "rigLinkTokenLeakObserved" in operator
    and "Kaliv Body logcat leaked the rig token value." in operator,
    "live-body proof retains exact-token leak refusal",
)
check(
    "live_body_qualified = $true" not in operator
    and "avatar_from_rig_qualified = $true" not in operator
    and "live_frame_qualified = $true" not in operator,
    "live-body receipt values cannot be synthesized as literals",
)
check(
    "visual_acceptance = $false" in operator
    and "release_gate_satisfied = $false" in operator
    and "production_activation = $false" in operator,
    "live-body proof cannot promote visual/release/production authority",
)

print(f"\nKaliv Body live-body physical contract: {passed} passed, {failed} failed")
raise SystemExit(0 if failed == 0 else 1)
