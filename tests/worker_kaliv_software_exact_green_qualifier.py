#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "kaliv_software_exact_green_qualifier",
    ROOT / "scripts" / "kaliv_software_exact_green_qualifier.py",
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
                "exact_head_qualified": True,
                "software_green": True,
                "evidence_ref": f"github-actions:{repo}:{ch * 8}",
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
    except module.SoftwareExactGreenError as exc:
        assert fragment in str(exc), (fragment, str(exc))
    else:
        raise AssertionError(f"evidence unexpectedly accepted; wanted {fragment!r}")


def run_contract() -> None:
    valid = _evidence()
    verdict = module.qualify(valid)
    assert verdict["state"] == "QUALIFIED"
    assert verdict["software_exact_green_gate_satisfied"] is True
    assert verdict["release_gate_satisfied"] is False
    assert verdict["production_activation"] is False
    assert verdict["release_evidence_ref"].startswith(
        "kaliv-software-exact-green:"
        + "1" * 40 + ":"
        + "2" * 40 + ":"
        + "3" * 40 + ":"
        + "4" * 40 + ":"
    )

    not_exact = copy.deepcopy(valid)
    not_exact["repositories"][0]["exact_head_qualified"] = False
    _reject(not_exact, "exact_head_qualified must be true")

    not_green = copy.deepcopy(valid)
    not_green["repositories"][1]["software_green"] = False
    _reject(not_green, "software_green must be true")

    mutable_sha = copy.deepcopy(valid)
    mutable_sha["repositories"][2]["git_sha"] = "main"
    _reject(mutable_sha, "lowercase 40-hex")

    duplicate_repo = copy.deepcopy(valid)
    duplicate_repo["repositories"][3]["repository"] = "Ternedal/ModelRig"
    _reject(duplicate_repo, "duplicate repository evidence")

    missing_repo = copy.deepcopy(valid)
    missing_repo["repositories"] = missing_repo["repositories"][:-1]
    _reject(missing_repo, "exactly the four required core repositories")

    unknown_repo = copy.deepcopy(valid)
    unknown_repo["repositories"][3]["repository"] = "Ternedal/UnknownRig"
    _reject(unknown_repo, "not a required core repository")

    duplicate_ref = copy.deepcopy(valid)
    duplicate_ref["repositories"][3]["evidence_ref"] = (
        duplicate_ref["repositories"][2]["evidence_ref"]
    )
    _reject(duplicate_ref, "evidence references must be distinct")

    activation = copy.deepcopy(valid)
    activation["production_activation"] = True
    _reject(activation, "cannot activate production")

    extra = copy.deepcopy(valid)
    extra["repositories"][0]["branch"] = "main"
    _reject(extra, "unknown branch")


if __name__ == "__main__":
    run_contract()
    print("Kaliv software exact-green qualifier contract: PASS")
