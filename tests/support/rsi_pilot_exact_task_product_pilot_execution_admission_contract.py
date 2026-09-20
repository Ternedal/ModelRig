"""Adversarial contract for ADR-DC-104 product-pilot execution admission."""
from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from source_code import code_of  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_execution_admission as admission  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_start_transaction as start_tx  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_start_recovery as start_recovery  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_start_readiness as readiness  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_task_registry as registry  # noqa: E402
import rsi_pilot_exact_task_product_pilot_start_transaction_contract as tx_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_start_recovery_contract as recovery_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_task_registry_contract as registry_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_lineage_attestation_contract as lineage_contract  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-product-pilot-execution-admission-v1.schema.json"
)
SOURCE = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "improvement_pilot_exact_task_product_pilot_execution_admission.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError, AttributeError):
        return
    raise AssertionError("ADR-DC-104 unexpectedly accepted unsafe execution admission")


def _registry_payload_from_ready(ready):
    live = readiness._get_live_readiness_source(ready)
    assert live is not None
    task_registry = live["task_registry"]
    registry_live = registry._get_live_product_pilot_task_registry_inputs(task_registry)
    assert registry_live is not None
    lineage = registry_live["lineage_attestation"]
    payload, development_task, task_sha = registry_contract._host_registry(lineage)
    assert task_sha == task_registry.development_task_sha256
    return payload, development_task, task_registry


def _start(fixture):
    auth_temp, authorization, ready = tx_contract._authorization(fixture)
    tx_temp, tx_ledger = tx_contract._ledger("rsi-product-execution-admission-start-")
    start = tx_contract._execute(authorization, tx_ledger)
    payload, development_task, task_registry = _registry_payload_from_ready(ready)
    return (
        auth_temp,
        tx_temp,
        tx_ledger,
        start,
        ready,
        payload,
        development_task,
        task_registry,
    )


def run_contract(*, shared_fixture=None) -> None:
    if os.name == "nt":
        return

    owns_fixture = shared_fixture is None
    fixture = lineage_contract._build_fixture() if owns_fixture else shared_fixture
    auth_temp = None
    tx_temp = None
    try:
        (
            auth_temp,
            tx_temp,
            tx_ledger,
            start,
            ready,
            registry_payload,
            development_task,
            task_registry,
        ) = _start(fixture)

        receipt = admission._build_verified_product_pilot_execution_admission(
            start_state=start,
            registry_payload=registry_payload,
            now_provider=lambda: "2026-09-15T09:55:00Z",
        )
        assert receipt.admission_authenticated is True
        assert receipt.start_state_source_type == "start_transaction"
        assert receipt.start_state_source_sha256 == start.sha256
        assert receipt.start_transaction_receipt_sha256 == start.sha256
        assert receipt.product_pilot_start_readiness_sha256 == ready.sha256
        assert receipt.host_development_task_registry_sha256 == task_registry.host_development_task_registry_sha256
        assert receipt.development_task_id == development_task.task_id
        assert receipt.development_task_sha256 == task_registry.development_task_sha256
        assert receipt.development_task_base_sha == development_task.base_sha
        assert receipt.fixed_command_id == task_registry.fixed_command_id
        assert receipt.selected_pilot_task_id == task_registry.selected_pilot_task_id
        assert receipt.source_age_seconds == 9
        assert receipt.start_state_authenticated is True
        assert receipt.host_development_task_registry_reverified is True
        assert receipt.exact_development_task_reverified is True
        assert receipt.single_fixed_command_reverified is True
        assert receipt.executor_capability_materialization_authorized is True
        assert receipt.execution_plan_materialization_authorized is False
        assert receipt.task_execution_authorized is False
        assert receipt.local_commit_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.next_boundary_executor_capability_required is True

        live = admission._get_live_execution_admission_inputs(receipt)
        assert live is not None
        assert live["start_state"] is start
        assert live["start_transaction"] is start
        assert live["development_task"] == development_task

        serialized = admission.PilotExactTaskProductPilotExecutionAdmissionReceipt.from_mapping(
            receipt.to_dict()
        )
        assert serialized == receipt
        assert serialized.admission_authenticated is False

        replayed_start = start_tx.PilotExactTaskProductPilotStartTransactionReceipt.from_mapping(
            start.to_dict()
        )
        assert replayed_start.transaction_authenticated is False
        _reject(
            lambda: admission._build_verified_product_pilot_execution_admission(
                start_state=replayed_start,
                registry_payload=registry_payload,
                now_provider=lambda: "2026-09-15T09:55:00Z",
            )
        )

        _reject(
            lambda: admission._build_verified_product_pilot_execution_admission(
                start_state=start,
                registry_payload=registry_payload,
                now_provider=lambda: "2026-09-15T09:55:52Z",
            )
        )

        wrong = json.loads(registry_payload.decode("utf-8"))
        wrong["entries"][0]["development_task"]["goal"] = "tampered task"
        wrong_payload = json.dumps(
            wrong,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        _reject(
            lambda: admission._build_verified_product_pilot_execution_admission(
                start_state=start,
                registry_payload=wrong_payload,
                now_provider=lambda: "2026-09-15T09:55:00Z",
            )
        )

        auth_ledger = recovery_contract._auth_ledger(auth_temp)
        recovery_temp, recovery_ledger = recovery_contract._recovery_ledger(
            "rsi-product-execution-admission-recovery-"
        )
        try:
            recovered = recovery_contract._recover(
                start.transaction_key_sha256,
                tx_ledger,
                auth_ledger,
                recovery_ledger,
            )
            assert recovered.recovery_state_class == "completed_verified"
            recovered_admission = admission._build_verified_product_pilot_execution_admission(
                start_state=recovered,
                registry_payload=registry_payload,
                now_provider=lambda: "2026-09-15T09:59:10Z",
            )
            assert recovered_admission.admission_authenticated is True
            assert recovered_admission.start_state_source_type == "completed_recovery"
            assert recovered_admission.start_state_source_sha256 == recovered.sha256
            assert recovered_admission.start_transaction_receipt_sha256 == start.sha256
            assert recovered_admission.source_age_seconds == 8

            replayed_recovery = (
                start_recovery.PilotExactTaskProductPilotStartRecoveryReceipt.from_mapping(
                    recovered.to_dict()
                )
            )
            assert replayed_recovery.recovery_authenticated is False
            _reject(
                lambda: admission._build_verified_product_pilot_execution_admission(
                    start_state=replayed_recovery,
                    registry_payload=registry_payload,
                    now_provider=lambda: "2026-09-15T09:59:10Z",
                )
            )
        finally:
            recovery_temp.cleanup()

        for field, value in (
            ("executor_capability_materialization_authorized", False),
            ("execution_plan_materialization_authorized", True),
            ("task_execution_authorized", True),
            ("local_commit_authorized", True),
            ("remote_write_authorized", True),
            ("production_activation_authorized", True),
            ("next_boundary_executor_capability_required", False),
            ("nonce_reusable", True),
        ):
            raw = receipt.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: admission.PilotExactTaskProductPilotExecutionAdmissionReceipt.from_mapping(
                    raw
                )
            )
    finally:
        if tx_temp is not None:
            tx_temp.cleanup()
        if auth_temp is not None:
            auth_temp.cleanup()
        if owns_fixture:
            lineage_contract._cleanup(fixture)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(
        admission.PilotExactTaskProductPilotExecutionAdmissionReceipt.__dataclass_fields__
    )
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields
    assert schema["additionalProperties"] is False

    public = inspect.signature(
        admission.admit_pilot_exact_task_product_pilot_execution
    )
    assert tuple(public.parameters) == ("start_state",)

    source = code_of(SOURCE).lower()
    for forbidden in (
        "subprocess.",
        "urllib.",
        "requests.",
        "http.client",
        "socket.",
        "run_verified_tier_a_command",
        "execute_pilot_exact_task(",
        "create_once_file",
        ".write_text(",
        ".write_bytes(",
    ):
        assert forbidden not in source


if __name__ == "__main__":
    run_contract()
