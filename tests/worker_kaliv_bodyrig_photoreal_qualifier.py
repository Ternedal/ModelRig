#!/usr/bin/env python3
from __future__ import annotations
import copy, hashlib, importlib.util, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "kaliv_bodyrig_photoreal_qualifier",
    ROOT / "scripts" / "kaliv_bodyrig_photoreal_qualifier.py",
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)
REV = "a" * 40

def _authority() -> dict:
    v = {
        "format": "bodyrig-digital-twin-photoreal-release",
        "version": 1,
        "policy_revision": "bodyrig-digital-twin-photoreal-release-v1",
        "release_id": "",
        "person_id": "person-" + "1" * 32,
        "person_revision": "person-r0001",
        "assembly_fingerprint": "1" * 64,
        "body_revision": "body-r0001",
        "body_id": "body-" + "2" * 32,
        "body_package_sha256": "3" * 64,
        "bodyrig_revision": REV,
        "canonical_m6_release_id": "dtrelease-" + "4" * 32,
        "canonical_m6_release_file_sha256": "5" * 64,
        "canonical_m6_release_content_sha256": "6" * 64,
        "photoreal_m5_link_id": "dtphotom5-" + "7" * 32,
        "photoreal_m5_link_file_sha256": "8" * 64,
        "photoreal_m5_link_content_sha256": "9" * 64,
        "m4_photoreal_link_id": "dtphoto-" + "a" * 32,
        "windows_realization_sha256": "b" * 64,
        "quest_realization_sha256": "c" * 64,
        "visual_authority": "photoreal-v2-p3",
        "state": "released",
        "canonical_digital_twin_ready": True,
        "photoreal_digital_twin_ready": True,
        "finalized_utc": "2026-09-29T12:00:00Z",
        "production_activation": True,
    }
    v["release_id"] = module._release_id(v)
    return v

def _reject(v: dict, fragment: str, sha: str = REV) -> None:
    try:
        module.qualify(v, expected_bodyrig_sha=sha)
    except module.BodyRigPhotorealQualificationError as exc:
        assert fragment in str(exc), (fragment, str(exc))
    else:
        raise AssertionError(fragment)

def run_contract() -> None:
    v = _authority()
    out = module.qualify(v, expected_bodyrig_sha=REV)
    assert out["bodyrig_photoreal_likeness_gate_satisfied"] is True
    assert out["production_activation"] is False
    assert out["release_gate_satisfied"] is False
    assert out["release_evidence_ref"].startswith(f"bodyrig-photoreal-likeness:{REV}:")
    _reject(v, "different BodyRig Git SHA", "b" * 40)
    x = copy.deepcopy(v); x["photoreal_digital_twin_ready"] = False; x["release_id"] = module._release_id(x)
    _reject(x, "photoreal_digital_twin_ready must be true")
    x = copy.deepcopy(v); x["visual_authority"] = "machine-only"; x["release_id"] = module._release_id(x)
    _reject(x, "visual authority is not canonical")
    x = copy.deepcopy(v); x["release_id"] = "dtphotorel-" + "f" * 32
    _reject(x, "release_id does not match exact evidence")
    x = copy.deepcopy(v); x["production_activation"] = False; x["release_id"] = module._release_id(x)
    _reject(x, "production_activation must be true")
    for field in (
        "person_id",
        "person_revision",
        "body_revision",
        "body_id",
        "canonical_m6_release_id",
        "photoreal_m5_link_id",
        "m4_photoreal_link_id",
    ):
        x = copy.deepcopy(v)
        x[field] = "   "
        x["release_id"] = module._release_id(x)
        _reject(x, f"{field} is invalid")

if __name__ == "__main__":
    run_contract()
    print("Kaliv BodyRig Photoreal qualifier contract: PASS")
