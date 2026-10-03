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


STAGE_B_SHA256 = "e" * 64


def _stage_b() -> dict:
    return {
        "schema": gate._STAGE_B_FINAL_SCHEMA,
        "status": "complete",
        "candidate": {
            "git_sha": "a" * 40,
            "working_tree_clean": True,
        },
        "gate": {
            "passed": True,
            "release_freeze_complete": True,
            "updater_chain_complete": True,
            "strict_evidence_complete": True,
            "physical_campaign_complete": True,
            "browser_peer_physical_complete": True,
            "all_physical_evidence_complete": True,
            "production_activation": False,
        },
    }


def _observations() -> dict:
    return {
        "schema": gate.OBS_SCHEMA,
        "candidate_sha": "a" * 40,
        "production_activation": False,
        "policy": {
            "required_duration_seconds": 7200,
            "max_sample_gap_seconds": 3600,
        },
        "stage_b_evidence_ref": (
            "validation/stage-b-physical-final-latest.json#sha256="
            + STAGE_B_SHA256
        ),
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


def _reject(
    doc: dict,
    fragment: str,
    *,
    stage_b: dict | None = None,
    stage_b_sha256: str = STAGE_B_SHA256,
) -> None:
    try:
        gate.qualify(
            doc,
            observations_sha256="f" * 64,
            stage_b_report=_stage_b() if stage_b is None else stage_b,
            stage_b_sha256=stage_b_sha256,
        )
    except gate.RecoverySoakError as exc:
        assert fragment in str(exc), (fragment, str(exc))
    else:
        raise AssertionError(f"observations unexpectedly accepted; wanted {fragment!r}")


def run_contract() -> None:
    valid = _observations()
    q = gate.qualify(
        valid,
        observations_sha256="f" * 64,
        stage_b_report=_stage_b(),
        stage_b_sha256=STAGE_B_SHA256,
    )
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

    bad_stage_b_ref = copy.deepcopy(valid)
    bad_stage_b_ref["stage_b_evidence_ref"] = (
        "validation/stage-b-physical-final-latest.json#sha256=" + "d" * 64
    )
    _reject(bad_stage_b_ref, "digest does not match")

    malformed_stage_b_ref = copy.deepcopy(valid)
    malformed_stage_b_ref["stage_b_evidence_ref"] = "stage-b-report"
    _reject(malformed_stage_b_ref, "must end with #sha256")

    wrong_candidate = _stage_b()
    wrong_candidate["candidate"]["git_sha"] = "b" * 40
    _reject(valid, "candidate Git SHA does not match", stage_b=wrong_candidate)

    dirty_candidate = _stage_b()
    dirty_candidate["candidate"]["working_tree_clean"] = False
    _reject(valid, "checkout is not clean", stage_b=dirty_candidate)

    blocked_stage_b = _stage_b()
    blocked_stage_b["status"] = "blocked"
    _reject(valid, "status must be complete", stage_b=blocked_stage_b)

    incomplete_stage_b = _stage_b()
    incomplete_stage_b["gate"]["strict_evidence_complete"] = False
    _reject(valid, "strict_evidence_complete must be true", stage_b=incomplete_stage_b)

    activating_stage_b = _stage_b()
    activating_stage_b["gate"]["production_activation"] = True
    _reject(
        valid,
        "preserve production_activation=false",
        stage_b=activating_stage_b,
    )


if __name__ == "__main__":
    run_contract()
    print("Kaliv recovery soak qualification contract: PASS")
