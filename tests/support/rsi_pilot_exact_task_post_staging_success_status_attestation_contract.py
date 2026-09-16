"""Adversarial contract for ADR-DC-090 post-staging success-status attestation."""
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
    improvement_pilot_exact_task_post_staging_success_status_attestation as attestation,
)
import rsi_pilot_exact_task_staging_success_status_recovery_contract as recovery_contract  # noqa: E402
import rsi_pilot_exact_task_staging_success_status_transaction_contract as tx_contract  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-post-staging-success-status-attestation-v1.schema.json"
)
SOURCE = (
    ROOT / "devcontrol" / "src" / "kaliv_dev_control"
    / "improvement_pilot_exact_task_post_staging_success_status_attestation.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError(
        "ADR-DC-090 unexpectedly accepted unsafe post-success attestation"
    )


def _empty_recovery_ledger(prefix: str):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, root


def _normal_state(authorization, **overrides):
    values = {
        "success_deployment_status_node_id_sha256": "f" * 64,
        "success_status_created_at_utc": "2026-09-15T09:51:03Z",
        "success_status_updated_at_utc": "2026-09-15T09:51:03Z",
    }
    values.update(overrides)
    return recovery_contract._state(authorization, **values)


def _attest(
    authorization,
    *,
    tx_root,
    recovery_root,
    auth_root,
    transport,
    now="2026-09-15T09:51:50Z",
):
    return attestation._attest_verified_pilot_exact_task_post_staging_success_status(
        success_deployment_status_intent_sha256=(
            authorization.success_deployment_status_intent_sha256
        ),
        success_status_transaction_ledger_root=tx_root,
        success_status_recovery_ledger_root=recovery_root,
        success_status_authorization_ledger_root=auth_root,
        transport=transport,
        now_provider=lambda: now,
    )


def _assert_inert(receipt) -> None:
    assert receipt.durable_completion_verified is True
    assert receipt.exact_parent_deployment_verified is True
    assert receipt.exact_current_status_verified is True
    assert receipt.exact_success_status_verified is True
    assert receipt.exact_success_status_identity_verified is True
    assert receipt.exact_success_status_state_verified is True
    assert receipt.exact_success_status_environment_verified is True
    assert receipt.exact_success_status_description_verified is True
    assert receipt.double_observation_matched is True
    assert receipt.post_staging_success_status_verified is True
    assert receipt.success_deployment_status_authorized is False
    assert receipt.deployment_status_mutation_authorized is False
    assert receipt.remote_write_authorized is False
    assert receipt.deployment_mutation_authorized is False
    assert receipt.deploy_authorized is False
    assert receipt.release_authorized is False
    assert receipt.merge_authorized is False
    assert receipt.production_activation_authorized is False
    assert receipt.nonce_reusable is False


def run_contract() -> None:
    if os.name == "nt":
        return

    # Normal ADR-DC-088 durable completion.
    bundle, plan, auth_temp, authorization = tx_contract._authorization()
    tx_temp, tx_ledger = tx_contract._ledger("rsi-post-success-attestation-tx-")
    recovery_temp, recovery_root = _empty_recovery_ledger(
        "rsi-post-success-attestation-recovery-empty-"
    )
    try:
        status_id = authorization.current_deployment_status_id + 1
        tx_receipt = tx_contract._execute(
            authorization,
            tx_ledger,
            tx_contract._observer(plan, status_id=status_id),
            tx_contract._Writer(authorization, status_id=status_id),
        )
        assert tx_receipt.transaction_authenticated is True
        transport = recovery_contract._Transport(
            authorization,
            states=[_normal_state(authorization)],
        )
        receipt = _attest(
            authorization,
            tx_root=tx_ledger.root,
            recovery_root=recovery_root,
            auth_root=Path(auth_temp.name) / "ledger",
            transport=transport,
        )
        assert transport.calls == 2
        assert receipt.attestation_authenticated is True
        assert receipt.success_status_completion_source == "transaction"
        assert receipt.success_status_completion_source_receipt_sha256 == tx_receipt.sha256
        assert receipt.success_status_source_action == "execute_exact_staging_success_status"
        assert receipt.success_status_source_remote_write_performed is True
        assert receipt.success_status_recovery_lock_sha256 is None
        assert receipt.success_deployment_status_id == status_id
        assert receipt.success_deployment_status_node_id_sha256 == "f" * 64
        assert receipt.success_deployment_status_state == "success"
        assert receipt.success_deployment_status_environment == "staging"
        assert receipt.source_final_remote_success_status_state_sha256 == (
            tx_receipt.post_write_remote_success_status_state_sha256
        )
        _assert_inert(receipt)

        serialized = (
            attestation.PilotExactTaskPostStagingSuccessStatusAttestationReceipt.from_mapping(
                receipt.to_dict()
            )
        )
        assert serialized == receipt
        assert serialized.attestation_authenticated is False

        # A canonical but self-consistent durable receipt with only its final remote-state
        # digest replaced must not be accepted merely because ID/node/state still match.
        final_path, _tx_lock_path = tx_ledger._paths(
            authorization.success_deployment_status_intent_sha256
        )
        original_final = final_path.read_bytes()
        tampered = json.loads(original_final.decode("utf-8"))
        tampered["post_write_remote_success_status_state_sha256"] = "a" * 64
        final_path.write_bytes(
            json.dumps(
                tampered,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        try:
            hash_transport = recovery_contract._Transport(
                authorization,
                states=[_normal_state(authorization)],
            )
            _reject(
                lambda: _attest(
                    authorization,
                    tx_root=tx_ledger.root,
                    recovery_root=recovery_root,
                    auth_root=Path(auth_temp.name) / "ledger",
                    transport=hash_transport,
                )
            )
            assert hash_transport.calls == 2
        finally:
            final_path.write_bytes(original_final)

        collision_ledger = (
            recovery_contract.recovery._PilotExactTaskStagingSuccessStatusRecoveryLedger(
                recovery_root
            )
        )
        _collision_final, collision_lock = collision_ledger._paths(
            authorization.success_deployment_status_intent_sha256
        )
        collision_lock.write_bytes(b"synthetic-colliding-recovery-lock")
        try:
            collision_transport = recovery_contract._Transport(
                authorization,
                states=[_normal_state(authorization)],
            )
            _reject(
                lambda: _attest(
                    authorization,
                    tx_root=tx_ledger.root,
                    recovery_root=recovery_root,
                    auth_root=Path(auth_temp.name) / "ledger",
                    transport=collision_transport,
                )
            )
            assert collision_transport.calls == 0
        finally:
            collision_lock.unlink()

        bad_credential = recovery_contract._Transport(
            authorization,
            states=[_normal_state(authorization)],
        )
        bad_credential.credential_path_sha256 = "8" * 64
        _reject(
            lambda: _attest(
                authorization,
                tx_root=tx_ledger.root,
                recovery_root=recovery_root,
                auth_root=Path(auth_temp.name) / "ledger",
                transport=bad_credential,
            )
        )
        assert bad_credential.calls == 0

        exact = _normal_state(authorization)
        clear = recovery_contract._state(authorization, exact=False)
        race = recovery_contract._Transport(
            authorization,
            states=[exact, clear],
        )
        _reject(
            lambda: _attest(
                authorization,
                tx_root=tx_ledger.root,
                recovery_root=recovery_root,
                auth_root=Path(auth_temp.name) / "ledger",
                transport=race,
            )
        )
        assert race.calls == 2

        early = recovery_contract._Transport(
            authorization,
            states=[_normal_state(authorization)],
        )
        _reject(
            lambda: _attest(
                authorization,
                tx_root=tx_ledger.root,
                recovery_root=recovery_root,
                auth_root=Path(auth_temp.name) / "ledger",
                transport=early,
                now="2026-09-15T09:51:02Z",
            )
        )

        for field, value in (
            ("durable_completion_verified", False),
            ("exact_parent_deployment_verified", False),
            ("exact_current_status_verified", False),
            ("exact_success_status_verified", False),
            ("exact_success_status_identity_verified", False),
            ("exact_success_status_state_verified", False),
            ("exact_success_status_environment_verified", False),
            ("exact_success_status_description_verified", False),
            ("double_observation_matched", False),
            ("post_staging_success_status_verified", False),
            ("success_deployment_status_authorized", True),
            ("deployment_status_mutation_authorized", True),
            ("remote_write_authorized", True),
            ("deployment_mutation_authorized", True),
            ("deploy_authorized", True),
            ("release_authorized", True),
            ("merge_authorized", True),
            ("production_activation_authorized", True),
            ("nonce_reusable", True),
            ("success_deployment_status_state", "failure"),
            ("success_deployment_status_environment", "production"),
            ("success_status_completion_source", "recovery"),
            ("success_status_source_action", "retry_write"),
        ):
            raw = receipt.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: (
                    attestation.PilotExactTaskPostStagingSuccessStatusAttestationReceipt.from_mapping(
                        raw
                    )
                )
            )
    finally:
        recovery_temp.cleanup()
        tx_temp.cleanup()
        tx_contract._cleanup(bundle, auth_temp)

    # Write-free ADR-DC-089 completion.
    fixture = recovery_contract._auth_fixture()
    recovery_temp, recovery_ledger = recovery_contract._recovery_ledger(
        "rsi-post-success-attestation-recovered-"
    )
    try:
        (
            _bundle,
            _plan,
            authorization,
            _auth_temp,
            auth_ledger,
            _tx_temp,
            tx_ledger,
        ) = fixture
        state, durable_authorization = recovery_contract._inspect(
            authorization,
            auth_ledger,
            tx_ledger,
            recovery_contract._Transport(authorization),
        )
        assert durable_authorization.sha256 == authorization.sha256
        payload = recovery_contract._payload(state)
        verifier, op_sig, review_sig = (
            recovery_contract.deploy_auth_contract._dual_authority(
                payload,
                signed_at="2026-09-15T09:51:32Z",
            )
        )
        recovery_receipt = recovery_contract._recover(
            payload,
            verifier,
            op_sig,
            review_sig,
            auth_ledger,
            tx_ledger,
            recovery_ledger,
            recovery_contract._Transport(authorization),
        )
        assert recovery_receipt.recovery_authenticated is True

        transport = recovery_contract._Transport(authorization)
        receipt = _attest(
            authorization,
            tx_root=tx_ledger.root,
            recovery_root=recovery_ledger.root,
            auth_root=auth_ledger.root,
            transport=transport,
        )
        assert transport.calls == 2
        assert receipt.attestation_authenticated is True
        assert receipt.success_status_completion_source == "recovery"
        assert receipt.success_status_completion_source_receipt_sha256 == (
            recovery_receipt.sha256
        )
        assert receipt.success_status_source_action == "finalize_existing_state"
        assert receipt.success_status_source_remote_write_performed is False
        assert receipt.success_status_recovery_lock_sha256 is not None
        assert receipt.success_deployment_status_id == (
            recovery_receipt.success_deployment_status_id
        )
        assert receipt.success_deployment_status_node_id_sha256 == (
            recovery_receipt.success_deployment_status_node_id_sha256
        )
        assert receipt.source_final_remote_success_status_state_sha256 == (
            recovery_receipt.final_remote_success_status_state_sha256
        )
        _assert_inert(receipt)
    finally:
        recovery_temp.cleanup()
        recovery_contract._cleanup(fixture)

    schema = json.loads(code_of(SCHEMA))
    fields = set(
        attestation.PilotExactTaskPostStagingSuccessStatusAttestationReceipt.__dataclass_fields__
    )
    assert set(schema["required"]) == fields
    assert set(schema["properties"]) == fields
    assert len(fields) == 65

    signature = inspect.signature(
        attestation.attest_pilot_exact_task_post_staging_success_status
    )
    assert list(signature.parameters) == ["success_deployment_status_intent_sha256"]

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
    assert "urllib.request" not in source_text
    assert "subprocess" not in source_text
    assert "success_deployment_status_authorized: bool = False" in source_text
    assert "deployment_status_mutation_authorized: bool = False" in source_text
    assert "production_activation_authorized: bool = False" in source_text


if __name__ == "__main__":
    run_contract()
