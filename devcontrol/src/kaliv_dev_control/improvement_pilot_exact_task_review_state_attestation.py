"""ADR-DC-057 read-only exact GitHub review-state attestation.

This boundary accepts only one fresh live ADR-DC-056 post-lifecycle attestation.
It observes the exact pull request's submitted reviews and review threads through
bounded read-only GitHub GraphQL queries, verifies repository/PR/head identity,
and requires two identical complete observations.

GraphQL uses HTTP POST as its query transport, but this module permits only
operations whose document begins with ``query`` and rejects mutation documents.
No review submission, review dismissal, thread resolution, PR mutation, merge,
release, deployment, or production activation authority is granted.
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
from . import improvement_pilot_exact_task_post_lifecycle_attestation as source_boundary
from . import improvement_pilot_exact_task_pr_lifecycle_recovery as recovery_boundary
from . import improvement_pilot_exact_task_pr_lifecycle_transaction as lifecycle_tx_boundary
from . import improvement_pilot_exact_task_remote_publication_transaction as publication_tx_boundary
from .improvement_pilot_exact_task_post_lifecycle_attestation import (
    PILOT_EXACT_TASK_POST_LIFECYCLE_ATTESTATION_AUTHORITY,
    PilotExactTaskPostLifecycleAttestationReceipt,
)
from .improvement_pilot_exact_task_remote_publication_transaction import (
    PilotExactTaskGitHubPublisherCredential,
)

PILOT_EXACT_TASK_REVIEW_STATE_ATTESTATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-review-state-attestation-receipt/v1"
)
PILOT_EXACT_TASK_REVIEW_STATE_ATTESTATION_AUTHORITY = (
    "host-attested-one-dc-l16-exact-review-state-only"
)
PILOT_EXACT_TASK_REVIEW_STATE_ATTESTATION_SCOPE = (
    "read-only-exact-review-state-verification-v1"
)

_MAX_API_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_PAGES = 20
_PAGE_SIZE = 100
_TIMEOUT_SECONDS = 30.0
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_LOGIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-\[\]]{0,127}$")
_ASSOCIATION = re.compile(r"^[A-Z][A-Z_]{1,63}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_GITHUB_API_ROOT = "https://api.github.com"
_GITHUB_GRAPHQL = "https://api.github.com/graphql"
_REVIEW_STATES = {"APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED"}
_REVIEW_DECISIONS = {"NONE", "APPROVED", "CHANGES_REQUESTED", "REVIEW_REQUIRED"}


class PilotExactTaskReviewStateAttestationError(ValueError):
    """Live source, credential continuity, or exact GitHub review state is unsafe."""


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
        raise PilotExactTaskReviewStateAttestationError(
            "review-state evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskReviewStateAttestationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskReviewStateAttestationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskReviewStateAttestationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskReviewStateAttestationError(f"{name} is invalid") from exc


def _github_utc(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PilotExactTaskReviewStateAttestationError(f"{name} is invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskReviewStateAttestationError(f"{name} is invalid") from exc
    return parsed.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


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
        raise PilotExactTaskReviewStateAttestationError(
            f"{name} is not a canonical branch"
        )
    return value


def _login(value: Any, *, name: str = "reviewer login") -> str:
    if not isinstance(value, str):
        raise PilotExactTaskReviewStateAttestationError(f"{name} is invalid")
    normalized = value.lower()
    if _LOGIN.fullmatch(normalized) is None:
        raise PilotExactTaskReviewStateAttestationError(f"{name} is invalid")
    return normalized


def _reviewer_set_sha256(usernames: tuple[str, ...], teams: tuple[str, ...]) -> str:
    return hashlib.sha256(
        _canonical(
            {
                "reviewer_usernames": list(usernames),
                "reviewer_team_slugs": list(teams),
            }
        ).encode("utf-8")
    ).hexdigest()


def _require_live_post_lifecycle(
    value: Any,
) -> PilotExactTaskPostLifecycleAttestationReceipt:
    if type(value) is not PilotExactTaskPostLifecycleAttestationReceipt:
        raise PilotExactTaskReviewStateAttestationError(
            "exact live ADR-DC-056 post-lifecycle attestation is required"
        )
    try:
        replayed = PilotExactTaskPostLifecycleAttestationReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskReviewStateAttestationError(
            "ADR-DC-056 replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskReviewStateAttestationError(
            "ADR-DC-056 attestation identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_POST_LIFECYCLE_ATTESTATION_AUTHORITY
        or value.attestation_authenticated is not True
        or value.durable_completion_verified is not True
        or value.exact_pr_verified is not True
        or value.ready_for_review_verified is not True
        or value.reviewer_requests_verified is not True
        or value.double_observation_matched is not True
        or value.post_lifecycle_verified is not True
        or value.review_submission_authorized is not False
        or value.review_thread_mutation_authorized is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.draft is not False
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskReviewStateAttestationError(
            "ADR-DC-057 requires one fresh exact read-only ADR-DC-056 attestation"
        )
    live = source_boundary._get_live_post_lifecycle_attestation_inputs(value)
    if live is None:
        raise PilotExactTaskReviewStateAttestationError(
            "ADR-DC-056 live provenance is unavailable"
        )
    if (
        live.get("completion_source") != value.completion_source
        or live.get("completion_source_receipt_sha256")
        != value.completion_source_receipt_sha256
        or live.get("remote_observation_sha256") != value.remote_observation_sha256
    ):
        raise PilotExactTaskReviewStateAttestationError(
            "ADR-DC-056 live provenance no longer matches receipt"
        )
    return value


@dataclass(frozen=True, slots=True)
class _SubmittedReview:
    review_node_id_sha256: str
    reviewer_login: str
    state: str
    submitted_at_utc: str
    commit_sha: str | None
    author_association: str

    def __post_init__(self) -> None:
        _hex64(self.review_node_id_sha256, name="review_node_id_sha256")
        _login(self.reviewer_login)
        if self.state not in _REVIEW_STATES:
            raise PilotExactTaskReviewStateAttestationError(
                "submitted review state is unsupported"
            )
        _utc(self.submitted_at_utc, name="submitted_at_utc")
        if self.commit_sha is not None:
            _hex40(self.commit_sha, name="review commit SHA")
        if (
            not isinstance(self.author_association, str)
            or _ASSOCIATION.fullmatch(self.author_association) is None
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "review author association is invalid"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_node_id_sha256": self.review_node_id_sha256,
            "reviewer_login": self.reviewer_login,
            "state": self.state,
            "submitted_at_utc": self.submitted_at_utc,
            "commit_sha": self.commit_sha,
            "author_association": self.author_association,
        }


@dataclass(frozen=True, slots=True)
class _ReviewThreadState:
    thread_node_id_sha256: str
    path: str
    is_resolved: bool
    is_outdated: bool

    def __post_init__(self) -> None:
        _hex64(self.thread_node_id_sha256, name="thread_node_id_sha256")
        if (
            not isinstance(self.path, str)
            or not self.path
            or len(self.path) > 4096
            or "\x00" in self.path
            or self.path.startswith("/")
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "review-thread path is invalid"
            )
        if not isinstance(self.is_resolved, bool) or not isinstance(
            self.is_outdated, bool
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "review-thread state is invalid"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_node_id_sha256": self.thread_node_id_sha256,
            "path": self.path,
            "is_resolved": self.is_resolved,
            "is_outdated": self.is_outdated,
        }


@dataclass(frozen=True, slots=True)
class _ReviewRemoteState:
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
    maintainer_can_modify: bool
    review_decision: str
    reviews: tuple[_SubmittedReview, ...]
    review_threads: tuple[_ReviewThreadState, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "review-state repository identity is invalid"
            )
        _branch(self.base_branch, name="base_branch")
        _branch(self.head_branch, name="head_branch")
        _hex40(self.base_sha, name="base_sha")
        _hex40(self.head_sha, name="head_sha")
        _hex64(
            self.pull_request_node_id_sha256,
            name="pull_request_node_id_sha256",
        )
        if (
            isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/{self.pull_request_number}"
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "review-state pull-request identity is invalid"
            )
        if self.state != "OPEN" or self.draft is not False:
            raise PilotExactTaskReviewStateAttestationError(
                "review-state pull request must remain open and non-draft"
            )
        if self.maintainer_can_modify is not False:
            raise PilotExactTaskReviewStateAttestationError(
                "maintainer_can_modify must remain false"
            )
        if self.review_decision not in _REVIEW_DECISIONS:
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub review decision is unsupported"
            )
        if list(self.reviews) != sorted(
            self.reviews,
            key=lambda item: (
                item.submitted_at_utc,
                item.review_node_id_sha256,
            ),
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "submitted reviews are not canonical ordered"
            )
        if len({item.review_node_id_sha256 for item in self.reviews}) != len(
            self.reviews
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "submitted review identities are duplicated"
            )
        if list(self.review_threads) != sorted(
            self.review_threads,
            key=lambda item: item.thread_node_id_sha256,
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "review threads are not canonical ordered"
            )
        if len(
            {item.thread_node_id_sha256 for item in self.review_threads}
        ) != len(self.review_threads):
            raise PilotExactTaskReviewStateAttestationError(
                "review-thread identities are duplicated"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "repository_id": self.repository_id,
            "base_branch": self.base_branch,
            "base_sha": self.base_sha,
            "head_branch": self.head_branch,
            "head_sha": self.head_sha,
            "pull_request_number": self.pull_request_number,
            "pull_request_api_url": self.pull_request_api_url,
            "pull_request_node_id_sha256": self.pull_request_node_id_sha256,
            "state": self.state,
            "draft": self.draft,
            "maintainer_can_modify": self.maintainer_can_modify,
            "review_decision": self.review_decision,
            "reviews": [item.to_dict() for item in self.reviews],
            "review_threads": [item.to_dict() for item in self.review_threads],
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict()).encode("utf-8")).hexdigest()

    @property
    def reviews_sha256(self) -> str:
        return hashlib.sha256(
            _canonical([item.to_dict() for item in self.reviews]).encode("utf-8")
        ).hexdigest()

    @property
    def review_threads_sha256(self) -> str:
        return hashlib.sha256(
            _canonical([item.to_dict() for item in self.review_threads]).encode("utf-8")
        ).hexdigest()

    @property
    def approved_review_count(self) -> int:
        return sum(item.state == "APPROVED" for item in self.reviews)

    @property
    def changes_requested_review_count(self) -> int:
        return sum(item.state == "CHANGES_REQUESTED" for item in self.reviews)

    @property
    def commented_review_count(self) -> int:
        return sum(item.state == "COMMENTED" for item in self.reviews)

    @property
    def dismissed_review_count(self) -> int:
        return sum(item.state == "DISMISSED" for item in self.reviews)

    @property
    def exact_head_approved_review_count(self) -> int:
        return sum(
            item.state == "APPROVED" and item.commit_sha == self.head_sha
            for item in self.reviews
        )

    @property
    def exact_head_changes_requested_review_count(self) -> int:
        return sum(
            item.state == "CHANGES_REQUESTED" and item.commit_sha == self.head_sha
            for item in self.reviews
        )

    @property
    def unresolved_review_thread_count(self) -> int:
        return sum(not item.is_resolved for item in self.review_threads)

    @property
    def unresolved_outdated_review_thread_count(self) -> int:
        return sum(
            not item.is_resolved and item.is_outdated for item in self.review_threads
        )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class _GitHubReviewStateTransport:
    """Bounded GraphQL query transport for exact reviews and review threads."""

    def __init__(
        self,
        *,
        credential: PilotExactTaskGitHubPublisherCredential,
        credential_config_sha256: str,
        credential_path: Path,
    ) -> None:
        if type(credential) is not PilotExactTaskGitHubPublisherCredential:
            raise PilotExactTaskReviewStateAttestationError(
                "exact repository-bound GitHub credential is required"
            )
        self.credential = credential
        self.credential_id = credential.credential_id
        self.credential_config_sha256 = _hex64(
            credential_config_sha256,
            name="publisher credential config digest",
        )
        self.credential_path = Path(credential_path)
        if not self.credential_path.is_absolute():
            raise PilotExactTaskReviewStateAttestationError(
                "publisher credential path is not absolute"
            )
        self.credential_path_sha256 = _path_sha256(self.credential_path)
        self._opener = urllib.request.build_opener(_NoRedirect())

    def validate_for(
        self, attestation: PilotExactTaskPostLifecycleAttestationReceipt
    ) -> None:
        if (
            self.credential.repository != attestation.repository
            or self.credential.repository_id != attestation.repository_id
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub query credential is not bound to exact repository"
            )

    def _rest_json(self, *, path: str) -> Mapping[str, Any]:
        if (
            not isinstance(path, str)
            or not path.startswith("/repos/")
            or ".." in path
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "review-state REST query is outside exact GitHub scope"
            )
        url = _GITHUB_API_ROOT + path
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.credential.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ModelRig-DevControl-ReviewState/1",
            },
        )
        try:
            response = self._opener.open(request, timeout=_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            raise PilotExactTaskReviewStateAttestationError(
                f"GitHub review-state REST query failed with HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub review-state REST query failed"
            ) from exc
        with response:
            if response.status != 200 or response.geturl() != url:
                raise PilotExactTaskReviewStateAttestationError(
                    "GitHub review-state REST response identity/status is unexpected"
                )
            raw = response.read(_MAX_API_RESPONSE_BYTES + 1)
        if not raw or len(raw) > _MAX_API_RESPONSE_BYTES:
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub review-state REST response size is invalid"
            )
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub review-state REST response is invalid JSON"
            ) from exc
        if not isinstance(value, Mapping):
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub review-state REST response is not an object"
            )
        return value

    def _graphql_query(
        self, *, query: str, variables: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        normalized = query.lstrip()
        if (
            not normalized.startswith("query ")
            or "mutation" in normalized.lower()
            or "__schema" in normalized
            or "__type" in normalized
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "only explicit read-only GitHub GraphQL queries are allowed"
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
                "User-Agent": "ModelRig-DevControl-ReviewState/1",
            },
        )
        try:
            response = self._opener.open(request, timeout=_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            raise PilotExactTaskReviewStateAttestationError(
                f"GitHub review-state GraphQL query failed with HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub review-state GraphQL query failed"
            ) from exc
        with response:
            if response.status != 200 or response.geturl() != _GITHUB_GRAPHQL:
                raise PilotExactTaskReviewStateAttestationError(
                    "GitHub review-state GraphQL response identity/status is unexpected"
                )
            raw = response.read(_MAX_API_RESPONSE_BYTES + 1)
        if not raw or len(raw) > _MAX_API_RESPONSE_BYTES:
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub review-state GraphQL response size is invalid"
            )
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub review-state GraphQL response is invalid JSON"
            ) from exc
        if (
            not isinstance(value, Mapping)
            or value.get("errors") not in (None, [])
            or not isinstance(value.get("data"), Mapping)
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub review-state GraphQL query returned errors"
            )
        return value["data"]

    @staticmethod
    def _variables(
        attestation: PilotExactTaskPostLifecycleAttestationReceipt,
        cursor: str | None,
    ) -> dict[str, Any]:
        owner, repo = attestation.repository.split("/", 1)
        return {
            "owner": owner,
            "repo": repo,
            "number": attestation.pull_request_number,
            "cursor": cursor,
        }

    @staticmethod
    def _identity(
        *,
        repository: Mapping[str, Any],
        pull_request: Mapping[str, Any],
        attestation: PilotExactTaskPostLifecycleAttestationReceipt,
    ) -> dict[str, Any]:
        if repository.get("nameWithOwner") != attestation.repository:
            raise PilotExactTaskReviewStateAttestationError(
                "GraphQL repository identity changed"
            )
        node_id = pull_request.get("id")
        if not isinstance(node_id, str) or not node_id:
            raise PilotExactTaskReviewStateAttestationError(
                "GraphQL pull-request node identity is missing"
            )
        node_sha = hashlib.sha256(node_id.encode("utf-8")).hexdigest()
        decision = pull_request.get("reviewDecision")
        normalized_decision = "NONE" if decision is None else decision
        identity = {
            "base_branch": pull_request.get("baseRefName"),
            "base_sha": pull_request.get("baseRefOid"),
            "head_branch": pull_request.get("headRefName"),
            "head_sha": pull_request.get("headRefOid"),
            "pull_request_number": pull_request.get("number"),
            "pull_request_node_id_sha256": node_sha,
            "state": pull_request.get("state"),
            "draft": pull_request.get("isDraft"),
            "maintainer_can_modify": pull_request.get("maintainerCanModify"),
            "review_decision": normalized_decision,
        }
        if (
            identity["base_branch"] != attestation.base_branch
            or identity["base_sha"] != attestation.exact_task_base_sha
            or identity["head_branch"] != attestation.head_branch
            or identity["head_sha"] != attestation.predicted_commit_sha
            or identity["pull_request_number"] != attestation.pull_request_number
            or identity["pull_request_node_id_sha256"]
            != attestation.pull_request_node_id_sha256
            or identity["state"] != "OPEN"
            or identity["draft"] is not False
            or identity["maintainer_can_modify"] is not False
            or normalized_decision not in _REVIEW_DECISIONS
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub review-state PR identity no longer equals ADR-DC-056"
            )
        return identity

    @staticmethod
    def _page_info(connection: Any, *, name: str) -> tuple[bool, str | None]:
        if not isinstance(connection, Mapping):
            raise PilotExactTaskReviewStateAttestationError(
                f"{name} connection is invalid"
            )
        page_info = connection.get("pageInfo")
        if not isinstance(page_info, Mapping):
            raise PilotExactTaskReviewStateAttestationError(
                f"{name} pageInfo is invalid"
            )
        has_next = page_info.get("hasNextPage")
        cursor = page_info.get("endCursor")
        if not isinstance(has_next, bool):
            raise PilotExactTaskReviewStateAttestationError(
                f"{name} pagination flag is invalid"
            )
        if has_next and (not isinstance(cursor, str) or not cursor):
            raise PilotExactTaskReviewStateAttestationError(
                f"{name} pagination cursor is missing"
            )
        if not has_next and cursor is not None and not isinstance(cursor, str):
            raise PilotExactTaskReviewStateAttestationError(
                f"{name} pagination cursor is invalid"
            )
        return has_next, cursor

    @staticmethod
    def _parse_review(value: Any) -> _SubmittedReview | None:
        if not isinstance(value, Mapping):
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub submitted review is invalid"
            )
        state = value.get("state")
        submitted = value.get("submittedAt")
        if state == "PENDING" and submitted is None:
            return None
        if state not in _REVIEW_STATES or submitted is None:
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub review is neither pending nor a supported submitted review"
            )
        node_id = value.get("id")
        author = value.get("author")
        if (
            not isinstance(node_id, str)
            or not node_id
            or not isinstance(author, Mapping)
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub submitted review identity is invalid"
            )
        commit = value.get("commit")
        commit_sha = None
        if commit is not None:
            if not isinstance(commit, Mapping):
                raise PilotExactTaskReviewStateAttestationError(
                    "GitHub review commit is invalid"
                )
            commit_sha = _hex40(commit.get("oid"), name="review commit SHA")
        association = value.get("authorAssociation")
        if (
            not isinstance(association, str)
            or _ASSOCIATION.fullmatch(association) is None
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub review author association is invalid"
            )
        return _SubmittedReview(
            review_node_id_sha256=hashlib.sha256(
                node_id.encode("utf-8")
            ).hexdigest(),
            reviewer_login=_login(author.get("login")),
            state=state,
            submitted_at_utc=_github_utc(
                submitted, name="GitHub review submittedAt"
            ),
            commit_sha=commit_sha,
            author_association=association,
        )

    @staticmethod
    def _parse_thread(value: Any) -> _ReviewThreadState:
        if not isinstance(value, Mapping):
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub review thread is invalid"
            )
        node_id = value.get("id")
        if not isinstance(node_id, str) or not node_id:
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub review-thread identity is invalid"
            )
        return _ReviewThreadState(
            thread_node_id_sha256=hashlib.sha256(
                node_id.encode("utf-8")
            ).hexdigest(),
            path=value.get("path"),
            is_resolved=value.get("isResolved"),
            is_outdated=value.get("isOutdated"),
        )

    def _reviews(
        self, attestation: PilotExactTaskPostLifecycleAttestationReceipt
    ) -> tuple[dict[str, Any], tuple[_SubmittedReview, ...]]:
        query = (
            "query ReviewStateReviews($owner:String!,$repo:String!,$number:Int!,$cursor:String){"
            "repository(owner:$owner,name:$repo){nameWithOwner pullRequest(number:$number){"
            "id number state isDraft maintainerCanModify baseRefName baseRefOid "
            "headRefName headRefOid reviewDecision "
            "reviews(first:100,after:$cursor){nodes{"
            "id author{login} authorAssociation state submittedAt commit{oid}"
            "} pageInfo{hasNextPage endCursor}}}}}"
        )
        cursor = None
        identity = None
        items: list[_SubmittedReview] = []
        for _page in range(_MAX_PAGES):
            data = self._graphql_query(
                query=query,
                variables=self._variables(attestation, cursor),
            )
            repository = data.get("repository")
            pr = repository.get("pullRequest") if isinstance(repository, Mapping) else None
            if not isinstance(repository, Mapping) or not isinstance(pr, Mapping):
                raise PilotExactTaskReviewStateAttestationError(
                    "GitHub review query did not return exact pull request"
                )
            current_identity = self._identity(
                repository=repository,
                pull_request=pr,
                attestation=attestation,
            )
            if identity is None:
                identity = current_identity
            elif identity != current_identity:
                raise PilotExactTaskReviewStateAttestationError(
                    "pull-request identity changed during review pagination"
                )
            connection = pr.get("reviews")
            nodes = connection.get("nodes") if isinstance(connection, Mapping) else None
            if not isinstance(nodes, list):
                raise PilotExactTaskReviewStateAttestationError(
                    "GitHub review nodes are invalid"
                )
            for node in nodes:
                parsed = self._parse_review(node)
                if parsed is not None:
                    items.append(parsed)
            has_next, cursor = self._page_info(connection, name="reviews")
            if not has_next:
                break
        else:
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub review pagination exceeded bounded limit"
            )
        if identity is None:
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub review identity was not observed"
            )
        ordered = tuple(
            sorted(
                items,
                key=lambda item: (
                    item.submitted_at_utc,
                    item.review_node_id_sha256,
                ),
            )
        )
        if len({item.review_node_id_sha256 for item in ordered}) != len(ordered):
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub review pagination returned duplicate reviews"
            )
        return identity, ordered

    def _threads(
        self, attestation: PilotExactTaskPostLifecycleAttestationReceipt
    ) -> tuple[dict[str, Any], tuple[_ReviewThreadState, ...]]:
        query = (
            "query ReviewStateThreads($owner:String!,$repo:String!,$number:Int!,$cursor:String){"
            "repository(owner:$owner,name:$repo){nameWithOwner pullRequest(number:$number){"
            "id number state isDraft maintainerCanModify baseRefName baseRefOid "
            "headRefName headRefOid reviewDecision "
            "reviewThreads(first:100,after:$cursor){nodes{"
            "id isResolved isOutdated path"
            "} pageInfo{hasNextPage endCursor}}}}}"
        )
        cursor = None
        identity = None
        items: list[_ReviewThreadState] = []
        for _page in range(_MAX_PAGES):
            data = self._graphql_query(
                query=query,
                variables=self._variables(attestation, cursor),
            )
            repository = data.get("repository")
            pr = repository.get("pullRequest") if isinstance(repository, Mapping) else None
            if not isinstance(repository, Mapping) or not isinstance(pr, Mapping):
                raise PilotExactTaskReviewStateAttestationError(
                    "GitHub thread query did not return exact pull request"
                )
            current_identity = self._identity(
                repository=repository,
                pull_request=pr,
                attestation=attestation,
            )
            if identity is None:
                identity = current_identity
            elif identity != current_identity:
                raise PilotExactTaskReviewStateAttestationError(
                    "pull-request identity changed during thread pagination"
                )
            connection = pr.get("reviewThreads")
            nodes = connection.get("nodes") if isinstance(connection, Mapping) else None
            if not isinstance(nodes, list):
                raise PilotExactTaskReviewStateAttestationError(
                    "GitHub review-thread nodes are invalid"
                )
            items.extend(self._parse_thread(node) for node in nodes)
            has_next, cursor = self._page_info(connection, name="reviewThreads")
            if not has_next:
                break
        else:
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub review-thread pagination exceeded bounded limit"
            )
        if identity is None:
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub review-thread identity was not observed"
            )
        ordered = tuple(
            sorted(items, key=lambda item: item.thread_node_id_sha256)
        )
        if len({item.thread_node_id_sha256 for item in ordered}) != len(ordered):
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub review-thread pagination returned duplicates"
            )
        return identity, ordered

    def observe(
        self, attestation: PilotExactTaskPostLifecycleAttestationReceipt
    ) -> _ReviewRemoteState:
        self.validate_for(attestation)
        owner, repo = attestation.repository.split("/", 1)
        repo_value = self._rest_json(
            path=(
                f"/repos/{urllib.parse.quote(owner, safe='')}/"
                f"{urllib.parse.quote(repo, safe='')}"
            )
        )
        if (
            str(repo_value.get("id")) != attestation.repository_id
            or repo_value.get("full_name") != attestation.repository
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub REST repository identity no longer matches ADR-DC-056"
            )
        review_identity, reviews = self._reviews(attestation)
        thread_identity, threads = self._threads(attestation)
        if review_identity != thread_identity:
            raise PilotExactTaskReviewStateAttestationError(
                "review and thread queries disagree on pull-request identity"
            )
        return _ReviewRemoteState(
            repository=attestation.repository,
            repository_id=attestation.repository_id,
            base_branch=review_identity["base_branch"],
            base_sha=review_identity["base_sha"],
            head_branch=review_identity["head_branch"],
            head_sha=review_identity["head_sha"],
            pull_request_number=review_identity["pull_request_number"],
            pull_request_api_url=attestation.pull_request_api_url,
            pull_request_node_id_sha256=review_identity[
                "pull_request_node_id_sha256"
            ],
            state=review_identity["state"],
            draft=review_identity["draft"],
            maintainer_can_modify=review_identity["maintainer_can_modify"],
            review_decision=review_identity["review_decision"],
            reviews=reviews,
            review_threads=threads,
        )


def _credential_continuity(
    *,
    attestation: PilotExactTaskPostLifecycleAttestationReceipt,
    transaction_ledger_root: Path,
    publisher_credential_config_sha256: str,
    publisher_credential_path_sha256: str,
) -> None:
    ledger = lifecycle_tx_boundary._PilotExactTaskPrLifecycleTransactionLedger(
        _safe_ledger_root(transaction_ledger_root)
    )
    _final, lock, _ready, _reviewers = ledger._paths(
        attestation.execution_nonce_sha256
    )
    try:
        raw, payload = recovery_boundary._read_canonical_object(
            lock, name="ADR-DC-054 lifecycle transaction lock"
        )
    except Exception as exc:
        raise PilotExactTaskReviewStateAttestationError(
            "ADR-DC-054 transaction lock is unavailable"
        ) from exc
    if hashlib.sha256(payload).hexdigest() != attestation.transaction_lock_sha256:
        raise PilotExactTaskReviewStateAttestationError(
            "ADR-DC-054 transaction lock hash differs from ADR-DC-056"
        )
    expected = {
        "schema",
        "ledger_scope",
        "ledger_root_path_sha256",
        "transaction_key_sha256",
        "pr_lifecycle_authorization_sha256",
        "post_publication_attestation_sha256",
        "lifecycle_config_sha256",
        "reviewer_set_sha256",
        "pull_request_number",
        "predicted_commit_sha",
        "pre_state_sha256",
        "publisher_credential_config_sha256",
        "publisher_credential_path_sha256",
    }
    if (
        set(raw) != expected
        or raw.get("schema")
        != "kaliv-rsi-dc-l16-exact-task-pr-lifecycle-transaction-lock/v1"
        or raw.get("ledger_scope")
        != lifecycle_tx_boundary.PILOT_EXACT_TASK_PR_LIFECYCLE_TRANSACTION_LEDGER_SCOPE
        or raw.get("ledger_root_path_sha256") != ledger.root_sha256
        or raw.get("transaction_key_sha256") != attestation.execution_nonce_sha256
        or raw.get("pr_lifecycle_authorization_sha256")
        != attestation.pr_lifecycle_authorization_sha256
        or raw.get("post_publication_attestation_sha256")
        != attestation.post_publication_attestation_sha256
        or raw.get("lifecycle_config_sha256") != attestation.lifecycle_config_sha256
        or raw.get("reviewer_set_sha256") != attestation.reviewer_set_sha256
        or raw.get("pull_request_number") != attestation.pull_request_number
        or raw.get("predicted_commit_sha") != attestation.predicted_commit_sha
        or raw.get("publisher_credential_config_sha256")
        != publisher_credential_config_sha256
        or raw.get("publisher_credential_path_sha256")
        != publisher_credential_path_sha256
    ):
        raise PilotExactTaskReviewStateAttestationError(
            "current GitHub review credential does not equal ADR-DC-054 custody binding"
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
            str,
        ],
    ] = {}

    def mark(
        receipt: Any,
        *,
        source: PilotExactTaskPostLifecycleAttestationReceipt,
        review_state_sha256: str,
        credential_config_sha256: str,
        credential_path_sha256: str,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            weakref.ref(source),
            review_state_sha256,
            credential_config_sha256,
            credential_path_sha256,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        (
            pid,
            digest,
            receipt_ref,
            source_ref,
            review_state_sha256,
            credential_config_sha256,
            credential_path_sha256,
        ) = entry
        source = source_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or source is None
            or receipt.sha256 != digest
            or source.attestation_authenticated is not True
            or source.sha256 != receipt.post_lifecycle_attestation_sha256
            or receipt.review_state_sha256 != review_state_sha256
            or receipt.publisher_credential_config_sha256
            != credential_config_sha256
            or receipt.publisher_credential_path_sha256
            != credential_path_sha256
        ):
            return None
        return MappingProxyType(
            {
                "post_lifecycle_attestation": source,
                "review_state_sha256": review_state_sha256,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_review_state_attestation_authenticated,
    _get_live_review_state_attestation_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskReviewStateAttestationReceipt:
    post_lifecycle_attestation_sha256: str
    completion_source_receipt_sha256: str
    pr_lifecycle_authorization_sha256: str
    lifecycle_config_sha256: str
    reviewer_set_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    transaction_lock_sha256: str
    post_lifecycle_remote_observation_sha256: str
    review_state_sha256: str
    reviews_sha256: str
    review_threads_sha256: str
    repository: str
    repository_id: str
    base_branch: str
    head_branch: str
    exact_task_base_sha: str
    predicted_commit_sha: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_node_id_sha256: str
    authorized_reviewer_usernames: tuple[str, ...]
    authorized_reviewer_team_slugs: tuple[str, ...]
    publisher_credential_id: str
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    github_review_decision: str
    submitted_review_count: int
    approved_review_count: int
    changes_requested_review_count: int
    commented_review_count: int
    dismissed_review_count: int
    exact_head_approved_review_count: int
    exact_head_changes_requested_review_count: int
    review_thread_count: int
    unresolved_review_thread_count: int
    unresolved_outdated_review_thread_count: int
    post_lifecycle_attested_at_utc: str
    observed_at_utc: str
    post_lifecycle_attestation_authenticated: bool = True
    exact_pr_revalidated: bool = True
    submitted_reviews_observed: bool = True
    review_threads_observed: bool = True
    double_observation_matched: bool = True
    review_state_attested: bool = True
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    merge_readiness_authorized: bool = False
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
    attestation_scope: str = PILOT_EXACT_TASK_REVIEW_STATE_ATTESTATION_SCOPE
    authority: str = PILOT_EXACT_TASK_REVIEW_STATE_ATTESTATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_REVIEW_STATE_ATTESTATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_REVIEW_STATE_ATTESTATION_SCHEMA
            or self.authority != PILOT_EXACT_TASK_REVIEW_STATE_ATTESTATION_AUTHORITY
            or self.attestation_scope != PILOT_EXACT_TASK_REVIEW_STATE_ATTESTATION_SCOPE
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "review-state attestation identity is unsupported"
            )
        for name in (
            "post_lifecycle_attestation_sha256",
            "completion_source_receipt_sha256",
            "pr_lifecycle_authorization_sha256",
            "lifecycle_config_sha256",
            "reviewer_set_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
            "transaction_lock_sha256",
            "post_lifecycle_remote_observation_sha256",
            "review_state_sha256",
            "reviews_sha256",
            "review_threads_sha256",
            "pull_request_node_id_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.exact_task_base_sha, name="exact_task_base_sha")
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "review-state repository identity is invalid"
            )
        _branch(self.base_branch, name="base_branch")
        _branch(self.head_branch, name="head_branch")
        if (
            isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/{self.pull_request_number}"
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "review-state pull-request identity is invalid"
            )
        if self.github_review_decision not in _REVIEW_DECISIONS:
            raise PilotExactTaskReviewStateAttestationError(
                "review-state decision is unsupported"
            )
        if (
            not isinstance(self.publisher_credential_id, str)
            or not self.publisher_credential_id
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "publisher credential identity is invalid"
            )
        if (
            list(self.authorized_reviewer_usernames)
            != sorted(set(self.authorized_reviewer_usernames))
            or list(self.authorized_reviewer_team_slugs)
            != sorted(set(self.authorized_reviewer_team_slugs))
            or (
                not self.authorized_reviewer_usernames
                and not self.authorized_reviewer_team_slugs
            )
            or _reviewer_set_sha256(
                self.authorized_reviewer_usernames,
                self.authorized_reviewer_team_slugs,
            )
            != self.reviewer_set_sha256
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "authorized reviewer set is invalid"
            )
        counts = (
            self.submitted_review_count,
            self.approved_review_count,
            self.changes_requested_review_count,
            self.commented_review_count,
            self.dismissed_review_count,
            self.exact_head_approved_review_count,
            self.exact_head_changes_requested_review_count,
            self.review_thread_count,
            self.unresolved_review_thread_count,
            self.unresolved_outdated_review_thread_count,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counts
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "review-state counts are invalid"
            )
        if (
            self.approved_review_count
            + self.changes_requested_review_count
            + self.commented_review_count
            + self.dismissed_review_count
            != self.submitted_review_count
            or self.exact_head_approved_review_count > self.approved_review_count
            or self.exact_head_changes_requested_review_count
            > self.changes_requested_review_count
            or self.unresolved_review_thread_count > self.review_thread_count
            or self.unresolved_outdated_review_thread_count
            > self.unresolved_review_thread_count
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "review-state counts are inconsistent"
            )
        source_time = _utc(
            self.post_lifecycle_attested_at_utc,
            name="post_lifecycle_attested_at_utc",
        )
        observed = _utc(self.observed_at_utc, name="observed_at_utc")
        if observed < source_time:
            raise PilotExactTaskReviewStateAttestationError(
                "review-state attestation predates ADR-DC-056"
            )
        required_true = (
            "post_lifecycle_attestation_authenticated",
            "exact_pr_revalidated",
            "submitted_reviews_observed",
            "review_threads_observed",
            "double_observation_matched",
            "review_state_attested",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskReviewStateAttestationError(
                "review-state attestation evidence is incomplete"
            )
        forced_false = (
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "merge_readiness_authorized",
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
            raise PilotExactTaskReviewStateAttestationError(
                "read-only review-state attestation retains forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def attestation_authenticated(self) -> bool:
        return _get_live_review_state_attestation_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }
        result["authorized_reviewer_usernames"] = list(
            self.authorized_reviewer_usernames
        )
        result["authorized_reviewer_team_slugs"] = list(
            self.authorized_reviewer_team_slugs
        )
        return result

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskReviewStateAttestationReceipt":
        if (
            not isinstance(value, Mapping)
            or set(value) != set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        ):
            raise PilotExactTaskReviewStateAttestationError(
                "review-state attestation fields mismatch"
            )
        data = dict(value)
        if not isinstance(
            data.get("authorized_reviewer_usernames"), list
        ) or not isinstance(data.get("authorized_reviewer_team_slugs"), list):
            raise PilotExactTaskReviewStateAttestationError(
                "review-state authorized reviewer sets are invalid"
            )
        data["authorized_reviewer_usernames"] = tuple(
            data["authorized_reviewer_usernames"]
        )
        data["authorized_reviewer_team_slugs"] = tuple(
            data["authorized_reviewer_team_slugs"]
        )
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _attest_verified_pilot_exact_task_review_state(
    *,
    post_lifecycle_attestation: PilotExactTaskPostLifecycleAttestationReceipt,
    transaction_ledger_root: Path,
    transport: Any,
    publisher_credential_id: str,
    publisher_credential_config_sha256: str,
    publisher_credential_path_sha256: str,
    now_provider: Callable[[], str],
) -> PilotExactTaskReviewStateAttestationReceipt:
    source = _require_live_post_lifecycle(post_lifecycle_attestation)
    config_sha = _hex64(
        publisher_credential_config_sha256,
        name="publisher credential config digest",
    )
    path_sha = _hex64(
        publisher_credential_path_sha256,
        name="publisher credential path digest",
    )
    _credential_continuity(
        attestation=source,
        transaction_ledger_root=transaction_ledger_root,
        publisher_credential_config_sha256=config_sha,
        publisher_credential_path_sha256=path_sha,
    )
    if transport is None:
        raise PilotExactTaskReviewStateAttestationError(
            "read-only GitHub review-state transport is required"
        )
    for method in ("validate_for", "observe"):
        if not callable(getattr(transport, method, None)):
            raise PilotExactTaskReviewStateAttestationError(
                "GitHub review-state transport is incomplete"
            )
    transport.validate_for(source)
    first = transport.observe(source)
    second = transport.observe(source)
    if type(first) is not _ReviewRemoteState or type(second) is not _ReviewRemoteState:
        raise PilotExactTaskReviewStateAttestationError(
            "GitHub review-state transport returned invalid state"
        )
    if first.to_dict() != second.to_dict():
        raise PilotExactTaskReviewStateAttestationError(
            "GitHub review state changed between exact observations"
        )
    if (
        first.repository != source.repository
        or first.repository_id != source.repository_id
        or first.base_branch != source.base_branch
        or first.base_sha != source.exact_task_base_sha
        or first.head_branch != source.head_branch
        or first.head_sha != source.predicted_commit_sha
        or first.pull_request_number != source.pull_request_number
        or first.pull_request_api_url != source.pull_request_api_url
        or first.pull_request_node_id_sha256
        != source.pull_request_node_id_sha256
    ):
        raise PilotExactTaskReviewStateAttestationError(
            "review-state observation is not bound to exact ADR-DC-056 PR"
        )
    observed_at = now_provider()
    if _utc(observed_at, name="observed_at_utc") < _utc(
        source.attested_at_utc,
        name="post_lifecycle_attested_at_utc",
    ):
        raise PilotExactTaskReviewStateAttestationError(
            "system clock moved backwards after ADR-DC-056"
        )
    receipt = PilotExactTaskReviewStateAttestationReceipt(
        post_lifecycle_attestation_sha256=source.sha256,
        completion_source_receipt_sha256=source.completion_source_receipt_sha256,
        pr_lifecycle_authorization_sha256=source.pr_lifecycle_authorization_sha256,
        lifecycle_config_sha256=source.lifecycle_config_sha256,
        reviewer_set_sha256=source.reviewer_set_sha256,
        execution_nonce_sha256=source.execution_nonce_sha256,
        development_task_sha256=source.development_task_sha256,
        candidate_patch_sha256=source.candidate_patch_sha256,
        pr_intent_sha256=source.pr_intent_sha256,
        transaction_lock_sha256=source.transaction_lock_sha256,
        post_lifecycle_remote_observation_sha256=source.remote_observation_sha256,
        review_state_sha256=first.sha256,
        reviews_sha256=first.reviews_sha256,
        review_threads_sha256=first.review_threads_sha256,
        repository=source.repository,
        repository_id=source.repository_id,
        base_branch=source.base_branch,
        head_branch=source.head_branch,
        exact_task_base_sha=source.exact_task_base_sha,
        predicted_commit_sha=source.predicted_commit_sha,
        pull_request_number=source.pull_request_number,
        pull_request_api_url=source.pull_request_api_url,
        pull_request_node_id_sha256=source.pull_request_node_id_sha256,
        authorized_reviewer_usernames=source.reviewer_usernames,
        authorized_reviewer_team_slugs=source.reviewer_team_slugs,
        publisher_credential_id=publisher_credential_id,
        publisher_credential_config_sha256=config_sha,
        publisher_credential_path_sha256=path_sha,
        github_review_decision=first.review_decision,
        submitted_review_count=len(first.reviews),
        approved_review_count=first.approved_review_count,
        changes_requested_review_count=first.changes_requested_review_count,
        commented_review_count=first.commented_review_count,
        dismissed_review_count=first.dismissed_review_count,
        exact_head_approved_review_count=first.exact_head_approved_review_count,
        exact_head_changes_requested_review_count=(
            first.exact_head_changes_requested_review_count
        ),
        review_thread_count=len(first.review_threads),
        unresolved_review_thread_count=first.unresolved_review_thread_count,
        unresolved_outdated_review_thread_count=(
            first.unresolved_outdated_review_thread_count
        ),
        post_lifecycle_attested_at_utc=source.attested_at_utc,
        observed_at_utc=observed_at,
    )
    _mark_review_state_attestation_authenticated(
        receipt,
        source=source,
        review_state_sha256=first.sha256,
        credential_config_sha256=config_sha,
        credential_path_sha256=path_sha,
    )
    if receipt.attestation_authenticated is not True:
        raise PilotExactTaskReviewStateAttestationError(
            "review-state attestation lost live provenance"
        )
    return receipt


def _canonical_runtime() -> tuple[
    Path,
    _GitHubReviewStateTransport,
    str,
    str,
    str,
]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            root = _require_host_controlled_ledger_root(
                lifecycle_tx_boundary._POSIX_LEDGER
            )
        elif os.name == "nt":
            root = _require_host_controlled_ledger_root(
                lifecycle_tx_boundary._WINDOWS_LEDGER
            )
        else:
            raise PilotExactTaskReviewStateAttestationError(
                "review-state attestation is unsupported on this platform"
            )
        credential, digest, path = publication_tx_boundary._canonical_credential()
        transport = _GitHubReviewStateTransport(
            credential=credential,
            credential_config_sha256=digest,
            credential_path=path,
        )
        return (
            root,
            transport,
            transport.credential_id,
            transport.credential_config_sha256,
            transport.credential_path_sha256,
        )
    except PhysicalHostStateError as exc:
        raise PilotExactTaskReviewStateAttestationError(
            "review-state runtime is not host-admin controlled"
        ) from exc


def attest_pilot_exact_task_review_state(
    post_lifecycle_attestation: PilotExactTaskPostLifecycleAttestationReceipt,
) -> PilotExactTaskReviewStateAttestationReceipt:
    """Read-only attest exact submitted reviews and review-thread state."""
    try:
        (
            tx_root,
            transport,
            credential_id,
            credential_config_sha256,
            credential_path_sha256,
        ) = _canonical_runtime()
        return _attest_verified_pilot_exact_task_review_state(
            post_lifecycle_attestation=post_lifecycle_attestation,
            transaction_ledger_root=tx_root,
            transport=transport,
            publisher_credential_id=credential_id,
            publisher_credential_config_sha256=credential_config_sha256,
            publisher_credential_path_sha256=credential_path_sha256,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskReviewStateAttestationError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskReviewStateAttestationError(
            "exact review-state attestation failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_REVIEW_STATE_ATTESTATION_SCHEMA",
    "PILOT_EXACT_TASK_REVIEW_STATE_ATTESTATION_AUTHORITY",
    "PILOT_EXACT_TASK_REVIEW_STATE_ATTESTATION_SCOPE",
    "PilotExactTaskReviewStateAttestationError",
    "PilotExactTaskReviewStateAttestationReceipt",
    "attest_pilot_exact_task_review_state",
]
