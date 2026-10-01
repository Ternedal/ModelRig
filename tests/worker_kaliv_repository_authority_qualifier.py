#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "kaliv_repository_authority_qualifier",
    ROOT / "scripts" / "kaliv_repository_authority_qualifier.py",
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def _evidence() -> dict:
    return {
        "schema": module.SCHEMA,
        "repositories": [
            {
                "repository": repo,
                "git_sha": ch * 40,
                "live_repository_authority_passed": True,
                "evidence_ref": f"repository-authority:{repo}:{ch * 8}",
            }
            for repo, ch in (
                ("Ternedal/ModelRig", "1"),
                ("Ternedal/BodyRig", "2"),
                ("Ternedal/VisionRig", "3"),
                ("Ternedal/VoiceRig", "4"),
            )
        ],
        "production_activation": False,
    }


def _reject(doc: dict, fragment: str) -> None:
    try:
        module.qualify(doc)
    except module.RepositoryAuthorityQualificationError as exc:
        assert fragment in str(exc), (fragment, str(exc))
    else:
        raise AssertionError(f"evidence unexpectedly accepted; wanted {fragment!r}")


def run_contract() -> None:
    valid = _evidence()
    verdict = module.qualify(valid)
    assert verdict["state"] == "QUALIFIED"
    assert verdict["repository_authority_gate_satisfied"] is True
    assert verdict["release_gate_satisfied"] is False
    assert verdict["production_activation"] is False
    assert verdict["release_evidence_ref"].startswith(
        "kaliv-repository-authority:"
        + "1" * 40 + ":"
        + "2" * 40 + ":"
        + "3" * 40 + ":"
        + "4" * 40 + ":"
    )

    failed = copy.deepcopy(valid)
    failed["repositories"][0]["live_repository_authority_passed"] = False
    _reject(failed, "live_repository_authority_passed must be true")

    mutable = copy.deepcopy(valid)
    mutable["repositories"][1]["git_sha"] = "main"
    _reject(mutable, "lowercase 40-hex")

    duplicate = copy.deepcopy(valid)
    duplicate["repositories"][3]["repository"] = "Ternedal/BodyRig"
    _reject(duplicate, "duplicate repository authority evidence")

    duplicate_ref = copy.deepcopy(valid)
    duplicate_ref["repositories"][3]["evidence_ref"] = (
        duplicate_ref["repositories"][2]["evidence_ref"]
    )
    _reject(duplicate_ref, "evidence references must be distinct")

    activation = copy.deepcopy(valid)
    activation["production_activation"] = True
    _reject(activation, "cannot activate production")


if __name__ == "__main__":
    run_contract()
    print("Kaliv repository authority qualifier contract: PASS")
