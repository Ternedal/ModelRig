"""Contract for ADR-DC-111 recovery disposition without retry."""
from __future__ import annotations

import hashlib
import inspect
import json
import sys
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
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_execution_recovery as recovery  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_execution_recovery_resolution as resolution  # noqa: E402
from kaliv_dev_control.runtime_closure_builder import VERSION_CHECK_COMMAND_ID  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-product-pilot-execution-recovery-resolution-v1.schema.json"
)
SOURCE = (
    ROOT / "devcontrol" / "src" / "kaliv_dev_control"
    / "improvement_pilot_exact_task_product_pilot_execution_recovery_resolution.py"
)


def _h(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError, AttributeError):
        return
    raise AssertionError("ADR-DC-111 unexpectedly accepted unsafe recovery resolution")


def _source(state: str):
    if state == "completed_verified":
        recovered = _h("completed execution receipt")
        final_verified = True
        pending_verified = False
    elif state == "receipt_publication_uncertain":
        recovered = _h("pending execution receipt")
        final_verified = False
        pending_verified = True
    elif state == "consumed_uncertain":
        recovered = None
        final_verified = False
        pending_verified = False
    else:
        raise AssertionError(state)

    return recovery.PilotExactTaskProductPilotExecutionRecoveryReceipt(
        recovery_observation_sha256=_h("observation " + state),
        execution_nonce_sha256=_h("nonce"),
        execution_ledger_root_path_sha256=_h("ledger"),
        execution_lock_sha256=_h("lock"),
        execution_plan_sha256=_h("plan"),
        workspace_snapshot_receipt_sha256=_h("snapshot receipt"),
        executor_capability_sha256=_h("capability"),
        execution_admission_sha256=_h("admission"),
        development_task_sha256=_h("task"),
        workspace_snapshot_sha256=_h("snapshot"),
        fixed_command_id=VERSION_CHECK_COMMAND_ID,
        recovery_state_class=state,
        recovered_execution_receipt_sha256=recovered,
        final_receipt_verified=final_verified,
        pending_receipt_verified=pending_verified,
    )


def _resolve(source):
    enabled = {"value": True}
    live = {"ledger": object(), "observation": object()}

    def get_live(value):
        if enabled["value"] and value is source:
            return live
        return None

    with patch.object(
        recovery,
        "_get_live_execution_recovery_inputs",
        side_effect=get_live,
    ):
        assert source.recovery_authenticated is True
        receipt = resolution.resolve_pilot_exact_task_product_pilot_execution_recovery(
            source
        )
        assert receipt.resolution_authenticated is True

        reloaded = (
            resolution.PilotExactTaskProductPilotExecutionRecoveryResolutionReceipt.from_mapping(
                receipt.to_dict()
            )
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.resolution_authenticated is False

        source_reloaded = (
            recovery.PilotExactTaskProductPilotExecutionRecoveryReceipt.from_mapping(
                source.to_dict()
            )
        )
        assert source_reloaded == source
        assert source_reloaded.recovery_authenticated is False
        _reject(
            lambda: resolution.resolve_pilot_exact_task_product_pilot_execution_recovery(
                source_reloaded
            )
        )

        enabled["value"] = False
        assert source.recovery_authenticated is False
        assert receipt.resolution_authenticated is False

    return receipt


def run_contract(*, shared_fixture=None) -> None:
    del shared_fixture

    completed_source = _source("completed_verified")
    completed = _resolve(completed_source)
    assert completed.recovery_receipt_sha256 == completed_source.sha256
    assert completed.source_recovery_state_class == "completed_verified"
    assert completed.resolution_class == resolution.RESOLUTION_COMPLETED
    assert (
        completed.recovered_execution_receipt_sha256
        == completed_source.recovered_execution_receipt_sha256
    )
    assert completed.completed_execution_evidence_available is True
    assert completed.post_restart_verification_required is True
    assert completed.manual_intervention_required is False
    assert completed.next_boundary_post_restart_verification_required is True
    assert completed.next_boundary_manual_resolution_required is False

    pending_source = _source("receipt_publication_uncertain")
    pending = _resolve(pending_source)
    assert pending.source_recovery_state_class == "receipt_publication_uncertain"
    assert pending.resolution_class == resolution.RESOLUTION_PENDING
    assert (
        pending.recovered_execution_receipt_sha256
        == pending_source.recovered_execution_receipt_sha256
    )
    assert pending.completed_execution_evidence_available is False
    assert pending.post_restart_verification_required is False
    assert pending.manual_intervention_required is True
    assert pending.next_boundary_post_restart_verification_required is False
    assert pending.next_boundary_manual_resolution_required is True

    consumed_source = _source("consumed_uncertain")
    consumed = _resolve(consumed_source)
    assert consumed.source_recovery_state_class == "consumed_uncertain"
    assert consumed.resolution_class == resolution.RESOLUTION_CONSUMED
    assert consumed.recovered_execution_receipt_sha256 is None
    assert consumed.completed_execution_evidence_available is False
    assert consumed.post_restart_verification_required is False
    assert consumed.manual_intervention_required is True
    assert consumed.next_boundary_post_restart_verification_required is False
    assert consumed.next_boundary_manual_resolution_required is True

    for receipt in (completed, pending, consumed):
        assert receipt.recovery_authenticated_at_resolution is True
        assert receipt.resolution_evidence_verified is True
        assert receipt.execution_nonce_consumed is True
        assert receipt.retry_authorized is False
        assert receipt.task_execution_authorized is False
        assert receipt.local_commit_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False

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
    ):
        raw = completed.to_dict()
        raw[field] = True
        _reject(
            lambda raw=raw: resolution.PilotExactTaskProductPilotExecutionRecoveryResolutionReceipt.from_mapping(
                raw
            )
        )

    raw = completed.to_dict()
    raw["manual_intervention_required"] = True
    _reject(
        lambda: resolution.PilotExactTaskProductPilotExecutionRecoveryResolutionReceipt.from_mapping(
            raw
        )
    )
    raw = pending.to_dict()
    raw["next_boundary_post_restart_verification_required"] = True
    _reject(
        lambda: resolution.PilotExactTaskProductPilotExecutionRecoveryResolutionReceipt.from_mapping(
            raw
        )
    )

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(
        resolution.PilotExactTaskProductPilotExecutionRecoveryResolutionReceipt.__dataclass_fields__
    )
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields
    assert schema["additionalProperties"] is False

    public = inspect.signature(
        resolution.resolve_pilot_exact_task_product_pilot_execution_recovery
    )
    assert tuple(public.parameters) == ("recovery_receipt",)

    source = code_of(SOURCE)
    lowered = source.lower()
    assert "_get_live_execution_recovery_inputs" in source
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
    ):
        assert forbidden not in lowered


if __name__ == "__main__":
    run_contract()
