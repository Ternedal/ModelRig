"""ADR-DC-068 human-signed authorization for one exact reviewer request.

The claim binds one live ADR-DC-067 host-pinned reviewer target and a new
one-shot reviewer-request nonce. Verification proves human intent only. It does
not request a reviewer and grants no reusable reviewer, label, merge, release,
deploy or production authority.
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
from . import improvement_pilot_exact_task_pr_reviewer_target_attestation as target_boundary
from .improvement_pilot_exact_task_pr_reviewer_target_attestation import (
    PILOT_EXACT_TASK_PR_REVIEWER_TARGET_ATTESTATION_AUTHORITY,
    PilotExactTaskPrReviewerTargetAttestation,
)
from . import improvement_pilot_exact_task_pr_reviewer_handoff_requirements as reviewer_handoff_boundary
from . import improvement_pilot_exact_task_pr_ready_for_review_transaction as ready_transaction_boundary
from . import improvement_pilot_exact_task_pr_ready_for_review_node_identity as node_boundary
from . import improvement_pilot_exact_task_pr_ready_for_review_credential_capability as capability_boundary
from . import improvement_pilot_exact_task_pr_ready_for_review_state_observation as state_boundary
from . import improvement_pilot_exact_task_pr_ready_for_review_authorization as ready_auth_boundary

PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-reviewer-request-human-authorization/v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_PROOF_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-reviewer-request-human-authorization-proof/v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_AUTHORITY = (
    "dc-l16-exact-pr-reviewer-request-human-authorization-claim-only"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_PROOF_AUTHORITY = (
    "verified-human-dc-l16-exact-pr-reviewer-request-authorization-only"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_ISSUER_SYSTEM_ID = (
    "kaliv-rsi-dc-l16-exact-pr-reviewer-request-human-authority-v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_INTENT = (
    "authorize-one-exact-pull-request-reviewer-request"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_MAX_WINDOW_SECONDS = 10 * 60

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


class PilotExactTaskPrReviewerRequestAuthorizationError(ValueError):
    """Human reviewer-request authorization is malformed, stale, or unsafe."""


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
        raise PilotExactTaskPrReviewerRequestAuthorizationError(
            "reviewer-request authorization is not canonical JSON"
        ) from exc


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskPrReviewerRequestAuthorizationError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise PilotExactTaskPrReviewerRequestAuthorizationError(f"{name} is invalid")
    return value


def _login(value: Any) -> str:
    if not isinstance(value, str) or _LOGIN.fullmatch(value) is None:
        raise PilotExactTaskPrReviewerRequestAuthorizationError("reviewer login is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrReviewerRequestAuthorizationError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrReviewerRequestAuthorizationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReviewerRequestAuthorizationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrReviewerRequestAuthorizationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _notes(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PilotExactTaskPrReviewerRequestAuthorizationError("notes must be an array")
    items = tuple(value)
    if len(items) > 16 or len(items) != len(set(items)):
        raise PilotExactTaskPrReviewerRequestAuthorizationError("notes are invalid")
    for item in items:
        if (
            not isinstance(item, str)
            or not item
            or item.strip() != item
            or "\x00" in item
            or len(item.encode("utf-8")) > 2_048
        ):
            raise PilotExactTaskPrReviewerRequestAuthorizationError("note is invalid")
    return items


def _require_attestation(value: Any) -> PilotExactTaskPrReviewerTargetAttestation:
    if type(value) is not PilotExactTaskPrReviewerTargetAttestation:
        raise PilotExactTaskPrReviewerRequestAuthorizationError(
            "exact ADR-DC-067 reviewer-target attestation is required"
        )
    try:
        replayed = PilotExactTaskPrReviewerTargetAttestation.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrReviewerRequestAuthorizationError(
            "ADR-DC-067 attestation replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrReviewerRequestAuthorizationError(
            "ADR-DC-067 attestation identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_PR_REVIEWER_TARGET_ATTESTATION_AUTHORITY
        or value.reviewer_target_host_pinned is not True
        or value.exactly_one_reviewer_required is not True
        or value.reviewer_identity_observation_required is not True
        or value.reviewer_requestability_observation_required is not True
        or value.separate_human_reviewer_authorization_required is not True
        or value.one_shot_reviewer_request_nonce_required is not True
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
        raise PilotExactTaskPrReviewerRequestAuthorizationError(
            "human reviewer authority requires one inert ADR-DC-067 target"
        )
    return value


def _require_live_attestation(value: Any) -> PilotExactTaskPrReviewerTargetAttestation:
    exact = _require_attestation(value)
    if exact.attestation_authenticated is not True:
        raise PilotExactTaskPrReviewerRequestAuthorizationError(
            "human reviewer authority requires live ADR-DC-066 provenance"
        )
    return exact


def _binding(attestation: PilotExactTaskPrReviewerTargetAttestation) -> dict[str, Any]:
    exact = _require_attestation(attestation)
    return {
        "reviewer_target_attestation_sha256": exact.sha256,
        "reviewer_handoff_requirements_sha256": exact.reviewer_handoff_requirements_sha256,
        "ready_transaction_sha256": exact.ready_transaction_sha256,
        "predicted_commit_sha": exact.predicted_commit_sha,
        "reviewer_handoff_plan_sha256": exact.reviewer_handoff_plan_sha256,
        "repository": exact.repository,
        "pull_request_number": exact.pull_request_number,
        "pull_request_api_url": exact.pull_request_api_url,
        "pull_request_html_url": exact.pull_request_html_url,
        "pull_request_node_id_sha256": exact.pull_request_node_id_sha256,
        "base_branch": exact.base_branch,
        "head_branch": exact.head_branch,
        "reviewer_target_policy_sha256": exact.reviewer_target_policy_sha256,
        "reviewer_target_policy_epoch": exact.reviewer_target_policy_epoch,
        "reviewer_login": exact.reviewer_login,
        "reviewer_user_id": exact.reviewer_user_id,
        "required_reviewer_authorizer_actor_id": exact.required_reviewer_authorizer_actor_id,
        "target_attested_at_utc": exact.attested_at_utc,
    }


def _prior_nonces(attestation: PilotExactTaskPrReviewerTargetAttestation) -> dict[str, str]:
    exact = _require_live_attestation(attestation)
    target_inputs = target_boundary._get_live_pr_reviewer_target_attestation_inputs(exact)
    reviewer_requirements = None if target_inputs is None else target_inputs.get(
        "reviewer_handoff_requirements"
    )
    handoff_inputs = None if reviewer_requirements is None else reviewer_handoff_boundary._get_live_pr_reviewer_handoff_requirements_inputs(
        reviewer_requirements
    )
    ready_transaction = None if handoff_inputs is None else handoff_inputs.get("ready_transaction")
    tx_inputs = None if ready_transaction is None else ready_transaction_boundary._get_live_pr_ready_transaction_inputs(
        ready_transaction
    )
    identity = None if tx_inputs is None else tx_inputs.get("ready_node_identity")
    identity_inputs = None if identity is None else node_boundary._get_live_pr_ready_node_identity_inputs(identity)
    capability = None if identity_inputs is None else identity_inputs.get("ready_credential_capability")
    cap_inputs = None if capability is None else capability_boundary._get_live_pr_ready_credential_capability_inputs(capability)
    observation = None if cap_inputs is None else cap_inputs.get("ready_state_observation")
    state_inputs = None if observation is None else state_boundary._get_live_pr_ready_state_observation_inputs(observation)
    review_requirements = None if state_inputs is None else state_inputs.get("review_handoff_requirements")
    if (
        reviewer_requirements is None
        or getattr(reviewer_requirements, "requirements_authenticated", None) is not True
        or reviewer_requirements.sha256 != exact.reviewer_handoff_requirements_sha256
        or ready_transaction is None
        or getattr(ready_transaction, "transaction_authenticated", None) is not True
        or ready_transaction.sha256 != exact.ready_transaction_sha256
        or review_requirements is None
        or getattr(review_requirements, "requirements_authenticated", None) is not True
    ):
        raise PilotExactTaskPrReviewerRequestAuthorizationError(
            "ADR-DC-067 lost exact prior nonce provenance"
        )
    prior = ready_auth_boundary._prior_nonces(review_requirements)
    result = dict(prior)
    result["ready_for_review_nonce_sha256"] = reviewer_requirements.ready_for_review_nonce_sha256
    for name, value in result.items():
        _hex64(value, name=name)
    if len(result) != 5 or len(set(result.values())) != 5:
        raise PilotExactTaskPrReviewerRequestAuthorizationError(
            "prior one-shot nonces are not distinct"
        )
    return result


@dataclass(frozen=True, slots=True)
class PilotExactTaskPrReviewerRequestAuthorization:
    authorization_id: str
    reviewer_target_attestation: PilotExactTaskPrReviewerTargetAttestation
    reviewer_target_attestation_sha256: str
    reviewer_handoff_requirements_sha256: str
    ready_transaction_sha256: str
    predicted_commit_sha: str
    reviewer_handoff_plan_sha256: str
    execution_nonce_sha256: str
    local_write_nonce_sha256: str
    remote_publication_nonce_sha256: str
    pr_mutation_nonce_sha256: str
    ready_for_review_nonce_sha256: str
    repository: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_html_url: str
    pull_request_node_id_sha256: str
    base_branch: str
    head_branch: str
    reviewer_target_policy_sha256: str
    reviewer_target_policy_epoch: int
    reviewer_login: str
    reviewer_user_id: int
    required_reviewer_authorizer_actor_id: str
    target_attested_at_utc: str
    reviewer_request_authorizer_actor_id: str
    authorized_at_utc: str
    expires_at_utc: str
    reviewer_request_nonce_sha256: str
    notes: tuple[str, ...]
    human_reviewer_request_intent: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_INTENT
    one_shot_reviewer_request_required: bool = True
    reviewer_identity_observation_required: bool = True
    reviewer_requestability_observation_required: bool = True
    fresh_pr_state_revalidation_before_reviewer_request_required: bool = True
    reviewer_request_transaction_required: bool = True
    team_reviewers_forbidden: bool = True
    self_review_forbidden: bool = True
    label_mutation_separate_authority_required: bool = True
    merge_separate_authority_required: bool = True
    human_reviewer_request_authorization_verified: bool = False
    reviewer_request_authorization_consumed: bool = False
    reviewer_mutation_authorized: bool = False
    reviewer_request_performed: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_SCHEMA:
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer-request authorization schema is unsupported"
            )
        _identifier(self.authorization_id, name="authorization_id")
        attestation = _require_attestation(self.reviewer_target_attestation)
        for name in (
            "reviewer_target_attestation_sha256",
            "reviewer_handoff_requirements_sha256",
            "ready_transaction_sha256",
            "reviewer_handoff_plan_sha256",
            "execution_nonce_sha256",
            "local_write_nonce_sha256",
            "remote_publication_nonce_sha256",
            "pr_mutation_nonce_sha256",
            "ready_for_review_nonce_sha256",
            "pull_request_node_id_sha256",
            "reviewer_target_policy_sha256",
            "reviewer_request_nonce_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _login(self.reviewer_login)
        _actor(self.required_reviewer_authorizer_actor_id, name="required_reviewer_authorizer_actor_id")
        _actor(self.reviewer_request_authorizer_actor_id, name="reviewer_request_authorizer_actor_id")
        _notes(self.notes)
        mismatch = next(
            (name for name, expected in _binding(attestation).items() if getattr(self, name) != expected),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                f"reviewer-request authorization binding mismatch: {mismatch}"
            )
        if self.reviewer_request_authorizer_actor_id != self.required_reviewer_authorizer_actor_id:
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer request must be authorized by the required human actor"
            )
        if (
            isinstance(self.reviewer_user_id, bool)
            or not isinstance(self.reviewer_user_id, int)
            or self.reviewer_user_id < 1
            or isinstance(self.reviewer_target_policy_epoch, bool)
            or not isinstance(self.reviewer_target_policy_epoch, int)
            or self.reviewer_target_policy_epoch < 1
        ):
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer target identity is invalid"
            )
        if len({
            self.execution_nonce_sha256,
            self.local_write_nonce_sha256,
            self.remote_publication_nonce_sha256,
            self.pr_mutation_nonce_sha256,
            self.ready_for_review_nonce_sha256,
            self.reviewer_request_nonce_sha256,
        }) != 6:
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer-request nonce must be distinct from every prior one-shot nonce"
            )
        authorized = _utc(self.authorized_at_utc, name="authorized_at_utc")
        expires = _utc(self.expires_at_utc, name="expires_at_utc")
        target_at = _utc(self.target_attested_at_utc, name="target_attested_at_utc")
        if authorized < target_at or expires <= authorized:
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer-request authorization time window is invalid"
            )
        if expires - authorized > timedelta(
            seconds=PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_MAX_WINDOW_SECONDS
        ):
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer-request authorization window exceeds maximum"
            )
        if self.human_reviewer_request_intent != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_INTENT:
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer-request authorization intent is unsupported"
            )
        required_true = (
            "one_shot_reviewer_request_required",
            "reviewer_identity_observation_required",
            "reviewer_requestability_observation_required",
            "fresh_pr_state_revalidation_before_reviewer_request_required",
            "reviewer_request_transaction_required",
            "team_reviewers_forbidden",
            "self_review_forbidden",
            "label_mutation_separate_authority_required",
            "merge_separate_authority_required",
        )
        forced_false = (
            "human_reviewer_request_authorization_verified",
            "reviewer_request_authorization_consumed",
            "reviewer_mutation_authorized",
            "reviewer_request_performed",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer-request authorization safety requirements are incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer-request authorization claim cannot grant mutation authority"
            )
        if self.authority != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_AUTHORITY:
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer-request authorization authority is unsupported"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        result = {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]
        result["reviewer_target_attestation"] = self.reviewer_target_attestation.to_dict()
        result["notes"] = list(self.notes)
        return result

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrReviewerRequestAuthorization":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer-request authorization must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer-request authorization fields mismatch"
            )
        data = dict(value)
        if not isinstance(data["reviewer_target_attestation"], Mapping):
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer-target attestation must be an object"
            )
        if not isinstance(data["notes"], list):
            raise PilotExactTaskPrReviewerRequestAuthorizationError("notes must be an array")
        data["reviewer_target_attestation"] = PilotExactTaskPrReviewerTargetAttestation.from_mapping(
            data["reviewer_target_attestation"]
        )
        data["notes"] = tuple(data["notes"])
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


@dataclass(frozen=True, slots=True)
class PilotExactTaskPrReviewerRequestAuthorizationProof:
    authorization_sha256: str
    signature_sha256: str
    key_id: str
    issuer_actor_id: str
    issuer_system_id: str
    authorization: PilotExactTaskPrReviewerRequestAuthorization
    reviewer_target_attestation_sha256: str
    reviewer_handoff_requirements_sha256: str
    ready_transaction_sha256: str
    predicted_commit_sha: str
    reviewer_handoff_plan_sha256: str
    reviewer_target_policy_sha256: str
    reviewer_login: str
    reviewer_user_id: int
    reviewer_request_nonce_sha256: str
    verified_at_utc: str
    one_shot_reviewer_request_required: bool = True
    reviewer_identity_observation_required: bool = True
    reviewer_requestability_observation_required: bool = True
    fresh_pr_state_revalidation_before_reviewer_request_required: bool = True
    reviewer_request_transaction_required: bool = True
    team_reviewers_forbidden: bool = True
    self_review_forbidden: bool = True
    label_mutation_separate_authority_required: bool = True
    merge_separate_authority_required: bool = True
    human_reviewer_request_authorization_verified: bool = True
    reviewer_request_authorization_consumed: bool = False
    reviewer_mutation_authorized: bool = False
    reviewer_request_performed: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_PROOF_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_PROOF_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_PROOF_SCHEMA:
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer-request authorization proof schema is unsupported"
            )
        for name in (
            "authorization_sha256",
            "signature_sha256",
            "reviewer_target_attestation_sha256",
            "reviewer_handoff_requirements_sha256",
            "ready_transaction_sha256",
            "reviewer_handoff_plan_sha256",
            "reviewer_target_policy_sha256",
            "reviewer_request_nonce_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _identifier(self.key_id, name="key_id")
        _actor(self.issuer_actor_id, name="issuer_actor_id")
        _identifier(self.issuer_system_id, name="issuer_system_id")
        _login(self.reviewer_login)
        if self.issuer_system_id != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_ISSUER_SYSTEM_ID:
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer-request proof issuer system is invalid"
            )
        if type(self.authorization) is not PilotExactTaskPrReviewerRequestAuthorization:
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "exact reviewer-request authorization is required"
            )
        replayed = PilotExactTaskPrReviewerRequestAuthorization.from_mapping(
            self.authorization.to_dict()
        )
        if replayed != self.authorization or self.authorization_sha256 != self.authorization.sha256:
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer-request authorization proof identity mismatch"
            )
        if (
            self.issuer_actor_id != self.authorization.reviewer_request_authorizer_actor_id
            or self.reviewer_target_attestation_sha256 != self.authorization.reviewer_target_attestation_sha256
            or self.reviewer_handoff_requirements_sha256 != self.authorization.reviewer_handoff_requirements_sha256
            or self.ready_transaction_sha256 != self.authorization.ready_transaction_sha256
            or self.predicted_commit_sha != self.authorization.predicted_commit_sha
            or self.reviewer_handoff_plan_sha256 != self.authorization.reviewer_handoff_plan_sha256
            or self.reviewer_target_policy_sha256 != self.authorization.reviewer_target_policy_sha256
            or self.reviewer_login != self.authorization.reviewer_login
            or self.reviewer_user_id != self.authorization.reviewer_user_id
            or self.reviewer_request_nonce_sha256 != self.authorization.reviewer_request_nonce_sha256
        ):
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer-request authorization proof binding mismatch"
            )
        verified = _utc(self.verified_at_utc, name="verified_at_utc")
        authorized = _utc(self.authorization.authorized_at_utc, name="authorized_at_utc")
        expires = _utc(self.authorization.expires_at_utc, name="expires_at_utc")
        if verified < authorized or verified > expires:
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer-request proof verified outside its window"
            )
        required_true = (
            "one_shot_reviewer_request_required",
            "reviewer_identity_observation_required",
            "reviewer_requestability_observation_required",
            "fresh_pr_state_revalidation_before_reviewer_request_required",
            "reviewer_request_transaction_required",
            "team_reviewers_forbidden",
            "self_review_forbidden",
            "label_mutation_separate_authority_required",
            "merge_separate_authority_required",
            "human_reviewer_request_authorization_verified",
        )
        forced_false = (
            "reviewer_request_authorization_consumed",
            "reviewer_mutation_authorized",
            "reviewer_request_performed",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer-request proof evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer-request proof cannot grant mutation authority"
            )
        if self.authority != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_PROOF_AUTHORITY:
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer-request proof authority is unsupported"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        result = {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]
        result["authorization"] = self.authorization.to_dict()
        return result

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrReviewerRequestAuthorizationProof":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer-request authorization proof must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer-request authorization proof fields mismatch"
            )
        data = dict(value)
        if not isinstance(data["authorization"], Mapping):
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                "reviewer-request authorization must be an object"
            )
        data["authorization"] = PilotExactTaskPrReviewerRequestAuthorization.from_mapping(
            data["authorization"]
        )
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def build_pilot_exact_task_pr_reviewer_request_authorization(
    *,
    reviewer_target_attestation: PilotExactTaskPrReviewerTargetAttestation,
    authorization_id: str,
    reviewer_request_authorizer_actor_id: str,
    authorized_at_utc: str,
    expires_at_utc: str,
    reviewer_request_nonce_sha256: str,
    notes: Sequence[str] = (),
) -> PilotExactTaskPrReviewerRequestAuthorization:
    attestation = _require_live_attestation(reviewer_target_attestation)
    prior = _prior_nonces(attestation)
    return PilotExactTaskPrReviewerRequestAuthorization(
        authorization_id=authorization_id,
        reviewer_target_attestation=attestation,
        reviewer_request_authorizer_actor_id=reviewer_request_authorizer_actor_id,
        authorized_at_utc=authorized_at_utc,
        expires_at_utc=expires_at_utc,
        reviewer_request_nonce_sha256=reviewer_request_nonce_sha256,
        notes=_notes(notes),
        execution_nonce_sha256=prior["execution_nonce_sha256"],
        local_write_nonce_sha256=prior["local_write_nonce_sha256"],
        remote_publication_nonce_sha256=prior["remote_publication_nonce_sha256"],
        pr_mutation_nonce_sha256=prior["pr_mutation_nonce_sha256"],
        ready_for_review_nonce_sha256=prior["ready_for_review_nonce_sha256"],
        **_binding(attestation),
    )


def _verify_pilot_exact_task_pr_reviewer_request_authorization(
    *,
    reviewer_target_attestation: PilotExactTaskPrReviewerTargetAttestation,
    authorization: PilotExactTaskPrReviewerRequestAuthorization,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_provider: Callable[[], str],
) -> PilotExactTaskPrReviewerRequestAuthorizationProof:
    attestation = _require_live_attestation(reviewer_target_attestation)
    if type(authorization) is not PilotExactTaskPrReviewerRequestAuthorization:
        raise PilotExactTaskPrReviewerRequestAuthorizationError(
            "exact reviewer-request authorization is required"
        )
    replayed = PilotExactTaskPrReviewerRequestAuthorization.from_mapping(
        authorization.to_dict()
    )
    if replayed != authorization or replayed.sha256 != authorization.sha256:
        raise PilotExactTaskPrReviewerRequestAuthorizationError(
            "reviewer-request authorization replay identity mismatch"
        )
    if (
        authorization.reviewer_target_attestation is not attestation
        or authorization.reviewer_target_attestation_sha256 != attestation.sha256
    ):
        raise PilotExactTaskPrReviewerRequestAuthorizationError(
            "reviewer-request authorization is not bound to supplied live target"
        )
    for name, expected in _prior_nonces(attestation).items():
        if getattr(authorization, name) != expected:
            raise PilotExactTaskPrReviewerRequestAuthorizationError(
                f"reviewer-request prior nonce binding mismatch: {name}"
            )
    if not isinstance(signature, DetachedEd25519AuthoritySignature):
        raise PilotExactTaskPrReviewerRequestAuthorizationError(
            "detached Ed25519 signature is required"
        )
    if not isinstance(verifier, Ed25519AuthorityVerifier):
        raise PilotExactTaskPrReviewerRequestAuthorizationError(
            "Ed25519 verifier is required"
        )
    if signature.issuer_system_id != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_ISSUER_SYSTEM_ID:
        raise PilotExactTaskPrReviewerRequestAuthorizationError(
            "reviewer-request signature belongs to another issuer system"
        )
    if signature.issuer_actor_id != authorization.reviewer_request_authorizer_actor_id:
        raise PilotExactTaskPrReviewerRequestAuthorizationError(
            "reviewer-request signature actor mismatch"
        )
    if signature.signed_at_utc != authorization.authorized_at_utc:
        raise PilotExactTaskPrReviewerRequestAuthorizationError(
            "reviewer-request signature time mismatch"
        )
    verified_at = now_provider()
    verified = _utc(verified_at, name="verified_at_utc")
    authorized = _utc(authorization.authorized_at_utc, name="authorized_at_utc")
    expires = _utc(authorization.expires_at_utc, name="expires_at_utc")
    if verified < authorized or verified > expires:
        raise PilotExactTaskPrReviewerRequestAuthorizationError(
            "reviewer-request authorization is not currently valid"
        )
    try:
        payload_sha = verifier.verify(
            payload=authorization.canonical_json().encode("utf-8"),
            signature=signature,
            at_utc=verified_at,
        )
    except AsymmetricAuthorityError as exc:
        raise PilotExactTaskPrReviewerRequestAuthorizationError(
            "human reviewer-request signature verification failed"
        ) from exc
    if payload_sha != authorization.sha256:
        raise PilotExactTaskPrReviewerRequestAuthorizationError(
            "verified reviewer-request payload hash mismatch"
        )
    return PilotExactTaskPrReviewerRequestAuthorizationProof(
        authorization_sha256=authorization.sha256,
        signature_sha256=signature.sha256,
        key_id=signature.key_id,
        issuer_actor_id=signature.issuer_actor_id,
        issuer_system_id=signature.issuer_system_id,
        authorization=authorization,
        reviewer_target_attestation_sha256=attestation.sha256,
        reviewer_handoff_requirements_sha256=attestation.reviewer_handoff_requirements_sha256,
        ready_transaction_sha256=attestation.ready_transaction_sha256,
        predicted_commit_sha=attestation.predicted_commit_sha,
        reviewer_handoff_plan_sha256=attestation.reviewer_handoff_plan_sha256,
        reviewer_target_policy_sha256=attestation.reviewer_target_policy_sha256,
        reviewer_login=attestation.reviewer_login,
        reviewer_user_id=attestation.reviewer_user_id,
        reviewer_request_nonce_sha256=authorization.reviewer_request_nonce_sha256,
        verified_at_utc=verified_at,
    )


def verify_pilot_exact_task_pr_reviewer_request_authorization(
    *,
    reviewer_target_attestation: PilotExactTaskPrReviewerTargetAttestation,
    authorization: PilotExactTaskPrReviewerRequestAuthorization,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier | None = None,
) -> PilotExactTaskPrReviewerRequestAuthorizationProof:
    raise PilotExactTaskPrReviewerRequestAuthorizationError(
        "production reviewer-request verification boundary is not installed"
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_PROOF_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_PROOF_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_ISSUER_SYSTEM_ID",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_INTENT",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_MAX_WINDOW_SECONDS",
    "PilotExactTaskPrReviewerRequestAuthorizationError",
    "PilotExactTaskPrReviewerRequestAuthorization",
    "PilotExactTaskPrReviewerRequestAuthorizationProof",
    "build_pilot_exact_task_pr_reviewer_request_authorization",
    "verify_pilot_exact_task_pr_reviewer_request_authorization",
]
