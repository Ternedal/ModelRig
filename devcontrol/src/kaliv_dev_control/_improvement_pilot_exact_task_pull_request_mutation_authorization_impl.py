"""ADR-DC-055 human-signed authorization for one exact draft-PR intent.

The claim binds one exact live ADR-DC-054 pull-request mutation requirements
artifact and a distinct one-shot PR mutation nonce. Verification proves human
intent only. It performs no GitHub API operation and grants no PR mutation,
ready-for-review, merge, release, deploy, or production-activation authority.
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
from .improvement_pilot_exact_task_pull_request_mutation_requirements import (
    PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_REQUIREMENTS_AUTHORITY,
    PilotExactTaskPullRequestMutationRequirements,
)

PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pull-request-mutation-human-authorization/v1"
)
PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_PROOF_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pull-request-mutation-human-authorization-proof/v1"
)
PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_AUTHORITY = (
    "dc-l16-exact-pull-request-mutation-human-authorization-claim-only"
)
PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_PROOF_AUTHORITY = (
    "verified-human-dc-l16-exact-pull-request-mutation-authorization-only"
)
PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_ISSUER_SYSTEM_ID = (
    "kaliv-rsi-dc-l16-exact-pull-request-mutation-human-authority-v1"
)
PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_INTENT = (
    "authorize-one-exact-draft-pull-request-create"
)
PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_MAX_WINDOW_SECONDS = 10 * 60

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_BINDING_FIELDS = (
    "pull_request_mutation_requirements_sha256",
    "remote_publication_write_transaction_sha256",
    "credential_capability_sha256",
    "remote_write_reservation_sha256",
    "target_attestation_sha256",
    "remote_publication_authorization_proof_sha256",
    "local_commit_publication_requirements_sha256",
    "local_commit_write_transaction_sha256",
    "remote_publication_nonce_sha256",
    "repository",
    "api_host",
    "canonical_remote_url",
    "base_ref",
    "head_ref",
    "head_branch",
    "predicted_commit_sha",
    "remote_publication_verified_at_utc",
    "pr_requirements_materialized_at_utc",
)


class PilotExactTaskPullRequestMutationAuthorizationError(ValueError):
    """Human PR-mutation authorization is malformed, stale, or unsafe."""


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
        raise PilotExactTaskPullRequestMutationAuthorizationError(
            "pull-request mutation authorization is not canonical JSON"
        ) from exc


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskPullRequestMutationAuthorizationError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise PilotExactTaskPullRequestMutationAuthorizationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskPullRequestMutationAuthorizationError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskPullRequestMutationAuthorizationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPullRequestMutationAuthorizationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPullRequestMutationAuthorizationError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _notes(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PilotExactTaskPullRequestMutationAuthorizationError(
            "notes must be an array"
        )
    items = tuple(value)
    if len(items) > 16 or len(items) != len(set(items)):
        raise PilotExactTaskPullRequestMutationAuthorizationError("notes are invalid")
    for item in items:
        if (
            not isinstance(item, str)
            or not item
            or item.strip() != item
            or "\x00" in item
            or len(item.encode("utf-8")) > 2_048
        ):
            raise PilotExactTaskPullRequestMutationAuthorizationError("note is invalid")
    return items


def _require_requirements(
    value: Any,
) -> PilotExactTaskPullRequestMutationRequirements:
    if type(value) is not PilotExactTaskPullRequestMutationRequirements:
        raise PilotExactTaskPullRequestMutationAuthorizationError(
            "exact ADR-DC-054 pull-request mutation requirements are required"
        )
    try:
        replayed = PilotExactTaskPullRequestMutationRequirements.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPullRequestMutationAuthorizationError(
            "ADR-DC-054 requirements replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPullRequestMutationAuthorizationError(
            "ADR-DC-054 requirements identity mismatch"
        )
    if (
        value.authority
        != PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_REQUIREMENTS_AUTHORITY
        or value.remote_publication_transaction_authenticated is not True
        or value.remote_publication_completed is not True
        or value.remote_ref_verified is not True
        or value.pull_request_requirements_materialized is not True
        or value.draft_pull_request_required is not True
        or value.create_only_pull_request_required is not True
        or value.existing_open_pull_request_absent_required is not True
        or value.same_repository_head_required is not True
        or value.exact_base_ref_required is not True
        or value.exact_head_ref_required is not True
        or value.exact_head_sha_required is not True
        or value.separate_human_pr_mutation_authorization_required is not True
        or value.fresh_pull_request_state_observation_before_write_required is not True
        or value.one_shot_pr_mutation_reservation_required is not True
        or value.host_pinned_pr_credential_capability_required is not True
        or value.merge_separately_authorized_required is not True
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
        or value.repository != "Ternedal/ModelRig"
        or value.api_host != "api.github.com"
        or value.base_ref != "main"
    ):
        raise PilotExactTaskPullRequestMutationAuthorizationError(
            "PR authorization requires inert exact ADR-DC-054 requirements"
        )
    return value


def _require_live_requirements(
    value: Any,
) -> PilotExactTaskPullRequestMutationRequirements:
    exact = _require_requirements(value)
    if exact.requirements_authenticated is not True:
        raise PilotExactTaskPullRequestMutationAuthorizationError(
            "PR authorization requires live ADR-DC-054 provenance"
        )
    return exact


def _binding(
    requirements: PilotExactTaskPullRequestMutationRequirements,
) -> dict[str, Any]:
    exact = _require_requirements(requirements)
    return {
        "pull_request_mutation_requirements_sha256": exact.sha256,
        "remote_publication_write_transaction_sha256": (
            exact.remote_publication_write_transaction_sha256
        ),
        "credential_capability_sha256": exact.credential_capability_sha256,
        "remote_write_reservation_sha256": exact.remote_write_reservation_sha256,
        "target_attestation_sha256": exact.target_attestation_sha256,
        "remote_publication_authorization_proof_sha256": (
            exact.remote_publication_authorization_proof_sha256
        ),
        "local_commit_publication_requirements_sha256": (
            exact.local_commit_publication_requirements_sha256
        ),
        "local_commit_write_transaction_sha256": (
            exact.local_commit_write_transaction_sha256
        ),
        "remote_publication_nonce_sha256": exact.remote_publication_nonce_sha256,
        "repository": exact.repository,
        "api_host": exact.api_host,
        "canonical_remote_url": exact.canonical_remote_url,
        "base_ref": exact.base_ref,
        "head_ref": exact.head_ref,
        "head_branch": exact.head_branch,
        "predicted_commit_sha": exact.predicted_commit_sha,
        "remote_publication_verified_at_utc": exact.remote_publication_verified_at_utc,
        "pr_requirements_materialized_at_utc": exact.materialized_at_utc,
    }


_CLAIM_REQUIRED_TRUE = (
    "draft_pull_request_required",
    "create_only_pull_request_required",
    "existing_open_pull_request_absent_required",
    "same_repository_head_required",
    "exact_base_ref_required",
    "exact_head_ref_required",
    "exact_head_sha_required",
    "one_shot_pr_mutation_required",
    "fresh_pull_request_state_observation_before_write_required",
    "one_shot_pr_mutation_reservation_required",
    "host_pinned_pr_credential_capability_required",
    "merge_separately_authorized_required",
)

_CLAIM_FORCED_FALSE = (
    "human_pr_mutation_authorization_verified",
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


@dataclass(frozen=True, slots=True)
class PilotExactTaskPullRequestMutationAuthorization:
    authorization_id: str
    pull_request_mutation_requirements: PilotExactTaskPullRequestMutationRequirements
    pull_request_mutation_requirements_sha256: str
    remote_publication_write_transaction_sha256: str
    credential_capability_sha256: str
    remote_write_reservation_sha256: str
    target_attestation_sha256: str
    remote_publication_authorization_proof_sha256: str
    local_commit_publication_requirements_sha256: str
    local_commit_write_transaction_sha256: str
    remote_publication_nonce_sha256: str
    repository: str
    api_host: str
    canonical_remote_url: str
    base_ref: str
    head_ref: str
    head_branch: str
    predicted_commit_sha: str
    remote_publication_verified_at_utc: str
    pr_requirements_materialized_at_utc: str
    pr_mutation_authorizer_actor_id: str
    authorized_at_utc: str
    expires_at_utc: str
    pr_mutation_nonce_sha256: str
    notes: tuple[str, ...]
    human_pr_mutation_intent: str = (
        PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_INTENT
    )
    draft_pull_request_required: bool = True
    create_only_pull_request_required: bool = True
    existing_open_pull_request_absent_required: bool = True
    same_repository_head_required: bool = True
    exact_base_ref_required: bool = True
    exact_head_ref_required: bool = True
    exact_head_sha_required: bool = True
    one_shot_pr_mutation_required: bool = True
    fresh_pull_request_state_observation_before_write_required: bool = True
    one_shot_pr_mutation_reservation_required: bool = True
    host_pinned_pr_credential_capability_required: bool = True
    merge_separately_authorized_required: bool = True
    human_pr_mutation_authorization_verified: bool = False
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
    authority: str = PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_SCHEMA:
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "PR authorization schema unsupported"
            )
        if (
            self.authority
            != PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_AUTHORITY
        ):
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "PR authorization authority unsupported"
            )
        _identifier(self.authorization_id, name="authorization_id")
        requirements = _require_requirements(self.pull_request_mutation_requirements)
        for name in (
            "pull_request_mutation_requirements_sha256",
            "remote_publication_write_transaction_sha256",
            "credential_capability_sha256",
            "remote_write_reservation_sha256",
            "target_attestation_sha256",
            "remote_publication_authorization_proof_sha256",
            "local_commit_publication_requirements_sha256",
            "local_commit_write_transaction_sha256",
            "remote_publication_nonce_sha256",
            "pr_mutation_nonce_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _actor(
            self.pr_mutation_authorizer_actor_id,
            name="pr_mutation_authorizer_actor_id",
        )
        _notes(self.notes)
        expected = _binding(requirements)
        mismatch = next(
            (name for name, item in expected.items() if getattr(self, name) != item),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                f"PR authorization binding mismatch: {mismatch}"
            )
        if self.pr_mutation_nonce_sha256 == self.remote_publication_nonce_sha256:
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "PR mutation nonce must be distinct from remote-publication nonce"
            )
        authorized = _utc(self.authorized_at_utc, name="authorized_at_utc")
        expires = _utc(self.expires_at_utc, name="expires_at_utc")
        requirements_at = _utc(
            self.pr_requirements_materialized_at_utc,
            name="pr_requirements_materialized_at_utc",
        )
        if authorized < requirements_at or expires <= authorized:
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "PR authorization time window is invalid"
            )
        if expires - authorized > timedelta(
            seconds=PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_MAX_WINDOW_SECONDS
        ):
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "PR authorization window exceeds maximum"
            )
        if (
            self.human_pr_mutation_intent
            != PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_INTENT
        ):
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "PR authorization intent unsupported"
            )
        if any(getattr(self, name) is not True for name in _CLAIM_REQUIRED_TRUE):
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "PR authorization requirements incomplete"
            )
        if any(getattr(self, name) is not False for name in _CLAIM_FORCED_FALSE):
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "PR authorization claim cannot grant mutation authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }
        result["pull_request_mutation_requirements"] = (
            self.pull_request_mutation_requirements.to_dict()
        )
        result["notes"] = list(self.notes)
        return result

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskPullRequestMutationAuthorization":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "PR authorization must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "PR authorization fields mismatch"
            )
        data = dict(value)
        if not isinstance(data["pull_request_mutation_requirements"], Mapping):
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "PR requirements must be an object"
            )
        if not isinstance(data["notes"], list):
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "notes must be an array"
            )
        data["pull_request_mutation_requirements"] = (
            PilotExactTaskPullRequestMutationRequirements.from_mapping(
                data["pull_request_mutation_requirements"]
            )
        )
        data["notes"] = tuple(data["notes"])
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


_PROOF_REQUIRED_TRUE = _CLAIM_REQUIRED_TRUE + (
    "human_pr_mutation_authorization_verified",
)
_PROOF_FORCED_FALSE = (
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


@dataclass(frozen=True, slots=True)
class PilotExactTaskPullRequestMutationAuthorizationProof:
    authorization_sha256: str
    signature_sha256: str
    key_id: str
    issuer_actor_id: str
    issuer_system_id: str
    authorization: PilotExactTaskPullRequestMutationAuthorization
    pull_request_mutation_requirements_sha256: str
    predicted_commit_sha: str
    remote_publication_nonce_sha256: str
    pr_mutation_nonce_sha256: str
    verified_at_utc: str
    draft_pull_request_required: bool = True
    create_only_pull_request_required: bool = True
    existing_open_pull_request_absent_required: bool = True
    same_repository_head_required: bool = True
    exact_base_ref_required: bool = True
    exact_head_ref_required: bool = True
    exact_head_sha_required: bool = True
    one_shot_pr_mutation_required: bool = True
    fresh_pull_request_state_observation_before_write_required: bool = True
    one_shot_pr_mutation_reservation_required: bool = True
    host_pinned_pr_credential_capability_required: bool = True
    merge_separately_authorized_required: bool = True
    human_pr_mutation_authorization_verified: bool = True
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
    authority: str = PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_PROOF_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_PROOF_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema
            != PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_PROOF_SCHEMA
        ):
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "PR authorization proof schema unsupported"
            )
        if (
            self.authority
            != PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_PROOF_AUTHORITY
        ):
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "PR authorization proof authority unsupported"
            )
        for name in (
            "authorization_sha256",
            "signature_sha256",
            "pull_request_mutation_requirements_sha256",
            "remote_publication_nonce_sha256",
            "pr_mutation_nonce_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _identifier(self.key_id, name="key_id")
        _actor(self.issuer_actor_id, name="issuer_actor_id")
        _identifier(self.issuer_system_id, name="issuer_system_id")
        if (
            self.issuer_system_id
            != PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_ISSUER_SYSTEM_ID
        ):
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "PR authorization proof issuer system invalid"
            )
        if type(self.authorization) is not PilotExactTaskPullRequestMutationAuthorization:
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "exact PR authorization is required"
            )
        replayed = PilotExactTaskPullRequestMutationAuthorization.from_mapping(
            self.authorization.to_dict()
        )
        if (
            replayed != self.authorization
            or self.authorization_sha256 != self.authorization.sha256
        ):
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "PR proof authorization identity mismatch"
            )
        if (
            self.issuer_actor_id != self.authorization.pr_mutation_authorizer_actor_id
            or self.pull_request_mutation_requirements_sha256
            != self.authorization.pull_request_mutation_requirements_sha256
            or self.predicted_commit_sha != self.authorization.predicted_commit_sha
            or self.remote_publication_nonce_sha256
            != self.authorization.remote_publication_nonce_sha256
            or self.pr_mutation_nonce_sha256
            != self.authorization.pr_mutation_nonce_sha256
        ):
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "PR authorization proof binding mismatch"
            )
        verified = _utc(self.verified_at_utc, name="verified_at_utc")
        authorized = _utc(self.authorization.authorized_at_utc, name="authorized_at_utc")
        expires = _utc(self.authorization.expires_at_utc, name="expires_at_utc")
        if verified < authorized or verified > expires:
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "PR proof verified outside authorization window"
            )
        if any(getattr(self, name) is not True for name in _PROOF_REQUIRED_TRUE):
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "PR authorization proof evidence incomplete"
            )
        if any(getattr(self, name) is not False for name in _PROOF_FORCED_FALSE):
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "PR authorization proof cannot grant mutation authority"
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
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskPullRequestMutationAuthorizationProof":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "PR authorization proof must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "PR authorization proof fields mismatch"
            )
        data = dict(value)
        if not isinstance(data["authorization"], Mapping):
            raise PilotExactTaskPullRequestMutationAuthorizationError(
                "PR authorization must be an object"
            )
        data["authorization"] = PilotExactTaskPullRequestMutationAuthorization.from_mapping(
            data["authorization"]
        )
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def build_pilot_exact_task_pull_request_mutation_authorization(
    *,
    pull_request_mutation_requirements: PilotExactTaskPullRequestMutationRequirements,
    authorization_id: str,
    pr_mutation_authorizer_actor_id: str,
    authorized_at_utc: str,
    expires_at_utc: str,
    pr_mutation_nonce_sha256: str,
    notes: Sequence[str] = (),
) -> PilotExactTaskPullRequestMutationAuthorization:
    requirements = _require_live_requirements(pull_request_mutation_requirements)
    return PilotExactTaskPullRequestMutationAuthorization(
        authorization_id=authorization_id,
        pull_request_mutation_requirements=requirements,
        pr_mutation_authorizer_actor_id=pr_mutation_authorizer_actor_id,
        authorized_at_utc=authorized_at_utc,
        expires_at_utc=expires_at_utc,
        pr_mutation_nonce_sha256=pr_mutation_nonce_sha256,
        notes=_notes(notes),
        **_binding(requirements),
    )


def _verify_pilot_exact_task_pull_request_mutation_authorization(
    *,
    pull_request_mutation_requirements: PilotExactTaskPullRequestMutationRequirements,
    authorization: PilotExactTaskPullRequestMutationAuthorization,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_provider: Callable[[], str],
) -> PilotExactTaskPullRequestMutationAuthorizationProof:
    requirements = _require_live_requirements(pull_request_mutation_requirements)
    if type(authorization) is not PilotExactTaskPullRequestMutationAuthorization:
        raise PilotExactTaskPullRequestMutationAuthorizationError(
            "exact PR authorization is required"
        )
    replayed = PilotExactTaskPullRequestMutationAuthorization.from_mapping(
        authorization.to_dict()
    )
    if replayed != authorization or replayed.sha256 != authorization.sha256:
        raise PilotExactTaskPullRequestMutationAuthorizationError(
            "PR authorization replay identity mismatch"
        )
    if (
        authorization.pull_request_mutation_requirements is not requirements
        or authorization.pull_request_mutation_requirements_sha256 != requirements.sha256
    ):
        raise PilotExactTaskPullRequestMutationAuthorizationError(
            "PR authorization is not bound to supplied live requirements"
        )
    if not isinstance(signature, DetachedEd25519AuthoritySignature):
        raise PilotExactTaskPullRequestMutationAuthorizationError(
            "detached Ed25519 signature is required"
        )
    if not isinstance(verifier, Ed25519AuthorityVerifier):
        raise PilotExactTaskPullRequestMutationAuthorizationError(
            "Ed25519 verifier is required"
        )
    if (
        signature.issuer_system_id
        != PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_ISSUER_SYSTEM_ID
    ):
        raise PilotExactTaskPullRequestMutationAuthorizationError(
            "signature belongs to another issuer system"
        )
    if signature.issuer_actor_id != authorization.pr_mutation_authorizer_actor_id:
        raise PilotExactTaskPullRequestMutationAuthorizationError(
            "signature actor mismatch"
        )
    if signature.signed_at_utc != authorization.authorized_at_utc:
        raise PilotExactTaskPullRequestMutationAuthorizationError(
            "signature time mismatch"
        )
    verified_at = now_provider()
    verified = _utc(verified_at, name="verified_at_utc")
    authorized = _utc(authorization.authorized_at_utc, name="authorized_at_utc")
    expires = _utc(authorization.expires_at_utc, name="expires_at_utc")
    if verified < authorized or verified > expires:
        raise PilotExactTaskPullRequestMutationAuthorizationError(
            "PR authorization is not currently valid"
        )
    try:
        payload_sha = verifier.verify(
            payload=authorization.canonical_json().encode("utf-8"),
            signature=signature,
            at_utc=verified_at,
        )
    except AsymmetricAuthorityError as exc:
        raise PilotExactTaskPullRequestMutationAuthorizationError(
            "human PR-mutation signature verification failed"
        ) from exc
    if payload_sha != authorization.sha256:
        raise PilotExactTaskPullRequestMutationAuthorizationError(
            "verified PR payload hash mismatch"
        )
    return PilotExactTaskPullRequestMutationAuthorizationProof(
        authorization_sha256=authorization.sha256,
        signature_sha256=signature.sha256,
        key_id=signature.key_id,
        issuer_actor_id=signature.issuer_actor_id,
        issuer_system_id=signature.issuer_system_id,
        authorization=authorization,
        pull_request_mutation_requirements_sha256=requirements.sha256,
        predicted_commit_sha=requirements.predicted_commit_sha,
        remote_publication_nonce_sha256=requirements.remote_publication_nonce_sha256,
        pr_mutation_nonce_sha256=authorization.pr_mutation_nonce_sha256,
        verified_at_utc=verified_at,
    )


def verify_pilot_exact_task_pull_request_mutation_authorization(
    *,
    pull_request_mutation_requirements: PilotExactTaskPullRequestMutationRequirements,
    authorization: PilotExactTaskPullRequestMutationAuthorization,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier | None = None,
) -> PilotExactTaskPullRequestMutationAuthorizationProof:
    raise PilotExactTaskPullRequestMutationAuthorizationError(
        "production PR-mutation verification boundary is not installed"
    )


__all__ = [
    "PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_SCHEMA",
    "PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_PROOF_SCHEMA",
    "PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_AUTHORITY",
    "PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_PROOF_AUTHORITY",
    "PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_ISSUER_SYSTEM_ID",
    "PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_INTENT",
    "PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_MAX_WINDOW_SECONDS",
    "PilotExactTaskPullRequestMutationAuthorizationError",
    "PilotExactTaskPullRequestMutationAuthorization",
    "PilotExactTaskPullRequestMutationAuthorizationProof",
    "build_pilot_exact_task_pull_request_mutation_authorization",
    "verify_pilot_exact_task_pull_request_mutation_authorization",
]
