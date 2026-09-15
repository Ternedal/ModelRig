"""ADR-DC-070 credential-free exact GitHub reviewer identity observation.

Consumes one exact live ADR-DC-069 reviewer-request reservation, follows its
live provenance to the host-pinned ADR-DC-067 reviewer target, then observes
the pinned GitHub user and exact pull request through bounded credential-free
fixed-origin GETs. It proves identity and excludes self-review. Reviewer
requestability remains a separate authenticated read-only boundary.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Mapping

from . import improvement_pilot_exact_task_pr_reviewer_request_reservation as reservation_boundary
from . import improvement_pilot_exact_task_pr_reviewer_target_attestation as target_boundary
from .improvement_pilot_exact_task_pr_reviewer_request_reservation import (
    PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_RESERVATION_AUTHORITY,
    PilotExactTaskPrReviewerRequestReservationReceipt,
)
from .improvement_pilot_exact_task_pr_reviewer_target_attestation import (
    PilotExactTaskPrReviewerTargetAttestation,
)

PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_OBSERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-reviewer-identity-observation/v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_OBSERVATION_AUTHORITY = (
    "observed-one-dc-l16-exact-pr-reviewer-identity-only"
)
PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_OBSERVATION_SCOPE = (
    "credential-free-post-reservation-exact-pr-reviewer-identity-only-v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_API_VERSION = "2022-11-28"
PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_MAX_RESPONSE_BYTES = 256 * 1024
PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_TIMEOUT_SECONDS = 20
PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_MAX_RESERVATION_AGE_SECONDS = 60

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_NODE_ID = re.compile(r"^[A-Za-z0-9_+/=-]{8,256}$")


class PilotExactTaskPrReviewerIdentityObservationError(ValueError):
    """Reviewer identity or exact PR state is unsafe, stale, or ambiguous."""


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
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "reviewer identity artifact is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskPrReviewerIdentityObservationError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskPrReviewerIdentityObservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReviewerIdentityObservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrReviewerIdentityObservationError(
            f"{name} is invalid"
        ) from exc


def _login(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _LOGIN.fullmatch(value) is None:
        raise PilotExactTaskPrReviewerIdentityObservationError(f"{name} is invalid")
    return value


def _node_id(value: Any) -> str:
    if (
        not isinstance(value, str)
        or value.strip() != value
        or _NODE_ID.fullmatch(value) is None
        or "\x00" in value
    ):
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "GitHub user node id is invalid"
        )
    return value


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _require_live_reservation(
    value: Any,
) -> tuple[
    PilotExactTaskPrReviewerRequestReservationReceipt,
    PilotExactTaskPrReviewerTargetAttestation,
    Any,
]:
    if type(value) is not PilotExactTaskPrReviewerRequestReservationReceipt:
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "exact ADR-DC-069 reviewer-request reservation is required"
        )
    try:
        replayed = PilotExactTaskPrReviewerRequestReservationReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "ADR-DC-069 reservation replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "ADR-DC-069 reservation identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_RESERVATION_AUTHORITY
        or value.reservation_authenticated is not True
        or value.host_replay_guard_committed is not True
        or value.human_reviewer_request_authorization_freshly_verified is not True
        or value.reviewer_request_authorization_consumed is not True
        or value.reviewer_request_slot_reserved is not True
        or value.reviewer_identity_observation_required is not True
        or value.reviewer_requestability_observation_required is not True
        or value.fresh_pr_state_revalidation_before_reviewer_request_required is not True
        or value.reviewer_request_transaction_required is not True
        or value.team_reviewers_forbidden is not True
        or value.self_review_forbidden is not True
        or value.reviewer_mutation_authorized is not False
        or value.reviewer_request_performed is not False
        or value.label_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.repository != "Ternedal/ModelRig"
        or value.base_branch != "main"
    ):
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "identity observation requires one live inert ADR-DC-069 reservation"
        )
    reservation_inputs = (
        reservation_boundary._get_live_pr_reviewer_request_reservation_inputs(value)
    )
    target = (
        None
        if reservation_inputs is None
        else reservation_inputs.get("reviewer_target_attestation")
    )
    if (
        type(target) is not PilotExactTaskPrReviewerTargetAttestation
        or target.attestation_authenticated is not True
        or target.sha256 != value.reviewer_target_attestation_sha256
        or target.reviewer_handoff_requirements_sha256
        != value.reviewer_handoff_requirements_sha256
        or target.predicted_commit_sha != value.predicted_commit_sha
        or target.reviewer_handoff_plan_sha256 != value.reviewer_handoff_plan_sha256
        or target.reviewer_target_policy_sha256 != value.reviewer_target_policy_sha256
        or target.reviewer_target_policy_epoch != value.reviewer_target_policy_epoch
        or target.reviewer_login != value.reviewer_login
        or target.reviewer_user_id != value.reviewer_user_id
        or target.pull_request_number != value.pull_request_number
        or target.pull_request_api_url != value.pull_request_api_url
        or target.pull_request_html_url != value.pull_request_html_url
        or target.pull_request_node_id_sha256 != value.pull_request_node_id_sha256
        or target.base_branch != value.base_branch
        or target.head_branch != value.head_branch
    ):
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "ADR-DC-069 lost exact live reviewer-target provenance"
        )
    target_inputs = target_boundary._get_live_pr_reviewer_target_attestation_inputs(
        target
    )
    requirements = (
        None
        if target_inputs is None
        else target_inputs.get("reviewer_handoff_requirements")
    )
    if (
        requirements is None
        or getattr(requirements, "requirements_authenticated", None) is not True
        or requirements.sha256 != value.reviewer_handoff_requirements_sha256
        or requirements.ready_updated_at_utc != target.ready_updated_at_utc
        or requirements.predicted_commit_sha != value.predicted_commit_sha
    ):
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "ADR-DC-067 reviewer-handoff provenance is unavailable"
        )
    return value, target, requirements


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _credential_free_get_json(
    url: str,
    *,
    user_agent: str,
) -> tuple[Mapping[str, Any], bytes, str]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_API_VERSION,
            "User-Agent": user_agent,
        },
    )
    lowered_headers = {name.lower() for name in request.headers}
    if "authorization" in lowered_headers or "cookie" in lowered_headers:
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "reviewer identity reads must remain credential free"
        )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(
            request,
            timeout=PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_TIMEOUT_SECONDS,
        ) as response:
            status = getattr(response, "status", None)
            headers = {
                str(k).lower(): str(v).strip()
                for k, v in response.headers.items()
            }
            payload = response.read(
                PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_MAX_RESPONSE_BYTES + 1
            )
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "fixed-origin reviewer identity read failed"
        ) from exc
    if status != 200:
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "reviewer identity read returned a non-success status"
        )
    if len(payload) > PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_MAX_RESPONSE_BYTES:
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "reviewer identity response exceeded byte ceiling"
        )
    try:
        document = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "reviewer identity response is not UTF-8 JSON"
        ) from exc
    if not isinstance(document, Mapping):
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "reviewer identity response must be an object"
        )
    etag = headers.get("etag", "")
    if len(etag) > 512 or "\r" in etag or "\n" in etag or "\x00" in etag:
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "reviewer identity ETag is invalid"
        )
    return document, payload, etag


def _read_exact_reviewer_identity(
    *,
    reviewer_request_reservation: PilotExactTaskPrReviewerRequestReservationReceipt,
    reviewer_target_attestation: PilotExactTaskPrReviewerTargetAttestation,
    review_handoff_requirements: Any,
) -> Mapping[str, Any]:
    reservation = reviewer_request_reservation
    target = reviewer_target_attestation
    requirements = review_handoff_requirements
    user_url = f"https://api.github.com/users/{reservation.reviewer_login}"
    pr_url = (
        "https://api.github.com/repos/Ternedal/ModelRig/pulls/"
        f"{reservation.pull_request_number}"
    )
    if reservation.pull_request_api_url != pr_url or target.pull_request_api_url != pr_url:
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "reviewer identity PR target is not canonical"
        )
    user, user_payload, user_etag = _credential_free_get_json(
        user_url,
        user_agent="ModelRig-DevControl-ADR-DC-070-User",
    )
    pr, pr_payload, pr_etag = _credential_free_get_json(
        pr_url,
        user_agent="ModelRig-DevControl-ADR-DC-070-PR",
    )

    observed_login = _login(user.get("login"), name="observed reviewer login")
    node_id = _node_id(user.get("node_id"))
    if (
        observed_login != reservation.reviewer_login
        or user.get("id") != reservation.reviewer_user_id
        or user.get("type") != "User"
        or user.get("url") != user_url
        or user.get("html_url") != f"https://github.com/{reservation.reviewer_login}"
    ):
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "GitHub reviewer identity does not match reserved host-pinned target"
        )

    author = pr.get("user")
    head = pr.get("head")
    base = pr.get("base")
    head_repo = None if not isinstance(head, Mapping) else head.get("repo")
    base_repo = None if not isinstance(base, Mapping) else base.get("repo")
    requested_users = pr.get("requested_reviewers")
    requested_teams = pr.get("requested_teams")
    pr_node_id = _node_id(pr.get("node_id"))
    if not isinstance(author, Mapping):
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "pull request author identity is missing"
        )
    author_login = _login(author.get("login"), name="pull request author login")
    author_id = author.get("id")
    if isinstance(author_id, bool) or not isinstance(author_id, int) or author_id < 1:
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "pull request author id is invalid"
        )
    if (
        pr.get("number") != reservation.pull_request_number
        or pr.get("url") != reservation.pull_request_api_url
        or pr.get("html_url") != reservation.pull_request_html_url
        or hashlib.sha256(pr_node_id.encode("utf-8")).hexdigest()
        != reservation.pull_request_node_id_sha256
        or pr.get("state") != "open"
        or pr.get("closed_at") is not None
        or pr.get("merged_at") is not None
        or pr.get("draft") is not False
        or pr.get("title") != requirements.pr_title
        or pr.get("body") != requirements.pr_body
        or pr.get("maintainer_can_modify") is not False
        or pr.get("updated_at") != target.ready_updated_at_utc
        or not isinstance(requested_users, list)
        or requested_users
        or not isinstance(requested_teams, list)
        or requested_teams
        or not isinstance(head, Mapping)
        or head.get("ref") != reservation.head_branch
        or head.get("sha") != reservation.predicted_commit_sha
        or not isinstance(head_repo, Mapping)
        or head_repo.get("full_name") != reservation.repository
        or not isinstance(base, Mapping)
        or base.get("ref") != reservation.base_branch
        or not isinstance(base_repo, Mapping)
        or base_repo.get("full_name") != reservation.repository
    ):
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "pull request drifted before reviewer identity observation"
        )
    if (
        author_login.lower() == reservation.reviewer_login.lower()
        or author_id == reservation.reviewer_user_id
    ):
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "self-review target is forbidden"
        )

    return MappingProxyType(
        {
            "reviewer_user_api_url": user_url,
            "reviewer_user_html_url": str(user["html_url"]),
            "reviewer_user_node_id_sha256": hashlib.sha256(
                node_id.encode("utf-8")
            ).hexdigest(),
            "pull_request_author_login": author_login,
            "pull_request_author_user_id": author_id,
            "user_request_url_sha256": hashlib.sha256(
                user_url.encode("utf-8")
            ).hexdigest(),
            "user_response_body_sha256": hashlib.sha256(user_payload).hexdigest(),
            "user_response_etag_sha256": hashlib.sha256(
                user_etag.encode("utf-8")
            ).hexdigest(),
            "pr_request_url_sha256": hashlib.sha256(
                pr_url.encode("utf-8")
            ).hexdigest(),
            "pr_response_body_sha256": hashlib.sha256(pr_payload).hexdigest(),
            "pr_response_etag_sha256": hashlib.sha256(
                pr_etag.encode("utf-8")
            ).hexdigest(),
        }
    )


def _validate_reader_evidence(
    value: Any,
    *,
    reservation: PilotExactTaskPrReviewerRequestReservationReceipt,
) -> Mapping[str, Any]:
    expected = {
        "reviewer_user_api_url",
        "reviewer_user_html_url",
        "reviewer_user_node_id_sha256",
        "pull_request_author_login",
        "pull_request_author_user_id",
        "user_request_url_sha256",
        "user_response_body_sha256",
        "user_response_etag_sha256",
        "pr_request_url_sha256",
        "pr_response_body_sha256",
        "pr_response_etag_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "reviewer identity evidence fields mismatch"
        )
    result = dict(value)
    expected_user_url = f"https://api.github.com/users/{reservation.reviewer_login}"
    if (
        result.get("reviewer_user_api_url") != expected_user_url
        or result.get("reviewer_user_html_url")
        != f"https://github.com/{reservation.reviewer_login}"
    ):
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "reviewer identity evidence URL binding mismatch"
        )
    for name in (
        "reviewer_user_node_id_sha256",
        "user_request_url_sha256",
        "user_response_body_sha256",
        "user_response_etag_sha256",
        "pr_request_url_sha256",
        "pr_response_body_sha256",
        "pr_response_etag_sha256",
    ):
        _hex64(result.get(name), name=name)
    if (
        result["user_request_url_sha256"]
        != hashlib.sha256(expected_user_url.encode("utf-8")).hexdigest()
        or result["pr_request_url_sha256"]
        != hashlib.sha256(reservation.pull_request_api_url.encode("utf-8")).hexdigest()
    ):
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "reviewer identity evidence request digest mismatch"
        )
    author_login = _login(
        result.get("pull_request_author_login"),
        name="pull request author login",
    )
    author_id = result.get("pull_request_author_user_id")
    if (
        isinstance(author_id, bool)
        or not isinstance(author_id, int)
        or author_id < 1
        or author_login.lower() == reservation.reviewer_login.lower()
        or author_id == reservation.reviewer_user_id
    ):
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "reviewer identity evidence does not exclude self review"
        )
    return MappingProxyType(result)


_live_records: dict[
    int,
    tuple[
        int,
        str,
        weakref.ReferenceType[Any],
        weakref.ReferenceType[PilotExactTaskPrReviewerRequestReservationReceipt],
    ],
] = {}


def _mark_pr_reviewer_identity_observation_authenticated(
    observation: Any,
    reservation: PilotExactTaskPrReviewerRequestReservationReceipt,
) -> None:
    key = id(observation)

    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)

    _live_records[key] = (
        os.getpid(),
        observation.sha256,
        weakref.ref(observation, cleanup),
        weakref.ref(reservation),
    )


def _get_live_pr_reviewer_identity_observation_inputs(
    observation: Any,
) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(observation))
    if entry is None:
        return None
    pid, digest, observation_ref, reservation_ref = entry
    reservation = reservation_ref()
    if (
        pid != os.getpid()
        or observation_ref() is not observation
        or reservation is None
        or reservation.reservation_authenticated is not True
        or reservation.sha256 != observation.reviewer_request_reservation_sha256
        or observation.sha256 != digest
    ):
        return None
    return MappingProxyType({"reviewer_request_reservation": reservation})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReviewerIdentityObservation:
    reviewer_request_reservation_sha256: str
    reviewer_target_attestation_sha256: str
    reviewer_handoff_requirements_sha256: str
    reviewer_target_policy_sha256: str
    reviewer_target_policy_epoch: int
    reviewer_request_nonce_sha256: str
    repository: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_html_url: str
    pull_request_node_id_sha256: str
    base_branch: str
    head_branch: str
    predicted_commit_sha: str
    ready_updated_at_utc: str
    reviewer_login: str
    reviewer_user_id: int
    reviewer_user_api_url: str
    reviewer_user_html_url: str
    reviewer_user_node_id_sha256: str
    pull_request_author_login: str
    pull_request_author_user_id: int
    user_request_url_sha256: str
    user_response_body_sha256: str
    user_response_etag_sha256: str
    pr_request_url_sha256: str
    pr_response_body_sha256: str
    pr_response_etag_sha256: str
    reserved_at_utc: str
    observed_at_utc: str
    reviewer_request_authorization_consumed: bool = True
    reviewer_request_slot_reserved: bool = True
    reviewer_identity_verified: bool = True
    pull_request_author_verified: bool = True
    self_review_excluded: bool = True
    no_requested_reviewers_verified: bool = True
    exact_pr_state_reverified: bool = True
    credential_free_reads: bool = True
    redirects_forbidden: bool = True
    response_bounded: bool = True
    reviewer_requestability_observation_required: bool = True
    fresh_pr_state_revalidation_before_reviewer_request_required: bool = True
    reviewer_request_transaction_required: bool = True
    team_reviewers_forbidden: bool = True
    reviewer_mutation_authorized: bool = False
    reviewer_request_performed: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_OBSERVATION_AUTHORITY
    observation_scope: str = PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_OBSERVATION_SCOPE
    schema: str = PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_OBSERVATION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_OBSERVATION_AUTHORITY
            or self.observation_scope
            != PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_OBSERVATION_SCOPE
        ):
            raise PilotExactTaskPrReviewerIdentityObservationError(
                "reviewer identity schema/authority/scope is unsupported"
            )
        for name in (
            "reviewer_request_reservation_sha256",
            "reviewer_target_attestation_sha256",
            "reviewer_handoff_requirements_sha256",
            "reviewer_target_policy_sha256",
            "reviewer_request_nonce_sha256",
            "pull_request_node_id_sha256",
            "reviewer_user_node_id_sha256",
            "user_request_url_sha256",
            "user_response_body_sha256",
            "user_response_etag_sha256",
            "pr_request_url_sha256",
            "pr_response_body_sha256",
            "pr_response_etag_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        ready = _utc(self.ready_updated_at_utc, name="ready_updated_at_utc")
        reserved = _utc(self.reserved_at_utc, name="reserved_at_utc")
        observed = _utc(self.observed_at_utc, name="observed_at_utc")
        if (
            reserved < ready
            or observed < reserved
            or (observed - reserved).total_seconds()
            > PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_MAX_RESERVATION_AGE_SECONDS
        ):
            raise PilotExactTaskPrReviewerIdentityObservationError(
                "reviewer identity observation timing is invalid"
            )
        _login(self.reviewer_login, name="reviewer_login")
        author_login = _login(
            self.pull_request_author_login,
            name="pull_request_author_login",
        )
        if (
            isinstance(self.reviewer_target_policy_epoch, bool)
            or not isinstance(self.reviewer_target_policy_epoch, int)
            or self.reviewer_target_policy_epoch < 1
            or isinstance(self.reviewer_user_id, bool)
            or not isinstance(self.reviewer_user_id, int)
            or self.reviewer_user_id < 1
            or isinstance(self.pull_request_author_user_id, bool)
            or not isinstance(self.pull_request_author_user_id, int)
            or self.pull_request_author_user_id < 1
            or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.repository != "Ternedal/ModelRig"
            or self.base_branch != "main"
            or self.reviewer_user_api_url
            != f"https://api.github.com/users/{self.reviewer_login}"
            or self.reviewer_user_html_url
            != f"https://github.com/{self.reviewer_login}"
            or author_login.lower() == self.reviewer_login.lower()
            or self.pull_request_author_user_id == self.reviewer_user_id
        ):
            raise PilotExactTaskPrReviewerIdentityObservationError(
                "reviewer identity observation binding is invalid"
            )
        required_true = (
            "reviewer_request_authorization_consumed",
            "reviewer_request_slot_reserved",
            "reviewer_identity_verified",
            "pull_request_author_verified",
            "self_review_excluded",
            "no_requested_reviewers_verified",
            "exact_pr_state_reverified",
            "credential_free_reads",
            "redirects_forbidden",
            "response_bounded",
            "reviewer_requestability_observation_required",
            "fresh_pr_state_revalidation_before_reviewer_request_required",
            "reviewer_request_transaction_required",
            "team_reviewers_forbidden",
        )
        forced_false = (
            "reviewer_mutation_authorized",
            "reviewer_request_performed",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrReviewerIdentityObservationError(
                "reviewer identity safety evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReviewerIdentityObservationError(
                "reviewer identity observation cannot grant mutation authority"
            )

    @property
    def observation_authenticated(self) -> bool:
        return _get_live_pr_reviewer_identity_observation_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(
        cls,
        value: Any,
    ) -> "PilotExactTaskPrReviewerIdentityObservation":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReviewerIdentityObservationError(
                "reviewer identity observation must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReviewerIdentityObservationError(
                "reviewer identity observation fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _observe_verified_pilot_exact_task_pr_reviewer_identity(
    *,
    reviewer_request_reservation: PilotExactTaskPrReviewerRequestReservationReceipt,
    reader: Callable[..., Mapping[str, Any]],
    now_provider: Callable[[], str],
) -> PilotExactTaskPrReviewerIdentityObservation:
    reservation, target, requirements = _require_live_reservation(
        reviewer_request_reservation
    )
    observed_at = now_provider()
    observed = _utc(observed_at, name="observed_at_utc")
    reserved = _utc(reservation.reserved_at_utc, name="reserved_at_utc")
    if (
        observed < reserved
        or (observed - reserved).total_seconds()
        > PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_MAX_RESERVATION_AGE_SECONDS
    ):
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "ADR-DC-069 reservation is stale for reviewer identity observation"
        )
    evidence = _validate_reader_evidence(
        reader(
            reviewer_request_reservation=reservation,
            reviewer_target_attestation=target,
            review_handoff_requirements=requirements,
        ),
        reservation=reservation,
    )
    result = PilotExactTaskPrReviewerIdentityObservation(
        reviewer_request_reservation_sha256=reservation.sha256,
        reviewer_target_attestation_sha256=reservation.reviewer_target_attestation_sha256,
        reviewer_handoff_requirements_sha256=reservation.reviewer_handoff_requirements_sha256,
        reviewer_target_policy_sha256=reservation.reviewer_target_policy_sha256,
        reviewer_target_policy_epoch=reservation.reviewer_target_policy_epoch,
        reviewer_request_nonce_sha256=reservation.reviewer_request_nonce_sha256,
        repository=reservation.repository,
        pull_request_number=reservation.pull_request_number,
        pull_request_api_url=reservation.pull_request_api_url,
        pull_request_html_url=reservation.pull_request_html_url,
        pull_request_node_id_sha256=reservation.pull_request_node_id_sha256,
        base_branch=reservation.base_branch,
        head_branch=reservation.head_branch,
        predicted_commit_sha=reservation.predicted_commit_sha,
        ready_updated_at_utc=target.ready_updated_at_utc,
        reviewer_login=reservation.reviewer_login,
        reviewer_user_id=reservation.reviewer_user_id,
        reviewer_user_api_url=str(evidence["reviewer_user_api_url"]),
        reviewer_user_html_url=str(evidence["reviewer_user_html_url"]),
        reviewer_user_node_id_sha256=str(evidence["reviewer_user_node_id_sha256"]),
        pull_request_author_login=str(evidence["pull_request_author_login"]),
        pull_request_author_user_id=int(evidence["pull_request_author_user_id"]),
        user_request_url_sha256=str(evidence["user_request_url_sha256"]),
        user_response_body_sha256=str(evidence["user_response_body_sha256"]),
        user_response_etag_sha256=str(evidence["user_response_etag_sha256"]),
        pr_request_url_sha256=str(evidence["pr_request_url_sha256"]),
        pr_response_body_sha256=str(evidence["pr_response_body_sha256"]),
        pr_response_etag_sha256=str(evidence["pr_response_etag_sha256"]),
        reserved_at_utc=reservation.reserved_at_utc,
        observed_at_utc=observed_at,
    )
    _mark_pr_reviewer_identity_observation_authenticated(result, reservation)
    if result.observation_authenticated is not True:
        raise PilotExactTaskPrReviewerIdentityObservationError(
            "reviewer identity observation lost live ADR-DC-069 provenance"
        )
    return result


def observe_pilot_exact_task_pr_reviewer_identity(
    reviewer_request_reservation: PilotExactTaskPrReviewerRequestReservationReceipt,
) -> PilotExactTaskPrReviewerIdentityObservation:
    return _observe_verified_pilot_exact_task_pr_reviewer_identity(
        reviewer_request_reservation=reviewer_request_reservation,
        reader=_read_exact_reviewer_identity,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_OBSERVATION_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_OBSERVATION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_OBSERVATION_SCOPE",
    "PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_MAX_RESERVATION_AGE_SECONDS",
    "PilotExactTaskPrReviewerIdentityObservationError",
    "PilotExactTaskPrReviewerIdentityObservation",
    "observe_pilot_exact_task_pr_reviewer_identity",
]
