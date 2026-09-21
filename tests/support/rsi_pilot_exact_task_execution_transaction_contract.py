"""Adversarial contract for ADR-DC-039 exact one-shot Tier-A execution."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_execution_plan as execution_plan,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_execution_transaction as execution_transaction,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_prelaunch_reservation as prelaunch,
)
from kaliv_dev_control.tier_a_command_receipt import (  # noqa: E402
    TierACommandReceipt,
)
from kaliv_dev_control.tier_a_result import (  # noqa: E402
    TierAExecutionResult,
    TierAOutputStream,
)
from kaliv_dev_control.trusted_git_runtime import (  # noqa: E402
    TrustedGitRuntimeEvidence,
)
from rsi_pilot_exact_task_execution_plan_contract import _git_reader  # noqa: E402
from rsi_pilot_exact_task_prelaunch_reservation_contract import (  # noqa: E402
    _drift_after_first_snapshot_reader,
    _plan_fixture,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-execution-transaction-receipt-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-039 unexpectedly accepted invalid authority")


def _live_reservation():
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        plan,
        task,
        fixture,
        staged,
    ) = _plan_fixture()
    reservation_temp = tempfile.TemporaryDirectory(
        prefix="rsi-execution-transaction-reservation-"
    )
    ledger = prelaunch._PilotExactTaskPrelaunchReservationLedger(
        Path(reservation_temp.name).resolve()
    )
    _calls, reader = _git_reader(
        workspace=fixture["workspace"],
        base_sha=task.base_sha,
        staged=staged,
    )
    times = iter(("2026-09-15T00:10:00Z", "2026-09-15T00:10:01Z"))
    with patch.object(fixture["git_runner"], "run", side_effect=reader):
        reservation = prelaunch._reserve_verified_exact_task_prelaunch(
            execution_plan=plan,
            ledger=ledger,
            now_provider=lambda: next(times),
        )
    assert reservation.reservation_authenticated is True
    return (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        reservation,
        plan,
        task,
        fixture,
        staged,
    )


def _stream(payload: bytes = b"") -> TierAOutputStream:
    return TierAOutputStream(
        captured=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
        total_bytes=len(payload),
        truncated=False,
    )


def _tier_a_receipt(plan, task) -> TierACommandReceipt:
    task_sha = hashlib.sha256(task.canonical_json().encode("utf-8")).hexdigest()
    capability = plan.executor_capability
    runtime = TrustedGitRuntimeEvidence(
        runtime_manifest_sha256=capability.trusted_git_runtime_manifest_sha256,
        runtime_file_count=3,
        runtime_bytes=4096,
        executable_sha256="9" * 64,
        version="git version adr-dc-039-fixture",
        exec_path_relative_path="libexec/git-core",
        path_relative_directories=("bin", "libexec/git-core"),
        library_relative_directories=("lib",),
    )
    result = TierAExecutionResult.create(
        task_id=task.task_id,
        task_sha256=task_sha,
        base_sha=task.base_sha,
        command_id=plan.fixed_command_id,
        plan_sha256="6" * 64,
        lease_sha256=capability.lease_sha256,
        signed_report_sha256=capability.physical_report_sha256,
        returncode=0,
        duration_ms=25,
        timed_out=False,
        max_output_bytes=plan.fixed_command_plan.max_output_bytes,
        stdout=_stream(b"ok\n"),
        stderr=_stream(),
    )
    return TierACommandReceipt.create(
        task=task,
        git_runtime=runtime,
        result=result,
        before=plan.workspace_snapshot,
        after=plan.workspace_snapshot,
        reset=None,
    )


def run_contract() -> None:
    if os.name == "nt":
        # Synthetic Trusted-Git fixture is POSIX-only. Native Windows execution
        # remains covered by the existing Tier-A/Windows jobs.
        return

    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        reservation,
        plan,
        task,
        fixture,
        staged,
    ) = _live_reservation()
    execution_temp = tempfile.TemporaryDirectory(
        prefix="rsi-execution-transaction-"
    )
    try:
        ledger = execution_transaction._PilotExactTaskExecutionTransactionLedger(
            Path(execution_temp.name).resolve()
        )
        tier_a = _tier_a_receipt(plan, task)
        calls, reader = _git_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
        )

        def execute(*args, **kwargs):
            lock = (
                Path(execution_temp.name).resolve()
                / f".{reservation.execution_nonce_sha256}.lock"
            )
            assert lock.is_file(), "executor ran before permanent nonce consumption"
            assert args[0] == task
            assert kwargs["git_runner"] is fixture["git_runner"]
            assert kwargs["workspace_root"] == fixture["workspace"]
            assert kwargs["control_plane_root"] == fixture["control"]
            assert kwargs["process_memory_bytes"] == plan.executor_capability.process_memory_bytes
            assert kwargs["active_process_limit"] == plan.executor_capability.active_process_limit
            return tier_a

        times = iter(
            (
                "2026-09-15T00:20:00Z",
                "2026-09-15T00:20:01Z",
                "2026-09-15T00:20:02Z",
            )
        )
        with patch.object(
            fixture["git_runner"],
            "run",
            side_effect=reader,
        ), patch.object(
            execution_transaction,
            "run_single_verified_tier_a_command_with_receipt",
            side_effect=execute,
        ) as mocked:
            receipt = execution_transaction._execute_reserved_exact_task(
                prelaunch_reservation=reservation,
                ledger=ledger,
                now_provider=lambda: next(times),
            )

        assert mocked.call_count == 1
        assert len(calls) == 10
        assert receipt.transaction_authenticated is True
        assert receipt.consumption_key_sha256 == reservation.execution_nonce_sha256
        assert receipt.prelaunch_reservation_sha256 == reservation.sha256
        assert receipt.execution_plan_sha256 == plan.sha256
        assert receipt.executor_capability_sha256 == plan.executor_capability_sha256
        assert receipt.admission_receipt_sha256 == plan.admission_receipt_sha256
        assert receipt.development_task_sha256 == plan.development_task_sha256
        assert receipt.fixed_command_plan_sha256 == plan.fixed_command_plan_sha256
        assert receipt.workspace_snapshot_sha256 == plan.workspace_snapshot_sha256
        assert receipt.tier_a_receipt == tier_a
        assert receipt.tier_a_receipt_sha256 == tier_a.sha256
        assert receipt.host_replay_guard_committed is True
        assert receipt.execution_consumed is True
        assert receipt.task_execution_started is True
        assert receipt.task_execution_completed is True
        assert receipt.task_execution_passed is True
        assert receipt.local_commit_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.production_activation_authorized is False

        reloaded = (
            execution_transaction.PilotExactTaskExecutionTransactionReceipt.from_mapping(
                receipt.to_dict()
            )
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.transaction_authenticated is False

        _reject(
            lambda: execution_transaction.PilotExactTaskExecutionTransactionReceipt.from_mapping(
                {**receipt.to_dict(), "execution_consumed": False}
            )
        )
        _reject(
            lambda: execution_transaction.PilotExactTaskExecutionTransactionReceipt.from_mapping(
                {**receipt.to_dict(), "task_execution_started": False}
            )
        )
        _reject(
            lambda: execution_transaction.PilotExactTaskExecutionTransactionReceipt.from_mapping(
                {**receipt.to_dict(), "local_commit_authorized": True}
            )
        )
        _reject(
            lambda: execution_transaction.PilotExactTaskExecutionTransactionReceipt.from_mapping(
                {**receipt.to_dict(), "production_activation_authorized": True}
            )
        )

        # Same canonical consumption ledger can never execute the nonce twice.
        replay_calls, replay_reader = _git_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
        )
        with patch.object(
            fixture["git_runner"], "run", side_effect=replay_reader
        ), patch.object(
            execution_transaction,
            "run_single_verified_tier_a_command_with_receipt",
            return_value=tier_a,
        ) as replay_executor:
            _reject(
                lambda: execution_transaction._execute_reserved_exact_task(
                    prelaunch_reservation=reservation,
                    ledger=ledger,
                    now_provider=lambda: "2026-09-15T00:20:03Z",
                )
            )
        assert replay_calls
        assert replay_executor.call_count == 0

        # Reloaded ADR-DC-038 evidence cannot recover live executor authority.
        replayed_reservation = (
            prelaunch.PilotExactTaskPrelaunchReservationReceipt.from_mapping(
                reservation.to_dict()
            )
        )
        assert replayed_reservation.reservation_authenticated is False
        reloaded_temp = tempfile.TemporaryDirectory(
            prefix="rsi-execution-transaction-reloaded-"
        )
        try:
            reloaded_ledger = (
                execution_transaction._PilotExactTaskExecutionTransactionLedger(
                    Path(reloaded_temp.name).resolve()
                )
            )
            _reject(
                lambda: execution_transaction._execute_reserved_exact_task(
                    prelaunch_reservation=replayed_reservation,
                    ledger=reloaded_ledger,
                    now_provider=lambda: "2026-09-15T00:21:00Z",
                )
            )
        finally:
            reloaded_temp.cleanup()

        # Drift after permanent consumption burns the nonce fail-closed and the
        # executor must never run. A later clean retry remains refused.
        drift_temp = tempfile.TemporaryDirectory(
            prefix="rsi-execution-transaction-drift-"
        )
        try:
            drift_ledger = (
                execution_transaction._PilotExactTaskExecutionTransactionLedger(
                    Path(drift_temp.name).resolve()
                )
            )
            drift_calls, drift_reader = _drift_after_first_snapshot_reader(
                workspace=fixture["workspace"],
                base_sha=task.base_sha,
                staged=staged,
            )
            with patch.object(
                fixture["git_runner"], "run", side_effect=drift_reader
            ), patch.object(
                execution_transaction,
                "run_single_verified_tier_a_command_with_receipt",
                return_value=tier_a,
            ) as drift_executor:
                _reject(
                    lambda: execution_transaction._execute_reserved_exact_task(
                        prelaunch_reservation=reservation,
                        ledger=drift_ledger,
                        now_provider=lambda: "2026-09-15T00:22:00Z",
                    )
                )
            assert drift_calls
            assert drift_executor.call_count == 0
            drift_lock = (
                Path(drift_temp.name).resolve()
                / f".{reservation.execution_nonce_sha256}.lock"
            )
            assert drift_lock.is_file()

            clean_calls, clean_reader = _git_reader(
                workspace=fixture["workspace"],
                base_sha=task.base_sha,
                staged=staged,
            )
            with patch.object(
                fixture["git_runner"], "run", side_effect=clean_reader
            ), patch.object(
                execution_transaction,
                "run_single_verified_tier_a_command_with_receipt",
                return_value=tier_a,
            ) as clean_executor:
                _reject(
                    lambda: execution_transaction._execute_reserved_exact_task(
                        prelaunch_reservation=reservation,
                        ledger=drift_ledger,
                        now_provider=lambda: "2026-09-15T00:22:01Z",
                    )
                )
            assert clean_calls
            assert clean_executor.call_count == 0
        finally:
            drift_temp.cleanup()

        # If the hardened executor fails after the consume marker, there is no
        # automatic retry. The permanent marker remains recovery evidence.
        crash_temp = tempfile.TemporaryDirectory(
            prefix="rsi-execution-transaction-crash-"
        )
        try:
            crash_ledger = (
                execution_transaction._PilotExactTaskExecutionTransactionLedger(
                    Path(crash_temp.name).resolve()
                )
            )
            crash_calls, crash_reader = _git_reader(
                workspace=fixture["workspace"],
                base_sha=task.base_sha,
                staged=staged,
            )
            crash_times = iter(
                ("2026-09-15T00:23:00Z", "2026-09-15T00:23:01Z")
            )
            with patch.object(
                fixture["git_runner"], "run", side_effect=crash_reader
            ), patch.object(
                execution_transaction,
                "run_single_verified_tier_a_command_with_receipt",
                side_effect=RuntimeError("synthetic executor loss"),
            ) as crash_executor:
                _reject(
                    lambda: execution_transaction._execute_reserved_exact_task(
                        prelaunch_reservation=reservation,
                        ledger=crash_ledger,
                        now_provider=lambda: next(crash_times),
                    )
                )
            assert crash_executor.call_count == 1
            crash_lock = (
                Path(crash_temp.name).resolve()
                / f".{reservation.execution_nonce_sha256}.lock"
            )
            assert crash_lock.is_file()

            retry_calls, retry_reader = _git_reader(
                workspace=fixture["workspace"],
                base_sha=task.base_sha,
                staged=staged,
            )
            with patch.object(
                fixture["git_runner"], "run", side_effect=retry_reader
            ), patch.object(
                execution_transaction,
                "run_single_verified_tier_a_command_with_receipt",
                return_value=tier_a,
            ) as retry_executor:
                _reject(
                    lambda: execution_transaction._execute_reserved_exact_task(
                        prelaunch_reservation=reservation,
                        ledger=crash_ledger,
                        now_provider=lambda: "2026-09-15T00:23:02Z",
                    )
                )
            assert retry_calls
            assert retry_executor.call_count == 0
        finally:
            crash_temp.cleanup()

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert props["execution_consumed"]["const"] is True
        assert props["task_execution_started"]["const"] is True
        assert props["task_execution_completed"]["const"] is True
        assert props["local_commit_authorized"]["const"] is False
        assert props["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            execution_transaction.execute_pilot_exact_task
        ).parameters
        assert tuple(public_parameters) == ("prelaunch_reservation",)

        source = inspect.getsource(execution_transaction)
        assert "run_single_verified_tier_a_command_with_receipt(" in source
        assert "run_verified_tier_a_command(" not in source
        assert "subprocess" not in source
        assert "shell=True" not in source
        assert ".reset_to_base(" not in source
        assert '("reset",' not in source
        assert '("clean",' not in source
    finally:
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
