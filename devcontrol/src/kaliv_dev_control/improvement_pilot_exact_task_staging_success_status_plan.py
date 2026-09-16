"""ADR-DC-085 deterministic staging success Deployment Status plan/readiness.

Consumes exactly one fresh live ADR-DC-084 staging runtime build-identity receipt
plus one host-admin-pinned success-status plan config. It freezes the exact
success Deployment Status body for the already-running staging Deployment.

This boundary is intent/readiness only. It performs no network I/O and grants
no Deployment Status, Deployment, release, production, or other write authority.
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

from ._improvement_physical_state_host_control import PhysicalHostStateError, _require_elevated_operator
from . import improvement_pilot_exact_task_pr_lifecycle_authorization as lifecycle_auth_boundary
from . import improvement_pilot_exact_task_staging_runtime_build_identity as build_identity_boundary
from .improvement_pilot_exact_task_staging_runtime_build_identity import (
    PILOT_EXACT_TASK_STAGING_RUNTIME_BUILD_IDENTITY_AUTHORITY,
    PilotExactTaskStagingRuntimeBuildIdentityReceipt,
)

PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_PLAN_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-staging-success-status-plan-receipt/v1"
)
PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_PLAN_AUTHORITY = (
    "host-planned-one-dc-l16-exact-staging-success-status-intent-only"
)
PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_PLAN_SCOPE = (
    "deterministic-exact-staging-success-status-intent-only-v1"
)
PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_PLAN_CONFIG_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-staging-success-status-plan-config/v1"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_MAX_FILE_BYTES = 1024 * 1024
_MAX_DESCRIPTION_BYTES = 1024
_STATUS_STATE = "success"
_STATUS_ENVIRONMENT = "staging"
_STATUS_AUTO_INACTIVE = False

_POSIX_CONFIG = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-pilot-exact-task-staging-success-status-plan-config-v1.json"
)
_WINDOWS_CONFIG = (
    Path(r"C:\Program Files\ModelRig\DevControl\authority")
    / "rsi-pilot-exact-task-staging-success-status-plan-config-v1.json"
)


class PilotExactTaskStagingSuccessStatusPlanError(ValueError):
    """Runtime build evidence or deterministic success intent is unsafe."""


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
        raise PilotExactTaskStagingSuccessStatusPlanError(
            "staging success status evidence is not canonical JSON"
        ) from exc


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskStagingSuccessStatusPlanError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskStagingSuccessStatusPlanError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskStagingSuccessStatusPlanError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskStagingSuccessStatusPlanError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True, slots=True)
class PilotExactTaskStagingSuccessStatusPlanConfig:
    repository: str
    repository_id: str
    deployment_status_state: str = _STATUS_STATE
    deployment_status_environment: str = _STATUS_ENVIRONMENT
    deployment_status_auto_inactive: bool = _STATUS_AUTO_INACTIVE
    allow_log_url: bool = False
    allow_environment_url: bool = False
    schema: str = PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_PLAN_CONFIG_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_PLAN_CONFIG_SCHEMA:
            raise PilotExactTaskStagingSuccessStatusPlanError(
                "staging success status config schema is unsupported"
            )
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskStagingSuccessStatusPlanError(
                "staging success status config repository identity is invalid"
            )
        if (
            self.deployment_status_state != _STATUS_STATE
            or self.deployment_status_environment != _STATUS_ENVIRONMENT
            or self.deployment_status_auto_inactive is not False
            or self.allow_log_url is not False
            or self.allow_environment_url is not False
        ):
            raise PilotExactTaskStagingSuccessStatusPlanError(
                "staging success status config weakens fixed success intent"
            )

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskStagingSuccessStatusPlanError(
                "staging success status config fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _parse_config(payload: bytes) -> PilotExactTaskStagingSuccessStatusPlanConfig:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskStagingSuccessStatusPlanError(
            "staging success status config payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskStagingSuccessStatusPlanError(
            "staging success status config JSON is invalid"
        ) from exc
    config = PilotExactTaskStagingSuccessStatusPlanConfig.from_mapping(raw)
    if config.canonical_json().encode("utf-8") != payload:
        raise PilotExactTaskStagingSuccessStatusPlanError(
            "staging success status config is not canonical JSON"
        )
    return config


def _read_host_config(path: Path) -> tuple[PilotExactTaskStagingSuccessStatusPlanConfig, str]:
    try:
        first = lifecycle_auth_boundary._read_host_authority_file(Path(path))
        second = lifecycle_auth_boundary._read_host_authority_file(Path(path))
    except Exception as exc:
        raise PilotExactTaskStagingSuccessStatusPlanError(
            "staging success status config is not host-admin controlled"
        ) from exc
    if first != second:
        raise PilotExactTaskStagingSuccessStatusPlanError(
            "staging success status config changed while being read"
        )
    config = _parse_config(second)
    return config, hashlib.sha256(second).hexdigest()


def _require_live_build_identity(
    value: Any,
) -> PilotExactTaskStagingRuntimeBuildIdentityReceipt:
    if type(value) is not PilotExactTaskStagingRuntimeBuildIdentityReceipt:
        raise PilotExactTaskStagingSuccessStatusPlanError(
            "exact live ADR-DC-084 staging runtime build identity is required"
        )
    try:
        replayed = PilotExactTaskStagingRuntimeBuildIdentityReceipt.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskStagingSuccessStatusPlanError(
            "ADR-DC-084 replay validation failed"
        ) from exc
    required_true = (
        "staging_runtime_verification_authenticated",
        "functional_staging_runtime_verified",
        "server_commit_identity_observable",
        "server_commit_identity_verified",
        "server_clean_build_verified",
        "server_artifact_identity_verified",
        "worker_frozen_build_verified",
        "worker_commit_identity_verified",
        "worker_source_identity_verified",
        "worker_artifact_identity_verified",
        "server_worker_commit_matched",
        "double_build_identity_observation_matched",
        "runtime_commit_identity_observable",
        "runtime_commit_identity_verified",
        "runtime_artifact_identity_verified",
        "staging_runtime_build_identity_verified",
        "success_deployment_status_ready",
    )
    required_false = (
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
        "production_activation_authorized",
        "product_pilot_started",
        "nonce_reusable",
    )
    if (
        replayed != value
        or replayed.sha256 != value.sha256
        or value.authority != PILOT_EXACT_TASK_STAGING_RUNTIME_BUILD_IDENTITY_AUTHORITY
        or value.verification_authenticated is not True
        or value.deployment_environment != "staging"
        or value.deployment_status_state != "in_progress"
        or value.deployment_status_environment != "staging"
        or value.server_commit_sha != value.merge_commit_sha
        or value.worker_commit_sha != value.merge_commit_sha
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in required_false)
    ):
        raise PilotExactTaskStagingSuccessStatusPlanError(
            "ADR-DC-085 requires one fresh inert ADR-DC-084 build identity receipt"
        )
    live = build_identity_boundary._get_live_staging_runtime_build_identity_inputs(value)
    if (
        live is None
        or live.get("runtime_build_identity_observation_sha256")
        != value.runtime_build_identity_observation_sha256
    ):
        raise PilotExactTaskStagingSuccessStatusPlanError(
            "ADR-DC-084 live provenance is unavailable"
        )
    return value


def _description(source: PilotExactTaskStagingRuntimeBuildIdentityReceipt) -> str:
    value = (
        "ModelRig exact RSI staging runtime verified; "
        f"deployment={source.deployment_id}; sha={source.merge_commit_sha[:12]}"
    )
    if not value or value.strip() != value or len(value.encode("utf-8")) > _MAX_DESCRIPTION_BYTES:
        raise PilotExactTaskStagingSuccessStatusPlanError(
            "deterministic success status description is invalid"
        )
    return value


def _status_body(*, state: str, description: str, environment: str, auto_inactive: bool) -> str:
    return _canonical(
        {
            "state": state,
            "description": description,
            "environment": environment,
            "auto_inactive": auto_inactive,
        }
    )


def _success_intent_sha256(
    *,
    source: PilotExactTaskStagingRuntimeBuildIdentityReceipt,
    config_sha256: str,
    body: str,
) -> str:
    payload = {
        "staging_runtime_build_identity_sha256": source.sha256,
        "staging_runtime_verification_sha256": source.staging_runtime_verification_sha256,
        "post_staging_deployment_status_attestation_sha256": (
            source.post_staging_deployment_status_attestation_sha256
        ),
        "deployment_status_authorization_sha256": source.deployment_status_authorization_sha256,
        "staging_deployment_status_plan_sha256": source.staging_deployment_status_plan_sha256,
        "deployment_status_intent_sha256": source.deployment_status_intent_sha256,
        "status_transaction_lock_sha256": source.status_transaction_lock_sha256,
        "status_recovery_lock_sha256": source.status_recovery_lock_sha256,
        "repository": source.repository,
        "repository_id": source.repository_id,
        "deployment_id": source.deployment_id,
        "deployment_node_id_sha256": source.deployment_node_id_sha256,
        "current_deployment_status_id": source.deployment_status_id,
        "current_deployment_status_node_id_sha256": source.deployment_status_node_id_sha256,
        "merge_commit_sha": source.merge_commit_sha,
        "exact_source_version": source.exact_source_version,
        "runtime_build_identity_observation_sha256": (
            source.runtime_build_identity_observation_sha256
        ),
        "server_commit_sha": source.server_commit_sha,
        "server_executable_sha256": source.server_executable_sha256,
        "worker_commit_sha": source.worker_commit_sha,
        "worker_code_sha256": source.worker_code_sha256,
        "worker_artifact_sha256": source.worker_artifact_sha256,
        "staging_success_status_plan_config_sha256": _hex64(
            config_sha256, name="staging_success_status_plan_config_sha256"
        ),
        "success_deployment_status_body": body,
    }
    return _sha256_text(_canonical(payload))


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: Any,
        *,
        source: PilotExactTaskStagingRuntimeBuildIdentityReceipt,
        config_sha256: str,
        intent_sha256: str,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            weakref.ref(source),
            config_sha256,
            intent_sha256,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, source_ref, config_sha, intent_sha = entry
        source = source_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or source is None
            or receipt.sha256 != digest
            or source.verification_authenticated is not True
            or source.sha256 != receipt.staging_runtime_build_identity_sha256
            or receipt.staging_success_status_plan_config_sha256 != config_sha
            or receipt.success_deployment_status_intent_sha256 != intent_sha
        ):
            return None
        return MappingProxyType(
            {
                "staging_runtime_build_identity": source,
                "staging_success_status_plan_config_sha256": config_sha,
                "success_deployment_status_intent_sha256": intent_sha,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_staging_success_status_plan_authenticated,
    _get_live_staging_success_status_plan_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskStagingSuccessStatusPlanReceipt:
    staging_runtime_build_identity_sha256: str
    staging_runtime_verification_sha256: str
    post_staging_deployment_status_attestation_sha256: str
    status_completion_source_receipt_sha256: str
    deployment_status_authorization_sha256: str
    staging_deployment_status_plan_sha256: str
    deployment_authorization_sha256: str
    deployment_intent_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    deployment_status_intent_sha256: str
    status_transaction_lock_sha256: str
    status_recovery_lock_sha256: str | None
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    repository: str
    repository_id: str
    deployment_environment: str
    merge_commit_sha: str
    deployment_id: int
    deployment_node_id_sha256: str
    current_deployment_status_id: int
    current_deployment_status_node_id_sha256: str
    current_deployment_status_state: str
    current_deployment_status_environment: str
    exact_source_version: str
    runtime_build_identity_observation_sha256: str
    server_commit_sha: str
    server_executable_sha256: str
    worker_commit_sha: str
    worker_code_sha256: str
    worker_artifact_sha256: str
    source_verified_at_utc: str
    staging_success_status_plan_config_sha256: str
    success_deployment_status_intent_sha256: str
    success_deployment_status_state: str
    success_deployment_status_environment: str
    success_deployment_status_description: str
    success_deployment_status_description_sha256: str
    success_deployment_status_body: str
    success_deployment_status_body_sha256: str
    success_deployment_status_log_url: None
    success_deployment_status_environment_url: None
    success_deployment_status_auto_inactive: bool
    planned_at_utc: str
    staging_runtime_build_identity_authenticated: bool = True
    exact_runtime_commit_verified: bool = True
    exact_runtime_artifacts_verified: bool = True
    success_status_plan_config_host_pinned: bool = True
    success_status_intent_materialized: bool = True
    success_status_transition_planned: bool = True
    success_deployment_status_ready: bool = True
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
    production_activation_authorized: bool = False
    product_pilot_started: bool = False
    nonce_reusable: bool = False
    plan_scope: str = PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_PLAN_SCOPE
    authority: str = PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_PLAN_AUTHORITY
    schema: str = PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_PLAN_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_PLAN_SCHEMA
            or self.authority != PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_PLAN_AUTHORITY
            or self.plan_scope != PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_PLAN_SCOPE
        ):
            raise PilotExactTaskStagingSuccessStatusPlanError(
                "staging success status plan identity is unsupported"
            )
        hex64_fields = (
            "staging_runtime_build_identity_sha256",
            "staging_runtime_verification_sha256",
            "post_staging_deployment_status_attestation_sha256",
            "status_completion_source_receipt_sha256",
            "deployment_status_authorization_sha256",
            "staging_deployment_status_plan_sha256",
            "deployment_authorization_sha256",
            "deployment_intent_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
            "deployment_status_intent_sha256",
            "status_transaction_lock_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "deployment_node_id_sha256",
            "current_deployment_status_node_id_sha256",
            "runtime_build_identity_observation_sha256",
            "server_executable_sha256",
            "worker_code_sha256",
            "worker_artifact_sha256",
            "staging_success_status_plan_config_sha256",
            "success_deployment_status_intent_sha256",
            "success_deployment_status_description_sha256",
            "success_deployment_status_body_sha256",
        )
        for name in hex64_fields:
            _hex64(getattr(self, name), name=name)
        if self.status_recovery_lock_sha256 is not None:
            _hex64(self.status_recovery_lock_sha256, name="status_recovery_lock_sha256")
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        _hex40(self.server_commit_sha, name="server_commit_sha")
        _hex40(self.worker_commit_sha, name="worker_commit_sha")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.deployment_environment != "staging"
            or isinstance(self.deployment_id, bool)
            or not isinstance(self.deployment_id, int)
            or self.deployment_id < 1
            or isinstance(self.current_deployment_status_id, bool)
            or not isinstance(self.current_deployment_status_id, int)
            or self.current_deployment_status_id < 1
            or self.current_deployment_status_state != "in_progress"
            or self.current_deployment_status_environment != "staging"
            or _VERSION.fullmatch(self.exact_source_version) is None
            or self.server_commit_sha != self.merge_commit_sha
            or self.worker_commit_sha != self.merge_commit_sha
            or self.success_deployment_status_state != _STATUS_STATE
            or self.success_deployment_status_environment != _STATUS_ENVIRONMENT
            or self.success_deployment_status_auto_inactive is not False
            or self.success_deployment_status_log_url is not None
            or self.success_deployment_status_environment_url is not None
        ):
            raise PilotExactTaskStagingSuccessStatusPlanError(
                "staging success status plan projection is invalid"
            )
        expected_description = (
            "ModelRig exact RSI staging runtime verified; "
            f"deployment={self.deployment_id}; sha={self.merge_commit_sha[:12]}"
        )
        if (
            self.success_deployment_status_description != expected_description
            or self.success_deployment_status_description_sha256
            != _sha256_text(expected_description)
        ):
            raise PilotExactTaskStagingSuccessStatusPlanError(
                "success status description projection is invalid"
            )
        expected_body = _status_body(
            state=_STATUS_STATE,
            description=expected_description,
            environment=_STATUS_ENVIRONMENT,
            auto_inactive=False,
        )
        if (
            self.success_deployment_status_body != expected_body
            or self.success_deployment_status_body_sha256 != _sha256_text(expected_body)
        ):
            raise PilotExactTaskStagingSuccessStatusPlanError(
                "success status body projection is invalid"
            )
        if _utc(self.planned_at_utc, name="planned_at_utc") < _utc(
            self.source_verified_at_utc, name="source_verified_at_utc"
        ):
            raise PilotExactTaskStagingSuccessStatusPlanError(
                "staging success status plan predates ADR-DC-084"
            )
        required_true = (
            "staging_runtime_build_identity_authenticated",
            "exact_runtime_commit_verified",
            "exact_runtime_artifacts_verified",
            "success_status_plan_config_host_pinned",
            "success_status_intent_materialized",
            "success_status_transition_planned",
            "success_deployment_status_ready",
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
            "production_activation_authorized",
            "product_pilot_started",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskStagingSuccessStatusPlanError(
                "staging success status plan evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskStagingSuccessStatusPlanError(
                "staging success status plan retains forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())

    @property
    def plan_authenticated(self) -> bool:
        return _get_live_staging_success_status_plan_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskStagingSuccessStatusPlanError(
                "staging success status plan receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _plan_verified_pilot_exact_task_staging_success_status(
    *,
    staging_runtime_build_identity: PilotExactTaskStagingRuntimeBuildIdentityReceipt,
    config: PilotExactTaskStagingSuccessStatusPlanConfig,
    config_sha256: str,
    now_provider: Callable[[], str],
) -> PilotExactTaskStagingSuccessStatusPlanReceipt:
    source = _require_live_build_identity(staging_runtime_build_identity)
    if type(config) is not PilotExactTaskStagingSuccessStatusPlanConfig:
        raise PilotExactTaskStagingSuccessStatusPlanError(
            "exact staging success status config is required"
        )
    config_digest = _hex64(
        config_sha256, name="staging_success_status_plan_config_sha256"
    )
    if config.sha256 != config_digest:
        raise PilotExactTaskStagingSuccessStatusPlanError(
            "staging success status config digest mismatch"
        )
    if config.repository != source.repository or config.repository_id != source.repository_id:
        raise PilotExactTaskStagingSuccessStatusPlanError(
            "staging success status config differs from exact deployment repository"
        )
    description = _description(source)
    body = _status_body(
        state=config.deployment_status_state,
        description=description,
        environment=config.deployment_status_environment,
        auto_inactive=config.deployment_status_auto_inactive,
    )
    intent = _success_intent_sha256(
        source=source, config_sha256=config_digest, body=body
    )
    planned_at = now_provider()
    if _utc(planned_at, name="planned_at_utc") < _utc(
        source.verified_at_utc, name="source_verified_at_utc"
    ):
        raise PilotExactTaskStagingSuccessStatusPlanError(
            "system clock moved backwards before staging success status planning"
        )
    receipt = PilotExactTaskStagingSuccessStatusPlanReceipt(
        staging_runtime_build_identity_sha256=source.sha256,
        staging_runtime_verification_sha256=source.staging_runtime_verification_sha256,
        post_staging_deployment_status_attestation_sha256=(
            source.post_staging_deployment_status_attestation_sha256
        ),
        status_completion_source_receipt_sha256=source.status_completion_source_receipt_sha256,
        deployment_status_authorization_sha256=source.deployment_status_authorization_sha256,
        staging_deployment_status_plan_sha256=source.staging_deployment_status_plan_sha256,
        deployment_authorization_sha256=source.deployment_authorization_sha256,
        deployment_intent_sha256=source.deployment_intent_sha256,
        execution_nonce_sha256=source.execution_nonce_sha256,
        development_task_sha256=source.development_task_sha256,
        candidate_patch_sha256=source.candidate_patch_sha256,
        pr_intent_sha256=source.pr_intent_sha256,
        deployment_status_intent_sha256=source.deployment_status_intent_sha256,
        status_transaction_lock_sha256=source.status_transaction_lock_sha256,
        status_recovery_lock_sha256=source.status_recovery_lock_sha256,
        publisher_credential_config_sha256=source.publisher_credential_config_sha256,
        publisher_credential_path_sha256=source.publisher_credential_path_sha256,
        repository=source.repository,
        repository_id=source.repository_id,
        deployment_environment=source.deployment_environment,
        merge_commit_sha=source.merge_commit_sha,
        deployment_id=source.deployment_id,
        deployment_node_id_sha256=source.deployment_node_id_sha256,
        current_deployment_status_id=source.deployment_status_id,
        current_deployment_status_node_id_sha256=source.deployment_status_node_id_sha256,
        current_deployment_status_state=source.deployment_status_state,
        current_deployment_status_environment=source.deployment_status_environment,
        exact_source_version=source.exact_source_version,
        runtime_build_identity_observation_sha256=source.runtime_build_identity_observation_sha256,
        server_commit_sha=source.server_commit_sha,
        server_executable_sha256=source.server_executable_sha256,
        worker_commit_sha=source.worker_commit_sha,
        worker_code_sha256=source.worker_code_sha256,
        worker_artifact_sha256=source.worker_artifact_sha256,
        source_verified_at_utc=source.verified_at_utc,
        staging_success_status_plan_config_sha256=config_digest,
        success_deployment_status_intent_sha256=intent,
        success_deployment_status_state=_STATUS_STATE,
        success_deployment_status_environment=_STATUS_ENVIRONMENT,
        success_deployment_status_description=description,
        success_deployment_status_description_sha256=_sha256_text(description),
        success_deployment_status_body=body,
        success_deployment_status_body_sha256=_sha256_text(body),
        success_deployment_status_log_url=None,
        success_deployment_status_environment_url=None,
        success_deployment_status_auto_inactive=False,
        planned_at_utc=planned_at,
    )
    _mark_staging_success_status_plan_authenticated(
        receipt,
        source=source,
        config_sha256=config_digest,
        intent_sha256=intent,
    )
    if receipt.plan_authenticated is not True:
        raise PilotExactTaskStagingSuccessStatusPlanError(
            "staging success status plan lost live provenance"
        )
    return receipt


def _canonical_config() -> tuple[PilotExactTaskStagingSuccessStatusPlanConfig, str]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_CONFIG
        elif os.name == "nt":
            path = _WINDOWS_CONFIG
        else:
            raise PilotExactTaskStagingSuccessStatusPlanError(
                "staging success status planning platform is unsupported"
            )
        return _read_host_config(path)
    except PilotExactTaskStagingSuccessStatusPlanError:
        raise
    except (PhysicalHostStateError, ValueError, TypeError, OSError) as exc:
        raise PilotExactTaskStagingSuccessStatusPlanError(
            "staging success status planning runtime is not host-admin controlled"
        ) from exc


def plan_pilot_exact_task_staging_success_status(
    staging_runtime_build_identity: PilotExactTaskStagingRuntimeBuildIdentityReceipt,
) -> PilotExactTaskStagingSuccessStatusPlanReceipt:
    """Freeze an exact staging success-status intent without granting write authority."""
    source = _require_live_build_identity(staging_runtime_build_identity)
    config, config_sha = _canonical_config()
    return _plan_verified_pilot_exact_task_staging_success_status(
        staging_runtime_build_identity=source,
        config=config,
        config_sha256=config_sha,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
