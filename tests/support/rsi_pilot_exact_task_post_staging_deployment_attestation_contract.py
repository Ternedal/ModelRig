"""Adversarial contract for ADR-DC-076 read-only post-staging Deployment attestation."""
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
    improvement_pilot_exact_task_post_staging_deployment_attestation as post_deploy,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_deployment_recovery as deploy_recovery,
)
import rsi_pilot_exact_task_staging_deployment_recovery_contract as recovery_contract  # noqa: E402
import rsi_pilot_exact_task_staging_deployment_state_observation_contract as state_contract  # noqa: E402
import rsi_pilot_exact_task_staging_deployment_transaction_contract as tx_contract  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-post-staging-deployment-attestation-v1.schema.json"
SOURCE = ROOT / "devcontrol" / "src" / "kaliv_dev_control" / "improvement_pilot_exact_task_post_staging_deployment_attestation.py"


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-076 unexpectedly accepted unsafe post-staging evidence")


def _empty_recovery_root(prefix: str):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, root


def _recovery_path(value) -> Path:
    if isinstance(value, deploy_recovery._PilotExactTaskStagingDeploymentRecoveryLedger):
        return value.root
    return Path(value)


def _attest(authorization, auth_temp, tx_temp, recovery_root, transport, *, now="2026-09-15T09:49:50Z"):
    return post_deploy._attest_verified_pilot_exact_task_post_staging_deployment(
        execution_nonce_sha256=authorization.execution_nonce_sha256,
        transaction_ledger_root=Path(tx_temp.name) / "ledger",
        recovery_ledger_root=_recovery_path(recovery_root),
        deployment_authorization_ledger_root=Path(auth_temp.name) / "ledger",
        transport=transport,
        now_provider=lambda: now,
    )


def _cleanup(items, auth_temp, tx_temp, recovery_temp):
    recovery_temp.cleanup()
    tx_temp.cleanup()
    auth_temp.cleanup()
    state_contract.plan_contract.ready_contract._cleanup_source(items)


def _normal_completion():
    items, readiness, plan, observation, authorization, auth_temp = tx_contract._live_authorization()
    tx_temp, tx_ledger = tx_contract._transaction_ledger("rsi-post-staging-tx-")
    observer = state_contract._Transport(plan, readiness, state_class="clear", deployment_id=4242, node_hash="e" * 64)
    writer = tx_contract._Writer(observer, readiness, deployment_id=4242, node_hash="e" * 64)
    receipt = tx_contract._execute(authorization, tx_ledger, observer, writer)
    recovery_temp, recovery_root = _empty_recovery_root("rsi-post-staging-recovery-")
    return items, readiness, authorization, auth_temp, tx_temp, tx_ledger, receipt, recovery_temp, recovery_root


def _recovered_completion():
    items, readiness, _plan, _observation, authorization, auth_temp, tx_temp, tx_ledger, _lock = recovery_contract._partial_transaction("rsi-post-staging-partial-")
    recovery_temp, recovery_ledger = recovery_contract._recovery_ledger("rsi-post-staging-recovery-ledger-")
    state, _ = recovery_contract._inspect(
        authorization,
        auth_temp,
        tx_temp,
        recovery_contract._Transport(authorization, readiness),
    )
    payload = recovery_contract._payload(state)
    verifier, op_sig, review_sig = recovery_contract.auth_contract._dual_authority(payload)
    receipt = recovery_contract._recover(
        payload,
        verifier,
        op_sig,
        review_sig,
        auth_temp,
        tx_temp,
        recovery_ledger,
        recovery_contract._Transport(authorization, readiness),
    )
    return items, readiness, authorization, auth_temp, tx_temp, tx_ledger, receipt, recovery_temp, recovery_ledger


def run_contract() -> None:
    if os.name == "nt":
        return

    items, readiness, authorization, auth_temp, tx_temp, tx_ledger, tx_receipt, recovery_temp, recovery_root = _normal_completion()
    try:
        transport = recovery_contract._Transport(
            authorization,
            readiness,
            deployment_id=tx_receipt.deployment_id,
            node_hash=tx_receipt.deployment_node_id_sha256,
        )
        receipt = _attest(authorization, auth_temp, tx_temp, recovery_root, transport)
        assert transport.calls == 2
        assert receipt.attestation_authenticated is True
        assert receipt.completion_source == "transaction"
        assert receipt.completion_source_receipt_sha256 == tx_receipt.sha256
        assert receipt.source_action == "execute_exact_staging_deployment"
        assert receipt.source_remote_write_performed is True
        assert receipt.recovery_lock_sha256 is None
        assert receipt.deployment_id == 4242
        assert receipt.deployment_node_id_sha256 == "e" * 64
        assert receipt.post_staging_deployment_verified is True
        assert receipt.deployment_status_mutation_authorized is False
        assert receipt.deployment_mutation_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False

        serialized = post_deploy.PilotExactTaskPostStagingDeploymentAttestationReceipt.from_mapping(receipt.to_dict())
        assert serialized == receipt
        assert serialized.attestation_authenticated is False

        cred = recovery_contract._Transport(authorization, readiness, deployment_id=4242, node_hash="e" * 64)
        cred.credential_path_sha256 = "8" * 64
        _reject(lambda: _attest(authorization, auth_temp, tx_temp, recovery_root, cred))
        assert cred.calls == 0

        wrong_id = recovery_contract._Transport(authorization, readiness, deployment_id=4243, node_hash="e" * 64)
        _reject(lambda: _attest(authorization, auth_temp, tx_temp, recovery_root, wrong_id))

        wrong_payload = recovery_contract._Transport(
            authorization,
            readiness,
            deployment_id=4242,
            node_hash="e" * 64,
            payload_sha="a" * 64,
        )
        _reject(lambda: _attest(authorization, auth_temp, tx_temp, recovery_root, wrong_payload))

        drift = recovery_contract._Transport(
            authorization,
            readiness,
            deployment_id=4242,
            node_hash="e" * 64,
            scripted=["exact_existing", "clear"],
        )
        _reject(lambda: _attest(authorization, auth_temp, tx_temp, recovery_root, drift))

        # Both durable final sources are ambiguous.
        recovery_ledger = deploy_recovery._PilotExactTaskStagingDeploymentRecoveryLedger(recovery_root)
        recovery_final, _ = recovery_ledger._paths(authorization.execution_nonce_sha256)
        recovery_final.write_text("{}", encoding="utf-8")
        try:
            ambiguous = recovery_contract._Transport(authorization, readiness, deployment_id=4242, node_hash="e" * 64)
            _reject(lambda: _attest(authorization, auth_temp, tx_temp, recovery_root, ambiguous))
            assert ambiguous.calls == 0
        finally:
            recovery_final.unlink()

        # Tampered durable final source is rejected before observation.
        tx_final, _ = tx_ledger._paths(authorization.execution_nonce_sha256)
        original = tx_final.read_bytes()
        raw = json.loads(original.decode("utf-8"))
        raw["deployment_authorization_sha256"] = "a" * 64
        tx_final.write_text(json.dumps(raw, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        try:
            tampered = recovery_contract._Transport(authorization, readiness, deployment_id=4242, node_hash="e" * 64)
            _reject(lambda: _attest(authorization, auth_temp, tx_temp, recovery_root, tampered))
            assert tampered.calls == 0
        finally:
            tx_final.write_bytes(original)

        backwards = recovery_contract._Transport(authorization, readiness, deployment_id=4242, node_hash="e" * 64)
        _reject(lambda: _attest(authorization, auth_temp, tx_temp, recovery_root, backwards, now="2026-09-15T09:49:39Z"))

        for field in (
            "deployment_status_mutation_authorized",
            "deployment_mutation_authorized",
            "deploy_authorized",
            "remote_write_authorized",
            "production_activation_authorized",
            "nonce_reusable",
        ):
            value = receipt.to_dict()
            value[field] = True
            _reject(lambda value=value: post_deploy.PilotExactTaskPostStagingDeploymentAttestationReceipt.from_mapping(value))
    finally:
        _cleanup(items, auth_temp, tx_temp, recovery_temp)

    r_items, r_readiness, r_authorization, r_auth_temp, r_tx_temp, _r_tx_ledger, recovery_receipt, r_recovery_temp, r_recovery_ledger = _recovered_completion()
    try:
        transport = recovery_contract._Transport(
            r_authorization,
            r_readiness,
            deployment_id=recovery_receipt.deployment_id,
            node_hash=recovery_receipt.deployment_node_id_sha256,
        )
        recovered = _attest(r_authorization, r_auth_temp, r_tx_temp, r_recovery_ledger, transport)
        assert transport.calls == 2
        assert recovered.attestation_authenticated is True
        assert recovered.completion_source == "recovery"
        assert recovered.completion_source_receipt_sha256 == recovery_receipt.sha256
        assert recovered.source_action == "finalize_existing_state"
        assert recovered.source_remote_write_performed is False
        assert recovered.recovery_lock_sha256 is not None
        assert recovered.deployment_id == recovery_receipt.deployment_id
        assert recovered.deployment_node_id_sha256 == recovery_receipt.deployment_node_id_sha256
        assert recovered.deployment_status_mutation_authorized is False
        assert recovered.remote_write_authorized is False
        assert recovered.production_activation_authorized is False
    finally:
        _cleanup(r_items, r_auth_temp, r_tx_temp, r_recovery_temp)

    # No completed source means no attestation and no remote reads.
    m_items, m_readiness, _m_plan, _m_observation, m_authorization, m_auth_temp = tx_contract._live_authorization()
    m_tx_temp, _ = tx_contract._transaction_ledger("rsi-post-staging-missing-tx-")
    m_recovery_temp, m_recovery_root = _empty_recovery_root("rsi-post-staging-missing-recovery-")
    try:
        transport = recovery_contract._Transport(m_authorization, m_readiness)
        _reject(lambda: _attest(m_authorization, m_auth_temp, m_tx_temp, m_recovery_root, transport))
        assert transport.calls == 0
    finally:
        _cleanup(m_items, m_auth_temp, m_tx_temp, m_recovery_temp)

    schema = json.loads(code_of(SCHEMA))
    fields = set(post_deploy.PilotExactTaskPostStagingDeploymentAttestationReceipt.__dataclass_fields__)
    assert set(schema["required"]) == fields
    assert set(schema["properties"]) == fields
    assert len(fields) == 60

    signature = inspect.signature(post_deploy.attest_pilot_exact_task_post_staging_deployment)
    assert list(signature.parameters) == ["execution_nonce_sha256"]

    source = code_of(SOURCE)
    for forbidden in ('method="POST"', "method='POST'", 'method="PUT"', "method='PUT'", 'method="PATCH"', "method='PATCH'", 'method="DELETE"', "method='DELETE'"):
        assert forbidden not in source
    assert "/statuses" not in source
    assert "create_once_file" not in source


if __name__ == "__main__":
    run_contract()
