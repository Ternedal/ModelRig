"""Adversarial contract for ADR-DC-095 post-production activation attestation."""
from __future__ import annotations

import inspect
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
from source_code import code_of  # noqa: E402
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import improvement_pilot_exact_task_post_production_activation_attestation as attestation  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_production_activation_recovery as recovery  # noqa: E402
import rsi_pilot_exact_task_production_activation_recovery_contract as recovery_contract  # noqa: E402
import rsi_pilot_exact_task_production_activation_transaction_contract as tx_contract  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-post-production-activation-attestation-v1.schema.json"
)
SOURCE = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "improvement_pilot_exact_task_post_production_activation_attestation.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-095 unexpectedly accepted unsafe post-production state")


def _empty_recovery_ledger(fixture):
    root = fixture["root"] / "post-production-recovery-ledger"
    root.mkdir()
    return recovery._PilotExactTaskProductionActivationRecoveryLedger(root)


def _attest(fixture, recovery_ledger, *, moments=None):
    if moments is None:
        moments = iter(("2026-09-15T09:54:00Z", "2026-09-15T09:54:01Z"))
    return attestation._attest_verified_pilot_exact_task_post_production_activation(
        production_activation_key_sha256=fixture[
            "authorization"
        ].production_activation_candidate_sha256,
        transaction_config=fixture["config"],
        transaction_ledger=fixture["ledger"],
        recovery_ledger=recovery_ledger,
        now_provider=moments.__next__,
    )


def _assert_no_authority(receipt) -> None:
    assert receipt.production_activation is True
    assert receipt.production_activation_attested is True
    assert receipt.durable_completion_verified is True
    assert receipt.transaction_lock_authenticated is True
    assert receipt.double_observation_matched is True
    assert receipt.preflight_receipt_verified is True
    assert receipt.machine_production_receipt_verified is True
    assert receipt.required_switches_active is True
    assert receipt.environment_matches_post_activation is True
    assert receipt.manual_intervention_required is False
    assert receipt.promotion_gate_execution_authorized is False
    assert receipt.production_env_mutation_authorized is False
    assert receipt.appliance_restart_authorized is False
    assert receipt.production_receipt_write_authorized is False
    assert receipt.production_activation_authorized is False
    assert receipt.success_deployment_status_authorized is False
    assert receipt.deployment_status_mutation_authorized is False
    assert receipt.deployment_mutation_authorized is False
    assert receipt.deploy_authorized is False
    assert receipt.remote_write_authorized is False
    assert receipt.release_authorized is False
    assert receipt.tag_write_authorized is False
    assert receipt.release_mutation_authorized is False
    assert receipt.merge_authorized is False
    assert receipt.push_authorized is False
    assert receipt.pr_mutation_authorized is False
    assert receipt.review_submission_authorized is False
    assert receipt.review_thread_mutation_authorized is False
    assert receipt.product_pilot_started is False
    assert receipt.nonce_reusable is False


def run_contract() -> None:
    if os.name == "nt":
        return

    normal = tx_contract._fixture()
    try:
        transaction = tx_contract._execute(normal)
        tx_contract._assert_consumed(transaction)
        recovery_ledger = _empty_recovery_ledger(normal)
        receipt = _attest(normal, recovery_ledger)
        assert receipt.attestation_authenticated is True
        assert receipt.production_activation_completion_source == "transaction"
        assert (
            receipt.production_activation_source_receipt_sha256
            == transaction.sha256
        )
        assert (
            receipt.production_activation_transaction_lock_sha256
            == transaction.production_activation_transaction_lock_sha256
        )
        assert receipt.production_activation_recovery_ledger_root_path_sha256 is None
        assert receipt.production_activation_recovery_lock_sha256 is None
        assert receipt.environment_after_sha256 == transaction.environment_after_sha256
        assert (
            receipt.production_preflight_sha256
            == transaction.production_preflight_sha256
        )
        assert (
            receipt.machine_production_receipt_sha256
            == transaction.machine_production_receipt_sha256
        )
        _assert_no_authority(receipt)

        serialized = (
            attestation.PilotExactTaskPostProductionActivationAttestationReceipt.from_mapping(
                receipt.to_dict()
            )
        )
        assert serialized == receipt
        assert serialized.attestation_authenticated is False

        for field, value in (
            ("production_activation", False),
            ("production_activation_attested", False),
            ("durable_completion_verified", False),
            ("environment_matches_post_activation", False),
            ("production_activation_authorized", True),
            ("remote_write_authorized", True),
            ("product_pilot_started", True),
            ("nonce_reusable", True),
        ):
            raw = receipt.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: attestation.PilotExactTaskPostProductionActivationAttestationReceipt.from_mapping(
                    raw
                )
            )

        collision_final, collision_lock = recovery_ledger._paths(
            normal["authorization"].production_activation_candidate_sha256
        )
        assert not collision_final.exists()
        collision_lock.write_text("collision\n", encoding="utf-8")
        _reject(lambda: _attest(normal, recovery_ledger))
    finally:
        tx_contract._cleanup(normal)

    recovered = recovery_contract._make_exact_activated_lock()
    try:
        recovery_receipt, recovery_ledger = recovery_contract._recover(recovered)
        assert recovery_receipt.recovery_state_class == "exact_activated"
        receipt = _attest(recovered, recovery_ledger)
        assert receipt.attestation_authenticated is True
        assert receipt.production_activation_completion_source == "recovery"
        assert (
            receipt.production_activation_source_receipt_sha256
            == recovery_receipt.sha256
        )
        assert (
            receipt.production_activation_recovery_ledger_root_path_sha256
            == recovery_receipt.production_activation_recovery_ledger_root_path_sha256
        )
        assert (
            receipt.production_activation_recovery_lock_sha256
            == recovery_receipt.production_activation_recovery_lock_sha256
        )
        assert (
            receipt.environment_after_sha256
            == recovery_receipt.environment_observed_sha256
        )
        assert receipt.output_state_sha256 == recovery_receipt.output_state_sha256
        _assert_no_authority(receipt)
    finally:
        tx_contract._cleanup(recovered)

    inactive = recovery_contract._make_inactive_lock()
    try:
        inactive_receipt, recovery_ledger = recovery_contract._recover(inactive)
        assert inactive_receipt.recovery_state_class == "inactive_verified"
        _reject(lambda: _attest(inactive, recovery_ledger))
    finally:
        tx_contract._cleanup(inactive)

    drift = tx_contract._fixture()
    try:
        tx_contract._execute(drift)
        recovery_ledger = _empty_recovery_ledger(drift)
        original_observe = recovery._observe_lock_only_state
        observe_calls = 0

        def drifting_observe(*, lock, transaction_config):
            nonlocal observe_calls
            observation = original_observe(
                lock=lock,
                transaction_config=transaction_config,
            )
            observe_calls += 1
            if observe_calls == 2:
                replacement = (
                    "f" * 64
                    if observation.output_state_sha256 != "f" * 64
                    else "e" * 64
                )
                return replace(observation, output_state_sha256=replacement)
            return observation

        recovery._observe_lock_only_state = drifting_observe
        try:
            _reject(lambda: _attest(drift, recovery_ledger))
        finally:
            recovery._observe_lock_only_state = original_observe
        assert observe_calls == 2
    finally:
        tx_contract._cleanup(drift)

    host_drift = tx_contract._fixture()
    try:
        tx_contract._execute(host_drift)
        recovery_ledger = _empty_recovery_ledger(host_drift)
        env_path = Path(host_drift["config"].appliance_dir) / "modelrig.env"
        env_path.write_text(
            env_path.read_text(encoding="utf-8") + "# post-activation drift\n",
            encoding="utf-8",
        )
        _reject(lambda: _attest(host_drift, recovery_ledger))
    finally:
        tx_contract._cleanup(host_drift)

    backward = tx_contract._fixture()
    try:
        tx_contract._execute(backward)
        recovery_ledger = _empty_recovery_ledger(backward)
        moments = iter(("2026-09-15T09:54:01Z", "2026-09-15T09:54:00Z"))
        _reject(
            lambda: _attest(
                backward,
                recovery_ledger,
                moments=moments,
            )
        )
    finally:
        tx_contract._cleanup(backward)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(
        attestation.PilotExactTaskPostProductionActivationAttestationReceipt.__dataclass_fields__
    )
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields

    public_signature = inspect.signature(
        attestation.attest_pilot_exact_task_post_production_activation
    )
    assert tuple(public_signature.parameters) == ("production_activation_key_sha256",)

    source = code_of(SOURCE)
    for forbidden in (
        "subprocess.",
        "create_once_file",
        "urllib",
        "requests.",
        "http.client",
        "\"POST\"",
        "\"PUT\"",
        "\"PATCH\"",
        "\"DELETE\"",
        ".write_text(",
        ".write_bytes(",
        ".unlink(",
        ".rename(",
    ):
        assert forbidden not in source
    assert "recover_pilot_exact_task_production_activation(" not in source
    assert "execute_pilot_exact_task_production_activation(" not in source


if __name__ == "__main__":
    run_contract()
