"""Adversarial contract for ADR-DC-103 product-pilot start recovery."""
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
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_start_authorization as start_auth  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_start_recovery as recovery  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_start_transaction as start_tx  # noqa: E402
import rsi_pilot_exact_task_product_pilot_start_transaction_contract as tx_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_lineage_attestation_contract as lineage_contract  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-product-pilot-start-recovery-v1.schema.json"
)
SOURCE = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "improvement_pilot_exact_task_product_pilot_start_recovery.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError, AttributeError):
        return
    raise AssertionError("ADR-DC-103 unexpectedly accepted unsafe recovery")


def _recovery_ledger(prefix):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, recovery._PilotExactTaskProductPilotStartRecoveryLedger(root)


def _auth_ledger(auth_temp):
    return start_auth._PilotExactTaskProductPilotStartAuthorizationLedger(
        Path(auth_temp.name) / "ledger"
    )


def _recover(key, tx_ledger, auth_ledger, recovery_ledger, moments=None):
    if moments is None:
        moments = iter(
            (
                "2026-09-15T09:59:00Z",
                "2026-09-15T09:59:01Z",
                "2026-09-15T09:59:02Z",
            )
        )
    return recovery._recover_verified_pilot_exact_task_product_pilot_start(
        transaction_key_sha256=key,
        transaction_ledger=tx_ledger,
        authorization_ledger=auth_ledger,
        recovery_ledger=recovery_ledger,
        now_provider=moments.__next__,
    )


def run_contract(*, shared_fixture=None) -> None:
    if os.name == "nt":
        return

    owns_fixture = shared_fixture is None
    fixture = lineage_contract._build_fixture() if owns_fixture else shared_fixture
    auth_temp = None
    completed_temp = None
    try:
        auth_temp, authorization, _ready = tx_contract._authorization(fixture)
        authorization_ledger = _auth_ledger(auth_temp)

        completed_temp, completed_ledger = tx_contract._ledger(
            "rsi-product-start-recovery-completed-tx-"
        )
        completed = tx_contract._execute(authorization, completed_ledger)
        assert completed.transaction_authenticated is True
        key = completed.transaction_key_sha256

        recovery_temp, recovery_ledger = _recovery_ledger(
            "rsi-product-start-recovery-completed-"
        )
        try:
            receipt = _recover(
                key,
                completed_ledger,
                authorization_ledger,
                recovery_ledger,
            )
            assert receipt.recovery_authenticated is True
            assert receipt.recovery_state_class == "completed_verified"
            assert receipt.recovered_start_transaction_receipt_sha256 == completed.sha256
            assert receipt.transaction_lock_verified is True
            assert receipt.durable_start_authorization_verified is True
            assert receipt.double_observation_matched is True
            assert receipt.recovery_classification_verified is True
            assert receipt.start_receipt_verified is True
            assert receipt.product_pilot_start_authorized is False
            assert receipt.product_pilot_started is True
            assert receipt.reserved_start_not_started is False
            assert receipt.manual_intervention_required is False
            assert receipt.task_execution_authorized is False
            assert receipt.remote_write_authorized is False
            assert receipt.production_activation_authorized is False
            assert receipt.nonce_reusable is False
            assert receipt.next_boundary_execution_authorization_required is True

            live = recovery._get_live_recovery_inputs(receipt)
            assert live is not None
            recovered_tx = live["recovered_start_transaction"]
            assert recovered_tx is not None
            assert recovered_tx.sha256 == completed.sha256
            assert recovered_tx.transaction_authenticated is False

            serialized = recovery.PilotExactTaskProductPilotStartRecoveryReceipt.from_mapping(
                receipt.to_dict()
            )
            assert serialized == receipt
            assert serialized.recovery_authenticated is False

            _reject(
                lambda: _recover(
                    key,
                    completed_ledger,
                    authorization_ledger,
                    recovery_ledger,
                )
            )
        finally:
            recovery_temp.cleanup()

        lock_temp, lock_ledger = tx_contract._ledger(
            "rsi-product-start-recovery-lock-only-tx-"
        )
        try:
            moments = iter(("2026-09-15T09:58:40Z", "2026-09-15T09:58:42Z"))
            _reject(lambda: tx_contract._execute(authorization, lock_ledger, moments))
            lock_key = start_tx._transaction_key(authorization)
            final_path, lock_path = lock_ledger._paths(lock_key)
            assert lock_path.exists()
            assert not final_path.exists()

            lock_recovery_temp, lock_recovery_ledger = _recovery_ledger(
                "rsi-product-start-recovery-lock-only-"
            )
            try:
                lock_receipt = _recover(
                    lock_key,
                    lock_ledger,
                    authorization_ledger,
                    lock_recovery_ledger,
                )
                assert lock_receipt.recovery_state_class == "reserved_not_started"
                assert lock_receipt.recovered_start_transaction_receipt_sha256 is None
                assert lock_receipt.start_receipt_verified is False
                assert lock_receipt.product_pilot_start_authorized is False
                assert lock_receipt.product_pilot_started is False
                assert lock_receipt.reserved_start_not_started is True
                assert lock_receipt.manual_intervention_required is True
                assert lock_receipt.task_execution_authorized is False
                assert lock_receipt.next_boundary_execution_authorization_required is False
                live = recovery._get_live_recovery_inputs(lock_receipt)
                assert live is not None
                assert live["recovered_start_transaction"] is None
            finally:
                lock_recovery_temp.cleanup()
        finally:
            lock_temp.cleanup()

        tamper_temp, tamper_ledger = tx_contract._ledger(
            "rsi-product-start-recovery-tamper-tx-"
        )
        try:
            moments = iter(("2026-09-15T09:58:40Z", "2026-09-15T09:58:42Z"))
            _reject(lambda: tx_contract._execute(authorization, tamper_ledger, moments))
            tamper_key = start_tx._transaction_key(authorization)
            _final, lock_path = tamper_ledger._paths(tamper_key)
            raw = json.loads(lock_path.read_text(encoding="utf-8"))
            raw["product_pilot_start_readiness_sha256"] = "f" * 64
            lock_path.write_text(
                json.dumps(
                    raw,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            tamper_recovery_temp, tamper_recovery_ledger = _recovery_ledger(
                "rsi-product-start-recovery-tamper-"
            )
            try:
                _reject(
                    lambda: _recover(
                        tamper_key,
                        tamper_ledger,
                        authorization_ledger,
                        tamper_recovery_ledger,
                    )
                )
                assert tuple(tamper_recovery_ledger.root.iterdir()) == ()
            finally:
                tamper_recovery_temp.cleanup()
        finally:
            tamper_temp.cleanup()

        field_recovery_temp, field_recovery_ledger = _recovery_ledger(
            "rsi-product-start-recovery-fields-"
        )
        try:
            receipt = _recover(
                key,
                completed_ledger,
                authorization_ledger,
                field_recovery_ledger,
            )
            for field in (
                "product_pilot_start_authorized",
                "task_execution_authorized",
                "local_commit_authorized",
                "remote_write_authorized",
                "push_authorized",
                "pr_mutation_authorized",
                "merge_authorized",
                "release_authorized",
                "deploy_authorized",
                "production_activation_authorized",
                "nonce_reusable",
            ):
                raw = receipt.to_dict()
                raw[field] = True
                _reject(
                    lambda raw=raw: recovery.PilotExactTaskProductPilotStartRecoveryReceipt.from_mapping(
                        raw
                    )
                )
        finally:
            field_recovery_temp.cleanup()
    finally:
        if completed_temp is not None:
            completed_temp.cleanup()
        if auth_temp is not None:
            auth_temp.cleanup()
        if owns_fixture:
            lineage_contract._cleanup(fixture)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(
        recovery.PilotExactTaskProductPilotStartRecoveryReceipt.__dataclass_fields__
    )
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields
    assert schema["additionalProperties"] is False

    public = inspect.signature(
        recovery.recover_pilot_exact_task_product_pilot_start
    )
    assert tuple(public.parameters) == ("transaction_key_sha256",)

    source = code_of(SOURCE).lower()
    for forbidden in (
        "subprocess.",
        "urllib.",
        "requests.",
        "http.client",
        "socket.",
        "execute_pilot_exact_task_product_pilot_start(",
        "ledger.commit(",
        "unlink(",
        "rename(",
    ):
        assert forbidden not in source
    assert "create_once_file" in source


if __name__ == "__main__":
    run_contract()
