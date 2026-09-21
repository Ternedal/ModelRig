"""ADR-DC-094 write-free recovery classification for lock-only production activation.

Reconstructs one consumed ADR-DC-093 transaction from its durable transaction
lock plus the current physical host state. Recovery never reruns the production
activation controller, never mutates modelrig.env, never restarts the appliance,
never writes a production activation receipt, and never backfills ADR-DC-093.

The boundary double-observes the host around a separate create-once recovery
lock. It may classify only:
- inactive_verified: exact pre-activation bytes remain (optionally with the
  exact bound preflight receipt only);
- exact_activated: the exact bound preflight/final machine receipts and current
  production environment prove activation;
- manual_intervention_required: coherent host state that cannot prove either
  safe inactive state or exact completed activation.

All reusable production/deployment/release/GitHub mutation authority is false.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
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
from .durable_publication import DurablePublicationError, create_once_file
from . import improvement_pilot_exact_task_production_activation_authorization as auth_boundary
from . import improvement_pilot_exact_task_production_activation_transaction as tx_boundary

PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_RECOVERY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-production-activation-recovery-receipt/v1"
)
PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_RECOVERY_AUTHORITY = (
    "host-classified-dc-l16-production-activation-lock-recovery-only"
)
PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_RECOVERY_SCOPE = (
    "write-free-lock-only-production-activation-recovery-classification-v1"
)
PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_RECOVERY_LEDGER_SCOPE = "canonical-host-local-v1"
_TRANSACTION_LOCK_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-production-activation-transaction-lock/v1"
)
_RECOVERY_LOCK_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-production-activation-recovery-lock/v1"
)
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_MAX_BYTES = 8_000_000
_EXPECTED_OUTPUTS = (
    "production-activation-preflight.json",
    "production-activation.json",
)

_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/rsi-pilot-exact-task-production-activation-recovery-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-production-activation-recovery-ledger-v1"
)


class PilotExactTaskProductionActivationRecoveryError(ValueError):
    """ADR-DC-093 lock-only state is unavailable, inconsistent, or unsafe."""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskProductionActivationRecoveryError(
            "production activation recovery evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskProductionActivationRecoveryError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskProductionActivationRecoveryError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str):
        raise PilotExactTaskProductionActivationRecoveryError(f"{name} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PilotExactTaskProductionActivationRecoveryError(f"{name} is invalid") from exc
    if parsed.tzinfo is None:
        raise PilotExactTaskProductionActivationRecoveryError(f"{name} lacks timezone")
    return parsed.astimezone(timezone.utc)


def _utc_seconds(value: Any, *, name: str) -> str:
    parsed = _utc(value, name=name)
    if parsed.microsecond:
        raise PilotExactTaskProductionActivationRecoveryError(
            f"{name} must use whole UTC seconds"
        )
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _path_digest(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()


def _read_regular(path: Path, *, label: str, max_bytes: int = _MAX_BYTES) -> bytes:
    try:
        info = path.lstat()
    except OSError as exc:
        raise PilotExactTaskProductionActivationRecoveryError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise PilotExactTaskProductionActivationRecoveryError(
            f"{label} must be a non-symlink regular file"
        )
    if info.st_size <= 0 or info.st_size > max_bytes:
        raise PilotExactTaskProductionActivationRecoveryError(f"{label} size is invalid")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise PilotExactTaskProductionActivationRecoveryError(f"{label} is unreadable") from exc


def _read_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes, str]:
    raw = _read_regular(path, label=label)
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskProductionActivationRecoveryError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise PilotExactTaskProductionActivationRecoveryError(f"{label} must be a JSON object")
    return value, raw, hashlib.sha256(raw).hexdigest()


_TRANSACTION_LOCK_FIELDS = frozenset(
    {
        "schema",
        "ledger_scope",
        "ledger_root_path_sha256",
        "production_activation_key_sha256",
        "production_activation_authorization_sha256",
        "production_activation_candidate_sha256",
        "production_activation_transaction_config_sha256",
        "pre_activation_evidence_sha256",
        "pre_lock_checkout_state_sha256",
        "bodyrig_final_receipt_sha256",
        "agent3_report_sha256",
        "environment_before_sha256",
        "promotion_gate_sha256",
        "promotion_controller_sha256",
        "powershell_sha256",
        "output_dir_path_sha256",
        "repository",
        "repository_id",
        "merge_commit_sha",
        "promotion_head_sha",
        "locked_at_utc",
    }
)


def _load_transaction_lock(
    *,
    production_activation_key_sha256: str,
    transaction_config: tx_boundary.PilotExactTaskProductionActivationTransactionConfig,
    transaction_ledger: tx_boundary._PilotExactTaskProductionActivationTransactionLedger,
) -> tuple[dict[str, Any], Path, bytes, str]:
    key = _hex64(
        production_activation_key_sha256,
        name="production_activation_key_sha256",
    )
    final_path, lock_path = transaction_ledger._paths(key)
    if final_path.exists() or final_path.is_symlink():
        raise PilotExactTaskProductionActivationRecoveryError(
            "ADR-DC-093 already has a final transaction receipt; recovery is not lock-only"
        )
    raw = _read_regular(lock_path, label="ADR-DC-093 transaction lock")
    try:
        lock = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskProductionActivationRecoveryError(
            "ADR-DC-093 transaction lock is invalid JSON"
        ) from exc
    if (
        not isinstance(lock, dict)
        or set(lock) != _TRANSACTION_LOCK_FIELDS
        or _canonical(lock).encode("utf-8") != raw
    ):
        raise PilotExactTaskProductionActivationRecoveryError(
            "ADR-DC-093 transaction lock is not the exact canonical lock"
        )
    for name in (
        "ledger_root_path_sha256",
        "production_activation_key_sha256",
        "production_activation_authorization_sha256",
        "production_activation_candidate_sha256",
        "production_activation_transaction_config_sha256",
        "pre_activation_evidence_sha256",
        "pre_lock_checkout_state_sha256",
        "bodyrig_final_receipt_sha256",
        "agent3_report_sha256",
        "environment_before_sha256",
        "promotion_gate_sha256",
        "promotion_controller_sha256",
        "powershell_sha256",
        "output_dir_path_sha256",
    ):
        _hex64(lock.get(name), name=name)
    _hex40(lock.get("merge_commit_sha"), name="merge_commit_sha")
    _hex40(lock.get("promotion_head_sha"), name="promotion_head_sha")
    _utc_seconds(lock.get("locked_at_utc"), name="locked_at_utc")
    expected_output = (
        Path(transaction_config.output_root).resolve() / key
    )
    if (
        lock.get("schema") != _TRANSACTION_LOCK_SCHEMA
        or lock.get("ledger_scope")
        != tx_boundary.PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_TRANSACTION_LEDGER_SCOPE
        or lock.get("ledger_root_path_sha256") != transaction_ledger.root_sha256
        or lock.get("production_activation_key_sha256") != key
        or lock.get("production_activation_candidate_sha256") != key
        or lock.get("production_activation_transaction_config_sha256")
        != transaction_config.sha256
        or lock.get("repository") != transaction_config.repository
        or lock.get("repository_id") != transaction_config.repository_id
        or lock.get("output_dir_path_sha256") != _path_digest(expected_output)
        or not isinstance(lock.get("repository"), str)
        or _REPOSITORY.fullmatch(lock["repository"]) is None
        or not isinstance(lock.get("repository_id"), str)
        or _REPOSITORY_ID.fullmatch(lock["repository_id"]) is None
    ):
        raise PilotExactTaskProductionActivationRecoveryError(
            "ADR-DC-093 transaction lock does not match the host-pinned transaction"
        )
    return lock, lock_path, raw, hashlib.sha256(raw).hexdigest()


def _preflight_verified(
    value: Mapping[str, Any],
    *,
    raw_sha256: str,
    lock: Mapping[str, Any],
) -> bool:
    try:
        changed = value.get("promotion_changed_paths")
        bodyrig = value.get("bodyrig")
        agent3 = value.get("agent3")
        environment = value.get("environment")
        if (
            not isinstance(changed, list)
            or any(not isinstance(item, str) for item in changed)
            or not tx_boundary._REQUIRED_PROMOTION_PATHS.issubset(set(changed))
            or bool(set(changed) - tx_boundary._ALLOWED_PROMOTION_PATHS)
            or not isinstance(bodyrig, Mapping)
            or not isinstance(agent3, Mapping)
            or not isinstance(environment, Mapping)
        ):
            return False
        _hex40(value.get("origin_main_sha"), name="preflight origin_main_sha")
        _hex64(value.get("worker_code_sha256"), name="preflight worker_code_sha256")
        if not isinstance(value.get("version"), str) or not value.get("version"):
            return False
        return (
            value.get("schema") == tx_boundary.MACHINE_PREFLIGHT_SCHEMA
            and value.get("production_activation") is False
            and value.get("candidate_git_sha") == lock["merge_commit_sha"]
            and value.get("promotion_git_sha") == lock["promotion_head_sha"]
            and bodyrig.get("final_receipt_sha256")
            == lock["bodyrig_final_receipt_sha256"]
            and bodyrig.get("machine_live_proof") is True
            and bodyrig.get("machine_quality") is True
            and bodyrig.get("product_exercise") is True
            and agent3.get("report_sha256") == lock["agent3_report_sha256"]
            and agent3.get("write_pilot_eligible") is True
            and environment.get("before_sha256") == lock["environment_before_sha256"]
            and _HEX64.fullmatch(raw_sha256) is not None
        )
    except (KeyError, TypeError, PilotExactTaskProductionActivationRecoveryError):
        return False


def _machine_verified(
    value: Mapping[str, Any],
    *,
    preflight: Mapping[str, Any],
    preflight_sha256: str,
    machine_sha256: str,
    lock: Mapping[str, Any],
    env_values: Mapping[str, str],
    env_sha256: str,
    config: tx_boundary.PilotExactTaskProductionActivationTransactionConfig,
) -> bool:
    try:
        bindings = value.get("bindings")
        bodyrig = value.get("bodyrig")
        agent3 = value.get("agent3")
        runtime = value.get("runtime")
        if (
            set(value)
            != {
                "schema",
                "created_at",
                "production_activation",
                "scope",
                "candidate_git_sha",
                "promotion_git_sha",
                "origin_main_sha",
                "version",
                "worker_code_sha256",
                "bindings",
                "bodyrig",
                "agent3",
                "runtime",
                "switches",
                "scheduler_approval_secret_present",
                "human_acceptance_required",
            }
            or not isinstance(bindings, Mapping)
            or not isinstance(bodyrig, Mapping)
            or not isinstance(agent3, Mapping)
            or not isinstance(runtime, Mapping)
            or set(runtime) != set(tx_boundary._RUNTIME_TRUE_FIELDS)
        ):
            return False
        _utc(value.get("created_at"), name="machine production receipt created_at")
        _hex40(value.get("origin_main_sha"), name="machine origin_main_sha")
        _hex64(value.get("worker_code_sha256"), name="machine worker_code_sha256")
        _hex64(bodyrig.get("package_sha256"), name="machine bodyrig package_sha256")
        report = env_values.get("KALIV_AGENT3_VALIDATION_REPORT", "")
        expected_report = str(Path(config.agent3_report_path).resolve())
        return (
            value.get("schema") == tx_boundary.MACHINE_FINAL_SCHEMA
            and value.get("production_activation") is True
            and value.get("scope") == list(tx_boundary._MACHINE_SCOPE)
            and value.get("candidate_git_sha") == lock["merge_commit_sha"]
            and value.get("promotion_git_sha") == lock["promotion_head_sha"]
            and value.get("origin_main_sha") == preflight.get("origin_main_sha")
            and value.get("version") == preflight.get("version")
            and value.get("worker_code_sha256") == preflight.get("worker_code_sha256")
            and value.get("switches") == auth_boundary.REQUIRED_SWITCHES
            and value.get("scheduler_approval_secret_present") is True
            and value.get("human_acceptance_required") is False
            and bindings.get("preflight_sha256") == preflight_sha256
            and bindings.get("bodyrig_final_receipt_sha256")
            == lock["bodyrig_final_receipt_sha256"]
            and bindings.get("agent3_report_sha256") == lock["agent3_report_sha256"]
            and bindings.get("environment_before_sha256")
            == lock["environment_before_sha256"]
            and bindings.get("environment_after_sha256") == env_sha256
            and env_sha256 != lock["environment_before_sha256"]
            and all(runtime.get(name) is True for name in tx_boundary._RUNTIME_TRUE_FIELDS)
            and bodyrig.get("machine_live_proof") is True
            and bodyrig.get("machine_quality") is True
            and bodyrig.get("product_exercise") is True
            and agent3.get("write_pilot_eligible") is True
            and agent3.get("report_bound_live") is True
            and all(
                env_values.get(key) == expected
                for key, expected in auth_boundary.REQUIRED_SWITCHES.items()
            )
            and os.path.normcase(os.path.abspath(os.path.expanduser(report)))
            == os.path.normcase(os.path.abspath(os.path.expanduser(expected_report)))
            and len(
                env_values.get("KALIV_SCHEDULER_APPROVAL_SECRET", "").encode("utf-8")
            )
            >= 32
            and _HEX64.fullmatch(machine_sha256) is not None
        )
    except (KeyError, TypeError, PilotExactTaskProductionActivationRecoveryError):
        return False


@dataclass(frozen=True, slots=True)
class _RecoveryObservation:
    environment_observed_sha256: str
    output_state_sha256: str
    production_preflight_observed_sha256: str | None
    machine_production_receipt_observed_sha256: str | None
    recovery_state_class: str
    production_activation_observed: bool | None
    preflight_receipt_verified: bool
    machine_production_receipt_verified: bool
    environment_matches_pre_activation: bool
    required_switches_active: bool
    manual_intervention_required: bool

    def __post_init__(self) -> None:
        _hex64(self.environment_observed_sha256, name="environment_observed_sha256")
        _hex64(self.output_state_sha256, name="output_state_sha256")
        for name in (
            "production_preflight_observed_sha256",
            "machine_production_receipt_observed_sha256",
        ):
            value = getattr(self, name)
            if value is not None:
                _hex64(value, name=name)
        if self.recovery_state_class not in {
            "inactive_verified",
            "exact_activated",
            "manual_intervention_required",
        }:
            raise PilotExactTaskProductionActivationRecoveryError(
                "recovery state class is unsupported"
            )
        if self.recovery_state_class == "inactive_verified":
            if (
                self.production_activation_observed is not False
                or self.machine_production_receipt_verified is not False
                or self.environment_matches_pre_activation is not True
                or self.required_switches_active is not False
                or self.manual_intervention_required is not True
            ):
                raise PilotExactTaskProductionActivationRecoveryError(
                    "inactive recovery classification is inconsistent"
                )
        elif self.recovery_state_class == "exact_activated":
            if (
                self.production_activation_observed is not True
                or self.preflight_receipt_verified is not True
                or self.machine_production_receipt_verified is not True
                or self.environment_matches_pre_activation is not False
                or self.required_switches_active is not True
                or self.manual_intervention_required is not False
            ):
                raise PilotExactTaskProductionActivationRecoveryError(
                    "exact activation recovery classification is inconsistent"
                )
        elif (
            self.production_activation_observed is not None
            or self.manual_intervention_required is not True
        ):
            raise PilotExactTaskProductionActivationRecoveryError(
                "manual recovery classification is inconsistent"
            )

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict()).encode("utf-8")).hexdigest()


def _observe_lock_only_state(
    *,
    lock: Mapping[str, Any],
    transaction_config: tx_boundary.PilotExactTaskProductionActivationTransactionConfig,
) -> _RecoveryObservation:
    env_path = Path(transaction_config.appliance_dir) / "modelrig.env"
    try:
        env_values, env_sha = tx_boundary._target_env_values(env_path)
    except Exception as exc:
        raise PilotExactTaskProductionActivationRecoveryError(
            "modelrig.env cannot be safely observed for recovery"
        ) from exc
    switches_active = all(
        env_values.get(key) == expected
        for key, expected in auth_boundary.REQUIRED_SWITCHES.items()
    )
    matches_before = env_sha == lock["environment_before_sha256"]

    output_dir = Path(transaction_config.output_root).resolve() / lock[
        "production_activation_key_sha256"
    ]
    inventory: list[str] = []
    preflight: dict[str, Any] | None = None
    final: dict[str, Any] | None = None
    preflight_sha: str | None = None
    machine_sha: str | None = None

    if output_dir.exists() or output_dir.is_symlink():
        try:
            info = output_dir.lstat()
        except OSError as exc:
            raise PilotExactTaskProductionActivationRecoveryError(
                "production activation output state is unreadable"
            ) from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise PilotExactTaskProductionActivationRecoveryError(
                "production activation output path is not a safe directory"
            )
        try:
            inventory = sorted(item.name for item in output_dir.iterdir())
        except OSError as exc:
            raise PilotExactTaskProductionActivationRecoveryError(
                "production activation output inventory is unreadable"
            ) from exc
        for name in inventory:
            path = output_dir / name
            try:
                item_info = path.lstat()
            except OSError as exc:
                raise PilotExactTaskProductionActivationRecoveryError(
                    "production activation output entry is unreadable"
                ) from exc
            if stat.S_ISLNK(item_info.st_mode) or not stat.S_ISREG(item_info.st_mode):
                raise PilotExactTaskProductionActivationRecoveryError(
                    "production activation output contains a non-regular entry"
                )
        if "production-activation-preflight.json" in inventory:
            try:
                preflight, _pre_raw, preflight_sha = _read_json(
                    output_dir / "production-activation-preflight.json",
                    label="production activation preflight",
                )
            except PilotExactTaskProductionActivationRecoveryError:
                preflight = None
                preflight_sha = None
        if "production-activation.json" in inventory:
            try:
                final, _final_raw, machine_sha = _read_json(
                    output_dir / "production-activation.json",
                    label="production activation final receipt",
                )
            except PilotExactTaskProductionActivationRecoveryError:
                final = None
                machine_sha = None

    output_projection = {
        "inventory": inventory,
        "preflight_sha256": preflight_sha,
        "machine_receipt_sha256": machine_sha,
    }
    output_state_sha = hashlib.sha256(
        _canonical(output_projection).encode("utf-8")
    ).hexdigest()

    preflight_ok = bool(
        preflight is not None
        and preflight_sha is not None
        and _preflight_verified(
            preflight,
            raw_sha256=preflight_sha,
            lock=lock,
        )
    )
    machine_ok = bool(
        inventory == list(_EXPECTED_OUTPUTS)
        and preflight_ok
        and final is not None
        and machine_sha is not None
        and _machine_verified(
            final,
            preflight=preflight,
            preflight_sha256=preflight_sha,
            machine_sha256=machine_sha,
            lock=lock,
            env_values=env_values,
            env_sha256=env_sha,
            config=transaction_config,
        )
    )

    if machine_ok:
        state_class = "exact_activated"
        production_activation: bool | None = True
        manual = False
    elif (
        matches_before
        and not switches_active
        and (
            inventory == []
            or (
                inventory == ["production-activation-preflight.json"]
                and preflight_ok
            )
        )
    ):
        state_class = "inactive_verified"
        production_activation = False
        manual = True
    else:
        state_class = "manual_intervention_required"
        production_activation = None
        manual = True
        machine_ok = False

    return _RecoveryObservation(
        environment_observed_sha256=env_sha,
        output_state_sha256=output_state_sha,
        production_preflight_observed_sha256=preflight_sha,
        machine_production_receipt_observed_sha256=machine_sha,
        recovery_state_class=state_class,
        production_activation_observed=production_activation,
        preflight_receipt_verified=preflight_ok,
        machine_production_receipt_verified=machine_ok,
        environment_matches_pre_activation=matches_before,
        required_switches_active=switches_active,
        manual_intervention_required=manual,
    )


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskProductionActivationRecoveryReceipt:
    production_activation_recovery_ledger_root_path_sha256: str
    production_activation_recovery_key_sha256: str
    production_activation_recovery_lock_sha256: str
    production_activation_transaction_ledger_root_path_sha256: str
    production_activation_transaction_lock_sha256: str
    production_activation_authorization_sha256: str
    production_activation_candidate_sha256: str
    production_activation_transaction_config_sha256: str
    pre_activation_evidence_sha256: str
    environment_before_sha256: str
    environment_observed_sha256: str
    output_dir_path_sha256: str
    output_state_sha256: str
    production_preflight_observed_sha256: str | None
    machine_production_receipt_observed_sha256: str | None
    repository: str
    repository_id: str
    merge_commit_sha: str
    promotion_git_sha: str
    transaction_locked_at_utc: str
    recovery_observed_at_utc: str
    recovery_completed_at_utc: str
    recovery_state_class: str
    production_activation_observed: bool | None
    preflight_receipt_verified: bool
    machine_production_receipt_verified: bool
    environment_matches_pre_activation: bool
    required_switches_active: bool
    host_production_activation_recovery_guard_committed: bool = True
    transaction_lock_authenticated: bool = True
    double_observation_matched: bool = True
    recovery_receipt_write_performed: bool = True
    manual_intervention_required: bool = True
    controller_rerun_performed: bool = False
    production_env_mutation_performed: bool = False
    appliance_restart_performed: bool = False
    production_receipt_write_performed: bool = False
    transaction_receipt_backfilled: bool = False
    promotion_gate_execution_authorized: bool = False
    production_env_mutation_authorized: bool = False
    appliance_restart_authorized: bool = False
    production_receipt_write_authorized: bool = False
    production_activation_authorized: bool = False
    success_deployment_status_authorized: bool = False
    deployment_status_mutation_authorized: bool = False
    deployment_mutation_authorized: bool = False
    deploy_authorized: bool = False
    remote_write_authorized: bool = False
    release_authorized: bool = False
    tag_write_authorized: bool = False
    release_mutation_authorized: bool = False
    merge_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    product_pilot_started: bool = False
    nonce_reusable: bool = False
    recovery_scope: str = PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_RECOVERY_SCOPE
    authority: str = PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_RECOVERY_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_RECOVERY_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_RECOVERY_SCHEMA
            or self.authority != PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_RECOVERY_AUTHORITY
            or self.recovery_scope != PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_RECOVERY_SCOPE
        ):
            raise PilotExactTaskProductionActivationRecoveryError(
                "recovery receipt identity is unsupported"
            )
        for name in (
            "production_activation_recovery_ledger_root_path_sha256",
            "production_activation_recovery_key_sha256",
            "production_activation_recovery_lock_sha256",
            "production_activation_transaction_ledger_root_path_sha256",
            "production_activation_transaction_lock_sha256",
            "production_activation_authorization_sha256",
            "production_activation_candidate_sha256",
            "production_activation_transaction_config_sha256",
            "pre_activation_evidence_sha256",
            "environment_before_sha256",
            "environment_observed_sha256",
            "output_dir_path_sha256",
            "output_state_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in (
            "production_preflight_observed_sha256",
            "machine_production_receipt_observed_sha256",
        ):
            value = getattr(self, name)
            if value is not None:
                _hex64(value, name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        _hex40(self.promotion_git_sha, name="promotion_git_sha")
        if (
            self.production_activation_recovery_key_sha256
            != self.production_activation_candidate_sha256
            or not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskProductionActivationRecoveryError(
                "recovery receipt projection is invalid"
            )
        locked = _utc(self.transaction_locked_at_utc, name="transaction_locked_at_utc")
        observed = _utc(self.recovery_observed_at_utc, name="recovery_observed_at_utc")
        completed = _utc(self.recovery_completed_at_utc, name="recovery_completed_at_utc")
        if observed < locked or completed < observed:
            raise PilotExactTaskProductionActivationRecoveryError(
                "recovery receipt timestamps are invalid"
            )
        required_true = (
            "host_production_activation_recovery_guard_committed",
            "transaction_lock_authenticated",
            "double_observation_matched",
            "recovery_receipt_write_performed",
        )
        forced_false = (
            "controller_rerun_performed",
            "production_env_mutation_performed",
            "appliance_restart_performed",
            "production_receipt_write_performed",
            "transaction_receipt_backfilled",
            "promotion_gate_execution_authorized",
            "production_env_mutation_authorized",
            "appliance_restart_authorized",
            "production_receipt_write_authorized",
            "production_activation_authorized",
            "success_deployment_status_authorized",
            "deployment_status_mutation_authorized",
            "deployment_mutation_authorized",
            "deploy_authorized",
            "remote_write_authorized",
            "release_authorized",
            "tag_write_authorized",
            "release_mutation_authorized",
            "merge_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "product_pilot_started",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskProductionActivationRecoveryError(
                "recovery receipt lacks durable observation proof"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductionActivationRecoveryError(
                "recovery receipt retains forbidden mutation authority"
            )
        observation = _RecoveryObservation(
            environment_observed_sha256=self.environment_observed_sha256,
            output_state_sha256=self.output_state_sha256,
            production_preflight_observed_sha256=self.production_preflight_observed_sha256,
            machine_production_receipt_observed_sha256=self.machine_production_receipt_observed_sha256,
            recovery_state_class=self.recovery_state_class,
            production_activation_observed=self.production_activation_observed,
            preflight_receipt_verified=self.preflight_receipt_verified,
            machine_production_receipt_verified=self.machine_production_receipt_verified,
            environment_matches_pre_activation=self.environment_matches_pre_activation,
            required_switches_active=self.required_switches_active,
            manual_intervention_required=self.manual_intervention_required,
        )
        if observation.recovery_state_class != self.recovery_state_class:
            raise PilotExactTaskProductionActivationRecoveryError(
                "recovery receipt observation is inconsistent"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def recovery_authenticated(self) -> bool:
        return _get_live_recovery_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductionActivationRecoveryError(
                "recovery receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskProductionActivationRecoveryLedger:
    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path]:
        digest = _hex64(key, name="production_activation_recovery_key_sha256")
        return self.root / f"{digest}.json", self.root / f".{digest}.lock"

    def acquire(
        self,
        *,
        key: str,
        transaction_lock_sha256: str,
        observation: _RecoveryObservation,
        observed_at_utc: str,
    ) -> bytes:
        final, lock = self._paths(key)
        if final.exists() or final.is_symlink() or lock.exists() or lock.is_symlink():
            raise PilotExactTaskProductionActivationRecoveryError(
                "production activation recovery was already consumed or interrupted"
            )
        payload = _canonical(
            {
                "schema": _RECOVERY_LOCK_SCHEMA,
                "ledger_scope": PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_RECOVERY_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "production_activation_recovery_key_sha256": key,
                "production_activation_transaction_lock_sha256": transaction_lock_sha256,
                "recovery_observation_sha256": observation.sha256,
                "recovery_state_class": observation.recovery_state_class,
                "observed_at_utc": observed_at_utc,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskProductionActivationRecoveryError(
                "recovery classification could not be durably reserved"
            ) from exc
        return payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskProductionActivationRecoveryReceipt,
        lock_payload: bytes,
        transaction_lock_path: Path,
        transaction_lock_payload: bytes,
    ) -> PilotExactTaskProductionActivationRecoveryReceipt:
        final, lock = self._paths(receipt.production_activation_recovery_key_sha256)
        try:
            observed_lock = lock.read_bytes()
            observed_tx_lock = transaction_lock_path.read_bytes()
        except OSError as exc:
            raise PilotExactTaskProductionActivationRecoveryError(
                "durable recovery provenance became unavailable"
            ) from exc
        if (
            final.exists()
            or final.is_symlink()
            or observed_lock != lock_payload
            or observed_tx_lock != transaction_lock_payload
        ):
            raise PilotExactTaskProductionActivationRecoveryError(
                "durable recovery provenance changed before publication"
            )
        payload = receipt.canonical_json().encode("utf-8")
        try:
            create_once_file(final, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskProductionActivationRecoveryError(
                "recovery receipt could not be published"
            ) from exc
        parsed = PilotExactTaskProductionActivationRecoveryReceipt.from_mapping(
            json.loads(payload.decode("utf-8"))
        )
        _mark_recovery_authenticated(
            parsed,
            final_path=final,
            final_payload=payload,
            recovery_lock_path=lock,
            recovery_lock_payload=lock_payload,
            transaction_lock_path=transaction_lock_path,
            transaction_lock_payload=transaction_lock_payload,
        )
        if parsed.recovery_authenticated is not True:
            raise PilotExactTaskProductionActivationRecoveryError(
                "recovery receipt lost live durable provenance"
            )
        return parsed


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: PilotExactTaskProductionActivationRecoveryReceipt,
        *,
        final_path: Path,
        final_payload: bytes,
        recovery_lock_path: Path,
        recovery_lock_payload: bytes,
        transaction_lock_path: Path,
        transaction_lock_payload: bytes,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            final_path,
            final_payload,
            recovery_lock_path,
            recovery_lock_payload,
            transaction_lock_path,
            transaction_lock_payload,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        (
            pid,
            digest,
            receipt_ref,
            final_path,
            final_payload,
            recovery_lock_path,
            recovery_lock_payload,
            transaction_lock_path,
            transaction_lock_payload,
        ) = entry
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or receipt.sha256 != digest
        ):
            return None
        try:
            if (
                final_path.read_bytes() != final_payload
                or recovery_lock_path.read_bytes() != recovery_lock_payload
                or transaction_lock_path.read_bytes() != transaction_lock_payload
            ):
                return None
        except OSError:
            return None
        return MappingProxyType(
            {
                "recovery_final_path": final_path,
                "transaction_lock_path": transaction_lock_path,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_recovery_authenticated, _get_live_recovery_inputs = _live_registry()


def _recover_verified_pilot_exact_task_production_activation(
    *,
    production_activation_key_sha256: str,
    transaction_config: tx_boundary.PilotExactTaskProductionActivationTransactionConfig,
    transaction_ledger: tx_boundary._PilotExactTaskProductionActivationTransactionLedger,
    recovery_ledger: _PilotExactTaskProductionActivationRecoveryLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskProductionActivationRecoveryReceipt:
    if type(transaction_config) is not tx_boundary.PilotExactTaskProductionActivationTransactionConfig:
        raise PilotExactTaskProductionActivationRecoveryError(
            "exact ADR-DC-093 transaction config is required"
        )
    lock, tx_lock_path, tx_lock_payload, tx_lock_sha = _load_transaction_lock(
        production_activation_key_sha256=production_activation_key_sha256,
        transaction_config=transaction_config,
        transaction_ledger=transaction_ledger,
    )
    observed_at = _utc_seconds(now_provider(), name="recovery_observed_at_utc")
    if _utc(observed_at, name="recovery_observed_at_utc") < _utc(
        lock["locked_at_utc"], name="transaction_locked_at_utc"
    ):
        raise PilotExactTaskProductionActivationRecoveryError(
            "recovery observation predates the transaction lock"
        )
    first = _observe_lock_only_state(lock=lock, transaction_config=transaction_config)
    recovery_lock = recovery_ledger.acquire(
        key=lock["production_activation_key_sha256"],
        transaction_lock_sha256=tx_lock_sha,
        observation=first,
        observed_at_utc=observed_at,
    )
    lock_again, tx_lock_path_again, tx_lock_payload_again, tx_lock_sha_again = (
        _load_transaction_lock(
            production_activation_key_sha256=production_activation_key_sha256,
            transaction_config=transaction_config,
            transaction_ledger=transaction_ledger,
        )
    )
    second = _observe_lock_only_state(lock=lock_again, transaction_config=transaction_config)
    if (
        lock_again != lock
        or tx_lock_path_again != tx_lock_path
        or tx_lock_payload_again != tx_lock_payload
        or tx_lock_sha_again != tx_lock_sha
        or second != first
    ):
        raise PilotExactTaskProductionActivationRecoveryError(
            "lock-only production activation state changed after recovery reservation"
        )
    completed_at = _utc_seconds(now_provider(), name="recovery_completed_at_utc")
    if _utc(completed_at, name="recovery_completed_at_utc") < _utc(
        observed_at, name="recovery_observed_at_utc"
    ):
        raise PilotExactTaskProductionActivationRecoveryError(
            "recovery completion predates observation"
        )
    receipt = PilotExactTaskProductionActivationRecoveryReceipt(
        production_activation_recovery_ledger_root_path_sha256=recovery_ledger.root_sha256,
        production_activation_recovery_key_sha256=lock["production_activation_key_sha256"],
        production_activation_recovery_lock_sha256=hashlib.sha256(recovery_lock).hexdigest(),
        production_activation_transaction_ledger_root_path_sha256=transaction_ledger.root_sha256,
        production_activation_transaction_lock_sha256=tx_lock_sha,
        production_activation_authorization_sha256=lock["production_activation_authorization_sha256"],
        production_activation_candidate_sha256=lock["production_activation_candidate_sha256"],
        production_activation_transaction_config_sha256=lock[
            "production_activation_transaction_config_sha256"
        ],
        pre_activation_evidence_sha256=lock["pre_activation_evidence_sha256"],
        environment_before_sha256=lock["environment_before_sha256"],
        environment_observed_sha256=first.environment_observed_sha256,
        output_dir_path_sha256=lock["output_dir_path_sha256"],
        output_state_sha256=first.output_state_sha256,
        production_preflight_observed_sha256=first.production_preflight_observed_sha256,
        machine_production_receipt_observed_sha256=first.machine_production_receipt_observed_sha256,
        repository=lock["repository"],
        repository_id=lock["repository_id"],
        merge_commit_sha=lock["merge_commit_sha"],
        promotion_git_sha=lock["promotion_head_sha"],
        transaction_locked_at_utc=_utc_seconds(
            lock["locked_at_utc"], name="transaction_locked_at_utc"
        ),
        recovery_observed_at_utc=observed_at,
        recovery_completed_at_utc=completed_at,
        recovery_state_class=first.recovery_state_class,
        production_activation_observed=first.production_activation_observed,
        preflight_receipt_verified=first.preflight_receipt_verified,
        machine_production_receipt_verified=first.machine_production_receipt_verified,
        environment_matches_pre_activation=first.environment_matches_pre_activation,
        required_switches_active=first.required_switches_active,
        manual_intervention_required=first.manual_intervention_required,
    )
    return recovery_ledger.commit(
        receipt=receipt,
        lock_payload=recovery_lock,
        transaction_lock_path=tx_lock_path,
        transaction_lock_payload=tx_lock_payload,
    )


def _canonical_runtime() -> tuple[
    tx_boundary.PilotExactTaskProductionActivationTransactionConfig,
    tx_boundary._PilotExactTaskProductionActivationTransactionLedger,
    _PilotExactTaskProductionActivationRecoveryLedger,
]:
    try:
        _require_elevated_operator()
        if os.name != "nt":
            raise PilotExactTaskProductionActivationRecoveryError(
                "production activation recovery must run on the physical Windows appliance"
            )
        config, _config_sha = tx_boundary._read_host_config(tx_boundary._WINDOWS_CONFIG)
        _require_host_controlled_ledger_root(tx_boundary._WINDOWS_LEDGER)
        _require_host_controlled_ledger_root(_WINDOWS_LEDGER)
        return (
            config,
            tx_boundary._PilotExactTaskProductionActivationTransactionLedger(
                tx_boundary._WINDOWS_LEDGER
            ),
            _PilotExactTaskProductionActivationRecoveryLedger(_WINDOWS_LEDGER),
        )
    except PilotExactTaskProductionActivationRecoveryError:
        raise
    except (PhysicalHostStateError, ValueError, TypeError, OSError) as exc:
        raise PilotExactTaskProductionActivationRecoveryError(
            "production activation recovery runtime is not host-admin controlled"
        ) from exc


def recover_pilot_exact_task_production_activation(
    production_activation_key_sha256: str,
) -> PilotExactTaskProductionActivationRecoveryReceipt:
    """Classify one ADR-DC-093 lock-only state without production mutation."""
    config, transaction_ledger, recovery_ledger = _canonical_runtime()
    return _recover_verified_pilot_exact_task_production_activation(
        production_activation_key_sha256=production_activation_key_sha256,
        transaction_config=config,
        transaction_ledger=transaction_ledger,
        recovery_ledger=recovery_ledger,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
