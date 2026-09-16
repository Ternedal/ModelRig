"""Adversarial contract for ADR-DC-081 write-free first Deployment Status recovery."""
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
    improvement_pilot_exact_task_staging_deployment_status_recovery as status_recovery,
)
import rsi_pilot_exact_task_staging_deployment_status_authorization_contract as auth_contract  # noqa: E402
import rsi_pilot_exact_task_staging_deployment_status_state_observation_contract as state_contract  # noqa: E402
import rsi_pilot_exact_task_staging_deployment_status_transaction_contract as tx_contract  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-staging-deployment-status-recovery-v1.schema.json"
)
SOURCE = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "improvement_pilot_exact_task_staging_deployment_status_recovery.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-081 unexpectedly accepted unsafe status recovery")


def _recovery_ledger(prefix: str):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return (
        temp,
        status_recovery._PilotExactTaskStagingDeploymentStatusRecoveryLedger(root),
    )


def _partial_transaction(prefix: str, *, recovered=False):
    context, plan, observation, auth_temp, authorization = tx_contract._authorization(
        recovered=recovered
    )
    tx_temp, tx_ledger = tx_contract._ledger(prefix)
    lock_payload = tx_ledger.acquire(authorization=authorization)
    final_path, lock_path = tx_ledger._paths(
        authorization.deployment_status_intent_sha256
    )
    assert lock_path.exists()
    assert not final_path.exists()
    return (
        context,
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
        *,
        state_class="exact_existing",
        status_id=5151,
        node_hash="a" * 64,
        description_sha=None,
        state=None,
        environment=None,
        log_url=None,
        environment_url=None,
        scripted=None,
    ):
        self.authorization_sha256 = authorization.sha256
        self.credential_config_sha256 = authorization.publisher_credential_config_sha256
        self.credential_path_sha256 = authorization.publisher_credential_path_sha256
        self.state_class = state_class
        self.status_id = status_id
        self.node_hash = node_hash
        self.description_sha = (
            authorization.deployment_status_description_sha256
            if description_sha is None
            else description_sha
        )
        self.state = (
            authorization.deployment_status_state if state is None else state
        )
        self.environment = (
            authorization.deployment_status_environment
            if environment is None
            else environment
        )
        self.log_url = log_url
        self.environment_url = environment_url
        self.scripted = list(scripted or ())
        self.calls = 0

    def _state(self, authorization, state_class):
        if state_class == "clear":
            return status_recovery._StatusRecoveryRemoteState(
                repository=authorization.repository,
                repository_id=authorization.repository_id,
                deployment_id=authorization.deployment_id,
                deployment_node_id_sha256=authorization.deployment_node_id_sha256,
                deployment_status_lane_state="absent",
                deployment_status_id=None,
                deployment_status_node_id_sha256=None,
                observed_status_state=None,
                observed_status_environment=None,
                observed_status_description_sha256=None,
                observed_status_log_url=None,
                observed_status_environment_url=None,
                status_created_at_utc=None,
                status_updated_at_utc=None,
                remote_state_class="clear",
            )
        if state_class != "exact_existing":
            raise AssertionError("unsupported ADR-DC-081 synthetic state")
        return status_recovery._StatusRecoveryRemoteState(
            repository=authorization.repository,
            repository_id=authorization.repository_id,
            deployment_id=authorization.deployment_id,
            deployment_node_id_sha256=authorization.deployment_node_id_sha256,
            deployment_status_lane_state="exact",
            deployment_status_id=self.status_id,
            deployment_status_node_id_sha256=self.node_hash,
            observed_status_state=self.state,
            observed_status_environment=self.environment,
            observed_status_description_sha256=self.description_sha,
            observed_status_log_url=self.log_url,
            observed_status_environment_url=self.environment_url,
            status_created_at_utc="2026-09-15T09:50:15Z",
            status_updated_at_utc="2026-09-15T09:50:16Z",
            remote_state_class="exact_existing",
        )

    def observe(self, authorization):
        self.calls += 1
        assert authorization.sha256 == self.authorization_sha256
        state_class = self.scripted.pop(0) if self.scripted else self.state_class
        return self._state(authorization, state_class)


def _roots(auth_temp, tx_temp):
    return Path(auth_temp.name) / "ledger", Path(tx_temp.name) / "ledger"


def _inspect(
    authorization,
    auth_temp,
    tx_temp,
    transport,
    *,
    now="2026-09-15T09:50:18Z",
):
    auth_root, tx_root = _roots(auth_temp, tx_temp)
    return status_recovery._observe_verified_recovery_state(
        deployment_status_intent_sha256=authorization.deployment_status_intent_sha256,
        transaction_ledger_root=tx_root,
        status_authorization_ledger_root=auth_root,
        transport=transport,
        now_provider=lambda: now,
    )


def _payload(state):
    return status_recovery._build_recovery_payload(
        state=state,
        requested_at_utc="2026-09-15T09:49:59Z",
        expires_at_utc="2026-09-15T09:54:59Z",
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
    now="2026-09-15T09:50:20Z",
):
    auth_root, tx_root = _roots(auth_temp, tx_temp)
    return status_recovery._recover_verified_pilot_exact_task_staging_deployment_status(
        authorization_payload=payload,
        operator_signature=op_sig,
        reviewer_signature=review_sig,
        verifier=verifier,
        transaction_ledger_root=tx_root,
        status_authorization_ledger_root=auth_root,
        recovery_ledger=ledger,
        transport=transport,
        now_provider=lambda: now,
    )


def _cleanup(context, auth_temp, tx_temp):
    tx_temp.cleanup()
    auth_temp.cleanup()
    state_contract._cleanup(context)


def run_contract() -> None:
    if os.name == "nt":
        return

    (
        context,
        plan,
        observation,
        authorization,
        auth_temp,
        tx_temp,
        _tx_ledger,
        lock_payload,
    ) = _partial_transaction("rsi-staging-status-recovery-")
    recovery_temp, recovery_ledger = _recovery_ledger(
        "rsi-staging-status-recovery-ledger-"
    )
    try:
        assert observation.observation_authenticated is True
        exact_transport = _Transport(authorization)
        state, durable_authorization = _inspect(
            authorization,
            auth_temp,
            tx_temp,
            exact_transport,
        )
        assert exact_transport.calls == 2
        assert durable_authorization.sha256 == authorization.sha256
        assert durable_authorization.authorization_authenticated is False
        assert (
            state.transaction_key_sha256
            == authorization.deployment_status_intent_sha256
        )
        assert state.deployment_status_authorization_sha256 == authorization.sha256
        assert (
            state.transaction_lock_sha256
            == hashlib.sha256(lock_payload).hexdigest()
        )
        assert state.durable_phase == "lock_only"
        assert state.remote_state_class == "exact_existing"
        assert state.action_required == "finalize_existing_state"
        assert state.manual_intervention_required is False
        assert state.remote_write_required is False
        assert state.deployment_status_id == 5151
        assert state.deployment_status_node_id_sha256 == "a" * 64

        payload = _payload(state)
        verifier, op_sig, review_sig = auth_contract._dual_authority(payload)
        recovery_transport = _Transport(authorization)
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
        assert (
            receipt.recovery_key_sha256
            == authorization.deployment_status_intent_sha256
        )
        assert receipt.deployment_status_authorization_sha256 == authorization.sha256
        assert (
            receipt.deployment_status_intent_sha256
            == authorization.deployment_status_intent_sha256
        )
        assert receipt.transaction_lock_sha256 == state.transaction_lock_sha256
        assert receipt.source_durable_phase == "lock_only"
        assert receipt.source_remote_state_class == "exact_existing"
        assert receipt.deployment_status_id == 5151
        assert receipt.deployment_status_node_id_sha256 == "a" * 64
        assert receipt.action_performed == "finalize_existing_state"
        assert receipt.remote_write_performed is False
        assert receipt.durable_state_verified is True
        assert receipt.remote_state_verified is True
        assert receipt.exact_first_deployment_status_finalized is True
        assert receipt.recovery_completed is True
        assert receipt.deployment_status_mutation_authorized is False
        assert receipt.deployment_mutation_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False

        reloaded = (
            status_recovery.PilotExactTaskStagingDeploymentStatusRecoveryReceipt.from_mapping(
                receipt.to_dict()
            )
        )
        assert reloaded == receipt
        assert reloaded.recovery_authenticated is False

        replay_transport = _Transport(authorization)
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

        (
            clear_context,
            clear_plan,
            clear_observation,
            clear_authorization,
            clear_auth_temp,
            clear_tx_temp,
            _clear_tx_ledger,
            _clear_lock,
        ) = _partial_transaction("rsi-staging-status-recovery-clear-")
        try:
            assert clear_observation.observation_authenticated is True
            clear_transport = _Transport(
                clear_authorization,
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
            _cleanup(clear_context, clear_auth_temp, clear_tx_temp)

        (
            cred_context,
            _cred_plan,
            cred_observation,
            cred_authorization,
            cred_auth_temp,
            cred_tx_temp,
            _cred_tx_ledger,
            _cred_lock,
        ) = _partial_transaction("rsi-staging-status-recovery-cred-")
        try:
            assert cred_observation.observation_authenticated is True
            cred_transport = _Transport(cred_authorization)
            cred_transport.credential_path_sha256 = "8" * 64
            _reject(
                lambda: _inspect(
                    cred_authorization,
                    cred_auth_temp,
                    cred_tx_temp,
                    cred_transport,
                )
            )
            assert cred_transport.calls == 0
        finally:
            _cleanup(cred_context, cred_auth_temp, cred_tx_temp)

        (
            mismatch_context,
            _mismatch_plan,
            mismatch_observation,
            mismatch_authorization,
            mismatch_auth_temp,
            mismatch_tx_temp,
            _mismatch_tx_ledger,
            _mismatch_lock,
        ) = _partial_transaction("rsi-staging-status-recovery-mismatch-")
        try:
            assert mismatch_observation.observation_authenticated is True
            mismatch_transport = _Transport(
                mismatch_authorization,
                description_sha="b" * 64,
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
            _cleanup(
                mismatch_context,
                mismatch_auth_temp,
                mismatch_tx_temp,
            )

        (
            race_context,
            _race_plan,
            race_observation,
            race_authorization,
            race_auth_temp,
            race_tx_temp,
            _race_tx_ledger,
            _race_lock,
        ) = _partial_transaction("rsi-staging-status-recovery-race-")
        race_recovery_temp, race_recovery_ledger = _recovery_ledger(
            "rsi-staging-status-recovery-race-ledger-"
        )
        try:
            assert race_observation.observation_authenticated is True
            initial_transport = _Transport(race_authorization)
            race_state, _ = _inspect(
                race_authorization,
                race_auth_temp,
                race_tx_temp,
                initial_transport,
            )
            race_payload = _payload(race_state)
            race_verifier, race_op, race_review = auth_contract._dual_authority(
                race_payload
            )
            race_transport = _Transport(
                race_authorization,
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
                race_authorization.deployment_status_intent_sha256
            )
            assert recovery_lock.exists()
            assert not recovery_final.exists()
        finally:
            race_recovery_temp.cleanup()
            _cleanup(race_context, race_auth_temp, race_tx_temp)

        (
            final_context,
            _final_plan,
            final_observation,
            final_authorization,
            final_auth_temp,
            final_tx_temp,
            _final_tx_ledger,
            _final_lock,
        ) = _partial_transaction("rsi-staging-status-recovery-final-drift-")
        final_recovery_temp, final_recovery_ledger = _recovery_ledger(
            "rsi-staging-status-recovery-final-drift-ledger-"
        )
        try:
            assert final_observation.observation_authenticated is True
            initial_transport = _Transport(final_authorization)
            final_state, _ = _inspect(
                final_authorization,
                final_auth_temp,
                final_tx_temp,
                initial_transport,
            )
            final_payload = _payload(final_state)
            final_verifier, final_op, final_review = auth_contract._dual_authority(
                final_payload
            )
            final_transport = _Transport(
                final_authorization,
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
                    final_payload,
                    final_verifier,
                    final_op,
                    final_review,
                    final_auth_temp,
                    final_tx_temp,
                    final_recovery_ledger,
                    final_transport,
                )
            )
            recovery_final, recovery_lock = final_recovery_ledger._paths(
                final_authorization.deployment_status_intent_sha256
            )
            assert recovery_lock.exists()
            assert not recovery_final.exists()
        finally:
            final_recovery_temp.cleanup()
            _cleanup(final_context, final_auth_temp, final_tx_temp)

        (
            collapse_context,
            _collapse_plan,
            collapse_observation,
            collapse_authorization,
            collapse_auth_temp,
            collapse_tx_temp,
            _collapse_tx_ledger,
            _collapse_lock,
        ) = _partial_transaction("rsi-staging-status-recovery-collapse-")
        collapse_recovery_temp, collapse_recovery_ledger = _recovery_ledger(
            "rsi-staging-status-recovery-collapse-ledger-"
        )
        try:
            assert collapse_observation.observation_authenticated is True
            collapse_state, _ = _inspect(
                collapse_authorization,
                collapse_auth_temp,
                collapse_tx_temp,
                _Transport(collapse_authorization),
            )
            collapse_payload = _payload(collapse_state)
            collapse_verifier, collapse_op, collapse_review = (
                auth_contract._dual_authority(collapse_payload, same_key=True)
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
                    _Transport(collapse_authorization),
                )
            )
        finally:
            collapse_recovery_temp.cleanup()
            _cleanup(collapse_context, collapse_auth_temp, collapse_tx_temp)

        (
            expired_context,
            _expired_plan,
            expired_observation,
            expired_authorization,
            expired_auth_temp,
            expired_tx_temp,
            _expired_tx_ledger,
            _expired_lock,
        ) = _partial_transaction("rsi-staging-status-recovery-expired-")
        expired_recovery_temp, expired_recovery_ledger = _recovery_ledger(
            "rsi-staging-status-recovery-expired-ledger-"
        )
        try:
            assert expired_observation.observation_authenticated is True
            expired_state, _ = _inspect(
                expired_authorization,
                expired_auth_temp,
                expired_tx_temp,
                _Transport(expired_authorization),
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
                    _Transport(expired_authorization),
                    now="2026-09-15T09:55:00Z",
                )
            )
        finally:
            expired_recovery_temp.cleanup()
            _cleanup(expired_context, expired_auth_temp, expired_tx_temp)

        for field, value in (
            ("durable_state_verified", False),
            ("remote_state_verified", False),
            ("dual_external_ed25519_authorized", False),
            ("recovery_authority_consumed", False),
            ("exact_first_deployment_status_finalized", False),
            ("recovery_completed", False),
            ("deployment_status_mutation_authorized", True),
            ("deployment_mutation_authorized", True),
            ("deploy_authorized", True),
            ("remote_write_authorized", True),
            ("release_authorized", True),
            ("production_activation_authorized", True),
            ("nonce_reusable", True),
            ("remote_write_performed", True),
            ("action_performed", "retry_remote_write"),
            ("deployment_status_state", "success"),
            ("deployment_status_environment", "production"),
        ):
            raw = receipt.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: status_recovery.PilotExactTaskStagingDeploymentStatusRecoveryReceipt.from_mapping(
                    raw
                )
            )

        schema = json.loads(code_of(SCHEMA))
        receipt_fields = set(
            status_recovery.PilotExactTaskStagingDeploymentStatusRecoveryReceipt.__dataclass_fields__
        )
        assert set(schema["properties"]) == receipt_fields
        assert set(schema["required"]) == receipt_fields
        assert len(receipt_fields) == 70

        build_sig = inspect.signature(
            status_recovery.build_pilot_exact_task_staging_deployment_status_recovery_payload
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
        inspect_sig = inspect.signature(
            status_recovery.inspect_pilot_exact_task_staging_deployment_status_recovery
        )
        assert list(inspect_sig.parameters) == ["deployment_status_intent_sha256"]
        recover_sig = inspect.signature(
            status_recovery.recover_pilot_exact_task_staging_deployment_status
        )
        assert list(recover_sig.parameters) == [
            "authorization_payload",
            "operator_signature",
            "reviewer_signature",
        ]

        source_text = code_of(SOURCE)
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
        assert "create_deployment_status(" not in source_text
        assert "writer.create(" not in source_text
        assert "remote_write_performed: bool" in source_text
        assert "deployment_status_mutation_authorized: bool = False" in source_text
        assert "deployment_mutation_authorized: bool = False" in source_text
        assert "production_activation_authorized: bool = False" in source_text
    finally:
        recovery_temp.cleanup()
        _cleanup(context, auth_temp, tx_temp)

    (
        recovered_context,
        recovered_plan,
        recovered_observation,
        recovered_authorization,
        recovered_auth_temp,
        recovered_tx_temp,
        _recovered_tx_ledger,
        _recovered_lock,
    ) = _partial_transaction(
        "rsi-staging-status-recovery-upstream-recovered-",
        recovered=True,
    )
    recovered_recovery_temp, recovered_recovery_ledger = _recovery_ledger(
        "rsi-staging-status-recovery-upstream-recovered-ledger-"
    )
    try:
        assert recovered_observation.observation_authenticated is True
        initial = _Transport(recovered_authorization)
        recovered_state, _ = _inspect(
            recovered_authorization,
            recovered_auth_temp,
            recovered_tx_temp,
            initial,
        )
        payload = _payload(recovered_state)
        verifier, op_sig, review_sig = auth_contract._dual_authority(payload)
        receipt = _recover(
            payload,
            verifier,
            op_sig,
            review_sig,
            recovered_auth_temp,
            recovered_tx_temp,
            recovered_recovery_ledger,
            _Transport(recovered_authorization),
        )
        assert receipt.recovery_authenticated is True
        assert receipt.completion_source == "recovery"
        assert receipt.source_action == "finalize_existing_state"
        assert receipt.source_remote_write_performed is False
        assert receipt.remote_write_performed is False
        assert receipt.exact_first_deployment_status_finalized is True
        assert receipt.deployment_status_mutation_authorized is False
        assert receipt.deployment_mutation_authorized is False
        assert receipt.production_activation_authorized is False
    finally:
        recovered_recovery_temp.cleanup()
        _cleanup(recovered_context, recovered_auth_temp, recovered_tx_temp)


if __name__ == "__main__":
    run_contract()
