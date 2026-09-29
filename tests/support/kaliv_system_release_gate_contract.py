from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "kaliv_system_release_gate_contract",
    ROOT / "scripts" / "kaliv_system_release_gate.py",
)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


def _manifest() -> dict:
    return {
        "schema": gate.SCHEMA,
        "release_id": "kaliv-rc-contract",
        "repositories": [
            {"repository": repo, "git_sha": ch * 40}
            for repo, ch in (
                ("Ternedal/ModelRig", "1"),
                ("Ternedal/BodyRig", "2"),
                ("Ternedal/VisionRig", "3"),
                ("Ternedal/VoiceRig", "4"),
            )
        ],
        "gates": {
            name: {
                "status": "PASS",
                "evidence_refs": [
                    (
                        (
                            "kaliv-software-exact-green:"
                            + "1" * 40 + ":"
                            + "2" * 40 + ":"
                            + "3" * 40 + ":"
                            + "4" * 40 + ":"
                            + "7" * 64
                            if name == "software_exact_green"
                            else (
                                "kaliv-body-android-physical-gate:" + "1" * 40 + ":" + "a" * 64
                                if name == "bodyrig_android_live_body"
                                else (
                            "consciousness-live-lifecycle:"
                            + "1" * 40
                            + ":"
                            + "c" * 64
                            if name == "consciousness_live_lifecycle"
                            else (
                                "visionrig-physical-perception:"
                                + "3" * 40
                                + ":"
                                + "e" * 64
                                if name == "visionrig_physical_perception"
                                else (
                                    "kaliv-end-to-end-latency:"
                                    + "1" * 40
                                    + ":"
                                    + "9" * 64
                                    if name == "end_to_end_latency"
                                    else f"evidence:{name}:1"
                                )
                            )
                        )
                    )
                )
                ],
            }
            for name in gate.REQUIRED_GATES
        },
        "production_activation": False,
    }


def _must_reject(manifest: dict, fragment: str) -> None:
    try:
        gate.evaluate_manifest(manifest)
    except gate.SystemReleaseManifestError as exc:
        assert fragment in str(exc), (fragment, str(exc))
    else:
        raise AssertionError(f"manifest unexpectedly accepted; wanted {fragment!r}")


def _test_modelrig_clean_merge_equivalence_helper() -> None:
    original_run = gate.subprocess.run
    original_git = gate._git

    class _Result:
        stdout = ""

    try:
        gate.subprocess.run = lambda *args, **kwargs: _Result()
        gate._git = lambda *args: "tree-" + "a" * 40
        assert gate._modelrig_evidence_matches_pin("a" * 40, "b" * 40) is True

        def different_tree(*args):
            joined = " ".join(args)
            return "tree-evidence" if ("a" * 40) in joined else "tree-pinned"

        gate._git = different_tree
        assert gate._modelrig_evidence_matches_pin("a" * 40, "b" * 40) is False

        def non_ancestor(*args, **kwargs):
            raise gate.subprocess.CalledProcessError(1, args[0])

        gate.subprocess.run = non_ancestor
        gate._git = original_git
        assert gate._modelrig_evidence_matches_pin("a" * 40, "b" * 40) is False
    finally:
        gate.subprocess.run = original_run
        gate._git = original_git


def run_contract() -> None:
    _test_modelrig_clean_merge_equivalence_helper()
    valid = _manifest()
    verdict = gate.evaluate_manifest(valid)
    assert verdict.state == "QUALIFIED"
    assert verdict.release_ready is True
    assert verdict.production_activation is False
    assert set(verdict.pinned_repositories) >= set(gate.REQUIRED_REPOSITORIES)
    assert verdict.pending_gates == ()
    assert verdict.failed_gates == ()

    pending = copy.deepcopy(valid)
    pending["gates"]["bodyrig_photoreal_likeness"]["status"] = "PENDING"
    pending["gates"]["bodyrig_photoreal_likeness"]["evidence_refs"] = []
    verdict = gate.evaluate_manifest(pending)
    assert verdict.state == "BLOCKED"
    assert verdict.release_ready is False
    assert verdict.pending_gates == ("bodyrig_photoreal_likeness",)
    assert verdict.production_activation is False

    software_mutable_ref = copy.deepcopy(valid)
    software_mutable_ref["gates"]["software_exact_green"]["evidence_refs"] = [
        "operator-says-all-repos-green"
    ]
    _must_reject(
        software_mutable_ref,
        "requires canonical kaliv-software-exact-green evidence",
    )

    software_wrong_body = copy.deepcopy(valid)
    software_wrong_body["gates"]["software_exact_green"]["evidence_refs"] = [
        "kaliv-software-exact-green:"
        + "1" * 40 + ":"
        + "f" * 40 + ":"
        + "3" * 40 + ":"
        + "4" * 40 + ":"
        + "7" * 64
    ]
    _must_reject(
        software_wrong_body,
        "repository SHAs do not match the pinned release revisions",
    )

    software_multiple_refs = copy.deepcopy(valid)
    software_multiple_refs["gates"]["software_exact_green"]["evidence_refs"] = [
        "kaliv-software-exact-green:"
        + "1" * 40 + ":"
        + "2" * 40 + ":"
        + "3" * 40 + ":"
        + "4" * 40 + ":"
        + "7" * 64,
        "kaliv-software-exact-green:"
        + "1" * 40 + ":"
        + "2" * 40 + ":"
        + "3" * 40 + ":"
        + "4" * 40 + ":"
        + "8" * 64,
    ]
    _must_reject(
        software_multiple_refs,
        "requires exactly one cross-repository qualification evidence ref",
    )

    consciousness_mutable_ref = copy.deepcopy(valid)
    consciousness_mutable_ref["gates"]["consciousness_live_lifecycle"]["evidence_refs"] = [
        "operator-says-consciousness-is-good"
    ]
    _must_reject(
        consciousness_mutable_ref,
        "requires exact-head-bound consciousness-live-lifecycle evidence",
    )

    consciousness_wrong_head = copy.deepcopy(valid)
    consciousness_wrong_head["gates"]["consciousness_live_lifecycle"]["evidence_refs"] = [
        "consciousness-live-lifecycle:" + "f" * 40 + ":" + "d" * 64
    ]
    _must_reject(
        consciousness_wrong_head,
        "not exact-tree-equivalent to the pinned ModelRig revision",
    )

    consciousness_multiple_refs = copy.deepcopy(valid)
    consciousness_multiple_refs["gates"]["consciousness_live_lifecycle"]["evidence_refs"] = [
        "consciousness-live-lifecycle:" + "1" * 40 + ":" + "c" * 64,
        "consciousness-live-lifecycle:" + "1" * 40 + ":" + "d" * 64,
    ]
    _must_reject(
        consciousness_multiple_refs,
        "requires exactly one lifecycle qualification evidence ref",
    )

    vision_mutable_ref = copy.deepcopy(valid)
    vision_mutable_ref["gates"]["visionrig_physical_perception"]["evidence_refs"] = [
        "operator-says-vision-is-good"
    ]
    _must_reject(
        vision_mutable_ref,
        "requires exact-head-bound visionrig-physical-perception evidence",
    )

    vision_wrong_head = copy.deepcopy(valid)
    vision_wrong_head["gates"]["visionrig_physical_perception"]["evidence_refs"] = [
        "visionrig-physical-perception:" + "f" * 40 + ":" + "e" * 64
    ]
    _must_reject(
        vision_wrong_head,
        "bound to a different VisionRig Git SHA",
    )

    vision_multiple_refs = copy.deepcopy(valid)
    vision_multiple_refs["gates"]["visionrig_physical_perception"]["evidence_refs"] = [
        "visionrig-physical-perception:" + "3" * 40 + ":" + "e" * 64,
        "visionrig-physical-perception:" + "3" * 40 + ":" + "f" * 64,
    ]
    _must_reject(
        vision_multiple_refs,
        "requires exactly one physical qualification evidence ref",
    )

    android_pending = copy.deepcopy(valid)
    android_pending["gates"]["bodyrig_android_live_body"]["status"] = "PENDING"
    android_pending["gates"]["bodyrig_android_live_body"]["evidence_refs"] = []
    verdict = gate.evaluate_manifest(android_pending)
    assert verdict.state == "BLOCKED"
    assert verdict.release_ready is False
    assert verdict.pending_gates == ("bodyrig_android_live_body",)
    assert verdict.production_activation is False

    android_mutable_ref = copy.deepcopy(valid)
    android_mutable_ref["gates"]["bodyrig_android_live_body"]["evidence_refs"] = [
        "operator-says-android-is-good"
    ]
    _must_reject(
        android_mutable_ref,
        "requires exact-head-bound kaliv-body-android-physical-gate evidence refs",
    )

    android_wrong_head = copy.deepcopy(valid)
    android_wrong_head["gates"]["bodyrig_android_live_body"]["evidence_refs"] = [
        "kaliv-body-android-physical-gate:" + "f" * 40 + ":" + "b" * 64
    ]
    _must_reject(
        android_wrong_head,
        "not exact-tree-equivalent to the pinned ModelRig revision",
    )

    # A normal GitHub merge commit gets a new commit SHA even when it
    # preserves the exact qualified tree. The release gate may translate that
    # identity only through the dedicated ancestry+tree-equivalence helper.
    original_matcher = gate._modelrig_evidence_matches_pin
    try:
        gate._modelrig_evidence_matches_pin = (
            lambda evidence_sha, pinned_sha:
            evidence_sha == pinned_sha
            or (evidence_sha == "a" * 40 and pinned_sha == "1" * 40)
        )
        merge_equivalent = copy.deepcopy(valid)
        merge_equivalent["gates"]["bodyrig_android_live_body"]["evidence_refs"] = [
            "kaliv-body-android-physical-gate:" + "a" * 40 + ":" + "b" * 64
        ]
        verdict = gate.evaluate_manifest(merge_equivalent)
        assert verdict.release_ready is True
    finally:
        gate._modelrig_evidence_matches_pin = original_matcher

    android_multiple_refs = copy.deepcopy(valid)
    android_multiple_refs["gates"]["bodyrig_android_live_body"]["evidence_refs"] = [
        "kaliv-body-android-physical-gate:" + "1" * 40 + ":" + "a" * 64,
        "kaliv-body-android-physical-gate:" + "1" * 40 + ":" + "b" * 64,
    ]
    _must_reject(
        android_multiple_refs,
        "requires exactly one independent physical gate evidence ref",
    )

    latency_mutable_ref = copy.deepcopy(valid)
    latency_mutable_ref["gates"]["end_to_end_latency"]["evidence_refs"] = [
        "operator-says-latency-is-fine"
    ]
    _must_reject(
        latency_mutable_ref,
        "requires exact-head-bound kaliv-end-to-end-latency evidence",
    )

    latency_wrong_head = copy.deepcopy(valid)
    latency_wrong_head["gates"]["end_to_end_latency"]["evidence_refs"] = [
        "kaliv-end-to-end-latency:" + "f" * 40 + ":" + "9" * 64
    ]
    _must_reject(
        latency_wrong_head,
        "not exact-tree-equivalent to the pinned ModelRig revision",
    )

    latency_multiple_refs = copy.deepcopy(valid)
    latency_multiple_refs["gates"]["end_to_end_latency"]["evidence_refs"] = [
        "kaliv-end-to-end-latency:" + "1" * 40 + ":" + "9" * 64,
        "kaliv-end-to-end-latency:" + "1" * 40 + ":" + "8" * 64,
    ]
    _must_reject(
        latency_multiple_refs,
        "requires exactly one measurement qualification evidence ref",
    )

    failed = copy.deepcopy(valid)
    failed["gates"]["recovery_soak"]["status"] = "FAIL"
    verdict = gate.evaluate_manifest(failed)
    assert verdict.state == "BLOCKED"
    assert verdict.failed_gates == ("recovery_soak",)

    no_evidence = copy.deepcopy(valid)
    no_evidence["gates"]["visionrig_physical_perception"]["evidence_refs"] = []
    _must_reject(no_evidence, "cannot PASS without explicit evidence")

    mutable_ref = copy.deepcopy(valid)
    mutable_ref["repositories"][0]["git_sha"] = "main"
    _must_reject(mutable_ref, "lowercase 40-hex Git SHA")

    missing_repo = copy.deepcopy(valid)
    missing_repo["repositories"] = [
        item
        for item in missing_repo["repositories"]
        if item["repository"] != "Ternedal/VoiceRig"
    ]
    _must_reject(missing_repo, "missing required repository pins")

    duplicate_repo = copy.deepcopy(valid)
    duplicate_repo["repositories"].append(copy.deepcopy(duplicate_repo["repositories"][0]))
    _must_reject(duplicate_repo, "duplicate repository pin")

    missing_gate = copy.deepcopy(valid)
    del missing_gate["gates"]["end_to_end_latency"]
    _must_reject(missing_gate, "missing end_to_end_latency")

    invented_gate = copy.deepcopy(valid)
    invented_gate["gates"]["ci_says_everything_is_fine"] = {
        "status": "PASS",
        "evidence_refs": ["evidence:fake"],
    }
    _must_reject(invented_gate, "unknown ci_says_everything_is_fine")

    activation = copy.deepcopy(valid)
    activation["production_activation"] = True
    _must_reject(activation, "cannot activate production")

    # A software-only manifest must remain blocked even if every repository is
    # exact-pinned. CI is deliberately only one of nine independent gates.
    software_only = copy.deepcopy(valid)
    for name in gate.REQUIRED_GATES:
        if name == "software_exact_green":
            continue
        software_only["gates"][name] = {"status": "PENDING", "evidence_refs": []}
    verdict = gate.evaluate_manifest(software_only)
    assert verdict.release_ready is False
    assert verdict.state == "BLOCKED"
    assert set(verdict.pending_gates) == set(gate.REQUIRED_GATES) - {
        "software_exact_green"
    }


if __name__ == "__main__":
    run_contract()
    print("Kaliv system release gate contract: PASS")
