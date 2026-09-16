"""Adversarial contract for ADR-DC-080 first Deployment Status transaction."""
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
    improvement_pilot_exact_task_staging_deployment_status_authorization as status_auth,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_deployment_status_transaction as status_tx,
)
import rsi_pilot_exact_task_staging_deployment_status_authorization_contract as auth_contract  # noqa: E402
import rsi_pilot_exact_task_staging_deployment_status_state_observation_contract as state_contract  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-staging-deployment-status-transaction-v1.schema.json"
)
SOURCE = (
    ROOT / "devcontrol" / "src" / "kaliv_dev_control"
    / "improvement_pilot_exact_task_staging_deployment_status_transaction.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-080 unexpectedly accepted unsafe status transaction")


def _authorization(*, recovered=False):
    context, plan, observation = auth_contract._fixture(recovered=recovered)
    temp, ledger = auth_contract._ledger("rsi-staging-status-auth-for-tx-")
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
        ledger,
        state_contract._Transport(plan),
    )
    assert receipt.authorization_authenticated is True
    return context, plan, observation, temp, receipt


def _ledger(prefix):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, status_tx._PilotExactTaskStagingDeploymentStatusTransactionLedger(root)


class _Writer:
    def __init__(
        self,
        authorization,
        *,
        status_id=5151,
        status_node_hash="a" * 64,
        fail=False,
    ):
        self.authorization_sha256 = authorization.sha256
        self.credential_config_sha256 = authorization.publisher_credential_config_sha256
        self.credential_path_sha256 = authorization.publisher_credential_path_sha256
        self.status_id = status_id
        self.status_node_hash = status_node_hash
        self.fail = fail
        self.calls = 0
        self.created = False

    def create(self, authorization):
        self.calls += 1
        assert authorization.sha256 == self.authorization_sha256
        if self.fail:
            raise ValueError("synthetic ambiguous writer failure")
        self.created = True
        return self.status_id, self.status_node_hash


class _Transport:
    def __init__(
        self,
        plan,
        authorization,
        writer,
        *,
        scripted=None,
        post_status_id=None,
        post_status_node_hash=None,
    ):
        self.plan_sha256 = plan.sha256
        self.authorization = authorization
        self.writer = writer
        self.scripted = list(scripted or ())
        self.post_status_id = post_status_id
        self.post_status_node_hash = post_status_node_hash
        self.credential_config_sha256 = authorization.publisher_credential_config_sha256
        self.credential_path_sha256 = authorization.publisher_credential_path_sha256
        self.calls = 0

    def observe(self, plan):
        self.calls += 1
        assert plan.sha256 == self.plan_sha256
        state_class = (
            self.scripted.pop(0)
            if self.scripted
            else ("exact-existing" if self.writer.created else "clear")
        )
        synthetic = state_contract._Transport(
            plan,
            state_class=state_class,
            status_id=(
                self.writer.status_id
                if self.post_status_id is None
                else self.post_status_id
            ),
            status_node_hash=(
                self.writer.status_node_hash
                if self.post_status_node_hash is None
                else self.post_status_node_hash
            ),
        )
        return synthetic._state(plan, state_class)


def _execute(authorization, ledger, observer, writer, *, now="2026-09-15T09:50:20Z"):
    return status_tx._execute_verified_pilot_exact_task_staging_deployment_status(
        deployment_status_authorization=authorization,
        ledger=ledger,
        observer=observer,
        writer=writer,
        now_provider=lambda: now,
    )


def _cleanup(context, auth_temp, tx_temp=None):
    if tx_temp is not None:
        tx_temp.cleanup()
    auth_temp.cleanup()
    state_contract._cleanup(context)


def run_contract() -> None:
    if os.name == "nt":
        return

    context, plan, observation, auth_temp, authorization = _authorization()
    tx_temp, ledger = _ledger("rsi-staging-status-tx-")
    try:
        writer = _Writer(authorization)
        observer = _Transport(plan, authorization, writer)
        receipt = _execute(authorization, ledger, observer, writer)
        assert observer.calls == 6
        assert writer.calls == 1
        assert writer.created is True
        assert receipt.transaction_authenticated is True
        assert receipt.deployment_status_transaction_key_sha256 == authorization.deployment_status_intent_sha256
        assert receipt.deployment_status_authorization_sha256 == authorization.sha256
        assert receipt.deployment_status_state_observation_sha256 == observation.sha256
        assert receipt.staging_deployment_status_plan_sha256 == plan.sha256
        assert receipt.remote_pre_write_status_state_sha256 == authorization.remote_deployment_status_state_sha256
        assert receipt.deployment_id == authorization.deployment_id
        assert receipt.deployment_node_id_sha256 == authorization.deployment_node_id_sha256
        assert receipt.deployment_status_state == "in_progress"
        assert receipt.deployment_status_environment == "staging"
        assert receipt.deployment_status_description == authorization.deployment_status_description
        assert receipt.deployment_status_body == authorization.deployment_status_body
        assert receipt.deployment_status_auto_inactive is False
        assert receipt.deployment_status_log_url is None
        assert receipt.deployment_status_environment_url is None
        assert receipt.deployment_status_id == 5151
        assert receipt.deployment_status_node_id_sha256 == "a" * 64
        assert receipt.transaction_lock_committed is True
        assert receipt.deployment_status_authorization_authenticated is True
        assert receipt.pre_write_clear_revalidated is True
        assert receipt.post_lock_clear_revalidated is True
        assert receipt.first_deployment_status_created is True
        assert receipt.exact_post_write_state_verified is True
        assert receipt.deployment_status_mutation_authorized is False
        assert receipt.deployment_mutation_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False

        serialized = status_tx.PilotExactTaskStagingDeploymentStatusTransactionReceipt.from_mapping(
            receipt.to_dict()
        )
        assert serialized == receipt
        assert serialized.transaction_authenticated is False

        replay_writer = _Writer(authorization)
        replay_observer = _Transport(plan, authorization, replay_writer)
        _reject(lambda: _execute(authorization, ledger, replay_observer, replay_writer))
        assert replay_writer.calls == 0

        stale = status_auth.PilotExactTaskStagingDeploymentStatusAuthorizationReceipt.from_mapping(
            authorization.to_dict()
        )
        assert stale.authorization_authenticated is False
        stale_temp, stale_ledger = _ledger("rsi-staging-status-tx-stale-")
        try:
            stale_writer = _Writer(authorization)
            stale_observer = _Transport(plan, authorization, stale_writer)
            _reject(lambda: _execute(stale, stale_ledger, stale_observer, stale_writer))
            assert stale_writer.calls == 0
        finally:
            stale_temp.cleanup()

        credential_temp, credential_ledger = _ledger("rsi-staging-status-tx-credential-")
        try:
            bad_writer = _Writer(authorization)
            bad_writer.credential_path_sha256 = "8" * 64
            bad_observer = _Transport(plan, authorization, bad_writer)
            _reject(lambda: _execute(authorization, credential_ledger, bad_observer, bad_writer))
            assert bad_writer.calls == 0
            assert bad_observer.calls == 0
        finally:
            credential_temp.cleanup()

        expired_temp, expired_ledger = _ledger("rsi-staging-status-tx-expired-")
        try:
            expired_writer = _Writer(authorization)
            expired_observer = _Transport(plan, authorization, expired_writer)
            _reject(
                lambda: _execute(
                    authorization,
                    expired_ledger,
                    expired_observer,
                    expired_writer,
                    now="2026-09-15T09:55:00Z",
                )
            )
            assert expired_writer.calls == 0
            assert expired_observer.calls == 0
        finally:
            expired_temp.cleanup()

        race_temp, race_ledger = _ledger("rsi-staging-status-tx-race-")
        try:
            race_writer = _Writer(authorization)
            race_observer = _Transport(
                plan,
                authorization,
                race_writer,
                scripted=["clear", "clear", "clear", "exact-existing"],
            )
            _reject(lambda: _execute(authorization, race_ledger, race_observer, race_writer))
            final_path, lock_path = race_ledger._paths(authorization.deployment_status_intent_sha256)
            assert lock_path.exists()
            assert not final_path.exists()
            assert race_writer.calls == 0
        finally:
            race_temp.cleanup()

        failure_temp, failure_ledger = _ledger("rsi-staging-status-tx-writer-failure-")
        try:
            failure_writer = _Writer(authorization, fail=True)
            failure_observer = _Transport(plan, authorization, failure_writer)
            _reject(lambda: _execute(authorization, failure_ledger, failure_observer, failure_writer))
            final_path, lock_path = failure_ledger._paths(authorization.deployment_status_intent_sha256)
            assert lock_path.exists()
            assert not final_path.exists()
            assert failure_writer.calls == 1
        finally:
            failure_temp.cleanup()

        mismatch_temp, mismatch_ledger = _ledger("rsi-staging-status-tx-post-mismatch-")
        try:
            mismatch_writer = _Writer(authorization)
            mismatch_observer = _Transport(
                plan,
                authorization,
                mismatch_writer,
                post_status_id=9999,
            )
            _reject(lambda: _execute(authorization, mismatch_ledger, mismatch_observer, mismatch_writer))
            final_path, lock_path = mismatch_ledger._paths(authorization.deployment_status_intent_sha256)
            assert lock_path.exists()
            assert not final_path.exists()
            assert mismatch_writer.calls == 1
        finally:
            mismatch_temp.cleanup()

        for field, value in (
            ("transaction_lock_committed", False),
            ("deployment_status_authorization_authenticated", False),
            ("pre_write_clear_revalidated", False),
            ("post_lock_clear_revalidated", False),
            ("first_deployment_status_created", False),
            ("exact_post_write_state_verified", False),
            ("deployment_status_mutation_authorized", True),
            ("deployment_mutation_authorized", True),
            ("deploy_authorized", True),
            ("remote_write_authorized", True),
            ("release_authorized", True),
            ("production_activation_authorized", True),
            ("nonce_reusable", True),
            ("deployment_status_state", "success"),
            ("deployment_status_environment", "production"),
            ("deployment_status_auto_inactive", True),
            ("deployment_status_log_url", "https://example.invalid/log"),
            ("deployment_status_environment_url", "https://example.invalid/env"),
        ):
            raw = receipt.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: status_tx.PilotExactTaskStagingDeploymentStatusTransactionReceipt.from_mapping(raw)
            )

        schema = json.loads(code_of(SCHEMA))
        receipt_fields = set(
            status_tx.PilotExactTaskStagingDeploymentStatusTransactionReceipt.__dataclass_fields__
        )
        assert set(schema["properties"]) == receipt_fields
        assert set(schema["required"]) == receipt_fields
        assert len(receipt_fields) == 69

        signature = inspect.signature(
            status_tx.execute_pilot_exact_task_staging_deployment_status
        )
        assert list(signature.parameters) == ["deployment_status_authorization"]

        source_text = code_of(SOURCE)
        assert source_text.count('method="POST"') == 1
        for forbidden in (
            'method="PUT"', "method='PUT'",
            'method="PATCH"', "method='PATCH'",
            'method="DELETE"', "method='DELETE'",
        ):
            assert forbidden not in source_text
        assert "/deployments/{authorization.deployment_id}/statuses" in source_text
        assert "first_deployment_status_created: bool = True" in source_text
        assert "deployment_status_mutation_authorized: bool = False" in source_text
        assert "deployment_mutation_authorized: bool = False" in source_text
        assert "production_activation_authorized: bool = False" in source_text
    finally:
        _cleanup(context, auth_temp, tx_temp)

    recovered_context, recovered_plan, recovered_observation, recovered_auth_temp, recovered_authorization = _authorization(
        recovered=True
    )
    recovered_tx_temp, recovered_ledger = _ledger("rsi-staging-status-tx-recovered-")
    try:
        writer = _Writer(recovered_authorization)
        observer = _Transport(recovered_plan, recovered_authorization, writer)
        receipt = _execute(recovered_authorization, recovered_ledger, observer, writer)
        assert receipt.transaction_authenticated is True
        assert receipt.completion_source == "recovery"
        assert receipt.source_action == "finalize_existing_state"
        assert receipt.source_remote_write_performed is False
        assert receipt.first_deployment_status_created is True
        assert receipt.deployment_status_mutation_authorized is False
        assert receipt.deployment_mutation_authorized is False
        assert receipt.production_activation_authorized is False
    finally:
        _cleanup(recovered_context, recovered_auth_temp, recovered_tx_temp)


if __name__ == "__main__":
    run_contract()
