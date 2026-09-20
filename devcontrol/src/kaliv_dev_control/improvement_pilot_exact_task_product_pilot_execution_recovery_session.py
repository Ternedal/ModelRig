"""Canonical post-restart recovery session for product-pilot execution.

This facade adds no new authority. It composes:
ADR-DC-110 durable execution recovery classification,
ADR-DC-111 fail-closed recovery resolution, and
ADR-DC-112 fresh post-restart verification for completed evidence.

Pending or lock-only states stop at ADR-DC-111 and remain manual. No path retries
ADR-DC-108 or launches a process.
"""
from __future__ import annotations

from typing import Any

from . import improvement_pilot_exact_task_product_pilot_execution_recovery as recovery_boundary
from . import improvement_pilot_exact_task_product_pilot_execution_recovery_resolution as resolution_boundary
from . import improvement_pilot_exact_task_product_pilot_post_restart_verification as post_restart_boundary


class PilotExactTaskProductPilotExecutionRecoverySessionError(ValueError):
    """The post-restart product-pilot recovery session failed closed."""


def _require_manual_resolution(value: Any):
    if (
        type(value)
        is not resolution_boundary.PilotExactTaskProductPilotExecutionRecoveryResolutionReceipt
        or value.resolution_authenticated is not True
        or value.manual_intervention_required is not True
        or value.post_restart_verification_required is not False
        or value.next_boundary_post_restart_verification_required is not False
        or value.next_boundary_manual_resolution_required is not True
        or value.execution_nonce_consumed is not True
        or value.retry_authorized is not False
        or value.task_execution_authorized is not False
        or value.local_commit_authorized is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskProductPilotExecutionRecoverySessionError(
            "ADR-DC-111 did not return a safe manual recovery disposition"
        )
    return value


def _require_closed_post_restart_verification(value: Any):
    if (
        type(value)
        is not post_restart_boundary.PilotExactTaskProductPilotPostRestartVerificationReceipt
        or value.verification_authenticated is not True
        or value.recovery_resolution_authenticated is not True
        or value.durable_execution_receipt_verified is not True
        or value.host_executor_profile_revalidated is not True
        or value.physical_report_revalidated is not True
        or value.tier_a_lease_revalidated is not True
        or value.workspace_authority_revalidated is not True
        or value.control_plane_toolhost_revalidated is not True
        or value.trusted_git_runtime_revalidated is not True
        or value.post_restart_workspace_verified is not True
        or value.execution_nonce_consumed is not True
        or value.product_pilot_execution_closed is not True
        or value.first_product_pilot_task_closed is not True
        or value.manual_intervention_required is not False
        or value.retry_authorized is not False
        or value.task_execution_authorized is not False
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
        raise PilotExactTaskProductPilotExecutionRecoverySessionError(
            "ADR-DC-112 did not return an authenticated closed recovery"
        )
    return value


def run_pilot_exact_task_product_pilot_execution_recovery_session(
    execution_nonce_sha256: str,
):
    """Recover one consumed execution nonce without ever retrying execution."""
    try:
        recovered = recovery_boundary.recover_pilot_exact_task_product_pilot_execution(
            execution_nonce_sha256
        )
    except Exception as exc:
        raise PilotExactTaskProductPilotExecutionRecoverySessionError(
            "product-pilot recovery session failed at ADR-DC-110 classification"
        ) from exc

    try:
        resolved = (
            resolution_boundary.resolve_pilot_exact_task_product_pilot_execution_recovery(
                recovered
            )
        )
    except Exception as exc:
        raise PilotExactTaskProductPilotExecutionRecoverySessionError(
            "product-pilot recovery session failed at ADR-DC-111 resolution"
        ) from exc

    if resolved.next_boundary_post_restart_verification_required:
        if (
            resolved.resolution_class != resolution_boundary.RESOLUTION_COMPLETED
            or resolved.manual_intervention_required
            or not resolved.completed_execution_evidence_available
        ):
            raise PilotExactTaskProductPilotExecutionRecoverySessionError(
                "ADR-DC-111 post-restart transition is inconsistent"
            )
        try:
            verified = (
                post_restart_boundary.verify_pilot_exact_task_product_pilot_post_restart(
                    resolved
                )
            )
        except Exception as exc:
            raise PilotExactTaskProductPilotExecutionRecoverySessionError(
                "product-pilot recovery session failed at ADR-DC-112 fresh verification; "
                "the execution nonce remains spent and must not be retried"
            ) from exc
        return _require_closed_post_restart_verification(verified)

    if resolved.next_boundary_manual_resolution_required:
        return _require_manual_resolution(resolved)

    raise PilotExactTaskProductPilotExecutionRecoverySessionError(
        "ADR-DC-111 returned no safe next recovery boundary"
    )


__all__ = [
    "PilotExactTaskProductPilotExecutionRecoverySessionError",
    "run_pilot_exact_task_product_pilot_execution_recovery_session",
]
