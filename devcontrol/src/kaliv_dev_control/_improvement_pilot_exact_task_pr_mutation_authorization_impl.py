"""ADR-DC-054 human-signed authorization for one exact draft PR creation.

The claim binds one live ADR-DC-054 deterministic PR requirements artifact and a
new one-shot PR-mutation nonce. Verification proves human intent only; it does
not create a pull request and grants no reusable PR, merge, release, deploy or
production-activation authority.
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
from .improvement_pilot_exact_task_pr_mutation_requirements import (
    PILOT_EXACT_TASK_PR_MUTATION_REQUIREMENTS_AUTHORITY,
    PilotExactTaskPrMutationRequirements,
)

PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-mutation-human-authorization/v1"
)
PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_PROOF_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-mutation-human-authorization-proof/v1"
)
PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_AUTHORITY = (
    "dc-l16-exact-draft-pr-mutation-human-authorization-claim-only"
)
PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_PROOF_AUTHORITY = (
    "verified-human-dc-l16-exact-draft-pr-mutation-authorization-only"
)
PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_ISSUER_SYSTEM_ID = (
    "kaliv-rsi-dc-l16-exact-pr-mutation-human-authority-v1"
)
PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_INTENT = (
    "authorize-one-exact-draft-pull-request-creation"
)
PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_MAX_WINDOW_SECONDS = 10 * 60

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_BINDING_FIELDS = (
    "pr_mutation_requirements_sha256",
    "remote_write_transaction_sha256",
    "credential_capability_sha256",
    "remote_write_reservation_sha256",
    "authorization_proof_sha256",
    "execution_nonce_sha256",
    "local_write_nonce_sha256",
    "remote_publication_nonce_sha256",
    "predicted_commit_sha",
    "repository",
    "base_branch",
    "head_branch",
    "pr_title",
    "pr_body",
    "pr_plan_sha256",
    "prior_remote_publication_authorizer_actor_id",
    "requirements_materialized_at_utc",
)


class PilotExactTaskPrMutationAuthorizationError(ValueError):
    """Human PR-mutation authorization is malformed, stale or unsafe."""


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
        raise PilotExactTaskPrMutationAuthorizationError(
            "PR mutation authorization is not canonical JSON"
        ) from exc


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskPrMutationAuthorizationError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise PilotExactTaskPrMutationAuthorizationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrMutationAuthorizationError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrMutationAuthorizationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrMutationAuthorizationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrMutationAuthorizationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _notes(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PilotExactTaskPrMutationAuthorizationError("notes must be an array")
    items = tuple(value)
    if len(items) > 16 or len(items) != len(set(items)):
        raise PilotExactTaskPrMutationAuthorizationError("notes are invalid")
    for item in items:
        if (
            not isinstance(item, str)
            or not item
            or item.strip() != item
            or "\x00" in item
            or len(item.encode("utf-8")) > 2_048
        ):
            raise PilotExactTaskPrMutationAuthorizationError("note is invalid")
    return items


def _require_requirements(value: Any) -> PilotExactTaskPrMutationRequirements:
    if type(value) is not PilotExactTaskPrMutationRequirements:
        raise PilotExactTaskPrMutationAuthorizationError(
            "exact ADR-DC-054 PR requirements are required"
        )
    try:
        replayed = PilotExactTaskPrMutationRequirements.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrMutationAuthorizationError(
            "ADR-DC-054 PR requirements replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrMutationAuthorizationError(
            "ADR-DC-054 PR requirements identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_PR_MUTATION_REQUIREMENTS_AUTHORITY
        or value.remote_publication_completed is not True
        or value.remote_ref_verified is not True
        or value.create_new_draft_pull_request_required is not True
        or value.base_branch_host_pinned is not True
        or value.head_branch_exact_remote_candidate is not True
        or value.pr_title_deterministic is not True
        or value.pr_body_deterministic is not True
        or value.maintainer_can_modify is not False
        or value.separate_human_pr_mutation_authorization_required is not True
        or value.one_shot_pr_mutation_nonce_required is not True
        or value.no_existing_open_pr_required is not True
        or value.ready_for_review_forbidden is not True
        or value.reviewer_mutation_forbidden is not True
        or value.label_mutation_forbidden is not True
        or value.pr_mutation_authorization_consumed is not False
        or value.pr_mutation_authorized is not False
        or value.pull_request_create_authorized is not False
        or value.pull_request_created is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskPrMutationAuthorizationError(
            "human PR authorization requires inert exact PR requirements"
        )
    return value


def _require_live_requirements(value: Any) -> PilotExactTaskPrMutationRequirements:
    exact = _require_requirements(value)
    if exact.requirements_authenticated is not True:
        raise PilotExactTaskPrMutationAuthorizationError(
            "human PR authorization requires live ADR-DC-053 provenance"
        )
    return exact


def _binding(requirements: PilotExactTaskPrMutationRequirements) -> dict[str, Any]:
    exact = _require_requirements(requirements)
    return {
        "pr_mutation_requirements_sha256": exact.sha256,
        "remote_write_transaction_sha256": exact.remote_write_transaction_sha256,
        "credential_capability_sha256": exact.credential_capability_sha256,
        "remote_write_reservation_sha256": exact.remote_write_reservation_sha256,
        "authorization_proof_sha256": exact.authorization_proof_sha256,
        "execution_nonce_sha256": exact.execution_nonce_sha256,
        "local_write_nonce_sha256": exact.local_write_nonce_sha256,
        "remote_publication_nonce_sha256": exact.remote_publication_nonce_sha256,
        "predicted_commit_sha": exact.predicted_commit_sha,
        "repository": exact.repository,
        "base_branch": exact.base_branch,
        "head_branch": exact.head_branch,
        "pr_title": exact.pr_title,
        "pr_body": exact.pr_body,
        "pr_plan_sha256": exact.pr_plan_sha256,
        "prior_remote_publication_authorizer_actor_id": (
            exact.prior_remote_publication_authorizer_actor_id
        ),
        "requirements_materialized_at_utc": exact.materialized_at_utc,
    }


@dataclass(frozen=True, slots=True)
class PilotExactTaskPrMutationAuthorization:
    authorization_id: str
    pr_mutation_requirements: PilotExactTaskPrMutationRequirements
    pr_mutation_requirements_sha256: str
    remote_write_transaction_sha256: str
    credential_capability_sha256: str
    remote_write_reservation_sha256: str
    authorization_proof_sha256: str
    execution_nonce_sha256: str
    local_write_nonce_sha256: str
    remote_publication_nonce_sha256: str
    predicted_commit_sha: str
    repository: str
    base_branch: str
    head_branch: str
    pr_title: str
    pr_body: str
    pr_plan_sha256: str
    prior_remote_publication_authorizer_actor_id: str
    requirements_materialized_at_utc: str
    pr_mutation_authorizer_actor_id: str
    authorized_at_utc: str
    expires_at_utc: str
    pr_mutation_nonce_sha256: str
    notes: tuple[str, ...]
    human_pr_mutation_intent: str = PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_INTENT
    one_shot_pr_mutation_required: bool = True
    create_new_draft_pull_request_required: bool = True
    no_existing_open_pr_required: bool = True
    ready_for_review_forbidden: bool = True
    reviewer_mutation_forbidden: bool = True
    label_mutation_forbidden: bool = True
    human_pr_mutation_authorization_verified: bool = False
    pr_mutation_authorization_consumed: bool = False
    pr_mutation_authorized: bool = False
    pull_request_create_authorized: bool = False
    pull_request_created: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_SCHEMA:
            raise PilotExactTaskPrMutationAuthorizationError(
                "PR authorization schema is unsupported"
            )
        _identifier(self.authorization_id, name="authorization_id")
        requirements = _require_requirements(self.pr_mutation_requirements)
        for name in (
            "pr_mutation_requirements_sha256",
            "remote_write_transaction_sha256",
            "credential_capability_sha256",
            "remote_write_reservation_sha256",
            "authorization_proof_sha256",
            "execution_nonce_sha256",
            "local_write_nonce_sha256",
            "remote_publication_nonce_sha256",
            "pr_plan_sha256",
            "pr_mutation_nonce_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _actor(
            self.prior_remote_publication_authorizer_actor_id,
            name="prior_remote_publication_authorizer_actor_id",
        )
        _actor(self.pr_mutation_authorizer_actor_id, name="pr_mutation_authorizer_actor_id")
        _notes(self.notes)
        mismatch = next(
            (
                name
                for name, expected in _binding(requirements).items()
                if getattr(self, name) != expected
            ),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskPrMutationAuthorizationError(
                f"PR authorization binding mismatch: {mismatch}"
            )
        if self.pr_mutation_authorizer_actor_id != self.prior_remote_publication_authorizer_actor_id:
            raise PilotExactTaskPrMutationAuthorizationError(
                "PR mutation must be authorized by the same human as remote publication"
            )
        if self.pr_mutation_nonce_sha256 in {
            self.execution_nonce_sha256,
            self.local_write_nonce_sha256,
            self.remote_publication_nonce_sha256,
        }:
            raise PilotExactTaskPrMutationAuthorizationError(
                "PR mutation nonce must be distinct from all prior one-shot nonces"
            )
        authorized = _utc(self.authorized_at_utc, name="authorized_at_utc")
        expires = _utc(self.expires_at_utc, name="expires_at_utc")
        materialized = _utc(
            self.requirements_materialized_at_utc,
            name="requirements_materialized_at_utc",
        )
        if authorized < materialized or expires <= authorized:
            raise PilotExactTaskPrMutationAuthorizationError(
                "PR authorization time window is invalid"
            )
        if expires - authorized > timedelta(
            seconds=PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_MAX_WINDOW_SECONDS
        ):
            raise PilotExactTaskPrMutationAuthorizationError(
                "PR authorization window exceeds maximum"
            )
        if self.human_pr_mutation_intent != PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_INTENT:
            raise PilotExactTaskPrMutationAuthorizationError(
                "PR authorization intent is unsupported"
            )
        required_true = (
            "one_shot_pr_mutation_required",
            "create_new_draft_pull_request_required",
            "no_existing_open_pr_required",
            "ready_for_review_forbidden",
            "reviewer_mutation_forbidden",
            "label_mutation_forbidden",
        )
        forced_false = (
            "human_pr_mutation_authorization_verified",
            "pr_mutation_authorization_consumed",
            "pr_mutation_authorized",
            "pull_request_create_authorized",
            "pull_request_created",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrMutationAuthorizationError(
                "PR authorization safety requirements are incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrMutationAuthorizationError(
                "PR authorization claim cannot grant mutation authority"
            )
        if self.authority != PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_AUTHORITY:
            raise PilotExactTaskPrMutationAuthorizationError(
                "PR authorization authority is unsupported"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }
        result["pr_mutation_requirements"] = self.pr_mutation_requirements.to_dict()
        result["notes"] = list(self.notes)
        return result

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrMutationAuthorization":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrMutationAuthorizationError(
                "PR authorization must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrMutationAuthorizationError(
                "PR authorization fields mismatch"
            )
        data = dict(value)
        if not isinstance(data["pr_mutation_requirements"], Mapping):
            raise PilotExactTaskPrMutationAuthorizationError(
                "PR requirements must be an object"
            )
        if not isinstance(data["notes"], list):
            raise PilotExactTaskPrMutationAuthorizationError("notes must be an array")
        data["pr_mutation_requirements"] = PilotExactTaskPrMutationRequirements.from_mapping(
            data["pr_mutation_requirements"]
        )
        data["notes"] = tuple(data["notes"])
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


@dataclass(frozen=True, slots=True)
class PilotExactTaskPrMutationAuthorizationProof:
    authorization_sha256: str
    signature_sha256: str
    key_id: str
    issuer_actor_id: str
    issuer_system_id: str
    authorization: PilotExactTaskPrMutationAuthorization
    pr_mutation_requirements_sha256: str
    remote_write_transaction_sha256: str
    predicted_commit_sha: str
    pr_plan_sha256: str
    pr_mutation_nonce_sha256: str
    verified_at_utc: str
    one_shot_pr_mutation_required: bool = True
    create_new_draft_pull_request_required: bool = True
    no_existing_open_pr_required: bool = True
    ready_for_review_forbidden: bool = True
    reviewer_mutation_forbidden: bool = True
    label_mutation_forbidden: bool = True
    human_pr_mutation_authorization_verified: bool = True
    pr_mutation_authorization_consumed: bool = False
    pr_mutation_authorized: bool = False
    pull_request_create_authorized: bool = False
    pull_request_created: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_PROOF_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_PROOF_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_PROOF_SCHEMA:
            raise PilotExactTaskPrMutationAuthorizationError(
                "PR authorization proof schema is unsupported"
            )
        for name in (
            "authorization_sha256",
            "signature_sha256",
            "pr_mutation_requirements_sha256",
            "remote_write_transaction_sha256",
            "pr_plan_sha256",
            "pr_mutation_nonce_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _identifier(self.key_id, name="key_id")
        _actor(self.issuer_actor_id, name="issuer_actor_id")
        _identifier(self.issuer_system_id, name="issuer_system_id")
        if self.issuer_system_id != PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_ISSUER_SYSTEM_ID:
            raise PilotExactTaskPrMutationAuthorizationError(
                "PR authorization proof issuer system is invalid"
            )
        if type(self.authorization) is not PilotExactTaskPrMutationAuthorization:
            raise PilotExactTaskPrMutationAuthorizationError(
                "exact PR authorization is required"
            )
        replayed = PilotExactTaskPrMutationAuthorization.from_mapping(
            self.authorization.to_dict()
        )
        if replayed != self.authorization or self.authorization_sha256 != self.authorization.sha256:
            raise PilotExactTaskPrMutationAuthorizationError(
                "PR authorization proof identity mismatch"
            )
        if (
            self.issuer_actor_id != self.authorization.pr_mutation_authorizer_actor_id
            or self.pr_mutation_requirements_sha256
            != self.authorization.pr_mutation_requirements_sha256
            or self.remote_write_transaction_sha256
            != self.authorization.remote_write_transaction_sha256
            or self.predicted_commit_sha != self.authorization.predicted_commit_sha
            or self.pr_plan_sha256 != self.authorization.pr_plan_sha256
            or self.pr_mutation_nonce_sha256 != self.authorization.pr_mutation_nonce_sha256
        ):
            raise PilotExactTaskPrMutationAuthorizationError(
                "PR authorization proof binding mismatch"
            )
        verified = _utc(self.verified_at_utc, name="verified_at_utc")
        authorized = _utc(self.authorization.authorized_at_utc, name="authorized_at_utc")
        expires = _utc(self.authorization.expires_at_utc, name="expires_at_utc")
        if verified < authorized or verified > expires:
            raise PilotExactTaskPrMutationAuthorizationError(
                "PR authorization proof verified outside its window"
            )
        required_true = (
            "one_shot_pr_mutation_required",
            "create_new_draft_pull_request_required",
            "no_existing_open_pr_required",
            "ready_for_review_forbidden",
            "reviewer_mutation_forbidden",
            "label_mutation_forbidden",
            "human_pr_mutation_authorization_verified",
        )
        forced_false = (
            "pr_mutation_authorization_consumed",
            "pr_mutation_authorized",
            "pull_request_create_authorized",
            "pull_request_created",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrMutationAuthorizationError(
                "PR authorization proof evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrMutationAuthorizationError(
                "PR authorization proof cannot grant mutation authority"
            )
        if self.authority != PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_PROOF_AUTHORITY:
            raise PilotExactTaskPrMutationAuthorizationError(
                "PR authorization proof authority is unsupported"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }
        result["authorization"] = self.authorization.to_dict()
        return result

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrMutationAuthorizationProof":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrMutationAuthorizationError(
                "PR authorization proof must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrMutationAuthorizationError(
                "PR authorization proof fields mismatch"
            )
        data = dict(value)
        if not isinstance(data["authorization"], Mapping):
            raise PilotExactTaskPrMutationAuthorizationError(
                "PR authorization must be an object"
            )
        data["authorization"] = PilotExactTaskPrMutationAuthorization.from_mapping(
            data["authorization"]
        )
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def build_pilot_exact_task_pr_mutation_authorization(
    *,
    pr_mutation_requirements: PilotExactTaskPrMutationRequirements,
    authorization_id: str,
    pr_mutation_authorizer_actor_id: str,
    authorized_at_utc: str,
    expires_at_utc: str,
    pr_mutation_nonce_sha256: str,
    notes: Sequence[str] = (),
) -> PilotExactTaskPrMutationAuthorization:
    requirements = _require_live_requirements(pr_mutation_requirements)
    return PilotExactTaskPrMutationAuthorization(
        authorization_id=authorization_id,
        pr_mutation_requirements=requirements,
        pr_mutation_authorizer_actor_id=pr_mutation_authorizer_actor_id,
        authorized_at_utc=authorized_at_utc,
        expires_at_utc=expires_at_utc,
        pr_mutation_nonce_sha256=pr_mutation_nonce_sha256,
        notes=_notes(notes),
        **_binding(requirements),
    )


def _verify_pilot_exact_task_pr_mutation_authorization(
    *,
    pr_mutation_requirements: PilotExactTaskPrMutationRequirements,
    authorization: PilotExactTaskPrMutationAuthorization,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_provider: Callable[[], str],
) -> PilotExactTaskPrMutationAuthorizationProof:
    requirements = _require_live_requirements(pr_mutation_requirements)
    if type(authorization) is not PilotExactTaskPrMutationAuthorization:
        raise PilotExactTaskPrMutationAuthorizationError(
            "exact PR authorization is required"
        )
    replayed = PilotExactTaskPrMutationAuthorization.from_mapping(
        authorization.to_dict()
    )
    if replayed != authorization or replayed.sha256 != authorization.sha256:
        raise PilotExactTaskPrMutationAuthorizationError(
            "PR authorization replay identity mismatch"
        )
    if (
        authorization.pr_mutation_requirements is not requirements
        or authorization.pr_mutation_requirements_sha256 != requirements.sha256
    ):
        raise PilotExactTaskPrMutationAuthorizationError(
            "PR authorization is not bound to supplied live requirements"
        )
    if not isinstance(signature, DetachedEd25519AuthoritySignature):
        raise PilotExactTaskPrMutationAuthorizationError(
            "detached Ed25519 signature is required"
        )
    if not isinstance(verifier, Ed25519AuthorityVerifier):
        raise PilotExactTaskPrMutationAuthorizationError("Ed25519 verifier is required")
    if signature.issuer_system_id != PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_ISSUER_SYSTEM_ID:
        raise PilotExactTaskPrMutationAuthorizationError(
            "PR signature belongs to another issuer system"
        )
    if signature.issuer_actor_id != authorization.pr_mutation_authorizer_actor_id:
        raise PilotExactTaskPrMutationAuthorizationError("PR signature actor mismatch")
    if signature.signed_at_utc != authorization.authorized_at_utc:
        raise PilotExactTaskPrMutationAuthorizationError("PR signature time mismatch")
    verified_at = now_provider()
    verified = _utc(verified_at, name="verified_at_utc")
    authorized = _utc(authorization.authorized_at_utc, name="authorized_at_utc")
    expires = _utc(authorization.expires_at_utc, name="expires_at_utc")
    if verified < authorized or verified > expires:
        raise PilotExactTaskPrMutationAuthorizationError(
            "PR authorization is not currently valid"
        )
    try:
        payload_sha = verifier.verify(
            payload=authorization.canonical_json().encode("utf-8"),
            signature=signature,
            at_utc=verified_at,
        )
    except AsymmetricAuthorityError as exc:
        raise PilotExactTaskPrMutationAuthorizationError(
            "human PR mutation signature verification failed"
        ) from exc
    if payload_sha != authorization.sha256:
        raise PilotExactTaskPrMutationAuthorizationError(
            "verified PR authorization payload hash mismatch"
        )
    return PilotExactTaskPrMutationAuthorizationProof(
        authorization_sha256=authorization.sha256,
        signature_sha256=signature.sha256,
        key_id=signature.key_id,
        issuer_actor_id=signature.issuer_actor_id,
        issuer_system_id=signature.issuer_system_id,
        authorization=authorization,
        pr_mutation_requirements_sha256=requirements.sha256,
        remote_write_transaction_sha256=requirements.remote_write_transaction_sha256,
        predicted_commit_sha=requirements.predicted_commit_sha,
        pr_plan_sha256=requirements.pr_plan_sha256,
        pr_mutation_nonce_sha256=authorization.pr_mutation_nonce_sha256,
        verified_at_utc=verified_at,
    )


def verify_pilot_exact_task_pr_mutation_authorization(
    *,
    pr_mutation_requirements: PilotExactTaskPrMutationRequirements,
    authorization: PilotExactTaskPrMutationAuthorization,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier | None = None,
) -> PilotExactTaskPrMutationAuthorizationProof:
    raise PilotExactTaskPrMutationAuthorizationError(
        "production PR-mutation verification boundary is not installed"
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_SCHEMA",
    "PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_PROOF_SCHEMA",
    "PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_PROOF_AUTHORITY",
    "PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_ISSUER_SYSTEM_ID",
    "PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_INTENT",
    "PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_MAX_WINDOW_SECONDS",
    "PilotExactTaskPrMutationAuthorizationError",
    "PilotExactTaskPrMutationAuthorization",
    "PilotExactTaskPrMutationAuthorizationProof",
    "build_pilot_exact_task_pr_mutation_authorization",
    "verify_pilot_exact_task_pr_mutation_authorization",
]
