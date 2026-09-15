"""ADR-DC-039 one-shot exact-task Tier-A execution transaction.

This is the first RSI pilot boundary allowed to start the exact reviewed task.
It requires the live ADR-DC-038 pre-launch reservation, rechecks the exact frozen
workspace, permanently consumes the signed execution nonce before launch, and
then delegates execution to the existing hardened Tier-A receipt orchestrator.

The boundary never grants local commit, remote publication, merge, release,
deploy, or production-activation authority.
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
from types import MappingProxyType
from typing import Any, Callable, Mapping

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
    _require_host_controlled_ledger_root,
)
from ._improvement_pilot_start_consumption_impl import _path_sha256, _safe_ledger_root
from .durable_publication import DurablePublicationError, create_once_file, unlink_durable
from . import improvement_pilot_exact_task_prelaunch_reservation as prelaunch_boundary
from .improvement_pilot_exact_task_prelaunch_reservation import (
    PILOT_EXACT_TASK_PRELAUNCH_RESERVATION_AUTHORITY,
    PilotExactTaskPrelaunchReservationReceipt,
)
from .tier_a_command_receipt import (
    TierACommandReceipt,
    run_single_verified_tier_a_command_with_receipt,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_EXECUTION_TRANSACTION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-execution-transaction-receipt/v1"
)
PILOT_EXACT_TASK_EXECUTION_TRANSACTION_AUTHORITY = (
    "host-executed-one-dc-l16-exact-tier-a-task-only"
)
PILOT_EXACT_TASK_EXECUTION_TRANSACTION_LEDGER_SCOPE = "canonical-host-local-v1"
# TierAExecutionResult permits up to 100,000,000 captured bytes. The canonical
# JSON embeds those bytes as base64, so the durable receipt budget must cover
# that fully valid worst case plus metadata rather than fail after execution.
_MAX_ARTIFACT_BYTES = 160 * 1024 * 1024
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-execution-transaction-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-execution-transaction-ledger-v1"
)


class PilotExactTaskExecutionTransactionError(ValueError):
    """The exact one-shot Tier-A execution transaction is unsafe or replayed."""


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
        raise PilotExactTaskExecutionTransactionError(
            "execution transaction is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskExecutionTransactionError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskExecutionTransactionError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskExecutionTransactionError(f"{name} is invalid") from exc


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


def _require_live_prelaunch_reservation(
    value: Any,
) -> tuple[PilotExactTaskPrelaunchReservationReceipt, Mapping[str, Any]]:
    if type(value) is not PilotExactTaskPrelaunchReservationReceipt:
        raise PilotExactTaskExecutionTransactionError(
            "exact ADR-DC-038 pre-launch reservation receipt is required"
        )
    try:
        replayed = PilotExactTaskPrelaunchReservationReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskExecutionTransactionError(
            "ADR-DC-038 reservation replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskExecutionTransactionError(
            "ADR-DC-038 reservation identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_PRELAUNCH_RESERVATION_AUTHORITY
        or value.host_replay_guard_committed is not True
        or value.prelaunch_execution_reserved is not True
        or value.execution_plan_materialized is not True
        or value.execution_consumed is not False
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
        or value.reservation_authenticated is not True
    ):
        raise PilotExactTaskExecutionTransactionError(
            "execution transaction requires the live unconsumed ADR-DC-038 reservation"
        )
    inputs = prelaunch_boundary._get_live_prelaunch_reservation_inputs(value)
    if inputs is None:
        raise PilotExactTaskExecutionTransactionError(
            "ADR-DC-038 live reservation inputs are unavailable"
        )
    plan = inputs.get("execution_plan")
    if (
        plan is None
        or getattr(plan, "sha256", None) != value.execution_plan_sha256
        or getattr(plan, "execution_nonce_sha256", None)
        != value.execution_nonce_sha256
        or getattr(plan, "executor_capability_sha256", None)
        != value.executor_capability_sha256
        or getattr(plan, "admission_receipt_sha256", None)
        != value.admission_receipt_sha256
        or getattr(plan, "development_task_sha256", None)
        != value.development_task_sha256
        or getattr(plan, "fixed_command_plan_sha256", None)
        != value.fixed_command_plan_sha256
        or getattr(plan, "workspace_snapshot_sha256", None)
        != value.workspace_snapshot_sha256
    ):
        raise PilotExactTaskExecutionTransactionError(
            "ADR-DC-038 reservation is not bound to its exact live execution plan"
        )
    return value, inputs


def _fresh_prelaunch_check(
    reservation: PilotExactTaskPrelaunchReservationReceipt,
    inputs: Mapping[str, Any],
) -> None:
    plan = inputs["execution_plan"]
    if reservation.reservation_authenticated is not True:
        raise PilotExactTaskExecutionTransactionError(
            "pre-launch reservation lost live durable provenance"
        )
    try:
        prelaunch_boundary._fresh_snapshot_matches(plan, inputs)
    except Exception as exc:
        raise PilotExactTaskExecutionTransactionError(
            "fresh pre-launch workspace or fixed-command check failed"
        ) from exc


def _validate_tier_a_receipt(
    receipt: Any,
    *,
    reservation: PilotExactTaskPrelaunchReservationReceipt,
    inputs: Mapping[str, Any],
) -> TierACommandReceipt:
    if type(receipt) is not TierACommandReceipt:
        raise PilotExactTaskExecutionTransactionError(
            "Tier-A executor did not return the exact canonical receipt type"
        )
    try:
        replayed = TierACommandReceipt.from_mapping(receipt.to_dict())
    except Exception as exc:
        raise PilotExactTaskExecutionTransactionError(
            "Tier-A receipt replay validation failed"
        ) from exc
    if replayed != receipt or replayed.sha256 != receipt.sha256:
        raise PilotExactTaskExecutionTransactionError("Tier-A receipt identity mismatch")

    plan = inputs["execution_plan"]
    task = inputs["task"]
    capability = plan.executor_capability
    expected_task_sha = hashlib.sha256(
        task.canonical_json().encode("utf-8")
    ).hexdigest()
    if (
        receipt.task_id != task.task_id
        or receipt.task_sha256 != expected_task_sha
        or receipt.task_sha256 != reservation.development_task_sha256
        or receipt.base_sha != task.base_sha
        or receipt.command_id != plan.fixed_command_id
        or receipt.workspace_before != plan.workspace_snapshot
        or receipt.workspace_before.sha256 != reservation.workspace_snapshot_sha256
        or receipt.git_runtime.runtime_manifest_sha256
        != capability.trusted_git_runtime_manifest_sha256
        or receipt.tier_a_result.task_id != task.task_id
        or receipt.tier_a_result.task_sha256 != expected_task_sha
        or receipt.tier_a_result.base_sha != task.base_sha
        or receipt.tier_a_result.command_id != plan.fixed_command_id
        or receipt.tier_a_result.lease_sha256 != capability.lease_sha256
        or receipt.tier_a_result.signed_report_sha256
        != capability.physical_report_sha256
        or receipt.tier_a_result.max_output_bytes
        != plan.fixed_command_plan.max_output_bytes
    ):
        raise PilotExactTaskExecutionTransactionError(
            "Tier-A receipt does not match the exact reserved execution"
        )
    return receipt


def _live_registry():
    records: dict[
        int,
        tuple[
            int,
            str,
            weakref.ReferenceType[Any],
            weakref.ReferenceType[Any],
            Path,
            bytes,
            Path,
            bytes,
        ],
    ] = {}

    def mark(
        receipt: Any,
        reservation: PilotExactTaskPrelaunchReservationReceipt,
        *,
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
            weakref.ref(reservation),
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
            reservation_ref,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
        ) = entry
        reservation = reservation_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or reservation is None
            or reservation.reservation_authenticated is not True
            or receipt.sha256 != digest
            or _read_bound_file(final_path) != final_payload
            or _read_bound_file(lock_path) != lock_payload
        ):
            return None
        inputs = prelaunch_boundary._get_live_prelaunch_reservation_inputs(reservation)
        if inputs is None:
            return None
        result = dict(inputs)
        result["prelaunch_reservation"] = reservation
        return MappingProxyType(result)

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_execution_transaction_authenticated,
    _get_live_execution_transaction_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskExecutionTransactionReceipt:
    ledger_root_path_sha256: str
    consumption_key_sha256: str
    prelaunch_reservation_sha256: str
    execution_plan_sha256: str
    executor_capability_sha256: str
    admission_receipt_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    fixed_command_plan_sha256: str
    workspace_snapshot_sha256: str
    tier_a_receipt: TierACommandReceipt
    tier_a_receipt_sha256: str
    prepared_at_utc: str
    started_at_utc: str
    completed_at_utc: str
    host_replay_guard_committed: bool = True
    prelaunch_reservation_authenticated: bool = True
    fresh_workspace_snapshot_matched: bool = True
    fixed_command_plan_revalidated: bool = True
    tier_a_receipt_verified: bool = True
    execution_consumed: bool = True
    task_execution_started: bool = True
    task_execution_completed: bool = True
    task_execution_passed: bool = False
    integration_ready: bool = False
    product_pilot_started: bool = False
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_EXECUTION_TRANSACTION_AUTHORITY
    ledger_scope: str = PILOT_EXACT_TASK_EXECUTION_TRANSACTION_LEDGER_SCOPE
    schema: str = PILOT_EXACT_TASK_EXECUTION_TRANSACTION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_EXECUTION_TRANSACTION_SCHEMA:
            raise PilotExactTaskExecutionTransactionError(
                "execution transaction schema is unsupported"
            )
        if self.ledger_scope != PILOT_EXACT_TASK_EXECUTION_TRANSACTION_LEDGER_SCOPE:
            raise PilotExactTaskExecutionTransactionError(
                "execution transaction ledger scope is unsupported"
            )
        for name in (
            "ledger_root_path_sha256",
            "consumption_key_sha256",
            "prelaunch_reservation_sha256",
            "execution_plan_sha256",
            "executor_capability_sha256",
            "admission_receipt_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "fixed_command_plan_sha256",
            "workspace_snapshot_sha256",
            "tier_a_receipt_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        if self.consumption_key_sha256 != self.execution_nonce_sha256:
            raise PilotExactTaskExecutionTransactionError(
                "execution consumption key must be the signed execution nonce"
            )
        if type(self.tier_a_receipt) is not TierACommandReceipt:
            raise PilotExactTaskExecutionTransactionError(
                "execution transaction requires the exact Tier-A receipt"
            )
        try:
            replayed = TierACommandReceipt.from_mapping(self.tier_a_receipt.to_dict())
        except Exception as exc:
            raise PilotExactTaskExecutionTransactionError(
                "embedded Tier-A receipt replay validation failed"
            ) from exc
        if replayed != self.tier_a_receipt or replayed.sha256 != self.tier_a_receipt_sha256:
            raise PilotExactTaskExecutionTransactionError(
                "embedded Tier-A receipt identity mismatch"
            )
        if (
            self.development_task_sha256 != self.tier_a_receipt.task_sha256
            or self.workspace_snapshot_sha256
            != self.tier_a_receipt.workspace_before.sha256
        ):
            raise PilotExactTaskExecutionTransactionError(
                "execution transaction top-level identity disagrees with Tier-A receipt"
            )

        prepared = _utc(self.prepared_at_utc, name="prepared_at_utc")
        started = _utc(self.started_at_utc, name="started_at_utc")
        completed = _utc(self.completed_at_utc, name="completed_at_utc")
        if not prepared <= started <= completed:
            raise PilotExactTaskExecutionTransactionError(
                "execution transaction timestamps are not monotonic"
            )
        required_true = (
            "host_replay_guard_committed",
            "prelaunch_reservation_authenticated",
            "fresh_workspace_snapshot_matched",
            "fixed_command_plan_revalidated",
            "tier_a_receipt_verified",
            "execution_consumed",
            "task_execution_started",
            "task_execution_completed",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskExecutionTransactionError(
                "execution transaction evidence is incomplete"
            )
        if type(self.task_execution_passed) is not bool:
            raise PilotExactTaskExecutionTransactionError(
                "task_execution_passed must be boolean"
            )
        if self.task_execution_passed is not self.tier_a_receipt.passed:
            raise PilotExactTaskExecutionTransactionError(
                "task execution pass state does not match Tier-A receipt"
            )
        forced_false = (
            "integration_ready",
            "product_pilot_started",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskExecutionTransactionError(
                "execution transaction cannot grant publication authority"
            )
        if self.authority != PILOT_EXACT_TASK_EXECUTION_TRANSACTION_AUTHORITY:
            raise PilotExactTaskExecutionTransactionError(
                "execution transaction authority is unsupported"
            )

    @property
    def transaction_authenticated(self) -> bool:
        return _get_live_execution_transaction_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name in self.__dataclass_fields__:  # type: ignore[attr-defined]
            value = getattr(self, name)
            result[name] = value.to_dict() if name == "tier_a_receipt" else value
        return result

    @classmethod
    def from_mapping(
        cls,
        value: Any,
    ) -> "PilotExactTaskExecutionTransactionReceipt":
        if not isinstance(value, Mapping):
            raise PilotExactTaskExecutionTransactionError(
                "execution transaction receipt must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskExecutionTransactionError(
                "execution transaction receipt fields mismatch"
            )
        data = dict(value)
        try:
            data["tier_a_receipt"] = TierACommandReceipt.from_mapping(
                data["tier_a_receipt"]
            )
        except Exception as exc:
            raise PilotExactTaskExecutionTransactionError(
                "execution transaction Tier-A receipt is invalid"
            ) from exc
        return cls(**data)

    @classmethod
    def from_json(
        cls,
        text: str,
    ) -> "PilotExactTaskExecutionTransactionReceipt":
        try:
            return cls.from_mapping(json.loads(text))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PilotExactTaskExecutionTransactionError(
                "execution transaction JSON is invalid"
            ) from exc

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskExecutionTransactionLedger:
    """Permanent create-once execution-consumption ledger keyed by the nonce."""

    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
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
        reservation: PilotExactTaskPrelaunchReservationReceipt,
    ) -> bytes:
        key = reservation.execution_nonce_sha256
        final, pending, lock = self._paths(key)
        if any(path.exists() or path.is_symlink() for path in (final, pending, lock)):
            raise PilotExactTaskExecutionTransactionError(
                "exact execution nonce was already consumed or requires recovery"
            )
        payload = _canonical(
            {
                "schema": (
                    "kaliv-rsi-dc-l16-exact-task-execution-transaction-lock/v1"
                ),
                "ledger_scope": PILOT_EXACT_TASK_EXECUTION_TRANSACTION_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "consumption_key_sha256": key,
                "prelaunch_reservation_sha256": reservation.sha256,
                "execution_plan_sha256": reservation.execution_plan_sha256,
                "executor_capability_sha256": reservation.executor_capability_sha256,
                "admission_receipt_sha256": reservation.admission_receipt_sha256,
                "execution_nonce_sha256": reservation.execution_nonce_sha256,
                "development_task_sha256": reservation.development_task_sha256,
                "fixed_command_plan_sha256": reservation.fixed_command_plan_sha256,
                "workspace_snapshot_sha256": reservation.workspace_snapshot_sha256,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskExecutionTransactionError(
                "exact execution nonce could not be durably consumed"
            ) from exc
        return payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskExecutionTransactionReceipt,
        reservation: PilotExactTaskPrelaunchReservationReceipt,
        lock_payload: bytes,
    ) -> PilotExactTaskExecutionTransactionReceipt:
        final, pending, lock = self._paths(receipt.consumption_key_sha256)
        if _read_bound_file(lock) != lock_payload:
            raise PilotExactTaskExecutionTransactionError(
                "execution consumption marker changed before commit"
            )
        if (
            final.exists()
            or final.is_symlink()
            or pending.exists()
            or pending.is_symlink()
        ):
            raise PilotExactTaskExecutionTransactionError(
                "execution transaction receipt state already exists"
            )
        payload = receipt.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskExecutionTransactionError(
                "execution transaction receipt exceeds byte bound"
            )
        try:
            create_once_file(pending, payload)
            create_once_file(final, payload)
            if _read_bound_file(final) != payload:
                raise PilotExactTaskExecutionTransactionError(
                    "execution transaction receipt read-back mismatch"
                )
            parsed = PilotExactTaskExecutionTransactionReceipt.from_mapping(
                json.loads(payload.decode("utf-8", errors="strict"))
            )
            if parsed.ledger_root_path_sha256 != self.root_sha256:
                raise PilotExactTaskExecutionTransactionError(
                    "execution transaction receipt belongs to another ledger"
                )
            unlink_durable(pending)
            if _read_bound_file(lock) != lock_payload:
                raise PilotExactTaskExecutionTransactionError(
                    "execution marker changed before provenance registration"
                )
            _mark_execution_transaction_authenticated(
                parsed,
                reservation,
                final_path=final,
                final_payload=payload,
                lock_path=lock,
                lock_payload=lock_payload,
            )
            if parsed.transaction_authenticated is not True:
                raise PilotExactTaskExecutionTransactionError(
                    "execution transaction lost live durable provenance"
                )
            return parsed
        except Exception as exc:
            if isinstance(exc, PilotExactTaskExecutionTransactionError):
                raise
            raise PilotExactTaskExecutionTransactionError(
                "execution is consumed but receipt publication requires recovery"
            ) from exc


def _execute_reserved_exact_task(
    *,
    prelaunch_reservation: PilotExactTaskPrelaunchReservationReceipt,
    ledger: _PilotExactTaskExecutionTransactionLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskExecutionTransactionReceipt:
    reservation, inputs = _require_live_prelaunch_reservation(prelaunch_reservation)
    if type(ledger) is not _PilotExactTaskExecutionTransactionLedger:
        raise PilotExactTaskExecutionTransactionError(
            "execution transaction ledger is required"
        )

    _fresh_prelaunch_check(reservation, inputs)
    prepared_at = now_provider()
    prepared_time = _utc(prepared_at, name="prepared_at_utc")

    # The nonce is permanently consumed before any executor call. Crash, launch
    # failure, or later uncertainty therefore cannot silently re-enable retry.
    marker = ledger.acquire(reservation=reservation)

    reservation, inputs = _require_live_prelaunch_reservation(reservation)
    _fresh_prelaunch_check(reservation, inputs)
    started_at = now_provider()
    started_time = _utc(started_at, name="started_at_utc")
    if started_time < prepared_time:
        raise PilotExactTaskExecutionTransactionError(
            "system clock moved backwards before exact task launch"
        )

    try:
        tier_a_receipt = run_single_verified_tier_a_command_with_receipt(
            inputs["task"],
            inputs["catalog"],
            inputs["toolchain"],
            inputs["isolation_attestation"],
            inputs["physical_verifier"],
            git_runner=inputs["git_runner"],
            signed_runtime_closure=inputs["signed_runtime_closure"],
            runtime_closure_verifier=inputs["runtime_closure_verifier"],
            trusted_runtime_root=Path(inputs["trusted_runtime_root"]),
            workspace_root=Path(inputs["workspace_root"]),
            control_plane_root=Path(inputs["control_plane_root"]),
            source_env=inputs["source_env"],
            process_memory_bytes=inputs["process_memory_bytes"],
            active_process_limit=inputs["active_process_limit"],
        )
    except Exception as exc:
        raise PilotExactTaskExecutionTransactionError(
            "exact Tier-A execution was consumed but no canonical receipt was produced"
        ) from exc

    exact_tier_a_receipt = _validate_tier_a_receipt(
        tier_a_receipt,
        reservation=reservation,
        inputs=inputs,
    )
    completed_at = now_provider()
    completed_time = _utc(completed_at, name="completed_at_utc")
    if completed_time < started_time:
        raise PilotExactTaskExecutionTransactionError(
            "system clock moved backwards during exact task execution"
        )

    receipt = PilotExactTaskExecutionTransactionReceipt(
        ledger_root_path_sha256=ledger.root_sha256,
        consumption_key_sha256=reservation.execution_nonce_sha256,
        prelaunch_reservation_sha256=reservation.sha256,
        execution_plan_sha256=reservation.execution_plan_sha256,
        executor_capability_sha256=reservation.executor_capability_sha256,
        admission_receipt_sha256=reservation.admission_receipt_sha256,
        execution_nonce_sha256=reservation.execution_nonce_sha256,
        development_task_sha256=reservation.development_task_sha256,
        fixed_command_plan_sha256=reservation.fixed_command_plan_sha256,
        workspace_snapshot_sha256=reservation.workspace_snapshot_sha256,
        tier_a_receipt=exact_tier_a_receipt,
        tier_a_receipt_sha256=exact_tier_a_receipt.sha256,
        prepared_at_utc=prepared_at,
        started_at_utc=started_at,
        completed_at_utc=completed_at,
        task_execution_passed=exact_tier_a_receipt.passed,
    )
    return ledger.commit(
        receipt=receipt,
        reservation=reservation,
        lock_payload=marker,
    )


def _canonical_ledger_root() -> Path:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_LEDGER
        elif os.name == "nt":
            path = _WINDOWS_LEDGER
        else:
            raise PilotExactTaskExecutionTransactionError(
                "execution transaction ledger is unsupported on this platform"
            )
        return _require_host_controlled_ledger_root(path)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskExecutionTransactionError(
            "canonical execution transaction ledger is not host-admin controlled"
        ) from exc


def execute_pilot_exact_task(
    prelaunch_reservation: PilotExactTaskPrelaunchReservationReceipt,
) -> PilotExactTaskExecutionTransactionReceipt:
    """Host-pinned ADR-DC-039 one-shot execution entrypoint."""
    try:
        root = _canonical_ledger_root()
        ledger = _PilotExactTaskExecutionTransactionLedger(root)
        return _execute_reserved_exact_task(
            prelaunch_reservation=prelaunch_reservation,
            ledger=ledger,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskExecutionTransactionError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskExecutionTransactionError(
            "host-controlled exact task execution failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_EXECUTION_TRANSACTION_SCHEMA",
    "PILOT_EXACT_TASK_EXECUTION_TRANSACTION_AUTHORITY",
    "PILOT_EXACT_TASK_EXECUTION_TRANSACTION_LEDGER_SCOPE",
    "PilotExactTaskExecutionTransactionError",
    "PilotExactTaskExecutionTransactionReceipt",
    "execute_pilot_exact_task",
]
