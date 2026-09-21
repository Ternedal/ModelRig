"""Adversarial contract for ADR-DC-096 v2 product-pilot start readiness."""
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

from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_start_readiness as readiness  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_start_requirements as requirements  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_post_production_activation_attestation as attestation  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_task_registry as registry  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_runtime_preflight as runtime  # noqa: E402
import rsi_pilot_exact_task_product_pilot_lineage_attestation_contract as lineage_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_runtime_preflight_contract as runtime_contract  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-product-pilot-start-readiness-v2.schema.json"
)
SOURCE = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "improvement_pilot_exact_task_product_pilot_start_readiness.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError, AttributeError):
        return
    raise AssertionError("ADR-DC-096 v2 unexpectedly accepted unsafe pilot readiness")


def _components(fixture):
    source = fixture["post_production"]
    manifest = requirements.build_pilot_exact_task_product_pilot_start_requirements(
        source
    )
    task_registry, lineage_receipt = runtime_contract._registry_receipt(fixture)
    claim = runtime_contract._claim(task_registry)
    verifier, signature = runtime_contract._authority(claim)
    runtime_receipt = runtime._verify_pilot_exact_task_product_pilot_runtime_preflight(
        task_registry_receipt=task_registry,
        attestation=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-15T09:54:31Z",
    )
    assert source.attestation_authenticated is True
    assert lineage_receipt.attestation_authenticated is True
    assert task_registry.registry_authenticated is True
    assert runtime_receipt.preflight_authenticated is True
    return source, manifest, task_registry, runtime_receipt


def _evaluate(source, manifest, task_registry, runtime_receipt, when):
    return readiness._evaluate_verified_pilot_exact_task_product_pilot_start_readiness(
        source,
        manifest,
        task_registry,
        runtime_receipt,
        now_provider=lambda: when,
    )


def _ready_from_fixture(fixture, when="2026-09-15T09:54:40Z"):
    source, manifest, task_registry, runtime_receipt = _components(fixture)
    return _evaluate(
        source,
        manifest,
        task_registry,
        runtime_receipt,
        when,
    )


def _assert_inert(receipt) -> None:
    for field in (
        "production_activation",
        "production_activation_attested",
        "post_production_state_verified",
        "requirements_manifest_verified",
        "pre_authorization_requirements_satisfied",
        "fresh_human_product_pilot_go_verified",
        "explicit_pilot_scope_verified",
        "product_integration_selection_reverified",
        "runtime_preflight_reverified",
        "allowlisted_task_registry_verified",
        "canonical_workspace_revalidated",
        "feature_flag_default_off_verified",
        "local_only_scope_verified",
        "manual_operator_invocation_verified",
        "kill_switch_armed",
        "revoke_not_asserted",
        "restart_recovery_verified",
        "network_writes_blocked_verified",
        "credentials_absent_verified",
        "unattended_cadence_forbidden_verified",
        "general_shell_forbidden_verified",
        "model_defined_commands_forbidden_verified",
        "exact_source_binding_verified",
        "exact_toolchain_binding_verified",
        "one_shot_start_authorization_required",
        "host_local_replay_guard_required",
        "start_receipt_required",
        "product_pilot_start_ready",
        "next_boundary_authorization_required",
    ):
        assert getattr(receipt, field) is True, field
    for field in (
        "product_pilot_start_authorized",
        "product_pilot_started",
        "task_execution_authorized",
        "local_commit_authorized",
        "manual_intervention_required",
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
    ):
        assert getattr(receipt, field) is False, field


def run_contract(*, shared_fixture=None) -> None:
    if os.name == "nt":
        return

    owns_fixture = shared_fixture is None
    fixture = lineage_contract._build_fixture() if owns_fixture else shared_fixture
    try:
        source, manifest, task_registry, runtime_receipt = _components(fixture)
        receipt = _evaluate(
            source,
            manifest,
            task_registry,
            runtime_receipt,
            "2026-09-15T09:54:40Z",
        )
        assert receipt.readiness_authenticated is True
        assert receipt.schema == readiness.PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_SCHEMA
        assert receipt.schema.endswith("/v2")
        assert receipt.post_production_activation_attestation_sha256 == source.sha256
        assert receipt.product_pilot_start_requirements_sha256 == manifest.sha256
        assert (
            receipt.product_pilot_task_registry_receipt_sha256
            == task_registry.sha256
        )
        assert (
            receipt.product_pilot_runtime_preflight_receipt_sha256
            == runtime_receipt.sha256
        )
        assert (
            receipt.product_pilot_lineage_attestation_sha256
            == task_registry.lineage_attestation_sha256
        )
        assert (
            receipt.fresh_human_decision_proof_sha256
            == task_registry.fresh_human_decision_proof_sha256
        )
        assert receipt.development_task_sha256 == task_registry.development_task_sha256
        assert receipt.fixed_command_id == task_registry.fixed_command_id
        assert receipt.attestation_age_seconds == 39
        assert receipt.human_go_age_seconds == 29
        assert receipt.runtime_preflight_age_seconds == 9
        _assert_inert(receipt)

        live = readiness._get_live_readiness_source(receipt)
        assert live is not None
        assert live["source"] is source
        assert live["requirements"] is manifest
        assert live["task_registry"] is task_registry
        assert live["runtime_preflight"] is runtime_receipt

        serialized = readiness.PilotExactTaskProductPilotStartReadinessReceipt.from_mapping(
            receipt.to_dict()
        )
        assert serialized == receipt
        assert serialized.readiness_authenticated is False

        replayed_source = (
            attestation.PilotExactTaskPostProductionActivationAttestationReceipt.from_mapping(
                source.to_dict()
            )
        )
        assert replayed_source.attestation_authenticated is False
        _reject(
            lambda: _evaluate(
                replayed_source,
                manifest,
                task_registry,
                runtime_receipt,
                "2026-09-15T09:54:40Z",
            )
        )

        replayed_registry = registry.PilotExactTaskProductPilotTaskRegistryReceipt.from_mapping(
            task_registry.to_dict()
        )
        assert replayed_registry.registry_authenticated is False
        _reject(
            lambda: _evaluate(
                source,
                manifest,
                replayed_registry,
                runtime_receipt,
                "2026-09-15T09:54:40Z",
            )
        )

        replayed_runtime = runtime.PilotExactTaskProductPilotRuntimePreflightReceipt.from_mapping(
            runtime_receipt.to_dict()
        )
        assert replayed_runtime.preflight_authenticated is False
        _reject(
            lambda: _evaluate(
                source,
                manifest,
                task_registry,
                replayed_runtime,
                "2026-09-15T09:54:40Z",
            )
        )

        _reject(
            lambda: _evaluate(
                source,
                manifest,
                task_registry,
                runtime_receipt,
                "2026-09-15T09:55:02Z",
            )
        )

        for field, value in (
            ("pre_authorization_requirements_satisfied", False),
            ("runtime_preflight_reverified", False),
            ("allowlisted_task_registry_verified", False),
            ("product_pilot_start_ready", False),
            ("product_pilot_start_authorized", True),
            ("product_pilot_started", True),
            ("task_execution_authorized", True),
            ("remote_write_authorized", True),
            ("production_activation_authorized", True),
            ("next_boundary_authorization_required", False),
            ("nonce_reusable", True),
        ):
            raw = receipt.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: readiness.PilotExactTaskProductPilotStartReadinessReceipt.from_mapping(
                    raw
                )
            )

        raw = receipt.to_dict()
        raw["human_go_age_seconds"] -= 1
        _reject(
            lambda: readiness.PilotExactTaskProductPilotStartReadinessReceipt.from_mapping(
                raw
            )
        )
    finally:
        if owns_fixture:
            lineage_contract._cleanup(fixture)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(
        readiness.PilotExactTaskProductPilotStartReadinessReceipt.__dataclass_fields__
    )
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields
    assert schema["additionalProperties"] is False

    public_signature = inspect.signature(
        readiness.evaluate_pilot_exact_task_product_pilot_start_readiness
    )
    assert tuple(public_signature.parameters) == (
        "post_production_activation_attestation",
        "product_pilot_start_requirements",
        "product_pilot_task_registry_receipt",
        "product_pilot_runtime_preflight_receipt",
    )

    source_code = code_of(SOURCE)
    for forbidden in (
        "subprocess.",
        "create_once_file",
        "urllib",
        "requests.",
        "http.client",
        '"POST"',
        '"PUT"',
        '"PATCH"',
        '"DELETE"',
        ".write_text(",
        ".write_bytes(",
        ".unlink(",
        ".rename(",
    ):
        assert forbidden not in source_code


if __name__ == "__main__":
    run_contract()
