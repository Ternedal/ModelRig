"""ADR-DC-054 one-shot exact PR lifecycle transaction.

This boundary consumes one exact live ADR-DC-053 lifecycle authorization before
any GitHub mutation. It revalidates the exact draft pull request, durably locks
one transaction slot, revalidates again, marks only that pull request ready for
review, requests only the host-pinned reviewer set, and verifies the resulting
remote state.

No push, merge, release, deployment, or production activation authority is
created or exercised.
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
from . import improvement_pilot_exact_task_pr_lifecycle_authorization as auth_boundary
from .improvement_pilot_exact_task_pr_lifecycle_authorization import (
    PILOT_EXACT_TASK_PR_LIFECYCLE_AUTHORIZATION_AUTHORITY,
    PilotExactTaskPrLifecycleAuthorizationReceipt,
    PilotExactTaskPrLifecycleConfig,
)
from . import improvement_pilot_exact_task_remote_publication_transaction as publication_tx_boundary
from .improvement_pilot_exact_task_remote_publication_transaction import (
    PilotExactTaskGitHubPublisherCredential,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_PR_LIFECYCLE_TRANSACTION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-lifecycle-transaction-receipt/v1"
)
PILOT_EXACT_TASK_PR_LIFECYCLE_TRANSACTION_AUTHORITY = (
    "host-executed-one-dc-l16-exact-pr-lifecycle-only"
)
PILOT_EXACT_TASK_PR_LIFECYCLE_TRANSACTION_LEDGER_SCOPE = "canonical-host-local-v1"
_MAX_API_RESPONSE_BYTES = 2 * 1024 * 1024
_TIMEOUT_SECONDS = 30.0
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_NODE = re.compile(r"^[A-Za-z0-9_=-]{8,256}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_GITHUB_API_ROOT = "https://api.github.com"
_GITHUB_GRAPHQL = "https://api.github.com/graphql"
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-pr-lifecycle-transaction-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-pr-lifecycle-transaction-ledger-v1"
)


class PilotExactTaskPrLifecycleTransactionError(ValueError):
    """Exact lifecycle transaction is stale, replayed, partial, or over-broad."""


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
        raise PilotExactTaskPrLifecycleTransactionError(
            "PR lifecycle transaction evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrLifecycleTransactionError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrLifecycleTransactionError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrLifecycleTransactionError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrLifecycleTransactionError(f"{name} is invalid") from exc


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
        raise PilotExactTaskPrLifecycleTransactionError(f"{name} is invalid")
    return value


def _node(value: Any) -> str:
    if not isinstance(value, str) or _NODE.fullmatch(value) is None:
        raise PilotExactTaskPrLifecycleTransactionError("pull-request node id is invalid")
    return value


def _reviewer_set_sha256(usernames: tuple[str, ...], teams: tuple[str, ...]) -> str:
    return hashlib.sha256(
        _canonical(
            {
                "reviewer_usernames": list(usernames),
                "reviewer_team_slugs": list(teams),
            }
        ).encode("utf-8")
    ).hexdigest()


def _require_live_authorization(
    value: Any,
) -> tuple[
    PilotExactTaskPrLifecycleAuthorizationReceipt,
    Any,
    PilotExactTaskPrLifecycleConfig,
]:
    if type(value) is not PilotExactTaskPrLifecycleAuthorizationReceipt:
        raise PilotExactTaskPrLifecycleTransactionError(
            "exact ADR-DC-053 lifecycle authorization is required"
        )
    try:
        replayed = PilotExactTaskPrLifecycleAuthorizationReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPrLifecycleTransactionError(
            "ADR-DC-053 lifecycle authorization replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrLifecycleTransactionError(
            "ADR-DC-053 lifecycle authorization identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_PR_LIFECYCLE_AUTHORIZATION_AUTHORITY
        or value.authorization_authenticated is not True
        or value.host_lifecycle_guard_committed is not True
        or value.post_publication_attestation_authenticated is not True
        or value.post_publication_verified is not True
        or value.lifecycle_config_host_pinned is not True
        or value.external_ed25519_authorized is not True
        or value.ready_for_review_authorized is not True
        or value.reviewer_request_authorized is not True
        or value.remote_write_authorized is not True
        or value.pr_mutation_authorized is not True
        or value.push_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskPrLifecycleTransactionError(
            "transaction requires one live unused ADR-DC-053 authorization"
        )
    inputs = auth_boundary._get_live_pr_lifecycle_authorization_inputs(value)
    if inputs is None:
        raise PilotExactTaskPrLifecycleTransactionError(
            "ADR-DC-053 live lifecycle inputs are unavailable"
        )
    attestation = inputs.get("post_publication_attestation")
    config = inputs.get("lifecycle_config")
    if (
        attestation is None
        or type(config) is not PilotExactTaskPrLifecycleConfig
        or getattr(attestation, "sha256", None)
        != value.post_publication_attestation_sha256
        or getattr(attestation, "attestation_authenticated", False) is not True
        or config.sha256 != value.lifecycle_config_sha256
        or config.reviewer_set_sha256 != value.reviewer_set_sha256
        or config.reviewer_usernames != value.reviewer_usernames
        or config.reviewer_team_slugs != value.reviewer_team_slugs
        or getattr(attestation, "pull_request_number", None)
        != value.pull_request_number
        or getattr(attestation, "predicted_commit_sha", None)
        != value.predicted_commit_sha
    ):
        raise PilotExactTaskPrLifecycleTransactionError(
            "ADR-DC-053 authorization is not bound to exact live provenance"
        )
    return value, attestation, config


@dataclass(frozen=True, slots=True)
class _LifecycleRemoteState:
    pull_request_node_id: str
    draft: bool
    reviewer_usernames: tuple[str, ...]
    reviewer_team_slugs: tuple[str, ...]
    repository: str
    repository_id: str
    base_branch: str
    base_sha: str
    head_branch: str
    head_sha: str
    pull_request_number: int
    pull_request_api_url: str
    maintainer_can_modify: bool
    state: str

    def __post_init__(self) -> None:
        _node(self.pull_request_node_id)
        if self.state != "open":
            raise PilotExactTaskPrLifecycleTransactionError(
                "lifecycle pull request is not open"
            )
        if not isinstance(self.draft, bool):
            raise PilotExactTaskPrLifecycleTransactionError(
                "lifecycle draft state is invalid"
            )
        if self.maintainer_can_modify is not False:
            raise PilotExactTaskPrLifecycleTransactionError(
                "maintainer_can_modify must remain false"
            )
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PilotExactTaskPrLifecycleTransactionError("repository is invalid")
        if not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None:
            raise PilotExactTaskPrLifecycleTransactionError("repository_id is invalid")
        _branch(self.base_branch, name="base_branch")
        _branch(self.head_branch, name="head_branch")
        _hex40(self.base_sha, name="base_sha")
        _hex40(self.head_sha, name="head_sha")
        if (
            isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/{self.pull_request_number}"
        ):
            raise PilotExactTaskPrLifecycleTransactionError(
                "pull-request identity is invalid"
            )
        if list(self.reviewer_usernames) != sorted(set(self.reviewer_usernames)):
            raise PilotExactTaskPrLifecycleTransactionError(
                "remote reviewer usernames are not sorted/unique"
            )
        if list(self.reviewer_team_slugs) != sorted(set(self.reviewer_team_slugs)):
            raise PilotExactTaskPrLifecycleTransactionError(
                "remote reviewer teams are not sorted/unique"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "pull_request_node_id_sha256": hashlib.sha256(
                self.pull_request_node_id.encode("utf-8")
            ).hexdigest(),
            "draft": self.draft,
            "reviewer_usernames": list(self.reviewer_usernames),
            "reviewer_team_slugs": list(self.reviewer_team_slugs),
            "repository": self.repository,
            "repository_id": self.repository_id,
            "base_branch": self.base_branch,
            "base_sha": self.base_sha,
            "head_branch": self.head_branch,
            "head_sha": self.head_sha,
            "pull_request_number": self.pull_request_number,
            "pull_request_api_url": self.pull_request_api_url,
            "maintainer_can_modify": self.maintainer_can_modify,
            "state": self.state,
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict()).encode("utf-8")).hexdigest()


def _validate_state_binding(
    state: _LifecycleRemoteState,
    authorization: PilotExactTaskPrLifecycleAuthorizationReceipt,
) -> None:
    inputs = auth_boundary._get_live_pr_lifecycle_authorization_inputs(authorization)
    attestation = None if inputs is None else inputs.get("post_publication_attestation")
    if attestation is None:
        raise PilotExactTaskPrLifecycleTransactionError(
            "live ADR-DC-053 attestation binding is unavailable"
        )
    if (
        state.repository != authorization.repository
        or state.repository_id != authorization.repository_id
        or state.base_branch != authorization.base_branch
        or state.base_sha != getattr(attestation, "exact_task_base_sha", None)
        or state.head_branch != authorization.head_branch
        or state.head_sha != authorization.predicted_commit_sha
        or state.pull_request_number != authorization.pull_request_number
        or state.pull_request_api_url != authorization.pull_request_api_url
    ):
        raise PilotExactTaskPrLifecycleTransactionError(
            "GitHub lifecycle state is not bound to exact ADR-DC-053 authority"
        )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class _GitHubPrLifecycleTransport:
    """Exact ready-for-review + reviewer-request transport."""

    def __init__(
        self,
        *,
        credential: PilotExactTaskGitHubPublisherCredential,
        credential_config_sha256: str,
        credential_path: Path,
    ) -> None:
        if type(credential) is not PilotExactTaskGitHubPublisherCredential:
            raise PilotExactTaskPrLifecycleTransactionError(
                "exact publisher credential is required"
            )
        self.credential = credential
        self.credential_id = credential.credential_id
        self.credential_config_sha256 = _hex64(
            credential_config_sha256, name="publisher credential config digest"
        )
        self.credential_path = Path(credential_path)
        if (
            not self.credential_path.is_absolute()
            or _has_linkish_component(self.credential_path)
        ):
            raise PilotExactTaskPrLifecycleTransactionError(
                "publisher credential path identity is unsafe"
            )
        self.credential_path_sha256 = _path_sha256(self.credential_path)
        self._opener = urllib.request.build_opener(_NoRedirect())

    def validate_for(
        self, authorization: PilotExactTaskPrLifecycleAuthorizationReceipt
    ) -> None:
        if (
            self.credential.repository != authorization.repository
            or self.credential.repository_id != authorization.repository_id
        ):
            raise PilotExactTaskPrLifecycleTransactionError(
                "publisher credential is not bound to lifecycle repository"
            )

    @staticmethod
    def _repo_root(authorization: PilotExactTaskPrLifecycleAuthorizationReceipt) -> str:
        owner, repo = authorization.repository.split("/", 1)
        return (
            f"/repos/{urllib.parse.quote(owner, safe='')}/"
            f"{urllib.parse.quote(repo, safe='')}"
        )

    def _rest_json(
        self,
        *,
        path: str,
        method: str,
        body: Mapping[str, Any] | None = None,
        expected_status: int,
    ) -> Any:
        if (
            not isinstance(path, str)
            or not path.startswith("/repos/")
            or ".." in path
            or method not in {"GET", "POST"}
        ):
            raise PilotExactTaskPrLifecycleTransactionError(
                "lifecycle REST request is outside exact GitHub scope"
            )
        payload = None
        if method == "POST":
            if not isinstance(body, Mapping):
                raise PilotExactTaskPrLifecycleTransactionError(
                    "lifecycle POST body is missing"
                )
            payload = _canonical(dict(body)).encode("utf-8")
        elif body is not None:
            raise PilotExactTaskPrLifecycleTransactionError(
                "lifecycle GET cannot carry a body"
            )
        url = _GITHUB_API_ROOT + path
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.credential.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ModelRig-DevControl-PrLifecycle/1",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url, data=payload, method=method, headers=headers
        )
        try:
            response = self._opener.open(request, timeout=_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            raise PilotExactTaskPrLifecycleTransactionError(
                f"GitHub lifecycle REST request failed with HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PilotExactTaskPrLifecycleTransactionError(
                "GitHub lifecycle REST request failed"
            ) from exc
        with response:
            if response.status != expected_status or response.geturl() != url:
                raise PilotExactTaskPrLifecycleTransactionError(
                    "GitHub lifecycle REST response identity/status is unexpected"
                )
            raw = response.read(_MAX_API_RESPONSE_BYTES + 1)
        if not raw or len(raw) > _MAX_API_RESPONSE_BYTES:
            raise PilotExactTaskPrLifecycleTransactionError(
                "GitHub lifecycle REST response size is invalid"
            )
        try:
            return json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PilotExactTaskPrLifecycleTransactionError(
                "GitHub lifecycle REST response is invalid JSON"
            ) from exc

    def _graphql(self, *, query: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(query, str) or "markPullRequestReadyForReview" not in query:
            raise PilotExactTaskPrLifecycleTransactionError(
                "unsupported lifecycle GraphQL mutation"
            )
        payload = _canonical(
            {"query": query, "variables": dict(variables)}
        ).encode("utf-8")
        request = urllib.request.Request(
            _GITHUB_GRAPHQL,
            data=payload,
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.credential.token}",
                "Content-Type": "application/json",
                "User-Agent": "ModelRig-DevControl-PrLifecycle/1",
            },
        )
        try:
            response = self._opener.open(request, timeout=_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            raise PilotExactTaskPrLifecycleTransactionError(
                f"GitHub lifecycle GraphQL request failed with HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PilotExactTaskPrLifecycleTransactionError(
                "GitHub lifecycle GraphQL request failed"
            ) from exc
        with response:
            if response.status != 200 or response.geturl() != _GITHUB_GRAPHQL:
                raise PilotExactTaskPrLifecycleTransactionError(
                    "GitHub lifecycle GraphQL response identity/status is unexpected"
                )
            raw = response.read(_MAX_API_RESPONSE_BYTES + 1)
        if not raw or len(raw) > _MAX_API_RESPONSE_BYTES:
            raise PilotExactTaskPrLifecycleTransactionError(
                "GitHub lifecycle GraphQL response size is invalid"
            )
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PilotExactTaskPrLifecycleTransactionError(
                "GitHub lifecycle GraphQL response is invalid JSON"
            ) from exc
        if (
            not isinstance(value, Mapping)
            or value.get("errors") not in (None, [])
            or not isinstance(value.get("data"), Mapping)
        ):
            raise PilotExactTaskPrLifecycleTransactionError(
                "GitHub lifecycle GraphQL mutation returned errors"
            )
        return value["data"]

    def observe(
        self, authorization: PilotExactTaskPrLifecycleAuthorizationReceipt
    ) -> _LifecycleRemoteState:
        self.validate_for(authorization)
        root = self._repo_root(authorization)
        pr = self._rest_json(
            path=f"{root}/pulls/{authorization.pull_request_number}",
            method="GET",
            expected_status=200,
        )
        reviewers = self._rest_json(
            path=(
                f"{root}/pulls/{authorization.pull_request_number}/"
                "requested_reviewers"
            ),
            method="GET",
            expected_status=200,
        )
        if not isinstance(pr, Mapping) or not isinstance(reviewers, Mapping):
            raise PilotExactTaskPrLifecycleTransactionError(
                "GitHub lifecycle observation is invalid"
            )
        base = pr.get("base")
        head = pr.get("head")
        base_repo = base.get("repo") if isinstance(base, Mapping) else None
        if (
            not isinstance(base, Mapping)
            or not isinstance(head, Mapping)
            or not isinstance(base_repo, Mapping)
        ):
            raise PilotExactTaskPrLifecycleTransactionError(
                "GitHub lifecycle pull-request refs are invalid"
            )
        users_raw = reviewers.get("users")
        teams_raw = reviewers.get("teams")
        if not isinstance(users_raw, list) or not isinstance(teams_raw, list):
            raise PilotExactTaskPrLifecycleTransactionError(
                "GitHub requested-reviewer state is invalid"
            )
        usernames: list[str] = []
        team_slugs: list[str] = []
        for item in users_raw:
            if not isinstance(item, Mapping) or not isinstance(item.get("login"), str):
                raise PilotExactTaskPrLifecycleTransactionError(
                    "GitHub requested reviewer identity is invalid"
                )
            usernames.append(item["login"].lower())
        for item in teams_raw:
            if not isinstance(item, Mapping) or not isinstance(item.get("slug"), str):
                raise PilotExactTaskPrLifecycleTransactionError(
                    "GitHub requested team identity is invalid"
                )
            team_slugs.append(item["slug"].lower())
        repository_id = str(base_repo.get("id"))
        state = _LifecycleRemoteState(
            pull_request_node_id=_node(pr.get("node_id")),
            draft=pr.get("draft"),
            reviewer_usernames=tuple(sorted(usernames)),
            reviewer_team_slugs=tuple(sorted(team_slugs)),
            repository=authorization.repository,
            repository_id=repository_id,
            base_branch=base.get("ref"),
            base_sha=base.get("sha"),
            head_branch=head.get("ref"),
            head_sha=head.get("sha"),
            pull_request_number=pr.get("number"),
            pull_request_api_url=pr.get("url"),
            maintainer_can_modify=pr.get("maintainer_can_modify"),
            state=pr.get("state"),
        )
        _validate_state_binding(state, authorization)
        return state

    def mark_ready(
        self,
        *,
        authorization: PilotExactTaskPrLifecycleAuthorizationReceipt,
        pull_request_node_id: str,
    ) -> None:
        self.validate_for(authorization)
        node_id = _node(pull_request_node_id)
        query = (
            "mutation MarkReady($pullRequestId:ID!){"
            "markPullRequestReadyForReview(input:{pullRequestId:$pullRequestId}){"
            "pullRequest{id number isDraft}}}"
        )
        data = self._graphql(
            query=query,
            variables={"pullRequestId": node_id},
        )
        result = data.get("markPullRequestReadyForReview")
        pr = result.get("pullRequest") if isinstance(result, Mapping) else None
        if (
            not isinstance(pr, Mapping)
            or pr.get("id") != node_id
            or pr.get("number") != authorization.pull_request_number
            or pr.get("isDraft") is not False
        ):
            raise PilotExactTaskPrLifecycleTransactionError(
                "GitHub ready-for-review mutation did not return exact PR"
            )

    def request_reviewers(
        self,
        *,
        authorization: PilotExactTaskPrLifecycleAuthorizationReceipt,
    ) -> None:
        self.validate_for(authorization)
        root = self._repo_root(authorization)
        value = self._rest_json(
            path=(
                f"{root}/pulls/{authorization.pull_request_number}/"
                "requested_reviewers"
            ),
            method="POST",
            body={
                "reviewers": list(authorization.reviewer_usernames),
                "team_reviewers": list(authorization.reviewer_team_slugs),
            },
            expected_status=201,
        )
        if not isinstance(value, Mapping) or value.get("number") != authorization.pull_request_number:
            raise PilotExactTaskPrLifecycleTransactionError(
                "GitHub reviewer request did not return exact PR"
            )


def _require_pre_state(
    state: _LifecycleRemoteState,
    authorization: PilotExactTaskPrLifecycleAuthorizationReceipt,
) -> None:
    _validate_state_binding(state, authorization)
    if (
        state.draft is not True
        or state.reviewer_usernames
        or state.reviewer_team_slugs
    ):
        raise PilotExactTaskPrLifecycleTransactionError(
            "lifecycle transaction requires exact untouched draft PR"
        )


def _require_ready_state(
    state: _LifecycleRemoteState,
    authorization: PilotExactTaskPrLifecycleAuthorizationReceipt,
    *,
    node_id: str,
) -> None:
    _validate_state_binding(state, authorization)
    if (
        state.pull_request_node_id != node_id
        or state.draft is not False
        or state.reviewer_usernames
        or state.reviewer_team_slugs
    ):
        raise PilotExactTaskPrLifecycleTransactionError(
            "ready-for-review state is not exact"
        )


def _require_final_state(
    state: _LifecycleRemoteState,
    authorization: PilotExactTaskPrLifecycleAuthorizationReceipt,
    *,
    node_id: str,
) -> None:
    _validate_state_binding(state, authorization)
    if (
        state.pull_request_node_id != node_id
        or state.draft is not False
        or state.reviewer_usernames != authorization.reviewer_usernames
        or state.reviewer_team_slugs != authorization.reviewer_team_slugs
        or _reviewer_set_sha256(
            state.reviewer_usernames, state.reviewer_team_slugs
        )
        != authorization.reviewer_set_sha256
    ):
        raise PilotExactTaskPrLifecycleTransactionError(
            "final lifecycle state is not exact"
        )


class _PilotExactTaskPrLifecycleTransactionLedger:
    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path, Path, Path]:
        digest = _hex64(key, name="transaction_key_sha256")
        return (
            self.root / f"{digest}.json",
            self.root / f".{digest}.lock",
            self.root / f".{digest}.ready.json",
            self.root / f".{digest}.reviewers.json",
        )

    def acquire(
        self,
        *,
        authorization: PilotExactTaskPrLifecycleAuthorizationReceipt,
        pre_state_sha256: str,
        credential_config_sha256: str,
        credential_path_sha256: str,
    ) -> bytes:
        final, lock, ready, reviewers = self._paths(authorization.execution_nonce_sha256)
        if any(path.exists() or path.is_symlink() for path in (final, lock, ready, reviewers)):
            raise PilotExactTaskPrLifecycleTransactionError(
                "PR lifecycle transaction nonce already consumed or needs recovery"
            )
        payload = _canonical(
            {
                "schema": "kaliv-rsi-dc-l16-exact-task-pr-lifecycle-transaction-lock/v1",
                "ledger_scope": PILOT_EXACT_TASK_PR_LIFECYCLE_TRANSACTION_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "transaction_key_sha256": authorization.execution_nonce_sha256,
                "pr_lifecycle_authorization_sha256": authorization.sha256,
                "post_publication_attestation_sha256": authorization.post_publication_attestation_sha256,
                "lifecycle_config_sha256": authorization.lifecycle_config_sha256,
                "reviewer_set_sha256": authorization.reviewer_set_sha256,
                "pull_request_number": authorization.pull_request_number,
                "predicted_commit_sha": authorization.predicted_commit_sha,
                "pre_state_sha256": _hex64(pre_state_sha256, name="pre_state_sha256"),
                "publisher_credential_config_sha256": _hex64(
                    credential_config_sha256, name="publisher credential config digest"
                ),
                "publisher_credential_path_sha256": _hex64(
                    credential_path_sha256, name="publisher credential path digest"
                ),
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskPrLifecycleTransactionError(
                "PR lifecycle transaction could not be durably consumed"
            ) from exc
        return payload

    def mark_ready(
        self,
        *,
        authorization: PilotExactTaskPrLifecycleAuthorizationReceipt,
        node_id: str,
        state_sha256: str,
        ready_at_utc: str,
    ) -> bytes:
        _final, lock, ready, _reviewers = self._paths(authorization.execution_nonce_sha256)
        if not lock.is_file() or ready.exists() or ready.is_symlink():
            raise PilotExactTaskPrLifecycleTransactionError(
                "ready marker durable phase is invalid"
            )
        payload = _canonical(
            {
                "schema": "kaliv-rsi-dc-l16-exact-task-pr-lifecycle-ready-marker/v1",
                "transaction_key_sha256": authorization.execution_nonce_sha256,
                "pr_lifecycle_authorization_sha256": authorization.sha256,
                "pull_request_node_id_sha256": hashlib.sha256(
                    _node(node_id).encode("utf-8")
                ).hexdigest(),
                "ready_state_sha256": _hex64(state_sha256, name="ready state digest"),
                "ready_at_utc": ready_at_utc,
            }
        ).encode("utf-8")
        try:
            create_once_file(ready, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskPrLifecycleTransactionError(
                "ready-for-review marker could not be published"
            ) from exc
        return payload

    def mark_reviewers(
        self,
        *,
        authorization: PilotExactTaskPrLifecycleAuthorizationReceipt,
        final_state_sha256: str,
        reviewers_requested_at_utc: str,
    ) -> bytes:
        _final, lock, ready, reviewers = self._paths(authorization.execution_nonce_sha256)
        if (
            not lock.is_file()
            or not ready.is_file()
            or reviewers.exists()
            or reviewers.is_symlink()
        ):
            raise PilotExactTaskPrLifecycleTransactionError(
                "reviewer marker durable phase is invalid"
            )
        payload = _canonical(
            {
                "schema": "kaliv-rsi-dc-l16-exact-task-pr-lifecycle-reviewers-marker/v1",
                "transaction_key_sha256": authorization.execution_nonce_sha256,
                "pr_lifecycle_authorization_sha256": authorization.sha256,
                "reviewer_set_sha256": authorization.reviewer_set_sha256,
                "final_state_sha256": _hex64(
                    final_state_sha256, name="final lifecycle state digest"
                ),
                "reviewers_requested_at_utc": reviewers_requested_at_utc,
            }
        ).encode("utf-8")
        try:
            create_once_file(reviewers, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskPrLifecycleTransactionError(
                "reviewer-request marker could not be published"
            ) from exc
        return payload

    def commit(
        self,
        *,
        receipt: "PilotExactTaskPrLifecycleTransactionReceipt",
        authorization: PilotExactTaskPrLifecycleAuthorizationReceipt,
        lock_payload: bytes,
        ready_payload: bytes,
        reviewers_payload: bytes,
    ) -> "PilotExactTaskPrLifecycleTransactionReceipt":
        final, lock, ready, reviewers = self._paths(receipt.transaction_key_sha256)
        try:
            current = (lock.read_bytes(), ready.read_bytes(), reviewers.read_bytes())
        except OSError as exc:
            raise PilotExactTaskPrLifecycleTransactionError(
                "lifecycle transaction durable phase evidence is unavailable"
            ) from exc
        if (
            final.exists()
            or final.is_symlink()
            or current != (lock_payload, ready_payload, reviewers_payload)
        ):
            raise PilotExactTaskPrLifecycleTransactionError(
                "lifecycle transaction durable state changed before finalization"
            )
        payload = receipt.canonical_json().encode("utf-8")
        try:
            create_once_file(final, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskPrLifecycleTransactionError(
                "lifecycle transaction final receipt could not be durably published"
            ) from exc
        parsed = PilotExactTaskPrLifecycleTransactionReceipt.from_mapping(
            json.loads(payload.decode("utf-8"))
        )
        _mark_transaction_authenticated(
            parsed,
            authorization=authorization,
            final_path=final,
            final_payload=payload,
            lock_path=lock,
            lock_payload=lock_payload,
            ready_path=ready,
            ready_payload=ready_payload,
            reviewers_path=reviewers,
            reviewers_payload=reviewers_payload,
        )
        if parsed.transaction_authenticated is not True:
            raise PilotExactTaskPrLifecycleTransactionError(
                "lifecycle transaction receipt lost live provenance"
            )
        return parsed


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrLifecycleTransactionReceipt:
    transaction_ledger_root_path_sha256: str
    transaction_key_sha256: str
    pr_lifecycle_authorization_sha256: str
    post_publication_attestation_sha256: str
    lifecycle_config_sha256: str
    reviewer_set_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    repository: str
    repository_id: str
    base_branch: str
    head_branch: str
    predicted_commit_sha: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_node_id_sha256: str
    reviewer_usernames: tuple[str, ...]
    reviewer_team_slugs: tuple[str, ...]
    publisher_credential_id: str
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    pre_state_sha256: str
    post_ready_state_sha256: str
    final_state_sha256: str
    started_at_utc: str
    ready_at_utc: str
    reviewers_requested_at_utc: str
    completed_at_utc: str
    host_transaction_guard_committed: bool = True
    pr_lifecycle_authorization_authenticated: bool = True
    pr_lifecycle_authorization_consumed: bool = True
    exact_pr_revalidated_after_consumption: bool = True
    ready_for_review_completed: bool = True
    reviewer_requests_completed: bool = True
    final_pr_state_verified: bool = True
    remote_write_performed: bool = True
    ready_for_review_authorized: bool = False
    reviewer_request_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    product_pilot_started: bool = False
    draft: bool = False
    nonce_reusable: bool = False
    ledger_scope: str = PILOT_EXACT_TASK_PR_LIFECYCLE_TRANSACTION_LEDGER_SCOPE
    authority: str = PILOT_EXACT_TASK_PR_LIFECYCLE_TRANSACTION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PR_LIFECYCLE_TRANSACTION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_LIFECYCLE_TRANSACTION_SCHEMA
            or self.authority != PILOT_EXACT_TASK_PR_LIFECYCLE_TRANSACTION_AUTHORITY
            or self.ledger_scope != PILOT_EXACT_TASK_PR_LIFECYCLE_TRANSACTION_LEDGER_SCOPE
        ):
            raise PilotExactTaskPrLifecycleTransactionError(
                "PR lifecycle transaction receipt identity is unsupported"
            )
        for name in (
            "transaction_ledger_root_path_sha256",
            "transaction_key_sha256",
            "pr_lifecycle_authorization_sha256",
            "post_publication_attestation_sha256",
            "lifecycle_config_sha256",
            "reviewer_set_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
            "pull_request_node_id_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "pre_state_sha256",
            "post_ready_state_sha256",
            "final_state_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        if (
            self.transaction_key_sha256 != self.execution_nonce_sha256
            or self.reviewer_set_sha256
            != _reviewer_set_sha256(
                self.reviewer_usernames, self.reviewer_team_slugs
            )
        ):
            raise PilotExactTaskPrLifecycleTransactionError(
                "lifecycle transaction binding hashes are inconsistent"
            )
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PilotExactTaskPrLifecycleTransactionError("repository is invalid")
        if not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None:
            raise PilotExactTaskPrLifecycleTransactionError("repository_id is invalid")
        _branch(self.base_branch, name="base_branch")
        _branch(self.head_branch, name="head_branch")
        if (
            isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/{self.pull_request_number}"
        ):
            raise PilotExactTaskPrLifecycleTransactionError(
                "pull-request identity is invalid"
            )
        for name in (
            "started_at_utc",
            "ready_at_utc",
            "reviewers_requested_at_utc",
            "completed_at_utc",
        ):
            _utc(getattr(self, name), name=name)
        started = _utc(self.started_at_utc, name="started_at_utc")
        ready = _utc(self.ready_at_utc, name="ready_at_utc")
        reviewers = _utc(
            self.reviewers_requested_at_utc, name="reviewers_requested_at_utc"
        )
        completed = _utc(self.completed_at_utc, name="completed_at_utc")
        if not (started <= ready <= reviewers <= completed):
            raise PilotExactTaskPrLifecycleTransactionError(
                "lifecycle transaction timestamps are out of order"
            )
        required_true = (
            "host_transaction_guard_committed",
            "pr_lifecycle_authorization_authenticated",
            "pr_lifecycle_authorization_consumed",
            "exact_pr_revalidated_after_consumption",
            "ready_for_review_completed",
            "reviewer_requests_completed",
            "final_pr_state_verified",
            "remote_write_performed",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrLifecycleTransactionError(
                "lifecycle transaction evidence is incomplete"
            )
        forced_false = (
            "ready_for_review_authorized",
            "reviewer_request_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "product_pilot_started",
            "draft",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrLifecycleTransactionError(
                "completed lifecycle transaction retains forbidden authority/state"
            )
        if (
            not isinstance(self.publisher_credential_id, str)
            or not self.publisher_credential_id
            or "token" in self.to_dict()
        ):
            raise PilotExactTaskPrLifecycleTransactionError(
                "publisher credential identity is invalid"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def transaction_authenticated(self) -> bool:
        return _get_live_transaction_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }
        result["reviewer_usernames"] = list(self.reviewer_usernames)
        result["reviewer_team_slugs"] = list(self.reviewer_team_slugs)
        return result

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrLifecycleTransactionReceipt":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):  # type: ignore[attr-defined]
            raise PilotExactTaskPrLifecycleTransactionError(
                "PR lifecycle transaction receipt fields mismatch"
            )
        data = dict(value)
        if not isinstance(data.get("reviewer_usernames"), list) or not isinstance(
            data.get("reviewer_team_slugs"), list
        ):
            raise PilotExactTaskPrLifecycleTransactionError(
                "lifecycle transaction reviewer sets are invalid"
            )
        data["reviewer_usernames"] = tuple(data["reviewer_usernames"])
        data["reviewer_team_slugs"] = tuple(data["reviewer_team_slugs"])
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _read_bound(path: Path) -> bytes | None:
    try:
        payload = Path(path).read_bytes()
    except OSError:
        return None
    if not payload:
        return None
    return payload


def _live_registry():
    records: dict[
        int,
        tuple[
            int,
            str,
            weakref.ReferenceType[Any],
            weakref.ReferenceType[Any],
            Path,
            bytes,
            Path,
            bytes,
            Path,
            bytes,
            Path,
            bytes,
        ],
    ] = {}

    def mark(
        receipt: Any,
        *,
        authorization: PilotExactTaskPrLifecycleAuthorizationReceipt,
        final_path: Path,
        final_payload: bytes,
        lock_path: Path,
        lock_payload: bytes,
        ready_path: Path,
        ready_payload: bytes,
        reviewers_path: Path,
        reviewers_payload: bytes,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            weakref.ref(authorization),
            final_path,
            final_payload,
            lock_path,
            lock_payload,
            ready_path,
            ready_payload,
            reviewers_path,
            reviewers_payload,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        (
            pid,
            digest,
            receipt_ref,
            authorization_ref,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
            ready_path,
            ready_payload,
            reviewers_path,
            reviewers_payload,
        ) = entry
        authorization = authorization_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or authorization is None
            or receipt.sha256 != digest
            or authorization.authorization_authenticated is not True
            or receipt.pr_lifecycle_authorization_sha256 != authorization.sha256
            or _read_bound(final_path) != final_payload
            or _read_bound(lock_path) != lock_payload
            or _read_bound(ready_path) != ready_payload
            or _read_bound(reviewers_path) != reviewers_payload
        ):
            return None
        return MappingProxyType({"pr_lifecycle_authorization": authorization})

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_transaction_authenticated, _get_live_transaction_inputs = _live_registry()


def _execute_verified_pilot_exact_task_pr_lifecycle(
    *,
    pr_lifecycle_authorization: PilotExactTaskPrLifecycleAuthorizationReceipt,
    ledger: _PilotExactTaskPrLifecycleTransactionLedger,
    transport: Any,
    credential_id: str,
    credential_config_sha256: str,
    credential_path_sha256: str,
    now_provider: Callable[[], str],
) -> PilotExactTaskPrLifecycleTransactionReceipt:
    authorization, _attestation, _config = _require_live_authorization(
        pr_lifecycle_authorization
    )
    if transport is None:
        raise PilotExactTaskPrLifecycleTransactionError(
            "exact lifecycle transport is required"
        )
    for method in ("validate_for", "observe", "mark_ready", "request_reviewers"):
        if not callable(getattr(transport, method, None)):
            raise PilotExactTaskPrLifecycleTransactionError(
                "lifecycle transport is incomplete"
            )
    transport.validate_for(authorization)
    started_at = now_provider()
    started = _utc(started_at, name="started_at_utc")
    if not (
        _utc(authorization.requested_at_utc, name="requested_at_utc")
        <= started
        < _utc(authorization.expires_at_utc, name="expires_at_utc")
    ):
        raise PilotExactTaskPrLifecycleTransactionError(
            "ADR-DC-053 lifecycle authorization expired before execution"
        )

    pre = transport.observe(authorization)
    if type(pre) is not _LifecycleRemoteState:
        raise PilotExactTaskPrLifecycleTransactionError(
            "lifecycle transport returned invalid pre-state"
        )
    _require_pre_state(pre, authorization)

    lock_payload = ledger.acquire(
        authorization=authorization,
        pre_state_sha256=pre.sha256,
        credential_config_sha256=credential_config_sha256,
        credential_path_sha256=credential_path_sha256,
    )
    live_again = _require_live_authorization(authorization)
    if live_again[0] is not authorization:
        raise PilotExactTaskPrLifecycleTransactionError(
            "ADR-DC-053 authority changed after transaction consumption"
        )

    pre_again = transport.observe(authorization)
    if type(pre_again) is not _LifecycleRemoteState:
        raise PilotExactTaskPrLifecycleTransactionError(
            "lifecycle transport returned invalid post-lock state"
        )
    _require_pre_state(pre_again, authorization)
    if pre_again.to_dict() != pre.to_dict():
        raise PilotExactTaskPrLifecycleTransactionError(
            "lifecycle PR state changed after durable consumption"
        )

    node_id = pre.pull_request_node_id
    transport.mark_ready(
        authorization=authorization,
        pull_request_node_id=node_id,
    )
    ready_state = transport.observe(authorization)
    if type(ready_state) is not _LifecycleRemoteState:
        raise PilotExactTaskPrLifecycleTransactionError(
            "lifecycle transport returned invalid ready state"
        )
    _require_ready_state(ready_state, authorization, node_id=node_id)
    ready_at = now_provider()
    ready_payload = ledger.mark_ready(
        authorization=authorization,
        node_id=node_id,
        state_sha256=ready_state.sha256,
        ready_at_utc=ready_at,
    )

    transport.request_reviewers(authorization=authorization)
    final_first = transport.observe(authorization)
    if type(final_first) is not _LifecycleRemoteState:
        raise PilotExactTaskPrLifecycleTransactionError(
            "lifecycle transport returned invalid final state"
        )
    _require_final_state(final_first, authorization, node_id=node_id)
    final_second = transport.observe(authorization)
    if type(final_second) is not _LifecycleRemoteState:
        raise PilotExactTaskPrLifecycleTransactionError(
            "lifecycle transport returned invalid repeated final state"
        )
    _require_final_state(final_second, authorization, node_id=node_id)
    if final_first.to_dict() != final_second.to_dict():
        raise PilotExactTaskPrLifecycleTransactionError(
            "final lifecycle state changed between observations"
        )
    reviewers_requested_at = now_provider()
    reviewers_payload = ledger.mark_reviewers(
        authorization=authorization,
        final_state_sha256=final_first.sha256,
        reviewers_requested_at_utc=reviewers_requested_at,
    )
    completed_at = now_provider()

    receipt = PilotExactTaskPrLifecycleTransactionReceipt(
        transaction_ledger_root_path_sha256=ledger.root_sha256,
        transaction_key_sha256=authorization.execution_nonce_sha256,
        pr_lifecycle_authorization_sha256=authorization.sha256,
        post_publication_attestation_sha256=authorization.post_publication_attestation_sha256,
        lifecycle_config_sha256=authorization.lifecycle_config_sha256,
        reviewer_set_sha256=authorization.reviewer_set_sha256,
        execution_nonce_sha256=authorization.execution_nonce_sha256,
        development_task_sha256=authorization.development_task_sha256,
        candidate_patch_sha256=authorization.candidate_patch_sha256,
        pr_intent_sha256=authorization.pr_intent_sha256,
        repository=authorization.repository,
        repository_id=authorization.repository_id,
        base_branch=authorization.base_branch,
        head_branch=authorization.head_branch,
        predicted_commit_sha=authorization.predicted_commit_sha,
        pull_request_number=authorization.pull_request_number,
        pull_request_api_url=authorization.pull_request_api_url,
        pull_request_node_id_sha256=hashlib.sha256(
            node_id.encode("utf-8")
        ).hexdigest(),
        reviewer_usernames=authorization.reviewer_usernames,
        reviewer_team_slugs=authorization.reviewer_team_slugs,
        publisher_credential_id=credential_id,
        publisher_credential_config_sha256=credential_config_sha256,
        publisher_credential_path_sha256=credential_path_sha256,
        pre_state_sha256=pre.sha256,
        post_ready_state_sha256=ready_state.sha256,
        final_state_sha256=final_first.sha256,
        started_at_utc=started_at,
        ready_at_utc=ready_at,
        reviewers_requested_at_utc=reviewers_requested_at,
        completed_at_utc=completed_at,
    )
    return ledger.commit(
        receipt=receipt,
        authorization=authorization,
        lock_payload=lock_payload,
        ready_payload=ready_payload,
        reviewers_payload=reviewers_payload,
    )


def _canonical_runtime() -> tuple[
    _PilotExactTaskPrLifecycleTransactionLedger,
    _GitHubPrLifecycleTransport,
]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            root = _require_host_controlled_ledger_root(_POSIX_LEDGER)
        elif os.name == "nt":
            root = _require_host_controlled_ledger_root(_WINDOWS_LEDGER)
        else:
            raise PilotExactTaskPrLifecycleTransactionError(
                "PR lifecycle transaction platform is unsupported"
            )
        credential, digest, credential_path = publication_tx_boundary._canonical_credential()
        transport = _GitHubPrLifecycleTransport(
            credential=credential,
            credential_config_sha256=digest,
            credential_path=credential_path,
        )
        return _PilotExactTaskPrLifecycleTransactionLedger(root), transport
    except PhysicalHostStateError as exc:
        raise PilotExactTaskPrLifecycleTransactionError(
            "PR lifecycle transaction runtime is not host-admin controlled"
        ) from exc


def execute_pilot_exact_task_pr_lifecycle(
    pr_lifecycle_authorization: PilotExactTaskPrLifecycleAuthorizationReceipt,
) -> PilotExactTaskPrLifecycleTransactionReceipt:
    """Consume one lifecycle authority and perform only the exact PR lifecycle writes."""
    ledger, transport = _canonical_runtime()
    return _execute_verified_pilot_exact_task_pr_lifecycle(
        pr_lifecycle_authorization=pr_lifecycle_authorization,
        ledger=ledger,
        transport=transport,
        credential_id=transport.credential_id,
        credential_config_sha256=transport.credential_config_sha256,
        credential_path_sha256=transport.credential_path_sha256,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
