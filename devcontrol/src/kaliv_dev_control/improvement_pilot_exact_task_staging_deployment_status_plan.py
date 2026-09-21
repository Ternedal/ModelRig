"""ADR-DC-077 deterministic staging Deployment Status intent plan.

Consumes only one fresh live ADR-DC-076 post-staging Deployment attestation and
one host-admin-pinned status-plan config. It freezes the exact first Deployment
Status intent for the already-created staging Deployment.

V1 is deliberately conservative: state is ``in_progress``, environment is
``staging``, ``auto_inactive`` is false, and no log/environment URL is allowed.
The plan grants no Deployment Status, Deployment, production, or other remote
write authority.
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

from . import improvement_pilot_exact_task_pr_lifecycle_authorization as lifecycle_auth_boundary
from . import improvement_pilot_exact_task_post_staging_deployment_attestation as attestation_boundary
from ._improvement_physical_state_host_control import PhysicalHostStateError, _require_elevated_operator
from .improvement_pilot_exact_task_post_staging_deployment_attestation import (
    PILOT_EXACT_TASK_POST_STAGING_DEPLOYMENT_ATTESTATION_AUTHORITY,
    PilotExactTaskPostStagingDeploymentAttestationReceipt,
)

PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_PLAN_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-staging-deployment-status-plan-receipt/v1"
)
PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_PLAN_AUTHORITY = (
    "host-planned-one-dc-l16-exact-staging-deployment-status-intent-only"
)
PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_PLAN_SCOPE = (
    "deterministic-exact-staging-deployment-status-intent-only-v1"
)
PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_PLAN_CONFIG_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-staging-deployment-status-plan-config/v1"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_MAX_FILE_BYTES = 1024 * 1024
_MAX_DESCRIPTION_BYTES = 1024
_STATUS_STATE = "in_progress"
_STATUS_ENVIRONMENT = "staging"
_STATUS_AUTO_INACTIVE = False
_POSIX_CONFIG = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-pilot-exact-task-staging-deployment-status-plan-config-v1.json"
)
_WINDOWS_CONFIG = (
    Path(r"C:\Program Files\ModelRig\DevControl\authority")
    / "rsi-pilot-exact-task-staging-deployment-status-plan-config-v1.json"
)


class PilotExactTaskStagingDeploymentStatusPlanError(ValueError):
    """Post-staging evidence or deterministic status intent is unsafe."""


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
        raise PilotExactTaskStagingDeploymentStatusPlanError(
            "staging Deployment Status evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskStagingDeploymentStatusPlanError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskStagingDeploymentStatusPlanError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskStagingDeploymentStatusPlanError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskStagingDeploymentStatusPlanError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


@dataclass(frozen=True, slots=True)
class PilotExactTaskStagingDeploymentStatusPlanConfig:
    repository: str
    repository_id: str
    deployment_status_state: str = _STATUS_STATE
    deployment_status_environment: str = _STATUS_ENVIRONMENT
    deployment_status_auto_inactive: bool = _STATUS_AUTO_INACTIVE
    allow_log_url: bool = False
    allow_environment_url: bool = False
    schema: str = PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_PLAN_CONFIG_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_PLAN_CONFIG_SCHEMA:
            raise PilotExactTaskStagingDeploymentStatusPlanError(
                "staging Deployment Status config schema is unsupported"
            )
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskStagingDeploymentStatusPlanError(
                "staging Deployment Status config repository identity is invalid"
            )
        if (
            self.deployment_status_state != _STATUS_STATE
            or self.deployment_status_environment != _STATUS_ENVIRONMENT
            or self.deployment_status_auto_inactive is not False
            or self.allow_log_url is not False
            or self.allow_environment_url is not False
        ):
            raise PilotExactTaskStagingDeploymentStatusPlanError(
                "staging Deployment Status config weakens fixed in-progress intent"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskStagingDeploymentStatusPlanError(
                "staging Deployment Status config fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _parse_config(payload: bytes) -> PilotExactTaskStagingDeploymentStatusPlanConfig:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskStagingDeploymentStatusPlanError(
            "staging Deployment Status config payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskStagingDeploymentStatusPlanError(
            "staging Deployment Status config JSON is invalid"
        ) from exc
    config = PilotExactTaskStagingDeploymentStatusPlanConfig.from_mapping(raw)
    if config.canonical_json().encode("utf-8") != payload:
        raise PilotExactTaskStagingDeploymentStatusPlanError(
            "staging Deployment Status config is not canonical JSON"
        )
    return config


def _read_host_config(
    path: Path,
) -> tuple[PilotExactTaskStagingDeploymentStatusPlanConfig, str]:
    try:
        first = lifecycle_auth_boundary._read_host_authority_file(Path(path))
        second = lifecycle_auth_boundary._read_host_authority_file(Path(path))
    except Exception as exc:
        raise PilotExactTaskStagingDeploymentStatusPlanError(
            "staging Deployment Status config is not host-admin controlled"
        ) from exc
    if first != second:
        raise PilotExactTaskStagingDeploymentStatusPlanError(
            "staging Deployment Status config changed while being read"
        )
    config = _parse_config(second)
    return config, hashlib.sha256(second).hexdigest()


def _require_live_attestation(
    value: Any,
) -> PilotExactTaskPostStagingDeploymentAttestationReceipt:
    if type(value) is not PilotExactTaskPostStagingDeploymentAttestationReceipt:
        raise PilotExactTaskStagingDeploymentStatusPlanError(
            "exact live ADR-DC-076 post-staging attestation is required"
        )
    try:
        replayed = PilotExactTaskPostStagingDeploymentAttestationReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskStagingDeploymentStatusPlanError(
            "ADR-DC-076 replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskStagingDeploymentStatusPlanError(
            "ADR-DC-076 attestation identity mismatch"
        )
    if (
        value.authority
        != PILOT_EXACT_TASK_POST_STAGING_DEPLOYMENT_ATTESTATION_AUTHORITY
        or value.attestation_authenticated is not True
        or value.durable_completion_verified is not True
        or value.exact_remote_deployment_verified is not True
        or value.exact_merge_commit_verified is not True
        or value.exact_payload_verified is not True
        or value.exact_description_verified is not True
        or value.double_observation_matched is not True
        or value.post_staging_deployment_verified is not True
        or value.deployment_environment != "staging"
        or value.deployment_task != "deploy"
        or value.deployment_status_mutation_authorized is not False
        or value.deployment_mutation_authorized is not False
        or value.deploy_authorized is not False
        or value.remote_write_authorized is not False
        or value.production_activation_authorized is not False
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskStagingDeploymentStatusPlanError(
            "ADR-DC-077 requires exact read-only ADR-DC-076 completion evidence"
        )
    live = attestation_boundary._get_live_post_staging_deployment_attestation_inputs(value)
    if (
        live is None
        or live.get("completion_source") != value.completion_source
        or live.get("completion_source_receipt_sha256")
        != value.completion_source_receipt_sha256
        or live.get("remote_observation_sha256") != value.remote_observation_sha256
    ):
        raise PilotExactTaskStagingDeploymentStatusPlanError(
            "ADR-DC-076 live provenance is unavailable"
        )
    return value


def _description(source: PilotExactTaskPostStagingDeploymentAttestationReceipt) -> str:
    value = (
        "ModelRig exact RSI staging verification in progress; "
        f"deployment={source.deployment_id}; sha={source.merge_commit_sha[:12]}"
    )
    if (
        not value
        or value.strip() != value
        or len(value.encode("utf-8")) > _MAX_DESCRIPTION_BYTES
    ):
        raise PilotExactTaskStagingDeploymentStatusPlanError(
            "deterministic Deployment Status description is invalid"
        )
    return value


def _status_body(
    *,
    state: str,
    description: str,
    environment: str,
    auto_inactive: bool,
) -> str:
    return _canonical(
        {
            "state": state,
            "description": description,
            "environment": environment,
            "auto_inactive": auto_inactive,
        }
    )


def _status_intent_sha256(
    *,
    source: PilotExactTaskPostStagingDeploymentAttestationReceipt,
    config_sha256: str,
    body: str,
) -> str:
    payload = {
        "post_staging_deployment_attestation_sha256": source.sha256,
        "completion_source_receipt_sha256": source.completion_source_receipt_sha256,
        "deployment_authorization_sha256": source.deployment_authorization_sha256,
        "staging_deployment_plan_sha256": source.staging_deployment_plan_sha256,
        "deployment_intent_sha256": source.deployment_intent_sha256,
        "execution_nonce_sha256": source.execution_nonce_sha256,
        "repository": source.repository,
        "repository_id": source.repository_id,
        "deployment_id": source.deployment_id,
        "deployment_node_id_sha256": source.deployment_node_id_sha256,
        "merge_commit_sha": source.merge_commit_sha,
        "deployment_identity": source.deployment_identity,
        "deployment_ref": source.deployment_ref,
        "deployment_task": source.deployment_task,
        "deployment_payload_sha256": source.deployment_payload_sha256,
        "deployment_description_sha256": source.deployment_description_sha256,
        "remote_observation_sha256": source.remote_observation_sha256,
        "staging_deployment_status_plan_config_sha256": _hex64(
            config_sha256,
            name="staging_deployment_status_plan_config_sha256",
        ),
        "deployment_status_body": body,
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: Any,
        *,
        source: PilotExactTaskPostStagingDeploymentAttestationReceipt,
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
            or source.attestation_authenticated is not True
            or source.sha256 != receipt.post_staging_deployment_attestation_sha256
            or receipt.staging_deployment_status_plan_config_sha256 != config_sha
            or receipt.deployment_status_intent_sha256 != intent_sha
        ):
            return None
        return MappingProxyType(
            {
                "post_staging_deployment_attestation": source,
                "staging_deployment_status_plan_config_sha256": config_sha,
                "deployment_status_intent_sha256": intent_sha,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_staging_deployment_status_plan_authenticated,
    _get_live_staging_deployment_status_plan_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskStagingDeploymentStatusPlanReceipt:
    post_staging_deployment_attestation_sha256: str
    completion_source_receipt_sha256: str
    deployment_authorization_sha256: str
    deployment_state_observation_sha256: str
    staging_deployment_plan_sha256: str
    deploy_readiness_evaluation_sha256: str
    post_release_attestation_sha256: str
    deployment_intent_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    upstream_merge_transaction_lock_sha256: str
    release_transaction_lock_sha256: str
    transaction_lock_sha256: str
    recovery_lock_sha256: str | None
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    remote_observation_sha256: str
    repository: str
    repository_id: str
    deployment_environment: str
    merge_commit_sha: str
    deployment_identity: str
    deployment_ref: str
    deployment_task: str
    deployment_payload_sha256: str
    deployment_description_sha256: str
    deployment_id: int
    deployment_node_id_sha256: str
    completion_source: str
    source_action: str
    source_remote_write_performed: bool
    source_attested_at_utc: str
    staging_deployment_status_plan_config_sha256: str
    deployment_status_intent_sha256: str
    deployment_status_state: str
    deployment_status_environment: str
    deployment_status_description: str
    deployment_status_description_sha256: str
    deployment_status_body: str
    deployment_status_body_sha256: str
    deployment_status_log_url: str | None
    deployment_status_environment_url: str | None
    deployment_status_auto_inactive: bool
    planned_at_utc: str
    post_staging_attestation_authenticated: bool = True
    post_staging_deployment_verified: bool = True
    staging_deployment_status_plan_config_host_pinned: bool = True
    deployment_status_intent_materialized: bool = True
    deployment_status_transition_planned: bool = True
    deployment_status_ready: bool = True
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
    plan_scope: str = PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_PLAN_SCOPE
    authority: str = PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_PLAN_AUTHORITY
    schema: str = PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_PLAN_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_PLAN_SCHEMA
            or self.authority != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_PLAN_AUTHORITY
            or self.plan_scope != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_PLAN_SCOPE
        ):
            raise PilotExactTaskStagingDeploymentStatusPlanError(
                "staging Deployment Status plan identity is unsupported"
            )
        for name in (
            "post_staging_deployment_attestation_sha256",
            "completion_source_receipt_sha256",
            "deployment_authorization_sha256",
            "deployment_state_observation_sha256",
            "staging_deployment_plan_sha256",
            "deploy_readiness_evaluation_sha256",
            "post_release_attestation_sha256",
            "deployment_intent_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
            "upstream_merge_transaction_lock_sha256",
            "release_transaction_lock_sha256",
            "transaction_lock_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "remote_observation_sha256",
            "deployment_payload_sha256",
            "deployment_description_sha256",
            "deployment_node_id_sha256",
            "staging_deployment_status_plan_config_sha256",
            "deployment_status_intent_sha256",
            "deployment_status_description_sha256",
            "deployment_status_body_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        if self.recovery_lock_sha256 is not None:
            _hex64(self.recovery_lock_sha256, name="recovery_lock_sha256")
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.deployment_environment != "staging"
            or self.deployment_status_environment != "staging"
            or self.deployment_task != "deploy"
            or self.deployment_identity != f"modelrig-staging-{self.merge_commit_sha}"
            or self.deployment_ref != f"modelrig-rsi-{self.merge_commit_sha}"
            or isinstance(self.deployment_id, bool)
            or not isinstance(self.deployment_id, int)
            or self.deployment_id < 1
            or self.completion_source not in {"transaction", "recovery"}
            or self.source_action
            not in {"execute_exact_staging_deployment", "finalize_existing_state"}
            or not isinstance(self.source_remote_write_performed, bool)
        ):
            raise PilotExactTaskStagingDeploymentStatusPlanError(
                "staging Deployment Status source identity is invalid"
            )
        if self.completion_source == "transaction":
            if (
                self.source_action != "execute_exact_staging_deployment"
                or self.source_remote_write_performed is not True
                or self.recovery_lock_sha256 is not None
            ):
                raise PilotExactTaskStagingDeploymentStatusPlanError(
                    "normal Deployment Status plan source is inconsistent"
                )
        elif (
            self.source_action != "finalize_existing_state"
            or self.source_remote_write_performed is not False
            or self.recovery_lock_sha256 is None
        ):
            raise PilotExactTaskStagingDeploymentStatusPlanError(
                "recovered Deployment Status plan source is inconsistent"
            )
        if (
            self.deployment_status_state != _STATUS_STATE
            or self.deployment_status_auto_inactive is not False
            or self.deployment_status_log_url is not None
            or self.deployment_status_environment_url is not None
            or self.deployment_status_description != _description_projection(
                self.deployment_id, self.merge_commit_sha
            )
            or hashlib.sha256(
                self.deployment_status_description.encode("utf-8")
            ).hexdigest()
            != self.deployment_status_description_sha256
            or self.deployment_status_body
            != _status_body(
                state=self.deployment_status_state,
                description=self.deployment_status_description,
                environment=self.deployment_status_environment,
                auto_inactive=self.deployment_status_auto_inactive,
            )
            or hashlib.sha256(self.deployment_status_body.encode("utf-8")).hexdigest()
            != self.deployment_status_body_sha256
        ):
            raise PilotExactTaskStagingDeploymentStatusPlanError(
                "deterministic Deployment Status request is inconsistent"
            )
        source_time = _utc(self.source_attested_at_utc, name="source_attested_at_utc")
        planned = _utc(self.planned_at_utc, name="planned_at_utc")
        if planned < source_time:
            raise PilotExactTaskStagingDeploymentStatusPlanError(
                "Deployment Status plan predates source attestation"
            )
        required_true = (
            "post_staging_attestation_authenticated",
            "post_staging_deployment_verified",
            "staging_deployment_status_plan_config_host_pinned",
            "deployment_status_intent_materialized",
            "deployment_status_transition_planned",
            "deployment_status_ready",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskStagingDeploymentStatusPlanError(
                "Deployment Status readiness evidence is incomplete"
            )
        forced_false = (
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
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskStagingDeploymentStatusPlanError(
                "Deployment Status plan retains forbidden mutation authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def plan_authenticated(self) -> bool:
        return _get_live_staging_deployment_status_plan_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskStagingDeploymentStatusPlanError(
                "Deployment Status plan receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _description_projection(deployment_id: int, merge_commit_sha: str) -> str:
    return (
        "ModelRig exact RSI staging verification in progress; "
        f"deployment={deployment_id}; sha={merge_commit_sha[:12]}"
    )


def _plan_verified_pilot_exact_task_staging_deployment_status(
    *,
    post_staging_attestation: PilotExactTaskPostStagingDeploymentAttestationReceipt,
    config: PilotExactTaskStagingDeploymentStatusPlanConfig,
    config_sha256: str,
    now_provider: Callable[[], str],
) -> PilotExactTaskStagingDeploymentStatusPlanReceipt:
    source = _require_live_attestation(post_staging_attestation)
    if type(config) is not PilotExactTaskStagingDeploymentStatusPlanConfig:
        raise PilotExactTaskStagingDeploymentStatusPlanError(
            "exact staging Deployment Status plan config is required"
        )
    config_digest = _hex64(
        config_sha256,
        name="staging_deployment_status_plan_config_sha256",
    )
    if config.sha256 != config_digest:
        raise PilotExactTaskStagingDeploymentStatusPlanError(
            "staging Deployment Status config digest mismatch"
        )
    if config.repository != source.repository or config.repository_id != source.repository_id:
        raise PilotExactTaskStagingDeploymentStatusPlanError(
            "staging Deployment Status config repository differs from attestation"
        )
    description = _description(source)
    body = _status_body(
        state=config.deployment_status_state,
        description=description,
        environment=config.deployment_status_environment,
        auto_inactive=config.deployment_status_auto_inactive,
    )
    intent_sha = _status_intent_sha256(
        source=source,
        config_sha256=config_digest,
        body=body,
    )
    planned_at = now_provider()
    if _utc(planned_at, name="planned_at_utc") < _utc(
        source.attested_at_utc,
        name="attested_at_utc",
    ):
        raise PilotExactTaskStagingDeploymentStatusPlanError(
            "system clock moved backwards before Deployment Status planning"
        )
    receipt = PilotExactTaskStagingDeploymentStatusPlanReceipt(
        post_staging_deployment_attestation_sha256=source.sha256,
        completion_source_receipt_sha256=source.completion_source_receipt_sha256,
        deployment_authorization_sha256=source.deployment_authorization_sha256,
        deployment_state_observation_sha256=source.deployment_state_observation_sha256,
        staging_deployment_plan_sha256=source.staging_deployment_plan_sha256,
        deploy_readiness_evaluation_sha256=source.deploy_readiness_evaluation_sha256,
        post_release_attestation_sha256=source.post_release_attestation_sha256,
        deployment_intent_sha256=source.deployment_intent_sha256,
        execution_nonce_sha256=source.execution_nonce_sha256,
        development_task_sha256=source.development_task_sha256,
        candidate_patch_sha256=source.candidate_patch_sha256,
        pr_intent_sha256=source.pr_intent_sha256,
        upstream_merge_transaction_lock_sha256=source.upstream_merge_transaction_lock_sha256,
        release_transaction_lock_sha256=source.release_transaction_lock_sha256,
        transaction_lock_sha256=source.transaction_lock_sha256,
        recovery_lock_sha256=source.recovery_lock_sha256,
        publisher_credential_config_sha256=source.publisher_credential_config_sha256,
        publisher_credential_path_sha256=source.publisher_credential_path_sha256,
        remote_observation_sha256=source.remote_observation_sha256,
        repository=source.repository,
        repository_id=source.repository_id,
        deployment_environment=source.deployment_environment,
        merge_commit_sha=source.merge_commit_sha,
        deployment_identity=source.deployment_identity,
        deployment_ref=source.deployment_ref,
        deployment_task=source.deployment_task,
        deployment_payload_sha256=source.deployment_payload_sha256,
        deployment_description_sha256=source.deployment_description_sha256,
        deployment_id=source.deployment_id,
        deployment_node_id_sha256=source.deployment_node_id_sha256,
        completion_source=source.completion_source,
        source_action=source.source_action,
        source_remote_write_performed=source.source_remote_write_performed,
        source_attested_at_utc=source.attested_at_utc,
        staging_deployment_status_plan_config_sha256=config_digest,
        deployment_status_intent_sha256=intent_sha,
        deployment_status_state=config.deployment_status_state,
        deployment_status_environment=config.deployment_status_environment,
        deployment_status_description=description,
        deployment_status_description_sha256=hashlib.sha256(
            description.encode("utf-8")
        ).hexdigest(),
        deployment_status_body=body,
        deployment_status_body_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        deployment_status_log_url=None,
        deployment_status_environment_url=None,
        deployment_status_auto_inactive=config.deployment_status_auto_inactive,
        planned_at_utc=planned_at,
    )
    _mark_staging_deployment_status_plan_authenticated(
        receipt,
        source=source,
        config_sha256=config_digest,
        intent_sha256=intent_sha,
    )
    if receipt.plan_authenticated is not True:
        raise PilotExactTaskStagingDeploymentStatusPlanError(
            "Deployment Status plan lost live provenance"
        )
    return receipt


def _canonical_config() -> tuple[PilotExactTaskStagingDeploymentStatusPlanConfig, str]:
    try:
        _require_elevated_operator()
        path = _POSIX_CONFIG if os.name == "posix" else _WINDOWS_CONFIG if os.name == "nt" else None
        if path is None:
            raise PilotExactTaskStagingDeploymentStatusPlanError(
                "Deployment Status planning platform is unsupported"
            )
        return _read_host_config(path)
    except PilotExactTaskStagingDeploymentStatusPlanError:
        raise
    except PhysicalHostStateError as exc:
        raise PilotExactTaskStagingDeploymentStatusPlanError(
            "Deployment Status plan runtime is not host-admin controlled"
        ) from exc


def plan_pilot_exact_task_staging_deployment_status(
    post_staging_attestation: PilotExactTaskPostStagingDeploymentAttestationReceipt,
) -> PilotExactTaskStagingDeploymentStatusPlanReceipt:
    """Freeze one exact in-progress staging Deployment Status intent."""
    config, digest = _canonical_config()
    return _plan_verified_pilot_exact_task_staging_deployment_status(
        post_staging_attestation=post_staging_attestation,
        config=config,
        config_sha256=digest,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
