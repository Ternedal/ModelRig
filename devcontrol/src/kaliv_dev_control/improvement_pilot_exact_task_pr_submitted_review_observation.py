"""ADR-DC-078 read-only exact submitted-review observation.

Loads one restart-safe ADR-DC-077 checkpoint, freshly revalidates the exact
pull-request identity/head and observes submitted GitHub reviews through
bounded credential-free GETs to fixed api.github.com. Two complete observations
must match exactly. This boundary reports evidence only; review policy and all
mutation authority remain separate.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping

from .github_read import GitHubReadError, HttpResponse, ReadOnlyTransport, UrllibReadOnlyTransport
from . import improvement_pilot_exact_task_pr_review_observation_checkpoint as checkpoint_boundary
from .improvement_pilot_exact_task_pr_review_observation_checkpoint import (
    PILOT_EXACT_TASK_PR_REVIEW_OBSERVATION_CHECKPOINT_AUTHORITY,
    PilotExactTaskPrReviewObservationCheckpoint,
)

PILOT_EXACT_TASK_PR_SUBMITTED_REVIEW_OBSERVATION_SCHEMA = "kaliv-rsi-dc-l16-exact-task-pr-submitted-review-observation/v1"
PILOT_EXACT_TASK_PR_SUBMITTED_REVIEW_OBSERVATION_AUTHORITY = "observed-one-dc-l16-exact-pr-submitted-review-state-only"
PILOT_EXACT_TASK_PR_SUBMITTED_REVIEW_OBSERVATION_SCOPE = "credential-free-stable-exact-head-submitted-reviews-v1"
PILOT_EXACT_TASK_PR_SUBMITTED_REVIEW_API_VERSION = "2022-11-28"
_REPOSITORY = "Ternedal/ModelRig"
_API_ORIGIN = "https://api.github.com"
_PAGE_SIZE = 100
_MAX_REVIEW_PAGES = 10
_PR_MAX_BYTES = 256 * 1024
_REVIEW_PAGE_MAX_BYTES = 512 * 1024
_TIMEOUT_SECONDS = 20
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_REVIEW_STATES = {"APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED", "PENDING"}
_NO_REVIEW_NODE_SHA256 = hashlib.sha256(b"none").hexdigest()
_NO_REVIEW_SUBMITTED_AT = "1970-01-01T00:00:00Z"


class PilotExactTaskPrSubmittedReviewObservationError(ValueError):
    """Submitted-review state is drifted, malformed, unbounded, or unsafe."""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPrSubmittedReviewObservationError("submitted-review evidence is not canonical JSON") from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrSubmittedReviewObservationError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrSubmittedReviewObservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrSubmittedReviewObservationError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskPrSubmittedReviewObservationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _etag_sha256(headers: Mapping[str, str]) -> str:
    etag = headers.get("etag", "")
    if not isinstance(etag, str) or len(etag) > 512 or any(marker in etag for marker in ("\r", "\n", "\x00")):
        raise PilotExactTaskPrSubmittedReviewObservationError("GitHub ETag is invalid")
    return hashlib.sha256(etag.encode("utf-8")).hexdigest()


def _json_response(response: HttpResponse, *, name: str) -> Any:
    if type(response) is not HttpResponse or response.status != 200:
        raise PilotExactTaskPrSubmittedReviewObservationError(f"{name} response status is unsafe")
    try:
        return json.loads(response.body.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrSubmittedReviewObservationError(f"{name} response is not UTF-8 JSON") from exc


def _headers() -> Mapping[str, str]:
    return MappingProxyType({
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": PILOT_EXACT_TASK_PR_SUBMITTED_REVIEW_API_VERSION,
        "User-Agent": "ModelRig-DevControl-ADR-DC-078",
    })


def _require_authenticated_checkpoint(value: Any) -> PilotExactTaskPrReviewObservationCheckpoint:
    if type(value) is not PilotExactTaskPrReviewObservationCheckpoint:
        raise PilotExactTaskPrSubmittedReviewObservationError("exact ADR-DC-077 checkpoint is required")
    try:
        replayed = PilotExactTaskPrReviewObservationCheckpoint.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrSubmittedReviewObservationError("ADR-DC-077 checkpoint replay validation failed") from exc
    required_true = (
        "source_attestation_verified", "durable_checkpoint_committed", "restart_safe_reauthentication_supported",
        "exact_pr_identity_bound", "exact_head_sha_bound", "exact_reviewer_identity_bound",
        "reviewer_request_performed_verified", "exact_requested_reviewer_verified", "team_reviewers_absent_verified",
        "future_review_observation_must_revalidate_exact_pr", "submitted_reviews_read_only_observation_only",
        "reviewer_request_nonce_consumed", "observation_checkpoint_reusable",
    )
    forced_false = (
        "credential_material_in_artifact", "reviewer_mutation_authorized", "review_submission_authorized",
        "review_thread_mutation_authorized", "ready_for_review_authorized", "label_mutation_authorized",
        "merge_readiness_authorized", "merge_authorized", "release_authorized", "deploy_authorized",
        "production_activation_authorized",
    )
    if (
        replayed != value or replayed.sha256 != value.sha256
        or value.authority != PILOT_EXACT_TASK_PR_REVIEW_OBSERVATION_CHECKPOINT_AUTHORITY
        or value.checkpoint_authenticated is not True
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
        or value.repository != _REPOSITORY or value.base_branch != "main"
        or _HEAD.fullmatch(value.head_branch) is None or _LOGIN.fullmatch(value.reviewer_login) is None
        or checkpoint_boundary._get_live_pr_review_observation_checkpoint_inputs(value) is None
    ):
        raise PilotExactTaskPrSubmittedReviewObservationError("submitted-review observation requires one authenticated inert ADR-DC-077 checkpoint")
    return value


def _get(transport: ReadOnlyTransport, url: str, *, max_bytes: int) -> HttpResponse:
    try:
        return transport.get(url, headers=_headers(), timeout_seconds=_TIMEOUT_SECONDS, max_bytes=max_bytes)
    except GitHubReadError as exc:
        raise PilotExactTaskPrSubmittedReviewObservationError("credential-free fixed-origin GitHub read failed") from exc


def _read_exact_pr(checkpoint: PilotExactTaskPrReviewObservationCheckpoint, *, transport: ReadOnlyTransport) -> Mapping[str, Any]:
    response = _get(transport, checkpoint.pull_request_api_url, max_bytes=_PR_MAX_BYTES)
    document = _json_response(response, name="pull request")
    if not isinstance(document, Mapping):
        raise PilotExactTaskPrSubmittedReviewObservationError("pull request response must be an object")
    node_id = document.get("node_id")
    author = document.get("user")
    head = document.get("head")
    base = document.get("base")
    head_repo = None if not isinstance(head, Mapping) else head.get("repo")
    base_repo = None if not isinstance(base, Mapping) else base.get("repo")
    reviewers = document.get("requested_reviewers")
    teams = document.get("requested_teams")
    if (
        document.get("number") != checkpoint.pull_request_number
        or document.get("url") != checkpoint.pull_request_api_url
        or document.get("html_url") != checkpoint.pull_request_html_url
        or not isinstance(node_id, str) or not node_id
        or hashlib.sha256(node_id.encode("utf-8")).hexdigest() != checkpoint.pull_request_node_id_sha256
        or document.get("state") != "open" or document.get("closed_at") is not None
        or document.get("merged_at") is not None or document.get("draft") is not False
        or not isinstance(author, Mapping) or author.get("login") != checkpoint.pull_request_author_login
        or author.get("id") != checkpoint.pull_request_author_user_id
        or not isinstance(head, Mapping) or head.get("ref") != checkpoint.head_branch
        or head.get("sha") != checkpoint.predicted_commit_sha
        or not isinstance(head_repo, Mapping) or head_repo.get("full_name") != checkpoint.repository
        or not isinstance(base, Mapping) or base.get("ref") != checkpoint.base_branch
        or not isinstance(base_repo, Mapping) or base_repo.get("full_name") != checkpoint.repository
        or not isinstance(reviewers, list) or len(reviewers) > 1
        or not isinstance(teams, list) or len(teams) != 0
    ):
        raise PilotExactTaskPrSubmittedReviewObservationError("pull request drifted from exact checkpoint identity/state")
    pinned_present = False
    if reviewers:
        reviewer = reviewers[0]
        reviewer_node_id = None if not isinstance(reviewer, Mapping) else reviewer.get("node_id")
        if (
            not isinstance(reviewer, Mapping) or reviewer.get("login") != checkpoint.reviewer_login
            or reviewer.get("id") != checkpoint.reviewer_user_id
            or not isinstance(reviewer_node_id, str) or not reviewer_node_id
            or hashlib.sha256(reviewer_node_id.encode("utf-8")).hexdigest() != checkpoint.reviewer_user_node_id_sha256
        ):
            raise PilotExactTaskPrSubmittedReviewObservationError("requested reviewer set contains a non-pinned identity")
        pinned_present = True
    return MappingProxyType({
        "pr_response_body_sha256": hashlib.sha256(response.body).hexdigest(),
        "pr_response_etag_sha256": _etag_sha256(response.headers),
        "requested_reviewer_count": len(reviewers),
        "requested_team_count": 0,
        "pinned_reviewer_request_present": pinned_present,
    })


def _normalize_review(review: Any, *, checkpoint: PilotExactTaskPrReviewObservationCheckpoint) -> Mapping[str, Any]:
    if not isinstance(review, Mapping):
        raise PilotExactTaskPrSubmittedReviewObservationError("GitHub review entry must be an object")
    review_id = review.get("id")
    node_id = review.get("node_id")
    user = review.get("user")
    state = review.get("state")
    commit_id = review.get("commit_id")
    submitted_at = review.get("submitted_at")
    if (
        isinstance(review_id, bool) or not isinstance(review_id, int) or review_id < 1
        or not isinstance(node_id, str) or not node_id or len(node_id) > 512
        or not isinstance(user, Mapping) or not isinstance(user.get("login"), str)
        or _LOGIN.fullmatch(user["login"]) is None
        or isinstance(user.get("id"), bool) or not isinstance(user.get("id"), int) or user["id"] < 1
        or state not in _REVIEW_STATES
        or (commit_id is not None and (not isinstance(commit_id, str) or _HEX40.fullmatch(commit_id) is None or commit_id == "0" * 40))
    ):
        raise PilotExactTaskPrSubmittedReviewObservationError("GitHub review entry identity/state is invalid")
    if submitted_at is not None:
        _utc(submitted_at, name="review submitted_at")
    if state != "PENDING" and submitted_at is None:
        raise PilotExactTaskPrSubmittedReviewObservationError("submitted review lacks submitted_at")
    login_matches = user["login"].lower() == checkpoint.reviewer_login.lower()
    id_matches = user["id"] == checkpoint.reviewer_user_id
    if login_matches != id_matches:
        raise PilotExactTaskPrSubmittedReviewObservationError("pinned reviewer identity split across login/id")
    return MappingProxyType({
        "id": review_id,
        "node_id_sha256": hashlib.sha256(node_id.encode("utf-8")).hexdigest(),
        "reviewer_login": user["login"],
        "reviewer_user_id": user["id"],
        "state": state,
        "commit_id": commit_id,
        "submitted_at": submitted_at,
        "is_pinned_reviewer": login_matches and id_matches,
        "is_exact_head": commit_id == checkpoint.predicted_commit_sha,
    })


def _read_reviews(checkpoint: PilotExactTaskPrReviewObservationCheckpoint, *, transport: ReadOnlyTransport) -> Mapping[str, Any]:
    pages: list[Mapping[str, Any]] = []
    reviews: list[Mapping[str, Any]] = []
    seen_ids: set[int] = set()
    complete = False
    for page in range(1, _MAX_REVIEW_PAGES + 1):
        url = f"{checkpoint.pull_request_api_url}/reviews?per_page={_PAGE_SIZE}&page={page}"
        response = _get(transport, url, max_bytes=_REVIEW_PAGE_MAX_BYTES)
        document = _json_response(response, name="reviews")
        if not isinstance(document, list) or len(document) > _PAGE_SIZE:
            raise PilotExactTaskPrSubmittedReviewObservationError("review page shape exceeds pagination bounds")
        pages.append(MappingProxyType({
            "page": page, "count": len(document),
            "body_sha256": hashlib.sha256(response.body).hexdigest(),
            "etag_sha256": _etag_sha256(response.headers),
        }))
        for raw in document:
            normalized = _normalize_review(raw, checkpoint=checkpoint)
            review_id = int(normalized["id"])
            if review_id in seen_ids:
                raise PilotExactTaskPrSubmittedReviewObservationError("duplicate review id across pagination")
            seen_ids.add(review_id)
            reviews.append(normalized)
        if len(document) < _PAGE_SIZE:
            complete = True
            break
    if not complete:
        raise PilotExactTaskPrSubmittedReviewObservationError("review inventory exceeded bounded pagination")
    reviews.sort(key=lambda item: int(item["id"]))
    pinned = [item for item in reviews if item["is_pinned_reviewer"]]
    exact = [item for item in pinned if item["is_exact_head"]]
    stale = [item for item in pinned if not item["is_exact_head"]]
    counts = {state: sum(1 for item in exact if item["state"] == state) for state in _REVIEW_STATES}
    submitted_exact = [item for item in exact if item["state"] != "PENDING" and item["submitted_at"] is not None]
    submitted_exact.sort(key=lambda item: (str(item["submitted_at"]), int(item["id"])))
    latest = submitted_exact[-1] if submitted_exact else None
    evidence = {"pages": [dict(item) for item in pages], "reviews": [dict(item) for item in reviews]}
    return MappingProxyType({
        "reviews_evidence_sha256": hashlib.sha256(_canonical(evidence).encode("utf-8")).hexdigest(),
        "review_page_count": len(pages), "total_review_count": len(reviews),
        "pinned_reviewer_review_count": len(pinned), "pinned_exact_head_review_count": len(exact),
        "pinned_stale_head_review_count": len(stale),
        "exact_head_approved_review_count": counts["APPROVED"],
        "exact_head_changes_requested_review_count": counts["CHANGES_REQUESTED"],
        "exact_head_commented_review_count": counts["COMMENTED"],
        "exact_head_dismissed_review_count": counts["DISMISSED"],
        "exact_head_pending_review_count": counts["PENDING"],
        "latest_exact_head_review_present": latest is not None,
        "latest_exact_head_review_id": 0 if latest is None else int(latest["id"]),
        "latest_exact_head_review_node_id_sha256": _NO_REVIEW_NODE_SHA256 if latest is None else str(latest["node_id_sha256"]),
        "latest_exact_head_review_state": "NONE" if latest is None else str(latest["state"]),
        "latest_exact_head_review_submitted_at_utc": _NO_REVIEW_SUBMITTED_AT if latest is None else str(latest["submitted_at"]),
    })


def _observe_once(checkpoint: PilotExactTaskPrReviewObservationCheckpoint, *, transport: ReadOnlyTransport) -> Mapping[str, Any]:
    return MappingProxyType({**dict(_read_exact_pr(checkpoint, transport=transport)), **dict(_read_reviews(checkpoint, transport=transport))})


_live_records: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[PilotExactTaskPrReviewObservationCheckpoint]]] = {}


def _mark_authenticated(observation: Any, checkpoint: PilotExactTaskPrReviewObservationCheckpoint) -> None:
    key = id(observation)
    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)
    _live_records[key] = (os.getpid(), observation.sha256, weakref.ref(observation, cleanup), weakref.ref(checkpoint))


def _get_live_pr_submitted_review_observation_inputs(observation: Any) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(observation))
    if entry is None:
        return None
    pid, digest, observation_ref, checkpoint_ref = entry
    checkpoint = checkpoint_ref()
    if (
        pid != os.getpid() or observation_ref() is not observation or checkpoint is None
        or checkpoint.checkpoint_authenticated is not True
        or checkpoint.sha256 != observation.review_observation_checkpoint_sha256
        or observation.sha256 != digest
    ):
        return None
    return MappingProxyType({"review_observation_checkpoint": checkpoint})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrSubmittedReviewObservation:
    review_observation_checkpoint_sha256: str
    checkpoint_key_sha256: str
    source_reviewer_request_attestation_sha256: str
    reviewer_write_transaction_sha256: str
    reviewer_request_nonce_sha256: str
    repository: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_html_url: str
    pull_request_node_id_sha256: str
    base_branch: str
    head_branch: str
    predicted_commit_sha: str
    reviewer_login: str
    reviewer_user_id: int
    reviewer_user_node_id_sha256: str
    pull_request_author_login: str
    pull_request_author_user_id: int
    pr_response_body_sha256: str
    pr_response_etag_sha256: str
    reviews_evidence_sha256: str
    requested_reviewer_count: int
    requested_team_count: int
    pinned_reviewer_request_present: bool
    review_page_count: int
    total_review_count: int
    pinned_reviewer_review_count: int
    pinned_exact_head_review_count: int
    pinned_stale_head_review_count: int
    exact_head_approved_review_count: int
    exact_head_changes_requested_review_count: int
    exact_head_commented_review_count: int
    exact_head_dismissed_review_count: int
    exact_head_pending_review_count: int
    latest_exact_head_review_present: bool
    latest_exact_head_review_id: int
    latest_exact_head_review_node_id_sha256: str
    latest_exact_head_review_state: str
    latest_exact_head_review_submitted_at_utc: str
    first_observed_at_utc: str
    second_observed_at_utc: str
    stable_double_observation_verified: bool = True
    credential_free_reads: bool = True
    fixed_origin_reads: bool = True
    redirects_forbidden: bool = True
    response_bounded: bool = True
    pagination_bounded: bool = True
    exact_pr_identity_revalidated: bool = True
    exact_head_revalidated: bool = True
    exact_reviewer_identity_bound: bool = True
    other_requested_reviewers_absent_verified: bool = True
    team_reviewers_absent_verified: bool = True
    submitted_reviews_observed: bool = True
    checkpoint_reusable: bool = True
    review_policy_evaluated: bool = False
    reviewer_mutation_authorized: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    ready_for_review_authorized: bool = False
    label_mutation_authorized: bool = False
    merge_readiness_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_SUBMITTED_REVIEW_OBSERVATION_AUTHORITY
    observation_scope: str = PILOT_EXACT_TASK_PR_SUBMITTED_REVIEW_OBSERVATION_SCOPE
    schema: str = PILOT_EXACT_TASK_PR_SUBMITTED_REVIEW_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PR_SUBMITTED_REVIEW_OBSERVATION_SCHEMA or self.authority != PILOT_EXACT_TASK_PR_SUBMITTED_REVIEW_OBSERVATION_AUTHORITY or self.observation_scope != PILOT_EXACT_TASK_PR_SUBMITTED_REVIEW_OBSERVATION_SCOPE:
            raise PilotExactTaskPrSubmittedReviewObservationError("submitted-review observation schema/authority/scope unsupported")
        for name in (
            "review_observation_checkpoint_sha256", "checkpoint_key_sha256", "source_reviewer_request_attestation_sha256",
            "reviewer_write_transaction_sha256", "reviewer_request_nonce_sha256", "pull_request_node_id_sha256",
            "reviewer_user_node_id_sha256", "pr_response_body_sha256", "pr_response_etag_sha256",
            "reviews_evidence_sha256", "latest_exact_head_review_node_id_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        first = _utc(self.first_observed_at_utc, name="first_observed_at_utc")
        second = _utc(self.second_observed_at_utc, name="second_observed_at_utc")
        _utc(self.latest_exact_head_review_submitted_at_utc, name="latest_exact_head_review_submitted_at_utc")
        if second < first:
            raise PilotExactTaskPrSubmittedReviewObservationError("clock moved backwards during submitted-review observation")
        if (
            self.repository != _REPOSITORY or self.base_branch != "main" or _HEAD.fullmatch(self.head_branch) is None
            or isinstance(self.pull_request_number, bool) or not isinstance(self.pull_request_number, int) or self.pull_request_number < 1
            or self.pull_request_api_url != f"{_API_ORIGIN}/repos/{_REPOSITORY}/pulls/{self.pull_request_number}"
            or self.pull_request_html_url != f"https://github.com/{_REPOSITORY}/pull/{self.pull_request_number}"
            or not isinstance(self.reviewer_login, str) or _LOGIN.fullmatch(self.reviewer_login) is None
            or isinstance(self.reviewer_user_id, bool) or not isinstance(self.reviewer_user_id, int) or self.reviewer_user_id < 1
            or not isinstance(self.pull_request_author_login, str) or _LOGIN.fullmatch(self.pull_request_author_login) is None
            or isinstance(self.pull_request_author_user_id, bool) or not isinstance(self.pull_request_author_user_id, int) or self.pull_request_author_user_id < 1
            or self.pull_request_author_user_id == self.reviewer_user_id
            or self.pull_request_author_login.lower() == self.reviewer_login.lower()
        ):
            raise PilotExactTaskPrSubmittedReviewObservationError("submitted-review observation target binding invalid")
        integer_fields = (
            "requested_reviewer_count", "requested_team_count", "review_page_count", "total_review_count",
            "pinned_reviewer_review_count", "pinned_exact_head_review_count", "pinned_stale_head_review_count",
            "exact_head_approved_review_count", "exact_head_changes_requested_review_count", "exact_head_commented_review_count",
            "exact_head_dismissed_review_count", "exact_head_pending_review_count", "latest_exact_head_review_id",
        )
        if any(isinstance(getattr(self, name), bool) or not isinstance(getattr(self, name), int) or getattr(self, name) < 0 for name in integer_fields):
            raise PilotExactTaskPrSubmittedReviewObservationError("submitted-review observation counts are invalid")
        if (
            self.requested_reviewer_count not in {0, 1} or self.requested_team_count != 0
            or not 1 <= self.review_page_count <= _MAX_REVIEW_PAGES
            or self.pinned_reviewer_review_count != self.pinned_exact_head_review_count + self.pinned_stale_head_review_count
            or sum((self.exact_head_approved_review_count, self.exact_head_changes_requested_review_count, self.exact_head_commented_review_count, self.exact_head_dismissed_review_count, self.exact_head_pending_review_count)) != self.pinned_exact_head_review_count
            or self.pinned_reviewer_review_count > self.total_review_count
        ):
            raise PilotExactTaskPrSubmittedReviewObservationError("submitted-review observation counts are inconsistent")
        if not isinstance(self.pinned_reviewer_request_present, bool) or self.pinned_reviewer_request_present != (self.requested_reviewer_count == 1) or not isinstance(self.latest_exact_head_review_present, bool):
            raise PilotExactTaskPrSubmittedReviewObservationError("submitted-review observation booleans are inconsistent")
        if self.latest_exact_head_review_present:
            if self.latest_exact_head_review_id < 1 or self.latest_exact_head_review_state not in {"APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED"} or self.latest_exact_head_review_submitted_at_utc == _NO_REVIEW_SUBMITTED_AT or self.latest_exact_head_review_node_id_sha256 == _NO_REVIEW_NODE_SHA256:
                raise PilotExactTaskPrSubmittedReviewObservationError("latest exact-head review binding is invalid")
        elif self.latest_exact_head_review_id != 0 or self.latest_exact_head_review_state != "NONE" or self.latest_exact_head_review_submitted_at_utc != _NO_REVIEW_SUBMITTED_AT or self.latest_exact_head_review_node_id_sha256 != _NO_REVIEW_NODE_SHA256:
            raise PilotExactTaskPrSubmittedReviewObservationError("no-review sentinel binding is invalid")
        required_true = (
            "stable_double_observation_verified", "credential_free_reads", "fixed_origin_reads", "redirects_forbidden",
            "response_bounded", "pagination_bounded", "exact_pr_identity_revalidated", "exact_head_revalidated",
            "exact_reviewer_identity_bound", "other_requested_reviewers_absent_verified", "team_reviewers_absent_verified",
            "submitted_reviews_observed", "checkpoint_reusable",
        )
        forced_false = (
            "review_policy_evaluated", "reviewer_mutation_authorized", "review_submission_authorized",
            "review_thread_mutation_authorized", "ready_for_review_authorized", "label_mutation_authorized",
            "merge_readiness_authorized", "merge_authorized", "release_authorized", "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrSubmittedReviewObservationError("submitted-review observation evidence incomplete")
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrSubmittedReviewObservationError("submitted-review observation cannot grant mutation/policy authority")

    @property
    def observation_authenticated(self) -> bool:
        return _get_live_pr_submitted_review_observation_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrSubmittedReviewObservation":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrSubmittedReviewObservationError("submitted-review observation must be an object")
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrSubmittedReviewObservationError("submitted-review observation fields mismatch")
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _observe_verified_pilot_exact_task_pr_submitted_reviews(*, review_observation_checkpoint: PilotExactTaskPrReviewObservationCheckpoint, transport: ReadOnlyTransport, now_provider: Any) -> PilotExactTaskPrSubmittedReviewObservation:
    checkpoint = _require_authenticated_checkpoint(review_observation_checkpoint)
    first_at = now_provider()
    _utc(first_at, name="first_observed_at_utc")
    first = _observe_once(checkpoint, transport=transport)
    second_at = now_provider()
    if _utc(second_at, name="second_observed_at_utc") < _utc(first_at, name="first_observed_at_utc"):
        raise PilotExactTaskPrSubmittedReviewObservationError("clock moved backwards during submitted-review observation")
    second = _observe_once(checkpoint, transport=transport)
    if dict(first) != dict(second):
        raise PilotExactTaskPrSubmittedReviewObservationError("submitted-review state changed between complete observations")
    result = PilotExactTaskPrSubmittedReviewObservation(
        review_observation_checkpoint_sha256=checkpoint.sha256,
        checkpoint_key_sha256=checkpoint.checkpoint_key_sha256,
        source_reviewer_request_attestation_sha256=checkpoint.source_reviewer_request_attestation_sha256,
        reviewer_write_transaction_sha256=checkpoint.reviewer_write_transaction_sha256,
        reviewer_request_nonce_sha256=checkpoint.reviewer_request_nonce_sha256,
        repository=checkpoint.repository, pull_request_number=checkpoint.pull_request_number,
        pull_request_api_url=checkpoint.pull_request_api_url, pull_request_html_url=checkpoint.pull_request_html_url,
        pull_request_node_id_sha256=checkpoint.pull_request_node_id_sha256, base_branch=checkpoint.base_branch,
        head_branch=checkpoint.head_branch, predicted_commit_sha=checkpoint.predicted_commit_sha,
        reviewer_login=checkpoint.reviewer_login, reviewer_user_id=checkpoint.reviewer_user_id,
        reviewer_user_node_id_sha256=checkpoint.reviewer_user_node_id_sha256,
        pull_request_author_login=checkpoint.pull_request_author_login,
        pull_request_author_user_id=checkpoint.pull_request_author_user_id,
        pr_response_body_sha256=str(first["pr_response_body_sha256"]),
        pr_response_etag_sha256=str(first["pr_response_etag_sha256"]),
        reviews_evidence_sha256=str(first["reviews_evidence_sha256"]),
        requested_reviewer_count=int(first["requested_reviewer_count"]), requested_team_count=int(first["requested_team_count"]),
        pinned_reviewer_request_present=bool(first["pinned_reviewer_request_present"]), review_page_count=int(first["review_page_count"]),
        total_review_count=int(first["total_review_count"]), pinned_reviewer_review_count=int(first["pinned_reviewer_review_count"]),
        pinned_exact_head_review_count=int(first["pinned_exact_head_review_count"]), pinned_stale_head_review_count=int(first["pinned_stale_head_review_count"]),
        exact_head_approved_review_count=int(first["exact_head_approved_review_count"]), exact_head_changes_requested_review_count=int(first["exact_head_changes_requested_review_count"]),
        exact_head_commented_review_count=int(first["exact_head_commented_review_count"]), exact_head_dismissed_review_count=int(first["exact_head_dismissed_review_count"]),
        exact_head_pending_review_count=int(first["exact_head_pending_review_count"]), latest_exact_head_review_present=bool(first["latest_exact_head_review_present"]),
        latest_exact_head_review_id=int(first["latest_exact_head_review_id"]), latest_exact_head_review_node_id_sha256=str(first["latest_exact_head_review_node_id_sha256"]),
        latest_exact_head_review_state=str(first["latest_exact_head_review_state"]), latest_exact_head_review_submitted_at_utc=str(first["latest_exact_head_review_submitted_at_utc"]),
        first_observed_at_utc=first_at, second_observed_at_utc=second_at,
    )
    _mark_authenticated(result, checkpoint)
    if result.observation_authenticated is not True:
        raise PilotExactTaskPrSubmittedReviewObservationError("submitted-review observation lost live checkpoint provenance")
    return result


def observe_pilot_exact_task_pr_submitted_reviews(checkpoint_key_sha256: str) -> PilotExactTaskPrSubmittedReviewObservation:
    """Load one durable checkpoint and observe exact submitted review state twice."""
    checkpoint = checkpoint_boundary.load_pilot_exact_task_pr_review_observation_checkpoint(checkpoint_key_sha256)
    return _observe_verified_pilot_exact_task_pr_submitted_reviews(
        review_observation_checkpoint=checkpoint,
        transport=UrllibReadOnlyTransport(),
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_SUBMITTED_REVIEW_OBSERVATION_SCHEMA",
    "PILOT_EXACT_TASK_PR_SUBMITTED_REVIEW_OBSERVATION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_SUBMITTED_REVIEW_OBSERVATION_SCOPE",
    "PilotExactTaskPrSubmittedReviewObservationError",
    "PilotExactTaskPrSubmittedReviewObservation",
    "observe_pilot_exact_task_pr_submitted_reviews",
]
