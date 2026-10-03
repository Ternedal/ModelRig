from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
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
COMPONENT_ROOT = Path(tempfile.mkdtemp(prefix="kaliv-recovery-stage-b-contract-"))
_ORIGINAL_REVALIDATE = gate._revalidate_stage_b_component
_ORIGINAL_CHECKOUT_CANDIDATE = gate._candidate_identity_from_checkout
_ORIGINAL_FREEZE_REVALIDATE = gate._revalidate_release_freeze
_ORIGINAL_LOADER = gate._load_stage_b_validator
REVALIDATED_COMPONENTS: list[str] = []
FREEZE_REVALIDATIONS: list[str] = []


def _checkout_candidate(**overrides) -> dict:
    value = {
        "version": "2.0.14",
        "git_sha": "a" * 40,
        "code_sha256": "c" * 64,
        "working_tree_clean": True,
        "version_stamps_consistent": True,
    }
    value.update(overrides)
    return value


def _stub_revalidate(
    _repository_root: Path,
    name: str,
    _receipt: dict,
    *,
    candidate_identity: dict,
) -> None:
    assert candidate_identity["git_sha"] == "a" * 40
    assert candidate_identity["version"] == "2.0.14"
    assert candidate_identity["code_sha256"] == "c" * 64
    REVALIDATED_COMPONENTS.append(name)


def _write_component(name: str, schema: str, gate_fields: dict, *, extra: dict | None = None) -> dict:
    value = {
        "schema": schema,
        "candidate": {
            "version": "2.0.14",
            "git_sha": "a" * 40,
            "code_sha256": "c" * 64,
        },
        "gate": {**gate_fields, "production_activation": False},
    }
    if extra:
        value.update(extra)
    relative = Path("validation") / f"{name}.json"
    path = COMPONENT_ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return {
        "path": str(relative),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "schema": schema,
    }


def _artifact(path: str, digit: str) -> dict:
    return {
        "path": path,
        "sha256": digit * 64,
        "bytes": 128,
    }


def _component_evidence() -> dict:
    campaign_passed = list(gate._EXPECTED_STAGE_B_PROOFS[:-1])
    final_passed = list(gate._EXPECTED_STAGE_B_PROOFS)
    lifecycle_artifacts = {
        "reboot": _artifact(
            "validation/appliance-lifecycle-evidence/reboot.log", "1"
        ),
        "supervisor_backend": _artifact(
            "validation/appliance-lifecycle-evidence/supervisor_backend.log", "2"
        ),
        "supervisor_worker": _artifact(
            "validation/appliance-lifecycle-evidence/supervisor_worker.log", "3"
        ),
    }
    return {
        "updater_chain": _write_component(
            "updater-chain",
            gate._STAGE_B_COMPONENTS["updater_chain"][0],
            {"passed": True, "updater_chain_complete": True},
        ),
        "physical_campaign": _write_component(
            "physical-campaign",
            gate._STAGE_B_COMPONENTS["physical_campaign"][0],
            {"passed": True, "physical_campaign_complete": True},
            extra={
                "mode": "verify",
                "summary": {"total": 8, "passed": campaign_passed},
                "evidence": {
                    "lifecycle": {
                        "status": "pass",
                        "summary": {"artifacts": lifecycle_artifacts},
                    }
                },
            },
        ),
        "component_final_gate": _write_component(
            "component-final",
            gate._STAGE_B_COMPONENTS["component_final_gate"][0],
            {"passed": True, "all_physical_evidence_complete": True},
            extra={"summary": {"total": 9, "passed": final_passed}},
        ),
        "strict_stage_b": _write_component(
            "strict-stage-b",
            gate._STAGE_B_COMPONENTS["strict_stage_b"][0],
            {"passed": True, "strict_evidence_complete": True},
            extra={
                "evidence": {
                    "appliance_interruption": _artifact(
                        "validation/appliance-lifecycle-evidence/appliance_interruption.log",
                        "4",
                    )
                }
            },
        ),
    }


def _stage_b() -> dict:
    return {
        "schema": gate._STAGE_B_FINAL_SCHEMA,
        "status": "complete",
        "candidate": {
            "version": "2.0.14",
            "git_sha": "a" * 40,
            "code_sha256": "c" * 64,
            "working_tree_clean": True,
        },
        "evidence": _component_evidence(),
        "steps": [
            {"label": label, "command": ["python", script], "exit_code": 0}
            for label, script in gate._EXPECTED_STAGE_B_STEPS
        ],
        "summary": {
            "total": len(gate._EXPECTED_STAGE_B_PROOFS),
            "passed": list(gate._EXPECTED_STAGE_B_PROOFS),
            "errors": [],
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
                "kind": "reboot",
                "observed_at": "2026-09-29T10:05:00+00:00",
                "passed": True,
                "evidence_ref": (
                    "validation/appliance-lifecycle-evidence/reboot.log#sha256="
                    + "1" * 64
                ),
            },
            {
                "kind": "backend_restart",
                "observed_at": "2026-09-29T10:10:00+00:00",
                "passed": True,
                "evidence_ref": (
                    "validation/appliance-lifecycle-evidence/supervisor_backend.log#sha256="
                    + "2" * 64
                ),
            },
            {
                "kind": "worker_restart",
                "observed_at": "2026-09-29T10:12:00+00:00",
                "passed": True,
                "evidence_ref": (
                    "validation/appliance-lifecycle-evidence/supervisor_worker.log#sha256="
                    + "3" * 64
                ),
            },
            {
                "kind": "interruption_recovery",
                "observed_at": "2026-09-29T10:14:00+00:00",
                "passed": True,
                "evidence_ref": (
                    "validation/appliance-lifecycle-evidence/appliance_interruption.log#sha256="
                    + "4" * 64
                ),
            },
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
            stage_b_report_path=Path("validation/stage-b-physical-final-latest.json"),
            stage_b_repository_root=COMPONENT_ROOT,
        )
    except gate.RecoverySoakError as exc:
        assert fragment in str(exc), (fragment, str(exc))
    else:
        raise AssertionError(f"observations unexpectedly accepted; wanted {fragment!r}")


def run_contract() -> None:
    valid = _observations()
    gate._candidate_identity_from_checkout = lambda _root: _checkout_candidate()
    gate._revalidate_release_freeze = (
        lambda _root, *, candidate_identity: FREEZE_REVALIDATIONS.append(
            candidate_identity["git_sha"]
        )
    )

    gate._revalidate_stage_b_component = _ORIGINAL_REVALIDATE
    _reject(
        valid,
        "Stage-B evidence updater_chain.source must be an object",
        stage_b=_stage_b(),
    )

    REVALIDATED_COMPONENTS.clear()
    gate._revalidate_stage_b_component = _stub_revalidate
    q = gate.qualify(
        valid,
        observations_sha256="f" * 64,
        stage_b_report=_stage_b(),
        stage_b_sha256=STAGE_B_SHA256,
        stage_b_report_path=Path("validation/stage-b-physical-final-latest.json"),
        stage_b_repository_root=COMPONENT_ROOT,
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
    assert REVALIDATED_COMPONENTS == list(gate._STAGE_B_COMPONENTS)
    assert FREEZE_REVALIDATIONS == ["a" * 40]

    gate._revalidate_release_freeze = (
        lambda _root, *, candidate_identity: (_ for _ in ()).throw(
            gate.RecoverySoakError("canonical release freeze did not pass")
        )
    )
    _reject(valid, "canonical release freeze did not pass")
    gate._revalidate_release_freeze = (
        lambda _root, *, candidate_identity: FREEZE_REVALIDATIONS.append(
            candidate_identity["git_sha"]
        )
    )

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

    wrong_event_ref = copy.deepcopy(valid)
    wrong_event_ref["recovery_events"][1]["evidence_ref"] = (
        "validation/appliance-lifecycle-evidence/supervisor_backend.log#sha256="
        + "9" * 64
    )
    _reject(wrong_event_ref, "does not match canonical Stage-B lifecycle evidence")

    outside_window = copy.deepcopy(valid)
    outside_window["recovery_events"][0]["observed_at"] = (
        "2026-09-29T09:59:59+00:00"
    )
    _reject(outside_window, "must occur inside the soak sample window")

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

    wrong_stage_b_path_ref = copy.deepcopy(valid)
    wrong_stage_b_path_ref["stage_b_evidence_ref"] = (
        "validation/other-stage-b-report.json#sha256=" + STAGE_B_SHA256
    )
    _reject(wrong_stage_b_path_ref, "path does not match the loaded Stage-B report")

    malformed_stage_b_ref = copy.deepcopy(valid)
    malformed_stage_b_ref["stage_b_evidence_ref"] = "stage-b-report"
    _reject(malformed_stage_b_ref, "must end with #sha256")

    wrong_candidate = _stage_b()
    wrong_candidate["candidate"]["git_sha"] = "b" * 40
    _reject(valid, "candidate git_sha does not match repository checkout", stage_b=wrong_candidate)

    gate._candidate_identity_from_checkout = lambda _root: _checkout_candidate(
        git_sha="b" * 40
    )
    _reject(valid, "candidate git_sha does not match repository checkout")
    gate._candidate_identity_from_checkout = lambda _root: _checkout_candidate(
        code_sha256="d" * 64
    )
    _reject(valid, "candidate code_sha256 does not match repository checkout")
    gate._candidate_identity_from_checkout = lambda _root: _checkout_candidate(
        version="9.9.9"
    )
    _reject(valid, "candidate version does not match repository checkout")
    gate._candidate_identity_from_checkout = lambda _root: _checkout_candidate()

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

    failed_step = _stage_b()
    failed_step["steps"][0]["exit_code"] = 1
    _reject(valid, "exit_code must be zero", stage_b=failed_step)

    malformed_step = _stage_b()
    malformed_step["steps"][0]["exit_code"] = "0"
    _reject(valid, "exit_code must be an integer", stage_b=malformed_step)

    stage_b_errors = _stage_b()
    stage_b_errors["summary"]["errors"] = ["strict evidence failed"]
    _reject(valid, "summary.errors must be empty", stage_b=stage_b_errors)

    wrong_total = _stage_b()
    wrong_total["summary"]["total"] = 8
    _reject(valid, "summary.total must be nine", stage_b=wrong_total)

    truncated_steps = _stage_b()
    truncated_steps["steps"] = truncated_steps["steps"][:-1]
    _reject(valid, "complete six-step execution sequence", stage_b=truncated_steps)

    wrong_step = _stage_b()
    wrong_step["steps"][2]["label"] = "release maybe"
    _reject(valid, "label does not match canonical sequence", stage_b=wrong_step)

    wrong_command = _stage_b()
    wrong_command["steps"][2]["command"][1] = "not_freeze_check.py"
    _reject(valid, "command does not match canonical script", stage_b=wrong_command)

    missing_proof = _stage_b()
    missing_proof["summary"]["passed"] = missing_proof["summary"]["passed"][:-1]
    _reject(valid, "all nine canonical proofs", stage_b=missing_proof)

    duplicated_proof = _stage_b()
    duplicated_proof["summary"]["passed"][-1] = duplicated_proof["summary"]["passed"][0]
    _reject(valid, "all nine canonical proofs", stage_b=duplicated_proof)

    no_components = _stage_b()
    del no_components["evidence"]
    _reject(valid, "stage_b_report.evidence must be an object", stage_b=no_components)

    missing_component = _stage_b()
    del missing_component["evidence"]["strict_stage_b"]
    _reject(valid, "missing strict_stage_b", stage_b=missing_component)

    tampered_component = _stage_b()
    tampered_path = COMPONENT_ROOT / tampered_component["evidence"]["updater_chain"]["path"]
    tampered_path.write_text("{}\n", encoding="utf-8")
    _reject(valid, "byte count does not match file", stage_b=tampered_component)

    wrong_component_hash = _stage_b()
    wrong_component_hash["evidence"]["physical_campaign"]["sha256"] = "0" * 64
    _reject(valid, "SHA-256 does not match file", stage_b=wrong_component_hash)

    escaping_component = _stage_b()
    escaping_component["evidence"]["component_final_gate"]["path"] = "../outside.json"
    _reject(valid, "escapes repository root", stage_b=escaping_component)

    wrong_component_schema = _stage_b()
    wrong_component_schema["evidence"]["strict_stage_b"]["schema"] = "wrong/v1"
    _reject(valid, "schema metadata mismatch", stage_b=wrong_component_schema)

    wrong_component_candidate = _stage_b()
    strict_path = COMPONENT_ROOT / wrong_component_candidate["evidence"]["strict_stage_b"]["path"]
    strict_value = json.loads(strict_path.read_text(encoding="utf-8"))
    strict_value["candidate"]["git_sha"] = "b" * 40
    strict_raw = (json.dumps(strict_value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    strict_path.write_bytes(strict_raw)
    strict_meta = wrong_component_candidate["evidence"]["strict_stage_b"]
    strict_meta["sha256"] = hashlib.sha256(strict_raw).hexdigest()
    strict_meta["bytes"] = len(strict_raw)
    _reject(valid, "candidate git_sha mismatch", stage_b=wrong_component_candidate)

    wrong_component_code = _stage_b()
    final_path = COMPONENT_ROOT / wrong_component_code["evidence"]["component_final_gate"]["path"]
    final_value = json.loads(final_path.read_text(encoding="utf-8"))
    final_value["candidate"]["code_sha256"] = "d" * 64
    final_raw = (json.dumps(final_value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    final_path.write_bytes(final_raw)
    final_meta = wrong_component_code["evidence"]["component_final_gate"]
    final_meta["sha256"] = hashlib.sha256(final_raw).hexdigest()
    final_meta["bytes"] = len(final_raw)
    _reject(valid, "candidate code_sha256 mismatch", stage_b=wrong_component_code)

    for value in (float("nan"), float("inf"), float("-inf")):
        try:
            gate._positive_number(value, "max_age_hours")
        except gate.RecoverySoakError as exc:
            assert "finite" in str(exc)
        else:
            raise AssertionError(f"non-finite max_age_hours accepted: {value!r}")

    for value in (0.0, 720.0001):
        try:
            gate._positive_number(value, "max_age_hours")
        except gate.RecoverySoakError as exc:
            assert "at most 720" in str(exc)
        else:
            raise AssertionError(f"out-of-range max_age_hours accepted: {value!r}")

    assert gate._positive_number(720.0, "max_age_hours") == 720.0

    gate._candidate_identity_from_checkout = _ORIGINAL_CHECKOUT_CANDIDATE

    class _CandidateModule:
        def __init__(self, candidate: dict):
            self._candidate = candidate

        def candidate_identity(self, _root: Path) -> dict:
            return dict(self._candidate)

    for candidate, fragment in (
        (_checkout_candidate(working_tree_clean=False), "working tree is not clean"),
        (
            _checkout_candidate(version_stamps_consistent=False),
            "version stamps are inconsistent",
        ),
    ):
        gate._load_stage_b_validator = lambda _name, candidate=candidate: _CandidateModule(candidate)
        try:
            gate._candidate_identity_from_checkout(COMPONENT_ROOT)
        except gate.RecoverySoakError as exc:
            assert fragment in str(exc), (fragment, str(exc))
        else:
            raise AssertionError(f"invalid checkout candidate accepted: {candidate!r}")
    gate._load_stage_b_validator = _ORIGINAL_LOADER

    gate._revalidate_stage_b_component = _ORIGINAL_REVALIDATE
    gate._candidate_identity_from_checkout = _ORIGINAL_CHECKOUT_CANDIDATE
    gate._revalidate_release_freeze = _ORIGINAL_FREEZE_REVALIDATE


if __name__ == "__main__":
    try:
        run_contract()
        print("Kaliv recovery soak qualification contract: PASS")
    finally:
        gate._revalidate_stage_b_component = _ORIGINAL_REVALIDATE
        gate._candidate_identity_from_checkout = _ORIGINAL_CHECKOUT_CANDIDATE
        gate._revalidate_release_freeze = _ORIGINAL_FREEZE_REVALIDATE
        gate._load_stage_b_validator = _ORIGINAL_LOADER
        shutil.rmtree(COMPONENT_ROOT, ignore_errors=True)
