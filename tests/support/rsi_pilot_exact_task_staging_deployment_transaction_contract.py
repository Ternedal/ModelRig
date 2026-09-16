"""Adversarial contract for ADR-DC-074 exact staging Deployment transaction."""
from __future__ import annotations

import inspect
import json
import os
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
from source_code import code_of  # noqa: E402

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_deployment_authorization as deploy_auth,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_deployment_transaction as deploy_tx,
)
import rsi_pilot_exact_task_staging_deployment_authorization_contract as auth_contract  # noqa: E402
import rsi_pilot_exact_task_staging_deployment_state_observation_contract as state_contract  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-staging-deployment-transaction-v1.schema.json"
SOURCE = ROOT / "devcontrol" / "src" / "kaliv_dev_control" / "improvement_pilot_exact_task_staging_deployment_transaction.py"


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-074 unexpectedly accepted unsafe deployment transaction")


def _transaction_ledger(prefix: str):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, deploy_tx._PilotExactTaskStagingDeploymentTransactionLedger(root)


class _Writer:
    def __init__(
        self,
        transport,
        readiness,
        *,
        deployment_id=4242,
        node_hash="e" * 64,
        observed_node_hash=None,
        fail=False,
    ):
        self.transport = transport
        self.credential_config_sha256 = readiness.publisher_credential_config_sha256
        self.credential_path_sha256 = readiness.publisher_credential_path_sha256
        self.deployment_id = deployment_id
        self.node_hash = node_hash
        self.observed_node_hash = node_hash if observed_node_hash is None else observed_node_hash
        self.fail = fail
        self.calls = 0

    def create(self, plan):
        self.calls += 1
        if self.fail:
            raise deploy_tx.PilotExactTaskStagingDeploymentTransactionError("synthetic write failure")
        self.transport.deployment_id = self.deployment_id
        self.transport.node_hash = self.observed_node_hash
        self.transport.state_class = "exact-existing"
        return self.deployment_id, self.node_hash


def _live_authorization():
    items, readiness, plan, observation = auth_contract._fixture()
    auth_temp, auth_ledger = auth_contract._ledger("rsi-staging-deploy-auth-for-tx-")
    config = auth_contract._config(observation)
    payload = auth_contract._payload(observation, config)
    verifier, op_sig, review_sig = auth_contract._dual_authority(payload)
    receipt = auth_contract._authorize(
        observation,
        config,
        payload,
        verifier,
        op_sig,
        review_sig,
        auth_ledger,
        state_contract._Transport(plan, readiness),
        now="2026-09-15T09:49:30Z",
    )
    assert receipt.authorization_authenticated is True
    # ADR-DC-073 deliberately binds live provenance through a weakref to the
    # exact ADR-DC-072 observation. Return it so every transaction fixture keeps
    # that authority chain alive for the duration of the test.
    return items, readiness, plan, observation, receipt, auth_temp


def _execute(receipt, ledger, observer, writer, *, now="2026-09-15T09:49:40Z"):
    return deploy_tx._execute_verified_pilot_exact_task_staging_deployment(
        deployment_authorization=receipt,
        ledger=ledger,
        observer=observer,
        writer=writer,
        now_provider=lambda: now,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    items, readiness, plan, observation, authorization, auth_temp = _live_authorization()
    tx_temp, ledger = _transaction_ledger("rsi-staging-deploy-tx-")
    try:
        observer = state_contract._Transport(
            plan,
            readiness,
            state_class="clear",
            deployment_id=4242,
            node_hash="e" * 64,
        )
        writer = _Writer(observer, readiness)
        receipt = _execute(authorization, ledger, observer, writer)

        assert observation.observation_authenticated is True
        assert observer.calls == 6
        assert writer.calls == 1
        assert receipt.transaction_authenticated is True
        assert receipt.deployment_authorization_sha256 == authorization.sha256
        assert receipt.staging_deployment_plan_sha256 == plan.sha256
        assert receipt.deployment_intent_sha256 == plan.deployment_intent_sha256
        assert receipt.deployment_transaction_key_sha256 == authorization.execution_nonce_sha256
        assert receipt.deployment_id == 4242
        assert receipt.deployment_node_id_sha256 == "e" * 64
        assert receipt.deployment_environment == "staging"
        assert receipt.deployment_ref == plan.deployment_ref
        assert receipt.deployment_task == "deploy"
        assert receipt.merge_commit_sha == plan.merge_commit_sha
        assert receipt.deployment_created is True
        assert receipt.exact_post_write_state_verified is True
        assert receipt.deployment_status_mutation_authorized is False
        assert receipt.deployment_mutation_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False

        reloaded = deploy_tx.PilotExactTaskStagingDeploymentTransactionReceipt.from_mapping(receipt.to_dict())
        assert reloaded == receipt
        assert reloaded.transaction_authenticated is False

        replay_writer = _Writer(state_contract._Transport(plan, readiness), readiness)
        _reject(lambda: _execute(authorization, ledger, replay_writer.transport, replay_writer))
        assert replay_writer.calls == 0

        stale = deploy_auth.PilotExactTaskStagingDeploymentAuthorizationReceipt.from_mapping(
            authorization.to_dict()
        )
        assert stale.authorization_authenticated is False
        stale_temp, stale_ledger = _transaction_ledger("rsi-staging-deploy-tx-stale-")
        try:
            stale_observer = state_contract._Transport(plan, readiness)
            stale_writer = _Writer(stale_observer, readiness)
            _reject(lambda: _execute(stale, stale_ledger, stale_observer, stale_writer))
            assert stale_writer.calls == 0
        finally:
            stale_temp.cleanup()

        cred_temp, cred_ledger = _transaction_ledger("rsi-staging-deploy-tx-cred-")
        try:
            cred_observer = state_contract._Transport(plan, readiness)
            cred_writer = _Writer(cred_observer, readiness)
            cred_writer.credential_path_sha256 = "8" * 64
            _reject(lambda: _execute(authorization, cred_ledger, cred_observer, cred_writer))
            assert cred_writer.calls == 0
        finally:
            cred_temp.cleanup()

        race_items, race_readiness, race_plan, race_observation, race_authorization, race_auth_temp = _live_authorization()
        race_temp, race_ledger = _transaction_ledger("rsi-staging-deploy-tx-race-")
        try:
            assert race_observation.observation_authenticated is True
            race_observer = state_contract._Transport(
                race_plan,
                race_readiness,
                scripted=["clear", "clear", "clear", "exact-existing"],
            )
            race_writer = _Writer(race_observer, race_readiness)
            _reject(lambda: _execute(race_authorization, race_ledger, race_observer, race_writer))
            final_path, lock_path = race_ledger._paths(race_authorization.execution_nonce_sha256)
            assert lock_path.exists()
            assert not final_path.exists()
            assert race_writer.calls == 0
        finally:
            race_temp.cleanup()
            race_auth_temp.cleanup()
            state_contract.plan_contract.ready_contract._cleanup_source(race_items)

        fail_items, fail_readiness, fail_plan, fail_observation, fail_authorization, fail_auth_temp = _live_authorization()
        fail_temp, fail_ledger = _transaction_ledger("rsi-staging-deploy-tx-write-fail-")
        try:
            assert fail_observation.observation_authenticated is True
            fail_observer = state_contract._Transport(fail_plan, fail_readiness)
            fail_writer = _Writer(fail_observer, fail_readiness, fail=True)
            _reject(lambda: _execute(fail_authorization, fail_ledger, fail_observer, fail_writer))
            final_path, lock_path = fail_ledger._paths(fail_authorization.execution_nonce_sha256)
            assert lock_path.exists()
            assert not final_path.exists()
            assert fail_writer.calls == 1
        finally:
            fail_temp.cleanup()
            fail_auth_temp.cleanup()
            state_contract.plan_contract.ready_contract._cleanup_source(fail_items)

        drift_items, drift_readiness, drift_plan, drift_observation, drift_authorization, drift_auth_temp = _live_authorization()
        drift_temp, drift_ledger = _transaction_ledger("rsi-staging-deploy-tx-post-write-drift-")
        try:
            assert drift_observation.observation_authenticated is True
            drift_observer = state_contract._Transport(drift_plan, drift_readiness, node_hash="d" * 64)
            drift_writer = _Writer(
                drift_observer,
                drift_readiness,
                node_hash="e" * 64,
                observed_node_hash="d" * 64,
            )
            _reject(lambda: _execute(drift_authorization, drift_ledger, drift_observer, drift_writer))
            final_path, lock_path = drift_ledger._paths(drift_authorization.execution_nonce_sha256)
            assert lock_path.exists()
            assert not final_path.exists()
            assert drift_writer.calls == 1
        finally:
            drift_temp.cleanup()
            drift_auth_temp.cleanup()
            state_contract.plan_contract.ready_contract._cleanup_source(drift_items)

        expired_items, expired_readiness, expired_plan, expired_observation, expired_authorization, expired_auth_temp = _live_authorization()
        expired_temp, expired_ledger = _transaction_ledger("rsi-staging-deploy-tx-expired-")
        try:
            assert expired_observation.observation_authenticated is True
            expired_observer = state_contract._Transport(expired_plan, expired_readiness)
            expired_writer = _Writer(expired_observer, expired_readiness)
            _reject(
                lambda: _execute(
                    expired_authorization,
                    expired_ledger,
                    expired_observer,
                    expired_writer,
                    now="2026-09-15T09:55:00Z",
                )
            )
            assert expired_writer.calls == 0
        finally:
            expired_temp.cleanup()
            expired_auth_temp.cleanup()
            state_contract.plan_contract.ready_contract._cleanup_source(expired_items)

        for field, value in (
            ("transaction_lock_committed", False),
            ("deployment_authorization_authenticated", False),
            ("pre_write_clear_revalidated", False),
            ("post_lock_clear_revalidated", False),
            ("deployment_created", False),
            ("exact_post_write_state_verified", False),
            ("deployment_status_mutation_authorized", True),
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
                    deploy_tx.PilotExactTaskStagingDeploymentTransactionReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        schema = json.loads(code_of(SCHEMA))
        receipt_fields = set(deploy_tx.PilotExactTaskStagingDeploymentTransactionReceipt.__dataclass_fields__)
        assert set(schema["properties"]) == receipt_fields
        assert set(schema["required"]) == receipt_fields
        assert len(receipt_fields) == 46

        execute_sig = inspect.signature(deploy_tx.execute_pilot_exact_task_staging_deployment)
        assert list(execute_sig.parameters) == ["deployment_authorization"]

        source_text = code_of(SOURCE)
        assert source_text.count('method="POST"') == 1
        assert 'method="PUT"' not in source_text
        assert 'method="PATCH"' not in source_text
        assert 'method="DELETE"' not in source_text
        assert "/deployments" in source_text
        assert "/statuses" not in source_text
        assert "deployment_status_mutation_authorized: bool = False" in source_text
        assert "production_activation_authorized: bool = False" in source_text
    finally:
        tx_temp.cleanup()
        auth_temp.cleanup()
        state_contract.plan_contract.ready_contract._cleanup_source(items)


if __name__ == "__main__":
    run_contract()
