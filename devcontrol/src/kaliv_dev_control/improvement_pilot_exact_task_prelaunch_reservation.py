"""ADR-DC-038 replay-safe pre-launch reservation for one exact task.

This boundary fresh-revalidates the live ADR-DC-037 plan, re-snapshots the
workspace, and durably reserves the human-signed execution nonce before a later
executor may launch anything. It never launches the pilot task itself.
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
from ._improvement_pilot_start_consumption_impl import (
    _path_sha256,
    _safe_ledger_root,
)
from .durable_publication import (
    DurablePublicationError,
    create_once_file,
    unlink_durable,
)
from . import improvement_pilot_exact_task_execution_plan as plan_boundary
from .improvement_pilot_exact_task_execution_plan import (
    PILOT_EXACT_TASK_EXECUTION_PLAN_AUTHORITY,
    PilotExactTaskExecutionPlan,
)
from .tier_a_command_receipt import _GitWorkspaceEvidence
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_PRELAUNCH_RESERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-prelaunch-reservation-receipt/v1"
)
PILOT_EXACT_TASK_PRELAUNCH_RESERVATION_AUTHORITY = (
    "host-reserved-one-dc-l16-exact-task-prelaunch-only"
)
PILOT_EXACT_TASK_PRELAUNCH_RESERVATION_LEDGER_SCOPE = (
    "canonical-host-local-v1"
)
_MAX_ARTIFACT_BYTES = 1024 * 1024
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-prelaunch-reservation-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-prelaunch-reservation-ledger-v1"
)


class PilotExactTaskPrelaunchReservationError(ValueError):
    """The exact pre-launch reservation is replayed, drifted, or unsafe."""


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
        raise PilotExactTaskPrelaunchReservationError(
            "pre-launch reservation is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskPrelaunchReservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrelaunchReservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrelaunchReservationError(
            f"{name} is invalid"
        ) from exc


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


def _require_execution_plan(value: Any) -> PilotExactTaskExecutionPlan:
    if type(value) is not PilotExactTaskExecutionPlan:
        raise PilotExactTaskPrelaunchReservationError(
            "exact ADR-DC-037 execution plan is required"
        )
    try:
        replayed = PilotExactTaskExecutionPlan.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrelaunchReservationError(
            "ADR-DC-037 execution plan replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrelaunchReservationError(
            "ADR-DC-037 execution plan identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_EXECUTION_PLAN_AUTHORITY
        or value.execution_plan_materialized is not True
        or value.prelaunch_execution_reservation_required is not True
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
    ):
        raise PilotExactTaskPrelaunchReservationError(
            "pre-launch reservation requires one inert ADR-DC-037 plan"
        )
    return value


def _fresh_plan_inputs(
    plan: PilotExactTaskExecutionPlan,
) -> Mapping[str, Any]:
    inputs = plan_boundary._get_live_execution_plan_inputs(plan)
    if inputs is None:
        raise PilotExactTaskPrelaunchReservationError(
            "pre-launch reservation requires the exact live ADR-DC-037 plan"
        )
    return inputs


def _fresh_snapshot_matches(
    plan: PilotExactTaskExecutionPlan,
    inputs: Mapping[str, Any],
) -> None:
    try:
        snapshot = _GitWorkspaceEvidence(
            Path(inputs["workspace_root"]),
            inputs["task"],
            inputs["git_runner"],
        ).snapshot()
    except Exception as exc:
        raise PilotExactTaskPrelaunchReservationError(
            "fresh trusted-Git workspace snapshot failed"
        ) from exc
    if (
        snapshot != plan.workspace_snapshot
        or snapshot.sha256 != plan.workspace_snapshot_sha256
    ):
        raise PilotExactTaskPrelaunchReservationError(
            "workspace changed after ADR-DC-037 execution-plan materialization"
        )
    fixed = inputs.get("fixed_command_plan")
    if (
        fixed != plan.fixed_command_plan
        or getattr(fixed, "sha256", None)
        != plan.fixed_command_plan_sha256
    ):
        raise PilotExactTaskPrelaunchReservationError(
            "fixed command plan changed after ADR-DC-037 materialization"
        )


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
        plan: PilotExactTaskExecutionPlan,
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
            weakref.ref(plan),
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
            plan_ref,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
        ) = entry
        plan = plan_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or plan is None
            or plan.sha256 != receipt.execution_plan_sha256
            or receipt.sha256 != digest
            or _read_bound_file(final_path) != final_payload
            or _read_bound_file(lock_path) != lock_payload
        ):
            return None
        try:
            inputs = _fresh_plan_inputs(plan)
        except Exception:
            return None
        result = dict(inputs)
        result["execution_plan"] = plan
        return MappingProxyType(result)

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_reservation_authenticated,
    _get_live_prelaunch_reservation_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrelaunchReservationReceipt:
    ledger_root_path_sha256: str
    reservation_key_sha256: str
    execution_plan_sha256: str
    executor_capability_sha256: str
    admission_receipt_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    fixed_command_plan_sha256: str
    workspace_snapshot_sha256: str
    fresh_revalidated_at_utc: str
    reserved_at_utc: str
    host_replay_guard_committed: bool = True
    fresh_capability_revalidated: bool = True
    fresh_workspace_snapshot_matched: bool = True
    fixed_command_plan_revalidated: bool = True
    prelaunch_execution_reserved: bool = True
    one_shot_execution_required: bool = True
    execution_plan_materialized: bool = True
    execution_consumed: bool = False
    task_execution_started: bool = False
    task_execution_completed: bool = False
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
    authority: str = PILOT_EXACT_TASK_PRELAUNCH_RESERVATION_AUTHORITY
    ledger_scope: str = PILOT_EXACT_TASK_PRELAUNCH_RESERVATION_LEDGER_SCOPE
    schema: str = PILOT_EXACT_TASK_PRELAUNCH_RESERVATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PRELAUNCH_RESERVATION_SCHEMA:
            raise PilotExactTaskPrelaunchReservationError(
                "pre-launch reservation schema is unsupported"
            )
        if (
            self.ledger_scope
            != PILOT_EXACT_TASK_PRELAUNCH_RESERVATION_LEDGER_SCOPE
        ):
            raise PilotExactTaskPrelaunchReservationError(
                "pre-launch reservation ledger scope is unsupported"
            )
        for name in (
            "ledger_root_path_sha256",
            "reservation_key_sha256",
            "execution_plan_sha256",
            "executor_capability_sha256",
            "admission_receipt_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "fixed_command_plan_sha256",
            "workspace_snapshot_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        if self.reservation_key_sha256 != self.execution_nonce_sha256:
            raise PilotExactTaskPrelaunchReservationError(
                "pre-launch reservation key must be the exact signed execution nonce"
            )
        fresh = _utc(
            self.fresh_revalidated_at_utc,
            name="fresh_revalidated_at_utc",
        )
        reserved = _utc(self.reserved_at_utc, name="reserved_at_utc")
        if reserved < fresh:
            raise PilotExactTaskPrelaunchReservationError(
                "pre-launch reservation predates fresh revalidation"
            )
        required_true = (
            "host_replay_guard_committed",
            "fresh_capability_revalidated",
            "fresh_workspace_snapshot_matched",
            "fixed_command_plan_revalidated",
            "prelaunch_execution_reserved",
            "one_shot_execution_required",
            "execution_plan_materialized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrelaunchReservationError(
                "pre-launch reservation evidence is incomplete"
            )
        required_false = (
            "execution_consumed",
            "task_execution_started",
            "task_execution_completed",
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
        if any(getattr(self, name) is not False for name in required_false):
            raise PilotExactTaskPrelaunchReservationError(
                "pre-launch reservation cannot grant execution/publication authority"
            )
        if self.authority != PILOT_EXACT_TASK_PRELAUNCH_RESERVATION_AUTHORITY:
            raise PilotExactTaskPrelaunchReservationError(
                "pre-launch reservation authority is unsupported"
            )

    @property
    def reservation_authenticated(self) -> bool:
        return _get_live_prelaunch_reservation_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            self.canonical_json().encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(
        cls,
        value: Any,
    ) -> "PilotExactTaskPrelaunchReservationReceipt":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrelaunchReservationError(
                "pre-launch reservation receipt must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrelaunchReservationError(
                "pre-launch reservation receipt fields mismatch"
            )
        return cls(**dict(value))

    @classmethod
    def from_json(
        cls,
        text: str,
    ) -> "PilotExactTaskPrelaunchReservationReceipt":
        try:
            return cls.from_mapping(json.loads(text))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PilotExactTaskPrelaunchReservationError(
                "pre-launch reservation JSON is invalid"
            ) from exc

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskPrelaunchReservationLedger:
    """Permanent create-once reservation keyed by the signed execution nonce."""

    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path, Path]:
        digest = _hex64(key, name="reservation_key_sha256")
        return (
            self.root / f"{digest}.json",
            self.root / f".{digest}.pending.json",
            self.root / f".{digest}.lock",
        )

    def acquire(self, *, plan: PilotExactTaskExecutionPlan) -> bytes:
        key = plan.execution_nonce_sha256
        final, pending, lock = self._paths(key)
        if any(
            path.exists() or path.is_symlink()
            for path in (final, pending, lock)
        ):
            raise PilotExactTaskPrelaunchReservationError(
                "exact execution nonce was already reserved or requires recovery"
            )
        payload = _canonical(
            {
                "schema": (
                    "kaliv-rsi-dc-l16-exact-task-"
                    "prelaunch-reservation-lock/v1"
                ),
                "ledger_scope": (
                    PILOT_EXACT_TASK_PRELAUNCH_RESERVATION_LEDGER_SCOPE
                ),
                "ledger_root_path_sha256": self.root_sha256,
                "reservation_key_sha256": key,
                "execution_plan_sha256": plan.sha256,
                "executor_capability_sha256": (
                    plan.executor_capability_sha256
                ),
                "admission_receipt_sha256": plan.admission_receipt_sha256,
                "execution_nonce_sha256": plan.execution_nonce_sha256,
                "development_task_sha256": plan.development_task_sha256,
                "fixed_command_plan_sha256": plan.fixed_command_plan_sha256,
                "workspace_snapshot_sha256": plan.workspace_snapshot_sha256,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskPrelaunchReservationError(
                "pre-launch execution nonce could not be durably reserved"
            ) from exc
        return payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskPrelaunchReservationReceipt,
        plan: PilotExactTaskExecutionPlan,
        lock_payload: bytes,
    ) -> PilotExactTaskPrelaunchReservationReceipt:
        final, pending, lock = self._paths(receipt.reservation_key_sha256)
        if _read_bound_file(lock) != lock_payload:
            raise PilotExactTaskPrelaunchReservationError(
                "pre-launch reservation marker changed before commit"
            )
        if (
            final.exists()
            or final.is_symlink()
            or pending.exists()
            or pending.is_symlink()
        ):
            raise PilotExactTaskPrelaunchReservationError(
                "pre-launch reservation receipt state already exists"
            )
        payload = receipt.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskPrelaunchReservationError(
                "pre-launch reservation receipt exceeds byte bound"
            )
        try:
            create_once_file(pending, payload)
            create_once_file(final, payload)
            if _read_bound_file(final) != payload:
                raise PilotExactTaskPrelaunchReservationError(
                    "pre-launch reservation receipt read-back mismatch"
                )
            parsed = PilotExactTaskPrelaunchReservationReceipt.from_mapping(
                json.loads(payload.decode("utf-8", errors="strict"))
            )
            if parsed.ledger_root_path_sha256 != self.root_sha256:
                raise PilotExactTaskPrelaunchReservationError(
                    "pre-launch reservation receipt belongs to another ledger"
                )
            unlink_durable(pending)
            if _read_bound_file(lock) != lock_payload:
                raise PilotExactTaskPrelaunchReservationError(
                    "pre-launch marker changed before provenance registration"
                )
            _mark_reservation_authenticated(
                parsed,
                plan,
                final_path=final,
                final_payload=payload,
                lock_path=lock,
                lock_payload=lock_payload,
            )
            if parsed.reservation_authenticated is not True:
                raise PilotExactTaskPrelaunchReservationError(
                    "pre-launch reservation lost live transaction provenance"
                )
            return parsed
        except Exception as exc:
            if isinstance(exc, PilotExactTaskPrelaunchReservationError):
                raise
            raise PilotExactTaskPrelaunchReservationError(
                "pre-launch reservation is durable but receipt requires recovery"
            ) from exc


def _reserve_verified_exact_task_prelaunch(
    *,
    execution_plan: PilotExactTaskExecutionPlan,
    ledger: _PilotExactTaskPrelaunchReservationLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskPrelaunchReservationReceipt:
    plan = _require_execution_plan(execution_plan)
    if type(ledger) is not _PilotExactTaskPrelaunchReservationLedger:
        raise PilotExactTaskPrelaunchReservationError(
            "pre-launch reservation ledger is required"
        )

    before_inputs = _fresh_plan_inputs(plan)
    _fresh_snapshot_matches(plan, before_inputs)
    fresh_at = now_provider()
    fresh_time = _utc(fresh_at, name="fresh_revalidated_at_utc")

    marker = ledger.acquire(plan=plan)

    # Revalidate after durable reservation as well. Any drift now burns the
    # nonce fail-closed instead of making it reusable after uncertain state.
    after_inputs = _fresh_plan_inputs(plan)
    _fresh_snapshot_matches(plan, after_inputs)
    reserved_at = now_provider()
    reserved_time = _utc(reserved_at, name="reserved_at_utc")
    if reserved_time < fresh_time:
        raise PilotExactTaskPrelaunchReservationError(
            "system clock moved backwards during pre-launch reservation"
        )

    receipt = PilotExactTaskPrelaunchReservationReceipt(
        ledger_root_path_sha256=ledger.root_sha256,
        reservation_key_sha256=plan.execution_nonce_sha256,
        execution_plan_sha256=plan.sha256,
        executor_capability_sha256=plan.executor_capability_sha256,
        admission_receipt_sha256=plan.admission_receipt_sha256,
        execution_nonce_sha256=plan.execution_nonce_sha256,
        development_task_sha256=plan.development_task_sha256,
        fixed_command_plan_sha256=plan.fixed_command_plan_sha256,
        workspace_snapshot_sha256=plan.workspace_snapshot_sha256,
        fresh_revalidated_at_utc=fresh_at,
        reserved_at_utc=reserved_at,
    )
    return ledger.commit(
        receipt=receipt,
        plan=plan,
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
            raise PilotExactTaskPrelaunchReservationError(
                "pre-launch reservation ledger is unsupported on this platform"
            )
        return _require_host_controlled_ledger_root(path)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskPrelaunchReservationError(
            "canonical pre-launch reservation ledger is not host-admin controlled"
        ) from exc


def reserve_pilot_exact_task_prelaunch(
    execution_plan: PilotExactTaskExecutionPlan,
) -> PilotExactTaskPrelaunchReservationReceipt:
    """Host-pinned ADR-DC-038 boundary. Reserve but never launch the task."""
    try:
        root = _canonical_ledger_root()
        ledger = _PilotExactTaskPrelaunchReservationLedger(root)
        return _reserve_verified_exact_task_prelaunch(
            execution_plan=execution_plan,
            ledger=ledger,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskPrelaunchReservationError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskPrelaunchReservationError(
            "host-controlled pre-launch reservation failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_PRELAUNCH_RESERVATION_SCHEMA",
    "PILOT_EXACT_TASK_PRELAUNCH_RESERVATION_AUTHORITY",
    "PILOT_EXACT_TASK_PRELAUNCH_RESERVATION_LEDGER_SCOPE",
    "PilotExactTaskPrelaunchReservationError",
    "PilotExactTaskPrelaunchReservationReceipt",
    "reserve_pilot_exact_task_prelaunch",
]
