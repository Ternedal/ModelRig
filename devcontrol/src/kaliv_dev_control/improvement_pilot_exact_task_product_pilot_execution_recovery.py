"""ADR-DC-110 read-only recovery classification for durable ADR-DC-108 state.

This boundary never retries execution and never repairs the ADR-DC-108 ledger.
It double-observes one execution nonce in the canonical host-controlled ledger
and classifies exactly one durable state:

* completed_verified: lock + exact final receipt, no pending receipt;
* receipt_publication_uncertain: lock + exact pending receipt, no final receipt;
* consumed_uncertain: lock only.

Every classified state keeps the nonce spent. Uncertain states require manual
intervention; no state authorizes another launch.
"""
from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from . import improvement_pilot_exact_task_product_pilot_execution as execution_boundary
from .runtime_closure_builder import VERSION_CHECK_COMMAND_ID

PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-execution-recovery/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_AUTHORITY = (
    "read-only-product-pilot-execution-ledger-classification-only"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_SCOPE = (
    "durable-adr-dc-108-state-classification-no-retry-v1"
)
_MAX_BYTES = 160 * 1024 * 1024
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_LOCK_SCHEMA = "kaliv-rsi-dc-l16-exact-task-product-pilot-execution-lock/v1"
_LOCK_FIELDS = frozenset(
    {
        "schema",
        "ledger_scope",
        "ledger_root_path_sha256",
        "consumption_key_sha256",
        "execution_plan_sha256",
        "workspace_snapshot_receipt_sha256",
        "executor_capability_sha256",
        "execution_admission_sha256",
        "execution_nonce_sha256",
        "development_task_sha256",
        "workspace_snapshot_sha256",
        "fixed_command_id",
    }
)


class PilotExactTaskProductPilotExecutionRecoveryError(ValueError):
    """Durable ADR-DC-108 state is missing, changing, or inconsistent."""


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
        raise PilotExactTaskProductPilotExecutionRecoveryError(
            "execution recovery evidence is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskProductPilotExecutionRecoveryError(
            f"{name} is invalid"
        )
    return value


def _read_regular(path: Path, *, name: str) -> bytes:
    try:
        info = path.lstat()
    except OSError as exc:
        raise PilotExactTaskProductPilotExecutionRecoveryError(
            f"{name} is unavailable"
        ) from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise PilotExactTaskProductPilotExecutionRecoveryError(
            f"{name} must be a non-symlink regular file"
        )
    if info.st_size <= 0 or info.st_size > _MAX_BYTES:
        raise PilotExactTaskProductPilotExecutionRecoveryError(
            f"{name} size is invalid"
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise PilotExactTaskProductPilotExecutionRecoveryError(
            f"{name} is unreadable"
        ) from exc


def _optional_regular(path: Path, *, name: str) -> bytes | None:
    if not path.exists() and not path.is_symlink():
        return None
    return _read_regular(path, name=name)


def _canonical_object(raw: bytes, *, name: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskProductPilotExecutionRecoveryError(
            f"{name} is invalid JSON"
        ) from exc
    if not isinstance(value, dict) or _canonical(value).encode("utf-8") != raw:
        raise PilotExactTaskProductPilotExecutionRecoveryError(
            f"{name} is not exact canonical JSON"
        )
    return value


@dataclass(frozen=True, slots=True)
class _ExecutionRecoveryObservation:
    execution_nonce_sha256: str
    ledger_root_path_sha256: str
    lock_sha256: str
    execution_plan_sha256: str
    workspace_snapshot_receipt_sha256: str
    executor_capability_sha256: str
    execution_admission_sha256: str
    development_task_sha256: str
    workspace_snapshot_sha256: str
    fixed_command_id: str
    recovery_state_class: str
    recovered_execution_receipt_sha256: str | None
    final_receipt_verified: bool
    pending_receipt_verified: bool

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            _canonical(self.to_dict()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def _validate_receipt(
    raw: bytes,
    *,
    lock: Mapping[str, Any],
    ledger_root_sha256: str,
    name: str,
) -> execution_boundary.PilotExactTaskProductPilotExecutionReceipt:
    try:
        receipt = (
            execution_boundary.PilotExactTaskProductPilotExecutionReceipt.from_mapping(
                _canonical_object(raw, name=name)
            )
        )
    except Exception as exc:
        raise PilotExactTaskProductPilotExecutionRecoveryError(
            f"{name} is not a valid ADR-DC-108 receipt"
        ) from exc
    if receipt.canonical_json().encode("utf-8") != raw:
        raise PilotExactTaskProductPilotExecutionRecoveryError(
            f"{name} canonical bytes changed during replay"
        )
    checks = (
        (receipt.ledger_root_path_sha256, ledger_root_sha256),
        (receipt.consumption_key_sha256, lock["consumption_key_sha256"]),
        (receipt.execution_nonce_sha256, lock["execution_nonce_sha256"]),
        (receipt.execution_plan_sha256, lock["execution_plan_sha256"]),
        (
            receipt.workspace_snapshot_receipt_sha256,
            lock["workspace_snapshot_receipt_sha256"],
        ),
        (receipt.executor_capability_sha256, lock["executor_capability_sha256"]),
        (receipt.execution_admission_sha256, lock["execution_admission_sha256"]),
        (receipt.development_task_sha256, lock["development_task_sha256"]),
        (receipt.workspace_snapshot_sha256, lock["workspace_snapshot_sha256"]),
        (receipt.fixed_command_id, lock["fixed_command_id"]),
    )
    if any(left != right for left, right in checks):
        raise PilotExactTaskProductPilotExecutionRecoveryError(
            f"{name} does not match the durable execution lock"
        )
    return receipt


def _observe(
    *,
    execution_nonce_sha256: str,
    ledger: execution_boundary._PilotExactTaskProductPilotExecutionLedger,
) -> _ExecutionRecoveryObservation:
    nonce = _hex64(
        execution_nonce_sha256,
        name="execution_nonce_sha256",
    )
    final_path, pending_path, lock_path = ledger._paths(nonce)
    lock_raw = _read_regular(lock_path, name="ADR-DC-108 execution lock")
    lock = _canonical_object(lock_raw, name="ADR-DC-108 execution lock")
    if (
        set(lock) != _LOCK_FIELDS
        or lock.get("schema") != _LOCK_SCHEMA
        or lock.get("ledger_scope")
        != execution_boundary.PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_LEDGER_SCOPE
        or lock.get("ledger_root_path_sha256") != ledger.root_sha256
        or lock.get("consumption_key_sha256") != nonce
        or lock.get("execution_nonce_sha256") != nonce
        or lock.get("fixed_command_id") != VERSION_CHECK_COMMAND_ID
    ):
        raise PilotExactTaskProductPilotExecutionRecoveryError(
            "ADR-DC-108 execution lock is not exact"
        )
    for field in (
        "ledger_root_path_sha256",
        "consumption_key_sha256",
        "execution_plan_sha256",
        "workspace_snapshot_receipt_sha256",
        "executor_capability_sha256",
        "execution_admission_sha256",
        "execution_nonce_sha256",
        "development_task_sha256",
        "workspace_snapshot_sha256",
    ):
        _hex64(lock.get(field), name=field)

    final_raw = _optional_regular(final_path, name="ADR-DC-108 final receipt")
    pending_raw = _optional_regular(
        pending_path,
        name="ADR-DC-108 pending receipt",
    )

    recovered_sha = None
    final_verified = False
    pending_verified = False
    if final_raw is not None and pending_raw is not None:
        raise PilotExactTaskProductPilotExecutionRecoveryError(
            "ADR-DC-108 final and pending receipts coexist and require manual inspection"
        )
    if final_raw is not None:
        final = _validate_receipt(
            final_raw,
            lock=lock,
            ledger_root_sha256=ledger.root_sha256,
            name="ADR-DC-108 final receipt",
        )
        recovered_sha = final.sha256
        final_verified = True
        state = "completed_verified"
    elif pending_raw is not None:
        pending = _validate_receipt(
            pending_raw,
            lock=lock,
            ledger_root_sha256=ledger.root_sha256,
            name="ADR-DC-108 pending receipt",
        )
        recovered_sha = pending.sha256
        pending_verified = True
        state = "receipt_publication_uncertain"
    else:
        state = "consumed_uncertain"

    return _ExecutionRecoveryObservation(
        execution_nonce_sha256=nonce,
        ledger_root_path_sha256=ledger.root_sha256,
        lock_sha256=hashlib.sha256(lock_raw).hexdigest(),
        execution_plan_sha256=lock["execution_plan_sha256"],
        workspace_snapshot_receipt_sha256=lock[
            "workspace_snapshot_receipt_sha256"
        ],
        executor_capability_sha256=lock["executor_capability_sha256"],
        execution_admission_sha256=lock["execution_admission_sha256"],
        development_task_sha256=lock["development_task_sha256"],
        workspace_snapshot_sha256=lock["workspace_snapshot_sha256"],
        fixed_command_id=lock["fixed_command_id"],
        recovery_state_class=state,
        recovered_execution_receipt_sha256=recovered_sha,
        final_receipt_verified=final_verified,
        pending_receipt_verified=pending_verified,
    )


@dataclass(frozen=True, slots=True)
class PilotExactTaskProductPilotExecutionRecoveryReceipt:
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
    recovery_state_class: str
    recovered_execution_receipt_sha256: str | None
    final_receipt_verified: bool
    pending_receipt_verified: bool
    double_observation_matched: bool = True
    execution_nonce_consumed: bool = True
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
    manual_intervention_required: bool = True
    next_boundary_recovery_resolution_required: bool = True
    recovery_scope: str = PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_SCOPE
    authority: str = PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_AUTHORITY
            or self.recovery_scope
            != PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_SCOPE
        ):
            raise PilotExactTaskProductPilotExecutionRecoveryError(
                "execution recovery receipt identity is unsupported"
            )
        for field in (
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
            raise PilotExactTaskProductPilotExecutionRecoveryError(
                "execution recovery command is not the reviewed product-pilot command"
            )
        if self.recovery_state_class == "completed_verified":
            if (
                self.recovered_execution_receipt_sha256 is None
                or self.final_receipt_verified is not True
                or self.pending_receipt_verified is not False
            ):
                raise PilotExactTaskProductPilotExecutionRecoveryError(
                    "completed execution recovery projection is inconsistent"
                )
            _hex64(
                self.recovered_execution_receipt_sha256,
                name="recovered_execution_receipt_sha256",
            )
        elif self.recovery_state_class == "receipt_publication_uncertain":
            if (
                self.recovered_execution_receipt_sha256 is None
                or self.final_receipt_verified is not False
                or self.pending_receipt_verified is not True
            ):
                raise PilotExactTaskProductPilotExecutionRecoveryError(
                    "pending execution recovery projection is inconsistent"
                )
            _hex64(
                self.recovered_execution_receipt_sha256,
                name="recovered_execution_receipt_sha256",
            )
        elif self.recovery_state_class == "consumed_uncertain":
            if (
                self.recovered_execution_receipt_sha256 is not None
                or self.final_receipt_verified is not False
                or self.pending_receipt_verified is not False
            ):
                raise PilotExactTaskProductPilotExecutionRecoveryError(
                    "lock-only execution recovery projection is inconsistent"
                )
        else:
            raise PilotExactTaskProductPilotExecutionRecoveryError(
                "execution recovery state class is unsupported"
            )
        for field in (
            "double_observation_matched",
            "execution_nonce_consumed",
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
            "next_boundary_recovery_resolution_required",
        ):
            if type(getattr(self, field)) is not bool:
                raise PilotExactTaskProductPilotExecutionRecoveryError(
                    f"{field} must be boolean"
                )
        if (
            self.double_observation_matched is not True
            or self.execution_nonce_consumed is not True
            or self.manual_intervention_required is not True
            or self.next_boundary_recovery_resolution_required is not True
        ):
            raise PilotExactTaskProductPilotExecutionRecoveryError(
                "execution recovery lacks fail-closed classification evidence"
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
                raise PilotExactTaskProductPilotExecutionRecoveryError(
                    "execution recovery grants forbidden retry/mutation authority"
                )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            self.canonical_json().encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductPilotExecutionRecoveryError(
                "execution recovery receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _classify_verified_execution_recovery(
    *,
    execution_nonce_sha256: str,
    ledger: execution_boundary._PilotExactTaskProductPilotExecutionLedger,
) -> PilotExactTaskProductPilotExecutionRecoveryReceipt:
    if type(ledger) is not execution_boundary._PilotExactTaskProductPilotExecutionLedger:
        raise PilotExactTaskProductPilotExecutionRecoveryError(
            "exact ADR-DC-108 ledger is required"
        )
    first = _observe(
        execution_nonce_sha256=execution_nonce_sha256,
        ledger=ledger,
    )
    second = _observe(
        execution_nonce_sha256=execution_nonce_sha256,
        ledger=ledger,
    )
    if first != second or first.sha256 != second.sha256:
        raise PilotExactTaskProductPilotExecutionRecoveryError(
            "ADR-DC-108 durable state changed between recovery observations"
        )
    return PilotExactTaskProductPilotExecutionRecoveryReceipt(
        recovery_observation_sha256=first.sha256,
        execution_nonce_sha256=first.execution_nonce_sha256,
        execution_ledger_root_path_sha256=first.ledger_root_path_sha256,
        execution_lock_sha256=first.lock_sha256,
        execution_plan_sha256=first.execution_plan_sha256,
        workspace_snapshot_receipt_sha256=first.workspace_snapshot_receipt_sha256,
        executor_capability_sha256=first.executor_capability_sha256,
        execution_admission_sha256=first.execution_admission_sha256,
        development_task_sha256=first.development_task_sha256,
        workspace_snapshot_sha256=first.workspace_snapshot_sha256,
        fixed_command_id=first.fixed_command_id,
        recovery_state_class=first.recovery_state_class,
        recovered_execution_receipt_sha256=(
            first.recovered_execution_receipt_sha256
        ),
        final_receipt_verified=first.final_receipt_verified,
        pending_receipt_verified=first.pending_receipt_verified,
    )


def recover_pilot_exact_task_product_pilot_execution(
    execution_nonce_sha256: str,
) -> PilotExactTaskProductPilotExecutionRecoveryReceipt:
    """Classify durable ADR-DC-108 state without retrying or modifying it."""
    try:
        ledger = execution_boundary._canonical_ledger()
    except Exception as exc:
        raise PilotExactTaskProductPilotExecutionRecoveryError(
            "canonical ADR-DC-108 execution ledger is unavailable"
        ) from exc
    return _classify_verified_execution_recovery(
        execution_nonce_sha256=execution_nonce_sha256,
        ledger=ledger,
    )


__all__ = [
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_AUTHORITY",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECOVERY_SCOPE",
    "PilotExactTaskProductPilotExecutionRecoveryError",
    "PilotExactTaskProductPilotExecutionRecoveryReceipt",
    "recover_pilot_exact_task_product_pilot_execution",
]
