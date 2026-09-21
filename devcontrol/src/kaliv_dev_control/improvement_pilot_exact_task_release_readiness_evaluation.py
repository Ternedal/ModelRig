"""ADR-DC-063 exact release-readiness policy evaluation.

This boundary accepts only one fresh live ADR-DC-062 post-merge attestation,
re-observes the exact merged PR and base ref through a credential-bound GET-only
GitHub observer, and evaluates those immutable facts under one host-admin-pinned
release-readiness policy.

A positive ``release_ready`` result is evidence only. No tag, GitHub Release,
release, deploy or production authority is granted here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
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
from ._improvement_pilot_start_consumption_impl import _path_sha256
from . import improvement_pilot_exact_task_pr_lifecycle_authorization as lifecycle_auth_boundary
from . import improvement_pilot_exact_task_remote_publication_transaction as publication_tx_boundary
from . import improvement_pilot_exact_task_post_merge_attestation as post_merge_boundary
from .improvement_pilot_exact_task_post_merge_attestation import (
    PILOT_EXACT_TASK_POST_MERGE_ATTESTATION_AUTHORITY,
    PilotExactTaskPostMergeAttestationReceipt,
)
from .improvement_pilot_exact_task_remote_publication_transaction import (
    PilotExactTaskGitHubPublisherCredential,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_RELEASE_READINESS_EVALUATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-release-readiness-evaluation-receipt/v1"
)
PILOT_EXACT_TASK_RELEASE_READINESS_EVALUATION_AUTHORITY = (
    "host-evaluated-one-dc-l16-exact-release-readiness-only"
)
PILOT_EXACT_TASK_RELEASE_READINESS_EVALUATION_SCOPE = (
    "exact-post-merge-release-policy-evaluation-only-v1"
)
PILOT_EXACT_TASK_RELEASE_READINESS_POLICY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-release-readiness-policy/v1"
)

_MAX_FILE_BYTES = 1024 * 1024
_MAX_API_RESPONSE_BYTES = 2 * 1024 * 1024
_TIMEOUT_SECONDS = 30.0
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_GITHUB_API_ROOT = "https://api.github.com"
_BLOCKER_ORDER = (
    "base-branch-not-release-target",
    "merge-method-not-release-approved",
    "completion-source-not-release-approved",
    "merge-commit-not-current-base-head",
)
_POSIX_POLICY = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-pilot-exact-task-release-readiness-policy-v1.json"
)
_WINDOWS_POLICY = Path(
    r"C:\Program Files\ModelRig\DevControl\authority"
) / "rsi-pilot-exact-task-release-readiness-policy-v1.json"


class PilotExactTaskReleaseReadinessEvaluationError(ValueError):
    """Post-merge evidence or release-readiness policy is stale or unsafe."""


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
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "release-readiness evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskReleaseReadinessEvaluationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskReleaseReadinessEvaluationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskReleaseReadinessEvaluationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskReleaseReadinessEvaluationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _branch(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or value.strip() != value
        or _BRANCH.fullmatch(value) is None
        or value.endswith(("/", ".", ".lock"))
        or "@{" in value
        or "\\" in value
    ):
        raise PilotExactTaskReleaseReadinessEvaluationError(f"{name} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class PilotExactTaskReleaseReadinessPolicy:
    repository: str
    repository_id: str
    release_base_branch: str
    allowed_completion_sources: tuple[str, ...] = ("recovery", "transaction")
    required_merge_method: str = "squash"
    require_current_base_head: bool = True
    require_exact_authorized_parent: bool = True
    schema: str = PILOT_EXACT_TASK_RELEASE_READINESS_POLICY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_RELEASE_READINESS_POLICY_SCHEMA:
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release-readiness policy schema is unsupported"
            )
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release-readiness policy repository is invalid"
            )
        if not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None:
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release-readiness policy repository_id is invalid"
            )
        _branch(self.release_base_branch, name="release_base_branch")
        if (
            not isinstance(self.allowed_completion_sources, tuple)
            or not self.allowed_completion_sources
            or tuple(sorted(set(self.allowed_completion_sources)))
            != self.allowed_completion_sources
            or any(
                value not in {"transaction", "recovery"}
                for value in self.allowed_completion_sources
            )
        ):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release-readiness completion-source policy is invalid"
            )
        if self.required_merge_method != "squash":
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release-readiness policy must require squash merge"
            )
        if self.require_current_base_head is not True:
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release-readiness policy must require current base HEAD"
            )
        if self.require_exact_authorized_parent is not True:
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release-readiness policy must require exact authorized parent"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "repository_id": self.repository_id,
            "release_base_branch": self.release_base_branch,
            "allowed_completion_sources": list(self.allowed_completion_sources),
            "required_merge_method": self.required_merge_method,
            "require_current_base_head": self.require_current_base_head,
            "require_exact_authorized_parent": self.require_exact_authorized_parent,
            "schema": self.schema,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskReleaseReadinessPolicy":
        expected = {
            "repository",
            "repository_id",
            "release_base_branch",
            "allowed_completion_sources",
            "required_merge_method",
            "require_current_base_head",
            "require_exact_authorized_parent",
            "schema",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release-readiness policy fields mismatch"
            )
        sources = value.get("allowed_completion_sources")
        if not isinstance(sources, list):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release-readiness completion sources must be an array"
            )
        data = dict(value)
        data["allowed_completion_sources"] = tuple(sources)
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _parse_policy(payload: bytes) -> PilotExactTaskReleaseReadinessPolicy:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "release-readiness policy payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "release-readiness policy JSON is invalid"
        ) from exc
    policy = PilotExactTaskReleaseReadinessPolicy.from_mapping(raw)
    if policy.canonical_json().encode("utf-8") != payload:
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "release-readiness policy is not canonical JSON"
        )
    return policy


def _read_host_policy(path: Path) -> tuple[PilotExactTaskReleaseReadinessPolicy, str]:
    try:
        first = lifecycle_auth_boundary._read_host_authority_file(Path(path))
        second = lifecycle_auth_boundary._read_host_authority_file(Path(path))
    except Exception as exc:
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "release-readiness policy is not host-admin controlled"
        ) from exc
    if first != second:
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "release-readiness policy changed while being read"
        )
    policy = _parse_policy(second)
    return policy, hashlib.sha256(second).hexdigest()


def _require_live_post_merge(
    value: Any,
) -> PilotExactTaskPostMergeAttestationReceipt:
    if type(value) is not PilotExactTaskPostMergeAttestationReceipt:
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "exact live ADR-DC-062 post-merge attestation is required"
        )
    try:
        replayed = PilotExactTaskPostMergeAttestationReceipt.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "ADR-DC-062 replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "ADR-DC-062 identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_POST_MERGE_ATTESTATION_AUTHORITY
        or value.attestation_authenticated is not True
        or value.durable_completion_verified is not True
        or value.exact_remote_merge_verified is not True
        or value.exact_base_parent_verified is not True
        or value.double_observation_matched is not True
        or value.post_merge_verified is not True
        or value.merge_authorized is not False
        or value.remote_write_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "ADR-DC-063 requires one fresh read-only ADR-DC-062 attestation"
        )
    live = post_merge_boundary._get_live_post_merge_attestation_inputs(value)
    if (
        live is None
        or live.get("completion_source") != value.completion_source
        or live.get("completion_source_receipt_sha256")
        != value.completion_source_receipt_sha256
        or live.get("remote_observation_sha256") != value.remote_observation_sha256
    ):
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "ADR-DC-062 live provenance is unavailable"
        )
    return value


@dataclass(frozen=True, slots=True)
class _ReleaseReadinessRemoteState:
    repository: str
    repository_id: str
    base_branch: str
    current_base_sha: str
    head_branch: str
    head_sha: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_node_id_sha256: str
    merge_commit_sha: str
    merge_commit_parent_sha: str
    merged: bool
    draft: bool
    state: str
    maintainer_can_modify: bool

    def __post_init__(self) -> None:
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release observer repository is invalid"
            )
        if not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None:
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release observer repository_id is invalid"
            )
        _branch(self.base_branch, name="base_branch")
        _branch(self.head_branch, name="head_branch")
        for name in (
            "current_base_sha",
            "head_sha",
            "merge_commit_sha",
            "merge_commit_parent_sha",
        ):
            _hex40(getattr(self, name), name=name)
        _hex64(self.pull_request_node_id_sha256, name="pull_request_node_id_sha256")
        if (
            isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/{self.pull_request_number}"
            or self.merged is not True
            or self.draft is not False
            or self.state != "closed"
            or self.maintainer_can_modify is not False
        ):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release observer PR state is invalid"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict()).encode("utf-8")).hexdigest()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _GitHubReleaseReadinessObserver:
    """Credential-bound GET-only observer for exact post-merge release facts."""

    def __init__(
        self,
        *,
        credential: PilotExactTaskGitHubPublisherCredential,
        credential_config_sha256: str,
        credential_path: Path,
    ) -> None:
        if type(credential) is not PilotExactTaskGitHubPublisherCredential:
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "exact publisher credential is required"
            )
        self.credential = credential
        self.credential_config_sha256 = _hex64(
            credential_config_sha256, name="credential_config_sha256"
        )
        self.credential_path = Path(credential_path)
        if (
            not self.credential_path.is_absolute()
            or _has_linkish_component(self.credential_path)
        ):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "publisher credential path is unsafe"
            )
        self.credential_path_sha256 = _path_sha256(self.credential_path)
        self._opener = urllib.request.build_opener(_NoRedirect())

    @staticmethod
    def _repo_root(source: PilotExactTaskPostMergeAttestationReceipt) -> str:
        owner, repo = source.repository.split("/", 1)
        return (
            f"/repos/{urllib.parse.quote(owner, safe='')}/"
            f"{urllib.parse.quote(repo, safe='')}"
        )

    def _api_json(
        self,
        *,
        source: PilotExactTaskPostMergeAttestationReceipt,
        path: str,
    ) -> Any:
        root = self._repo_root(source)
        if (
            not isinstance(path, str)
            or not (path == root or path.startswith(root + "/"))
            or ".." in path
        ):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release-readiness GET is outside exact GitHub scope"
            )
        url = _GITHUB_API_ROOT + path
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.credential.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ModelRig-DevControl-ExactReleaseReadiness/1",
            },
        )
        try:
            response = self._opener.open(request, timeout=_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            raise PilotExactTaskReleaseReadinessEvaluationError(
                f"GitHub release-readiness GET failed with HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "GitHub release-readiness GET failed"
            ) from exc
        with response:
            if response.status != 200 or response.geturl() != url:
                raise PilotExactTaskReleaseReadinessEvaluationError(
                    "GitHub release-readiness response identity/status is unexpected"
                )
            raw = response.read(_MAX_API_RESPONSE_BYTES + 1)
        if not raw or len(raw) > _MAX_API_RESPONSE_BYTES:
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "GitHub release-readiness response size is invalid"
            )
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "GitHub release-readiness response is invalid JSON"
            ) from exc

    @staticmethod
    def _node_hash(value: Any) -> str:
        if not isinstance(value, str) or not value:
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "GitHub PR node identity is invalid"
            )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def observe(
        self, source: PilotExactTaskPostMergeAttestationReceipt
    ) -> _ReleaseReadinessRemoteState:
        if type(source) is not PilotExactTaskPostMergeAttestationReceipt:
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "exact post-merge source is required"
            )
        if (
            self.credential.repository != source.repository
            or self.credential.repository_id != source.repository_id
        ):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "publisher credential is not bound to exact release target"
            )
        root = self._repo_root(source)
        repo = self._api_json(source=source, path=root)
        if (
            not isinstance(repo, Mapping)
            or str(repo.get("id")) != source.repository_id
            or repo.get("full_name") != source.repository
        ):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "GitHub repository identity differs from post-merge source"
            )
        pull = self._api_json(
            source=source, path=f"{root}/pulls/{source.pull_request_number}"
        )
        if not isinstance(pull, Mapping):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "GitHub PR response is invalid"
            )
        head = pull.get("head")
        base = pull.get("base")
        if not isinstance(head, Mapping) or not isinstance(base, Mapping):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "GitHub PR head/base identity is invalid"
            )
        head_repo = head.get("repo")
        base_repo = base.get("repo")
        if not isinstance(head_repo, Mapping) or not isinstance(base_repo, Mapping):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "GitHub PR repository identity is invalid"
            )
        if (
            head.get("ref") != source.head_branch
            or head.get("sha") != source.head_sha
            or str(head_repo.get("id")) != source.repository_id
            or base.get("ref") != source.base_branch
            or str(base_repo.get("id")) != source.repository_id
            or pull.get("state") != "closed"
            or pull.get("draft") is not False
            or pull.get("merged_at") in {None, ""}
            or pull.get("merge_commit_sha") != source.merge_commit_sha
            or pull.get("maintainer_can_modify") is not False
            or self._node_hash(pull.get("node_id"))
            != source.pull_request_node_id_sha256
        ):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "GitHub PR no longer proves exact merged identity"
            )
        ref_name = urllib.parse.quote(source.base_branch, safe="")
        ref = self._api_json(
            source=source, path=f"{root}/git/ref/heads/{ref_name}"
        )
        ref_object = ref.get("object") if isinstance(ref, Mapping) else None
        if not isinstance(ref_object, Mapping):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "GitHub base ref response is invalid"
            )
        current_base_sha = _hex40(ref_object.get("sha"), name="current_base_sha")
        commit = self._api_json(
            source=source, path=f"{root}/git/commits/{source.merge_commit_sha}"
        )
        parents = commit.get("parents") if isinstance(commit, Mapping) else None
        if not isinstance(parents, list) or len(parents) != 1:
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "squash merge commit must have exactly one parent"
            )
        parent = parents[0]
        if not isinstance(parent, Mapping):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "squash merge parent is invalid"
            )
        parent_sha = _hex40(parent.get("sha"), name="merge_commit_parent_sha")
        return _ReleaseReadinessRemoteState(
            repository=source.repository,
            repository_id=source.repository_id,
            base_branch=source.base_branch,
            current_base_sha=current_base_sha,
            head_branch=source.head_branch,
            head_sha=source.head_sha,
            pull_request_number=source.pull_request_number,
            pull_request_api_url=source.pull_request_api_url,
            pull_request_node_id_sha256=source.pull_request_node_id_sha256,
            merge_commit_sha=source.merge_commit_sha,
            merge_commit_parent_sha=parent_sha,
            merged=True,
            draft=False,
            state="closed",
            maintainer_can_modify=False,
        )


def _normalize_remote_state(
    value: Any,
    source: PilotExactTaskPostMergeAttestationReceipt,
) -> _ReleaseReadinessRemoteState:
    if type(value) is not _ReleaseReadinessRemoteState:
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "release-readiness observer returned invalid state"
        )
    if (
        value.repository != source.repository
        or value.repository_id != source.repository_id
        or value.base_branch != source.base_branch
        or value.head_branch != source.head_branch
        or value.head_sha != source.head_sha
        or value.pull_request_number != source.pull_request_number
        or value.pull_request_api_url != source.pull_request_api_url
        or value.pull_request_node_id_sha256 != source.pull_request_node_id_sha256
        or value.merge_commit_sha != source.merge_commit_sha
        or value.merge_commit_parent_sha != source.authorized_base_sha
        or value.merged is not True
        or value.draft is not False
        or value.state != "closed"
        or value.maintainer_can_modify is not False
    ):
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "fresh GitHub state is not the exact attested squash merge"
        )
    return value


def _blockers(
    *,
    source: PilotExactTaskPostMergeAttestationReceipt,
    policy: PilotExactTaskReleaseReadinessPolicy,
    remote: _ReleaseReadinessRemoteState,
) -> tuple[str, ...]:
    result: list[str] = []
    if source.base_branch != policy.release_base_branch:
        result.append("base-branch-not-release-target")
    if source.merge_method != policy.required_merge_method:
        result.append("merge-method-not-release-approved")
    if source.completion_source not in policy.allowed_completion_sources:
        result.append("completion-source-not-release-approved")
    if remote.current_base_sha != source.merge_commit_sha:
        result.append("merge-commit-not-current-base-head")
    return tuple(code for code in _BLOCKER_ORDER if code in result)


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
        receipt: Any,
        *,
        source: PilotExactTaskPostMergeAttestationReceipt,
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
            or source.sha256 != receipt.post_merge_attestation_sha256
            or receipt.release_readiness_policy_sha256 != policy_sha
            or receipt.remote_observation_sha256 != observation_sha
        ):
            return None
        return MappingProxyType(
            {
                "post_merge_attestation": source,
                "release_readiness_policy_sha256": policy_sha,
                "remote_observation_sha256": observation_sha,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_release_readiness_evaluation_authenticated,
    _get_live_release_readiness_evaluation_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskReleaseReadinessEvaluationReceipt:
    post_merge_attestation_sha256: str
    completion_source_receipt_sha256: str
    merge_authorization_sha256: str
    merge_readiness_evaluation_sha256: str
    merge_readiness_policy_sha256: str
    merge_config_sha256: str
    release_readiness_policy_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    transaction_lock_sha256: str
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    remote_observation_sha256: str
    repository: str
    repository_id: str
    base_branch: str
    release_base_branch: str
    authorized_base_sha: str
    current_base_sha: str
    head_branch: str
    head_sha: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_node_id_sha256: str
    merge_method: str
    merge_commit_sha: str
    completion_source: str
    allowed_completion_sources: tuple[str, ...]
    blocker_codes: tuple[str, ...]
    post_merge_attested_at_utc: str
    evaluated_at_utc: str
    post_merge_attestation_authenticated: bool = True
    release_readiness_policy_host_pinned: bool = True
    exact_merge_revalidated: bool = True
    exact_authorized_parent_satisfied: bool = True
    double_observation_matched: bool = True
    base_branch_policy_satisfied: bool = False
    merge_method_policy_satisfied: bool = False
    completion_source_policy_satisfied: bool = False
    current_base_head_satisfied: bool = False
    release_readiness_evaluated: bool = True
    release_ready: bool = False
    release_readiness_authorized: bool = False
    merge_authorized: bool = False
    remote_write_authorized: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    ready_for_review_authorized: bool = False
    reviewer_request_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    product_pilot_started: bool = False
    nonce_reusable: bool = False
    evaluation_scope: str = PILOT_EXACT_TASK_RELEASE_READINESS_EVALUATION_SCOPE
    authority: str = PILOT_EXACT_TASK_RELEASE_READINESS_EVALUATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_RELEASE_READINESS_EVALUATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_RELEASE_READINESS_EVALUATION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_RELEASE_READINESS_EVALUATION_AUTHORITY
            or self.evaluation_scope
            != PILOT_EXACT_TASK_RELEASE_READINESS_EVALUATION_SCOPE
        ):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release-readiness evaluation identity is unsupported"
            )
        for name in (
            "post_merge_attestation_sha256",
            "completion_source_receipt_sha256",
            "merge_authorization_sha256",
            "merge_readiness_evaluation_sha256",
            "merge_readiness_policy_sha256",
            "merge_config_sha256",
            "release_readiness_policy_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
            "transaction_lock_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "remote_observation_sha256",
            "pull_request_node_id_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("authorized_base_sha", "current_base_sha", "head_sha", "merge_commit_sha"):
            _hex40(getattr(self, name), name=name)
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release-readiness repository identity is invalid"
            )
        _branch(self.base_branch, name="base_branch")
        _branch(self.release_base_branch, name="release_base_branch")
        _branch(self.head_branch, name="head_branch")
        if (
            isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/{self.pull_request_number}"
            or self.merge_method != "squash"
            or self.completion_source not in {"transaction", "recovery"}
        ):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release-readiness target identity is invalid"
            )
        if (
            not isinstance(self.allowed_completion_sources, tuple)
            or not self.allowed_completion_sources
            or tuple(sorted(set(self.allowed_completion_sources)))
            != self.allowed_completion_sources
            or any(
                value not in {"transaction", "recovery"}
                for value in self.allowed_completion_sources
            )
        ):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release-readiness policy projection is invalid"
            )
        criteria = (
            self.base_branch_policy_satisfied,
            self.merge_method_policy_satisfied,
            self.completion_source_policy_satisfied,
            self.current_base_head_satisfied,
            self.exact_authorized_parent_satisfied,
        )
        if any(not isinstance(value, bool) for value in criteria):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release-readiness criteria flags are invalid"
            )
        if self.base_branch_policy_satisfied != (
            self.base_branch == self.release_base_branch
        ):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release base-branch criterion is inconsistent"
            )
        if self.merge_method_policy_satisfied != (self.merge_method == "squash"):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release merge-method criterion is inconsistent"
            )
        if self.completion_source_policy_satisfied != (
            self.completion_source in self.allowed_completion_sources
        ):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release completion-source criterion is inconsistent"
            )
        if self.current_base_head_satisfied != (
            self.current_base_sha == self.merge_commit_sha
        ):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release current-base criterion is inconsistent"
            )
        if self.exact_authorized_parent_satisfied is not True:
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release exact-parent criterion must be satisfied"
            )
        expected_blockers: list[str] = []
        if not self.base_branch_policy_satisfied:
            expected_blockers.append(_BLOCKER_ORDER[0])
        if not self.merge_method_policy_satisfied:
            expected_blockers.append(_BLOCKER_ORDER[1])
        if not self.completion_source_policy_satisfied:
            expected_blockers.append(_BLOCKER_ORDER[2])
        if not self.current_base_head_satisfied:
            expected_blockers.append(_BLOCKER_ORDER[3])
        if tuple(expected_blockers) != self.blocker_codes:
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release-readiness blocker set is inconsistent"
            )
        if self.release_ready != all(criteria) or self.release_ready != (not self.blocker_codes):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release_ready does not equal evaluated criteria"
            )
        source_time = _utc(
            self.post_merge_attested_at_utc, name="post_merge_attested_at_utc"
        )
        evaluated = _utc(self.evaluated_at_utc, name="evaluated_at_utc")
        if evaluated < source_time:
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release-readiness evaluation predates post-merge attestation"
            )
        required_true = (
            "post_merge_attestation_authenticated",
            "release_readiness_policy_host_pinned",
            "exact_merge_revalidated",
            "exact_authorized_parent_satisfied",
            "double_observation_matched",
            "release_readiness_evaluated",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release-readiness evidence is incomplete"
            )
        forced_false = (
            "release_readiness_authorized",
            "merge_authorized",
            "remote_write_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "ready_for_review_authorized",
            "reviewer_request_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "product_pilot_started",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release-readiness evaluation retains forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def evaluation_authenticated(self) -> bool:
        return _get_live_release_readiness_evaluation_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }
        result["allowed_completion_sources"] = list(self.allowed_completion_sources)
        result["blocker_codes"] = list(self.blocker_codes)
        return result

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskReleaseReadinessEvaluationReceipt":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):  # type: ignore[attr-defined]
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release-readiness evaluation fields mismatch"
            )
        sources = value.get("allowed_completion_sources")
        blockers = value.get("blocker_codes")
        if not isinstance(sources, list) or not isinstance(blockers, list):
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release-readiness list fields are invalid"
            )
        data = dict(value)
        data["allowed_completion_sources"] = tuple(sources)
        data["blocker_codes"] = tuple(blockers)
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _evaluate_verified_pilot_exact_task_release_readiness(
    *,
    post_merge_attestation: PilotExactTaskPostMergeAttestationReceipt,
    policy: PilotExactTaskReleaseReadinessPolicy,
    policy_sha256: str,
    transport: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskReleaseReadinessEvaluationReceipt:
    source = _require_live_post_merge(post_merge_attestation)
    if type(policy) is not PilotExactTaskReleaseReadinessPolicy:
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "exact host release-readiness policy is required"
        )
    supplied_policy_sha = _hex64(
        policy_sha256, name="release_readiness_policy_sha256"
    )
    if policy.sha256 != supplied_policy_sha:
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "release-readiness policy digest mismatch"
        )
    if policy.repository != source.repository or policy.repository_id != source.repository_id:
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "release-readiness policy is not bound to exact repository"
        )
    if transport is None or not callable(getattr(transport, "observe", None)):
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "read-only release-readiness GitHub observer is required"
        )
    if (
        getattr(transport, "credential_config_sha256", None)
        != source.publisher_credential_config_sha256
        or getattr(transport, "credential_path_sha256", None)
        != source.publisher_credential_path_sha256
    ):
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "release-readiness observer credential identity differs from ADR-DC-060 lock"
        )
    try:
        first = _normalize_remote_state(transport.observe(source), source)
        second = _normalize_remote_state(transport.observe(source), source)
    except PilotExactTaskReleaseReadinessEvaluationError:
        raise
    except Exception as exc:
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "release-readiness GitHub observation failed"
        ) from exc
    if first != second:
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "GitHub release-readiness state changed between observations"
        )
    observation_sha = first.sha256
    blockers = _blockers(source=source, policy=policy, remote=first)
    base_ok = source.base_branch == policy.release_base_branch
    method_ok = source.merge_method == policy.required_merge_method
    completion_ok = source.completion_source in policy.allowed_completion_sources
    head_ok = first.current_base_sha == source.merge_commit_sha
    evaluated_at = now_provider()
    if _utc(evaluated_at, name="evaluated_at_utc") < _utc(
        source.attested_at_utc, name="post_merge_attested_at_utc"
    ):
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "system clock moved backwards after ADR-DC-062"
        )
    receipt = PilotExactTaskReleaseReadinessEvaluationReceipt(
        post_merge_attestation_sha256=source.sha256,
        completion_source_receipt_sha256=source.completion_source_receipt_sha256,
        merge_authorization_sha256=source.merge_authorization_sha256,
        merge_readiness_evaluation_sha256=source.merge_readiness_evaluation_sha256,
        merge_readiness_policy_sha256=source.merge_readiness_policy_sha256,
        merge_config_sha256=source.merge_config_sha256,
        release_readiness_policy_sha256=supplied_policy_sha,
        execution_nonce_sha256=source.execution_nonce_sha256,
        development_task_sha256=source.development_task_sha256,
        candidate_patch_sha256=source.candidate_patch_sha256,
        pr_intent_sha256=source.pr_intent_sha256,
        transaction_lock_sha256=source.transaction_lock_sha256,
        publisher_credential_config_sha256=source.publisher_credential_config_sha256,
        publisher_credential_path_sha256=source.publisher_credential_path_sha256,
        remote_observation_sha256=observation_sha,
        repository=source.repository,
        repository_id=source.repository_id,
        base_branch=source.base_branch,
        release_base_branch=policy.release_base_branch,
        authorized_base_sha=source.authorized_base_sha,
        current_base_sha=first.current_base_sha,
        head_branch=source.head_branch,
        head_sha=source.head_sha,
        pull_request_number=source.pull_request_number,
        pull_request_api_url=source.pull_request_api_url,
        pull_request_node_id_sha256=source.pull_request_node_id_sha256,
        merge_method=source.merge_method,
        merge_commit_sha=source.merge_commit_sha,
        completion_source=source.completion_source,
        allowed_completion_sources=policy.allowed_completion_sources,
        blocker_codes=blockers,
        post_merge_attested_at_utc=source.attested_at_utc,
        evaluated_at_utc=evaluated_at,
        base_branch_policy_satisfied=base_ok,
        merge_method_policy_satisfied=method_ok,
        completion_source_policy_satisfied=completion_ok,
        current_base_head_satisfied=head_ok,
        release_ready=not blockers,
    )
    _mark_release_readiness_evaluation_authenticated(
        receipt,
        source=source,
        policy_sha256=supplied_policy_sha,
        observation_sha256=observation_sha,
    )
    if receipt.evaluation_authenticated is not True:
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "release-readiness evaluation lost live provenance"
        )
    return receipt


def _canonical_policy() -> tuple[PilotExactTaskReleaseReadinessPolicy, str]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_POLICY
        elif os.name == "nt":
            path = _WINDOWS_POLICY
        else:
            raise PilotExactTaskReleaseReadinessEvaluationError(
                "release-readiness policy platform is unsupported"
            )
        return _read_host_policy(path)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "release-readiness policy requires an elevated host operator"
        ) from exc


def evaluate_pilot_exact_task_release_readiness(
    post_merge_attestation: PilotExactTaskPostMergeAttestationReceipt,
) -> PilotExactTaskReleaseReadinessEvaluationReceipt:
    """Evaluate one fresh exact merge under the fixed host release policy."""
    try:
        policy, digest = _canonical_policy()
        credential, credential_digest, credential_path = (
            publication_tx_boundary._canonical_credential()
        )
        transport = _GitHubReleaseReadinessObserver(
            credential=credential,
            credential_config_sha256=credential_digest,
            credential_path=credential_path,
        )
        return _evaluate_verified_pilot_exact_task_release_readiness(
            post_merge_attestation=post_merge_attestation,
            policy=policy,
            policy_sha256=digest,
            transport=transport,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskReleaseReadinessEvaluationError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskReleaseReadinessEvaluationError(
            "exact release-readiness evaluation failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_RELEASE_READINESS_EVALUATION_SCHEMA",
    "PILOT_EXACT_TASK_RELEASE_READINESS_EVALUATION_AUTHORITY",
    "PILOT_EXACT_TASK_RELEASE_READINESS_EVALUATION_SCOPE",
    "PILOT_EXACT_TASK_RELEASE_READINESS_POLICY_SCHEMA",
    "PilotExactTaskReleaseReadinessEvaluationError",
    "PilotExactTaskReleaseReadinessPolicy",
    "PilotExactTaskReleaseReadinessEvaluationReceipt",
    "evaluate_pilot_exact_task_release_readiness",
]
