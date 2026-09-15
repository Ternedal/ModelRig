"""ADR-DC-056 read-only GitHub PR-state observation for one reserved draft PR.

Consumes one live authenticated ADR-DC-055 reservation receipt and performs one
fixed-origin, unauthenticated GET against the public Ternedal/ModelRig pull-list
endpoint. Only an empty open-PR result for the exact reserved head/base is
accepted. No GitHub mutation authority is granted.
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
from types import MappingProxyType
from typing import Any, Callable, Mapping

from . import improvement_pilot_exact_task_pr_mutation_reservation as reservation_boundary
from .improvement_pilot_exact_task_pr_mutation_reservation import (
    PILOT_EXACT_TASK_PR_MUTATION_RESERVATION_AUTHORITY,
    PilotExactTaskPrMutationReservationReceipt,
)

PILOT_EXACT_TASK_PR_STATE_OBSERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-state-observation/v1"
)
PILOT_EXACT_TASK_PR_STATE_OBSERVATION_AUTHORITY = (
    "observed-zero-open-prs-for-one-reserved-draft-pr-only"
)
PILOT_EXACT_TASK_PR_STATE_OBSERVATION_ORIGIN = "https://api.github.com"
PILOT_EXACT_TASK_PR_STATE_OBSERVATION_API_VERSION = "2022-11-28"
PILOT_EXACT_TASK_PR_STATE_OBSERVATION_MAX_RESPONSE_BYTES = 256 * 1024
PILOT_EXACT_TASK_PR_STATE_OBSERVATION_TIMEOUT_SECONDS = 20

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")


class PilotExactTaskPrStateObservationError(ValueError):
    """The exact PR-state observation is malformed, stale, ambiguous, or unsafe."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPrStateObservationError("PR-state observation is not canonical JSON") from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrStateObservationError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrStateObservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrStateObservationError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskPrStateObservationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_live_reservation(value: Any) -> tuple[PilotExactTaskPrMutationReservationReceipt, Any]:
    if type(value) is not PilotExactTaskPrMutationReservationReceipt:
        raise PilotExactTaskPrStateObservationError("exact ADR-DC-055 reservation receipt is required")
    try:
        replayed = PilotExactTaskPrMutationReservationReceipt.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrStateObservationError("ADR-DC-055 reservation replay validation failed") from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrStateObservationError("ADR-DC-055 reservation identity mismatch")
    if (
        value.authority != PILOT_EXACT_TASK_PR_MUTATION_RESERVATION_AUTHORITY
        or value.reservation_authenticated is not True
        or value.host_replay_guard_committed is not True
        or value.human_pr_mutation_authorization_freshly_verified is not True
        or value.pr_mutation_authorization_consumed is not True
        or value.pr_mutation_slot_reserved is not True
        or value.no_existing_open_pr_observation_required is not True
        or value.create_new_draft_pull_request_required is not True
        or value.draft_pull_request_required is not True
        or value.maintainer_can_modify is not False
        or value.pr_mutation_authorized is not False
        or value.pull_request_create_authorized is not False
        or value.pull_request_created is not False
        or value.ready_for_review_authorized is not False
        or value.reviewer_mutation_authorized is not False
        or value.label_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.repository != "Ternedal/ModelRig"
        or value.base_branch != "main"
        or _HEAD.fullmatch(value.head_branch) is None
    ):
        raise PilotExactTaskPrStateObservationError("PR-state observation requires one live inert ADR-DC-055 reservation")
    inputs = reservation_boundary._get_live_pr_mutation_reservation_inputs(value)
    requirements = None if inputs is None else inputs.get("pr_mutation_requirements")
    if (
        requirements is None
        or getattr(requirements, "requirements_authenticated", None) is not True
        or requirements.sha256 != value.pr_mutation_requirements_sha256
        or requirements.pr_plan_sha256 != value.pr_plan_sha256
        or requirements.repository != value.repository
        or requirements.base_branch != value.base_branch
        or requirements.head_branch != value.head_branch
    ):
        raise PilotExactTaskPrStateObservationError("ADR-DC-055 reservation lost live deterministic PR-plan provenance")
    return value, requirements


def _query_url(*, head_branch: str) -> str:
    if _HEAD.fullmatch(head_branch) is None:
        raise PilotExactTaskPrStateObservationError("PR head branch is invalid")
    query = urllib.parse.urlencode((
        ("state", "open"),
        ("head", f"Ternedal:{head_branch}"),
        ("base", "main"),
        ("per_page", "2"),
    ))
    return f"{PILOT_EXACT_TASK_PR_STATE_OBSERVATION_ORIGIN}/repos/Ternedal/ModelRig/pulls?{query}"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _read_public_open_pr_state(*, head_branch: str) -> Mapping[str, Any]:
    url = _query_url(head_branch=head_branch)
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": PILOT_EXACT_TASK_PR_STATE_OBSERVATION_API_VERSION,
            "User-Agent": "ModelRig-DevControl-ADR-DC-056",
        },
    )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(request, timeout=PILOT_EXACT_TASK_PR_STATE_OBSERVATION_TIMEOUT_SECONDS) as response:
            status = getattr(response, "status", None)
            headers = {str(k).lower(): str(v).strip() for k, v in response.headers.items()}
            payload = response.read(PILOT_EXACT_TASK_PR_STATE_OBSERVATION_MAX_RESPONSE_BYTES + 1)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PilotExactTaskPrStateObservationError("fixed-origin GitHub PR-state read failed") from exc
    if status != 200:
        raise PilotExactTaskPrStateObservationError("GitHub PR-state read returned a non-success status")
    if len(payload) > PILOT_EXACT_TASK_PR_STATE_OBSERVATION_MAX_RESPONSE_BYTES:
        raise PilotExactTaskPrStateObservationError("GitHub PR-state response exceeded byte ceiling")
    link = headers.get("link", "").replace(" ", "").lower()
    if 'rel="next"' in link or "rel=next" in link:
        raise PilotExactTaskPrStateObservationError("GitHub PR-state response unexpectedly paginated")
    if any(name in request.headers for name in ("Authorization", "Cookie")):
        raise PilotExactTaskPrStateObservationError("PR-state read must not carry credentials")
    try:
        document = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrStateObservationError("GitHub PR-state response is not UTF-8 JSON") from exc
    if not isinstance(document, list):
        raise PilotExactTaskPrStateObservationError("GitHub pull-list response must be an array")
    if document:
        raise PilotExactTaskPrStateObservationError("an open pull request already exists for the exact reserved head/base")
    etag = headers.get("etag", "")
    if len(etag) > 512 or "\r" in etag or "\n" in etag or "\x00" in etag:
        raise PilotExactTaskPrStateObservationError("GitHub PR-state ETag is invalid")
    return MappingProxyType({
        "request_url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
        "response_body_sha256": hashlib.sha256(payload).hexdigest(),
        "response_etag_sha256": hashlib.sha256(etag.encode("utf-8")).hexdigest(),
        "open_pr_match_count": 0,
    })


def _validate_reader_evidence(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "request_url_sha256", "response_body_sha256", "response_etag_sha256", "open_pr_match_count"
    }:
        raise PilotExactTaskPrStateObservationError("PR-state reader evidence fields mismatch")
    result = dict(value)
    for name in ("request_url_sha256", "response_body_sha256", "response_etag_sha256"):
        _hex64(result.get(name), name=name)
    if result.get("open_pr_match_count") != 0:
        raise PilotExactTaskPrStateObservationError("PR-state observation requires zero exact open PR matches")
    return result


def _live_registry():
    records: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[Any]]] = {}

    def mark(observation: Any, reservation: PilotExactTaskPrMutationReservationReceipt) -> None:
        key = id(observation)
        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)
        records[key] = (os.getpid(), observation.sha256, weakref.ref(observation, cleanup), weakref.ref(reservation))

    def get(observation: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(observation))
        if entry is None:
            return None
        pid, digest, observation_ref, reservation_ref = entry
        reservation = reservation_ref()
        if (
            pid != os.getpid()
            or observation_ref() is not observation
            or reservation is None
            or reservation.reservation_authenticated is not True
            or reservation.sha256 != observation.pr_mutation_reservation_sha256
            or observation.sha256 != digest
        ):
            return None
        return MappingProxyType({"pr_mutation_reservation": reservation})

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_pr_state_observation_authenticated, _get_live_pr_state_observation_inputs = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrStateObservation:
    pr_mutation_reservation_sha256: str
    pr_mutation_requirements_sha256: str
    remote_write_transaction_sha256: str
    predicted_commit_sha: str
    pr_plan_sha256: str
    pr_mutation_nonce_sha256: str
    repository: str
    base_branch: str
    head_branch: str
    request_url_sha256: str
    response_body_sha256: str
    response_etag_sha256: str
    open_pr_match_count: int
    observed_at_utc: str
    reservation_revalidated: bool = True
    fixed_origin_github_read: bool = True
    credential_free_read: bool = True
    redirects_forbidden: bool = True
    response_bounded: bool = True
    no_existing_open_pr_verified: bool = True
    create_new_draft_pull_request_required: bool = True
    fresh_pr_state_revalidation_before_create_required: bool = True
    maintainer_can_modify: bool = False
    pr_mutation_authorized: bool = False
    pull_request_create_authorized: bool = False
    pull_request_created: bool = False
    ready_for_review_authorized: bool = False
    reviewer_mutation_authorized: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_STATE_OBSERVATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PR_STATE_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PR_STATE_OBSERVATION_SCHEMA or self.authority != PILOT_EXACT_TASK_PR_STATE_OBSERVATION_AUTHORITY:
            raise PilotExactTaskPrStateObservationError("PR-state observation schema/authority is unsupported")
        for name in (
            "pr_mutation_reservation_sha256", "pr_mutation_requirements_sha256", "remote_write_transaction_sha256",
            "pr_plan_sha256", "pr_mutation_nonce_sha256", "request_url_sha256", "response_body_sha256", "response_etag_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _utc(self.observed_at_utc, name="observed_at_utc")
        if (
            self.repository != "Ternedal/ModelRig"
            or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
            or self.open_pr_match_count != 0
        ):
            raise PilotExactTaskPrStateObservationError("PR-state observation target/result binding is invalid")
        required_true = (
            "reservation_revalidated", "fixed_origin_github_read", "credential_free_read", "redirects_forbidden",
            "response_bounded", "no_existing_open_pr_verified", "create_new_draft_pull_request_required",
            "fresh_pr_state_revalidation_before_create_required",
        )
        forced_false = (
            "maintainer_can_modify", "pr_mutation_authorized", "pull_request_create_authorized", "pull_request_created",
            "ready_for_review_authorized", "reviewer_mutation_authorized", "label_mutation_authorized", "merge_authorized",
            "release_authorized", "deploy_authorized", "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrStateObservationError("PR-state observation evidence is incomplete")
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrStateObservationError("PR-state observation cannot grant GitHub mutation authority")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def observation_authenticated(self) -> bool:
        return _get_live_pr_state_observation_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrStateObservation":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrStateObservationError("PR-state observation must be an object")
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrStateObservationError("PR-state observation fields mismatch")
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _observe_verified_pilot_exact_task_pr_state(
    *,
    pr_mutation_reservation: PilotExactTaskPrMutationReservationReceipt,
    reader: Callable[..., Mapping[str, Any]],
    now_provider: Callable[[], str],
) -> PilotExactTaskPrStateObservation:
    reservation, requirements = _require_live_reservation(pr_mutation_reservation)
    evidence = _validate_reader_evidence(reader(head_branch=reservation.head_branch))
    observed_at = now_provider()
    _utc(observed_at, name="observed_at_utc")
    result = PilotExactTaskPrStateObservation(
        pr_mutation_reservation_sha256=reservation.sha256,
        pr_mutation_requirements_sha256=reservation.pr_mutation_requirements_sha256,
        remote_write_transaction_sha256=reservation.remote_write_transaction_sha256,
        predicted_commit_sha=reservation.predicted_commit_sha,
        pr_plan_sha256=reservation.pr_plan_sha256,
        pr_mutation_nonce_sha256=reservation.pr_mutation_nonce_sha256,
        repository=reservation.repository,
        base_branch=reservation.base_branch,
        head_branch=reservation.head_branch,
        request_url_sha256=evidence["request_url_sha256"],
        response_body_sha256=evidence["response_body_sha256"],
        response_etag_sha256=evidence["response_etag_sha256"],
        open_pr_match_count=evidence["open_pr_match_count"],
        observed_at_utc=observed_at,
    )
    _mark_pr_state_observation_authenticated(result, reservation)
    if result.observation_authenticated is not True or requirements.sha256 != result.pr_mutation_requirements_sha256:
        raise PilotExactTaskPrStateObservationError("PR-state observation lost live ADR-DC-055 provenance")
    return result


def observe_pilot_exact_task_pr_state(
    pr_mutation_reservation: PilotExactTaskPrMutationReservationReceipt,
) -> PilotExactTaskPrStateObservation:
    """Observe zero existing open PRs for the exact reserved plan; never mutate GitHub."""
    return _observe_verified_pilot_exact_task_pr_state(
        pr_mutation_reservation=pr_mutation_reservation,
        reader=_read_public_open_pr_state,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_STATE_OBSERVATION_SCHEMA",
    "PILOT_EXACT_TASK_PR_STATE_OBSERVATION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_STATE_OBSERVATION_ORIGIN",
    "PilotExactTaskPrStateObservationError",
    "PilotExactTaskPrStateObservation",
    "observe_pilot_exact_task_pr_state",
]
