"""Adversarial contract for ADR-DC-038 exact pre-launch reservation."""
from __future__ import annotations

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
    improvement_pilot_exact_task_prelaunch_reservation as prelaunch,
)
from rsi_pilot_exact_task_execution_plan_contract import (  # noqa: E402
    _git_reader,
    _materialized_capability,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-prelaunch-reservation-receipt-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-038 unexpectedly accepted invalid authority")


def _plan_fixture():
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        capability,
        task,
        fixture,
    ) = _materialized_capability()
    workspace = fixture["workspace"]
    (workspace / ".git").mkdir(exist_ok=True)
    staged = (
        b"diff --git a/VERSION b/VERSION\n"
        b"index 1111111..2222222 100644\n"
        b"--- a/VERSION\n"
        b"+++ b/VERSION\n"
        b"@@ -1 +1 @@\n"
        b"-old\n"
        b"+new\n"
    )
    _calls, reader = _git_reader(
        workspace=workspace,
        base_sha=task.base_sha,
        staged=staged,
    )
    with patch.object(fixture["git_runner"], "run", side_effect=reader):
        plan = execution_plan.materialize_pilot_exact_task_execution_plan(capability)
    assert plan.materialization_authenticated is True
    return (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        plan,
        task,
        fixture,
        staged,
    )


def _drift_after_first_snapshot_reader(
    *, workspace: Path, base_sha: str, staged: bytes
):
    snapshot_number = 0
    calls: list[tuple[str, ...]] = []

    def run(args, *, cwd, **_kwargs):
        nonlocal snapshot_number
        args = tuple(args)
        calls.append(args)
        assert Path(cwd) == workspace
        if args == ("rev-parse", "--show-toplevel"):
            snapshot_number += 1
            return (os.fspath(workspace) + "\n").encode("utf-8")
        if args == ("rev-parse", "HEAD"):
            sha = base_sha if snapshot_number == 1 else "f" * 40
            return (sha + "\n").encode("ascii")
        if args == (
            "diff",
            "--cached",
            "--binary",
            "--full-index",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            "--",
        ):
            return staged
        if args == (
            "diff",
            "--binary",
            "--full-index",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            "--",
        ):
            return b""
        if args == ("ls-files", "--others", "--exclude-standard", "-z"):
            return b""
        raise AssertionError(
            f"ADR-DC-038 attempted unexpected Git command: {args!r}"
        )

    return calls, run


def run_contract() -> None:
    if os.name == "nt":
        return
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
        prefix="rsi-prelaunch-reservation-"
    )
    try:
        ledger = prelaunch._PilotExactTaskPrelaunchReservationLedger(
            Path(reservation_temp.name).resolve()
        )
        calls, reader = _git_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
        )
        times = iter(
            ("2026-09-14T20:30:00Z", "2026-09-14T20:30:01Z")
        )
        with patch.object(fixture["git_runner"], "run", side_effect=reader):
            receipt = prelaunch._reserve_verified_exact_task_prelaunch(
                execution_plan=plan,
                ledger=ledger,
                now_provider=lambda: next(times),
            )
        assert len(calls) == 10
        assert receipt.reservation_authenticated is True
        assert receipt.reservation_key_sha256 == plan.execution_nonce_sha256
        assert receipt.execution_plan_sha256 == plan.sha256
        assert receipt.executor_capability_sha256 == plan.executor_capability_sha256
        assert receipt.admission_receipt_sha256 == plan.admission_receipt_sha256
        assert receipt.development_task_sha256 == plan.development_task_sha256
        assert receipt.fixed_command_plan_sha256 == plan.fixed_command_plan_sha256
        assert receipt.workspace_snapshot_sha256 == plan.workspace_snapshot_sha256
        assert receipt.host_replay_guard_committed is True
        assert receipt.prelaunch_execution_reserved is True
        assert receipt.execution_consumed is False
        assert receipt.task_execution_started is False
        assert receipt.task_execution_completed is False
        assert receipt.local_commit_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.production_activation_authorized is False

        reloaded = prelaunch.PilotExactTaskPrelaunchReservationReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.reservation_authenticated is False

        _reject(
            lambda: prelaunch.PilotExactTaskPrelaunchReservationReceipt.from_mapping(
                {**receipt.to_dict(), "execution_consumed": True}
            )
        )
        _reject(
            lambda: prelaunch.PilotExactTaskPrelaunchReservationReceipt.from_mapping(
                {**receipt.to_dict(), "task_execution_started": True}
            )
        )
        _reject(
            lambda: prelaunch.PilotExactTaskPrelaunchReservationReceipt.from_mapping(
                {
                    **receipt.to_dict(),
                    "production_activation_authorized": True,
                }
            )
        )
        _reject(
            lambda: prelaunch.PilotExactTaskPrelaunchReservationReceipt.from_mapping(
                {**receipt.to_dict(), "reservation_key_sha256": "a" * 64}
            )
        )

        replay_calls, replay_reader = _git_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
        )
        with patch.object(
            fixture["git_runner"], "run", side_effect=replay_reader
        ):
            _reject(
                lambda: prelaunch._reserve_verified_exact_task_prelaunch(
                    execution_plan=plan,
                    ledger=ledger,
                    now_provider=lambda: "2026-09-14T20:30:02Z",
                )
            )
        assert replay_calls

        replayed_plan = execution_plan.PilotExactTaskExecutionPlan.from_mapping(
            plan.to_dict()
        )
        assert replayed_plan.materialization_authenticated is False
        second_ledger_temp = tempfile.TemporaryDirectory(
            prefix="rsi-prelaunch-replay-"
        )
        try:
            second_ledger = prelaunch._PilotExactTaskPrelaunchReservationLedger(
                Path(second_ledger_temp.name).resolve()
            )
            _reject(
                lambda: prelaunch._reserve_verified_exact_task_prelaunch(
                    execution_plan=replayed_plan,
                    ledger=second_ledger,
                    now_provider=lambda: "2026-09-14T20:31:00Z",
                )
            )
        finally:
            second_ledger_temp.cleanup()

        drift_temp = tempfile.TemporaryDirectory(prefix="rsi-prelaunch-drift-")
        try:
            drift_ledger = prelaunch._PilotExactTaskPrelaunchReservationLedger(
                Path(drift_temp.name).resolve()
            )
            drift_calls, drift_reader = _drift_after_first_snapshot_reader(
                workspace=fixture["workspace"],
                base_sha=task.base_sha,
                staged=staged,
            )
            with patch.object(
                fixture["git_runner"], "run", side_effect=drift_reader
            ):
                _reject(
                    lambda: prelaunch._reserve_verified_exact_task_prelaunch(
                        execution_plan=plan,
                        ledger=drift_ledger,
                        now_provider=lambda: "2026-09-14T20:32:00Z",
                    )
                )
            assert drift_calls
            lock = (
                Path(drift_temp.name).resolve()
                / f".{plan.execution_nonce_sha256}.lock"
            )
            assert lock.is_file()

            clean_calls, clean_reader = _git_reader(
                workspace=fixture["workspace"],
                base_sha=task.base_sha,
                staged=staged,
            )
            with patch.object(
                fixture["git_runner"], "run", side_effect=clean_reader
            ):
                _reject(
                    lambda: prelaunch._reserve_verified_exact_task_prelaunch(
                        execution_plan=plan,
                        ledger=drift_ledger,
                        now_provider=lambda: "2026-09-14T20:32:01Z",
                    )
                )
            assert clean_calls
        finally:
            drift_temp.cleanup()

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert props["prelaunch_execution_reserved"]["const"] is True
        assert props["execution_consumed"]["const"] is False
        assert props["task_execution_started"]["const"] is False
        assert props["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            prelaunch.reserve_pilot_exact_task_prelaunch
        ).parameters
        assert tuple(public_parameters) == ("execution_plan",)

        source = inspect.getsource(prelaunch)
        assert "run_verified_tier_a_command" not in source
        assert "run_single_verified_tier_a_command_with_receipt" not in source
        assert "subprocess" not in source
        assert "shell=True" not in source
        assert ".reset_to_base(" not in source
        assert '("reset",' not in source
        assert '("clean",' not in source
    finally:
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
