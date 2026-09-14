"""Adversarial contract for ADR-DC-029 exact-task execution-admission requirements."""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

import kaliv_dev_control  # noqa: E402
from kaliv_dev_control import catalog  # noqa: E402
import kaliv_dev_control.improvement_pilot_execution_admission_attestation as att  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_admission_requirements as req  # noqa: E402
from rsi_pilot_execution_admission_attestation_contract import (  # noqa: E402
    _authority,
    _claim,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-execution-admission-requirements-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (req.PilotExactTaskExecutionAdmissionRequirementsError, ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-029 unexpectedly accepted invalid input")


def _proof(*, all_green: bool = True):
    temp, claim = _claim(all_green=all_green)
    verifier, signature = _authority(claim)
    proof = att._verify_pilot_execution_admission_attestation(
        attestation=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:31:00Z",
    )
    return temp, proof


def run_contract() -> None:
    assert catalog.modelrig_command_catalog().command_ids == ()
    temp, proof = _proof()
    try:
        requirements = req.build_pilot_exact_task_execution_admission_requirements(proof)
        assert requirements.schema == req.PILOT_EXACT_TASK_EXECUTION_ADMISSION_REQUIREMENTS_SCHEMA
        assert requirements.authority == req.PILOT_EXACT_TASK_EXECUTION_ADMISSION_REQUIREMENTS_AUTHORITY
        assert requirements.admission_attestation_proof is proof
        assert requirements.admission_attestation_proof_sha256 == proof.sha256
        assert requirements.admission_attestation_sha256 == proof.attestation_sha256
        assert requirements.admission_attestation_signature_sha256 == proof.signature_sha256
        assert requirements.admission_packet_sha256 == proof.packet_sha256
        assert requirements.start_receipt_sha256 == proof.start_receipt_sha256

        inherited = proof.attestation.packet.admission_requirements
        assert requirements.repository == inherited.repository
        assert requirements.base_sha == inherited.base_sha
        assert requirements.requested_main_sha == inherited.requested_main_sha
        assert requirements.trial_id == inherited.trial_id
        assert requirements.operator_surface == inherited.operator_surface
        assert requirements.selected_pilot_task_id == inherited.selected_pilot_task_id
        assert requirements.workspace_root_path_sha256 == inherited.workspace_root_path_sha256
        assert (
            requirements.local_commits_allowed_by_human_scope
            is inherited.local_commits_allowed_by_human_scope
        )

        required_true = (
            "fresh_host_attestation_reverification_required",
            "fresh_live_consumption_revalidation_required",
            "fresh_human_task_execution_authorization_required",
            "one_shot_execution_nonce_required",
            "host_local_execution_admission_ledger_required",
            "exact_allowlisted_task_registry_entry_required",
            "exact_selected_task_required",
            "canonical_workspace_revalidation_required",
            "exact_source_base_head_binding_required",
            "exact_toolchain_binding_required",
            "feature_flag_enabled_reobservation_required",
            "native_windows_isolation_revalidation_required",
            "trusted_git_closure_revalidation_required",
            "kill_switch_armed_revalidation_required",
            "revoke_not_asserted_revalidation_required",
            "restart_recovery_revalidation_required",
            "network_write_blocked_revalidation_required",
            "credentials_absent_revalidation_required",
            "general_shell_forbidden",
            "model_defined_commands_forbidden",
            "unattended_cadence_forbidden",
            "exact_fixed_command_plan_required",
            "bounded_execution_budget_required",
            "manual_operator_invocation_required",
            "post_execution_receipt_required",
        )
        for field in required_true:
            assert getattr(requirements, field) is True
            _reject(
                lambda field=field: req.PilotExactTaskExecutionAdmissionRequirements.from_mapping(
                    {**requirements.to_dict(), field: False}
                )
            )

        forced_false = (
            "task_execution_admission_observed",
            "task_execution_authorized",
            "task_execution_started",
            "integration_ready",
            "product_pilot_started",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        for field in forced_false:
            assert getattr(requirements, field) is False
            _reject(
                lambda field=field: req.PilotExactTaskExecutionAdmissionRequirements.from_mapping(
                    {**requirements.to_dict(), field: True}
                )
            )

        replayed = req.PilotExactTaskExecutionAdmissionRequirements.from_mapping(
            requirements.to_dict()
        )
        assert replayed == requirements
        assert replayed.sha256 == requirements.sha256

        # A cryptographically valid but failed ADR-DC-028 attestation is evidence,
        # not a basis for later exact-task admission requirements.
        failed_temp, failed_proof = _proof(all_green=False)
        try:
            assert failed_proof.execution_admission_satisfied is False
            _reject(
                lambda: req.build_pilot_exact_task_execution_admission_requirements(
                    failed_proof
                )
            )
        finally:
            failed_temp.cleanup()

        _reject(
            lambda: req.PilotExactTaskExecutionAdmissionRequirements.from_mapping(
                {**requirements.to_dict(), "admission_attestation_proof_sha256": "0" * 64}
            )
        )
        _reject(
            lambda: req.PilotExactTaskExecutionAdmissionRequirements.from_mapping(
                {**requirements.to_dict(), "selected_pilot_task_id": "different.task"}
            )
        )
        forged_nested = requirements.to_dict()
        forged_nested["admission_attestation_proof"] = {
            **forged_nested["admission_attestation_proof"],
            "task_execution_authorized": True,
        }
        _reject(
            lambda: req.PilotExactTaskExecutionAdmissionRequirements.from_mapping(
                forged_nested
            )
        )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(requirements.to_dict())
        assert schema["additionalProperties"] is False
        assert (
            props["admission_attestation_proof"]["$ref"]
            == "rsi-pilot-execution-admission-attestation-proof-v1.schema.json"
        )
        assert props["schema"]["const"] == req.PILOT_EXACT_TASK_EXECUTION_ADMISSION_REQUIREMENTS_SCHEMA
        assert props["authority"]["const"] == req.PILOT_EXACT_TASK_EXECUTION_ADMISSION_REQUIREMENTS_AUTHORITY
        for field in required_true:
            assert props[field]["const"] is True
        for field in forced_false:
            assert props[field]["const"] is False

        root_source = inspect.getsource(kaliv_dev_control)
        assert "improvement_pilot_exact_task_execution_admission_requirements" not in root_source
        source = inspect.getsource(req).lower()
        for forbidden in (
            "subprocess",
            "socket",
            "requests",
            "urllib",
            "git push",
            "merge_pull_request",
            "create_pull_request",
            "open(",
            "read_text",
            "read_bytes",
            "write_text",
            "write_bytes",
        ):
            assert forbidden not in source, forbidden
    finally:
        temp.cleanup()

    # Keep ADR-030 transitively wired through ADR-029 and the same Stage-B
    # support entrypoint instead of expanding the locked top-level inventory.
    from rsi_pilot_exact_task_execution_authorization_contract import (
        run_contract as run_execution_authorization_contract,
    )
    # ADR-031 follows ADR-030 but remains on this same Stage-B support chain.
    from rsi_pilot_exact_task_execution_revalidation_observation_contract import (
        run_contract as run_revalidation_observation_contract,
    )
    # ADR-032 verifies ADR-031 but still runs through the locked Stage-B chain.
    from rsi_pilot_exact_task_execution_revalidation_attestation_contract import (
        run_contract as run_revalidation_attestation_contract,
    )
    # ADR-033 consumes the exact signed execution nonce but still executes no task.
    from rsi_pilot_exact_task_execution_admission_contract import (
        run_contract as run_exact_task_execution_admission_contract,
    )

    run_execution_authorization_contract()
    run_revalidation_observation_contract()
    run_revalidation_attestation_contract()
    run_exact_task_execution_admission_contract()


if __name__ == "__main__":
    run_contract()
