"""Adversarial contract for ADR-DC-048 exact read-only remote-state observation."""
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
    improvement_pilot_exact_task_remote_publication_plan as publication_plan,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_remote_state_observation as remote_state,
)
from rsi_pilot_exact_task_post_commit_integration_evaluation_contract import (  # noqa: E402
    _evaluation_reader,
)
from rsi_pilot_exact_task_remote_publication_plan_contract import (  # noqa: E402
    _live_readiness,
    _target,
)

_LIVE_PLAN_KEEPALIVES = {}


def _retain_ready(plan, ready) -> None:
    key = id(plan)

    def cleanup(_):
        _LIVE_PLAN_KEEPALIVES.pop(key, None)

    _LIVE_PLAN_KEEPALIVES[key] = (weakref.ref(plan, cleanup), ready)


SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-remote-state-observation-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-048 unexpectedly accepted unsafe remote state")


class _Observer:
    def __init__(self, values):
        self.values = list(values)
        self.calls = []

    def observe(self, plan):
        self.calls.append(plan.sha256)
        if not self.values:
            raise AssertionError("unexpected extra remote observation")
        return self.values.pop(0)


def _snapshot(plan, *, base_sha=None, head_exists=False, matching_pr_count=0):
    return {
        "repository_id": plan.repository_id,
        "repository": plan.repository,
        "default_branch": plan.base_branch,
        "base_sha": base_sha or plan.base_sha,
        "head_exists": head_exists,
        "matching_pr_count": matching_pr_count,
    }


def _live_plan():
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
    assert calls
    assert plan.plan_authenticated is True
    _retain_ready(plan, ready)
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
        plan,
    )


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
        plan,
    ) = _live_plan()
    try:
        good = _snapshot(plan)
        observer = _Observer((good, dict(good)))
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
            receipt = remote_state._observe_verified_pilot_exact_task_remote_state(
                remote_publication_plan=plan,
                observer=observer,
                now_provider=lambda: "2026-09-15T06:41:20Z",
            )

        assert len(observer.calls) == 2
        assert len(calls) == 48
        assert receipt.observation_authenticated is True
        assert receipt.remote_publication_plan_sha256 == plan.sha256
        assert receipt.integration_readiness_sha256 == ready.sha256
        assert receipt.remote_target_config_sha256 == plan.remote_target_config_sha256
        assert receipt.remote_repository_identity_sha256 == plan.remote_repository_identity_sha256
        assert receipt.pr_intent_sha256 == plan.pr_intent_sha256
        assert receipt.task_id == task.task_id
        assert receipt.repository == task.repository
        assert receipt.repository_id == plan.repository_id
        assert receipt.provider == "github"
        assert receipt.host == "github.com"
        assert receipt.base_branch == "main"
        assert receipt.head_branch == plan.head_branch
        assert receipt.exact_task_base_sha == task.base_sha
        assert receipt.observed_base_sha == task.base_sha
        assert receipt.predicted_commit_sha == identity.predicted_commit_sha
        assert receipt.remote_publication_plan_authenticated is True
        assert receipt.remote_repository_identity_verified is True
        assert receipt.remote_default_branch_verified is True
        assert receipt.base_branch_observed is True
        assert receipt.base_branch_matches_exact_task_base is True
        assert receipt.head_branch_observed is True
        assert receipt.head_branch_exists is False
        assert receipt.head_branch_absent is True
        assert receipt.matching_prs_observed is True
        assert receipt.matching_pr_count == 0
        assert receipt.matching_pr_absent is True
        assert receipt.double_observation_matched is True
        assert receipt.remote_state_observed is True
        assert receipt.publication_lane_clear is True
        assert receipt.integration_ready is True
        assert receipt.remote_publication_plan_materialized is True
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False

        expected_observation_sha = remote_state._remote_observation_sha256(
            plan=plan,
            observation=remote_state._validate_observation(plan, good),
        )
        assert receipt.remote_observation_sha256 == expected_observation_sha

        reloaded = remote_state.PilotExactTaskRemoteStateObservationReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.observation_authenticated is False

        for field, value in (
            ("base_branch_matches_exact_task_base", False),
            ("head_branch_exists", True),
            ("head_branch_absent", False),
            ("matching_pr_count", 1),
            ("matching_pr_absent", False),
            ("publication_lane_clear", False),
            ("remote_write_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("merge_authorized", True),
            ("production_activation_authorized", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    remote_state.PilotExactTaskRemoteStateObservationReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        reloaded_plan = publication_plan.PilotExactTaskRemotePublicationPlan.from_mapping(
            plan.to_dict()
        )
        assert reloaded_plan.plan_authenticated is False
        _reject(
            lambda: remote_state._observe_verified_pilot_exact_task_remote_state(
                remote_publication_plan=reloaded_plan,
                observer=_Observer((good, good)),
                now_provider=lambda: "2026-09-15T06:41:21Z",
            )
        )

        bad_cases = (
            (_snapshot(plan, base_sha="f" * 40), _snapshot(plan, base_sha="f" * 40)),
            (_snapshot(plan, head_exists=True), _snapshot(plan, head_exists=True)),
            (_snapshot(plan, matching_pr_count=1), _snapshot(plan, matching_pr_count=1)),
            (_snapshot(plan), _snapshot(plan, head_exists=True)),
        )
        for first, second in bad_cases:
            bad_observer = _Observer((first, second))
            bad_calls, bad_reader = _evaluation_reader(
                workspace=fixture["workspace"],
                local_ref=local_transaction.local_head_ref,
                base_sha=identity.base_sha,
                predicted_commit_sha=identity.predicted_commit_sha,
                root_tree_sha=identity.root_tree_sha,
                commit_payload=commit_payload,
                index_payload=index_payload,
            )
            with patch.object(fixture["git_runner"], "run", side_effect=bad_reader):
                _reject(
                    lambda bad_observer=bad_observer: remote_state._observe_verified_pilot_exact_task_remote_state(
                        remote_publication_plan=plan,
                        observer=bad_observer,
                        now_provider=lambda: "2026-09-15T06:41:22Z",
                    )
                )
            assert bad_calls

        rollback_observer = _Observer((good, dict(good)))
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
                lambda: remote_state._observe_verified_pilot_exact_task_remote_state(
                    remote_publication_plan=plan,
                    observer=rollback_observer,
                    now_provider=lambda: "2026-09-15T06:41:09Z",
                )
            )
        assert rollback_calls

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert schema["properties"]["remote_state_observed"]["const"] is True
        assert schema["properties"]["publication_lane_clear"]["const"] is True
        assert schema["properties"]["head_branch_exists"]["const"] is False
        assert schema["properties"]["matching_pr_count"]["const"] == 0
        assert schema["properties"]["push_authorized"]["const"] is False
        assert schema["properties"]["pr_mutation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            remote_state.observe_pilot_exact_task_remote_state
        ).parameters
        assert tuple(public_parameters) == ("remote_publication_plan",)

        source = inspect.getsource(remote_state)
        assert "urllib.request" in source
        assert 'method="GET"' in source
        assert '"Authorization"' not in source
        assert "subprocess" not in source
        assert "shell=True" not in source
        assert '("push",' not in source
        assert '("fetch",' not in source
        assert '("update-ref",' not in source
        assert "requests." not in source
        assert "httpx." not in source
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
