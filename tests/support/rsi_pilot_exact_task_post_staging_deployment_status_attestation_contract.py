"""Adversarial contract for ADR-DC-082 read-only post-Deployment-Status attestation."""
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

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_post_staging_deployment_status_attestation as post_status,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_deployment_status_recovery as status_recovery,
)
import rsi_pilot_exact_task_staging_deployment_status_recovery_contract as recovery_contract  # noqa: E402
import rsi_pilot_exact_task_staging_deployment_status_transaction_contract as tx_contract  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-post-staging-deployment-status-attestation-v1.schema.json"
)
SOURCE = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "improvement_pilot_exact_task_post_staging_deployment_status_attestation.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-082 unexpectedly accepted unsafe post-status evidence")


def _empty_recovery_root(prefix: str):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, root


def _recovery_path(value) -> Path:
    if isinstance(
        value,
        status_recovery._PilotExactTaskStagingDeploymentStatusRecoveryLedger,
    ):
        return value.root
    return Path(value)


def _attest(
    authorization,
    auth_temp,
    tx_temp,
    recovery_root,
    transport,
    *,
    now="2026-09-15T09:50:30Z",
):
    return post_status._attest_verified_pilot_exact_task_post_staging_deployment_status(
        deployment_status_intent_sha256=authorization.deployment_status_intent_sha256,
        status_transaction_ledger_root=Path(tx_temp.name) / "ledger",
        status_recovery_ledger_root=_recovery_path(recovery_root),
        status_authorization_ledger_root=Path(auth_temp.name) / "ledger",
        transport=transport,
        now_provider=lambda: now,
    )


def _normal_completion(*, recovered=False):
    context, plan, observation, auth_temp, authorization = tx_contract._authorization(
        recovered=recovered
    )
    tx_temp, tx_ledger = tx_contract._ledger("rsi-post-status-tx-")
    writer = tx_contract._Writer(authorization, status_id=5151, status_node_hash="a" * 64)
    observer = tx_contract._Transport(plan, authorization, writer)
    receipt = tx_contract._execute(authorization, tx_ledger, observer, writer)
    recovery_temp, recovery_root = _empty_recovery_root(
        "rsi-post-status-empty-recovery-"
    )
    return (
        context,
        plan,
        observation,
        authorization,
        auth_temp,
        tx_temp,
        tx_ledger,
        receipt,
        recovery_temp,
        recovery_root,
    )


def _recovered_completion(*, recovered=False):
    (
        context,
        plan,
        observation,
        authorization,
        auth_temp,
        tx_temp,
        tx_ledger,
        _lock,
    ) = recovery_contract._partial_transaction(
        "rsi-post-status-partial-",
        recovered=recovered,
    )
    recovery_temp, recovery_ledger = recovery_contract._recovery_ledger(
        "rsi-post-status-recovery-ledger-"
    )
    state, _ = recovery_contract._inspect(
        authorization,
        auth_temp,
        tx_temp,
        recovery_contract._Transport(authorization),
    )
    payload = recovery_contract._payload(state)
    verifier, op_sig, review_sig = recovery_contract.auth_contract._dual_authority(
        payload
    )
    receipt = recovery_contract._recover(
        payload,
        verifier,
        op_sig,
        review_sig,
        auth_temp,
        tx_temp,
        recovery_ledger,
        recovery_contract._Transport(authorization),
    )
    return (
        context,
        plan,
        observation,
        authorization,
        auth_temp,
        tx_temp,
        tx_ledger,
        receipt,
        recovery_temp,
        recovery_ledger,
    )


def _cleanup(context, auth_temp, tx_temp, recovery_temp):
    recovery_temp.cleanup()
    tx_temp.cleanup()
    auth_temp.cleanup()
    recovery_contract.state_contract._cleanup(context)


def run_contract() -> None:
    if os.name == "nt":
        return

    (
        context,
        _plan,
        observation,
        authorization,
        auth_temp,
        tx_temp,
        tx_ledger,
        tx_receipt,
        recovery_temp,
        recovery_root,
    ) = _normal_completion()
    try:
        assert observation.observation_authenticated is True
        transport = recovery_contract._Transport(
            authorization,
            status_id=tx_receipt.deployment_status_id,
            node_hash=tx_receipt.deployment_status_node_id_sha256,
        )
        receipt = _attest(
            authorization,
            auth_temp,
            tx_temp,
            recovery_root,
            transport,
        )
        assert transport.calls == 2
        assert receipt.attestation_authenticated is True
        assert receipt.status_completion_source == "transaction"
        assert (
            receipt.status_completion_source_receipt_sha256
            == tx_receipt.sha256
        )
        assert (
            receipt.status_source_action
            == "execute_exact_first_staging_deployment_status"
        )
        assert receipt.status_source_remote_write_performed is True
        assert receipt.status_recovery_lock_sha256 is None
        assert receipt.deployment_status_id == tx_receipt.deployment_status_id
        assert (
            receipt.deployment_status_node_id_sha256
            == tx_receipt.deployment_status_node_id_sha256
        )
        assert receipt.deployment_status_state == "in_progress"
        assert receipt.deployment_status_environment == "staging"
        assert receipt.post_staging_deployment_status_verified is True
        assert receipt.deployment_status_mutation_authorized is False
        assert receipt.deployment_mutation_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False

        serialized = (
            post_status.PilotExactTaskPostStagingDeploymentStatusAttestationReceipt.from_mapping(
                receipt.to_dict()
            )
        )
        assert serialized == receipt
        assert serialized.attestation_authenticated is False

        credential = recovery_contract._Transport(
            authorization,
            status_id=tx_receipt.deployment_status_id,
            node_hash=tx_receipt.deployment_status_node_id_sha256,
        )
        credential.credential_path_sha256 = "8" * 64
        _reject(
            lambda: _attest(
                authorization,
                auth_temp,
                tx_temp,
                recovery_root,
                credential,
            )
        )
        assert credential.calls == 0

        wrong_id = recovery_contract._Transport(
            authorization,
            status_id=9999,
            node_hash=tx_receipt.deployment_status_node_id_sha256,
        )
        _reject(
            lambda: _attest(
                authorization,
                auth_temp,
                tx_temp,
                recovery_root,
                wrong_id,
            )
        )

        wrong_node = recovery_contract._Transport(
            authorization,
            status_id=tx_receipt.deployment_status_id,
            node_hash="b" * 64,
        )
        _reject(
            lambda: _attest(
                authorization,
                auth_temp,
                tx_temp,
                recovery_root,
                wrong_node,
            )
        )

        drift = recovery_contract._Transport(
            authorization,
            status_id=tx_receipt.deployment_status_id,
            node_hash=tx_receipt.deployment_status_node_id_sha256,
            scripted=["exact_existing", "clear"],
        )
        _reject(
            lambda: _attest(
                authorization,
                auth_temp,
                tx_temp,
                recovery_root,
                drift,
            )
        )

        # Both durable completion sources are ambiguous.
        recovery_ledger = (
            status_recovery._PilotExactTaskStagingDeploymentStatusRecoveryLedger(
                recovery_root
            )
        )
        recovery_final, _ = recovery_ledger._paths(
            authorization.deployment_status_intent_sha256
        )
        recovery_final.write_text("{}", encoding="utf-8")
        try:
            ambiguous = recovery_contract._Transport(
                authorization,
                status_id=tx_receipt.deployment_status_id,
                node_hash=tx_receipt.deployment_status_node_id_sha256,
            )
            _reject(
                lambda: _attest(
                    authorization,
                    auth_temp,
                    tx_temp,
                    recovery_root,
                    ambiguous,
                )
            )
            assert ambiguous.calls == 0
        finally:
            recovery_final.unlink()

        # Tampered transaction completion is rejected before remote reads.
        tx_final, _ = tx_ledger._paths(
            authorization.deployment_status_intent_sha256
        )
        original = tx_final.read_bytes()
        raw = json.loads(original.decode("utf-8"))
        raw["deployment_status_authorization_sha256"] = "b" * 64
        tx_final.write_text(
            json.dumps(raw, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        try:
            tampered = recovery_contract._Transport(
                authorization,
                status_id=tx_receipt.deployment_status_id,
                node_hash=tx_receipt.deployment_status_node_id_sha256,
            )
            _reject(
                lambda: _attest(
                    authorization,
                    auth_temp,
                    tx_temp,
                    recovery_root,
                    tampered,
                )
            )
            assert tampered.calls == 0
        finally:
            tx_final.write_bytes(original)

        backwards = recovery_contract._Transport(
            authorization,
            status_id=tx_receipt.deployment_status_id,
            node_hash=tx_receipt.deployment_status_node_id_sha256,
        )
        _reject(
            lambda: _attest(
                authorization,
                auth_temp,
                tx_temp,
                recovery_root,
                backwards,
                now="2026-09-15T09:50:15Z",
            )
        )

        for field in (
            "durable_completion_verified",
            "exact_parent_deployment_verified",
            "exact_remote_deployment_status_verified",
            "exact_status_identity_verified",
            "exact_status_state_verified",
            "exact_status_environment_verified",
            "exact_status_description_verified",
            "status_urls_absent_verified",
            "double_observation_matched",
            "post_staging_deployment_status_verified",
        ):
            value = receipt.to_dict()
            value[field] = False
            _reject(
                lambda value=value: post_status.PilotExactTaskPostStagingDeploymentStatusAttestationReceipt.from_mapping(
                    value
                )
            )

        for field in (
            "deployment_status_mutation_authorized",
            "deployment_mutation_authorized",
            "deploy_authorized",
            "remote_write_authorized",
            "release_authorized",
            "production_activation_authorized",
            "nonce_reusable",
        ):
            value = receipt.to_dict()
            value[field] = True
            _reject(
                lambda value=value: post_status.PilotExactTaskPostStagingDeploymentStatusAttestationReceipt.from_mapping(
                    value
                )
            )
    finally:
        _cleanup(context, auth_temp, tx_temp, recovery_temp)

    (
        r_context,
        _r_plan,
        _r_observation,
        r_authorization,
        r_auth_temp,
        r_tx_temp,
        _r_tx_ledger,
        recovery_receipt,
        r_recovery_temp,
        r_recovery_ledger,
    ) = _recovered_completion(recovered=True)
    try:
        transport = recovery_contract._Transport(
            r_authorization,
            status_id=recovery_receipt.deployment_status_id,
            node_hash=recovery_receipt.deployment_status_node_id_sha256,
        )
        recovered = _attest(
            r_authorization,
            r_auth_temp,
            r_tx_temp,
            r_recovery_ledger,
            transport,
        )
        assert transport.calls == 2
        assert recovered.attestation_authenticated is True
        assert recovered.status_completion_source == "recovery"
        assert (
            recovered.status_completion_source_receipt_sha256
            == recovery_receipt.sha256
        )
        assert recovered.status_source_action == "finalize_existing_state"
        assert recovered.status_source_remote_write_performed is False
        assert recovered.status_recovery_lock_sha256 is not None
        assert recovered.deployment_completion_source == "recovery"
        assert recovered.deployment_source_remote_write_performed is False
        assert recovered.deployment_recovery_lock_sha256 is not None
        assert recovered.deployment_status_id == recovery_receipt.deployment_status_id
        assert (
            recovered.deployment_status_node_id_sha256
            == recovery_receipt.deployment_status_node_id_sha256
        )
        assert recovered.deployment_status_mutation_authorized is False
        assert recovered.remote_write_authorized is False
        assert recovered.production_activation_authorized is False
    finally:
        _cleanup(r_context, r_auth_temp, r_tx_temp, r_recovery_temp)

    # No completed source means no attestation and no remote reads.
    (
        m_context,
        _m_plan,
        _m_observation,
        m_authorization,
        m_auth_temp,
        m_tx_temp,
        _m_tx_ledger,
        _m_lock,
    ) = recovery_contract._partial_transaction("rsi-post-status-missing-")
    m_recovery_temp, m_recovery_root = _empty_recovery_root(
        "rsi-post-status-missing-recovery-"
    )
    try:
        transport = recovery_contract._Transport(m_authorization)
        _reject(
            lambda: _attest(
                m_authorization,
                m_auth_temp,
                m_tx_temp,
                m_recovery_root,
                transport,
            )
        )
        assert transport.calls == 0
    finally:
        _cleanup(m_context, m_auth_temp, m_tx_temp, m_recovery_temp)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(
        post_status.PilotExactTaskPostStagingDeploymentStatusAttestationReceipt.__dataclass_fields__
    )
    assert set(schema["required"]) == fields
    assert set(schema["properties"]) == fields
    assert len(fields) == 82

    signature = inspect.signature(
        post_status.attest_pilot_exact_task_post_staging_deployment_status
    )
    assert list(signature.parameters) == ["deployment_status_intent_sha256"]

    source = SOURCE.read_text(encoding="utf-8")
    for forbidden in (
        'method="POST"',
        "method='POST'",
        'method="PUT"',
        "method='PUT'",
        'method="PATCH"',
        "method='PATCH'",
        'method="DELETE"',
        "method='DELETE'",
        "create_deployment_status(",
        "create_once_file",
    ):
        assert forbidden not in source


if __name__ == "__main__":
    run_contract()
