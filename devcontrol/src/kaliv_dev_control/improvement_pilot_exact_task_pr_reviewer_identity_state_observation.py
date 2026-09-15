"""ADR-DC-070 credential-free reviewer identity and ready-PR state observation.

Consumes one exact live ADR-DC-069 reviewer-request reservation and performs two
bounded fixed-origin GETs: the host-pinned GitHub user and the exact ready pull
request. This proves public reviewer identity, non-self-review, and unchanged PR
state only. It deliberately does not claim repository-level requestability and
performs no GitHub mutation.
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

PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_OBSERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-reviewer-identity-state-observation/v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_OBSERVATION_AUTHORITY = (
    "observed-one-dc-l16-exact-pr-reviewer-identity-and-ready-state-only"
)
PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_OBSERVATION_SCOPE = (
    "one-credential-free-reviewer-identity-and-ready-pr-state-v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_API_VERSION = "2022-11-28"
PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_TIMEOUT_SECONDS = 20
PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_MAX_RESPONSE_BYTES = 256 * 1024
PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_MAX_RESERVATION_AGE_SECONDS = 60

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_NODE_ID = re.compile(r"^[A-Za-z0-9_+/=-]{8,256}$")


class PilotExactTaskPrReviewerIdentityStateObservationError(ValueError):
    """Reviewer identity or ready-PR state is stale, ambiguous, or unsafe."""


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
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            "reviewer identity/state observation is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrReviewerIdentityStateObservationError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrReviewerIdentityStateObservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            f"{name} is invalid"
        ) from exc


def _login(value: Any, *, name: str = "reviewer_login") -> str:
    if not isinstance(value, str) or _LOGIN.fullmatch(value) is None:
        raise PilotExactTaskPrReviewerIdentityStateObservationError(f"{name} is invalid")
    return value


def _node_id(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or value.strip() != value
        or _NODE_ID.fullmatch(value) is None
        or "\x00" in value
    ):
        raise PilotExactTaskPrReviewerIdentityStateObservationError(f"{name} is invalid")
    return value


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _require_live_reservation(
    value: Any,
) -> tuple[PilotExactTaskPrReviewerRequestReservationReceipt, Any, Any]:
    if type(value) is not PilotExactTaskPrReviewerRequestReservationReceipt:
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            "exact ADR-DC-069 reviewer-request reservation is required"
        )
    try:
        replayed = PilotExactTaskPrReviewerRequestReservationReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            "ADR-DC-069 reservation replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
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
    ):
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            "reviewer identity/state observation requires one live inert ADR-DC-069 reservation"
        )
    reservation_inputs = (
        reservation_boundary._get_live_pr_reviewer_request_reservation_inputs(value)
    )
    target = None if reservation_inputs is None else reservation_inputs.get(
        "reviewer_target_attestation"
    )
    if (
        target is None
        or getattr(target, "attestation_authenticated", None) is not True
        or target.sha256 != value.reviewer_target_attestation_sha256
        or target.reviewer_handoff_requirements_sha256
        != value.reviewer_handoff_requirements_sha256
        or target.ready_transaction_sha256 != value.ready_transaction_sha256
        or target.predicted_commit_sha != value.predicted_commit_sha
        or target.reviewer_handoff_plan_sha256 != value.reviewer_handoff_plan_sha256
        or target.reviewer_target_policy_sha256 != value.reviewer_target_policy_sha256
        or target.reviewer_target_policy_epoch != value.reviewer_target_policy_epoch
        or target.reviewer_login != value.reviewer_login
        or target.reviewer_user_id != value.reviewer_user_id
        or target.pull_request_number != value.pull_request_number
        or target.pull_request_api_url != value.pull_request_api_url
        or target.pull_request_node_id_sha256 != value.pull_request_node_id_sha256
    ):
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            "ADR-DC-069 lost exact live reviewer-target provenance"
        )
    target_inputs = target_boundary._get_live_pr_reviewer_target_attestation_inputs(target)
    requirements = None if target_inputs is None else target_inputs.get(
        "reviewer_handoff_requirements"
    )
    if (
        requirements is None
        or getattr(requirements, "requirements_authenticated", None) is not True
        or requirements.sha256 != value.reviewer_handoff_requirements_sha256
        or requirements.ready_transaction_sha256 != value.ready_transaction_sha256
        or requirements.predicted_commit_sha != value.predicted_commit_sha
        or requirements.reviewer_handoff_plan_sha256 != value.reviewer_handoff_plan_sha256
        or requirements.pull_request_number != value.pull_request_number
    ):
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            "ADR-DC-067 lost exact live ADR-DC-066 reviewer-handoff provenance"
        )
    return value, target, requirements


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _credential_free_json_get(*, url: str, user_agent: str) -> tuple[Mapping[str, Any], bytes, str]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_API_VERSION,
            "User-Agent": user_agent,
        },
    )
    lowered = {str(name).lower() for name in request.headers}
    if "authorization" in lowered or "cookie" in lowered:
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            "reviewer identity/state reads must remain credential free"
        )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(
            request,
            timeout=PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_TIMEOUT_SECONDS,
        ) as response:
            status = getattr(response, "status", None)
            headers = {str(k).lower(): str(v).strip() for k, v in response.headers.items()}
            payload = response.read(
                PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_MAX_RESPONSE_BYTES + 1
            )
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            "fixed-origin reviewer identity/state read failed"
        ) from exc
    if (
        status != 200
        or len(payload) > PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_MAX_RESPONSE_BYTES
    ):
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            "reviewer identity/state read status or size is unsafe"
        )
    try:
        document = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            "reviewer identity/state response is not UTF-8 JSON"
        ) from exc
    if not isinstance(document, Mapping):
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            "reviewer identity/state response must be an object"
        )
    etag = headers.get("etag", "")
    if len(etag) > 512 or "\r" in etag or "\n" in etag or "\x00" in etag:
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            "reviewer identity/state response ETag is invalid"
        )
    return document, payload, etag


def _read_exact_reviewer_identity(*, reservation_receipt: Any, reviewer_target: Any) -> Mapping[str, Any]:
    receipt = reservation_receipt
    target = reviewer_target
    login = _login(target.reviewer_login)
    url = f"https://api.github.com/users/{login}"
    document, payload, etag = _credential_free_json_get(
        url=url,
        user_agent="ModelRig-DevControl-ADR-DC-070-Reviewer",
    )
    node = _node_id(document.get("node_id"), name="reviewer_node_id")
    if (
        document.get("login") != login
        or document.get("id") != target.reviewer_user_id
        or document.get("type") != "User"
        or document.get("url") != url
        or receipt.reviewer_login != login
        or receipt.reviewer_user_id != target.reviewer_user_id
    ):
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            "public GitHub reviewer identity no longer matches host-pinned target"
        )
    return MappingProxyType(
        {
            "reviewer_request_url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
            "reviewer_response_body_sha256": hashlib.sha256(payload).hexdigest(),
            "reviewer_response_etag_sha256": hashlib.sha256(etag.encode("utf-8")).hexdigest(),
            "reviewer_node_id_sha256": hashlib.sha256(node.encode("utf-8")).hexdigest(),
        }
    )


def _read_exact_ready_pr_state(
    *,
    reservation_receipt: Any,
    reviewer_target: Any,
    reviewer_handoff_requirements: Any,
) -> Mapping[str, Any]:
    receipt = reservation_receipt
    target = reviewer_target
    requirements = reviewer_handoff_requirements
    url = receipt.pull_request_api_url
    document, payload, etag = _credential_free_json_get(
        url=url,
        user_agent="ModelRig-DevControl-ADR-DC-070-PR",
    )
    head = document.get("head")
    base = document.get("base")
    author = document.get("user")
    head_repo = None if not isinstance(head, Mapping) else head.get("repo")
    base_repo = None if not isinstance(base, Mapping) else base.get("repo")
    requested_reviewers = document.get("requested_reviewers")
    requested_teams = document.get("requested_teams")
    if not isinstance(author, Mapping):
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            "pull-request author identity is unavailable"
        )
    author_id = author.get("id")
    author_login = author.get("login")
    if (
        isinstance(author_id, bool)
        or not isinstance(author_id, int)
        or author_id < 1
        or not isinstance(author_login, str)
        or _LOGIN.fullmatch(author_login) is None
    ):
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            "pull-request author identity is invalid"
        )
    if author_id == target.reviewer_user_id:
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            "host-pinned reviewer is the pull-request author"
        )
    if (
        document.get("number") != receipt.pull_request_number
        or document.get("url") != receipt.pull_request_api_url
        or document.get("html_url") != receipt.pull_request_html_url
        or hashlib.sha256(
            _node_id(document.get("node_id"), name="pull_request_node_id").encode("utf-8")
        ).hexdigest()
        != receipt.pull_request_node_id_sha256
        or document.get("state") != "open"
        or document.get("closed_at") is not None
        or document.get("merged_at") is not None
        or document.get("draft") is not False
        or document.get("title") != requirements.pr_title
        or document.get("body") != requirements.pr_body
        or document.get("maintainer_can_modify") is not False
        or document.get("updated_at") != target.ready_updated_at_utc
        or not isinstance(requested_reviewers, list)
        or len(requested_reviewers) != 0
        or not isinstance(requested_teams, list)
        or len(requested_teams) != 0
        or not isinstance(head, Mapping)
        or head.get("ref") != receipt.head_branch
        or head.get("sha") != receipt.predicted_commit_sha
        or not isinstance(head_repo, Mapping)
        or head_repo.get("full_name") != receipt.repository
        or not isinstance(base, Mapping)
        or base.get("ref") != receipt.base_branch
        or not isinstance(base_repo, Mapping)
        or base_repo.get("full_name") != receipt.repository
    ):
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            "ready pull request no longer matches exact reviewer-request preconditions"
        )
    return MappingProxyType(
        {
            "pr_request_url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
            "pr_response_body_sha256": hashlib.sha256(payload).hexdigest(),
            "pr_response_etag_sha256": hashlib.sha256(etag.encode("utf-8")).hexdigest(),
            "pull_request_author_login": author_login,
            "pull_request_author_user_id": author_id,
            "observed_updated_at_utc": target.ready_updated_at_utc,
            "requested_reviewer_count": 0,
            "requested_team_count": 0,
        }
    )


def _validate_identity_evidence(value: Any, *, receipt: Any, target: Any) -> Mapping[str, Any]:
    expected = {
        "reviewer_request_url_sha256",
        "reviewer_response_body_sha256",
        "reviewer_response_etag_sha256",
        "reviewer_node_id_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            "reviewer identity evidence fields mismatch"
        )
    result = dict(value)
    for name in expected:
        _hex64(result.get(name), name=name)
    expected_url = f"https://api.github.com/users/{_login(target.reviewer_login)}"
    if (
        result["reviewer_request_url_sha256"]
        != hashlib.sha256(expected_url.encode("utf-8")).hexdigest()
        or receipt.reviewer_user_id != target.reviewer_user_id
    ):
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            "reviewer identity evidence does not match exact target"
        )
    return MappingProxyType(result)


def _validate_pr_evidence(value: Any, *, receipt: Any, target: Any) -> Mapping[str, Any]:
    expected = {
        "pr_request_url_sha256",
        "pr_response_body_sha256",
        "pr_response_etag_sha256",
        "pull_request_author_login",
        "pull_request_author_user_id",
        "observed_updated_at_utc",
        "requested_reviewer_count",
        "requested_team_count",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            "pull-request state evidence fields mismatch"
        )
    result = dict(value)
    for name in ("pr_request_url_sha256", "pr_response_body_sha256", "pr_response_etag_sha256"):
        _hex64(result.get(name), name=name)
    if (
        result["pr_request_url_sha256"]
        != hashlib.sha256(receipt.pull_request_api_url.encode("utf-8")).hexdigest()
        or result["observed_updated_at_utc"] != target.ready_updated_at_utc
        or result["requested_reviewer_count"] != 0
        or result["requested_team_count"] != 0
        or isinstance(result["pull_request_author_user_id"], bool)
        or not isinstance(result["pull_request_author_user_id"], int)
        or result["pull_request_author_user_id"] < 1
        or result["pull_request_author_user_id"] == target.reviewer_user_id
        or not isinstance(result["pull_request_author_login"], str)
        or _LOGIN.fullmatch(result["pull_request_author_login"]) is None
    ):
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            "pull-request state evidence does not match exact ready state"
        )
    _utc(result["observed_updated_at_utc"], name="observed_updated_at_utc")
    return MappingProxyType(result)


_live_records: dict[
    int,
    tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[Any]],
] = {}


def _mark_pr_reviewer_identity_state_observation_authenticated(
    observation: Any,
    reservation_receipt: PilotExactTaskPrReviewerRequestReservationReceipt,
) -> None:
    key = id(observation)

    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)

    _live_records[key] = (
        os.getpid(),
        observation.sha256,
        weakref.ref(observation, cleanup),
        weakref.ref(reservation_receipt),
    )


def _get_live_pr_reviewer_identity_state_observation_inputs(observation: Any) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(observation))
    if entry is None:
        return None
    pid, digest, observation_ref, receipt_ref = entry
    receipt = receipt_ref()
    if (
        pid != os.getpid()
        or observation_ref() is not observation
        or receipt is None
        or receipt.reservation_authenticated is not True
        or receipt.sha256 != observation.reviewer_request_reservation_sha256
        or observation.sha256 != digest
    ):
        return None
    return MappingProxyType({"reviewer_request_reservation": receipt})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReviewerIdentityStateObservation:
    reviewer_request_reservation_sha256: str
    reviewer_target_attestation_sha256: str
    reviewer_handoff_requirements_sha256: str
    ready_transaction_sha256: str
    predicted_commit_sha: str
    reviewer_handoff_plan_sha256: str
    reviewer_target_policy_sha256: str
    reviewer_target_policy_epoch: int
    ready_for_review_nonce_sha256: str
    reviewer_request_nonce_sha256: str
    repository: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_html_url: str
    pull_request_node_id_sha256: str
    base_branch: str
    head_branch: str
    ready_updated_at_utc: str
    reviewer_login: str
    reviewer_user_id: int
    reviewer_node_id_sha256: str
    pull_request_author_login: str
    pull_request_author_user_id: int
    reviewer_request_url_sha256: str
    reviewer_response_body_sha256: str
    reviewer_response_etag_sha256: str
    pr_request_url_sha256: str
    pr_response_body_sha256: str
    pr_response_etag_sha256: str
    observed_updated_at_utc: str
    observed_at_utc: str
    reviewer_public_identity_verified: bool = True
    reviewer_numeric_user_id_verified: bool = True
    reviewer_not_pr_author_verified: bool = True
    ready_pr_state_freshly_revalidated: bool = True
    no_requested_reviewers_verified: bool = True
    credential_free_reads: bool = True
    redirects_forbidden: bool = True
    responses_bounded: bool = True
    reviewer_requestability_verified: bool = False
    credentialed_reviewer_requestability_check_required: bool = True
    reviewer_request_credential_capability_required: bool = True
    reviewer_request_transaction_required: bool = True
    team_reviewers_forbidden: bool = True
    label_mutation_separate_authority_required: bool = True
    merge_separate_authority_required: bool = True
    reviewer_mutation_authorized: bool = False
    reviewer_request_performed: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_OBSERVATION_AUTHORITY
    observation_scope: str = PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_OBSERVATION_SCOPE
    schema: str = PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_OBSERVATION_SCHEMA
            or self.authority != PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_OBSERVATION_AUTHORITY
            or self.observation_scope != PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_OBSERVATION_SCOPE
        ):
            raise PilotExactTaskPrReviewerIdentityStateObservationError(
                "reviewer identity/state observation schema/authority/scope is unsupported"
            )
        for name in (
            "reviewer_request_reservation_sha256",
            "reviewer_target_attestation_sha256",
            "reviewer_handoff_requirements_sha256",
            "ready_transaction_sha256",
            "reviewer_handoff_plan_sha256",
            "reviewer_target_policy_sha256",
            "ready_for_review_nonce_sha256",
            "reviewer_request_nonce_sha256",
            "pull_request_node_id_sha256",
            "reviewer_node_id_sha256",
            "reviewer_request_url_sha256",
            "reviewer_response_body_sha256",
            "reviewer_response_etag_sha256",
            "pr_request_url_sha256",
            "pr_response_body_sha256",
            "pr_response_etag_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _login(self.reviewer_login)
        _login(self.pull_request_author_login, name="pull_request_author_login")
        ready = _utc(self.ready_updated_at_utc, name="ready_updated_at_utc")
        observed_updated = _utc(self.observed_updated_at_utc, name="observed_updated_at_utc")
        observed = _utc(self.observed_at_utc, name="observed_at_utc")
        if ready != observed_updated:
            raise PilotExactTaskPrReviewerIdentityStateObservationError(
                "observed PR state does not match exact ready-state timestamp"
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
            or self.pull_request_author_user_id == self.reviewer_user_id
            or self.repository != "Ternedal/ModelRig"
            or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
            or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"https://api.github.com/repos/Ternedal/ModelRig/pulls/{self.pull_request_number}"
            or self.pull_request_html_url
            != f"https://github.com/Ternedal/ModelRig/pull/{self.pull_request_number}"
        ):
            raise PilotExactTaskPrReviewerIdentityStateObservationError(
                "reviewer identity/state target binding is invalid"
            )
        if observed < ready:
            raise PilotExactTaskPrReviewerIdentityStateObservationError(
                "reviewer identity/state observation predates ready PR state"
            )
        required_true = (
            "reviewer_public_identity_verified",
            "reviewer_numeric_user_id_verified",
            "reviewer_not_pr_author_verified",
            "ready_pr_state_freshly_revalidated",
            "no_requested_reviewers_verified",
            "credential_free_reads",
            "redirects_forbidden",
            "responses_bounded",
            "credentialed_reviewer_requestability_check_required",
            "reviewer_request_credential_capability_required",
            "reviewer_request_transaction_required",
            "team_reviewers_forbidden",
            "label_mutation_separate_authority_required",
            "merge_separate_authority_required",
        )
        forced_false = (
            "reviewer_requestability_verified",
            "reviewer_mutation_authorized",
            "reviewer_request_performed",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrReviewerIdentityStateObservationError(
                "reviewer identity/state safety evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReviewerIdentityStateObservationError(
                "reviewer identity/state observation cannot grant mutation authority"
            )

    @property
    def observation_authenticated(self) -> bool:
        return _get_live_pr_reviewer_identity_state_observation_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrReviewerIdentityStateObservation":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReviewerIdentityStateObservationError(
                "reviewer identity/state observation must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReviewerIdentityStateObservationError(
                "reviewer identity/state observation fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _observe_verified_pilot_exact_task_pr_reviewer_identity_state(
    *,
    reviewer_request_reservation: PilotExactTaskPrReviewerRequestReservationReceipt,
    reviewer_reader: Callable[..., Mapping[str, Any]],
    pr_reader: Callable[..., Mapping[str, Any]],
    now_provider: Callable[[], str],
) -> PilotExactTaskPrReviewerIdentityStateObservation:
    receipt, target, requirements = _require_live_reservation(reviewer_request_reservation)
    reviewer_evidence = _validate_identity_evidence(
        reviewer_reader(
            reservation_receipt=receipt,
            reviewer_target=target,
        ),
        receipt=receipt,
        target=target,
    )
    pr_evidence = _validate_pr_evidence(
        pr_reader(
            reservation_receipt=receipt,
            reviewer_target=target,
            reviewer_handoff_requirements=requirements,
        ),
        receipt=receipt,
        target=target,
    )
    observed_at = now_provider()
    observed = _utc(observed_at, name="observed_at_utc")
    reserved = _utc(receipt.reserved_at_utc, name="reserved_at_utc")
    if observed < reserved or (
        observed - reserved
    ).total_seconds() > PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_MAX_RESERVATION_AGE_SECONDS:
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            "reviewer identity/state observation is too far from nonce reservation"
        )
    result = PilotExactTaskPrReviewerIdentityStateObservation(
        reviewer_request_reservation_sha256=receipt.sha256,
        reviewer_target_attestation_sha256=receipt.reviewer_target_attestation_sha256,
        reviewer_handoff_requirements_sha256=receipt.reviewer_handoff_requirements_sha256,
        ready_transaction_sha256=receipt.ready_transaction_sha256,
        predicted_commit_sha=receipt.predicted_commit_sha,
        reviewer_handoff_plan_sha256=receipt.reviewer_handoff_plan_sha256,
        reviewer_target_policy_sha256=receipt.reviewer_target_policy_sha256,
        reviewer_target_policy_epoch=receipt.reviewer_target_policy_epoch,
        ready_for_review_nonce_sha256=receipt.ready_for_review_nonce_sha256,
        reviewer_request_nonce_sha256=receipt.reviewer_request_nonce_sha256,
        repository=receipt.repository,
        pull_request_number=receipt.pull_request_number,
        pull_request_api_url=receipt.pull_request_api_url,
        pull_request_html_url=receipt.pull_request_html_url,
        pull_request_node_id_sha256=receipt.pull_request_node_id_sha256,
        base_branch=receipt.base_branch,
        head_branch=receipt.head_branch,
        ready_updated_at_utc=target.ready_updated_at_utc,
        reviewer_login=receipt.reviewer_login,
        reviewer_user_id=receipt.reviewer_user_id,
        reviewer_node_id_sha256=reviewer_evidence["reviewer_node_id_sha256"],
        pull_request_author_login=pr_evidence["pull_request_author_login"],
        pull_request_author_user_id=pr_evidence["pull_request_author_user_id"],
        reviewer_request_url_sha256=reviewer_evidence["reviewer_request_url_sha256"],
        reviewer_response_body_sha256=reviewer_evidence["reviewer_response_body_sha256"],
        reviewer_response_etag_sha256=reviewer_evidence["reviewer_response_etag_sha256"],
        pr_request_url_sha256=pr_evidence["pr_request_url_sha256"],
        pr_response_body_sha256=pr_evidence["pr_response_body_sha256"],
        pr_response_etag_sha256=pr_evidence["pr_response_etag_sha256"],
        observed_updated_at_utc=pr_evidence["observed_updated_at_utc"],
        observed_at_utc=observed_at,
    )
    _mark_pr_reviewer_identity_state_observation_authenticated(result, receipt)
    if result.observation_authenticated is not True:
        raise PilotExactTaskPrReviewerIdentityStateObservationError(
            "reviewer identity/state observation lost live durable reservation provenance"
        )
    return result


def observe_pilot_exact_task_pr_reviewer_identity_state(
    reviewer_request_reservation: PilotExactTaskPrReviewerRequestReservationReceipt,
) -> PilotExactTaskPrReviewerIdentityStateObservation:
    """Freshly prove public reviewer identity and unchanged ready PR state only."""
    return _observe_verified_pilot_exact_task_pr_reviewer_identity_state(
        reviewer_request_reservation=reviewer_request_reservation,
        reviewer_reader=_read_exact_reviewer_identity,
        pr_reader=_read_exact_ready_pr_state,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_OBSERVATION_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_OBSERVATION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_OBSERVATION_SCOPE",
    "PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_MAX_RESERVATION_AGE_SECONDS",
    "PilotExactTaskPrReviewerIdentityStateObservationError",
    "PilotExactTaskPrReviewerIdentityStateObservation",
    "observe_pilot_exact_task_pr_reviewer_identity_state",
]
