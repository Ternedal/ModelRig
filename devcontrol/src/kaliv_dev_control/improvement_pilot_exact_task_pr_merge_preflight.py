"""ADR-DC-080 fresh semantic merge preflight.

Consumes one live APPROVED ADR-DC-079 review disposition plus an inert replay of
its exact content-addressed ADR-DC-066 reviewer-handoff requirements artifact.
The original requirements digest is already anchored by the restart-safe
ADR-DC-077 checkpoint. This boundary restores only semantic PR metadata policy,
then performs two bounded credential-free fixed-origin GETs of the exact pull
request.

Passing this preflight is not merge readiness and grants no mutation authority.
A later boundary must freshly re-observe review state and independently verify
required checks, review threads, branch policy, and exact PR/head state before
any merge capability can exist.
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
from . import improvement_pilot_exact_task_pr_review_disposition as disposition_boundary
from . import improvement_pilot_exact_task_pr_submitted_review_observation as observation_boundary
from .improvement_pilot_exact_task_pr_review_disposition import (
    PILOT_EXACT_TASK_PR_REVIEW_DISPOSITION_AUTHORITY,
    PilotExactTaskPrReviewDisposition,
)
from .improvement_pilot_exact_task_pr_reviewer_handoff_requirements import (
    PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_REQUIREMENTS_AUTHORITY,
    PilotExactTaskPrReviewerHandoffRequirements,
)

PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-merge-preflight/v1"
)
PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_AUTHORITY = (
    "preflighted-one-dc-l16-exact-pr-review-and-semantic-metadata-only"
)
PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_SCOPE = (
    "credential-free-stable-semantic-metadata-preflight-v1"
)
PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_API_VERSION = "2022-11-28"
PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_MAX_REVIEW_DISPOSITION_AGE_SECONDS = 10

_REPOSITORY = "Ternedal/ModelRig"
_PR_MAX_BYTES = 256 * 1024
_TIMEOUT_SECONDS = 20
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


class PilotExactTaskPrMergePreflightError(ValueError):
    """Merge preflight input/state is stale, drifted, or unsafe."""


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
        raise PilotExactTaskPrMergePreflightError(
            "merge-preflight value is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskPrMergePreflightError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskPrMergePreflightError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrMergePreflightError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrMergePreflightError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _etag_sha256(headers: Mapping[str, str]) -> str:
    etag = headers.get("etag", "")
    if (
        not isinstance(etag, str)
        or len(etag) > 512
        or any(marker in etag for marker in ("\r", "\n", "\x00"))
    ):
        raise PilotExactTaskPrMergePreflightError("GitHub ETag is invalid")
    return hashlib.sha256(etag.encode("utf-8")).hexdigest()


def _headers() -> Mapping[str, str]:
    return MappingProxyType(
        {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_API_VERSION,
            "User-Agent": "ModelRig-DevControl-ADR-DC-080",
        }
    )


def _require_live_approved_disposition(
    value: Any,
) -> tuple[
    PilotExactTaskPrReviewDisposition,
    Any,
    Any,
]:
    if type(value) is not PilotExactTaskPrReviewDisposition:
        raise PilotExactTaskPrMergePreflightError(
            "exact live ADR-DC-079 review disposition is required"
        )
    try:
        replayed = PilotExactTaskPrReviewDisposition.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrMergePreflightError(
            "ADR-DC-079 disposition replay validation failed"
        ) from exc

    forced_false = (
        "reviewer_mutation_authorized",
        "review_submission_authorized",
        "review_thread_mutation_authorized",
        "ready_for_review_authorized",
        "label_mutation_authorized",
        "merge_readiness_authorized",
        "merge_authorized",
        "release_authorized",
        "deploy_authorized",
        "production_activation_authorized",
    )
    live = disposition_boundary._get_live_pr_review_disposition_inputs(value)
    observation = None if live is None else live.get("submitted_review_observation")
    observation_inputs = (
        None
        if observation is None
        else observation_boundary._get_live_pr_submitted_review_observation_inputs(
            observation
        )
    )
    checkpoint = (
        None
        if observation_inputs is None
        else observation_inputs.get("review_observation_checkpoint")
    )
    if (
        replayed != value
        or replayed.sha256 != value.sha256
        or value.authority != PILOT_EXACT_TASK_PR_REVIEW_DISPOSITION_AUTHORITY
        or value.disposition_authenticated is not True
        or value.review_disposition != "APPROVED"
        or value.review_policy_evaluated is not True
        or value.review_policy_passed is not True
        or value.exact_head_approval_verified is not True
        or value.fresh_merge_preflight_required is not True
        or value.semantic_pr_metadata_policy_required is not True
        or any(getattr(value, name) is not False for name in forced_false)
        or value.repository != _REPOSITORY
        or value.base_branch != "main"
        or _HEAD.fullmatch(value.head_branch) is None
        or observation is None
        or getattr(observation, "observation_authenticated", None) is not True
        or observation.sha256 != value.submitted_review_observation_sha256
        or checkpoint is None
        or getattr(checkpoint, "checkpoint_authenticated", None) is not True
        or checkpoint.sha256 != value.review_observation_checkpoint_sha256
        or checkpoint.checkpoint_key_sha256 != value.checkpoint_key_sha256
        or checkpoint.predicted_commit_sha != value.predicted_commit_sha
        or checkpoint.pull_request_number != value.pull_request_number
        or checkpoint.reviewer_login != value.reviewer_login
        or checkpoint.reviewer_user_id != value.reviewer_user_id
    ):
        raise PilotExactTaskPrMergePreflightError(
            "merge preflight requires one live approved inert ADR-DC-079 disposition"
        )
    return value, observation, checkpoint


def _require_semantic_requirements(
    value: Any,
    *,
    disposition: PilotExactTaskPrReviewDisposition,
    checkpoint: Any,
) -> PilotExactTaskPrReviewerHandoffRequirements:
    if not isinstance(value, Mapping):
        raise PilotExactTaskPrMergePreflightError(
            "semantic requirements artifact must be a mapping replay"
        )
    try:
        requirements = PilotExactTaskPrReviewerHandoffRequirements.from_mapping(value)
    except Exception as exc:
        raise PilotExactTaskPrMergePreflightError(
            "ADR-DC-066 semantic requirements artifact is invalid"
        ) from exc
    required_true = (
        "post_ready_pr_reverified",
        "pull_request_open_verified",
        "ready_state_verified",
        "exact_head_sha_verified",
        "exact_base_verified",
        "exact_metadata_verified",
        "merge_separate_authority_required",
    )
    forced_false = (
        "pr_mutation_authorized",
        "pull_request_create_authorized",
        "ready_for_review_authorized",
        "reviewer_mutation_authorized",
        "reviewer_request_performed",
        "label_mutation_authorized",
        "merge_authorized",
        "release_authorized",
        "deploy_authorized",
        "production_activation_authorized",
    )
    if (
        requirements.authority
        != PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_REQUIREMENTS_AUTHORITY
        or requirements.requirements_authenticated is not False
        or requirements.sha256 != checkpoint.reviewer_handoff_requirements_sha256
        or requirements.repository != disposition.repository
        or requirements.pull_request_number != disposition.pull_request_number
        or requirements.pull_request_api_url != checkpoint.pull_request_api_url
        or requirements.pull_request_html_url != checkpoint.pull_request_html_url
        or requirements.pull_request_node_id_sha256
        != disposition.pull_request_node_id_sha256
        or requirements.base_branch != disposition.base_branch
        or requirements.head_branch != disposition.head_branch
        or requirements.predicted_commit_sha != disposition.predicted_commit_sha
        or not requirements.pr_title
        or not requirements.pr_body
        or any(getattr(requirements, name) is not True for name in required_true)
        or any(getattr(requirements, name) is not False for name in forced_false)
    ):
        raise PilotExactTaskPrMergePreflightError(
            "semantic requirements artifact does not match authenticated checkpoint"
        )
    return requirements


def _require_disposition_window(
    disposition: PilotExactTaskPrReviewDisposition,
    *,
    at_utc: str,
) -> None:
    at = _utc(at_utc, name="merge preflight observation time")
    evaluated = _utc(
        disposition.evaluated_at_utc,
        name="ADR-DC-079 evaluated_at_utc",
    )
    if (
        at < evaluated
        or (at - evaluated).total_seconds()
        > PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_MAX_REVIEW_DISPOSITION_AGE_SECONDS
    ):
        raise PilotExactTaskPrMergePreflightError(
            "ADR-DC-079 approved disposition is too old for merge preflight"
        )


def _get(
    transport: ReadOnlyTransport,
    url: str,
    *,
    max_bytes: int,
) -> HttpResponse:
    try:
        return transport.get(
            url,
            headers=_headers(),
            timeout_seconds=_TIMEOUT_SECONDS,
            max_bytes=max_bytes,
        )
    except GitHubReadError as exc:
        raise PilotExactTaskPrMergePreflightError(
            "credential-free fixed-origin GitHub read failed"
        ) from exc


def _read_exact_pr(
    *,
    checkpoint: Any,
    requirements: PilotExactTaskPrReviewerHandoffRequirements,
    transport: ReadOnlyTransport,
) -> Mapping[str, Any]:
    response = _get(
        transport,
        checkpoint.pull_request_api_url,
        max_bytes=_PR_MAX_BYTES,
    )
    if (
        type(response) is not HttpResponse
        or response.status != 200
        or len(response.body) > _PR_MAX_BYTES
    ):
        raise PilotExactTaskPrMergePreflightError(
            "pull request preflight response status/size is unsafe"
        )
    content_type = str(response.headers.get("content-type", "")).lower()
    if content_type and not (
        content_type.startswith("application/json")
        or content_type.startswith("application/vnd.github+json")
    ):
        raise PilotExactTaskPrMergePreflightError(
            "pull request preflight content type is unsafe"
        )
    try:
        document = json.loads(response.body.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrMergePreflightError(
            "pull request preflight response is not UTF-8 JSON"
        ) from exc
    if not isinstance(document, Mapping):
        raise PilotExactTaskPrMergePreflightError(
            "pull request preflight response must be an object"
        )

    node_id = document.get("node_id")
    author = document.get("user")
    head = document.get("head")
    base = document.get("base")
    head_repo = None if not isinstance(head, Mapping) else head.get("repo")
    base_repo = None if not isinstance(base, Mapping) else base.get("repo")
    reviewers = document.get("requested_reviewers")
    teams = document.get("requested_teams")
    updated_at = document.get("updated_at")
    if (
        document.get("number") != checkpoint.pull_request_number
        or document.get("url") != checkpoint.pull_request_api_url
        or document.get("html_url") != checkpoint.pull_request_html_url
        or not isinstance(node_id, str)
        or not node_id
        or hashlib.sha256(node_id.encode("utf-8")).hexdigest()
        != checkpoint.pull_request_node_id_sha256
        or document.get("state") != "open"
        or document.get("closed_at") is not None
        or document.get("merged_at") is not None
        or document.get("draft") is not False
        or document.get("title") != requirements.pr_title
        or document.get("body") != requirements.pr_body
        or document.get("maintainer_can_modify") is not False
        or not isinstance(author, Mapping)
        or author.get("login") != checkpoint.pull_request_author_login
        or author.get("id") != checkpoint.pull_request_author_user_id
        or not isinstance(head, Mapping)
        or head.get("ref") != checkpoint.head_branch
        or head.get("sha") != checkpoint.predicted_commit_sha
        or not isinstance(head_repo, Mapping)
        or head_repo.get("full_name") != checkpoint.repository
        or not isinstance(base, Mapping)
        or base.get("ref") != checkpoint.base_branch
        or not isinstance(base_repo, Mapping)
        or base_repo.get("full_name") != checkpoint.repository
        or not isinstance(reviewers, list)
        or len(reviewers) > 1
        or not isinstance(teams, list)
        or len(teams) != 0
    ):
        raise PilotExactTaskPrMergePreflightError(
            "pull request drifted from semantic merge-preflight policy"
        )
    _utc(updated_at, name="preflight PR updated_at")

    pinned_present = False
    if reviewers:
        reviewer = reviewers[0]
        reviewer_node_id = (
            None if not isinstance(reviewer, Mapping) else reviewer.get("node_id")
        )
        if (
            not isinstance(reviewer, Mapping)
            or reviewer.get("login") != checkpoint.reviewer_login
            or reviewer.get("id") != checkpoint.reviewer_user_id
            or not isinstance(reviewer_node_id, str)
            or not reviewer_node_id
            or hashlib.sha256(reviewer_node_id.encode("utf-8")).hexdigest()
            != checkpoint.reviewer_user_node_id_sha256
        ):
            raise PilotExactTaskPrMergePreflightError(
                "requested reviewer set contains a non-pinned identity"
            )
        pinned_present = True

    return MappingProxyType(
        {
            "response_body_sha256": hashlib.sha256(response.body).hexdigest(),
            "response_etag_sha256": _etag_sha256(response.headers),
            "observed_updated_at_utc": updated_at,
            "requested_reviewer_count": len(reviewers),
            "requested_team_count": 0,
            "pinned_reviewer_request_present": pinned_present,
        }
    )


_live_records: dict[
    int,
    tuple[
        int,
        str,
        weakref.ReferenceType[Any],
        weakref.ReferenceType[PilotExactTaskPrReviewDisposition],
        weakref.ReferenceType[Any],
        PilotExactTaskPrReviewerHandoffRequirements,
    ],
] = {}


def _mark_authenticated(
    result: Any,
    disposition: PilotExactTaskPrReviewDisposition,
    checkpoint: Any,
    requirements: PilotExactTaskPrReviewerHandoffRequirements,
) -> None:
    key = id(result)

    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)

    _live_records[key] = (
        os.getpid(),
        result.sha256,
        weakref.ref(result, cleanup),
        weakref.ref(disposition),
        weakref.ref(checkpoint),
        requirements,
    )


def _get_live_pr_merge_preflight_inputs(result: Any) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(result))
    if entry is None:
        return None
    (
        pid,
        digest,
        result_ref,
        disposition_ref,
        checkpoint_ref,
        requirements,
    ) = entry
    disposition = disposition_ref()
    checkpoint = checkpoint_ref()
    if (
        pid != os.getpid()
        or result_ref() is not result
        or disposition is None
        or checkpoint is None
        or disposition.disposition_authenticated is not True
        or disposition.sha256 != result.review_disposition_sha256
        or checkpoint.checkpoint_authenticated is not True
        or checkpoint.sha256 != result.review_observation_checkpoint_sha256
        or requirements.sha256 != result.reviewer_handoff_requirements_sha256
        or hashlib.sha256(requirements.pr_title.encode("utf-8")).hexdigest()
        != result.semantic_pr_title_sha256
        or hashlib.sha256(requirements.pr_body.encode("utf-8")).hexdigest()
        != result.semantic_pr_body_sha256
        or result.sha256 != digest
    ):
        return None
    return MappingProxyType(
        {
            "review_disposition": disposition,
            "review_observation_checkpoint": checkpoint,
            "semantic_requirements": requirements,
        }
    )


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrMergePreflight:
    review_disposition_sha256: str
    submitted_review_observation_sha256: str
    review_observation_checkpoint_sha256: str
    checkpoint_key_sha256: str
    reviewer_handoff_requirements_sha256: str
    source_reviewer_request_attestation_sha256: str
    reviewer_write_transaction_sha256: str
    reviewer_request_nonce_sha256: str
    semantic_pr_title_sha256: str
    semantic_pr_body_sha256: str
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
    review_disposition: str
    first_response_body_sha256: str
    first_response_etag_sha256: str
    second_response_body_sha256: str
    second_response_etag_sha256: str
    observed_updated_at_utc: str
    requested_reviewer_count: int
    requested_team_count: int
    pinned_reviewer_request_present: bool
    first_observed_at_utc: str
    second_observed_at_utc: str
    source_review_disposition_verified: bool = True
    source_exact_head_approval_verified: bool = True
    semantic_requirements_replay_verified: bool = True
    semantic_metadata_policy_restored: bool = True
    semantic_metadata_verified: bool = True
    maintainer_can_modify_false_verified: bool = True
    exact_pr_identity_revalidated: bool = True
    exact_head_revalidated: bool = True
    exact_base_revalidated: bool = True
    exact_author_revalidated: bool = True
    open_ready_state_revalidated: bool = True
    requested_reviewer_shape_revalidated: bool = True
    stable_double_observation_verified: bool = True
    credential_free_reads: bool = True
    fixed_origin_reads: bool = True
    redirects_forbidden: bool = True
    response_bounded: bool = True
    fresh_review_disposition_age_verified: bool = True
    metadata_and_review_preflight_passed: bool = True
    fresh_review_reobservation_before_merge_required: bool = True
    required_status_checks_preflight_required: bool = True
    review_threads_preflight_required: bool = True
    branch_policy_preflight_required: bool = True
    fresh_merge_transaction_revalidation_required: bool = True
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
    authority: str = PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_AUTHORITY
    preflight_scope: str = PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_SCOPE
    schema: str = PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_SCHEMA
            or self.authority != PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_AUTHORITY
            or self.preflight_scope != PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_SCOPE
        ):
            raise PilotExactTaskPrMergePreflightError(
                "merge-preflight schema/authority/scope unsupported"
            )
        for name in (
            "review_disposition_sha256",
            "submitted_review_observation_sha256",
            "review_observation_checkpoint_sha256",
            "checkpoint_key_sha256",
            "reviewer_handoff_requirements_sha256",
            "source_reviewer_request_attestation_sha256",
            "reviewer_write_transaction_sha256",
            "reviewer_request_nonce_sha256",
            "semantic_pr_title_sha256",
            "semantic_pr_body_sha256",
            "pull_request_node_id_sha256",
            "reviewer_user_node_id_sha256",
            "first_response_body_sha256",
            "first_response_etag_sha256",
            "second_response_body_sha256",
            "second_response_etag_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        first = _utc(self.first_observed_at_utc, name="first_observed_at_utc")
        second = _utc(self.second_observed_at_utc, name="second_observed_at_utc")
        _utc(self.observed_updated_at_utc, name="observed_updated_at_utc")
        if second < first:
            raise PilotExactTaskPrMergePreflightError(
                "merge-preflight clock moved backwards"
            )
        if (
            self.first_response_body_sha256 != self.second_response_body_sha256
            or self.first_response_etag_sha256 != self.second_response_etag_sha256
        ):
            raise PilotExactTaskPrMergePreflightError(
                "merge-preflight double-observation evidence is inconsistent"
            )
        if (
            self.repository != _REPOSITORY
            or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
            or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"https://api.github.com/repos/Ternedal/ModelRig/pulls/{self.pull_request_number}"
            or self.pull_request_html_url
            != f"https://github.com/Ternedal/ModelRig/pull/{self.pull_request_number}"
            or not isinstance(self.reviewer_login, str)
            or _LOGIN.fullmatch(self.reviewer_login) is None
            or isinstance(self.reviewer_user_id, bool)
            or not isinstance(self.reviewer_user_id, int)
            or self.reviewer_user_id < 1
            or not isinstance(self.pull_request_author_login, str)
            or _LOGIN.fullmatch(self.pull_request_author_login) is None
            or isinstance(self.pull_request_author_user_id, bool)
            or not isinstance(self.pull_request_author_user_id, int)
            or self.pull_request_author_user_id < 1
            or self.pull_request_author_user_id == self.reviewer_user_id
            or self.pull_request_author_login.lower() == self.reviewer_login.lower()
            or self.review_disposition != "APPROVED"
            or isinstance(self.requested_reviewer_count, bool)
            or not isinstance(self.requested_reviewer_count, int)
            or self.requested_reviewer_count not in {0, 1}
            or self.requested_team_count != 0
            or not isinstance(self.pinned_reviewer_request_present, bool)
            or self.pinned_reviewer_request_present
            is not (self.requested_reviewer_count == 1)
        ):
            raise PilotExactTaskPrMergePreflightError(
                "merge-preflight exact target binding is invalid"
            )
        required_true = (
            "source_review_disposition_verified",
            "source_exact_head_approval_verified",
            "semantic_requirements_replay_verified",
            "semantic_metadata_policy_restored",
            "semantic_metadata_verified",
            "maintainer_can_modify_false_verified",
            "exact_pr_identity_revalidated",
            "exact_head_revalidated",
            "exact_base_revalidated",
            "exact_author_revalidated",
            "open_ready_state_revalidated",
            "requested_reviewer_shape_revalidated",
            "stable_double_observation_verified",
            "credential_free_reads",
            "fixed_origin_reads",
            "redirects_forbidden",
            "response_bounded",
            "fresh_review_disposition_age_verified",
            "metadata_and_review_preflight_passed",
            "fresh_review_reobservation_before_merge_required",
            "required_status_checks_preflight_required",
            "review_threads_preflight_required",
            "branch_policy_preflight_required",
            "fresh_merge_transaction_revalidation_required",
        )
        forced_false = (
            "reviewer_mutation_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "ready_for_review_authorized",
            "label_mutation_authorized",
            "merge_readiness_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrMergePreflightError(
                "merge-preflight evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrMergePreflightError(
                "merge preflight cannot grant mutation authority"
            )

    @property
    def preflight_authenticated(self) -> bool:
        return _get_live_pr_merge_preflight_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrMergePreflight":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrMergePreflightError(
                "merge preflight must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrMergePreflightError(
                "merge-preflight fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _preflight_verified_pilot_exact_task_pr_merge(
    *,
    review_disposition: PilotExactTaskPrReviewDisposition,
    semantic_requirements_artifact: Mapping[str, Any],
    transport: ReadOnlyTransport,
    now_provider: Any,
) -> PilotExactTaskPrMergePreflight:
    disposition, _observation, checkpoint = _require_live_approved_disposition(
        review_disposition
    )
    requirements = _require_semantic_requirements(
        semantic_requirements_artifact,
        disposition=disposition,
        checkpoint=checkpoint,
    )

    first_at = now_provider()
    _require_disposition_window(disposition, at_utc=first_at)
    first = _read_exact_pr(
        checkpoint=checkpoint,
        requirements=requirements,
        transport=transport,
    )
    second_at = now_provider()
    _require_disposition_window(disposition, at_utc=second_at)
    if _utc(second_at, name="second_observed_at_utc") < _utc(
        first_at, name="first_observed_at_utc"
    ):
        raise PilotExactTaskPrMergePreflightError(
            "clock moved backwards during merge preflight"
        )
    second = _read_exact_pr(
        checkpoint=checkpoint,
        requirements=requirements,
        transport=transport,
    )
    if dict(first) != dict(second):
        raise PilotExactTaskPrMergePreflightError(
            "pull request changed between merge-preflight observations"
        )

    result = PilotExactTaskPrMergePreflight(
        review_disposition_sha256=disposition.sha256,
        submitted_review_observation_sha256=disposition.submitted_review_observation_sha256,
        review_observation_checkpoint_sha256=disposition.review_observation_checkpoint_sha256,
        checkpoint_key_sha256=disposition.checkpoint_key_sha256,
        reviewer_handoff_requirements_sha256=requirements.sha256,
        source_reviewer_request_attestation_sha256=disposition.source_reviewer_request_attestation_sha256,
        reviewer_write_transaction_sha256=disposition.reviewer_write_transaction_sha256,
        reviewer_request_nonce_sha256=disposition.reviewer_request_nonce_sha256,
        semantic_pr_title_sha256=hashlib.sha256(
            requirements.pr_title.encode("utf-8")
        ).hexdigest(),
        semantic_pr_body_sha256=hashlib.sha256(
            requirements.pr_body.encode("utf-8")
        ).hexdigest(),
        repository=disposition.repository,
        pull_request_number=disposition.pull_request_number,
        pull_request_api_url=checkpoint.pull_request_api_url,
        pull_request_html_url=checkpoint.pull_request_html_url,
        pull_request_node_id_sha256=disposition.pull_request_node_id_sha256,
        base_branch=disposition.base_branch,
        head_branch=disposition.head_branch,
        predicted_commit_sha=disposition.predicted_commit_sha,
        reviewer_login=disposition.reviewer_login,
        reviewer_user_id=disposition.reviewer_user_id,
        reviewer_user_node_id_sha256=disposition.reviewer_user_node_id_sha256,
        pull_request_author_login=checkpoint.pull_request_author_login,
        pull_request_author_user_id=checkpoint.pull_request_author_user_id,
        review_disposition=disposition.review_disposition,
        first_response_body_sha256=str(first["response_body_sha256"]),
        first_response_etag_sha256=str(first["response_etag_sha256"]),
        second_response_body_sha256=str(second["response_body_sha256"]),
        second_response_etag_sha256=str(second["response_etag_sha256"]),
        observed_updated_at_utc=str(second["observed_updated_at_utc"]),
        requested_reviewer_count=int(second["requested_reviewer_count"]),
        requested_team_count=int(second["requested_team_count"]),
        pinned_reviewer_request_present=bool(
            second["pinned_reviewer_request_present"]
        ),
        first_observed_at_utc=first_at,
        second_observed_at_utc=second_at,
    )
    _mark_authenticated(result, disposition, checkpoint, requirements)
    if result.preflight_authenticated is not True:
        raise PilotExactTaskPrMergePreflightError(
            "merge preflight lost live provenance"
        )
    return result


def preflight_pilot_exact_task_pr_merge(
    review_disposition: PilotExactTaskPrReviewDisposition,
    semantic_requirements_artifact: Mapping[str, Any],
) -> PilotExactTaskPrMergePreflight:
    """Freshly verify exact approved review + semantic PR metadata; never merge."""
    return _preflight_verified_pilot_exact_task_pr_merge(
        review_disposition=review_disposition,
        semantic_requirements_artifact=semantic_requirements_artifact,
        transport=UrllibReadOnlyTransport(),
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_SCHEMA",
    "PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_AUTHORITY",
    "PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_SCOPE",
    "PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_MAX_REVIEW_DISPOSITION_AGE_SECONDS",
    "PilotExactTaskPrMergePreflightError",
    "PilotExactTaskPrMergePreflight",
    "preflight_pilot_exact_task_pr_merge",
]
