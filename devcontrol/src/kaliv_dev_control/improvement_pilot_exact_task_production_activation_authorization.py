"""ADR-DC-092 dual-authorized one-shot production activation.

Consumes exactly one fresh live ADR-DC-091 readiness receipt with
``production_activation_ready=true``. Two independent external Ed25519
signatures may authorize only the existing machine-gated production promotion
lane. This boundary does not mutate ``modelrig.env``, restart the appliance,
perform network I/O, or publish a production receipt; the later transaction
must consume this one-shot authority and still satisfy the machine gate.
"""
from __future__ import annotations

import hashlib
import json
import os
import weakref
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
    _require_host_controlled_ledger_root,
)
from ._improvement_pilot_start_consumption_impl import _path_sha256, _safe_ledger_root
from .asymmetric_authority import (
    AsymmetricAuthorityError,
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
)
from .durable_publication import DurablePublicationError, create_once_file
from . import improvement_pilot_exact_task_pr_lifecycle_authorization as lifecycle_auth_boundary
from . import improvement_pilot_exact_task_release_authorization as shared_auth
from . import improvement_pilot_exact_task_production_activation_readiness as readiness_boundary
from .improvement_pilot_exact_task_production_activation_readiness import (
    PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_READINESS_AUTHORITY,
    PilotExactTaskProductionActivationReadinessReceipt,
)

PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_AUTHORIZATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-production-activation-authorization-receipt/v1"
)
PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_AUTHORIZATION_AUTHORITY = (
    "dual-authorized-one-dc-l16-machine-gated-production-activation-only"
)
PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_AUTHORIZATION_SCOPE = (
    "one-shot-existing-machine-gated-production-promotion-only-v1"
)
PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_AUTHORIZATION_CONFIG_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-production-activation-authorization-config/v1"
)
PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_AUTHORIZATION_KEYRING_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-production-activation-authorization-keyring/v1"
)
PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_AUTHORIZATION_CLAIM_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-production-activation-authorization-claim/v1"
)
PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_AUTHORIZATION_LEDGER_SCOPE = (
    "canonical-host-local-v1"
)

CANDIDATE_BRANCH = "feat/unity-frame-source"
PROMOTION_BRANCH = "feat/production-activation-promotion"
PROMOTION_GATE_PATH = "scripts/production_activation_gate.py"
PROMOTION_CONTROLLER_PATH = "scripts/production_activation_promote.ps1"
REQUIRED_SWITCHES = {
    "KALIV_AGENT3_ENABLED": "1",
    "KALIV_SCHEDULER": "1",
    "KALIV_SCHEDULER_API": "1",
    "KALIV_TOOLS_ENABLED": "1",
}
REQUIRED_SWITCHES_SHA256 = hashlib.sha256(
    json.dumps(
        REQUIRED_SWITCHES,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()

_MAX_FILE_BYTES = 1024 * 1024
_MAX_AUTH_SECONDS = 10 * 60
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-production-activation-authorization-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-production-activation-authorization-ledger-v1"
)
_POSIX_CONFIG = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-pilot-exact-task-production-activation-authorization-config-v1.json"
)
_WINDOWS_CONFIG = (
    Path(r"C:\Program Files\ModelRig\DevControl\authority")
    / "rsi-pilot-exact-task-production-activation-authorization-config-v1.json"
)
_POSIX_KEYRING = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-pilot-exact-task-production-activation-authorization-keyring-v1.json"
)
_WINDOWS_KEYRING = (
    Path(r"C:\Program Files\ModelRig\DevControl\authority")
    / "rsi-pilot-exact-task-production-activation-authorization-keyring-v1.json"
)


class PilotExactTaskProductionActivationAuthorizationError(ValueError):
    """Production activation authority is stale, replayed, or over-broad."""


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
        raise PilotExactTaskProductionActivationAuthorizationError(
            "production-activation authorization evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    try:
        return shared_auth._hex40(value, name=name)
    except ValueError as exc:
        raise PilotExactTaskProductionActivationAuthorizationError(str(exc)) from exc


def _hex64(value: Any, *, name: str) -> str:
    try:
        return shared_auth._hex64(value, name=name)
    except ValueError as exc:
        raise PilotExactTaskProductionActivationAuthorizationError(str(exc)) from exc


def _utc(value: Any, *, name: str):
    try:
        return shared_auth._utc(value, name=name)
    except ValueError as exc:
        raise PilotExactTaskProductionActivationAuthorizationError(str(exc)) from exc


def _now_utc_seconds() -> str:
    return shared_auth._now_utc_seconds()


@dataclass(frozen=True, slots=True)
class PilotExactTaskProductionActivationAuthorizationConfig:
    repository: str
    repository_id: str
    promotion_gate_sha256: str
    promotion_controller_sha256: str
    source_environment: str = "staging"
    target_environment: str = "production"
    candidate_branch: str = CANDIDATE_BRANCH
    promotion_branch: str = PROMOTION_BRANCH
    promotion_gate_path: str = PROMOTION_GATE_PATH
    promotion_controller_path: str = PROMOTION_CONTROLLER_PATH
    required_switches_sha256: str = REQUIRED_SWITCHES_SHA256
    require_bodyrig_machine_evidence: bool = True
    require_agent3_write_pilot: bool = True
    require_allowlisted_promotion_tree: bool = True
    require_recovery_first_restart: bool = True
    require_live_post_restart_health: bool = True
    schema: str = PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_AUTHORIZATION_CONFIG_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_AUTHORIZATION_CONFIG_SCHEMA:
            raise PilotExactTaskProductionActivationAuthorizationError(
                "production-activation authorization config schema is unsupported"
            )
        if (
            not isinstance(self.repository, str)
            or shared_auth._REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or shared_auth._REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskProductionActivationAuthorizationError(
                "repository identity is invalid"
            )
        _hex64(self.promotion_gate_sha256, name="promotion_gate_sha256")
        _hex64(self.promotion_controller_sha256, name="promotion_controller_sha256")
        if (
            self.source_environment != "staging"
            or self.target_environment != "production"
            or self.candidate_branch != CANDIDATE_BRANCH
            or self.promotion_branch != PROMOTION_BRANCH
            or self.promotion_gate_path != PROMOTION_GATE_PATH
            or self.promotion_controller_path != PROMOTION_CONTROLLER_PATH
            or self.required_switches_sha256 != REQUIRED_SWITCHES_SHA256
            or self.require_bodyrig_machine_evidence is not True
            or self.require_agent3_write_pilot is not True
            or self.require_allowlisted_promotion_tree is not True
            or self.require_recovery_first_restart is not True
            or self.require_live_post_restart_health is not True
        ):
            raise PilotExactTaskProductionActivationAuthorizationError(
                "config weakens fixed machine-gated production activation scope"
            )

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductionActivationAuthorizationError(
                "authorization config fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _parse_config(payload: bytes) -> PilotExactTaskProductionActivationAuthorizationConfig:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskProductionActivationAuthorizationError(
            "authorization config payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskProductionActivationAuthorizationError(
            "authorization config JSON is invalid"
        ) from exc
    config = PilotExactTaskProductionActivationAuthorizationConfig.from_mapping(raw)
    if config.canonical_json().encode("utf-8") != payload:
        raise PilotExactTaskProductionActivationAuthorizationError(
            "authorization config is not canonical JSON"
        )
    return config


def _parse_keyring(payload: bytes) -> tuple[Ed25519AuthorityVerifier, str]:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskProductionActivationAuthorizationError(
            "authorization keyring payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskProductionActivationAuthorizationError(
            "authorization keyring JSON is invalid"
        ) from exc
    if (
        not isinstance(raw, dict)
        or set(raw) != {"schema", "minimum_keyring_epoch", "keys"}
        or raw.get("schema")
        != PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_AUTHORIZATION_KEYRING_SCHEMA
    ):
        raise PilotExactTaskProductionActivationAuthorizationError(
            "authorization keyring schema/fields mismatch"
        )
    epoch, items = raw["minimum_keyring_epoch"], raw["keys"]
    if (
        isinstance(epoch, bool)
        or not isinstance(epoch, int)
        or epoch < 1
        or not isinstance(items, list)
        or not 2 <= len(items) <= 64
    ):
        raise PilotExactTaskProductionActivationAuthorizationError(
            "authorization keyring content is invalid"
        )
    keys: dict[str, TrustedEd25519AuthorityKey] = {}
    for item in items:
        try:
            key = TrustedEd25519AuthorityKey.from_mapping(item)
        except Exception as exc:
            raise PilotExactTaskProductionActivationAuthorizationError(
                "trusted production-activation key is invalid"
            ) from exc
        if key.key_id in keys:
            raise PilotExactTaskProductionActivationAuthorizationError(
                "duplicate production-activation key ID"
            )
        keys[key.key_id] = key
    if list(keys) != sorted(keys):
        raise PilotExactTaskProductionActivationAuthorizationError(
            "authorization keyring keys must be sorted"
        )
    expected = _canonical(
        {
            "schema": PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_AUTHORIZATION_KEYRING_SCHEMA,
            "minimum_keyring_epoch": epoch,
            "keys": [keys[key_id].to_dict() for key_id in sorted(keys)],
        }
    ).encode("utf-8")
    if expected != payload:
        raise PilotExactTaskProductionActivationAuthorizationError(
            "authorization keyring is not canonical JSON"
        )
    return (
        Ed25519AuthorityVerifier(keys, minimum_keyring_epoch=epoch),
        hashlib.sha256(payload).hexdigest(),
    )


def _read_host_authority_file(path: Path) -> bytes:
    try:
        data = lifecycle_auth_boundary._read_host_authority_file(path)
    except Exception as exc:
        raise PilotExactTaskProductionActivationAuthorizationError(
            "authority file is not host-admin controlled"
        ) from exc
    if not data or len(data) > _MAX_FILE_BYTES:
        raise PilotExactTaskProductionActivationAuthorizationError(
            "authority file is invalid"
        )
    return data


def _require_live_ready(
    value: Any,
) -> PilotExactTaskProductionActivationReadinessReceipt:
    if type(value) is not PilotExactTaskProductionActivationReadinessReceipt:
        raise PilotExactTaskProductionActivationAuthorizationError(
            "exact live ADR-DC-091 production readiness receipt is required"
        )
    try:
        replayed = PilotExactTaskProductionActivationReadinessReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskProductionActivationAuthorizationError(
            "ADR-DC-091 replay validation failed"
        ) from exc
    if (
        replayed != value
        or replayed.sha256 != value.sha256
        or value.authority != PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_READINESS_AUTHORITY
        or value.evaluation_authenticated is not True
        or value.production_activation_readiness_evaluated is not True
        or value.production_activation_ready is not True
        or value.blocker_codes != ()
        or value.source_environment != "staging"
        or value.target_environment != "production"
        or value.exact_staging_success_satisfied is not True
        or value.runtime_build_identity_bound is not True
        or value.no_residual_mutation_authority_satisfied is not True
        or value.production_activation_readiness_authorized is not False
        or value.production_activation_authorized is not False
        or value.remote_write_authorized is not False
        or value.deploy_authorized is not False
        or value.product_pilot_started is not False
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskProductionActivationAuthorizationError(
            "ADR-DC-092 requires one fresh positive inert ADR-DC-091 receipt"
        )
    live = readiness_boundary._get_live_production_activation_readiness_inputs(value)
    if (
        live is None
        or live.get("production_activation_readiness_policy_sha256")
        != value.production_activation_readiness_policy_sha256
        or live.get("production_activation_candidate_sha256")
        != value.production_activation_candidate_sha256
    ):
        raise PilotExactTaskProductionActivationAuthorizationError(
            "ADR-DC-091 live provenance is unavailable"
        )
    return value


def _validate_config_for_readiness(
    config: PilotExactTaskProductionActivationAuthorizationConfig,
    readiness: PilotExactTaskProductionActivationReadinessReceipt,
) -> None:
    if (
        config.repository != readiness.repository
        or config.repository_id != readiness.repository_id
        or config.source_environment != readiness.source_environment
        or config.target_environment != readiness.target_environment
    ):
        raise PilotExactTaskProductionActivationAuthorizationError(
            "host config does not match exact ADR-DC-091 candidate"
        )


def _build_authorization_payload(
    *,
    production_activation_readiness: PilotExactTaskProductionActivationReadinessReceipt,
    activation_config: PilotExactTaskProductionActivationAuthorizationConfig,
    requested_at_utc: str,
    expires_at_utc: str,
    operator_actor_id: str,
    operator_system_id: str,
    operator_key_id: str,
    reviewer_actor_id: str,
    reviewer_system_id: str,
    reviewer_key_id: str,
) -> bytes:
    readiness = _require_live_ready(production_activation_readiness)
    if type(activation_config) is not PilotExactTaskProductionActivationAuthorizationConfig:
        raise PilotExactTaskProductionActivationAuthorizationError(
            "exact production-activation config is required"
        )
    _validate_config_for_readiness(activation_config, readiness)
    requested = _utc(requested_at_utc, name="requested_at_utc")
    expires = _utc(expires_at_utc, name="expires_at_utc")
    evaluated = _utc(readiness.evaluated_at_utc, name="readiness_evaluated_at_utc")
    if (
        requested < evaluated
        or not requested < expires
        or (expires - requested).total_seconds() > _MAX_AUTH_SECONDS
    ):
        raise PilotExactTaskProductionActivationAuthorizationError(
            "authorization validity window is invalid"
        )
    for name, identity in (
        ("operator_actor_id", operator_actor_id),
        ("operator_system_id", operator_system_id),
        ("operator_key_id", operator_key_id),
        ("reviewer_actor_id", reviewer_actor_id),
        ("reviewer_system_id", reviewer_system_id),
        ("reviewer_key_id", reviewer_key_id),
    ):
        pattern = shared_auth._ACTOR if name.endswith("actor_id") else shared_auth._IDENTIFIER
        if not isinstance(identity, str) or pattern.fullmatch(identity) is None:
            raise PilotExactTaskProductionActivationAuthorizationError(
                f"{name} is invalid"
            )
    if (
        operator_actor_id == reviewer_actor_id
        or operator_system_id == reviewer_system_id
        or operator_key_id == reviewer_key_id
    ):
        raise PilotExactTaskProductionActivationAuthorizationError(
            "operator and reviewer identities must be independent"
        )
    values = {
        "schema": PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_AUTHORIZATION_CLAIM_SCHEMA,
        "production_activation_readiness_sha256": readiness.sha256,
        "production_activation_readiness_policy_sha256": (
            readiness.production_activation_readiness_policy_sha256
        ),
        "production_activation_candidate_sha256": (
            readiness.production_activation_candidate_sha256
        ),
        "post_staging_success_status_attestation_sha256": (
            readiness.post_staging_success_status_attestation_sha256
        ),
        "staging_runtime_build_identity_sha256": (
            readiness.staging_runtime_build_identity_sha256
        ),
        "success_deployment_status_intent_sha256": (
            readiness.success_deployment_status_intent_sha256
        ),
        "production_activation_authorization_config_sha256": activation_config.sha256,
        "repository": readiness.repository,
        "repository_id": readiness.repository_id,
        "source_environment": readiness.source_environment,
        "target_environment": readiness.target_environment,
        "merge_commit_sha": readiness.merge_commit_sha,
        "deployment_id": readiness.deployment_id,
        "deployment_node_id_sha256": readiness.deployment_node_id_sha256,
        "success_deployment_status_id": readiness.success_deployment_status_id,
        "success_deployment_status_node_id_sha256": (
            readiness.success_deployment_status_node_id_sha256
        ),
        "success_status_completion_source": readiness.success_status_completion_source,
        "success_status_source_action": readiness.success_status_source_action,
        "candidate_branch": activation_config.candidate_branch,
        "promotion_branch": activation_config.promotion_branch,
        "promotion_gate_path": activation_config.promotion_gate_path,
        "promotion_controller_path": activation_config.promotion_controller_path,
        "promotion_gate_sha256": activation_config.promotion_gate_sha256,
        "promotion_controller_sha256": activation_config.promotion_controller_sha256,
        "required_switches_sha256": activation_config.required_switches_sha256,
        "require_bodyrig_machine_evidence": True,
        "require_agent3_write_pilot": True,
        "require_allowlisted_promotion_tree": True,
        "require_recovery_first_restart": True,
        "require_live_post_restart_health": True,
        "requested_at_utc": requested_at_utc,
        "expires_at_utc": expires_at_utc,
        "operator_actor_id": operator_actor_id,
        "operator_system_id": operator_system_id,
        "operator_key_id": operator_key_id,
        "reviewer_actor_id": reviewer_actor_id,
        "reviewer_system_id": reviewer_system_id,
        "reviewer_key_id": reviewer_key_id,
    }
    return _canonical(values).encode("utf-8")


_CLAIM_FIELDS = {
    "schema",
    "production_activation_readiness_sha256",
    "production_activation_readiness_policy_sha256",
    "production_activation_candidate_sha256",
    "post_staging_success_status_attestation_sha256",
    "staging_runtime_build_identity_sha256",
    "success_deployment_status_intent_sha256",
    "production_activation_authorization_config_sha256",
    "repository",
    "repository_id",
    "source_environment",
    "target_environment",
    "merge_commit_sha",
    "deployment_id",
    "deployment_node_id_sha256",
    "success_deployment_status_id",
    "success_deployment_status_node_id_sha256",
    "success_status_completion_source",
    "success_status_source_action",
    "candidate_branch",
    "promotion_branch",
    "promotion_gate_path",
    "promotion_controller_path",
    "promotion_gate_sha256",
    "promotion_controller_sha256",
    "required_switches_sha256",
    "require_bodyrig_machine_evidence",
    "require_agent3_write_pilot",
    "require_allowlisted_promotion_tree",
    "require_recovery_first_restart",
    "require_live_post_restart_health",
    "requested_at_utc",
    "expires_at_utc",
    "operator_actor_id",
    "operator_system_id",
    "operator_key_id",
    "reviewer_actor_id",
    "reviewer_system_id",
    "reviewer_key_id",
}


def _parse_claim(payload: bytes) -> dict[str, Any]:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskProductionActivationAuthorizationError(
            "authorization payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskProductionActivationAuthorizationError(
            "authorization payload JSON is invalid"
        ) from exc
    if (
        not isinstance(raw, dict)
        or set(raw) != _CLAIM_FIELDS
        or raw.get("schema")
        != PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_AUTHORIZATION_CLAIM_SCHEMA
        or _canonical(raw).encode("utf-8") != payload
    ):
        raise PilotExactTaskProductionActivationAuthorizationError(
            "authorization payload fields/canonical form mismatch"
        )
    return raw


def _verify_claim_and_signatures(
    *,
    readiness: PilotExactTaskProductionActivationReadinessReceipt,
    config: PilotExactTaskProductionActivationAuthorizationConfig,
    payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_utc: str,
) -> dict[str, Any]:
    claim = _parse_claim(payload)
    expected = _build_authorization_payload(
        production_activation_readiness=readiness,
        activation_config=config,
        requested_at_utc=claim["requested_at_utc"],
        expires_at_utc=claim["expires_at_utc"],
        operator_actor_id=claim["operator_actor_id"],
        operator_system_id=claim["operator_system_id"],
        operator_key_id=claim["operator_key_id"],
        reviewer_actor_id=claim["reviewer_actor_id"],
        reviewer_system_id=claim["reviewer_system_id"],
        reviewer_key_id=claim["reviewer_key_id"],
    )
    if expected != payload:
        raise PilotExactTaskProductionActivationAuthorizationError(
            "authorization payload is not exactly bound"
        )
    now = _utc(now_utc, name="reserved_at_utc")
    requested = _utc(claim["requested_at_utc"], name="requested_at_utc")
    expires = _utc(claim["expires_at_utc"], name="expires_at_utc")
    if not requested <= now < expires:
        raise PilotExactTaskProductionActivationAuthorizationError(
            "authorization is not currently valid"
        )
    if (
        type(operator_signature) is not DetachedEd25519AuthoritySignature
        or type(reviewer_signature) is not DetachedEd25519AuthoritySignature
    ):
        raise PilotExactTaskProductionActivationAuthorizationError(
            "two detached Ed25519 signatures are required"
        )
    if (
        operator_signature.key_id == reviewer_signature.key_id
        or operator_signature.issuer_actor_id == reviewer_signature.issuer_actor_id
        or operator_signature.issuer_system_id == reviewer_signature.issuer_system_id
    ):
        raise PilotExactTaskProductionActivationAuthorizationError(
            "signatures must be independent"
        )
    if (
        operator_signature.key_id != claim["operator_key_id"]
        or operator_signature.issuer_actor_id != claim["operator_actor_id"]
        or operator_signature.issuer_system_id != claim["operator_system_id"]
        or reviewer_signature.key_id != claim["reviewer_key_id"]
        or reviewer_signature.issuer_actor_id != claim["reviewer_actor_id"]
        or reviewer_signature.issuer_system_id != claim["reviewer_system_id"]
    ):
        raise PilotExactTaskProductionActivationAuthorizationError(
            "signature identities do not match authorization claim"
        )
    for signature in (operator_signature, reviewer_signature):
        signed = _utc(signature.signed_at_utc, name="signed_at_utc")
        if signed < requested or signed > now or signed >= expires:
            raise PilotExactTaskProductionActivationAuthorizationError(
                "signature time is outside authorization window"
            )
    try:
        verifier.verify(payload=payload, signature=operator_signature, at_utc=now_utc)
        verifier.verify(payload=payload, signature=reviewer_signature, at_utc=now_utc)
    except AsymmetricAuthorityError as exc:
        raise PilotExactTaskProductionActivationAuthorizationError(
            "detached production-activation signature verification failed"
        ) from exc
    return claim


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskProductionActivationAuthorizationReceipt:
    production_activation_authorization_ledger_root_path_sha256: str
    production_activation_key_sha256: str
    production_activation_authorization_payload_sha256: str
    production_activation_readiness_sha256: str
    production_activation_readiness_policy_sha256: str
    production_activation_candidate_sha256: str
    post_staging_success_status_attestation_sha256: str
    staging_runtime_build_identity_sha256: str
    success_deployment_status_intent_sha256: str
    production_activation_authorization_config_sha256: str
    repository: str
    repository_id: str
    source_environment: str
    target_environment: str
    merge_commit_sha: str
    deployment_id: int
    deployment_node_id_sha256: str
    success_deployment_status_id: int
    success_deployment_status_node_id_sha256: str
    success_status_completion_source: str
    success_status_source_action: str
    candidate_branch: str
    promotion_branch: str
    promotion_gate_path: str
    promotion_controller_path: str
    promotion_gate_sha256: str
    promotion_controller_sha256: str
    required_switches_sha256: str
    operator_actor_id: str
    operator_system_id: str
    operator_key_id: str
    reviewer_actor_id: str
    reviewer_system_id: str
    reviewer_key_id: str
    readiness_evaluated_at_utc: str
    requested_at_utc: str
    expires_at_utc: str
    reserved_at_utc: str
    host_production_activation_guard_committed: bool = True
    production_activation_readiness_authenticated: bool = True
    production_activation_candidate_bound: bool = True
    production_activation_authorization_config_host_pinned: bool = True
    machine_gate_identity_host_pinned: bool = True
    dual_external_ed25519_authorized: bool = True
    promotion_gate_execution_authorized: bool = True
    production_env_mutation_authorized: bool = True
    appliance_restart_authorized: bool = True
    production_receipt_write_authorized: bool = True
    production_activation_authorized: bool = True
    success_deployment_status_authorized: bool = False
    deployment_status_mutation_authorized: bool = False
    deployment_mutation_authorized: bool = False
    deploy_authorized: bool = False
    remote_write_authorized: bool = False
    release_authorized: bool = False
    tag_write_authorized: bool = False
    release_mutation_authorized: bool = False
    merge_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    product_pilot_started: bool = False
    nonce_reusable: bool = False
    authorization_scope: str = PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_AUTHORIZATION_SCOPE
    authority: str = PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_AUTHORIZATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_AUTHORIZATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_AUTHORIZATION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_AUTHORIZATION_AUTHORITY
            or self.authorization_scope
            != PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_AUTHORIZATION_SCOPE
        ):
            raise PilotExactTaskProductionActivationAuthorizationError(
                "authorization receipt identity is unsupported"
            )
        for name in (
            "production_activation_authorization_ledger_root_path_sha256",
            "production_activation_key_sha256",
            "production_activation_authorization_payload_sha256",
            "production_activation_readiness_sha256",
            "production_activation_readiness_policy_sha256",
            "production_activation_candidate_sha256",
            "post_staging_success_status_attestation_sha256",
            "staging_runtime_build_identity_sha256",
            "success_deployment_status_intent_sha256",
            "production_activation_authorization_config_sha256",
            "deployment_node_id_sha256",
            "success_deployment_status_node_id_sha256",
            "promotion_gate_sha256",
            "promotion_controller_sha256",
            "required_switches_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        if self.production_activation_key_sha256 != self.production_activation_candidate_sha256:
            raise PilotExactTaskProductionActivationAuthorizationError(
                "replay key must equal exact production activation candidate"
            )
        if (
            not isinstance(self.repository, str)
            or shared_auth._REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or shared_auth._REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.source_environment != "staging"
            or self.target_environment != "production"
            or isinstance(self.deployment_id, bool)
            or not isinstance(self.deployment_id, int)
            or self.deployment_id < 1
            or isinstance(self.success_deployment_status_id, bool)
            or not isinstance(self.success_deployment_status_id, int)
            or self.success_deployment_status_id < 1
            or self.candidate_branch != CANDIDATE_BRANCH
            or self.promotion_branch != PROMOTION_BRANCH
            or self.promotion_gate_path != PROMOTION_GATE_PATH
            or self.promotion_controller_path != PROMOTION_CONTROLLER_PATH
            or self.required_switches_sha256 != REQUIRED_SWITCHES_SHA256
            or self.success_status_completion_source not in ("transaction", "recovery")
            or self.success_status_source_action not in (
                "execute_exact_staging_success_status",
                "finalize_existing_state",
            )
        ):
            raise PilotExactTaskProductionActivationAuthorizationError(
                "authorization receipt projection is invalid"
            )
        if (
            self.success_status_completion_source == "transaction"
            and self.success_status_source_action != "execute_exact_staging_success_status"
        ) or (
            self.success_status_completion_source == "recovery"
            and self.success_status_source_action != "finalize_existing_state"
        ):
            raise PilotExactTaskProductionActivationAuthorizationError(
                "completion provenance is inconsistent"
            )
        for name in ("operator_actor_id", "reviewer_actor_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or shared_auth._ACTOR.fullmatch(value) is None:
                raise PilotExactTaskProductionActivationAuthorizationError(
                    f"{name} is invalid"
                )
        for name in (
            "operator_system_id",
            "operator_key_id",
            "reviewer_system_id",
            "reviewer_key_id",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or shared_auth._IDENTIFIER.fullmatch(value) is None
            ):
                raise PilotExactTaskProductionActivationAuthorizationError(
                    f"{name} is invalid"
                )
        if (
            self.operator_actor_id == self.reviewer_actor_id
            or self.operator_system_id == self.reviewer_system_id
            or self.operator_key_id == self.reviewer_key_id
        ):
            raise PilotExactTaskProductionActivationAuthorizationError(
                "receipt signers are not independent"
            )
        readiness_time = _utc(
            self.readiness_evaluated_at_utc, name="readiness_evaluated_at_utc"
        )
        requested = _utc(self.requested_at_utc, name="requested_at_utc")
        expires = _utc(self.expires_at_utc, name="expires_at_utc")
        reserved = _utc(self.reserved_at_utc, name="reserved_at_utc")
        if (
            requested < readiness_time
            or not requested <= reserved < expires
            or (expires - requested).total_seconds() > _MAX_AUTH_SECONDS
        ):
            raise PilotExactTaskProductionActivationAuthorizationError(
                "authorization receipt timestamps are invalid"
            )
        required_true = (
            "host_production_activation_guard_committed",
            "production_activation_readiness_authenticated",
            "production_activation_candidate_bound",
            "production_activation_authorization_config_host_pinned",
            "machine_gate_identity_host_pinned",
            "dual_external_ed25519_authorized",
            "promotion_gate_execution_authorized",
            "production_env_mutation_authorized",
            "appliance_restart_authorized",
            "production_receipt_write_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskProductionActivationAuthorizationError(
                "production activation authorization is incomplete"
            )
        forced_false = (
            "success_deployment_status_authorized",
            "deployment_status_mutation_authorized",
            "deployment_mutation_authorized",
            "deploy_authorized",
            "remote_write_authorized",
            "release_authorized",
            "tag_write_authorized",
            "release_mutation_authorized",
            "merge_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "product_pilot_started",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductionActivationAuthorizationError(
                "authorization grants forbidden extra authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def authorization_authenticated(self) -> bool:
        return _get_live_production_activation_authorization_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductionActivationAuthorizationError(
                "authorization receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskProductionActivationAuthorizationLedger:
    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path]:
        digest = _hex64(key, name="production_activation_key_sha256")
        return self.root / f"{digest}.json", self.root / f".{digest}.lock"

    def acquire(
        self,
        *,
        readiness: PilotExactTaskProductionActivationReadinessReceipt,
        payload: bytes,
        config_sha256: str,
        operator_signature: DetachedEd25519AuthoritySignature,
        reviewer_signature: DetachedEd25519AuthoritySignature,
    ) -> bytes:
        key = readiness.production_activation_candidate_sha256
        final, lock = self._paths(key)
        if final.exists() or final.is_symlink() or lock.exists() or lock.is_symlink():
            raise PilotExactTaskProductionActivationAuthorizationError(
                "production activation candidate already consumed or needs recovery"
            )
        lock_payload = _canonical(
            {
                "schema": (
                    "kaliv-rsi-dc-l16-exact-task-production-activation-authorization-lock/v1"
                ),
                "ledger_scope": (
                    PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_AUTHORIZATION_LEDGER_SCOPE
                ),
                "ledger_root_path_sha256": self.root_sha256,
                "production_activation_key_sha256": key,
                "production_activation_readiness_sha256": readiness.sha256,
                "production_activation_candidate_sha256": (
                    readiness.production_activation_candidate_sha256
                ),
                "production_activation_authorization_payload_sha256": hashlib.sha256(
                    payload
                ).hexdigest(),
                "production_activation_authorization_config_sha256": config_sha256,
                "repository": readiness.repository,
                "repository_id": readiness.repository_id,
                "merge_commit_sha": readiness.merge_commit_sha,
                "deployment_id": readiness.deployment_id,
                "success_deployment_status_id": readiness.success_deployment_status_id,
                "operator_signature_sha256": operator_signature.sha256,
                "reviewer_signature_sha256": reviewer_signature.sha256,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, lock_payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskProductionActivationAuthorizationError(
                "production activation authorization could not be durably consumed"
            ) from exc
        return lock_payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskProductionActivationAuthorizationReceipt,
        lock_payload: bytes,
        readiness: PilotExactTaskProductionActivationReadinessReceipt,
        config: PilotExactTaskProductionActivationAuthorizationConfig,
    ) -> PilotExactTaskProductionActivationAuthorizationReceipt:
        final, lock = self._paths(receipt.production_activation_key_sha256)
        try:
            observed_lock = lock.read_bytes()
        except OSError as exc:
            raise PilotExactTaskProductionActivationAuthorizationError(
                "production activation authorization lock is unavailable"
            ) from exc
        if final.exists() or final.is_symlink() or observed_lock != lock_payload:
            raise PilotExactTaskProductionActivationAuthorizationError(
                "durable production activation authorization state changed"
            )
        final_payload = receipt.canonical_json().encode("utf-8")
        try:
            create_once_file(final, final_payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskProductionActivationAuthorizationError(
                "production activation authorization receipt could not be published"
            ) from exc
        parsed = PilotExactTaskProductionActivationAuthorizationReceipt.from_mapping(
            json.loads(final_payload.decode("utf-8"))
        )
        _mark_production_activation_authorization_authenticated(
            parsed,
            readiness=readiness,
            config=config,
            final_path=final,
            final_payload=final_payload,
            lock_path=lock,
            lock_payload=lock_payload,
        )
        if parsed.authorization_authenticated is not True:
            raise PilotExactTaskProductionActivationAuthorizationError(
                "production activation authorization lost live provenance"
            )
        return parsed


def _read_bound(path: Path) -> bytes | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return data if data and len(data) <= _MAX_FILE_BYTES else None


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: PilotExactTaskProductionActivationAuthorizationReceipt,
        *,
        readiness: PilotExactTaskProductionActivationReadinessReceipt,
        config: PilotExactTaskProductionActivationAuthorizationConfig,
        final_path: Path,
        final_payload: bytes,
        lock_path: Path,
        lock_payload: bytes,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            weakref.ref(readiness),
            config,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        (
            pid,
            digest,
            receipt_ref,
            readiness_ref,
            config,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
        ) = entry
        readiness = readiness_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or readiness is None
            or receipt.sha256 != digest
            or readiness.evaluation_authenticated is not True
            or readiness.sha256 != receipt.production_activation_readiness_sha256
            or readiness.production_activation_candidate_sha256
            != receipt.production_activation_candidate_sha256
            or readiness.production_activation_ready is not True
            or config.sha256
            != receipt.production_activation_authorization_config_sha256
            or _read_bound(final_path) != final_payload
            or _read_bound(lock_path) != lock_payload
        ):
            return None
        return MappingProxyType(
            {
                "production_activation_readiness": readiness,
                "production_activation_authorization_config": config,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_production_activation_authorization_authenticated,
    _get_live_production_activation_authorization_inputs,
) = _live_registry()


def _authorize_verified_pilot_exact_task_production_activation(
    *,
    production_activation_readiness: PilotExactTaskProductionActivationReadinessReceipt,
    activation_config: PilotExactTaskProductionActivationAuthorizationConfig,
    authorization_payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    ledger: _PilotExactTaskProductionActivationAuthorizationLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskProductionActivationAuthorizationReceipt:
    readiness = _require_live_ready(production_activation_readiness)
    if type(activation_config) is not PilotExactTaskProductionActivationAuthorizationConfig:
        raise PilotExactTaskProductionActivationAuthorizationError(
            "exact production-activation config is required"
        )
    _validate_config_for_readiness(activation_config, readiness)
    reserved_at = now_provider()
    claim = _verify_claim_and_signatures(
        readiness=readiness,
        config=activation_config,
        payload=authorization_payload,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
        verifier=verifier,
        now_utc=reserved_at,
    )
    lock_payload = ledger.acquire(
        readiness=readiness,
        payload=authorization_payload,
        config_sha256=activation_config.sha256,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
    )
    readiness = _require_live_ready(readiness)
    after_lock = now_provider()
    after = _utc(after_lock, name="post_lock_revalidated_at_utc")
    if not _utc(claim["requested_at_utc"], name="requested_at_utc") <= after < _utc(
        claim["expires_at_utc"], name="expires_at_utc"
    ):
        raise PilotExactTaskProductionActivationAuthorizationError(
            "authorization expired after durable reservation"
        )
    receipt = PilotExactTaskProductionActivationAuthorizationReceipt(
        production_activation_authorization_ledger_root_path_sha256=ledger.root_sha256,
        production_activation_key_sha256=readiness.production_activation_candidate_sha256,
        production_activation_authorization_payload_sha256=hashlib.sha256(
            authorization_payload
        ).hexdigest(),
        production_activation_readiness_sha256=readiness.sha256,
        production_activation_readiness_policy_sha256=(
            readiness.production_activation_readiness_policy_sha256
        ),
        production_activation_candidate_sha256=(
            readiness.production_activation_candidate_sha256
        ),
        post_staging_success_status_attestation_sha256=(
            readiness.post_staging_success_status_attestation_sha256
        ),
        staging_runtime_build_identity_sha256=(
            readiness.staging_runtime_build_identity_sha256
        ),
        success_deployment_status_intent_sha256=(
            readiness.success_deployment_status_intent_sha256
        ),
        production_activation_authorization_config_sha256=activation_config.sha256,
        repository=readiness.repository,
        repository_id=readiness.repository_id,
        source_environment=readiness.source_environment,
        target_environment=readiness.target_environment,
        merge_commit_sha=readiness.merge_commit_sha,
        deployment_id=readiness.deployment_id,
        deployment_node_id_sha256=readiness.deployment_node_id_sha256,
        success_deployment_status_id=readiness.success_deployment_status_id,
        success_deployment_status_node_id_sha256=(
            readiness.success_deployment_status_node_id_sha256
        ),
        success_status_completion_source=readiness.success_status_completion_source,
        success_status_source_action=readiness.success_status_source_action,
        candidate_branch=activation_config.candidate_branch,
        promotion_branch=activation_config.promotion_branch,
        promotion_gate_path=activation_config.promotion_gate_path,
        promotion_controller_path=activation_config.promotion_controller_path,
        promotion_gate_sha256=activation_config.promotion_gate_sha256,
        promotion_controller_sha256=activation_config.promotion_controller_sha256,
        required_switches_sha256=activation_config.required_switches_sha256,
        operator_actor_id=claim["operator_actor_id"],
        operator_system_id=claim["operator_system_id"],
        operator_key_id=claim["operator_key_id"],
        reviewer_actor_id=claim["reviewer_actor_id"],
        reviewer_system_id=claim["reviewer_system_id"],
        reviewer_key_id=claim["reviewer_key_id"],
        readiness_evaluated_at_utc=readiness.evaluated_at_utc,
        requested_at_utc=claim["requested_at_utc"],
        expires_at_utc=claim["expires_at_utc"],
        reserved_at_utc=reserved_at,
    )
    return ledger.commit(
        receipt=receipt,
        lock_payload=lock_payload,
        readiness=readiness,
        config=activation_config,
    )


def _canonical_runtime():
    try:
        _require_elevated_operator()
        if os.name == "posix":
            config_path, keyring_path, ledger_root = (
                _POSIX_CONFIG,
                _POSIX_KEYRING,
                _POSIX_LEDGER,
            )
        elif os.name == "nt":
            config_path, keyring_path, ledger_root = (
                _WINDOWS_CONFIG,
                _WINDOWS_KEYRING,
                _WINDOWS_LEDGER,
            )
        else:
            raise PilotExactTaskProductionActivationAuthorizationError(
                "production-activation authorization platform is unsupported"
            )
        config = _parse_config(_read_host_authority_file(config_path))
        verifier, _keyring_sha = _parse_keyring(
            _read_host_authority_file(keyring_path)
        )
        _require_host_controlled_ledger_root(ledger_root)
        return (
            config,
            verifier,
            _PilotExactTaskProductionActivationAuthorizationLedger(ledger_root),
        )
    except PilotExactTaskProductionActivationAuthorizationError:
        raise
    except (PhysicalHostStateError, ValueError, TypeError, OSError) as exc:
        raise PilotExactTaskProductionActivationAuthorizationError(
            "production-activation authorization runtime is not host-admin controlled"
        ) from exc


def _canonical_config() -> PilotExactTaskProductionActivationAuthorizationConfig:
    if os.name == "posix":
        path = _POSIX_CONFIG
    elif os.name == "nt":
        path = _WINDOWS_CONFIG
    else:
        raise PilotExactTaskProductionActivationAuthorizationError(
            "production-activation authorization platform is unsupported"
        )
    return _parse_config(_read_host_authority_file(path))


def build_pilot_exact_task_production_activation_authorization_payload(
    production_activation_readiness: PilotExactTaskProductionActivationReadinessReceipt,
    requested_at_utc: str,
    expires_at_utc: str,
    operator_actor_id: str,
    operator_system_id: str,
    operator_key_id: str,
    reviewer_actor_id: str,
    reviewer_system_id: str,
    reviewer_key_id: str,
) -> bytes:
    """Build exact bytes for two independent production-activation signers."""
    return _build_authorization_payload(
        production_activation_readiness=production_activation_readiness,
        activation_config=_canonical_config(),
        requested_at_utc=requested_at_utc,
        expires_at_utc=expires_at_utc,
        operator_actor_id=operator_actor_id,
        operator_system_id=operator_system_id,
        operator_key_id=operator_key_id,
        reviewer_actor_id=reviewer_actor_id,
        reviewer_system_id=reviewer_system_id,
        reviewer_key_id=reviewer_key_id,
    )


def authorize_pilot_exact_task_production_activation(
    production_activation_readiness: PilotExactTaskProductionActivationReadinessReceipt,
    authorization_payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
) -> PilotExactTaskProductionActivationAuthorizationReceipt:
    """Authorize the existing machine gate once; perform no activation here."""
    config, verifier, ledger = _canonical_runtime()
    return _authorize_verified_pilot_exact_task_production_activation(
        production_activation_readiness=production_activation_readiness,
        activation_config=config,
        authorization_payload=authorization_payload,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
        verifier=verifier,
        ledger=ledger,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
