#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "kaliv_bodyrig_digital_twin_m6_qualifier",
    ROOT / "scripts" / "kaliv_bodyrig_digital_twin_m6_qualifier.py",
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

REV = "a" * 40


def _authority() -> dict:
    value = {
        "format": "bodyrig-digital-twin-release",
        "version": 1,
        "policy_revision": "bodyrig-digital-twin-release-v1",
        "release_id": "",
        "person_id": "person-0123456789abcdef0123456789abcdef",
        "person_revision": "person-r0001",
        "assembly_fingerprint": "1" * 64,
        "body_revision": "body-r0001",
        "body_id": "body-0123456789abcdef0123456789abcdef",
        "body_package_sha256": "2" * 64,
        "bodyprint_sha256": "3" * 64,
        "bodyrig_revision": REV,
        "composition_authority_id": "dtcomp-0123456789abcdef0123456789abcdef",
        "composition_authority_sha256": "4" * 64,
        "composition_authority_content_sha256": "5" * 64,
        "gate_a_sha256": "6" * 64,
        "body_physical_release_sha256": "7" * 64,
        "windows_platform_input_sha256": "8" * 64,
        "windows_realization_sha256": "9" * 64,
        "windows_renderer_attestation_sha256": "a" * 64,
        "quest_platform_input_sha256": "b" * 64,
        "quest_realization_sha256": "c" * 64,
        "quest_renderer_attestation_sha256": "d" * 64,
        "finalized_utc": "2026-09-29T12:00:00Z",
        "state": "released",
        "digital_twin_ready": True,
        "production_activation": True,
    }
    evidence = {key: value[key] for key in module.RELEASE_ID_FIELDS}
    value["release_id"] = (
        "dtrelease-"
        + hashlib.sha256(module._canonical(evidence)).hexdigest()[:32]
    )
    return value


def _reject(value: dict, fragment: str, expected_sha: str = REV) -> None:
    try:
        module.qualify(value, expected_bodyrig_sha=expected_sha)
    except module.BodyRigM6QualificationError as exc:
        assert fragment in str(exc), (fragment, str(exc))
    else:
        raise AssertionError(f"authority unexpectedly accepted; wanted {fragment!r}")


def run_contract() -> None:
    valid = _authority()
    verdict = module.qualify(valid, expected_bodyrig_sha=REV)
    assert verdict["state"] == "QUALIFIED"
    assert verdict["bodyrig_digital_twin_m6_gate_satisfied"] is True
    assert verdict["release_gate_satisfied"] is False
    assert verdict["production_activation"] is False
    assert verdict["release_evidence_ref"].startswith(
        f"bodyrig-digital-twin-m6:{REV}:"
    )

    _reject(valid, "different BodyRig Git SHA", expected_sha="b" * 40)

    forged = copy.deepcopy(valid)
    forged["release_id"] = "dtrelease-" + "f" * 32
    _reject(forged, "release_id does not match")

    inactive = copy.deepcopy(valid)
    inactive["production_activation"] = False
    inactive["release_id"] = module._release_id(inactive)
    _reject(inactive, "production_activation must be true")

    not_ready = copy.deepcopy(valid)
    not_ready["digital_twin_ready"] = False
    not_ready["release_id"] = module._release_id(not_ready)
    _reject(not_ready, "digital_twin_ready must be true")

    extra = copy.deepcopy(valid)
    extra["unexpected"] = True
    _reject(extra, "fields are not canonical")

    bad_hash = copy.deepcopy(valid)
    bad_hash["windows_realization_sha256"] = "nope"
    _reject(bad_hash, "must be a lowercase SHA-256")

    for field in (
        "person_id",
        "person_revision",
        "body_revision",
        "body_id",
        "composition_authority_id",
    ):
        blank = copy.deepcopy(valid)
        blank[field] = "   "
        blank["release_id"] = module._release_id(blank)
        _reject(blank, f"{field} is invalid")


if __name__ == "__main__":
    run_contract()
    print("Kaliv BodyRig M6 qualifier contract: PASS")
