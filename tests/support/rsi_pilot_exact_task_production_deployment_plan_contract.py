"""Adversarial contract for ADR-DC-092 production Deployment planning."""
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
    improvement_pilot_exact_task_production_deployment_plan as production_plan,
)
import rsi_pilot_exact_task_staging_completion_readiness_contract as readiness_contract  # noqa: E402
from source_code import code_of  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-production-deployment-plan-v1.schema.json"
)
SOURCE = (
    ROOT / "devcontrol" / "src" / "kaliv_dev_control"
    / "improvement_pilot_exact_task_production_deployment_plan.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError(
        "ADR-DC-092 unexpectedly accepted unsafe production Deployment plan"
    )


def _config(source, **overrides):
    values = {
        "repository": source.repository,
        "repository_id": source.repository_id,
    }
    values.update(overrides)
    return production_plan.PilotExactTaskProductionDeploymentPlanConfig(**values)


def _plan(source, config, *, now="2026-09-15T09:52:30Z", digest=None):
    return production_plan._plan_verified_pilot_exact_task_production_deployment(
        staging_completion_readiness=source,
        config=config,
        config_sha256=config.sha256 if digest is None else digest,
        now_provider=lambda: now,
    )


def _assert_inert(receipt) -> None:
    assert receipt.staging_completion_readiness_authenticated is True
    assert receipt.production_plan_config_host_pinned is True
    assert receipt.readiness_fresh_verified is True
    assert receipt.exact_merge_commit_bound is True
    assert receipt.exact_runtime_build_identity_bound is True
    assert receipt.exact_staging_success_bound is True
    assert receipt.production_deployment_intent_materialized is True
    assert receipt.production_deployment_planned is True
    assert receipt.production_deployment_ready is True
    assert receipt.production_promotion_authorized is False
    assert receipt.production_deployment_authorized is False
    assert receipt.production_activation_authorized is False
    assert receipt.deployment_status_mutation_authorized is False
    assert receipt.deployment_mutation_authorized is False
    assert receipt.deploy_authorized is False
    assert receipt.remote_write_authorized is False
    assert receipt.release_authorized is False
    assert receipt.tag_write_authorized is False
    assert receipt.release_mutation_authorized is False
    assert receipt.merge_authorized is False
    assert receipt.push_authorized is False
    assert receipt.pr_mutation_authorized is False
    assert receipt.review_submission_authorized is False
    assert receipt.review_thread_mutation_authorized is False
    assert receipt.product_pilot_started is False
    assert receipt.nonce_reusable is False


def run_contract() -> None:
    if os.name == "nt":
        return

    post_source, bundle, auth_temp, tx_temp, recovery_temp = (
        readiness_contract._normal_source()
    )
    try:
        readiness_policy = readiness_contract._policy(post_source)
        source = readiness_contract._evaluate(post_source, readiness_policy)
        assert source.evaluation_authenticated is True
        assert source.staging_complete is True
        assert source.next_boundary_ready is True

        config = _config(source)
        receipt = _plan(source, config)
        assert receipt.plan_authenticated is True
        assert receipt.staging_completion_readiness_sha256 == source.sha256
        assert receipt.post_staging_success_status_attestation_sha256 == (
            source.post_staging_success_status_attestation_sha256
        )
        assert receipt.staging_runtime_build_identity_sha256 == (
            source.staging_runtime_build_identity_sha256
        )
        assert receipt.repository == source.repository
        assert receipt.repository_id == source.repository_id
        assert receipt.production_deployment_environment == "production"
        assert receipt.production_deployment_ref == source.merge_commit_sha
        assert receipt.production_deployment_task == "deploy"
        assert receipt.production_deployment_identity == (
            f"modelrig-production-{source.merge_commit_sha}"
        )
        assert receipt.source_staging_deployment_id == source.deployment_id
        assert receipt.source_success_status_id == source.success_deployment_status_id
        assert receipt.max_readiness_age_seconds == 60
        assert receipt.readiness_age_seconds == 20
        body = json.loads(receipt.production_deployment_body)
        assert body["ref"] == source.merge_commit_sha
        assert body["task"] == "deploy"
        assert body["auto_merge"] is False
        assert body["required_contexts"] == []
        assert body["environment"] == "production"
        assert body["transient_environment"] is False
        assert body["production_environment"] is True
        assert body["payload"] == json.loads(receipt.production_deployment_payload)
        _assert_inert(receipt)

        duplicate = _plan(source, config)
        assert duplicate.to_dict() == receipt.to_dict()
        assert duplicate.production_deployment_intent_sha256 == (
            receipt.production_deployment_intent_sha256
        )

        serialized = (
            production_plan.PilotExactTaskProductionDeploymentPlanReceipt.from_mapping(
                receipt.to_dict()
            )
        )
        assert serialized == receipt
        assert serialized.plan_authenticated is False

        serialized_source = (
            readiness_contract.readiness.PilotExactTaskStagingCompletionReadinessReceipt.from_mapping(
                source.to_dict()
            )
        )
        assert serialized_source.evaluation_authenticated is False
        _reject(lambda: _plan(serialized_source, config))

        _reject(lambda: _plan(source, config, now="2026-09-15T09:53:11Z"))
        strict_config = _config(source, max_readiness_age_seconds=10)
        _reject(lambda: _plan(source, strict_config))
        _reject(lambda: _plan(source, config, now="2026-09-15T09:52:09Z"))
        _reject(lambda: _plan(source, config, digest="a" * 64))

        wrong_repo = production_plan.PilotExactTaskProductionDeploymentPlanConfig(
            repository="other/ModelRig",
            repository_id=source.repository_id,
        )
        _reject(lambda: _plan(source, wrong_repo))

        for overrides in (
            {"deployment_environment": "staging"},
            {"deployment_task": "production"},
            {"deployment_ref_mode": "branch-head-v1"},
            {"auto_merge": True},
            {"required_contexts": ("ci",)},
            {"transient_environment": True},
            {"production_environment": False},
            {"max_readiness_age_seconds": 61},
            {"max_readiness_age_seconds": 0},
        ):
            values = {
                "repository": source.repository,
                "repository_id": source.repository_id,
            }
            values.update(overrides)
            _reject(
                lambda values=values: (
                    production_plan.PilotExactTaskProductionDeploymentPlanConfig(
                        **values
                    )
                )
            )

        parsed = production_plan._parse_config(
            config.canonical_json().encode("utf-8")
        )
        assert parsed == config
        _reject(
            lambda: production_plan._parse_config(
                (config.canonical_json() + "\n").encode("utf-8")
            )
        )

        for field, value in (
            ("staging_completion_readiness_authenticated", False),
            ("production_plan_config_host_pinned", False),
            ("readiness_fresh_verified", False),
            ("exact_merge_commit_bound", False),
            ("exact_runtime_build_identity_bound", False),
            ("exact_staging_success_bound", False),
            ("production_deployment_intent_materialized", False),
            ("production_deployment_planned", False),
            ("production_deployment_ready", False),
            ("production_promotion_authorized", True),
            ("production_deployment_authorized", True),
            ("production_activation_authorized", True),
            ("deployment_status_mutation_authorized", True),
            ("deployment_mutation_authorized", True),
            ("deploy_authorized", True),
            ("remote_write_authorized", True),
            ("release_authorized", True),
            ("merge_authorized", True),
            ("product_pilot_started", True),
            ("nonce_reusable", True),
            ("production_deployment_environment", "staging"),
            ("production_deployment_ref", "a" * 40),
            ("production_deployment_task", "other"),
            ("readiness_age_seconds", 61),
            ("production_deployment_body_sha256", "a" * 64),
            ("production_deployment_intent_sha256", "b" * 64),
        ):
            raw = receipt.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: (
                    production_plan.PilotExactTaskProductionDeploymentPlanReceipt.from_mapping(
                        raw
                    )
                )
            )
    finally:
        readiness_contract._cleanup_normal(
            bundle, auth_temp, tx_temp, recovery_temp
        )

    post_contract = readiness_contract.post_contract
    fixture = post_contract.recovery_contract._auth_fixture()
    recovery_temp, recovery_ledger = post_contract.recovery_contract._recovery_ledger(
        "rsi-production-plan-recovered-"
    )
    try:
        (
            _bundle,
            _plan_source,
            authorization,
            _auth_temp,
            auth_ledger,
            _tx_temp,
            tx_ledger,
        ) = fixture
        state, _ = post_contract.recovery_contract._inspect(
            authorization,
            auth_ledger,
            tx_ledger,
            post_contract.recovery_contract._Transport(authorization),
        )
        payload = post_contract.recovery_contract._payload(state)
        verifier, op_sig, review_sig = (
            post_contract.recovery_contract.deploy_auth_contract._dual_authority(
                payload,
                signed_at="2026-09-15T09:51:32Z",
            )
        )
        post_contract.recovery_contract._recover(
            payload,
            verifier,
            op_sig,
            review_sig,
            auth_ledger,
            tx_ledger,
            recovery_ledger,
            post_contract.recovery_contract._Transport(authorization),
        )
        post_success = post_contract._attest(
            authorization,
            tx_root=tx_ledger.root,
            recovery_root=recovery_ledger.root,
            auth_root=auth_ledger.root,
            transport=post_contract.recovery_contract._Transport(authorization),
        )
        readiness_source = readiness_contract._evaluate(
            post_success,
            readiness_contract._policy(post_success),
        )
        receipt = _plan(readiness_source, _config(readiness_source))
        assert receipt.source_completion_source == "recovery"
        assert receipt.source_completion_action == "finalize_existing_state"
        assert receipt.source_remote_write_performed is False
        _assert_inert(receipt)
    finally:
        recovery_temp.cleanup()
        post_contract.recovery_contract._cleanup(fixture)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(
        production_plan.PilotExactTaskProductionDeploymentPlanReceipt.__dataclass_fields__
    )
    assert set(schema["required"]) == fields
    assert set(schema["properties"]) == fields
    assert len(fields) == 59

    signature = inspect.signature(
        production_plan.plan_pilot_exact_task_production_deployment
    )
    assert list(signature.parameters) == ["staging_completion_readiness"]

    source_text = code_of(SOURCE)
    assert "urllib.request" not in source_text
    assert "subprocess" not in source_text
    for forbidden in (
        'method="POST"',
        "method='POST'",
        'method="PUT"',
        "method='PUT'",
        'method="PATCH"',
        "method='PATCH'",
        'method="DELETE"',
        "method='DELETE'",
    ):
        assert forbidden not in source_text
    assert "production_promotion_authorized: bool = False" in source_text
    assert "production_deployment_authorized: bool = False" in source_text
    assert "production_activation_authorized: bool = False" in source_text
    assert "remote_write_authorized: bool = False" in source_text


if __name__ == "__main__":
    run_contract()
