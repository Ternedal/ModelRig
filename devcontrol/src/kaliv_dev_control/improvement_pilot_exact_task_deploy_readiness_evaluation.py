"""ADR-DC-070 read-only exact staging deploy-readiness evaluation.

Accepts only one fresh live ADR-DC-069 post-release attestation, re-observes the
exact deterministic tag + draft/prerelease release twice through the existing
credential-bound GET-only observer, and evaluates those facts under one
host-admin-pinned staging deployment policy.

A positive ``deploy_ready`` result is evidence only. No deployment, release
mutation, production activation, or other remote-write authority is granted.
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
from . import improvement_pilot_exact_task_post_release_attestation as post_release_boundary
from . import improvement_pilot_exact_task_release_recovery as recovery_boundary
from . import improvement_pilot_exact_task_remote_publication_transaction as publication_tx_boundary
from .improvement_pilot_exact_task_post_release_attestation import (
    PILOT_EXACT_TASK_POST_RELEASE_ATTESTATION_AUTHORITY,
    PilotExactTaskPostReleaseAttestationReceipt,
)

PILOT_EXACT_TASK_DEPLOY_READINESS_EVALUATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-deploy-readiness-evaluation-receipt/v1"
)
PILOT_EXACT_TASK_DEPLOY_READINESS_EVALUATION_AUTHORITY = (
    "host-evaluated-one-dc-l16-exact-staging-deploy-readiness-only"
)
PILOT_EXACT_TASK_DEPLOY_READINESS_EVALUATION_SCOPE = (
    "exact-post-release-staging-deploy-policy-evaluation-only-v1"
)
PILOT_EXACT_TASK_DEPLOY_READINESS_POLICY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-deploy-readiness-policy/v1"
)

_MAX_FILE_BYTES = 1024 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ALLOWED_COMPLETION_SOURCES = ("recovery", "transaction")
_ALLOWED_SOURCE_ACTIONS = (
    "create_missing_release",
    "execute_exact_release",
    "finalize_existing_state",
)
_BLOCKER_ORDER = (
    "base-branch-not-deployment-target",
    "completion-source-not-deployment-approved",
    "completion-action-not-deployment-approved",
)
_POSIX_POLICY = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-pilot-exact-task-deploy-readiness-policy-v1.json"
)
_WINDOWS_POLICY = Path(
    r"C:\Program Files\ModelRig\DevControl\authority"
) / "rsi-pilot-exact-task-deploy-readiness-policy-v1.json"


class PilotExactTaskDeployReadinessEvaluationError(ValueError):
    """Post-release evidence or staging deployment policy is stale or unsafe."""


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
        raise PilotExactTaskDeployReadinessEvaluationError(
            "deploy-readiness evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskDeployReadinessEvaluationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskDeployReadinessEvaluationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskDeployReadinessEvaluationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskDeployReadinessEvaluationError(
            f"{name} is invalid"
        ) from exc


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
        raise PilotExactTaskDeployReadinessEvaluationError(f"{name} is invalid")
    return value


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
        raise PilotExactTaskDeployReadinessEvaluationError(f"{name} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class PilotExactTaskDeployReadinessPolicy:
    repository: str
    repository_id: str
    deployment_environment: str
    deployment_base_branch: str
    allowed_completion_sources: tuple[str, ...] = _ALLOWED_COMPLETION_SOURCES
    allowed_source_actions: tuple[str, ...] = _ALLOWED_SOURCE_ACTIONS
    require_exact_draft_release: bool = True
    require_exact_tag_target: bool = True
    require_zero_release_assets: bool = True
    schema: str = PILOT_EXACT_TASK_DEPLOY_READINESS_POLICY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_DEPLOY_READINESS_POLICY_SCHEMA:
            raise PilotExactTaskDeployReadinessEvaluationError(
                "deploy-readiness policy schema is unsupported"
            )
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskDeployReadinessEvaluationError(
                "deploy-readiness policy repository identity is invalid"
            )
        if self.deployment_environment != "staging":
            raise PilotExactTaskDeployReadinessEvaluationError(
                "deploy-readiness v1 is restricted to staging"
            )
        _branch(self.deployment_base_branch, name="deployment_base_branch")
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
            self.require_exact_draft_release is not True
            or self.require_exact_tag_target is not True
            or self.require_zero_release_assets is not True
        ):
            raise PilotExactTaskDeployReadinessEvaluationError(
                "deploy-readiness v1 exact release requirements cannot be weakened"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "repository_id": self.repository_id,
            "deployment_environment": self.deployment_environment,
            "deployment_base_branch": self.deployment_base_branch,
            "allowed_completion_sources": list(self.allowed_completion_sources),
            "allowed_source_actions": list(self.allowed_source_actions),
            "require_exact_draft_release": self.require_exact_draft_release,
            "require_exact_tag_target": self.require_exact_tag_target,
            "require_zero_release_assets": self.require_zero_release_assets,
            "schema": self.schema,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskDeployReadinessPolicy":
        expected = {
            "repository",
            "repository_id",
            "deployment_environment",
            "deployment_base_branch",
            "allowed_completion_sources",
            "allowed_source_actions",
            "require_exact_draft_release",
            "require_exact_tag_target",
            "require_zero_release_assets",
            "schema",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise PilotExactTaskDeployReadinessEvaluationError(
                "deploy-readiness policy fields mismatch"
            )
        completion = value.get("allowed_completion_sources")
        actions = value.get("allowed_source_actions")
        if not isinstance(completion, list) or not isinstance(actions, list):
            raise PilotExactTaskDeployReadinessEvaluationError(
                "deploy-readiness policy allowlists must be arrays"
            )
        data = dict(value)
        data["allowed_completion_sources"] = tuple(completion)
        data["allowed_source_actions"] = tuple(actions)
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _parse_policy(payload: bytes) -> PilotExactTaskDeployReadinessPolicy:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskDeployReadinessEvaluationError(
            "deploy-readiness policy payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskDeployReadinessEvaluationError(
            "deploy-readiness policy JSON is invalid"
        ) from exc
    policy = PilotExactTaskDeployReadinessPolicy.from_mapping(raw)
    if policy.canonical_json().encode("utf-8") != payload:
        raise PilotExactTaskDeployReadinessEvaluationError(
            "deploy-readiness policy is not canonical JSON"
        )
    return policy


def _read_host_policy(
    path: Path,
) -> tuple[PilotExactTaskDeployReadinessPolicy, str]:
    try:
        first = lifecycle_auth_boundary._read_host_authority_file(Path(path))
        second = lifecycle_auth_boundary._read_host_authority_file(Path(path))
    except Exception as exc:
        raise PilotExactTaskDeployReadinessEvaluationError(
            "deploy-readiness policy is not host-admin controlled"
        ) from exc
    if first != second:
        raise PilotExactTaskDeployReadinessEvaluationError(
            "deploy-readiness policy changed while being read"
        )
    policy = _parse_policy(second)
    return policy, hashlib.sha256(second).hexdigest()


def _require_live_post_release(
    value: Any,
) -> PilotExactTaskPostReleaseAttestationReceipt:
    if type(value) is not PilotExactTaskPostReleaseAttestationReceipt:
        raise PilotExactTaskDeployReadinessEvaluationError(
            "exact live ADR-DC-069 post-release attestation is required"
        )
    try:
        replayed = PilotExactTaskPostReleaseAttestationReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskDeployReadinessEvaluationError(
            "ADR-DC-069 replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskDeployReadinessEvaluationError(
            "ADR-DC-069 identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_POST_RELEASE_ATTESTATION_AUTHORITY
        or value.attestation_authenticated is not True
        or value.durable_completion_verified is not True
        or value.exact_remote_release_verified is not True
        or value.exact_tag_target_verified is not True
        or value.exact_draft_release_verified is not True
        or value.double_observation_matched is not True
        or value.post_release_verified is not True
        or value.tag_write_authorized is not False
        or value.release_mutation_authorized is not False
        or value.release_authorized is not False
        or value.remote_write_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskDeployReadinessEvaluationError(
            "ADR-DC-070 requires one fresh read-only ADR-DC-069 attestation"
        )
    live = post_release_boundary._get_live_post_release_attestation_inputs(value)
    if (
        live is None
        or live.get("completion_source") != value.completion_source
        or live.get("completion_source_receipt_sha256")
        != value.completion_source_receipt_sha256
        or live.get("remote_observation_sha256") != value.remote_observation_sha256
    ):
        raise PilotExactTaskDeployReadinessEvaluationError(
            "ADR-DC-069 live provenance is unavailable"
        )
    return value


def _normalize_remote_state(
    value: Any,
    source: PilotExactTaskPostReleaseAttestationReceipt,
) -> dict[str, Any]:
    if type(value) is not recovery_boundary._ReleaseRecoveryRemoteState:
        raise PilotExactTaskDeployReadinessEvaluationError(
            "deploy-readiness observer returned invalid state"
        )
    if (
        value.repository != source.repository
        or value.repository_id != source.repository_id
        or value.remote_state_class != "exact_existing"
        or value.tag_state != "exact"
        or value.tag_target_sha != source.tag_target_sha
        or value.release_state != "exact-draft"
        or value.release_id != source.release_id
        or value.release_node_id_sha256 != source.release_node_id_sha256
    ):
        raise PilotExactTaskDeployReadinessEvaluationError(
            "fresh GitHub state is not the exact attested deterministic release"
        )
    return {
        "repository": source.repository,
        "repository_id": source.repository_id,
        "release_base_branch": source.release_base_branch,
        "merge_commit_sha": source.merge_commit_sha,
        "release_version": source.release_version,
        "tag_name": source.tag_name,
        "tag_target_sha": source.tag_target_sha,
        "release_name": source.release_name,
        "release_body_sha256": source.release_body_sha256,
        "release_id": source.release_id,
        "release_node_id_sha256": source.release_node_id_sha256,
        "release_draft": True,
        "release_prerelease": True,
        "release_asset_count": 0,
        "remote_state_class": "exact_existing",
    }


def _blockers(
    *,
    source: PilotExactTaskPostReleaseAttestationReceipt,
    policy: PilotExactTaskDeployReadinessPolicy,
) -> tuple[str, ...]:
    result: list[str] = []
    if source.release_base_branch != policy.deployment_base_branch:
        result.append("base-branch-not-deployment-target")
    if source.completion_source not in policy.allowed_completion_sources:
        result.append("completion-source-not-deployment-approved")
    if source.source_action not in policy.allowed_source_actions:
        result.append("completion-action-not-deployment-approved")
    return tuple(code for code in _BLOCKER_ORDER if code in result)


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: Any,
        *,
        source: PilotExactTaskPostReleaseAttestationReceipt,
        policy_sha256: str,
        observation_sha256: str,
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
            observation_sha256,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, source_ref, policy_sha, observation_sha = entry
        source = source_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or source is None
            or receipt.sha256 != digest
            or source.attestation_authenticated is not True
            or source.sha256 != receipt.post_release_attestation_sha256
            or receipt.deploy_readiness_policy_sha256 != policy_sha
            or receipt.remote_observation_sha256 != observation_sha
        ):
            return None
        return MappingProxyType(
            {
                "post_release_attestation": source,
                "deploy_readiness_policy_sha256": policy_sha,
                "remote_observation_sha256": observation_sha,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_deploy_readiness_evaluation_authenticated,
    _get_live_deploy_readiness_evaluation_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskDeployReadinessEvaluationReceipt:
    post_release_attestation_sha256: str
    completion_source_receipt_sha256: str
    release_authorization_sha256: str
    release_intent_sha256: str
    release_plan_sha256: str
    release_readiness_evaluation_sha256: str
    release_plan_config_sha256: str
    release_authorization_config_sha256: str
    deploy_readiness_policy_sha256: str
    remote_observation_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    upstream_merge_transaction_lock_sha256: str
    release_transaction_lock_sha256: str
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    repository: str
    repository_id: str
    deployment_environment: str
    release_base_branch: str
    deployment_base_branch: str
    merge_commit_sha: str
    release_version: str
    tag_name: str
    tag_target_sha: str
    release_name: str
    release_body_sha256: str
    release_id: int
    release_node_id_sha256: str
    completion_source: str
    source_action: str
    source_remote_write_performed: bool
    allowed_completion_sources: tuple[str, ...]
    allowed_source_actions: tuple[str, ...]
    blocker_codes: tuple[str, ...]
    post_release_attested_at_utc: str
    evaluated_at_utc: str
    post_release_attestation_authenticated: bool = True
    deploy_readiness_policy_host_pinned: bool = True
    exact_remote_release_revalidated: bool = True
    double_observation_matched: bool = True
    exact_tag_target_satisfied: bool = True
    exact_draft_release_satisfied: bool = True
    zero_release_assets_satisfied: bool = True
    base_branch_policy_satisfied: bool = False
    completion_source_policy_satisfied: bool = False
    source_action_policy_satisfied: bool = False
    deploy_readiness_evaluated: bool = True
    deploy_ready: bool = False
    deploy_readiness_authorized: bool = False
    tag_write_authorized: bool = False
    release_mutation_authorized: bool = False
    release_authorized: bool = False
    remote_write_authorized: bool = False
    merge_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    ready_for_review_authorized: bool = False
    reviewer_request_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    product_pilot_started: bool = False
    nonce_reusable: bool = False
    evaluation_scope: str = PILOT_EXACT_TASK_DEPLOY_READINESS_EVALUATION_SCOPE
    authority: str = PILOT_EXACT_TASK_DEPLOY_READINESS_EVALUATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_DEPLOY_READINESS_EVALUATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_DEPLOY_READINESS_EVALUATION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_DEPLOY_READINESS_EVALUATION_AUTHORITY
            or self.evaluation_scope
            != PILOT_EXACT_TASK_DEPLOY_READINESS_EVALUATION_SCOPE
        ):
            raise PilotExactTaskDeployReadinessEvaluationError(
                "deploy-readiness evaluation identity is unsupported"
            )
        for name in (
            "post_release_attestation_sha256",
            "completion_source_receipt_sha256",
            "release_authorization_sha256",
            "release_intent_sha256",
            "release_plan_sha256",
            "release_readiness_evaluation_sha256",
            "release_plan_config_sha256",
            "release_authorization_config_sha256",
            "deploy_readiness_policy_sha256",
            "remote_observation_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
            "upstream_merge_transaction_lock_sha256",
            "release_transaction_lock_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "release_body_sha256",
            "release_node_id_sha256",
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
            raise PilotExactTaskDeployReadinessEvaluationError(
                "deploy-readiness repository/environment identity is invalid"
            )
        _branch(self.release_base_branch, name="release_base_branch")
        _branch(self.deployment_base_branch, name="deployment_base_branch")
        if (
            self.tag_target_sha != self.merge_commit_sha
            or self.release_version != f"rsi-{self.merge_commit_sha}"
            or self.tag_name != f"modelrig-rsi-{self.merge_commit_sha}"
            or self.release_name != f"ModelRig RSI {self.merge_commit_sha[:12]}"
            or isinstance(self.release_id, bool)
            or not isinstance(self.release_id, int)
            or self.release_id < 1
            or self.completion_source not in _ALLOWED_COMPLETION_SOURCES
            or self.source_action not in _ALLOWED_SOURCE_ACTIONS
            or not isinstance(self.source_remote_write_performed, bool)
        ):
            raise PilotExactTaskDeployReadinessEvaluationError(
                "deploy-readiness deterministic release identity is invalid"
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
        criteria = (
            self.base_branch_policy_satisfied,
            self.completion_source_policy_satisfied,
            self.source_action_policy_satisfied,
            self.exact_tag_target_satisfied,
            self.exact_draft_release_satisfied,
            self.zero_release_assets_satisfied,
        )
        if any(not isinstance(value, bool) for value in criteria):
            raise PilotExactTaskDeployReadinessEvaluationError(
                "deploy-readiness criteria flags are invalid"
            )
        if self.base_branch_policy_satisfied != (
            self.release_base_branch == self.deployment_base_branch
        ):
            raise PilotExactTaskDeployReadinessEvaluationError(
                "deployment base-branch criterion is inconsistent"
            )
        if self.completion_source_policy_satisfied != (
            self.completion_source in self.allowed_completion_sources
        ):
            raise PilotExactTaskDeployReadinessEvaluationError(
                "deployment completion-source criterion is inconsistent"
            )
        if self.source_action_policy_satisfied != (
            self.source_action in self.allowed_source_actions
        ):
            raise PilotExactTaskDeployReadinessEvaluationError(
                "deployment completion-action criterion is inconsistent"
            )
        if (
            self.exact_tag_target_satisfied is not True
            or self.exact_draft_release_satisfied is not True
            or self.zero_release_assets_satisfied is not True
        ):
            raise PilotExactTaskDeployReadinessEvaluationError(
                "exact deterministic release criteria must remain satisfied"
            )
        expected_blockers: list[str] = []
        if not self.base_branch_policy_satisfied:
            expected_blockers.append(_BLOCKER_ORDER[0])
        if not self.completion_source_policy_satisfied:
            expected_blockers.append(_BLOCKER_ORDER[1])
        if not self.source_action_policy_satisfied:
            expected_blockers.append(_BLOCKER_ORDER[2])
        if tuple(expected_blockers) != self.blocker_codes:
            raise PilotExactTaskDeployReadinessEvaluationError(
                "deploy-readiness blocker set is inconsistent"
            )
        if self.deploy_ready != all(criteria) or self.deploy_ready != (
            not self.blocker_codes
        ):
            raise PilotExactTaskDeployReadinessEvaluationError(
                "deploy_ready does not equal evaluated criteria"
            )
        source_time = _utc(
            self.post_release_attested_at_utc,
            name="post_release_attested_at_utc",
        )
        evaluated = _utc(self.evaluated_at_utc, name="evaluated_at_utc")
        if evaluated < source_time:
            raise PilotExactTaskDeployReadinessEvaluationError(
                "deploy-readiness evaluation predates post-release attestation"
            )
        required_true = (
            "post_release_attestation_authenticated",
            "deploy_readiness_policy_host_pinned",
            "exact_remote_release_revalidated",
            "double_observation_matched",
            "exact_tag_target_satisfied",
            "exact_draft_release_satisfied",
            "zero_release_assets_satisfied",
            "deploy_readiness_evaluated",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskDeployReadinessEvaluationError(
                "deploy-readiness evidence is incomplete"
            )
        forced_false = (
            "deploy_readiness_authorized",
            "tag_write_authorized",
            "release_mutation_authorized",
            "release_authorized",
            "remote_write_authorized",
            "merge_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "ready_for_review_authorized",
            "reviewer_request_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "product_pilot_started",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskDeployReadinessEvaluationError(
                "deploy-readiness evaluation retains forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def evaluation_authenticated(self) -> bool:
        return _get_live_deploy_readiness_evaluation_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }
        result["allowed_completion_sources"] = list(
            self.allowed_completion_sources
        )
        result["allowed_source_actions"] = list(self.allowed_source_actions)
        result["blocker_codes"] = list(self.blocker_codes)
        return result

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskDeployReadinessEvaluationReceipt":
        if (
            not isinstance(value, Mapping)
            or set(value) != set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        ):
            raise PilotExactTaskDeployReadinessEvaluationError(
                "deploy-readiness evaluation fields mismatch"
            )
        completion = value.get("allowed_completion_sources")
        actions = value.get("allowed_source_actions")
        blockers = value.get("blocker_codes")
        if (
            not isinstance(completion, list)
            or not isinstance(actions, list)
            or not isinstance(blockers, list)
        ):
            raise PilotExactTaskDeployReadinessEvaluationError(
                "deploy-readiness list fields are invalid"
            )
        data = dict(value)
        data["allowed_completion_sources"] = tuple(completion)
        data["allowed_source_actions"] = tuple(actions)
        data["blocker_codes"] = tuple(blockers)
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _evaluate_verified_pilot_exact_task_deploy_readiness(
    *,
    post_release_attestation: PilotExactTaskPostReleaseAttestationReceipt,
    policy: PilotExactTaskDeployReadinessPolicy,
    policy_sha256: str,
    transport: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskDeployReadinessEvaluationReceipt:
    source = _require_live_post_release(post_release_attestation)
    if type(policy) is not PilotExactTaskDeployReadinessPolicy:
        raise PilotExactTaskDeployReadinessEvaluationError(
            "exact host deployment policy is required"
        )
    supplied_policy_sha = _hex64(
        policy_sha256,
        name="deploy_readiness_policy_sha256",
    )
    if policy.sha256 != supplied_policy_sha:
        raise PilotExactTaskDeployReadinessEvaluationError(
            "deploy-readiness policy digest mismatch"
        )
    if (
        policy.repository != source.repository
        or policy.repository_id != source.repository_id
    ):
        raise PilotExactTaskDeployReadinessEvaluationError(
            "deploy-readiness policy is not bound to exact repository"
        )
    if transport is None or not callable(getattr(transport, "observe", None)):
        raise PilotExactTaskDeployReadinessEvaluationError(
            "read-only deploy-readiness GitHub observer is required"
        )
    if (
        getattr(transport, "credential_config_sha256", None)
        != source.publisher_credential_config_sha256
        or getattr(transport, "credential_path_sha256", None)
        != source.publisher_credential_path_sha256
    ):
        raise PilotExactTaskDeployReadinessEvaluationError(
            "deploy-readiness observer credential identity differs from ADR-DC-066"
        )
    try:
        first = _normalize_remote_state(
            transport.observe(source),
            source,
        )
        second = _normalize_remote_state(
            transport.observe(source),
            source,
        )
    except PilotExactTaskDeployReadinessEvaluationError:
        raise
    except Exception as exc:
        raise PilotExactTaskDeployReadinessEvaluationError(
            "deploy-readiness GitHub observation failed"
        ) from exc
    if first != second:
        raise PilotExactTaskDeployReadinessEvaluationError(
            "GitHub deploy-readiness state changed between observations"
        )
    observation_sha = hashlib.sha256(
        _canonical(first).encode("utf-8")
    ).hexdigest()
    blockers = _blockers(source=source, policy=policy)
    base_ok = source.release_base_branch == policy.deployment_base_branch
    completion_ok = source.completion_source in policy.allowed_completion_sources
    action_ok = source.source_action in policy.allowed_source_actions
    evaluated_at = now_provider()
    if _utc(evaluated_at, name="evaluated_at_utc") < _utc(
        source.attested_at_utc,
        name="post_release_attested_at_utc",
    ):
        raise PilotExactTaskDeployReadinessEvaluationError(
            "system clock moved backwards after ADR-DC-069"
        )
    receipt = PilotExactTaskDeployReadinessEvaluationReceipt(
        post_release_attestation_sha256=source.sha256,
        completion_source_receipt_sha256=source.completion_source_receipt_sha256,
        release_authorization_sha256=source.release_authorization_sha256,
        release_intent_sha256=source.release_intent_sha256,
        release_plan_sha256=source.release_plan_sha256,
        release_readiness_evaluation_sha256=source.release_readiness_evaluation_sha256,
        release_plan_config_sha256=source.release_plan_config_sha256,
        release_authorization_config_sha256=source.release_authorization_config_sha256,
        deploy_readiness_policy_sha256=supplied_policy_sha,
        remote_observation_sha256=observation_sha,
        execution_nonce_sha256=source.execution_nonce_sha256,
        development_task_sha256=source.development_task_sha256,
        candidate_patch_sha256=source.candidate_patch_sha256,
        pr_intent_sha256=source.pr_intent_sha256,
        upstream_merge_transaction_lock_sha256=(
            source.upstream_merge_transaction_lock_sha256
        ),
        release_transaction_lock_sha256=source.transaction_lock_sha256,
        publisher_credential_config_sha256=source.publisher_credential_config_sha256,
        publisher_credential_path_sha256=source.publisher_credential_path_sha256,
        repository=source.repository,
        repository_id=source.repository_id,
        deployment_environment=policy.deployment_environment,
        release_base_branch=source.release_base_branch,
        deployment_base_branch=policy.deployment_base_branch,
        merge_commit_sha=source.merge_commit_sha,
        release_version=source.release_version,
        tag_name=source.tag_name,
        tag_target_sha=source.tag_target_sha,
        release_name=source.release_name,
        release_body_sha256=source.release_body_sha256,
        release_id=source.release_id,
        release_node_id_sha256=source.release_node_id_sha256,
        completion_source=source.completion_source,
        source_action=source.source_action,
        source_remote_write_performed=source.source_remote_write_performed,
        allowed_completion_sources=policy.allowed_completion_sources,
        allowed_source_actions=policy.allowed_source_actions,
        blocker_codes=blockers,
        post_release_attested_at_utc=source.attested_at_utc,
        evaluated_at_utc=evaluated_at,
        base_branch_policy_satisfied=base_ok,
        completion_source_policy_satisfied=completion_ok,
        source_action_policy_satisfied=action_ok,
        deploy_ready=not blockers,
    )
    _mark_deploy_readiness_evaluation_authenticated(
        receipt,
        source=source,
        policy_sha256=supplied_policy_sha,
        observation_sha256=observation_sha,
    )
    if receipt.evaluation_authenticated is not True:
        raise PilotExactTaskDeployReadinessEvaluationError(
            "deploy-readiness evaluation lost live provenance"
        )
    return receipt


def _canonical_policy() -> tuple[PilotExactTaskDeployReadinessPolicy, str]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_POLICY
        elif os.name == "nt":
            path = _WINDOWS_POLICY
        else:
            raise PilotExactTaskDeployReadinessEvaluationError(
                "deploy-readiness policy platform is unsupported"
            )
        return _read_host_policy(path)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskDeployReadinessEvaluationError(
            "deploy-readiness policy requires an elevated host operator"
        ) from exc


def evaluate_pilot_exact_task_deploy_readiness(
    post_release_attestation: PilotExactTaskPostReleaseAttestationReceipt,
) -> PilotExactTaskDeployReadinessEvaluationReceipt:
    """Evaluate one fresh exact release under the fixed staging deploy policy."""
    try:
        policy, digest = _canonical_policy()
        credential, credential_digest, credential_path = (
            publication_tx_boundary._canonical_credential()
        )
        transport = post_release_boundary._GitHubPostReleaseObserver(
            credential=credential,
            credential_config_sha256=credential_digest,
            credential_path=credential_path,
        )
        return _evaluate_verified_pilot_exact_task_deploy_readiness(
            post_release_attestation=post_release_attestation,
            policy=policy,
            policy_sha256=digest,
            transport=transport,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskDeployReadinessEvaluationError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskDeployReadinessEvaluationError(
            "exact deploy-readiness evaluation failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_DEPLOY_READINESS_EVALUATION_SCHEMA",
    "PILOT_EXACT_TASK_DEPLOY_READINESS_EVALUATION_AUTHORITY",
    "PILOT_EXACT_TASK_DEPLOY_READINESS_EVALUATION_SCOPE",
    "PILOT_EXACT_TASK_DEPLOY_READINESS_POLICY_SCHEMA",
    "PilotExactTaskDeployReadinessEvaluationError",
    "PilotExactTaskDeployReadinessPolicy",
    "PilotExactTaskDeployReadinessEvaluationReceipt",
    "evaluate_pilot_exact_task_deploy_readiness",
]
