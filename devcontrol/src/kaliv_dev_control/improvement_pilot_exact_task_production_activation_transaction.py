"""ADR-DC-093 one-shot machine-gated production activation transaction.

Consumes one fresh live ADR-DC-092 production-activation authorization.
Before any production mutation it verifies the exact promotion checkout,
machine-gate/controller hashes, BodyRig evidence candidate, Agent3 report,
and pre-activation environment, then durably consumes one transaction slot.

After the durable lock it revalidates the same evidence and executes exactly
one hash-pinned production_activation_promote.ps1 controller. A non-zero,
timed-out, or ambiguous controller result is never retried here; the durable
lock is intentionally left for a separate recovery boundary. A final receipt
is published only when the controller's create-only production-activation
receipt and the resulting modelrig.env independently match the authorized
candidate and fixed machine-gated scope.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
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
from . import improvement_pilot_exact_task_pr_lifecycle_authorization as lifecycle_auth_boundary
from . import improvement_pilot_exact_task_production_activation_authorization as auth_boundary
from .improvement_pilot_exact_task_production_activation_authorization import (
    PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_AUTHORIZATION_AUTHORITY,
    PilotExactTaskProductionActivationAuthorizationReceipt,
)

PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_TRANSACTION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-production-activation-transaction-receipt/v1"
)
PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_TRANSACTION_AUTHORITY = (
    "host-executed-one-dc-l16-machine-gated-production-activation-only"
)
PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_TRANSACTION_SCOPE = (
    "one-shot-existing-machine-gated-production-promotion-transaction-only-v1"
)
PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_TRANSACTION_CONFIG_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-production-activation-transaction-config/v1"
)
PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_TRANSACTION_LEDGER_SCOPE = "canonical-host-local-v1"
MACHINE_PREFLIGHT_SCHEMA = "kaliv-production-activation-preflight/v1"
MACHINE_FINAL_SCHEMA = "kaliv-production-activation/v1"
BODYRIG_FINAL_SCHEMA = "bodyrig.unity_live_automatic_final/v0.1"

_ALLOWED_PROMOTION_PATHS = frozenset(
    {
        "CURRENT_STATE.md",
        "PRODUCTION_ACTIVATION.md",
        "scripts/production_activation_gate.py",
        "scripts/production_activation_promote.ps1",
        "tests/workflow_production_activation_promotion.py",
    }
)
_REQUIRED_PROMOTION_PATHS = frozenset(
    {auth_boundary.PROMOTION_GATE_PATH, auth_boundary.PROMOTION_CONTROLLER_PATH}
)
_MACHINE_SCOPE = ("agent3", "tools", "scheduler", "scheduler_api")
_RUNTIME_TRUE_FIELDS = (
    "backend_health",
    "worker_health",
    "agent3_enabled",
    "agent3_write_pilot_eligible",
    "tools_surface",
    "scheduler_configured",
    "scheduler_running",
    "scheduler_resources_open",
    "scheduler_admin_surface",
)
_MAX_JSON_BYTES = 2_000_000
_MAX_TEXT_BYTES = 8_000_000
_MAX_RUN_SECONDS = 900
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_TOKEN_ENV = "MODELRIG_TOKEN"
_BASE_URL = "http://127.0.0.1:8080"
_WORKER_URL = "http://127.0.0.1:8099"
_READY_TIMEOUT_SECONDS = 120

_POSIX_CONFIG = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-pilot-exact-task-production-activation-transaction-config-v1.json"
)
_WINDOWS_CONFIG = (
    Path(r"C:\Program Files\ModelRig\DevControl\authority")
    / "rsi-pilot-exact-task-production-activation-transaction-config-v1.json"
)
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-production-activation-transaction-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-production-activation-transaction-ledger-v1"
)


class PilotExactTaskProductionActivationTransactionError(ValueError):
    """Production activation transaction is stale, ambiguous, or outside authority."""


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
        raise PilotExactTaskProductionActivationTransactionError(
            "production activation transaction evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskProductionActivationTransactionError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskProductionActivationTransactionError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    try:
        return auth_boundary._utc(value, name=name)
    except ValueError as exc:
        raise PilotExactTaskProductionActivationTransactionError(str(exc)) from exc


def _utc_seconds(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise PilotExactTaskProductionActivationTransactionError(f"{name} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PilotExactTaskProductionActivationTransactionError(f"{name} is invalid") from exc
    if parsed.tzinfo is None:
        raise PilotExactTaskProductionActivationTransactionError(f"{name} lacks timezone")
    return parsed.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _path_text(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise PilotExactTaskProductionActivationTransactionError(f"{name} is invalid")
    windows_absolute = bool(re.match(r"^[A-Za-z]:[\\/]", value))
    if not Path(value).is_absolute() and not windows_absolute:
        raise PilotExactTaskProductionActivationTransactionError(f"{name} must be absolute")
    return value


def _path_digest(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()


def _sha_file(path: Path, *, label: str, max_bytes: int = _MAX_TEXT_BYTES) -> str:
    try:
        info = path.lstat()
    except OSError as exc:
        raise PilotExactTaskProductionActivationTransactionError(f"{label} is missing") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise PilotExactTaskProductionActivationTransactionError(
            f"{label} must be a non-symlink regular file"
        )
    if info.st_size <= 0 or info.st_size > max_bytes:
        raise PilotExactTaskProductionActivationTransactionError(f"{label} size is invalid")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise PilotExactTaskProductionActivationTransactionError(f"{label} is unreadable") from exc
    return digest.hexdigest()


def _read_bytes(path: Path, *, label: str, max_bytes: int = _MAX_JSON_BYTES) -> bytes:
    _sha_file(path, label=label, max_bytes=max_bytes)
    try:
        return path.read_bytes()
    except OSError as exc:
        raise PilotExactTaskProductionActivationTransactionError(f"{label} is unreadable") from exc


def _load_json_object(path: Path, *, label: str) -> tuple[dict[str, Any], bytes, str]:
    raw = _read_bytes(path, label=label, max_bytes=_MAX_JSON_BYTES)
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskProductionActivationTransactionError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise PilotExactTaskProductionActivationTransactionError(f"{label} must be a JSON object")
    return value, raw, hashlib.sha256(raw).hexdigest()


def _require_directory(path: Path, *, label: str) -> Path:
    try:
        info = path.lstat()
    except OSError as exc:
        raise PilotExactTaskProductionActivationTransactionError(f"{label} is missing") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise PilotExactTaskProductionActivationTransactionError(
            f"{label} must be a non-symlink directory"
        )
    return path.resolve()


@dataclass(frozen=True, slots=True)
class PilotExactTaskProductionActivationTransactionConfig:
    repository: str
    repository_id: str
    promotion_repo_root: str
    appliance_dir: str
    agent3_report_path: str
    output_root: str
    powershell_path: str
    powershell_sha256: str
    source_environment: str = "staging"
    target_environment: str = "production"
    base_url: str = _BASE_URL
    worker_url: str = _WORKER_URL
    token_env: str = _TOKEN_ENV
    ready_timeout_seconds: int = _READY_TIMEOUT_SECONDS
    candidate_branch: str = auth_boundary.CANDIDATE_BRANCH
    promotion_branch: str = auth_boundary.PROMOTION_BRANCH
    promotion_gate_path: str = auth_boundary.PROMOTION_GATE_PATH
    promotion_controller_path: str = auth_boundary.PROMOTION_CONTROLLER_PATH
    require_clean_checkout: bool = True
    require_remote_candidate_match_authorized_merge: bool = True
    require_pre_activation_inactive_state: bool = True
    require_create_only_machine_receipt: bool = True
    schema: str = PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_TRANSACTION_CONFIG_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_TRANSACTION_CONFIG_SCHEMA:
            raise PilotExactTaskProductionActivationTransactionError(
                "production activation transaction config schema is unsupported"
            )
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskProductionActivationTransactionError(
                "transaction repository identity is invalid"
            )
        for name in (
            "promotion_repo_root",
            "appliance_dir",
            "agent3_report_path",
            "output_root",
            "powershell_path",
        ):
            _path_text(getattr(self, name), name=name)
        _hex64(self.powershell_sha256, name="powershell_sha256")
        if (
            self.source_environment != "staging"
            or self.target_environment != "production"
            or self.base_url != _BASE_URL
            or self.worker_url != _WORKER_URL
            or self.token_env != _TOKEN_ENV
            or self.ready_timeout_seconds != _READY_TIMEOUT_SECONDS
            or self.candidate_branch != auth_boundary.CANDIDATE_BRANCH
            or self.promotion_branch != auth_boundary.PROMOTION_BRANCH
            or self.promotion_gate_path != auth_boundary.PROMOTION_GATE_PATH
            or self.promotion_controller_path != auth_boundary.PROMOTION_CONTROLLER_PATH
            or self.require_clean_checkout is not True
            or self.require_remote_candidate_match_authorized_merge is not True
            or self.require_pre_activation_inactive_state is not True
            or self.require_create_only_machine_receipt is not True
        ):
            raise PilotExactTaskProductionActivationTransactionError(
                "transaction config weakens fixed machine-gated activation scope"
            )

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductionActivationTransactionError(
                "transaction config fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _parse_config(payload: bytes) -> PilotExactTaskProductionActivationTransactionConfig:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_JSON_BYTES:
        raise PilotExactTaskProductionActivationTransactionError(
            "transaction config payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskProductionActivationTransactionError(
            "transaction config JSON is invalid"
        ) from exc
    config = PilotExactTaskProductionActivationTransactionConfig.from_mapping(raw)
    if config.canonical_json().encode("utf-8") != payload:
        raise PilotExactTaskProductionActivationTransactionError(
            "transaction config is not canonical JSON"
        )
    return config


def _read_host_config(path: Path) -> tuple[PilotExactTaskProductionActivationTransactionConfig, str]:
    try:
        first = lifecycle_auth_boundary._read_host_authority_file(path)
        second = lifecycle_auth_boundary._read_host_authority_file(path)
    except Exception as exc:
        raise PilotExactTaskProductionActivationTransactionError(
            "transaction config is not host-admin controlled"
        ) from exc
    if first != second:
        raise PilotExactTaskProductionActivationTransactionError(
            "transaction config changed while being read"
        )
    config = _parse_config(second)
    return config, hashlib.sha256(second).hexdigest()


def _require_live_authorization(
    value: Any,
) -> PilotExactTaskProductionActivationAuthorizationReceipt:
    if type(value) is not PilotExactTaskProductionActivationAuthorizationReceipt:
        raise PilotExactTaskProductionActivationTransactionError(
            "exact live ADR-DC-092 production activation authorization is required"
        )
    try:
        replayed = PilotExactTaskProductionActivationAuthorizationReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskProductionActivationTransactionError(
            "ADR-DC-092 replay validation failed"
        ) from exc
    required_true = (
        "host_production_activation_guard_committed",
        "production_activation_readiness_authenticated",
        "production_activation_candidate_bound",
        "production_activation_authorization_config_host_pinned",
        "machine_gate_identity_host_pinned",
        "dual_external_ed25519_authorized",
        "promotion_gate_execution_authorized",
        "production_env_mutation_authorized",
        "appliance_restart_authorized",
        "production_receipt_write_authorized",
        "production_activation_authorized",
    )
    forced_false = (
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
    if (
        replayed != value
        or replayed.sha256 != value.sha256
        or value.authority != PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_AUTHORIZATION_AUTHORITY
        or value.authorization_authenticated is not True
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
        or value.source_environment != "staging"
        or value.target_environment != "production"
        or value.candidate_branch != auth_boundary.CANDIDATE_BRANCH
        or value.promotion_branch != auth_boundary.PROMOTION_BRANCH
        or value.promotion_gate_path != auth_boundary.PROMOTION_GATE_PATH
        or value.promotion_controller_path != auth_boundary.PROMOTION_CONTROLLER_PATH
        or value.required_switches_sha256 != auth_boundary.REQUIRED_SWITCHES_SHA256
    ):
        raise PilotExactTaskProductionActivationTransactionError(
            "ADR-DC-093 requires one fresh narrow ADR-DC-092 authorization"
        )
    live = auth_boundary._get_live_production_activation_authorization_inputs(value)
    if live is None:
        raise PilotExactTaskProductionActivationTransactionError(
            "ADR-DC-092 live authorization provenance is unavailable"
        )
    readiness = live.get("production_activation_readiness")
    config = live.get("production_activation_authorization_config")
    if (
        readiness is None
        or getattr(readiness, "evaluation_authenticated", False) is not True
        or getattr(readiness, "sha256", None) != value.production_activation_readiness_sha256
        or getattr(readiness, "production_activation_candidate_sha256", None)
        != value.production_activation_candidate_sha256
        or config is None
        or getattr(config, "sha256", None)
        != value.production_activation_authorization_config_sha256
    ):
        raise PilotExactTaskProductionActivationTransactionError(
            "ADR-DC-092 live authorization inputs are inconsistent"
        )
    return value


def _validate_config_for_authorization(
    config: PilotExactTaskProductionActivationTransactionConfig,
    authorization: PilotExactTaskProductionActivationAuthorizationReceipt,
) -> None:
    if (
        config.repository != authorization.repository
        or config.repository_id != authorization.repository_id
        or config.source_environment != authorization.source_environment
        or config.target_environment != authorization.target_environment
    ):
        raise PilotExactTaskProductionActivationTransactionError(
            "transaction host config does not match exact ADR-DC-092 authorization"
        )


@dataclass(frozen=True, slots=True)
class _PromotionCheckoutState:
    local_head_sha: str
    remote_candidate_sha: str
    remote_promotion_sha: str
    changed_paths: tuple[str, ...]
    working_tree_clean: bool
    candidate_is_ancestor: bool

    def __post_init__(self) -> None:
        for name in ("local_head_sha", "remote_candidate_sha", "remote_promotion_sha"):
            _hex40(getattr(self, name), name=name)
        if (
            not isinstance(self.changed_paths, tuple)
            or tuple(sorted(set(self.changed_paths))) != self.changed_paths
            or any(
                not isinstance(item, str)
                or not item
                or item.startswith("/")
                or "\\" in item
                or ".." in item.split("/")
                for item in self.changed_paths
            )
        ):
            raise PilotExactTaskProductionActivationTransactionError(
                "promotion changed-path inventory is invalid"
            )
        if not isinstance(self.working_tree_clean, bool) or not isinstance(
            self.candidate_is_ancestor, bool
        ):
            raise PilotExactTaskProductionActivationTransactionError(
                "promotion checkout booleans are invalid"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "local_head_sha": self.local_head_sha,
            "remote_candidate_sha": self.remote_candidate_sha,
            "remote_promotion_sha": self.remote_promotion_sha,
            "changed_paths": list(self.changed_paths),
            "working_tree_clean": self.working_tree_clean,
            "candidate_is_ancestor": self.candidate_is_ancestor,
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict()).encode("utf-8")).hexdigest()


def _normalize_checkout_state(
    value: Any,
    authorization: PilotExactTaskProductionActivationAuthorizationReceipt,
) -> _PromotionCheckoutState:
    if not isinstance(value, Mapping) or set(value) != {
        "local_head_sha",
        "remote_candidate_sha",
        "remote_promotion_sha",
        "changed_paths",
        "working_tree_clean",
        "candidate_is_ancestor",
    }:
        raise PilotExactTaskProductionActivationTransactionError(
            "promotion checkout observation fields mismatch"
        )
    raw_paths = value.get("changed_paths")
    if not isinstance(raw_paths, (list, tuple)):
        raise PilotExactTaskProductionActivationTransactionError(
            "promotion changed paths must be an array"
        )
    state = _PromotionCheckoutState(
        local_head_sha=value["local_head_sha"],
        remote_candidate_sha=value["remote_candidate_sha"],
        remote_promotion_sha=value["remote_promotion_sha"],
        changed_paths=tuple(raw_paths),
        working_tree_clean=value["working_tree_clean"],
        candidate_is_ancestor=value["candidate_is_ancestor"],
    )
    changed = frozenset(state.changed_paths)
    if (
        state.working_tree_clean is not True
        or state.candidate_is_ancestor is not True
        or state.remote_candidate_sha != authorization.merge_commit_sha
        or state.local_head_sha != state.remote_promotion_sha
        or not _REQUIRED_PROMOTION_PATHS.issubset(changed)
        or bool(changed - _ALLOWED_PROMOTION_PATHS)
    ):
        raise PilotExactTaskProductionActivationTransactionError(
            "promotion checkout is not the exact authorized machine-gated lane"
        )
    return state


def _target_env_values(env_path: Path) -> tuple[dict[str, str], str]:
    raw = _read_bytes(env_path, label="modelrig.env", max_bytes=_MAX_TEXT_BYTES)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise PilotExactTaskProductionActivationTransactionError(
            "modelrig.env is not valid UTF-8"
        ) from exc
    targets = {
        **auth_boundary.REQUIRED_SWITCHES,
        "KALIV_AGENT3_VALIDATION_REPORT": "",
        "KALIV_SCHEDULER_APPROVAL_SECRET": "",
    }
    by_fold = {key.casefold(): key for key in targets}
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        raw_key, raw_value = line.split("=", 1)
        key = by_fold.get(raw_key.strip().casefold())
        if key is None:
            continue
        if key in values:
            raise PilotExactTaskProductionActivationTransactionError(
                f"modelrig.env contains duplicate target key {key}"
            )
        value = raw_value.strip()
        if "#" in value:
            raise PilotExactTaskProductionActivationTransactionError(
                f"modelrig.env target {key} contains an inline comment"
            )
        if len(value) >= 2 and value[0] in {"'", '"'}:
            if value[-1] != value[0]:
                raise PilotExactTaskProductionActivationTransactionError(
                    f"modelrig.env target {key} has mismatched quotes"
                )
            value = value[1:-1]
        values[key] = value
    return values, hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class _PreActivationEvidence:
    bodyrig_final_receipt_sha256: str
    bodyrig_evidence_dir_path_sha256: str
    agent3_report_sha256: str
    agent3_report_path_sha256: str
    environment_before_sha256: str
    promotion_gate_sha256: str
    promotion_controller_sha256: str
    powershell_sha256: str
    checkout_state_sha256: str
    promotion_head_sha: str
    output_dir_path_sha256: str

    def __post_init__(self) -> None:
        for name in (
            "bodyrig_final_receipt_sha256",
            "bodyrig_evidence_dir_path_sha256",
            "agent3_report_sha256",
            "agent3_report_path_sha256",
            "environment_before_sha256",
            "promotion_gate_sha256",
            "promotion_controller_sha256",
            "powershell_sha256",
            "checkout_state_sha256",
            "output_dir_path_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.promotion_head_sha, name="promotion_head_sha")

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict()).encode("utf-8")).hexdigest()


def _collect_pre_activation_evidence(
    *,
    authorization: PilotExactTaskProductionActivationAuthorizationReceipt,
    config: PilotExactTaskProductionActivationTransactionConfig,
    bodyrig_evidence_dir: Path,
    executor: Any,
) -> tuple[_PreActivationEvidence, _PromotionCheckoutState, Path]:
    authorization = _require_live_authorization(authorization)
    _validate_config_for_authorization(config, authorization)
    bodyrig_dir = _require_directory(bodyrig_evidence_dir, label="BodyRig evidence directory")
    bodyrig, _body_raw, body_sha = _load_json_object(
        bodyrig_dir / "live-automatic-final-receipt.json",
        label="BodyRig automatic final receipt",
    )
    if (
        bodyrig.get("schema") != BODYRIG_FINAL_SCHEMA
        or bodyrig.get("production_activation") is not False
        or bodyrig.get("candidate_git_sha") != authorization.merge_commit_sha
        or bodyrig.get("machine_live_proof") is not True
        or bodyrig.get("machine_quality") is not True
        or bodyrig.get("product_exercise") is not True
    ):
        raise PilotExactTaskProductionActivationTransactionError(
            "BodyRig final evidence is not bound to the authorized merge"
        )
    package_sha = bodyrig.get("package_sha256")
    if package_sha is not None:
        _hex64(package_sha, name="BodyRig package_sha256")

    repo_root = _require_directory(Path(config.promotion_repo_root), label="promotion repo root")
    appliance_dir = _require_directory(Path(config.appliance_dir), label="appliance directory")
    output_root = _require_directory(Path(config.output_root), label="activation output root")
    gate_sha = _sha_file(repo_root / authorization.promotion_gate_path, label="promotion gate")
    controller_sha = _sha_file(
        repo_root / authorization.promotion_controller_path,
        label="promotion controller",
    )
    powershell_sha = _sha_file(Path(config.powershell_path), label="PowerShell executable")
    if (
        gate_sha != authorization.promotion_gate_sha256
        or controller_sha != authorization.promotion_controller_sha256
        or powershell_sha != config.powershell_sha256
    ):
        raise PilotExactTaskProductionActivationTransactionError(
            "machine-gate/controller/PowerShell identity differs from host-pinned authority"
        )
    agent3_path = Path(config.agent3_report_path)
    _agent3, _agent3_raw, agent3_sha = _load_json_object(
        agent3_path, label="Agent3 rig-validation report"
    )
    env_values, env_sha = _target_env_values(appliance_dir / "modelrig.env")
    if all(
        env_values.get(key) == expected
        for key, expected in auth_boundary.REQUIRED_SWITCHES.items()
    ):
        raise PilotExactTaskProductionActivationTransactionError(
            "production target switches are already active before ADR-DC-093"
        )
    if executor is None or not callable(getattr(executor, "observe", None)):
        raise PilotExactTaskProductionActivationTransactionError(
            "exact production activation executor/observer is required"
        )
    checkout = _normalize_checkout_state(executor.observe(authorization, config), authorization)
    output_dir = output_root / authorization.production_activation_candidate_sha256
    if output_dir.exists() or output_dir.is_symlink():
        raise PilotExactTaskProductionActivationTransactionError(
            "deterministic production activation output directory already exists"
        )
    evidence = _PreActivationEvidence(
        bodyrig_final_receipt_sha256=body_sha,
        bodyrig_evidence_dir_path_sha256=_path_digest(bodyrig_dir),
        agent3_report_sha256=agent3_sha,
        agent3_report_path_sha256=_path_digest(agent3_path),
        environment_before_sha256=env_sha,
        promotion_gate_sha256=gate_sha,
        promotion_controller_sha256=controller_sha,
        powershell_sha256=powershell_sha,
        checkout_state_sha256=checkout.sha256,
        promotion_head_sha=checkout.local_head_sha,
        output_dir_path_sha256=_path_digest(output_dir),
    )
    return evidence, checkout, output_dir


@dataclass(frozen=True, slots=True)
class _ExecutionResult:
    returncode: int
    stdout_sha256: str
    stderr_sha256: str

    def __post_init__(self) -> None:
        if isinstance(self.returncode, bool) or not isinstance(self.returncode, int):
            raise PilotExactTaskProductionActivationTransactionError(
                "controller returncode is invalid"
            )
        _hex64(self.stdout_sha256, name="controller_stdout_sha256")
        _hex64(self.stderr_sha256, name="controller_stderr_sha256")


def _normalize_execution_result(value: Any) -> _ExecutionResult:
    if not isinstance(value, Mapping) or set(value) != {
        "returncode",
        "stdout_sha256",
        "stderr_sha256",
    }:
        raise PilotExactTaskProductionActivationTransactionError(
            "controller execution result fields mismatch"
        )
    return _ExecutionResult(**dict(value))


def _run_checked(
    args: list[str],
    *,
    cwd: Path,
    timeout: int,
    env: Mapping[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            cwd=str(cwd),
            check=check,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            timeout=timeout,
            env=None if env is None else dict(env),
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise PilotExactTaskProductionActivationTransactionError(
            f"bounded subprocess failed: {args[0]}"
        ) from exc


class _PowerShellProductionActivationExecutor:
    def _git(self, root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return _run_checked(["git", *args], cwd=root, timeout=60, check=check)

    def observe(
        self,
        authorization: PilotExactTaskProductionActivationAuthorizationReceipt,
        config: PilotExactTaskProductionActivationTransactionConfig,
    ) -> Mapping[str, Any]:
        root = Path(config.promotion_repo_root).resolve()
        clean = self._git(
            root, "status", "--porcelain=v1", "--untracked-files=all"
        ).stdout.strip() == ""
        head = self._git(root, "rev-parse", "HEAD").stdout.strip()
        remote = self._git(
            root,
            "ls-remote",
            "--exit-code",
            "origin",
            f"refs/heads/{authorization.candidate_branch}",
            f"refs/heads/{authorization.promotion_branch}",
        ).stdout
        refs: dict[str, str] = {}
        for line in remote.splitlines():
            parts = line.strip().split("\t")
            if len(parts) == 2:
                refs[parts[1]] = parts[0]
        candidate = refs.get(f"refs/heads/{authorization.candidate_branch}", "")
        promotion = refs.get(f"refs/heads/{authorization.promotion_branch}", "")
        ancestor = (
            self._git(
                root,
                "merge-base",
                "--is-ancestor",
                candidate,
                head,
                check=False,
            ).returncode
            == 0
        )
        changed = tuple(
            sorted(
                line.strip()
                for line in self._git(
                    root, "diff", "--name-only", f"{candidate}..{head}"
                ).stdout.splitlines()
                if line.strip()
            )
        )
        return {
            "local_head_sha": head,
            "remote_candidate_sha": candidate,
            "remote_promotion_sha": promotion,
            "changed_paths": list(changed),
            "working_tree_clean": clean,
            "candidate_is_ancestor": ancestor,
        }

    def run(
        self,
        authorization: PilotExactTaskProductionActivationAuthorizationReceipt,
        config: PilotExactTaskProductionActivationTransactionConfig,
        bodyrig_evidence_dir: Path,
        output_dir: Path,
    ) -> Mapping[str, Any]:
        root = Path(config.promotion_repo_root).resolve()
        if os.environ.get(config.token_env, "").strip() == "":
            raise PilotExactTaskProductionActivationTransactionError(
                f"{config.token_env} is not set in the process environment"
            )
        args = [
            config.powershell_path,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(root / authorization.promotion_controller_path),
            "-BodyRigEvidenceDir",
            str(bodyrig_evidence_dir.resolve()),
            "-Agent3ReportPath",
            str(Path(config.agent3_report_path).resolve()),
            "-ApplianceDir",
            str(Path(config.appliance_dir).resolve()),
            "-BaseUrl",
            config.base_url,
            "-WorkerUrl",
            config.worker_url,
            "-TokenEnv",
            config.token_env,
            "-OutputDir",
            str(output_dir.resolve()),
            "-ReadyTimeoutSeconds",
            str(config.ready_timeout_seconds),
        ]
        try:
            result = subprocess.run(
                args,
                cwd=str(root),
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
                timeout=_MAX_RUN_SECONDS,
                env=os.environ.copy(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PilotExactTaskProductionActivationTransactionError(
                "production activation controller execution is ambiguous"
            ) from exc
        return {
            "returncode": result.returncode,
            "stdout_sha256": hashlib.sha256(result.stdout.encode("utf-8")).hexdigest(),
            "stderr_sha256": hashlib.sha256(result.stderr.encode("utf-8")).hexdigest(),
        }


@dataclass(frozen=True, slots=True)
class _MachineActivationEvidence:
    production_preflight_sha256: str
    machine_production_receipt_sha256: str
    environment_after_sha256: str
    promotion_git_sha: str
    origin_main_sha: str
    version: str
    worker_code_sha256: str
    bodyrig_body_id: str
    bodyrig_package_sha256: str
    machine_production_receipt_created_at_utc: str

    def __post_init__(self) -> None:
        for name in (
            "production_preflight_sha256",
            "machine_production_receipt_sha256",
            "environment_after_sha256",
            "worker_code_sha256",
            "bodyrig_package_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.promotion_git_sha, name="promotion_git_sha")
        _hex40(self.origin_main_sha, name="origin_main_sha")
        if (
            not isinstance(self.version, str)
            or not self.version
            or len(self.version) > 128
            or not isinstance(self.bodyrig_body_id, str)
            or not self.bodyrig_body_id
            or len(self.bodyrig_body_id) > 512
        ):
            raise PilotExactTaskProductionActivationTransactionError(
                "machine production identity is invalid"
            )
        _utc(
            self.machine_production_receipt_created_at_utc,
            name="machine production receipt time",
        )


def _validate_machine_output(
    *,
    authorization: PilotExactTaskProductionActivationAuthorizationReceipt,
    config: PilotExactTaskProductionActivationTransactionConfig,
    pre: _PreActivationEvidence,
    checkout: _PromotionCheckoutState,
    output_dir: Path,
    started_at_utc: str,
    completed_at_utc: str,
) -> tuple[_MachineActivationEvidence, bytes, bytes]:
    output = _require_directory(output_dir, label="production activation output directory")
    try:
        entries = sorted(item.name for item in output.iterdir())
    except OSError as exc:
        raise PilotExactTaskProductionActivationTransactionError(
            "production activation output directory is unreadable"
        ) from exc
    if entries != ["production-activation-preflight.json", "production-activation.json"]:
        raise PilotExactTaskProductionActivationTransactionError(
            "production activation output contains unexpected or missing files"
        )
    preflight, preflight_raw, preflight_sha = _load_json_object(
        output / "production-activation-preflight.json",
        label="production activation preflight receipt",
    )
    final, final_raw, final_sha = _load_json_object(
        output / "production-activation.json",
        label="production activation final receipt",
    )
    if (
        preflight.get("schema") != MACHINE_PREFLIGHT_SCHEMA
        or preflight.get("production_activation") is not False
        or preflight.get("candidate_git_sha") != authorization.merge_commit_sha
        or preflight.get("promotion_git_sha") != checkout.local_head_sha
        or preflight.get("promotion_changed_paths") != list(checkout.changed_paths)
        or (preflight.get("bodyrig") or {}).get("final_receipt_sha256")
        != pre.bodyrig_final_receipt_sha256
        or (preflight.get("agent3") or {}).get("report_sha256")
        != pre.agent3_report_sha256
        or (preflight.get("environment") or {}).get("before_sha256")
        != pre.environment_before_sha256
    ):
        raise PilotExactTaskProductionActivationTransactionError(
            "machine preflight receipt is not exactly bound to ADR-DC-093 inputs"
        )
    expected_final_fields = {
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
    if set(final) != expected_final_fields:
        raise PilotExactTaskProductionActivationTransactionError(
            "machine production receipt fields mismatch"
        )
    bindings = final.get("bindings")
    bodyrig = final.get("bodyrig")
    agent3 = final.get("agent3")
    runtime = final.get("runtime")
    if (
        not isinstance(bindings, Mapping)
        or set(bindings)
        != {
            "preflight_sha256",
            "bodyrig_final_receipt_sha256",
            "agent3_report_sha256",
            "environment_before_sha256",
            "environment_after_sha256",
        }
        or not isinstance(bodyrig, Mapping)
        or set(bodyrig)
        != {
            "body_id",
            "package_sha256",
            "machine_live_proof",
            "machine_quality",
            "product_exercise",
        }
        or not isinstance(agent3, Mapping)
        or set(agent3) != {"write_pilot_eligible", "report_bound_live"}
        or not isinstance(runtime, Mapping)
        or set(runtime) != set(_RUNTIME_TRUE_FIELDS)
    ):
        raise PilotExactTaskProductionActivationTransactionError(
            "machine production receipt nested fields mismatch"
        )
    origin_main = _hex40(final.get("origin_main_sha"), name="origin_main_sha")
    worker_code = _hex64(final.get("worker_code_sha256"), name="worker_code_sha256")
    package_sha = _hex64(bodyrig.get("package_sha256"), name="bodyrig_package_sha256")
    body_id = bodyrig.get("body_id")
    if (
        final.get("schema") != MACHINE_FINAL_SCHEMA
        or final.get("production_activation") is not True
        or final.get("scope") != list(_MACHINE_SCOPE)
        or final.get("candidate_git_sha") != authorization.merge_commit_sha
        or final.get("promotion_git_sha") != checkout.local_head_sha
        or final.get("switches") != auth_boundary.REQUIRED_SWITCHES
        or final.get("scheduler_approval_secret_present") is not True
        or final.get("human_acceptance_required") is not False
        or bindings.get("preflight_sha256") != preflight_sha
        or bindings.get("bodyrig_final_receipt_sha256")
        != pre.bodyrig_final_receipt_sha256
        or bindings.get("agent3_report_sha256") != pre.agent3_report_sha256
        or bindings.get("environment_before_sha256") != pre.environment_before_sha256
        or any(runtime.get(name) is not True for name in _RUNTIME_TRUE_FIELDS)
        or bodyrig.get("machine_live_proof") is not True
        or bodyrig.get("machine_quality") is not True
        or bodyrig.get("product_exercise") is not True
        or agent3.get("write_pilot_eligible") is not True
        or agent3.get("report_bound_live") is not True
        or not isinstance(body_id, str)
        or not body_id
    ):
        raise PilotExactTaskProductionActivationTransactionError(
            "machine production receipt did not prove exact activation"
        )
    env_values, env_after = _target_env_values(Path(config.appliance_dir) / "modelrig.env")
    if (
        env_after != bindings.get("environment_after_sha256")
        or env_after == pre.environment_before_sha256
        or any(
            env_values.get(key) != expected
            for key, expected in auth_boundary.REQUIRED_SWITCHES.items()
        )
        or os.path.normcase(
            os.path.abspath(
                os.path.expanduser(env_values.get("KALIV_AGENT3_VALIDATION_REPORT", ""))
            )
        )
        != os.path.normcase(
            os.path.abspath(os.path.expanduser(config.agent3_report_path))
        )
        or len(env_values.get("KALIV_SCHEDULER_APPROVAL_SECRET", "").encode("utf-8")) < 32
    ):
        raise PilotExactTaskProductionActivationTransactionError(
            "post-controller modelrig.env does not match machine receipt"
        )
    machine_time = _utc_seconds(
        final.get("created_at"), name="machine production receipt time"
    )
    started = _utc(started_at_utc, name="controller_started_at_utc")
    completed = _utc(completed_at_utc, name="controller_completed_at_utc")
    observed = _utc(machine_time, name="machine production receipt time")
    if observed < started or observed > completed:
        raise PilotExactTaskProductionActivationTransactionError(
            "machine production receipt timestamp is outside controller execution"
        )
    if (
        preflight.get("origin_main_sha") != origin_main
        or preflight.get("version") != final.get("version")
        or preflight.get("worker_code_sha256") != worker_code
    ):
        raise PilotExactTaskProductionActivationTransactionError(
            "machine preflight/final identity changed during controller execution"
        )
    evidence = _MachineActivationEvidence(
        production_preflight_sha256=preflight_sha,
        machine_production_receipt_sha256=final_sha,
        environment_after_sha256=env_after,
        promotion_git_sha=checkout.local_head_sha,
        origin_main_sha=origin_main,
        version=final.get("version"),
        worker_code_sha256=worker_code,
        bodyrig_body_id=body_id,
        bodyrig_package_sha256=package_sha,
        machine_production_receipt_created_at_utc=machine_time,
    )
    return evidence, preflight_raw, final_raw


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskProductionActivationTransactionReceipt:
    production_activation_transaction_ledger_root_path_sha256: str
    production_activation_key_sha256: str
    production_activation_transaction_lock_sha256: str
    production_activation_authorization_sha256: str
    production_activation_authorization_config_sha256: str
    production_activation_readiness_sha256: str
    production_activation_candidate_sha256: str
    production_activation_transaction_config_sha256: str
    bodyrig_final_receipt_sha256: str
    bodyrig_evidence_dir_path_sha256: str
    agent3_report_sha256: str
    agent3_report_path_sha256: str
    production_preflight_sha256: str
    machine_production_receipt_sha256: str
    environment_before_sha256: str
    environment_after_sha256: str
    pre_lock_checkout_state_sha256: str
    post_lock_checkout_state_sha256: str
    output_dir_path_sha256: str
    promotion_gate_sha256: str
    promotion_controller_sha256: str
    powershell_sha256: str
    required_switches_sha256: str
    controller_stdout_sha256: str
    controller_stderr_sha256: str
    repository: str
    repository_id: str
    source_environment: str
    target_environment: str
    merge_commit_sha: str
    deployment_id: int
    deployment_node_id_sha256: str
    success_deployment_status_id: int
    success_deployment_status_node_id_sha256: str
    success_status_completion_source: str
    success_status_source_action: str
    candidate_branch: str
    promotion_branch: str
    promotion_gate_path: str
    promotion_controller_path: str
    promotion_git_sha: str
    origin_main_sha: str
    version: str
    worker_code_sha256: str
    bodyrig_body_id: str
    bodyrig_package_sha256: str
    authorization_requested_at_utc: str
    authorization_expires_at_utc: str
    transaction_locked_at_utc: str
    controller_started_at_utc: str
    machine_production_receipt_created_at_utc: str
    controller_completed_at_utc: str
    controller_returncode: int
    host_production_activation_transaction_guard_committed: bool = True
    production_activation_authorization_authenticated: bool = True
    production_activation_authority_consumed: bool = True
    machine_gate_identity_verified: bool = True
    bodyrig_machine_evidence_bound: bool = True
    agent3_write_pilot_evidence_bound: bool = True
    pre_activation_state_verified: bool = True
    remote_candidate_matches_authorized_merge: bool = True
    promotion_checkout_allowlisted: bool = True
    controller_executed_once: bool = True
    controller_exit_success: bool = True
    production_machine_receipt_verified: bool = True
    production_env_mutation_performed: bool = True
    appliance_restart_performed: bool = True
    production_receipt_write_performed: bool = True
    production_activation_completed: bool = True
    production_activation: bool = True
    recovery_required: bool = False
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
    transaction_scope: str = PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_TRANSACTION_SCOPE
    authority: str = PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_TRANSACTION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_TRANSACTION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_TRANSACTION_SCHEMA
            or self.authority != PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_TRANSACTION_AUTHORITY
            or self.transaction_scope != PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_TRANSACTION_SCOPE
        ):
            raise PilotExactTaskProductionActivationTransactionError(
                "transaction receipt identity is unsupported"
            )
        for name in (
            "production_activation_transaction_ledger_root_path_sha256",
            "production_activation_key_sha256",
            "production_activation_transaction_lock_sha256",
            "production_activation_authorization_sha256",
            "production_activation_authorization_config_sha256",
            "production_activation_readiness_sha256",
            "production_activation_candidate_sha256",
            "production_activation_transaction_config_sha256",
            "bodyrig_final_receipt_sha256",
            "bodyrig_evidence_dir_path_sha256",
            "agent3_report_sha256",
            "agent3_report_path_sha256",
            "production_preflight_sha256",
            "machine_production_receipt_sha256",
            "environment_before_sha256",
            "environment_after_sha256",
            "pre_lock_checkout_state_sha256",
            "post_lock_checkout_state_sha256",
            "output_dir_path_sha256",
            "promotion_gate_sha256",
            "promotion_controller_sha256",
            "powershell_sha256",
            "required_switches_sha256",
            "controller_stdout_sha256",
            "controller_stderr_sha256",
            "deployment_node_id_sha256",
            "success_deployment_status_node_id_sha256",
            "worker_code_sha256",
            "bodyrig_package_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("merge_commit_sha", "promotion_git_sha", "origin_main_sha"):
            _hex40(getattr(self, name), name=name)
        if (
            self.production_activation_key_sha256 != self.production_activation_candidate_sha256
            or not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.source_environment != "staging"
            or self.target_environment != "production"
            or self.candidate_branch != auth_boundary.CANDIDATE_BRANCH
            or self.promotion_branch != auth_boundary.PROMOTION_BRANCH
            or self.promotion_gate_path != auth_boundary.PROMOTION_GATE_PATH
            or self.promotion_controller_path != auth_boundary.PROMOTION_CONTROLLER_PATH
            or self.required_switches_sha256 != auth_boundary.REQUIRED_SWITCHES_SHA256
            or self.pre_lock_checkout_state_sha256 != self.post_lock_checkout_state_sha256
            or self.environment_before_sha256 == self.environment_after_sha256
            or self.success_status_completion_source not in ("transaction", "recovery")
            or self.success_status_source_action not in (
                "execute_exact_staging_success_status",
                "finalize_existing_state",
            )
            or isinstance(self.controller_returncode, bool)
            or self.controller_returncode != 0
            or not isinstance(self.version, str)
            or not self.version
            or not isinstance(self.bodyrig_body_id, str)
            or not self.bodyrig_body_id
        ):
            raise PilotExactTaskProductionActivationTransactionError(
                "transaction receipt projection is invalid"
            )
        if (
            self.success_status_completion_source == "transaction"
            and self.success_status_source_action != "execute_exact_staging_success_status"
        ) or (
            self.success_status_completion_source == "recovery"
            and self.success_status_source_action != "finalize_existing_state"
        ):
            raise PilotExactTaskProductionActivationTransactionError(
                "transaction completion provenance is inconsistent"
            )
        requested = _utc(self.authorization_requested_at_utc, name="authorization_requested_at_utc")
        expires = _utc(self.authorization_expires_at_utc, name="authorization_expires_at_utc")
        locked = _utc(self.transaction_locked_at_utc, name="transaction_locked_at_utc")
        started = _utc(self.controller_started_at_utc, name="controller_started_at_utc")
        machine = _utc(
            self.machine_production_receipt_created_at_utc,
            name="machine_production_receipt_created_at_utc",
        )
        completed = _utc(self.controller_completed_at_utc, name="controller_completed_at_utc")
        if not requested <= locked < expires or not locked <= started <= machine <= completed:
            raise PilotExactTaskProductionActivationTransactionError(
                "transaction receipt timestamps are invalid"
            )
        required_true = (
            "host_production_activation_transaction_guard_committed",
            "production_activation_authorization_authenticated",
            "production_activation_authority_consumed",
            "machine_gate_identity_verified",
            "bodyrig_machine_evidence_bound",
            "agent3_write_pilot_evidence_bound",
            "pre_activation_state_verified",
            "remote_candidate_matches_authorized_merge",
            "promotion_checkout_allowlisted",
            "controller_executed_once",
            "controller_exit_success",
            "production_machine_receipt_verified",
            "production_env_mutation_performed",
            "appliance_restart_performed",
            "production_receipt_write_performed",
            "production_activation_completed",
            "production_activation",
        )
        forced_false = (
            "recovery_required",
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
            raise PilotExactTaskProductionActivationTransactionError(
                "transaction receipt does not prove complete production activation"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductionActivationTransactionError(
                "completed transaction retains forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def transaction_authenticated(self) -> bool:
        return _get_live_production_activation_transaction_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductionActivationTransactionError(
                "transaction receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskProductionActivationTransactionLedger:
    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path]:
        digest = _hex64(key, name="production_activation_key_sha256")
        return self.root / f"{digest}.json", self.root / f".{digest}.lock"

    def acquire(
        self,
        *,
        authorization: PilotExactTaskProductionActivationAuthorizationReceipt,
        config: PilotExactTaskProductionActivationTransactionConfig,
        pre: _PreActivationEvidence,
        checkout: _PromotionCheckoutState,
        locked_at_utc: str,
    ) -> bytes:
        key = authorization.production_activation_candidate_sha256
        final, lock = self._paths(key)
        if final.exists() or final.is_symlink() or lock.exists() or lock.is_symlink():
            raise PilotExactTaskProductionActivationTransactionError(
                "production activation candidate already executed or needs recovery"
            )
        lock_payload = _canonical(
            {
                "schema": "kaliv-rsi-dc-l16-exact-task-production-activation-transaction-lock/v1",
                "ledger_scope": PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_TRANSACTION_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "production_activation_key_sha256": key,
                "production_activation_authorization_sha256": authorization.sha256,
                "production_activation_candidate_sha256": authorization.production_activation_candidate_sha256,
                "production_activation_transaction_config_sha256": config.sha256,
                "pre_activation_evidence_sha256": pre.sha256,
                "pre_lock_checkout_state_sha256": checkout.sha256,
                "bodyrig_final_receipt_sha256": pre.bodyrig_final_receipt_sha256,
                "agent3_report_sha256": pre.agent3_report_sha256,
                "environment_before_sha256": pre.environment_before_sha256,
                "promotion_gate_sha256": pre.promotion_gate_sha256,
                "promotion_controller_sha256": pre.promotion_controller_sha256,
                "powershell_sha256": pre.powershell_sha256,
                "output_dir_path_sha256": pre.output_dir_path_sha256,
                "repository": authorization.repository,
                "repository_id": authorization.repository_id,
                "merge_commit_sha": authorization.merge_commit_sha,
                "promotion_head_sha": pre.promotion_head_sha,
                "locked_at_utc": locked_at_utc,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, lock_payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskProductionActivationTransactionError(
                "production activation transaction could not be durably reserved"
            ) from exc
        return lock_payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskProductionActivationTransactionReceipt,
        lock_payload: bytes,
        authorization: PilotExactTaskProductionActivationAuthorizationReceipt,
        config: PilotExactTaskProductionActivationTransactionConfig,
        preflight_path: Path,
        preflight_payload: bytes,
        machine_receipt_path: Path,
        machine_receipt_payload: bytes,
    ) -> PilotExactTaskProductionActivationTransactionReceipt:
        final, lock = self._paths(receipt.production_activation_key_sha256)
        try:
            observed_lock = lock.read_bytes()
        except OSError as exc:
            raise PilotExactTaskProductionActivationTransactionError(
                "production activation transaction lock is unavailable"
            ) from exc
        if final.exists() or final.is_symlink() or observed_lock != lock_payload:
            raise PilotExactTaskProductionActivationTransactionError(
                "durable production activation transaction state changed"
            )
        final_payload = receipt.canonical_json().encode("utf-8")
        try:
            create_once_file(final, final_payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskProductionActivationTransactionError(
                "production activation transaction receipt could not be published"
            ) from exc
        parsed = PilotExactTaskProductionActivationTransactionReceipt.from_mapping(
            json.loads(final_payload.decode("utf-8"))
        )
        _mark_production_activation_transaction_authenticated(
            parsed,
            authorization=authorization,
            config=config,
            final_path=final,
            final_payload=final_payload,
            lock_path=lock,
            lock_payload=lock_payload,
            preflight_path=preflight_path,
            preflight_payload=preflight_payload,
            machine_receipt_path=machine_receipt_path,
            machine_receipt_payload=machine_receipt_payload,
        )
        if parsed.transaction_authenticated is not True:
            raise PilotExactTaskProductionActivationTransactionError(
                "production activation transaction lost live provenance"
            )
        return parsed


def _read_bound(path: Path, *, max_bytes: int = _MAX_JSON_BYTES) -> bytes | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return data if data and len(data) <= max_bytes else None


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: PilotExactTaskProductionActivationTransactionReceipt,
        *,
        authorization: PilotExactTaskProductionActivationAuthorizationReceipt,
        config: PilotExactTaskProductionActivationTransactionConfig,
        final_path: Path,
        final_payload: bytes,
        lock_path: Path,
        lock_payload: bytes,
        preflight_path: Path,
        preflight_payload: bytes,
        machine_receipt_path: Path,
        machine_receipt_payload: bytes,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            weakref.ref(authorization),
            config,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
            preflight_path,
            preflight_payload,
            machine_receipt_path,
            machine_receipt_payload,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        (
            pid,
            digest,
            receipt_ref,
            authorization_ref,
            config,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
            preflight_path,
            preflight_payload,
            machine_receipt_path,
            machine_receipt_payload,
        ) = entry
        authorization = authorization_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or authorization is None
            or receipt.sha256 != digest
            or authorization.authorization_authenticated is not True
            or authorization.sha256 != receipt.production_activation_authorization_sha256
            or config.sha256 != receipt.production_activation_transaction_config_sha256
            or _read_bound(final_path) != final_payload
            or _read_bound(lock_path) != lock_payload
            or _read_bound(preflight_path) != preflight_payload
            or _read_bound(machine_receipt_path) != machine_receipt_payload
        ):
            return None
        return MappingProxyType(
            {
                "production_activation_authorization": authorization,
                "production_activation_transaction_config": config,
                "production_activation_preflight_path": preflight_path,
                "machine_production_receipt_path": machine_receipt_path,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_production_activation_transaction_authenticated,
    _get_live_production_activation_transaction_inputs,
) = _live_registry()


def _execute_verified_pilot_exact_task_production_activation(
    *,
    production_activation_authorization: PilotExactTaskProductionActivationAuthorizationReceipt,
    transaction_config: PilotExactTaskProductionActivationTransactionConfig,
    transaction_ledger: _PilotExactTaskProductionActivationTransactionLedger,
    bodyrig_evidence_dir: Path,
    executor: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskProductionActivationTransactionReceipt:
    authorization = _require_live_authorization(production_activation_authorization)
    if type(transaction_config) is not PilotExactTaskProductionActivationTransactionConfig:
        raise PilotExactTaskProductionActivationTransactionError(
            "exact production activation transaction config is required"
        )
    _validate_config_for_authorization(transaction_config, authorization)
    now = now_provider()
    current = _utc(now, name="transaction_preflight_at_utc")
    requested = _utc(authorization.requested_at_utc, name="authorization_requested_at_utc")
    expires = _utc(authorization.expires_at_utc, name="authorization_expires_at_utc")
    if not requested <= current < expires:
        raise PilotExactTaskProductionActivationTransactionError(
            "production activation authorization is expired before transaction"
        )
    pre, checkout, output_dir = _collect_pre_activation_evidence(
        authorization=authorization,
        config=transaction_config,
        bodyrig_evidence_dir=Path(bodyrig_evidence_dir),
        executor=executor,
    )
    locked_at = now_provider()
    locked = _utc(locked_at, name="transaction_locked_at_utc")
    if not requested <= locked < expires:
        raise PilotExactTaskProductionActivationTransactionError(
            "production activation authorization expired before durable lock"
        )
    lock_payload = transaction_ledger.acquire(
        authorization=authorization,
        config=transaction_config,
        pre=pre,
        checkout=checkout,
        locked_at_utc=locked_at,
    )
    authorization = _require_live_authorization(authorization)
    after, checkout_after, output_dir_after = _collect_pre_activation_evidence(
        authorization=authorization,
        config=transaction_config,
        bodyrig_evidence_dir=Path(bodyrig_evidence_dir),
        executor=executor,
    )
    if after != pre or checkout_after != checkout or output_dir_after != output_dir:
        raise PilotExactTaskProductionActivationTransactionError(
            "production activation evidence changed after durable lock"
        )
    launch_at = now_provider()
    launch = _utc(launch_at, name="controller_started_at_utc")
    if not requested <= launch < expires:
        raise PilotExactTaskProductionActivationTransactionError(
            "production activation authorization expired after durable lock"
        )
    if executor is None or not callable(getattr(executor, "run", None)):
        raise PilotExactTaskProductionActivationTransactionError(
            "production activation executor cannot run the exact controller"
        )
    execution = _normalize_execution_result(
        executor.run(
            authorization,
            transaction_config,
            Path(bodyrig_evidence_dir),
            output_dir,
        )
    )
    completed_at = now_provider()
    _utc(completed_at, name="controller_completed_at_utc")
    if execution.returncode != 0:
        raise PilotExactTaskProductionActivationTransactionError(
            "production activation controller failed after durable lock; do not retry"
        )
    machine, preflight_payload, machine_payload = _validate_machine_output(
        authorization=authorization,
        config=transaction_config,
        pre=pre,
        checkout=checkout,
        output_dir=output_dir,
        started_at_utc=launch_at,
        completed_at_utc=completed_at,
    )
    receipt = PilotExactTaskProductionActivationTransactionReceipt(
        production_activation_transaction_ledger_root_path_sha256=transaction_ledger.root_sha256,
        production_activation_key_sha256=authorization.production_activation_candidate_sha256,
        production_activation_transaction_lock_sha256=hashlib.sha256(lock_payload).hexdigest(),
        production_activation_authorization_sha256=authorization.sha256,
        production_activation_authorization_config_sha256=authorization.production_activation_authorization_config_sha256,
        production_activation_readiness_sha256=authorization.production_activation_readiness_sha256,
        production_activation_candidate_sha256=authorization.production_activation_candidate_sha256,
        production_activation_transaction_config_sha256=transaction_config.sha256,
        bodyrig_final_receipt_sha256=pre.bodyrig_final_receipt_sha256,
        bodyrig_evidence_dir_path_sha256=pre.bodyrig_evidence_dir_path_sha256,
        agent3_report_sha256=pre.agent3_report_sha256,
        agent3_report_path_sha256=pre.agent3_report_path_sha256,
        production_preflight_sha256=machine.production_preflight_sha256,
        machine_production_receipt_sha256=machine.machine_production_receipt_sha256,
        environment_before_sha256=pre.environment_before_sha256,
        environment_after_sha256=machine.environment_after_sha256,
        pre_lock_checkout_state_sha256=pre.checkout_state_sha256,
        post_lock_checkout_state_sha256=after.checkout_state_sha256,
        output_dir_path_sha256=pre.output_dir_path_sha256,
        promotion_gate_sha256=pre.promotion_gate_sha256,
        promotion_controller_sha256=pre.promotion_controller_sha256,
        powershell_sha256=pre.powershell_sha256,
        required_switches_sha256=authorization.required_switches_sha256,
        controller_stdout_sha256=execution.stdout_sha256,
        controller_stderr_sha256=execution.stderr_sha256,
        repository=authorization.repository,
        repository_id=authorization.repository_id,
        source_environment=authorization.source_environment,
        target_environment=authorization.target_environment,
        merge_commit_sha=authorization.merge_commit_sha,
        deployment_id=authorization.deployment_id,
        deployment_node_id_sha256=authorization.deployment_node_id_sha256,
        success_deployment_status_id=authorization.success_deployment_status_id,
        success_deployment_status_node_id_sha256=authorization.success_deployment_status_node_id_sha256,
        success_status_completion_source=authorization.success_status_completion_source,
        success_status_source_action=authorization.success_status_source_action,
        candidate_branch=authorization.candidate_branch,
        promotion_branch=authorization.promotion_branch,
        promotion_gate_path=authorization.promotion_gate_path,
        promotion_controller_path=authorization.promotion_controller_path,
        promotion_git_sha=machine.promotion_git_sha,
        origin_main_sha=machine.origin_main_sha,
        version=machine.version,
        worker_code_sha256=machine.worker_code_sha256,
        bodyrig_body_id=machine.bodyrig_body_id,
        bodyrig_package_sha256=machine.bodyrig_package_sha256,
        authorization_requested_at_utc=authorization.requested_at_utc,
        authorization_expires_at_utc=authorization.expires_at_utc,
        transaction_locked_at_utc=locked_at,
        controller_started_at_utc=launch_at,
        machine_production_receipt_created_at_utc=machine.machine_production_receipt_created_at_utc,
        controller_completed_at_utc=completed_at,
        controller_returncode=execution.returncode,
    )
    preflight_path = output_dir / "production-activation-preflight.json"
    machine_receipt_path = output_dir / "production-activation.json"
    return transaction_ledger.commit(
        receipt=receipt,
        lock_payload=lock_payload,
        authorization=authorization,
        config=transaction_config,
        preflight_path=preflight_path,
        preflight_payload=preflight_payload,
        machine_receipt_path=machine_receipt_path,
        machine_receipt_payload=machine_payload,
    )


def _canonical_runtime() -> tuple[
    PilotExactTaskProductionActivationTransactionConfig,
    _PilotExactTaskProductionActivationTransactionLedger,
    _PowerShellProductionActivationExecutor,
]:
    try:
        _require_elevated_operator()
        if os.name != "nt":
            raise PilotExactTaskProductionActivationTransactionError(
                "production activation transaction must run on the physical Windows appliance"
            )
        config, _config_sha = _read_host_config(_WINDOWS_CONFIG)
        _require_host_controlled_ledger_root(_WINDOWS_LEDGER)
        return (
            config,
            _PilotExactTaskProductionActivationTransactionLedger(_WINDOWS_LEDGER),
            _PowerShellProductionActivationExecutor(),
        )
    except PilotExactTaskProductionActivationTransactionError:
        raise
    except (PhysicalHostStateError, ValueError, TypeError, OSError) as exc:
        raise PilotExactTaskProductionActivationTransactionError(
            "production activation transaction runtime is not host-admin controlled"
        ) from exc


def execute_pilot_exact_task_production_activation(
    production_activation_authorization: PilotExactTaskProductionActivationAuthorizationReceipt,
    bodyrig_evidence_dir: Path,
) -> PilotExactTaskProductionActivationTransactionReceipt:
    """Consume ADR-DC-092 and run the exact machine-gated production controller once."""
    config, ledger, executor = _canonical_runtime()
    return _execute_verified_pilot_exact_task_production_activation(
        production_activation_authorization=production_activation_authorization,
        transaction_config=config,
        transaction_ledger=ledger,
        bodyrig_evidence_dir=Path(bodyrig_evidence_dir),
        executor=executor,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
