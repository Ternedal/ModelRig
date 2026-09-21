"""Contract for ADR-DC-110 read-only product-pilot execution recovery."""
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

from source_code import code_of  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_executor_capability as capability  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_workspace_snapshot as workspace_snapshot  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_execution_plan as plan  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_execution as execution  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_execution_recovery as recovery  # noqa: E402
from kaliv_dev_control import tier_a_command_receipt as command_receipt_boundary  # noqa: E402
from kaliv_dev_control.runtime_closure_builder import VERSION_CHECK_COMMAND_ID  # noqa: E402
from kaliv_dev_control.tier_a_command_receipt import TierACommandReceipt  # noqa: E402
from kaliv_dev_control.tier_a_result import TierAExecutionResult, TierAOutputStream  # noqa: E402
import rsi_pilot_exact_task_product_pilot_executor_capability_contract as capability_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_lineage_attestation_contract as lineage_contract  # noqa: E402
from rsi_pilot_exact_task_executor_capability_contract import _authority_fixture  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-product-pilot-execution-recovery-v1.schema.json"
)
SOURCE = (
    ROOT / "devcontrol" / "src" / "kaliv_dev_control"
    / "improvement_pilot_exact_task_product_pilot_execution_recovery.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError, AttributeError, RuntimeError):
        return
    raise AssertionError("ADR-DC-110 unexpectedly accepted unsafe recovery state")


def _stream(payload: bytes) -> TierAOutputStream:
    return TierAOutputStream(
        captured=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
        total_bytes=len(payload),
        truncated=False,
    )


def run_contract(*, shared_fixture=None) -> None:
    if os.name == "nt":
        return

    owns_fixture = shared_fixture is None
    fixture = lineage_contract._build_fixture() if owns_fixture else shared_fixture
    auth_temp = None
    tx_temp = None
    capability_temp = None
    completed_temp = None
    pending_temp = None
    lock_only_temp = None
    coexist_temp = None
    git_run_patch = None
    try:
        auth_temp, tx_temp, admitted, task = capability_contract._admission(fixture)
        capability_temp = tempfile.TemporaryDirectory(
            prefix="rsi-product-pilot-execution-recovery-capability-"
        )
        authority = _authority_fixture(Path(capability_temp.name).resolve(), task)
        original_path_sha = capability._path_sha256

        def scoped_path_sha(path: Path) -> str:
            if Path(path) == authority["workspace"]:
                return admitted.workspace_root_path_sha256
            return original_path_sha(Path(path))

        executor_capability = capability._materialize_verified_product_pilot_executor_capability(
            execution_admission=admitted,
            catalog=authority["catalog"],
            toolchain=authority["toolchain"],
            isolation_attestation=authority["attestation"],
            physical_verifier=authority["physical_verifier"],
            signed_runtime_closure=authority["signed_closure"],
            runtime_closure_verifier=authority["runtime_verifier"],
            trusted_runtime_root=authority["trusted"],
            git_runner=authority["git_runner"],
            workspace_root=authority["workspace"],
            control_plane_root=authority["control"],
            path_sha256=scoped_path_sha,
        )

        workspace = authority["workspace"]
        (workspace / ".git").mkdir()

        def git_read(args, **kwargs):
            del kwargs
            if args == ("--version",):
                return b"git version adr-dc-110-fixture\n"
            if args == ("rev-parse", "--show-toplevel"):
                return (os.fspath(workspace) + "\n").encode("utf-8")
            if args == ("rev-parse", "HEAD"):
                return (task.base_sha + "\n").encode("ascii")
            if args[0] == "diff":
                return b""
            if args == ("ls-files", "--others", "--exclude-standard", "-z"):
                return b""
            raise AssertionError(f"unexpected trusted Git command: {args!r}")

        git_run_patch = patch.object(
            authority["git_runner"], "run", side_effect=git_read
        )
        git_run_patch.start()

        frozen = workspace_snapshot.materialize_pilot_exact_task_product_pilot_workspace_snapshot(
            executor_capability
        )
        execution_plan = plan.materialize_pilot_exact_task_product_pilot_execution_plan(
            frozen
        )
        result = TierAExecutionResult.create(
            task_id=task.task_id,
            task_sha256=execution_plan.development_task_sha256,
            base_sha=task.base_sha,
            command_id=VERSION_CHECK_COMMAND_ID,
            plan_sha256=execution_plan.sha256,
            lease_sha256=execution_plan.lease_sha256,
            signed_report_sha256=execution_plan.physical_report_sha256,
            returncode=0,
            duration_ms=5,
            timed_out=False,
            max_output_bytes=task.budget.max_output_bytes,
            stdout=_stream(b"2.0.13\n"),
            stderr=_stream(b""),
        )
        tier_a_receipt = TierACommandReceipt.create(
            task=task,
            git_runtime=authority["git_runner"].evidence(),
            result=result,
            before=execution_plan.workspace_snapshot,
            after=execution_plan.workspace_snapshot,
            reset=None,
        )

        completed_temp = tempfile.TemporaryDirectory(
            prefix="rsi-product-pilot-recovery-completed-"
        )
        completed_ledger = execution._PilotExactTaskProductPilotExecutionLedger(
            Path(completed_temp.name).resolve()
        )
        times = iter(
            (
                "2026-09-20T22:00:00Z",
                "2026-09-20T22:00:01Z",
                "2026-09-20T22:00:02Z",
            )
        )
        with patch.object(
            command_receipt_boundary,
            "run_single_verified_tier_a_command_with_receipt",
            return_value=tier_a_receipt,
        ):
            completed_execution = (
                execution._execute_verified_pilot_exact_task_product_pilot_plan(
                    execution_plan=execution_plan,
                    ledger=completed_ledger,
                    now_provider=lambda: next(times),
                )
            )

        completed = recovery._classify_verified_execution_recovery(
            execution_nonce_sha256=execution_plan.execution_nonce_sha256,
            ledger=completed_ledger,
        )
        assert completed.recovery_state_class == "completed_verified"
        assert completed.recovered_execution_receipt_sha256 == completed_execution.sha256
        assert completed.final_receipt_verified is True
        assert completed.pending_receipt_verified is False
        assert completed.execution_nonce_consumed is True
        assert completed.retry_authorized is False
        assert completed.task_execution_authorized is False
        assert completed.manual_intervention_required is True
        assert completed.nonce_reusable is False
        assert completed.recovery_authenticated is True

        completed_final, _, completed_lock = completed_ledger._paths(
            execution_plan.execution_nonce_sha256
        )
        completed_final_payload = completed_final.read_bytes()
        completed_final.write_bytes(b"{}")
        assert completed.recovery_authenticated is False
        completed_final.write_bytes(completed_final_payload)
        assert completed.recovery_authenticated is True

        completed_lock_payload = completed_lock.read_bytes()
        completed_lock.write_bytes(b"{}")
        assert completed.recovery_authenticated is False
        completed_lock.write_bytes(completed_lock_payload)
        assert completed.recovery_authenticated is True

        # Pending-only state: exact canonical ADR-DC-108 receipt exists in the
        # pending slot but final publication did not complete.
        pending_temp = tempfile.TemporaryDirectory(
            prefix="rsi-product-pilot-recovery-pending-"
        )
        pending_ledger = execution._PilotExactTaskProductPilotExecutionLedger(
            Path(pending_temp.name).resolve()
        )
        pending_ledger.acquire(plan=execution_plan)
        pending_raw = completed_execution.to_dict()
        pending_raw["ledger_root_path_sha256"] = pending_ledger.root_sha256
        pending_receipt = execution.PilotExactTaskProductPilotExecutionReceipt.from_mapping(
            pending_raw
        )
        pending_final, pending_path, _ = pending_ledger._paths(
            execution_plan.execution_nonce_sha256
        )
        assert not pending_final.exists()
        pending_path.write_bytes(pending_receipt.canonical_json().encode("utf-8"))
        pending = recovery._classify_verified_execution_recovery(
            execution_nonce_sha256=execution_plan.execution_nonce_sha256,
            ledger=pending_ledger,
        )
        assert pending.recovery_state_class == "receipt_publication_uncertain"
        assert pending.recovered_execution_receipt_sha256 == pending_receipt.sha256
        assert pending.final_receipt_verified is False
        assert pending.pending_receipt_verified is True
        assert pending.retry_authorized is False
        assert pending.manual_intervention_required is True
        assert pending.recovery_authenticated is True

        # Lock-only state: durable consumption happened, but there is no receipt
        # evidence proving whether the process launched or completed.
        lock_only_temp = tempfile.TemporaryDirectory(
            prefix="rsi-product-pilot-recovery-lock-only-"
        )
        lock_only_ledger = execution._PilotExactTaskProductPilotExecutionLedger(
            Path(lock_only_temp.name).resolve()
        )
        lock_only_ledger.acquire(plan=execution_plan)
        lock_only = recovery._classify_verified_execution_recovery(
            execution_nonce_sha256=execution_plan.execution_nonce_sha256,
            ledger=lock_only_ledger,
        )
        assert lock_only.recovery_state_class == "consumed_uncertain"
        assert lock_only.recovered_execution_receipt_sha256 is None
        assert lock_only.final_receipt_verified is False
        assert lock_only.pending_receipt_verified is False
        assert lock_only.retry_authorized is False
        assert lock_only.nonce_reusable is False
        assert lock_only.manual_intervention_required is True
        assert lock_only.recovery_authenticated is True

        lock_final, lock_pending, lock_path = lock_only_ledger._paths(
            execution_plan.execution_nonce_sha256
        )
        assert not lock_final.exists()
        assert not lock_pending.exists()
        original_lock = lock_path.read_bytes()
        tampered_lock = json.loads(original_lock.decode("utf-8"))
        tampered_lock["fixed_command_id"] = "modelrig.other.check"
        lock_path.write_bytes(
            json.dumps(
                tampered_lock,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        _reject(
            lambda: recovery._classify_verified_execution_recovery(
                execution_nonce_sha256=execution_plan.execution_nonce_sha256,
                ledger=lock_only_ledger,
            )
        )
        lock_path.write_bytes(original_lock)

        # Final+pending coexistence is not normalized or guessed by recovery.
        coexist_temp = tempfile.TemporaryDirectory(
            prefix="rsi-product-pilot-recovery-coexist-"
        )
        coexist_ledger = execution._PilotExactTaskProductPilotExecutionLedger(
            Path(coexist_temp.name).resolve()
        )
        coexist_ledger.acquire(plan=execution_plan)
        coexist_final, coexist_pending, _ = coexist_ledger._paths(
            execution_plan.execution_nonce_sha256
        )
        coexist_raw = completed_execution.to_dict()
        coexist_raw["ledger_root_path_sha256"] = coexist_ledger.root_sha256
        coexist_receipt = execution.PilotExactTaskProductPilotExecutionReceipt.from_mapping(
            coexist_raw
        ).canonical_json().encode("utf-8")
        coexist_final.write_bytes(coexist_receipt)
        coexist_pending.write_bytes(coexist_receipt)
        _reject(
            lambda: recovery._classify_verified_execution_recovery(
                execution_nonce_sha256=execution_plan.execution_nonce_sha256,
                ledger=coexist_ledger,
            )
        )

        # A changing observation between reads fails closed.
        first = recovery._observe(
            execution_nonce_sha256=execution_plan.execution_nonce_sha256,
            ledger=lock_only_ledger,
        )
        changed = recovery._ExecutionRecoveryObservation(
            **{
                **first.to_dict(),
                "lock_sha256": "f" * 64,
            }
        )
        with patch.object(recovery, "_observe", side_effect=(first, changed)):
            _reject(
                lambda: recovery._classify_verified_execution_recovery(
                    execution_nonce_sha256=execution_plan.execution_nonce_sha256,
                    ledger=lock_only_ledger,
                )
            )

        reloaded = recovery.PilotExactTaskProductPilotExecutionRecoveryReceipt.from_mapping(
            completed.to_dict()
        )
        assert reloaded == completed
        assert reloaded.sha256 == completed.sha256
        assert reloaded.recovery_authenticated is False

        for field, value in (
            ("double_observation_matched", False),
            ("execution_nonce_consumed", False),
            ("retry_authorized", True),
            ("task_execution_authorized", True),
            ("local_commit_authorized", True),
            ("remote_write_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("merge_authorized", True),
            ("release_authorized", True),
            ("deploy_authorized", True),
            ("production_activation_authorized", True),
            ("nonce_reusable", True),
            ("manual_intervention_required", False),
            ("next_boundary_recovery_resolution_required", False),
        ):
            raw = completed.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: recovery.PilotExactTaskProductPilotExecutionRecoveryReceipt.from_mapping(
                    raw
                )
            )
    finally:
        if git_run_patch is not None:
            git_run_patch.stop()
        for value in (
            coexist_temp,
            lock_only_temp,
            pending_temp,
            completed_temp,
            capability_temp,
            tx_temp,
            auth_temp,
        ):
            if value is not None:
                value.cleanup()
        if owns_fixture:
            lineage_contract._cleanup(fixture)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(
        recovery.PilotExactTaskProductPilotExecutionRecoveryReceipt.__dataclass_fields__
    )
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields
    assert schema["additionalProperties"] is False

    public = inspect.signature(
        recovery.recover_pilot_exact_task_product_pilot_execution
    )
    assert tuple(public.parameters) == ("execution_nonce_sha256",)

    source = code_of(SOURCE)
    lowered = source.lower()
    assert "_canonical_ledger" in source
    assert "_observe(" in source
    for forbidden in (
        "run_single_verified_tier_a_command_with_receipt",
        "run_verified_tier_a_command",
        "create_once_file",
        "unlink_durable",
        ".reset_to_base(",
        "subprocess.",
        "requests.",
        "urllib.",
        "socket.",
        "write_text(",
        "write_bytes(",
    ):
        assert forbidden not in lowered


if __name__ == "__main__":
    run_contract()
