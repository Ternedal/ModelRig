"""Adversarial contract for ADR-DC-094 write-free production activation recovery."""
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

from kaliv_dev_control import improvement_pilot_exact_task_production_activation_recovery as recovery  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_production_activation_transaction as tx  # noqa: E402
import rsi_pilot_exact_task_production_activation_transaction_contract as tx_contract  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-production-activation-recovery-v1.schema.json"
SOURCE = ROOT / "devcontrol" / "src" / "kaliv_dev_control" / "improvement_pilot_exact_task_production_activation_recovery.py"


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-094 unexpectedly accepted unsafe recovery state")


def _recovery_ledger(fixture):
    root = fixture["root"] / "recovery-ledger"
    root.mkdir()
    return recovery._PilotExactTaskProductionActivationRecoveryLedger(root)


def _make_inactive_lock():
    fixture = tx_contract._fixture()
    good = dict(fixture["executor"]._default_state)
    bad = dict(good)
    bad["remote_candidate_sha"] = "2" * 40
    executor = tx_contract._FakeExecutor(
        fixture["authorization"],
        fixture["config"],
        states=[good, bad],
    )
    try:
        tx_contract._execute(fixture, executor=executor)
    except tx.PilotExactTaskProductionActivationTransactionError:
        pass
    else:
        raise AssertionError("expected ADR-DC-093 post-lock drift")
    final, lock = fixture["ledger"]._paths(
        fixture["authorization"].production_activation_candidate_sha256
    )
    assert lock.exists()
    assert not final.exists()
    assert executor.run_calls == 0
    return fixture


class _CommitRefusingLedger(tx._PilotExactTaskProductionActivationTransactionLedger):
    def commit(self, **kwargs):
        raise tx.PilotExactTaskProductionActivationTransactionError(
            "fixture refuses ADR-DC-093 final receipt after machine activation"
        )


def _make_exact_activated_lock():
    fixture = tx_contract._fixture()
    ledger = _CommitRefusingLedger(fixture["ledger"].root)
    fixture["ledger"] = ledger
    try:
        tx_contract._execute(fixture)
    except tx.PilotExactTaskProductionActivationTransactionError:
        pass
    else:
        raise AssertionError("expected fixture transaction finalization refusal")
    final, lock = ledger._paths(
        fixture["authorization"].production_activation_candidate_sha256
    )
    assert lock.exists()
    assert not final.exists()
    assert fixture["executor"].run_calls == 1
    output = (
        Path(fixture["config"].output_root)
        / fixture["authorization"].production_activation_candidate_sha256
    )
    assert (output / "production-activation-preflight.json").exists()
    assert (output / "production-activation.json").exists()
    return fixture


def _recover(fixture, ledger=None):
    if ledger is None:
        ledger = _recovery_ledger(fixture)
    moments = iter(("2026-09-15T09:53:00Z", "2026-09-15T09:53:01Z"))
    receipt = recovery._recover_verified_pilot_exact_task_production_activation(
        production_activation_key_sha256=fixture[
            "authorization"
        ].production_activation_candidate_sha256,
        transaction_config=fixture["config"],
        transaction_ledger=fixture["ledger"],
        recovery_ledger=ledger,
        now_provider=lambda: next(moments),
    )
    return receipt, ledger


def _assert_no_authority(receipt) -> None:
    assert receipt.controller_rerun_performed is False
    assert receipt.production_env_mutation_performed is False
    assert receipt.appliance_restart_performed is False
    assert receipt.production_receipt_write_performed is False
    assert receipt.transaction_receipt_backfilled is False
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

    inactive = _make_inactive_lock()
    try:
        receipt, ledger = _recover(inactive)
        assert receipt.recovery_authenticated is True
        assert receipt.recovery_state_class == "inactive_verified"
        assert receipt.production_activation_observed is False
        assert receipt.environment_matches_pre_activation is True
        assert receipt.required_switches_active is False
        assert receipt.machine_production_receipt_verified is False
        assert receipt.manual_intervention_required is True
        assert receipt.double_observation_matched is True
        _assert_no_authority(receipt)

        serialized = recovery.PilotExactTaskProductionActivationRecoveryReceipt.from_mapping(
            receipt.to_dict()
        )
        assert serialized == receipt
        assert serialized.recovery_authenticated is False

        _reject(lambda: _recover(inactive, ledger=ledger))

        for field, value in (
            ("controller_rerun_performed", True),
            ("production_env_mutation_performed", True),
            ("production_activation_authorized", True),
            ("remote_write_authorized", True),
            ("nonce_reusable", True),
            ("production_activation_observed", True),
            ("manual_intervention_required", False),
        ):
            raw = receipt.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: recovery.PilotExactTaskProductionActivationRecoveryReceipt.from_mapping(
                    raw
                )
            )

        drift_root = inactive["root"] / "recovery-ledger-drift"
        drift_root.mkdir()
        drift_ledger = recovery._PilotExactTaskProductionActivationRecoveryLedger(
            drift_root
        )
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
            moments = iter(("2026-09-15T09:54:00Z", "2026-09-15T09:54:01Z"))
            _reject(
                lambda: recovery._recover_verified_pilot_exact_task_production_activation(
                    production_activation_key_sha256=inactive[
                        "authorization"
                    ].production_activation_candidate_sha256,
                    transaction_config=inactive["config"],
                    transaction_ledger=inactive["ledger"],
                    recovery_ledger=drift_ledger,
                    now_provider=moments.__next__,
                )
            )
        finally:
            recovery._observe_lock_only_state = original_observe
        assert observe_calls == 2
        drift_final, drift_lock = drift_ledger._paths(
            inactive["authorization"].production_activation_candidate_sha256
        )
        assert not drift_final.exists()
        assert drift_lock.exists()
    finally:
        tx_contract._cleanup(inactive)

    exact = _make_exact_activated_lock()
    try:
        receipt, _ledger = _recover(exact)
        assert receipt.recovery_state_class == "exact_activated"
        assert receipt.production_activation_observed is True
        assert receipt.preflight_receipt_verified is True
        assert receipt.machine_production_receipt_verified is True
        assert receipt.environment_matches_pre_activation is False
        assert receipt.required_switches_active is True
        assert receipt.manual_intervention_required is False
        assert receipt.production_preflight_observed_sha256
        assert receipt.machine_production_receipt_observed_sha256
        _assert_no_authority(receipt)
    finally:
        tx_contract._cleanup(exact)

    ambiguous = _make_inactive_lock()
    try:
        env = Path(ambiguous["config"].appliance_dir) / "modelrig.env"
        env.write_text(
            "MODELRIG_HOST=0.0.0.0\n"
            "KALIV_AGENT3_ENABLED=1\n"
            "KALIV_TOOLS_ENABLED=1\n"
            "KALIV_SCHEDULER=1\n"
            "KALIV_SCHEDULER_API=1\n"
            f"KALIV_AGENT3_VALIDATION_REPORT={Path(ambiguous['config'].agent3_report_path).resolve()}\n"
            "KALIV_SCHEDULER_APPROVAL_SECRET=" + ("S" * 32) + "\n",
            encoding="utf-8",
        )
        receipt, _ledger = _recover(ambiguous)
        assert receipt.recovery_state_class == "manual_intervention_required"
        assert receipt.production_activation_observed is None
        assert receipt.environment_matches_pre_activation is False
        assert receipt.required_switches_active is True
        assert receipt.machine_production_receipt_verified is False
        assert receipt.manual_intervention_required is True
        _assert_no_authority(receipt)
    finally:
        tx_contract._cleanup(ambiguous)

    completed = tx_contract._fixture()
    try:
        tx_contract._execute(completed)
        ledger = _recovery_ledger(completed)
        _reject(
            lambda: recovery._recover_verified_pilot_exact_task_production_activation(
                production_activation_key_sha256=completed[
                    "authorization"
                ].production_activation_candidate_sha256,
                transaction_config=completed["config"],
                transaction_ledger=completed["ledger"],
                recovery_ledger=ledger,
                now_provider=lambda: "2026-09-15T09:53:00Z",
            )
        )
        recovery_final, recovery_lock = ledger._paths(
            completed["authorization"].production_activation_candidate_sha256
        )
        assert not recovery_final.exists()
        assert not recovery_lock.exists()
    finally:
        tx_contract._cleanup(completed)

    tampered = _make_inactive_lock()
    try:
        _final, lock_path = tampered["ledger"]._paths(
            tampered["authorization"].production_activation_candidate_sha256
        )
        raw = json.loads(lock_path.read_text(encoding="utf-8"))
        raw["environment_before_sha256"] = "9" * 64
        lock_path.write_text(
            json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        ledger = _recovery_ledger(tampered)
        receipt = recovery._recover_verified_pilot_exact_task_production_activation(
            production_activation_key_sha256=tampered[
                "authorization"
            ].production_activation_candidate_sha256,
            transaction_config=tampered["config"],
            transaction_ledger=tampered["ledger"],
            recovery_ledger=ledger,
            now_provider=iter(
                ("2026-09-15T09:53:00Z", "2026-09-15T09:53:01Z")
            ).__next__,
        )
        assert receipt.recovery_state_class == "manual_intervention_required"
        assert receipt.production_activation_observed is None
        _assert_no_authority(receipt)
    finally:
        tx_contract._cleanup(tampered)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(
        recovery.PilotExactTaskProductionActivationRecoveryReceipt.__dataclass_fields__
    )
    assert set(schema["required"]) == fields
    assert set(schema["properties"]) == fields
    assert len(fields) == 61

    signature = inspect.signature(
        recovery.recover_pilot_exact_task_production_activation
    )
    assert list(signature.parameters) == ["production_activation_key_sha256"]

    source_text = code_of(SOURCE)
    for forbidden in (
        "subprocess.",
        "executor.run(",
        ".run(",
        "write_text(",
        "write_bytes(",
        "os.replace(",
        "shutil.",
        'method="POST"',
        "method='POST'",
        'method="PUT"',
        "method='PUT'",
        'method="PATCH"',
        "method='PATCH'",
        'method="DELETE"',
        "method='DELETE'",
        "create_deployment",
        "create_deployment_status",
    ):
        assert forbidden not in source_text
    assert "create_once_file" in source_text
    assert "production_activation_authorized: bool = False" in source_text
    assert "controller_rerun_performed: bool = False" in source_text
    assert "transaction_receipt_backfilled: bool = False" in source_text


if __name__ == "__main__":
    run_contract()
