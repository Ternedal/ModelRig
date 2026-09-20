"""ADR-DC-111 fail-closed resolution of one live ADR-DC-110 recovery.

This boundary grants no retry or mutation authority. It consumes only a live,
process-local authenticated ADR-DC-110 recovery receipt and projects one of
three dispositions:

* completed_ready_for_post_restart_verification
* pending_receipt_manual_resolution_required
* consumed_uncertain_manual_resolution_required

Only completed_verified durable evidence may advance to a later fresh
post-restart verification boundary. Pending or lock-only state remains manual.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from typing import Any, Mapping

from . import improvement_pilot_exact_task_product_pilot_execution_recovery as recovery_boundary
from .runtime_closure_builder import VERSION_CHECK_COMMAND_ID

PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_RESOLUTION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-execution-recovery-resolution/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_RESOLUTION_AUTHORITY = (
    "live-recovery-disposition-no-retry-only"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_RESOLUTION_SCOPE = (
    "adr-dc-110-recovery-disposition-v1"
)

RESOLUTION_COMPLETED = "completed_ready_for_post_restart_verification"
RESOLUTION_PENDING = "pending_receipt_manual_resolution_required"
RESOLUTION_CONSUMED = "consumed_uncertain_manual_resolution_required"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class PilotExactTaskProductPilotExecutionRecoveryResolutionError(ValueError):
    """ADR-DC-110 recovery cannot be safely resolved."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskProductPilotExecutionRecoveryResolutionError(
            "execution recovery resolution is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskProductPilotExecutionRecoveryResolutionError(
            f"{name} is invalid"
        )
    return value


def _require_live_recovery(value: Any):
    if (
        type(value)
        is not recovery_boundary.PilotExactTaskProductPilotExecutionRecoveryReceipt
        or value.recovery_authenticated is not True
        or value.double_observation_matched is not True
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
        or value.manual_intervention_required is not True
        or value.next_boundary_recovery_resolution_required is not True
        or value.fixed_command_id != VERSION_CHECK_COMMAND_ID
    ):
        raise PilotExactTaskProductPilotExecutionRecoveryResolutionError(
            "live fail-closed ADR-DC-110 recovery receipt is required"
        )
    live = recovery_boundary._get_live_execution_recovery_inputs(value)
    if live is None:
        raise PilotExactTaskProductPilotExecutionRecoveryResolutionError(
            "ADR-DC-110 live durable recovery provenance is unavailable"
        )
    return value, live


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskProductPilotExecutionRecoveryResolutionReceipt:
    recovery_receipt_sha256: str
    recovery_observation_sha256: str
    execution_nonce_sha256: str
    execution_ledger_root_path_sha256: str
    execution_lock_sha256: str
    execution_plan_sha256: str
    workspace_snapshot_receipt_sha256: str
    executor_capability_sha256: str
    execution_admission_sha256: str
    development_task_sha256: str
    workspace_snapshot_sha256: str
    fixed_command_id: str
    source_recovery_state_class: str
    recovered_execution_receipt_sha256: str | None
    resolution_class: str
    recovery_authenticated_at_resolution: bool = True
    resolution_evidence_verified: bool = True
    execution_nonce_consumed: bool = True
    completed_execution_evidence_available: bool = False
    post_restart_verification_required: bool = False
    manual_intervention_required: bool = True
    retry_authorized: bool = False
    task_execution_authorized: bool = False
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    nonce_reusable: bool = False
    next_boundary_post_restart_verification_required: bool = False
    next_boundary_manual_resolution_required: bool = True
    resolution_scope: str = (
        PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_RESOLUTION_SCOPE
    )
    authority: str = (
        PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_RESOLUTION_AUTHORITY
    )
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_RESOLUTION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema
            != PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_RESOLUTION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_RESOLUTION_AUTHORITY
            or self.resolution_scope
            != PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_RESOLUTION_SCOPE
        ):
            raise PilotExactTaskProductPilotExecutionRecoveryResolutionError(
                "execution recovery resolution identity is unsupported"
            )
        for field in (
            "recovery_receipt_sha256",
            "recovery_observation_sha256",
            "execution_nonce_sha256",
            "execution_ledger_root_path_sha256",
            "execution_lock_sha256",
            "execution_plan_sha256",
            "workspace_snapshot_receipt_sha256",
            "executor_capability_sha256",
            "execution_admission_sha256",
            "development_task_sha256",
            "workspace_snapshot_sha256",
        ):
            _hex64(getattr(self, field), name=field)
        if self.fixed_command_id != VERSION_CHECK_COMMAND_ID:
            raise PilotExactTaskProductPilotExecutionRecoveryResolutionError(
                "recovery resolution command is not the reviewed version check"
            )
        if self.recovered_execution_receipt_sha256 is not None:
            _hex64(
                self.recovered_execution_receipt_sha256,
                name="recovered_execution_receipt_sha256",
            )
        for field in (
            "recovery_authenticated_at_resolution",
            "resolution_evidence_verified",
            "execution_nonce_consumed",
            "completed_execution_evidence_available",
            "post_restart_verification_required",
            "manual_intervention_required",
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
            "next_boundary_post_restart_verification_required",
            "next_boundary_manual_resolution_required",
        ):
            if type(getattr(self, field)) is not bool:
                raise PilotExactTaskProductPilotExecutionRecoveryResolutionError(
                    f"{field} must be boolean"
                )
        if (
            self.recovery_authenticated_at_resolution is not True
            or self.resolution_evidence_verified is not True
            or self.execution_nonce_consumed is not True
        ):
            raise PilotExactTaskProductPilotExecutionRecoveryResolutionError(
                "recovery resolution lacks mandatory live evidence"
            )
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
            if getattr(self, field) is not False:
                raise PilotExactTaskProductPilotExecutionRecoveryResolutionError(
                    "recovery resolution grants forbidden retry/mutation authority"
                )

        if self.source_recovery_state_class == "completed_verified":
            if (
                self.resolution_class != RESOLUTION_COMPLETED
                or self.recovered_execution_receipt_sha256 is None
                or self.completed_execution_evidence_available is not True
                or self.post_restart_verification_required is not True
                or self.manual_intervention_required is not False
                or self.next_boundary_post_restart_verification_required is not True
                or self.next_boundary_manual_resolution_required is not False
            ):
                raise PilotExactTaskProductPilotExecutionRecoveryResolutionError(
                    "completed recovery resolution is inconsistent"
                )
        elif self.source_recovery_state_class == "receipt_publication_uncertain":
            if (
                self.resolution_class != RESOLUTION_PENDING
                or self.recovered_execution_receipt_sha256 is None
                or self.completed_execution_evidence_available is not False
                or self.post_restart_verification_required is not False
                or self.manual_intervention_required is not True
                or self.next_boundary_post_restart_verification_required is not False
                or self.next_boundary_manual_resolution_required is not True
            ):
                raise PilotExactTaskProductPilotExecutionRecoveryResolutionError(
                    "pending recovery resolution is inconsistent"
                )
        elif self.source_recovery_state_class == "consumed_uncertain":
            if (
                self.resolution_class != RESOLUTION_CONSUMED
                or self.recovered_execution_receipt_sha256 is not None
                or self.completed_execution_evidence_available is not False
                or self.post_restart_verification_required is not False
                or self.manual_intervention_required is not True
                or self.next_boundary_post_restart_verification_required is not False
                or self.next_boundary_manual_resolution_required is not True
            ):
                raise PilotExactTaskProductPilotExecutionRecoveryResolutionError(
                    "lock-only recovery resolution is inconsistent"
                )
        else:
            raise PilotExactTaskProductPilotExecutionRecoveryResolutionError(
                "source recovery state is unsupported"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            self.canonical_json().encode("utf-8")
        ).hexdigest()

    @property
    def resolution_authenticated(self) -> bool:
        return _get_live_recovery_resolution_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductPilotExecutionRecoveryResolutionError(
                "execution recovery resolution fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _live_resolution_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: PilotExactTaskProductPilotExecutionRecoveryResolutionReceipt,
        *,
        recovery_receipt: recovery_boundary.PilotExactTaskProductPilotExecutionRecoveryReceipt,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            recovery_receipt,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, source = entry
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or receipt.sha256 != digest
            or source.sha256 != receipt.recovery_receipt_sha256
            or source.recovery_authenticated is not True
        ):
            return None
        live = recovery_boundary._get_live_execution_recovery_inputs(source)
        if live is None:
            return None
        checks = (
            (source.recovery_observation_sha256, receipt.recovery_observation_sha256),
            (source.execution_nonce_sha256, receipt.execution_nonce_sha256),
            (
                source.execution_ledger_root_path_sha256,
                receipt.execution_ledger_root_path_sha256,
            ),
            (source.execution_lock_sha256, receipt.execution_lock_sha256),
            (source.execution_plan_sha256, receipt.execution_plan_sha256),
            (
                source.workspace_snapshot_receipt_sha256,
                receipt.workspace_snapshot_receipt_sha256,
            ),
            (source.executor_capability_sha256, receipt.executor_capability_sha256),
            (source.execution_admission_sha256, receipt.execution_admission_sha256),
            (source.development_task_sha256, receipt.development_task_sha256),
            (source.workspace_snapshot_sha256, receipt.workspace_snapshot_sha256),
            (source.fixed_command_id, receipt.fixed_command_id),
            (source.recovery_state_class, receipt.source_recovery_state_class),
            (
                source.recovered_execution_receipt_sha256,
                receipt.recovered_execution_receipt_sha256,
            ),
        )
        if any(left != right for left, right in checks):
            return None
        result = dict(live)
        result["recovery_receipt"] = source
        return result

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_recovery_resolution_authenticated,
    _get_live_recovery_resolution_inputs,
) = _live_resolution_registry()


def resolve_pilot_exact_task_product_pilot_execution_recovery(
    recovery_receipt: recovery_boundary.PilotExactTaskProductPilotExecutionRecoveryReceipt,
) -> PilotExactTaskProductPilotExecutionRecoveryResolutionReceipt:
    """Resolve one live ADR-DC-110 classification without retry or mutation."""
    source, _live = _require_live_recovery(recovery_receipt)

    if source.recovery_state_class == "completed_verified":
        resolution_class = RESOLUTION_COMPLETED
        completed_available = True
        post_restart_required = True
        manual_required = False
        next_post_restart = True
        next_manual = False
    elif source.recovery_state_class == "receipt_publication_uncertain":
        resolution_class = RESOLUTION_PENDING
        completed_available = False
        post_restart_required = False
        manual_required = True
        next_post_restart = False
        next_manual = True
    elif source.recovery_state_class == "consumed_uncertain":
        resolution_class = RESOLUTION_CONSUMED
        completed_available = False
        post_restart_required = False
        manual_required = True
        next_post_restart = False
        next_manual = True
    else:
        raise PilotExactTaskProductPilotExecutionRecoveryResolutionError(
            "ADR-DC-110 recovery state is unsupported"
        )

    receipt = PilotExactTaskProductPilotExecutionRecoveryResolutionReceipt(
        recovery_receipt_sha256=source.sha256,
        recovery_observation_sha256=source.recovery_observation_sha256,
        execution_nonce_sha256=source.execution_nonce_sha256,
        execution_ledger_root_path_sha256=source.execution_ledger_root_path_sha256,
        execution_lock_sha256=source.execution_lock_sha256,
        execution_plan_sha256=source.execution_plan_sha256,
        workspace_snapshot_receipt_sha256=source.workspace_snapshot_receipt_sha256,
        executor_capability_sha256=source.executor_capability_sha256,
        execution_admission_sha256=source.execution_admission_sha256,
        development_task_sha256=source.development_task_sha256,
        workspace_snapshot_sha256=source.workspace_snapshot_sha256,
        fixed_command_id=source.fixed_command_id,
        source_recovery_state_class=source.recovery_state_class,
        recovered_execution_receipt_sha256=source.recovered_execution_receipt_sha256,
        resolution_class=resolution_class,
        completed_execution_evidence_available=completed_available,
        post_restart_verification_required=post_restart_required,
        manual_intervention_required=manual_required,
        next_boundary_post_restart_verification_required=next_post_restart,
        next_boundary_manual_resolution_required=next_manual,
    )
    _mark_recovery_resolution_authenticated(
        receipt,
        recovery_receipt=source,
    )
    if receipt.resolution_authenticated is not True:
        raise PilotExactTaskProductPilotExecutionRecoveryResolutionError(
            "execution recovery resolution lost live ADR-DC-110 provenance"
        )
    return receipt


__all__ = [
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_RESOLUTION_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_RESOLUTION_AUTHORITY",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_RESOLUTION_SCOPE",
    "RESOLUTION_COMPLETED",
    "RESOLUTION_PENDING",
    "RESOLUTION_CONSUMED",
    "PilotExactTaskProductPilotExecutionRecoveryResolutionError",
    "PilotExactTaskProductPilotExecutionRecoveryResolutionReceipt",
    "resolve_pilot_exact_task_product_pilot_execution_recovery",
]
