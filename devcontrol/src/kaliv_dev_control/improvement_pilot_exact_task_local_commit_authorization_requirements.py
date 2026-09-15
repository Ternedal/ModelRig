"""ADR-DC-043 inert requirements for one later exact local-commit authorization.

This boundary accepts only the exact live ADR-DC-042 commit-object identity,
fresh-rechecks the frozen staged candidate twice, and freezes the evidence and
safety requirements that a later human-signed one-shot local-commit
authorization must bind.

It is deliberately not an authorization or a write capability.  It writes no
Git objects, moves no refs, creates no commit, and grants no local/remote write
or publication authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .contract import DevelopmentTask, normalize_repo_path
from . import improvement_pilot_exact_task_local_commit_object_identity as identity_boundary
from .improvement_pilot_exact_task_local_commit_object_identity import (
    PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHOR_EMAIL,
    PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHOR_NAME,
    PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_FORMAT,
    PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_IDENTITY_AUTHORITY,
    PILOT_EXACT_TASK_LOCAL_COMMIT_TIMEZONE,
    PilotExactTaskLocalCommitObjectIdentity,
)
from .tier_a_command_receipt import GitWorkspaceSnapshot, _GitWorkspaceEvidence

PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_REQUIREMENTS_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-local-commit-authorization-requirements/v1"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_REQUIREMENTS_AUTHORITY = (
    "dc-l16-exact-task-local-commit-authorization-requirements-only"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_REQUIREMENTS_SCOPE = (
    "local-commit-human-authorization-requirements-only-v1"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_INTENT = (
    "authorize-one-exact-local-commit-object-write-and-ref-update"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_MAX_WINDOW_SECONDS = 10 * 60

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_KEY_FIELDS = (
    "local_commit_object_identity_sha256",
    "local_commit_plan_sha256",
    "post_execution_evaluation_sha256",
    "execution_transaction_sha256",
    "tier_a_receipt_sha256",
    "execution_nonce_sha256",
    "development_task_sha256",
    "task_id",
    "repository",
    "base_sha",
    "fixed_command_plan_sha256",
    "post_execution_workspace_snapshot_sha256",
    "candidate_patch_sha256",
    "candidate_patch_bytes",
    "candidate_numstat_sha256",
    "scope_policy_sha256",
    "changed_paths",
    "changed_file_count",
    "root_tree_sha",
    "predicted_commit_sha",
    "commit_payload_sha256",
    "index_manifest_sha256",
    "index_entry_count",
    "commit_subject",
    "commit_subject_sha256",
    "author_name",
    "author_email",
    "committer_name",
    "committer_email",
    "commit_epoch_seconds",
    "commit_timezone",
    "object_format",
    "source_identity_materialized_at_utc",
    "requirements_materialized_at_utc",
    "authorization_intent",
    "authorization_max_window_seconds",
)


class PilotExactTaskLocalCommitAuthorizationRequirementsError(ValueError):
    """Exact local-commit authorization requirements are malformed or unsafe."""


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
        raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
            "local-commit authorization requirements are not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
            f"{name} is invalid"
        )
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
            f"{name} is invalid"
        )
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _development_task_sha256(task: DevelopmentTask) -> str:
    return hashlib.sha256(task.canonical_json().encode("utf-8")).hexdigest()


def _requirements_key_from_values(value: Any) -> str:
    payload = {name: getattr(value, name) for name in _KEY_FIELDS}
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _replay_object_identity(
    value: Any,
) -> PilotExactTaskLocalCommitObjectIdentity:
    if type(value) is not PilotExactTaskLocalCommitObjectIdentity:
        raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
            "exact ADR-DC-042 local commit object identity is required"
        )
    try:
        replayed = PilotExactTaskLocalCommitObjectIdentity.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
            "ADR-DC-042 object identity replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
            "ADR-DC-042 object identity replay mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_IDENTITY_AUTHORITY
        or value.local_commit_plan_authenticated is not True
        or value.fresh_workspace_snapshot_matched is not True
        or value.index_manifest_bound is not True
        or value.root_tree_identity_materialized is not True
        or value.commit_object_identity_materialized is not True
        or value.git_object_write_authorized is not False
        or value.local_ref_update_authorized is not False
        or value.local_commit_authorized is not False
        or value.local_commit_created is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
            "authorization requirements require inert ADR-DC-042 evidence"
        )
    return value


def _require_live_object_identity(
    value: Any,
) -> tuple[PilotExactTaskLocalCommitObjectIdentity, Mapping[str, Any]]:
    identity = _replay_object_identity(value)
    if identity.identity_authenticated is not True:
        raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
            "ADR-DC-042 live identity provenance is required"
        )
    inputs = identity_boundary._get_live_local_commit_object_identity_inputs(identity)
    if inputs is None:
        raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
            "ADR-DC-042 live identity inputs are unavailable"
        )
    task = inputs.get("task")
    plan = inputs.get("local_commit_plan")
    if (
        type(task) is not DevelopmentTask
        or plan is None
        or _development_task_sha256(task) != identity.development_task_sha256
        or getattr(plan, "sha256", None) != identity.local_commit_plan_sha256
        or task.task_id != identity.task_id
        or task.repository != identity.repository
        or task.base_sha != identity.base_sha
        or getattr(plan, "candidate_patch_sha256", None)
        != identity.candidate_patch_sha256
        or getattr(plan, "candidate_patch_bytes", None)
        != identity.candidate_patch_bytes
        or getattr(plan, "candidate_numstat_sha256", None)
        != identity.candidate_numstat_sha256
        or getattr(plan, "scope_policy_sha256", None)
        != identity.scope_policy_sha256
    ):
        raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
            "ADR-DC-042 identity is not bound to its exact live task/plan"
        )
    return identity, inputs


def _fresh_workspace_snapshot(inputs: Mapping[str, Any]) -> GitWorkspaceSnapshot:
    try:
        evidence = _GitWorkspaceEvidence(
            Path(inputs["workspace_root"]),
            inputs["task"],
            inputs["git_runner"],
        )
        return evidence.snapshot()
    except Exception as exc:
        raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
            "fresh authorization-requirements Trusted-Git snapshot failed"
        ) from exc


def _require_snapshot_matches_identity(
    identity: PilotExactTaskLocalCommitObjectIdentity,
    inputs: Mapping[str, Any],
    snapshot: GitWorkspaceSnapshot,
) -> None:
    plan = inputs.get("local_commit_plan")
    planned_snapshot = getattr(plan, "post_execution_workspace_snapshot", None)
    planned_snapshot_sha = getattr(
        plan, "post_execution_workspace_snapshot_sha256", None
    )
    if (
        type(planned_snapshot) is not GitWorkspaceSnapshot
        or snapshot != planned_snapshot
        or snapshot.sha256 != planned_snapshot_sha
        or snapshot.sha256 != identity.post_execution_workspace_snapshot_sha256
        or snapshot.head_sha != identity.base_sha
        or snapshot.staged_patch_sha256 != identity.candidate_patch_sha256
        or snapshot.staged_patch_bytes != identity.candidate_patch_bytes
        or snapshot.staged_patch_bytes <= 0
        or snapshot.unstaged_patch_bytes != 0
        or snapshot.untracked_path_count != 0
    ):
        raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
            "workspace no longer matches the exact ADR-DC-042 candidate identity"
        )


@dataclass(frozen=True, slots=True)
class PilotExactTaskLocalCommitAuthorizationRequirements:
    local_commit_object_identity_sha256: str
    local_commit_plan_sha256: str
    post_execution_evaluation_sha256: str
    execution_transaction_sha256: str
    tier_a_receipt_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    task_id: str
    repository: str
    base_sha: str
    fixed_command_plan_sha256: str
    post_execution_workspace_snapshot_sha256: str
    candidate_patch_sha256: str
    candidate_patch_bytes: int
    candidate_numstat_sha256: str
    scope_policy_sha256: str
    changed_paths: tuple[str, ...]
    changed_file_count: int
    root_tree_sha: str
    predicted_commit_sha: str
    commit_payload_sha256: str
    index_manifest_sha256: str
    index_entry_count: int
    commit_subject: str
    commit_subject_sha256: str
    author_name: str
    author_email: str
    committer_name: str
    committer_email: str
    commit_epoch_seconds: int
    commit_timezone: str
    object_format: str
    source_identity_materialized_at_utc: str
    requirements_materialized_at_utc: str
    authorization_intent: str
    authorization_max_window_seconds: int
    requirements_key_sha256: str
    source_identity_authenticated_at_materialization: bool = True
    fresh_workspace_snapshot_matched: bool = True
    exact_object_identity_required: bool = True
    fresh_human_local_commit_authorization_required: bool = True
    one_shot_local_commit_nonce_required: bool = True
    host_local_authorization_replay_ledger_required: bool = True
    host_local_commit_execution_ledger_required: bool = True
    fresh_source_identity_revalidation_before_authorization_required: bool = True
    fresh_workspace_revalidation_before_write_required: bool = True
    exact_parent_head_revalidation_required: bool = True
    exact_index_manifest_revalidation_required: bool = True
    exact_root_tree_identity_required: bool = True
    exact_predicted_commit_identity_required: bool = True
    fixed_author_committer_identity_required: bool = True
    fixed_commit_subject_required: bool = True
    manual_operator_invocation_required: bool = True
    failure_after_consumption_burns_nonce_required: bool = True
    remote_publication_forbidden: bool = True
    human_local_commit_authorization_verified: bool = False
    local_commit_authorization_consumed: bool = False
    git_object_write_authorized: bool = False
    local_ref_update_authorized: bool = False
    local_commit_authorized: bool = False
    local_commit_created: bool = False
    integration_ready: bool = False
    product_pilot_started: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    requirements_scope: str = PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_REQUIREMENTS_SCOPE
    authority: str = PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_REQUIREMENTS_AUTHORITY
    schema: str = PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_REQUIREMENTS_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_REQUIREMENTS_SCHEMA:
            raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
                "local-commit authorization requirements schema is unsupported"
            )
        if self.requirements_scope != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_REQUIREMENTS_SCOPE:
            raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
                "local-commit authorization requirements scope is unsupported"
            )
        for name in (
            "local_commit_object_identity_sha256",
            "local_commit_plan_sha256",
            "post_execution_evaluation_sha256",
            "execution_transaction_sha256",
            "tier_a_receipt_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "fixed_command_plan_sha256",
            "post_execution_workspace_snapshot_sha256",
            "candidate_patch_sha256",
            "candidate_numstat_sha256",
            "scope_policy_sha256",
            "commit_payload_sha256",
            "index_manifest_sha256",
            "commit_subject_sha256",
            "requirements_key_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("base_sha", "root_tree_sha", "predicted_commit_sha"):
            _hex40(getattr(self, name), name=name)
        if (
            not isinstance(self.task_id, str)
            or _TASK_ID.fullmatch(self.task_id) is None
        ):
            raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
                "task_id is invalid"
            )
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
        ):
            raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
                "repository is invalid"
            )
        if (
            isinstance(self.candidate_patch_bytes, bool)
            or not isinstance(self.candidate_patch_bytes, int)
            or self.candidate_patch_bytes <= 0
            or self.candidate_patch_bytes > 32 * 1024 * 1024
        ):
            raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
                "candidate_patch_bytes is invalid"
            )
        if (
            isinstance(self.changed_file_count, bool)
            or not isinstance(self.changed_file_count, int)
            or self.changed_file_count <= 0
            or self.changed_file_count > 200
            or not isinstance(self.changed_paths, tuple)
            or len(self.changed_paths) != self.changed_file_count
            or len(set(self.changed_paths)) != len(self.changed_paths)
        ):
            raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
                "changed path evidence is invalid"
            )
        for index, path in enumerate(self.changed_paths):
            if normalize_repo_path(path, name=f"changed_paths[{index}]") != path:
                raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
                    "changed_paths are not canonical"
                )
        if (
            isinstance(self.index_entry_count, bool)
            or not isinstance(self.index_entry_count, int)
            or self.index_entry_count <= 0
            or self.index_entry_count > 1_000_000
        ):
            raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
                "index_entry_count is invalid"
            )
        if (
            isinstance(self.commit_epoch_seconds, bool)
            or not isinstance(self.commit_epoch_seconds, int)
            or self.commit_epoch_seconds <= 0
        ):
            raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
                "commit_epoch_seconds is invalid"
            )
        if self.object_format != PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_FORMAT:
            raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
                "Git object format is unsupported"
            )
        if (
            self.author_name != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHOR_NAME
            or self.committer_name != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHOR_NAME
            or self.author_email != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHOR_EMAIL
            or self.committer_email != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHOR_EMAIL
            or self.commit_timezone != PILOT_EXACT_TASK_LOCAL_COMMIT_TIMEZONE
        ):
            raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
                "author/committer identity is not the reviewed fixed identity"
            )
        if (
            not isinstance(self.commit_subject, str)
            or not self.commit_subject
            or self.commit_subject.strip() != self.commit_subject
            or "\n" in self.commit_subject
            or "\r" in self.commit_subject
            or "\x00" in self.commit_subject
            or hashlib.sha256(self.commit_subject.encode("utf-8")).hexdigest()
            != self.commit_subject_sha256
        ):
            raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
                "commit subject identity is invalid"
            )
        source_time = _utc(
            self.source_identity_materialized_at_utc,
            name="source_identity_materialized_at_utc",
        )
        requirements_time = _utc(
            self.requirements_materialized_at_utc,
            name="requirements_materialized_at_utc",
        )
        if requirements_time < source_time:
            raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
                "authorization requirements predate source object identity"
            )
        if self.authorization_intent != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_INTENT:
            raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
                "local-commit authorization intent is unsupported"
            )
        if (
            isinstance(self.authorization_max_window_seconds, bool)
            or self.authorization_max_window_seconds
            != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_MAX_WINDOW_SECONDS
        ):
            raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
                "local-commit authorization window policy is invalid"
            )
        if _requirements_key_from_values(self) != self.requirements_key_sha256:
            raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
                "requirements key does not bind the exact local-commit evidence"
            )

        required_true = (
            "source_identity_authenticated_at_materialization",
            "fresh_workspace_snapshot_matched",
            "exact_object_identity_required",
            "fresh_human_local_commit_authorization_required",
            "one_shot_local_commit_nonce_required",
            "host_local_authorization_replay_ledger_required",
            "host_local_commit_execution_ledger_required",
            "fresh_source_identity_revalidation_before_authorization_required",
            "fresh_workspace_revalidation_before_write_required",
            "exact_parent_head_revalidation_required",
            "exact_index_manifest_revalidation_required",
            "exact_root_tree_identity_required",
            "exact_predicted_commit_identity_required",
            "fixed_author_committer_identity_required",
            "fixed_commit_subject_required",
            "manual_operator_invocation_required",
            "failure_after_consumption_burns_nonce_required",
            "remote_publication_forbidden",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
                "all local-commit authorization safeguards must remain enabled"
            )
        forced_false = (
            "human_local_commit_authorization_verified",
            "local_commit_authorization_consumed",
            "git_object_write_authorized",
            "local_ref_update_authorized",
            "local_commit_authorized",
            "local_commit_created",
            "integration_ready",
            "product_pilot_started",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
                "authorization requirements cannot grant local/remote write authority"
            )
        if self.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_REQUIREMENTS_AUTHORITY:
            raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
                "authorization requirements authority is unsupported"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name in self.__dataclass_fields__:  # type: ignore[attr-defined]
            value = getattr(self, name)
            result[name] = list(value) if name == "changed_paths" else value
        return result

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskLocalCommitAuthorizationRequirements":
        if not isinstance(value, Mapping):
            raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
                "authorization requirements must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
                "authorization requirements fields mismatch"
            )
        data = dict(value)
        try:
            data["changed_paths"] = tuple(data["changed_paths"])
        except Exception as exc:
            raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
                "authorization requirements changed_paths are invalid"
            ) from exc
        return cls(**data)

    @classmethod
    def from_json(
        cls, text: str
    ) -> "PilotExactTaskLocalCommitAuthorizationRequirements":
        try:
            return cls.from_mapping(json.loads(text))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
                "authorization requirements JSON is invalid"
            ) from exc

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _build_verified_pilot_exact_task_local_commit_authorization_requirements(
    *,
    object_identity: PilotExactTaskLocalCommitObjectIdentity,
    now_provider,
) -> PilotExactTaskLocalCommitAuthorizationRequirements:
    identity, inputs = _require_live_object_identity(object_identity)

    first = _fresh_workspace_snapshot(inputs)
    _require_snapshot_matches_identity(identity, inputs, first)

    materialized_at = now_provider()
    source_time = _utc(identity.materialized_at_utc, name="source identity materialized_at_utc")
    materialized_time = _utc(
        materialized_at, name="requirements_materialized_at_utc"
    )
    if materialized_time < source_time:
        raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
            "system clock moved backwards after ADR-DC-042 materialization"
        )

    values = dict(
        local_commit_object_identity_sha256=identity.sha256,
        local_commit_plan_sha256=identity.local_commit_plan_sha256,
        post_execution_evaluation_sha256=identity.post_execution_evaluation_sha256,
        execution_transaction_sha256=identity.execution_transaction_sha256,
        tier_a_receipt_sha256=identity.tier_a_receipt_sha256,
        execution_nonce_sha256=identity.execution_nonce_sha256,
        development_task_sha256=identity.development_task_sha256,
        task_id=identity.task_id,
        repository=identity.repository,
        base_sha=identity.base_sha,
        fixed_command_plan_sha256=identity.fixed_command_plan_sha256,
        post_execution_workspace_snapshot_sha256=(
            identity.post_execution_workspace_snapshot_sha256
        ),
        candidate_patch_sha256=identity.candidate_patch_sha256,
        candidate_patch_bytes=identity.candidate_patch_bytes,
        candidate_numstat_sha256=identity.candidate_numstat_sha256,
        scope_policy_sha256=identity.scope_policy_sha256,
        changed_paths=identity.changed_paths,
        changed_file_count=identity.changed_file_count,
        root_tree_sha=identity.root_tree_sha,
        predicted_commit_sha=identity.predicted_commit_sha,
        commit_payload_sha256=identity.commit_payload_sha256,
        index_manifest_sha256=identity.index_manifest_sha256,
        index_entry_count=identity.index_entry_count,
        commit_subject=identity.commit_subject,
        commit_subject_sha256=identity.commit_subject_sha256,
        author_name=identity.author_name,
        author_email=identity.author_email,
        committer_name=identity.committer_name,
        committer_email=identity.committer_email,
        commit_epoch_seconds=identity.commit_epoch_seconds,
        commit_timezone=identity.commit_timezone,
        object_format=identity.object_format,
        source_identity_materialized_at_utc=identity.materialized_at_utc,
        requirements_materialized_at_utc=materialized_at,
        authorization_intent=PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_INTENT,
        authorization_max_window_seconds=(
            PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_MAX_WINDOW_SECONDS
        ),
    )

    key_probe = type("_RequirementsKeyProbe", (), values)()
    requirements = PilotExactTaskLocalCommitAuthorizationRequirements(
        **values,
        requirements_key_sha256=_requirements_key_from_values(key_probe),
    )

    second = _fresh_workspace_snapshot(inputs)
    _require_snapshot_matches_identity(identity, inputs, second)
    if second != first or second.sha256 != first.sha256:
        raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
            "workspace changed while authorization requirements were materialized"
        )
    return requirements


def build_pilot_exact_task_local_commit_authorization_requirements(
    object_identity: PilotExactTaskLocalCommitObjectIdentity,
) -> PilotExactTaskLocalCommitAuthorizationRequirements:
    """Build inert human-authorization requirements from one live ADR-DC-042 identity."""
    try:
        return _build_verified_pilot_exact_task_local_commit_authorization_requirements(
            object_identity=object_identity,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskLocalCommitAuthorizationRequirementsError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskLocalCommitAuthorizationRequirementsError(
            "host-controlled local-commit authorization requirements failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_REQUIREMENTS_SCHEMA",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_REQUIREMENTS_AUTHORITY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_REQUIREMENTS_SCOPE",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_INTENT",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_MAX_WINDOW_SECONDS",
    "PilotExactTaskLocalCommitAuthorizationRequirementsError",
    "PilotExactTaskLocalCommitAuthorizationRequirements",
    "build_pilot_exact_task_local_commit_authorization_requirements",
]
