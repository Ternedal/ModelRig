"""ADR-DC-044 human-signed authorization for one exact local commit.

This layer verifies fresh human intent over one exact ADR-DC-043 requirements
manifest. The verified proof is deliberately not a write admission: it does not
consume the one-shot nonce, write Git objects, move refs, create a commit, push,
mutate a PR, merge, release, deploy, or activate production.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from .asymmetric_authority import (
    AsymmetricAuthorityError,
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
)
from .improvement_pilot_exact_task_local_commit_authorization_requirements import (
    PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_INTENT,
    PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_MAX_WINDOW_SECONDS,
    PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_REQUIREMENTS_AUTHORITY,
    PilotExactTaskLocalCommitAuthorizationRequirements,
)

PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-local-commit-human-authorization/v1"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_PROOF_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-local-commit-human-authorization-proof/v1"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_AUTHORITY = (
    "dc-l16-exact-task-local-commit-human-authorization-claim-only"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_PROOF_AUTHORITY = (
    "verified-human-dc-l16-exact-task-local-commit-authorization-only"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ISSUER_SYSTEM_ID = (
    "kaliv-rsi-dc-l16-exact-task-local-commit-human-authority-v1"
)

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_BINDING_FIELDS = (
    "authorization_requirements_sha256",
    "requirements_key_sha256",
    "local_commit_object_identity_sha256",
    "local_commit_plan_sha256",
    "post_execution_evaluation_sha256",
    "execution_transaction_sha256",
    "tier_a_receipt_sha256",
    "execution_nonce_sha256",
    "development_task_sha256",
    "task_id",
    "repository",
    "base_sha",
    "root_tree_sha",
    "predicted_commit_sha",
    "commit_payload_sha256",
    "index_manifest_sha256",
    "commit_subject_sha256",
)

_AUTHORIZATION_FIELDS = {
    "schema",
    "authorization_id",
    "authorization_requirements",
    *_BINDING_FIELDS,
    "local_commit_authorizer_actor_id",
    "authorized_at_utc",
    "expires_at_utc",
    "local_commit_nonce_sha256",
    "notes",
    "human_local_commit_intent",
    "one_shot_local_commit_required",
    "local_commit_authorization_consumed",
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
    "authorization_requirements_sha256",
    "requirements_key_sha256",
    "local_commit_object_identity_sha256",
    "predicted_commit_sha",
    "local_commit_nonce_sha256",
    "verified_at_utc",
    "one_shot_local_commit_required",
    "local_commit_authorization_consumed",
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
            "local-commit authorization is not canonical JSON"
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


def _hex(
    value: Any,
    *,
    name: str,
    pattern: re.Pattern[str] = _HEX64,
) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PilotExactTaskLocalCommitAuthorizationError(f"{name} is invalid")
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
            "authorization notes must be an array"
        )
    items = tuple(value)
    if len(items) > 16:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "authorization has too many notes"
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
                "authorization note is invalid"
            )
    if len(items) != len(set(items)):
        raise PilotExactTaskLocalCommitAuthorizationError(
            "authorization notes must be unique"
        )
    return items


def _require_requirements(
    value: Any,
) -> PilotExactTaskLocalCommitAuthorizationRequirements:
    if type(value) is not PilotExactTaskLocalCommitAuthorizationRequirements:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "exact ADR-DC-043 local-commit authorization requirements are required"
        )
    try:
        replayed = PilotExactTaskLocalCommitAuthorizationRequirements.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "ADR-DC-043 requirements replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "ADR-DC-043 requirements replay identity mismatch"
        )
    required_true = (
        "fresh_human_local_commit_authorization_required",
        "one_shot_local_commit_nonce_required",
        "host_local_authorization_replay_ledger_required",
        "host_local_commit_execution_ledger_required",
        "fresh_workspace_revalidation_before_write_required",
        "exact_parent_head_revalidation_required",
        "exact_index_manifest_revalidation_required",
        "exact_root_tree_identity_required",
        "exact_predicted_commit_identity_required",
        "manual_operator_invocation_required",
        "failure_after_consumption_burns_nonce_required",
        "remote_publication_forbidden",
    )
    forced_false = (
        "human_local_commit_authorization_verified",
        "local_commit_authorization_consumed",
        "git_object_write_authorized",
        "local_ref_update_authorized",
        "local_commit_authorized",
        "local_commit_created",
        "remote_write_authorized",
        "push_authorized",
        "pr_mutation_authorized",
        "merge_authorized",
        "release_authorized",
        "deploy_authorized",
        "production_activation_authorized",
    )
    if (
        value.authority
        != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_REQUIREMENTS_AUTHORITY
        or value.authorization_intent
        != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_INTENT
        or value.authorization_max_window_seconds
        != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_MAX_WINDOW_SECONDS
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
    ):
        raise PilotExactTaskLocalCommitAuthorizationError(
            "human local-commit authorization requires inert exact ADR-DC-043 requirements"
        )
    return value


def _expected_binding(
    requirements: PilotExactTaskLocalCommitAuthorizationRequirements,
) -> dict[str, Any]:
    exact = _require_requirements(requirements)
    return {
        "authorization_requirements_sha256": exact.sha256,
        "requirements_key_sha256": exact.requirements_key_sha256,
        "local_commit_object_identity_sha256": (
            exact.local_commit_object_identity_sha256
        ),
        "local_commit_plan_sha256": exact.local_commit_plan_sha256,
        "post_execution_evaluation_sha256": exact.post_execution_evaluation_sha256,
        "execution_transaction_sha256": exact.execution_transaction_sha256,
        "tier_a_receipt_sha256": exact.tier_a_receipt_sha256,
        "execution_nonce_sha256": exact.execution_nonce_sha256,
        "development_task_sha256": exact.development_task_sha256,
        "task_id": exact.task_id,
        "repository": exact.repository,
        "base_sha": exact.base_sha,
        "root_tree_sha": exact.root_tree_sha,
        "predicted_commit_sha": exact.predicted_commit_sha,
        "commit_payload_sha256": exact.commit_payload_sha256,
        "index_manifest_sha256": exact.index_manifest_sha256,
        "commit_subject_sha256": exact.commit_subject_sha256,
    }


@dataclass(frozen=True, slots=True)
class PilotExactTaskLocalCommitAuthorization:
    authorization_id: str
    authorization_requirements: PilotExactTaskLocalCommitAuthorizationRequirements
    authorization_requirements_sha256: str
    requirements_key_sha256: str
    local_commit_object_identity_sha256: str
    local_commit_plan_sha256: str
    post_execution_evaluation_sha256: str
    execution_transaction_sha256: str
    tier_a_receipt_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    task_id: str
    repository: str
    base_sha: str
    root_tree_sha: str
    predicted_commit_sha: str
    commit_payload_sha256: str
    index_manifest_sha256: str
    commit_subject_sha256: str
    local_commit_authorizer_actor_id: str
    authorized_at_utc: str
    expires_at_utc: str
    local_commit_nonce_sha256: str
    notes: tuple[str, ...]
    human_local_commit_intent: str = PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_INTENT
    one_shot_local_commit_required: bool = True
    local_commit_authorization_consumed: bool = False
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
                "authorization schema unsupported"
            )
        _identifier(self.authorization_id, name="authorization_id")
        requirements = _require_requirements(self.authorization_requirements)
        for name in (
            "authorization_requirements_sha256",
            "requirements_key_sha256",
            "local_commit_object_identity_sha256",
            "local_commit_plan_sha256",
            "post_execution_evaluation_sha256",
            "execution_transaction_sha256",
            "tier_a_receipt_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "commit_payload_sha256",
            "index_manifest_sha256",
            "commit_subject_sha256",
            "local_commit_nonce_sha256",
        ):
            _hex(getattr(self, name), name=name)
        for name in ("base_sha", "root_tree_sha", "predicted_commit_sha"):
            _hex(getattr(self, name), name=name, pattern=_HEX40)
        _actor(
            self.local_commit_authorizer_actor_id,
            name="local_commit_authorizer_actor_id",
        )
        if self.repository != "Ternedal/ModelRig":
            raise PilotExactTaskLocalCommitAuthorizationError(
                "repository is unsupported"
            )
        expected = _expected_binding(requirements)
        mismatch = next(
            (name for name, item in expected.items() if getattr(self, name) != item),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskLocalCommitAuthorizationError(
                f"local-commit authorization binding mismatch: {mismatch}"
            )
        if (
            self.local_commit_nonce_sha256 == "0" * 64
            or self.local_commit_nonce_sha256 == self.execution_nonce_sha256
            or self.local_commit_nonce_sha256 == self.requirements_key_sha256
        ):
            raise PilotExactTaskLocalCommitAuthorizationError(
                "local-commit nonce must be fresh and distinct"
            )
        _notes(self.notes)
        authorized = _utc(self.authorized_at_utc, name="authorized_at_utc")
        expires = _utc(self.expires_at_utc, name="expires_at_utc")
        requirements_time = _utc(
            requirements.requirements_materialized_at_utc,
            name="requirements_materialized_at_utc",
        )
        if authorized < requirements_time:
            raise PilotExactTaskLocalCommitAuthorizationError(
                "local-commit authorization predates ADR-DC-043 requirements"
            )
        if expires <= authorized:
            raise PilotExactTaskLocalCommitAuthorizationError(
                "local-commit authorization expiry is invalid"
            )
        if expires - authorized > timedelta(
            seconds=PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_MAX_WINDOW_SECONDS
        ):
            raise PilotExactTaskLocalCommitAuthorizationError(
                "local-commit authorization window exceeds the maximum"
            )
        if (
            self.human_local_commit_intent
            != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_INTENT
        ):
            raise PilotExactTaskLocalCommitAuthorizationError(
                "human local-commit intent unsupported"
            )
        if self.one_shot_local_commit_required is not True:
            raise PilotExactTaskLocalCommitAuthorizationError(
                "one-shot local-commit authorization is required"
            )
        forced_false = (
            "local_commit_authorization_consumed",
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
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskLocalCommitAuthorizationError(
                "authorization claim cannot grant or consume write authority"
            )
        if self.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_AUTHORITY:
            raise PilotExactTaskLocalCommitAuthorizationError(
                "authorization claim authority unsupported"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            name: (
                self.authorization_requirements.to_dict()
                if name == "authorization_requirements"
                else list(self.notes)
                if name == "notes"
                else getattr(self, name)
            )
            for name in self.__dataclass_fields__
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskLocalCommitAuthorization":
        data = _strict(value, fields=_AUTHORIZATION_FIELDS, name="authorization")
        mapped = dict(data)
        try:
            mapped["authorization_requirements"] = (
                PilotExactTaskLocalCommitAuthorizationRequirements.from_mapping(
                    mapped["authorization_requirements"]
                )
            )
            mapped["notes"] = tuple(mapped["notes"])
        except Exception as exc:
            raise PilotExactTaskLocalCommitAuthorizationError(
                "authorization nested evidence is invalid"
            ) from exc
        return cls(**mapped)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _require_authorization(value: Any) -> PilotExactTaskLocalCommitAuthorization:
    if type(value) is not PilotExactTaskLocalCommitAuthorization:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "exact local-commit authorization claim is required"
        )
    replayed = PilotExactTaskLocalCommitAuthorization.from_mapping(value.to_dict())
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "local-commit authorization claim replay mismatch"
        )
    return value


@dataclass(frozen=True, slots=True)
class PilotExactTaskLocalCommitAuthorizationProof:
    authorization_sha256: str
    signature_sha256: str
    key_id: str
    issuer_actor_id: str
    issuer_system_id: str
    authorization: PilotExactTaskLocalCommitAuthorization
    authorization_requirements_sha256: str
    requirements_key_sha256: str
    local_commit_object_identity_sha256: str
    predicted_commit_sha: str
    local_commit_nonce_sha256: str
    verified_at_utc: str
    one_shot_local_commit_required: bool = True
    local_commit_authorization_consumed: bool = False
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
                "authorization proof schema unsupported"
            )
        authorization = _require_authorization(self.authorization)
        for name in (
            "authorization_sha256",
            "signature_sha256",
            "authorization_requirements_sha256",
            "requirements_key_sha256",
            "local_commit_object_identity_sha256",
            "local_commit_nonce_sha256",
        ):
            _hex(getattr(self, name), name=name)
        _hex(self.predicted_commit_sha, name="predicted_commit_sha", pattern=_HEX40)
        _identifier(self.key_id, name="key_id")
        _actor(self.issuer_actor_id, name="issuer_actor_id")
        _identifier(self.issuer_system_id, name="issuer_system_id")
        verified = _utc(self.verified_at_utc, name="verified_at_utc")
        authorized = _utc(authorization.authorized_at_utc, name="authorized_at_utc")
        expires = _utc(authorization.expires_at_utc, name="expires_at_utc")
        expected = {
            "authorization_sha256": authorization.sha256,
            "authorization_requirements_sha256": (
                authorization.authorization_requirements_sha256
            ),
            "requirements_key_sha256": authorization.requirements_key_sha256,
            "local_commit_object_identity_sha256": (
                authorization.local_commit_object_identity_sha256
            ),
            "predicted_commit_sha": authorization.predicted_commit_sha,
            "local_commit_nonce_sha256": authorization.local_commit_nonce_sha256,
        }
        mismatch = next(
            (name for name, item in expected.items() if getattr(self, name) != item),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskLocalCommitAuthorizationError(
                f"authorization proof binding mismatch: {mismatch}"
            )
        if self.issuer_actor_id != authorization.local_commit_authorizer_actor_id:
            raise PilotExactTaskLocalCommitAuthorizationError(
                "authorization proof issuer actor mismatch"
            )
        if (
            self.issuer_system_id
            != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ISSUER_SYSTEM_ID
        ):
            raise PilotExactTaskLocalCommitAuthorizationError(
                "authorization proof issuer system mismatch"
            )
        if verified < authorized or verified >= expires:
            raise PilotExactTaskLocalCommitAuthorizationError(
                "authorization proof verification time is outside authorization window"
            )
        if (
            self.one_shot_local_commit_required is not True
            or self.human_local_commit_authorization_verified is not True
        ):
            raise PilotExactTaskLocalCommitAuthorizationError(
                "verified proof must preserve one-shot human approval"
            )
        forced_false = (
            "local_commit_authorization_consumed",
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
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskLocalCommitAuthorizationError(
                "verified human proof cannot grant or consume write authority"
            )
        if self.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_PROOF_AUTHORITY:
            raise PilotExactTaskLocalCommitAuthorizationError(
                "authorization proof authority unsupported"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            name: (
                self.authorization.to_dict()
                if name == "authorization"
                else getattr(self, name)
            )
            for name in self.__dataclass_fields__
        }

    @classmethod
    def from_mapping(
        cls,
        value: Any,
    ) -> "PilotExactTaskLocalCommitAuthorizationProof":
        data = _strict(value, fields=_PROOF_FIELDS, name="authorization proof")
        mapped = dict(data)
        try:
            mapped["authorization"] = PilotExactTaskLocalCommitAuthorization.from_mapping(
                mapped["authorization"]
            )
        except Exception as exc:
            raise PilotExactTaskLocalCommitAuthorizationError(
                "authorization proof nested claim is invalid"
            ) from exc
        return cls(**mapped)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def build_pilot_exact_task_local_commit_authorization(
    *,
    authorization_requirements: PilotExactTaskLocalCommitAuthorizationRequirements,
    authorization_id: str,
    local_commit_authorizer_actor_id: str,
    authorized_at_utc: str,
    expires_at_utc: str,
    local_commit_nonce_sha256: str,
    notes: Sequence[str] = (),
) -> PilotExactTaskLocalCommitAuthorization:
    requirements = _require_requirements(authorization_requirements)
    return PilotExactTaskLocalCommitAuthorization(
        authorization_id=authorization_id,
        authorization_requirements=requirements,
        **_expected_binding(requirements),
        local_commit_authorizer_actor_id=local_commit_authorizer_actor_id,
        authorized_at_utc=authorized_at_utc,
        expires_at_utc=expires_at_utc,
        local_commit_nonce_sha256=local_commit_nonce_sha256,
        notes=_notes(notes),
    )


def _verify_pilot_exact_task_local_commit_authorization(
    *,
    authorization: PilotExactTaskLocalCommitAuthorization,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_provider,
) -> PilotExactTaskLocalCommitAuthorizationProof:
    claim = _require_authorization(authorization)
    if type(signature) is not DetachedEd25519AuthoritySignature:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "detached Ed25519 local-commit authorization signature is required"
        )
    if not isinstance(verifier, Ed25519AuthorityVerifier):
        raise PilotExactTaskLocalCommitAuthorizationError(
            "Ed25519 local-commit authorization verifier is required"
        )
    if (
        signature.issuer_system_id
        != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ISSUER_SYSTEM_ID
    ):
        raise PilotExactTaskLocalCommitAuthorizationError(
            "local-commit authorization signature issuer system mismatch"
        )
    if signature.issuer_actor_id != claim.local_commit_authorizer_actor_id:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "local-commit authorization signature actor mismatch"
        )
    if signature.signed_at_utc != claim.authorized_at_utc:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "local-commit authorization signature time must equal authorization time"
        )
    payload = claim.canonical_json().encode("utf-8")
    if hashlib.sha256(payload).hexdigest() != signature.payload_sha256:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "local-commit authorization signature payload mismatch"
        )
    verified_at = now_provider()
    verified_time = _utc(verified_at, name="verified_at_utc")
    authorized_time = _utc(claim.authorized_at_utc, name="authorized_at_utc")
    expires_time = _utc(claim.expires_at_utc, name="expires_at_utc")
    if verified_time < authorized_time or verified_time >= expires_time:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "local-commit authorization is not currently fresh"
        )
    try:
        verifier.verify(
            payload=payload,
            signature=signature,
            at_utc=verified_at,
        )
    except AsymmetricAuthorityError as exc:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "local-commit human authorization signature verification failed"
        ) from exc
    proof = PilotExactTaskLocalCommitAuthorizationProof(
        authorization_sha256=claim.sha256,
        signature_sha256=signature.sha256,
        key_id=signature.key_id,
        issuer_actor_id=signature.issuer_actor_id,
        issuer_system_id=signature.issuer_system_id,
        authorization=claim,
        authorization_requirements_sha256=claim.authorization_requirements_sha256,
        requirements_key_sha256=claim.requirements_key_sha256,
        local_commit_object_identity_sha256=claim.local_commit_object_identity_sha256,
        predicted_commit_sha=claim.predicted_commit_sha,
        local_commit_nonce_sha256=claim.local_commit_nonce_sha256,
        verified_at_utc=verified_at,
    )
    replayed = PilotExactTaskLocalCommitAuthorizationProof.from_mapping(proof.to_dict())
    if replayed != proof or replayed.sha256 != proof.sha256:
        raise PilotExactTaskLocalCommitAuthorizationError(
            "local-commit authorization proof replay validation failed"
        )
    return proof


def verify_pilot_exact_task_local_commit_authorization(
    *,
    authorization: PilotExactTaskLocalCommitAuthorization,
    signature: DetachedEd25519AuthoritySignature,
) -> PilotExactTaskLocalCommitAuthorizationProof:
    raise PilotExactTaskLocalCommitAuthorizationError(
        "production local-commit authorization boundary is not installed"
    )


__all__ = [
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_SCHEMA",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_PROOF_SCHEMA",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_AUTHORITY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_PROOF_AUTHORITY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ISSUER_SYSTEM_ID",
    "PilotExactTaskLocalCommitAuthorizationError",
    "PilotExactTaskLocalCommitAuthorization",
    "PilotExactTaskLocalCommitAuthorizationProof",
    "build_pilot_exact_task_local_commit_authorization",
    "verify_pilot_exact_task_local_commit_authorization",
]
