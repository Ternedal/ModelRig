"""Adversarial contract for ADR-DC-026 execution-admission requirements."""
from __future__ import annotations

import inspect
import json
import sys
import tempfile
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
import kaliv_dev_control.improvement_pilot_start_consumption as consume  # noqa: E402
import kaliv_dev_control.improvement_pilot_execution_admission_requirements as req  # noqa: E402
from rsi_pilot_start_consumption_contract import _chain  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-execution-admission-requirements-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-026 unexpectedly accepted invalid input")


def _receipt():
    supplied, fresh, preflight_signature, _authorization_signature = _chain()
    temp = tempfile.TemporaryDirectory(prefix="rsi-pilot-admission-req-")
    root = Path(temp.name).resolve()
    ledger = consume._PilotStartConsumptionLedger(root)
    receipt = consume._consume_verified_pilot_start_authorization(
        supplied_proof=supplied,
        fresh_proof=fresh,
        preflight_signature_sha256=preflight_signature.sha256,
        ledger=ledger,
        now_provider=lambda: "2026-09-14T08:28:00Z",
    )
    return temp, receipt


def run_contract() -> None:
    assert catalog.modelrig_command_catalog().command_ids == ()
    temp, receipt = _receipt()
    try:
        requirements = req.build_pilot_execution_admission_requirements(receipt)
        assert requirements.schema == req.PILOT_EXECUTION_ADMISSION_REQUIREMENTS_SCHEMA
        assert requirements.authority == req.PILOT_EXECUTION_ADMISSION_REQUIREMENTS_AUTHORITY
        assert requirements.start_receipt is receipt
        assert requirements.start_receipt_sha256 == receipt.sha256
        assert requirements.authorization_proof_sha256 == receipt.authorization_proof_sha256
        assert requirements.fresh_authorization_proof_sha256 == receipt.fresh_authorization_proof_sha256
        assert requirements.authorization_signature_sha256 == receipt.authorization_signature_sha256
        assert requirements.preflight_signature_sha256 == receipt.preflight_signature_sha256
        assert requirements.start_nonce_sha256 == receipt.start_nonce_sha256
        assert requirements.ledger_root_path_sha256 == receipt.ledger_root_path_sha256

        authorization = receipt.authorization_proof.authorization
        assert requirements.repository == authorization.repository
        assert requirements.base_sha == authorization.base_sha
        assert requirements.requested_main_sha == authorization.requested_main_sha
        assert requirements.trial_id == authorization.trial_id
        assert requirements.operator_surface == authorization.operator_surface
        assert requirements.selected_pilot_task_id == authorization.selected_pilot_task_id
        assert requirements.workspace_root_path_sha256 == authorization.workspace_root_path_sha256
        assert (
            requirements.local_commits_allowed_by_human_scope
            is authorization.local_commits_allowed
        )

        required_true = (
            "host_ledger_revalidation_required",
            "fresh_upstream_authority_reverification_required",
            "live_consumption_receipt_required_at_admission",
            "allowlisted_task_registry_required",
            "exact_selected_task_required",
            "canonical_workspace_revalidation_required",
            "feature_flag_enabled_observation_required",
            "native_windows_isolation_required",
            "trusted_git_closure_required",
            "kill_switch_armed_required",
            "revoke_not_asserted_required",
            "restart_recovery_proof_required",
            "network_write_blocked_required",
            "credentials_absent_required",
            "unattended_cadence_forbidden",
            "general_shell_forbidden",
            "model_defined_commands_forbidden",
            "exact_source_base_head_binding_required",
            "exact_toolchain_binding_required",
            "execution_receipt_required",
            "manual_operator_invocation_required",
        )
        for field in required_true:
            assert getattr(requirements, field) is True
            _reject(
                lambda field=field: req.PilotExecutionAdmissionRequirements.from_mapping(
                    {**requirements.to_dict(), field: False}
                )
            )

        forced_false = (
            "execution_admission_observed",
            "task_execution_authorized",
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
                lambda field=field: req.PilotExecutionAdmissionRequirements.from_mapping(
                    {**requirements.to_dict(), field: True}
                )
            )

        replayed_requirements = req.PilotExecutionAdmissionRequirements.from_mapping(
            requirements.to_dict()
        )
        assert replayed_requirements == requirements
        assert replayed_requirements.sha256 == requirements.sha256
        assert replayed_requirements.start_receipt == receipt
        assert replayed_requirements.start_receipt.transaction_authenticated is False

        # Durable ADR-DC-025 evidence may define inert requirements, but cannot become
        # admission authority after reload. ADR-026 requires the later admission to
        # receive live consumption provenance again and revalidate ledger + upstream
        # authority before any execution-admission decision.
        reloaded_receipt = consume.PilotStartConsumptionReceipt.from_mapping(
            receipt.to_dict()
        )
        assert receipt.transaction_authenticated is True
        assert reloaded_receipt.transaction_authenticated is False
        from_reloaded = req.build_pilot_execution_admission_requirements(reloaded_receipt)
        assert from_reloaded == requirements
        assert from_reloaded.task_execution_authorized is False
        assert from_reloaded.host_ledger_revalidation_required is True
        assert from_reloaded.fresh_upstream_authority_reverification_required is True
        assert from_reloaded.live_consumption_receipt_required_at_admission is True

        _reject(
            lambda: req.PilotExecutionAdmissionRequirements.from_mapping(
                {
                    **requirements.to_dict(),
                    "start_receipt_sha256": "0" * 64,
                }
            )
        )
        _reject(
            lambda: req.PilotExecutionAdmissionRequirements.from_mapping(
                {
                    **requirements.to_dict(),
                    "start_receipt": {
                        **requirements.to_dict()["start_receipt"],
                        "task_execution_authorized": True,
                    },
                }
            )
        )
        _reject(
            lambda: req.PilotExecutionAdmissionRequirements.from_mapping(
                {
                    **requirements.to_dict(),
                    "selected_pilot_task_id": "different.task",
                }
            )
        )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(requirements.to_dict())
        assert schema["additionalProperties"] is False
        assert props["start_receipt"]["$ref"] == "rsi-pilot-start-consumption-receipt-v1.schema.json"
        assert props["schema"]["const"] == req.PILOT_EXECUTION_ADMISSION_REQUIREMENTS_SCHEMA
        assert props["authority"]["const"] == req.PILOT_EXECUTION_ADMISSION_REQUIREMENTS_AUTHORITY
        for field in required_true:
            assert props[field]["const"] is True
        for field in forced_false:
            assert props[field]["const"] is False

        root_source = inspect.getsource(kaliv_dev_control)
        assert "improvement_pilot_execution_admission_requirements" not in root_source
        module_source = inspect.getsource(req).lower()
        for forbidden in (
            "subprocess",
            "socket",
            "requests",
            "urllib",
            "git push",
            "merge_pull_request",
            "create_pull_request",
        ):
            assert forbidden not in module_source, forbidden
    finally:
        temp.cleanup()


if __name__ == "__main__":
    run_contract()
