"""Adversarial contract for ADR-DC-089 write-free staging success-status recovery."""
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
    improvement_pilot_exact_task_staging_success_status_recovery as recovery,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_success_status_transaction as success_tx,
)
import rsi_pilot_exact_task_staging_deployment_authorization_contract as deploy_auth_contract  # noqa: E402
import rsi_pilot_exact_task_staging_success_status_authorization_contract as auth_contract  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-staging-success-status-recovery-v1.schema.json"
)
SOURCE = (
    ROOT / "devcontrol" / "src" / "kaliv_dev_control"
    / "improvement_pilot_exact_task_staging_success_status_recovery.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-089 unexpectedly accepted unsafe success-status recovery")


def _state(authorization, *, exact=True, **overrides):
    values = dict(
        repository=authorization.repository,
        repository_id=authorization.repository_id,
        deployment_id=authorization.deployment_id,
        deployment_node_id_sha256=authorization.deployment_node_id_sha256,
        current_deployment_status_id=authorization.current_deployment_status_id,
        current_deployment_status_node_id_sha256=(
            authorization.current_deployment_status_node_id_sha256
        ),
        success_deployment_status_id=None,
        success_deployment_status_node_id_sha256=None,
        observed_success_status_state=None,
        observed_success_status_environment=None,
        observed_success_status_description_sha256=None,
        success_status_created_at_utc=None,
        success_status_updated_at_utc=None,
        remote_state_class="clear",
    )
    if exact:
        values.update(
            success_deployment_status_id=authorization.current_deployment_status_id + 1,
            success_deployment_status_node_id_sha256="d" * 64,
            observed_success_status_state="success",
            observed_success_status_environment="staging",
            observed_success_status_description_sha256=(
                authorization.success_deployment_status_description_sha256
            ),
            success_status_created_at_utc="2026-09-15T09:51:25Z",
            success_status_updated_at_utc="2026-09-15T09:51:25Z",
            remote_state_class="exact_existing",
        )
    values.update(overrides)
    return recovery._SuccessStatusRecoveryRemoteState(**values)


class _Transport:
    def __init__(self, authorization, *, states=None):
        self.authorization = authorization
        self.credential_config_sha256 = authorization.publisher_credential_config_sha256
        self.credential_path_sha256 = authorization.publisher_credential_path_sha256
        self.states = list(states or [_state(authorization)])
        self.calls = 0

    def observe(self, authorization):
        assert authorization.sha256 == self.authorization.sha256
        self.calls += 1
        if len(self.states) > 1:
            return self.states.pop(0)
        return self.states[0]


def _auth_fixture(*, recovered=False):
    bundle, plan, observation = auth_contract._fixture(recovered=recovered)
    auth_temp, auth_ledger = auth_contract._ledger("rsi-staging-success-recovery-auth-")
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
        auth_contract.state_contract._Transport(plan),
    )
    assert authorization.authorization_authenticated is True
    tx_temp = tempfile.TemporaryDirectory(prefix="rsi-staging-success-recovery-tx-")
    tx_root = Path(tx_temp.name) / "ledger"
    tx_root.mkdir()
    tx_ledger = success_tx._PilotExactTaskStagingSuccessStatusTransactionLedger(tx_root)
    lock_payload = tx_ledger.acquire(authorization=authorization)
    assert lock_payload
    return bundle, plan, authorization, auth_temp, auth_ledger, tx_temp, tx_ledger


def _cleanup(fixture):
    bundle, _plan, _authorization, auth_temp, _auth_ledger, tx_temp, _tx_ledger = fixture
    tx_temp.cleanup()
    auth_temp.cleanup()
    auth_contract.state_contract.plan_contract._cleanup(bundle)


def _recovery_ledger(prefix):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, recovery._PilotExactTaskStagingSuccessStatusRecoveryLedger(root)


def _inspect(authorization, auth_ledger, tx_ledger, transport, *, now="2026-09-15T09:51:30Z"):
    return recovery._observe_verified_recovery_state(
        success_deployment_status_intent_sha256=(
            authorization.success_deployment_status_intent_sha256
        ),
        transaction_ledger_root=tx_ledger.root,
        success_status_authorization_ledger_root=auth_ledger.root,
        transport=transport,
        now_provider=lambda: now,
    )


def _payload(state):
    return recovery._build_recovery_payload(
        state=state,
        requested_at_utc="2026-09-15T09:51:31Z",
        expires_at_utc="2026-09-15T09:56:31Z",
        operator_actor_id="deploy.operator",
        operator_system_id="offline-deploy-operator",
        operator_key_id="deploy-op-1",
        reviewer_actor_id="deploy.reviewer",
        reviewer_system_id="offline-deploy-reviewer",
        reviewer_key_id="deploy-review-1",
    )


def _recover(state_payload, verifier, op_sig, review_sig, auth_ledger, tx_ledger, recovery_ledger, transport, *, now="2026-09-15T09:51:40Z"):
    return recovery._recover_verified_pilot_exact_task_staging_success_status(
        authorization_payload=state_payload,
        operator_signature=op_sig,
        reviewer_signature=review_sig,
        verifier=verifier,
        transaction_ledger_root=tx_ledger.root,
        success_status_authorization_ledger_root=auth_ledger.root,
        recovery_ledger=recovery_ledger,
        transport=transport,
        now_provider=lambda: now,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    fixture = _auth_fixture()
    recovery_temp, recovery_ledger = _recovery_ledger("rsi-staging-success-recovery-")
    try:
        _, _, authorization, _, auth_ledger, _, tx_ledger = fixture

        inspect_transport = _Transport(authorization)
        state, durable_authorization = _inspect(
            authorization, auth_ledger, tx_ledger, inspect_transport
        )
        assert inspect_transport.calls == 2
        assert durable_authorization.sha256 == authorization.sha256
        assert state.durable_phase == "lock_only"
        assert state.remote_state_class == "exact_existing"
        assert state.action_required == "finalize_existing_state"
        assert state.manual_intervention_required is False
        assert state.remote_write_required is False
        assert state.success_deployment_status_id == authorization.current_deployment_status_id + 1
        assert state.success_deployment_status_node_id_sha256 == "d" * 64

        payload = _payload(state)
        verifier, op_sig, review_sig = deploy_auth_contract._dual_authority(
            payload, signed_at="2026-09-15T09:51:32Z"
        )
        transport = _Transport(authorization)
        receipt = _recover(
            payload,
            verifier,
            op_sig,
            review_sig,
            auth_ledger,
            tx_ledger,
            recovery_ledger,
            transport,
        )
        assert transport.calls == 6
        assert receipt.recovery_authenticated is True
        assert receipt.recovery_key_sha256 == authorization.success_deployment_status_intent_sha256
        assert receipt.success_status_authorization_sha256 == authorization.sha256
        assert receipt.success_status_transaction_lock_sha256 == state.success_status_transaction_lock_sha256
        assert receipt.source_durable_phase == "lock_only"
        assert receipt.source_remote_state_class == "exact_existing"
        assert receipt.success_deployment_status_state == "success"
        assert receipt.success_deployment_status_environment == "staging"
        assert receipt.action_performed == "finalize_existing_state"
        assert receipt.remote_write_performed is False
        assert receipt.exact_success_deployment_status_finalized is True
        assert receipt.recovery_completed is True
        assert receipt.deployment_status_mutation_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False

        serialized = recovery.PilotExactTaskStagingSuccessStatusRecoveryReceipt.from_mapping(
            receipt.to_dict()
        )
        assert serialized == receipt
        assert serialized.recovery_authenticated is False

        replay_transport = _Transport(authorization)
        _reject(
            lambda: _recover(
                payload,
                verifier,
                op_sig,
                review_sig,
                auth_ledger,
                tx_ledger,
                recovery_ledger,
                replay_transport,
            )
        )

        clear_transport = _Transport(authorization, states=[_state(authorization, exact=False)])
        clear_state, _ = _inspect(
            authorization, auth_ledger, tx_ledger, clear_transport
        )
        assert clear_state.remote_state_class == "clear"
        assert clear_state.action_required == "manual_intervention"
        assert clear_state.manual_intervention_required is True
        assert clear_state.remote_write_required is False
        _reject(lambda: _payload(clear_state))

        wrong_credential = _Transport(authorization)
        wrong_credential.credential_path_sha256 = "8" * 64
        _reject(lambda: _inspect(authorization, auth_ledger, tx_ledger, wrong_credential))
        assert wrong_credential.calls == 0

        bad_raw = json.loads(payload.decode("utf-8"))
        bad_raw["success_deployment_status_id"] += 50
        bad_bytes = json.dumps(
            bad_raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        bad_verifier, bad_op, bad_review = deploy_auth_contract._dual_authority(
            bad_bytes, signed_at="2026-09-15T09:51:32Z"
        )
        tamper_temp, tamper_ledger = _recovery_ledger(
            "rsi-staging-success-recovery-tamper-"
        )
        try:
            _reject(
                lambda: _recover(
                    bad_bytes,
                    bad_verifier,
                    bad_op,
                    bad_review,
                    auth_ledger,
                    tx_ledger,
                    tamper_ledger,
                    _Transport(authorization),
                )
            )
        finally:
            tamper_temp.cleanup()

        collapse_verifier, collapse_op, collapse_review = deploy_auth_contract._dual_authority(
            payload, same_key=True, signed_at="2026-09-15T09:51:32Z"
        )
        collapse_temp, collapse_ledger = _recovery_ledger(
            "rsi-staging-success-recovery-collapse-"
        )
        try:
            _reject(
                lambda: _recover(
                    payload,
                    collapse_verifier,
                    collapse_op,
                    collapse_review,
                    auth_ledger,
                    tx_ledger,
                    collapse_ledger,
                    _Transport(authorization),
                )
            )
        finally:
            collapse_temp.cleanup()

        expired_temp, expired_ledger = _recovery_ledger(
            "rsi-staging-success-recovery-expired-"
        )
        try:
            _reject(
                lambda: _recover(
                    payload,
                    verifier,
                    op_sig,
                    review_sig,
                    auth_ledger,
                    tx_ledger,
                    expired_ledger,
                    _Transport(authorization),
                    now="2026-09-15T09:56:32Z",
                )
            )
        finally:
            expired_temp.cleanup()

        race_temp, race_ledger = _recovery_ledger("rsi-staging-success-recovery-race-")
        try:
            race_transport = _Transport(
                authorization,
                states=[
                    _state(authorization),
                    _state(authorization),
                    _state(authorization, exact=False),
                    _state(authorization, exact=False),
                ],
            )
            _reject(
                lambda: _recover(
                    payload,
                    verifier,
                    op_sig,
                    review_sig,
                    auth_ledger,
                    tx_ledger,
                    race_ledger,
                    race_transport,
                )
            )
            final_path, lock_path = race_ledger._paths(
                authorization.success_deployment_status_intent_sha256
            )
            assert lock_path.exists()
            assert not final_path.exists()
            assert race_transport.calls == 4
        finally:
            race_temp.cleanup()

        for field, value in (
            ("durable_state_verified", False),
            ("remote_state_verified", False),
            ("dual_external_ed25519_authorized", False),
            ("recovery_authority_consumed", False),
            ("exact_success_deployment_status_finalized", False),
            ("recovery_completed", False),
            ("remote_write_performed", True),
            ("deployment_status_mutation_authorized", True),
            ("remote_write_authorized", True),
            ("deployment_mutation_authorized", True),
            ("deploy_authorized", True),
            ("release_authorized", True),
            ("production_activation_authorized", True),
            ("nonce_reusable", True),
            ("success_deployment_status_state", "failure"),
            ("success_deployment_status_environment", "production"),
            ("source_remote_state_class", "clear"),
            ("action_performed", "retry_write"),
        ):
            raw = receipt.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: recovery.PilotExactTaskStagingSuccessStatusRecoveryReceipt.from_mapping(raw)
            )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        receipt_fields = set(
            recovery.PilotExactTaskStagingSuccessStatusRecoveryReceipt.__dataclass_fields__
        )
        assert set(schema["properties"]) == receipt_fields
        assert set(schema["required"]) == receipt_fields
        assert len(receipt_fields) == 65

        inspect_sig = inspect.signature(
            recovery.inspect_pilot_exact_task_staging_success_status_recovery
        )
        assert list(inspect_sig.parameters) == ["success_deployment_status_intent_sha256"]
        build_sig = inspect.signature(
            recovery.build_pilot_exact_task_staging_success_status_recovery_payload
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
            recovery.recover_pilot_exact_task_staging_success_status
        )
        assert list(recover_sig.parameters) == [
            "authorization_payload",
            "operator_signature",
            "reviewer_signature",
        ]

        source_text = code_of(SOURCE)
        assert 'method="GET"' in source_text
        for forbidden in (
            'method="POST"', "method='POST'",
            'method="PUT"', "method='PUT'",
            'method="PATCH"', "method='PATCH'",
            'method="DELETE"', "method='DELETE'",
            "writer.create(",
        ):
            assert forbidden not in source_text
        assert "create_once_file" in source_text
        assert "remote_write_performed: bool" in source_text
        assert "production_activation_authorized: bool = False" in source_text

        final_exists_fixture = _auth_fixture()
        try:
            _, _, final_auth, _, final_auth_ledger, _, final_tx_ledger = final_exists_fixture
            final_path, _lock_path = final_tx_ledger._paths(
                final_auth.success_deployment_status_intent_sha256
            )
            final_path.write_text("{}", encoding="utf-8")
            _reject(
                lambda: _inspect(
                    final_auth,
                    final_auth_ledger,
                    final_tx_ledger,
                    _Transport(final_auth),
                )
            )
        finally:
            _cleanup(final_exists_fixture)
    finally:
        recovery_temp.cleanup()
        _cleanup(fixture)

    recovered_fixture = _auth_fixture(recovered=True)
    recovered_temp, recovered_ledger = _recovery_ledger(
        "rsi-staging-success-recovery-upstream-recovered-"
    )
    try:
        _, _, authorization, _, auth_ledger, _, tx_ledger = recovered_fixture
        state, _ = _inspect(
            authorization, auth_ledger, tx_ledger, _Transport(authorization)
        )
        assert state.status_recovery_lock_sha256 is not None
        payload = _payload(state)
        verifier, op_sig, review_sig = deploy_auth_contract._dual_authority(
            payload, signed_at="2026-09-15T09:51:32Z"
        )
        receipt = _recover(
            payload,
            verifier,
            op_sig,
            review_sig,
            auth_ledger,
            tx_ledger,
            recovered_ledger,
            _Transport(authorization),
        )
        assert receipt.recovery_authenticated is True
        assert receipt.status_recovery_lock_sha256 is not None
        assert receipt.remote_write_performed is False
        assert receipt.production_activation_authorized is False
    finally:
        recovered_temp.cleanup()
        _cleanup(recovered_fixture)


if __name__ == "__main__":
    run_contract()
