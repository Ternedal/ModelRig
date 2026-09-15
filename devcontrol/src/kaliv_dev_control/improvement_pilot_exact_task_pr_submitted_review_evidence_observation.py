"""ADR-DC-093 credential-free granular submitted-review evidence observation.

Consumes one live authenticated ADR-DC-092 evidence-requirements receipt and,
when granular submitted-review evidence is required, performs two complete
fixed-origin read-only observations of the exact pull request and its submitted
review inventory. All review rows are preserved as normalized evidence; this
boundary never treats an APPROVED row (or GraphQL reviewDecision) as policy
satisfaction and never infers the last push actor from commit author metadata.
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
from typing import Any, Callable, Mapping

from . import improvement_pilot_exact_task_pr_review_evidence_requirements as requirements_boundary
from .github_read import GitHubReadError, HttpResponse, ReadOnlyTransport, UrllibReadOnlyTransport
from .improvement_pilot_exact_task_pr_review_evidence_requirements import (
    PilotExactTaskPrReviewEvidenceRequirements,
)

SCHEMA = "kaliv-rsi-dc-l16-exact-task-pr-submitted-review-evidence-observation/v1"
AUTHORITY = "observed-one-dc-l16-exact-pr-granular-submitted-review-evidence-only"
OBSERVATION_SCOPE = "credential-free-stable-exact-head-all-reviewers-read-only-v1"
API_VERSION = "2022-11-28"
_REPOSITORY = "Ternedal/ModelRig"
_API_ORIGIN = "https://api.github.com"
_PAGE_SIZE = 100
_MAX_PAGES = 10
_MAX_REVIEWS = _PAGE_SIZE * _MAX_PAGES
_PR_MAX_BYTES = 256 * 1024
_REVIEW_PAGE_MAX_BYTES = 512 * 1024
_TIMEOUT_SECONDS = 20
_MAX_SOURCE_AGE_SECONDS = 60
_MAX_OBSERVATION_WINDOW_SECONDS = 30
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_REVIEW_STATES = frozenset({"APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED", "PENDING"})


class PilotExactTaskPrSubmittedReviewEvidenceObservationError(ValueError):
    """Granular submitted-review evidence is stale, malformed, incomplete, or unsafe."""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("review evidence is not canonical JSON") from exc


def _canonical_bytes(value: Any) -> bytes:
    return _canonical(value).encode("utf-8")


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrSubmittedReviewEvidenceObservationError(f"{name} invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrSubmittedReviewEvidenceObservationError(f"{name} invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrSubmittedReviewEvidenceObservationError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskPrSubmittedReviewEvidenceObservationError(f"{name} invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _etag_sha256(headers: Mapping[str, str]) -> str:
    etag = ""
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == "etag":
            etag = value
            break
    if not isinstance(etag, str) or len(etag.encode("utf-8")) > 512 or any(marker in etag for marker in ("\r", "\n", "\x00")):
        raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("GitHub ETag invalid")
    return hashlib.sha256(etag.encode("utf-8")).hexdigest()


def _headers() -> Mapping[str, str]:
    return MappingProxyType({
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "ModelRig-DevControl-ADR-DC-093",
    })


def _get(transport: ReadOnlyTransport, url: str, *, max_bytes: int) -> HttpResponse:
    if not isinstance(url, str) or not url.startswith(_API_ORIGIN + "/repos/Ternedal/ModelRig/"):
        raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("review evidence URL escaped fixed GitHub origin/repository")
    try:
        response = transport.get(url, headers=_headers(), timeout_seconds=_TIMEOUT_SECONDS, max_bytes=max_bytes)
    except GitHubReadError as exc:
        raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("credential-free fixed-origin GitHub review read failed") from exc
    if type(response) is not HttpResponse or response.status != 200 or len(response.body) > max_bytes:
        raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("GitHub review response status/size unsafe")
    return response


def _json(response: HttpResponse, *, name: str) -> Any:
    try:
        return json.loads(response.body.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrSubmittedReviewEvidenceObservationError(f"{name} is not UTF-8 JSON") from exc


def _require_live_requirements(value: Any) -> tuple[PilotExactTaskPrReviewEvidenceRequirements, Any]:
    if type(value) is not PilotExactTaskPrReviewEvidenceRequirements:
        raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("live ADR-DC-092 requirements required")
    try:
        replay = PilotExactTaskPrReviewEvidenceRequirements.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("ADR-DC-092 replay validation failed") from exc
    live = requirements_boundary._get_live_pr_review_evidence_requirements_inputs(value)
    observation = None if live is None else live.get("review_thread_state_observation")
    if (
        replay != value or replay.sha256 != value.sha256 or value.requirements_authenticated is not True
        or live is None or observation is None or getattr(observation, "observation_authenticated", None) is not True
        or value.requirements_result != "SUPPORTED"
        or value.exact_head_submitted_review_inventory_required is not True
        or value.exact_head_commit_binding_required is not True
        or value.reviewer_identity_binding_required is not True
        or value.review_evidence_evaluation_required is not True
        or value.graphql_review_decision_sufficient_for_pass is not False
        or value.repository != _REPOSITORY or observation.repository != value.repository
        or value.pull_request_number != observation.pull_request_number
        or value.predicted_commit_sha != observation.predicted_commit_sha
        or value.review_thread_state_observation_sha256 != observation.sha256
        or value.branch_policy_fully_evaluated is not False
        or value.merge_readiness_authorized is not False
        or value.merge_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("ADR-DC-093 source requirements invalid")
    return value, observation


def _require_source_window(observation: Any, *, at_utc: str) -> None:
    at = _utc(at_utc, name="submitted-review observation time")
    source = _utc(observation.second_observed_at_utc, name="ADR-DC-090 second_observed_at_utc")
    if at < source or (at - source).total_seconds() > _MAX_SOURCE_AGE_SECONDS:
        raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("ADR-DC-090 review/thread evidence too old")


def _pr_url(requirements: PilotExactTaskPrReviewEvidenceRequirements) -> str:
    return f"{_API_ORIGIN}/repos/Ternedal/ModelRig/pulls/{requirements.pull_request_number}"


def _read_exact_pr(requirements: PilotExactTaskPrReviewEvidenceRequirements, observation: Any, *, transport: ReadOnlyTransport) -> Mapping[str, Any]:
    url = _pr_url(requirements)
    response = _get(transport, url, max_bytes=_PR_MAX_BYTES)
    value = _json(response, name="pull request")
    if not isinstance(value, Mapping):
        raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("pull request response must be an object")
    node_id = value.get("node_id")
    head = value.get("head")
    base = value.get("base")
    head_repo = head.get("repo") if isinstance(head, Mapping) else None
    base_repo = base.get("repo") if isinstance(base, Mapping) else None
    if (
        value.get("number") != requirements.pull_request_number
        or not isinstance(node_id, str) or not node_id
        or hashlib.sha256(node_id.encode("utf-8")).hexdigest() != observation.pull_request_node_id_sha256
        or value.get("state") != "open" or value.get("draft") is not False
        or value.get("closed_at") is not None or value.get("merged_at") is not None
        or not isinstance(head, Mapping) or head.get("ref") != observation.head_ref_name
        or head.get("sha") != requirements.predicted_commit_sha
        or not isinstance(head_repo, Mapping) or head_repo.get("full_name") != _REPOSITORY
        or not isinstance(base, Mapping) or base.get("ref") != "main"
        or not isinstance(base_repo, Mapping) or base_repo.get("full_name") != _REPOSITORY
    ):
        raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("pull request identity/head drifted from ADR-DC-092/090")
    return MappingProxyType({
        "pull_request_node_id_sha256": hashlib.sha256(node_id.encode("utf-8")).hexdigest(),
        "head_ref_name": str(head["ref"]),
        "head_sha": str(head["sha"]),
        "body_sha256": hashlib.sha256(response.body).hexdigest(),
        "etag_sha256": _etag_sha256(response.headers),
    })


def _review_row(value: Any, *, requirements: PilotExactTaskPrReviewEvidenceRequirements) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("review row must be an object")
    review_id = value.get("id")
    node_id = value.get("node_id")
    user = value.get("user")
    state = value.get("state")
    commit_id = value.get("commit_id")
    submitted_at = value.get("submitted_at")
    if (
        isinstance(review_id, bool) or not isinstance(review_id, int) or review_id < 1
        or not isinstance(node_id, str) or not node_id or len(node_id.encode("utf-8")) > 1024
        or not isinstance(user, Mapping)
        or not isinstance(user.get("login"), str) or _LOGIN.fullmatch(user["login"]) is None
        or isinstance(user.get("id"), bool) or not isinstance(user.get("id"), int) or user["id"] < 1
        or not isinstance(user.get("node_id"), str) or not user["node_id"] or len(user["node_id"].encode("utf-8")) > 1024
        or state not in _REVIEW_STATES
        or (commit_id is not None and (not isinstance(commit_id, str) or _HEX40.fullmatch(commit_id) is None or commit_id == "0" * 40))
    ):
        raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("review row identity/state invalid")
    if submitted_at is not None:
        _utc(submitted_at, name="review submitted_at")
    if state != "PENDING" and submitted_at is None:
        raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("submitted review lacks submitted_at")
    return MappingProxyType({
        "review_id": review_id,
        "review_node_id_sha256": hashlib.sha256(node_id.encode("utf-8")).hexdigest(),
        "reviewer_login": user["login"],
        "reviewer_login_folded": user["login"].lower(),
        "reviewer_user_id": user["id"],
        "reviewer_user_node_id_sha256": hashlib.sha256(user["node_id"].encode("utf-8")).hexdigest(),
        "state": state,
        "commit_id": commit_id,
        "submitted_at_utc": submitted_at,
        "is_exact_head": commit_id == requirements.predicted_commit_sha,
    })


def _validate_reviewer_identity_consistency(rows: tuple[Mapping[str, Any], ...]) -> None:
    by_id: dict[int, tuple[str, str]] = {}
    by_login: dict[str, tuple[int, str]] = {}
    for row in rows:
        user_id = int(row["reviewer_user_id"])
        login = str(row["reviewer_login_folded"])
        node = str(row["reviewer_user_node_id_sha256"])
        previous_id = by_id.get(user_id)
        if previous_id is not None and previous_id != (login, node):
            raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("reviewer identity drifted for GitHub user id")
        previous_login = by_login.get(login)
        if previous_login is not None and previous_login != (user_id, node):
            raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("reviewer login mapped to conflicting identity")
        by_id[user_id] = (login, node)
        by_login[login] = (user_id, node)


def _read_reviews(requirements: PilotExactTaskPrReviewEvidenceRequirements, *, transport: ReadOnlyTransport) -> Mapping[str, Any]:
    rows: list[Mapping[str, Any]] = []
    page_evidence: list[Mapping[str, Any]] = []
    seen_ids: set[int] = set()
    complete = False
    for page in range(1, _MAX_PAGES + 1):
        url = f"{_pr_url(requirements)}/reviews?per_page={_PAGE_SIZE}&page={page}"
        response = _get(transport, url, max_bytes=_REVIEW_PAGE_MAX_BYTES)
        value = _json(response, name="review page")
        if not isinstance(value, list) or len(value) > _PAGE_SIZE:
            raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("review page shape exceeds bounds")
        page_rows = tuple(_review_row(item, requirements=requirements) for item in value)
        for row in page_rows:
            review_id = int(row["review_id"])
            if review_id in seen_ids:
                raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("duplicate review id across pagination")
            seen_ids.add(review_id)
            rows.append(row)
            if len(rows) > _MAX_REVIEWS:
                raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("review inventory exceeds bound")
        page_evidence.append(MappingProxyType({
            "page": page,
            "row_count": len(page_rows),
            "body_sha256": hashlib.sha256(response.body).hexdigest(),
            "etag_sha256": _etag_sha256(response.headers),
        }))
        if len(value) < _PAGE_SIZE:
            complete = True
            break
    if not complete:
        raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("review inventory completeness not provable within page bound")
    normalized = tuple(sorted(rows, key=lambda item: int(item["review_id"])))
    _validate_reviewer_identity_consistency(normalized)
    exact = tuple(item for item in normalized if item["is_exact_head"])
    stale = tuple(item for item in normalized if not item["is_exact_head"])
    reviewer_identities = {(int(item["reviewer_user_id"]), str(item["reviewer_user_node_id_sha256"])) for item in normalized}
    exact_reviewer_identities = {(int(item["reviewer_user_id"]), str(item["reviewer_user_node_id_sha256"])) for item in exact}
    return MappingProxyType({
        "rows": normalized,
        "review_inventory_sha256": hashlib.sha256(_canonical_bytes([dict(item) for item in normalized])).hexdigest(),
        "review_pages_evidence_sha256": hashlib.sha256(_canonical_bytes([dict(item) for item in page_evidence])).hexdigest(),
        "review_page_count": len(page_evidence),
        "total_review_count": len(normalized),
        "exact_head_review_row_count": len(exact),
        "stale_head_review_row_count": len(stale),
        "distinct_reviewer_count": len(reviewer_identities),
        "exact_head_distinct_reviewer_count": len(exact_reviewer_identities),
    })


def _snapshot(requirements: PilotExactTaskPrReviewEvidenceRequirements, observation: Any, *, transport: ReadOnlyTransport) -> Mapping[str, Any]:
    pr = _read_exact_pr(requirements, observation, transport=transport)
    reviews = _read_reviews(requirements, transport=transport)
    combined = {
        "pr": dict(pr),
        "review_inventory_sha256": reviews["review_inventory_sha256"],
        "review_pages_evidence_sha256": reviews["review_pages_evidence_sha256"],
        "review_page_count": reviews["review_page_count"],
        "total_review_count": reviews["total_review_count"],
        "exact_head_review_row_count": reviews["exact_head_review_row_count"],
        "stale_head_review_row_count": reviews["stale_head_review_row_count"],
        "distinct_reviewer_count": reviews["distinct_reviewer_count"],
        "exact_head_distinct_reviewer_count": reviews["exact_head_distinct_reviewer_count"],
    }
    return MappingProxyType({
        **combined,
        "rows": reviews["rows"],
        "combined_evidence_sha256": hashlib.sha256(_canonical_bytes(combined)).hexdigest(),
    })


_live: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[Any], tuple[Mapping[str, Any], ...]]] = {}


def _get_live_pr_submitted_review_evidence_observation_inputs(value: Any) -> Mapping[str, Any] | None:
    row = _live.get(id(value))
    if row is None:
        return None
    pid, digest, ref, requirements_ref, rows = row
    requirements = requirements_ref()
    if (
        pid != os.getpid() or ref() is not value or requirements is None
        or requirements.requirements_authenticated is not True
        or requirements.sha256 != value.review_evidence_requirements_sha256
        or value.sha256 != digest
        or hashlib.sha256(_canonical_bytes([dict(item) for item in rows])).hexdigest() != value.review_inventory_sha256
    ):
        return None
    return MappingProxyType({"review_evidence_requirements": requirements, "reviews": rows})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrSubmittedReviewEvidenceObservation:
    review_evidence_requirements_sha256: str
    review_policy_sha256: str
    review_thread_state_observation_sha256: str
    repository: str
    pull_request_number: int
    predicted_commit_sha: str
    pull_request_node_id_sha256: str
    head_ref_name: str
    review_inventory_sha256: str
    first_review_inventory_sha256: str
    second_review_inventory_sha256: str
    first_combined_evidence_sha256: str
    second_combined_evidence_sha256: str
    review_page_count: int
    total_review_count: int
    exact_head_review_row_count: int
    stale_head_review_row_count: int
    distinct_reviewer_count: int
    exact_head_distinct_reviewer_count: int
    first_observed_at_utc: str
    second_observed_at_utc: str
    source_requirements_verified: bool = True
    source_review_policy_verified: bool = True
    source_review_thread_observation_verified: bool = True
    fresh_source_age_verified: bool = True
    credential_free_reads: bool = True
    fixed_github_api_origin: bool = True
    redirects_forbidden: bool = True
    response_bounded: bool = True
    pagination_bounded: bool = True
    exact_pr_identity_revalidated: bool = True
    exact_head_revalidated: bool = True
    all_reviewer_identities_bound: bool = True
    review_inventory_complete: bool = True
    stable_double_observation_verified: bool = True
    exact_head_review_rows_preserved: bool = True
    stale_head_review_rows_preserved: bool = True
    granular_review_evidence_observed: bool = True
    approval_policy_evaluated: bool = False
    stale_review_policy_evaluated: bool = False
    code_owner_policy_evaluated: bool = False
    last_push_actor_inferred_from_commit_metadata: bool = False
    last_push_actor_evidence_still_required: bool = True
    code_owner_evidence_still_required: bool = False
    conversation_resolution_evidence_already_bound: bool = True
    review_evidence_evaluation_required: bool = True
    merge_method_policy_still_required: bool = True
    fresh_required_status_reobservation_before_merge_required: bool = True
    fresh_review_reobservation_required: bool = True
    fresh_merge_transaction_revalidation_required: bool = True
    branch_policy_fully_evaluated: bool = False
    review_thread_policy_evaluated: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    merge_readiness_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = AUTHORITY
    observation_scope: str = OBSERVATION_SCOPE
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SCHEMA or self.authority != AUTHORITY or self.observation_scope != OBSERVATION_SCOPE:
            raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("observation schema/authority/scope invalid")
        for name in (
            "review_evidence_requirements_sha256", "review_policy_sha256", "review_thread_state_observation_sha256",
            "pull_request_node_id_sha256", "review_inventory_sha256", "first_review_inventory_sha256",
            "second_review_inventory_sha256", "first_combined_evidence_sha256", "second_combined_evidence_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        if self.repository != _REPOSITORY or isinstance(self.pull_request_number, bool) or not isinstance(self.pull_request_number, int) or self.pull_request_number < 1:
            raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("observation target invalid")
        if not isinstance(self.head_ref_name, str) or not self.head_ref_name or len(self.head_ref_name.encode("utf-8")) > 512:
            raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("head_ref_name invalid")
        first = _utc(self.first_observed_at_utc, name="first_observed_at_utc")
        second = _utc(self.second_observed_at_utc, name="second_observed_at_utc")
        if second < first or (second - first).total_seconds() > _MAX_OBSERVATION_WINDOW_SECONDS:
            raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("observation window invalid")
        for name, maximum, minimum in (
            ("review_page_count", _MAX_PAGES, 1),
            ("total_review_count", _MAX_REVIEWS, 0),
            ("exact_head_review_row_count", _MAX_REVIEWS, 0),
            ("stale_head_review_row_count", _MAX_REVIEWS, 0),
            ("distinct_reviewer_count", _MAX_REVIEWS, 0),
            ("exact_head_distinct_reviewer_count", _MAX_REVIEWS, 0),
        ):
            item = getattr(self, name)
            if isinstance(item, bool) or not isinstance(item, int) or not minimum <= item <= maximum:
                raise PilotExactTaskPrSubmittedReviewEvidenceObservationError(f"{name} invalid")
        if (
            self.exact_head_review_row_count + self.stale_head_review_row_count != self.total_review_count
            or self.distinct_reviewer_count > self.total_review_count
            or self.exact_head_distinct_reviewer_count > self.exact_head_review_row_count
            or self.first_review_inventory_sha256 != self.second_review_inventory_sha256
            or self.review_inventory_sha256 != self.first_review_inventory_sha256
            or self.first_combined_evidence_sha256 != self.second_combined_evidence_sha256
        ):
            raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("review inventory/count evidence invalid")
        bool_fields = (
            "source_requirements_verified", "source_review_policy_verified", "source_review_thread_observation_verified",
            "fresh_source_age_verified", "credential_free_reads", "fixed_github_api_origin", "redirects_forbidden",
            "response_bounded", "pagination_bounded", "exact_pr_identity_revalidated", "exact_head_revalidated",
            "all_reviewer_identities_bound", "review_inventory_complete", "stable_double_observation_verified",
            "exact_head_review_rows_preserved", "stale_head_review_rows_preserved", "granular_review_evidence_observed",
            "approval_policy_evaluated", "stale_review_policy_evaluated", "code_owner_policy_evaluated",
            "last_push_actor_inferred_from_commit_metadata", "last_push_actor_evidence_still_required",
            "code_owner_evidence_still_required", "conversation_resolution_evidence_already_bound",
            "review_evidence_evaluation_required", "merge_method_policy_still_required",
            "fresh_required_status_reobservation_before_merge_required", "fresh_review_reobservation_required",
            "fresh_merge_transaction_revalidation_required", "branch_policy_fully_evaluated", "review_thread_policy_evaluated",
            "review_submission_authorized", "review_thread_mutation_authorized", "merge_readiness_authorized",
            "merge_authorized", "release_authorized", "deploy_authorized", "production_activation_authorized",
        )
        if any(type(getattr(self, name)) is not bool for name in bool_fields):
            raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("observation booleans must be exact bools")
        required_true = (
            "source_requirements_verified", "source_review_policy_verified", "source_review_thread_observation_verified",
            "fresh_source_age_verified", "credential_free_reads", "fixed_github_api_origin", "redirects_forbidden",
            "response_bounded", "pagination_bounded", "exact_pr_identity_revalidated", "exact_head_revalidated",
            "all_reviewer_identities_bound", "review_inventory_complete", "stable_double_observation_verified",
            "exact_head_review_rows_preserved", "stale_head_review_rows_preserved", "granular_review_evidence_observed",
            "conversation_resolution_evidence_already_bound", "review_evidence_evaluation_required",
            "merge_method_policy_still_required", "fresh_required_status_reobservation_before_merge_required",
            "fresh_review_reobservation_required", "fresh_merge_transaction_revalidation_required",
        )
        required_false = (
            "approval_policy_evaluated", "stale_review_policy_evaluated", "code_owner_policy_evaluated",
            "last_push_actor_inferred_from_commit_metadata", "branch_policy_fully_evaluated", "review_thread_policy_evaluated",
            "review_submission_authorized", "review_thread_mutation_authorized", "merge_readiness_authorized",
            "merge_authorized", "release_authorized", "deploy_authorized", "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true) or any(getattr(self, name) is not False for name in required_false):
            raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("observation widened authority or evaluated policy")

    @property
    def observation_authenticated(self) -> bool:
        return _get_live_pr_submitted_review_evidence_observation_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrSubmittedReviewEvidenceObservation":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("observation fields mismatch")
        return cls(**dict(value))


def _observe_verified_pilot_exact_task_pr_submitted_review_evidence(
    *,
    review_evidence_requirements: PilotExactTaskPrReviewEvidenceRequirements,
    transport: ReadOnlyTransport,
    now_provider: Callable[[], str],
) -> PilotExactTaskPrSubmittedReviewEvidenceObservation:
    requirements, source_observation = _require_live_requirements(review_evidence_requirements)
    first_at = now_provider()
    _require_source_window(source_observation, at_utc=first_at)
    first = _snapshot(requirements, source_observation, transport=transport)
    second = _snapshot(requirements, source_observation, transport=transport)
    second_at = now_provider()
    _require_source_window(source_observation, at_utc=second_at)
    first_dt = _utc(first_at, name="first_observed_at_utc")
    second_dt = _utc(second_at, name="second_observed_at_utc")
    if second_dt < first_dt or (second_dt - first_dt).total_seconds() > _MAX_OBSERVATION_WINDOW_SECONDS:
        raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("observation clock/window invalid")
    stable_keys = (
        "pull_request_node_id_sha256", "head_ref_name", "head_sha", "review_inventory_sha256",
        "combined_evidence_sha256", "review_page_count", "total_review_count", "exact_head_review_row_count",
        "stale_head_review_row_count", "distinct_reviewer_count", "exact_head_distinct_reviewer_count",
    )
    if any(first[name] != second[name] for name in stable_keys):
        raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("double submitted-review observation drifted")
    rows = tuple(first["rows"])
    result = PilotExactTaskPrSubmittedReviewEvidenceObservation(
        requirements.sha256,
        requirements.review_policy_sha256,
        requirements.review_thread_state_observation_sha256,
        requirements.repository,
        requirements.pull_request_number,
        requirements.predicted_commit_sha,
        source_observation.pull_request_node_id_sha256,
        source_observation.head_ref_name,
        first["review_inventory_sha256"],
        first["review_inventory_sha256"],
        second["review_inventory_sha256"],
        first["combined_evidence_sha256"],
        second["combined_evidence_sha256"],
        first["review_page_count"],
        first["total_review_count"],
        first["exact_head_review_row_count"],
        first["stale_head_review_row_count"],
        first["distinct_reviewer_count"],
        first["exact_head_distinct_reviewer_count"],
        first_at,
        second_at,
        last_push_actor_evidence_still_required=requirements.latest_push_actor_evidence_required,
        code_owner_evidence_still_required=(
            requirements.code_owner_change_set_evidence_required or requirements.code_owner_identity_evidence_required
        ),
    )
    key = id(result)
    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live.pop(key, None)
    _live[key] = (os.getpid(), result.sha256, weakref.ref(result, cleanup), weakref.ref(requirements), rows)
    if result.observation_authenticated is not True:
        raise PilotExactTaskPrSubmittedReviewEvidenceObservationError("submitted-review observation lost live provenance")
    return result


def observe_pilot_exact_task_pr_submitted_review_evidence(
    review_evidence_requirements: PilotExactTaskPrReviewEvidenceRequirements,
) -> PilotExactTaskPrSubmittedReviewEvidenceObservation:
    return _observe_verified_pilot_exact_task_pr_submitted_review_evidence(
        review_evidence_requirements=review_evidence_requirements,
        transport=UrllibReadOnlyTransport(),
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "SCHEMA", "AUTHORITY", "OBSERVATION_SCOPE",
    "PilotExactTaskPrSubmittedReviewEvidenceObservationError",
    "PilotExactTaskPrSubmittedReviewEvidenceObservation",
    "observe_pilot_exact_task_pr_submitted_review_evidence",
]
