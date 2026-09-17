"""Adversarial contract for ADR-DC-085 deterministic staging success-status plan."""
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
    improvement_pilot_exact_task_staging_success_status_plan as success_plan,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_runtime_build_identity as build_identity,
)
import rsi_pilot_exact_task_staging_runtime_build_identity_contract as build_contract  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-staging-success-status-plan-v1.schema.json"
)
SOURCE = (
    ROOT / "devcontrol" / "src" / "kaliv_dev_control"
    / "improvement_pilot_exact_task_staging_success_status_plan.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-085 unexpectedly accepted unsafe success-status intent")


def _live_build_identity(*, recovered=False):
    bundle, _config, _credential, _path, runtime = build_contract._runtime_receipt(
        recovered=recovered
    )
    receipt = build_contract._verify(runtime, build_contract._BuildProbe(runtime))
    assert receipt.verification_authenticated is True
    return bundle, receipt


def _cleanup(bundle) -> None:
    build_contract.runtime_contract._cleanup(bundle)


def _config(source):
    return success_plan.PilotExactTaskStagingSuccessStatusPlanConfig(
        repository=source.repository,
        repository_id=source.repository_id,
    )


def _plan(source, config=None, *, now="2026-09-15T09:51:00Z"):
    config = config or _config(source)
    return success_plan._plan_verified_pilot_exact_task_staging_success_status(
        staging_runtime_build_identity=source,
        config=config,
        config_sha256=config.sha256,
        now_provider=lambda: now,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    bundle, source = _live_build_identity()
    try:
        receipt = _plan(source)
        assert receipt.plan_authenticated is True
        assert receipt.staging_runtime_build_identity_sha256 == source.sha256
        assert receipt.staging_runtime_verification_sha256 == source.staging_runtime_verification_sha256
        assert receipt.repository == source.repository
        assert receipt.repository_id == source.repository_id
        assert receipt.merge_commit_sha == source.merge_commit_sha
        assert receipt.deployment_id == source.deployment_id
        assert receipt.current_deployment_status_id == source.deployment_status_id
        assert receipt.current_deployment_status_state == "in_progress"
        assert receipt.current_deployment_status_environment == "staging"
        assert receipt.server_commit_sha == source.merge_commit_sha
        assert receipt.worker_commit_sha == source.merge_commit_sha
        assert receipt.server_executable_sha256 == source.server_executable_sha256
        assert receipt.worker_code_sha256 == source.worker_code_sha256
        assert receipt.worker_artifact_sha256 == source.worker_artifact_sha256
        assert receipt.success_deployment_status_state == "success"
        assert receipt.success_deployment_status_environment == "staging"
        assert receipt.success_deployment_status_auto_inactive is False
        assert receipt.success_deployment_status_log_url is None
        assert receipt.success_deployment_status_environment_url is None
        assert json.loads(receipt.success_deployment_status_body) == {
            "state": "success",
            "description": receipt.success_deployment_status_description,
            "environment": "staging",
            "auto_inactive": False,
        }
        assert receipt.success_deployment_status_ready is True
        assert receipt.success_deployment_status_authorized is False
        assert receipt.deployment_status_mutation_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False

        duplicate = _plan(source)
        assert duplicate == receipt
        assert duplicate.sha256 == receipt.sha256

        serialized = success_plan.PilotExactTaskStagingSuccessStatusPlanReceipt.from_mapping(
            receipt.to_dict()
        )
        assert serialized == receipt
        assert serialized.plan_authenticated is False

        serialized_source = build_identity.PilotExactTaskStagingRuntimeBuildIdentityReceipt.from_mapping(
            source.to_dict()
        )
        assert serialized_source.verification_authenticated is False
        _reject(lambda: _plan(serialized_source))

        bad_repo = success_plan.PilotExactTaskStagingSuccessStatusPlanConfig(
            repository=source.repository,
            repository_id="999",
        )
        _reject(lambda: _plan(source, bad_repo))

        _reject(lambda: success_plan.PilotExactTaskStagingSuccessStatusPlanConfig(
            repository=source.repository,
            repository_id=source.repository_id,
            deployment_status_state="in_progress",
        ))
        _reject(lambda: success_plan.PilotExactTaskStagingSuccessStatusPlanConfig(
            repository=source.repository,
            repository_id=source.repository_id,
            deployment_status_environment="production",
        ))
        _reject(lambda: success_plan.PilotExactTaskStagingSuccessStatusPlanConfig(
            repository=source.repository,
            repository_id=source.repository_id,
            deployment_status_auto_inactive=True,
        ))
        _reject(lambda: success_plan.PilotExactTaskStagingSuccessStatusPlanConfig(
            repository=source.repository,
            repository_id=source.repository_id,
            allow_log_url=True,
        ))
        _reject(lambda: success_plan.PilotExactTaskStagingSuccessStatusPlanConfig(
            repository=source.repository,
            repository_id=source.repository_id,
            allow_environment_url=True,
        ))

        _reject(lambda: _plan(source, now="2026-09-15T09:50:49Z"))

        for field, value in (
            ("success_deployment_status_state", "failure"),
            ("success_deployment_status_environment", "production"),
            ("success_deployment_status_auto_inactive", True),
            ("success_deployment_status_log_url", "https://example.invalid/log"),
            ("success_deployment_status_environment_url", "https://example.invalid"),
            ("server_commit_sha", "1" * 40),
            ("worker_commit_sha", "2" * 40),
        ):
            data = receipt.to_dict()
            data[field] = value
            _reject(
                lambda data=data: success_plan.PilotExactTaskStagingSuccessStatusPlanReceipt.from_mapping(data)
            )

        for field in (
            "staging_runtime_build_identity_authenticated",
            "exact_runtime_commit_verified",
            "exact_runtime_artifacts_verified",
            "success_status_plan_config_host_pinned",
            "success_status_intent_materialized",
            "success_status_transition_planned",
            "success_deployment_status_ready",
        ):
            data = receipt.to_dict()
            data[field] = False
            _reject(
                lambda data=data: success_plan.PilotExactTaskStagingSuccessStatusPlanReceipt.from_mapping(data)
            )

        for field in (
            "success_deployment_status_authorized",
            "deployment_status_mutation_authorized",
            "deployment_mutation_authorized",
            "deploy_authorized",
            "remote_write_authorized",
            "release_authorized",
            "production_activation_authorized",
            "nonce_reusable",
        ):
            data = receipt.to_dict()
            data[field] = True
            _reject(
                lambda data=data: success_plan.PilotExactTaskStagingSuccessStatusPlanReceipt.from_mapping(data)
            )
    finally:
        _cleanup(bundle)

    recovered_bundle, recovered_source = _live_build_identity(recovered=True)
    try:
        recovered = _plan(recovered_source)
        assert recovered.plan_authenticated is True
        assert recovered.status_recovery_lock_sha256 is not None
        assert recovered.success_deployment_status_state == "success"
        assert recovered.success_deployment_status_ready is True
        assert recovered.success_deployment_status_authorized is False
    finally:
        _cleanup(recovered_bundle)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(success_plan.PilotExactTaskStagingSuccessStatusPlanReceipt.__dataclass_fields__)
    assert set(schema["required"]) == fields
    assert set(schema["properties"]) == fields
    assert len(fields) == 73

    signature = inspect.signature(success_plan.plan_pilot_exact_task_staging_success_status)
    assert list(signature.parameters) == ["staging_runtime_build_identity"]

    source_text = code_of(SOURCE)
    for forbidden in (
        "urllib.request",
        'method="POST"',
        "method='POST'",
        'method="PUT"',
        "method='PUT'",
        'method="PATCH"',
        "method='PATCH'",
        'method="DELETE"',
        "method='DELETE'",
        "create_deployment_status(",
        "create_once_file",
    ):
        assert forbidden not in source_text
    assert '_STATUS_STATE = "success"' in source_text
    assert "success_deployment_status_authorized: bool = False" in source_text
    assert "deployment_status_mutation_authorized: bool = False" in source_text
    assert "production_activation_authorized: bool = False" in source_text


if __name__ == "__main__":
    run_contract()
