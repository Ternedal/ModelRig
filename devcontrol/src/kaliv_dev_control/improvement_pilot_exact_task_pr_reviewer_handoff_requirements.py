"""ADR-DC-066 read-only post-ready verification and reviewer handoff requirements.

Consumes one exact live authenticated ADR-DC-065 ready-for-review transaction,
performs one fresh credential-free fixed-origin GET of that exact pull request,
and freezes inert requirements for a later reviewer-selection/authorization flow.
No reviewer is selected or requested and no GitHub mutation authority is granted.
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

from . import improvement_pilot_exact_task_pr_ready_for_review_transaction as transaction_boundary
from .improvement_pilot_exact_task_pr_ready_for_review_transaction import (
    PILOT_EXACT_TASK_PR_READY_TRANSACTION_AUTHORITY,
    PilotExactTaskPrReadyTransaction,
)
from . import improvement_pilot_exact_task_pr_ready_for_review_node_identity as node_boundary

PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_REQUIREMENTS_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-reviewer-handoff-requirements/v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_REQUIREMENTS_AUTHORITY = (
    "verified-one-dc-l16-exact-ready-pr-reviewer-handoff-requirements-only"
)
PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_REQUIREMENTS_SCOPE = (
    "one-ready-pr-reviewer-handoff-only-v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_OPERATION = "request-pull-request-reviewers"
PILOT_EXACT_TASK_PR_REVIEWER_SELECTION_SOURCE = "host-pinned-reviewer-policy-only"
PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_API_VERSION = "2022-11-28"
PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_MAX_RESPONSE_BYTES = 256 * 1024
PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_TIMEOUT_SECONDS = 20

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_NODE_ID = re.compile(r"^[A-Za-z0-9_+/=-]{8,256}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")


class PilotExactTaskPrReviewerHandoffRequirementsError(ValueError):
    """The post-ready PR state or reviewer handoff is unsafe or drifted."""


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
        raise PilotExactTaskPrReviewerHandoffRequirementsError(
            "reviewer handoff requirements are not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrReviewerHandoffRequirementsError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrReviewerHandoffRequirementsError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReviewerHandoffRequirementsError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrReviewerHandoffRequirementsError(f"{name} is invalid") from exc


def _node_id(value: Any) -> str:
    if (
        not isinstance(value, str)
        or value.strip() != value
        or _NODE_ID.fullmatch(value) is None
        or "\x00" in value
    ):
        raise PilotExactTaskPrReviewerHandoffRequirementsError(
            "pull-request node id is invalid"
        )
    return value


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _require_live_transaction(
    value: Any,
) -> tuple[PilotExactTaskPrReadyTransaction, Any, Any, Any]:
    if type(value) is not PilotExactTaskPrReadyTransaction:
        raise PilotExactTaskPrReviewerHandoffRequirementsError(
            "exact ADR-DC-065 ready transaction is required"
        )
    try:
        replayed = PilotExactTaskPrReadyTransaction.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrReviewerHandoffRequirementsError(
            "ADR-DC-065 transaction replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrReviewerHandoffRequirementsError(
            "ADR-DC-065 transaction identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_PR_READY_TRANSACTION_AUTHORITY
        or value.transaction_authenticated is not True
        or value.host_transaction_start_committed is not True
        or value.ready_for_review_authorization_consumed is not True
        or value.ready_for_review_slot_consumed is not True
        or value.ready_for_review_performed is not True
        or value.post_ready_readback_verified is not True
        or value.draft_state_cleared_verified is not True
        or value.exact_head_sha_verified is not True
        or value.exact_base_verified is not True
        or value.exact_metadata_verified is not True
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
        raise PilotExactTaskPrReviewerHandoffRequirementsError(
            "reviewer handoff requires one completed inert ADR-DC-065 transaction"
        )

    tx_inputs = transaction_boundary._get_live_pr_ready_transaction_inputs(value)
    identity = None if tx_inputs is None else tx_inputs.get("ready_node_identity")
    if (
        identity is None
        or getattr(identity, "identity_authenticated", None) is not True
        or identity.sha256 != value.node_identity_sha256
        or identity.pull_request_node_id_sha256 != value.pull_request_node_id_sha256
    ):
        raise PilotExactTaskPrReviewerHandoffRequirementsError(
            "ADR-DC-065 lost exact live ADR-DC-064 node identity"
        )
    identity_inputs = node_boundary._get_live_pr_ready_node_identity_inputs(identity)
    capability = None if identity_inputs is None else identity_inputs.get(
        "ready_credential_capability"
    )
    if capability is None or getattr(capability, "capability_authenticated", None) is not True:
        raise PilotExactTaskPrReviewerHandoffRequirementsError(
            "ADR-DC-064 lost live ADR-DC-063 capability provenance"
        )
    try:
        _capability, _observation, _reservation, requirements = (
            node_boundary._require_live_capability(capability)
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewerHandoffRequirementsError(
            "post-ready reviewer handoff lost live ADR-DC-059 requirements"
        ) from exc
    if (
        requirements.sha256 != value.review_handoff_requirements_sha256
        or requirements.pr_create_transaction_sha256 != value.pr_create_transaction_sha256
        or requirements.predicted_commit_sha != value.predicted_commit_sha
        or requirements.review_handoff_plan_sha256 != value.review_handoff_plan_sha256
        or requirements.pull_request_number != value.pull_request_number
        or requirements.pull_request_api_url != value.pull_request_api_url
        or requirements.pull_request_html_url != value.pull_request_html_url
        or requirements.base_branch != value.base_branch
        or requirements.head_branch != value.head_branch
    ):
        raise PilotExactTaskPrReviewerHandoffRequirementsError(
            "ADR-DC-065 no longer matches exact reviewer-handoff provenance"
        )
    return value, identity, capability, requirements


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _read_exact_ready_pr_for_reviewer_handoff(
    *,
    ready_transaction: PilotExactTaskPrReadyTransaction,
    review_handoff_requirements: Any,
) -> Mapping[str, Any]:
    transaction = ready_transaction
    requirements = review_handoff_requirements
    url = transaction.pull_request_api_url
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_API_VERSION,
            "User-Agent": "ModelRig-DevControl-ADR-DC-066",
        },
    )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(
            request,
            timeout=PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_TIMEOUT_SECONDS,
        ) as response:
            status = getattr(response, "status", None)
            headers = {str(k).lower(): str(v).strip() for k, v in response.headers.items()}
            payload = response.read(
                PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_MAX_RESPONSE_BYTES + 1
            )
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PilotExactTaskPrReviewerHandoffRequirementsError(
            "fixed-origin post-ready PR read failed"
        ) from exc
    if status != 200 or len(payload) > PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_MAX_RESPONSE_BYTES:
        raise PilotExactTaskPrReviewerHandoffRequirementsError(
            "post-ready PR read status/size is unsafe"
        )
    lowered_headers = {name.lower() for name in request.headers}
    if "authorization" in lowered_headers or "cookie" in lowered_headers:
        raise PilotExactTaskPrReviewerHandoffRequirementsError(
            "post-ready reviewer read must remain credential free"
        )
    try:
        document = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrReviewerHandoffRequirementsError(
            "post-ready PR response is not UTF-8 JSON"
        ) from exc
    if not isinstance(document, Mapping):
        raise PilotExactTaskPrReviewerHandoffRequirementsError(
            "post-ready PR response must be an object"
        )
    head = document.get("head")
    base = document.get("base")
    head_repo = None if not isinstance(head, Mapping) else head.get("repo")
    base_repo = None if not isinstance(base, Mapping) else base.get("repo")
    requested_reviewers = document.get("requested_reviewers")
    requested_teams = document.get("requested_teams")
    node = document.get("node_id")
    if (
        document.get("number") != transaction.pull_request_number
        or document.get("node_id") != transaction.pull_request_node_id
        or document.get("url") != transaction.pull_request_api_url
        or document.get("html_url") != transaction.pull_request_html_url
        or document.get("state") != "open"
        or document.get("closed_at") is not None
        or document.get("merged_at") is not None
        or document.get("draft") is not False
        or document.get("title") != requirements.pr_title
        or document.get("body") != requirements.pr_body
        or document.get("maintainer_can_modify") is not False
        or document.get("updated_at") != transaction.ready_updated_at_utc
        or not isinstance(requested_reviewers, list)
        or len(requested_reviewers) != 0
        or not isinstance(requested_teams, list)
        or len(requested_teams) != 0
        or not isinstance(head, Mapping)
        or head.get("ref") != transaction.head_branch
        or head.get("sha") != transaction.predicted_commit_sha
        or not isinstance(head_repo, Mapping)
        or head_repo.get("full_name") != transaction.repository
        or not isinstance(base, Mapping)
        or base.get("ref") != transaction.base_branch
        or not isinstance(base_repo, Mapping)
        or base_repo.get("full_name") != transaction.repository
        or _node_id(node) != transaction.pull_request_node_id
    ):
        raise PilotExactTaskPrReviewerHandoffRequirementsError(
            "post-ready PR no longer matches exact reviewer-handoff preconditions"
        )
    etag = headers.get("etag", "")
    if len(etag) > 512 or "\r" in etag or "\n" in etag or "\x00" in etag:
        raise PilotExactTaskPrReviewerHandoffRequirementsError(
            "post-ready PR ETag is invalid"
        )
    return MappingProxyType(
        {
            "request_url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
            "response_body_sha256": hashlib.sha256(payload).hexdigest(),
            "response_etag_sha256": hashlib.sha256(etag.encode("utf-8")).hexdigest(),
            "observed_updated_at_utc": transaction.ready_updated_at_utc,
            "requested_reviewer_count": 0,
            "requested_team_count": 0,
        }
    )


def _validate_reader_evidence(value: Any, *, transaction: PilotExactTaskPrReadyTransaction) -> Mapping[str, Any]:
    expected = {
        "request_url_sha256",
        "response_body_sha256",
        "response_etag_sha256",
        "observed_updated_at_utc",
        "requested_reviewer_count",
        "requested_team_count",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrReviewerHandoffRequirementsError(
            "reviewer-handoff read evidence fields mismatch"
        )
    result = dict(value)
    for name in ("request_url_sha256", "response_body_sha256", "response_etag_sha256"):
        _hex64(result.get(name), name=name)
    _utc(result.get("observed_updated_at_utc"), name="observed_updated_at_utc")
    if (
        result["request_url_sha256"]
        != hashlib.sha256(transaction.pull_request_api_url.encode("utf-8")).hexdigest()
        or result["observed_updated_at_utc"] != transaction.ready_updated_at_utc
        or result["requested_reviewer_count"] != 0
        or result["requested_team_count"] != 0
    ):
        raise PilotExactTaskPrReviewerHandoffRequirementsError(
            "reviewer-handoff evidence does not match exact ready state"
        )
    return MappingProxyType(result)


def _handoff_plan(*, transaction: PilotExactTaskPrReadyTransaction, requirements: Any) -> dict[str, Any]:
    return {
        "provider": "github",
        "operation": PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_OPERATION,
        "repository": transaction.repository,
        "pull_request_number": transaction.pull_request_number,
        "pull_request_node_id_sha256": transaction.pull_request_node_id_sha256,
        "base_branch": transaction.base_branch,
        "head_branch": transaction.head_branch,
        "head_sha": transaction.predicted_commit_sha,
        "title": requirements.pr_title,
        "body_sha256": hashlib.sha256(requirements.pr_body.encode("utf-8")).hexdigest(),
        "expected_state": "open",
        "expected_draft": False,
        "expected_requested_reviewer_count": 0,
        "expected_requested_team_count": 0,
        "expected_updated_at_utc": transaction.ready_updated_at_utc,
        "reviewer_selection_source": PILOT_EXACT_TASK_PR_REVIEWER_SELECTION_SOURCE,
        "human_reviewer_request_authorization_required": True,
        "one_shot_reviewer_request_nonce_required": True,
        "fresh_pr_state_revalidation_before_reviewer_request_required": True,
    }


def _plan_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


_live_records: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[PilotExactTaskPrReadyTransaction]]] = {}


def _mark_pr_reviewer_handoff_requirements_authenticated(
    requirements: Any,
    transaction: PilotExactTaskPrReadyTransaction,
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


def _get_live_pr_reviewer_handoff_requirements_inputs(requirements: Any) -> Mapping[str, Any] | None:
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
        or transaction.sha256 != requirements.ready_transaction_sha256
        or requirements.sha256 != digest
    ):
        return None
    return MappingProxyType({"ready_transaction": transaction})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReviewerHandoffRequirements:
    ready_transaction_sha256: str
    node_identity_sha256: str
    ready_credential_capability_sha256: str
    ready_state_observation_sha256: str
    ready_for_review_reservation_sha256: str
    review_handoff_requirements_sha256: str
    pr_create_transaction_sha256: str
    predicted_commit_sha: str
    review_handoff_plan_sha256: str
    ready_for_review_nonce_sha256: str
    required_reviewer_authorizer_actor_id: str
    repository: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_html_url: str
    pull_request_node_id: str
    pull_request_node_id_sha256: str
    base_branch: str
    head_branch: str
    pr_title: str
    pr_body: str
    ready_updated_at_utc: str
    request_url_sha256: str
    response_body_sha256: str
    response_etag_sha256: str
    observed_updated_at_utc: str
    reviewer_handoff_plan_sha256: str
    materialized_at_utc: str
    post_ready_pr_reverified: bool = True
    credential_free_read: bool = True
    redirects_forbidden: bool = True
    response_bounded: bool = True
    pull_request_open_verified: bool = True
    ready_state_verified: bool = True
    exact_head_sha_verified: bool = True
    exact_base_verified: bool = True
    exact_metadata_verified: bool = True
    no_requested_reviewers_verified: bool = True
    reviewer_target_host_policy_required: bool = True
    separate_human_reviewer_authorization_required: bool = True
    one_shot_reviewer_request_nonce_required: bool = True
    fresh_pr_state_revalidation_before_reviewer_request_required: bool = True
    label_mutation_separate_authority_required: bool = True
    merge_separate_authority_required: bool = True
    pr_mutation_authorized: bool = False
    pull_request_create_authorized: bool = False
    ready_for_review_authorized: bool = False
    reviewer_mutation_authorized: bool = False
    reviewer_request_performed: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    requirements_scope: str = PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_REQUIREMENTS_SCOPE
    authority: str = PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_REQUIREMENTS_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_REQUIREMENTS_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_REQUIREMENTS_SCHEMA
            or self.authority != PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_REQUIREMENTS_AUTHORITY
            or self.requirements_scope != PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_REQUIREMENTS_SCOPE
        ):
            raise PilotExactTaskPrReviewerHandoffRequirementsError(
                "reviewer handoff schema/authority/scope is unsupported"
            )
        for name in (
            "ready_transaction_sha256",
            "node_identity_sha256",
            "ready_credential_capability_sha256",
            "ready_state_observation_sha256",
            "ready_for_review_reservation_sha256",
            "review_handoff_requirements_sha256",
            "pr_create_transaction_sha256",
            "review_handoff_plan_sha256",
            "ready_for_review_nonce_sha256",
            "pull_request_node_id_sha256",
            "request_url_sha256",
            "response_body_sha256",
            "response_etag_sha256",
            "reviewer_handoff_plan_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        node = _node_id(self.pull_request_node_id)
        if self.pull_request_node_id_sha256 != hashlib.sha256(node.encode("utf-8")).hexdigest():
            raise PilotExactTaskPrReviewerHandoffRequirementsError(
                "reviewer handoff node-id digest mismatch"
            )
        ready = _utc(self.ready_updated_at_utc, name="ready_updated_at_utc")
        observed = _utc(self.observed_updated_at_utc, name="observed_updated_at_utc")
        materialized = _utc(self.materialized_at_utc, name="materialized_at_utc")
        if ready != observed or materialized < observed:
            raise PilotExactTaskPrReviewerHandoffRequirementsError(
                "reviewer handoff timestamps are inconsistent"
            )
        if (
            not isinstance(self.required_reviewer_authorizer_actor_id, str)
            or _ACTOR.fullmatch(self.required_reviewer_authorizer_actor_id) is None
            or self.repository != "Ternedal/ModelRig"
            or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
            or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url != f"https://api.github.com/repos/Ternedal/ModelRig/pulls/{self.pull_request_number}"
            or self.pull_request_html_url != f"https://github.com/Ternedal/ModelRig/pull/{self.pull_request_number}"
            or not isinstance(self.pr_title, str)
            or not self.pr_title
            or len(self.pr_title) > 256
            or not isinstance(self.pr_body, str)
            or not self.pr_body
            or len(self.pr_body.encode("utf-8")) > 64 * 1024
        ):
            raise PilotExactTaskPrReviewerHandoffRequirementsError(
                "reviewer handoff target/metadata binding is invalid"
            )
        plan = _handoff_plan(transaction=_ReviewerPlanView(self), requirements=self)
        if self.reviewer_handoff_plan_sha256 != _plan_sha256(plan):
            raise PilotExactTaskPrReviewerHandoffRequirementsError(
                "reviewer handoff plan digest mismatch"
            )
        required_true = (
            "post_ready_pr_reverified",
            "credential_free_read",
            "redirects_forbidden",
            "response_bounded",
            "pull_request_open_verified",
            "ready_state_verified",
            "exact_head_sha_verified",
            "exact_base_verified",
            "exact_metadata_verified",
            "no_requested_reviewers_verified",
            "reviewer_target_host_policy_required",
            "separate_human_reviewer_authorization_required",
            "one_shot_reviewer_request_nonce_required",
            "fresh_pr_state_revalidation_before_reviewer_request_required",
            "label_mutation_separate_authority_required",
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
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrReviewerHandoffRequirementsError(
                "reviewer handoff safety requirements are incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReviewerHandoffRequirementsError(
                "reviewer handoff requirements cannot grant mutation authority"
            )

    @property
    def requirements_authenticated(self) -> bool:
        return _get_live_pr_reviewer_handoff_requirements_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrReviewerHandoffRequirements":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReviewerHandoffRequirementsError(
                "reviewer handoff requirements must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReviewerHandoffRequirementsError(
                "reviewer handoff requirements fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _ReviewerPlanView:
    def __init__(self, value: PilotExactTaskPrReviewerHandoffRequirements) -> None:
        self.repository = value.repository
        self.pull_request_number = value.pull_request_number
        self.pull_request_node_id_sha256 = value.pull_request_node_id_sha256
        self.base_branch = value.base_branch
        self.head_branch = value.head_branch
        self.predicted_commit_sha = value.predicted_commit_sha
        self.ready_updated_at_utc = value.ready_updated_at_utc


def _materialize_verified_pilot_exact_task_pr_reviewer_handoff_requirements(
    *,
    ready_transaction: PilotExactTaskPrReadyTransaction,
    reader: Callable[..., Mapping[str, Any]],
    now_provider: Callable[[], str],
) -> PilotExactTaskPrReviewerHandoffRequirements:
    transaction, _identity, _capability, requirements = _require_live_transaction(
        ready_transaction
    )
    evidence = _validate_reader_evidence(
        reader(
            ready_transaction=transaction,
            review_handoff_requirements=requirements,
        ),
        transaction=transaction,
    )
    materialized_at = now_provider()
    _utc(materialized_at, name="materialized_at_utc")
    plan = _handoff_plan(transaction=transaction, requirements=requirements)
    result = PilotExactTaskPrReviewerHandoffRequirements(
        ready_transaction_sha256=transaction.sha256,
        node_identity_sha256=transaction.node_identity_sha256,
        ready_credential_capability_sha256=transaction.ready_credential_capability_sha256,
        ready_state_observation_sha256=transaction.ready_state_observation_sha256,
        ready_for_review_reservation_sha256=transaction.ready_for_review_reservation_sha256,
        review_handoff_requirements_sha256=transaction.review_handoff_requirements_sha256,
        pr_create_transaction_sha256=transaction.pr_create_transaction_sha256,
        predicted_commit_sha=transaction.predicted_commit_sha,
        review_handoff_plan_sha256=transaction.review_handoff_plan_sha256,
        ready_for_review_nonce_sha256=transaction.ready_for_review_nonce_sha256,
        required_reviewer_authorizer_actor_id=requirements.required_ready_for_review_authorizer_actor_id,
        repository=transaction.repository,
        pull_request_number=transaction.pull_request_number,
        pull_request_api_url=transaction.pull_request_api_url,
        pull_request_html_url=transaction.pull_request_html_url,
        pull_request_node_id=transaction.pull_request_node_id,
        pull_request_node_id_sha256=transaction.pull_request_node_id_sha256,
        base_branch=transaction.base_branch,
        head_branch=transaction.head_branch,
        pr_title=requirements.pr_title,
        pr_body=requirements.pr_body,
        ready_updated_at_utc=transaction.ready_updated_at_utc,
        request_url_sha256=evidence["request_url_sha256"],
        response_body_sha256=evidence["response_body_sha256"],
        response_etag_sha256=evidence["response_etag_sha256"],
        observed_updated_at_utc=evidence["observed_updated_at_utc"],
        reviewer_handoff_plan_sha256=_plan_sha256(plan),
        materialized_at_utc=materialized_at,
    )
    _mark_pr_reviewer_handoff_requirements_authenticated(result, transaction)
    if result.requirements_authenticated is not True:
        raise PilotExactTaskPrReviewerHandoffRequirementsError(
            "reviewer handoff requirements lost live ADR-DC-065 provenance"
        )
    return result


def materialize_pilot_exact_task_pr_reviewer_handoff_requirements(
    ready_transaction: PilotExactTaskPrReadyTransaction,
) -> PilotExactTaskPrReviewerHandoffRequirements:
    """Freshly verify the ready PR and freeze inert reviewer-handoff requirements."""
    return _materialize_verified_pilot_exact_task_pr_reviewer_handoff_requirements(
        ready_transaction=ready_transaction,
        reader=_read_exact_ready_pr_for_reviewer_handoff,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_REQUIREMENTS_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_REQUIREMENTS_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_REQUIREMENTS_SCOPE",
    "PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_OPERATION",
    "PILOT_EXACT_TASK_PR_REVIEWER_SELECTION_SOURCE",
    "PilotExactTaskPrReviewerHandoffRequirementsError",
    "PilotExactTaskPrReviewerHandoffRequirements",
    "materialize_pilot_exact_task_pr_reviewer_handoff_requirements",
]
