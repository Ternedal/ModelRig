"""Adversarial contract for ADR-DC-088 staging success-status transaction."""
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
from source_code import code_of  # noqa: E402
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_success_status_authorization as success_auth,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_success_status_transaction as success_tx,
)
import rsi_pilot_exact_task_staging_success_status_authorization_contract as auth_contract  # noqa: E402
import rsi_pilot_exact_task_staging_success_status_state_observation_contract as state_contract  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-staging-success-status-transaction-v1.schema.json"
)
SOURCE = (
    ROOT / "devcontrol" / "src" / "kaliv_dev_control"
    / "improvement_pilot_exact_task_staging_success_status_transaction.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError(
        "ADR-DC-088 unexpectedly accepted unsafe success-status transaction"
    )


def _authorization(*, recovered=False):
    bundle, plan, observation = auth_contract._fixture(recovered=recovered)
    auth_temp, auth_ledger = auth_contract._ledger(
        "rsi-staging-success-status-tx-auth-"
    )
    config = auth_contract._config(observation)
    payload = auth_contract._payload(observation, config)
    verifier, op_sig, review_sig = auth_contract._dual_authority(payload)
    authorization = auth_contract._authorize(
        observation,
        config,
        payload,
        verifier,
        op_sig,
        review_sig,
        auth_ledger,
        state_contract._Transport(plan),
    )
    assert authorization.authorization_authenticated is True
    # ADR-DC-087 weakref-binds both the exact ADR-DC-086 observation and
    # ADR-DC-085 plan. Return the observation explicitly so ADR-DC-088 keeps
    # the complete live authority chain alive for the transaction duration.
    return bundle, plan, observation, auth_temp, authorization


def _cleanup(bundle, auth_temp) -> None:
    auth_temp.cleanup()
    state_contract.plan_contract._cleanup(bundle)


def _ledger(prefix):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, success_tx._PilotExactTaskStagingSuccessStatusTransactionLedger(root)


class _Writer:
    def __init__(
        self,
        authorization,
        *,
        status_id=None,
        node_hash="f" * 64,
        fail=False,
    ):
        self.credential_config_sha256 = authorization.publisher_credential_config_sha256
        self.credential_path_sha256 = authorization.publisher_credential_path_sha256
        self.status_id = (
            authorization.current_deployment_status_id + 1
            if status_id is None
            else status_id
        )
        self.node_hash = node_hash
        self.fail = fail
        self.calls = 0

    def create(self, authorization):
        self.calls += 1
        if self.fail:
            raise success_tx.PilotExactTaskStagingSuccessStatusTransactionError(
                "synthetic ambiguous writer failure"
            )
        return self.status_id, self.node_hash


def _observer(plan, *, status_id, node_hash="f" * 64):
    clear = state_contract._state(plan)
    exact = state_contract._state(
        plan,
        exact=True,
        success_deployment_status_id=status_id,
        success_deployment_status_node_id_sha256=node_hash,
    )
    return state_contract._Transport(
        plan,
        states=[clear, clear, clear, clear, exact, exact],
    )


def _execute(
    authorization,
    ledger,
    observer,
    writer,
    *,
    now="2026-09-15T09:51:30Z",
):
    return success_tx._execute_verified_pilot_exact_task_staging_success_status(
        success_status_authorization=authorization,
        ledger=ledger,
        observer=observer,
        writer=writer,
        now_provider=lambda: now,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    bundle, plan, observation, auth_temp, authorization = _authorization()
    assert observation.observation_authenticated is True
    tx_temp, ledger = _ledger("rsi-staging-success-status-tx-")
    try:
        status_id = authorization.current_deployment_status_id + 1
        writer = _Writer(authorization, status_id=status_id)
        observer = _observer(plan, status_id=status_id)
        receipt = _execute(authorization, ledger, observer, writer)

        assert observer.calls == 6
        assert writer.calls == 1
        assert receipt.transaction_authenticated is True
        assert receipt.success_status_transaction_key_sha256 == (
            authorization.success_deployment_status_intent_sha256
        )
        assert receipt.success_status_authorization_sha256 == authorization.sha256
        assert receipt.success_status_state_observation_sha256 == (
            authorization.success_status_state_observation_sha256
        )
        assert receipt.staging_success_status_plan_sha256 == (
            authorization.staging_success_status_plan_sha256
        )
        assert receipt.staging_runtime_build_identity_sha256 == (
            authorization.staging_runtime_build_identity_sha256
        )
        assert receipt.remote_pre_write_success_status_state_sha256 == (
            authorization.remote_success_status_state_sha256
        )
        assert receipt.deployment_id == authorization.deployment_id
        assert receipt.current_deployment_status_id == (
            authorization.current_deployment_status_id
        )
        assert receipt.success_deployment_status_state == "success"
        assert receipt.success_deployment_status_environment == "staging"
        assert receipt.success_deployment_status_description == (
            authorization.success_deployment_status_description
        )
        assert receipt.success_deployment_status_body == (
            authorization.success_deployment_status_body
        )
        assert receipt.success_deployment_status_auto_inactive is False
        assert receipt.success_deployment_status_log_url is None
        assert receipt.success_deployment_status_environment_url is None
        assert receipt.success_deployment_status_id == status_id
        assert receipt.success_deployment_status_node_id_sha256 == "f" * 64
        assert receipt.transaction_lock_committed is True
        assert receipt.success_status_authorization_authenticated is True
        assert receipt.pre_write_clear_revalidated is True
        assert receipt.post_lock_clear_revalidated is True
        assert receipt.success_deployment_status_created is True
        assert receipt.exact_post_write_state_verified is True
        assert receipt.success_deployment_status_authorized is False
        assert receipt.deployment_status_mutation_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.deployment_mutation_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False

        serialized = (
            success_tx.PilotExactTaskStagingSuccessStatusTransactionReceipt.from_mapping(
                receipt.to_dict()
            )
        )
        assert serialized == receipt
        assert serialized.transaction_authenticated is False

        replay_observer = _observer(plan, status_id=status_id)
        replay_writer = _Writer(authorization, status_id=status_id)
        _reject(
            lambda: _execute(
                authorization,
                ledger,
                replay_observer,
                replay_writer,
            )
        )
        assert replay_writer.calls == 0

        stale = (
            success_auth.PilotExactTaskStagingSuccessStatusAuthorizationReceipt.from_mapping(
                authorization.to_dict()
            )
        )
        assert stale.authorization_authenticated is False
        stale_temp, stale_ledger = _ledger("rsi-staging-success-status-tx-stale-")
        try:
            stale_observer = _observer(plan, status_id=status_id)
            stale_writer = _Writer(authorization, status_id=status_id)
            _reject(
                lambda: _execute(
                    stale,
                    stale_ledger,
                    stale_observer,
                    stale_writer,
                )
            )
            assert stale_observer.calls == 0
            assert stale_writer.calls == 0
        finally:
            stale_temp.cleanup()

        credential_temp, credential_ledger = _ledger(
            "rsi-staging-success-status-tx-credential-"
        )
        try:
            bad_writer = _Writer(authorization, status_id=status_id)
            bad_writer.credential_path_sha256 = "8" * 64
            credential_observer = _observer(plan, status_id=status_id)
            _reject(
                lambda: _execute(
                    authorization,
                    credential_ledger,
                    credential_observer,
                    bad_writer,
                )
            )
            assert credential_observer.calls == 0
            assert bad_writer.calls == 0
        finally:
            credential_temp.cleanup()

        observer_credential_temp, observer_credential_ledger = _ledger(
            "rsi-staging-success-status-tx-observer-credential-"
        )
        try:
            bad_observer = _observer(plan, status_id=status_id)
            bad_observer.credential_path_sha256 = "9" * 64
            observer_writer = _Writer(authorization, status_id=status_id)
            _reject(
                lambda: _execute(
                    authorization,
                    observer_credential_ledger,
                    bad_observer,
                    observer_writer,
                )
            )
            assert bad_observer.calls == 0
            assert observer_writer.calls == 0
        finally:
            observer_credential_temp.cleanup()

        expired_temp, expired_ledger = _ledger(
            "rsi-staging-success-status-tx-expired-"
        )
        try:
            expired_observer = _observer(plan, status_id=status_id)
            expired_writer = _Writer(authorization, status_id=status_id)
            _reject(
                lambda: _execute(
                    authorization,
                    expired_ledger,
                    expired_observer,
                    expired_writer,
                    now="2026-09-15T09:56:12Z",
                )
            )
            assert expired_observer.calls == 0
            assert expired_writer.calls == 0
        finally:
            expired_temp.cleanup()

        race_temp, race_ledger = _ledger("rsi-staging-success-status-tx-race-")
        try:
            clear = state_contract._state(plan)
            exact = state_contract._state(
                plan,
                exact=True,
                success_deployment_status_id=status_id,
                success_deployment_status_node_id_sha256="f" * 64,
            )
            race_observer = state_contract._Transport(
                plan,
                states=[clear, clear, exact, exact],
            )
            race_writer = _Writer(authorization, status_id=status_id)
            _reject(
                lambda: _execute(
                    authorization,
                    race_ledger,
                    race_observer,
                    race_writer,
                )
            )
            final_path, lock_path = race_ledger._paths(
                authorization.success_deployment_status_intent_sha256
            )
            assert lock_path.exists()
            assert not final_path.exists()
            assert race_writer.calls == 0
        finally:
            race_temp.cleanup()

        failure_temp, failure_ledger = _ledger(
            "rsi-staging-success-status-tx-write-failure-"
        )
        try:
            failure_observer = state_contract._Transport(
                plan,
                states=[state_contract._state(plan)] * 4,
            )
            failure_writer = _Writer(
                authorization,
                status_id=status_id,
                fail=True,
            )
            _reject(
                lambda: _execute(
                    authorization,
                    failure_ledger,
                    failure_observer,
                    failure_writer,
                )
            )
            final_path, lock_path = failure_ledger._paths(
                authorization.success_deployment_status_intent_sha256
            )
            assert lock_path.exists()
            assert not final_path.exists()
            assert failure_writer.calls == 1
        finally:
            failure_temp.cleanup()

        mismatch_temp, mismatch_ledger = _ledger(
            "rsi-staging-success-status-tx-postwrite-mismatch-"
        )
        try:
            clear = state_contract._state(plan)
            wrong_exact = state_contract._state(
                plan,
                exact=True,
                success_deployment_status_id=status_id,
                success_deployment_status_node_id_sha256="e" * 64,
            )
            mismatch_observer = state_contract._Transport(
                plan,
                states=[clear, clear, clear, clear, wrong_exact, wrong_exact],
            )
            mismatch_writer = _Writer(authorization, status_id=status_id)
            _reject(
                lambda: _execute(
                    authorization,
                    mismatch_ledger,
                    mismatch_observer,
                    mismatch_writer,
                )
            )
            final_path, lock_path = mismatch_ledger._paths(
                authorization.success_deployment_status_intent_sha256
            )
            assert lock_path.exists()
            assert not final_path.exists()
            assert mismatch_writer.calls == 1
        finally:
            mismatch_temp.cleanup()

        for field, value in (
            ("transaction_lock_committed", False),
            ("success_status_authorization_authenticated", False),
            ("pre_write_clear_revalidated", False),
            ("post_lock_clear_revalidated", False),
            ("success_deployment_status_created", False),
            ("exact_post_write_state_verified", False),
            ("success_deployment_status_authorized", True),
            ("deployment_status_mutation_authorized", True),
            ("remote_write_authorized", True),
            ("deployment_mutation_authorized", True),
            ("production_activation_authorized", True),
            ("nonce_reusable", True),
            ("success_deployment_status_state", "failure"),
            ("success_deployment_status_environment", "production"),
            ("success_deployment_status_auto_inactive", True),
            ("success_deployment_status_log_url", "https://example.invalid/log"),
            (
                "success_deployment_status_environment_url",
                "https://example.invalid/env",
            ),
        ):
            raw = receipt.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: (
                    success_tx.PilotExactTaskStagingSuccessStatusTransactionReceipt.from_mapping(
                        raw
                    )
                )
            )
    finally:
        tx_temp.cleanup()
        _cleanup(bundle, auth_temp)

    (
        recovered_bundle,
        recovered_plan,
        recovered_observation,
        recovered_auth_temp,
        recovered_auth,
    ) = _authorization(recovered=True)
    assert recovered_observation.observation_authenticated is True
    recovered_tx_temp, recovered_ledger = _ledger(
        "rsi-staging-success-status-tx-recovered-"
    )
    try:
        recovered_status_id = recovered_auth.current_deployment_status_id + 1
        recovered_receipt = _execute(
            recovered_auth,
            recovered_ledger,
            _observer(recovered_plan, status_id=recovered_status_id),
            _Writer(recovered_auth, status_id=recovered_status_id),
        )
        assert recovered_receipt.transaction_authenticated is True
        assert recovered_receipt.status_recovery_lock_sha256 is not None
        assert recovered_receipt.success_deployment_status_created is True
        assert recovered_receipt.remote_write_authorized is False
        assert recovered_receipt.production_activation_authorized is False
    finally:
        recovered_tx_temp.cleanup()
        _cleanup(recovered_bundle, recovered_auth_temp)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(
        success_tx.PilotExactTaskStagingSuccessStatusTransactionReceipt.__dataclass_fields__
    )
    assert set(schema["required"]) == fields
    assert set(schema["properties"]) == fields
    assert len(fields) == 61

    signature = inspect.signature(
        success_tx.execute_pilot_exact_task_staging_success_status
    )
    assert list(signature.parameters) == ["success_status_authorization"]

    source_text = code_of(SOURCE)
    assert source_text.count('method="POST"') == 1
    for forbidden in (
        'method="PUT"',
        "method='PUT'",
        'method="PATCH"',
        "method='PATCH'",
        'method="DELETE"',
        "method='DELETE'",
    ):
        assert forbidden not in source_text
    assert "/statuses" in source_text
    assert "success_deployment_status_authorized: bool = False" in source_text
    assert "deployment_status_mutation_authorized: bool = False" in source_text
    assert "production_activation_authorized: bool = False" in source_text


if __name__ == "__main__":
    run_contract()
