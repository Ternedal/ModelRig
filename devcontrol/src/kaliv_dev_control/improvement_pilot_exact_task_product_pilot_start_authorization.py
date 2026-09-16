"""ADR-DC-097 dual-authorized one-shot product-pilot start authorization.

Consumes exactly one fresh live authenticated ADR-DC-096 readiness receipt. Two
independent detached Ed25519 signatures may authorize only a later exact
product-pilot start transaction. This boundary does not start the pilot, perform
network I/O, invoke subprocesses, mutate production state, restart the appliance,
or grant unrelated repository/deployment/release authority.
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
from ._improvement_pilot_start_consumption_impl import _path_sha256
from .asymmetric_authority import (
    AsymmetricAuthorityError,
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
)
from .durable_publication import DurablePublicationError, create_once_file
from . import improvement_pilot_exact_task_pr_lifecycle_authorization as lifecycle_auth_boundary
from . import improvement_pilot_exact_task_release_authorization as shared_auth
from . import improvement_pilot_exact_task_product_pilot_start_readiness as readiness_boundary
from .improvement_pilot_exact_task_product_pilot_start_readiness import (
    PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_AUTHORITY,
    PilotExactTaskProductPilotStartReadinessReceipt,
)

PILOT_EXACT_TASK_PRODUCT_PILOT_START_AUTHORIZATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-start-authorization-receipt/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_AUTHORIZATION_AUTHORITY = (
    "dual-authorized-one-dc-l16-exact-product-pilot-start-only"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_AUTHORIZATION_SCOPE = (
    "one-shot-exact-product-pilot-start-only-v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_AUTHORIZATION_CONFIG_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-start-authorization-config/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_AUTHORIZATION_KEYRING_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-start-authorization-keyring/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_AUTHORIZATION_CLAIM_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-start-authorization-claim/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_AUTHORIZATION_LEDGER_SCOPE = (
    "canonical-host-local-v1"
)

PRODUCT_PILOT_ID = "modelrig-product-pilot-v1"
_MAX_FILE_BYTES = 1024 * 1024
_MAX_AUTH_SECONDS = 5 * 60
_MAX_READINESS_AGE_AT_RESERVATION_SECONDS = 60

_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-product-pilot-start-authorization-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-product-pilot-start-authorization-ledger-v1"
)
_POSIX_CONFIG = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-pilot-exact-task-product-pilot-start-authorization-config-v1.json"
)
_WINDOWS_CONFIG = (
    Path(r"C:\Program Files\ModelRig\DevControl\authority")
    / "rsi-pilot-exact-task-product-pilot-start-authorization-config-v1.json"
)
_POSIX_KEYRING = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-pilot-exact-task-product-pilot-start-authorization-keyring-v1.json"
)
_WINDOWS_KEYRING = (
    Path(r"C:\Program Files\ModelRig\DevControl\authority")
    / "rsi-pilot-exact-task-product-pilot-start-authorization-keyring-v1.json"
)


class PilotExactTaskProductPilotStartAuthorizationError(ValueError):
    """Product-pilot start authority is stale, replayed, or over-broad."""


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
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "product-pilot authorization evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    try:
        return shared_auth._hex40(value, name=name)
    except ValueError as exc:
        raise PilotExactTaskProductPilotStartAuthorizationError(str(exc)) from exc


def _hex64(value: Any, *, name: str) -> str:
    try:
        return shared_auth._hex64(value, name=name)
    except ValueError as exc:
        raise PilotExactTaskProductPilotStartAuthorizationError(str(exc)) from exc


def _utc(value: Any, *, name: str):
    try:
        return shared_auth._utc(value, name=name)
    except ValueError as exc:
        raise PilotExactTaskProductPilotStartAuthorizationError(str(exc)) from exc


def _now_utc_seconds() -> str:
    return shared_auth._now_utc_seconds()


@dataclass(frozen=True, slots=True)
class PilotExactTaskProductPilotStartAuthorizationConfig:
    repository: str
    repository_id: str
    product_pilot_id: str = PRODUCT_PILOT_ID
    require_exact_post_production_state: bool = True
    require_live_readiness_provenance: bool = True
    require_dual_external_ed25519: bool = True
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_AUTHORIZATION_CONFIG_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PRODUCT_PILOT_START_AUTHORIZATION_CONFIG_SCHEMA:
            raise PilotExactTaskProductPilotStartAuthorizationError(
                "product-pilot authorization config schema is unsupported"
            )
        if (
            not isinstance(self.repository, str)
            or shared_auth._REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or shared_auth._REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskProductPilotStartAuthorizationError(
                "repository identity is invalid"
            )
        if (
            self.product_pilot_id != PRODUCT_PILOT_ID
            or self.require_exact_post_production_state is not True
            or self.require_live_readiness_provenance is not True
            or self.require_dual_external_ed25519 is not True
        ):
            raise PilotExactTaskProductPilotStartAuthorizationError(
                "config weakens fixed product-pilot start scope"
            )

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductPilotStartAuthorizationError(
                "authorization config fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _parse_config(payload: bytes) -> PilotExactTaskProductPilotStartAuthorizationConfig:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "authorization config payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "authorization config JSON is invalid"
        ) from exc
    config = PilotExactTaskProductPilotStartAuthorizationConfig.from_mapping(raw)
    if config.canonical_json().encode("utf-8") != payload:
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "authorization config is not canonical JSON"
        )
    return config


def _parse_keyring(payload: bytes) -> tuple[Ed25519AuthorityVerifier, str]:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "authorization keyring payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "authorization keyring JSON is invalid"
        ) from exc
    if (
        not isinstance(raw, dict)
        or set(raw) != {"schema", "minimum_keyring_epoch", "keys"}
        or raw.get("schema")
        != PILOT_EXACT_TASK_PRODUCT_PILOT_START_AUTHORIZATION_KEYRING_SCHEMA
    ):
        raise PilotExactTaskProductPilotStartAuthorizationError(
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
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "authorization keyring content is invalid"
        )
    keys: dict[str, TrustedEd25519AuthorityKey] = {}
    for item in items:
        try:
            key = TrustedEd25519AuthorityKey.from_mapping(item)
        except Exception as exc:
            raise PilotExactTaskProductPilotStartAuthorizationError(
                "trusted product-pilot key is invalid"
            ) from exc
        if key.key_id in keys:
            raise PilotExactTaskProductPilotStartAuthorizationError(
                "duplicate product-pilot key ID"
            )
        keys[key.key_id] = key
    if list(keys) != sorted(keys):
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "authorization keyring keys must be sorted"
        )
    expected = _canonical(
        {
            "schema": PILOT_EXACT_TASK_PRODUCT_PILOT_START_AUTHORIZATION_KEYRING_SCHEMA,
            "minimum_keyring_epoch": epoch,
            "keys": [keys[key_id].to_dict() for key_id in sorted(keys)],
        }
    ).encode("utf-8")
    if expected != payload:
        raise PilotExactTaskProductPilotStartAuthorizationError(
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
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "authority file is not host-admin controlled"
        ) from exc
    if not data or len(data) > _MAX_FILE_BYTES:
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "authority file is invalid"
        )
    return data


def _require_live_ready(
    value: Any,
) -> PilotExactTaskProductPilotStartReadinessReceipt:
    if type(value) is not PilotExactTaskProductPilotStartReadinessReceipt:
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "exact live ADR-DC-096 readiness receipt is required"
        )
    try:
        replayed = PilotExactTaskProductPilotStartReadinessReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "ADR-DC-096 replay validation failed"
        ) from exc
    if (
        replayed != value
        or replayed.sha256 != value.sha256
        or value.authority != PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_AUTHORITY
        or value.readiness_authenticated is not True
        or value.production_activation is not True
        or value.production_activation_attested is not True
        or value.post_production_state_verified is not True
        or value.product_pilot_start_ready is not True
        or value.product_pilot_start_authorized is not False
        or value.product_pilot_started is not False
        or value.remote_write_authorized is not False
        or value.production_activation_authorized is not False
        or value.next_boundary_authorization_required is not True
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "ADR-DC-097 requires one fresh positive inert ADR-DC-096 receipt"
        )
    live = readiness_boundary._get_live_readiness_source(value)
    if live is None:
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "ADR-DC-096 live provenance is unavailable"
        )
    return value


def _validate_config_for_readiness(
    config: PilotExactTaskProductPilotStartAuthorizationConfig,
    readiness: PilotExactTaskProductPilotStartReadinessReceipt,
) -> None:
    if (
        config.repository != readiness.repository
        or config.repository_id != readiness.repository_id
    ):
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "host config does not match exact ADR-DC-096 candidate"
        )


def _start_intent_sha256(
    readiness: PilotExactTaskProductPilotStartReadinessReceipt,
    config: PilotExactTaskProductPilotStartAuthorizationConfig,
) -> str:
    values = {
        "schema": "kaliv-rsi-dc-l16-exact-task-product-pilot-start-intent/v1",
        "product_pilot_start_readiness_sha256": readiness.sha256,
        "production_activation_candidate_sha256": (
            readiness.production_activation_candidate_sha256
        ),
        "repository": readiness.repository,
        "repository_id": readiness.repository_id,
        "merge_commit_sha": readiness.merge_commit_sha,
        "promotion_git_sha": readiness.promotion_git_sha,
        "environment_after_sha256": readiness.environment_after_sha256,
        "output_state_sha256": readiness.output_state_sha256,
        "machine_production_receipt_sha256": readiness.machine_production_receipt_sha256,
        "product_pilot_id": config.product_pilot_id,
        "authorization_config_sha256": config.sha256,
    }
    return hashlib.sha256(_canonical(values).encode("utf-8")).hexdigest()


def _build_authorization_payload(
    *,
    product_pilot_start_readiness: PilotExactTaskProductPilotStartReadinessReceipt,
    authorization_config: PilotExactTaskProductPilotStartAuthorizationConfig,
    requested_at_utc: str,
    expires_at_utc: str,
    operator_actor_id: str,
    operator_system_id: str,
    operator_key_id: str,
    reviewer_actor_id: str,
    reviewer_system_id: str,
    reviewer_key_id: str,
) -> bytes:
    readiness = _require_live_ready(product_pilot_start_readiness)
    if type(authorization_config) is not PilotExactTaskProductPilotStartAuthorizationConfig:
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "exact product-pilot authorization config is required"
        )
    _validate_config_for_readiness(authorization_config, readiness)
    requested = _utc(requested_at_utc, name="requested_at_utc")
    expires = _utc(expires_at_utc, name="expires_at_utc")
    evaluated = _utc(readiness.evaluated_at_utc, name="readiness_evaluated_at_utc")
    if (
        requested < evaluated
        or not requested < expires
        or (expires - requested).total_seconds() > _MAX_AUTH_SECONDS
        or (requested - evaluated).total_seconds()
        > _MAX_READINESS_AGE_AT_RESERVATION_SECONDS
    ):
        raise PilotExactTaskProductPilotStartAuthorizationError(
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
        pattern = (
            shared_auth._ACTOR
            if name.endswith("actor_id")
            else shared_auth._IDENTIFIER
        )
        if not isinstance(identity, str) or pattern.fullmatch(identity) is None:
            raise PilotExactTaskProductPilotStartAuthorizationError(
                f"{name} is invalid"
            )
    if (
        operator_actor_id == reviewer_actor_id
        or operator_system_id == reviewer_system_id
        or operator_key_id == reviewer_key_id
    ):
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "operator and reviewer identities must be independent"
        )
    values = {
        "schema": PILOT_EXACT_TASK_PRODUCT_PILOT_START_AUTHORIZATION_CLAIM_SCHEMA,
        "product_pilot_start_readiness_sha256": readiness.sha256,
        "product_pilot_start_intent_sha256": _start_intent_sha256(
            readiness, authorization_config
        ),
        "post_production_activation_attestation_sha256": (
            readiness.post_production_activation_attestation_sha256
        ),
        "production_activation_candidate_sha256": (
            readiness.production_activation_candidate_sha256
        ),
        "production_activation_source_receipt_sha256": (
            readiness.production_activation_source_receipt_sha256
        ),
        "production_activation_transaction_lock_sha256": (
            readiness.production_activation_transaction_lock_sha256
        ),
        "environment_after_sha256": readiness.environment_after_sha256,
        "output_state_sha256": readiness.output_state_sha256,
        "production_preflight_sha256": readiness.production_preflight_sha256,
        "machine_production_receipt_sha256": readiness.machine_production_receipt_sha256,
        "authorization_config_sha256": authorization_config.sha256,
        "repository": readiness.repository,
        "repository_id": readiness.repository_id,
        "merge_commit_sha": readiness.merge_commit_sha,
        "promotion_git_sha": readiness.promotion_git_sha,
        "product_pilot_id": authorization_config.product_pilot_id,
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
    "product_pilot_start_readiness_sha256",
    "product_pilot_start_intent_sha256",
    "post_production_activation_attestation_sha256",
    "production_activation_candidate_sha256",
    "production_activation_source_receipt_sha256",
    "production_activation_transaction_lock_sha256",
    "environment_after_sha256",
    "output_state_sha256",
    "production_preflight_sha256",
    "machine_production_receipt_sha256",
    "authorization_config_sha256",
    "repository",
    "repository_id",
    "merge_commit_sha",
    "promotion_git_sha",
    "product_pilot_id",
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
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "authorization payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "authorization payload JSON is invalid"
        ) from exc
    if (
        not isinstance(raw, dict)
        or set(raw) != _CLAIM_FIELDS
        or raw.get("schema")
        != PILOT_EXACT_TASK_PRODUCT_PILOT_START_AUTHORIZATION_CLAIM_SCHEMA
        or _canonical(raw).encode("utf-8") != payload
    ):
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "authorization payload fields/canonical form mismatch"
        )
    return raw


def _verify_claim_and_signatures(
    *,
    readiness: PilotExactTaskProductPilotStartReadinessReceipt,
    config: PilotExactTaskProductPilotStartAuthorizationConfig,
    payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_utc: str,
) -> dict[str, Any]:
    claim = _parse_claim(payload)
    expected = _build_authorization_payload(
        product_pilot_start_readiness=readiness,
        authorization_config=config,
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
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "authorization payload is not exactly bound"
        )
    now = _utc(now_utc, name="reserved_at_utc")
    requested = _utc(claim["requested_at_utc"], name="requested_at_utc")
    expires = _utc(claim["expires_at_utc"], name="expires_at_utc")
    evaluated = _utc(readiness.evaluated_at_utc, name="readiness_evaluated_at_utc")
    if (
        not requested <= now < expires
        or (now - evaluated).total_seconds()
        > _MAX_READINESS_AGE_AT_RESERVATION_SECONDS
    ):
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "authorization is not currently valid against fresh readiness"
        )
    if (
        type(operator_signature) is not DetachedEd25519AuthoritySignature
        or type(reviewer_signature) is not DetachedEd25519AuthoritySignature
    ):
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "two detached Ed25519 signatures are required"
        )
    if (
        operator_signature.key_id == reviewer_signature.key_id
        or operator_signature.issuer_actor_id == reviewer_signature.issuer_actor_id
        or operator_signature.issuer_system_id == reviewer_signature.issuer_system_id
    ):
        raise PilotExactTaskProductPilotStartAuthorizationError(
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
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "signature identities do not match authorization claim"
        )
    for signature in (operator_signature, reviewer_signature):
        signed = _utc(signature.signed_at_utc, name="signed_at_utc")
        if signed < requested or signed > now or signed >= expires:
            raise PilotExactTaskProductPilotStartAuthorizationError(
                "signature time is outside authorization window"
            )
    try:
        verifier.verify(payload=payload, signature=operator_signature, at_utc=now_utc)
        verifier.verify(payload=payload, signature=reviewer_signature, at_utc=now_utc)
    except AsymmetricAuthorityError as exc:
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "detached product-pilot signature verification failed"
        ) from exc
    return claim


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskProductPilotStartAuthorizationReceipt:
    product_pilot_start_authorization_ledger_root_path_sha256: str
    product_pilot_start_key_sha256: str
    product_pilot_start_authorization_payload_sha256: str
    product_pilot_start_readiness_sha256: str
    product_pilot_start_intent_sha256: str
    post_production_activation_attestation_sha256: str
    production_activation_candidate_sha256: str
    production_activation_source_receipt_sha256: str
    production_activation_transaction_lock_sha256: str
    environment_after_sha256: str
    output_state_sha256: str
    production_preflight_sha256: str
    machine_production_receipt_sha256: str
    authorization_config_sha256: str
    repository: str
    repository_id: str
    merge_commit_sha: str
    promotion_git_sha: str
    product_pilot_id: str
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
    host_product_pilot_start_guard_committed: bool = True
    product_pilot_start_readiness_authenticated: bool = True
    product_pilot_start_intent_bound: bool = True
    product_pilot_start_authorization_config_host_pinned: bool = True
    dual_external_ed25519_authorized: bool = True
    product_pilot_start_authorized: bool = True
    product_pilot_started: bool = False
    production_activation: bool = True
    production_activation_attested: bool = True
    production_activation_authorized: bool = False
    promotion_gate_execution_authorized: bool = False
    production_env_mutation_authorized: bool = False
    appliance_restart_authorized: bool = False
    production_receipt_write_authorized: bool = False
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
    nonce_reusable: bool = False
    authorization_scope: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_AUTHORIZATION_SCOPE
    authority: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_AUTHORIZATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_AUTHORIZATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCT_PILOT_START_AUTHORIZATION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PRODUCT_PILOT_START_AUTHORIZATION_AUTHORITY
            or self.authorization_scope
            != PILOT_EXACT_TASK_PRODUCT_PILOT_START_AUTHORIZATION_SCOPE
        ):
            raise PilotExactTaskProductPilotStartAuthorizationError(
                "authorization receipt identity is unsupported"
            )
        for name in (
            "product_pilot_start_authorization_ledger_root_path_sha256",
            "product_pilot_start_key_sha256",
            "product_pilot_start_authorization_payload_sha256",
            "product_pilot_start_readiness_sha256",
            "product_pilot_start_intent_sha256",
            "post_production_activation_attestation_sha256",
            "production_activation_candidate_sha256",
            "production_activation_source_receipt_sha256",
            "production_activation_transaction_lock_sha256",
            "environment_after_sha256",
            "output_state_sha256",
            "production_preflight_sha256",
            "machine_production_receipt_sha256",
            "authorization_config_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        _hex40(self.promotion_git_sha, name="promotion_git_sha")
        if (
            self.product_pilot_start_key_sha256 != self.product_pilot_start_intent_sha256
            or self.product_pilot_id != PRODUCT_PILOT_ID
            or not isinstance(self.repository, str)
            or shared_auth._REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or shared_auth._REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskProductPilotStartAuthorizationError(
                "authorization receipt identity projection is invalid"
            )
        readiness_evaluated = _utc(
            self.readiness_evaluated_at_utc, name="readiness_evaluated_at_utc"
        )
        requested = _utc(self.requested_at_utc, name="requested_at_utc")
        expires = _utc(self.expires_at_utc, name="expires_at_utc")
        reserved = _utc(self.reserved_at_utc, name="reserved_at_utc")
        if (
            requested < readiness_evaluated
            or not requested <= reserved < expires
            or (expires - requested).total_seconds() > _MAX_AUTH_SECONDS
            or (reserved - readiness_evaluated).total_seconds()
            > _MAX_READINESS_AGE_AT_RESERVATION_SECONDS
        ):
            raise PilotExactTaskProductPilotStartAuthorizationError(
                "authorization receipt validity window is invalid"
            )
        for name in (
            "operator_actor_id",
            "reviewer_actor_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or shared_auth._ACTOR.fullmatch(value) is None:
                raise PilotExactTaskProductPilotStartAuthorizationError(
                    "authorization actor identity is invalid"
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
                raise PilotExactTaskProductPilotStartAuthorizationError(
                    "authorization signer identity is invalid"
                )
        if (
            self.operator_actor_id == self.reviewer_actor_id
            or self.operator_system_id == self.reviewer_system_id
            or self.operator_key_id == self.reviewer_key_id
        ):
            raise PilotExactTaskProductPilotStartAuthorizationError(
                "authorization signer identities are not independent"
            )
        required_true = (
            "host_product_pilot_start_guard_committed",
            "product_pilot_start_readiness_authenticated",
            "product_pilot_start_intent_bound",
            "product_pilot_start_authorization_config_host_pinned",
            "dual_external_ed25519_authorized",
            "product_pilot_start_authorized",
            "production_activation",
            "production_activation_attested",
        )
        forced_false = (
            "product_pilot_started",
            "production_activation_authorized",
            "promotion_gate_execution_authorized",
            "production_env_mutation_authorized",
            "appliance_restart_authorized",
            "production_receipt_write_authorized",
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
            "nonce_reusable",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskProductPilotStartAuthorizationError(
                "authorization receipt lacks exact product-pilot authority"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductPilotStartAuthorizationError(
                "authorization receipt retains forbidden unrelated authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def authorization_authenticated(self) -> bool:
        return _get_live_product_pilot_start_authorization_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductPilotStartAuthorizationError(
                "authorization receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskProductPilotStartAuthorizationLedger:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path]:
        _hex64(key, name="product_pilot_start_key_sha256")
        return (
            self.root / f"{key}.json",
            self.root / f"{key}.lock.json",
        )

    def acquire(
        self,
        *,
        readiness: PilotExactTaskProductPilotStartReadinessReceipt,
        intent_sha256: str,
        payload: bytes,
        config_sha256: str,
        operator_signature: DetachedEd25519AuthoritySignature,
        reviewer_signature: DetachedEd25519AuthoritySignature,
    ) -> bytes:
        key = _hex64(intent_sha256, name="product_pilot_start_intent_sha256")
        final, lock = self._paths(key)
        if final.exists() or final.is_symlink() or lock.exists() or lock.is_symlink():
            raise PilotExactTaskProductPilotStartAuthorizationError(
                "product-pilot start intent already consumed or needs recovery"
            )
        lock_payload = _canonical(
            {
                "schema": (
                    "kaliv-rsi-dc-l16-exact-task-product-pilot-start-authorization-lock/v1"
                ),
                "ledger_scope": PILOT_EXACT_TASK_PRODUCT_PILOT_START_AUTHORIZATION_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "product_pilot_start_key_sha256": key,
                "product_pilot_start_readiness_sha256": readiness.sha256,
                "production_activation_candidate_sha256": (
                    readiness.production_activation_candidate_sha256
                ),
                "product_pilot_start_authorization_payload_sha256": hashlib.sha256(
                    payload
                ).hexdigest(),
                "authorization_config_sha256": config_sha256,
                "repository": readiness.repository,
                "repository_id": readiness.repository_id,
                "merge_commit_sha": readiness.merge_commit_sha,
                "operator_signature_sha256": operator_signature.sha256,
                "reviewer_signature_sha256": reviewer_signature.sha256,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, lock_payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskProductPilotStartAuthorizationError(
                "product-pilot authorization could not be durably consumed"
            ) from exc
        return lock_payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskProductPilotStartAuthorizationReceipt,
        lock_payload: bytes,
        readiness: PilotExactTaskProductPilotStartReadinessReceipt,
        config: PilotExactTaskProductPilotStartAuthorizationConfig,
    ) -> PilotExactTaskProductPilotStartAuthorizationReceipt:
        final, lock = self._paths(receipt.product_pilot_start_key_sha256)
        try:
            observed_lock = lock.read_bytes()
        except OSError as exc:
            raise PilotExactTaskProductPilotStartAuthorizationError(
                "product-pilot authorization lock is unavailable"
            ) from exc
        if final.exists() or final.is_symlink() or observed_lock != lock_payload:
            raise PilotExactTaskProductPilotStartAuthorizationError(
                "durable product-pilot authorization state changed"
            )
        final_payload = receipt.canonical_json().encode("utf-8")
        try:
            create_once_file(final, final_payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskProductPilotStartAuthorizationError(
                "product-pilot authorization receipt could not be published"
            ) from exc
        parsed = PilotExactTaskProductPilotStartAuthorizationReceipt.from_mapping(
            json.loads(final_payload.decode("utf-8"))
        )
        _mark_product_pilot_start_authorization_authenticated(
            parsed,
            readiness=readiness,
            config=config,
            final_path=final,
            final_payload=final_payload,
            lock_path=lock,
            lock_payload=lock_payload,
        )
        if parsed.authorization_authenticated is not True:
            raise PilotExactTaskProductPilotStartAuthorizationError(
                "product-pilot authorization lost live provenance"
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
        receipt: PilotExactTaskProductPilotStartAuthorizationReceipt,
        *,
        readiness: PilotExactTaskProductPilotStartReadinessReceipt,
        config: PilotExactTaskProductPilotStartAuthorizationConfig,
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
            or readiness.readiness_authenticated is not True
            or readiness.sha256 != receipt.product_pilot_start_readiness_sha256
            or readiness.production_activation_candidate_sha256
            != receipt.production_activation_candidate_sha256
            or readiness.product_pilot_start_ready is not True
            or config.sha256 != receipt.authorization_config_sha256
            or _read_bound(final_path) != final_payload
            or _read_bound(lock_path) != lock_payload
        ):
            return None
        return MappingProxyType(
            {
                "product_pilot_start_readiness": readiness,
                "product_pilot_start_authorization_config": config,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_product_pilot_start_authorization_authenticated,
    _get_live_product_pilot_start_authorization_inputs,
) = _live_registry()


def _authorize_verified_pilot_exact_task_product_pilot_start(
    *,
    product_pilot_start_readiness: PilotExactTaskProductPilotStartReadinessReceipt,
    authorization_config: PilotExactTaskProductPilotStartAuthorizationConfig,
    authorization_payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    ledger: _PilotExactTaskProductPilotStartAuthorizationLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskProductPilotStartAuthorizationReceipt:
    readiness = _require_live_ready(product_pilot_start_readiness)
    if type(authorization_config) is not PilotExactTaskProductPilotStartAuthorizationConfig:
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "exact product-pilot authorization config is required"
        )
    _validate_config_for_readiness(authorization_config, readiness)
    reserved_at = now_provider()
    claim = _verify_claim_and_signatures(
        readiness=readiness,
        config=authorization_config,
        payload=authorization_payload,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
        verifier=verifier,
        now_utc=reserved_at,
    )
    intent_sha256 = _start_intent_sha256(readiness, authorization_config)
    if claim["product_pilot_start_intent_sha256"] != intent_sha256:
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "product-pilot start intent digest mismatch"
        )
    lock_payload = ledger.acquire(
        readiness=readiness,
        intent_sha256=intent_sha256,
        payload=authorization_payload,
        config_sha256=authorization_config.sha256,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
    )
    readiness = _require_live_ready(readiness)
    after_lock = now_provider()
    after = _utc(after_lock, name="post_lock_revalidated_at_utc")
    evaluated = _utc(readiness.evaluated_at_utc, name="readiness_evaluated_at_utc")
    if (
        not _utc(claim["requested_at_utc"], name="requested_at_utc")
        <= after
        < _utc(claim["expires_at_utc"], name="expires_at_utc")
        or (after - evaluated).total_seconds()
        > _MAX_READINESS_AGE_AT_RESERVATION_SECONDS
    ):
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "authorization expired after durable reservation"
        )
    receipt = PilotExactTaskProductPilotStartAuthorizationReceipt(
        product_pilot_start_authorization_ledger_root_path_sha256=ledger.root_sha256,
        product_pilot_start_key_sha256=intent_sha256,
        product_pilot_start_authorization_payload_sha256=hashlib.sha256(
            authorization_payload
        ).hexdigest(),
        product_pilot_start_readiness_sha256=readiness.sha256,
        product_pilot_start_intent_sha256=intent_sha256,
        post_production_activation_attestation_sha256=(
            readiness.post_production_activation_attestation_sha256
        ),
        production_activation_candidate_sha256=(
            readiness.production_activation_candidate_sha256
        ),
        production_activation_source_receipt_sha256=(
            readiness.production_activation_source_receipt_sha256
        ),
        production_activation_transaction_lock_sha256=(
            readiness.production_activation_transaction_lock_sha256
        ),
        environment_after_sha256=readiness.environment_after_sha256,
        output_state_sha256=readiness.output_state_sha256,
        production_preflight_sha256=readiness.production_preflight_sha256,
        machine_production_receipt_sha256=readiness.machine_production_receipt_sha256,
        authorization_config_sha256=authorization_config.sha256,
        repository=readiness.repository,
        repository_id=readiness.repository_id,
        merge_commit_sha=readiness.merge_commit_sha,
        promotion_git_sha=readiness.promotion_git_sha,
        product_pilot_id=authorization_config.product_pilot_id,
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
        config=authorization_config,
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
            raise PilotExactTaskProductPilotStartAuthorizationError(
                "product-pilot authorization platform is unsupported"
            )
        config = _parse_config(_read_host_authority_file(config_path))
        verifier, _keyring_sha = _parse_keyring(
            _read_host_authority_file(keyring_path)
        )
        _require_host_controlled_ledger_root(ledger_root)
        return (
            config,
            verifier,
            _PilotExactTaskProductPilotStartAuthorizationLedger(ledger_root),
        )
    except PilotExactTaskProductPilotStartAuthorizationError:
        raise
    except (PhysicalHostStateError, ValueError, TypeError, OSError) as exc:
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "product-pilot authorization runtime is not host-admin controlled"
        ) from exc


def _canonical_config() -> PilotExactTaskProductPilotStartAuthorizationConfig:
    if os.name == "posix":
        path = _POSIX_CONFIG
    elif os.name == "nt":
        path = _WINDOWS_CONFIG
    else:
        raise PilotExactTaskProductPilotStartAuthorizationError(
            "product-pilot authorization platform is unsupported"
        )
    return _parse_config(_read_host_authority_file(path))


def build_pilot_exact_task_product_pilot_start_authorization_payload(
    product_pilot_start_readiness: PilotExactTaskProductPilotStartReadinessReceipt,
    requested_at_utc: str,
    expires_at_utc: str,
    operator_actor_id: str,
    operator_system_id: str,
    operator_key_id: str,
    reviewer_actor_id: str,
    reviewer_system_id: str,
    reviewer_key_id: str,
) -> bytes:
    """Build exact bytes for two independent product-pilot start signers."""
    return _build_authorization_payload(
        product_pilot_start_readiness=product_pilot_start_readiness,
        authorization_config=_canonical_config(),
        requested_at_utc=requested_at_utc,
        expires_at_utc=expires_at_utc,
        operator_actor_id=operator_actor_id,
        operator_system_id=operator_system_id,
        operator_key_id=operator_key_id,
        reviewer_actor_id=reviewer_actor_id,
        reviewer_system_id=reviewer_system_id,
        reviewer_key_id=reviewer_key_id,
    )


def authorize_pilot_exact_task_product_pilot_start(
    product_pilot_start_readiness: PilotExactTaskProductPilotStartReadinessReceipt,
    authorization_payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
) -> PilotExactTaskProductPilotStartAuthorizationReceipt:
    """Authorize exactly one later pilot-start transaction; do not start it here."""
    config, verifier, ledger = _canonical_runtime()
    return _authorize_verified_pilot_exact_task_product_pilot_start(
        product_pilot_start_readiness=product_pilot_start_readiness,
        authorization_config=config,
        authorization_payload=authorization_payload,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
        verifier=verifier,
        ledger=ledger,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
