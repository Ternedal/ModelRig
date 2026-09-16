"""Adversarial contract for ADR-DC-075 write-free staging Deployment recovery."""
from __future__ import annotations

import hashlib
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
    improvement_pilot_exact_task_staging_deployment_recovery as deploy_recovery,
)
import rsi_pilot_exact_task_staging_deployment_authorization_contract as auth_contract  # noqa: E402
import rsi_pilot_exact_task_staging_deployment_state_observation_contract as state_contract  # noqa: E402
import rsi_pilot_exact_task_staging_deployment_transaction_contract as tx_contract  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-staging-deployment-recovery-v1.schema.json"
SOURCE = ROOT / "devcontrol" / "src" / "kaliv_dev_control" / "improvement_pilot_exact_task_staging_deployment_recovery.py"


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-075 unexpectedly accepted unsafe deployment recovery")


def _recovery_ledger(prefix: str):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, deploy_recovery._PilotExactTaskStagingDeploymentRecoveryLedger(root)


def _partial_transaction(prefix: str):
    items, readiness, plan, observation, authorization, auth_temp = tx_contract._live_authorization()
    tx_temp, tx_ledger = tx_contract._transaction_ledger(prefix)
    lock_payload = tx_ledger.acquire(authorization=authorization)
    final_path, lock_path = tx_ledger._paths(authorization.execution_nonce_sha256)
    assert lock_path.exists()
    assert not final_path.exists()
    return (
        items,
        readiness,
        plan,
        observation,
        authorization,
        auth_temp,
        tx_temp,
        tx_ledger,
        lock_payload,
    )


class _Transport:
    def __init__(
        self,
        authorization,
        readiness,
        *,
        state_class="exact_existing",
        deployment_id=4242,
        node_hash="f" * 64,
        deployment_sha=None,
        payload_sha=None,
        description_sha=None,
        scripted=None,
    ):
        self.authorization_sha256 = authorization.sha256
        self.credential_config_sha256 = readiness.publisher_credential_config_sha256
        self.credential_path_sha256 = readiness.publisher_credential_path_sha256
        self.state_class = state_class
        self.deployment_id = deployment_id
        self.node_hash = node_hash
        self.deployment_sha = authorization.merge_commit_sha if deployment_sha is None else deployment_sha
        self.payload_sha = authorization.deployment_payload_sha256 if payload_sha is None else payload_sha
        self.description_sha = (
            authorization.deployment_description_sha256
            if description_sha is None
            else description_sha
        )
        self.scripted = list(scripted or ())
        self.calls = 0

    def _state(self, authorization, state_class):
        if state_class == "clear":
            return deploy_recovery._DeploymentRecoveryRemoteState(
                repository=authorization.repository,
                repository_id=authorization.repository_id,
                deployment_state="absent",
                deployment_id=None,
                deployment_node_id_sha256=None,
                deployment_sha=None,
                observed_payload_sha256=None,
                observed_description_sha256=None,
                remote_state_class="clear",
            )
        if state_class != "exact_existing":
            raise AssertionError("unsupported ADR-DC-075 synthetic state")
        return deploy_recovery._DeploymentRecoveryRemoteState(
            repository=authorization.repository,
            repository_id=authorization.repository_id,
            deployment_state="exact",
            deployment_id=self.deployment_id,
            deployment_node_id_sha256=self.node_hash,
            deployment_sha=self.deployment_sha,
            observed_payload_sha256=self.payload_sha,
            observed_description_sha256=self.description_sha,
            remote_state_class="exact_existing",
        )

    def observe(self, authorization):
        self.calls += 1
        assert authorization.sha256 == self.authorization_sha256
        state_class = self.scripted.pop(0) if self.scripted else self.state_class
        return self._state(authorization, state_class)


def _roots(auth_temp, tx_temp):
    return Path(auth_temp.name) / "ledger", Path(tx_temp.name) / "ledger"


def _inspect(authorization, auth_temp, tx_temp, transport, *, now="2026-09-15T09:49:25Z"):
    auth_root, tx_root = _roots(auth_temp, tx_temp)
    return deploy_recovery._observe_verified_recovery_state(
        execution_nonce_sha256=authorization.execution_nonce_sha256,
        transaction_ledger_root=tx_root,
        deployment_authorization_ledger_root=auth_root,
        transport=transport,
        now_provider=lambda: now,
    )


def _payload(state):
    return deploy_recovery._build_recovery_payload(
        state=state,
        requested_at_utc="2026-09-15T09:49:10Z",
        expires_at_utc="2026-09-15T09:54:10Z",
        operator_actor_id="deploy.operator",
        operator_system_id="offline-deploy-operator",
        operator_key_id="deploy-op-1",
        reviewer_actor_id="deploy.reviewer",
        reviewer_system_id="offline-deploy-reviewer",
        reviewer_key_id="deploy-review-1",
    )


def _recover(
    payload,
    verifier,
    op_sig,
    review_sig,
    auth_temp,
    tx_temp,
    ledger,
    transport,
    *,
    now="2026-09-15T09:49:30Z",
):
    auth_root, tx_root = _roots(auth_temp, tx_temp)
    return deploy_recovery._recover_verified_pilot_exact_task_staging_deployment(
        authorization_payload=payload,
        operator_signature=op_sig,
        reviewer_signature=review_sig,
        verifier=verifier,
        transaction_ledger_root=tx_root,
        deployment_authorization_ledger_root=auth_root,
        recovery_ledger=ledger,
        transport=transport,
        now_provider=lambda: now,
    )


def _cleanup(items, auth_temp, tx_temp):
    tx_temp.cleanup()
    auth_temp.cleanup()
    state_contract.plan_contract.ready_contract._cleanup_source(items)


def run_contract() -> None:
    if os.name == "nt":
        return

    (
        items,
        readiness,
        plan,
        observation,
        authorization,
        auth_temp,
        tx_temp,
        _tx_ledger,
        lock_payload,
    ) = _partial_transaction("rsi-staging-deploy-recovery-")
    recovery_temp, recovery_ledger = _recovery_ledger("rsi-staging-deploy-recovery-ledger-")
    try:
        assert observation.observation_authenticated is True
        exact_transport = _Transport(authorization, readiness)
        state, durable_authorization = _inspect(
            authorization,
            auth_temp,
            tx_temp,
            exact_transport,
        )
        assert exact_transport.calls == 2
        assert durable_authorization.sha256 == authorization.sha256
        assert durable_authorization.authorization_authenticated is False
        assert state.transaction_key_sha256 == authorization.execution_nonce_sha256
        assert state.deployment_authorization_sha256 == authorization.sha256
        assert state.transaction_lock_sha256 == hashlib.sha256(lock_payload).hexdigest()
        assert state.durable_phase == "lock_only"
        assert state.remote_state_class == "exact_existing"
        assert state.action_required == "finalize_existing_state"
        assert state.manual_intervention_required is False
        assert state.remote_write_required is False
        assert state.deployment_id == 4242
        assert state.deployment_node_id_sha256 == "f" * 64

        payload = _payload(state)
        verifier, op_sig, review_sig = auth_contract._dual_authority(payload)
        recovery_transport = _Transport(authorization, readiness)
        receipt = _recover(
            payload,
            verifier,
            op_sig,
            review_sig,
            auth_temp,
            tx_temp,
            recovery_ledger,
            recovery_transport,
        )
        assert recovery_transport.calls == 6
        assert receipt.recovery_authenticated is True
        assert receipt.recovery_key_sha256 == authorization.execution_nonce_sha256
        assert receipt.deployment_authorization_sha256 == authorization.sha256
        assert receipt.deployment_intent_sha256 == authorization.deployment_intent_sha256
        assert receipt.transaction_lock_sha256 == state.transaction_lock_sha256
        assert receipt.source_durable_phase == "lock_only"
        assert receipt.source_remote_state_class == "exact_existing"
        assert receipt.deployment_id == 4242
        assert receipt.deployment_node_id_sha256 == "f" * 64
        assert receipt.action_performed == "finalize_existing_state"
        assert receipt.remote_write_performed is False
        assert receipt.durable_state_verified is True
        assert receipt.remote_state_verified is True
        assert receipt.exact_staging_deployment_finalized is True
        assert receipt.recovery_completed is True
        assert receipt.deployment_status_mutation_authorized is False
        assert receipt.deployment_mutation_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False

        reloaded = deploy_recovery.PilotExactTaskStagingDeploymentRecoveryReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.recovery_authenticated is False

        replay_transport = _Transport(authorization, readiness)
        _reject(
            lambda: _recover(
                payload,
                verifier,
                op_sig,
                review_sig,
                auth_temp,
                tx_temp,
                recovery_ledger,
                replay_transport,
            )
        )

        clear_items, clear_readiness, clear_plan, clear_observation, clear_authorization, clear_auth_temp, clear_tx_temp, _clear_tx_ledger, _clear_lock = _partial_transaction(
            "rsi-staging-deploy-recovery-clear-"
        )
        try:
            assert clear_observation.observation_authenticated is True
            clear_transport = _Transport(
                clear_authorization,
                clear_readiness,
                state_class="clear",
            )
            clear_state, _ = _inspect(
                clear_authorization,
                clear_auth_temp,
                clear_tx_temp,
                clear_transport,
            )
            assert clear_state.remote_state_class == "clear"
            assert clear_state.action_required == "manual_intervention"
            assert clear_state.manual_intervention_required is True
            assert clear_state.remote_write_required is False
            _reject(lambda: _payload(clear_state))
        finally:
            _cleanup(clear_items, clear_auth_temp, clear_tx_temp)

        cred_items, cred_readiness, cred_plan, cred_observation, cred_authorization, cred_auth_temp, cred_tx_temp, _cred_tx_ledger, _cred_lock = _partial_transaction(
            "rsi-staging-deploy-recovery-cred-"
        )
        try:
            assert cred_observation.observation_authenticated is True
            cred_transport = _Transport(cred_authorization, cred_readiness)
            cred_transport.credential_path_sha256 = "8" * 64
            _reject(
                lambda: _inspect(
                    cred_authorization,
                    cred_auth_temp,
                    cred_tx_temp,
                    cred_transport,
                )
            )
        finally:
            _cleanup(cred_items, cred_auth_temp, cred_tx_temp)

        mismatch_items, mismatch_readiness, mismatch_plan, mismatch_observation, mismatch_authorization, mismatch_auth_temp, mismatch_tx_temp, _mismatch_tx_ledger, _mismatch_lock = _partial_transaction(
            "rsi-staging-deploy-recovery-mismatch-"
        )
        try:
            assert mismatch_observation.observation_authenticated is True
            mismatch_transport = _Transport(
                mismatch_authorization,
                mismatch_readiness,
                payload_sha="a" * 64,
            )
            _reject(
                lambda: _inspect(
                    mismatch_authorization,
                    mismatch_auth_temp,
                    mismatch_tx_temp,
                    mismatch_transport,
                )
            )
        finally:
            _cleanup(mismatch_items, mismatch_auth_temp, mismatch_tx_temp)

        race_items, race_readiness, race_plan, race_observation, race_authorization, race_auth_temp, race_tx_temp, _race_tx_ledger, _race_lock = _partial_transaction(
            "rsi-staging-deploy-recovery-race-"
        )
        race_recovery_temp, race_recovery_ledger = _recovery_ledger(
            "rsi-staging-deploy-recovery-race-ledger-"
        )
        try:
            assert race_observation.observation_authenticated is True
            initial_transport = _Transport(race_authorization, race_readiness)
            race_state, _ = _inspect(
                race_authorization,
                race_auth_temp,
                race_tx_temp,
                initial_transport,
            )
            race_payload = _payload(race_state)
            race_verifier, race_op, race_review = auth_contract._dual_authority(race_payload)
            race_transport = _Transport(
                race_authorization,
                race_readiness,
                scripted=[
                    "exact_existing",
                    "exact_existing",
                    "exact_existing",
                    "clear",
                ],
            )
            _reject(
                lambda: _recover(
                    race_payload,
                    race_verifier,
                    race_op,
                    race_review,
                    race_auth_temp,
                    race_tx_temp,
                    race_recovery_ledger,
                    race_transport,
                )
            )
            recovery_final, recovery_lock = race_recovery_ledger._paths(
                race_authorization.execution_nonce_sha256
            )
            assert recovery_lock.exists()
            assert not recovery_final.exists()
        finally:
            race_recovery_temp.cleanup()
            _cleanup(race_items, race_auth_temp, race_tx_temp)

        final_drift_items, final_drift_readiness, final_drift_plan, final_drift_observation, final_drift_authorization, final_drift_auth_temp, final_drift_tx_temp, _final_drift_tx_ledger, _final_drift_lock = _partial_transaction(
            "rsi-staging-deploy-recovery-final-drift-"
        )
        final_drift_recovery_temp, final_drift_recovery_ledger = _recovery_ledger(
            "rsi-staging-deploy-recovery-final-drift-ledger-"
        )
        try:
            assert final_drift_observation.observation_authenticated is True
            initial_transport = _Transport(
                final_drift_authorization,
                final_drift_readiness,
            )
            final_drift_state, _ = _inspect(
                final_drift_authorization,
                final_drift_auth_temp,
                final_drift_tx_temp,
                initial_transport,
            )
            final_drift_payload = _payload(final_drift_state)
            final_drift_verifier, final_drift_op, final_drift_review = (
                auth_contract._dual_authority(final_drift_payload)
            )
            final_drift_transport = _Transport(
                final_drift_authorization,
                final_drift_readiness,
                scripted=[
                    "exact_existing",
                    "exact_existing",
                    "exact_existing",
                    "exact_existing",
                    "exact_existing",
                    "clear",
                ],
            )
            _reject(
                lambda: _recover(
                    final_drift_payload,
                    final_drift_verifier,
                    final_drift_op,
                    final_drift_review,
                    final_drift_auth_temp,
                    final_drift_tx_temp,
                    final_drift_recovery_ledger,
                    final_drift_transport,
                )
            )
            recovery_final, recovery_lock = final_drift_recovery_ledger._paths(
                final_drift_authorization.execution_nonce_sha256
            )
            assert recovery_lock.exists()
            assert not recovery_final.exists()
        finally:
            final_drift_recovery_temp.cleanup()
            _cleanup(
                final_drift_items,
                final_drift_auth_temp,
                final_drift_tx_temp,
            )

        tamper_items, tamper_readiness, tamper_plan, tamper_observation, tamper_authorization, tamper_auth_temp, tamper_tx_temp, _tamper_tx_ledger, _tamper_lock = _partial_transaction(
            "rsi-staging-deploy-recovery-tamper-"
        )
        tamper_recovery_temp, tamper_recovery_ledger = _recovery_ledger(
            "rsi-staging-deploy-recovery-tamper-ledger-"
        )
        try:
            assert tamper_observation.observation_authenticated is True
            tamper_transport = _Transport(tamper_authorization, tamper_readiness)
            tamper_state, _ = _inspect(
                tamper_authorization,
                tamper_auth_temp,
                tamper_tx_temp,
                tamper_transport,
            )
            tamper_payload = json.loads(_payload(tamper_state).decode())
            tamper_payload["deployment_id"] = tamper_payload["deployment_id"] + 1
            tamper_bytes = json.dumps(
                tamper_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
            tamper_verifier, tamper_op, tamper_review = auth_contract._dual_authority(
                tamper_bytes
            )
            _reject(
                lambda: _recover(
                    tamper_bytes,
                    tamper_verifier,
                    tamper_op,
                    tamper_review,
                    tamper_auth_temp,
                    tamper_tx_temp,
                    tamper_recovery_ledger,
                    _Transport(tamper_authorization, tamper_readiness),
                )
            )
            recovery_final, recovery_lock = tamper_recovery_ledger._paths(
                tamper_authorization.execution_nonce_sha256
            )
            assert not recovery_lock.exists()
            assert not recovery_final.exists()
        finally:
            tamper_recovery_temp.cleanup()
            _cleanup(tamper_items, tamper_auth_temp, tamper_tx_temp)

        collapse_items, collapse_readiness, collapse_plan, collapse_observation, collapse_authorization, collapse_auth_temp, collapse_tx_temp, _collapse_tx_ledger, _collapse_lock = _partial_transaction(
            "rsi-staging-deploy-recovery-collapse-"
        )
        collapse_recovery_temp, collapse_recovery_ledger = _recovery_ledger(
            "rsi-staging-deploy-recovery-collapse-ledger-"
        )
        try:
            assert collapse_observation.observation_authenticated is True
            collapse_transport = _Transport(collapse_authorization, collapse_readiness)
            collapse_state, _ = _inspect(
                collapse_authorization,
                collapse_auth_temp,
                collapse_tx_temp,
                collapse_transport,
            )
            collapse_payload = _payload(collapse_state)
            collapse_verifier, collapse_op, collapse_review = auth_contract._dual_authority(
                collapse_payload,
                same_key=True,
            )
            _reject(
                lambda: _recover(
                    collapse_payload,
                    collapse_verifier,
                    collapse_op,
                    collapse_review,
                    collapse_auth_temp,
                    collapse_tx_temp,
                    collapse_recovery_ledger,
                    _Transport(collapse_authorization, collapse_readiness),
                )
            )
        finally:
            collapse_recovery_temp.cleanup()
            _cleanup(collapse_items, collapse_auth_temp, collapse_tx_temp)

        expired_items, expired_readiness, expired_plan, expired_observation, expired_authorization, expired_auth_temp, expired_tx_temp, _expired_tx_ledger, _expired_lock = _partial_transaction(
            "rsi-staging-deploy-recovery-expired-"
        )
        expired_recovery_temp, expired_recovery_ledger = _recovery_ledger(
            "rsi-staging-deploy-recovery-expired-ledger-"
        )
        try:
            assert expired_observation.observation_authenticated is True
            expired_transport = _Transport(expired_authorization, expired_readiness)
            expired_state, _ = _inspect(
                expired_authorization,
                expired_auth_temp,
                expired_tx_temp,
                expired_transport,
            )
            expired_payload = _payload(expired_state)
            expired_verifier, expired_op, expired_review = auth_contract._dual_authority(
                expired_payload
            )
            _reject(
                lambda: _recover(
                    expired_payload,
                    expired_verifier,
                    expired_op,
                    expired_review,
                    expired_auth_temp,
                    expired_tx_temp,
                    expired_recovery_ledger,
                    _Transport(expired_authorization, expired_readiness),
                    now="2026-09-15T09:55:00Z",
                )
            )
        finally:
            expired_recovery_temp.cleanup()
            _cleanup(expired_items, expired_auth_temp, expired_tx_temp)

        for field, value in (
            ("durable_state_verified", False),
            ("remote_state_verified", False),
            ("dual_external_ed25519_authorized", False),
            ("recovery_authority_consumed", False),
            ("exact_staging_deployment_finalized", False),
            ("recovery_completed", False),
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
            ("remote_write_performed", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    deploy_recovery.PilotExactTaskStagingDeploymentRecoveryReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        schema = json.loads(code_of(SCHEMA))
        receipt_fields = set(
            deploy_recovery.PilotExactTaskStagingDeploymentRecoveryReceipt.__dataclass_fields__
        )
        assert set(schema["properties"]) == receipt_fields
        assert set(schema["required"]) == receipt_fields
        assert len(receipt_fields) == 61

        inspect_sig = inspect.signature(
            deploy_recovery.inspect_pilot_exact_task_staging_deployment_recovery
        )
        assert list(inspect_sig.parameters) == ["execution_nonce_sha256"]
        build_sig = inspect.signature(
            deploy_recovery.build_pilot_exact_task_staging_deployment_recovery_payload
        )
        assert list(build_sig.parameters) == [
            "state",
            "requested_at_utc",
            "expires_at_utc",
            "operator_actor_id",
            "operator_system_id",
            "operator_key_id",
            "reviewer_actor_id",
            "reviewer_system_id",
            "reviewer_key_id",
        ]
        recover_sig = inspect.signature(
            deploy_recovery.recover_pilot_exact_task_staging_deployment
        )
        assert list(recover_sig.parameters) == [
            "authorization_payload",
            "operator_signature",
            "reviewer_signature",
        ]

        source_text = code_of(SOURCE)
        assert 'method="POST"' not in source_text
        assert 'method="PUT"' not in source_text
        assert 'method="PATCH"' not in source_text
        assert 'method="DELETE"' not in source_text
        assert "create_deployment(" not in source_text
        assert "create_deployment_status(" not in source_text
        assert "remote_write_performed=False" in source_text
        assert "deployment_status_mutation_authorized: bool = False" in source_text
        assert "production_activation_authorized: bool = False" in source_text
    finally:
        recovery_temp.cleanup()
        _cleanup(items, auth_temp, tx_temp)


if __name__ == "__main__":
    run_contract()
