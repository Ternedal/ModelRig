"""Adversarial contract for ADR-DC-096 product-pilot start requirements."""
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
from source_code import code_of  # noqa: E402

DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_start_requirements as requirements  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_post_production_activation_attestation as attestation  # noqa: E402
import rsi_pilot_exact_task_post_production_activation_attestation_contract as attestation_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_lineage_attestation_contract as lineage_contract  # noqa: E402
import rsi_pilot_exact_task_production_activation_recovery_contract as recovery_contract  # noqa: E402
import rsi_pilot_exact_task_production_activation_transaction_contract as tx_contract  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-product-pilot-start-requirements-v1.schema.json"
)
SOURCE = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "improvement_pilot_exact_task_product_pilot_start_requirements.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError(
        "ADR-DC-096 unexpectedly accepted unsafe product-pilot start requirements"
    )


def _assert_requirements_only(receipt) -> None:
    required_true = (
        "production_activation",
        "production_activation_attested",
        "post_production_activation_attestation_required",
        "fresh_post_production_activation_attestation_required",
        "fresh_human_product_pilot_go_required",
        "explicit_pilot_scope_required",
        "product_integration_selection_reverification_required",
        "runtime_preflight_reverification_required",
        "allowlisted_task_registry_required",
        "canonical_workspace_revalidation_required",
        "feature_flag_default_off_required",
        "local_only_scope_required",
        "manual_operator_invocation_required",
        "kill_switch_armed_required",
        "revoke_not_asserted_required",
        "restart_recovery_required",
        "network_writes_blocked_required",
        "credentials_absent_required",
        "unattended_cadence_forbidden",
        "general_shell_forbidden",
        "model_defined_commands_forbidden",
        "exact_source_binding_required",
        "exact_toolchain_binding_required",
        "one_shot_start_authorization_required",
        "host_local_replay_guard_required",
        "start_receipt_required",
    )
    forced_false = (
        "requirements_satisfied",
        "product_pilot_ready",
        "product_pilot_start_authorized",
        "product_pilot_started",
        "task_execution_authorized",
        "local_commit_authorized",
        "promotion_gate_execution_authorized",
        "production_env_mutation_authorized",
        "appliance_restart_authorized",
        "production_receipt_write_authorized",
        "production_activation_authorized",
        "success_deployment_status_authorized",
        "deployment_status_mutation_authorized",
        "deployment_mutation_authorized",
        "deploy_authorized",
        "remote_write_authorized",
        "release_authorized",
        "tag_write_authorized",
        "release_mutation_authorized",
        "merge_authorized",
        "push_authorized",
        "pr_mutation_authorized",
        "review_submission_authorized",
        "review_thread_mutation_authorized",
        "nonce_reusable",
    )
    assert all(getattr(receipt, name) is True for name in required_true)
    assert all(getattr(receipt, name) is False for name in forced_false)


def _assert_schema_parity() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(
        requirements.PilotExactTaskProductPilotStartRequirements.__dataclass_fields__
    )
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields


def run_contract() -> None:
    if os.name == "nt":
        return

    # Use the canonical deep lineage fixture so ADR-DC-096 consumes the same
    # live post-production attestation topology as readiness-v2 and ADR-DC-097.
    fixture = lineage_contract._build_fixture()
    try:
        source = fixture["post_production"]
        assert source.attestation_authenticated is True

        manifest = (
            requirements.build_pilot_exact_task_product_pilot_start_requirements(
                source
            )
        )
        assert (
            manifest.post_production_activation_attestation_sha256
            == source.sha256
        )
        assert manifest.production_activation_completion_source == "transaction"
        assert (
            manifest.production_activation_source_receipt_sha256
            == source.production_activation_source_receipt_sha256
        )
        assert (
            manifest.production_activation_candidate_sha256
            == source.production_activation_candidate_sha256
        )
        assert manifest.environment_after_sha256 == source.environment_after_sha256
        assert manifest.repository == source.repository
        assert manifest.repository_id == source.repository_id
        assert manifest.merge_commit_sha == source.merge_commit_sha
        assert manifest.promotion_git_sha == source.promotion_git_sha
        assert (
            manifest.post_production_second_observed_at_utc
            == source.second_observed_at_utc
        )
        _assert_requirements_only(manifest)

        roundtrip = (
            requirements.PilotExactTaskProductPilotStartRequirements.from_mapping(
                manifest.to_dict()
            )
        )
        assert roundtrip == manifest
        assert roundtrip.sha256 == manifest.sha256

        serialized_source = (
            attestation.PilotExactTaskPostProductionActivationAttestationReceipt.from_mapping(
                source.to_dict()
            )
        )
        assert serialized_source == source
        assert serialized_source.attestation_authenticated is False
        _reject(
            lambda: requirements.build_pilot_exact_task_product_pilot_start_requirements(
                serialized_source
            )
        )

        for field, value in (
            ("fresh_human_product_pilot_go_required", False),
            ("runtime_preflight_reverification_required", False),
            ("network_writes_blocked_required", False),
            ("requirements_satisfied", True),
            ("product_pilot_ready", True),
            ("product_pilot_start_authorized", True),
            ("product_pilot_started", True),
            ("task_execution_authorized", True),
            ("remote_write_authorized", True),
            ("production_activation_authorized", True),
            ("nonce_reusable", True),
        ):
            raw = manifest.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: requirements.PilotExactTaskProductPilotStartRequirements.from_mapping(
                    raw
                )
            )

        invalid_hash = manifest.to_dict()
        invalid_hash["post_production_activation_attestation_sha256"] = "0" * 64
        _reject(
            lambda: requirements.PilotExactTaskProductPilotStartRequirements.from_mapping(
                invalid_hash
            )
        )

        invalid_time = manifest.to_dict()
        invalid_time["post_production_first_observed_at_utc"] = (
            "2000-01-01T00:00:00Z"
        )
        _reject(
            lambda: requirements.PilotExactTaskProductPilotStartRequirements.from_mapping(
                invalid_time
            )
        )
    finally:
        lineage_contract._cleanup(fixture)

    recovered = recovery_contract._make_exact_activated_lock()
    try:
        recovery_receipt, recovery_ledger = recovery_contract._recover(recovered)
        assert recovery_receipt.recovery_state_class == "exact_activated"
        source = attestation_contract._attest(recovered, recovery_ledger)
        manifest = (
            requirements.build_pilot_exact_task_product_pilot_start_requirements(
                source
            )
        )
        assert manifest.production_activation_completion_source == "recovery"
        assert (
            manifest.post_production_activation_attestation_sha256
            == source.sha256
        )
        _assert_requirements_only(manifest)
    finally:
        tx_contract._cleanup(recovered)

    _assert_schema_parity()

    signature = inspect.signature(
        requirements.build_pilot_exact_task_product_pilot_start_requirements
    )
    assert tuple(signature.parameters) == ("attestation",)

    source_code = code_of(SOURCE)
    for forbidden in (
        "subprocess",
        "urllib",
        "requests",
        "socket",
        "create_once_file",
        "write_text",
        "write_bytes",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
    ):
        assert forbidden not in source_code
    assert "attestation_authenticated" in source_code
    assert "fresh_human_product_pilot_go_required" in source_code
    assert "product_pilot_started" in source_code
    assert "product_pilot_start_authorized" in source_code


if __name__ == "__main__":
    run_contract()
