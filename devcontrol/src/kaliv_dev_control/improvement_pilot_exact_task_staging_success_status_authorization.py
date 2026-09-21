"""ADR-DC-087 dual-authorized one-shot staging success Deployment Status.

Consumes exactly one fresh live ADR-DC-086 observation whose success-status lane
is still ``clear``. A host-admin-pinned config and two independent detached
Ed25519 signatures authorize only the frozen ADR-DC-085 ``success`` intent.

The success-intent digest is durably consumed before authority is published and
the exact lane is double-observed again after that durable lock. This boundary
performs no GitHub mutation. Deployment mutation and production activation stay
forbidden; only the later ADR-DC-088 transaction may consume the narrow success
Deployment Status write authority.
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
from . import improvement_pilot_exact_task_remote_publication_transaction as publication_tx_boundary
from . import improvement_pilot_exact_task_staging_success_status_plan as plan_boundary
from . import improvement_pilot_exact_task_staging_success_status_state_observation as state_boundary
from .improvement_pilot_exact_task_staging_success_status_state_observation import (
    PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_STATE_OBSERVATION_AUTHORITY,
    PilotExactTaskStagingSuccessStatusStateObservationReceipt,
)

PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_AUTHORIZATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-staging-success-status-authorization-receipt/v1"
)
PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_AUTHORIZATION_AUTHORITY = (
    "dual-authorized-one-dc-l16-exact-staging-success-status-only"
)
PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_AUTHORIZATION_SCOPE = (
    "one-shot-exact-staging-success-status-only-v1"
)
PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_AUTHORIZATION_CONFIG_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-staging-success-status-authorization-config/v1"
)
PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_AUTHORIZATION_KEYRING_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-staging-success-status-authorization-keyring/v1"
)
PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_AUTHORIZATION_CLAIM_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-staging-success-status-authorization-claim/v1"
)
PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_AUTHORIZATION_LEDGER_SCOPE = (
    "canonical-host-local-v1"
)

_MAX_FILE_BYTES = 1024 * 1024
_MAX_AUTH_SECONDS = 10 * 60
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-staging-success-status-authorization-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-staging-success-status-authorization-ledger-v1"
)
_POSIX_CONFIG = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-pilot-exact-task-staging-success-status-authorization-config-v1.json"
)
_WINDOWS_CONFIG = (
    Path(r"C:\Program Files\ModelRig\DevControl\authority")
    / "rsi-pilot-exact-task-staging-success-status-authorization-config-v1.json"
)
_POSIX_KEYRING = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-pilot-exact-task-staging-success-status-authorization-keyring-v1.json"
)
_WINDOWS_KEYRING = (
    Path(r"C:\Program Files\ModelRig\DevControl\authority")
    / "rsi-pilot-exact-task-staging-success-status-authorization-keyring-v1.json"
)


class PilotExactTaskStagingSuccessStatusAuthorizationError(ValueError):
    """Success Deployment Status authority is stale, replayed, or over-broad."""


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
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "success-status authorization evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    try:
        return shared_auth._hex40(value, name=name)
    except ValueError as exc:
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(str(exc)) from exc


def _hex64(value: Any, *, name: str) -> str:
    try:
        return shared_auth._hex64(value, name=name)
    except ValueError as exc:
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(str(exc)) from exc


def _utc(value: Any, *, name: str):
    try:
        return shared_auth._utc(value, name=name)
    except ValueError as exc:
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(str(exc)) from exc


def _now_utc_seconds() -> str:
    return shared_auth._now_utc_seconds()


@dataclass(frozen=True, slots=True)
class PilotExactTaskStagingSuccessStatusAuthorizationConfig:
    repository: str
    repository_id: str
    deployment_environment: str = "staging"
    required_remote_state_class: str = "clear"
    deployment_status_state: str = "success"
    deployment_status_environment: str = "staging"
    deployment_status_auto_inactive: bool = False
    allow_log_url: bool = False
    allow_environment_url: bool = False
    schema: str = PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_AUTHORIZATION_CONFIG_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_AUTHORIZATION_CONFIG_SCHEMA:
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "success-status authorization config schema is unsupported"
            )
        if (
            not isinstance(self.repository, str)
            or shared_auth._REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or shared_auth._REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "repository identity is invalid"
            )
        if (
            self.deployment_environment != "staging"
            or self.required_remote_state_class != "clear"
            or self.deployment_status_state != "success"
            or self.deployment_status_environment != "staging"
            or self.deployment_status_auto_inactive is not False
            or self.allow_log_url is not False
            or self.allow_environment_url is not False
        ):
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "config weakens fixed staging success-status scope"
            )

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "config fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _parse_config(payload: bytes) -> PilotExactTaskStagingSuccessStatusAuthorizationConfig:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "config payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "config JSON is invalid"
        ) from exc
    config = PilotExactTaskStagingSuccessStatusAuthorizationConfig.from_mapping(raw)
    if config.canonical_json().encode("utf-8") != payload:
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "config is not canonical JSON"
        )
    return config


def _parse_keyring(payload: bytes) -> tuple[Ed25519AuthorityVerifier, str]:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "keyring payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "keyring JSON is invalid"
        ) from exc
    if (
        not isinstance(raw, dict)
        or set(raw) != {"schema", "minimum_keyring_epoch", "keys"}
        or raw.get("schema")
        != PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_AUTHORIZATION_KEYRING_SCHEMA
    ):
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "keyring schema/fields mismatch"
        )
    epoch, key_items = raw["minimum_keyring_epoch"], raw["keys"]
    if (
        isinstance(epoch, bool)
        or not isinstance(epoch, int)
        or epoch < 1
        or not isinstance(key_items, list)
        or not 2 <= len(key_items) <= 64
    ):
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "keyring content is invalid"
        )
    keys: dict[str, TrustedEd25519AuthorityKey] = {}
    for item in key_items:
        try:
            key = TrustedEd25519AuthorityKey.from_mapping(item)
        except Exception as exc:
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "trusted key is invalid"
            ) from exc
        if key.key_id in keys:
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "duplicate key ID"
            )
        keys[key.key_id] = key
    if list(keys) != sorted(keys):
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "keyring keys must be sorted"
        )
    expected = _canonical(
        {
            "schema": PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_AUTHORIZATION_KEYRING_SCHEMA,
            "minimum_keyring_epoch": epoch,
            "keys": [keys[key_id].to_dict() for key_id in sorted(keys)],
        }
    ).encode("utf-8")
    if expected != payload:
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "keyring is not canonical JSON"
        )
    return (
        Ed25519AuthorityVerifier(keys, minimum_keyring_epoch=epoch),
        hashlib.sha256(payload).hexdigest(),
    )


def _read_host_authority_file(path: Path) -> bytes:
    try:
        data = lifecycle_auth_boundary._read_host_authority_file(path)
    except Exception as exc:
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "authority file is not host-admin controlled"
        ) from exc
    if not data or len(data) > _MAX_FILE_BYTES:
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "authority file is invalid"
        )
    return data


def _live_plan_for_observation(
    observation: PilotExactTaskStagingSuccessStatusStateObservationReceipt,
):
    live = state_boundary._get_live_staging_success_status_state_observation_inputs(
        observation
    )
    plan = None if live is None else live.get("staging_success_status_plan")
    if (
        plan is None
        or getattr(plan, "plan_authenticated", False) is not True
        or getattr(plan, "sha256", None) != observation.staging_success_status_plan_sha256
    ):
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "ADR-DC-085 live success-status plan provenance is unavailable"
        )
    return plan


def _require_live_clear_state(
    value: Any,
) -> PilotExactTaskStagingSuccessStatusStateObservationReceipt:
    if type(value) is not PilotExactTaskStagingSuccessStatusStateObservationReceipt:
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "exact live ADR-DC-086 success-status observation is required"
        )
    try:
        replayed = (
            PilotExactTaskStagingSuccessStatusStateObservationReceipt.from_mapping(
                value.to_dict()
            )
        )
    except Exception as exc:
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "ADR-DC-086 replay validation failed"
        ) from exc
    required_true = (
        "plan_authenticated",
        "parent_deployment_verified",
        "remote_repository_verified",
        "current_in_progress_status_verified",
        "status_inventory_bounded",
        "success_status_state_verified",
        "double_observation_matched",
        "success_status_state_acceptable",
        "success_deployment_status_ready",
        "success_status_lane_clear",
    )
    forced_false = (
        "exact_existing_success_status",
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
        "production_activation_authorized",
        "product_pilot_started",
        "nonce_reusable",
    )
    if (
        replayed != value
        or replayed.sha256 != value.sha256
        or value.authority
        != PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_STATE_OBSERVATION_AUTHORITY
        or value.observation_authenticated is not True
        or value.remote_state_class != "clear"
        or value.success_deployment_status_id is not None
        or value.success_deployment_status_node_id_sha256 is not None
        or value.observed_success_status_state is not None
        or value.observed_success_status_environment is not None
        or value.observed_success_status_description_sha256 is not None
        or value.observed_success_status_log_url is not None
        or value.observed_success_status_environment_url is not None
        or value.success_status_created_at_utc is not None
        or value.success_status_updated_at_utc is not None
        or value.success_deployment_status_state_planned != "success"
        or value.success_deployment_status_environment_planned != "staging"
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
    ):
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "ADR-DC-087 requires one fresh clear ADR-DC-086 success-status lane"
        )
    _live_plan_for_observation(value)
    return value


def _validate_config_for_observation(
    config: PilotExactTaskStagingSuccessStatusAuthorizationConfig,
    observation: PilotExactTaskStagingSuccessStatusStateObservationReceipt,
) -> None:
    if (
        config.repository != observation.repository
        or config.repository_id != observation.repository_id
        or config.deployment_environment != "staging"
        or config.required_remote_state_class != observation.remote_state_class
        or config.deployment_status_state
        != observation.success_deployment_status_state_planned
        or config.deployment_status_environment
        != observation.success_deployment_status_environment_planned
        or config.deployment_status_auto_inactive is not False
        or config.allow_log_url is not False
        or config.allow_environment_url is not False
    ):
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "host config does not match exact ADR-DC-086 target"
        )


def _fresh_revalidate_clear_lane(
    observation: PilotExactTaskStagingSuccessStatusStateObservationReceipt,
    transport: Any,
) -> str:
    observation = _require_live_clear_state(observation)
    plan = _live_plan_for_observation(observation)
    if transport is None or not callable(getattr(transport, "observe", None)):
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "fresh read-only success-status observer is required"
        )
    if (
        getattr(transport, "credential_config_sha256", None)
        != observation.publisher_credential_config_sha256
        or getattr(transport, "credential_path_sha256", None)
        != observation.publisher_credential_path_sha256
    ):
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "observer credential identity differs from ADR-DC-086"
        )
    try:
        first = state_boundary._normalize_remote_state(transport.observe(plan), plan)
        second = state_boundary._normalize_remote_state(transport.observe(plan), plan)
    except Exception as exc:
        if isinstance(exc, PilotExactTaskStagingSuccessStatusAuthorizationError):
            raise
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "fresh staging success-status revalidation failed"
        ) from exc
    if first != second:
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "remote staging success-status state changed during revalidation"
        )
    if (
        first.remote_state_class != "clear"
        or first.sha256 != observation.remote_success_status_state_sha256
    ):
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "remote staging success-status lane is no longer exact clear state"
        )
    return first.sha256


def _status_plan(observation):
    return _live_plan_for_observation(_require_live_clear_state(observation))


def _build_authorization_payload(
    *,
    success_status_state_observation: PilotExactTaskStagingSuccessStatusStateObservationReceipt,
    success_status_config: PilotExactTaskStagingSuccessStatusAuthorizationConfig,
    requested_at_utc: str,
    expires_at_utc: str,
    operator_actor_id: str,
    operator_system_id: str,
    operator_key_id: str,
    reviewer_actor_id: str,
    reviewer_system_id: str,
    reviewer_key_id: str,
) -> bytes:
    observation = _require_live_clear_state(success_status_state_observation)
    plan = _status_plan(observation)
    _validate_config_for_observation(success_status_config, observation)
    requested = _utc(requested_at_utc, name="requested_at_utc")
    expires = _utc(expires_at_utc, name="expires_at_utc")
    if not requested < expires or (expires - requested).total_seconds() > _MAX_AUTH_SECONDS:
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
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
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                f"{name} is invalid"
            )
    if (
        operator_actor_id == reviewer_actor_id
        or operator_system_id == reviewer_system_id
        or operator_key_id == reviewer_key_id
    ):
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "operator and reviewer identities must be independent"
        )
    values = {
        "schema": PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_AUTHORIZATION_CLAIM_SCHEMA,
        "success_status_state_observation_sha256": observation.sha256,
        "staging_success_status_plan_sha256": observation.staging_success_status_plan_sha256,
        "staging_runtime_build_identity_sha256": observation.staging_runtime_build_identity_sha256,
        "success_deployment_status_intent_sha256": observation.success_deployment_status_intent_sha256,
        "deployment_status_intent_sha256": observation.deployment_status_intent_sha256,
        "status_transaction_lock_sha256": observation.status_transaction_lock_sha256,
        "status_recovery_lock_sha256": observation.status_recovery_lock_sha256,
        "remote_success_status_state_sha256": observation.remote_success_status_state_sha256,
        "success_status_authorization_config_sha256": success_status_config.sha256,
        "publisher_credential_config_sha256": observation.publisher_credential_config_sha256,
        "publisher_credential_path_sha256": observation.publisher_credential_path_sha256,
        "repository": observation.repository,
        "repository_id": observation.repository_id,
        "deployment_environment": "staging",
        "merge_commit_sha": observation.merge_commit_sha,
        "deployment_id": observation.deployment_id,
        "deployment_node_id_sha256": observation.deployment_node_id_sha256,
        "current_deployment_status_id": observation.current_deployment_status_id,
        "current_deployment_status_node_id_sha256": observation.current_deployment_status_node_id_sha256,
        "success_deployment_status_state": observation.success_deployment_status_state_planned,
        "success_deployment_status_environment": observation.success_deployment_status_environment_planned,
        "success_deployment_status_description": plan.success_deployment_status_description,
        "success_deployment_status_description_sha256": observation.success_deployment_status_description_sha256,
        "success_deployment_status_body": plan.success_deployment_status_body,
        "success_deployment_status_body_sha256": observation.success_deployment_status_body_sha256,
        "success_deployment_status_auto_inactive": False,
        "success_deployment_status_log_url": None,
        "success_deployment_status_environment_url": None,
        "required_remote_state_class": "clear",
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
    "success_status_state_observation_sha256",
    "staging_success_status_plan_sha256",
    "staging_runtime_build_identity_sha256",
    "success_deployment_status_intent_sha256",
    "deployment_status_intent_sha256",
    "status_transaction_lock_sha256",
    "status_recovery_lock_sha256",
    "remote_success_status_state_sha256",
    "success_status_authorization_config_sha256",
    "publisher_credential_config_sha256",
    "publisher_credential_path_sha256",
    "repository",
    "repository_id",
    "deployment_environment",
    "merge_commit_sha",
    "deployment_id",
    "deployment_node_id_sha256",
    "current_deployment_status_id",
    "current_deployment_status_node_id_sha256",
    "success_deployment_status_state",
    "success_deployment_status_environment",
    "success_deployment_status_description",
    "success_deployment_status_description_sha256",
    "success_deployment_status_body",
    "success_deployment_status_body_sha256",
    "success_deployment_status_auto_inactive",
    "success_deployment_status_log_url",
    "success_deployment_status_environment_url",
    "required_remote_state_class",
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
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "authorization payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "authorization payload JSON is invalid"
        ) from exc
    if (
        not isinstance(raw, dict)
        or set(raw) != _CLAIM_FIELDS
        or raw.get("schema")
        != PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_AUTHORIZATION_CLAIM_SCHEMA
        or _canonical(raw).encode("utf-8") != payload
    ):
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "authorization payload fields/canonical form mismatch"
        )
    return raw


def _verify_claim_and_signatures(
    *,
    observation: PilotExactTaskStagingSuccessStatusStateObservationReceipt,
    config: PilotExactTaskStagingSuccessStatusAuthorizationConfig,
    payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_utc: str,
) -> dict[str, Any]:
    claim = _parse_claim(payload)
    expected_payload = _build_authorization_payload(
        success_status_state_observation=observation,
        success_status_config=config,
        requested_at_utc=claim["requested_at_utc"],
        expires_at_utc=claim["expires_at_utc"],
        operator_actor_id=claim["operator_actor_id"],
        operator_system_id=claim["operator_system_id"],
        operator_key_id=claim["operator_key_id"],
        reviewer_actor_id=claim["reviewer_actor_id"],
        reviewer_system_id=claim["reviewer_system_id"],
        reviewer_key_id=claim["reviewer_key_id"],
    )
    if expected_payload != payload:
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "authorization payload is not exactly bound"
        )
    now = _utc(now_utc, name="reserved_at_utc")
    requested = _utc(claim["requested_at_utc"], name="requested_at_utc")
    expires = _utc(claim["expires_at_utc"], name="expires_at_utc")
    if not requested <= now < expires:
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "authorization is not currently valid"
        )
    if (
        type(operator_signature) is not DetachedEd25519AuthoritySignature
        or type(reviewer_signature) is not DetachedEd25519AuthoritySignature
    ):
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "two detached Ed25519 signatures are required"
        )
    if (
        operator_signature.key_id == reviewer_signature.key_id
        or operator_signature.issuer_actor_id == reviewer_signature.issuer_actor_id
        or operator_signature.issuer_system_id == reviewer_signature.issuer_system_id
    ):
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "signatures must be independent"
        )
    payload_sha = hashlib.sha256(payload).hexdigest()
    for signature, actor_id, system_id, key_id in (
        (
            operator_signature,
            claim["operator_actor_id"],
            claim["operator_system_id"],
            claim["operator_key_id"],
        ),
        (
            reviewer_signature,
            claim["reviewer_actor_id"],
            claim["reviewer_system_id"],
            claim["reviewer_key_id"],
        ),
    ):
        if (
            signature.payload_sha256 != payload_sha
            or signature.issuer_actor_id != actor_id
            or signature.issuer_system_id != system_id
            or signature.key_id != key_id
        ):
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "signature binding mismatch"
            )
        signed = _utc(signature.signed_at_utc, name="signed_at_utc")
        if not requested <= signed < expires or signed > now:
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "signature timestamp is outside authorization window"
            )
        try:
            verifier.verify(payload=payload, signature=signature, at_utc=now_utc)
        except AsymmetricAuthorityError as exc:
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "Ed25519 verification failed"
            ) from exc
    return claim


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskStagingSuccessStatusAuthorizationReceipt:
    success_status_authorization_ledger_root_path_sha256: str
    success_status_key_sha256: str
    success_status_authorization_payload_sha256: str
    success_status_state_observation_sha256: str
    staging_success_status_plan_sha256: str
    staging_runtime_build_identity_sha256: str
    success_deployment_status_intent_sha256: str
    deployment_status_intent_sha256: str
    status_transaction_lock_sha256: str
    status_recovery_lock_sha256: str | None
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    success_status_authorization_config_sha256: str
    remote_success_status_state_sha256: str
    repository: str
    repository_id: str
    deployment_environment: str
    merge_commit_sha: str
    deployment_id: int
    deployment_node_id_sha256: str
    current_deployment_status_id: int
    current_deployment_status_node_id_sha256: str
    success_deployment_status_state: str
    success_deployment_status_environment: str
    success_deployment_status_description: str
    success_deployment_status_description_sha256: str
    success_deployment_status_body: str
    success_deployment_status_body_sha256: str
    success_deployment_status_auto_inactive: bool
    success_deployment_status_log_url: str | None
    success_deployment_status_environment_url: str | None
    required_remote_state_class: str
    operator_actor_id: str
    operator_system_id: str
    operator_key_id: str
    reviewer_actor_id: str
    reviewer_system_id: str
    reviewer_key_id: str
    source_observed_at_utc: str
    requested_at_utc: str
    expires_at_utc: str
    reserved_at_utc: str
    host_success_status_guard_committed: bool = True
    success_status_state_observation_authenticated: bool = True
    staging_success_status_plan_authenticated: bool = True
    success_status_lane_clear: bool = True
    success_status_authorization_config_host_pinned: bool = True
    dual_external_ed25519_authorized: bool = True
    success_deployment_status_authorized: bool = True
    deployment_status_mutation_authorized: bool = True
    remote_write_authorized: bool = True
    deployment_mutation_authorized: bool = False
    deploy_authorized: bool = False
    release_authorized: bool = False
    tag_write_authorized: bool = False
    release_mutation_authorized: bool = False
    merge_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    production_activation_authorized: bool = False
    product_pilot_started: bool = False
    nonce_reusable: bool = False
    authorization_scope: str = PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_AUTHORIZATION_SCOPE
    authority: str = PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_AUTHORIZATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_AUTHORIZATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_AUTHORIZATION_SCHEMA
            or self.authority != PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_AUTHORIZATION_AUTHORITY
            or self.authorization_scope != PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_AUTHORIZATION_SCOPE
        ):
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "receipt identity is unsupported"
            )
        for name in (
            "success_status_authorization_ledger_root_path_sha256",
            "success_status_key_sha256",
            "success_status_authorization_payload_sha256",
            "success_status_state_observation_sha256",
            "staging_success_status_plan_sha256",
            "staging_runtime_build_identity_sha256",
            "success_deployment_status_intent_sha256",
            "deployment_status_intent_sha256",
            "status_transaction_lock_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "success_status_authorization_config_sha256",
            "remote_success_status_state_sha256",
            "deployment_node_id_sha256",
            "current_deployment_status_node_id_sha256",
            "success_deployment_status_description_sha256",
            "success_deployment_status_body_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        if self.status_recovery_lock_sha256 is not None:
            _hex64(self.status_recovery_lock_sha256, name="status_recovery_lock_sha256")
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        if self.success_status_key_sha256 != self.success_deployment_status_intent_sha256:
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "replay key must equal exact success-status intent"
            )
        if (
            not isinstance(self.repository, str)
            or shared_auth._REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or shared_auth._REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.deployment_environment != "staging"
            or isinstance(self.deployment_id, bool)
            or not isinstance(self.deployment_id, int)
            or self.deployment_id < 1
            or isinstance(self.current_deployment_status_id, bool)
            or not isinstance(self.current_deployment_status_id, int)
            or self.current_deployment_status_id < 1
            or self.required_remote_state_class != "clear"
            or self.success_deployment_status_state != "success"
            or self.success_deployment_status_environment != "staging"
            or self.success_deployment_status_auto_inactive is not False
            or self.success_deployment_status_log_url is not None
            or self.success_deployment_status_environment_url is not None
        ):
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "receipt projection is invalid"
            )
        expected_description = (
            "ModelRig exact RSI staging runtime verified; "
            f"deployment={self.deployment_id}; sha={self.merge_commit_sha[:12]}"
        )
        expected_body = plan_boundary._status_body(
            state="success",
            description=expected_description,
            environment="staging",
            auto_inactive=False,
        )
        if (
            self.success_deployment_status_description != expected_description
            or hashlib.sha256(expected_description.encode("utf-8")).hexdigest()
            != self.success_deployment_status_description_sha256
            or self.success_deployment_status_body != expected_body
            or hashlib.sha256(expected_body.encode("utf-8")).hexdigest()
            != self.success_deployment_status_body_sha256
        ):
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "deterministic success Deployment Status request is invalid"
            )
        for name in ("operator_actor_id", "reviewer_actor_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or shared_auth._ACTOR.fullmatch(value) is None:
                raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                    f"{name} is invalid"
                )
        for name in (
            "operator_system_id",
            "operator_key_id",
            "reviewer_system_id",
            "reviewer_key_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or shared_auth._IDENTIFIER.fullmatch(value) is None:
                raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                    f"{name} is invalid"
                )
        if (
            self.operator_actor_id == self.reviewer_actor_id
            or self.operator_system_id == self.reviewer_system_id
            or self.operator_key_id == self.reviewer_key_id
        ):
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "receipt signers are not independent"
            )
        source_time = _utc(self.source_observed_at_utc, name="source_observed_at_utc")
        requested = _utc(self.requested_at_utc, name="requested_at_utc")
        expires = _utc(self.expires_at_utc, name="expires_at_utc")
        reserved = _utc(self.reserved_at_utc, name="reserved_at_utc")
        if (
            requested < source_time
            or not requested <= reserved < expires
            or (expires - requested).total_seconds() > _MAX_AUTH_SECONDS
        ):
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "receipt timestamps are invalid"
            )
        required_true = (
            "host_success_status_guard_committed",
            "success_status_state_observation_authenticated",
            "staging_success_status_plan_authenticated",
            "success_status_lane_clear",
            "success_status_authorization_config_host_pinned",
            "dual_external_ed25519_authorized",
            "success_deployment_status_authorized",
            "deployment_status_mutation_authorized",
            "remote_write_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "authorization evidence/authority is incomplete"
            )
        forced_false = (
            "deployment_mutation_authorized",
            "deploy_authorized",
            "release_authorized",
            "tag_write_authorized",
            "release_mutation_authorized",
            "merge_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "production_activation_authorized",
            "product_pilot_started",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "authorization grants forbidden extra authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def authorization_authenticated(self) -> bool:
        return _get_live_staging_success_status_authorization_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskStagingSuccessStatusAuthorizationLedger:
    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path]:
        digest = _hex64(key, name="success_status_key_sha256")
        return self.root / f"{digest}.json", self.root / f".{digest}.lock"

    def acquire(
        self,
        *,
        observation: PilotExactTaskStagingSuccessStatusStateObservationReceipt,
        payload: bytes,
        config_sha256: str,
        operator_signature: DetachedEd25519AuthoritySignature,
        reviewer_signature: DetachedEd25519AuthoritySignature,
    ) -> bytes:
        key = observation.success_deployment_status_intent_sha256
        final, lock = self._paths(key)
        if final.exists() or final.is_symlink() or lock.exists() or lock.is_symlink():
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "success-status intent already consumed or needs recovery"
            )
        lock_payload = _canonical(
            {
                "schema": (
                    "kaliv-rsi-dc-l16-exact-task-staging-success-status-authorization-lock/v1"
                ),
                "ledger_scope": PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_AUTHORIZATION_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "success_status_key_sha256": key,
                "success_status_state_observation_sha256": observation.sha256,
                "staging_success_status_plan_sha256": observation.staging_success_status_plan_sha256,
                "success_deployment_status_intent_sha256": observation.success_deployment_status_intent_sha256,
                "remote_success_status_state_sha256": observation.remote_success_status_state_sha256,
                "success_status_authorization_payload_sha256": hashlib.sha256(payload).hexdigest(),
                "success_status_authorization_config_sha256": config_sha256,
                "repository": observation.repository,
                "repository_id": observation.repository_id,
                "deployment_id": observation.deployment_id,
                "deployment_node_id_sha256": observation.deployment_node_id_sha256,
                "current_deployment_status_id": observation.current_deployment_status_id,
                "success_deployment_status_state": observation.success_deployment_status_state_planned,
                "success_deployment_status_environment": observation.success_deployment_status_environment_planned,
                "success_deployment_status_description_sha256": observation.success_deployment_status_description_sha256,
                "success_deployment_status_body_sha256": observation.success_deployment_status_body_sha256,
                "operator_signature_sha256": hashlib.sha256(
                    operator_signature.canonical_json().encode("utf-8")
                ).hexdigest(),
                "reviewer_signature_sha256": hashlib.sha256(
                    reviewer_signature.canonical_json().encode("utf-8")
                ).hexdigest(),
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, lock_payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "success-status authorization could not be durably consumed"
            ) from exc
        return lock_payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskStagingSuccessStatusAuthorizationReceipt,
        lock_payload: bytes,
        observation: PilotExactTaskStagingSuccessStatusStateObservationReceipt,
        config: PilotExactTaskStagingSuccessStatusAuthorizationConfig,
        plan: Any,
    ) -> PilotExactTaskStagingSuccessStatusAuthorizationReceipt:
        final, lock = self._paths(receipt.success_status_key_sha256)
        try:
            observed_lock = lock.read_bytes()
        except OSError as exc:
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "success-status authorization lock is unavailable"
            ) from exc
        if final.exists() or final.is_symlink() or observed_lock != lock_payload:
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "durable success-status authorization state changed"
            )
        final_payload = receipt.canonical_json().encode("utf-8")
        try:
            create_once_file(final, final_payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "success-status authorization receipt could not be published"
            ) from exc
        parsed = PilotExactTaskStagingSuccessStatusAuthorizationReceipt.from_mapping(
            json.loads(final_payload.decode("utf-8"))
        )
        _mark_staging_success_status_authorization_authenticated(
            parsed,
            observation=observation,
            config=config,
            plan=plan,
            final_path=final,
            final_payload=final_payload,
            lock_path=lock,
            lock_payload=lock_payload,
        )
        if parsed.authorization_authenticated is not True:
            raise PilotExactTaskStagingSuccessStatusAuthorizationError(
                "success-status authorization lost live provenance"
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
        receipt: PilotExactTaskStagingSuccessStatusAuthorizationReceipt,
        *,
        observation: PilotExactTaskStagingSuccessStatusStateObservationReceipt,
        config: PilotExactTaskStagingSuccessStatusAuthorizationConfig,
        plan: Any,
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
            weakref.ref(observation),
            weakref.ref(plan),
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
            observation_ref,
            plan_ref,
            config,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
        ) = entry
        observation, plan = observation_ref(), plan_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or observation is None
            or plan is None
            or receipt.sha256 != digest
            or observation.observation_authenticated is not True
            or observation.sha256 != receipt.success_status_state_observation_sha256
            or observation.remote_state_class != "clear"
            or observation.success_status_lane_clear is not True
            or plan.plan_authenticated is not True
            or plan.sha256 != receipt.staging_success_status_plan_sha256
            or config.sha256 != receipt.success_status_authorization_config_sha256
            or _read_bound(final_path) != final_payload
            or _read_bound(lock_path) != lock_payload
        ):
            return None
        return MappingProxyType(
            {
                "success_status_state_observation": observation,
                "staging_success_status_plan": plan,
                "success_status_authorization_config": config,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_staging_success_status_authorization_authenticated,
    _get_live_staging_success_status_authorization_inputs,
) = _live_registry()


def _authorize_verified_pilot_exact_task_staging_success_status(
    *,
    success_status_state_observation: PilotExactTaskStagingSuccessStatusStateObservationReceipt,
    success_status_config: PilotExactTaskStagingSuccessStatusAuthorizationConfig,
    authorization_payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    ledger: _PilotExactTaskStagingSuccessStatusAuthorizationLedger,
    transport: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskStagingSuccessStatusAuthorizationReceipt:
    observation = _require_live_clear_state(success_status_state_observation)
    plan = _status_plan(observation)
    if type(success_status_config) is not PilotExactTaskStagingSuccessStatusAuthorizationConfig:
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "exact success-status config is required"
        )
    _validate_config_for_observation(success_status_config, observation)
    _fresh_revalidate_clear_lane(observation, transport)
    reserved_at = now_provider()
    claim = _verify_claim_and_signatures(
        observation=observation,
        config=success_status_config,
        payload=authorization_payload,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
        verifier=verifier,
        now_utc=reserved_at,
    )
    lock_payload = ledger.acquire(
        observation=observation,
        payload=authorization_payload,
        config_sha256=success_status_config.sha256,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
    )
    # Durable consumption happens before the second complete double observation.
    # Any drift burns this exact success-intent slot and publishes no authority.
    _fresh_revalidate_clear_lane(observation, transport)
    receipt = PilotExactTaskStagingSuccessStatusAuthorizationReceipt(
        success_status_authorization_ledger_root_path_sha256=ledger.root_sha256,
        success_status_key_sha256=observation.success_deployment_status_intent_sha256,
        success_status_authorization_payload_sha256=hashlib.sha256(
            authorization_payload
        ).hexdigest(),
        success_status_state_observation_sha256=observation.sha256,
        staging_success_status_plan_sha256=observation.staging_success_status_plan_sha256,
        staging_runtime_build_identity_sha256=observation.staging_runtime_build_identity_sha256,
        success_deployment_status_intent_sha256=observation.success_deployment_status_intent_sha256,
        deployment_status_intent_sha256=observation.deployment_status_intent_sha256,
        status_transaction_lock_sha256=observation.status_transaction_lock_sha256,
        status_recovery_lock_sha256=observation.status_recovery_lock_sha256,
        publisher_credential_config_sha256=observation.publisher_credential_config_sha256,
        publisher_credential_path_sha256=observation.publisher_credential_path_sha256,
        success_status_authorization_config_sha256=success_status_config.sha256,
        remote_success_status_state_sha256=observation.remote_success_status_state_sha256,
        repository=observation.repository,
        repository_id=observation.repository_id,
        deployment_environment="staging",
        merge_commit_sha=observation.merge_commit_sha,
        deployment_id=observation.deployment_id,
        deployment_node_id_sha256=observation.deployment_node_id_sha256,
        current_deployment_status_id=observation.current_deployment_status_id,
        current_deployment_status_node_id_sha256=(
            observation.current_deployment_status_node_id_sha256
        ),
        success_deployment_status_state=observation.success_deployment_status_state_planned,
        success_deployment_status_environment=(
            observation.success_deployment_status_environment_planned
        ),
        success_deployment_status_description=plan.success_deployment_status_description,
        success_deployment_status_description_sha256=(
            observation.success_deployment_status_description_sha256
        ),
        success_deployment_status_body=plan.success_deployment_status_body,
        success_deployment_status_body_sha256=(
            observation.success_deployment_status_body_sha256
        ),
        success_deployment_status_auto_inactive=False,
        success_deployment_status_log_url=None,
        success_deployment_status_environment_url=None,
        required_remote_state_class="clear",
        operator_actor_id=claim["operator_actor_id"],
        operator_system_id=claim["operator_system_id"],
        operator_key_id=claim["operator_key_id"],
        reviewer_actor_id=claim["reviewer_actor_id"],
        reviewer_system_id=claim["reviewer_system_id"],
        reviewer_key_id=claim["reviewer_key_id"],
        source_observed_at_utc=observation.observed_at_utc,
        requested_at_utc=claim["requested_at_utc"],
        expires_at_utc=claim["expires_at_utc"],
        reserved_at_utc=reserved_at,
    )
    return ledger.commit(
        receipt=receipt,
        lock_payload=lock_payload,
        observation=observation,
        config=success_status_config,
        plan=plan,
    )


def _canonical_paths() -> tuple[Path, Path, Path]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            return (
                _POSIX_CONFIG,
                _POSIX_KEYRING,
                _require_host_controlled_ledger_root(_POSIX_LEDGER),
            )
        if os.name == "nt":
            return (
                _WINDOWS_CONFIG,
                _WINDOWS_KEYRING,
                _require_host_controlled_ledger_root(_WINDOWS_LEDGER),
            )
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "platform is unsupported"
        )
    except PhysicalHostStateError as exc:
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "success-status authorization ledger is not host-admin controlled"
        ) from exc


def _canonical_config() -> PilotExactTaskStagingSuccessStatusAuthorizationConfig:
    config_path, _keyring_path, _ledger_root = _canonical_paths()
    first = _read_host_authority_file(config_path)
    second = _read_host_authority_file(config_path)
    if first != second:
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "config changed while being read"
        )
    return _parse_config(second)


def _canonical_runtime():
    config_path, keyring_path, ledger_root = _canonical_paths()
    first_config = _read_host_authority_file(config_path)
    second_config = _read_host_authority_file(config_path)
    if first_config != second_config:
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "config changed while being read"
        )
    first_keyring = _read_host_authority_file(keyring_path)
    second_keyring = _read_host_authority_file(keyring_path)
    if first_keyring != second_keyring:
        raise PilotExactTaskStagingSuccessStatusAuthorizationError(
            "keyring changed while being read"
        )
    config = _parse_config(second_config)
    verifier, _keyring_sha = _parse_keyring(second_keyring)
    return (
        config,
        verifier,
        _PilotExactTaskStagingSuccessStatusAuthorizationLedger(ledger_root),
    )


def build_pilot_exact_task_staging_success_status_authorization_payload(
    success_status_state_observation: PilotExactTaskStagingSuccessStatusStateObservationReceipt,
    requested_at_utc: str,
    expires_at_utc: str,
    operator_actor_id: str,
    operator_system_id: str,
    operator_key_id: str,
    reviewer_actor_id: str,
    reviewer_system_id: str,
    reviewer_key_id: str,
) -> bytes:
    """Build exact bytes for two independent staging-success authority signers."""
    return _build_authorization_payload(
        success_status_state_observation=success_status_state_observation,
        success_status_config=_canonical_config(),
        requested_at_utc=requested_at_utc,
        expires_at_utc=expires_at_utc,
        operator_actor_id=operator_actor_id,
        operator_system_id=operator_system_id,
        operator_key_id=operator_key_id,
        reviewer_actor_id=reviewer_actor_id,
        reviewer_system_id=reviewer_system_id,
        reviewer_key_id=reviewer_key_id,
    )


def authorize_pilot_exact_task_staging_success_status(
    success_status_state_observation: PilotExactTaskStagingSuccessStatusStateObservationReceipt,
    authorization_payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
) -> PilotExactTaskStagingSuccessStatusAuthorizationReceipt:
    """Reserve one exact staging success status; perform no GitHub mutation."""
    config, verifier, ledger = _canonical_runtime()
    credential, credential_digest, credential_path = (
        publication_tx_boundary._canonical_credential()
    )
    transport = state_boundary._GitHubStagingSuccessStatusStateObserver(
        credential=credential,
        credential_config_sha256=credential_digest,
        credential_path=credential_path,
    )
    return _authorize_verified_pilot_exact_task_staging_success_status(
        success_status_state_observation=success_status_state_observation,
        success_status_config=config,
        authorization_payload=authorization_payload,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
        verifier=verifier,
        ledger=ledger,
        transport=transport,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
