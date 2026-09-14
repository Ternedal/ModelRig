"""Human-signed authorization for one exact DC-L16 pilot start.

ADR-DC-024 adds a fresh human authority boundary after one fully satisfied,
host-attested ADR-DC-023 runtime-preflight proof.  It authorizes only one future
start intent; it does not consume that intent, start product code, register a
command, execute a task, create a local commit, mutate Git/GitHub or grant any
remote/production authority.
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
from .improvement_pilot_runtime_preflight_attestation import (
    PILOT_RUNTIME_PREFLIGHT_ATTESTATION_PROOF_AUTHORITY,
    PilotRuntimePreflightAttestationProof,
)

PILOT_START_AUTHORIZATION_SCHEMA = "kaliv-rsi-dc-l16-pilot-start-authorization/v1"
PILOT_START_AUTHORIZATION_PROOF_SCHEMA = (
    "kaliv-rsi-dc-l16-pilot-start-authorization-proof/v1"
)
PILOT_START_AUTHORIZATION_AUTHORITY = "dc-l16-pilot-start-authorization-claim-only"
PILOT_START_AUTHORIZATION_PROOF_AUTHORITY = (
    "verified-human-dc-l16-pilot-start-authorization-only"
)
PILOT_START_AUTHORIZATION_ISSUER_SYSTEM_ID = (
    "kaliv-rsi-dc-l16-pilot-start-human-authority-v1"
)
PILOT_START_AUTHORIZATION_INTENT = "authorize-one-local-pilot-start"
PILOT_START_AUTHORIZATION_MAX_WINDOW_SECONDS = 15 * 60

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_BINDING_FIELDS = (
    "preflight_proof_sha256",
    "attestation_sha256",
    "packet_sha256",
    "selection_proof_sha256",
    "candidate_proof_sha256",
    "requirements_sha256",
    "trial_scope_sha256",
    "repository",
    "base_sha",
    "requested_main_sha",
    "trial_id",
    "operator_surface",
    "selected_pilot_task_id",
    "workspace_root_path_sha256",
    "local_commits_allowed",
    "observer_actor_id",
    "observer_host_id",
)

_AUTHORIZATION_FIELDS = {
    "schema",
    "authorization_id",
    "preflight_proof",
    *_BINDING_FIELDS,
    "start_authorizer_actor_id",
    "authorized_at_utc",
    "expires_at_utc",
    "start_nonce_sha256",
    "notes",
    "human_start_intent",
    "one_shot_start_required",
    "start_consumed",
    "integration_ready",
    "pilot_start_authorized",
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
    "preflight_proof_sha256",
    "attestation_sha256",
    "packet_sha256",
    "selection_proof_sha256",
    "candidate_proof_sha256",
    "requirements_sha256",
    "trial_scope_sha256",
    "start_nonce_sha256",
    "verified_at_utc",
    "one_shot_start_required",
    "start_consumed",
    "integration_ready",
    "pilot_start_authorized",
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


class PilotStartAuthorizationError(ValueError):
    """Pilot-start authorization is malformed, stale, untrusted or too broad."""


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
        raise PilotStartAuthorizationError(
            "pilot-start authorization is not canonical JSON"
        ) from exc


def _strict(value: Any, *, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PilotStartAuthorizationError(f"{name} fields mismatch")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotStartAuthorizationError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise PilotStartAuthorizationError(f"{name} is invalid")
    return value


def _hex(value: Any, *, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PilotStartAuthorizationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotStartAuthorizationError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotStartAuthorizationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _notes(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PilotStartAuthorizationError("authorization notes must be an array")
    items = tuple(value)
    if len(items) > 16:
        raise PilotStartAuthorizationError("authorization has too many notes")
    for item in items:
        if (
            not isinstance(item, str)
            or not item
            or item.strip() != item
            or "\x00" in item
            or len(item.encode("utf-8")) > 2_048
        ):
            raise PilotStartAuthorizationError("authorization note is invalid")
    if len(items) != len(set(items)):
        raise PilotStartAuthorizationError("authorization notes must be unique")
    return items


def _require_satisfied_preflight(
    value: Any,
) -> PilotRuntimePreflightAttestationProof:
    if type(value) is not PilotRuntimePreflightAttestationProof:
        raise PilotStartAuthorizationError(
            "exact PilotRuntimePreflightAttestationProof is required"
        )
    if (
        value.authority != PILOT_RUNTIME_PREFLIGHT_ATTESTATION_PROOF_AUTHORITY
        or value.host_attestation_verified is not True
        or value.preflight_observed is not True
        or value.preflight_satisfied is not True
        or value.integration_ready is not False
        or value.pilot_start_authorized is not False
        or value.product_pilot_started is not False
        or value.local_commit_authorized is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotStartAuthorizationError(
            "pilot-start authorization requires a fully satisfied inert ADR-DC-023 proof"
        )
    try:
        replayed = PilotRuntimePreflightAttestationProof.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotStartAuthorizationError(
            "runtime preflight attestation proof replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotStartAuthorizationError(
            "runtime preflight attestation proof replay identity mismatch"
        )
    return value


def _expected_binding(
    preflight: PilotRuntimePreflightAttestationProof,
) -> dict[str, Any]:
    packet = preflight.attestation.packet
    selection = packet.selection_proof
    candidate = selection.selection.candidate_proof
    requirements = packet.preflight_requirements
    return {
        "preflight_proof_sha256": preflight.sha256,
        "attestation_sha256": preflight.attestation_sha256,
        "packet_sha256": preflight.packet_sha256,
        "selection_proof_sha256": packet.selection_proof_sha256,
        "candidate_proof_sha256": selection.candidate_proof_sha256,
        "requirements_sha256": packet.preflight_requirements_sha256,
        "trial_scope_sha256": requirements.trial_scope_sha256,
        "repository": candidate.repository,
        "base_sha": candidate.base_sha,
        "requested_main_sha": candidate.requested_main_sha,
        "trial_id": candidate.trial_id,
        "operator_surface": candidate.operator_surface,
        "selected_pilot_task_id": candidate.selected_pilot_task_id,
        "workspace_root_path_sha256": candidate.workspace_root_path_sha256,
        "local_commits_allowed": candidate.local_commits_allowed,
        "observer_actor_id": packet.observer_actor_id,
        "observer_host_id": preflight.attestation.observer_host_id,
    }


@dataclass(frozen=True, slots=True)
class PilotStartAuthorization:
    authorization_id: str
    preflight_proof: PilotRuntimePreflightAttestationProof
    preflight_proof_sha256: str
    attestation_sha256: str
    packet_sha256: str
    selection_proof_sha256: str
    candidate_proof_sha256: str
    requirements_sha256: str
    trial_scope_sha256: str
    repository: str
    base_sha: str
    requested_main_sha: str
    trial_id: str
    operator_surface: str
    selected_pilot_task_id: str
    workspace_root_path_sha256: str
    local_commits_allowed: bool
    observer_actor_id: str
    observer_host_id: str
    start_authorizer_actor_id: str
    authorized_at_utc: str
    expires_at_utc: str
    start_nonce_sha256: str
    notes: tuple[str, ...]
    human_start_intent: str = PILOT_START_AUTHORIZATION_INTENT
    one_shot_start_required: bool = True
    start_consumed: bool = False
    integration_ready: bool = False
    pilot_start_authorized: bool = False
    product_pilot_started: bool = False
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_START_AUTHORIZATION_AUTHORITY
    schema: str = PILOT_START_AUTHORIZATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_START_AUTHORIZATION_SCHEMA:
            raise PilotStartAuthorizationError(
                "pilot-start authorization schema is unsupported"
            )
        _identifier(self.authorization_id, name="authorization_id")
        preflight = _require_satisfied_preflight(self.preflight_proof)
        for name, value, pattern in (
            ("preflight_proof_sha256", self.preflight_proof_sha256, _HEX64),
            ("attestation_sha256", self.attestation_sha256, _HEX64),
            ("packet_sha256", self.packet_sha256, _HEX64),
            ("selection_proof_sha256", self.selection_proof_sha256, _HEX64),
            ("candidate_proof_sha256", self.candidate_proof_sha256, _HEX64),
            ("requirements_sha256", self.requirements_sha256, _HEX64),
            ("trial_scope_sha256", self.trial_scope_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("requested_main_sha", self.requested_main_sha, _HEX40),
            ("workspace_root_path_sha256", self.workspace_root_path_sha256, _HEX64),
            ("start_nonce_sha256", self.start_nonce_sha256, _HEX64),
        ):
            _hex(value, name=name, pattern=pattern)
        if self.start_nonce_sha256 == "0" * 64:
            raise PilotStartAuthorizationError("start nonce must not be a placeholder")
        for name, value in (
            ("trial_id", self.trial_id),
            ("operator_surface", self.operator_surface),
            ("selected_pilot_task_id", self.selected_pilot_task_id),
            ("observer_host_id", self.observer_host_id),
        ):
            _identifier(value, name=name)
        _actor(self.observer_actor_id, name="observer_actor_id")
        _actor(self.start_authorizer_actor_id, name="start_authorizer_actor_id")
        if self.repository != "Ternedal/ModelRig":
            raise PilotStartAuthorizationError("repository is unsupported")
        if type(self.local_commits_allowed) is not bool:
            raise PilotStartAuthorizationError(
                "local_commits_allowed must be boolean"
            )
        _notes(self.notes)
        expected = _expected_binding(preflight)
        mismatch = next(
            (
                name
                for name, item in expected.items()
                if getattr(self, name) != item
            ),
            None,
        )
        if mismatch is not None:
            raise PilotStartAuthorizationError(
                f"pilot-start authorization binding mismatch: {mismatch}"
            )
        selection_actor = (
            preflight.attestation.packet.selection_proof.selection.selection_maker_actor_id
        )
        if self.start_authorizer_actor_id != selection_actor:
            raise PilotStartAuthorizationError(
                "pilot-start authorizer must be the human who signed the exact candidate selection"
            )
        if self.start_authorizer_actor_id == self.observer_actor_id:
            raise PilotStartAuthorizationError(
                "pilot-start human authority must be distinct from the preflight observer"
            )
        if self.start_authorizer_actor_id == preflight.issuer_actor_id:
            raise PilotStartAuthorizationError(
                "pilot-start human authority must be distinct from the host attestor"
            )
        authorized = _utc(self.authorized_at_utc, name="authorized_at_utc")
        expires = _utc(self.expires_at_utc, name="expires_at_utc")
        preflight_verified = _utc(
            preflight.verified_at_utc,
            name="preflight verified_at_utc",
        )
        if authorized < preflight_verified:
            raise PilotStartAuthorizationError(
                "pilot-start authorization predates preflight verification"
            )
        if expires <= authorized:
            raise PilotStartAuthorizationError(
                "pilot-start authorization expiry is invalid"
            )
        if expires - authorized > timedelta(
            seconds=PILOT_START_AUTHORIZATION_MAX_WINDOW_SECONDS
        ):
            raise PilotStartAuthorizationError(
                "pilot-start authorization window exceeds the maximum"
            )
        if self.human_start_intent != PILOT_START_AUTHORIZATION_INTENT:
            raise PilotStartAuthorizationError(
                "pilot-start authorization intent is unsupported"
            )
        if (
            self.one_shot_start_required is not True
            or self.start_consumed is not False
            or self.integration_ready is not False
            or self.pilot_start_authorized is not False
            or self.product_pilot_started is not False
            or self.local_commit_authorized is not False
            or self.remote_write_authorized is not False
            or self.push_authorized is not False
            or self.pr_mutation_authorized is not False
            or self.merge_authorized is not False
            or self.release_authorized is not False
            or self.deploy_authorized is not False
            or self.production_activation_authorized is not False
            or self.authority != PILOT_START_AUTHORIZATION_AUTHORITY
        ):
            raise PilotStartAuthorizationError(
                "pilot-start authorization claim authority boundary is invalid"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotStartAuthorization":
        data = dict(
            _strict(
                value,
                fields=_AUTHORIZATION_FIELDS,
                name="pilot-start authorization",
            )
        )
        if not isinstance(data.get("preflight_proof"), Mapping):
            raise PilotStartAuthorizationError(
                "preflight_proof must be an object"
            )
        if not isinstance(data.get("notes"), list):
            raise PilotStartAuthorizationError(
                "authorization notes must be an array"
            )
        data["preflight_proof"] = (
            PilotRuntimePreflightAttestationProof.from_mapping(
                data["preflight_proof"]
            )
        )
        data["notes"] = tuple(data["notes"])
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "authorization_id": self.authorization_id,
            "preflight_proof": self.preflight_proof.to_dict(),
            **{name: getattr(self, name) for name in _BINDING_FIELDS},
            "start_authorizer_actor_id": self.start_authorizer_actor_id,
            "authorized_at_utc": self.authorized_at_utc,
            "expires_at_utc": self.expires_at_utc,
            "start_nonce_sha256": self.start_nonce_sha256,
            "notes": list(self.notes),
            "human_start_intent": self.human_start_intent,
            "one_shot_start_required": self.one_shot_start_required,
            "start_consumed": self.start_consumed,
            "integration_ready": self.integration_ready,
            "pilot_start_authorized": self.pilot_start_authorized,
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
class PilotStartAuthorizationProof:
    authorization_sha256: str
    signature_sha256: str
    key_id: str
    issuer_actor_id: str
    issuer_system_id: str
    authorization: PilotStartAuthorization
    preflight_proof_sha256: str
    attestation_sha256: str
    packet_sha256: str
    selection_proof_sha256: str
    candidate_proof_sha256: str
    requirements_sha256: str
    trial_scope_sha256: str
    start_nonce_sha256: str
    verified_at_utc: str
    one_shot_start_required: bool = True
    start_consumed: bool = False
    integration_ready: bool = False
    pilot_start_authorized: bool = True
    product_pilot_started: bool = False
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_START_AUTHORIZATION_PROOF_AUTHORITY
    schema: str = PILOT_START_AUTHORIZATION_PROOF_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_START_AUTHORIZATION_PROOF_SCHEMA:
            raise PilotStartAuthorizationError(
                "pilot-start authorization proof schema is unsupported"
            )
        for name, value in (
            ("authorization_sha256", self.authorization_sha256),
            ("signature_sha256", self.signature_sha256),
            ("preflight_proof_sha256", self.preflight_proof_sha256),
            ("attestation_sha256", self.attestation_sha256),
            ("packet_sha256", self.packet_sha256),
            ("selection_proof_sha256", self.selection_proof_sha256),
            ("candidate_proof_sha256", self.candidate_proof_sha256),
            ("requirements_sha256", self.requirements_sha256),
            ("trial_scope_sha256", self.trial_scope_sha256),
            ("start_nonce_sha256", self.start_nonce_sha256),
        ):
            _hex(value, name=name, pattern=_HEX64)
        _identifier(self.key_id, name="key_id")
        _actor(self.issuer_actor_id, name="issuer_actor_id")
        _identifier(self.issuer_system_id, name="issuer_system_id")
        if self.issuer_system_id != PILOT_START_AUTHORIZATION_ISSUER_SYSTEM_ID:
            raise PilotStartAuthorizationError(
                "pilot-start proof issuer system is invalid"
            )
        if type(self.authorization) is not PilotStartAuthorization:
            raise PilotStartAuthorizationError(
                "exact PilotStartAuthorization is required"
            )
        if self.authorization_sha256 != self.authorization.sha256:
            raise PilotStartAuthorizationError(
                "pilot-start proof payload hash mismatch"
            )
        for name in (
            "preflight_proof_sha256",
            "attestation_sha256",
            "packet_sha256",
            "selection_proof_sha256",
            "candidate_proof_sha256",
            "requirements_sha256",
            "trial_scope_sha256",
            "start_nonce_sha256",
        ):
            if getattr(self, name) != getattr(self.authorization, name):
                raise PilotStartAuthorizationError(
                    f"pilot-start proof {name} binding mismatch"
                )
        if self.issuer_actor_id != self.authorization.start_authorizer_actor_id:
            raise PilotStartAuthorizationError(
                "pilot-start proof signer mismatch"
            )
        verified = _utc(self.verified_at_utc, name="verified_at_utc")
        authorized = _utc(
            self.authorization.authorized_at_utc,
            name="authorized_at_utc",
        )
        expires = _utc(
            self.authorization.expires_at_utc,
            name="expires_at_utc",
        )
        if verified < authorized or verified > expires:
            raise PilotStartAuthorizationError(
                "pilot-start proof was not verified inside the authorization window"
            )
        if (
            self.one_shot_start_required is not True
            or self.start_consumed is not False
            or self.integration_ready is not False
            or self.pilot_start_authorized is not True
            or self.product_pilot_started is not False
            or self.local_commit_authorized is not False
            or self.remote_write_authorized is not False
            or self.push_authorized is not False
            or self.pr_mutation_authorized is not False
            or self.merge_authorized is not False
            or self.release_authorized is not False
            or self.deploy_authorized is not False
            or self.production_activation_authorized is not False
            or self.authority != PILOT_START_AUTHORIZATION_PROOF_AUTHORITY
        ):
            raise PilotStartAuthorizationError(
                "pilot-start proof authority boundary is invalid"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotStartAuthorizationProof":
        data = dict(
            _strict(
                value,
                fields=_PROOF_FIELDS,
                name="pilot-start authorization proof",
            )
        )
        if not isinstance(data.get("authorization"), Mapping):
            raise PilotStartAuthorizationError(
                "authorization must be an object"
            )
        data["authorization"] = PilotStartAuthorization.from_mapping(
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
            "preflight_proof_sha256": self.preflight_proof_sha256,
            "attestation_sha256": self.attestation_sha256,
            "packet_sha256": self.packet_sha256,
            "selection_proof_sha256": self.selection_proof_sha256,
            "candidate_proof_sha256": self.candidate_proof_sha256,
            "requirements_sha256": self.requirements_sha256,
            "trial_scope_sha256": self.trial_scope_sha256,
            "start_nonce_sha256": self.start_nonce_sha256,
            "verified_at_utc": self.verified_at_utc,
            "one_shot_start_required": self.one_shot_start_required,
            "start_consumed": self.start_consumed,
            "integration_ready": self.integration_ready,
            "pilot_start_authorized": self.pilot_start_authorized,
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


def build_pilot_start_authorization(
    *,
    preflight_proof: PilotRuntimePreflightAttestationProof,
    authorization_id: str,
    start_authorizer_actor_id: str,
    authorized_at_utc: str,
    expires_at_utc: str,
    start_nonce_sha256: str,
    notes: Sequence[str] = (),
) -> PilotStartAuthorization:
    """Build exact externally-signable bytes; the claim itself authorizes nothing."""
    preflight = _require_satisfied_preflight(preflight_proof)
    binding = _expected_binding(preflight)
    return PilotStartAuthorization(
        authorization_id=authorization_id,
        preflight_proof=preflight,
        start_authorizer_actor_id=start_authorizer_actor_id,
        authorized_at_utc=authorized_at_utc,
        expires_at_utc=expires_at_utc,
        start_nonce_sha256=start_nonce_sha256,
        notes=_notes(notes),
        **binding,
    )


def _verify_pilot_start_authorization(
    *,
    preflight_proof: PilotRuntimePreflightAttestationProof,
    authorization: PilotStartAuthorization,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_provider: Callable[[], str],
) -> PilotStartAuthorizationProof:
    preflight = _require_satisfied_preflight(preflight_proof)
    if type(authorization) is not PilotStartAuthorization:
        raise PilotStartAuthorizationError(
            "exact PilotStartAuthorization is required"
        )
    if (
        authorization.preflight_proof_sha256 != preflight.sha256
        or authorization.preflight_proof != preflight
    ):
        raise PilotStartAuthorizationError(
            "pilot-start authorization is not exactly bound to supplied preflight proof"
        )
    if not isinstance(signature, DetachedEd25519AuthoritySignature):
        raise PilotStartAuthorizationError(
            "detached Ed25519 pilot-start signature is required"
        )
    if not isinstance(verifier, Ed25519AuthorityVerifier):
        raise PilotStartAuthorizationError(
            "Ed25519 pilot-start verifier is required"
        )
    if signature.issuer_system_id != PILOT_START_AUTHORIZATION_ISSUER_SYSTEM_ID:
        raise PilotStartAuthorizationError(
            "pilot-start signature belongs to another issuer system"
        )
    if signature.issuer_actor_id != authorization.start_authorizer_actor_id:
        raise PilotStartAuthorizationError(
            "pilot-start signer must be the start authorizer"
        )
    if signature.signed_at_utc != authorization.authorized_at_utc:
        raise PilotStartAuthorizationError(
            "pilot-start signature time does not match authorization"
        )
    verified_at = now_provider()
    verified = _utc(verified_at, name="pilot-start verification time")
    authorized = _utc(authorization.authorized_at_utc, name="authorized_at_utc")
    expires = _utc(authorization.expires_at_utc, name="expires_at_utc")
    if verified < authorized or verified > expires:
        raise PilotStartAuthorizationError(
            "pilot-start authorization is not currently valid"
        )
    try:
        verified_payload_sha256 = verifier.verify(
            payload=authorization.canonical_json().encode("utf-8"),
            signature=signature,
            at_utc=verified_at,
        )
    except AsymmetricAuthorityError as exc:
        raise PilotStartAuthorizationError(
            "pilot-start authority verification failed"
        ) from exc
    if verified_payload_sha256 != authorization.sha256:
        raise PilotStartAuthorizationError(
            "pilot-start verified payload hash mismatch"
        )
    return PilotStartAuthorizationProof(
        authorization_sha256=authorization.sha256,
        signature_sha256=signature.sha256,
        key_id=signature.key_id,
        issuer_actor_id=signature.issuer_actor_id,
        issuer_system_id=signature.issuer_system_id,
        authorization=authorization,
        preflight_proof_sha256=authorization.preflight_proof_sha256,
        attestation_sha256=authorization.attestation_sha256,
        packet_sha256=authorization.packet_sha256,
        selection_proof_sha256=authorization.selection_proof_sha256,
        candidate_proof_sha256=authorization.candidate_proof_sha256,
        requirements_sha256=authorization.requirements_sha256,
        trial_scope_sha256=authorization.trial_scope_sha256,
        start_nonce_sha256=authorization.start_nonce_sha256,
        verified_at_utc=verified_at,
    )


def verify_pilot_start_authorization(
    *,
    preflight_proof: PilotRuntimePreflightAttestationProof,
    authorization: PilotStartAuthorization,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier | None = None,
) -> PilotStartAuthorizationProof:
    """Injectable compatibility surface replaced by the production facade."""
    if verifier is None:
        raise PilotStartAuthorizationError(
            "pilot-start verifier is unavailable outside production facade"
        )
    return _verify_pilot_start_authorization(
        preflight_proof=preflight_proof,
        authorization=authorization,
        signature=signature,
        verifier=verifier,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_START_AUTHORIZATION_SCHEMA",
    "PILOT_START_AUTHORIZATION_PROOF_SCHEMA",
    "PILOT_START_AUTHORIZATION_AUTHORITY",
    "PILOT_START_AUTHORIZATION_PROOF_AUTHORITY",
    "PILOT_START_AUTHORIZATION_ISSUER_SYSTEM_ID",
    "PILOT_START_AUTHORIZATION_INTENT",
    "PILOT_START_AUTHORIZATION_MAX_WINDOW_SECONDS",
    "PilotStartAuthorizationError",
    "PilotStartAuthorization",
    "PilotStartAuthorizationProof",
    "build_pilot_start_authorization",
    "verify_pilot_start_authorization",
]
