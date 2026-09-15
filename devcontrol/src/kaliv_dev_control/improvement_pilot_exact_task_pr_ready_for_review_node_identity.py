"""ADR-DC-064 read-only GitHub pull-request node identity attestation.

Consumes one exact live ADR-DC-063 ready credential capability, performs one
credential-free fixed-origin REST GET of the exact still-draft pull request and
binds GitHub's opaque GraphQL node id to the already authorized PR state.
No GraphQL request or GitHub mutation occurs here.
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

from . import improvement_pilot_exact_task_pr_ready_for_review_credential_capability as capability_boundary
from .improvement_pilot_exact_task_pr_ready_for_review_credential_capability import (
    PILOT_EXACT_TASK_PR_READY_CREDENTIAL_CAPABILITY_AUTHORITY,
    PILOT_EXACT_TASK_PR_READY_CREDENTIAL_OPERATION,
    PILOT_EXACT_TASK_PR_READY_CREDENTIAL_PROTOCOL,
    PilotExactTaskPrReadyCredentialCapability,
)
from . import improvement_pilot_exact_task_pr_ready_for_review_state_observation as state_boundary

PILOT_EXACT_TASK_PR_READY_NODE_IDENTITY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-ready-for-review-node-identity/v1"
)
PILOT_EXACT_TASK_PR_READY_NODE_IDENTITY_AUTHORITY = (
    "attested-one-dc-l16-exact-pr-graphql-node-identity-only"
)
PILOT_EXACT_TASK_PR_READY_NODE_IDENTITY_MAX_CAPABILITY_AGE_SECONDS = 60
PILOT_EXACT_TASK_PR_READY_NODE_IDENTITY_API_VERSION = "2022-11-28"
PILOT_EXACT_TASK_PR_READY_NODE_IDENTITY_MAX_RESPONSE_BYTES = 256 * 1024
PILOT_EXACT_TASK_PR_READY_NODE_IDENTITY_TIMEOUT_SECONDS = 20

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_NODE_ID = re.compile(r"^[A-Za-z0-9_+/=-]{8,256}$")


class PilotExactTaskPrReadyNodeIdentityError(ValueError):
    """The exact GraphQL pull-request node identity is unsafe or drifted."""


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
        raise PilotExactTaskPrReadyNodeIdentityError(
            "ready node identity is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrReadyNodeIdentityError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrReadyNodeIdentityError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReadyNodeIdentityError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrReadyNodeIdentityError(f"{name} is invalid") from exc


def _node_id(value: Any) -> str:
    if (
        not isinstance(value, str)
        or value.strip() != value
        or _NODE_ID.fullmatch(value) is None
        or "\x00" in value
    ):
        raise PilotExactTaskPrReadyNodeIdentityError(
            "GitHub pull-request node id is invalid"
        )
    return value


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _require_live_capability(
    value: Any,
) -> tuple[PilotExactTaskPrReadyCredentialCapability, Any, Any, Any]:
    if type(value) is not PilotExactTaskPrReadyCredentialCapability:
        raise PilotExactTaskPrReadyNodeIdentityError(
            "exact ADR-DC-063 ready credential capability is required"
        )
    try:
        replayed = PilotExactTaskPrReadyCredentialCapability.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPrReadyNodeIdentityError(
            "ADR-DC-063 capability replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrReadyNodeIdentityError(
            "ADR-DC-063 capability identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_PR_READY_CREDENTIAL_CAPABILITY_AUTHORITY
        or value.capability_authenticated is not True
        or value.ready_for_review_authorization_consumed is not True
        or value.ready_for_review_slot_reserved is not True
        or value.fresh_exact_pr_state_observed is not True
        or value.signed_updated_at_still_current is not True
        or value.credential_broker_host_pinned is not True
        or value.credential_broker_binary_verified is not True
        or value.credential_secret_not_loaded is not True
        or value.credential_broker_owns_https is not True
        or value.credential_operation != PILOT_EXACT_TASK_PR_READY_CREDENTIAL_OPERATION
        or value.credential_protocol != PILOT_EXACT_TASK_PR_READY_CREDENTIAL_PROTOCOL
        or value.one_shot_ready_for_review_transaction_required is not True
        or value.fresh_pr_state_revalidation_before_ready_required is not True
        or value.post_ready_readback_verification_required is not True
        or value.reviewer_mutation_separate_authority_required is not True
        or value.label_mutation_separate_authority_required is not True
        or value.merge_separate_authority_required is not True
        or value.credential_material_in_artifact is not False
        or value.credential_material_in_process_arguments is not False
        or value.credential_material_in_environment is not False
        or value.pr_mutation_authorized is not False
        or value.pull_request_create_authorized is not False
        or value.ready_for_review_authorized is not False
        or value.ready_for_review_performed is not False
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
        raise PilotExactTaskPrReadyNodeIdentityError(
            "node identity requires one live inert ADR-DC-063 capability"
        )
    cap_inputs = capability_boundary._get_live_pr_ready_credential_capability_inputs(
        value
    )
    observation = None if cap_inputs is None else cap_inputs.get(
        "ready_state_observation"
    )
    if (
        observation is None
        or getattr(observation, "observation_authenticated", None) is not True
        or observation.sha256 != value.ready_state_observation_sha256
    ):
        raise PilotExactTaskPrReadyNodeIdentityError(
            "ADR-DC-063 lost live ADR-DC-062 observation provenance"
        )
    state_inputs = state_boundary._get_live_pr_ready_state_observation_inputs(
        observation
    )
    reservation = None if state_inputs is None else state_inputs.get(
        "ready_for_review_reservation"
    )
    requirements = None if state_inputs is None else state_inputs.get(
        "review_handoff_requirements"
    )
    if (
        reservation is None
        or requirements is None
        or getattr(reservation, "reservation_authenticated", None) is not True
        or getattr(requirements, "requirements_authenticated", None) is not True
        or reservation.sha256 != value.ready_for_review_reservation_sha256
        or requirements.sha256 != value.review_handoff_requirements_sha256
        or requirements.pr_create_transaction_sha256 != value.pr_create_transaction_sha256
        or requirements.predicted_commit_sha != value.predicted_commit_sha
        or requirements.review_handoff_plan_sha256 != value.review_handoff_plan_sha256
        or requirements.pull_request_number != value.pull_request_number
        or requirements.pull_request_api_url != value.pull_request_api_url
        or requirements.pull_request_html_url != value.pull_request_html_url
        or requirements.base_branch != value.base_branch
        or requirements.head_branch != value.head_branch
        or requirements.observed_updated_at_utc != value.fresh_observed_updated_at_utc
    ):
        raise PilotExactTaskPrReadyNodeIdentityError(
            "ADR-DC-063 lost exact live reservation/handoff provenance"
        )
    return value, observation, reservation, requirements


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _read_exact_pr_node_identity(
    *,
    ready_credential_capability: PilotExactTaskPrReadyCredentialCapability,
    review_handoff_requirements: Any,
) -> Mapping[str, Any]:
    capability = ready_credential_capability
    requirements = review_handoff_requirements
    url = capability.pull_request_api_url
    expected_url = (
        f"https://api.github.com/repos/Ternedal/ModelRig/pulls/"
        f"{capability.pull_request_number}"
    )
    if url != expected_url:
        raise PilotExactTaskPrReadyNodeIdentityError(
            "ready node identity REST target is not canonical"
        )
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": PILOT_EXACT_TASK_PR_READY_NODE_IDENTITY_API_VERSION,
            "User-Agent": "ModelRig-DevControl-ADR-DC-064",
        },
    )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(
            request,
            timeout=PILOT_EXACT_TASK_PR_READY_NODE_IDENTITY_TIMEOUT_SECONDS,
        ) as response:
            status = getattr(response, "status", None)
            headers = {
                str(k).lower(): str(v).strip()
                for k, v in response.headers.items()
            }
            payload = response.read(
                PILOT_EXACT_TASK_PR_READY_NODE_IDENTITY_MAX_RESPONSE_BYTES + 1
            )
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PilotExactTaskPrReadyNodeIdentityError(
            "fixed-origin PR node identity read failed"
        ) from exc
    if status != 200:
        raise PilotExactTaskPrReadyNodeIdentityError(
            "PR node identity read returned a non-success status"
        )
    if len(payload) > PILOT_EXACT_TASK_PR_READY_NODE_IDENTITY_MAX_RESPONSE_BYTES:
        raise PilotExactTaskPrReadyNodeIdentityError(
            "PR node identity response exceeded byte ceiling"
        )
    lowered_headers = {name.lower() for name in request.headers}
    if "authorization" in lowered_headers or "cookie" in lowered_headers:
        raise PilotExactTaskPrReadyNodeIdentityError(
            "PR node identity read must remain credential free"
        )
    try:
        document = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrReadyNodeIdentityError(
            "PR node identity response is not UTF-8 JSON"
        ) from exc
    if not isinstance(document, Mapping):
        raise PilotExactTaskPrReadyNodeIdentityError(
            "PR node identity response must be an object"
        )
    head = document.get("head")
    base = document.get("base")
    head_repo = None if not isinstance(head, Mapping) else head.get("repo")
    base_repo = None if not isinstance(base, Mapping) else base.get("repo")
    node_id = _node_id(document.get("node_id"))
    if (
        document.get("number") != capability.pull_request_number
        or document.get("url") != capability.pull_request_api_url
        or document.get("html_url") != capability.pull_request_html_url
        or document.get("state") != "open"
        or document.get("closed_at") is not None
        or document.get("merged_at") is not None
        or document.get("draft") is not True
        or document.get("title") != requirements.pr_title
        or document.get("body") != requirements.pr_body
        or document.get("maintainer_can_modify") is not False
        or document.get("updated_at") != capability.fresh_observed_updated_at_utc
        or not isinstance(head, Mapping)
        or head.get("ref") != capability.head_branch
        or head.get("sha") != capability.predicted_commit_sha
        or not isinstance(head_repo, Mapping)
        or head_repo.get("full_name") != capability.repository
        or not isinstance(base, Mapping)
        or base.get("ref") != capability.base_branch
        or not isinstance(base_repo, Mapping)
        or base_repo.get("full_name") != capability.repository
    ):
        raise PilotExactTaskPrReadyNodeIdentityError(
            "PR state drifted while resolving GraphQL node identity"
        )
    etag = headers.get("etag", "")
    if len(etag) > 512 or "\r" in etag or "\n" in etag or "\x00" in etag:
        raise PilotExactTaskPrReadyNodeIdentityError("PR node identity ETag is invalid")
    return MappingProxyType(
        {
            "request_url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
            "response_body_sha256": hashlib.sha256(payload).hexdigest(),
            "response_etag_sha256": hashlib.sha256(etag.encode("utf-8")).hexdigest(),
            "pull_request_node_id": node_id,
            "pull_request_node_id_sha256": hashlib.sha256(node_id.encode("utf-8")).hexdigest(),
            "observed_updated_at_utc": capability.fresh_observed_updated_at_utc,
        }
    )


def _validate_reader_evidence(value: Any, *, capability: PilotExactTaskPrReadyCredentialCapability) -> Mapping[str, Any]:
    expected = {
        "request_url_sha256",
        "response_body_sha256",
        "response_etag_sha256",
        "pull_request_node_id",
        "pull_request_node_id_sha256",
        "observed_updated_at_utc",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrReadyNodeIdentityError(
            "PR node identity evidence fields mismatch"
        )
    result = dict(value)
    for name in (
        "request_url_sha256",
        "response_body_sha256",
        "response_etag_sha256",
        "pull_request_node_id_sha256",
    ):
        _hex64(result.get(name), name=name)
    node = _node_id(result.get("pull_request_node_id"))
    if (
        result["request_url_sha256"]
        != hashlib.sha256(capability.pull_request_api_url.encode("utf-8")).hexdigest()
        or result["pull_request_node_id_sha256"]
        != hashlib.sha256(node.encode("utf-8")).hexdigest()
        or result.get("observed_updated_at_utc")
        != capability.fresh_observed_updated_at_utc
    ):
        raise PilotExactTaskPrReadyNodeIdentityError(
            "PR node identity evidence does not match exact capability state"
        )
    return MappingProxyType(result)


_live_records: dict[
    int,
    tuple[
        int,
        str,
        weakref.ReferenceType[Any],
        weakref.ReferenceType[PilotExactTaskPrReadyCredentialCapability],
    ],
] = {}


def _mark_pr_ready_node_identity_authenticated(
    identity: Any,
    capability: PilotExactTaskPrReadyCredentialCapability,
) -> None:
    key = id(identity)

    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)

    _live_records[key] = (
        os.getpid(),
        identity.sha256,
        weakref.ref(identity, cleanup),
        weakref.ref(capability),
    )


def _get_live_pr_ready_node_identity_inputs(identity: Any) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(identity))
    if entry is None:
        return None
    pid, digest, identity_ref, capability_ref = entry
    capability = capability_ref()
    if (
        pid != os.getpid()
        or identity_ref() is not identity
        or capability is None
        or capability.capability_authenticated is not True
        or capability.sha256 != identity.ready_credential_capability_sha256
        or identity.sha256 != digest
    ):
        return None
    return MappingProxyType({"ready_credential_capability": capability})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReadyNodeIdentity:
    ready_credential_capability_sha256: str
    ready_state_observation_sha256: str
    ready_for_review_reservation_sha256: str
    review_handoff_requirements_sha256: str
    pr_create_transaction_sha256: str
    predicted_commit_sha: str
    review_handoff_plan_sha256: str
    ready_for_review_nonce_sha256: str
    repository: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_html_url: str
    pull_request_node_id: str
    pull_request_node_id_sha256: str
    base_branch: str
    head_branch: str
    signed_observed_updated_at_utc: str
    fresh_observed_updated_at_utc: str
    request_url_sha256: str
    response_body_sha256: str
    response_etag_sha256: str
    observed_updated_at_utc: str
    observed_at_utc: str
    credential_free_rest_read: bool = True
    fixed_origin_rest_read: bool = True
    redirects_forbidden: bool = True
    response_bounded: bool = True
    exact_pr_state_reverified: bool = True
    graphql_pull_request_node_identity_verified: bool = True
    graphql_ready_for_review_mutation_required: bool = True
    ready_for_review_authorization_consumed: bool = True
    ready_for_review_slot_reserved: bool = True
    ready_for_review_authorized: bool = False
    ready_for_review_performed: bool = False
    reviewer_mutation_authorized: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_READY_NODE_IDENTITY_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PR_READY_NODE_IDENTITY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PR_READY_NODE_IDENTITY_SCHEMA or self.authority != PILOT_EXACT_TASK_PR_READY_NODE_IDENTITY_AUTHORITY:
            raise PilotExactTaskPrReadyNodeIdentityError(
                "ready node identity schema/authority is unsupported"
            )
        for name in (
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
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        node = _node_id(self.pull_request_node_id)
        if self.pull_request_node_id_sha256 != hashlib.sha256(node.encode("utf-8")).hexdigest():
            raise PilotExactTaskPrReadyNodeIdentityError("GraphQL node id digest mismatch")
        signed = _utc(self.signed_observed_updated_at_utc, name="signed_observed_updated_at_utc")
        fresh = _utc(self.fresh_observed_updated_at_utc, name="fresh_observed_updated_at_utc")
        observed_state = _utc(self.observed_updated_at_utc, name="observed_updated_at_utc")
        observed = _utc(self.observed_at_utc, name="observed_at_utc")
        if signed != fresh or fresh != observed_state or observed < observed_state:
            raise PilotExactTaskPrReadyNodeIdentityError("node identity timestamps are inconsistent")
        if (
            self.repository != "Ternedal/ModelRig"
            or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
            or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url != f"https://api.github.com/repos/Ternedal/ModelRig/pulls/{self.pull_request_number}"
            or self.pull_request_html_url != f"https://github.com/Ternedal/ModelRig/pull/{self.pull_request_number}"
            or self.request_url_sha256 != hashlib.sha256(self.pull_request_api_url.encode("utf-8")).hexdigest()
        ):
            raise PilotExactTaskPrReadyNodeIdentityError("ready node identity target binding is invalid")
        required_true = (
            "credential_free_rest_read",
            "fixed_origin_rest_read",
            "redirects_forbidden",
            "response_bounded",
            "exact_pr_state_reverified",
            "graphql_pull_request_node_identity_verified",
            "graphql_ready_for_review_mutation_required",
            "ready_for_review_authorization_consumed",
            "ready_for_review_slot_reserved",
        )
        forced_false = (
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
            raise PilotExactTaskPrReadyNodeIdentityError("ready node identity evidence is incomplete")
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReadyNodeIdentityError("ready node identity cannot grant mutation authority")

    @property
    def identity_authenticated(self) -> bool:
        return _get_live_pr_ready_node_identity_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrReadyNodeIdentity":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReadyNodeIdentityError("ready node identity must be an object")
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReadyNodeIdentityError("ready node identity fields mismatch")
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _attest_verified_pilot_exact_task_pr_ready_node_identity(
    *,
    ready_credential_capability: PilotExactTaskPrReadyCredentialCapability,
    reader: Callable[..., Mapping[str, Any]],
    now_provider: Callable[[], str],
) -> PilotExactTaskPrReadyNodeIdentity:
    capability, _observation, _reservation, requirements = _require_live_capability(
        ready_credential_capability
    )
    observed_at = now_provider()
    observed = _utc(observed_at, name="observed_at_utc")
    materialized = _utc(capability.materialized_at_utc, name="capability materialized_at_utc")
    if observed < materialized or (observed - materialized).total_seconds() > PILOT_EXACT_TASK_PR_READY_NODE_IDENTITY_MAX_CAPABILITY_AGE_SECONDS:
        raise PilotExactTaskPrReadyNodeIdentityError(
            "ready credential capability is too old for node identity attestation"
        )
    try:
        evidence = _validate_reader_evidence(
            reader(
                ready_credential_capability=capability,
                review_handoff_requirements=requirements,
            ),
            capability=capability,
        )
    except PilotExactTaskPrReadyNodeIdentityError:
        raise
    except Exception as exc:
        raise PilotExactTaskPrReadyNodeIdentityError(
            "exact PR node identity read failed"
        ) from exc
    result = PilotExactTaskPrReadyNodeIdentity(
        ready_credential_capability_sha256=capability.sha256,
        ready_state_observation_sha256=capability.ready_state_observation_sha256,
        ready_for_review_reservation_sha256=capability.ready_for_review_reservation_sha256,
        review_handoff_requirements_sha256=capability.review_handoff_requirements_sha256,
        pr_create_transaction_sha256=capability.pr_create_transaction_sha256,
        predicted_commit_sha=capability.predicted_commit_sha,
        review_handoff_plan_sha256=capability.review_handoff_plan_sha256,
        ready_for_review_nonce_sha256=capability.ready_for_review_nonce_sha256,
        repository=capability.repository,
        pull_request_number=capability.pull_request_number,
        pull_request_api_url=capability.pull_request_api_url,
        pull_request_html_url=capability.pull_request_html_url,
        pull_request_node_id=evidence["pull_request_node_id"],
        pull_request_node_id_sha256=evidence["pull_request_node_id_sha256"],
        base_branch=capability.base_branch,
        head_branch=capability.head_branch,
        signed_observed_updated_at_utc=capability.signed_observed_updated_at_utc,
        fresh_observed_updated_at_utc=capability.fresh_observed_updated_at_utc,
        request_url_sha256=evidence["request_url_sha256"],
        response_body_sha256=evidence["response_body_sha256"],
        response_etag_sha256=evidence["response_etag_sha256"],
        observed_updated_at_utc=evidence["observed_updated_at_utc"],
        observed_at_utc=observed_at,
    )
    _mark_pr_ready_node_identity_authenticated(result, capability)
    if result.identity_authenticated is not True:
        raise PilotExactTaskPrReadyNodeIdentityError(
            "ready node identity lost live capability provenance"
        )
    return result


def attest_pilot_exact_task_pr_ready_node_identity(
    ready_credential_capability: PilotExactTaskPrReadyCredentialCapability,
) -> PilotExactTaskPrReadyNodeIdentity:
    """Bind the exact public PR's GitHub node id; perform no mutation."""
    return _attest_verified_pilot_exact_task_pr_ready_node_identity(
        ready_credential_capability=ready_credential_capability,
        reader=_read_exact_pr_node_identity,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_READY_NODE_IDENTITY_SCHEMA",
    "PILOT_EXACT_TASK_PR_READY_NODE_IDENTITY_AUTHORITY",
    "PILOT_EXACT_TASK_PR_READY_NODE_IDENTITY_MAX_CAPABILITY_AGE_SECONDS",
    "PilotExactTaskPrReadyNodeIdentityError",
    "PilotExactTaskPrReadyNodeIdentity",
    "attest_pilot_exact_task_pr_ready_node_identity",
]
