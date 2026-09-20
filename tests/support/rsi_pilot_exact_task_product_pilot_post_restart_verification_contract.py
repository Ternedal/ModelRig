"""Adversarial contract for ADR-DC-112 fresh post-restart verification."""
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
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_execution_recovery_resolution as resolution  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_post_restart_verification as post_restart  # noqa: E402
from kaliv_dev_control import tier_a_command_receipt as command_receipt_boundary  # noqa: E402
from kaliv_dev_control.runtime_closure_builder import VERSION_CHECK_COMMAND_ID  # noqa: E402
from kaliv_dev_control.tier_a_command_receipt import GitWorkspaceSnapshot, TierACommandReceipt  # noqa: E402
from kaliv_dev_control.tier_a_result import TierAExecutionResult, TierAOutputStream  # noqa: E402
import rsi_pilot_exact_task_product_pilot_executor_capability_contract as capability_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_lineage_attestation_contract as lineage_contract  # noqa: E402
from rsi_pilot_exact_task_executor_capability_contract import _authority_fixture  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-product-pilot-post-restart-verification-v1.schema.json"
)
SOURCE = (
    ROOT / "devcontrol" / "src" / "kaliv_dev_control"
    / "improvement_pilot_exact_task_product_pilot_post_restart_verification.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError, AttributeError, RuntimeError):
        return
    raise AssertionError("ADR-DC-112 unexpectedly accepted unsafe restart state")


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
    execution_ledger_temp = None
    git_run_patch = None
    try:
        auth_temp, tx_temp, admitted, task = capability_contract._admission(fixture)
        capability_temp = tempfile.TemporaryDirectory(
            prefix="rsi-product-pilot-post-restart-capability-"
        )
        authority = _authority_fixture(Path(capability_temp.name).resolve(), task)
        original_path_sha = capability._path_sha256

        def scoped_path_sha(path: Path) -> str:
            candidate = Path(path)
            if candidate == authority["workspace"]:
                return admitted.workspace_root_path_sha256
            return original_path_sha(candidate)

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
        assert executor_capability.capability_authenticated is True

        workspace = authority["workspace"]
        (workspace / ".git").mkdir()
        runtime_version = {"value": "git version adr-dc-112-fixture\n"}
        untracked = {"value": b""}

        def git_read(args, **kwargs):
            del kwargs
            if args == ("--version",):
                return runtime_version["value"].encode("utf-8")
            if args == ("rev-parse", "--show-toplevel"):
                return (os.fspath(workspace) + "\n").encode("utf-8")
            if args == ("rev-parse", "HEAD"):
                return (task.base_sha + "\n").encode("ascii")
            if args[0] == "diff":
                return b""
            if args == ("ls-files", "--others", "--exclude-standard", "-z"):
                return untracked["value"]
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
            duration_ms=7,
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
        assert tier_a_receipt.passed is True

        execution_ledger_temp = tempfile.TemporaryDirectory(
            prefix="rsi-product-pilot-post-restart-ledger-"
        )
        ledger = execution._PilotExactTaskProductPilotExecutionLedger(
            Path(execution_ledger_temp.name).resolve()
        )
        times = iter(
            (
                "2026-09-20T22:30:00Z",
                "2026-09-20T22:30:01Z",
                "2026-09-20T22:30:02Z",
            )
        )
        with patch.object(
            command_receipt_boundary,
            "run_single_verified_tier_a_command_with_receipt",
            return_value=tier_a_receipt,
        ):
            executed = execution._execute_verified_pilot_exact_task_product_pilot_plan(
                execution_plan=execution_plan,
                ledger=ledger,
                now_provider=lambda: next(times),
            )
        assert executed.execution_authenticated is True

        recovered = recovery._classify_verified_execution_recovery(
            execution_nonce_sha256=execution_plan.execution_nonce_sha256,
            ledger=ledger,
        )
        assert recovered.recovery_state_class == "completed_verified"
        assert recovered.recovery_authenticated is True

        resolved = resolution.resolve_pilot_exact_task_product_pilot_execution_recovery(
            recovered
        )
        assert resolved.resolution_class == resolution.RESOLUTION_COMPLETED
        assert resolved.resolution_authenticated is True

        resolver_enabled = {"value": True}

        def host_resolver(*, development_task_sha256: str):
            assert development_task_sha256 == execution_plan.development_task_sha256
            if not resolver_enabled["value"]:
                raise RuntimeError("host profile unavailable")
            return {
                "catalog": authority["catalog"],
                "toolchain": authority["toolchain"],
                "isolation_attestation": authority["attestation"],
                "physical_verifier": authority["physical_verifier"],
                "signed_runtime_closure": authority["signed_closure"],
                "runtime_closure_verifier": authority["runtime_verifier"],
                "trusted_runtime_root": authority["trusted"],
                "git_runner": authority["git_runner"],
                "workspace_root": authority["workspace"],
                "control_plane_root": authority["control"],
            }

        verified = post_restart._verify_pilot_exact_task_product_pilot_post_restart(
            recovery_resolution=resolved,
            resolver=host_resolver,
        )
        assert verified.verification_authenticated is True
        assert verified.recovery_resolution_sha256 == resolved.sha256
        assert verified.recovery_receipt_sha256 == recovered.sha256
        assert verified.execution_receipt_sha256 == executed.sha256
        assert verified.execution_nonce_sha256 == executed.execution_nonce_sha256
        assert verified.execution_plan_sha256 == execution_plan.sha256
        assert verified.development_task_id == task.task_id
        assert verified.development_task_sha256 == execution_plan.development_task_sha256
        assert verified.development_task_base_sha == task.base_sha
        assert verified.fixed_command_id == VERSION_CHECK_COMMAND_ID
        assert verified.tier_a_command_receipt_sha256 == tier_a_receipt.sha256
        assert verified.signed_report_sha256 == execution_plan.physical_report_sha256
        assert verified.lease_sha256 == execution_plan.lease_sha256
        assert verified.git_runtime_evidence_sha256 == tier_a_receipt.git_runtime.sha256
        assert (
            verified.expected_post_execution_workspace_snapshot_sha256
            == execution_plan.workspace_snapshot.sha256
        )
        assert verified.post_restart_workspace_snapshot == execution_plan.workspace_snapshot
        assert verified.execution_outcome_passed is True
        assert verified.recovery_verified is False
        assert verified.recovery_resolution_authenticated is True
        assert verified.durable_execution_receipt_verified is True
        assert verified.host_executor_profile_revalidated is True
        assert verified.physical_report_revalidated is True
        assert verified.tier_a_lease_revalidated is True
        assert verified.workspace_authority_revalidated is True
        assert verified.control_plane_toolhost_revalidated is True
        assert verified.trusted_git_runtime_revalidated is True
        assert verified.post_restart_workspace_verified is True
        assert verified.execution_nonce_consumed is True
        assert verified.product_pilot_execution_closed is True
        assert verified.first_product_pilot_task_closed is True
        assert verified.manual_intervention_required is False
        assert verified.retry_authorized is False
        assert verified.task_execution_authorized is False
        assert verified.local_commit_authorized is False
        assert verified.remote_write_authorized is False
        assert verified.push_authorized is False
        assert verified.pr_mutation_authorized is False
        assert verified.merge_authorized is False
        assert verified.release_authorized is False
        assert verified.deploy_authorized is False
        assert verified.production_activation_authorized is False
        assert verified.nonce_reusable is False
        assert verified.next_boundary_stack_consolidation_required is True

        reloaded = (
            post_restart.PilotExactTaskProductPilotPostRestartVerificationReceipt.from_mapping(
                verified.to_dict()
            )
        )
        assert reloaded == verified
        assert reloaded.sha256 == verified.sha256
        assert reloaded.verification_authenticated is False

        resolved_reloaded = (
            resolution.PilotExactTaskProductPilotExecutionRecoveryResolutionReceipt.from_mapping(
                resolved.to_dict()
            )
        )
        assert resolved_reloaded.resolution_authenticated is False
        _reject(
            lambda: post_restart._verify_pilot_exact_task_product_pilot_post_restart(
                recovery_resolution=resolved_reloaded,
                resolver=host_resolver,
            )
        )

        runtime_version["value"] = "git version adr-dc-112-drift\n"
        assert verified.verification_authenticated is False
        runtime_version["value"] = "git version adr-dc-112-fixture\n"
        assert verified.verification_authenticated is True

        untracked["value"] = b"unexpected.txt\0"
        assert verified.verification_authenticated is False
        untracked["value"] = b""
        assert verified.verification_authenticated is True

        resolver_enabled["value"] = False
        assert verified.verification_authenticated is False
        resolver_enabled["value"] = True
        assert verified.verification_authenticated is True

        final_path, _, lock_path = ledger._paths(
            execution_plan.execution_nonce_sha256
        )
        final_payload = final_path.read_bytes()
        final_path.write_bytes(b"{}")
        assert resolved.resolution_authenticated is False
        assert verified.verification_authenticated is False
        final_path.write_bytes(final_payload)
        assert resolved.resolution_authenticated is True
        assert verified.verification_authenticated is True

        lock_payload = lock_path.read_bytes()
        lock_path.write_bytes(b"{}")
        assert resolved.resolution_authenticated is False
        assert verified.verification_authenticated is False
        lock_path.write_bytes(lock_payload)
        assert resolved.resolution_authenticated is True
        assert verified.verification_authenticated is True

        for field in (
            "retry_authorized",
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
            "manual_intervention_required",
        ):
            raw = verified.to_dict()
            raw[field] = True
            _reject(
                lambda raw=raw: post_restart.PilotExactTaskProductPilotPostRestartVerificationReceipt.from_mapping(
                    raw
                )
            )
    finally:
        if git_run_patch is not None:
            git_run_patch.stop()
        for value in (
            execution_ledger_temp,
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
        post_restart.PilotExactTaskProductPilotPostRestartVerificationReceipt.__dataclass_fields__
    )
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields
    assert schema["additionalProperties"] is False
    nested = schema["properties"]["post_restart_workspace_snapshot"]
    assert set(nested["properties"]) == set(GitWorkspaceSnapshot.__dataclass_fields__)
    assert set(nested["required"]) == set(GitWorkspaceSnapshot.__dataclass_fields__)
    assert nested["additionalProperties"] is False

    public = inspect.signature(
        post_restart.verify_pilot_exact_task_product_pilot_post_restart
    )
    assert tuple(public.parameters) == ("recovery_resolution",)

    source = code_of(SOURCE)
    lowered = source.lower()
    assert "_resolve_host_executor_materialization_inputs" in source
    assert "_load_candidates" in source
    for forbidden in (
        "execute_pilot_exact_task_product_pilot_plan",
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
        "git push",
    ):
        assert forbidden not in lowered


if __name__ == "__main__":
    run_contract()
