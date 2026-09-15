"""ADR-DC-060 one-shot exact GitHub squash-merge transaction.

This boundary accepts only one live ADR-DC-059 merge authorization. It fresh-
revalidates exact review state and merge readiness before and after a durable
transaction lock, then performs exactly one SHA-pinned squash merge.

No release, deploy or production authority follows. Partial states are durable:
lock-only means execution is ambiguous/pre-merge; a merged marker means GitHub
returned a successful merge and post-merge verification may need recovery.
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
    _require_host_controlled_ledger_root,
)
from ._improvement_pilot_start_consumption_impl import _path_sha256, _safe_ledger_root
from .durable_publication import DurablePublicationError, create_once_file
from . import improvement_pilot_exact_task_merge_authorization as auth_boundary
from . import improvement_pilot_exact_task_merge_readiness_evaluation as readiness_boundary
from . import improvement_pilot_exact_task_review_state_attestation as review_boundary
from . import improvement_pilot_exact_task_remote_publication_transaction as publication_tx_boundary
from .improvement_pilot_exact_task_merge_authorization import (
    PILOT_EXACT_TASK_MERGE_AUTHORIZATION_AUTHORITY,
    PilotExactTaskMergeAuthorizationReceipt,
)
from .improvement_pilot_exact_task_merge_readiness_evaluation import (
    PilotExactTaskMergeReadinessEvaluationReceipt,
)
from .improvement_pilot_exact_task_remote_publication_transaction import (
    PilotExactTaskGitHubPublisherCredential,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_MERGE_TRANSACTION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-merge-transaction-receipt/v1"
)
PILOT_EXACT_TASK_MERGE_TRANSACTION_AUTHORITY = (
    "host-executed-one-dc-l16-exact-pr-squash-merge-only"
)
PILOT_EXACT_TASK_MERGE_TRANSACTION_SCOPE = "one-shot-exact-squash-merge-transaction-v1"
PILOT_EXACT_TASK_MERGE_TRANSACTION_LEDGER_SCOPE = "canonical-host-local-v1"

_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
_MAX_API_RESPONSE_BYTES = 2 * 1024 * 1024
_TIMEOUT_SECONDS = 30.0
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_GITHUB_API_ROOT = "https://api.github.com"
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/rsi-pilot-exact-task-merge-transaction-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-merge-transaction-ledger-v1"
)


class PilotExactTaskMergeTransactionError(ValueError):
    """Exact merge transaction is stale, replayed, ambiguous or over-broad."""


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
        raise PilotExactTaskMergeTransactionError(
            "merge transaction evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskMergeTransactionError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskMergeTransactionError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskMergeTransactionError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskMergeTransactionError(f"{name} is invalid") from exc


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
        raise PilotExactTaskMergeTransactionError(f"{name} is invalid")
    return value


def _read_bound(path: Path) -> bytes | None:
    candidate = Path(path)
    if not candidate.is_absolute() or _has_linkish_component(candidate):
        return None
    try:
        payload = candidate.read_bytes()
    except OSError:
        return None
    if not payload or len(payload) > _MAX_ARTIFACT_BYTES:
        return None
    return payload


@dataclass(frozen=True, slots=True)
class _PreMergeRemoteState:
    repository: str
    repository_id: str
    base_branch: str
    base_sha: str
    head_branch: str
    head_sha: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_node_id_sha256: str
    state: str
    draft: bool
    merged: bool
    maintainer_can_modify: bool
    mergeable: bool
    mergeable_state: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskMergeTransactionError(
                "pre-merge repository identity is invalid"
            )
        _branch(self.base_branch, name="pre-merge base branch")
        _branch(self.head_branch, name="pre-merge head branch")
        _hex40(self.base_sha, name="pre-merge base SHA")
        _hex40(self.head_sha, name="pre-merge head SHA")
        _hex64(self.pull_request_node_id_sha256, name="pre-merge PR node hash")
        if (
            isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/{self.pull_request_number}"
        ):
            raise PilotExactTaskMergeTransactionError(
                "pre-merge pull-request identity is invalid"
            )
        if (
            self.state != "open"
            or self.draft is not False
            or self.merged is not False
            or self.maintainer_can_modify is not False
            or self.mergeable is not True
            or self.mergeable_state != "clean"
        ):
            raise PilotExactTaskMergeTransactionError(
                "pre-merge pull request is not exact clean mergeable state"
            )

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict()).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class _PostMergeRemoteState:
    repository: str
    repository_id: str
    base_branch: str
    base_ref_sha: str
    head_branch: str
    head_sha: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_node_id_sha256: str
    state: str
    draft: bool
    merged: bool
    merge_commit_sha: str
    merge_commit_parent_sha: str
    maintainer_can_modify: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskMergeTransactionError(
                "post-merge repository identity is invalid"
            )
        _branch(self.base_branch, name="post-merge base branch")
        _branch(self.head_branch, name="post-merge head branch")
        for name in ("base_ref_sha", "head_sha", "merge_commit_sha", "merge_commit_parent_sha"):
            _hex40(getattr(self, name), name=name)
        _hex64(self.pull_request_node_id_sha256, name="post-merge PR node hash")
        if (
            isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/{self.pull_request_number}"
        ):
            raise PilotExactTaskMergeTransactionError(
                "post-merge pull-request identity is invalid"
            )
        if (
            self.state != "closed"
            or self.draft is not False
            or self.merged is not True
            or self.maintainer_can_modify is not False
            or self.base_ref_sha != self.merge_commit_sha
        ):
            raise PilotExactTaskMergeTransactionError(
                "post-merge pull request is not exact completed state"
            )

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict()).encode("utf-8")).hexdigest()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class _GitHubExactMergeTransport:
    """Narrow GitHub transport: authenticated GET plus one exact merge PUT."""

    def __init__(
        self,
        *,
        credential: PilotExactTaskGitHubPublisherCredential,
        credential_config_sha256: str,
        credential_path: Path,
    ) -> None:
        if type(credential) is not PilotExactTaskGitHubPublisherCredential:
            raise PilotExactTaskMergeTransactionError("exact publisher credential is required")
        self.credential = credential
        self.credential_id = credential.credential_id
        self.credential_config_sha256 = _hex64(
            credential_config_sha256, name="publisher credential config digest"
        )
        self.credential_path = Path(credential_path)
        if not self.credential_path.is_absolute() or _has_linkish_component(self.credential_path):
            raise PilotExactTaskMergeTransactionError("publisher credential path identity is unsafe")
        self.credential_path_sha256 = _path_sha256(self.credential_path)
        self._opener = urllib.request.build_opener(_NoRedirect())

    @staticmethod
    def _repo_root(authorization: PilotExactTaskMergeAuthorizationReceipt) -> str:
        owner, repo = authorization.repository.split("/", 1)
        return f"/repos/{urllib.parse.quote(owner, safe='')}/{urllib.parse.quote(repo, safe='')}"

    def validate_for(self, authorization: PilotExactTaskMergeAuthorizationReceipt) -> None:
        if (
            type(authorization) is not PilotExactTaskMergeAuthorizationReceipt
            or self.credential.repository != authorization.repository
            or self.credential.repository_id != authorization.repository_id
        ):
            raise PilotExactTaskMergeTransactionError("publisher credential is not bound to exact merge target")

    def _api_json(
        self,
        *,
        authorization: PilotExactTaskMergeAuthorizationReceipt,
        path: str,
        method: str,
        body: Mapping[str, Any] | None = None,
    ) -> Any:
        root = self._repo_root(authorization)
        exact_merge = f"{root}/pulls/{authorization.pull_request_number}/merge"
        if (
            not isinstance(path, str)
            or not (path == root or path.startswith(root + "/"))
            or ".." in path
            or method not in {"GET", "PUT"}
            or (method == "PUT" and path != exact_merge)
        ):
            raise PilotExactTaskMergeTransactionError("merge API request is outside exact GitHub scope")
        payload = None
        if method == "PUT":
            if not isinstance(body, Mapping):
                raise PilotExactTaskMergeTransactionError("merge PUT body is missing")
            exact_body = {"sha": authorization.head_sha, "merge_method": "squash"}
            if dict(body) != exact_body:
                raise PilotExactTaskMergeTransactionError("merge PUT body is not exact authorized merge")
            payload = _canonical(exact_body).encode("utf-8")
        elif body is not None:
            raise PilotExactTaskMergeTransactionError("merge GET cannot carry a body")
        url = _GITHUB_API_ROOT + path
        request = urllib.request.Request(
            url,
            data=payload,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.credential.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ModelRig-DevControl-ExactMerge/1",
                **({"Content-Type": "application/json"} if payload is not None else {}),
            },
        )
        try:
            response = self._opener.open(request, timeout=_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            raise PilotExactTaskMergeTransactionError(f"GitHub merge request failed with HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PilotExactTaskMergeTransactionError("GitHub merge request failed") from exc
        with response:
            if response.status != 200 or response.geturl() != url:
                raise PilotExactTaskMergeTransactionError("GitHub merge response identity/status is unexpected")
            raw = response.read(_MAX_API_RESPONSE_BYTES + 1)
        if not raw or len(raw) > _MAX_API_RESPONSE_BYTES:
            raise PilotExactTaskMergeTransactionError("GitHub merge response size is invalid")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PilotExactTaskMergeTransactionError("GitHub merge response is invalid JSON") from exc

    def _repository(self, authorization: PilotExactTaskMergeAuthorizationReceipt) -> None:
        value = self._api_json(authorization=authorization, path=self._repo_root(authorization), method="GET")
        if (
            not isinstance(value, Mapping)
            or str(value.get("id")) != authorization.repository_id
            or value.get("full_name") != authorization.repository
        ):
            raise PilotExactTaskMergeTransactionError("GitHub repository identity no longer matches merge authority")

    def _pull(self, authorization: PilotExactTaskMergeAuthorizationReceipt) -> Mapping[str, Any]:
        value = self._api_json(
            authorization=authorization,
            path=f"{self._repo_root(authorization)}/pulls/{authorization.pull_request_number}",
            method="GET",
        )
        if not isinstance(value, Mapping):
            raise PilotExactTaskMergeTransactionError("GitHub pull-request response is invalid")
        return value

    def _ref(self, authorization: PilotExactTaskMergeAuthorizationReceipt, branch: str) -> str:
        branch_q = urllib.parse.quote(_branch(branch, name="merge ref branch"), safe="")
        value = self._api_json(
            authorization=authorization,
            path=f"{self._repo_root(authorization)}/git/ref/heads/{branch_q}",
            method="GET",
        )
        obj = value.get("object") if isinstance(value, Mapping) else None
        if not isinstance(obj, Mapping) or obj.get("type") != "commit":
            raise PilotExactTaskMergeTransactionError("GitHub branch ref does not resolve to one commit")
        return _hex40(obj.get("sha"), name="GitHub ref SHA")

    def _commit_parent(self, authorization: PilotExactTaskMergeAuthorizationReceipt, merge_commit_sha: str) -> str:
        sha = _hex40(merge_commit_sha, name="merge commit SHA")
        value = self._api_json(
            authorization=authorization,
            path=f"{self._repo_root(authorization)}/commits/{sha}",
            method="GET",
        )
        parents = value.get("parents") if isinstance(value, Mapping) else None
        if not isinstance(parents, list) or len(parents) != 1:
            raise PilotExactTaskMergeTransactionError("squash merge commit does not have exactly one parent")
        parent = parents[0]
        if not isinstance(parent, Mapping):
            raise PilotExactTaskMergeTransactionError("squash merge parent is invalid")
        return _hex40(parent.get("sha"), name="squash merge parent SHA")

    @staticmethod
    def _node_hash(value: Any) -> str:
        if not isinstance(value, str) or not value:
            raise PilotExactTaskMergeTransactionError("GitHub pull-request node identity is invalid")
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _head_base(value: Mapping[str, Any], *, side: str) -> tuple[str, str, str]:
        item = value.get(side)
        if not isinstance(item, Mapping):
            raise PilotExactTaskMergeTransactionError(f"GitHub PR {side} identity is invalid")
        repo = item.get("repo")
        if not isinstance(repo, Mapping):
            raise PilotExactTaskMergeTransactionError(f"GitHub PR {side} repository identity is invalid")
        return (
            _branch(item.get("ref"), name=f"GitHub PR {side} branch"),
            _hex40(item.get("sha"), name=f"GitHub PR {side} SHA"),
            str(repo.get("id")),
        )

    def observe_pre(self, authorization: PilotExactTaskMergeAuthorizationReceipt) -> _PreMergeRemoteState:
        self.validate_for(authorization)
        self._repository(authorization)
        pr = self._pull(authorization)
        head_branch, head_sha, head_repo_id = self._head_base(pr, side="head")
        base_branch, _pr_base_sha, base_repo_id = self._head_base(pr, side="base")
        state = _PreMergeRemoteState(
            repository=authorization.repository,
            repository_id=authorization.repository_id,
            base_branch=base_branch,
            base_sha=self._ref(authorization, authorization.base_branch),
            head_branch=head_branch,
            head_sha=head_sha,
            pull_request_number=authorization.pull_request_number,
            pull_request_api_url=authorization.pull_request_api_url,
            pull_request_node_id_sha256=self._node_hash(pr.get("node_id")),
            state=pr.get("state"),
            draft=pr.get("draft"),
            merged=pr.get("merged"),
            maintainer_can_modify=pr.get("maintainer_can_modify"),
            mergeable=pr.get("mergeable"),
            mergeable_state=pr.get("mergeable_state"),
        )
        if (
            head_repo_id != authorization.repository_id
            or base_repo_id != authorization.repository_id
            or state.base_branch != authorization.base_branch
            or state.base_sha != authorization.base_sha
            or state.head_branch != authorization.head_branch
            or state.head_sha != authorization.head_sha
            or state.pull_request_node_id_sha256 != authorization.pull_request_node_id_sha256
        ):
            raise PilotExactTaskMergeTransactionError("pre-merge GitHub state differs from exact merge authority")
        return state

    def merge(self, authorization: PilotExactTaskMergeAuthorizationReceipt) -> tuple[str, str]:
        value = self._api_json(
            authorization=authorization,
            path=f"{self._repo_root(authorization)}/pulls/{authorization.pull_request_number}/merge",
            method="PUT",
            body={"sha": authorization.head_sha, "merge_method": "squash"},
        )
        if (
            not isinstance(value, Mapping)
            or value.get("merged") is not True
            or not isinstance(value.get("message"), str)
            or not value.get("message")
        ):
            raise PilotExactTaskMergeTransactionError("GitHub did not confirm exact merge")
        sha = _hex40(value.get("sha"), name="GitHub merge commit SHA")
        response = {"sha": sha, "merged": True, "message": value["message"]}
        return sha, hashlib.sha256(_canonical(response).encode("utf-8")).hexdigest()

    def observe_post(
        self,
        authorization: PilotExactTaskMergeAuthorizationReceipt,
        merge_commit_sha: str,
    ) -> _PostMergeRemoteState:
        self.validate_for(authorization)
        self._repository(authorization)
        pr = self._pull(authorization)
        head_branch, head_sha, head_repo_id = self._head_base(pr, side="head")
        base_branch, _pr_base_sha, base_repo_id = self._head_base(pr, side="base")
        merge_sha = _hex40(merge_commit_sha, name="merge commit SHA")
        state = _PostMergeRemoteState(
            repository=authorization.repository,
            repository_id=authorization.repository_id,
            base_branch=base_branch,
            base_ref_sha=self._ref(authorization, authorization.base_branch),
            head_branch=head_branch,
            head_sha=head_sha,
            pull_request_number=authorization.pull_request_number,
            pull_request_api_url=authorization.pull_request_api_url,
            pull_request_node_id_sha256=self._node_hash(pr.get("node_id")),
            state=pr.get("state"),
            draft=pr.get("draft"),
            merged=pr.get("merged"),
            merge_commit_sha=_hex40(pr.get("merge_commit_sha"), name="GitHub PR merge commit SHA"),
            merge_commit_parent_sha=self._commit_parent(authorization, merge_sha),
            maintainer_can_modify=pr.get("maintainer_can_modify"),
        )
        if (
            head_repo_id != authorization.repository_id
            or base_repo_id != authorization.repository_id
            or state.base_branch != authorization.base_branch
            or state.head_branch != authorization.head_branch
            or state.head_sha != authorization.head_sha
            or state.pull_request_node_id_sha256 != authorization.pull_request_node_id_sha256
            or state.merge_commit_sha != merge_sha
            or state.base_ref_sha != merge_sha
            or state.merge_commit_parent_sha != authorization.base_sha
        ):
            raise PilotExactTaskMergeTransactionError("post-merge GitHub state differs from exact authorized squash merge")
        return state


def _require_live_authorization(
    value: Any,
) -> tuple[PilotExactTaskMergeAuthorizationReceipt, PilotExactTaskMergeReadinessEvaluationReceipt]:
    if type(value) is not PilotExactTaskMergeAuthorizationReceipt:
        raise PilotExactTaskMergeTransactionError("exact live ADR-DC-059 merge authorization is required")
    try:
        replayed = PilotExactTaskMergeAuthorizationReceipt.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskMergeTransactionError("ADR-DC-059 authorization replay validation failed") from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskMergeTransactionError("ADR-DC-059 authorization identity mismatch")
    if (
        value.authority != PILOT_EXACT_TASK_MERGE_AUTHORIZATION_AUTHORITY
        or value.authorization_authenticated is not True
        or value.host_merge_guard_committed is not True
        or value.merge_readiness_evaluation_authenticated is not True
        or value.merge_ready is not True
        or value.merge_config_host_pinned is not True
        or value.dual_external_ed25519_authorized is not True
        or value.merge_authorized is not True
        or value.remote_write_authorized is not True
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskMergeTransactionError("transaction requires one live unused ADR-DC-059 merge authority")
    inputs = auth_boundary._get_live_merge_authorization_inputs(value)
    if inputs is None:
        raise PilotExactTaskMergeTransactionError("ADR-DC-059 live authorization inputs are unavailable")
    evaluation = inputs.get("merge_readiness_evaluation")
    if (
        type(evaluation) is not PilotExactTaskMergeReadinessEvaluationReceipt
        or evaluation.evaluation_authenticated is not True
        or evaluation.sha256 != value.merge_readiness_evaluation_sha256
        or evaluation.merge_ready is not True
    ):
        raise PilotExactTaskMergeTransactionError("ADR-DC-059 is not bound to exact live merge-ready evaluation")
    return value, evaluation


def _require_fresh_ready(
    authorization: PilotExactTaskMergeAuthorizationReceipt,
    fresh: Any,
) -> PilotExactTaskMergeReadinessEvaluationReceipt:
    if (
        type(fresh) is not PilotExactTaskMergeReadinessEvaluationReceipt
        or fresh.evaluation_authenticated is not True
        or fresh.merge_ready is not True
        or fresh.blocker_codes != ()
        or fresh.merge_readiness_policy_sha256 != authorization.merge_readiness_policy_sha256
        or fresh.execution_nonce_sha256 != authorization.execution_nonce_sha256
        or fresh.development_task_sha256 != authorization.development_task_sha256
        or fresh.candidate_patch_sha256 != authorization.candidate_patch_sha256
        or fresh.pr_intent_sha256 != authorization.pr_intent_sha256
        or fresh.repository != authorization.repository
        or fresh.repository_id != authorization.repository_id
        or fresh.base_branch != authorization.base_branch
        or fresh.exact_task_base_sha != authorization.base_sha
        or fresh.head_branch != authorization.head_branch
        or fresh.predicted_commit_sha != authorization.head_sha
        or fresh.pull_request_number != authorization.pull_request_number
        or fresh.pull_request_api_url != authorization.pull_request_api_url
        or fresh.pull_request_node_id_sha256 != authorization.pull_request_node_id_sha256
        or fresh.merge_readiness_evaluated is not True
        or fresh.merge_authorized is not False
        or fresh.remote_write_authorized is not False
    ):
        raise PilotExactTaskMergeTransactionError("fresh merge-readiness state no longer equals ADR-DC-059 authority")
    return fresh


def _canonical_fresh_revalidate(
    authorization: PilotExactTaskMergeAuthorizationReceipt,
) -> PilotExactTaskMergeReadinessEvaluationReceipt:
    _authorization, evaluation = _require_live_authorization(authorization)
    live = readiness_boundary._get_live_merge_readiness_evaluation_inputs(evaluation)
    review_state = live.get("review_state_attestation") if isinstance(live, Mapping) else None
    if review_state is None:
        raise PilotExactTaskMergeTransactionError("ADR-DC-058 live review-state source is unavailable")
    review_live = review_boundary._get_live_review_state_attestation_inputs(review_state)
    post_lifecycle = review_live.get("post_lifecycle_attestation") if isinstance(review_live, Mapping) else None
    if post_lifecycle is None:
        raise PilotExactTaskMergeTransactionError("ADR-DC-057 live post-lifecycle source is unavailable")
    fresh_review = review_boundary.attest_pilot_exact_task_review_state(post_lifecycle)
    fresh = readiness_boundary.evaluate_pilot_exact_task_merge_readiness(fresh_review)
    return _require_fresh_ready(authorization, fresh)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskMergeTransactionReceipt:
    transaction_ledger_root_path_sha256: str
    transaction_key_sha256: str
    merge_authorization_sha256: str
    merge_readiness_evaluation_sha256: str
    merge_readiness_policy_sha256: str
    merge_config_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    repository: str
    repository_id: str
    base_branch: str
    authorized_base_sha: str
    head_branch: str
    head_sha: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_node_id_sha256: str
    merge_method: str
    publisher_credential_id: str
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    pre_merge_state_sha256: str
    pre_lock_fresh_merge_readiness_sha256: str
    post_lock_fresh_merge_readiness_sha256: str
    merge_response_sha256: str
    merge_commit_sha: str
    final_remote_state_sha256: str
    authorization_reserved_at_utc: str
    transaction_started_at_utc: str
    merge_requested_at_utc: str
    merged_at_utc: str
    completed_at_utc: str
    transaction_lock_committed: bool = True
    merge_authorization_authenticated: bool = True
    pre_lock_merge_readiness_revalidated: bool = True
    pre_merge_remote_state_double_observed: bool = True
    post_lock_merge_readiness_revalidated: bool = True
    exact_sha_pinned_squash_merge_executed: bool = True
    merge_response_verified: bool = True
    post_merge_remote_state_double_observed: bool = True
    exact_base_parent_verified: bool = True
    merged: bool = True
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
    transaction_scope: str = PILOT_EXACT_TASK_MERGE_TRANSACTION_SCOPE
    authority: str = PILOT_EXACT_TASK_MERGE_TRANSACTION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_MERGE_TRANSACTION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_MERGE_TRANSACTION_SCHEMA
            or self.authority != PILOT_EXACT_TASK_MERGE_TRANSACTION_AUTHORITY
            or self.transaction_scope != PILOT_EXACT_TASK_MERGE_TRANSACTION_SCOPE
        ):
            raise PilotExactTaskMergeTransactionError("merge transaction receipt identity is unsupported")
        for name in (
            "transaction_ledger_root_path_sha256", "transaction_key_sha256", "merge_authorization_sha256",
            "merge_readiness_evaluation_sha256", "merge_readiness_policy_sha256", "merge_config_sha256",
            "execution_nonce_sha256", "development_task_sha256", "candidate_patch_sha256", "pr_intent_sha256",
            "pull_request_node_id_sha256", "publisher_credential_config_sha256", "publisher_credential_path_sha256",
            "pre_merge_state_sha256", "pre_lock_fresh_merge_readiness_sha256", "post_lock_fresh_merge_readiness_sha256",
            "merge_response_sha256", "final_remote_state_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("authorized_base_sha", "head_sha", "merge_commit_sha"):
            _hex40(getattr(self, name), name=name)
        if (
            self.transaction_key_sha256 != self.execution_nonce_sha256
            or not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskMergeTransactionError("merge transaction replay/repository identity is invalid")
        _branch(self.base_branch, name="base_branch")
        _branch(self.head_branch, name="head_branch")
        if (
            isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url != f"{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/{self.pull_request_number}"
            or self.merge_method != "squash"
            or not isinstance(self.publisher_credential_id, str)
            or not self.publisher_credential_id
        ):
            raise PilotExactTaskMergeTransactionError("merge transaction target identity is invalid")
        reserved = _utc(self.authorization_reserved_at_utc, name="authorization_reserved_at_utc")
        started = _utc(self.transaction_started_at_utc, name="transaction_started_at_utc")
        requested = _utc(self.merge_requested_at_utc, name="merge_requested_at_utc")
        merged = _utc(self.merged_at_utc, name="merged_at_utc")
        completed = _utc(self.completed_at_utc, name="completed_at_utc")
        if not reserved <= started <= requested <= merged <= completed:
            raise PilotExactTaskMergeTransactionError("merge transaction timestamps are invalid")
        required_true = (
            "transaction_lock_committed", "merge_authorization_authenticated", "pre_lock_merge_readiness_revalidated",
            "pre_merge_remote_state_double_observed", "post_lock_merge_readiness_revalidated",
            "exact_sha_pinned_squash_merge_executed", "merge_response_verified",
            "post_merge_remote_state_double_observed", "exact_base_parent_verified", "merged",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskMergeTransactionError("merge transaction completion evidence is incomplete")
        forced_false = (
            "merge_authorized", "remote_write_authorized", "review_submission_authorized",
            "review_thread_mutation_authorized", "ready_for_review_authorized", "reviewer_request_authorized",
            "push_authorized", "pr_mutation_authorized", "release_authorized", "deploy_authorized",
            "production_activation_authorized", "product_pilot_started", "nonce_reusable",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskMergeTransactionError("completed merge transaction retains forbidden authority")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def transaction_authenticated(self) -> bool:
        return _get_live_merge_transaction_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskMergeTransactionReceipt":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):  # type: ignore[attr-defined]
            raise PilotExactTaskMergeTransactionError("merge transaction receipt fields mismatch")
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskMergeTransactionLedger:
    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path, Path]:
        digest = _hex64(key, name="transaction_key_sha256")
        return self.root / f"{digest}.json", self.root / f".{digest}.lock", self.root / f".{digest}.merged.json"

    def acquire(
        self,
        *,
        authorization: PilotExactTaskMergeAuthorizationReceipt,
        pre_state_sha256: str,
        fresh_readiness_sha256: str,
        credential_config_sha256: str,
        credential_path_sha256: str,
    ) -> bytes:
        key = authorization.execution_nonce_sha256
        final, lock, merged = self._paths(key)
        if any(path.exists() or path.is_symlink() for path in (final, lock, merged)):
            raise PilotExactTaskMergeTransactionError("merge transaction nonce already consumed or needs recovery")
        payload = _canonical({
            "schema": "kaliv-rsi-dc-l16-exact-task-merge-transaction-lock/v1",
            "ledger_scope": PILOT_EXACT_TASK_MERGE_TRANSACTION_LEDGER_SCOPE,
            "ledger_root_path_sha256": self.root_sha256,
            "transaction_key_sha256": key,
            "merge_authorization_sha256": authorization.sha256,
            "merge_readiness_evaluation_sha256": authorization.merge_readiness_evaluation_sha256,
            "merge_readiness_policy_sha256": authorization.merge_readiness_policy_sha256,
            "merge_config_sha256": authorization.merge_config_sha256,
            "repository": authorization.repository,
            "repository_id": authorization.repository_id,
            "base_branch": authorization.base_branch,
            "base_sha": authorization.base_sha,
            "head_branch": authorization.head_branch,
            "head_sha": authorization.head_sha,
            "pull_request_number": authorization.pull_request_number,
            "merge_method": authorization.merge_method,
            "pre_merge_state_sha256": _hex64(pre_state_sha256, name="pre-merge state hash"),
            "pre_lock_fresh_merge_readiness_sha256": _hex64(fresh_readiness_sha256, name="fresh readiness hash"),
            "publisher_credential_config_sha256": _hex64(credential_config_sha256, name="credential config hash"),
            "publisher_credential_path_sha256": _hex64(credential_path_sha256, name="credential path hash"),
        }).encode("utf-8")
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskMergeTransactionError("merge transaction lock could not be durably committed") from exc
        return payload

    def mark_merged(
        self,
        *,
        authorization: PilotExactTaskMergeAuthorizationReceipt,
        lock_payload: bytes,
        merge_commit_sha: str,
        merge_response_sha256: str,
        merged_at_utc: str,
    ) -> bytes:
        final, lock, merged = self._paths(authorization.execution_nonce_sha256)
        if final.exists() or merged.exists() or merged.is_symlink():
            raise PilotExactTaskMergeTransactionError("merge transaction already finalized or marked merged")
        if _read_bound(lock) != lock_payload:
            raise PilotExactTaskMergeTransactionError("merge transaction lock changed before merged marker")
        payload = _canonical({
            "schema": "kaliv-rsi-dc-l16-exact-task-merge-transaction-merged/v1",
            "ledger_scope": PILOT_EXACT_TASK_MERGE_TRANSACTION_LEDGER_SCOPE,
            "transaction_key_sha256": authorization.execution_nonce_sha256,
            "merge_authorization_sha256": authorization.sha256,
            "merge_commit_sha": _hex40(merge_commit_sha, name="merge commit SHA"),
            "merge_response_sha256": _hex64(merge_response_sha256, name="merge response hash"),
            "merged_at_utc": merged_at_utc,
        }).encode("utf-8")
        _utc(merged_at_utc, name="merged_at_utc")
        try:
            create_once_file(merged, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskMergeTransactionError("merged marker could not be durably committed") from exc
        return payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskMergeTransactionReceipt,
        lock_payload: bytes,
        merged_payload: bytes,
        authorization: PilotExactTaskMergeAuthorizationReceipt,
    ) -> PilotExactTaskMergeTransactionReceipt:
        final, lock, merged = self._paths(receipt.transaction_key_sha256)
        if (
            final.exists()
            or final.is_symlink()
            or _read_bound(lock) != lock_payload
            or _read_bound(merged) != merged_payload
        ):
            raise PilotExactTaskMergeTransactionError("merge transaction durable state changed before finalization")
        payload = receipt.canonical_json().encode("utf-8")
        try:
            create_once_file(final, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskMergeTransactionError("merge transaction receipt could not be durably published") from exc
        parsed = PilotExactTaskMergeTransactionReceipt.from_mapping(json.loads(payload.decode("utf-8")))
        _mark_merge_transaction_authenticated(
            parsed,
            authorization=authorization,
            final_path=final,
            final_payload=payload,
            lock_path=lock,
            lock_payload=lock_payload,
            merged_path=merged,
            merged_payload=merged_payload,
        )
        if parsed.transaction_authenticated is not True:
            raise PilotExactTaskMergeTransactionError("merge transaction lost live provenance")
        return parsed


def _live_registry():
    records = {}

    def mark(receipt, *, authorization, final_path, final_payload, lock_path, lock_payload, merged_path, merged_payload):
        key = id(receipt)

        def cleanup(_):
            records.pop(key, None)

        records[key] = (
            os.getpid(), receipt.sha256, weakref.ref(receipt, cleanup), weakref.ref(authorization),
            final_path, final_payload, lock_path, lock_payload, merged_path, merged_payload,
        )

    def get(receipt):
        entry = records.get(id(receipt))
        if entry is None:
            return None
        (
            pid, digest, receipt_ref, authorization_ref, final_path, final_payload,
            lock_path, lock_payload, merged_path, merged_payload,
        ) = entry
        authorization = authorization_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or authorization is None
            or receipt.sha256 != digest
            or authorization.authorization_authenticated is not True
            or authorization.sha256 != receipt.merge_authorization_sha256
            or _read_bound(final_path) != final_payload
            or _read_bound(lock_path) != lock_payload
            or _read_bound(merged_path) != merged_payload
        ):
            return None
        return MappingProxyType({"merge_authorization": authorization})

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_merge_transaction_authenticated, _get_live_merge_transaction_inputs = _live_registry()


def _execute_verified_pilot_exact_task_merge(
    *,
    merge_authorization: PilotExactTaskMergeAuthorizationReceipt,
    transaction_ledger: _PilotExactTaskMergeTransactionLedger,
    transport: Any,
    fresh_revalidator: Callable[[PilotExactTaskMergeAuthorizationReceipt], PilotExactTaskMergeReadinessEvaluationReceipt],
    now_provider: Callable[[], str],
) -> PilotExactTaskMergeTransactionReceipt:
    authorization, _source_evaluation = _require_live_authorization(merge_authorization)
    if transport is None:
        raise PilotExactTaskMergeTransactionError("exact GitHub merge transport is required")
    for method in ("validate_for", "observe_pre", "merge", "observe_post"):
        if not callable(getattr(transport, method, None)):
            raise PilotExactTaskMergeTransactionError("exact GitHub merge transport is incomplete")
    transport.validate_for(authorization)
    started_at = now_provider()
    started = _utc(started_at, name="transaction_started_at_utc")
    if not (
        _utc(authorization.reserved_at_utc, name="authorization_reserved_at_utc")
        <= started
        < _utc(authorization.expires_at_utc, name="authorization_expires_at_utc")
    ):
        raise PilotExactTaskMergeTransactionError("merge authorization is expired before transaction start")

    fresh_before = _require_fresh_ready(authorization, fresh_revalidator(authorization))
    pre_first = transport.observe_pre(authorization)
    pre_second = transport.observe_pre(authorization)
    if (
        type(pre_first) is not _PreMergeRemoteState
        or type(pre_second) is not _PreMergeRemoteState
        or pre_first.to_dict() != pre_second.to_dict()
    ):
        raise PilotExactTaskMergeTransactionError("pre-merge remote state changed between exact observations")

    lock_payload = transaction_ledger.acquire(
        authorization=authorization,
        pre_state_sha256=pre_first.sha256,
        fresh_readiness_sha256=fresh_before.sha256,
        credential_config_sha256=transport.credential_config_sha256,
        credential_path_sha256=transport.credential_path_sha256,
    )

    fresh_after = _require_fresh_ready(authorization, fresh_revalidator(authorization))
    current = transport.observe_pre(authorization)
    if type(current) is not _PreMergeRemoteState or current.to_dict() != pre_first.to_dict():
        raise PilotExactTaskMergeTransactionError("pre-merge remote state drifted after durable transaction lock")

    merge_requested_at = now_provider()
    requested = _utc(merge_requested_at, name="merge_requested_at_utc")
    if not (
        started <= requested < _utc(authorization.expires_at_utc, name="authorization_expires_at_utc")
    ):
        raise PilotExactTaskMergeTransactionError("merge authorization expired after transaction lock")

    merge_commit_sha, merge_response_sha256 = transport.merge(authorization)
    merge_commit_sha = _hex40(merge_commit_sha, name="merge commit SHA")
    merge_response_sha256 = _hex64(merge_response_sha256, name="merge response hash")
    merged_at = now_provider()
    if _utc(merged_at, name="merged_at_utc") < requested:
        raise PilotExactTaskMergeTransactionError("system clock moved backwards during merge")
    merged_payload = transaction_ledger.mark_merged(
        authorization=authorization,
        lock_payload=lock_payload,
        merge_commit_sha=merge_commit_sha,
        merge_response_sha256=merge_response_sha256,
        merged_at_utc=merged_at,
    )

    post_first = transport.observe_post(authorization, merge_commit_sha)
    post_second = transport.observe_post(authorization, merge_commit_sha)
    if (
        type(post_first) is not _PostMergeRemoteState
        or type(post_second) is not _PostMergeRemoteState
        or post_first.to_dict() != post_second.to_dict()
        or post_first.merge_commit_parent_sha != authorization.base_sha
    ):
        raise PilotExactTaskMergeTransactionError("post-merge remote state is not stable exact authorized squash merge")

    completed_at = now_provider()
    if _utc(completed_at, name="completed_at_utc") < _utc(merged_at, name="merged_at_utc"):
        raise PilotExactTaskMergeTransactionError("system clock moved backwards after merge")
    receipt = PilotExactTaskMergeTransactionReceipt(
        transaction_ledger_root_path_sha256=transaction_ledger.root_sha256,
        transaction_key_sha256=authorization.execution_nonce_sha256,
        merge_authorization_sha256=authorization.sha256,
        merge_readiness_evaluation_sha256=authorization.merge_readiness_evaluation_sha256,
        merge_readiness_policy_sha256=authorization.merge_readiness_policy_sha256,
        merge_config_sha256=authorization.merge_config_sha256,
        execution_nonce_sha256=authorization.execution_nonce_sha256,
        development_task_sha256=authorization.development_task_sha256,
        candidate_patch_sha256=authorization.candidate_patch_sha256,
        pr_intent_sha256=authorization.pr_intent_sha256,
        repository=authorization.repository,
        repository_id=authorization.repository_id,
        base_branch=authorization.base_branch,
        authorized_base_sha=authorization.base_sha,
        head_branch=authorization.head_branch,
        head_sha=authorization.head_sha,
        pull_request_number=authorization.pull_request_number,
        pull_request_api_url=authorization.pull_request_api_url,
        pull_request_node_id_sha256=authorization.pull_request_node_id_sha256,
        merge_method=authorization.merge_method,
        publisher_credential_id=transport.credential_id,
        publisher_credential_config_sha256=transport.credential_config_sha256,
        publisher_credential_path_sha256=transport.credential_path_sha256,
        pre_merge_state_sha256=pre_first.sha256,
        pre_lock_fresh_merge_readiness_sha256=fresh_before.sha256,
        post_lock_fresh_merge_readiness_sha256=fresh_after.sha256,
        merge_response_sha256=merge_response_sha256,
        merge_commit_sha=merge_commit_sha,
        final_remote_state_sha256=post_first.sha256,
        authorization_reserved_at_utc=authorization.reserved_at_utc,
        transaction_started_at_utc=started_at,
        merge_requested_at_utc=merge_requested_at,
        merged_at_utc=merged_at,
        completed_at_utc=completed_at,
    )
    return transaction_ledger.commit(
        receipt=receipt,
        lock_payload=lock_payload,
        merged_payload=merged_payload,
        authorization=authorization,
    )


def _canonical_runtime() -> tuple[_PilotExactTaskMergeTransactionLedger, _GitHubExactMergeTransport]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            root = _require_host_controlled_ledger_root(_POSIX_LEDGER)
        elif os.name == "nt":
            root = _require_host_controlled_ledger_root(_WINDOWS_LEDGER)
        else:
            raise PilotExactTaskMergeTransactionError("merge transaction is unsupported on this platform")
        credential, digest, path = publication_tx_boundary._canonical_credential()
        transport = _GitHubExactMergeTransport(
            credential=credential,
            credential_config_sha256=digest,
            credential_path=path,
        )
        return _PilotExactTaskMergeTransactionLedger(root), transport
    except PhysicalHostStateError as exc:
        raise PilotExactTaskMergeTransactionError("merge transaction runtime is not host-admin controlled") from exc


def execute_pilot_exact_task_merge(
    merge_authorization: PilotExactTaskMergeAuthorizationReceipt,
) -> PilotExactTaskMergeTransactionReceipt:
    """Consume one exact merge authority and execute only its SHA-pinned squash merge."""
    ledger, transport = _canonical_runtime()
    return _execute_verified_pilot_exact_task_merge(
        merge_authorization=merge_authorization,
        transaction_ledger=ledger,
        transport=transport,
        fresh_revalidator=_canonical_fresh_revalidate,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
