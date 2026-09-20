"""ADR-DC-108 crash-safe one-shot product-pilot Tier-A execution.

Consumes one live ADR-DC-107 execution plan exactly once. The signed execution
nonce is durably reserved in a host-admin-controlled create-once ledger before
any process launch. Crash, launch failure, or receipt-publication uncertainty
therefore never silently re-enables retry.

The only process launch remains the existing Tier-A command-receipt orchestrator,
which receives the exact ADR-DC-106 workspace snapshot as its expected
pre-execution state.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
    _require_host_controlled_ledger_root,
)
from ._improvement_pilot_start_consumption_impl import _path_sha256, _safe_ledger_root
from .contract import DevelopmentTask
from .durable_publication import DurablePublicationError, create_once_file, unlink_durable
from . import improvement_pilot_exact_task_product_pilot_execution_plan as plan_boundary
from . import improvement_pilot_exact_task_product_pilot_executor_capability as capability_boundary
from . import tier_a_command_receipt as command_receipt_boundary
from .tier_a_command_receipt import TierACommandReceipt
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECEIPT_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-execution-receipt/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_AUTHORITY = (
    "host-consumed-product-pilot-one-shot-tier-a-execution-evidence-only"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_LEDGER_SCOPE = "canonical-host-local-v1"
_MAX_ARTIFACT_BYTES = 160 * 1024 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-product-pilot-execution-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-product-pilot-execution-ledger-v1"
)


class PilotExactTaskProductPilotExecutionError(ValueError):
    """The live execution plan cannot safely launch the reviewed Tier-A task."""


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
        raise PilotExactTaskProductPilotExecutionError(
            "product-pilot execution receipt is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskProductPilotExecutionError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskProductPilotExecutionError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskProductPilotExecutionError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskProductPilotExecutionError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskProductPilotExecutionError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _read_bound_file(path: Path) -> bytes | None:
    candidate = Path(path)
    if not candidate.is_absolute() or _has_linkish_component(candidate):
        return None
    try:
        payload = candidate.read_bytes()
    except OSError:
        return None
    if not payload or len(payload) > _MAX_ARTIFACT_BYTES:
        return None
    return payload


def _task_sha256(task: DevelopmentTask) -> str:
    return hashlib.sha256(task.canonical_json().encode("utf-8")).hexdigest()


def _require_live_plan(value: Any):
    if (
        type(value) is not plan_boundary.PilotExactTaskProductPilotExecutionPlanReceipt
        or value.plan_authenticated is not True
        or value.product_pilot_started is not True
        or value.workspace_snapshot_authenticated is not True
        or value.exact_workspace_snapshot_bound is not True
        or value.command_specification_bound is not True
        or value.execution_plan_materialized is not True
        or value.task_execution_authorized is not True
        or value.one_shot_task_execution_required is not True
        or value.pre_launch_substrate_revalidation_required is not True
        or value.pre_launch_workspace_snapshot_revalidation_required is not True
        or value.task_execution_started is not False
        or value.task_execution_completed is not False
        or value.local_commit_authorized is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.nonce_reusable is not False
        or value.next_boundary_task_execution_required is not True
    ):
        raise PilotExactTaskProductPilotExecutionError(
            "live unconsumed ADR-DC-107 execution plan is required"
        )
    live = plan_boundary._get_live_product_pilot_execution_plan_inputs(value)
    if live is None:
        raise PilotExactTaskProductPilotExecutionError(
            "ADR-DC-107 execution plan lost live substrate or snapshot authority"
        )
    task = live.get("task")
    if (
        type(task) is not DevelopmentTask
        or task.task_id != value.development_task_id
        or _task_sha256(task) != value.development_task_sha256
        or task.base_sha != value.development_task_base_sha
        or task.allowed_command_ids != (value.fixed_command_id,)
        or task.required_tests != task.allowed_command_ids
        or live.get("workspace_snapshot") is not value.workspace_snapshot
    ):
        raise PilotExactTaskProductPilotExecutionError(
            "ADR-DC-107 task or exact workspace plan provenance is inconsistent"
        )
    return value, live, task


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskProductPilotExecutionReceipt:
    ledger_root_path_sha256: str
    consumption_key_sha256: str
    execution_plan_sha256: str
    workspace_snapshot_receipt_sha256: str
    executor_capability_sha256: str
    execution_admission_sha256: str
    execution_nonce_sha256: str
    development_task_id: str
    development_task_sha256: str
    development_task_base_sha: str
    fixed_command_id: str
    workspace_snapshot_sha256: str
    tier_a_command_receipt_sha256: str
    tier_a_command_receipt: TierACommandReceipt
    prepared_at_utc: str
    started_at_utc: str
    completed_at_utc: str
    product_pilot_started: bool
    execution_plan_authenticated_at_launch: bool
    host_replay_guard_committed: bool
    execution_receipt_durably_published: bool
    task_execution_consumed: bool
    one_shot_execution_enforced: bool
    exact_pre_execution_snapshot_verified: bool
    tier_a_command_receipt_verified: bool
    task_execution_started: bool
    task_execution_completed: bool
    task_execution_passed: bool
    workspace_unchanged: bool
    workspace_reset_performed: bool
    recovery_required: bool
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    nonce_reusable: bool = False
    next_boundary_execution_verification_required: bool = True
    ledger_scope: str = PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_LEDGER_SCOPE
    authority: str = PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECEIPT_SCHEMA
            or self.authority != PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_AUTHORITY
            or self.ledger_scope
            != PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_LEDGER_SCOPE
        ):
            raise PilotExactTaskProductPilotExecutionError(
                "product-pilot execution receipt identity is unsupported"
            )
        for name in (
            "ledger_root_path_sha256",
            "consumption_key_sha256",
            "execution_plan_sha256",
            "workspace_snapshot_receipt_sha256",
            "executor_capability_sha256",
            "execution_admission_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "workspace_snapshot_sha256",
            "tier_a_command_receipt_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        if self.consumption_key_sha256 != self.execution_nonce_sha256:
            raise PilotExactTaskProductPilotExecutionError(
                "execution consumption key must equal the signed execution nonce"
            )
        _hex40(self.development_task_base_sha, name="development_task_base_sha")
        _identifier(self.development_task_id, name="development_task_id")
        _identifier(self.fixed_command_id, name="fixed_command_id")
        prepared = _utc(self.prepared_at_utc, name="prepared_at_utc")
        started = _utc(self.started_at_utc, name="started_at_utc")
        completed = _utc(self.completed_at_utc, name="completed_at_utc")
        if not prepared <= started <= completed:
            raise PilotExactTaskProductPilotExecutionError(
                "product-pilot execution timestamps are not monotonic"
            )
        if type(self.tier_a_command_receipt) is not TierACommandReceipt:
            raise PilotExactTaskProductPilotExecutionError(
                "exact canonical Tier-A command receipt is required"
            )
        command = self.tier_a_command_receipt
        try:
            replayed = TierACommandReceipt.from_mapping(command.to_dict())
        except Exception as exc:
            raise PilotExactTaskProductPilotExecutionError(
                "Tier-A command receipt replay validation failed"
            ) from exc
        if (
            replayed != command
            or replayed.sha256 != command.sha256
            or command.sha256 != self.tier_a_command_receipt_sha256
        ):
            raise PilotExactTaskProductPilotExecutionError(
                "Tier-A command receipt identity is inconsistent"
            )
        if (
            command.task_id != self.development_task_id
            or command.task_sha256 != self.development_task_sha256
            or command.base_sha != self.development_task_base_sha
            or command.command_id != self.fixed_command_id
            or command.workspace_before.sha256 != self.workspace_snapshot_sha256
        ):
            raise PilotExactTaskProductPilotExecutionError(
                "Tier-A receipt is not bound to the exact product-pilot plan"
            )
        for name in (
            "product_pilot_started",
            "execution_plan_authenticated_at_launch",
            "host_replay_guard_committed",
            "execution_receipt_durably_published",
            "task_execution_consumed",
            "one_shot_execution_enforced",
            "exact_pre_execution_snapshot_verified",
            "tier_a_command_receipt_verified",
            "task_execution_started",
            "task_execution_completed",
            "task_execution_passed",
            "workspace_unchanged",
            "workspace_reset_performed",
            "recovery_required",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "nonce_reusable",
            "next_boundary_execution_verification_required",
        ):
            if type(getattr(self, name)) is not bool:
                raise PilotExactTaskProductPilotExecutionError(
                    f"{name} must be boolean"
                )
        required_true = (
            "product_pilot_started",
            "execution_plan_authenticated_at_launch",
            "host_replay_guard_committed",
            "execution_receipt_durably_published",
            "task_execution_consumed",
            "one_shot_execution_enforced",
            "exact_pre_execution_snapshot_verified",
            "tier_a_command_receipt_verified",
            "task_execution_started",
            "task_execution_completed",
            "next_boundary_execution_verification_required",
        )
        forced_false = (
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskProductPilotExecutionError(
                "product-pilot execution receipt lacks mandatory execution evidence"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductPilotExecutionError(
                "product-pilot execution receipt grants mutation authority"
            )
        if self.task_execution_passed is not command.passed:
            raise PilotExactTaskProductPilotExecutionError(
                "product-pilot pass state disagrees with Tier-A receipt"
            )
        if self.workspace_unchanged is not command.workspace_unchanged:
            raise PilotExactTaskProductPilotExecutionError(
                "workspace unchanged state disagrees with Tier-A receipt"
            )
        if self.workspace_reset_performed is not command.workspace_reset_performed:
            raise PilotExactTaskProductPilotExecutionError(
                "workspace reset state disagrees with Tier-A receipt"
            )
        if self.recovery_required is self.task_execution_passed:
            raise PilotExactTaskProductPilotExecutionError(
                "recovery requirement must be the inverse of execution pass state"
            )
        if self.task_execution_passed and (
            not self.workspace_unchanged or self.workspace_reset_performed
        ):
            raise PilotExactTaskProductPilotExecutionError(
                "passing product-pilot execution must preserve the exact workspace"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def execution_authenticated(self) -> bool:
        return _get_live_product_pilot_execution_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            name: (
                self.tier_a_command_receipt.to_dict()
                if name == "tier_a_command_receipt"
                else getattr(self, name)
            )
            for name in self.__dataclass_fields__
        }

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductPilotExecutionError(
                "product-pilot execution receipt fields mismatch"
            )
        raw = dict(value)
        try:
            raw["tier_a_command_receipt"] = TierACommandReceipt.from_mapping(
                raw["tier_a_command_receipt"]
            )
        except Exception as exc:
            raise PilotExactTaskProductPilotExecutionError(
                "nested Tier-A command receipt is invalid"
            ) from exc
        return cls(**raw)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _live_execution_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: PilotExactTaskProductPilotExecutionReceipt,
        *,
        executor_capability: capability_boundary.PilotExactTaskProductPilotExecutorCapabilityReceipt,
        final_path: Path,
        final_payload: bytes,
        lock_path: Path,
        lock_payload: bytes,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            executor_capability,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        (
            pid,
            digest,
            receipt_ref,
            executor_capability,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
        ) = entry
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or receipt.sha256 != digest
            or executor_capability.sha256 != receipt.executor_capability_sha256
            or executor_capability.execution_nonce_sha256
            != receipt.execution_nonce_sha256
            or _read_bound_file(final_path) != final_payload
            or _read_bound_file(lock_path) != lock_payload
        ):
            return None
        fresh = capability_boundary._get_live_product_pilot_executor_capability_inputs(
            executor_capability
        )
        if fresh is None:
            return None
        task = fresh.get("task")
        if (
            type(task) is not DevelopmentTask
            or task.task_id != receipt.development_task_id
            or _task_sha256(task) != receipt.development_task_sha256
            or task.base_sha != receipt.development_task_base_sha
            or task.allowed_command_ids != (receipt.fixed_command_id,)
            or task.required_tests != task.allowed_command_ids
        ):
            return None
        live = dict(fresh)
        live["executor_capability"] = executor_capability
        return live

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_product_pilot_execution_authenticated,
    _get_live_product_pilot_execution_inputs,
) = _live_execution_registry()


class _PilotExactTaskProductPilotExecutionLedger:
    """Permanent create-once execution ledger keyed by execution nonce."""

    def __init__(self, root: Path) -> None:
        try:
            self.root = _safe_ledger_root(root)
        except Exception as exc:
            raise PilotExactTaskProductPilotExecutionError(
                "product-pilot execution ledger root is unsafe"
            ) from exc
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path, Path]:
        digest = _hex64(key, name="consumption_key_sha256")
        return (
            self.root / f"{digest}.json",
            self.root / f".{digest}.pending.json",
            self.root / f".{digest}.lock",
        )

    def acquire(
        self,
        *,
        plan: plan_boundary.PilotExactTaskProductPilotExecutionPlanReceipt,
    ) -> bytes:
        key = plan.execution_nonce_sha256
        final, pending, lock = self._paths(key)
        if any(path.exists() or path.is_symlink() for path in (final, pending, lock)):
            raise PilotExactTaskProductPilotExecutionError(
                "product-pilot execution nonce was already consumed or requires recovery"
            )
        payload = _canonical(
            {
                "schema": (
                    "kaliv-rsi-dc-l16-exact-task-product-pilot-execution-lock/v1"
                ),
                "ledger_scope": PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "consumption_key_sha256": key,
                "execution_plan_sha256": plan.sha256,
                "workspace_snapshot_receipt_sha256": (
                    plan.workspace_snapshot_receipt_sha256
                ),
                "executor_capability_sha256": plan.executor_capability_sha256,
                "execution_admission_sha256": plan.execution_admission_sha256,
                "execution_nonce_sha256": plan.execution_nonce_sha256,
                "development_task_sha256": plan.development_task_sha256,
                "workspace_snapshot_sha256": plan.workspace_snapshot_sha256,
                "fixed_command_id": plan.fixed_command_id,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskProductPilotExecutionError(
                "product-pilot execution nonce could not be durably consumed"
            ) from exc
        return payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskProductPilotExecutionReceipt,
        executor_capability: capability_boundary.PilotExactTaskProductPilotExecutorCapabilityReceipt,
        lock_payload: bytes,
    ) -> PilotExactTaskProductPilotExecutionReceipt:
        final, pending, lock = self._paths(receipt.consumption_key_sha256)
        if _read_bound_file(lock) != lock_payload:
            raise PilotExactTaskProductPilotExecutionError(
                "product-pilot execution consumption marker changed before commit"
            )
        if (
            final.exists()
            or final.is_symlink()
            or pending.exists()
            or pending.is_symlink()
        ):
            raise PilotExactTaskProductPilotExecutionError(
                "product-pilot execution receipt state already exists"
            )
        payload = receipt.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskProductPilotExecutionError(
                "product-pilot execution receipt exceeds byte bound"
            )
        try:
            create_once_file(pending, payload)
            create_once_file(final, payload)
            if _read_bound_file(final) != payload:
                raise PilotExactTaskProductPilotExecutionError(
                    "product-pilot execution receipt read-back mismatch"
                )
            parsed = PilotExactTaskProductPilotExecutionReceipt.from_mapping(
                json.loads(payload.decode("utf-8", errors="strict"))
            )
            if (
                parsed.ledger_root_path_sha256 != self.root_sha256
                or parsed.consumption_key_sha256
                != parsed.execution_nonce_sha256
            ):
                raise PilotExactTaskProductPilotExecutionError(
                    "product-pilot execution receipt belongs to another ledger"
                )
            unlink_durable(pending)
            if _read_bound_file(lock) != lock_payload:
                raise PilotExactTaskProductPilotExecutionError(
                    "product-pilot execution marker changed before provenance registration"
                )
            _mark_product_pilot_execution_authenticated(
                parsed,
                executor_capability=executor_capability,
                final_path=final,
                final_payload=payload,
                lock_path=lock,
                lock_payload=lock_payload,
            )
            if parsed.execution_authenticated is not True:
                raise PilotExactTaskProductPilotExecutionError(
                    "product-pilot execution receipt lost live durable provenance"
                )
            return parsed
        except Exception as exc:
            if isinstance(exc, PilotExactTaskProductPilotExecutionError):
                raise
            raise PilotExactTaskProductPilotExecutionError(
                "product-pilot execution is consumed but receipt publication requires recovery"
            ) from exc


def _execute_verified_pilot_exact_task_product_pilot_plan(
    *,
    execution_plan: plan_boundary.PilotExactTaskProductPilotExecutionPlanReceipt,
    ledger: _PilotExactTaskProductPilotExecutionLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskProductPilotExecutionReceipt:
    plan, live, task = _require_live_plan(execution_plan)
    if type(ledger) is not _PilotExactTaskProductPilotExecutionLedger:
        raise PilotExactTaskProductPilotExecutionError(
            "product-pilot execution ledger is required"
        )

    prepared_at = now_provider()
    prepared_time = _utc(prepared_at, name="prepared_at_utc")
    marker = ledger.acquire(plan=plan)

    plan_again, live_again, task_again = _require_live_plan(plan)
    if plan_again is not plan or task_again != task:
        raise PilotExactTaskProductPilotExecutionError(
            "product-pilot execution authority changed after durable nonce reservation"
        )
    live = live_again
    started_at = now_provider()
    started_time = _utc(started_at, name="started_at_utc")
    if started_time < prepared_time:
        raise PilotExactTaskProductPilotExecutionError(
            "system clock moved backwards before product-pilot launch"
        )

    try:
        command = command_receipt_boundary.run_single_verified_tier_a_command_with_receipt(
            task,
            live["catalog"],
            live["toolchain"],
            live["isolation_attestation"],
            live["physical_verifier"],
            git_runner=live["git_runner"],
            signed_runtime_closure=live["signed_runtime_closure"],
            runtime_closure_verifier=live["runtime_closure_verifier"],
            trusted_runtime_root=live["trusted_runtime_root"],
            workspace_root=live["workspace_root"],
            control_plane_root=live["control_plane_root"],
            source_env=live["source_env"],
            expected_workspace_snapshot=plan.workspace_snapshot,
            process_memory_bytes=plan.process_memory_bytes,
            active_process_limit=plan.active_process_limit,
        )
    except Exception as exc:
        raise PilotExactTaskProductPilotExecutionError(
            "product-pilot Tier-A launch was consumed but produced no canonical receipt"
        ) from exc

    if type(command) is not TierACommandReceipt:
        raise PilotExactTaskProductPilotExecutionError(
            "one-shot product-pilot launch returned no canonical Tier-A receipt"
        )
    try:
        replayed = TierACommandReceipt.from_mapping(command.to_dict())
    except Exception as exc:
        raise PilotExactTaskProductPilotExecutionError(
            "one-shot product-pilot Tier-A receipt replay validation failed"
        ) from exc
    if replayed != command or replayed.sha256 != command.sha256:
        raise PilotExactTaskProductPilotExecutionError(
            "one-shot product-pilot Tier-A receipt identity mismatch"
        )
    if command.workspace_before.sha256 != plan.workspace_snapshot_sha256:
        raise PilotExactTaskProductPilotExecutionError(
            "Tier-A launch did not use the exact frozen product-pilot snapshot"
        )
    if (
        command.task_id != plan.development_task_id
        or command.task_sha256 != plan.development_task_sha256
        or command.base_sha != plan.development_task_base_sha
        or command.command_id != plan.fixed_command_id
        or command.git_runtime.runtime_manifest_sha256
        != plan.trusted_git_runtime_manifest_sha256
        or command.tier_a_result.lease_sha256 != plan.lease_sha256
        or command.tier_a_result.signed_report_sha256
        != plan.physical_report_sha256
        or command.tier_a_result.max_output_bytes
        != plan.task_max_output_bytes
    ):
        raise PilotExactTaskProductPilotExecutionError(
            "Tier-A launch receipt does not match the exact product-pilot plan"
        )

    completed_at = now_provider()
    completed_time = _utc(completed_at, name="completed_at_utc")
    if completed_time < started_time:
        raise PilotExactTaskProductPilotExecutionError(
            "system clock moved backwards during product-pilot execution"
        )
    executor_capability = live.get("executor_capability")
    if (
        type(executor_capability)
        is not capability_boundary.PilotExactTaskProductPilotExecutorCapabilityReceipt
    ):
        raise PilotExactTaskProductPilotExecutionError(
            "live product-pilot executor capability disappeared after execution"
        )

    receipt = PilotExactTaskProductPilotExecutionReceipt(
        ledger_root_path_sha256=ledger.root_sha256,
        consumption_key_sha256=plan.execution_nonce_sha256,
        execution_plan_sha256=plan.sha256,
        workspace_snapshot_receipt_sha256=plan.workspace_snapshot_receipt_sha256,
        executor_capability_sha256=plan.executor_capability_sha256,
        execution_admission_sha256=plan.execution_admission_sha256,
        execution_nonce_sha256=plan.execution_nonce_sha256,
        development_task_id=plan.development_task_id,
        development_task_sha256=plan.development_task_sha256,
        development_task_base_sha=plan.development_task_base_sha,
        fixed_command_id=plan.fixed_command_id,
        workspace_snapshot_sha256=plan.workspace_snapshot_sha256,
        tier_a_command_receipt_sha256=command.sha256,
        tier_a_command_receipt=command,
        prepared_at_utc=prepared_at,
        started_at_utc=started_at,
        completed_at_utc=completed_at,
        product_pilot_started=True,
        execution_plan_authenticated_at_launch=True,
        host_replay_guard_committed=True,
        execution_receipt_durably_published=True,
        task_execution_consumed=True,
        one_shot_execution_enforced=True,
        exact_pre_execution_snapshot_verified=True,
        tier_a_command_receipt_verified=True,
        task_execution_started=True,
        task_execution_completed=True,
        task_execution_passed=command.passed,
        workspace_unchanged=command.workspace_unchanged,
        workspace_reset_performed=command.workspace_reset_performed,
        recovery_required=not command.passed,
    )
    return ledger.commit(
        receipt=receipt,
        executor_capability=executor_capability,
        lock_payload=marker,
    )


def _canonical_ledger() -> _PilotExactTaskProductPilotExecutionLedger:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            root = _POSIX_LEDGER
        elif os.name == "nt":
            root = _WINDOWS_LEDGER
        else:
            raise PilotExactTaskProductPilotExecutionError(
                "product-pilot execution ledger platform is unsupported"
            )
        return _PilotExactTaskProductPilotExecutionLedger(
            _require_host_controlled_ledger_root(root)
        )
    except PilotExactTaskProductPilotExecutionError:
        raise
    except (PhysicalHostStateError, OSError, ValueError, TypeError) as exc:
        raise PilotExactTaskProductPilotExecutionError(
            "product-pilot execution ledger is not host-admin controlled"
        ) from exc


def execute_pilot_exact_task_product_pilot_plan(
    execution_plan: plan_boundary.PilotExactTaskProductPilotExecutionPlanReceipt,
) -> PilotExactTaskProductPilotExecutionReceipt:
    """Durably consume one live plan and execute its reviewed Tier-A command once."""
    return _execute_verified_pilot_exact_task_product_pilot_plan(
        execution_plan=execution_plan,
        ledger=_canonical_ledger(),
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_RECEIPT_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_AUTHORITY",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_LEDGER_SCOPE",
    "PilotExactTaskProductPilotExecutionError",
    "PilotExactTaskProductPilotExecutionReceipt",
    "execute_pilot_exact_task_product_pilot_plan",
]
