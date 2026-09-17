"""Adversarial contract for ADR-DC-034 exact-task execution-plan requirements."""
from __future__ import annotations

import inspect
import json
import os
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
import kaliv_dev_control.improvement_pilot_exact_task_execution_admission as admission  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_plan_requirements as plan_req  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_revalidation_attestation as revalidation  # noqa: E402
from rsi_pilot_exact_task_execution_admission_contract import _ledger, _proof  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-execution-plan-requirements-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-034 unexpectedly accepted invalid input")


class _DeferredSourceCleanup:
    """No-op cleanup for a proof fixture owned by the parent Stage-B bridge."""

    def cleanup(self) -> None:
        return None


def _cached_proofs():
    cache_path = os.environ.get("MODELRIG_STAGE_B_ADMISSION_PROOF_CACHE")
    if not cache_path:
        return None
    payload = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    proof = revalidation.PilotExactTaskExecutionRevalidationAttestationProof.from_mapping(
        payload["proof"]
    )
    fresh = revalidation.PilotExactTaskExecutionRevalidationAttestationProof.from_mapping(
        payload["fresh"]
    )
    admission.require_fresh_revalidation_proof_identity(proof, fresh)
    return _DeferredSourceCleanup(), proof, fresh


def _live_receipt():
    cached = _cached_proofs()
    if cached is None:
        source_temp, proof, fresh, *_ = _proof()
    else:
        source_temp, proof, fresh = cached
    ledger_temp, ledger = _ledger("rsi-exact-task-plan-requirements-")
    times = iter(("2026-09-14T08:36:20Z", "2026-09-14T08:36:21Z"))
    receipt = admission._admit_verified_exact_task_execution(
        supplied_proof=proof,
        fresh_proof=fresh,
        ledger=ledger,
        now_provider=lambda: next(times),
    )
    assert receipt.transaction_authenticated is True
    return source_temp, ledger_temp, receipt


def run_contract() -> None:
    assert catalog.modelrig_command_catalog().command_ids == ()
    source_temp, ledger_temp, receipt = _live_receipt()
    try:
        requirements = plan_req.build_pilot_exact_task_execution_plan_requirements(
            receipt
        )
        assert requirements.schema == plan_req.PILOT_EXACT_TASK_EXECUTION_PLAN_REQUIREMENTS_SCHEMA
        assert requirements.authority == plan_req.PILOT_EXACT_TASK_EXECUTION_PLAN_REQUIREMENTS_AUTHORITY
        assert requirements.admission_receipt is receipt
        assert requirements.admission_receipt_sha256 == receipt.sha256
        assert requirements.admission_key_sha256 == receipt.admission_key_sha256
        assert requirements.execution_nonce_sha256 == receipt.execution_nonce_sha256
        assert (
            requirements.revalidation_attestation_proof_sha256
            == receipt.revalidation_attestation_proof_sha256
        )
        assert (
            requirements.execution_authorization_proof_sha256
            == receipt.execution_authorization_proof_sha256
        )
        assert requirements.start_receipt_sha256 == receipt.start_receipt_sha256
        assert requirements.selected_pilot_task_id == receipt.selected_pilot_task_id
        assert requirements.workspace_root_path_sha256 == receipt.workspace_root_path_sha256
        assert (
            requirements.local_commits_allowed_by_human_scope
            is receipt.local_commits_allowed_by_human_scope
        )

        packet = receipt.revalidation_attestation_proof.attestation.packet
        assert requirements.repository == packet.repository
        assert requirements.base_sha == packet.base_sha
        assert requirements.requested_main_sha == packet.requested_main_sha
        assert requirements.trial_id == packet.trial_id
        assert requirements.operator_surface == packet.operator_surface

        required_true = (
            "live_admission_receipt_required",
            "exact_admission_receipt_identity_required",
            "one_shot_executor_consumption_required",
            "durable_pre_launch_execution_consumption_reservation_required",
            "execution_consumption_key_is_signed_nonce_required",
            "concurrent_execution_replay_forbidden",
            "uncertain_execution_consumption_reservation_fails_closed",
            "post_execution_consumption_finalizes_reservation_required",
            "host_pinned_task_registry_required",
            "exact_development_task_required",
            "selected_pilot_task_mapping_required",
            "task_repository_base_match_required",
            "canonical_workspace_match_required",
            "single_fixed_command_required",
            "reviewed_nonempty_command_catalog_required",
            "exact_toolchain_binding_required",
            "signed_runtime_closure_required",
            "host_resolved_signed_runtime_closure_required",
            "caller_selected_signed_runtime_closure_forbidden",
            "host_pinned_physical_verifier_required",
            "host_resolved_isolation_attestation_required",
            "caller_selected_isolation_attestation_forbidden",
            "host_pinned_runtime_closure_verifier_required",
            "canonical_trusted_runtime_root_required",
            "host_resolved_trusted_runtime_root_required",
            "caller_selected_trusted_runtime_root_forbidden",
            "host_pinned_trusted_git_runner_required",
            "control_plane_toolhost_binding_required",
            "reviewed_source_environment_required",
            "caller_selected_source_environment_forbidden",
            "exact_native_process_limits_required",
            "caller_selected_native_process_limits_forbidden",
            "caller_selected_executable_verifier_forbidden",
            "trusted_git_runtime_required",
            "native_windows_tier_a_required",
            "network_deny_required",
            "credentials_absent_required",
            "general_shell_forbidden",
            "model_defined_commands_forbidden",
            "unattended_cadence_forbidden",
            "exact_execution_budget_required",
            "manual_operator_invocation_required",
            "pre_execution_git_snapshot_required",
            "host_resolved_pre_execution_git_snapshot_required",
            "execution_plan_workspace_state_binding_required",
            "pre_launch_git_snapshot_revalidation_required",
            "workspace_state_change_after_plan_materialization_forbidden",
            "post_execution_tier_a_receipt_required",
            "workspace_drift_fail_closed_reset_required",
            "post_execution_consumption_receipt_required",
        )
        for field in required_true:
            assert getattr(requirements, field) is True
            _reject(
                lambda field=field: plan_req.PilotExactTaskExecutionPlanRequirements.from_mapping(
                    {**requirements.to_dict(), field: False}
                )
            )

        forced_false = (
            "execution_plan_materialized",
            "execution_consumed",
            "task_execution_started",
            "task_execution_completed",
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
                lambda field=field: plan_req.PilotExactTaskExecutionPlanRequirements.from_mapping(
                    {**requirements.to_dict(), field: True}
                )
            )

        # The requirements artifact is durable inert evidence and can round-trip.
        replayed = plan_req.PilotExactTaskExecutionPlanRequirements.from_mapping(
            requirements.to_dict()
        )
        assert replayed == requirements
        assert replayed.sha256 == requirements.sha256
        assert replayed.admission_receipt.transaction_authenticated is False

        # But a reloaded ADR-DC-033 receipt can never issue a fresh requirements
        # artifact. Only the exact live transaction object can cross that boundary.
        reloaded_receipt = admission.PilotExactTaskExecutionAdmissionReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded_receipt.transaction_authenticated is False
        _reject(
            lambda: plan_req.build_pilot_exact_task_execution_plan_requirements(
                reloaded_receipt
            )
        )

        # Every copied receipt/scope field is an exact binding, not caller input.
        for field, value in (
            ("admission_receipt_sha256", "1" * 64),
            ("admission_key_sha256", "2" * 64),
            ("execution_nonce_sha256", "3" * 64),
            ("revalidation_attestation_proof_sha256", "4" * 64),
            ("execution_authorization_proof_sha256", "5" * 64),
            ("start_receipt_sha256", "6" * 64),
            ("repository", "Other/Repository"),
            ("base_sha", "a" * 40),
            ("requested_main_sha", "b" * 40),
            ("trial_id", "different.trial"),
            ("operator_surface", "different.operator"),
            ("selected_pilot_task_id", "different.task"),
            ("workspace_root_path_sha256", "7" * 64),
            (
                "local_commits_allowed_by_human_scope",
                not requirements.local_commits_allowed_by_human_scope,
            ),
        ):
            _reject(
                lambda field=field, value=value: plan_req.PilotExactTaskExecutionPlanRequirements.from_mapping(
                    {**requirements.to_dict(), field: value}
                )
            )
        _reject(
            lambda: plan_req.PilotExactTaskExecutionPlanRequirements.from_mapping(
                {**requirements.to_dict(), "unexpected": False}
            )
        )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(requirements.to_dict())
        assert schema["additionalProperties"] is False
        assert props["admission_receipt"]["$ref"] == (
            "rsi-pilot-exact-task-execution-admission-receipt-v1.schema.json"
        )
        assert props["schema"]["const"] == plan_req.PILOT_EXACT_TASK_EXECUTION_PLAN_REQUIREMENTS_SCHEMA
        assert props["authority"]["const"] == plan_req.PILOT_EXACT_TASK_EXECUTION_PLAN_REQUIREMENTS_AUTHORITY
        for field in required_true:
            assert props[field]["const"] is True
        for field in forced_false:
            assert props[field]["const"] is False

        root_source = inspect.getsource(kaliv_dev_control)
        assert "improvement_pilot_exact_task_execution_plan_requirements" not in root_source
        source = inspect.getsource(plan_req).lower()
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
            "run_verified_tier_a_command",
        ):
            assert forbidden not in source, forbidden
    finally:
        ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
