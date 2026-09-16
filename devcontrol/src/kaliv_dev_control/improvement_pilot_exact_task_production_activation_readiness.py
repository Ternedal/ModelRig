"""ADR-DC-091 production-activation readiness evaluation.

Consumes one fresh live ADR-DC-090 post-staging success-status attestation and
one host-admin-pinned production-readiness policy. A positive readiness result
is evidence only and grants no production or remote mutation authority.
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
from . import improvement_pilot_exact_task_post_staging_success_status_attestation as source_boundary
from . import improvement_pilot_exact_task_pr_lifecycle_authorization as lifecycle_auth_boundary
from .improvement_pilot_exact_task_post_staging_success_status_attestation import (
    PILOT_EXACT_TASK_POST_STAGING_SUCCESS_STATUS_ATTESTATION_AUTHORITY,
    PilotExactTaskPostStagingSuccessStatusAttestationReceipt,
)

PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_READINESS_SCHEMA = "kaliv-rsi-dc-l16-exact-task-production-activation-readiness-evaluation-receipt/v1"
PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_READINESS_AUTHORITY = "host-evaluated-one-dc-l16-exact-production-activation-readiness-only"
PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_READINESS_SCOPE = "exact-post-staging-success-production-activation-policy-evaluation-only-v1"
PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_READINESS_POLICY_SCHEMA = "kaliv-rsi-dc-l16-exact-task-production-activation-readiness-policy/v1"
PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_CANDIDATE_SCHEMA = "kaliv-rsi-dc-l16-exact-task-production-activation-candidate/v1"

_MAX_FILE_BYTES = 1024 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ALLOWED_COMPLETION_SOURCES = ("recovery", "transaction")
_ALLOWED_SOURCE_ACTIONS = ("execute_exact_staging_success_status", "finalize_existing_state")
_BLOCKER_ORDER = (
    "completion-source-not-production-approved",
    "completion-action-not-production-approved",
    "staging-success-attestation-too-old",
)
_POSIX_POLICY = Path("/etc/modelrig/devcontrol/authority/rsi-pilot-exact-task-production-activation-readiness-policy-v1.json")
_WINDOWS_POLICY = Path(r"C:\Program Files\ModelRig\DevControl\authority") / "rsi-pilot-exact-task-production-activation-readiness-policy-v1.json"


class PilotExactTaskProductionActivationReadinessError(ValueError):
    """Post-staging success evidence or production-readiness policy is unsafe."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskProductionActivationReadinessError("production-readiness evidence is not canonical JSON") from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskProductionActivationReadinessError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskProductionActivationReadinessError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskProductionActivationReadinessError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskProductionActivationReadinessError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sorted_unique_tuple(value: Any, *, name: str, allowed: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not value or tuple(sorted(set(value))) != value or any(item not in allowed for item in value):
        raise PilotExactTaskProductionActivationReadinessError(f"{name} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class PilotExactTaskProductionActivationReadinessPolicy:
    repository: str
    repository_id: str
    source_environment: str
    target_environment: str
    allowed_completion_sources: tuple[str, ...] = _ALLOWED_COMPLETION_SOURCES
    allowed_source_actions: tuple[str, ...] = _ALLOWED_SOURCE_ACTIONS
    max_attestation_age_seconds: int = 15 * 60
    require_exact_staging_success: bool = True
    require_runtime_build_identity_binding: bool = True
    require_no_residual_mutation_authority: bool = True
    schema: str = PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_READINESS_POLICY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_READINESS_POLICY_SCHEMA:
            raise PilotExactTaskProductionActivationReadinessError("production-readiness policy schema is unsupported")
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None or not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None or self.source_environment != "staging" or self.target_environment != "production":
            raise PilotExactTaskProductionActivationReadinessError("production-readiness repository/environment identity is invalid")
        _sorted_unique_tuple(self.allowed_completion_sources, name="allowed_completion_sources", allowed=_ALLOWED_COMPLETION_SOURCES)
        _sorted_unique_tuple(self.allowed_source_actions, name="allowed_source_actions", allowed=_ALLOWED_SOURCE_ACTIONS)
        if isinstance(self.max_attestation_age_seconds, bool) or not isinstance(self.max_attestation_age_seconds, int) or not 1 <= self.max_attestation_age_seconds <= 3600:
            raise PilotExactTaskProductionActivationReadinessError("max_attestation_age_seconds is invalid")
        if self.require_exact_staging_success is not True or self.require_runtime_build_identity_binding is not True or self.require_no_residual_mutation_authority is not True:
            raise PilotExactTaskProductionActivationReadinessError("production-readiness mandatory evidence requirements cannot be weakened")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "repository_id": self.repository_id,
            "source_environment": self.source_environment,
            "target_environment": self.target_environment,
            "allowed_completion_sources": list(self.allowed_completion_sources),
            "allowed_source_actions": list(self.allowed_source_actions),
            "max_attestation_age_seconds": self.max_attestation_age_seconds,
            "require_exact_staging_success": self.require_exact_staging_success,
            "require_runtime_build_identity_binding": self.require_runtime_build_identity_binding,
            "require_no_residual_mutation_authority": self.require_no_residual_mutation_authority,
            "schema": self.schema,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskProductionActivationReadinessPolicy":
        expected = {"repository", "repository_id", "source_environment", "target_environment", "allowed_completion_sources", "allowed_source_actions", "max_attestation_age_seconds", "require_exact_staging_success", "require_runtime_build_identity_binding", "require_no_residual_mutation_authority", "schema"}
        if not isinstance(value, Mapping) or set(value) != expected:
            raise PilotExactTaskProductionActivationReadinessError("production-readiness policy fields mismatch")
        completion = value.get("allowed_completion_sources")
        actions = value.get("allowed_source_actions")
        if not isinstance(completion, list) or not isinstance(actions, list):
            raise PilotExactTaskProductionActivationReadinessError("production-readiness policy allowlists must be arrays")
        data = dict(value)
        data["allowed_completion_sources"] = tuple(completion)
        data["allowed_source_actions"] = tuple(actions)
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _parse_policy(payload: bytes) -> PilotExactTaskProductionActivationReadinessPolicy:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskProductionActivationReadinessError("production-readiness policy payload is invalid")
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskProductionActivationReadinessError("production-readiness policy JSON is invalid") from exc
    policy = PilotExactTaskProductionActivationReadinessPolicy.from_mapping(raw)
    if policy.canonical_json().encode("utf-8") != payload:
        raise PilotExactTaskProductionActivationReadinessError("production-readiness policy is not canonical JSON")
    return policy


def _read_host_policy(path: Path) -> tuple[PilotExactTaskProductionActivationReadinessPolicy, str]:
    try:
        first = lifecycle_auth_boundary._read_host_authority_file(Path(path))
        second = lifecycle_auth_boundary._read_host_authority_file(Path(path))
    except Exception as exc:
        raise PilotExactTaskProductionActivationReadinessError("production-readiness policy is not host-admin controlled") from exc
    if first != second:
        raise PilotExactTaskProductionActivationReadinessError("production-readiness policy changed while being read")
    policy = _parse_policy(second)
    return policy, hashlib.sha256(second).hexdigest()


def _require_live_attestation(value: Any) -> PilotExactTaskPostStagingSuccessStatusAttestationReceipt:
    if type(value) is not PilotExactTaskPostStagingSuccessStatusAttestationReceipt:
        raise PilotExactTaskProductionActivationReadinessError("exact live ADR-DC-090 post-staging success attestation is required")
    try:
        replayed = PilotExactTaskPostStagingSuccessStatusAttestationReceipt.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskProductionActivationReadinessError("ADR-DC-090 replay validation failed") from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskProductionActivationReadinessError("ADR-DC-090 identity mismatch")
    required_true = ("durable_completion_verified", "exact_parent_deployment_verified", "exact_current_status_verified", "exact_success_status_verified", "exact_success_status_identity_verified", "exact_success_status_state_verified", "exact_success_status_environment_verified", "exact_success_status_description_verified", "double_observation_matched", "post_staging_success_status_verified")
    forced_false = ("success_deployment_status_authorized", "deployment_status_mutation_authorized", "deployment_mutation_authorized", "deploy_authorized", "remote_write_authorized", "release_authorized", "tag_write_authorized", "release_mutation_authorized", "merge_authorized", "push_authorized", "pr_mutation_authorized", "review_submission_authorized", "review_thread_mutation_authorized", "production_activation_authorized", "product_pilot_started", "nonce_reusable")
    if value.authority != PILOT_EXACT_TASK_POST_STAGING_SUCCESS_STATUS_ATTESTATION_AUTHORITY or value.attestation_authenticated is not True or any(getattr(value, name) is not True for name in required_true) or any(getattr(value, name) is not False for name in forced_false) or value.deployment_environment != "staging" or value.success_deployment_status_state != "success" or value.success_deployment_status_environment != "staging":
        raise PilotExactTaskProductionActivationReadinessError("ADR-DC-091 requires one fresh inert ADR-DC-090 attestation")
    live = source_boundary._get_live_post_staging_success_status_attestation_inputs(value)
    if live is None or live.get("success_status_completion_source") != value.success_status_completion_source or live.get("success_status_completion_source_receipt_sha256") != value.success_status_completion_source_receipt_sha256 or live.get("remote_success_status_observation_sha256") != value.remote_success_status_observation_sha256:
        raise PilotExactTaskProductionActivationReadinessError("ADR-DC-090 live provenance is unavailable")
    return value


def _candidate_payload(*, source_sha256: str, source_receipt_sha256: str, runtime_sha256: str, success_intent_sha256: str, policy_sha256: str, repository: str, repository_id: str, merge_commit_sha: str, deployment_id: int, deployment_node_id_sha256: str, success_status_id: int, success_status_node_id_sha256: str, completion_source: str, source_action: str, source_environment: str, target_environment: str) -> dict[str, Any]:
    return {
        "schema": PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_CANDIDATE_SCHEMA,
        "post_staging_success_status_attestation_sha256": source_sha256,
        "success_status_completion_source_receipt_sha256": source_receipt_sha256,
        "staging_runtime_build_identity_sha256": runtime_sha256,
        "success_deployment_status_intent_sha256": success_intent_sha256,
        "production_activation_readiness_policy_sha256": policy_sha256,
        "repository": repository,
        "repository_id": repository_id,
        "merge_commit_sha": merge_commit_sha,
        "deployment_id": deployment_id,
        "deployment_node_id_sha256": deployment_node_id_sha256,
        "success_deployment_status_id": success_status_id,
        "success_deployment_status_node_id_sha256": success_status_node_id_sha256,
        "success_status_completion_source": completion_source,
        "success_status_source_action": source_action,
        "source_environment": source_environment,
        "target_environment": target_environment,
    }


def _candidate_sha256(source: PilotExactTaskPostStagingSuccessStatusAttestationReceipt, policy_sha256: str, target_environment: str) -> str:
    _hex64(policy_sha256, name="production_activation_readiness_policy_sha256")
    payload = _candidate_payload(
        source_sha256=source.sha256,
        source_receipt_sha256=source.success_status_completion_source_receipt_sha256,
        runtime_sha256=source.staging_runtime_build_identity_sha256,
        success_intent_sha256=source.success_deployment_status_intent_sha256,
        policy_sha256=policy_sha256,
        repository=source.repository,
        repository_id=source.repository_id,
        merge_commit_sha=source.merge_commit_sha,
        deployment_id=source.deployment_id,
        deployment_node_id_sha256=source.deployment_node_id_sha256,
        success_status_id=source.success_deployment_status_id,
        success_status_node_id_sha256=source.success_deployment_status_node_id_sha256,
        completion_source=source.success_status_completion_source,
        source_action=source.success_status_source_action,
        source_environment=source.deployment_environment,
        target_environment=target_environment,
    )
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _blockers(source: PilotExactTaskPostStagingSuccessStatusAttestationReceipt, policy: PilotExactTaskProductionActivationReadinessPolicy, evaluated_at_utc: str) -> tuple[str, ...]:
    evaluated = _utc(evaluated_at_utc, name="evaluated_at_utc")
    attested = _utc(source.attested_at_utc, name="staging_success_attested_at_utc")
    if evaluated < attested:
        raise PilotExactTaskProductionActivationReadinessError("production-readiness evaluation predates staging success attestation")
    result: list[str] = []
    if source.success_status_completion_source not in policy.allowed_completion_sources:
        result.append("completion-source-not-production-approved")
    if source.success_status_source_action not in policy.allowed_source_actions:
        result.append("completion-action-not-production-approved")
    if (evaluated - attested).total_seconds() > policy.max_attestation_age_seconds:
        result.append("staging-success-attestation-too-old")
    return tuple(code for code in _BLOCKER_ORDER if code in result)


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}
    def mark(receipt: Any, *, source: PilotExactTaskPostStagingSuccessStatusAttestationReceipt, policy_sha256: str, candidate_sha256: str) -> None:
        key = id(receipt)
        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)
        records[key] = (os.getpid(), receipt.sha256, weakref.ref(receipt, cleanup), weakref.ref(source), policy_sha256, candidate_sha256)
    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, source_ref, policy_sha, candidate_sha = entry
        source = source_ref()
        if pid != os.getpid() or receipt_ref() is not receipt or source is None or receipt.sha256 != digest or source.attestation_authenticated is not True or source.sha256 != receipt.post_staging_success_status_attestation_sha256 or receipt.production_activation_readiness_policy_sha256 != policy_sha or receipt.production_activation_candidate_sha256 != candidate_sha:
            return None
        return MappingProxyType({"post_staging_success_status_attestation": source, "production_activation_readiness_policy_sha256": policy_sha, "production_activation_candidate_sha256": candidate_sha})
    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(_mark_production_activation_readiness_authenticated, _get_live_production_activation_readiness_inputs) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskProductionActivationReadinessReceipt:
    post_staging_success_status_attestation_sha256: str
    success_status_completion_source_receipt_sha256: str
    success_status_authorization_sha256: str
    success_status_state_observation_sha256: str
    staging_success_status_plan_sha256: str
    staging_runtime_build_identity_sha256: str
    success_deployment_status_intent_sha256: str
    deployment_status_intent_sha256: str
    status_transaction_lock_sha256: str
    status_recovery_lock_sha256: str | None
    success_status_transaction_lock_sha256: str
    success_status_recovery_lock_sha256: str | None
    source_final_remote_success_status_state_sha256: str
    remote_success_status_observation_sha256: str
    production_activation_readiness_policy_sha256: str
    production_activation_candidate_sha256: str
    repository: str
    repository_id: str
    source_environment: str
    target_environment: str
    merge_commit_sha: str
    deployment_id: int
    deployment_node_id_sha256: str
    current_deployment_status_id: int
    current_deployment_status_node_id_sha256: str
    success_deployment_status_id: int
    success_deployment_status_node_id_sha256: str
    success_status_completion_source: str
    success_status_source_action: str
    success_status_source_remote_write_performed: bool
    allowed_completion_sources: tuple[str, ...]
    allowed_source_actions: tuple[str, ...]
    max_attestation_age_seconds: int
    blocker_codes: tuple[str, ...]
    staging_success_attested_at_utc: str
    evaluated_at_utc: str
    post_staging_success_attestation_authenticated: bool = True
    production_activation_readiness_policy_host_pinned: bool = True
    exact_staging_success_satisfied: bool = True
    runtime_build_identity_bound: bool = True
    no_residual_mutation_authority_satisfied: bool = True
    completion_source_policy_satisfied: bool = False
    source_action_policy_satisfied: bool = False
    attestation_freshness_policy_satisfied: bool = False
    production_activation_readiness_evaluated: bool = True
    production_activation_ready: bool = False
    production_activation_readiness_authorized: bool = False
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
    evaluation_scope: str = PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_READINESS_SCOPE
    authority: str = PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_READINESS_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_READINESS_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_READINESS_SCHEMA or self.authority != PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_READINESS_AUTHORITY or self.evaluation_scope != PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_READINESS_SCOPE:
            raise PilotExactTaskProductionActivationReadinessError("production-readiness evaluation identity is unsupported")
        for name in ("post_staging_success_status_attestation_sha256", "success_status_completion_source_receipt_sha256", "success_status_authorization_sha256", "success_status_state_observation_sha256", "staging_success_status_plan_sha256", "staging_runtime_build_identity_sha256", "success_deployment_status_intent_sha256", "deployment_status_intent_sha256", "status_transaction_lock_sha256", "success_status_transaction_lock_sha256", "source_final_remote_success_status_state_sha256", "remote_success_status_observation_sha256", "production_activation_readiness_policy_sha256", "production_activation_candidate_sha256", "deployment_node_id_sha256", "current_deployment_status_node_id_sha256", "success_deployment_status_node_id_sha256"):
            _hex64(getattr(self, name), name=name)
        for name in ("status_recovery_lock_sha256", "success_status_recovery_lock_sha256"):
            value = getattr(self, name)
            if value is not None:
                _hex64(value, name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None or not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None or self.source_environment != "staging" or self.target_environment != "production" or isinstance(self.deployment_id, bool) or not isinstance(self.deployment_id, int) or self.deployment_id < 1 or isinstance(self.current_deployment_status_id, bool) or not isinstance(self.current_deployment_status_id, int) or self.current_deployment_status_id < 1 or isinstance(self.success_deployment_status_id, bool) or not isinstance(self.success_deployment_status_id, int) or self.success_deployment_status_id < 1 or self.success_deployment_status_id == self.current_deployment_status_id or self.success_status_completion_source not in _ALLOWED_COMPLETION_SOURCES or self.success_status_source_action not in _ALLOWED_SOURCE_ACTIONS or not isinstance(self.success_status_source_remote_write_performed, bool):
            raise PilotExactTaskProductionActivationReadinessError("production-readiness source projection is invalid")
        if self.success_status_completion_source == "transaction":
            if self.success_status_recovery_lock_sha256 is not None or self.success_status_source_action != "execute_exact_staging_success_status" or self.success_status_source_remote_write_performed is not True:
                raise PilotExactTaskProductionActivationReadinessError("normal production-readiness source is inconsistent")
        elif self.success_status_recovery_lock_sha256 is None or self.success_status_source_action != "finalize_existing_state" or self.success_status_source_remote_write_performed is not False:
            raise PilotExactTaskProductionActivationReadinessError("recovered production-readiness source is inconsistent")
        _sorted_unique_tuple(self.allowed_completion_sources, name="allowed_completion_sources", allowed=_ALLOWED_COMPLETION_SOURCES)
        _sorted_unique_tuple(self.allowed_source_actions, name="allowed_source_actions", allowed=_ALLOWED_SOURCE_ACTIONS)
        if isinstance(self.max_attestation_age_seconds, bool) or not isinstance(self.max_attestation_age_seconds, int) or not 1 <= self.max_attestation_age_seconds <= 3600:
            raise PilotExactTaskProductionActivationReadinessError("max_attestation_age_seconds is invalid")
        source_time = _utc(self.staging_success_attested_at_utc, name="staging_success_attested_at_utc")
        evaluated = _utc(self.evaluated_at_utc, name="evaluated_at_utc")
        if evaluated < source_time:
            raise PilotExactTaskProductionActivationReadinessError("production-readiness evaluation predates source attestation")
        expected_source = self.success_status_completion_source in self.allowed_completion_sources
        expected_action = self.success_status_source_action in self.allowed_source_actions
        expected_fresh = (evaluated - source_time).total_seconds() <= self.max_attestation_age_seconds
        if self.completion_source_policy_satisfied != expected_source or self.source_action_policy_satisfied != expected_action or self.attestation_freshness_policy_satisfied != expected_fresh:
            raise PilotExactTaskProductionActivationReadinessError("production-readiness policy criteria are inconsistent")
        expected_blockers = []
        if not expected_source: expected_blockers.append(_BLOCKER_ORDER[0])
        if not expected_action: expected_blockers.append(_BLOCKER_ORDER[1])
        if not expected_fresh: expected_blockers.append(_BLOCKER_ORDER[2])
        if tuple(expected_blockers) != self.blocker_codes:
            raise PilotExactTaskProductionActivationReadinessError("production-readiness blocker set is inconsistent")
        if self.production_activation_ready != (expected_source and expected_action and expected_fresh):
            raise PilotExactTaskProductionActivationReadinessError("production_activation_ready does not equal evaluated criteria")
        candidate = hashlib.sha256(_canonical(_candidate_payload(
            source_sha256=self.post_staging_success_status_attestation_sha256,
            source_receipt_sha256=self.success_status_completion_source_receipt_sha256,
            runtime_sha256=self.staging_runtime_build_identity_sha256,
            success_intent_sha256=self.success_deployment_status_intent_sha256,
            policy_sha256=self.production_activation_readiness_policy_sha256,
            repository=self.repository,
            repository_id=self.repository_id,
            merge_commit_sha=self.merge_commit_sha,
            deployment_id=self.deployment_id,
            deployment_node_id_sha256=self.deployment_node_id_sha256,
            success_status_id=self.success_deployment_status_id,
            success_status_node_id_sha256=self.success_deployment_status_node_id_sha256,
            completion_source=self.success_status_completion_source,
            source_action=self.success_status_source_action,
            source_environment=self.source_environment,
            target_environment=self.target_environment,
        )).encode("utf-8")).hexdigest()
        if self.production_activation_candidate_sha256 != candidate:
            raise PilotExactTaskProductionActivationReadinessError("production activation candidate digest is inconsistent")
        required_true = ("post_staging_success_attestation_authenticated", "production_activation_readiness_policy_host_pinned", "exact_staging_success_satisfied", "runtime_build_identity_bound", "no_residual_mutation_authority_satisfied", "production_activation_readiness_evaluated")
        forced_false = ("production_activation_readiness_authorized", "success_deployment_status_authorized", "deployment_status_mutation_authorized", "deployment_mutation_authorized", "deploy_authorized", "remote_write_authorized", "release_authorized", "tag_write_authorized", "release_mutation_authorized", "merge_authorized", "push_authorized", "pr_mutation_authorized", "review_submission_authorized", "review_thread_mutation_authorized", "production_activation_authorized", "product_pilot_started", "nonce_reusable")
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskProductionActivationReadinessError("production-readiness evidence is incomplete")
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductionActivationReadinessError("production-readiness receipt grants forbidden mutation authority")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def evaluation_authenticated(self) -> bool:
        return _get_live_production_activation_readiness_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        values = {name: getattr(self, name) for name in self.__dataclass_fields__}
        values["allowed_completion_sources"] = list(self.allowed_completion_sources)
        values["allowed_source_actions"] = list(self.allowed_source_actions)
        values["blocker_codes"] = list(self.blocker_codes)
        return values

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductionActivationReadinessError("production-readiness receipt fields mismatch")
        data = dict(value)
        for name in ("allowed_completion_sources", "allowed_source_actions", "blocker_codes"):
            raw = data.get(name)
            if not isinstance(raw, list):
                raise PilotExactTaskProductionActivationReadinessError(f"{name} must be an array")
            data[name] = tuple(raw)
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _evaluate_verified_pilot_exact_task_production_activation_readiness(*, post_staging_success_status_attestation: PilotExactTaskPostStagingSuccessStatusAttestationReceipt, policy: PilotExactTaskProductionActivationReadinessPolicy, policy_sha256: str, now_provider: Callable[[], str]) -> PilotExactTaskProductionActivationReadinessReceipt:
    source = _require_live_attestation(post_staging_success_status_attestation)
    if type(policy) is not PilotExactTaskProductionActivationReadinessPolicy:
        raise PilotExactTaskProductionActivationReadinessError("exact production-readiness policy is required")
    if policy.repository != source.repository or policy.repository_id != source.repository_id or policy.source_environment != source.deployment_environment:
        raise PilotExactTaskProductionActivationReadinessError("production-readiness policy does not match ADR-DC-090 source")
    if policy.sha256 != _hex64(policy_sha256, name="production_activation_readiness_policy_sha256"):
        raise PilotExactTaskProductionActivationReadinessError("production-readiness policy digest mismatch")
    evaluated_at = now_provider()
    blockers = _blockers(source, policy, evaluated_at)
    attested = _utc(source.attested_at_utc, name="staging_success_attested_at_utc")
    evaluated = _utc(evaluated_at, name="evaluated_at_utc")
    candidate_sha = _candidate_sha256(source, policy_sha256, policy.target_environment)
    receipt = PilotExactTaskProductionActivationReadinessReceipt(
        post_staging_success_status_attestation_sha256=source.sha256,
        success_status_completion_source_receipt_sha256=source.success_status_completion_source_receipt_sha256,
        success_status_authorization_sha256=source.success_status_authorization_sha256,
        success_status_state_observation_sha256=source.success_status_state_observation_sha256,
        staging_success_status_plan_sha256=source.staging_success_status_plan_sha256,
        staging_runtime_build_identity_sha256=source.staging_runtime_build_identity_sha256,
        success_deployment_status_intent_sha256=source.success_deployment_status_intent_sha256,
        deployment_status_intent_sha256=source.deployment_status_intent_sha256,
        status_transaction_lock_sha256=source.status_transaction_lock_sha256,
        status_recovery_lock_sha256=source.status_recovery_lock_sha256,
        success_status_transaction_lock_sha256=source.success_status_transaction_lock_sha256,
        success_status_recovery_lock_sha256=source.success_status_recovery_lock_sha256,
        source_final_remote_success_status_state_sha256=source.source_final_remote_success_status_state_sha256,
        remote_success_status_observation_sha256=source.remote_success_status_observation_sha256,
        production_activation_readiness_policy_sha256=policy_sha256,
        production_activation_candidate_sha256=candidate_sha,
        repository=source.repository,
        repository_id=source.repository_id,
        source_environment=source.deployment_environment,
        target_environment=policy.target_environment,
        merge_commit_sha=source.merge_commit_sha,
        deployment_id=source.deployment_id,
        deployment_node_id_sha256=source.deployment_node_id_sha256,
        current_deployment_status_id=source.current_deployment_status_id,
        current_deployment_status_node_id_sha256=source.current_deployment_status_node_id_sha256,
        success_deployment_status_id=source.success_deployment_status_id,
        success_deployment_status_node_id_sha256=source.success_deployment_status_node_id_sha256,
        success_status_completion_source=source.success_status_completion_source,
        success_status_source_action=source.success_status_source_action,
        success_status_source_remote_write_performed=source.success_status_source_remote_write_performed,
        allowed_completion_sources=policy.allowed_completion_sources,
        allowed_source_actions=policy.allowed_source_actions,
        max_attestation_age_seconds=policy.max_attestation_age_seconds,
        blocker_codes=blockers,
        staging_success_attested_at_utc=source.attested_at_utc,
        evaluated_at_utc=evaluated_at,
        completion_source_policy_satisfied=source.success_status_completion_source in policy.allowed_completion_sources,
        source_action_policy_satisfied=source.success_status_source_action in policy.allowed_source_actions,
        attestation_freshness_policy_satisfied=(evaluated - attested).total_seconds() <= policy.max_attestation_age_seconds,
        production_activation_ready=not blockers,
    )
    _mark_production_activation_readiness_authenticated(receipt, source=source, policy_sha256=policy_sha256, candidate_sha256=candidate_sha)
    if receipt.evaluation_authenticated is not True:
        raise PilotExactTaskProductionActivationReadinessError("production-readiness evaluation lost live provenance")
    return receipt


def evaluate_pilot_exact_task_production_activation_readiness(post_staging_success_status_attestation: PilotExactTaskPostStagingSuccessStatusAttestationReceipt) -> PilotExactTaskProductionActivationReadinessReceipt:
    """Evaluate staging-success evidence for a later production authorization step."""
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_POLICY
        elif os.name == "nt":
            path = _WINDOWS_POLICY
        else:
            raise PilotExactTaskProductionActivationReadinessError("production-readiness platform is unsupported")
        policy, policy_sha = _read_host_policy(path)
    except PilotExactTaskProductionActivationReadinessError:
        raise
    except (PhysicalHostStateError, ValueError, TypeError, OSError) as exc:
        raise PilotExactTaskProductionActivationReadinessError("production-readiness runtime is not host-admin controlled") from exc
    return _evaluate_verified_pilot_exact_task_production_activation_readiness(
        post_staging_success_status_attestation=post_staging_success_status_attestation,
        policy=policy,
        policy_sha256=policy_sha,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
