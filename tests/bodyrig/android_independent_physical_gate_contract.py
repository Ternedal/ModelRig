#!/usr/bin/env python3
"""Static contract for the independent Kaliv Body Android live-body gate."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
GATE = code_of(ROOT / "scripts" / "kaliv_body_android_physical_gate.py")

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
    'HOST_SCHEMA = "modelrig.kaliv-body.android-host-qualification/v1"',
    'VISUAL_SCHEMA = "modelrig.kaliv-body.android-visual-acceptance/v1"',
    '"modelrig.kaliv-body.android-physical-gate/v1"',
    '"rev-parse", "HEAD"',
    '"status", "--porcelain=v1", "--untracked-files=all"',
    "apk_sha256",
    "apk_size_bytes",
    "logcat_sha256",
    "logcat_size_bytes",
    "host_receipt_sha256",
    "visual_receipt_sha256",
    "rig_link_qualified",
    "arcore_runtime_qualified",
    "plane_placement_qualified",
    "avatar_from_rig_qualified",
    "live_frame_qualified",
    "live_body_qualified",
    "visual_acceptance",
    "rig_link_token_leak_observed",
    "release_gate_satisfied",
    "production_activation",
    "directly observed on the physical Android Kaliv Body host",
    "KALIV BODY ANDROID PHYSICAL GATE: PASS",
    '"evidence_ref"',
    '"kaliv-body-android-physical-gate:"',
):
    check(required in GATE, f"independent gate contains {required}")

check(
    "hashlib.sha256(host_raw).hexdigest()" in GATE
    and 'visual.get("host_receipt_sha256")' in GATE,
    "visual receipt is digest-bound to the exact host receipt bytes",
)
check(
    "_hash_file(" in GATE
    and 'host.get("apk_path")' in GATE
    and 'host.get("logcat_path")' in GATE
    and 'host.get("logcat_sha256")' in GATE
    and 'host.get("logcat_size_bytes")' in GATE,
    "gate independently re-hashes APK and logcat artifacts",
)
check(
    "stat.S_ISLNK" in GATE
    and "MAX_APK_BYTES" in GATE
    and "MAX_LOG_BYTES" in GATE
    and "MAX_JSON_BYTES" in GATE,
    "artifact reads are symlink-refusing and size-bounded",
)
check(
    'host.get("live_body_qualified") is not True' in GATE
    and '"live_body_qualified": True' in GATE,
    "PASS requires end-to-end live-body evidence rather than fixture/local-avatar proof",
)
check(
    "visual_time < host_time" in GATE,
    "visual acceptance cannot predate host qualification",
)
check(
    "set(checks) != EXPECTED_VISUAL_CHECKS" in GATE
    and "any(checks[name] is not True" in GATE,
    "visual check set is exact and all observations must be true",
)
check(
    '"production_activation": False' in GATE
    and '"release_gate_satisfied": False' in GATE,
    "gate result cannot activate production or self-satisfy release",
)
check(
    'sort_keys=True' in GATE
    and 'separators=(",", ":")' in GATE
    and '"kaliv-body-android-physical-gate:"' in GATE
    and "+ expected_sha" in GATE
    and "hashlib.sha256(canonical).hexdigest()" in GATE,
    "PASS result issues an exact-head-bound content-addressed release evidence ref",
)
for forbidden in (
    '"production_activation": True',
    '"release_gate_satisfied": True',
    "KALIV_BODY_RIG_TOKEN",
    "bodyrig_rig_token",
):
    check(forbidden not in GATE, f"gate never embeds or grants {forbidden}")

print(f"\nKaliv Body Android independent live-body gate contract: {passed} passed, {failed} failed")
raise SystemExit(0 if failed == 0 else 1)
