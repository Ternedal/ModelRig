"""Human-signed authorization for one later exact DC-L16 task execution.

ADR-DC-030 verifies fresh human intent over one exact ADR-DC-029 requirements
manifest.  The verified proof is deliberately not an execution admission: it
does not consume the intent, authorize the executor, start a task, create a
commit, mutate Git/GitHub or grant publication/production authority.
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
from .improvement_pilot_exact_task_execution_admission_requirements import (
    PILOT_EXACT_TASK_EXECUTION_ADMISSION_REQUIREMENTS_AUTHORITY,
    PilotExactTaskExecutionAdmissionRequirements,
)

PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-execution-human-authorization/v1"
)
PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_PROOF_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-execution-human-authorization-proof/v1"
)
PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_AUTHORITY = (
    "dc-l16-exact-task-execution-human-authorization-claim-only"
)
PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_PROOF_AUTHORITY = (
    "verified-human-dc-l16-exact-task-execution-authorization-only"
)
PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_ISSUER_SYSTEM_ID = (
    "kaliv-rsi-dc-l16-exact-task-execution-human-authority-v1"
)
PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_INTENT = (
    "authorize-one-exact-task-execution"
)
PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_MAX_WINDOW_SECONDS = 10 * 60

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_BINDING_FIELDS = (
    "execution_requirements_sha256",
    "admission_attestation_proof_sha256",
    "admission_attestation_sha256",
    "admission_attestation_signature_sha256",
    "admission_packet_sha256",
    "start_receipt_sha256",
    "repository",
    "base_sha",
    "requested_main_sha",
    "trial_id",
    "operator_surface",
    "selected_pilot_task_id",
    "workspace_root_path_sha256",
    "local_commits_allowed_by_human_scope",
)

_AUTHORIZATION_FIELDS = {
    "schema",
    "authorization_id",
    "execution_requirements",
    *_BINDING_FIELDS,
    "execution_authorizer_actor_id",
    "authorized_at_utc",
    "expires_at_utc",
    "execution_nonce_sha256",
    "notes",
    "human_execution_intent",
    "one_shot_execution_required",
    "execution_authorization_consumed",
    "human_task_execution_authorization_verified",
    "task_execution_admission_observed",
    "task_execution_authorized",
    "task_execution_started",
    "integration_ready",
    "product_pilot_started",
    "local_commit_authorized",
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
    "execution_requirements_sha256",
    "admission_attestation_proof_sha256",
    "admission_attestation_signature_sha256",
    "start_receipt_sha256",
    "execution_nonce_sha256",
    "verified_at_utc",
    "one_shot_execution_required",
    "execution_authorization_consumed",
    "human_task_execution_authorization_verified",
    "task_execution_admission_observed",
    "task_execution_authorized",
    "task_execution_started",
    "integration_ready",
    "product_pilot_started",
    "local_commit_authorized",
    "remote_write_authorized",
    "push_authorized",
    "pr_mutation_authorized",
    "merge_authorized",
    "release_authorized",
    "deploy_authorized",
    "production_activation_authorized",
    "authority",
}


class PilotExactTaskExecutionAuthorizationError(ValueError):
    """Exact-task human execution authorization is malformed or unsafe."""


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
        raise PilotExactTaskExecutionAuthorizationError(
            "exact-task execution authorization is not canonical JSON"
        ) from exc


def _strict(value: Any, *, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PilotExactTaskExecutionAuthorizationError(f"{name} fields mismatch")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskExecutionAuthorizationError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise PilotExactTaskExecutionAuthorizationError(f"{name} is invalid")
    return value


def _hex(value: Any, *, name: str, pattern: re.Pattern[str] = _HEX64) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PilotExactTaskExecutionAuthorizationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskExecutionAuthorizationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskExecutionAuthorizationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _notes(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PilotExactTaskExecutionAuthorizationError("authorization notes must be an array")
    items = tuple(value)
    if len(items) > 16:
        raise PilotExactTaskExecutionAuthorizationError("authorization has too many notes")
    for item in items:
        if (
            not isinstance(item, str)
            or not item
            or item.strip() != item
            or "\x00" in item
            or len(item.encode("utf-8")) > 2_048
        ):
            raise PilotExactTaskExecutionAuthorizationError("authorization note is invalid")
    if len(items) != len(set(items)):
        raise PilotExactTaskExecutionAuthorizationError("authorization notes must be unique")
    return items


def _require_requirements(value: Any) -> PilotExactTaskExecutionAdmissionRequirements:
    if type(value) is not PilotExactTaskExecutionAdmissionRequirements:
        raise PilotExactTaskExecutionAuthorizationError(
            "exact ADR-DC-029 PilotExactTaskExecutionAdmissionRequirements is required"
        )
    try:
        replayed = PilotExactTaskExecutionAdmissionRequirements.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskExecutionAuthorizationError(
            "ADR-DC-029 requirements replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskExecutionAuthorizationError(
            "ADR-DC-029 requirements replay identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_EXECUTION_ADMISSION_REQUIREMENTS_AUTHORITY
        or value.fresh_human_task_execution_authorization_required is not True
        or value.one_shot_execution_nonce_required is not True
        or value.host_local_execution_admission_ledger_required is not True
        or value.task_execution_admission_observed is not False
        or value.task_execution_authorized is not False
        or value.task_execution_started is not False
        or value.local_commit_authorized is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskExecutionAuthorizationError(
            "human execution authorization requires inert exact ADR-DC-029 requirements"
        )
    return value


def _start_authorizer_actor_id(
    requirements: PilotExactTaskExecutionAdmissionRequirements,
) -> str:
    exact = _require_requirements(requirements)
    try:
        return (
            exact.admission_attestation_proof.attestation.packet.admission_requirements
            .start_receipt.authorization_proof.authorization.start_authorizer_actor_id
        )
    except AttributeError as exc:
        raise PilotExactTaskExecutionAuthorizationError(
            "upstream human start-authority provenance is unavailable"
        ) from exc


def _expected_binding(
    requirements: PilotExactTaskExecutionAdmissionRequirements,
) -> dict[str, Any]:
    exact = _require_requirements(requirements)
    return {
        "execution_requirements_sha256": exact.sha256,
        "admission_attestation_proof_sha256": exact.admission_attestation_proof_sha256,
        "admission_attestation_sha256": exact.admission_attestation_sha256,
        "admission_attestation_signature_sha256": (
            exact.admission_attestation_signature_sha256
        ),
        "admission_packet_sha256": exact.admission_packet_sha256,
        "start_receipt_sha256": exact.start_receipt_sha256,
        "repository": exact.repository,
        "base_sha": exact.base_sha,
        "requested_main_sha": exact.requested_main_sha,
        "trial_id": exact.trial_id,
        "operator_surface": exact.operator_surface,
        "selected_pilot_task_id": exact.selected_pilot_task_id,
        "workspace_root_path_sha256": exact.workspace_root_path_sha256,
        "local_commits_allowed_by_human_scope": (
            exact.local_commits_allowed_by_human_scope
        ),
    }


@dataclass(frozen=True, slots=True)
class PilotExactTaskExecutionAuthorization:
    authorization_id: str
    execution_requirements: PilotExactTaskExecutionAdmissionRequirements
    execution_requirements_sha256: str
    admission_attestation_proof_sha256: str
    admission_attestation_sha256: str
    admission_attestation_signature_sha256: str
    admission_packet_sha256: str
    start_receipt_sha256: str
    repository: str
    base_sha: str
    requested_main_sha: str
    trial_id: str
    operator_surface: str
    selected_pilot_task_id: str
    workspace_root_path_sha256: str
    local_commits_allowed_by_human_scope: bool
    execution_authorizer_actor_id: str
    authorized_at_utc: str
    expires_at_utc: str
    execution_nonce_sha256: str
    notes: tuple[str, ...]
    human_execution_intent: str = PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_INTENT
    one_shot_execution_required: bool = True
    execution_authorization_consumed: bool = False
    human_task_execution_authorization_verified: bool = False
    task_execution_admission_observed: bool = False
    task_execution_authorized: bool = False
    task_execution_started: bool = False
    integration_ready: bool = False
    product_pilot_started: bool = False
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_SCHEMA:
            raise PilotExactTaskExecutionAuthorizationError("authorization schema unsupported")
        _identifier(self.authorization_id, name="authorization_id")
        requirements = _require_requirements(self.execution_requirements)
        for name in (
            "execution_requirements_sha256",
            "admission_attestation_proof_sha256",
            "admission_attestation_sha256",
            "admission_attestation_signature_sha256",
            "admission_packet_sha256",
            "start_receipt_sha256",
            "workspace_root_path_sha256",
            "execution_nonce_sha256",
        ):
            _hex(getattr(self, name), name=name)
        for name in ("base_sha", "requested_main_sha"):
            _hex(getattr(self, name), name=name, pattern=_HEX40)
        for name in ("trial_id", "operator_surface", "selected_pilot_task_id"):
            _identifier(getattr(self, name), name=name)
        _actor(self.execution_authorizer_actor_id, name="execution_authorizer_actor_id")
        if self.repository != "Ternedal/ModelRig":
            raise PilotExactTaskExecutionAuthorizationError("repository is unsupported")
        if type(self.local_commits_allowed_by_human_scope) is not bool:
            raise PilotExactTaskExecutionAuthorizationError(
                "local_commits_allowed_by_human_scope must be boolean"
            )
        _notes(self.notes)
        expected = _expected_binding(requirements)
        mismatch = next(
            (name for name, item in expected.items() if getattr(self, name) != item),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskExecutionAuthorizationError(
                f"exact-task execution authorization binding mismatch: {mismatch}"
            )
        if self.execution_authorizer_actor_id != _start_authorizer_actor_id(requirements):
            raise PilotExactTaskExecutionAuthorizationError(
                "execution authorizer must be the same human who authorized pilot start"
            )
        if self.execution_authorizer_actor_id == requirements.admission_attestation_proof.issuer_actor_id:
            raise PilotExactTaskExecutionAuthorizationError(
                "human execution authority must be distinct from the host attestor"
            )
        if self.execution_nonce_sha256 == "0" * 64:
            raise PilotExactTaskExecutionAuthorizationError(
                "execution nonce must not be a placeholder"
            )
        upstream_start_nonce = (
            requirements.admission_attestation_proof.attestation.packet
            .admission_requirements.start_nonce_sha256
        )
        if self.execution_nonce_sha256 == upstream_start_nonce:
            raise PilotExactTaskExecutionAuthorizationError(
                "execution nonce must be distinct from the consumed pilot-start nonce"
            )
        authorized = _utc(self.authorized_at_utc, name="authorized_at_utc")
        expires = _utc(self.expires_at_utc, name="expires_at_utc")
        admission_verified = _utc(
            requirements.admission_attestation_proof.verified_at_utc,
            name="admission attestation verified_at_utc",
        )
        if authorized < admission_verified:
            raise PilotExactTaskExecutionAuthorizationError(
                "execution authorization predates ADR-DC-028 verification"
            )
        if expires <= authorized:
            raise PilotExactTaskExecutionAuthorizationError("authorization expiry is invalid")
        if expires - authorized > timedelta(
            seconds=PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_MAX_WINDOW_SECONDS
        ):
            raise PilotExactTaskExecutionAuthorizationError(
                "execution authorization window exceeds the maximum"
            )
        if self.human_execution_intent != PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_INTENT:
            raise PilotExactTaskExecutionAuthorizationError("human execution intent unsupported")
        if (
            self.one_shot_execution_required is not True
            or self.execution_authorization_consumed is not False
            or self.human_task_execution_authorization_verified is not False
            or self.task_execution_admission_observed is not False
            or self.task_execution_authorized is not False
            or self.task_execution_started is not False
            or self.integration_ready is not False
            or self.product_pilot_started is not False
            or self.local_commit_authorized is not False
            or self.remote_write_authorized is not False
            or self.push_authorized is not False
            or self.pr_mutation_authorized is not False
            or self.merge_authorized is not False
            or self.release_authorized is not False
            or self.deploy_authorized is not False
            or self.production_activation_authorized is not False
            or self.authority != PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_AUTHORITY
        ):
            raise PilotExactTaskExecutionAuthorizationError(
                "execution authorization claim authority boundary is invalid"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskExecutionAuthorization":
        data = dict(_strict(value, fields=_AUTHORIZATION_FIELDS, name="authorization"))
        if not isinstance(data.get("execution_requirements"), Mapping):
            raise PilotExactTaskExecutionAuthorizationError(
                "execution_requirements must be an object"
            )
        if not isinstance(data.get("notes"), list):
            raise PilotExactTaskExecutionAuthorizationError("notes must be an array")
        data["execution_requirements"] = (
            PilotExactTaskExecutionAdmissionRequirements.from_mapping(
                data["execution_requirements"]
            )
        )
        data["notes"] = tuple(data["notes"])
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "authorization_id": self.authorization_id,
            "execution_requirements": self.execution_requirements.to_dict(),
            **{name: getattr(self, name) for name in _BINDING_FIELDS},
            "execution_authorizer_actor_id": self.execution_authorizer_actor_id,
            "authorized_at_utc": self.authorized_at_utc,
            "expires_at_utc": self.expires_at_utc,
            "execution_nonce_sha256": self.execution_nonce_sha256,
            "notes": list(self.notes),
            "human_execution_intent": self.human_execution_intent,
            "one_shot_execution_required": self.one_shot_execution_required,
            "execution_authorization_consumed": self.execution_authorization_consumed,
            "human_task_execution_authorization_verified": self.human_task_execution_authorization_verified,
            "task_execution_admission_observed": self.task_execution_admission_observed,
            "task_execution_authorized": self.task_execution_authorized,
            "task_execution_started": self.task_execution_started,
            "integration_ready": self.integration_ready,
            "product_pilot_started": self.product_pilot_started,
            "local_commit_authorized": self.local_commit_authorized,
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
class PilotExactTaskExecutionAuthorizationProof:
    authorization_sha256: str
    signature_sha256: str
    key_id: str
    issuer_actor_id: str
    issuer_system_id: str
    authorization: PilotExactTaskExecutionAuthorization
    execution_requirements_sha256: str
    admission_attestation_proof_sha256: str
    admission_attestation_signature_sha256: str
    start_receipt_sha256: str
    execution_nonce_sha256: str
    verified_at_utc: str
    one_shot_execution_required: bool = True
    execution_authorization_consumed: bool = False
    human_task_execution_authorization_verified: bool = True
    task_execution_admission_observed: bool = False
    task_execution_authorized: bool = False
    task_execution_started: bool = False
    integration_ready: bool = False
    product_pilot_started: bool = False
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_PROOF_AUTHORITY
    schema: str = PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_PROOF_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_PROOF_SCHEMA:
            raise PilotExactTaskExecutionAuthorizationError("proof schema unsupported")
        for name in (
            "authorization_sha256",
            "signature_sha256",
            "execution_requirements_sha256",
            "admission_attestation_proof_sha256",
            "admission_attestation_signature_sha256",
            "start_receipt_sha256",
            "execution_nonce_sha256",
        ):
            _hex(getattr(self, name), name=name)
        _identifier(self.key_id, name="key_id")
        _actor(self.issuer_actor_id, name="issuer_actor_id")
        _identifier(self.issuer_system_id, name="issuer_system_id")
        if self.issuer_system_id != PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_ISSUER_SYSTEM_ID:
            raise PilotExactTaskExecutionAuthorizationError("proof issuer system invalid")
        if type(self.authorization) is not PilotExactTaskExecutionAuthorization:
            raise PilotExactTaskExecutionAuthorizationError(
                "exact PilotExactTaskExecutionAuthorization is required"
            )
        replayed = PilotExactTaskExecutionAuthorization.from_mapping(
            self.authorization.to_dict()
        )
        if replayed != self.authorization:
            raise PilotExactTaskExecutionAuthorizationError(
                "execution authorization proof replay identity mismatch"
            )
        if self.authorization_sha256 != self.authorization.sha256:
            raise PilotExactTaskExecutionAuthorizationError("proof payload hash mismatch")
        for name in (
            "execution_requirements_sha256",
            "admission_attestation_proof_sha256",
            "admission_attestation_signature_sha256",
            "start_receipt_sha256",
            "execution_nonce_sha256",
        ):
            if getattr(self, name) != getattr(self.authorization, name):
                raise PilotExactTaskExecutionAuthorizationError(
                    f"proof {name} binding mismatch"
                )
        if self.issuer_actor_id != self.authorization.execution_authorizer_actor_id:
            raise PilotExactTaskExecutionAuthorizationError("proof signer mismatch")
        verified = _utc(self.verified_at_utc, name="verified_at_utc")
        authorized = _utc(self.authorization.authorized_at_utc, name="authorized_at_utc")
        expires = _utc(self.authorization.expires_at_utc, name="expires_at_utc")
        if verified < authorized or verified > expires:
            raise PilotExactTaskExecutionAuthorizationError(
                "execution authorization proof verified outside authorization window"
            )
        if (
            self.one_shot_execution_required is not True
            or self.execution_authorization_consumed is not False
            or self.human_task_execution_authorization_verified is not True
            or self.task_execution_admission_observed is not False
            or self.task_execution_authorized is not False
            or self.task_execution_started is not False
            or self.integration_ready is not False
            or self.product_pilot_started is not False
            or self.local_commit_authorized is not False
            or self.remote_write_authorized is not False
            or self.push_authorized is not False
            or self.pr_mutation_authorized is not False
            or self.merge_authorized is not False
            or self.release_authorized is not False
            or self.deploy_authorized is not False
            or self.production_activation_authorized is not False
            or self.authority != PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_PROOF_AUTHORITY
        ):
            raise PilotExactTaskExecutionAuthorizationError(
                "execution authorization proof authority boundary is invalid"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskExecutionAuthorizationProof":
        data = dict(_strict(value, fields=_PROOF_FIELDS, name="authorization proof"))
        if not isinstance(data.get("authorization"), Mapping):
            raise PilotExactTaskExecutionAuthorizationError("authorization must be an object")
        data["authorization"] = PilotExactTaskExecutionAuthorization.from_mapping(
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
            "execution_requirements_sha256": self.execution_requirements_sha256,
            "admission_attestation_proof_sha256": self.admission_attestation_proof_sha256,
            "admission_attestation_signature_sha256": self.admission_attestation_signature_sha256,
            "start_receipt_sha256": self.start_receipt_sha256,
            "execution_nonce_sha256": self.execution_nonce_sha256,
            "verified_at_utc": self.verified_at_utc,
            "one_shot_execution_required": self.one_shot_execution_required,
            "execution_authorization_consumed": self.execution_authorization_consumed,
            "human_task_execution_authorization_verified": self.human_task_execution_authorization_verified,
            "task_execution_admission_observed": self.task_execution_admission_observed,
            "task_execution_authorized": self.task_execution_authorized,
            "task_execution_started": self.task_execution_started,
            "integration_ready": self.integration_ready,
            "product_pilot_started": self.product_pilot_started,
            "local_commit_authorized": self.local_commit_authorized,
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


def build_pilot_exact_task_execution_authorization(
    *,
    execution_requirements: PilotExactTaskExecutionAdmissionRequirements,
    authorization_id: str,
    execution_authorizer_actor_id: str,
    authorized_at_utc: str,
    expires_at_utc: str,
    execution_nonce_sha256: str,
    notes: Sequence[str] = (),
) -> PilotExactTaskExecutionAuthorization:
    requirements = _require_requirements(execution_requirements)
    return PilotExactTaskExecutionAuthorization(
        authorization_id=authorization_id,
        execution_requirements=requirements,
        execution_authorizer_actor_id=execution_authorizer_actor_id,
        authorized_at_utc=authorized_at_utc,
        expires_at_utc=expires_at_utc,
        execution_nonce_sha256=execution_nonce_sha256,
        notes=_notes(notes),
        **_expected_binding(requirements),
    )


def _verify_pilot_exact_task_execution_authorization(
    *,
    execution_requirements: PilotExactTaskExecutionAdmissionRequirements,
    authorization: PilotExactTaskExecutionAuthorization,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_provider: Callable[[], str],
) -> PilotExactTaskExecutionAuthorizationProof:
    requirements = _require_requirements(execution_requirements)
    if type(authorization) is not PilotExactTaskExecutionAuthorization:
        raise PilotExactTaskExecutionAuthorizationError(
            "exact PilotExactTaskExecutionAuthorization is required"
        )
    replayed = PilotExactTaskExecutionAuthorization.from_mapping(authorization.to_dict())
    if replayed != authorization or replayed.sha256 != authorization.sha256:
        raise PilotExactTaskExecutionAuthorizationError(
            "execution authorization replay identity mismatch"
        )
    if (
        authorization.execution_requirements_sha256 != requirements.sha256
        or authorization.execution_requirements != requirements
    ):
        raise PilotExactTaskExecutionAuthorizationError(
            "authorization is not exactly bound to supplied requirements"
        )
    if not isinstance(signature, DetachedEd25519AuthoritySignature):
        raise PilotExactTaskExecutionAuthorizationError(
            "detached Ed25519 human execution signature is required"
        )
    if not isinstance(verifier, Ed25519AuthorityVerifier):
        raise PilotExactTaskExecutionAuthorizationError(
            "Ed25519 execution-authority verifier is required"
        )
    if signature.issuer_system_id != PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_ISSUER_SYSTEM_ID:
        raise PilotExactTaskExecutionAuthorizationError(
            "execution signature belongs to another issuer system"
        )
    if signature.issuer_actor_id != authorization.execution_authorizer_actor_id:
        raise PilotExactTaskExecutionAuthorizationError(
            "execution signer must be the execution authorizer"
        )
    if signature.signed_at_utc != authorization.authorized_at_utc:
        raise PilotExactTaskExecutionAuthorizationError(
            "execution signature time does not match authorization"
        )
    verified_at = now_provider()
    verified = _utc(verified_at, name="verification time")
    authorized = _utc(authorization.authorized_at_utc, name="authorized_at_utc")
    expires = _utc(authorization.expires_at_utc, name="expires_at_utc")
    if verified < authorized or verified > expires:
        raise PilotExactTaskExecutionAuthorizationError(
            "human execution authorization is not currently valid"
        )
    try:
        verified_payload_sha256 = verifier.verify(
            payload=authorization.canonical_json().encode("utf-8"),
            signature=signature,
            at_utc=verified_at,
        )
    except AsymmetricAuthorityError as exc:
        raise PilotExactTaskExecutionAuthorizationError(
            "human execution authority verification failed"
        ) from exc
    if verified_payload_sha256 != authorization.sha256:
        raise PilotExactTaskExecutionAuthorizationError(
            "verified human execution payload hash mismatch"
        )
    return PilotExactTaskExecutionAuthorizationProof(
        authorization_sha256=authorization.sha256,
        signature_sha256=signature.sha256,
        key_id=signature.key_id,
        issuer_actor_id=signature.issuer_actor_id,
        issuer_system_id=signature.issuer_system_id,
        authorization=authorization,
        execution_requirements_sha256=authorization.execution_requirements_sha256,
        admission_attestation_proof_sha256=authorization.admission_attestation_proof_sha256,
        admission_attestation_signature_sha256=authorization.admission_attestation_signature_sha256,
        start_receipt_sha256=authorization.start_receipt_sha256,
        execution_nonce_sha256=authorization.execution_nonce_sha256,
        verified_at_utc=verified_at,
    )


def verify_pilot_exact_task_execution_authorization(
    *,
    execution_requirements: PilotExactTaskExecutionAdmissionRequirements,
    authorization: PilotExactTaskExecutionAuthorization,
    signature: DetachedEd25519AuthoritySignature,
    admission_attestation_signature: DetachedEd25519AuthoritySignature | None = None,
    verifier: Ed25519AuthorityVerifier | None = None,
) -> PilotExactTaskExecutionAuthorizationProof:
    if verifier is None:
        raise PilotExactTaskExecutionAuthorizationError(
            "execution-authority verifier is unavailable outside production facade"
        )
    return _verify_pilot_exact_task_execution_authorization(
        execution_requirements=execution_requirements,
        authorization=authorization,
        signature=signature,
        verifier=verifier,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_SCHEMA",
    "PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_PROOF_SCHEMA",
    "PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_AUTHORITY",
    "PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_PROOF_AUTHORITY",
    "PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_ISSUER_SYSTEM_ID",
    "PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_INTENT",
    "PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_MAX_WINDOW_SECONDS",
    "PilotExactTaskExecutionAuthorizationError",
    "PilotExactTaskExecutionAuthorization",
    "PilotExactTaskExecutionAuthorizationProof",
    "build_pilot_exact_task_execution_authorization",
    "verify_pilot_exact_task_execution_authorization",
]
