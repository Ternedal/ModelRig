"""ADR-DC-092 deterministic exact production Deployment intent plan.

Consumes one fresh live positive ADR-DC-091 staging-completion readiness receipt
plus one host-admin-pinned plan config and freezes one exact GitHub Deployment
request for ``production``. This boundary never performs or authorizes a write.
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
)
from . import improvement_pilot_exact_task_pr_lifecycle_authorization as lifecycle_auth_boundary
from . import improvement_pilot_exact_task_staging_completion_readiness as readiness_boundary
from .improvement_pilot_exact_task_staging_completion_readiness import (
    PILOT_EXACT_TASK_STAGING_COMPLETION_READINESS_AUTHORITY,
    PilotExactTaskStagingCompletionReadinessReceipt,
)

PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_PLAN_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-production-deployment-plan-receipt/v1"
)
PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_PLAN_AUTHORITY = (
    "host-planned-one-dc-l16-exact-production-deployment-intent-only"
)
PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_PLAN_SCOPE = (
    "deterministic-exact-production-deployment-intent-only-v1"
)
PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_PLAN_CONFIG_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-production-deployment-plan-config/v1"
)

_MAX_FILE_BYTES = 1024 * 1024
_MAX_READINESS_AGE_SECONDS = 60
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_IDENTITY = re.compile(r"^modelrig-production-[0-9a-f]{40}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_POSIX_CONFIG = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-pilot-exact-task-production-deployment-plan-config-v1.json"
)
_WINDOWS_CONFIG = Path(
    r"C:\Program Files\ModelRig\DevControl\authority"
) / "rsi-pilot-exact-task-production-deployment-plan-config-v1.json"


class PilotExactTaskProductionDeploymentPlanError(ValueError):
    """Readiness/config or deterministic production intent is unsafe."""


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
        raise PilotExactTaskProductionDeploymentPlanError(
            "production deployment evidence is not canonical JSON"
        ) from exc


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hex40(value: Any, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskProductionDeploymentPlanError(f"{name} is invalid")
    return value


def _hex64(value: Any, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskProductionDeploymentPlanError(f"{name} is invalid")
    return value


def _utc(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskProductionDeploymentPlanError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskProductionDeploymentPlanError(f"{name} is invalid") from exc


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True, slots=True)
class PilotExactTaskProductionDeploymentPlanConfig:
    repository: str
    repository_id: str
    deployment_environment: str = "production"
    deployment_task: str = "deploy"
    deployment_ref_mode: str = "exact-merge-commit-v1"
    auto_merge: bool = False
    required_contexts: tuple[str, ...] = ()
    transient_environment: bool = False
    production_environment: bool = True
    max_readiness_age_seconds: int = _MAX_READINESS_AGE_SECONDS
    schema: str = PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_PLAN_CONFIG_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_PLAN_CONFIG_SCHEMA
            or not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.deployment_environment != "production"
            or self.deployment_task != "deploy"
            or self.deployment_ref_mode != "exact-merge-commit-v1"
            or self.auto_merge is not False
            or self.required_contexts != ()
            or self.transient_environment is not False
            or self.production_environment is not True
        ):
            raise PilotExactTaskProductionDeploymentPlanError(
                "production deployment-plan config is unsafe"
            )
        if (
            isinstance(self.max_readiness_age_seconds, bool)
            or not isinstance(self.max_readiness_age_seconds, int)
            or not 1 <= self.max_readiness_age_seconds <= _MAX_READINESS_AGE_SECONDS
        ):
            raise PilotExactTaskProductionDeploymentPlanError(
                "production deployment-plan freshness config is invalid"
            )

    @property
    def sha256(self) -> str:
        return _sha(self.canonical_json())

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "repository_id": self.repository_id,
            "deployment_environment": self.deployment_environment,
            "deployment_task": self.deployment_task,
            "deployment_ref_mode": self.deployment_ref_mode,
            "auto_merge": self.auto_merge,
            "required_contexts": list(self.required_contexts),
            "transient_environment": self.transient_environment,
            "production_environment": self.production_environment,
            "max_readiness_age_seconds": self.max_readiness_age_seconds,
            "schema": self.schema,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskProductionDeploymentPlanConfig":
        if not isinstance(value, Mapping):
            raise PilotExactTaskProductionDeploymentPlanError("plan config must be an object")
        expected = set(cls.__dataclass_fields__)
        if set(value) != expected or not isinstance(value.get("required_contexts"), list):
            raise PilotExactTaskProductionDeploymentPlanError(
                "production deployment-plan config fields mismatch"
            )
        data = dict(value)
        data["required_contexts"] = tuple(data["required_contexts"])
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _parse_config(payload: bytes) -> PilotExactTaskProductionDeploymentPlanConfig:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskProductionDeploymentPlanError("plan config payload is invalid")
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskProductionDeploymentPlanError("plan config JSON is invalid") from exc
    config = PilotExactTaskProductionDeploymentPlanConfig.from_mapping(raw)
    if config.canonical_json().encode("utf-8") != payload:
        raise PilotExactTaskProductionDeploymentPlanError("plan config is not canonical JSON")
    return config


def _read_host_config(path: Path) -> tuple[PilotExactTaskProductionDeploymentPlanConfig, str]:
    try:
        first = lifecycle_auth_boundary._read_host_authority_file(Path(path))
        second = lifecycle_auth_boundary._read_host_authority_file(Path(path))
    except Exception as exc:
        raise PilotExactTaskProductionDeploymentPlanError(
            "plan config is not host-admin controlled"
        ) from exc
    if first != second:
        raise PilotExactTaskProductionDeploymentPlanError("plan config changed while read")
    config = _parse_config(second)
    return config, hashlib.sha256(second).hexdigest()


def _require_live_readiness(value: Any) -> PilotExactTaskStagingCompletionReadinessReceipt:
    if type(value) is not PilotExactTaskStagingCompletionReadinessReceipt:
        raise PilotExactTaskProductionDeploymentPlanError(
            "exact live ADR-DC-091 readiness is required"
        )
    replayed = PilotExactTaskStagingCompletionReadinessReceipt.from_mapping(value.to_dict())
    required_true = (
        "post_success_attestation_authenticated",
        "staging_completion_policy_host_pinned",
        "durable_completion_satisfied",
        "runtime_build_identity_binding_satisfied",
        "exact_success_status_satisfied",
        "freshness_policy_satisfied",
        "completion_source_policy_satisfied",
        "source_action_policy_satisfied",
        "staging_completion_evaluated",
        "staging_complete",
        "next_boundary_ready",
    )
    forced_false = (
        "staging_completion_authorized",
        "production_promotion_authorized",
        "production_deployment_authorized",
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
    if (
        replayed != value
        or replayed.sha256 != value.sha256
        or value.authority != PILOT_EXACT_TASK_STAGING_COMPLETION_READINESS_AUTHORITY
        or value.evaluation_authenticated is not True
        or value.blocker_codes != ()
        or value.deployment_environment != "staging"
        or value.success_deployment_status_state != "success"
        or value.success_deployment_status_environment != "staging"
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
    ):
        raise PilotExactTaskProductionDeploymentPlanError(
            "ADR-DC-092 requires positive inert ADR-DC-091 readiness"
        )
    live = readiness_boundary._get_live_staging_completion_readiness_inputs(value)
    if live is None or live.get("staging_completion_policy_sha256") != value.staging_completion_policy_sha256:
        raise PilotExactTaskProductionDeploymentPlanError(
            "ADR-DC-091 live provenance is unavailable"
        )
    return value


def _identity(merge_commit_sha: str) -> str:
    value = f"modelrig-production-{_hex40(merge_commit_sha, 'merge_commit_sha')}"
    if _IDENTITY.fullmatch(value) is None:
        raise PilotExactTaskProductionDeploymentPlanError("production identity is invalid")
    return value


def _request(source: PilotExactTaskStagingCompletionReadinessReceipt) -> tuple[str, str, str, str]:
    identity = _identity(source.merge_commit_sha)
    payload = _canonical(
        {
            "schema": "modelrig-rsi-exact-production-deployment-payload/v1",
            "production_deployment_identity": identity,
            "staging_completion_readiness_sha256": source.sha256,
            "staging_runtime_build_identity_sha256": source.staging_runtime_build_identity_sha256,
            "source_staging_deployment_id": source.deployment_id,
            "source_success_status_id": source.success_deployment_status_id,
        }
    )
    description = (
        "ModelRig exact RSI production Deployment intent\n"
        f"- identity: {identity}\n"
        f"- repository: {source.repository}\n"
        f"- merge: {source.merge_commit_sha}\n"
        f"- staging readiness: {source.sha256}"
    )
    body = _canonical(
        {
            "ref": source.merge_commit_sha,
            "task": "deploy",
            "auto_merge": False,
            "required_contexts": [],
            "environment": "production",
            "description": description,
            "payload": json.loads(payload),
            "transient_environment": False,
            "production_environment": True,
        }
    )
    if len(payload.encode()) > 8192 or len(description.encode()) > 4096 or len(body.encode()) > 16384:
        raise PilotExactTaskProductionDeploymentPlanError("production request is too large")
    return identity, payload, description, body


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(receipt: Any, *, source: PilotExactTaskStagingCompletionReadinessReceipt, config_sha256: str) -> None:
        key = id(receipt)
        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)
        records[key] = (
            os.getpid(), receipt.sha256, weakref.ref(receipt, cleanup),
            weakref.ref(source), config_sha256,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, source_ref, config_sha = entry
        source = source_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or source is None
            or receipt.sha256 != digest
            or source.evaluation_authenticated is not True
            or source.sha256 != receipt.staging_completion_readiness_sha256
            or receipt.production_deployment_plan_config_sha256 != config_sha
        ):
            return None
        return MappingProxyType(
            {"staging_completion_readiness": source, "plan_config_sha256": config_sha}
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_plan_authenticated, _get_live_production_deployment_plan_inputs = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskProductionDeploymentPlanReceipt:
    staging_completion_readiness_sha256: str
    post_staging_success_status_attestation_sha256: str
    staging_completion_policy_sha256: str
    production_deployment_plan_config_sha256: str
    staging_runtime_build_identity_sha256: str
    repository: str
    repository_id: str
    merge_commit_sha: str
    source_staging_deployment_id: int
    source_staging_deployment_node_id_sha256: str
    source_success_status_id: int
    source_success_status_node_id_sha256: str
    source_completion_source: str
    source_completion_action: str
    source_remote_write_performed: bool
    production_deployment_identity: str
    production_deployment_ref: str
    production_deployment_environment: str
    production_deployment_task: str
    production_deployment_payload: str
    production_deployment_payload_sha256: str
    production_deployment_description: str
    production_deployment_description_sha256: str
    production_deployment_body: str
    production_deployment_body_sha256: str
    production_deployment_intent_sha256: str
    max_readiness_age_seconds: int
    readiness_age_seconds: int
    staging_completion_evaluated_at_utc: str
    planned_at_utc: str
    staging_completion_readiness_authenticated: bool = True
    production_plan_config_host_pinned: bool = True
    readiness_fresh_verified: bool = True
    exact_merge_commit_bound: bool = True
    exact_runtime_build_identity_bound: bool = True
    exact_staging_success_bound: bool = True
    production_deployment_intent_materialized: bool = True
    production_deployment_planned: bool = True
    production_deployment_ready: bool = True
    production_promotion_authorized: bool = False
    production_deployment_authorized: bool = False
    production_activation_authorized: bool = False
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
    plan_scope: str = PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_PLAN_SCOPE
    authority: str = PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_PLAN_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_PLAN_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_PLAN_SCHEMA
            or self.authority != PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_PLAN_AUTHORITY
            or self.plan_scope != PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_PLAN_SCOPE
        ):
            raise PilotExactTaskProductionDeploymentPlanError("plan identity is unsupported")
        for name in (
            "staging_completion_readiness_sha256",
            "post_staging_success_status_attestation_sha256",
            "staging_completion_policy_sha256",
            "production_deployment_plan_config_sha256",
            "staging_runtime_build_identity_sha256",
            "source_staging_deployment_node_id_sha256",
            "source_success_status_node_id_sha256",
            "production_deployment_payload_sha256",
            "production_deployment_description_sha256",
            "production_deployment_body_sha256",
            "production_deployment_intent_sha256",
        ):
            _hex64(getattr(self, name), name)
        _hex40(self.merge_commit_sha, "merge_commit_sha")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.production_deployment_identity != f"modelrig-production-{self.merge_commit_sha}"
            or self.production_deployment_ref != self.merge_commit_sha
            or self.production_deployment_environment != "production"
            or self.production_deployment_task != "deploy"
            or self.source_completion_source not in {"transaction", "recovery"}
            or self.source_completion_action not in {
                "execute_exact_staging_success_status", "finalize_existing_state"
            }
            or not isinstance(self.source_remote_write_performed, bool)
        ):
            raise PilotExactTaskProductionDeploymentPlanError("plan projection is invalid")
        for name in ("source_staging_deployment_id", "source_success_status_id"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise PilotExactTaskProductionDeploymentPlanError(f"{name} is invalid")
        if (
            isinstance(self.max_readiness_age_seconds, bool)
            or not isinstance(self.max_readiness_age_seconds, int)
            or not 1 <= self.max_readiness_age_seconds <= 60
            or isinstance(self.readiness_age_seconds, bool)
            or not isinstance(self.readiness_age_seconds, int)
            or not 0 <= self.readiness_age_seconds <= self.max_readiness_age_seconds
        ):
            raise PilotExactTaskProductionDeploymentPlanError("plan freshness is invalid")
        evaluated = _utc(self.staging_completion_evaluated_at_utc, "evaluated_at")
        planned = _utc(self.planned_at_utc, "planned_at")
        if planned < evaluated or int((planned - evaluated).total_seconds()) != self.readiness_age_seconds:
            raise PilotExactTaskProductionDeploymentPlanError("plan timestamps mismatch")
        if (
            _sha(self.production_deployment_payload) != self.production_deployment_payload_sha256
            or _sha(self.production_deployment_description) != self.production_deployment_description_sha256
            or _sha(self.production_deployment_body) != self.production_deployment_body_sha256
        ):
            raise PilotExactTaskProductionDeploymentPlanError("plan request digest mismatch")
        try:
            payload = json.loads(self.production_deployment_payload)
            body = json.loads(self.production_deployment_body)
        except json.JSONDecodeError as exc:
            raise PilotExactTaskProductionDeploymentPlanError("plan request JSON is invalid") from exc
        if _canonical(payload) != self.production_deployment_payload or _canonical(body) != self.production_deployment_body:
            raise PilotExactTaskProductionDeploymentPlanError("plan request is not canonical")
        expected_body = {
            "ref": self.merge_commit_sha,
            "task": "deploy",
            "auto_merge": False,
            "required_contexts": [],
            "environment": "production",
            "description": self.production_deployment_description,
            "payload": payload,
            "transient_environment": False,
            "production_environment": True,
        }
        if body != expected_body:
            raise PilotExactTaskProductionDeploymentPlanError("frozen production body mismatch")
        expected_intent = _sha(
            _canonical(
                {
                    "schema": "modelrig-rsi-exact-production-deployment-intent/v1",
                    "staging_completion_readiness_sha256": self.staging_completion_readiness_sha256,
                    "production_deployment_plan_config_sha256": self.production_deployment_plan_config_sha256,
                    "staging_runtime_build_identity_sha256": self.staging_runtime_build_identity_sha256,
                    "repository": self.repository,
                    "repository_id": self.repository_id,
                    "merge_commit_sha": self.merge_commit_sha,
                    "source_staging_deployment_id": self.source_staging_deployment_id,
                    "source_success_status_id": self.source_success_status_id,
                    "production_deployment_identity": self.production_deployment_identity,
                    "production_deployment_body_sha256": self.production_deployment_body_sha256,
                }
            )
        )
        if expected_intent != self.production_deployment_intent_sha256:
            raise PilotExactTaskProductionDeploymentPlanError("plan intent digest mismatch")
        required_true = (
            "staging_completion_readiness_authenticated",
            "production_plan_config_host_pinned",
            "readiness_fresh_verified",
            "exact_merge_commit_bound",
            "exact_runtime_build_identity_bound",
            "exact_staging_success_bound",
            "production_deployment_intent_materialized",
            "production_deployment_planned",
            "production_deployment_ready",
        )
        forced_false = (
            "production_promotion_authorized",
            "production_deployment_authorized",
            "production_activation_authorized",
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
            raise PilotExactTaskProductionDeploymentPlanError("plan evidence is incomplete")
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductionDeploymentPlanError("plan retains forbidden authority")

    @property
    def sha256(self) -> str:
        return _sha(self.canonical_json())

    @property
    def plan_authenticated(self) -> bool:
        return _get_live_production_deployment_plan_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskProductionDeploymentPlanReceipt":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductionDeploymentPlanError("plan receipt fields mismatch")
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _plan_verified_pilot_exact_task_production_deployment(
    *,
    staging_completion_readiness: PilotExactTaskStagingCompletionReadinessReceipt,
    config: PilotExactTaskProductionDeploymentPlanConfig,
    config_sha256: str,
    now_provider: Callable[[], str],
) -> PilotExactTaskProductionDeploymentPlanReceipt:
    source = _require_live_readiness(staging_completion_readiness)
    if type(config) is not PilotExactTaskProductionDeploymentPlanConfig:
        raise PilotExactTaskProductionDeploymentPlanError("exact host plan config is required")
    digest = _hex64(config_sha256, "production_deployment_plan_config_sha256")
    if config.sha256 != digest:
        raise PilotExactTaskProductionDeploymentPlanError("plan config digest mismatch")
    if config.repository != source.repository or config.repository_id != source.repository_id:
        raise PilotExactTaskProductionDeploymentPlanError("plan config repository mismatch")
    planned_at = now_provider()
    evaluated = _utc(source.evaluated_at_utc, "staging_completion_evaluated_at_utc")
    planned = _utc(planned_at, "planned_at_utc")
    if planned < evaluated:
        raise PilotExactTaskProductionDeploymentPlanError("system clock moved backwards")
    age = int((planned - evaluated).total_seconds())
    if age > config.max_readiness_age_seconds:
        raise PilotExactTaskProductionDeploymentPlanError("ADR-DC-091 readiness is stale")
    identity, payload, description, body = _request(source)
    body_sha = _sha(body)
    intent_sha = _sha(
        _canonical(
            {
                "schema": "modelrig-rsi-exact-production-deployment-intent/v1",
                "staging_completion_readiness_sha256": source.sha256,
                "production_deployment_plan_config_sha256": digest,
                "staging_runtime_build_identity_sha256": source.staging_runtime_build_identity_sha256,
                "repository": source.repository,
                "repository_id": source.repository_id,
                "merge_commit_sha": source.merge_commit_sha,
                "source_staging_deployment_id": source.deployment_id,
                "source_success_status_id": source.success_deployment_status_id,
                "production_deployment_identity": identity,
                "production_deployment_body_sha256": body_sha,
            }
        )
    )
    receipt = PilotExactTaskProductionDeploymentPlanReceipt(
        staging_completion_readiness_sha256=source.sha256,
        post_staging_success_status_attestation_sha256=source.post_staging_success_status_attestation_sha256,
        staging_completion_policy_sha256=source.staging_completion_policy_sha256,
        production_deployment_plan_config_sha256=digest,
        staging_runtime_build_identity_sha256=source.staging_runtime_build_identity_sha256,
        repository=source.repository,
        repository_id=source.repository_id,
        merge_commit_sha=source.merge_commit_sha,
        source_staging_deployment_id=source.deployment_id,
        source_staging_deployment_node_id_sha256=source.deployment_node_id_sha256,
        source_success_status_id=source.success_deployment_status_id,
        source_success_status_node_id_sha256=source.success_deployment_status_node_id_sha256,
        source_completion_source=source.success_status_completion_source,
        source_completion_action=source.success_status_source_action,
        source_remote_write_performed=source.success_status_source_remote_write_performed,
        production_deployment_identity=identity,
        production_deployment_ref=source.merge_commit_sha,
        production_deployment_environment="production",
        production_deployment_task="deploy",
        production_deployment_payload=payload,
        production_deployment_payload_sha256=_sha(payload),
        production_deployment_description=description,
        production_deployment_description_sha256=_sha(description),
        production_deployment_body=body,
        production_deployment_body_sha256=body_sha,
        production_deployment_intent_sha256=intent_sha,
        max_readiness_age_seconds=config.max_readiness_age_seconds,
        readiness_age_seconds=age,
        staging_completion_evaluated_at_utc=source.evaluated_at_utc,
        planned_at_utc=planned_at,
    )
    _mark_plan_authenticated(receipt, source=source, config_sha256=digest)
    if receipt.plan_authenticated is not True:
        raise PilotExactTaskProductionDeploymentPlanError("plan lost live provenance")
    return receipt


def _canonical_config() -> tuple[PilotExactTaskProductionDeploymentPlanConfig, str]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_CONFIG
        elif os.name == "nt":
            path = _WINDOWS_CONFIG
        else:
            raise PilotExactTaskProductionDeploymentPlanError("plan platform is unsupported")
        return _read_host_config(path)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskProductionDeploymentPlanError(
            "production plan requires an elevated host operator"
        ) from exc


def plan_pilot_exact_task_production_deployment(
    staging_completion_readiness: PilotExactTaskStagingCompletionReadinessReceipt,
) -> PilotExactTaskProductionDeploymentPlanReceipt:
    """Materialize one exact inert production Deployment intent."""
    try:
        config, digest = _canonical_config()
        return _plan_verified_pilot_exact_task_production_deployment(
            staging_completion_readiness=staging_completion_readiness,
            config=config,
            config_sha256=digest,
            now_provider=_now,
        )
    except PilotExactTaskProductionDeploymentPlanError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskProductionDeploymentPlanError(
            "exact production Deployment planning failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_PLAN_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_PLAN_AUTHORITY",
    "PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_PLAN_SCOPE",
    "PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_PLAN_CONFIG_SCHEMA",
    "PilotExactTaskProductionDeploymentPlanError",
    "PilotExactTaskProductionDeploymentPlanConfig",
    "PilotExactTaskProductionDeploymentPlanReceipt",
    "plan_pilot_exact_task_production_deployment",
]
