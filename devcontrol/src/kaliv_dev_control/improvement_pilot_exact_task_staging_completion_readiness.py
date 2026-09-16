"""ADR-DC-091 inert staging-completion readiness evaluation.

Consumes one fresh live ADR-DC-090 post-staging-success attestation and one
host-admin-pinned completion policy. The boundary decides only whether the
already-attested staging completion is sufficiently fresh and policy-compatible
to proceed to a later, separate boundary.

A positive ``staging_complete`` / ``next_boundary_ready`` result is evidence
only. No production promotion, deployment, activation, Deployment Status, or
other remote-write authority is granted here.
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
from . import improvement_pilot_exact_task_post_staging_success_status_attestation as post_success_boundary
from .improvement_pilot_exact_task_post_staging_success_status_attestation import (
    PILOT_EXACT_TASK_POST_STAGING_SUCCESS_STATUS_ATTESTATION_AUTHORITY,
    PilotExactTaskPostStagingSuccessStatusAttestationReceipt,
)

PILOT_EXACT_TASK_STAGING_COMPLETION_READINESS_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-staging-completion-readiness-receipt/v1"
)
PILOT_EXACT_TASK_STAGING_COMPLETION_READINESS_AUTHORITY = (
    "host-evaluated-one-dc-l16-exact-staging-completion-readiness-only"
)
PILOT_EXACT_TASK_STAGING_COMPLETION_READINESS_SCOPE = (
    "exact-post-success-staging-completion-policy-evaluation-only-v1"
)
PILOT_EXACT_TASK_STAGING_COMPLETION_POLICY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-staging-completion-policy/v1"
)

_MAX_FILE_BYTES = 1024 * 1024
_MAX_ATTESTATION_AGE_SECONDS = 60
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ALLOWED_COMPLETION_SOURCES = ("recovery", "transaction")
_ALLOWED_SOURCE_ACTIONS = (
    "execute_exact_staging_success_status",
    "finalize_existing_state",
)
_BLOCKER_ORDER = (
    "post-success-attestation-too-old",
    "completion-source-not-staging-completion-approved",
    "completion-action-not-staging-completion-approved",
)
_POSIX_POLICY = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-pilot-exact-task-staging-completion-policy-v1.json"
)
_WINDOWS_POLICY = Path(
    r"C:\Program Files\ModelRig\DevControl\authority"
) / "rsi-pilot-exact-task-staging-completion-policy-v1.json"


class PilotExactTaskStagingCompletionReadinessError(ValueError):
    """Post-success evidence or staging-completion policy is stale or unsafe."""


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
        raise PilotExactTaskStagingCompletionReadinessError(
            "staging-completion evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskStagingCompletionReadinessError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskStagingCompletionReadinessError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskStagingCompletionReadinessError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskStagingCompletionReadinessError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _sorted_unique_tuple(
    value: Any,
    *,
    name: str,
    allowed: tuple[str, ...],
) -> tuple[str, ...]:
    if (
        not isinstance(value, tuple)
        or not value
        or tuple(sorted(set(value))) != value
        or any(item not in allowed for item in value)
    ):
        raise PilotExactTaskStagingCompletionReadinessError(f"{name} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class PilotExactTaskStagingCompletionPolicy:
    repository: str
    repository_id: str
    staging_environment: str
    allowed_completion_sources: tuple[str, ...] = _ALLOWED_COMPLETION_SOURCES
    allowed_source_actions: tuple[str, ...] = _ALLOWED_SOURCE_ACTIONS
    max_attestation_age_seconds: int = _MAX_ATTESTATION_AGE_SECONDS
    require_durable_completion: bool = True
    require_runtime_build_identity_binding: bool = True
    require_exact_success_status: bool = True
    schema: str = PILOT_EXACT_TASK_STAGING_COMPLETION_POLICY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_STAGING_COMPLETION_POLICY_SCHEMA:
            raise PilotExactTaskStagingCompletionReadinessError(
                "staging-completion policy schema is unsupported"
            )
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.staging_environment != "staging"
        ):
            raise PilotExactTaskStagingCompletionReadinessError(
                "staging-completion policy identity is invalid"
            )
        _sorted_unique_tuple(
            self.allowed_completion_sources,
            name="allowed_completion_sources",
            allowed=_ALLOWED_COMPLETION_SOURCES,
        )
        _sorted_unique_tuple(
            self.allowed_source_actions,
            name="allowed_source_actions",
            allowed=_ALLOWED_SOURCE_ACTIONS,
        )
        if (
            isinstance(self.max_attestation_age_seconds, bool)
            or not isinstance(self.max_attestation_age_seconds, int)
            or self.max_attestation_age_seconds < 1
            or self.max_attestation_age_seconds > _MAX_ATTESTATION_AGE_SECONDS
        ):
            raise PilotExactTaskStagingCompletionReadinessError(
                "staging-completion freshness policy is invalid"
            )
        if (
            self.require_durable_completion is not True
            or self.require_runtime_build_identity_binding is not True
            or self.require_exact_success_status is not True
        ):
            raise PilotExactTaskStagingCompletionReadinessError(
                "staging-completion exactness requirements cannot be weakened"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "repository_id": self.repository_id,
            "staging_environment": self.staging_environment,
            "allowed_completion_sources": list(self.allowed_completion_sources),
            "allowed_source_actions": list(self.allowed_source_actions),
            "max_attestation_age_seconds": self.max_attestation_age_seconds,
            "require_durable_completion": self.require_durable_completion,
            "require_runtime_build_identity_binding": (
                self.require_runtime_build_identity_binding
            ),
            "require_exact_success_status": self.require_exact_success_status,
            "schema": self.schema,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskStagingCompletionPolicy":
        expected = {
            "repository",
            "repository_id",
            "staging_environment",
            "allowed_completion_sources",
            "allowed_source_actions",
            "max_attestation_age_seconds",
            "require_durable_completion",
            "require_runtime_build_identity_binding",
            "require_exact_success_status",
            "schema",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise PilotExactTaskStagingCompletionReadinessError(
                "staging-completion policy fields mismatch"
            )
        sources = value.get("allowed_completion_sources")
        actions = value.get("allowed_source_actions")
        if not isinstance(sources, list) or not isinstance(actions, list):
            raise PilotExactTaskStagingCompletionReadinessError(
                "staging-completion policy allowlists must be arrays"
            )
        data = dict(value)
        data["allowed_completion_sources"] = tuple(sources)
        data["allowed_source_actions"] = tuple(actions)
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _parse_policy(payload: bytes) -> PilotExactTaskStagingCompletionPolicy:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskStagingCompletionReadinessError(
            "staging-completion policy payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskStagingCompletionReadinessError(
            "staging-completion policy JSON is invalid"
        ) from exc
    policy = PilotExactTaskStagingCompletionPolicy.from_mapping(raw)
    if policy.canonical_json().encode("utf-8") != payload:
        raise PilotExactTaskStagingCompletionReadinessError(
            "staging-completion policy is not canonical JSON"
        )
    return policy


def _read_host_policy(
    path: Path,
) -> tuple[PilotExactTaskStagingCompletionPolicy, str]:
    try:
        first = lifecycle_auth_boundary._read_host_authority_file(Path(path))
        second = lifecycle_auth_boundary._read_host_authority_file(Path(path))
    except Exception as exc:
        raise PilotExactTaskStagingCompletionReadinessError(
            "staging-completion policy is not host-admin controlled"
        ) from exc
    if first != second:
        raise PilotExactTaskStagingCompletionReadinessError(
            "staging-completion policy changed while being read"
        )
    policy = _parse_policy(second)
    return policy, hashlib.sha256(second).hexdigest()


def _require_live_post_success(
    value: Any,
) -> PilotExactTaskPostStagingSuccessStatusAttestationReceipt:
    if type(value) is not PilotExactTaskPostStagingSuccessStatusAttestationReceipt:
        raise PilotExactTaskStagingCompletionReadinessError(
            "exact live ADR-DC-090 post-success attestation is required"
        )
    try:
        replayed = (
            PilotExactTaskPostStagingSuccessStatusAttestationReceipt.from_mapping(
                value.to_dict()
            )
        )
    except Exception as exc:
        raise PilotExactTaskStagingCompletionReadinessError(
            "ADR-DC-090 replay validation failed"
        ) from exc
    required_true = (
        "durable_completion_verified",
        "exact_parent_deployment_verified",
        "exact_current_status_verified",
        "exact_success_status_verified",
        "exact_success_status_identity_verified",
        "exact_success_status_state_verified",
        "exact_success_status_environment_verified",
        "exact_success_status_description_verified",
        "double_observation_matched",
        "post_staging_success_status_verified",
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
    if (
        replayed != value
        or replayed.sha256 != value.sha256
        or value.authority
        != PILOT_EXACT_TASK_POST_STAGING_SUCCESS_STATUS_ATTESTATION_AUTHORITY
        or value.attestation_authenticated is not True
        or value.deployment_environment != "staging"
        or value.success_deployment_status_state != "success"
        or value.success_deployment_status_environment != "staging"
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
    ):
        raise PilotExactTaskStagingCompletionReadinessError(
            "ADR-DC-091 requires one fresh inert ADR-DC-090 attestation"
        )
    live = post_success_boundary._get_live_post_staging_success_status_attestation_inputs(
        value
    )
    if (
        live is None
        or live.get("success_status_completion_source")
        != value.success_status_completion_source
        or live.get("success_status_completion_source_receipt_sha256")
        != value.success_status_completion_source_receipt_sha256
        or live.get("remote_success_status_observation_sha256")
        != value.remote_success_status_observation_sha256
    ):
        raise PilotExactTaskStagingCompletionReadinessError(
            "ADR-DC-090 live provenance is unavailable"
        )
    return value


def _blockers(
    *,
    source: PilotExactTaskPostStagingSuccessStatusAttestationReceipt,
    policy: PilotExactTaskStagingCompletionPolicy,
    age_seconds: int,
) -> tuple[str, ...]:
    found: list[str] = []
    if age_seconds > policy.max_attestation_age_seconds:
        found.append("post-success-attestation-too-old")
    if source.success_status_completion_source not in policy.allowed_completion_sources:
        found.append("completion-source-not-staging-completion-approved")
    if source.success_status_source_action not in policy.allowed_source_actions:
        found.append("completion-action-not-staging-completion-approved")
    return tuple(code for code in _BLOCKER_ORDER if code in found)


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: Any,
        *,
        source: PilotExactTaskPostStagingSuccessStatusAttestationReceipt,
        policy_sha256: str,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            weakref.ref(source),
            policy_sha256,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, source_ref, policy_sha = entry
        source = source_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or source is None
            or receipt.sha256 != digest
            or source.attestation_authenticated is not True
            or source.sha256 != receipt.post_staging_success_status_attestation_sha256
            or receipt.staging_completion_policy_sha256 != policy_sha
        ):
            return None
        return MappingProxyType(
            {
                "post_staging_success_status_attestation": source,
                "staging_completion_policy_sha256": policy_sha,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_staging_completion_readiness_authenticated,
    _get_live_staging_completion_readiness_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskStagingCompletionReadinessReceipt:
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
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    staging_completion_policy_sha256: str
    repository: str
    repository_id: str
    deployment_environment: str
    merge_commit_sha: str
    deployment_id: int
    deployment_node_id_sha256: str
    current_deployment_status_id: int
    current_deployment_status_node_id_sha256: str
    success_deployment_status_id: int
    success_deployment_status_node_id_sha256: str
    success_deployment_status_state: str
    success_deployment_status_environment: str
    success_deployment_status_description_sha256: str
    success_deployment_status_body_sha256: str
    success_status_completion_source: str
    success_status_source_action: str
    success_status_source_remote_write_performed: bool
    allowed_completion_sources: tuple[str, ...]
    allowed_source_actions: tuple[str, ...]
    max_attestation_age_seconds: int
    attestation_age_seconds: int
    blocker_codes: tuple[str, ...]
    post_success_attested_at_utc: str
    evaluated_at_utc: str
    post_success_attestation_authenticated: bool = True
    staging_completion_policy_host_pinned: bool = True
    durable_completion_satisfied: bool = True
    runtime_build_identity_binding_satisfied: bool = True
    exact_success_status_satisfied: bool = True
    freshness_policy_satisfied: bool = False
    completion_source_policy_satisfied: bool = False
    source_action_policy_satisfied: bool = False
    staging_completion_evaluated: bool = True
    staging_complete: bool = False
    next_boundary_ready: bool = False
    staging_completion_authorized: bool = False
    production_promotion_authorized: bool = False
    production_deployment_authorized: bool = False
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
    evaluation_scope: str = PILOT_EXACT_TASK_STAGING_COMPLETION_READINESS_SCOPE
    authority: str = PILOT_EXACT_TASK_STAGING_COMPLETION_READINESS_AUTHORITY
    schema: str = PILOT_EXACT_TASK_STAGING_COMPLETION_READINESS_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_STAGING_COMPLETION_READINESS_SCHEMA
            or self.authority != PILOT_EXACT_TASK_STAGING_COMPLETION_READINESS_AUTHORITY
            or self.evaluation_scope != PILOT_EXACT_TASK_STAGING_COMPLETION_READINESS_SCOPE
        ):
            raise PilotExactTaskStagingCompletionReadinessError(
                "staging-completion evaluation identity is unsupported"
            )
        for name in (
            "post_staging_success_status_attestation_sha256",
            "success_status_completion_source_receipt_sha256",
            "success_status_authorization_sha256",
            "success_status_state_observation_sha256",
            "staging_success_status_plan_sha256",
            "staging_runtime_build_identity_sha256",
            "success_deployment_status_intent_sha256",
            "deployment_status_intent_sha256",
            "status_transaction_lock_sha256",
            "success_status_transaction_lock_sha256",
            "source_final_remote_success_status_state_sha256",
            "remote_success_status_observation_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "staging_completion_policy_sha256",
            "deployment_node_id_sha256",
            "current_deployment_status_node_id_sha256",
            "success_deployment_status_node_id_sha256",
            "success_deployment_status_description_sha256",
            "success_deployment_status_body_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in (
            "status_recovery_lock_sha256",
            "success_status_recovery_lock_sha256",
        ):
            value = getattr(self, name)
            if value is not None:
                _hex64(value, name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.deployment_environment != "staging"
            or self.success_deployment_status_state != "success"
            or self.success_deployment_status_environment != "staging"
            or self.success_status_completion_source not in _ALLOWED_COMPLETION_SOURCES
            or self.success_status_source_action not in _ALLOWED_SOURCE_ACTIONS
            or not isinstance(self.success_status_source_remote_write_performed, bool)
        ):
            raise PilotExactTaskStagingCompletionReadinessError(
                "staging-completion source projection is invalid"
            )
        for name in (
            "deployment_id",
            "current_deployment_status_id",
            "success_deployment_status_id",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise PilotExactTaskStagingCompletionReadinessError(
                    f"{name} is invalid"
                )
        if self.success_deployment_status_id == self.current_deployment_status_id:
            raise PilotExactTaskStagingCompletionReadinessError(
                "success status must differ from current in_progress status"
            )
        _sorted_unique_tuple(
            self.allowed_completion_sources,
            name="allowed_completion_sources",
            allowed=_ALLOWED_COMPLETION_SOURCES,
        )
        _sorted_unique_tuple(
            self.allowed_source_actions,
            name="allowed_source_actions",
            allowed=_ALLOWED_SOURCE_ACTIONS,
        )
        if (
            isinstance(self.max_attestation_age_seconds, bool)
            or not isinstance(self.max_attestation_age_seconds, int)
            or self.max_attestation_age_seconds < 1
            or self.max_attestation_age_seconds > _MAX_ATTESTATION_AGE_SECONDS
            or isinstance(self.attestation_age_seconds, bool)
            or not isinstance(self.attestation_age_seconds, int)
            or self.attestation_age_seconds < 0
        ):
            raise PilotExactTaskStagingCompletionReadinessError(
                "staging-completion age evidence is invalid"
            )
        freshness = self.attestation_age_seconds <= self.max_attestation_age_seconds
        source_ok = self.success_status_completion_source in self.allowed_completion_sources
        action_ok = self.success_status_source_action in self.allowed_source_actions
        if (
            self.freshness_policy_satisfied != freshness
            or self.completion_source_policy_satisfied != source_ok
            or self.source_action_policy_satisfied != action_ok
        ):
            raise PilotExactTaskStagingCompletionReadinessError(
                "staging-completion policy result is inconsistent"
            )
        expected_blockers: list[str] = []
        if not freshness:
            expected_blockers.append(_BLOCKER_ORDER[0])
        if not source_ok:
            expected_blockers.append(_BLOCKER_ORDER[1])
        if not action_ok:
            expected_blockers.append(_BLOCKER_ORDER[2])
        if tuple(expected_blockers) != self.blocker_codes:
            raise PilotExactTaskStagingCompletionReadinessError(
                "staging-completion blocker set is inconsistent"
            )
        criteria = (
            self.durable_completion_satisfied,
            self.runtime_build_identity_binding_satisfied,
            self.exact_success_status_satisfied,
            freshness,
            source_ok,
            action_ok,
        )
        if self.staging_complete != all(criteria) or self.staging_complete != (
            not self.blocker_codes
        ):
            raise PilotExactTaskStagingCompletionReadinessError(
                "staging_complete does not equal evaluated criteria"
            )
        if self.next_boundary_ready != self.staging_complete:
            raise PilotExactTaskStagingCompletionReadinessError(
                "next_boundary_ready must equal inert staging completion result"
            )
        source_time = _utc(
            self.post_success_attested_at_utc,
            name="post_success_attested_at_utc",
        )
        evaluated = _utc(self.evaluated_at_utc, name="evaluated_at_utc")
        if (
            evaluated < source_time
            or int((evaluated - source_time).total_seconds())
            != self.attestation_age_seconds
        ):
            raise PilotExactTaskStagingCompletionReadinessError(
                "staging-completion timestamps/age are inconsistent"
            )
        required_true = (
            "post_success_attestation_authenticated",
            "staging_completion_policy_host_pinned",
            "durable_completion_satisfied",
            "runtime_build_identity_binding_satisfied",
            "exact_success_status_satisfied",
            "staging_completion_evaluated",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskStagingCompletionReadinessError(
                "staging-completion evidence is incomplete"
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
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskStagingCompletionReadinessError(
                "staging-completion evaluation retains forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def evaluation_authenticated(self) -> bool:
        return _get_live_staging_completion_readiness_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        result = {name: getattr(self, name) for name in self.__dataclass_fields__}
        result["allowed_completion_sources"] = list(self.allowed_completion_sources)
        result["allowed_source_actions"] = list(self.allowed_source_actions)
        result["blocker_codes"] = list(self.blocker_codes)
        return result

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskStagingCompletionReadinessError(
                "staging-completion receipt fields mismatch"
            )
        sources = value.get("allowed_completion_sources")
        actions = value.get("allowed_source_actions")
        blockers = value.get("blocker_codes")
        if (
            not isinstance(sources, list)
            or not isinstance(actions, list)
            or not isinstance(blockers, list)
        ):
            raise PilotExactTaskStagingCompletionReadinessError(
                "staging-completion list fields are invalid"
            )
        data = dict(value)
        data["allowed_completion_sources"] = tuple(sources)
        data["allowed_source_actions"] = tuple(actions)
        data["blocker_codes"] = tuple(blockers)
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _evaluate_verified_pilot_exact_task_staging_completion_readiness(
    *,
    post_staging_success_status_attestation: PilotExactTaskPostStagingSuccessStatusAttestationReceipt,
    policy: PilotExactTaskStagingCompletionPolicy,
    policy_sha256: str,
    now_provider: Callable[[], str],
) -> PilotExactTaskStagingCompletionReadinessReceipt:
    source = _require_live_post_success(post_staging_success_status_attestation)
    if type(policy) is not PilotExactTaskStagingCompletionPolicy:
        raise PilotExactTaskStagingCompletionReadinessError(
            "exact host staging-completion policy is required"
        )
    supplied_policy_sha = _hex64(
        policy_sha256,
        name="staging_completion_policy_sha256",
    )
    if policy.sha256 != supplied_policy_sha:
        raise PilotExactTaskStagingCompletionReadinessError(
            "staging-completion policy digest mismatch"
        )
    if (
        policy.repository != source.repository
        or policy.repository_id != source.repository_id
        or policy.staging_environment != source.deployment_environment
    ):
        raise PilotExactTaskStagingCompletionReadinessError(
            "staging-completion policy is not bound to exact staging source"
        )
    evaluated_at = now_provider()
    source_time = _utc(
        source.attested_at_utc,
        name="post_success_attested_at_utc",
    )
    evaluated = _utc(evaluated_at, name="evaluated_at_utc")
    if evaluated < source_time:
        raise PilotExactTaskStagingCompletionReadinessError(
            "system clock moved backwards after ADR-DC-090"
        )
    age_seconds = int((evaluated - source_time).total_seconds())
    blockers = _blockers(source=source, policy=policy, age_seconds=age_seconds)
    freshness_ok = age_seconds <= policy.max_attestation_age_seconds
    source_ok = source.success_status_completion_source in policy.allowed_completion_sources
    action_ok = source.success_status_source_action in policy.allowed_source_actions
    staging_complete = not blockers
    receipt = PilotExactTaskStagingCompletionReadinessReceipt(
        post_staging_success_status_attestation_sha256=source.sha256,
        success_status_completion_source_receipt_sha256=(
            source.success_status_completion_source_receipt_sha256
        ),
        success_status_authorization_sha256=source.success_status_authorization_sha256,
        success_status_state_observation_sha256=(
            source.success_status_state_observation_sha256
        ),
        staging_success_status_plan_sha256=source.staging_success_status_plan_sha256,
        staging_runtime_build_identity_sha256=source.staging_runtime_build_identity_sha256,
        success_deployment_status_intent_sha256=(
            source.success_deployment_status_intent_sha256
        ),
        deployment_status_intent_sha256=source.deployment_status_intent_sha256,
        status_transaction_lock_sha256=source.status_transaction_lock_sha256,
        status_recovery_lock_sha256=source.status_recovery_lock_sha256,
        success_status_transaction_lock_sha256=(
            source.success_status_transaction_lock_sha256
        ),
        success_status_recovery_lock_sha256=source.success_status_recovery_lock_sha256,
        source_final_remote_success_status_state_sha256=(
            source.source_final_remote_success_status_state_sha256
        ),
        remote_success_status_observation_sha256=(
            source.remote_success_status_observation_sha256
        ),
        publisher_credential_config_sha256=source.publisher_credential_config_sha256,
        publisher_credential_path_sha256=source.publisher_credential_path_sha256,
        staging_completion_policy_sha256=supplied_policy_sha,
        repository=source.repository,
        repository_id=source.repository_id,
        deployment_environment=source.deployment_environment,
        merge_commit_sha=source.merge_commit_sha,
        deployment_id=source.deployment_id,
        deployment_node_id_sha256=source.deployment_node_id_sha256,
        current_deployment_status_id=source.current_deployment_status_id,
        current_deployment_status_node_id_sha256=(
            source.current_deployment_status_node_id_sha256
        ),
        success_deployment_status_id=source.success_deployment_status_id,
        success_deployment_status_node_id_sha256=(
            source.success_deployment_status_node_id_sha256
        ),
        success_deployment_status_state=source.success_deployment_status_state,
        success_deployment_status_environment=source.success_deployment_status_environment,
        success_deployment_status_description_sha256=(
            source.success_deployment_status_description_sha256
        ),
        success_deployment_status_body_sha256=(
            source.success_deployment_status_body_sha256
        ),
        success_status_completion_source=source.success_status_completion_source,
        success_status_source_action=source.success_status_source_action,
        success_status_source_remote_write_performed=(
            source.success_status_source_remote_write_performed
        ),
        allowed_completion_sources=policy.allowed_completion_sources,
        allowed_source_actions=policy.allowed_source_actions,
        max_attestation_age_seconds=policy.max_attestation_age_seconds,
        attestation_age_seconds=age_seconds,
        blocker_codes=blockers,
        post_success_attested_at_utc=source.attested_at_utc,
        evaluated_at_utc=evaluated_at,
        freshness_policy_satisfied=freshness_ok,
        completion_source_policy_satisfied=source_ok,
        source_action_policy_satisfied=action_ok,
        staging_complete=staging_complete,
        next_boundary_ready=staging_complete,
    )
    _mark_staging_completion_readiness_authenticated(
        receipt,
        source=source,
        policy_sha256=supplied_policy_sha,
    )
    if receipt.evaluation_authenticated is not True:
        raise PilotExactTaskStagingCompletionReadinessError(
            "staging-completion evaluation lost live provenance"
        )
    return receipt


def _canonical_policy() -> tuple[PilotExactTaskStagingCompletionPolicy, str]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_POLICY
        elif os.name == "nt":
            path = _WINDOWS_POLICY
        else:
            raise PilotExactTaskStagingCompletionReadinessError(
                "staging-completion policy platform is unsupported"
            )
        return _read_host_policy(path)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskStagingCompletionReadinessError(
            "staging-completion policy requires an elevated host operator"
        ) from exc


def evaluate_pilot_exact_task_staging_completion_readiness(
    post_staging_success_status_attestation: PilotExactTaskPostStagingSuccessStatusAttestationReceipt,
) -> PilotExactTaskStagingCompletionReadinessReceipt:
    """Evaluate one fresh exact staging success attestation under host policy."""
    try:
        policy, digest = _canonical_policy()
        return _evaluate_verified_pilot_exact_task_staging_completion_readiness(
            post_staging_success_status_attestation=(
                post_staging_success_status_attestation
            ),
            policy=policy,
            policy_sha256=digest,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskStagingCompletionReadinessError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskStagingCompletionReadinessError(
            "exact staging-completion evaluation failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_STAGING_COMPLETION_READINESS_SCHEMA",
    "PILOT_EXACT_TASK_STAGING_COMPLETION_READINESS_AUTHORITY",
    "PILOT_EXACT_TASK_STAGING_COMPLETION_READINESS_SCOPE",
    "PILOT_EXACT_TASK_STAGING_COMPLETION_POLICY_SCHEMA",
    "PilotExactTaskStagingCompletionReadinessError",
    "PilotExactTaskStagingCompletionPolicy",
    "PilotExactTaskStagingCompletionReadinessReceipt",
    "evaluate_pilot_exact_task_staging_completion_readiness",
]
