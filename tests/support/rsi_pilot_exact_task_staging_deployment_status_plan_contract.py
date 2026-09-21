"""Adversarial contract for ADR-DC-077 deterministic Deployment Status plan."""
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

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_post_staging_deployment_attestation as post_deploy,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_deployment_status_plan as status_plan,
)
import rsi_pilot_exact_task_post_staging_deployment_attestation_contract as attestation_contract  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-staging-deployment-status-plan-v1.schema.json"
SOURCE = ROOT / "devcontrol" / "src" / "kaliv_dev_control" / "improvement_pilot_exact_task_staging_deployment_status_plan.py"


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-077 unexpectedly accepted unsafe Deployment Status intent")


def _config(attestation):
    return status_plan.PilotExactTaskStagingDeploymentStatusPlanConfig(
        repository=attestation.repository,
        repository_id=attestation.repository_id,
    )


def _plan(attestation, config, *, now="2026-09-15T09:49:55Z"):
    return status_plan._plan_verified_pilot_exact_task_staging_deployment_status(
        post_staging_attestation=attestation,
        config=config,
        config_sha256=config.sha256,
        now_provider=lambda: now,
    )


def _normal_attestation():
    (
        items,
        readiness,
        authorization,
        auth_temp,
        tx_temp,
        _tx_ledger,
        tx_receipt,
        recovery_temp,
        recovery_root,
    ) = attestation_contract._normal_completion()
    transport = attestation_contract.recovery_contract._Transport(
        authorization,
        readiness,
        deployment_id=tx_receipt.deployment_id,
        node_hash=tx_receipt.deployment_node_id_sha256,
    )
    receipt = attestation_contract._attest(
        authorization,
        auth_temp,
        tx_temp,
        recovery_root,
        transport,
    )
    assert receipt.attestation_authenticated is True
    return (
        items,
        auth_temp,
        tx_temp,
        recovery_temp,
        receipt,
    )


def _recovered_attestation():
    (
        items,
        readiness,
        authorization,
        auth_temp,
        tx_temp,
        _tx_ledger,
        recovery_receipt,
        recovery_temp,
        recovery_ledger,
    ) = attestation_contract._recovered_completion()
    transport = attestation_contract.recovery_contract._Transport(
        authorization,
        readiness,
        deployment_id=recovery_receipt.deployment_id,
        node_hash=recovery_receipt.deployment_node_id_sha256,
    )
    receipt = attestation_contract._attest(
        authorization,
        auth_temp,
        tx_temp,
        recovery_ledger,
        transport,
    )
    assert receipt.attestation_authenticated is True
    return (
        items,
        auth_temp,
        tx_temp,
        recovery_temp,
        receipt,
    )


def _cleanup(context) -> None:
    items, auth_temp, tx_temp, recovery_temp, _receipt = context
    attestation_contract._cleanup(items, auth_temp, tx_temp, recovery_temp)


def run_contract() -> None:
    if os.name == "nt":
        return

    context = _normal_attestation()
    try:
        attestation = context[-1]
        config = _config(attestation)
        receipt = _plan(attestation, config)
        assert receipt.plan_authenticated is True
        assert receipt.post_staging_deployment_attestation_sha256 == attestation.sha256
        assert receipt.completion_source_receipt_sha256 == attestation.completion_source_receipt_sha256
        assert receipt.deployment_authorization_sha256 == attestation.deployment_authorization_sha256
        assert receipt.deployment_intent_sha256 == attestation.deployment_intent_sha256
        assert receipt.execution_nonce_sha256 == attestation.execution_nonce_sha256
        assert receipt.deployment_id == attestation.deployment_id
        assert receipt.deployment_node_id_sha256 == attestation.deployment_node_id_sha256
        assert receipt.completion_source == "transaction"
        assert receipt.source_action == "execute_exact_staging_deployment"
        assert receipt.source_remote_write_performed is True
        assert receipt.recovery_lock_sha256 is None
        assert receipt.deployment_status_state == "in_progress"
        assert receipt.deployment_status_environment == "staging"
        assert receipt.deployment_status_auto_inactive is False
        assert receipt.deployment_status_log_url is None
        assert receipt.deployment_status_environment_url is None
        body = json.loads(receipt.deployment_status_body)
        assert body == {
            "auto_inactive": False,
            "description": receipt.deployment_status_description,
            "environment": "staging",
            "state": "in_progress",
        }
        assert receipt.post_staging_attestation_authenticated is True
        assert receipt.post_staging_deployment_verified is True
        assert receipt.staging_deployment_status_plan_config_host_pinned is True
        assert receipt.deployment_status_intent_materialized is True
        assert receipt.deployment_status_transition_planned is True
        assert receipt.deployment_status_ready is True
        assert receipt.deployment_status_mutation_authorized is False
        assert receipt.deployment_mutation_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False

        duplicate = _plan(attestation, config)
        assert duplicate == receipt
        assert duplicate.sha256 == receipt.sha256
        assert duplicate.plan_authenticated is True

        serialized = status_plan.PilotExactTaskStagingDeploymentStatusPlanReceipt.from_mapping(
            receipt.to_dict()
        )
        assert serialized == receipt
        assert serialized.plan_authenticated is False

        stale_attestation = post_deploy.PilotExactTaskPostStagingDeploymentAttestationReceipt.from_mapping(
            attestation.to_dict()
        )
        assert stale_attestation.attestation_authenticated is False
        _reject(lambda: _plan(stale_attestation, config))

        wrong_repo = status_plan.PilotExactTaskStagingDeploymentStatusPlanConfig(
            repository="other/modelrig",
            repository_id=attestation.repository_id,
        )
        _reject(lambda: _plan(attestation, wrong_repo))

        _reject(
            lambda: status_plan.PilotExactTaskStagingDeploymentStatusPlanConfig(
                repository=attestation.repository,
                repository_id=attestation.repository_id,
                deployment_status_state="success",
            )
        )
        _reject(
            lambda: status_plan.PilotExactTaskStagingDeploymentStatusPlanConfig(
                repository=attestation.repository,
                repository_id=attestation.repository_id,
                deployment_status_environment="production",
            )
        )
        _reject(
            lambda: status_plan.PilotExactTaskStagingDeploymentStatusPlanConfig(
                repository=attestation.repository,
                repository_id=attestation.repository_id,
                deployment_status_auto_inactive=True,
            )
        )
        _reject(
            lambda: status_plan.PilotExactTaskStagingDeploymentStatusPlanConfig(
                repository=attestation.repository,
                repository_id=attestation.repository_id,
                allow_log_url=True,
            )
        )
        _reject(
            lambda: status_plan.PilotExactTaskStagingDeploymentStatusPlanConfig(
                repository=attestation.repository,
                repository_id=attestation.repository_id,
                allow_environment_url=True,
            )
        )

        _reject(lambda: _plan(attestation, config, now="2026-09-15T09:49:49Z"))

        for field, value in (
            ("deployment_status_state", "success"),
            ("deployment_status_environment", "production"),
            ("deployment_status_auto_inactive", True),
            ("deployment_status_log_url", "https://example.invalid/log"),
            ("deployment_status_environment_url", "https://example.invalid/env"),
            ("deployment_status_mutation_authorized", True),
            ("remote_write_authorized", True),
            ("production_activation_authorized", True),
            ("nonce_reusable", True),
        ):
            raw = receipt.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: status_plan.PilotExactTaskStagingDeploymentStatusPlanReceipt.from_mapping(raw)
            )
    finally:
        _cleanup(context)

    recovered_context = _recovered_attestation()
    try:
        attestation = recovered_context[-1]
        config = _config(attestation)
        receipt = _plan(attestation, config)
        assert receipt.plan_authenticated is True
        assert receipt.completion_source == "recovery"
        assert receipt.source_action == "finalize_existing_state"
        assert receipt.source_remote_write_performed is False
        assert receipt.recovery_lock_sha256 is not None
        assert receipt.deployment_status_state == "in_progress"
        assert receipt.deployment_status_ready is True
        assert receipt.deployment_status_mutation_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.production_activation_authorized is False
    finally:
        _cleanup(recovered_context)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    dataclass_fields = set(
        status_plan.PilotExactTaskStagingDeploymentStatusPlanReceipt.__dataclass_fields__
    )
    assert set(schema["required"]) == dataclass_fields
    assert set(schema["properties"]) == dataclass_fields
    assert len(dataclass_fields) == 70

    signature = inspect.signature(
        status_plan.plan_pilot_exact_task_staging_deployment_status
    )
    assert list(signature.parameters) == ["post_staging_attestation"]

    source = code_of(SOURCE)
    for forbidden in (
        'method="POST"', "method='POST'",
        'method="PUT"', "method='PUT'",
        'method="PATCH"', "method='PATCH'",
        'method="DELETE"', "method='DELETE'",
    ):
        assert forbidden not in source
    assert "/statuses" not in source
    assert "urllib.request" not in source
    assert "create_once_file" not in source


if __name__ == "__main__":
    run_contract()
