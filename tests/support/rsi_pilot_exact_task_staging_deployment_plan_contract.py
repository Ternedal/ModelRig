"""Adversarial contract for ADR-DC-071 exact staging deployment plan."""
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

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_deploy_readiness_evaluation as deploy_ready,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_deployment_plan as deploy_plan,
)
import rsi_pilot_exact_task_deploy_readiness_evaluation_contract as ready_contract  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-staging-deployment-plan-v1.schema.json"
)
SOURCE = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "improvement_pilot_exact_task_staging_deployment_plan.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-071 unexpectedly accepted unsafe staging plan")


def _live_readiness(*, policy=None, now="2026-09-15T09:47:00Z"):
    items = ready_contract._live_source()
    source = items[-1]
    selected = ready_contract._policy(source) if policy is None else policy(source)
    receipt = ready_contract._evaluate(
        source,
        selected,
        ready_contract._Transport(source),
        now=now,
    )
    assert receipt.evaluation_authenticated is True
    return items, receipt


def _config(source):
    return deploy_plan.PilotExactTaskStagingDeploymentPlanConfig(
        repository=source.repository,
        repository_id=source.repository_id,
    )


def _materialize(source, config, *, now="2026-09-15T09:48:00Z"):
    return deploy_plan._materialize_verified_pilot_exact_task_staging_deployment_plan(
        deploy_readiness_evaluation=source,
        config=config,
        config_sha256=config.sha256,
        now_provider=lambda: now,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    items, readiness = _live_readiness()
    try:
        config = _config(readiness)
        receipt = _materialize(readiness, config)
        assert receipt.plan_authenticated is True
        assert receipt.deploy_readiness_evaluation_sha256 == readiness.sha256
        assert receipt.deploy_readiness_policy_sha256 == readiness.deploy_readiness_policy_sha256
        assert receipt.deployment_environment == "staging"
        assert receipt.deployment_identity == f"modelrig-staging-{readiness.merge_commit_sha}"
        assert receipt.deployment_ref == readiness.tag_name
        assert receipt.deployment_task == "deploy"
        assert receipt.tag_target_sha == readiness.merge_commit_sha
        assert receipt.auto_merge is False
        assert receipt.required_contexts == ()
        assert receipt.transient_environment is False
        assert receipt.production_environment is False
        payload = json.loads(receipt.deployment_payload)
        assert payload["deployment_identity"] == receipt.deployment_identity
        assert payload["deployment_ref"] == receipt.deployment_ref
        assert payload["deployment_environment"] == "staging"
        assert payload["merge_commit_sha"] == readiness.merge_commit_sha
        assert receipt.deployment_creation_planned is True
        assert receipt.deploy_authorized is False
        assert receipt.deployment_mutation_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.production_activation_authorized is False

        same = _materialize(readiness, config)
        assert same.deployment_intent_sha256 == receipt.deployment_intent_sha256
        assert same.deployment_identity == receipt.deployment_identity
        assert same.deployment_payload == receipt.deployment_payload
        assert same.deployment_description == receipt.deployment_description

        reloaded = deploy_plan.PilotExactTaskStagingDeploymentPlanReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.plan_authenticated is False

        stale = deploy_ready.PilotExactTaskDeployReadinessEvaluationReceipt.from_mapping(
            readiness.to_dict()
        )
        assert stale.evaluation_authenticated is False
        _reject(lambda: _materialize(stale, config))

        other = deploy_plan.PilotExactTaskStagingDeploymentPlanConfig(
            repository="other/repo",
            repository_id=readiness.repository_id,
        )
        _reject(lambda: _materialize(readiness, other))
        _reject(
            lambda: deploy_plan._materialize_verified_pilot_exact_task_staging_deployment_plan(
                deploy_readiness_evaluation=readiness,
                config=config,
                config_sha256="9" * 64,
                now_provider=lambda: "2026-09-15T09:48:00Z",
            )
        )
        _reject(
            lambda: deploy_plan.PilotExactTaskStagingDeploymentPlanConfig(
                repository=readiness.repository,
                repository_id=readiness.repository_id,
                deployment_environment="production",
            )
        )
        _reject(
            lambda: deploy_plan.PilotExactTaskStagingDeploymentPlanConfig(
                repository=readiness.repository,
                repository_id=readiness.repository_id,
                auto_merge=True,
            )
        )
        _reject(
            lambda: deploy_plan.PilotExactTaskStagingDeploymentPlanConfig(
                repository=readiness.repository,
                repository_id=readiness.repository_id,
                required_contexts=("ci",),
            )
        )
        _reject(
            lambda: deploy_plan.PilotExactTaskStagingDeploymentPlanConfig(
                repository=readiness.repository,
                repository_id=readiness.repository_id,
                transient_environment=True,
            )
        )
        _reject(
            lambda: deploy_plan.PilotExactTaskStagingDeploymentPlanConfig(
                repository=readiness.repository,
                repository_id=readiness.repository_id,
                production_environment=True,
            )
        )
        _reject(
            lambda: _materialize(
                readiness,
                config,
                now="2026-09-15T09:46:00Z",
            )
        )

        negative_items, negative = _live_readiness(
            policy=lambda source: ready_contract._policy(
                source,
                base_branch="release-candidate",
            ),
            now="2026-09-15T09:47:10Z",
        )
        try:
            assert negative.evaluation_authenticated is True
            assert negative.deploy_ready is False
            _reject(lambda: _materialize(negative, _config(negative)))
        finally:
            ready_contract._cleanup_source(negative_items)

        for field, value in (
            ("deploy_readiness_authenticated", False),
            ("deploy_ready", False),
            ("staging_deployment_plan_config_host_pinned", False),
            ("deployment_intent_materialized", False),
            ("deployment_creation_planned", False),
            ("deploy_readiness_authorized", True),
            ("deployment_mutation_authorized", True),
            ("deploy_authorized", True),
            ("remote_write_authorized", True),
            ("release_authorized", True),
            ("tag_write_authorized", True),
            ("release_mutation_authorized", True),
            ("merge_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("review_submission_authorized", True),
            ("review_thread_mutation_authorized", True),
            ("production_activation_authorized", True),
            ("product_pilot_started", True),
            ("nonce_reusable", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    deploy_plan.PilotExactTaskStagingDeploymentPlanReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )
        _reject(
            lambda: deploy_plan.PilotExactTaskStagingDeploymentPlanReceipt.from_mapping(
                {**receipt.to_dict(), "deployment_ref": "other-tag"}
            )
        )
        _reject(
            lambda: deploy_plan.PilotExactTaskStagingDeploymentPlanReceipt.from_mapping(
                {**receipt.to_dict(), "deployment_payload": "{}"}
            )
        )
        _reject(
            lambda: deploy_plan.PilotExactTaskStagingDeploymentPlanReceipt.from_mapping(
                {**receipt.to_dict(), "deployment_intent_sha256": "8" * 64}
            )
        )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        receipt_fields = set(
            deploy_plan.PilotExactTaskStagingDeploymentPlanReceipt.__dataclass_fields__
        )
        assert set(schema["properties"]) == receipt_fields
        assert set(schema["required"]) == receipt_fields
        assert len(receipt_fields) == 61

        signature = inspect.signature(
            deploy_plan.materialize_pilot_exact_task_staging_deployment_plan
        )
        assert list(signature.parameters) == ["deploy_readiness_evaluation"]

        source_text = SOURCE.read_text(encoding="utf-8")
        assert "urllib" not in source_text
        assert "subprocess" not in source_text
        assert 'method="POST"' not in source_text
        assert 'method="PUT"' not in source_text
        assert 'method="PATCH"' not in source_text
        assert 'method="DELETE"' not in source_text
        assert "/deployments" not in source_text
        assert "create_deployment" not in source_text
        assert "create_deployment_status" not in source_text
        assert "production_activation_authorized: bool = False" in source_text
    finally:
        ready_contract._cleanup_source(items)


if __name__ == "__main__":
    run_contract()
