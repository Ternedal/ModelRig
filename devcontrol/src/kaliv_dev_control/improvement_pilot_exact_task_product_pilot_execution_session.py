"""Production composition for the first exact-task product-pilot execution.

This module adds no new authority. It composes the already reviewed boundaries:

ADR-DC-104 execution admission
ADR-DC-105 executor capability
ADR-DC-106 exact workspace snapshot
ADR-DC-107 frozen-snapshot execution plan
ADR-DC-108 durable one-shot Tier-A execution
ADR-DC-109 post-execution verification/recovery closure

No Git command, process launch, durable write, network operation or mutation is
implemented here. Each operation remains owned by its canonical boundary.
"""
from __future__ import annotations

from typing import Any

from . import improvement_pilot_exact_task_product_pilot_execution_admission as admission_boundary
from . import improvement_pilot_exact_task_product_pilot_executor_capability as capability_boundary
from . import improvement_pilot_exact_task_product_pilot_workspace_snapshot as snapshot_boundary
from . import improvement_pilot_exact_task_product_pilot_execution_plan as plan_boundary
from . import improvement_pilot_exact_task_product_pilot_execution as execution_boundary
from . import improvement_pilot_exact_task_product_pilot_execution_verification as verification_boundary


class PilotExactTaskProductPilotExecutionSessionError(ValueError):
    """The product-pilot execution session could not close safely."""


def _require_closed_verification(value: Any):
    if (
        type(value)
        is not verification_boundary.PilotExactTaskProductPilotExecutionVerificationReceipt
        or value.verification_authenticated is not True
        or value.execution_receipt_authenticated is not True
        or value.tier_a_execution_verified is not True
        or value.post_execution_workspace_verified is not True
        or value.product_pilot_execution_closed is not True
        or value.first_product_pilot_task_closed is not True
        or value.local_commit_authorized is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.nonce_reusable is not False
        or value.next_boundary_stack_consolidation_required is not True
    ):
        raise PilotExactTaskProductPilotExecutionSessionError(
            "ADR-DC-109 did not return an authenticated closed product-pilot execution"
        )
    return value


def run_pilot_exact_task_product_pilot_execution_session(
    start_state: Any,
) -> verification_boundary.PilotExactTaskProductPilotExecutionVerificationReceipt:
    """Run the exact reviewed product-pilot execution path and return ADR-DC-109."""

    try:
        admission = admission_boundary.admit_pilot_exact_task_product_pilot_execution(
            start_state
        )
    except Exception as exc:
        raise PilotExactTaskProductPilotExecutionSessionError(
            "product-pilot execution session failed at ADR-DC-104 admission"
        ) from exc

    try:
        capability = capability_boundary.materialize_pilot_exact_task_product_pilot_executor_capability(
            admission
        )
    except Exception as exc:
        raise PilotExactTaskProductPilotExecutionSessionError(
            "product-pilot execution session failed at ADR-DC-105 executor capability"
        ) from exc

    try:
        snapshot = snapshot_boundary.materialize_pilot_exact_task_product_pilot_workspace_snapshot(
            capability
        )
    except Exception as exc:
        raise PilotExactTaskProductPilotExecutionSessionError(
            "product-pilot execution session failed at ADR-DC-106 workspace snapshot"
        ) from exc

    try:
        execution_plan = plan_boundary.materialize_pilot_exact_task_product_pilot_execution_plan(
            snapshot
        )
    except Exception as exc:
        raise PilotExactTaskProductPilotExecutionSessionError(
            "product-pilot execution session failed at ADR-DC-107 execution plan"
        ) from exc

    try:
        execution = execution_boundary.execute_pilot_exact_task_product_pilot_plan(
            execution_plan
        )
    except Exception as exc:
        raise PilotExactTaskProductPilotExecutionSessionError(
            "product-pilot execution session failed at ADR-DC-108 durable execution; "
            "the execution nonce may already be consumed and must not be retried blindly"
        ) from exc

    try:
        verification = verification_boundary.verify_pilot_exact_task_product_pilot_execution(
            execution
        )
    except Exception as exc:
        raise PilotExactTaskProductPilotExecutionSessionError(
            "product-pilot execution session failed at ADR-DC-109 verification; "
            "do not rerun ADR-DC-108 with the same execution nonce"
        ) from exc

    return _require_closed_verification(verification)


__all__ = [
    "PilotExactTaskProductPilotExecutionSessionError",
    "run_pilot_exact_task_product_pilot_execution_session",
]
