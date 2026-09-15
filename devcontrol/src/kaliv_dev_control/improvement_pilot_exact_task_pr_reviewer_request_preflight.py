"""ADR-DC-073 fresh exact PR preflight before one reviewer request.

Consumes one exact live ADR-DC-072 reviewer requestability precondition and
performs one fresh credential-free exact-PR read through the already-hardened
ADR-DC-070 reader. This boundary revalidates the immutable reviewer target,
exact head/metadata, non-self-review, and absence of requested reviewers. It
performs no GitHub mutation and grants no reviewer-write authority.
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

from . import improvement_pilot_exact_task_pr_reviewer_identity_state_observation as identity_boundary
from . import improvement_pilot_exact_task_pr_reviewer_request_credential_capability as capability_boundary
from . import improvement_pilot_exact_task_pr_reviewer_requestability_precondition as requestability_boundary
from .improvement_pilot_exact_task_pr_reviewer_requestability_precondition import (
    PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PRECONDITION_AUTHORITY,
    PilotExactTaskPrReviewerRequestabilityPrecondition,
)

PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_PREFLIGHT_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-reviewer-request-preflight/v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_PREFLIGHT_AUTHORITY = (
    "observed-one-dc-l16-exact-pr-reviewer-request-preflight-only"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_PREFLIGHT_SCOPE = (
    "fresh-credential-free-exact-pr-state-before-reviewer-request-v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_PREFLIGHT_MAX_PRECONDITION_AGE_SECONDS = 30

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_ALLOWED_PERMISSIONS = frozenset({"read", "write", "admin"})


class PilotExactTaskPrReviewerRequestPreflightError(ValueError):
    """Reviewer-request preflight is stale, drifted, or lacks live provenance."""


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
        raise PilotExactTaskPrReviewerRequestPreflightError(
            "reviewer-request preflight is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrReviewerRequestPreflightError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrReviewerRequestPreflightError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReviewerRequestPreflightError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrReviewerRequestPreflightError(f"{name} is invalid") from exc


def _login(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _LOGIN.fullmatch(value) is None:
        raise PilotExactTaskPrReviewerRequestPreflightError(f"{name} is invalid")
    return value


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _require_live_precondition(
    value: Any,
) -> tuple[PilotExactTaskPrReviewerRequestabilityPrecondition, Any, Any, Any, Any]:
    if type(value) is not PilotExactTaskPrReviewerRequestabilityPrecondition:
        raise PilotExactTaskPrReviewerRequestPreflightError(
            "exact ADR-DC-072 requestability precondition is required"
        )
    try:
        replayed = PilotExactTaskPrReviewerRequestabilityPrecondition.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewerRequestPreflightError(
            "ADR-DC-072 precondition replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrReviewerRequestPreflightError(
            "ADR-DC-072 precondition identity mismatch"
        )
    required_true = (
        "reviewer_request_authorization_consumed",
        "reviewer_request_slot_reserved",
        "reviewer_identity_verified",
        "exact_pr_state_reverified",
        "credential_broker_freshly_verified",
        "credential_broker_invoked_without_secret_exposure",
        "permission_read_performed",
        "minimum_read_repository_permission_verified",
        "reviewer_requestability_precondition_verified",
        "fresh_pr_state_revalidation_before_reviewer_request_required",
        "post_request_readback_verification_required",
        "one_shot_reviewer_request_transaction_required",
        "team_reviewers_forbidden",
    )
    forced_false = (
        "credential_material_in_artifact",
        "credential_material_in_process_arguments",
        "credential_material_in_environment",
        "reviewer_mutation_authorized",
        "reviewer_request_performed",
        "label_mutation_authorized",
        "merge_authorized",
        "release_authorized",
        "deploy_authorized",
        "production_activation_authorized",
    )
    if (
        value.authority != PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PRECONDITION_AUTHORITY
        or value.observation_authenticated is not True
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
        or value.repository != "Ternedal/ModelRig"
        or value.base_branch != "main"
        or _HEAD.fullmatch(value.head_branch) is None
        or value.repository_permission not in _ALLOWED_PERMISSIONS
    ):
        raise PilotExactTaskPrReviewerRequestPreflightError(
            "preflight requires one live inert ADR-DC-072 precondition"
        )

    precondition_inputs = (
        requestability_boundary._get_live_pr_reviewer_requestability_precondition_inputs(
            value
        )
    )
    capability = None if precondition_inputs is None else precondition_inputs.get(
        "reviewer_request_credential_capability"
    )
    capability_inputs = (
        None
        if capability is None
        else capability_boundary._get_live_pr_reviewer_request_credential_capability_inputs(
            capability
        )
    )
    identity = None if capability_inputs is None else capability_inputs.get(
        "reviewer_identity_state_observation"
    )
    identity_inputs = (
        None
        if identity is None
        else identity_boundary._get_live_pr_reviewer_identity_state_observation_inputs(
            identity
        )
    )
    reservation = None if identity_inputs is None else identity_inputs.get(
        "reviewer_request_reservation"
    )
    try:
        receipt, target, requirements = identity_boundary._require_live_reservation(
            reservation
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewerRequestPreflightError(
            "ADR-DC-072 lost live ADR-DC-070/069 provenance"
        ) from exc

    if (
        capability is None
        or getattr(capability, "capability_authenticated", None) is not True
        or capability.sha256 != value.reviewer_request_credential_capability_sha256
        or identity is None
        or getattr(identity, "observation_authenticated", None) is not True
        or identity.sha256 != value.reviewer_identity_observation_sha256
        or receipt.sha256 != value.reviewer_request_reservation_sha256
        or target.sha256 != value.reviewer_target_attestation_sha256
        or requirements.sha256 != value.reviewer_handoff_requirements_sha256
        or target.reviewer_target_policy_sha256 != value.reviewer_target_policy_sha256
        or target.reviewer_target_policy_epoch != value.reviewer_target_policy_epoch
        or receipt.reviewer_request_nonce_sha256 != value.reviewer_request_nonce_sha256
        or receipt.pull_request_number != value.pull_request_number
        or receipt.predicted_commit_sha != value.predicted_commit_sha
        or target.reviewer_login != value.reviewer_login
        or target.reviewer_user_id != value.reviewer_user_id
        or identity.reviewer_user_node_id_sha256 != value.reviewer_user_node_id_sha256
    ):
        raise PilotExactTaskPrReviewerRequestPreflightError(
            "ADR-DC-072 live provenance does not match exact reviewer/PR target"
        )
    return value, identity, receipt, target, requirements


def _require_precondition_window(
    precondition: PilotExactTaskPrReviewerRequestabilityPrecondition,
    *,
    at_utc: str,
) -> None:
    at = _utc(at_utc, name="preflight_started_at_utc")
    observed = _utc(precondition.observed_at_utc, name="requestability_observed_at_utc")
    if (
        at < observed
        or (at - observed).total_seconds()
        > PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_PREFLIGHT_MAX_PRECONDITION_AGE_SECONDS
    ):
        raise PilotExactTaskPrReviewerRequestPreflightError(
            "ADR-DC-072 requestability precondition is too old for reviewer-request preflight"
        )


def _validate_pr_evidence(
    value: Any,
    *,
    precondition: PilotExactTaskPrReviewerRequestabilityPrecondition,
    target: Any,
) -> Mapping[str, Any]:
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
        raise PilotExactTaskPrReviewerRequestPreflightError(
            "fresh PR preflight evidence fields mismatch"
        )
    result = dict(value)
    for name in (
        "pr_request_url_sha256",
        "pr_response_body_sha256",
        "pr_response_etag_sha256",
    ):
        _hex64(result.get(name), name=name)
    author_login = _login(
        result.get("pull_request_author_login"),
        name="pull_request_author_login",
    )
    author_id = result.get("pull_request_author_user_id")
    if (
        result["pr_request_url_sha256"]
        != hashlib.sha256(precondition.pull_request_api_url.encode("utf-8")).hexdigest()
        or result.get("observed_updated_at_utc") != target.ready_updated_at_utc
        or result.get("requested_reviewer_count") != 0
        or result.get("requested_team_count") != 0
        or isinstance(author_id, bool)
        or not isinstance(author_id, int)
        or author_id < 1
        or author_id == precondition.reviewer_user_id
        or author_login.lower() == precondition.reviewer_login.lower()
    ):
        raise PilotExactTaskPrReviewerRequestPreflightError(
            "fresh PR preflight evidence does not match exact safe state"
        )
    _utc(result["observed_updated_at_utc"], name="fresh_observed_updated_at_utc")
    return MappingProxyType(result)


_live_records: dict[
    int,
    tuple[
        int,
        str,
        weakref.ReferenceType[Any],
        weakref.ReferenceType[PilotExactTaskPrReviewerRequestabilityPrecondition],
    ],
] = {}


def _mark_authenticated(
    observation: Any,
    precondition: PilotExactTaskPrReviewerRequestabilityPrecondition,
) -> None:
    key = id(observation)

    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)

    _live_records[key] = (
        os.getpid(),
        observation.sha256,
        weakref.ref(observation, cleanup),
        weakref.ref(precondition),
    )


def _get_live_pr_reviewer_request_preflight_inputs(
    observation: Any,
) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(observation))
    if entry is None:
        return None
    pid, digest, observation_ref, precondition_ref = entry
    precondition = precondition_ref()
    if (
        pid != os.getpid()
        or observation_ref() is not observation
        or precondition is None
        or precondition.observation_authenticated is not True
        or precondition.sha256 != observation.reviewer_requestability_precondition_sha256
        or observation.sha256 != digest
    ):
        return None
    return MappingProxyType({"reviewer_requestability_precondition": precondition})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReviewerRequestPreflight:
    reviewer_requestability_precondition_sha256: str
    reviewer_request_credential_capability_sha256: str
    reviewer_identity_observation_sha256: str
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
    reviewer_login: str
    reviewer_user_id: int
    reviewer_user_node_id_sha256: str
    repository_permission: str
    repository_role_name_sha256: str
    requestability_observed_at_utc: str
    ready_updated_at_utc: str
    fresh_pr_request_url_sha256: str
    fresh_pr_response_body_sha256: str
    fresh_pr_response_etag_sha256: str
    pull_request_author_login: str
    pull_request_author_user_id: int
    fresh_observed_updated_at_utc: str
    preflight_started_at_utc: str
    observed_at_utc: str
    reviewer_request_authorization_consumed: bool = True
    reviewer_request_slot_reserved: bool = True
    reviewer_identity_verified: bool = True
    reviewer_requestability_precondition_verified: bool = True
    fresh_exact_pr_state_revalidated: bool = True
    no_requested_reviewers_verified: bool = True
    reviewer_not_pr_author_verified: bool = True
    credential_free_pr_read: bool = True
    redirects_forbidden: bool = True
    response_bounded: bool = True
    reviewer_write_credential_capability_required: bool = True
    one_shot_reviewer_request_transaction_required: bool = True
    post_request_readback_verification_required: bool = True
    team_reviewers_forbidden: bool = True
    reviewer_mutation_authorized: bool = False
    reviewer_request_performed: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_PREFLIGHT_AUTHORITY
    observation_scope: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_PREFLIGHT_SCOPE
    schema: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_PREFLIGHT_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_PREFLIGHT_SCHEMA
            or self.authority != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_PREFLIGHT_AUTHORITY
            or self.observation_scope != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_PREFLIGHT_SCOPE
        ):
            raise PilotExactTaskPrReviewerRequestPreflightError(
                "reviewer-request preflight schema/authority/scope is unsupported"
            )
        for name in (
            "reviewer_requestability_precondition_sha256",
            "reviewer_request_credential_capability_sha256",
            "reviewer_identity_observation_sha256",
            "reviewer_request_reservation_sha256",
            "reviewer_target_attestation_sha256",
            "reviewer_handoff_requirements_sha256",
            "reviewer_target_policy_sha256",
            "reviewer_request_nonce_sha256",
            "pull_request_node_id_sha256",
            "reviewer_user_node_id_sha256",
            "repository_role_name_sha256",
            "fresh_pr_request_url_sha256",
            "fresh_pr_response_body_sha256",
            "fresh_pr_response_etag_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _login(self.reviewer_login, name="reviewer_login")
        author_login = _login(
            self.pull_request_author_login,
            name="pull_request_author_login",
        )
        requestability_observed = _utc(
            self.requestability_observed_at_utc,
            name="requestability_observed_at_utc",
        )
        ready_updated = _utc(self.ready_updated_at_utc, name="ready_updated_at_utc")
        fresh_updated = _utc(
            self.fresh_observed_updated_at_utc,
            name="fresh_observed_updated_at_utc",
        )
        started = _utc(self.preflight_started_at_utc, name="preflight_started_at_utc")
        observed = _utc(self.observed_at_utc, name="observed_at_utc")
        if (
            fresh_updated != ready_updated
            or started < requestability_observed
            or observed < started
            or (started - requestability_observed).total_seconds()
            > PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_PREFLIGHT_MAX_PRECONDITION_AGE_SECONDS
        ):
            raise PilotExactTaskPrReviewerRequestPreflightError(
                "reviewer-request preflight timestamps are invalid"
            )
        if (
            self.repository != "Ternedal/ModelRig"
            or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
            or self.repository_permission not in _ALLOWED_PERMISSIONS
            or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or isinstance(self.reviewer_user_id, bool)
            or not isinstance(self.reviewer_user_id, int)
            or self.reviewer_user_id < 1
            or isinstance(self.reviewer_target_policy_epoch, bool)
            or not isinstance(self.reviewer_target_policy_epoch, int)
            or self.reviewer_target_policy_epoch < 1
            or isinstance(self.pull_request_author_user_id, bool)
            or not isinstance(self.pull_request_author_user_id, int)
            or self.pull_request_author_user_id < 1
            or self.pull_request_author_user_id == self.reviewer_user_id
            or author_login.lower() == self.reviewer_login.lower()
            or self.pull_request_api_url
            != f"https://api.github.com/repos/Ternedal/ModelRig/pulls/{self.pull_request_number}"
            or self.pull_request_html_url
            != f"https://github.com/Ternedal/ModelRig/pull/{self.pull_request_number}"
            or self.fresh_pr_request_url_sha256
            != hashlib.sha256(self.pull_request_api_url.encode("utf-8")).hexdigest()
        ):
            raise PilotExactTaskPrReviewerRequestPreflightError(
                "reviewer-request preflight binding is invalid"
            )
        required_true = (
            "reviewer_request_authorization_consumed",
            "reviewer_request_slot_reserved",
            "reviewer_identity_verified",
            "reviewer_requestability_precondition_verified",
            "fresh_exact_pr_state_revalidated",
            "no_requested_reviewers_verified",
            "reviewer_not_pr_author_verified",
            "credential_free_pr_read",
            "redirects_forbidden",
            "response_bounded",
            "reviewer_write_credential_capability_required",
            "one_shot_reviewer_request_transaction_required",
            "post_request_readback_verification_required",
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
            raise PilotExactTaskPrReviewerRequestPreflightError(
                "reviewer-request preflight evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReviewerRequestPreflightError(
                "reviewer-request preflight cannot grant mutation authority"
            )

    @property
    def observation_authenticated(self) -> bool:
        return _get_live_pr_reviewer_request_preflight_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrReviewerRequestPreflight":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReviewerRequestPreflightError(
                "reviewer-request preflight must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReviewerRequestPreflightError(
                "reviewer-request preflight fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _observe_verified_pilot_exact_task_pr_reviewer_request_preflight(
    *,
    reviewer_requestability_precondition: PilotExactTaskPrReviewerRequestabilityPrecondition,
    pr_reader: Callable[..., Mapping[str, Any]],
    now_provider: Callable[[], str],
) -> PilotExactTaskPrReviewerRequestPreflight:
    precondition, identity, receipt, target, requirements = _require_live_precondition(
        reviewer_requestability_precondition
    )
    started_at = now_provider()
    _require_precondition_window(precondition, at_utc=started_at)
    evidence = _validate_pr_evidence(
        pr_reader(
            reservation_receipt=receipt,
            reviewer_target=target,
            reviewer_handoff_requirements=requirements,
        ),
        precondition=precondition,
        target=target,
    )
    observed_at = now_provider()
    if _utc(observed_at, name="observed_at_utc") < _utc(
        started_at,
        name="preflight_started_at_utc",
    ):
        raise PilotExactTaskPrReviewerRequestPreflightError(
            "clock moved backwards during reviewer-request preflight"
        )
    result = PilotExactTaskPrReviewerRequestPreflight(
        reviewer_requestability_precondition_sha256=precondition.sha256,
        reviewer_request_credential_capability_sha256=precondition.reviewer_request_credential_capability_sha256,
        reviewer_identity_observation_sha256=precondition.reviewer_identity_observation_sha256,
        reviewer_request_reservation_sha256=precondition.reviewer_request_reservation_sha256,
        reviewer_target_attestation_sha256=precondition.reviewer_target_attestation_sha256,
        reviewer_handoff_requirements_sha256=precondition.reviewer_handoff_requirements_sha256,
        reviewer_target_policy_sha256=precondition.reviewer_target_policy_sha256,
        reviewer_target_policy_epoch=precondition.reviewer_target_policy_epoch,
        reviewer_request_nonce_sha256=precondition.reviewer_request_nonce_sha256,
        repository=precondition.repository,
        pull_request_number=precondition.pull_request_number,
        pull_request_api_url=precondition.pull_request_api_url,
        pull_request_html_url=precondition.pull_request_html_url,
        pull_request_node_id_sha256=precondition.pull_request_node_id_sha256,
        base_branch=precondition.base_branch,
        head_branch=precondition.head_branch,
        predicted_commit_sha=precondition.predicted_commit_sha,
        reviewer_login=precondition.reviewer_login,
        reviewer_user_id=precondition.reviewer_user_id,
        reviewer_user_node_id_sha256=precondition.reviewer_user_node_id_sha256,
        repository_permission=precondition.repository_permission,
        repository_role_name_sha256=precondition.repository_role_name_sha256,
        requestability_observed_at_utc=precondition.observed_at_utc,
        ready_updated_at_utc=target.ready_updated_at_utc,
        fresh_pr_request_url_sha256=str(evidence["pr_request_url_sha256"]),
        fresh_pr_response_body_sha256=str(evidence["pr_response_body_sha256"]),
        fresh_pr_response_etag_sha256=str(evidence["pr_response_etag_sha256"]),
        pull_request_author_login=str(evidence["pull_request_author_login"]),
        pull_request_author_user_id=int(evidence["pull_request_author_user_id"]),
        fresh_observed_updated_at_utc=str(evidence["observed_updated_at_utc"]),
        preflight_started_at_utc=started_at,
        observed_at_utc=observed_at,
    )
    if (
        identity.pull_request_author_user_id != result.pull_request_author_user_id
        or identity.pull_request_author_login != result.pull_request_author_login
    ):
        raise PilotExactTaskPrReviewerRequestPreflightError(
            "pull-request author identity changed since ADR-DC-070"
        )
    _mark_authenticated(result, precondition)
    if result.observation_authenticated is not True:
        raise PilotExactTaskPrReviewerRequestPreflightError(
            "reviewer-request preflight lost live ADR-DC-072 provenance"
        )
    return result


def observe_pilot_exact_task_pr_reviewer_request_preflight(
    reviewer_requestability_precondition: PilotExactTaskPrReviewerRequestabilityPrecondition,
) -> PilotExactTaskPrReviewerRequestPreflight:
    """Freshly revalidate the exact ready PR; never request a reviewer."""
    return _observe_verified_pilot_exact_task_pr_reviewer_request_preflight(
        reviewer_requestability_precondition=reviewer_requestability_precondition,
        pr_reader=identity_boundary._read_exact_ready_pr_state,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_PREFLIGHT_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_PREFLIGHT_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_PREFLIGHT_SCOPE",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_PREFLIGHT_MAX_PRECONDITION_AGE_SECONDS",
    "PilotExactTaskPrReviewerRequestPreflightError",
    "PilotExactTaskPrReviewerRequestPreflight",
    "observe_pilot_exact_task_pr_reviewer_request_preflight",
]
