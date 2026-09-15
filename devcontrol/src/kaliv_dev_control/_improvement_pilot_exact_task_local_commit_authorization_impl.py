"""Human-signed authorization for one later exact local commit write.

ADR-DC-044 verifies fresh human intent over one exact ADR-DC-043 requirements
manifest. The verified proof is deliberately not a Git-write admission: it does
not reserve a write slot, write Git objects, move a local ref, create a commit,
or grant remote/publication/production authority.
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
from .improvement_pilot_exact_task_local_commit_write_requirements import (
    PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_REQUIREMENTS_AUTHORITY,
    PilotExactTaskLocalCommitWriteRequirements,
)

PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-local-commit-human-authorization/v1"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_PROOF_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-local-commit-human-authorization-proof/v1"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_AUTHORITY = (
    "dc-l16-exact-local-commit-human-authorization-claim-only"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_PROOF_AUTHORITY = (
    "verified-human-dc-l16-exact-local-commit-authorization-only"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ISSUER_SYSTEM_ID = (
    "kaliv-rsi-dc-l16-exact-local-commit-human-authority-v1"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_INTENT = (
    "authorize-one-exact-local-commit-write"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_MAX_WINDOW_SECONDS = 10 * 60

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_BINDING_FIELDS = (
    "local_commit_write_requirements_sha256",
    "local_commit_object_identity_sha256",
    "local_commit_plan_sha256",
    "post_execution_evaluation_sha256",
    "execution_transaction_sha256",
    "tier_a_receipt_sha256",
    "execution_nonce_sha256",
    "execution_authorizer_actor_id",
    "development_task_sha256",
    "task_id",
    "repository",
    "base_sha",
    "candidate_patch_sha256",
    "candidate_numstat_sha256",
    "scope_policy_sha256",
    "index_manifest_sha256",
    "root_tree_sha",
    "commit_payload_sha256",
    "predicted_commit_sha",
    "commit_subject_sha256",
    "commit_message_policy",
    "materialized_at_utc",
)

_AUTHORIZATION_FIELDS = {
    "schema",
    "authorization_id",
    "local_commit_write_requirements",
    *_BINDING_FIELDS,
    "local_commit_authorizer_actor_id",
    "authorized_at_utc",
    "expires_at_utc",
    "local_write_nonce_sha256",
    "notes",
    "human_local_commit_intent",
    "one_shot_local_write_required",
    "local_write_authorization_consumed",
    "human_local_commit_authorization_verified",
    "git_object_write_authorized",
    "local_ref_update_authorized",
    "local_commit_authorized",
    "local_commit_created",
    "integration_ready",
    "product_pilot_started",
    "remote_write_authorized",
    "push_authorized",
    "pr_mutation_authorized",
    "merge_authorized",
    "release_authorized",
    "deploy_authorized",
    "production_activation_authorized",
    "authority",
}

_PROOF_FIELDS = {
    "schema",
    "authorization_sha256",
    "signature_sha256",
    "key_id",
    "issuer_actor_id",
    "issuer_system_id",
    "authorization",
    "local_commit_write_requirements_sha256",
    "local_commit_object_identity_sha256",
    "execution_nonce_sha256",
    "local_write_nonce_sha256",
    "predicted_commit_sha",
    "verified_at_utc",
    "one_shot_local_write_required",
    "local_write_authorization_consumed",
    "human_local_commit_authorization_verified",
    "git_object_write_authorized",
    "local_ref_update_authorized",
    "local_commit_authorized",
    "local_commit_created",
    "integration_ready",
    "product_pilot_started",
    "remote_write_authorized",
    "push_authorized",
    "pr_mutation_authorized",
    "merge_authorized",
    "release_authorized",
    "deploy_authorized",
    "production_activation_authorized",
    "authority",
}


class PilotExactTaskLocalCommitAuthorizationError(ValueError):
    """Exact local-commit human authorization is malformed or unsafe."""


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
        raise PilotExactTaskLocalCommitAuthorizationError(
            "local commit authorization is not canonical JSON"
        ) from exc


def _strict(value: Any, *, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PilotExactTaskLocalCommitAuthorizationError(f"{name} fields mismatch")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskLocalCommitAuthorizationError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise PilotExactTaskLocalCommitAuthorizationError(f"{name} is invalid")
    return value


def _hex(value: Any, *, name: str, pattern: re.Pattern[str] = _HEX64) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PilotExactTaskLocalCommitAuthorizationError(f"{name} is invalid")
    if pattern is _HEX64 and value == "0" * 64:
        raise PilotExactTaskLocalCommitAuthorizationError(
            f"{name} must not be a placeholder"
        )
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskLocalCommitAuthorizationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskLocalCommitAuthorizationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _notes(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PilotExactTaskLocalCommitAuthorizationError(
            "local commit authorization notes must be an array"
        )
    items = tuple(value)
    if len(items) > 16:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "local commit authorization has too many notes"
        )
    for item in items:
        if (
            not isinstance(item, str)
            or not item
            or item.strip() != item
            or "\x00" in item
            or len(item.encode("utf-8")) > 2_048
        ):
            raise PilotExactTaskLocalCommitAuthorizationError(
                "local commit authorization note is invalid"
            )
    if len(items) != len(set(items)):
        raise PilotExactTaskLocalCommitAuthorizationError(
            "local commit authorization notes must be unique"
        )
    return items


def _require_requirements(value: Any) -> PilotExactTaskLocalCommitWriteRequirements:
    if type(value) is not PilotExactTaskLocalCommitWriteRequirements:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "exact ADR-DC-043 PilotExactTaskLocalCommitWriteRequirements is required"
        )
    try:
        replayed = PilotExactTaskLocalCommitWriteRequirements.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "ADR-DC-043 requirements replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "ADR-DC-043 requirements replay identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_REQUIREMENTS_AUTHORITY
        or value.local_commit_write_requirements_materialized is not True
        or value.separate_human_local_commit_authorization_required is not True
        or value.human_local_commit_authorizer_continuity_required is not True
        or value.one_shot_local_write_nonce_required is not True
        or value.local_write_nonce_distinct_from_execution_nonce_required is not True
        or value.durable_prewrite_reservation_required is not True
        or value.reservation_before_git_object_write_required is not True
        or value.remote_write_forbidden is not True
        or value.git_object_write_authorized is not False
        or value.local_ref_update_authorized is not False
        or value.local_commit_authorized is not False
        or value.local_commit_created is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskLocalCommitAuthorizationError(
            "human local-commit authorization requires inert exact ADR-DC-043 requirements"
        )
    if value.repository != "Ternedal/ModelRig":
        raise PilotExactTaskLocalCommitAuthorizationError("repository is unsupported")
    return value


def _expected_binding(
    requirements: PilotExactTaskLocalCommitWriteRequirements,
) -> dict[str, Any]:
    exact = _require_requirements(requirements)
    return {
        "local_commit_write_requirements_sha256": exact.sha256,
        "local_commit_object_identity_sha256": exact.local_commit_object_identity_sha256,
        "local_commit_plan_sha256": exact.local_commit_plan_sha256,
        "post_execution_evaluation_sha256": exact.post_execution_evaluation_sha256,
        "execution_transaction_sha256": exact.execution_transaction_sha256,
        "tier_a_receipt_sha256": exact.tier_a_receipt_sha256,
        "execution_nonce_sha256": exact.execution_nonce_sha256,
        "execution_authorizer_actor_id": exact.execution_authorizer_actor_id,
        "development_task_sha256": exact.development_task_sha256,
        "task_id": exact.task_id,
        "repository": exact.repository,
        "base_sha": exact.base_sha,
        "candidate_patch_sha256": exact.candidate_patch_sha256,
        "candidate_numstat_sha256": exact.candidate_numstat_sha256,
        "scope_policy_sha256": exact.scope_policy_sha256,
        "index_manifest_sha256": exact.index_manifest_sha256,
        "root_tree_sha": exact.root_tree_sha,
        "commit_payload_sha256": exact.commit_payload_sha256,
        "predicted_commit_sha": exact.predicted_commit_sha,
        "commit_subject_sha256": exact.commit_subject_sha256,
        "commit_message_policy": exact.commit_message_policy,
        "materialized_at_utc": exact.materialized_at_utc,
    }


@dataclass(frozen=True, slots=True)
class PilotExactTaskLocalCommitAuthorization:
    authorization_id: str
    local_commit_write_requirements: PilotExactTaskLocalCommitWriteRequirements
    local_commit_write_requirements_sha256: str
    local_commit_object_identity_sha256: str
    local_commit_plan_sha256: str
    post_execution_evaluation_sha256: str
    execution_transaction_sha256: str
    tier_a_receipt_sha256: str
    execution_nonce_sha256: str
    execution_authorizer_actor_id: str
    development_task_sha256: str
    task_id: str
    repository: str
    base_sha: str
    candidate_patch_sha256: str
    candidate_numstat_sha256: str
    scope_policy_sha256: str
    index_manifest_sha256: str
    root_tree_sha: str
    commit_payload_sha256: str
    predicted_commit_sha: str
    commit_subject_sha256: str
    commit_message_policy: str
    materialized_at_utc: str
    local_commit_authorizer_actor_id: str
    authorized_at_utc: str
    expires_at_utc: str
    local_write_nonce_sha256: str
    notes: tuple[str, ...]
    human_local_commit_intent: str = PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_INTENT
    one_shot_local_write_required: bool = True
    local_write_authorization_consumed: bool = False
    human_local_commit_authorization_verified: bool = False
    git_object_write_authorized: bool = False
    local_ref_update_authorized: bool = False
    local_commit_authorized: bool = False
    local_commit_created: bool = False
    integration_ready: bool = False
    product_pilot_started: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_SCHEMA:
            raise PilotExactTaskLocalCommitAuthorizationError(
                "local commit authorization schema unsupported"
            )
        _identifier(self.authorization_id, name="authorization_id")
        requirements = _require_requirements(self.local_commit_write_requirements)
        for name in (
            "local_commit_write_requirements_sha256",
            "local_commit_object_identity_sha256",
            "local_commit_plan_sha256",
            "post_execution_evaluation_sha256",
            "execution_transaction_sha256",
            "tier_a_receipt_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "candidate_numstat_sha256",
            "scope_policy_sha256",
            "index_manifest_sha256",
            "commit_payload_sha256",
            "commit_subject_sha256",
            "local_write_nonce_sha256",
        ):
            _hex(getattr(self, name), name=name)
        for name in ("base_sha", "root_tree_sha", "predicted_commit_sha"):
            _hex(getattr(self, name), name=name, pattern=_HEX40)
        _actor(self.execution_authorizer_actor_id, name="execution_authorizer_actor_id")
        _actor(self.local_commit_authorizer_actor_id, name="local_commit_authorizer_actor_id")
        _identifier(self.task_id, name="task_id")
        _notes(self.notes)

        expected = _expected_binding(requirements)
        mismatch = next(
            (name for name, item in expected.items() if getattr(self, name) != item),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskLocalCommitAuthorizationError(
                f"local commit authorization binding mismatch: {mismatch}"
            )
        if self.local_commit_authorizer_actor_id != self.execution_authorizer_actor_id:
            raise PilotExactTaskLocalCommitAuthorizationError(
                "local commit authorizer must be the same human who authorized task execution"
            )
        if self.local_write_nonce_sha256 == self.execution_nonce_sha256:
            raise PilotExactTaskLocalCommitAuthorizationError(
                "local write nonce must be distinct from the consumed execution nonce"
            )

        authorized = _utc(self.authorized_at_utc, name="authorized_at_utc")
        expires = _utc(self.expires_at_utc, name="expires_at_utc")
        materialized = _utc(self.materialized_at_utc, name="materialized_at_utc")
        if authorized < materialized:
            raise PilotExactTaskLocalCommitAuthorizationError(
                "local commit authorization predates ADR-DC-042 identity materialization"
            )
        if expires <= authorized:
            raise PilotExactTaskLocalCommitAuthorizationError(
                "local commit authorization expiry is invalid"
            )
        if expires - authorized > timedelta(
            seconds=PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_MAX_WINDOW_SECONDS
        ):
            raise PilotExactTaskLocalCommitAuthorizationError(
                "local commit authorization window exceeds the maximum"
            )
        if self.human_local_commit_intent != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_INTENT:
            raise PilotExactTaskLocalCommitAuthorizationError(
                "human local commit intent unsupported"
            )
        if (
            self.one_shot_local_write_required is not True
            or self.local_write_authorization_consumed is not False
            or self.human_local_commit_authorization_verified is not False
            or self.git_object_write_authorized is not False
            or self.local_ref_update_authorized is not False
            or self.local_commit_authorized is not False
            or self.local_commit_created is not False
            or self.integration_ready is not False
            or self.product_pilot_started is not False
            or self.remote_write_authorized is not False
            or self.push_authorized is not False
            or self.pr_mutation_authorized is not False
            or self.merge_authorized is not False
            or self.release_authorized is not False
            or self.deploy_authorized is not False
            or self.production_activation_authorized is not False
            or self.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_AUTHORITY
        ):
            raise PilotExactTaskLocalCommitAuthorizationError(
                "local commit authorization claim authority boundary is invalid"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskLocalCommitAuthorization":
        data = dict(_strict(value, fields=_AUTHORIZATION_FIELDS, name="authorization"))
        if not isinstance(data.get("local_commit_write_requirements"), Mapping):
            raise PilotExactTaskLocalCommitAuthorizationError(
                "local_commit_write_requirements must be an object"
            )
        if not isinstance(data.get("notes"), list):
            raise PilotExactTaskLocalCommitAuthorizationError("notes must be an array")
        data["local_commit_write_requirements"] = (
            PilotExactTaskLocalCommitWriteRequirements.from_mapping(
                data["local_commit_write_requirements"]
            )
        )
        data["notes"] = tuple(data["notes"])
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "authorization_id": self.authorization_id,
            "local_commit_write_requirements": self.local_commit_write_requirements.to_dict(),
            **{name: getattr(self, name) for name in _BINDING_FIELDS},
            "local_commit_authorizer_actor_id": self.local_commit_authorizer_actor_id,
            "authorized_at_utc": self.authorized_at_utc,
            "expires_at_utc": self.expires_at_utc,
            "local_write_nonce_sha256": self.local_write_nonce_sha256,
            "notes": list(self.notes),
            "human_local_commit_intent": self.human_local_commit_intent,
            "one_shot_local_write_required": self.one_shot_local_write_required,
            "local_write_authorization_consumed": self.local_write_authorization_consumed,
            "human_local_commit_authorization_verified": self.human_local_commit_authorization_verified,
            "git_object_write_authorized": self.git_object_write_authorized,
            "local_ref_update_authorized": self.local_ref_update_authorized,
            "local_commit_authorized": self.local_commit_authorized,
            "local_commit_created": self.local_commit_created,
            "integration_ready": self.integration_ready,
            "product_pilot_started": self.product_pilot_started,
            "remote_write_authorized": self.remote_write_authorized,
            "push_authorized": self.push_authorized,
            "pr_mutation_authorized": self.pr_mutation_authorized,
            "merge_authorized": self.merge_authorized,
            "release_authorized": self.release_authorized,
            "deploy_authorized": self.deploy_authorized,
            "production_activation_authorized": self.production_activation_authorized,
            "authority": self.authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PilotExactTaskLocalCommitAuthorizationProof:
    authorization_sha256: str
    signature_sha256: str
    key_id: str
    issuer_actor_id: str
    issuer_system_id: str
    authorization: PilotExactTaskLocalCommitAuthorization
    local_commit_write_requirements_sha256: str
    local_commit_object_identity_sha256: str
    execution_nonce_sha256: str
    local_write_nonce_sha256: str
    predicted_commit_sha: str
    verified_at_utc: str
    one_shot_local_write_required: bool = True
    local_write_authorization_consumed: bool = False
    human_local_commit_authorization_verified: bool = True
    git_object_write_authorized: bool = False
    local_ref_update_authorized: bool = False
    local_commit_authorized: bool = False
    local_commit_created: bool = False
    integration_ready: bool = False
    product_pilot_started: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_PROOF_AUTHORITY
    schema: str = PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_PROOF_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_PROOF_SCHEMA:
            raise PilotExactTaskLocalCommitAuthorizationError(
                "local commit authorization proof schema unsupported"
            )
        for name in (
            "authorization_sha256",
            "signature_sha256",
            "local_commit_write_requirements_sha256",
            "local_commit_object_identity_sha256",
            "execution_nonce_sha256",
            "local_write_nonce_sha256",
        ):
            _hex(getattr(self, name), name=name)
        _hex(self.predicted_commit_sha, name="predicted_commit_sha", pattern=_HEX40)
        _identifier(self.key_id, name="key_id")
        _actor(self.issuer_actor_id, name="issuer_actor_id")
        _identifier(self.issuer_system_id, name="issuer_system_id")
        if self.issuer_system_id != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ISSUER_SYSTEM_ID:
            raise PilotExactTaskLocalCommitAuthorizationError(
                "local commit authorization proof issuer system invalid"
            )
        if type(self.authorization) is not PilotExactTaskLocalCommitAuthorization:
            raise PilotExactTaskLocalCommitAuthorizationError(
                "exact PilotExactTaskLocalCommitAuthorization is required"
            )
        replayed = PilotExactTaskLocalCommitAuthorization.from_mapping(
            self.authorization.to_dict()
        )
        if replayed != self.authorization:
            raise PilotExactTaskLocalCommitAuthorizationError(
                "local commit authorization proof replay identity mismatch"
            )
        if self.authorization_sha256 != self.authorization.sha256:
            raise PilotExactTaskLocalCommitAuthorizationError(
                "local commit authorization proof payload hash mismatch"
            )
        expected = {
            "local_commit_write_requirements_sha256": self.authorization.local_commit_write_requirements_sha256,
            "local_commit_object_identity_sha256": self.authorization.local_commit_object_identity_sha256,
            "execution_nonce_sha256": self.authorization.execution_nonce_sha256,
            "local_write_nonce_sha256": self.authorization.local_write_nonce_sha256,
            "predicted_commit_sha": self.authorization.predicted_commit_sha,
        }
        mismatch = next(
            (name for name, value in expected.items() if getattr(self, name) != value),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskLocalCommitAuthorizationError(
                f"local commit authorization proof binding mismatch: {mismatch}"
            )
        if self.issuer_actor_id != self.authorization.local_commit_authorizer_actor_id:
            raise PilotExactTaskLocalCommitAuthorizationError(
                "local commit authorization proof signer mismatch"
            )
        verified = _utc(self.verified_at_utc, name="verified_at_utc")
        authorized = _utc(self.authorization.authorized_at_utc, name="authorized_at_utc")
        expires = _utc(self.authorization.expires_at_utc, name="expires_at_utc")
        if verified < authorized or verified > expires:
            raise PilotExactTaskLocalCommitAuthorizationError(
                "local commit authorization proof verified outside authorization window"
            )
        if (
            self.one_shot_local_write_required is not True
            or self.local_write_authorization_consumed is not False
            or self.human_local_commit_authorization_verified is not True
            or self.git_object_write_authorized is not False
            or self.local_ref_update_authorized is not False
            or self.local_commit_authorized is not False
            or self.local_commit_created is not False
            or self.integration_ready is not False
            or self.product_pilot_started is not False
            or self.remote_write_authorized is not False
            or self.push_authorized is not False
            or self.pr_mutation_authorized is not False
            or self.merge_authorized is not False
            or self.release_authorized is not False
            or self.deploy_authorized is not False
            or self.production_activation_authorized is not False
            or self.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_PROOF_AUTHORITY
        ):
            raise PilotExactTaskLocalCommitAuthorizationError(
                "local commit authorization proof authority boundary is invalid"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskLocalCommitAuthorizationProof":
        data = dict(_strict(value, fields=_PROOF_FIELDS, name="authorization proof"))
        if not isinstance(data.get("authorization"), Mapping):
            raise PilotExactTaskLocalCommitAuthorizationError(
                "authorization must be an object"
            )
        data["authorization"] = PilotExactTaskLocalCommitAuthorization.from_mapping(
            data["authorization"]
        )
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "authorization_sha256": self.authorization_sha256,
            "signature_sha256": self.signature_sha256,
            "key_id": self.key_id,
            "issuer_actor_id": self.issuer_actor_id,
            "issuer_system_id": self.issuer_system_id,
            "authorization": self.authorization.to_dict(),
            "local_commit_write_requirements_sha256": self.local_commit_write_requirements_sha256,
            "local_commit_object_identity_sha256": self.local_commit_object_identity_sha256,
            "execution_nonce_sha256": self.execution_nonce_sha256,
            "local_write_nonce_sha256": self.local_write_nonce_sha256,
            "predicted_commit_sha": self.predicted_commit_sha,
            "verified_at_utc": self.verified_at_utc,
            "one_shot_local_write_required": self.one_shot_local_write_required,
            "local_write_authorization_consumed": self.local_write_authorization_consumed,
            "human_local_commit_authorization_verified": self.human_local_commit_authorization_verified,
            "git_object_write_authorized": self.git_object_write_authorized,
            "local_ref_update_authorized": self.local_ref_update_authorized,
            "local_commit_authorized": self.local_commit_authorized,
            "local_commit_created": self.local_commit_created,
            "integration_ready": self.integration_ready,
            "product_pilot_started": self.product_pilot_started,
            "remote_write_authorized": self.remote_write_authorized,
            "push_authorized": self.push_authorized,
            "pr_mutation_authorized": self.pr_mutation_authorized,
            "merge_authorized": self.merge_authorized,
            "release_authorized": self.release_authorized,
            "deploy_authorized": self.deploy_authorized,
            "production_activation_authorized": self.production_activation_authorized,
            "authority": self.authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def build_pilot_exact_task_local_commit_authorization(
    *,
    local_commit_write_requirements: PilotExactTaskLocalCommitWriteRequirements,
    authorization_id: str,
    local_commit_authorizer_actor_id: str,
    authorized_at_utc: str,
    expires_at_utc: str,
    local_write_nonce_sha256: str,
    notes: Sequence[str] = (),
) -> PilotExactTaskLocalCommitAuthorization:
    requirements = _require_requirements(local_commit_write_requirements)
    return PilotExactTaskLocalCommitAuthorization(
        authorization_id=authorization_id,
        local_commit_write_requirements=requirements,
        local_commit_authorizer_actor_id=local_commit_authorizer_actor_id,
        authorized_at_utc=authorized_at_utc,
        expires_at_utc=expires_at_utc,
        local_write_nonce_sha256=local_write_nonce_sha256,
        notes=_notes(notes),
        **_expected_binding(requirements),
    )


def _verify_pilot_exact_task_local_commit_authorization(
    *,
    local_commit_write_requirements: PilotExactTaskLocalCommitWriteRequirements,
    authorization: PilotExactTaskLocalCommitAuthorization,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_provider: Callable[[], str],
) -> PilotExactTaskLocalCommitAuthorizationProof:
    requirements = _require_requirements(local_commit_write_requirements)
    if type(authorization) is not PilotExactTaskLocalCommitAuthorization:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "exact PilotExactTaskLocalCommitAuthorization is required"
        )
    replayed = PilotExactTaskLocalCommitAuthorization.from_mapping(authorization.to_dict())
    if replayed != authorization or replayed.sha256 != authorization.sha256:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "local commit authorization replay identity mismatch"
        )
    if (
        authorization.local_commit_write_requirements_sha256 != requirements.sha256
        or authorization.local_commit_write_requirements != requirements
    ):
        raise PilotExactTaskLocalCommitAuthorizationError(
            "authorization is not exactly bound to supplied requirements"
        )
    if not isinstance(signature, DetachedEd25519AuthoritySignature):
        raise PilotExactTaskLocalCommitAuthorizationError(
            "detached Ed25519 human local-commit signature is required"
        )
    if not isinstance(verifier, Ed25519AuthorityVerifier):
        raise PilotExactTaskLocalCommitAuthorizationError(
            "Ed25519 local-commit-authority verifier is required"
        )
    if signature.issuer_system_id != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ISSUER_SYSTEM_ID:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "local commit signature belongs to another issuer system"
        )
    if signature.issuer_actor_id != authorization.local_commit_authorizer_actor_id:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "local commit signer must be the local commit authorizer"
        )
    if signature.signed_at_utc != authorization.authorized_at_utc:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "local commit signature time does not match authorization"
        )
    verified_at = now_provider()
    verified = _utc(verified_at, name="verification time")
    authorized = _utc(authorization.authorized_at_utc, name="authorized_at_utc")
    expires = _utc(authorization.expires_at_utc, name="expires_at_utc")
    if verified < authorized or verified > expires:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "human local commit authorization is not currently valid"
        )
    try:
        verified_payload_sha256 = verifier.verify(
            payload=authorization.canonical_json().encode("utf-8"),
            signature=signature,
            at_utc=verified_at,
        )
    except AsymmetricAuthorityError as exc:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "human local commit authority verification failed"
        ) from exc
    if verified_payload_sha256 != authorization.sha256:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "verified human local commit payload hash mismatch"
        )
    return PilotExactTaskLocalCommitAuthorizationProof(
        authorization_sha256=authorization.sha256,
        signature_sha256=signature.sha256,
        key_id=signature.key_id,
        issuer_actor_id=signature.issuer_actor_id,
        issuer_system_id=signature.issuer_system_id,
        authorization=authorization,
        local_commit_write_requirements_sha256=authorization.local_commit_write_requirements_sha256,
        local_commit_object_identity_sha256=authorization.local_commit_object_identity_sha256,
        execution_nonce_sha256=authorization.execution_nonce_sha256,
        local_write_nonce_sha256=authorization.local_write_nonce_sha256,
        predicted_commit_sha=authorization.predicted_commit_sha,
        verified_at_utc=verified_at,
    )


def verify_pilot_exact_task_local_commit_authorization(
    *,
    local_commit_write_requirements: PilotExactTaskLocalCommitWriteRequirements,
    authorization: PilotExactTaskLocalCommitAuthorization,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier | None = None,
) -> PilotExactTaskLocalCommitAuthorizationProof:
    if verifier is None:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "local-commit-authority verifier is unavailable outside production facade"
        )
    return _verify_pilot_exact_task_local_commit_authorization(
        local_commit_write_requirements=local_commit_write_requirements,
        authorization=authorization,
        signature=signature,
        verifier=verifier,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_SCHEMA",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_PROOF_SCHEMA",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_AUTHORITY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_PROOF_AUTHORITY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ISSUER_SYSTEM_ID",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_INTENT",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_MAX_WINDOW_SECONDS",
    "PilotExactTaskLocalCommitAuthorizationError",
    "PilotExactTaskLocalCommitAuthorization",
    "PilotExactTaskLocalCommitAuthorizationProof",
    "build_pilot_exact_task_local_commit_authorization",
    "verify_pilot_exact_task_local_commit_authorization",
]
