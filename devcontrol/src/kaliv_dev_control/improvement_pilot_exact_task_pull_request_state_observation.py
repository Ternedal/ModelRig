"""ADR-DC-056 read-only observation of one exact GitHub pull-request state.

Consumes one exact live ADR-DC-055 human PR-mutation authorization proof. The
production entry point freshly re-verifies the human signature through the
host-pinned ADR-DC-055 authority, then performs two bounded GET-only reads from
the fixed GitHub API host:

1. verify the exact nonce-derived remote head still resolves to the published
   candidate commit SHA;
2. list open pull requests for exactly that same-repository head and base
   ``main`` and require the result to be empty.

No credential is loaded by this boundary, no GitHub mutation is performed, and
no PR/create/update/merge/release/deploy/production authority is granted.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Mapping

from . import improvement_pilot_exact_task_pull_request_mutation_authorization as auth_boundary
from . import improvement_pilot_exact_task_pull_request_mutation_requirements as requirements_boundary
from .github_read import GitHubReadError, HttpResponse, ReadOnlyTransport, UrllibReadOnlyTransport
from .improvement_pilot_exact_task_pull_request_mutation_authorization import (
    PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_PROOF_AUTHORITY,
    PilotExactTaskPullRequestMutationAuthorizationProof,
)

PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pull-request-state-observation/v1"
)
PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_AUTHORITY = (
    "host-observed-one-dc-l16-exact-open-pull-request-absent-only"
)
PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_SCOPE = (
    "one-read-only-exact-github-pull-request-state-observation-v1"
)
PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_API_HOST = "api.github.com"
PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_API_VERSION = "2022-11-28"
PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_MAX_PROOF_AGE_SECONDS = 5 * 60

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEAD_REF = re.compile(r"^refs/heads/agent/rsi/remote-candidate/[0-9a-f]{64}$")
_HEAD_BRANCH = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_MAX_HEAD_RESPONSE_BYTES = 32 * 1024
_MAX_PULL_LIST_RESPONSE_BYTES = 128 * 1024
_TIMEOUT_SECONDS = 30


class PilotExactTaskPullRequestStateObservationError(ValueError):
    """The exact GitHub pull-request state could not be observed safely."""


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
        raise PilotExactTaskPullRequestStateObservationError(
            "pull-request state observation is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskPullRequestStateObservationError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskPullRequestStateObservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPullRequestStateObservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPullRequestStateObservationError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _headers() -> Mapping[str, str]:
    return MappingProxyType(
        {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": (
                PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_API_VERSION
            ),
            "User-Agent": "kaliv-dev-control/1",
        }
    )


def _require_proof(
    value: Any,
) -> PilotExactTaskPullRequestMutationAuthorizationProof:
    if type(value) is not PilotExactTaskPullRequestMutationAuthorizationProof:
        raise PilotExactTaskPullRequestStateObservationError(
            "exact ADR-DC-055 PR-mutation authorization proof is required"
        )
    try:
        replayed = PilotExactTaskPullRequestMutationAuthorizationProof.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPullRequestStateObservationError(
            "ADR-DC-055 proof replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPullRequestStateObservationError(
            "ADR-DC-055 proof identity mismatch"
        )
    authorization = value.authorization
    requirements = authorization.pull_request_mutation_requirements
    if (
        value.authority
        != PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_PROOF_AUTHORITY
        or value.human_pr_mutation_authorization_verified is not True
        or value.draft_pull_request_required is not True
        or value.create_only_pull_request_required is not True
        or value.existing_open_pull_request_absent_required is not True
        or value.same_repository_head_required is not True
        or value.exact_base_ref_required is not True
        or value.exact_head_ref_required is not True
        or value.exact_head_sha_required is not True
        or value.one_shot_pr_mutation_required is not True
        or value.fresh_pull_request_state_observation_before_write_required is not True
        or value.one_shot_pr_mutation_reservation_required is not True
        or value.host_pinned_pr_credential_capability_required is not True
        or value.merge_separately_authorized_required is not True
        or value.pr_mutation_authorization_consumed is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.pull_request_create_authorized is not False
        or value.pull_request_update_authorized is not False
        or value.ready_for_review_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or authorization.pull_request_mutation_requirements_sha256
        != value.pull_request_mutation_requirements_sha256
        or authorization.predicted_commit_sha != value.predicted_commit_sha
        or authorization.remote_publication_nonce_sha256
        != value.remote_publication_nonce_sha256
        or authorization.pr_mutation_nonce_sha256 != value.pr_mutation_nonce_sha256
        or requirements.repository != "Ternedal/ModelRig"
        or requirements.api_host
        != PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_API_HOST
        or requirements.base_ref != "main"
        or _HEAD_REF.fullmatch(requirements.head_ref) is None
        or _HEAD_BRANCH.fullmatch(requirements.head_branch) is None
        or requirements.head_ref != f"refs/heads/{requirements.head_branch}"
        or requirements.predicted_commit_sha != value.predicted_commit_sha
    ):
        raise PilotExactTaskPullRequestStateObservationError(
            "PR-state observation requires one inert exact ADR-DC-055 proof"
        )
    return value


def _require_live_proof(
    value: Any,
) -> PilotExactTaskPullRequestMutationAuthorizationProof:
    proof = _require_proof(value)
    requirements = proof.authorization.pull_request_mutation_requirements
    try:
        live = auth_boundary._require_live_requirements(requirements)
    except Exception as exc:
        raise PilotExactTaskPullRequestStateObservationError(
            "PR-state observation requires live ADR-DC-054 provenance"
        ) from exc
    if live is not requirements:
        raise PilotExactTaskPullRequestStateObservationError(
            "ADR-DC-054 live requirements identity changed"
        )
    inputs = requirements_boundary._get_live_pull_request_mutation_requirements_inputs(
        requirements
    )
    transaction = None if inputs is None else inputs.get(
        "remote_publication_write_transaction"
    )
    if (
        transaction is None
        or getattr(transaction, "transaction_authenticated", None) is not True
        or getattr(transaction, "sha256", None)
        != requirements.remote_publication_write_transaction_sha256
        or getattr(transaction, "predicted_commit_sha", None)
        != requirements.predicted_commit_sha
        or getattr(transaction, "destination_ref", None) != requirements.head_ref
    ):
        raise PilotExactTaskPullRequestStateObservationError(
            "ADR-DC-054 requirements lost exact live ADR-DC-053 provenance"
        )
    return proof


def require_fresh_pull_request_mutation_authorization_proof_identity(
    supplied: PilotExactTaskPullRequestMutationAuthorizationProof,
    fresh: PilotExactTaskPullRequestMutationAuthorizationProof,
) -> None:
    left = _require_proof(supplied).to_dict()
    right = _require_proof(fresh).to_dict()
    left.pop("verified_at_utc")
    right.pop("verified_at_utc")
    if left != right:
        raise PilotExactTaskPullRequestStateObservationError(
            "fresh ADR-DC-055 proof does not match supplied PR authorization"
        )


def _require_observation_window(
    proof: PilotExactTaskPullRequestMutationAuthorizationProof,
    *,
    at_utc: str,
) -> datetime:
    at = _utc(at_utc, name="PR-state observation time")
    verified = _utc(proof.verified_at_utc, name="PR proof verified_at_utc")
    authorized = _utc(
        proof.authorization.authorized_at_utc,
        name="PR authorization authorized_at_utc",
    )
    expires = _utc(
        proof.authorization.expires_at_utc,
        name="PR authorization expires_at_utc",
    )
    if at < authorized or at < verified or at > expires:
        raise PilotExactTaskPullRequestStateObservationError(
            "PR-state observation is outside the live human authorization window"
        )
    if (
        at - verified
    ).total_seconds() > PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_MAX_PROOF_AGE_SECONDS:
        raise PilotExactTaskPullRequestStateObservationError(
            "ADR-DC-055 proof is too old for fresh PR-state observation"
        )
    return at


def _content_type(response: HttpResponse) -> str:
    return response.headers.get("content-type", "").split(";", 1)[0].strip().lower()


def _require_clean_response(
    response: Any,
    *,
    maximum: int,
    operation: str,
) -> HttpResponse:
    if not isinstance(response, HttpResponse):
        raise PilotExactTaskPullRequestStateObservationError(
            f"GitHub {operation} transport returned an invalid response"
        )
    if "location" in response.headers:
        raise PilotExactTaskPullRequestStateObservationError(
            f"GitHub {operation} redirect is forbidden"
        )
    if response.status != 200:
        raise PilotExactTaskPullRequestStateObservationError(
            f"GitHub {operation} returned status {response.status}"
        )
    if _content_type(response) not in {
        "application/json",
        "application/vnd.github+json",
    }:
        raise PilotExactTaskPullRequestStateObservationError(
            f"GitHub {operation} response is not JSON"
        )
    if len(response.body) > maximum:
        raise PilotExactTaskPullRequestStateObservationError(
            f"GitHub {operation} response exceeded byte ceiling"
        )
    return response


def _json(value: bytes, *, operation: str) -> Any:
    try:
        return json.loads(value.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPullRequestStateObservationError(
            f"GitHub {operation} response is invalid UTF-8 JSON"
        ) from exc


def _head_url(requirements: Any) -> str:
    quoted = urllib.parse.quote(requirements.head_branch, safe="/")
    return (
        "https://api.github.com/repos/Ternedal/ModelRig/git/ref/heads/"
        + quoted.removeprefix("heads/")
    )


def _pulls_url(requirements: Any) -> str:
    query = urllib.parse.urlencode(
        (
            ("state", "open"),
            ("head", f"Ternedal:{requirements.head_branch}"),
            ("base", requirements.base_ref),
            ("per_page", "2"),
            ("page", "1"),
        ),
        quote_via=urllib.parse.quote,
    )
    return "https://api.github.com/repos/Ternedal/ModelRig/pulls?" + query


def _query_sha256(requirements: Any) -> str:
    parsed = urllib.parse.urlsplit(_pulls_url(requirements))
    return hashlib.sha256(parsed.query.encode("ascii")).hexdigest()


def _observe_remote_head(
    *,
    transport: ReadOnlyTransport,
    requirements: Any,
) -> HttpResponse:
    try:
        raw = transport.get(
            _head_url(requirements),
            headers=_headers(),
            timeout_seconds=_TIMEOUT_SECONDS,
            max_bytes=_MAX_HEAD_RESPONSE_BYTES,
        )
    except Exception as exc:
        raise PilotExactTaskPullRequestStateObservationError(
            "exact GitHub head ref could not be observed safely"
        ) from exc
    response = _require_clean_response(
        raw,
        maximum=_MAX_HEAD_RESPONSE_BYTES,
        operation="head-ref observation",
    )
    document = _json(response.body, operation="head-ref observation")
    if not isinstance(document, Mapping):
        raise PilotExactTaskPullRequestStateObservationError(
            "GitHub head-ref response must be an object"
        )
    obj = document.get("object")
    if (
        document.get("ref") != requirements.head_ref
        or not isinstance(obj, Mapping)
        or obj.get("type") != "commit"
        or obj.get("sha") != requirements.predicted_commit_sha
    ):
        raise PilotExactTaskPullRequestStateObservationError(
            "GitHub remote head no longer equals the exact published candidate"
        )
    return response


def _reject_hidden_pagination(response: HttpResponse) -> None:
    link = response.headers.get("link", "")
    compact = link.replace(" ", "").lower()
    if 'rel="next"' in compact or "rel=next" in compact:
        raise PilotExactTaskPullRequestStateObservationError(
            "GitHub exact PR query unexpectedly requires pagination"
        )


def _observe_open_pull_request_absent(
    *,
    transport: ReadOnlyTransport,
    requirements: Any,
) -> HttpResponse:
    try:
        raw = transport.get(
            _pulls_url(requirements),
            headers=_headers(),
            timeout_seconds=_TIMEOUT_SECONDS,
            max_bytes=_MAX_PULL_LIST_RESPONSE_BYTES,
        )
    except Exception as exc:
        raise PilotExactTaskPullRequestStateObservationError(
            "exact GitHub pull-request state could not be observed safely"
        ) from exc
    response = _require_clean_response(
        raw,
        maximum=_MAX_PULL_LIST_RESPONSE_BYTES,
        operation="pull-request observation",
    )
    _reject_hidden_pagination(response)
    document = _json(response.body, operation="pull-request observation")
    if not isinstance(document, list):
        raise PilotExactTaskPullRequestStateObservationError(
            "GitHub pull-request list response must be an array"
        )
    if document:
        raise PilotExactTaskPullRequestStateObservationError(
            "an open pull request already exists for the exact head/base pair"
        )
    return response


def _live_registry():
    records: dict[
        int,
        tuple[
            int,
            str,
            weakref.ReferenceType[Any],
            PilotExactTaskPullRequestMutationAuthorizationProof,
        ],
    ] = {}

    def mark(
        observation: Any,
        proof: PilotExactTaskPullRequestMutationAuthorizationProof,
    ) -> None:
        key = id(observation)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            observation.sha256,
            weakref.ref(observation, cleanup),
            proof,
        )

    def get(observation: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(observation))
        if entry is None:
            return None
        pid, digest, observation_ref, proof = entry
        if (
            pid != os.getpid()
            or observation_ref() is not observation
            or observation.sha256 != digest
            or proof.sha256
            != observation.pull_request_mutation_authorization_proof_sha256
        ):
            return None
        try:
            _require_live_proof(proof)
        except Exception:
            return None
        return MappingProxyType(
            {"pull_request_mutation_authorization_proof": proof}
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_pull_request_state_observation_authenticated,
    _get_live_pull_request_state_observation_inputs,
) = _live_registry()


_REQUIRED_TRUE = (
    "human_pr_mutation_authorization_verified",
    "fresh_authorization_proof_reverified",
    "live_pr_requirements_verified",
    "remote_head_ref_observed",
    "remote_head_sha_matches_exact_candidate",
    "pull_request_state_observed",
    "existing_open_pull_request_absent",
    "same_repository_head_verified",
    "exact_base_ref_verified",
    "fixed_api_host_verified",
    "https_only_read",
    "get_only_read",
    "redirects_forbidden",
    "credentials_not_required",
    "response_bounded",
    "one_shot_pr_mutation_reservation_required",
    "host_pinned_pr_credential_capability_required",
    "merge_separately_authorized_required",
)

_FORCED_FALSE = (
    "pr_mutation_authorization_consumed",
    "remote_write_authorized",
    "push_authorized",
    "pr_mutation_authorized",
    "pull_request_create_authorized",
    "pull_request_update_authorized",
    "ready_for_review_authorized",
    "merge_authorized",
    "release_authorized",
    "deploy_authorized",
    "production_activation_authorized",
)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPullRequestStateObservation:
    pull_request_mutation_authorization_proof_sha256: str
    pull_request_mutation_requirements_sha256: str
    remote_publication_write_transaction_sha256: str
    remote_publication_nonce_sha256: str
    pr_mutation_nonce_sha256: str
    predicted_commit_sha: str
    repository: str
    api_host: str
    api_version: str
    base_ref: str
    head_owner: str
    head_ref: str
    head_branch: str
    query_sha256: str
    head_response_sha256: str
    head_response_bytes: int
    pull_list_response_sha256: str
    pull_list_response_bytes: int
    observed_at_utc: str
    human_pr_mutation_authorization_verified: bool = True
    fresh_authorization_proof_reverified: bool = True
    live_pr_requirements_verified: bool = True
    remote_head_ref_observed: bool = True
    remote_head_sha_matches_exact_candidate: bool = True
    pull_request_state_observed: bool = True
    existing_open_pull_request_absent: bool = True
    same_repository_head_verified: bool = True
    exact_base_ref_verified: bool = True
    fixed_api_host_verified: bool = True
    https_only_read: bool = True
    get_only_read: bool = True
    redirects_forbidden: bool = True
    credentials_not_required: bool = True
    response_bounded: bool = True
    one_shot_pr_mutation_reservation_required: bool = True
    host_pinned_pr_credential_capability_required: bool = True
    merge_separately_authorized_required: bool = True
    pr_mutation_authorization_consumed: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    pull_request_create_authorized: bool = False
    pull_request_update_authorized: bool = False
    ready_for_review_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_AUTHORITY
    observation_scope: str = PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_SCOPE
    schema: str = PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_SCHEMA:
            raise PilotExactTaskPullRequestStateObservationError(
                "PR-state observation schema is unsupported"
            )
        if self.authority != PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_AUTHORITY:
            raise PilotExactTaskPullRequestStateObservationError(
                "PR-state observation authority is unsupported"
            )
        if self.observation_scope != PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_SCOPE:
            raise PilotExactTaskPullRequestStateObservationError(
                "PR-state observation scope is unsupported"
            )
        for name in (
            "pull_request_mutation_authorization_proof_sha256",
            "pull_request_mutation_requirements_sha256",
            "remote_publication_write_transaction_sha256",
            "remote_publication_nonce_sha256",
            "pr_mutation_nonce_sha256",
            "query_sha256",
            "head_response_sha256",
            "pull_list_response_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        if (
            self.repository != "Ternedal/ModelRig"
            or self.api_host
            != PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_API_HOST
            or self.api_version
            != PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_API_VERSION
            or self.base_ref != "main"
            or self.head_owner != "Ternedal"
            or _HEAD_REF.fullmatch(self.head_ref) is None
            or _HEAD_BRANCH.fullmatch(self.head_branch) is None
            or self.head_ref != f"refs/heads/{self.head_branch}"
            or not self.head_ref.endswith(self.remote_publication_nonce_sha256)
        ):
            raise PilotExactTaskPullRequestStateObservationError(
                "PR-state observation target binding is invalid"
            )
        for name, maximum in (
            ("head_response_bytes", _MAX_HEAD_RESPONSE_BYTES),
            ("pull_list_response_bytes", _MAX_PULL_LIST_RESPONSE_BYTES),
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 1
                or value > maximum
            ):
                raise PilotExactTaskPullRequestStateObservationError(
                    f"{name} is outside the bounded response range"
                )
        _utc(self.observed_at_utc, name="observed_at_utc")
        if any(getattr(self, name) is not True for name in _REQUIRED_TRUE):
            raise PilotExactTaskPullRequestStateObservationError(
                "PR-state observation evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in _FORCED_FALSE):
            raise PilotExactTaskPullRequestStateObservationError(
                "PR-state observation cannot grant mutation authority"
            )

    @property
    def observation_authenticated(self) -> bool:
        return _get_live_pull_request_state_observation_inputs(self) is not None

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
        cls, value: Any
    ) -> "PilotExactTaskPullRequestStateObservation":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPullRequestStateObservationError(
                "PR-state observation must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPullRequestStateObservationError(
                "PR-state observation fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _observe_verified_pilot_exact_task_pull_request_state(
    *,
    authorization_proof: PilotExactTaskPullRequestMutationAuthorizationProof,
    fresh_authorization_proof: PilotExactTaskPullRequestMutationAuthorizationProof,
    transport: ReadOnlyTransport,
    now_provider: Callable[[], str],
) -> PilotExactTaskPullRequestStateObservation:
    proof = _require_live_proof(authorization_proof)
    require_fresh_pull_request_mutation_authorization_proof_identity(
        proof,
        fresh_authorization_proof,
    )
    requirements = proof.authorization.pull_request_mutation_requirements
    started_at = now_provider()
    _require_observation_window(fresh_authorization_proof, at_utc=started_at)
    head_response = _observe_remote_head(
        transport=transport,
        requirements=requirements,
    )
    pull_response = _observe_open_pull_request_absent(
        transport=transport,
        requirements=requirements,
    )
    observed_at = now_provider()
    started = _utc(started_at, name="PR-state observation started_at_utc")
    observed = _require_observation_window(
        fresh_authorization_proof,
        at_utc=observed_at,
    )
    if observed < started:
        raise PilotExactTaskPullRequestStateObservationError(
            "system clock moved backwards during PR-state observation"
        )
    result = PilotExactTaskPullRequestStateObservation(
        pull_request_mutation_authorization_proof_sha256=proof.sha256,
        pull_request_mutation_requirements_sha256=requirements.sha256,
        remote_publication_write_transaction_sha256=(
            requirements.remote_publication_write_transaction_sha256
        ),
        remote_publication_nonce_sha256=requirements.remote_publication_nonce_sha256,
        pr_mutation_nonce_sha256=proof.pr_mutation_nonce_sha256,
        predicted_commit_sha=requirements.predicted_commit_sha,
        repository=requirements.repository,
        api_host=requirements.api_host,
        api_version=PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_API_VERSION,
        base_ref=requirements.base_ref,
        head_owner="Ternedal",
        head_ref=requirements.head_ref,
        head_branch=requirements.head_branch,
        query_sha256=_query_sha256(requirements),
        head_response_sha256=hashlib.sha256(head_response.body).hexdigest(),
        head_response_bytes=len(head_response.body),
        pull_list_response_sha256=hashlib.sha256(pull_response.body).hexdigest(),
        pull_list_response_bytes=len(pull_response.body),
        observed_at_utc=observed_at,
    )
    _mark_pull_request_state_observation_authenticated(result, proof)
    if result.observation_authenticated is not True:
        raise PilotExactTaskPullRequestStateObservationError(
            "PR-state observation lost live ADR-DC-055 provenance"
        )
    return result


def observe_pilot_exact_task_pull_request_state(
    *,
    authorization_proof: PilotExactTaskPullRequestMutationAuthorizationProof,
    authorization_signature: Any,
) -> PilotExactTaskPullRequestStateObservation:
    """Observe exact GitHub PR absence without granting mutation authority."""
    proof = _require_live_proof(authorization_proof)
    authorization = proof.authorization
    requirements = authorization.pull_request_mutation_requirements
    try:
        fresh_proof = (
            auth_boundary.verify_pilot_exact_task_pull_request_mutation_authorization(
                pull_request_mutation_requirements=requirements,
                authorization=authorization,
                signature=authorization_signature,
            )
        )
        require_fresh_pull_request_mutation_authorization_proof_identity(
            proof,
            fresh_proof,
        )
        transport = UrllibReadOnlyTransport()
    except PilotExactTaskPullRequestStateObservationError:
        raise
    except Exception as exc:
        raise PilotExactTaskPullRequestStateObservationError(
            "host-controlled PR-state observation authority is unavailable"
        ) from exc
    try:
        return _observe_verified_pilot_exact_task_pull_request_state(
            authorization_proof=proof,
            fresh_authorization_proof=fresh_proof,
            transport=transport,
            now_provider=_now_utc_seconds,
        )
    except GitHubReadError as exc:
        raise PilotExactTaskPullRequestStateObservationError(
            "hardened GitHub read boundary failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_SCHEMA",
    "PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_AUTHORITY",
    "PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_SCOPE",
    "PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_API_HOST",
    "PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_API_VERSION",
    "PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_MAX_PROOF_AGE_SECONDS",
    "PilotExactTaskPullRequestStateObservationError",
    "PilotExactTaskPullRequestStateObservation",
    "observe_pilot_exact_task_pull_request_state",
]
