"""ADR-DC-071 deterministic exact staging deployment intent plan.

Accepts only one fresh live ADR-DC-070 staging deploy-readiness evaluation with
``deploy_ready=True`` plus one host-admin-pinned canonical deployment-plan
config. It freezes the exact immutable release tag and conservative GitHub
Deployment request semantics into one content-addressed staging intent.

No GitHub Deployment, environment mutation, deployment status, production
activation, or other remote write is performed or authorized here.
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
from . import improvement_pilot_exact_task_deploy_readiness_evaluation as readiness_boundary
from .improvement_pilot_exact_task_deploy_readiness_evaluation import (
    PILOT_EXACT_TASK_DEPLOY_READINESS_EVALUATION_AUTHORITY,
    PilotExactTaskDeployReadinessEvaluationReceipt,
)

PILOT_EXACT_TASK_STAGING_DEPLOYMENT_PLAN_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-staging-deployment-plan-receipt/v1"
)
PILOT_EXACT_TASK_STAGING_DEPLOYMENT_PLAN_AUTHORITY = (
    "host-planned-one-dc-l16-exact-staging-deployment-intent-only"
)
PILOT_EXACT_TASK_STAGING_DEPLOYMENT_PLAN_SCOPE = (
    "deterministic-exact-staging-deployment-intent-only-v1"
)
PILOT_EXACT_TASK_STAGING_DEPLOYMENT_PLAN_CONFIG_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-staging-deployment-plan-config/v1"
)

_MAX_FILE_BYTES = 1024 * 1024
_MAX_DESCRIPTION_BYTES = 4 * 1024
_MAX_PAYLOAD_BYTES = 8 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_DEPLOYMENT_IDENTITY = re.compile(r"^modelrig-staging-[0-9a-f]{40}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_DEPLOYMENT_ENVIRONMENT = "staging"
_DEPLOYMENT_TASK = "deploy"
_DEPLOYMENT_IDENTITY_PREFIX = "modelrig-staging-"
_DEPLOYMENT_REF_MODE = "exact-release-tag-v1"
_AUTO_MERGE = False
_REQUIRED_CONTEXTS: tuple[str, ...] = ()
_TRANSIENT_ENVIRONMENT = False
_PRODUCTION_ENVIRONMENT = False

_POSIX_CONFIG = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-pilot-exact-task-staging-deployment-plan-config-v1.json"
)
_WINDOWS_CONFIG = Path(
    r"C:\Program Files\ModelRig\DevControl\authority"
) / "rsi-pilot-exact-task-staging-deployment-plan-config-v1.json"


class PilotExactTaskStagingDeploymentPlanError(ValueError):
    """Deploy readiness/config or deterministic staging intent is unsafe."""


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
        raise PilotExactTaskStagingDeploymentPlanError(
            "staging deployment-plan evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskStagingDeploymentPlanError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskStagingDeploymentPlanError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskStagingDeploymentPlanError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskStagingDeploymentPlanError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _branch(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or value.strip() != value
        or _BRANCH.fullmatch(value) is None
        or value.endswith(("/", ".", ".lock"))
        or "@{" in value
        or "\\" in value
    ):
        raise PilotExactTaskStagingDeploymentPlanError(f"{name} is invalid")
    return value


def _tag(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or value.strip() != value
        or _TAG.fullmatch(value) is None
        or value.endswith(("/", ".", ".lock"))
        or ".." in value
        or "@{" in value
        or "\\" in value
    ):
        raise PilotExactTaskStagingDeploymentPlanError(f"{name} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class PilotExactTaskStagingDeploymentPlanConfig:
    repository: str
    repository_id: str
    deployment_environment: str = _DEPLOYMENT_ENVIRONMENT
    deployment_task: str = _DEPLOYMENT_TASK
    deployment_ref_mode: str = _DEPLOYMENT_REF_MODE
    deployment_identity_prefix: str = _DEPLOYMENT_IDENTITY_PREFIX
    auto_merge: bool = _AUTO_MERGE
    required_contexts: tuple[str, ...] = _REQUIRED_CONTEXTS
    transient_environment: bool = _TRANSIENT_ENVIRONMENT
    production_environment: bool = _PRODUCTION_ENVIRONMENT
    schema: str = PILOT_EXACT_TASK_STAGING_DEPLOYMENT_PLAN_CONFIG_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_PLAN_CONFIG_SCHEMA:
            raise PilotExactTaskStagingDeploymentPlanError(
                "staging deployment-plan config schema is unsupported"
            )
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskStagingDeploymentPlanError(
                "staging deployment-plan repository identity is invalid"
            )
        if (
            self.deployment_environment != _DEPLOYMENT_ENVIRONMENT
            or self.deployment_task != _DEPLOYMENT_TASK
            or self.deployment_ref_mode != _DEPLOYMENT_REF_MODE
            or self.deployment_identity_prefix != _DEPLOYMENT_IDENTITY_PREFIX
            or self.auto_merge is not False
            or self.required_contexts != ()
            or self.transient_environment is not False
            or self.production_environment is not False
        ):
            raise PilotExactTaskStagingDeploymentPlanError(
                "staging deployment-plan config weakens fixed staging intent"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "repository_id": self.repository_id,
            "deployment_environment": self.deployment_environment,
            "deployment_task": self.deployment_task,
            "deployment_ref_mode": self.deployment_ref_mode,
            "deployment_identity_prefix": self.deployment_identity_prefix,
            "auto_merge": self.auto_merge,
            "required_contexts": list(self.required_contexts),
            "transient_environment": self.transient_environment,
            "production_environment": self.production_environment,
            "schema": self.schema,
        }

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskStagingDeploymentPlanConfig":
        expected = {
            "repository",
            "repository_id",
            "deployment_environment",
            "deployment_task",
            "deployment_ref_mode",
            "deployment_identity_prefix",
            "auto_merge",
            "required_contexts",
            "transient_environment",
            "production_environment",
            "schema",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise PilotExactTaskStagingDeploymentPlanError(
                "staging deployment-plan config fields mismatch"
            )
        contexts = value.get("required_contexts")
        if not isinstance(contexts, list):
            raise PilotExactTaskStagingDeploymentPlanError(
                "staging deployment required_contexts must be an array"
            )
        data = dict(value)
        data["required_contexts"] = tuple(contexts)
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _parse_config(payload: bytes) -> PilotExactTaskStagingDeploymentPlanConfig:
    if (
        not isinstance(payload, bytes)
        or not payload
        or len(payload) > _MAX_FILE_BYTES
    ):
        raise PilotExactTaskStagingDeploymentPlanError(
            "staging deployment-plan config payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskStagingDeploymentPlanError(
            "staging deployment-plan config JSON is invalid"
        ) from exc
    config = PilotExactTaskStagingDeploymentPlanConfig.from_mapping(raw)
    if config.canonical_json().encode("utf-8") != payload:
        raise PilotExactTaskStagingDeploymentPlanError(
            "staging deployment-plan config is not canonical JSON"
        )
    return config


def _read_host_config(
    path: Path,
) -> tuple[PilotExactTaskStagingDeploymentPlanConfig, str]:
    try:
        first = lifecycle_auth_boundary._read_host_authority_file(Path(path))
        second = lifecycle_auth_boundary._read_host_authority_file(Path(path))
    except Exception as exc:
        raise PilotExactTaskStagingDeploymentPlanError(
            "staging deployment-plan config is not host-admin controlled"
        ) from exc
    if first != second:
        raise PilotExactTaskStagingDeploymentPlanError(
            "staging deployment-plan config changed while being read"
        )
    config = _parse_config(second)
    return config, hashlib.sha256(second).hexdigest()


def _require_live_readiness(
    value: Any,
) -> PilotExactTaskDeployReadinessEvaluationReceipt:
    if type(value) is not PilotExactTaskDeployReadinessEvaluationReceipt:
        raise PilotExactTaskStagingDeploymentPlanError(
            "exact live ADR-DC-070 deploy-readiness evaluation is required"
        )
    try:
        replayed = PilotExactTaskDeployReadinessEvaluationReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskStagingDeploymentPlanError(
            "ADR-DC-070 replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskStagingDeploymentPlanError(
            "ADR-DC-070 deploy-readiness identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_DEPLOY_READINESS_EVALUATION_AUTHORITY
        or value.evaluation_authenticated is not True
        or value.post_release_attestation_authenticated is not True
        or value.deploy_readiness_policy_host_pinned is not True
        or value.exact_remote_release_revalidated is not True
        or value.double_observation_matched is not True
        or value.exact_tag_target_satisfied is not True
        or value.exact_draft_release_satisfied is not True
        or value.zero_release_assets_satisfied is not True
        or value.base_branch_policy_satisfied is not True
        or value.completion_source_policy_satisfied is not True
        or value.source_action_policy_satisfied is not True
        or value.deploy_readiness_evaluated is not True
        or value.deploy_ready is not True
        or value.blocker_codes != ()
        or value.deployment_environment != "staging"
        or value.tag_target_sha != value.merge_commit_sha
        or value.deploy_readiness_authorized is not False
        or value.deploy_authorized is not False
        or value.remote_write_authorized is not False
        or value.release_authorized is not False
        or value.production_activation_authorized is not False
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskStagingDeploymentPlanError(
            "ADR-DC-071 requires positive read-only ADR-DC-070 readiness"
        )
    live = readiness_boundary._get_live_deploy_readiness_evaluation_inputs(value)
    if (
        live is None
        or live.get("deploy_readiness_policy_sha256")
        != value.deploy_readiness_policy_sha256
        or live.get("remote_observation_sha256") != value.remote_observation_sha256
    ):
        raise PilotExactTaskStagingDeploymentPlanError(
            "ADR-DC-070 live provenance is unavailable"
        )
    return value


def _deployment_identity(merge_commit_sha: str) -> str:
    value = f"{_DEPLOYMENT_IDENTITY_PREFIX}{_hex40(merge_commit_sha, name='merge_commit_sha')}"
    if _DEPLOYMENT_IDENTITY.fullmatch(value) is None:
        raise PilotExactTaskStagingDeploymentPlanError(
            "deterministic staging deployment identity is invalid"
        )
    return value


def _deployment_payload_fields(
    *,
    deployment_identity: str,
    repository: str,
    deployment_environment: str,
    deployment_ref: str,
    merge_commit_sha: str,
    deploy_readiness_evaluation_sha256: str,
    post_release_attestation_sha256: str,
    execution_nonce_sha256: str,
) -> str:
    payload = _canonical(
        {
            "schema": "modelrig-rsi-exact-staging-deployment-payload/v1",
            "deployment_identity": deployment_identity,
            "repository": repository,
            "deployment_environment": deployment_environment,
            "deployment_ref": deployment_ref,
            "merge_commit_sha": _hex40(
                merge_commit_sha, name="merge_commit_sha"
            ),
            "deploy_readiness_evaluation_sha256": _hex64(
                deploy_readiness_evaluation_sha256,
                name="deploy_readiness_evaluation_sha256",
            ),
            "post_release_attestation_sha256": _hex64(
                post_release_attestation_sha256,
                name="post_release_attestation_sha256",
            ),
            "execution_nonce_sha256": _hex64(
                execution_nonce_sha256,
                name="execution_nonce_sha256",
            ),
        }
    )
    if not payload or len(payload.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise PilotExactTaskStagingDeploymentPlanError(
            "deterministic staging deployment payload is invalid"
        )
    return payload


def _deployment_description_fields(
    *,
    deployment_identity: str,
    repository: str,
    deployment_environment: str,
    deployment_ref: str,
    merge_commit_sha: str,
    development_task_sha256: str,
    candidate_patch_sha256: str,
    deploy_readiness_evaluation_sha256: str,
) -> str:
    value = (
        "ModelRig exact RSI staging deployment\n"
        f"- identity: {deployment_identity}\n"
        f"- repository: {repository}\n"
        f"- environment: {deployment_environment}\n"
        f"- ref: {deployment_ref}\n"
        f"- merge commit: {merge_commit_sha}\n"
        f"- development task: {development_task_sha256}\n"
        f"- candidate patch: {candidate_patch_sha256}\n"
        f"- deploy readiness: {deploy_readiness_evaluation_sha256}\n"
        "Boundary: deterministic staging deployment intent only; no deployment "
        "or production activation has been authorized."
    )
    if (
        not value
        or value.strip() != value
        or len(value.encode("utf-8")) > _MAX_DESCRIPTION_BYTES
    ):
        raise PilotExactTaskStagingDeploymentPlanError(
            "deterministic staging deployment description is invalid"
        )
    return value


def _deployment_intent_sha256_fields(
    *,
    deploy_readiness_evaluation_sha256: str,
    post_release_attestation_sha256: str,
    deploy_readiness_policy_sha256: str,
    staging_deployment_plan_config_sha256: str,
    release_authorization_sha256: str,
    release_intent_sha256: str,
    release_plan_sha256: str,
    execution_nonce_sha256: str,
    development_task_sha256: str,
    candidate_patch_sha256: str,
    pr_intent_sha256: str,
    upstream_merge_transaction_lock_sha256: str,
    release_transaction_lock_sha256: str,
    repository: str,
    repository_id: str,
    deployment_environment: str,
    release_base_branch: str,
    deployment_base_branch: str,
    merge_commit_sha: str,
    release_version: str,
    tag_name: str,
    tag_target_sha: str,
    release_id: int,
    release_node_id_sha256: str,
    deployment_identity: str,
    deployment_ref: str,
    deployment_task: str,
    deployment_payload: str,
    deployment_description: str,
    auto_merge: bool,
    required_contexts: tuple[str, ...],
    transient_environment: bool,
    production_environment: bool,
) -> str:
    values = {
        "deploy_readiness_evaluation_sha256": _hex64(
            deploy_readiness_evaluation_sha256,
            name="deploy_readiness_evaluation_sha256",
        ),
        "post_release_attestation_sha256": _hex64(
            post_release_attestation_sha256,
            name="post_release_attestation_sha256",
        ),
        "deploy_readiness_policy_sha256": _hex64(
            deploy_readiness_policy_sha256,
            name="deploy_readiness_policy_sha256",
        ),
        "staging_deployment_plan_config_sha256": _hex64(
            staging_deployment_plan_config_sha256,
            name="staging_deployment_plan_config_sha256",
        ),
        "release_authorization_sha256": _hex64(
            release_authorization_sha256,
            name="release_authorization_sha256",
        ),
        "release_intent_sha256": _hex64(
            release_intent_sha256, name="release_intent_sha256"
        ),
        "release_plan_sha256": _hex64(
            release_plan_sha256, name="release_plan_sha256"
        ),
        "execution_nonce_sha256": _hex64(
            execution_nonce_sha256, name="execution_nonce_sha256"
        ),
        "development_task_sha256": _hex64(
            development_task_sha256, name="development_task_sha256"
        ),
        "candidate_patch_sha256": _hex64(
            candidate_patch_sha256, name="candidate_patch_sha256"
        ),
        "pr_intent_sha256": _hex64(pr_intent_sha256, name="pr_intent_sha256"),
        "upstream_merge_transaction_lock_sha256": _hex64(
            upstream_merge_transaction_lock_sha256,
            name="upstream_merge_transaction_lock_sha256",
        ),
        "release_transaction_lock_sha256": _hex64(
            release_transaction_lock_sha256,
            name="release_transaction_lock_sha256",
        ),
        "repository": repository,
        "repository_id": repository_id,
        "deployment_environment": deployment_environment,
        "release_base_branch": release_base_branch,
        "deployment_base_branch": deployment_base_branch,
        "merge_commit_sha": _hex40(merge_commit_sha, name="merge_commit_sha"),
        "release_version": release_version,
        "tag_name": tag_name,
        "tag_target_sha": _hex40(tag_target_sha, name="tag_target_sha"),
        "release_id": release_id,
        "release_node_id_sha256": _hex64(
            release_node_id_sha256, name="release_node_id_sha256"
        ),
        "deployment_identity": deployment_identity,
        "deployment_ref": deployment_ref,
        "deployment_task": deployment_task,
        "deployment_payload": deployment_payload,
        "deployment_description": deployment_description,
        "auto_merge": auto_merge,
        "required_contexts": list(required_contexts),
        "transient_environment": transient_environment,
        "production_environment": production_environment,
    }
    return hashlib.sha256(_canonical(values).encode("utf-8")).hexdigest()


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: Any,
        *,
        source: PilotExactTaskDeployReadinessEvaluationReceipt,
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
            or source.evaluation_authenticated is not True
            or source.sha256 != receipt.deploy_readiness_evaluation_sha256
            or receipt.staging_deployment_plan_config_sha256 != config_sha
            or receipt.deployment_intent_sha256 != intent_sha
        ):
            return None
        return MappingProxyType(
            {
                "deploy_readiness_evaluation": source,
                "staging_deployment_plan_config_sha256": config_sha,
                "deployment_intent_sha256": intent_sha,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_staging_deployment_plan_authenticated, _get_live_staging_deployment_plan_inputs = (
    _live_registry()
)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskStagingDeploymentPlanReceipt:
    deploy_readiness_evaluation_sha256: str
    post_release_attestation_sha256: str
    deploy_readiness_policy_sha256: str
    staging_deployment_plan_config_sha256: str
    deployment_intent_sha256: str
    release_authorization_sha256: str
    release_intent_sha256: str
    release_plan_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    upstream_merge_transaction_lock_sha256: str
    release_transaction_lock_sha256: str
    repository: str
    repository_id: str
    deployment_environment: str
    release_base_branch: str
    deployment_base_branch: str
    merge_commit_sha: str
    release_version: str
    tag_name: str
    tag_target_sha: str
    release_id: int
    release_node_id_sha256: str
    deployment_identity: str
    deployment_ref: str
    deployment_task: str
    deployment_payload: str
    deployment_payload_sha256: str
    deployment_description: str
    deployment_description_sha256: str
    auto_merge: bool
    required_contexts: tuple[str, ...]
    transient_environment: bool
    production_environment: bool
    readiness_evaluated_at_utc: str
    planned_at_utc: str
    deploy_readiness_authenticated: bool = True
    deploy_ready: bool = True
    staging_deployment_plan_config_host_pinned: bool = True
    deployment_intent_materialized: bool = True
    deployment_creation_planned: bool = True
    deploy_readiness_authorized: bool = False
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
    plan_scope: str = PILOT_EXACT_TASK_STAGING_DEPLOYMENT_PLAN_SCOPE
    authority: str = PILOT_EXACT_TASK_STAGING_DEPLOYMENT_PLAN_AUTHORITY
    schema: str = PILOT_EXACT_TASK_STAGING_DEPLOYMENT_PLAN_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_PLAN_SCHEMA
            or self.authority != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_PLAN_AUTHORITY
            or self.plan_scope != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_PLAN_SCOPE
        ):
            raise PilotExactTaskStagingDeploymentPlanError(
                "staging deployment-plan identity is unsupported"
            )
        for name in (
            "deploy_readiness_evaluation_sha256",
            "post_release_attestation_sha256",
            "deploy_readiness_policy_sha256",
            "staging_deployment_plan_config_sha256",
            "deployment_intent_sha256",
            "release_authorization_sha256",
            "release_intent_sha256",
            "release_plan_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
            "upstream_merge_transaction_lock_sha256",
            "release_transaction_lock_sha256",
            "release_node_id_sha256",
            "deployment_payload_sha256",
            "deployment_description_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("merge_commit_sha", "tag_target_sha"):
            _hex40(getattr(self, name), name=name)
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.deployment_environment != "staging"
        ):
            raise PilotExactTaskStagingDeploymentPlanError(
                "staging deployment repository/environment identity is invalid"
            )
        _branch(self.release_base_branch, name="release_base_branch")
        _branch(self.deployment_base_branch, name="deployment_base_branch")
        _tag(self.tag_name, name="tag_name")
        _tag(self.deployment_ref, name="deployment_ref")
        if (
            self.tag_target_sha != self.merge_commit_sha
            or self.deployment_ref != self.tag_name
            or self.release_version != f"rsi-{self.merge_commit_sha}"
            or self.tag_name != f"modelrig-rsi-{self.merge_commit_sha}"
            or self.deployment_identity != _deployment_identity(self.merge_commit_sha)
            or _DEPLOYMENT_IDENTITY.fullmatch(self.deployment_identity) is None
            or self.deployment_task != "deploy"
            or isinstance(self.release_id, bool)
            or not isinstance(self.release_id, int)
            or self.release_id < 1
            or self.auto_merge is not False
            or self.required_contexts != ()
            or self.transient_environment is not False
            or self.production_environment is not False
        ):
            raise PilotExactTaskStagingDeploymentPlanError(
                "deterministic staging deployment request is inconsistent"
            )
        if (
            not isinstance(self.deployment_payload, str)
            or not self.deployment_payload
            or len(self.deployment_payload.encode("utf-8")) > _MAX_PAYLOAD_BYTES
            or hashlib.sha256(self.deployment_payload.encode("utf-8")).hexdigest()
            != self.deployment_payload_sha256
        ):
            raise PilotExactTaskStagingDeploymentPlanError(
                "staging deployment payload identity is invalid"
            )
        expected_payload = _deployment_payload_fields(
            deployment_identity=self.deployment_identity,
            repository=self.repository,
            deployment_environment=self.deployment_environment,
            deployment_ref=self.deployment_ref,
            merge_commit_sha=self.merge_commit_sha,
            deploy_readiness_evaluation_sha256=self.deploy_readiness_evaluation_sha256,
            post_release_attestation_sha256=self.post_release_attestation_sha256,
            execution_nonce_sha256=self.execution_nonce_sha256,
        )
        if self.deployment_payload != expected_payload:
            raise PilotExactTaskStagingDeploymentPlanError(
                "staging deployment payload is not deterministic"
            )
        if (
            not isinstance(self.deployment_description, str)
            or not self.deployment_description
            or self.deployment_description.strip() != self.deployment_description
            or len(self.deployment_description.encode("utf-8"))
            > _MAX_DESCRIPTION_BYTES
            or hashlib.sha256(
                self.deployment_description.encode("utf-8")
            ).hexdigest()
            != self.deployment_description_sha256
        ):
            raise PilotExactTaskStagingDeploymentPlanError(
                "staging deployment description identity is invalid"
            )
        expected_description = _deployment_description_fields(
            deployment_identity=self.deployment_identity,
            repository=self.repository,
            deployment_environment=self.deployment_environment,
            deployment_ref=self.deployment_ref,
            merge_commit_sha=self.merge_commit_sha,
            development_task_sha256=self.development_task_sha256,
            candidate_patch_sha256=self.candidate_patch_sha256,
            deploy_readiness_evaluation_sha256=self.deploy_readiness_evaluation_sha256,
        )
        if self.deployment_description != expected_description:
            raise PilotExactTaskStagingDeploymentPlanError(
                "staging deployment description is not deterministic"
            )
        expected_intent = _deployment_intent_sha256_fields(
            deploy_readiness_evaluation_sha256=self.deploy_readiness_evaluation_sha256,
            post_release_attestation_sha256=self.post_release_attestation_sha256,
            deploy_readiness_policy_sha256=self.deploy_readiness_policy_sha256,
            staging_deployment_plan_config_sha256=self.staging_deployment_plan_config_sha256,
            release_authorization_sha256=self.release_authorization_sha256,
            release_intent_sha256=self.release_intent_sha256,
            release_plan_sha256=self.release_plan_sha256,
            execution_nonce_sha256=self.execution_nonce_sha256,
            development_task_sha256=self.development_task_sha256,
            candidate_patch_sha256=self.candidate_patch_sha256,
            pr_intent_sha256=self.pr_intent_sha256,
            upstream_merge_transaction_lock_sha256=self.upstream_merge_transaction_lock_sha256,
            release_transaction_lock_sha256=self.release_transaction_lock_sha256,
            repository=self.repository,
            repository_id=self.repository_id,
            deployment_environment=self.deployment_environment,
            release_base_branch=self.release_base_branch,
            deployment_base_branch=self.deployment_base_branch,
            merge_commit_sha=self.merge_commit_sha,
            release_version=self.release_version,
            tag_name=self.tag_name,
            tag_target_sha=self.tag_target_sha,
            release_id=self.release_id,
            release_node_id_sha256=self.release_node_id_sha256,
            deployment_identity=self.deployment_identity,
            deployment_ref=self.deployment_ref,
            deployment_task=self.deployment_task,
            deployment_payload=self.deployment_payload,
            deployment_description=self.deployment_description,
            auto_merge=self.auto_merge,
            required_contexts=self.required_contexts,
            transient_environment=self.transient_environment,
            production_environment=self.production_environment,
        )
        if self.deployment_intent_sha256 != expected_intent:
            raise PilotExactTaskStagingDeploymentPlanError(
                "staging deployment intent hash is inconsistent"
            )
        readiness_time = _utc(
            self.readiness_evaluated_at_utc,
            name="readiness_evaluated_at_utc",
        )
        planned = _utc(self.planned_at_utc, name="planned_at_utc")
        if planned < readiness_time:
            raise PilotExactTaskStagingDeploymentPlanError(
                "staging deployment plan predates deploy readiness"
            )
        required_true = (
            "deploy_readiness_authenticated",
            "deploy_ready",
            "staging_deployment_plan_config_host_pinned",
            "deployment_intent_materialized",
            "deployment_creation_planned",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskStagingDeploymentPlanError(
                "staging deployment-plan evidence is incomplete"
            )
        forced_false = (
            "deploy_readiness_authorized",
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
            raise PilotExactTaskStagingDeploymentPlanError(
                "inert staging deployment plan retains forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def plan_authenticated(self) -> bool:
        return _get_live_staging_deployment_plan_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }
        result["required_contexts"] = list(self.required_contexts)
        return result

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskStagingDeploymentPlanReceipt":
        if (
            not isinstance(value, Mapping)
            or set(value) != set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        ):
            raise PilotExactTaskStagingDeploymentPlanError(
                "staging deployment-plan fields mismatch"
            )
        contexts = value.get("required_contexts")
        if not isinstance(contexts, list):
            raise PilotExactTaskStagingDeploymentPlanError(
                "staging deployment required_contexts must be an array"
            )
        data = dict(value)
        data["required_contexts"] = tuple(contexts)
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _materialize_verified_pilot_exact_task_staging_deployment_plan(
    *,
    deploy_readiness_evaluation: PilotExactTaskDeployReadinessEvaluationReceipt,
    config: PilotExactTaskStagingDeploymentPlanConfig,
    config_sha256: str,
    now_provider: Callable[[], str],
) -> PilotExactTaskStagingDeploymentPlanReceipt:
    source = _require_live_readiness(deploy_readiness_evaluation)
    if type(config) is not PilotExactTaskStagingDeploymentPlanConfig:
        raise PilotExactTaskStagingDeploymentPlanError(
            "exact host staging deployment-plan config is required"
        )
    supplied_config_sha = _hex64(
        config_sha256,
        name="staging_deployment_plan_config_sha256",
    )
    if config.sha256 != supplied_config_sha:
        raise PilotExactTaskStagingDeploymentPlanError(
            "staging deployment-plan config digest mismatch"
        )
    if (
        config.repository != source.repository
        or config.repository_id != source.repository_id
        or config.deployment_environment != source.deployment_environment
    ):
        raise PilotExactTaskStagingDeploymentPlanError(
            "staging deployment-plan config is not bound to exact target"
        )
    identity = _deployment_identity(source.merge_commit_sha)
    deployment_ref = _tag(source.tag_name, name="deployment_ref")
    payload = _deployment_payload_fields(
        deployment_identity=identity,
        repository=source.repository,
        deployment_environment=source.deployment_environment,
        deployment_ref=deployment_ref,
        merge_commit_sha=source.merge_commit_sha,
        deploy_readiness_evaluation_sha256=source.sha256,
        post_release_attestation_sha256=source.post_release_attestation_sha256,
        execution_nonce_sha256=source.execution_nonce_sha256,
    )
    description = _deployment_description_fields(
        deployment_identity=identity,
        repository=source.repository,
        deployment_environment=source.deployment_environment,
        deployment_ref=deployment_ref,
        merge_commit_sha=source.merge_commit_sha,
        development_task_sha256=source.development_task_sha256,
        candidate_patch_sha256=source.candidate_patch_sha256,
        deploy_readiness_evaluation_sha256=source.sha256,
    )
    intent = _deployment_intent_sha256_fields(
        deploy_readiness_evaluation_sha256=source.sha256,
        post_release_attestation_sha256=source.post_release_attestation_sha256,
        deploy_readiness_policy_sha256=source.deploy_readiness_policy_sha256,
        staging_deployment_plan_config_sha256=supplied_config_sha,
        release_authorization_sha256=source.release_authorization_sha256,
        release_intent_sha256=source.release_intent_sha256,
        release_plan_sha256=source.release_plan_sha256,
        execution_nonce_sha256=source.execution_nonce_sha256,
        development_task_sha256=source.development_task_sha256,
        candidate_patch_sha256=source.candidate_patch_sha256,
        pr_intent_sha256=source.pr_intent_sha256,
        upstream_merge_transaction_lock_sha256=source.upstream_merge_transaction_lock_sha256,
        release_transaction_lock_sha256=source.release_transaction_lock_sha256,
        repository=source.repository,
        repository_id=source.repository_id,
        deployment_environment=source.deployment_environment,
        release_base_branch=source.release_base_branch,
        deployment_base_branch=source.deployment_base_branch,
        merge_commit_sha=source.merge_commit_sha,
        release_version=source.release_version,
        tag_name=source.tag_name,
        tag_target_sha=source.tag_target_sha,
        release_id=source.release_id,
        release_node_id_sha256=source.release_node_id_sha256,
        deployment_identity=identity,
        deployment_ref=deployment_ref,
        deployment_task=config.deployment_task,
        deployment_payload=payload,
        deployment_description=description,
        auto_merge=config.auto_merge,
        required_contexts=config.required_contexts,
        transient_environment=config.transient_environment,
        production_environment=config.production_environment,
    )
    planned_at = now_provider()
    if _utc(planned_at, name="planned_at_utc") < _utc(
        source.evaluated_at_utc,
        name="readiness_evaluated_at_utc",
    ):
        raise PilotExactTaskStagingDeploymentPlanError(
            "system clock moved backwards after deploy readiness"
        )
    receipt = PilotExactTaskStagingDeploymentPlanReceipt(
        deploy_readiness_evaluation_sha256=source.sha256,
        post_release_attestation_sha256=source.post_release_attestation_sha256,
        deploy_readiness_policy_sha256=source.deploy_readiness_policy_sha256,
        staging_deployment_plan_config_sha256=supplied_config_sha,
        deployment_intent_sha256=intent,
        release_authorization_sha256=source.release_authorization_sha256,
        release_intent_sha256=source.release_intent_sha256,
        release_plan_sha256=source.release_plan_sha256,
        execution_nonce_sha256=source.execution_nonce_sha256,
        development_task_sha256=source.development_task_sha256,
        candidate_patch_sha256=source.candidate_patch_sha256,
        pr_intent_sha256=source.pr_intent_sha256,
        upstream_merge_transaction_lock_sha256=source.upstream_merge_transaction_lock_sha256,
        release_transaction_lock_sha256=source.release_transaction_lock_sha256,
        repository=source.repository,
        repository_id=source.repository_id,
        deployment_environment=source.deployment_environment,
        release_base_branch=source.release_base_branch,
        deployment_base_branch=source.deployment_base_branch,
        merge_commit_sha=source.merge_commit_sha,
        release_version=source.release_version,
        tag_name=source.tag_name,
        tag_target_sha=source.tag_target_sha,
        release_id=source.release_id,
        release_node_id_sha256=source.release_node_id_sha256,
        deployment_identity=identity,
        deployment_ref=deployment_ref,
        deployment_task=config.deployment_task,
        deployment_payload=payload,
        deployment_payload_sha256=hashlib.sha256(
            payload.encode("utf-8")
        ).hexdigest(),
        deployment_description=description,
        deployment_description_sha256=hashlib.sha256(
            description.encode("utf-8")
        ).hexdigest(),
        auto_merge=config.auto_merge,
        required_contexts=config.required_contexts,
        transient_environment=config.transient_environment,
        production_environment=config.production_environment,
        readiness_evaluated_at_utc=source.evaluated_at_utc,
        planned_at_utc=planned_at,
    )
    _mark_staging_deployment_plan_authenticated(
        receipt,
        source=source,
        config_sha256=supplied_config_sha,
        intent_sha256=intent,
    )
    if receipt.plan_authenticated is not True:
        raise PilotExactTaskStagingDeploymentPlanError(
            "staging deployment plan lost live provenance"
        )
    return receipt


def _canonical_config() -> tuple[PilotExactTaskStagingDeploymentPlanConfig, str]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_CONFIG
        elif os.name == "nt":
            path = _WINDOWS_CONFIG
        else:
            raise PilotExactTaskStagingDeploymentPlanError(
                "staging deployment-plan platform is unsupported"
            )
        return _read_host_config(path)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskStagingDeploymentPlanError(
            "staging deployment-plan config requires an elevated host operator"
        ) from exc


def materialize_pilot_exact_task_staging_deployment_plan(
    deploy_readiness_evaluation: PilotExactTaskDeployReadinessEvaluationReceipt,
) -> PilotExactTaskStagingDeploymentPlanReceipt:
    """Freeze one exact staging deployment intent without remote mutation."""
    try:
        config, digest = _canonical_config()
        return _materialize_verified_pilot_exact_task_staging_deployment_plan(
            deploy_readiness_evaluation=deploy_readiness_evaluation,
            config=config,
            config_sha256=digest,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskStagingDeploymentPlanError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskStagingDeploymentPlanError(
            "exact staging deployment-plan materialization failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_STAGING_DEPLOYMENT_PLAN_SCHEMA",
    "PILOT_EXACT_TASK_STAGING_DEPLOYMENT_PLAN_AUTHORITY",
    "PILOT_EXACT_TASK_STAGING_DEPLOYMENT_PLAN_SCOPE",
    "PILOT_EXACT_TASK_STAGING_DEPLOYMENT_PLAN_CONFIG_SCHEMA",
    "PilotExactTaskStagingDeploymentPlanError",
    "PilotExactTaskStagingDeploymentPlanConfig",
    "PilotExactTaskStagingDeploymentPlanReceipt",
    "materialize_pilot_exact_task_staging_deployment_plan",
]
