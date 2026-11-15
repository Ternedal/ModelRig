#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

SPEC = importlib.util.spec_from_file_location(
    "kaliv_release_manifest_assembler",
    SCRIPTS / "kaliv_release_manifest_assembler.py",
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

M = "1" * 40
B = "2" * 40
V = "3" * 40
VOICE = "4" * 40
D = "a" * 64


def _refs() -> dict[str, str]:
    return {
        "software_exact_green":
            f"kaliv-software-exact-green:{M}:{B}:{V}:{VOICE}:{D}",
        "consciousness_live_lifecycle":
            f"consciousness-live-lifecycle:{M}:{D}",
        "visionrig_physical_perception":
            f"visionrig-physical-perception:{V}:{D}",
        "voicerig_physical_acceptance":
            f"voicerig-physical-acceptance:{VOICE}:{D}",
        "bodyrig_photoreal_likeness":
            f"bodyrig-photoreal-likeness:{B}:{D}",
        "bodyrig_digital_twin_m6":
            f"bodyrig-digital-twin-m6:{B}:{D}",
        "bodyrig_android_live_body":
            f"kaliv-body-android-physical-gate:{M}:{D}",
        "end_to_end_latency":
            f"kaliv-end-to-end-latency:{M}:{D}",
        "recovery_soak":
            f"kaliv-recovery-soak:{M}:{D}",
        "repository_authority":
            f"kaliv-repository-authority:{M}:{B}:{V}:{VOICE}:{D}",
    }


def _assemble(refs: dict[str, str] | None = None, scope: str = "embodied"):
    return module.assemble(
        release_id="kaliv-rc-test",
        release_scope=scope,
        modelrig_sha=M,
        bodyrig_sha=B,
        visionrig_sha=V,
        voicerig_sha=VOICE,
        evidence_refs=_refs() if refs is None else refs,
    )


def _reject(refs: dict[str, str], fragment: str) -> None:
    try:
        _assemble(refs)
    except module.ReleaseManifestAssemblyError as exc:
        assert fragment in str(exc), (fragment, str(exc))
    else:
        raise AssertionError(fragment)


def run_contract() -> None:
    manifest, verdict = _assemble()
    assert manifest["schema"] == "kaliv-system-release-manifest/v2"
    assert manifest["release_scope"] == "embodied"
    assert verdict["release_scope"] == "embodied"
    assert verdict["deferred_gates"] == []
    assert manifest["production_activation"] is False
    assert verdict["state"] == "QUALIFIED"
    assert verdict["release_ready"] is True
    assert verdict["production_activation"] is False
    assert set(manifest["gates"]) == set(module.release_gate.REQUIRED_GATES)
    assert all(
        entry == {"status": "PASS", "evidence_refs": [manifest["gates"][gate]["evidence_refs"][0]]}
        for gate, entry in manifest["gates"].items()
    )

    missing = _refs()
    del missing["recovery_soak"]
    _reject(missing, "missing recovery_soak")

    extra = _refs()
    extra["not_a_gate"] = "evidence:not-a-gate"
    _reject(extra, "unknown not_a_gate")

    mutable = _refs()
    mutable["bodyrig_photoreal_likeness"] = "operator-says-photoreal-passed"
    _reject(mutable, "rejected by the final release gate")

    wrong_body = _refs()
    wrong_body["bodyrig_digital_twin_m6"] = (
        "bodyrig-digital-twin-m6:" + "f" * 40 + ":" + D
    )
    _reject(wrong_body, "different BodyRig Git SHA")

    wrong_cross_repo = _refs()
    wrong_cross_repo["repository_authority"] = (
        f"kaliv-repository-authority:{M}:{B}:{V}:" + "f" * 40 + f":{D}"
    )
    _reject(wrong_cross_repo, "repository SHAs do not match")

    # ADR-SYS-001: a V1 manifest is assembled from the seven V1 refs only. The
    # body gates are written PENDING and reported as deferred, never claimed.
    body = set(module.release_gate.BODY_GATES)
    v1_refs = {gate: ref for gate, ref in _refs().items() if gate not in body}
    v1_manifest, v1_verdict = _assemble(v1_refs, scope="v1")
    assert v1_manifest["release_scope"] == "v1"
    assert v1_verdict["state"] == "QUALIFIED" and v1_verdict["release_ready"] is True
    assert set(v1_verdict["deferred_gates"]) == body
    for gate in body:
        assert v1_manifest["gates"][gate] == {"status": "PENDING", "evidence_refs": []}

    # V1 refs do not make an Embodied release, and Embodied refs are not
    # accepted under the V1 scope: a body claim must go through its own scope.
    try:
        _assemble(v1_refs, scope="embodied")
    except module.ReleaseManifestAssemblyError as exc:
        assert "missing bodyrig_android_live_body" in str(exc), str(exc)
    else:
        raise AssertionError("embodied manifest assembled without body evidence")
    try:
        _assemble(_refs(), scope="v1")
    except module.ReleaseManifestAssemblyError as exc:
        assert "unknown bodyrig_android_live_body" in str(exc), str(exc)
    else:
        raise AssertionError("v1 manifest accepted body evidence")
    v1_missing = dict(v1_refs)
    del v1_missing["recovery_soak"]
    try:
        _assemble(v1_missing, scope="v1")
    except module.ReleaseManifestAssemblyError as exc:
        assert "missing recovery_soak" in str(exc), str(exc)
    else:
        raise AssertionError("v1 manifest assembled without recovery_soak")
    try:
        _assemble(scope="core")
    except module.ReleaseManifestAssemblyError as exc:
        assert "release scope must be one of" in str(exc), str(exc)
    else:
        raise AssertionError("unknown release scope accepted")

    try:
        module.assemble(
            release_id="kaliv-rc-test",
            release_scope="embodied",
            modelrig_sha="main",
            bodyrig_sha=B,
            visionrig_sha=V,
            voicerig_sha=VOICE,
            evidence_refs=_refs(),
        )
    except module.ReleaseManifestAssemblyError as exc:
        assert "lowercase 40-hex" in str(exc)
    else:
        raise AssertionError("mutable ModelRig revision unexpectedly accepted")


if __name__ == "__main__":
    run_contract()
    print("Kaliv release manifest assembler contract: PASS")
