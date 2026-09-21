"""ADR-DC-047 inert exact remote-publication and draft-PR plan.

This boundary accepts only one exact live ADR-DC-046 integration-readiness
receipt, revalidates the completed local commit read-only, binds one host-pinned
GitHub destination, and deterministically materializes remote-branch plus draft
pull-request intent.

It performs no network or Git mutation and grants no push, pull-request, merge,
release, deploy or production-activation authority.
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
from typing import Any, Mapping

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
    _require_host_controlled_ledger_root,
)
from .contract import DevelopmentTask, MergeAuthority
from . import improvement_pilot_exact_task_integration_readiness as readiness_boundary
from .improvement_pilot_exact_task_integration_readiness import (
    PILOT_EXACT_TASK_INTEGRATION_READINESS_AUTHORITY,
    PilotExactTaskIntegrationReadinessReceipt,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_REMOTE_PUBLICATION_PLAN_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-publication-plan/v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_PLAN_AUTHORITY = (
    "host-planned-one-dc-l16-exact-remote-publication-intent-only"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_PLAN_SCOPE = (
    "exact-remote-publication-draft-pr-intent-only-v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-publication-target/v1"
)
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_MAX_TARGET_BYTES = 64 * 1024
_MAX_PR_BODY_BYTES = 12_000
_POSIX_TARGET = Path(
    "/etc/modelrig/devcontrol/"
    "rsi-pilot-exact-task-remote-publication-target-v1.json"
)
_WINDOWS_TARGET = (
    Path(r"C:\ProgramData\ModelRig\DevControl\config")
    / "rsi-pilot-exact-task-remote-publication-target-v1.json"
)


class PilotExactTaskRemotePublicationPlanError(ValueError):
    """Exact remote publication intent is malformed, mutable or over-authorized."""


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
        raise PilotExactTaskRemotePublicationPlanError(
            "remote publication plan is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskRemotePublicationPlanError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskRemotePublicationPlanError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskRemotePublicationPlanError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskRemotePublicationPlanError(f"{name} is invalid") from exc


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
        raise PilotExactTaskRemotePublicationPlanError(
            f"{name} is not a canonical branch name"
        )
    return value


def _remote_repository_identity_payload(
    *, repository: str, repository_id: str, provider: str, host: str
) -> dict[str, str]:
    return {
        "provider": provider,
        "host": host,
        "repository": repository,
        "repository_id": repository_id,
    }


def _remote_repository_identity_sha256(
    *, repository: str, repository_id: str, provider: str, host: str
) -> str:
    return hashlib.sha256(
        _canonical(
            _remote_repository_identity_payload(
                repository=repository,
                repository_id=repository_id,
                provider=provider,
                host=host,
            )
        ).encode("utf-8")
    ).hexdigest()


def _expected_head_branch(
    *, task_id: str, predicted_commit_sha: str, prefix: str
) -> str:
    suffix = task_id.lower().replace("_", "-")
    return _branch(
        f"{prefix}/{suffix}-{predicted_commit_sha[:12]}",
        name="planned head branch",
    )


def _expected_pr_title(*, task_id: str, predicted_commit_sha: str) -> str:
    title = f"draft(devcontrol): {task_id} exact RSI candidate {predicted_commit_sha[:12]}"
    if len(title.encode("utf-8")) > 240:
        raise PilotExactTaskRemotePublicationPlanError("planned PR title is oversized")
    return title


def _expected_pr_body(
    *,
    task_id: str,
    repository: str,
    repository_id: str,
    base_branch: str,
    head_branch: str,
    base_sha: str,
    predicted_commit_sha: str,
    root_tree_sha: str,
    candidate_patch_sha256: str,
    integration_readiness_sha256: str,
) -> str:
    body = (
        "## Exact Development Control candidate\n\n"
        f"- Task: `{task_id}`\n"
        f"- Repository: `{repository}` (`{repository_id}`)\n"
        f"- Base branch: `{base_branch}`\n"
        f"- Planned head branch: `{head_branch}`\n"
        f"- Exact pre-task base: `{base_sha}`\n"
        f"- Exact candidate commit: `{predicted_commit_sha}`\n"
        f"- Exact root tree: `{root_tree_sha}`\n"
        f"- Exact candidate patch: `{candidate_patch_sha256}`\n"
        f"- ADR-DC-046 readiness: `{integration_readiness_sha256}`\n\n"
        "## Authority boundary\n\n"
        "> This is deterministic **draft pull-request intent only**. "
        "ADR-DC-047 does not push a branch, create or mutate a pull request, "
        "request reviewers, merge, release, deploy or activate production. "
        "Human merge authority remains unchanged."
    )
    if not body or len(body.encode("utf-8")) > _MAX_PR_BODY_BYTES:
        raise PilotExactTaskRemotePublicationPlanError("planned PR body is oversized")
    return body


def _pr_intent_sha256(
    *,
    repository: str,
    repository_id: str,
    provider: str,
    host: str,
    remote_name: str,
    base_branch: str,
    head_branch: str,
    base_sha: str,
    predicted_commit_sha: str,
    pr_title: str,
    pr_body: str,
) -> str:
    payload = {
        "repository": repository,
        "repository_id": repository_id,
        "provider": provider,
        "host": host,
        "remote_name": remote_name,
        "base_branch": base_branch,
        "head_branch": head_branch,
        "base_sha": base_sha,
        "predicted_commit_sha": predicted_commit_sha,
        "draft": True,
        "maintainer_can_modify": False,
        "pr_title": pr_title,
        "pr_body": pr_body,
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PilotExactTaskRemotePublicationTarget:
    repository: str
    repository_id: str
    provider: str = "github"
    host: str = "github.com"
    remote_name: str = "origin"
    base_branch: str = "main"
    head_branch_prefix: str = "modelrig-rsi"
    schema: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_SCHEMA:
            raise PilotExactTaskRemotePublicationPlanError(
                "remote publication target schema is unsupported"
            )
        if self.provider != "github" or self.host != "github.com":
            raise PilotExactTaskRemotePublicationPlanError(
                "remote publication provider is unsupported"
            )
        if self.remote_name != "origin":
            raise PilotExactTaskRemotePublicationPlanError(
                "remote publication target must use origin"
            )
        if self.base_branch != "main":
            raise PilotExactTaskRemotePublicationPlanError(
                "remote publication base branch must remain main"
            )
        if self.head_branch_prefix != "modelrig-rsi":
            raise PilotExactTaskRemotePublicationPlanError(
                "remote publication branch prefix is unsupported"
            )
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
        ):
            raise PilotExactTaskRemotePublicationPlanError("target repository is invalid")
        if (
            not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskRemotePublicationPlanError("target repository ID is invalid")
        _branch(self.base_branch, name="target base branch")
        _branch(self.head_branch_prefix, name="target head branch prefix")

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskRemotePublicationTarget":
        if not isinstance(value, Mapping):
            raise PilotExactTaskRemotePublicationPlanError(
                "remote publication target must be an object"
            )
        expected = {
            "schema",
            "repository",
            "repository_id",
            "provider",
            "host",
            "remote_name",
            "base_branch",
            "head_branch_prefix",
        }
        if set(value) != expected:
            raise PilotExactTaskRemotePublicationPlanError(
                "remote publication target fields mismatch"
            )
        return cls(**dict(value))

    def to_dict(self) -> dict[str, str]:
        return {
            "schema": self.schema,
            "repository": self.repository,
            "repository_id": self.repository_id,
            "provider": self.provider,
            "host": self.host,
            "remote_name": self.remote_name,
            "base_branch": self.base_branch,
            "head_branch_prefix": self.head_branch_prefix,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _parse_target_payload(payload: bytes) -> tuple[PilotExactTaskRemotePublicationTarget, str]:
    if not isinstance(payload, bytes) or not 2 <= len(payload) <= _MAX_TARGET_BYTES:
        raise PilotExactTaskRemotePublicationPlanError(
            "remote publication target payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskRemotePublicationPlanError(
            "remote publication target JSON is invalid"
        ) from exc
    target = PilotExactTaskRemotePublicationTarget.from_mapping(raw)
    canonical = target.canonical_json().encode("utf-8")
    if payload != canonical:
        raise PilotExactTaskRemotePublicationPlanError(
            "remote publication target is not canonical JSON"
        )
    return target, hashlib.sha256(payload).hexdigest()


def _read_host_target(
    path: Path,
) -> tuple[PilotExactTaskRemotePublicationTarget, str, Path, bytes]:
    candidate = Path(path)
    if (
        not candidate.is_absolute()
        or _has_linkish_component(candidate)
        or not candidate.is_file()
    ):
        raise PilotExactTaskRemotePublicationPlanError(
            "remote publication target path is unsafe"
        )
    try:
        payload = candidate.read_bytes()
    except OSError as exc:
        raise PilotExactTaskRemotePublicationPlanError(
            "remote publication target cannot be read"
        ) from exc
    target, digest = _parse_target_payload(payload)
    return target, digest, candidate, payload


def _canonical_target() -> tuple[
    PilotExactTaskRemotePublicationTarget, str, Path, bytes
]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_TARGET
        elif os.name == "nt":
            path = _WINDOWS_TARGET
        else:
            raise PilotExactTaskRemotePublicationPlanError(
                "remote publication target is unsupported on this platform"
            )
        _require_host_controlled_ledger_root(path.parent)
        first = _read_host_target(path)
        second = _read_host_target(path)
        if first[1] != second[1] or first[3] != second[3] or first[0] != second[0]:
            raise PilotExactTaskRemotePublicationPlanError(
                "remote publication target changed while being read"
            )
        return second
    except PhysicalHostStateError as exc:
        raise PilotExactTaskRemotePublicationPlanError(
            "remote publication target is not host-admin controlled"
        ) from exc


def _require_live_readiness(
    value: Any,
) -> tuple[PilotExactTaskIntegrationReadinessReceipt, Mapping[str, Any], DevelopmentTask]:
    if type(value) is not PilotExactTaskIntegrationReadinessReceipt:
        raise PilotExactTaskRemotePublicationPlanError(
            "exact ADR-DC-046 integration readiness receipt is required"
        )
    try:
        replayed = PilotExactTaskIntegrationReadinessReceipt.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskRemotePublicationPlanError(
            "ADR-DC-046 readiness replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskRemotePublicationPlanError(
            "ADR-DC-046 readiness identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_INTEGRATION_READINESS_AUTHORITY
        or value.readiness_authenticated is not True
        or value.integration_ready is not True
        or value.semantic_acceptance_criteria_evaluated is not True
        or value.semantic_acceptance_criteria_all_satisfied is not True
        or value.trusted_external_semantic_review_verified is not True
        or value.fresh_post_commit_state_revalidated is not True
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskRemotePublicationPlanError(
            "remote publication planning requires one live inert ADR-DC-046 readiness"
        )
    inputs = readiness_boundary._get_live_integration_readiness_inputs(value)
    if inputs is None:
        raise PilotExactTaskRemotePublicationPlanError(
            "ADR-DC-046 live readiness inputs are unavailable"
        )
    task = inputs.get("task")
    evaluation = inputs.get("post_commit_integration_evaluation")
    identity = inputs.get("local_commit_object_identity")
    transaction = inputs.get("local_commit_transaction")
    if (
        type(task) is not DevelopmentTask
        or task.merge_authority is not MergeAuthority.HUMAN
        or evaluation is None
        or identity is None
        or transaction is None
        or task.task_id != value.task_id
        or task.repository != value.repository
        or task.base_sha != value.base_sha
        or getattr(identity, "sha256", None) != value.local_commit_object_identity_sha256
        or getattr(identity, "predicted_commit_sha", None) != value.predicted_commit_sha
        or getattr(identity, "candidate_patch_sha256", None) != value.candidate_patch_sha256
        or getattr(transaction, "sha256", None) != value.local_commit_transaction_sha256
        or getattr(evaluation, "sha256", None)
        != value.post_commit_integration_evaluation_sha256
    ):
        raise PilotExactTaskRemotePublicationPlanError(
            "ADR-DC-046 readiness is not bound to its exact live provenance"
        )
    return value, inputs, task


def _fresh_revalidate_exact_local_commit(
    *, readiness: PilotExactTaskIntegrationReadinessReceipt, inputs: Mapping[str, Any]
) -> None:
    evaluation = inputs.get("post_commit_integration_evaluation")
    if evaluation is None:
        raise PilotExactTaskRemotePublicationPlanError(
            "live readiness lacks ADR-DC-045 evaluation"
        )
    try:
        readiness_boundary._fresh_revalidate_post_commit(
            evaluation=evaluation,
            inputs=inputs,
        )
    except Exception as exc:
        raise PilotExactTaskRemotePublicationPlanError(
            "exact local commit changed before remote publication planning"
        ) from exc
    live = readiness_boundary._get_live_integration_readiness_inputs(readiness)
    if live is None or live.get("post_commit_integration_evaluation") is not evaluation:
        raise PilotExactTaskRemotePublicationPlanError(
            "live readiness changed during remote publication planning"
        )


def _live_registry():
    records: dict[
        int,
        tuple[
            int,
            str,
            weakref.ReferenceType[Any],
            weakref.ReferenceType[Any],
            str,
            str,
        ],
    ] = {}

    def mark(
        plan: Any,
        readiness: PilotExactTaskIntegrationReadinessReceipt,
        *,
        target_config_sha256: str,
        target_payload_sha256: str,
    ) -> None:
        key = id(plan)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            plan.sha256,
            weakref.ref(plan, cleanup),
            weakref.ref(readiness),
            target_config_sha256,
            target_payload_sha256,
        )

    def get(plan: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(plan))
        if entry is None:
            return None
        pid, digest, plan_ref, readiness_ref, target_digest, payload_digest = entry
        readiness = readiness_ref()
        if (
            pid != os.getpid()
            or plan_ref() is not plan
            or readiness is None
            or readiness.readiness_authenticated is not True
            or plan.sha256 != digest
            or plan.integration_readiness_sha256 != readiness.sha256
            or plan.remote_target_config_sha256 != target_digest
            or plan.remote_target_config_sha256 != payload_digest
        ):
            return None
        inputs = readiness_boundary._get_live_integration_readiness_inputs(readiness)
        if inputs is None:
            return None
        result = dict(inputs)
        result["integration_readiness"] = readiness
        return MappingProxyType(result)

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_remote_publication_plan_authenticated,
    _get_live_remote_publication_plan_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskRemotePublicationPlan:
    integration_readiness_sha256: str
    post_commit_integration_evaluation_sha256: str
    local_commit_transaction_sha256: str
    local_commit_object_identity_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    remote_target_config_sha256: str
    remote_repository_identity_sha256: str
    pr_intent_sha256: str
    task_id: str
    repository: str
    repository_id: str
    provider: str
    host: str
    remote_name: str
    base_branch: str
    head_branch: str
    base_sha: str
    predicted_commit_sha: str
    root_tree_sha: str
    pr_title: str
    pr_body: str
    planned_at_utc: str
    draft: bool = True
    maintainer_can_modify: bool = False
    integration_readiness_authenticated: bool = True
    integration_ready: bool = True
    exact_local_commit_revalidated: bool = True
    remote_target_host_pinned: bool = True
    remote_publication_plan_materialized: bool = True
    remote_branch_creation_planned: bool = True
    exact_commit_push_planned: bool = True
    draft_pr_creation_planned: bool = True
    remote_state_observed: bool = False
    git_object_write_authorized: bool = False
    local_ref_update_authorized: bool = False
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    product_pilot_started: bool = False
    plan_scope: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_PLAN_SCOPE
    authority: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_PLAN_AUTHORITY
    schema: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_PLAN_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_REMOTE_PUBLICATION_PLAN_SCHEMA:
            raise PilotExactTaskRemotePublicationPlanError(
                "remote publication plan schema is unsupported"
            )
        if self.plan_scope != PILOT_EXACT_TASK_REMOTE_PUBLICATION_PLAN_SCOPE:
            raise PilotExactTaskRemotePublicationPlanError(
                "remote publication plan scope is unsupported"
            )
        for name in (
            "integration_readiness_sha256",
            "post_commit_integration_evaluation_sha256",
            "local_commit_transaction_sha256",
            "local_commit_object_identity_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "remote_target_config_sha256",
            "remote_repository_identity_sha256",
            "pr_intent_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("base_sha", "predicted_commit_sha", "root_tree_sha"):
            _hex40(getattr(self, name), name=name)
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise PilotExactTaskRemotePublicationPlanError("task_id is invalid")
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PilotExactTaskRemotePublicationPlanError("repository is invalid")
        if not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None:
            raise PilotExactTaskRemotePublicationPlanError("repository_id is invalid")
        if self.provider != "github" or self.host != "github.com":
            raise PilotExactTaskRemotePublicationPlanError("provider/host is unsupported")
        if self.remote_name != "origin" or self.base_branch != "main":
            raise PilotExactTaskRemotePublicationPlanError("remote/base target is unsupported")
        _branch(self.base_branch, name="base_branch")
        _branch(self.head_branch, name="head_branch")
        if not isinstance(self.pr_title, str) or not self.pr_title or self.pr_title.strip() != self.pr_title:
            raise PilotExactTaskRemotePublicationPlanError("pr_title is invalid")
        if len(self.pr_title.encode("utf-8")) > 240:
            raise PilotExactTaskRemotePublicationPlanError("pr_title is oversized")
        if not isinstance(self.pr_body, str) or not self.pr_body or self.pr_body.strip() != self.pr_body:
            raise PilotExactTaskRemotePublicationPlanError("pr_body is invalid")
        if len(self.pr_body.encode("utf-8")) > _MAX_PR_BODY_BYTES:
            raise PilotExactTaskRemotePublicationPlanError("pr_body is oversized")
        _utc(self.planned_at_utc, name="planned_at_utc")
        required_true = (
            "draft",
            "integration_readiness_authenticated",
            "integration_ready",
            "exact_local_commit_revalidated",
            "remote_target_host_pinned",
            "remote_publication_plan_materialized",
            "remote_branch_creation_planned",
            "exact_commit_push_planned",
            "draft_pr_creation_planned",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskRemotePublicationPlanError(
                "remote publication plan evidence is incomplete"
            )
        forced_false = (
            "maintainer_can_modify",
            "remote_state_observed",
            "git_object_write_authorized",
            "local_ref_update_authorized",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "product_pilot_started",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskRemotePublicationPlanError(
                "remote publication plan cannot grant mutation authority"
            )
        expected_remote = _remote_repository_identity_sha256(
            repository=self.repository,
            repository_id=self.repository_id,
            provider=self.provider,
            host=self.host,
        )
        if self.remote_repository_identity_sha256 != expected_remote:
            raise PilotExactTaskRemotePublicationPlanError(
                "remote repository identity hash is inconsistent"
            )
        expected_title = _expected_pr_title(
            task_id=self.task_id,
            predicted_commit_sha=self.predicted_commit_sha,
        )
        expected_body = _expected_pr_body(
            task_id=self.task_id,
            repository=self.repository,
            repository_id=self.repository_id,
            base_branch=self.base_branch,
            head_branch=self.head_branch,
            base_sha=self.base_sha,
            predicted_commit_sha=self.predicted_commit_sha,
            root_tree_sha=self.root_tree_sha,
            candidate_patch_sha256=self.candidate_patch_sha256,
            integration_readiness_sha256=self.integration_readiness_sha256,
        )
        if self.pr_title != expected_title or self.pr_body != expected_body:
            raise PilotExactTaskRemotePublicationPlanError(
                "draft pull-request intent is not deterministic"
            )
        expected_intent = _pr_intent_sha256(
            repository=self.repository,
            repository_id=self.repository_id,
            provider=self.provider,
            host=self.host,
            remote_name=self.remote_name,
            base_branch=self.base_branch,
            head_branch=self.head_branch,
            base_sha=self.base_sha,
            predicted_commit_sha=self.predicted_commit_sha,
            pr_title=self.pr_title,
            pr_body=self.pr_body,
        )
        if self.pr_intent_sha256 != expected_intent:
            raise PilotExactTaskRemotePublicationPlanError(
                "draft pull-request intent hash is inconsistent"
            )
        if self.authority != PILOT_EXACT_TASK_REMOTE_PUBLICATION_PLAN_AUTHORITY:
            raise PilotExactTaskRemotePublicationPlanError(
                "remote publication plan authority is unsupported"
            )

    @property
    def plan_authenticated(self) -> bool:
        return _get_live_remote_publication_plan_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskRemotePublicationPlan":
        if not isinstance(value, Mapping):
            raise PilotExactTaskRemotePublicationPlanError(
                "remote publication plan must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskRemotePublicationPlanError(
                "remote publication plan fields mismatch"
            )
        return cls(**dict(value))

    @classmethod
    def from_json(cls, text: str) -> "PilotExactTaskRemotePublicationPlan":
        try:
            return cls.from_mapping(json.loads(text))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PilotExactTaskRemotePublicationPlanError(
                "remote publication plan JSON is invalid"
            ) from exc

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _materialize_verified_pilot_exact_task_remote_publication_plan(
    *,
    integration_readiness: PilotExactTaskIntegrationReadinessReceipt,
    target: PilotExactTaskRemotePublicationTarget,
    target_config_sha256: str,
    now_provider,
) -> PilotExactTaskRemotePublicationPlan:
    ready, inputs, task = _require_live_readiness(integration_readiness)
    if type(target) is not PilotExactTaskRemotePublicationTarget:
        raise PilotExactTaskRemotePublicationPlanError(
            "exact host-pinned remote publication target is required"
        )
    _hex64(target_config_sha256, name="remote_target_config_sha256")
    if target.sha256 != target_config_sha256:
        raise PilotExactTaskRemotePublicationPlanError(
            "remote target digest does not match canonical target"
        )
    if target.repository != task.repository:
        raise PilotExactTaskRemotePublicationPlanError(
            "remote target repository does not match exact DevelopmentTask"
        )

    _fresh_revalidate_exact_local_commit(readiness=ready, inputs=inputs)
    ready_again, inputs_again, task_again = _require_live_readiness(ready)
    if (
        ready_again is not ready
        or task_again is not task
        or inputs_again.get("local_commit_object_identity")
        is not inputs.get("local_commit_object_identity")
    ):
        raise PilotExactTaskRemotePublicationPlanError(
            "live readiness changed during remote publication planning"
        )

    planned_at = now_provider()
    if _utc(planned_at, name="planned_at_utc") < _utc(
        ready.readiness_evaluated_at_utc,
        name="readiness_evaluated_at_utc",
    ):
        raise PilotExactTaskRemotePublicationPlanError(
            "system clock moved backwards after ADR-DC-046 readiness"
        )

    head_branch = _expected_head_branch(
        task_id=task.task_id,
        predicted_commit_sha=ready.predicted_commit_sha,
        prefix=target.head_branch_prefix,
    )
    pr_title = _expected_pr_title(
        task_id=task.task_id,
        predicted_commit_sha=ready.predicted_commit_sha,
    )
    pr_body = _expected_pr_body(
        task_id=task.task_id,
        repository=task.repository,
        repository_id=target.repository_id,
        base_branch=target.base_branch,
        head_branch=head_branch,
        base_sha=task.base_sha,
        predicted_commit_sha=ready.predicted_commit_sha,
        root_tree_sha=ready.root_tree_sha,
        candidate_patch_sha256=ready.candidate_patch_sha256,
        integration_readiness_sha256=ready.sha256,
    )
    remote_identity_sha = _remote_repository_identity_sha256(
        repository=task.repository,
        repository_id=target.repository_id,
        provider=target.provider,
        host=target.host,
    )
    intent_sha = _pr_intent_sha256(
        repository=task.repository,
        repository_id=target.repository_id,
        provider=target.provider,
        host=target.host,
        remote_name=target.remote_name,
        base_branch=target.base_branch,
        head_branch=head_branch,
        base_sha=task.base_sha,
        predicted_commit_sha=ready.predicted_commit_sha,
        pr_title=pr_title,
        pr_body=pr_body,
    )
    plan = PilotExactTaskRemotePublicationPlan(
        integration_readiness_sha256=ready.sha256,
        post_commit_integration_evaluation_sha256=(
            ready.post_commit_integration_evaluation_sha256
        ),
        local_commit_transaction_sha256=ready.local_commit_transaction_sha256,
        local_commit_object_identity_sha256=ready.local_commit_object_identity_sha256,
        execution_nonce_sha256=ready.execution_nonce_sha256,
        development_task_sha256=ready.development_task_sha256,
        candidate_patch_sha256=ready.candidate_patch_sha256,
        remote_target_config_sha256=target_config_sha256,
        remote_repository_identity_sha256=remote_identity_sha,
        pr_intent_sha256=intent_sha,
        task_id=task.task_id,
        repository=task.repository,
        repository_id=target.repository_id,
        provider=target.provider,
        host=target.host,
        remote_name=target.remote_name,
        base_branch=target.base_branch,
        head_branch=head_branch,
        base_sha=task.base_sha,
        predicted_commit_sha=ready.predicted_commit_sha,
        root_tree_sha=ready.root_tree_sha,
        pr_title=pr_title,
        pr_body=pr_body,
        planned_at_utc=planned_at,
    )
    _mark_remote_publication_plan_authenticated(
        plan,
        ready,
        target_config_sha256=target_config_sha256,
        target_payload_sha256=target.sha256,
    )
    if plan.plan_authenticated is not True:
        raise PilotExactTaskRemotePublicationPlanError(
            "remote publication plan lost live provenance"
        )
    return plan


def materialize_pilot_exact_task_remote_publication_plan(
    integration_readiness: PilotExactTaskIntegrationReadinessReceipt,
) -> PilotExactTaskRemotePublicationPlan:
    """Host-pinned ADR-DC-047 exact inert remote publication plan."""
    try:
        target, digest, _path, _payload = _canonical_target()
        return _materialize_verified_pilot_exact_task_remote_publication_plan(
            integration_readiness=integration_readiness,
            target=target,
            target_config_sha256=digest,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskRemotePublicationPlanError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskRemotePublicationPlanError(
            "host-controlled exact remote publication planning failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_PLAN_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_PLAN_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_PLAN_SCOPE",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_SCHEMA",
    "PilotExactTaskRemotePublicationPlanError",
    "PilotExactTaskRemotePublicationTarget",
    "PilotExactTaskRemotePublicationPlan",
    "materialize_pilot_exact_task_remote_publication_plan",
]
