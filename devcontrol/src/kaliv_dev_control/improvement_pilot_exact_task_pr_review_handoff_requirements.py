"""ADR-DC-059 read-only post-create verification and review-handoff requirements.

Consumes one exact live authenticated ADR-DC-058 draft-PR create transaction,
performs a fresh credential-free fixed-origin GET of that exact pull request,
and materializes one inert, deterministic ready-for-review handoff plan.
No GitHub mutation authority is granted here.
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

from . import improvement_pilot_exact_task_pr_create_transaction as transaction_boundary
from .improvement_pilot_exact_task_pr_create_transaction import (
    PILOT_EXACT_TASK_PR_CREATE_TRANSACTION_AUTHORITY,
    PilotExactTaskPrCreateTransaction,
)
from . import improvement_pilot_exact_task_pr_credential_capability as capability_boundary
from . import improvement_pilot_exact_task_pr_state_observation as observation_boundary
from . import improvement_pilot_exact_task_pr_mutation_reservation as reservation_boundary
from . import improvement_pilot_exact_task_pr_mutation_requirements as requirements_boundary

PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_REQUIREMENTS_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-review-handoff-requirements/v1"
)
PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_REQUIREMENTS_AUTHORITY = (
    "verified-one-dc-l16-exact-draft-pr-review-handoff-requirements-only"
)
PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_REQUIREMENTS_SCOPE = (
    "one-draft-pr-ready-handoff-only-v1"
)
PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_OPERATION = (
    "mark-pull-request-ready-for-review"
)
PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_ORIGIN = "https://api.github.com"
PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_API_VERSION = "2022-11-28"
PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_MAX_RESPONSE_BYTES = 256 * 1024
PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_TIMEOUT_SECONDS = 20

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")


class PilotExactTaskPrReviewHandoffRequirementsError(ValueError):
    """The exact post-create PR state or review handoff is unsafe or drifted."""


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
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            "review-handoff requirements are not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskPrReviewHandoffRequirementsError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskPrReviewHandoffRequirementsError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _require_live_transaction(
    value: Any,
) -> tuple[PilotExactTaskPrCreateTransaction, Any, Any]:
    if type(value) is not PilotExactTaskPrCreateTransaction:
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            "exact ADR-DC-058 PR create transaction is required"
        )
    try:
        replayed = PilotExactTaskPrCreateTransaction.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            "ADR-DC-058 transaction replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            "ADR-DC-058 transaction identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_PR_CREATE_TRANSACTION_AUTHORITY
        or value.transaction_authenticated is not True
        or value.host_transaction_start_committed is not True
        or value.pr_mutation_slot_consumed is not True
        or value.pull_request_created is not True
        or value.draft_pull_request_created is not True
        or value.post_create_readback_verified is not True
        or value.draft_state_verified is not True
        or value.exact_head_sha_verified is not True
        or value.exact_base_verified is not True
        or value.exact_metadata_verified is not True
        or value.maintainer_can_modify is not False
        or value.pr_mutation_authorized is not False
        or value.pull_request_create_authorized is not False
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
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            "review handoff requires one completed inert ADR-DC-058 transaction"
        )

    tx_inputs = transaction_boundary._get_live_pr_create_transaction_inputs(value)
    capability = None if tx_inputs is None else tx_inputs.get("pr_credential_capability")
    if (
        capability is None
        or getattr(capability, "capability_authenticated", None) is not True
        or getattr(capability, "sha256", None) != value.pr_credential_capability_sha256
    ):
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            "ADR-DC-058 lost exact live ADR-DC-057 capability provenance"
        )

    cap_inputs = capability_boundary._get_live_pr_credential_capability_inputs(capability)
    observation = None if cap_inputs is None else cap_inputs.get("pr_state_observation")
    if observation is None or getattr(observation, "observation_authenticated", None) is not True:
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            "ADR-DC-057 lost live ADR-DC-056 observation provenance"
        )
    obs_inputs = observation_boundary._get_live_pr_state_observation_inputs(observation)
    reservation = None if obs_inputs is None else obs_inputs.get("pr_mutation_reservation")
    if (
        reservation is None
        or getattr(reservation, "reservation_authenticated", None) is not True
        or getattr(reservation, "sha256", None) != value.pr_mutation_reservation_sha256
    ):
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            "ADR-DC-056 lost live ADR-DC-055 reservation provenance"
        )
    reservation_inputs = reservation_boundary._get_live_pr_mutation_reservation_inputs(
        reservation
    )
    requirements = None if reservation_inputs is None else reservation_inputs.get(
        "pr_mutation_requirements"
    )
    if (
        requirements is None
        or getattr(requirements, "requirements_authenticated", None) is not True
        or getattr(requirements, "sha256", None) != value.pr_mutation_requirements_sha256
        or getattr(requirements, "pr_plan_sha256", None) != value.pr_plan_sha256
        or getattr(requirements, "predicted_commit_sha", None) != value.predicted_commit_sha
        or getattr(requirements, "repository", None) != value.repository
        or getattr(requirements, "base_branch", None) != value.base_branch
        or getattr(requirements, "head_branch", None) != value.head_branch
    ):
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            "ADR-DC-055 lost live deterministic ADR-DC-054 requirements"
        )
    if requirements_boundary._get_live_pr_mutation_requirements_inputs(requirements) is None:
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            "ADR-DC-054 deterministic PR-plan provenance is unavailable"
        )
    return value, capability, requirements


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _read_exact_draft_pr_state(
    *,
    pr_create_transaction: PilotExactTaskPrCreateTransaction,
    pr_mutation_requirements: Any,
) -> Mapping[str, Any]:
    transaction = pr_create_transaction
    requirements = pr_mutation_requirements
    number = transaction.pull_request_number
    url = f"{PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_ORIGIN}/repos/Ternedal/ModelRig/pulls/{number}"
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_API_VERSION,
            "User-Agent": "ModelRig-DevControl-ADR-DC-059",
        },
    )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(
            request,
            timeout=PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_TIMEOUT_SECONDS,
        ) as response:
            status = getattr(response, "status", None)
            headers = {
                str(k).lower(): str(v).strip()
                for k, v in response.headers.items()
            }
            payload = response.read(
                PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_MAX_RESPONSE_BYTES + 1
            )
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            "fixed-origin post-create PR read failed"
        ) from exc
    if status != 200:
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            "post-create PR read returned a non-success status"
        )
    if len(payload) > PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_MAX_RESPONSE_BYTES:
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            "post-create PR response exceeded byte ceiling"
        )
    lowered_headers = {name.lower() for name in request.headers}
    if "authorization" in lowered_headers or "cookie" in lowered_headers:
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            "post-create PR read must remain credential free"
        )
    try:
        document = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            "post-create PR response is not UTF-8 JSON"
        ) from exc
    if not isinstance(document, Mapping):
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            "post-create PR response must be an object"
        )

    head = document.get("head")
    base = document.get("base")
    head_repo = None if not isinstance(head, Mapping) else head.get("repo")
    base_repo = None if not isinstance(base, Mapping) else base.get("repo")
    expected_api = transaction.pull_request_api_url
    expected_html = transaction.pull_request_html_url
    updated_at = document.get("updated_at")
    if (
        document.get("number") != number
        or document.get("url") != expected_api
        or document.get("html_url") != expected_html
        or document.get("state") != "open"
        or document.get("closed_at") is not None
        or document.get("merged_at") is not None
        or document.get("draft") is not True
        or document.get("title") != requirements.pr_title
        or document.get("body") != requirements.pr_body
        or document.get("maintainer_can_modify") is not False
        or not isinstance(head, Mapping)
        or head.get("ref") != transaction.head_branch
        or head.get("sha") != transaction.predicted_commit_sha
        or not isinstance(head_repo, Mapping)
        or head_repo.get("full_name") != transaction.repository
        or not isinstance(base, Mapping)
        or base.get("ref") != transaction.base_branch
        or not isinstance(base_repo, Mapping)
        or base_repo.get("full_name") != transaction.repository
    ):
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            "post-create PR no longer matches the exact authorized draft"
        )
    _utc(updated_at, name="pull request updated_at")
    etag = headers.get("etag", "")
    if len(etag) > 512 or "\r" in etag or "\n" in etag or "\x00" in etag:
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            "post-create PR ETag is invalid"
        )
    return MappingProxyType(
        {
            "request_url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
            "response_body_sha256": hashlib.sha256(payload).hexdigest(),
            "response_etag_sha256": hashlib.sha256(etag.encode("utf-8")).hexdigest(),
            "observed_updated_at_utc": updated_at,
            "pull_request_number": number,
            "api_url": expected_api,
            "html_url": expected_html,
        }
    )


def _validate_reader_evidence(
    value: Any,
    *,
    transaction: PilotExactTaskPrCreateTransaction,
) -> Mapping[str, Any]:
    expected = {
        "request_url_sha256",
        "response_body_sha256",
        "response_etag_sha256",
        "observed_updated_at_utc",
        "pull_request_number",
        "api_url",
        "html_url",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            "post-create PR evidence fields mismatch"
        )
    result = dict(value)
    for name in (
        "request_url_sha256",
        "response_body_sha256",
        "response_etag_sha256",
    ):
        _hex64(result.get(name), name=name)
    _utc(result.get("observed_updated_at_utc"), name="observed_updated_at_utc")
    if (
        result.get("pull_request_number") != transaction.pull_request_number
        or result.get("api_url") != transaction.pull_request_api_url
        or result.get("html_url") != transaction.pull_request_html_url
    ):
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            "post-create PR evidence target mismatch"
        )
    return MappingProxyType(result)


def _handoff_plan(
    *,
    transaction: PilotExactTaskPrCreateTransaction,
    requirements: Any,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "provider": "github",
        "operation": PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_OPERATION,
        "repository": transaction.repository,
        "pull_request_number": transaction.pull_request_number,
        "api_url": transaction.pull_request_api_url,
        "html_url": transaction.pull_request_html_url,
        "base_branch": transaction.base_branch,
        "head_branch": transaction.head_branch,
        "head_sha": transaction.predicted_commit_sha,
        "title": requirements.pr_title,
        "body_sha256": hashlib.sha256(requirements.pr_body.encode("utf-8")).hexdigest(),
        "expected_state": "open",
        "expected_draft": True,
        "expected_maintainer_can_modify": False,
        "expected_updated_at_utc": evidence["observed_updated_at_utc"],
    }


def _plan_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


_live_records: dict[
    int,
    tuple[
        int,
        str,
        weakref.ReferenceType[Any],
        weakref.ReferenceType[PilotExactTaskPrCreateTransaction],
    ],
] = {}


def _mark_pr_review_handoff_requirements_authenticated(
    requirements: Any,
    transaction: PilotExactTaskPrCreateTransaction,
) -> None:
    key = id(requirements)

    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)

    _live_records[key] = (
        os.getpid(),
        requirements.sha256,
        weakref.ref(requirements, cleanup),
        weakref.ref(transaction),
    )


def _get_live_pr_review_handoff_requirements_inputs(
    requirements: Any,
) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(requirements))
    if entry is None:
        return None
    pid, digest, requirements_ref, transaction_ref = entry
    transaction = transaction_ref()
    if (
        pid != os.getpid()
        or requirements_ref() is not requirements
        or transaction is None
        or transaction.transaction_authenticated is not True
        or transaction.sha256 != requirements.pr_create_transaction_sha256
        or requirements.sha256 != digest
    ):
        return None
    return MappingProxyType({"pr_create_transaction": transaction})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReviewHandoffRequirements:
    pr_create_transaction_sha256: str
    pr_credential_capability_sha256: str
    pr_mutation_reservation_sha256: str
    pr_mutation_requirements_sha256: str
    remote_write_transaction_sha256: str
    predicted_commit_sha: str
    pr_plan_sha256: str
    pr_mutation_nonce_sha256: str
    required_ready_for_review_authorizer_actor_id: str
    repository: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_html_url: str
    base_branch: str
    head_branch: str
    pr_title: str
    pr_body: str
    request_url_sha256: str
    response_body_sha256: str
    response_etag_sha256: str
    observed_updated_at_utc: str
    review_handoff_plan_sha256: str
    materialized_at_utc: str
    post_create_pr_reverified: bool = True
    credential_free_read: bool = True
    redirects_forbidden: bool = True
    response_bounded: bool = True
    pull_request_open_verified: bool = True
    draft_state_verified: bool = True
    exact_head_sha_verified: bool = True
    exact_base_verified: bool = True
    exact_metadata_verified: bool = True
    ready_for_review_handoff_required: bool = True
    separate_human_ready_for_review_authorization_required: bool = True
    one_shot_ready_for_review_nonce_required: bool = True
    fresh_pr_state_revalidation_before_ready_required: bool = True
    reviewer_mutation_separate_authority_required: bool = True
    label_mutation_separate_authority_required: bool = True
    merge_separate_authority_required: bool = True
    maintainer_can_modify: bool = False
    pr_mutation_authorized: bool = False
    pull_request_create_authorized: bool = False
    ready_for_review_authorization_consumed: bool = False
    ready_for_review_authorized: bool = False
    ready_for_review_performed: bool = False
    reviewer_mutation_authorized: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    requirements_scope: str = PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_REQUIREMENTS_SCOPE
    authority: str = PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_REQUIREMENTS_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_REQUIREMENTS_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_REQUIREMENTS_SCHEMA
            or self.authority != PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_REQUIREMENTS_AUTHORITY
            or self.requirements_scope
            != PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_REQUIREMENTS_SCOPE
        ):
            raise PilotExactTaskPrReviewHandoffRequirementsError(
                "review-handoff schema/authority/scope is unsupported"
            )
        for name in (
            "pr_create_transaction_sha256",
            "pr_credential_capability_sha256",
            "pr_mutation_reservation_sha256",
            "pr_mutation_requirements_sha256",
            "remote_write_transaction_sha256",
            "pr_plan_sha256",
            "pr_mutation_nonce_sha256",
            "request_url_sha256",
            "response_body_sha256",
            "response_etag_sha256",
            "review_handoff_plan_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _utc(self.observed_updated_at_utc, name="observed_updated_at_utc")
        materialized = _utc(self.materialized_at_utc, name="materialized_at_utc")
        observed = _utc(self.observed_updated_at_utc, name="observed_updated_at_utc")
        if materialized < observed:
            raise PilotExactTaskPrReviewHandoffRequirementsError(
                "review-handoff requirements predate observed PR state"
            )
        if (
            not isinstance(self.required_ready_for_review_authorizer_actor_id, str)
            or _ACTOR.fullmatch(self.required_ready_for_review_authorizer_actor_id) is None
        ):
            raise PilotExactTaskPrReviewHandoffRequirementsError(
                "required ready-for-review authorizer actor is invalid"
            )
        if (
            self.repository != "Ternedal/ModelRig"
            or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
            or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"https://api.github.com/repos/Ternedal/ModelRig/pulls/{self.pull_request_number}"
            or self.pull_request_html_url
            != f"https://github.com/Ternedal/ModelRig/pull/{self.pull_request_number}"
            or not isinstance(self.pr_title, str)
            or not self.pr_title
            or len(self.pr_title) > 256
            or not isinstance(self.pr_body, str)
            or not self.pr_body
            or len(self.pr_body.encode("utf-8")) > 64 * 1024
        ):
            raise PilotExactTaskPrReviewHandoffRequirementsError(
                "review-handoff target/metadata binding is invalid"
            )
        plan = {
            "provider": "github",
            "operation": PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_OPERATION,
            "repository": self.repository,
            "pull_request_number": self.pull_request_number,
            "api_url": self.pull_request_api_url,
            "html_url": self.pull_request_html_url,
            "base_branch": self.base_branch,
            "head_branch": self.head_branch,
            "head_sha": self.predicted_commit_sha,
            "title": self.pr_title,
            "body_sha256": hashlib.sha256(self.pr_body.encode("utf-8")).hexdigest(),
            "expected_state": "open",
            "expected_draft": True,
            "expected_maintainer_can_modify": False,
            "expected_updated_at_utc": self.observed_updated_at_utc,
        }
        if self.review_handoff_plan_sha256 != _plan_sha256(plan):
            raise PilotExactTaskPrReviewHandoffRequirementsError(
                "review-handoff plan digest mismatch"
            )
        required_true = (
            "post_create_pr_reverified",
            "credential_free_read",
            "redirects_forbidden",
            "response_bounded",
            "pull_request_open_verified",
            "draft_state_verified",
            "exact_head_sha_verified",
            "exact_base_verified",
            "exact_metadata_verified",
            "ready_for_review_handoff_required",
            "separate_human_ready_for_review_authorization_required",
            "one_shot_ready_for_review_nonce_required",
            "fresh_pr_state_revalidation_before_ready_required",
            "reviewer_mutation_separate_authority_required",
            "label_mutation_separate_authority_required",
            "merge_separate_authority_required",
        )
        forced_false = (
            "maintainer_can_modify",
            "pr_mutation_authorized",
            "pull_request_create_authorized",
            "ready_for_review_authorization_consumed",
            "ready_for_review_authorized",
            "ready_for_review_performed",
            "reviewer_mutation_authorized",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrReviewHandoffRequirementsError(
                "review-handoff evidence/requirements are incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReviewHandoffRequirementsError(
                "review-handoff requirements cannot grant mutation authority"
            )

    @property
    def requirements_authenticated(self) -> bool:
        return _get_live_pr_review_handoff_requirements_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrReviewHandoffRequirements":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReviewHandoffRequirementsError(
                "review-handoff requirements must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReviewHandoffRequirementsError(
                "review-handoff requirements fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _materialize_verified_pilot_exact_task_pr_review_handoff_requirements(
    *,
    pr_create_transaction: PilotExactTaskPrCreateTransaction,
    reader: Callable[..., Mapping[str, Any]],
    now_provider: Callable[[], str],
) -> PilotExactTaskPrReviewHandoffRequirements:
    transaction, _capability, requirements = _require_live_transaction(
        pr_create_transaction
    )
    evidence = _validate_reader_evidence(
        reader(
            pr_create_transaction=transaction,
            pr_mutation_requirements=requirements,
        ),
        transaction=transaction,
    )
    materialized_at = now_provider()
    _utc(materialized_at, name="materialized_at_utc")
    if _utc(materialized_at, name="materialized_at_utc") < _utc(
        evidence["observed_updated_at_utc"],
        name="observed_updated_at_utc",
    ):
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            "system time predates freshly observed PR state"
        )
    plan = _handoff_plan(
        transaction=transaction,
        requirements=requirements,
        evidence=evidence,
    )
    result = PilotExactTaskPrReviewHandoffRequirements(
        pr_create_transaction_sha256=transaction.sha256,
        pr_credential_capability_sha256=transaction.pr_credential_capability_sha256,
        pr_mutation_reservation_sha256=transaction.pr_mutation_reservation_sha256,
        pr_mutation_requirements_sha256=transaction.pr_mutation_requirements_sha256,
        remote_write_transaction_sha256=transaction.remote_write_transaction_sha256,
        predicted_commit_sha=transaction.predicted_commit_sha,
        pr_plan_sha256=transaction.pr_plan_sha256,
        pr_mutation_nonce_sha256=transaction.pr_mutation_nonce_sha256,
        required_ready_for_review_authorizer_actor_id=(
            requirements.prior_remote_publication_authorizer_actor_id
        ),
        repository=transaction.repository,
        pull_request_number=transaction.pull_request_number,
        pull_request_api_url=transaction.pull_request_api_url,
        pull_request_html_url=transaction.pull_request_html_url,
        base_branch=transaction.base_branch,
        head_branch=transaction.head_branch,
        pr_title=requirements.pr_title,
        pr_body=requirements.pr_body,
        request_url_sha256=evidence["request_url_sha256"],
        response_body_sha256=evidence["response_body_sha256"],
        response_etag_sha256=evidence["response_etag_sha256"],
        observed_updated_at_utc=evidence["observed_updated_at_utc"],
        review_handoff_plan_sha256=_plan_sha256(plan),
        materialized_at_utc=materialized_at,
    )
    _mark_pr_review_handoff_requirements_authenticated(result, transaction)
    if result.requirements_authenticated is not True:
        raise PilotExactTaskPrReviewHandoffRequirementsError(
            "review-handoff requirements lost live ADR-DC-058 provenance"
        )
    return result


def materialize_pilot_exact_task_pr_review_handoff_requirements(
    pr_create_transaction: PilotExactTaskPrCreateTransaction,
) -> PilotExactTaskPrReviewHandoffRequirements:
    """Freshly verify the exact draft PR and freeze inert review-handoff requirements."""
    return _materialize_verified_pilot_exact_task_pr_review_handoff_requirements(
        pr_create_transaction=pr_create_transaction,
        reader=_read_exact_draft_pr_state,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_REQUIREMENTS_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_REQUIREMENTS_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_REQUIREMENTS_SCOPE",
    "PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_OPERATION",
    "PilotExactTaskPrReviewHandoffRequirementsError",
    "PilotExactTaskPrReviewHandoffRequirements",
    "materialize_pilot_exact_task_pr_review_handoff_requirements",
]
