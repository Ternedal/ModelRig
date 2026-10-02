#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "kaliv_voicerig_physical_qualifier",
    ROOT / "scripts" / "kaliv_voicerig_physical_qualifier.py",
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

REV = "a" * 40


def _artifact(seed: str, *, validated: bool = True) -> dict:
    value = {
        "path": f"C:/validation/{seed}.bin",
        "exists": True,
        "bytes": 123,
        "sha256": seed * 64,
    }
    if validated:
        value["validated"] = True
    return value


def _acceptance() -> dict:
    return {
        "ok": True,
        "stage": "release-ready",
        "source": {
            "available": True,
            "revision": REV,
            "dirty": False,
            "branch": "main",
            "root": "C:/VoiceRig",
        },
        "quality": {"pass": True, "note": "Danish voice and speaker likeness accepted."},
        "speaker_similarity": {"available": True, "cosine": 0.81},
        "gpu": {
            "after_build": {"peak_reserved_gb": 8.5},
            "after_synthesis": {"peak_reserved_gb": 9.0},
        },
        "modelrig": {
            "reachable": True,
            "authenticated": True,
            "tts": True,
            "provider": "voicerig",
            "package_matches": True,
        },
        "fallback": {
            "before_provider": "voicerig",
            "before_package": "voice.mrvoice",
            "provider": "piper",
            "piper_synthesis": {"provider": "piper", "riff": True},
            "restored_provider": "voicerig",
            "restored_package": "voice.mrvoice",
        },
        "artifacts": {
            "validation_report": {"path": "C:/validation/report.json", "bytes": 10, "sha256": "1" * 64},
            "fallback_report": {"path": "C:/validation/fallback.json", "bytes": 11, "sha256": "2" * 64},
            "package": _artifact("3"),
            "reference_wav": _artifact("4"),
            "validation_wav": _artifact("5"),
            "piper_fallback_wav": _artifact("6"),
        },
        "blockers": [],
        "warnings": [],
    }


def _reject(value: dict, fragment: str, sha: str = REV) -> None:
    try:
        module.qualify(value, expected_voicerig_sha=sha)
    except module.VoiceRigPhysicalQualificationError as exc:
        assert fragment in str(exc), (fragment, str(exc))
    else:
        raise AssertionError(fragment)


def run_contract() -> None:
    value = _acceptance()
    verdict = module.qualify(value, expected_voicerig_sha=REV)
    assert verdict["voicerig_physical_acceptance_gate_satisfied"] is True
    assert verdict["release_gate_satisfied"] is False
    assert verdict["production_activation"] is False
    assert verdict["release_evidence_ref"].startswith(
        f"voicerig-physical-acceptance:{REV}:"
    )

    _reject(value, "different VoiceRig Git SHA", "b" * 40)
    x = copy.deepcopy(value); x["ok"] = False
    _reject(x, "not a release-ready PASS")
    x = copy.deepcopy(value); x["quality"]["pass"] = False
    _reject(x, "listening quality did not PASS")
    x = copy.deepcopy(value); x["fallback"]["restored_provider"] = "piper"
    _reject(x, "fallback and restore evidence is incomplete")
    x = copy.deepcopy(value); x["artifacts"]["package"]["validated"] = False
    _reject(x, "package must be revalidated")
    x = copy.deepcopy(value); x["blockers"] = ["bad"]
    _reject(x, "contains blockers")
    x = copy.deepcopy(value); x["modelrig"]["authenticated"] = False
    _reject(x, "authenticated ModelRig access")
    x = copy.deepcopy(value); x["modelrig"]["provider"] = "piper"
    _reject(x, "active ModelRig VoiceRig TTS provider")
    x = copy.deepcopy(value); x["modelrig"]["package_matches"] = False
    _reject(x, "accepted voice package")
    x = copy.deepcopy(value); x["gpu"]["after_synthesis"]["peak_reserved_gb"] = 0
    _reject(x, "after_synthesis.peak_reserved_gb must be positive")


if __name__ == "__main__":
    run_contract()
    print("Kaliv VoiceRig physical qualifier contract: PASS")
