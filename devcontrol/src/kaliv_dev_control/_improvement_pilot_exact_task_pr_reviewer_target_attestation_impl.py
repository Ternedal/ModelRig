"""ADR-DC-067 host-pinned exact reviewer-target attestation.

Consumes one exact live ADR-DC-066 reviewer-handoff requirements artifact and
binds it to one host-admin-controlled reviewer policy. No GitHub request or
mutation occurs. Reviewer eligibility/identity must be freshly observed later,
and a separate human-signed reviewer-request authorization is still required.
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

from . import improvement_pilot_exact_task_pr_reviewer_handoff_requirements as handoff_boundary
from .improvement_pilot_exact_task_pr_reviewer_handoff_requirements import (
    PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_REQUIREMENTS_AUTHORITY,
    PILOT_EXACT_TASK_PR_REVIEWER_SELECTION_SOURCE,
    PilotExactTaskPrReviewerHandoffRequirements,
)

PILOT_EXACT_TASK_PR_REVIEWER_TARGET_POLICY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-reviewer-target-policy/v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_TARGET_ATTESTATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-reviewer-target-attestation/v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_TARGET_ATTESTATION_AUTHORITY = (
    "host-attested-one-dc-l16-exact-pr-reviewer-target-only"
)
PILOT_EXACT_TASK_PR_REVIEWER_TARGET_ATTESTATION_SCOPE = (
    "one-host-pinned-pr-reviewer-target-only-v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_TARGET_PROVIDER = "github"
PILOT_EXACT_TASK_PR_REVIEWER_TARGET_REPOSITORY = "Ternedal/ModelRig"
PILOT_EXACT_TASK_PR_REVIEWER_TARGET_KIND = "user"

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


class PilotExactTaskPrReviewerTargetAttestationError(ValueError):
    """Reviewer target is not exact, host-pinned, or safely bound."""


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
        raise PilotExactTaskPrReviewerTargetAttestationError(
            "reviewer target artifact is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrReviewerTargetAttestationError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrReviewerTargetAttestationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReviewerTargetAttestationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrReviewerTargetAttestationError(f"{name} is invalid") from exc


def _login(value: Any) -> str:
    if not isinstance(value, str) or _LOGIN.fullmatch(value) is None:
        raise PilotExactTaskPrReviewerTargetAttestationError(
            "reviewer login is invalid"
        )
    return value


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


@dataclass(frozen=True, slots=True)
class PilotExactTaskPrReviewerTargetPolicy:
    policy_epoch: int
    reviewer_login: str
    reviewer_user_id: int
    provider: str = PILOT_EXACT_TASK_PR_REVIEWER_TARGET_PROVIDER
    repository: str = PILOT_EXACT_TASK_PR_REVIEWER_TARGET_REPOSITORY
    reviewer_kind: str = PILOT_EXACT_TASK_PR_REVIEWER_TARGET_KIND
    reviewer_selection_source: str = PILOT_EXACT_TASK_PR_REVIEWER_SELECTION_SOURCE
    exactly_one_reviewer_required: bool = True
    reviewer_identity_observation_required: bool = True
    reviewer_requestability_observation_required: bool = True
    separate_human_reviewer_authorization_required: bool = True
    one_shot_reviewer_request_nonce_required: bool = True
    fresh_pr_state_revalidation_before_reviewer_request_required: bool = True
    reviewer_request_transaction_required: bool = True
    team_reviewers_forbidden: bool = True
    self_review_forbidden: bool = True
    label_mutation_separate_authority_required: bool = True
    merge_separate_authority_required: bool = True
    schema: str = PILOT_EXACT_TASK_PR_REVIEWER_TARGET_POLICY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PR_REVIEWER_TARGET_POLICY_SCHEMA:
            raise PilotExactTaskPrReviewerTargetAttestationError(
                "reviewer target policy schema is unsupported"
            )
        if (
            isinstance(self.policy_epoch, bool)
            or not isinstance(self.policy_epoch, int)
            or self.policy_epoch < 1
            or isinstance(self.reviewer_user_id, bool)
            or not isinstance(self.reviewer_user_id, int)
            or self.reviewer_user_id < 1
        ):
            raise PilotExactTaskPrReviewerTargetAttestationError(
                "reviewer target policy epoch/user id is invalid"
            )
        _login(self.reviewer_login)
        fixed = {
            "provider": PILOT_EXACT_TASK_PR_REVIEWER_TARGET_PROVIDER,
            "repository": PILOT_EXACT_TASK_PR_REVIEWER_TARGET_REPOSITORY,
            "reviewer_kind": PILOT_EXACT_TASK_PR_REVIEWER_TARGET_KIND,
            "reviewer_selection_source": PILOT_EXACT_TASK_PR_REVIEWER_SELECTION_SOURCE,
        }
        if any(getattr(self, name) != expected for name, expected in fixed.items()):
            raise PilotExactTaskPrReviewerTargetAttestationError(
                "reviewer target policy is outside the fixed provider/repository domain"
            )
        required_true = (
            "exactly_one_reviewer_required",
            "reviewer_identity_observation_required",
            "reviewer_requestability_observation_required",
            "separate_human_reviewer_authorization_required",
            "one_shot_reviewer_request_nonce_required",
            "fresh_pr_state_revalidation_before_reviewer_request_required",
            "reviewer_request_transaction_required",
            "team_reviewers_forbidden",
            "self_review_forbidden",
            "label_mutation_separate_authority_required",
            "merge_separate_authority_required",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrReviewerTargetAttestationError(
                "reviewer target policy weakens required controls"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrReviewerTargetPolicy":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReviewerTargetAttestationError(
                "reviewer target policy must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReviewerTargetAttestationError(
                "reviewer target policy fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _require_live_requirements(
    value: Any,
) -> tuple[PilotExactTaskPrReviewerHandoffRequirements, Any]:
    if type(value) is not PilotExactTaskPrReviewerHandoffRequirements:
        raise PilotExactTaskPrReviewerTargetAttestationError(
            "exact ADR-DC-066 reviewer-handoff requirements are required"
        )
    try:
        replayed = PilotExactTaskPrReviewerHandoffRequirements.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewerTargetAttestationError(
            "ADR-DC-066 requirements replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrReviewerTargetAttestationError(
            "ADR-DC-066 requirements identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_REQUIREMENTS_AUTHORITY
        or value.requirements_authenticated is not True
        or value.post_ready_pr_reverified is not True
        or value.ready_state_verified is not True
        or value.no_requested_reviewers_verified is not True
        or value.reviewer_target_host_policy_required is not True
        or value.separate_human_reviewer_authorization_required is not True
        or value.one_shot_reviewer_request_nonce_required is not True
        or value.fresh_pr_state_revalidation_before_reviewer_request_required is not True
        or value.reviewer_mutation_authorized is not False
        or value.reviewer_request_performed is not False
        or value.label_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.repository != PILOT_EXACT_TASK_PR_REVIEWER_TARGET_REPOSITORY
    ):
        raise PilotExactTaskPrReviewerTargetAttestationError(
            "reviewer target requires one live inert ADR-DC-066 requirements artifact"
        )
    inputs = handoff_boundary._get_live_pr_reviewer_handoff_requirements_inputs(value)
    ready_transaction = None if inputs is None else inputs.get("ready_transaction")
    if (
        ready_transaction is None
        or getattr(ready_transaction, "transaction_authenticated", None) is not True
        or ready_transaction.sha256 != value.ready_transaction_sha256
    ):
        raise PilotExactTaskPrReviewerTargetAttestationError(
            "ADR-DC-066 lost live ADR-DC-065 transaction provenance"
        )
    return value, ready_transaction


_live_records: dict[
    int,
    tuple[
        int,
        str,
        weakref.ReferenceType[Any],
        weakref.ReferenceType[PilotExactTaskPrReviewerHandoffRequirements],
    ],
] = {}


def _mark_pr_reviewer_target_attestation_authenticated(
    attestation: Any,
    requirements: PilotExactTaskPrReviewerHandoffRequirements,
) -> None:
    key = id(attestation)

    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)

    _live_records[key] = (
        os.getpid(),
        attestation.sha256,
        weakref.ref(attestation, cleanup),
        weakref.ref(requirements),
    )


def _get_live_pr_reviewer_target_attestation_inputs(attestation: Any) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(attestation))
    if entry is None:
        return None
    pid, digest, attestation_ref, requirements_ref = entry
    requirements = requirements_ref()
    if (
        pid != os.getpid()
        or attestation_ref() is not attestation
        or requirements is None
        or requirements.requirements_authenticated is not True
        or requirements.sha256 != attestation.reviewer_handoff_requirements_sha256
        or attestation.sha256 != digest
    ):
        return None
    return MappingProxyType({"reviewer_handoff_requirements": requirements})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReviewerTargetAttestation:
    reviewer_handoff_requirements_sha256: str
    ready_transaction_sha256: str
    node_identity_sha256: str
    ready_credential_capability_sha256: str
    ready_state_observation_sha256: str
    ready_for_review_reservation_sha256: str
    review_handoff_requirements_sha256: str
    pr_create_transaction_sha256: str
    predicted_commit_sha: str
    reviewer_handoff_plan_sha256: str
    required_reviewer_authorizer_actor_id: str
    repository: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_html_url: str
    pull_request_node_id_sha256: str
    base_branch: str
    head_branch: str
    ready_updated_at_utc: str
    reviewer_target_policy_sha256: str
    reviewer_target_policy_epoch: int
    reviewer_provider: str
    reviewer_kind: str
    reviewer_login: str
    reviewer_user_id: int
    attested_at_utc: str
    reviewer_target_host_pinned: bool = True
    exactly_one_reviewer_required: bool = True
    reviewer_identity_observation_required: bool = True
    reviewer_requestability_observation_required: bool = True
    separate_human_reviewer_authorization_required: bool = True
    one_shot_reviewer_request_nonce_required: bool = True
    fresh_pr_state_revalidation_before_reviewer_request_required: bool = True
    reviewer_request_transaction_required: bool = True
    team_reviewers_forbidden: bool = True
    self_review_forbidden: bool = True
    label_mutation_separate_authority_required: bool = True
    merge_separate_authority_required: bool = True
    reviewer_mutation_authorized: bool = False
    reviewer_request_performed: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_REVIEWER_TARGET_ATTESTATION_AUTHORITY
    attestation_scope: str = PILOT_EXACT_TASK_PR_REVIEWER_TARGET_ATTESTATION_SCOPE
    schema: str = PILOT_EXACT_TASK_PR_REVIEWER_TARGET_ATTESTATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_REVIEWER_TARGET_ATTESTATION_SCHEMA
            or self.authority != PILOT_EXACT_TASK_PR_REVIEWER_TARGET_ATTESTATION_AUTHORITY
            or self.attestation_scope != PILOT_EXACT_TASK_PR_REVIEWER_TARGET_ATTESTATION_SCOPE
        ):
            raise PilotExactTaskPrReviewerTargetAttestationError(
                "reviewer target attestation schema/authority/scope is unsupported"
            )
        for name in (
            "reviewer_handoff_requirements_sha256",
            "ready_transaction_sha256",
            "node_identity_sha256",
            "ready_credential_capability_sha256",
            "ready_state_observation_sha256",
            "ready_for_review_reservation_sha256",
            "review_handoff_requirements_sha256",
            "pr_create_transaction_sha256",
            "reviewer_handoff_plan_sha256",
            "reviewer_target_policy_sha256",
            "pull_request_node_id_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _utc(self.ready_updated_at_utc, name="ready_updated_at_utc")
        attested = _utc(self.attested_at_utc, name="attested_at_utc")
        if attested < _utc(self.ready_updated_at_utc, name="ready_updated_at_utc"):
            raise PilotExactTaskPrReviewerTargetAttestationError(
                "reviewer target attestation predates ready PR state"
            )
        _login(self.reviewer_login)
        if (
            isinstance(self.reviewer_target_policy_epoch, bool)
            or not isinstance(self.reviewer_target_policy_epoch, int)
            or self.reviewer_target_policy_epoch < 1
            or isinstance(self.reviewer_user_id, bool)
            or not isinstance(self.reviewer_user_id, int)
            or self.reviewer_user_id < 1
            or self.reviewer_provider != PILOT_EXACT_TASK_PR_REVIEWER_TARGET_PROVIDER
            or self.reviewer_kind != PILOT_EXACT_TASK_PR_REVIEWER_TARGET_KIND
            or self.repository != PILOT_EXACT_TASK_PR_REVIEWER_TARGET_REPOSITORY
            or self.base_branch != "main"
            or self.pull_request_number < 1
        ):
            raise PilotExactTaskPrReviewerTargetAttestationError(
                "reviewer target attestation target binding is invalid"
            )
        required_true = (
            "reviewer_target_host_pinned",
            "exactly_one_reviewer_required",
            "reviewer_identity_observation_required",
            "reviewer_requestability_observation_required",
            "separate_human_reviewer_authorization_required",
            "one_shot_reviewer_request_nonce_required",
            "fresh_pr_state_revalidation_before_reviewer_request_required",
            "reviewer_request_transaction_required",
            "team_reviewers_forbidden",
            "self_review_forbidden",
            "label_mutation_separate_authority_required",
            "merge_separate_authority_required",
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
            raise PilotExactTaskPrReviewerTargetAttestationError(
                "reviewer target attestation safety evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReviewerTargetAttestationError(
                "reviewer target attestation cannot grant mutation authority"
            )

    @property
    def attestation_authenticated(self) -> bool:
        return _get_live_pr_reviewer_target_attestation_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrReviewerTargetAttestation":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReviewerTargetAttestationError(
                "reviewer target attestation must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReviewerTargetAttestationError(
                "reviewer target attestation fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _attest_verified_pilot_exact_task_pr_reviewer_target(
    *,
    reviewer_handoff_requirements: PilotExactTaskPrReviewerHandoffRequirements,
    reviewer_target_policy: PilotExactTaskPrReviewerTargetPolicy,
    now_provider: Callable[[], str],
) -> PilotExactTaskPrReviewerTargetAttestation:
    requirements, _transaction = _require_live_requirements(reviewer_handoff_requirements)
    if type(reviewer_target_policy) is not PilotExactTaskPrReviewerTargetPolicy:
        raise PilotExactTaskPrReviewerTargetAttestationError(
            "exact reviewer target policy type is required"
        )
    policy = PilotExactTaskPrReviewerTargetPolicy.from_mapping(
        reviewer_target_policy.to_dict()
    )
    if policy != reviewer_target_policy or policy.sha256 != reviewer_target_policy.sha256:
        raise PilotExactTaskPrReviewerTargetAttestationError(
            "reviewer target policy identity mismatch"
        )
    attested_at = now_provider()
    _utc(attested_at, name="attested_at_utc")
    result = PilotExactTaskPrReviewerTargetAttestation(
        reviewer_handoff_requirements_sha256=requirements.sha256,
        ready_transaction_sha256=requirements.ready_transaction_sha256,
        node_identity_sha256=requirements.node_identity_sha256,
        ready_credential_capability_sha256=requirements.ready_credential_capability_sha256,
        ready_state_observation_sha256=requirements.ready_state_observation_sha256,
        ready_for_review_reservation_sha256=requirements.ready_for_review_reservation_sha256,
        review_handoff_requirements_sha256=requirements.review_handoff_requirements_sha256,
        pr_create_transaction_sha256=requirements.pr_create_transaction_sha256,
        predicted_commit_sha=requirements.predicted_commit_sha,
        reviewer_handoff_plan_sha256=requirements.reviewer_handoff_plan_sha256,
        required_reviewer_authorizer_actor_id=requirements.required_reviewer_authorizer_actor_id,
        repository=requirements.repository,
        pull_request_number=requirements.pull_request_number,
        pull_request_api_url=requirements.pull_request_api_url,
        pull_request_html_url=requirements.pull_request_html_url,
        pull_request_node_id_sha256=requirements.pull_request_node_id_sha256,
        base_branch=requirements.base_branch,
        head_branch=requirements.head_branch,
        ready_updated_at_utc=requirements.ready_updated_at_utc,
        reviewer_target_policy_sha256=policy.sha256,
        reviewer_target_policy_epoch=policy.policy_epoch,
        reviewer_provider=policy.provider,
        reviewer_kind=policy.reviewer_kind,
        reviewer_login=policy.reviewer_login,
        reviewer_user_id=policy.reviewer_user_id,
        attested_at_utc=attested_at,
    )
    _mark_pr_reviewer_target_attestation_authenticated(result, requirements)
    if result.attestation_authenticated is not True:
        raise PilotExactTaskPrReviewerTargetAttestationError(
            "reviewer target attestation lost live ADR-DC-066 provenance"
        )
    return result


def attest_pilot_exact_task_pr_reviewer_target(
    reviewer_handoff_requirements: PilotExactTaskPrReviewerHandoffRequirements,
) -> PilotExactTaskPrReviewerTargetAttestation:
    raise PilotExactTaskPrReviewerTargetAttestationError(
        "production reviewer-target policy boundary is not installed"
    )
