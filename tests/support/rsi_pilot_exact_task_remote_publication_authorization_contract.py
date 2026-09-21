"""Adversarial contract for ADR-DC-049 exact remote publication authorization."""
from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
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
    improvement_pilot_exact_task_remote_publication_authorization as publication_auth,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_remote_state_observation as remote_state,
)
from rsi_pilot_exact_task_post_commit_integration_evaluation_contract import (  # noqa: E402
    _evaluation_reader,
)
from rsi_pilot_exact_task_remote_state_observation_contract import (  # noqa: E402
    _Observer,
    _live_plan,
    _snapshot,
)

_LIVE_OBSERVATION_KEEPALIVES = {}


def _retain_plan(receipt, plan) -> None:
    key = id(receipt)

    def cleanup(_):
        _LIVE_OBSERVATION_KEEPALIVES.pop(key, None)

    _LIVE_OBSERVATION_KEEPALIVES[key] = (weakref.ref(receipt, cleanup), plan)


SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-remote-publication-authorization-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-049 unexpectedly accepted unsafe publication authority")


def _ledger(prefix: str):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, publication_auth._PilotExactTaskRemotePublicationAuthorizationLedger(root)


def _live_observation():
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
    assert calls
    assert receipt.observation_authenticated is True
    # ADR-DC-048 authenticates through a weak reference to ADR-DC-047.
    # Bind the plan lifetime to the observation without changing fixture shape.
    _retain_plan(receipt, plan)
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
        receipt,
        good,
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
        observation,
        good,
    ) = _live_observation()
    ledger_temp, ledger = _ledger("rsi-exact-task-remote-publication-auth-")
    try:
        observer = _Observer((good, dict(good), dict(good), dict(good)))
        calls, reader = _evaluation_reader(
            workspace=fixture["workspace"],
            local_ref=local_transaction.local_head_ref,
            base_sha=identity.base_sha,
            predicted_commit_sha=identity.predicted_commit_sha,
            root_tree_sha=identity.root_tree_sha,
            commit_payload=commit_payload,
            index_payload=index_payload,
        )
        times = iter(("2026-09-15T06:41:30Z", "2026-09-15T06:41:31Z"))
        with patch.object(fixture["git_runner"], "run", side_effect=reader):
            receipt = publication_auth._authorize_verified_pilot_exact_task_remote_publication(
                remote_state_observation=observation,
                ledger=ledger,
                observer=observer,
                now_provider=lambda: next(times),
            )

        assert len(observer.calls) == 4
        assert len(calls) == 48
        assert receipt.authorization_authenticated is True
        assert receipt.authorization_key_sha256 == plan.execution_nonce_sha256
        assert receipt.remote_state_observation_sha256 == observation.sha256
        assert receipt.remote_publication_plan_sha256 == plan.sha256
        assert receipt.integration_readiness_sha256 == ready.sha256
        assert receipt.remote_target_config_sha256 == plan.remote_target_config_sha256
        assert receipt.remote_repository_identity_sha256 == plan.remote_repository_identity_sha256
        assert receipt.pr_intent_sha256 == plan.pr_intent_sha256
        assert receipt.remote_observation_sha256 == observation.remote_observation_sha256
        assert receipt.fresh_remote_observation_sha256 == observation.remote_observation_sha256
        assert receipt.execution_nonce_sha256 == plan.execution_nonce_sha256
        assert receipt.development_task_sha256 == plan.development_task_sha256
        assert receipt.candidate_patch_sha256 == plan.candidate_patch_sha256
        assert receipt.task_id == task.task_id
        assert receipt.repository == task.repository
        assert receipt.repository_id == plan.repository_id
        assert receipt.provider == "github"
        assert receipt.host == "github.com"
        assert receipt.remote_name == "origin"
        assert receipt.base_branch == "main"
        assert receipt.head_branch == plan.head_branch
        assert receipt.exact_task_base_sha == task.base_sha
        assert receipt.predicted_commit_sha == identity.predicted_commit_sha
        assert receipt.host_replay_guard_committed is True
        assert receipt.remote_state_observation_authenticated is True
        assert receipt.publication_lane_clear is True
        assert receipt.fresh_local_commit_revalidated is True
        assert receipt.fresh_remote_state_revalidated is True
        assert receipt.remote_publication_authority_reserved is True
        assert receipt.one_shot_remote_publication_required is True
        assert receipt.exact_remote_branch_creation_authorized is True
        assert receipt.exact_commit_push_authorized is True
        assert receipt.exact_draft_pr_creation_authorized is True
        assert receipt.remote_write_authorized is True
        assert receipt.push_authorized is True
        assert receipt.pr_mutation_authorized is True
        assert receipt.remote_branch_created is False
        assert receipt.exact_commit_pushed is False
        assert receipt.draft_pr_created is False
        assert receipt.merge_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.product_pilot_started is False

        reloaded = publication_auth.PilotExactTaskRemotePublicationAuthorizationReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.authorization_authenticated is False

        for field, value in (
            ("remote_publication_authority_reserved", False),
            ("one_shot_remote_publication_required", False),
            ("exact_remote_branch_creation_authorized", False),
            ("exact_commit_push_authorized", False),
            ("exact_draft_pr_creation_authorized", False),
            ("remote_write_authorized", False),
            ("push_authorized", False),
            ("pr_mutation_authorized", False),
            ("remote_branch_created", True),
            ("exact_commit_pushed", True),
            ("draft_pr_created", True),
            ("merge_authorized", True),
            ("release_authorized", True),
            ("deploy_authorized", True),
            ("production_activation_authorized", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    publication_auth.PilotExactTaskRemotePublicationAuthorizationReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        reloaded_observation = remote_state.PilotExactTaskRemoteStateObservationReceipt.from_mapping(
            observation.to_dict()
        )
        assert reloaded_observation.observation_authenticated is False
        other_temp, other_ledger = _ledger("rsi-exact-task-remote-publication-reloaded-")
        try:
            _reject(
                lambda: publication_auth._authorize_verified_pilot_exact_task_remote_publication(
                    remote_state_observation=reloaded_observation,
                    ledger=other_ledger,
                    observer=_Observer((good, good, good, good)),
                    now_provider=lambda: "2026-09-15T06:41:40Z",
                )
            )
        finally:
            other_temp.cleanup()

        final, pending, lock = ledger._paths(plan.execution_nonce_sha256)
        assert final.is_file()
        assert lock.is_file()
        assert not pending.exists()
        _reject(lambda: ledger.acquire(observation=observation, plan=plan))

        drift_temp, drift_ledger = _ledger("rsi-exact-task-remote-publication-drift-")
        try:
            drift_observer = _Observer(
                (
                    good,
                    dict(good),
                    _snapshot(plan, head_exists=True),
                    _snapshot(plan, head_exists=True),
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
            )
            drift_times = iter(("2026-09-15T06:41:50Z", "2026-09-15T06:41:51Z"))
            with patch.object(fixture["git_runner"], "run", side_effect=drift_reader):
                _reject(
                    lambda: publication_auth._authorize_verified_pilot_exact_task_remote_publication(
                        remote_state_observation=observation,
                        ledger=drift_ledger,
                        observer=drift_observer,
                        now_provider=lambda: next(drift_times),
                    )
                )
            drift_final, drift_pending, drift_lock = drift_ledger._paths(
                plan.execution_nonce_sha256
            )
            assert drift_lock.is_file()
            assert not drift_final.exists()
            assert not drift_pending.exists()
            _reject(lambda: drift_ledger.acquire(observation=observation, plan=plan))
            assert drift_calls
        finally:
            drift_temp.cleanup()

        rollback_temp, rollback_ledger = _ledger("rsi-exact-task-remote-publication-clock-")
        try:
            rollback_observer = _Observer((good, good))
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
                    lambda: publication_auth._authorize_verified_pilot_exact_task_remote_publication(
                        remote_state_observation=observation,
                        ledger=rollback_ledger,
                        observer=rollback_observer,
                        now_provider=lambda: "2026-09-15T06:41:19Z",
                    )
                )
            _final, _pending, rollback_lock = rollback_ledger._paths(
                plan.execution_nonce_sha256
            )
            assert not rollback_lock.exists()
            assert rollback_calls
        finally:
            rollback_temp.cleanup()

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert schema["properties"]["remote_publication_authority_reserved"]["const"] is True
        assert schema["properties"]["push_authorized"]["const"] is True
        assert schema["properties"]["pr_mutation_authorized"]["const"] is True
        assert schema["properties"]["remote_branch_created"]["const"] is False
        assert schema["properties"]["draft_pr_created"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            publication_auth.authorize_pilot_exact_task_remote_publication
        ).parameters
        assert tuple(public_parameters) == ("remote_state_observation",)

        source = inspect.getsource(publication_auth)
        assert "create_once_file" in source
        assert "subprocess" not in source
        assert "shell=True" not in source
        assert 'method="POST"' not in source
        assert 'method="PATCH"' not in source
        assert 'method="DELETE"' not in source
        assert "requests." not in source
        assert "httpx." not in source
        assert '("push",' not in source
        assert '("update-ref",' not in source
    finally:
        ledger_temp.cleanup()
        transaction_temp.cleanup()
        auth_temp.cleanup()
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
