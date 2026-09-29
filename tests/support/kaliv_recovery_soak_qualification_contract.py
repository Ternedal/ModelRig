from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "kaliv_recovery_soak_qualification_contract",
    ROOT / "scripts" / "kaliv_recovery_soak_qualification.py",
)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


def _observations() -> dict:
    return {
        "schema": gate.OBS_SCHEMA,
        "candidate_sha": "a" * 40,
        "production_activation": False,
        "policy": {
            "required_duration_seconds": 7200,
            "max_sample_gap_seconds": 3600,
        },
        "stage_b_evidence_ref": "validation/stage-b-physical-final-latest.json#sha256=abc",
        "samples": [
            {
                "observed_at": "2026-09-29T10:00:00+00:00",
                "backend_healthy": True,
                "worker_healthy": True,
                "supervisor_looping": True,
                "state_error_absent": True,
            },
            {
                "observed_at": "2026-09-29T11:00:00+00:00",
                "backend_healthy": True,
                "worker_healthy": True,
                "supervisor_looping": True,
                "state_error_absent": True,
            },
            {
                "observed_at": "2026-09-29T12:00:00+00:00",
                "backend_healthy": True,
                "worker_healthy": True,
                "supervisor_looping": True,
                "state_error_absent": True,
            },
        ],
        "recovery_events": [
            {
                "kind": kind,
                "observed_at": f"2026-09-29T1{index}:05:00+00:00",
                "passed": True,
                "evidence_ref": f"validation/evidence/{kind}.json#sha256={index}",
            }
            for index, kind in enumerate(gate._REQUIRED_RECOVERY_KINDS)
        ],
    }


def _reject(doc: dict, fragment: str) -> None:
    try:
        gate.qualify(doc, observations_sha256="f" * 64)
    except gate.RecoverySoakError as exc:
        assert fragment in str(exc), (fragment, str(exc))
    else:
        raise AssertionError(f"observations unexpectedly accepted; wanted {fragment!r}")


def run_contract() -> None:
    valid = _observations()
    q = gate.qualify(valid, observations_sha256="f" * 64)
    assert q.qualified is True
    assert q.production_activation is False
    assert q.candidate_sha == "a" * 40
    assert q.observed_duration_seconds == 7200
    assert q.required_duration_seconds == 7200
    assert q.sample_count == 3
    assert q.max_observed_gap_seconds == 3600
    assert tuple(q.required_recovery_kinds) == gate._REQUIRED_RECOVERY_KINDS
    assert q.release_evidence_ref.startswith(
        "kaliv-recovery-soak:" + "a" * 40 + ":"
    )
    assert len(q.release_evidence_ref.rsplit(":", 1)[1]) == 64

    short = copy.deepcopy(valid)
    short["policy"]["required_duration_seconds"] = 7201
    _reject(short, "below declared policy")

    gap = copy.deepcopy(valid)
    gap["policy"]["max_sample_gap_seconds"] = 3599
    _reject(gap, "exceeds declared policy")

    unhealthy = copy.deepcopy(valid)
    unhealthy["samples"][1]["worker_healthy"] = False
    _reject(unhealthy, "worker_healthy must be true")

    state_error = copy.deepcopy(valid)
    state_error["samples"][1]["state_error_absent"] = False
    _reject(state_error, "state_error_absent must be true")

    non_monotonic = copy.deepcopy(valid)
    non_monotonic["samples"][1]["observed_at"] = valid["samples"][0]["observed_at"]
    _reject(non_monotonic, "strictly increasing")

    missing = copy.deepcopy(valid)
    missing["recovery_events"] = missing["recovery_events"][:-1]
    _reject(missing, "missing required recovery events")

    duplicate = copy.deepcopy(valid)
    duplicate["recovery_events"][-1]["kind"] = "reboot"
    _reject(duplicate, "duplicate recovery event kind")

    failed = copy.deepcopy(valid)
    failed["recovery_events"][0]["passed"] = False
    _reject(failed, "did not pass")

    extra_kind = copy.deepcopy(valid)
    extra_kind["recovery_events"][0]["kind"] = "magic_recovery"
    _reject(extra_kind, "kind is not allowed")

    bad_sha = copy.deepcopy(valid)
    bad_sha["candidate_sha"] = "main"
    _reject(bad_sha, "lowercase 40-hex")

    activation = copy.deepcopy(valid)
    activation["production_activation"] = True
    _reject(activation, "cannot activate production")

    no_stage_b = copy.deepcopy(valid)
    no_stage_b["stage_b_evidence_ref"] = ""
    _reject(no_stage_b, "bounded nonblank reference")


if __name__ == "__main__":
    run_contract()
    print("Kaliv recovery soak qualification contract: PASS")
