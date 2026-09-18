"""Adversarial contract for ADR-DC-047 exact inert remote publication planning."""
from __future__ import annotations

import inspect
import json
import os
import sys
import weakref
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_integration_readiness as readiness,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_remote_publication_plan as publication_plan,
)
from rsi_pilot_exact_task_integration_readiness_contract import (  # noqa: E402
    KEY_ID,
    REVIEWER,
    REVIEWER_SYSTEM,
    _assessments,
    _live_evaluation,
    _review_authority,
    _signature,
)
from rsi_pilot_exact_task_post_commit_integration_evaluation_contract import (  # noqa: E402
    _evaluation_reader,
)

_LIVE_READINESS_KEEPALIVES = {}


def _retain_mechanical(ready, mechanical) -> None:
    key = id(ready)

    def cleanup(_):
        _LIVE_READINESS_KEEPALIVES.pop(key, None)

    _LIVE_READINESS_KEEPALIVES[key] = (weakref.ref(ready, cleanup), mechanical)


SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-remote-publication-plan-v1.schema.json"
)
REPOSITORY_ID = "1287914122"


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-047 unexpectedly accepted unsafe publication intent")


def _live_readiness():
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        auth_temp,
        transaction_temp,
        evaluation,
        execution_receipt,
        execution_plan,
        local_plan,
        identity,
        authorization,
        local_transaction,
        mechanical,
        task,
        fixture,
        index_payload,
        commit_payload,
    ) = _live_evaluation()
    private_key, verifier, keyring_sha256 = _review_authority()
    reviewed_at = "2026-09-15T06:41:00Z"
    semantic_payload = readiness.build_pilot_exact_task_semantic_acceptance_payload(
        mechanical,
        _assessments(task),
        REVIEWER,
        REVIEWER_SYSTEM,
        KEY_ID,
        reviewed_at,
    )
    signature = _signature(private_key, semantic_payload, signed_at=reviewed_at)
    calls, reader = _evaluation_reader(
        workspace=fixture["workspace"],
        local_ref=local_transaction.local_head_ref,
        base_sha=identity.base_sha,
        predicted_commit_sha=identity.predicted_commit_sha,
        root_tree_sha=identity.root_tree_sha,
        commit_payload=commit_payload,
        index_payload=index_payload,
    )
    with patch.object(fixture["git_runner"], "run", side_effect=reader):
        ready = readiness._evaluate_verified_pilot_exact_task_integration_readiness(
            post_commit_integration_evaluation=mechanical,
            semantic_acceptance_payload=semantic_payload,
            signature=signature,
            authority_verifier=verifier,
            trusted_reviewer_keyring_sha256=keyring_sha256,
            now_provider=lambda: "2026-09-15T06:41:01Z",
        )
    assert calls
    assert ready.readiness_authenticated is True
    _retain_mechanical(ready, mechanical)
    return (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        auth_temp,
        transaction_temp,
        identity,
        local_transaction,
        mechanical,
        ready,
        task,
        fixture,
        index_payload,
        commit_payload,
    )


def _target(task):
    target = publication_plan.PilotExactTaskRemotePublicationTarget(
        repository=task.repository,
        repository_id=REPOSITORY_ID,
    )
    payload = target.canonical_json().encode("utf-8")
    parsed, digest = publication_plan._parse_target_payload(payload)
    assert parsed == target
    assert digest == target.sha256
    return target, digest


def run_contract() -> None:
    if os.name == "nt":
        return

    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        auth_temp,
        transaction_temp,
        identity,
        local_transaction,
        mechanical,
        ready,
        task,
        fixture,
        index_payload,
        commit_payload,
    ) = _live_readiness()
    try:
        target, target_digest = _target(task)
        calls, reader = _evaluation_reader(
            workspace=fixture["workspace"],
            local_ref=local_transaction.local_head_ref,
            base_sha=identity.base_sha,
            predicted_commit_sha=identity.predicted_commit_sha,
            root_tree_sha=identity.root_tree_sha,
            commit_payload=commit_payload,
            index_payload=index_payload,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=reader):
            plan = publication_plan._materialize_verified_pilot_exact_task_remote_publication_plan(
                integration_readiness=ready,
                target=target,
                target_config_sha256=target_digest,
                now_provider=lambda: "2026-09-15T06:41:10Z",
            )

        assert len(calls) == 24
        assert plan.plan_authenticated is True
        assert plan.integration_readiness_sha256 == ready.sha256
        assert plan.post_commit_integration_evaluation_sha256 == mechanical.sha256
        assert plan.local_commit_transaction_sha256 == local_transaction.sha256
        assert plan.local_commit_object_identity_sha256 == identity.sha256
        assert plan.execution_nonce_sha256 == identity.execution_nonce_sha256
        assert plan.development_task_sha256 == identity.development_task_sha256
        assert plan.candidate_patch_sha256 == identity.candidate_patch_sha256
        assert plan.remote_target_config_sha256 == target.sha256
        assert plan.task_id == task.task_id
        assert plan.repository == task.repository
        assert plan.repository_id == REPOSITORY_ID
        assert plan.provider == "github"
        assert plan.host == "github.com"
        assert plan.remote_name == "origin"
        assert plan.base_branch == "main"
        assert plan.head_branch == publication_plan._expected_head_branch(
            task_id=task.task_id,
            predicted_commit_sha=identity.predicted_commit_sha,
            prefix="modelrig-rsi",
        )
        assert plan.base_sha == task.base_sha
        assert plan.predicted_commit_sha == identity.predicted_commit_sha
        assert plan.root_tree_sha == identity.root_tree_sha
        assert plan.draft is True
        assert plan.maintainer_can_modify is False
        assert plan.integration_readiness_authenticated is True
        assert plan.integration_ready is True
        assert plan.exact_local_commit_revalidated is True
        assert plan.remote_target_host_pinned is True
        assert plan.remote_publication_plan_materialized is True
        assert plan.remote_branch_creation_planned is True
        assert plan.exact_commit_push_planned is True
        assert plan.draft_pr_creation_planned is True
        assert plan.remote_state_observed is False
        assert plan.remote_write_authorized is False
        assert plan.push_authorized is False
        assert plan.pr_mutation_authorized is False
        assert plan.merge_authorized is False
        assert plan.release_authorized is False
        assert plan.deploy_authorized is False
        assert plan.production_activation_authorized is False
        assert plan.product_pilot_started is False
        assert plan.pr_title.startswith(f"draft(devcontrol): {task.task_id}")
        assert identity.predicted_commit_sha in plan.pr_body
        assert ready.sha256 in plan.pr_body

        reloaded = publication_plan.PilotExactTaskRemotePublicationPlan.from_mapping(
            plan.to_dict()
        )
        assert reloaded == plan
        assert reloaded.sha256 == plan.sha256
        assert reloaded.plan_authenticated is False

        for field, value in (
            ("remote_publication_plan_materialized", False),
            ("remote_state_observed", True),
            ("remote_write_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("merge_authorized", True),
            ("production_activation_authorized", True),
            ("maintainer_can_modify", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    publication_plan.PilotExactTaskRemotePublicationPlan.from_mapping(
                        {**plan.to_dict(), field: value}
                    )
                )
            )

        _reject(
            lambda: publication_plan.PilotExactTaskRemotePublicationPlan.from_mapping(
                {**plan.to_dict(), "pr_title": "caller-controlled title"}
            )
        )
        _reject(
            lambda: publication_plan.PilotExactTaskRemotePublicationPlan.from_mapping(
                {**plan.to_dict(), "head_branch": "caller/branch"}
            )
        )

        reloaded_ready = readiness.PilotExactTaskIntegrationReadinessReceipt.from_mapping(
            ready.to_dict()
        )
        assert reloaded_ready.readiness_authenticated is False
        _reject(
            lambda: publication_plan._materialize_verified_pilot_exact_task_remote_publication_plan(
                integration_readiness=reloaded_ready,
                target=target,
                target_config_sha256=target_digest,
                now_provider=lambda: "2026-09-15T06:41:11Z",
            )
        )

        wrong_target = publication_plan.PilotExactTaskRemotePublicationTarget(
            repository="Other/Repository",
            repository_id=REPOSITORY_ID,
        )
        _reject(
            lambda: publication_plan._materialize_verified_pilot_exact_task_remote_publication_plan(
                integration_readiness=ready,
                target=wrong_target,
                target_config_sha256=wrong_target.sha256,
                now_provider=lambda: "2026-09-15T06:41:11Z",
            )
        )
        _reject(
            lambda: publication_plan._materialize_verified_pilot_exact_task_remote_publication_plan(
                integration_readiness=ready,
                target=target,
                target_config_sha256="a" * 64,
                now_provider=lambda: "2026-09-15T06:41:11Z",
            )
        )

        drift_calls, drift_reader = _evaluation_reader(
            workspace=fixture["workspace"],
            local_ref=local_transaction.local_head_ref,
            base_sha=identity.base_sha,
            predicted_commit_sha=identity.predicted_commit_sha,
            root_tree_sha=identity.root_tree_sha,
            commit_payload=commit_payload,
            index_payload=index_payload,
            drift_between_observations=True,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=drift_reader):
            _reject(
                lambda: publication_plan._materialize_verified_pilot_exact_task_remote_publication_plan(
                    integration_readiness=ready,
                    target=target,
                    target_config_sha256=target_digest,
                    now_provider=lambda: "2026-09-15T06:41:12Z",
                )
            )
        assert drift_calls

        rollback_calls, rollback_reader = _evaluation_reader(
            workspace=fixture["workspace"],
            local_ref=local_transaction.local_head_ref,
            base_sha=identity.base_sha,
            predicted_commit_sha=identity.predicted_commit_sha,
            root_tree_sha=identity.root_tree_sha,
            commit_payload=commit_payload,
            index_payload=index_payload,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=rollback_reader):
            _reject(
                lambda: publication_plan._materialize_verified_pilot_exact_task_remote_publication_plan(
                    integration_readiness=ready,
                    target=target,
                    target_config_sha256=target_digest,
                    now_provider=lambda: "2026-09-15T06:41:00Z",
                )
            )
        assert rollback_calls

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(plan.to_dict())
        assert set(schema["required"]) == set(plan.to_dict())
        assert props["integration_ready"]["const"] is True
        assert props["remote_state_observed"]["const"] is False
        assert props["remote_write_authorized"]["const"] is False
        assert props["push_authorized"]["const"] is False
        assert props["pr_mutation_authorized"]["const"] is False
        assert props["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            publication_plan.materialize_pilot_exact_task_remote_publication_plan
        ).parameters
        assert tuple(public_parameters) == ("integration_readiness",)

        source = inspect.getsource(publication_plan)
        assert "subprocess" not in source
        assert "shell=True" not in source
        assert "Ed25519PrivateKey" not in source
        assert "requests" not in source
        assert "httpx" not in source
        assert '("push",' not in source
        assert '("fetch",' not in source
        assert '("remote",' not in source
        assert '("update-ref",' not in source
        assert '("commit",' not in source
        assert "create_pull_request" not in source
        assert "update_pull_request" not in source
    finally:
        transaction_temp.cleanup()
        auth_temp.cleanup()
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
