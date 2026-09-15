"""ADR-DC-060 human-signed authorization for one exact ready-for-review handoff.

The claim binds one live ADR-DC-059 review-handoff requirements artifact and a
new one-shot ready-for-review nonce. Verification proves human intent only; it
does not mutate GitHub and grants no reusable review, label, merge, release,
deploy or production-activation authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence

from .asymmetric_authority import (
    AsymmetricAuthorityError,
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
)
from . import improvement_pilot_exact_task_pr_review_handoff_requirements as handoff_boundary
from .improvement_pilot_exact_task_pr_review_handoff_requirements import (
    PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_REQUIREMENTS_AUTHORITY,
    PilotExactTaskPrReviewHandoffRequirements,
)
from . import improvement_pilot_exact_task_pr_create_transaction as transaction_boundary
from . import improvement_pilot_exact_task_pr_credential_capability as capability_boundary
from . import improvement_pilot_exact_task_pr_state_observation as observation_boundary
from . import improvement_pilot_exact_task_pr_mutation_reservation as reservation_boundary

PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-ready-for-review-human-authorization/v1"
)
PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_PROOF_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-ready-for-review-human-authorization-proof/v1"
)
PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_AUTHORITY = (
    "dc-l16-exact-pr-ready-for-review-human-authorization-claim-only"
)
PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_PROOF_AUTHORITY = (
    "verified-human-dc-l16-exact-pr-ready-for-review-authorization-only"
)
PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_ISSUER_SYSTEM_ID = (
    "kaliv-rsi-dc-l16-exact-pr-ready-for-review-human-authority-v1"
)
PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_INTENT = (
    "authorize-one-exact-draft-pull-request-ready-for-review-handoff"
)
PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_MAX_WINDOW_SECONDS = 10 * 60

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PilotExactTaskPrReadyAuthorizationError(ValueError):
    """Human ready-for-review authorization is malformed, stale or unsafe."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPrReadyAuthorizationError(
            "ready-for-review authorization is not canonical JSON"
        ) from exc


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskPrReadyAuthorizationError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise PilotExactTaskPrReadyAuthorizationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrReadyAuthorizationError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrReadyAuthorizationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReadyAuthorizationError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskPrReadyAuthorizationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _notes(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PilotExactTaskPrReadyAuthorizationError("notes must be an array")
    items = tuple(value)
    if len(items) > 16 or len(items) != len(set(items)):
        raise PilotExactTaskPrReadyAuthorizationError("notes are invalid")
    for item in items:
        if (
            not isinstance(item, str)
            or not item
            or item.strip() != item
            or "\x00" in item
            or len(item.encode("utf-8")) > 2_048
        ):
            raise PilotExactTaskPrReadyAuthorizationError("note is invalid")
    return items


def _require_requirements(value: Any) -> PilotExactTaskPrReviewHandoffRequirements:
    if type(value) is not PilotExactTaskPrReviewHandoffRequirements:
        raise PilotExactTaskPrReadyAuthorizationError(
            "exact ADR-DC-059 review-handoff requirements are required"
        )
    try:
        replayed = PilotExactTaskPrReviewHandoffRequirements.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrReadyAuthorizationError(
            "ADR-DC-059 requirements replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrReadyAuthorizationError("ADR-DC-059 requirements identity mismatch")
    if (
        value.authority != PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_REQUIREMENTS_AUTHORITY
        or value.post_create_pr_reverified is not True
        or value.pull_request_open_verified is not True
        or value.draft_state_verified is not True
        or value.exact_head_sha_verified is not True
        or value.exact_base_verified is not True
        or value.exact_metadata_verified is not True
        or value.ready_for_review_handoff_required is not True
        or value.separate_human_ready_for_review_authorization_required is not True
        or value.one_shot_ready_for_review_nonce_required is not True
        or value.fresh_pr_state_revalidation_before_ready_required is not True
        or value.reviewer_mutation_separate_authority_required is not True
        or value.label_mutation_separate_authority_required is not True
        or value.merge_separate_authority_required is not True
        or value.maintainer_can_modify is not False
        or value.ready_for_review_authorization_consumed is not False
        or value.ready_for_review_authorized is not False
        or value.ready_for_review_performed is not False
        or value.reviewer_mutation_authorized is not False
        or value.label_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskPrReadyAuthorizationError(
            "human ready authorization requires inert exact ADR-DC-059 requirements"
        )
    return value


def _require_live_requirements(value: Any) -> PilotExactTaskPrReviewHandoffRequirements:
    exact = _require_requirements(value)
    if exact.requirements_authenticated is not True:
        raise PilotExactTaskPrReadyAuthorizationError(
            "human ready authorization requires live ADR-DC-058 provenance"
        )
    return exact


def _binding(requirements: PilotExactTaskPrReviewHandoffRequirements) -> dict[str, Any]:
    exact = _require_requirements(requirements)
    return {
        "review_handoff_requirements_sha256": exact.sha256,
        "pr_create_transaction_sha256": exact.pr_create_transaction_sha256,
        "pr_mutation_requirements_sha256": exact.pr_mutation_requirements_sha256,
        "predicted_commit_sha": exact.predicted_commit_sha,
        "pr_plan_sha256": exact.pr_plan_sha256,
        "pr_mutation_nonce_sha256": exact.pr_mutation_nonce_sha256,
        "repository": exact.repository,
        "pull_request_number": exact.pull_request_number,
        "pull_request_api_url": exact.pull_request_api_url,
        "pull_request_html_url": exact.pull_request_html_url,
        "base_branch": exact.base_branch,
        "head_branch": exact.head_branch,
        "review_handoff_plan_sha256": exact.review_handoff_plan_sha256,
        "required_ready_for_review_authorizer_actor_id": exact.required_ready_for_review_authorizer_actor_id,
        "requirements_materialized_at_utc": exact.materialized_at_utc,
    }


def _prior_nonces(requirements: PilotExactTaskPrReviewHandoffRequirements) -> dict[str, str]:
    exact = _require_live_requirements(requirements)
    handoff_inputs = handoff_boundary._get_live_pr_review_handoff_requirements_inputs(exact)
    transaction = None if handoff_inputs is None else handoff_inputs.get("pr_create_transaction")
    tx_inputs = None if transaction is None else transaction_boundary._get_live_pr_create_transaction_inputs(transaction)
    capability = None if tx_inputs is None else tx_inputs.get("pr_credential_capability")
    cap_inputs = None if capability is None else capability_boundary._get_live_pr_credential_capability_inputs(capability)
    observation = None if cap_inputs is None else cap_inputs.get("pr_state_observation")
    obs_inputs = None if observation is None else observation_boundary._get_live_pr_state_observation_inputs(observation)
    reservation = None if obs_inputs is None else obs_inputs.get("pr_mutation_reservation")
    reservation_inputs = None if reservation is None else reservation_boundary._get_live_pr_mutation_reservation_inputs(reservation)
    pr_requirements = None if reservation_inputs is None else reservation_inputs.get("pr_mutation_requirements")
    if (
        transaction is None
        or getattr(transaction, "transaction_authenticated", None) is not True
        or getattr(transaction, "sha256", None) != exact.pr_create_transaction_sha256
        or reservation is None
        or getattr(reservation, "reservation_authenticated", None) is not True
        or getattr(reservation, "pr_mutation_nonce_sha256", None) != exact.pr_mutation_nonce_sha256
        or pr_requirements is None
        or getattr(pr_requirements, "requirements_authenticated", None) is not True
        or getattr(pr_requirements, "sha256", None) != exact.pr_mutation_requirements_sha256
    ):
        raise PilotExactTaskPrReadyAuthorizationError(
            "ADR-DC-059 lost exact prior nonce provenance"
        )
    result = {
        "execution_nonce_sha256": pr_requirements.execution_nonce_sha256,
        "local_write_nonce_sha256": pr_requirements.local_write_nonce_sha256,
        "remote_publication_nonce_sha256": pr_requirements.remote_publication_nonce_sha256,
        "pr_mutation_nonce_sha256": exact.pr_mutation_nonce_sha256,
    }
    for name, value in result.items():
        _hex64(value, name=name)
    if len(set(result.values())) != 4:
        raise PilotExactTaskPrReadyAuthorizationError("prior one-shot nonces are not distinct")
    return result


@dataclass(frozen=True, slots=True)
class PilotExactTaskPrReadyAuthorization:
    authorization_id: str
    review_handoff_requirements: PilotExactTaskPrReviewHandoffRequirements
    review_handoff_requirements_sha256: str
    pr_create_transaction_sha256: str
    pr_mutation_requirements_sha256: str
    predicted_commit_sha: str
    pr_plan_sha256: str
    execution_nonce_sha256: str
    local_write_nonce_sha256: str
    remote_publication_nonce_sha256: str
    pr_mutation_nonce_sha256: str
    repository: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_html_url: str
    base_branch: str
    head_branch: str
    review_handoff_plan_sha256: str
    required_ready_for_review_authorizer_actor_id: str
    requirements_materialized_at_utc: str
    ready_for_review_authorizer_actor_id: str
    authorized_at_utc: str
    expires_at_utc: str
    ready_for_review_nonce_sha256: str
    notes: tuple[str, ...]
    human_ready_for_review_intent: str = PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_INTENT
    one_shot_ready_for_review_required: bool = True
    fresh_pr_state_revalidation_before_ready_required: bool = True
    reviewer_mutation_separate_authority_required: bool = True
    label_mutation_separate_authority_required: bool = True
    merge_separate_authority_required: bool = True
    human_ready_for_review_authorization_verified: bool = False
    ready_for_review_authorization_consumed: bool = False
    ready_for_review_authorized: bool = False
    ready_for_review_performed: bool = False
    reviewer_mutation_authorized: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_SCHEMA:
            raise PilotExactTaskPrReadyAuthorizationError("ready authorization schema is unsupported")
        _identifier(self.authorization_id, name="authorization_id")
        requirements = _require_requirements(self.review_handoff_requirements)
        for name in (
            "review_handoff_requirements_sha256",
            "pr_create_transaction_sha256",
            "pr_mutation_requirements_sha256",
            "pr_plan_sha256",
            "execution_nonce_sha256",
            "local_write_nonce_sha256",
            "remote_publication_nonce_sha256",
            "pr_mutation_nonce_sha256",
            "review_handoff_plan_sha256",
            "ready_for_review_nonce_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _actor(self.required_ready_for_review_authorizer_actor_id, name="required_ready_for_review_authorizer_actor_id")
        _actor(self.ready_for_review_authorizer_actor_id, name="ready_for_review_authorizer_actor_id")
        _notes(self.notes)
        mismatch = next((name for name, expected in _binding(requirements).items() if getattr(self, name) != expected), None)
        if mismatch is not None:
            raise PilotExactTaskPrReadyAuthorizationError(f"ready authorization binding mismatch: {mismatch}")
        if self.ready_for_review_authorizer_actor_id != self.required_ready_for_review_authorizer_actor_id:
            raise PilotExactTaskPrReadyAuthorizationError(
                "ready-for-review must be authorized by the required human actor"
            )
        if len({
            self.execution_nonce_sha256,
            self.local_write_nonce_sha256,
            self.remote_publication_nonce_sha256,
            self.pr_mutation_nonce_sha256,
            self.ready_for_review_nonce_sha256,
        }) != 5:
            raise PilotExactTaskPrReadyAuthorizationError(
                "ready-for-review nonce must be distinct from every prior one-shot nonce"
            )
        authorized = _utc(self.authorized_at_utc, name="authorized_at_utc")
        expires = _utc(self.expires_at_utc, name="expires_at_utc")
        materialized = _utc(self.requirements_materialized_at_utc, name="requirements_materialized_at_utc")
        if authorized < materialized or expires <= authorized:
            raise PilotExactTaskPrReadyAuthorizationError("ready authorization time window is invalid")
        if expires - authorized > timedelta(seconds=PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_MAX_WINDOW_SECONDS):
            raise PilotExactTaskPrReadyAuthorizationError("ready authorization window exceeds maximum")
        if self.human_ready_for_review_intent != PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_INTENT:
            raise PilotExactTaskPrReadyAuthorizationError("ready authorization intent is unsupported")
        required_true = (
            "one_shot_ready_for_review_required",
            "fresh_pr_state_revalidation_before_ready_required",
            "reviewer_mutation_separate_authority_required",
            "label_mutation_separate_authority_required",
            "merge_separate_authority_required",
        )
        forced_false = (
            "human_ready_for_review_authorization_verified",
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
            raise PilotExactTaskPrReadyAuthorizationError("ready authorization safety requirements are incomplete")
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReadyAuthorizationError("ready authorization claim cannot grant mutation authority")
        if self.authority != PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_AUTHORITY:
            raise PilotExactTaskPrReadyAuthorizationError("ready authorization authority is unsupported")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        result = {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]
        result["review_handoff_requirements"] = self.review_handoff_requirements.to_dict()
        result["notes"] = list(self.notes)
        return result

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrReadyAuthorization":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReadyAuthorizationError("ready authorization must be an object")
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReadyAuthorizationError("ready authorization fields mismatch")
        data = dict(value)
        if not isinstance(data["review_handoff_requirements"], Mapping):
            raise PilotExactTaskPrReadyAuthorizationError("review-handoff requirements must be an object")
        if not isinstance(data["notes"], list):
            raise PilotExactTaskPrReadyAuthorizationError("notes must be an array")
        data["review_handoff_requirements"] = PilotExactTaskPrReviewHandoffRequirements.from_mapping(
            data["review_handoff_requirements"]
        )
        data["notes"] = tuple(data["notes"])
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


@dataclass(frozen=True, slots=True)
class PilotExactTaskPrReadyAuthorizationProof:
    authorization_sha256: str
    signature_sha256: str
    key_id: str
    issuer_actor_id: str
    issuer_system_id: str
    authorization: PilotExactTaskPrReadyAuthorization
    review_handoff_requirements_sha256: str
    pr_create_transaction_sha256: str
    predicted_commit_sha: str
    review_handoff_plan_sha256: str
    ready_for_review_nonce_sha256: str
    verified_at_utc: str
    one_shot_ready_for_review_required: bool = True
    fresh_pr_state_revalidation_before_ready_required: bool = True
    reviewer_mutation_separate_authority_required: bool = True
    label_mutation_separate_authority_required: bool = True
    merge_separate_authority_required: bool = True
    human_ready_for_review_authorization_verified: bool = True
    ready_for_review_authorization_consumed: bool = False
    ready_for_review_authorized: bool = False
    ready_for_review_performed: bool = False
    reviewer_mutation_authorized: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_PROOF_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_PROOF_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_PROOF_SCHEMA:
            raise PilotExactTaskPrReadyAuthorizationError("ready authorization proof schema is unsupported")
        for name in (
            "authorization_sha256",
            "signature_sha256",
            "review_handoff_requirements_sha256",
            "pr_create_transaction_sha256",
            "review_handoff_plan_sha256",
            "ready_for_review_nonce_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _identifier(self.key_id, name="key_id")
        _actor(self.issuer_actor_id, name="issuer_actor_id")
        _identifier(self.issuer_system_id, name="issuer_system_id")
        if self.issuer_system_id != PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_ISSUER_SYSTEM_ID:
            raise PilotExactTaskPrReadyAuthorizationError("ready authorization proof issuer system is invalid")
        if type(self.authorization) is not PilotExactTaskPrReadyAuthorization:
            raise PilotExactTaskPrReadyAuthorizationError("exact ready authorization is required")
        replayed = PilotExactTaskPrReadyAuthorization.from_mapping(self.authorization.to_dict())
        if replayed != self.authorization or self.authorization_sha256 != self.authorization.sha256:
            raise PilotExactTaskPrReadyAuthorizationError("ready authorization proof identity mismatch")
        if (
            self.issuer_actor_id != self.authorization.ready_for_review_authorizer_actor_id
            or self.review_handoff_requirements_sha256 != self.authorization.review_handoff_requirements_sha256
            or self.pr_create_transaction_sha256 != self.authorization.pr_create_transaction_sha256
            or self.predicted_commit_sha != self.authorization.predicted_commit_sha
            or self.review_handoff_plan_sha256 != self.authorization.review_handoff_plan_sha256
            or self.ready_for_review_nonce_sha256 != self.authorization.ready_for_review_nonce_sha256
        ):
            raise PilotExactTaskPrReadyAuthorizationError("ready authorization proof binding mismatch")
        verified = _utc(self.verified_at_utc, name="verified_at_utc")
        authorized = _utc(self.authorization.authorized_at_utc, name="authorized_at_utc")
        expires = _utc(self.authorization.expires_at_utc, name="expires_at_utc")
        if verified < authorized or verified > expires:
            raise PilotExactTaskPrReadyAuthorizationError("ready authorization proof verified outside its window")
        required_true = (
            "one_shot_ready_for_review_required",
            "fresh_pr_state_revalidation_before_ready_required",
            "reviewer_mutation_separate_authority_required",
            "label_mutation_separate_authority_required",
            "merge_separate_authority_required",
            "human_ready_for_review_authorization_verified",
        )
        forced_false = (
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
            raise PilotExactTaskPrReadyAuthorizationError("ready authorization proof evidence is incomplete")
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReadyAuthorizationError("ready authorization proof cannot grant mutation authority")
        if self.authority != PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_PROOF_AUTHORITY:
            raise PilotExactTaskPrReadyAuthorizationError("ready authorization proof authority is unsupported")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        result = {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]
        result["authorization"] = self.authorization.to_dict()
        return result

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrReadyAuthorizationProof":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReadyAuthorizationError("ready authorization proof must be an object")
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReadyAuthorizationError("ready authorization proof fields mismatch")
        data = dict(value)
        if not isinstance(data["authorization"], Mapping):
            raise PilotExactTaskPrReadyAuthorizationError("ready authorization must be an object")
        data["authorization"] = PilotExactTaskPrReadyAuthorization.from_mapping(data["authorization"])
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def build_pilot_exact_task_pr_ready_authorization(
    *,
    review_handoff_requirements: PilotExactTaskPrReviewHandoffRequirements,
    authorization_id: str,
    ready_for_review_authorizer_actor_id: str,
    authorized_at_utc: str,
    expires_at_utc: str,
    ready_for_review_nonce_sha256: str,
    notes: Sequence[str] = (),
) -> PilotExactTaskPrReadyAuthorization:
    requirements = _require_live_requirements(review_handoff_requirements)
    prior = _prior_nonces(requirements)
    return PilotExactTaskPrReadyAuthorization(
        authorization_id=authorization_id,
        review_handoff_requirements=requirements,
        ready_for_review_authorizer_actor_id=ready_for_review_authorizer_actor_id,
        authorized_at_utc=authorized_at_utc,
        expires_at_utc=expires_at_utc,
        ready_for_review_nonce_sha256=ready_for_review_nonce_sha256,
        notes=_notes(notes),
        execution_nonce_sha256=prior["execution_nonce_sha256"],
        local_write_nonce_sha256=prior["local_write_nonce_sha256"],
        remote_publication_nonce_sha256=prior["remote_publication_nonce_sha256"],
        **_binding(requirements),
    )


def _verify_pilot_exact_task_pr_ready_authorization(
    *,
    review_handoff_requirements: PilotExactTaskPrReviewHandoffRequirements,
    authorization: PilotExactTaskPrReadyAuthorization,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_provider: Callable[[], str],
) -> PilotExactTaskPrReadyAuthorizationProof:
    requirements = _require_live_requirements(review_handoff_requirements)
    if type(authorization) is not PilotExactTaskPrReadyAuthorization:
        raise PilotExactTaskPrReadyAuthorizationError("exact ready authorization is required")
    replayed = PilotExactTaskPrReadyAuthorization.from_mapping(authorization.to_dict())
    if replayed != authorization or replayed.sha256 != authorization.sha256:
        raise PilotExactTaskPrReadyAuthorizationError("ready authorization replay identity mismatch")
    if (
        authorization.review_handoff_requirements is not requirements
        or authorization.review_handoff_requirements_sha256 != requirements.sha256
    ):
        raise PilotExactTaskPrReadyAuthorizationError(
            "ready authorization is not bound to supplied live requirements"
        )
    for name, expected in _prior_nonces(requirements).items():
        if getattr(authorization, name) != expected:
            raise PilotExactTaskPrReadyAuthorizationError(
                f"ready authorization prior nonce binding mismatch: {name}"
            )
    if not isinstance(signature, DetachedEd25519AuthoritySignature):
        raise PilotExactTaskPrReadyAuthorizationError("detached Ed25519 signature is required")
    if not isinstance(verifier, Ed25519AuthorityVerifier):
        raise PilotExactTaskPrReadyAuthorizationError("Ed25519 verifier is required")
    if signature.issuer_system_id != PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_ISSUER_SYSTEM_ID:
        raise PilotExactTaskPrReadyAuthorizationError("ready signature belongs to another issuer system")
    if signature.issuer_actor_id != authorization.ready_for_review_authorizer_actor_id:
        raise PilotExactTaskPrReadyAuthorizationError("ready signature actor mismatch")
    if signature.signed_at_utc != authorization.authorized_at_utc:
        raise PilotExactTaskPrReadyAuthorizationError("ready signature time mismatch")
    verified_at = now_provider()
    verified = _utc(verified_at, name="verified_at_utc")
    authorized = _utc(authorization.authorized_at_utc, name="authorized_at_utc")
    expires = _utc(authorization.expires_at_utc, name="expires_at_utc")
    if verified < authorized or verified > expires:
        raise PilotExactTaskPrReadyAuthorizationError("ready authorization is not currently valid")
    try:
        payload_sha = verifier.verify(
            payload=authorization.canonical_json().encode("utf-8"),
            signature=signature,
            at_utc=verified_at,
        )
    except AsymmetricAuthorityError as exc:
        raise PilotExactTaskPrReadyAuthorizationError(
            "human ready-for-review signature verification failed"
        ) from exc
    if payload_sha != authorization.sha256:
        raise PilotExactTaskPrReadyAuthorizationError("verified ready authorization payload hash mismatch")
    return PilotExactTaskPrReadyAuthorizationProof(
        authorization_sha256=authorization.sha256,
        signature_sha256=signature.sha256,
        key_id=signature.key_id,
        issuer_actor_id=signature.issuer_actor_id,
        issuer_system_id=signature.issuer_system_id,
        authorization=authorization,
        review_handoff_requirements_sha256=requirements.sha256,
        pr_create_transaction_sha256=requirements.pr_create_transaction_sha256,
        predicted_commit_sha=requirements.predicted_commit_sha,
        review_handoff_plan_sha256=requirements.review_handoff_plan_sha256,
        ready_for_review_nonce_sha256=authorization.ready_for_review_nonce_sha256,
        verified_at_utc=verified_at,
    )


def verify_pilot_exact_task_pr_ready_authorization(
    *,
    review_handoff_requirements: PilotExactTaskPrReviewHandoffRequirements,
    authorization: PilotExactTaskPrReadyAuthorization,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier | None = None,
) -> PilotExactTaskPrReadyAuthorizationProof:
    raise PilotExactTaskPrReadyAuthorizationError(
        "production ready-for-review verification boundary is not installed"
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_SCHEMA",
    "PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_PROOF_SCHEMA",
    "PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_PROOF_AUTHORITY",
    "PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_ISSUER_SYSTEM_ID",
    "PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_INTENT",
    "PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_MAX_WINDOW_SECONDS",
    "PilotExactTaskPrReadyAuthorizationError",
    "PilotExactTaskPrReadyAuthorization",
    "PilotExactTaskPrReadyAuthorizationProof",
    "build_pilot_exact_task_pr_ready_authorization",
    "verify_pilot_exact_task_pr_ready_authorization",
]
