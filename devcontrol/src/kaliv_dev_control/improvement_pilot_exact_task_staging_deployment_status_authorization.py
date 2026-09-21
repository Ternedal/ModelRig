"""ADR-DC-079 dual-authorized one-shot first staging Deployment Status.

Accepts only one fresh live ADR-DC-078 observation whose exact first-status lane
is clear. A host-admin-pinned config and two independent detached Ed25519
signatures authorize only the frozen ADR-DC-077 ``in_progress`` status intent.

The status-intent digest is durably consumed before authority is published.
This boundary performs no GitHub mutation. Deployment mutation and production
activation remain forbidden.
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
from . import improvement_pilot_exact_task_staging_deployment_status_plan as plan_boundary
from . import improvement_pilot_exact_task_staging_deployment_status_state_observation as state_boundary
from .improvement_pilot_exact_task_staging_deployment_status_state_observation import (
    PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_STATE_OBSERVATION_AUTHORITY,
    PilotExactTaskStagingDeploymentStatusStateObservationReceipt,
)

PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_AUTHORIZATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-staging-deployment-status-authorization-receipt/v1"
)
PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_AUTHORIZATION_AUTHORITY = (
    "dual-authorized-one-dc-l16-exact-first-staging-deployment-status-only"
)
PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_AUTHORIZATION_SCOPE = (
    "one-shot-exact-first-staging-deployment-status-only-v1"
)
PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_AUTHORIZATION_CONFIG_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-staging-deployment-status-authorization-config/v1"
)
PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_AUTHORIZATION_KEYRING_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-staging-deployment-status-authorization-keyring/v1"
)
PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_AUTHORIZATION_CLAIM_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-staging-deployment-status-authorization-claim/v1"
)
PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_AUTHORIZATION_LEDGER_SCOPE = (
    "canonical-host-local-v1"
)

_MAX_FILE_BYTES = 1024 * 1024
_MAX_AUTH_SECONDS = 10 * 60
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-staging-deployment-status-authorization-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-staging-deployment-status-authorization-ledger-v1"
)
_POSIX_CONFIG = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-pilot-exact-task-staging-deployment-status-authorization-config-v1.json"
)
_WINDOWS_CONFIG = (
    Path(r"C:\Program Files\ModelRig\DevControl\authority")
    / "rsi-pilot-exact-task-staging-deployment-status-authorization-config-v1.json"
)
_POSIX_KEYRING = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-pilot-exact-task-staging-deployment-status-authorization-keyring-v1.json"
)
_WINDOWS_KEYRING = (
    Path(r"C:\Program Files\ModelRig\DevControl\authority")
    / "rsi-pilot-exact-task-staging-deployment-status-authorization-keyring-v1.json"
)


class PilotExactTaskStagingDeploymentStatusAuthorizationError(ValueError):
    """First Deployment Status authority is stale, replayed, or over-broad."""


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
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "authorization evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    try:
        return shared_auth._hex40(value, name=name)
    except ValueError as exc:
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(str(exc)) from exc


def _hex64(value: Any, *, name: str) -> str:
    try:
        return shared_auth._hex64(value, name=name)
    except ValueError as exc:
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(str(exc)) from exc


def _utc(value: Any, *, name: str):
    try:
        return shared_auth._utc(value, name=name)
    except ValueError as exc:
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(str(exc)) from exc


def _now_utc_seconds() -> str:
    return shared_auth._now_utc_seconds()


@dataclass(frozen=True, slots=True)
class PilotExactTaskStagingDeploymentStatusAuthorizationConfig:
    repository: str
    repository_id: str
    deployment_environment: str = "staging"
    required_remote_state_class: str = "clear"
    deployment_status_state: str = "in_progress"
    deployment_status_environment: str = "staging"
    deployment_status_auto_inactive: bool = False
    allow_log_url: bool = False
    allow_environment_url: bool = False
    schema: str = PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_AUTHORIZATION_CONFIG_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_AUTHORIZATION_CONFIG_SCHEMA:
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "config schema is unsupported"
            )
        if (
            not isinstance(self.repository, str)
            or shared_auth._REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or shared_auth._REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "repository identity is invalid"
            )
        if (
            self.deployment_environment != "staging"
            or self.required_remote_state_class != "clear"
            or self.deployment_status_state != "in_progress"
            or self.deployment_status_environment != "staging"
            or self.deployment_status_auto_inactive is not False
            or self.allow_log_url is not False
            or self.allow_environment_url is not False
        ):
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "config weakens fixed first-status scope"
            )

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "config fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _parse_config(payload: bytes) -> PilotExactTaskStagingDeploymentStatusAuthorizationConfig:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "config payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "config JSON is invalid"
        ) from exc
    config = PilotExactTaskStagingDeploymentStatusAuthorizationConfig.from_mapping(raw)
    if config.canonical_json().encode("utf-8") != payload:
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "config is not canonical JSON"
        )
    return config


def _parse_keyring(payload: bytes) -> tuple[Ed25519AuthorityVerifier, str]:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "keyring payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "keyring JSON is invalid"
        ) from exc
    if (
        not isinstance(raw, dict)
        or set(raw) != {"schema", "minimum_keyring_epoch", "keys"}
        or raw.get("schema")
        != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_AUTHORIZATION_KEYRING_SCHEMA
    ):
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
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
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "keyring content is invalid"
        )
    keys: dict[str, TrustedEd25519AuthorityKey] = {}
    for item in key_items:
        try:
            key = TrustedEd25519AuthorityKey.from_mapping(item)
        except Exception as exc:
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "trusted key is invalid"
            ) from exc
        if key.key_id in keys:
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "duplicate key ID"
            )
        keys[key.key_id] = key
    if list(keys) != sorted(keys):
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "keyring keys must be sorted"
        )
    expected = _canonical(
        {
            "schema": PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_AUTHORIZATION_KEYRING_SCHEMA,
            "minimum_keyring_epoch": epoch,
            "keys": [keys[key_id].to_dict() for key_id in sorted(keys)],
        }
    ).encode("utf-8")
    if expected != payload:
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
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
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "authority file is not host-admin controlled"
        ) from exc
    if not data or len(data) > _MAX_FILE_BYTES:
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "authority file is invalid"
        )
    return data


def _live_plan_for_observation(
    observation: PilotExactTaskStagingDeploymentStatusStateObservationReceipt,
):
    live = state_boundary._get_live_staging_deployment_status_state_observation_inputs(
        observation
    )
    plan = None if live is None else live.get("staging_deployment_status_plan")
    if (
        plan is None
        or getattr(plan, "plan_authenticated", False) is not True
        or getattr(plan, "sha256", None)
        != observation.staging_deployment_status_plan_sha256
    ):
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "ADR-DC-077 live status plan provenance is unavailable"
        )
    return plan


def _require_live_clear_state(
    value: Any,
) -> PilotExactTaskStagingDeploymentStatusStateObservationReceipt:
    if type(value) is not PilotExactTaskStagingDeploymentStatusStateObservationReceipt:
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "exact live ADR-DC-078 observation is required"
        )
    try:
        replayed = (
            PilotExactTaskStagingDeploymentStatusStateObservationReceipt.from_mapping(
                value.to_dict()
            )
        )
    except Exception as exc:
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "ADR-DC-078 replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "ADR-DC-078 observation identity mismatch"
        )
    if (
        value.authority
        != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_STATE_OBSERVATION_AUTHORITY
        or value.observation_authenticated is not True
        or value.staging_deployment_status_plan_authenticated is not True
        or value.parent_deployment_verified is not True
        or value.remote_repository_verified is not True
        or value.status_inventory_bounded is not True
        or value.status_state_verified is not True
        or value.double_observation_matched is not True
        or value.status_state_acceptable is not True
        or value.remote_state_class != "clear"
        or value.deployment_status_lane_state != "absent"
        or value.deployment_status_id is not None
        or value.deployment_status_node_id_sha256 is not None
        or value.observed_status_state is not None
        or value.observed_status_environment is not None
        or value.observed_status_description_sha256 is not None
        or value.observed_status_log_url is not None
        or value.observed_status_environment_url is not None
        or value.status_created_at_utc is not None
        or value.status_updated_at_utc is not None
        or value.status_lane_clear is not True
        or value.exact_existing_status is not False
        or value.deployment_status_state_planned != "in_progress"
        or value.deployment_status_environment_planned != "staging"
        or value.deployment_status_auto_inactive_planned is not False
        or value.deployment_status_log_url_planned is not None
        or value.deployment_status_environment_url_planned is not None
        or value.deployment_status_mutation_authorized is not False
        or value.deployment_mutation_authorized is not False
        or value.deploy_authorized is not False
        or value.remote_write_authorized is not False
        or value.release_authorized is not False
        or value.production_activation_authorized is not False
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "ADR-DC-079 requires one fresh clear ADR-DC-078 status lane"
        )
    _live_plan_for_observation(value)
    return value


def _validate_config_for_observation(
    config: PilotExactTaskStagingDeploymentStatusAuthorizationConfig,
    observation: PilotExactTaskStagingDeploymentStatusStateObservationReceipt,
) -> None:
    if (
        config.repository != observation.repository
        or config.repository_id != observation.repository_id
        or config.deployment_environment != observation.deployment_environment
        or config.required_remote_state_class != observation.remote_state_class
        or config.deployment_status_state != observation.deployment_status_state_planned
        or config.deployment_status_environment
        != observation.deployment_status_environment_planned
        or config.deployment_status_auto_inactive
        != observation.deployment_status_auto_inactive_planned
        or config.allow_log_url is not False
        or config.allow_environment_url is not False
    ):
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "host config does not match exact ADR-DC-078 target"
        )


def _fresh_revalidate_clear_lane(
    observation: PilotExactTaskStagingDeploymentStatusStateObservationReceipt,
    transport: Any,
) -> str:
    observation = _require_live_clear_state(observation)
    plan = _live_plan_for_observation(observation)
    if transport is None or not callable(getattr(transport, "observe", None)):
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "fresh read-only Deployment Status observer is required"
        )
    if (
        getattr(transport, "credential_config_sha256", None)
        != observation.publisher_credential_config_sha256
        or getattr(transport, "credential_path_sha256", None)
        != observation.publisher_credential_path_sha256
    ):
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "observer credential identity differs from ADR-DC-078"
        )
    try:
        first = state_boundary._normalize_remote_state(transport.observe(plan), plan)
        second = state_boundary._normalize_remote_state(transport.observe(plan), plan)
    except Exception as exc:
        if isinstance(exc, PilotExactTaskStagingDeploymentStatusAuthorizationError):
            raise
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "fresh Deployment Status revalidation failed"
        ) from exc
    if first != second:
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "remote Deployment Status state changed during revalidation"
        )
    if (
        first.remote_state_class != "clear"
        or first.deployment_status_lane_state != "absent"
        or first.sha256 != observation.remote_deployment_status_state_sha256
    ):
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "remote Deployment Status lane is no longer exact clear state"
        )
    return first.sha256


def _status_plan(observation):
    return _live_plan_for_observation(_require_live_clear_state(observation))


def _build_authorization_payload(
    *,
    deployment_status_state_observation: PilotExactTaskStagingDeploymentStatusStateObservationReceipt,
    deployment_status_config: PilotExactTaskStagingDeploymentStatusAuthorizationConfig,
    requested_at_utc: str,
    expires_at_utc: str,
    operator_actor_id: str,
    operator_system_id: str,
    operator_key_id: str,
    reviewer_actor_id: str,
    reviewer_system_id: str,
    reviewer_key_id: str,
) -> bytes:
    observation = _require_live_clear_state(deployment_status_state_observation)
    plan = _status_plan(observation)
    _validate_config_for_observation(deployment_status_config, observation)
    requested = _utc(requested_at_utc, name="requested_at_utc")
    expires = _utc(expires_at_utc, name="expires_at_utc")
    if not requested < expires or (expires - requested).total_seconds() > _MAX_AUTH_SECONDS:
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
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
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                f"{name} is invalid"
            )
    if (
        operator_actor_id == reviewer_actor_id
        or operator_system_id == reviewer_system_id
        or operator_key_id == reviewer_key_id
    ):
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "operator and reviewer identities must be independent"
        )
    values = {
        "schema": PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_AUTHORIZATION_CLAIM_SCHEMA,
        "deployment_status_state_observation_sha256": observation.sha256,
        "staging_deployment_status_plan_sha256": observation.staging_deployment_status_plan_sha256,
        "post_staging_deployment_attestation_sha256": observation.post_staging_deployment_attestation_sha256,
        "completion_source_receipt_sha256": observation.completion_source_receipt_sha256,
        "deployment_authorization_sha256": observation.deployment_authorization_sha256,
        "staging_deployment_plan_sha256": observation.staging_deployment_plan_sha256,
        "deployment_intent_sha256": observation.deployment_intent_sha256,
        "execution_nonce_sha256": observation.execution_nonce_sha256,
        "deployment_status_intent_sha256": observation.deployment_status_intent_sha256,
        "remote_deployment_status_state_sha256": observation.remote_deployment_status_state_sha256,
        "deployment_status_authorization_config_sha256": deployment_status_config.sha256,
        "publisher_credential_config_sha256": observation.publisher_credential_config_sha256,
        "publisher_credential_path_sha256": observation.publisher_credential_path_sha256,
        "repository": observation.repository,
        "repository_id": observation.repository_id,
        "deployment_environment": observation.deployment_environment,
        "merge_commit_sha": observation.merge_commit_sha,
        "deployment_identity": observation.deployment_identity,
        "deployment_ref": observation.deployment_ref,
        "deployment_task": observation.deployment_task,
        "deployment_id": observation.deployment_id,
        "deployment_node_id_sha256": observation.deployment_node_id_sha256,
        "deployment_status_state": observation.deployment_status_state_planned,
        "deployment_status_environment": observation.deployment_status_environment_planned,
        "deployment_status_description": plan.deployment_status_description,
        "deployment_status_description_sha256": observation.deployment_status_description_sha256,
        "deployment_status_body": plan.deployment_status_body,
        "deployment_status_body_sha256": observation.deployment_status_body_sha256,
        "deployment_status_auto_inactive": False,
        "deployment_status_log_url": None,
        "deployment_status_environment_url": None,
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
    "deployment_status_state_observation_sha256",
    "staging_deployment_status_plan_sha256",
    "post_staging_deployment_attestation_sha256",
    "completion_source_receipt_sha256",
    "deployment_authorization_sha256",
    "staging_deployment_plan_sha256",
    "deployment_intent_sha256",
    "execution_nonce_sha256",
    "deployment_status_intent_sha256",
    "remote_deployment_status_state_sha256",
    "deployment_status_authorization_config_sha256",
    "publisher_credential_config_sha256",
    "publisher_credential_path_sha256",
    "repository",
    "repository_id",
    "deployment_environment",
    "merge_commit_sha",
    "deployment_identity",
    "deployment_ref",
    "deployment_task",
    "deployment_id",
    "deployment_node_id_sha256",
    "deployment_status_state",
    "deployment_status_environment",
    "deployment_status_description",
    "deployment_status_description_sha256",
    "deployment_status_body",
    "deployment_status_body_sha256",
    "deployment_status_auto_inactive",
    "deployment_status_log_url",
    "deployment_status_environment_url",
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
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "authorization payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "authorization payload JSON is invalid"
        ) from exc
    if (
        not isinstance(raw, dict)
        or set(raw) != _CLAIM_FIELDS
        or raw.get("schema")
        != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_AUTHORIZATION_CLAIM_SCHEMA
        or _canonical(raw).encode("utf-8") != payload
    ):
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "authorization payload fields/canonical form mismatch"
        )
    return raw


def _verify_claim_and_signatures(
    *,
    observation: PilotExactTaskStagingDeploymentStatusStateObservationReceipt,
    config: PilotExactTaskStagingDeploymentStatusAuthorizationConfig,
    payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_utc: str,
) -> dict[str, Any]:
    claim = _parse_claim(payload)
    expected_payload = _build_authorization_payload(
        deployment_status_state_observation=observation,
        deployment_status_config=config,
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
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "authorization payload is not exactly bound"
        )
    now = _utc(now_utc, name="reserved_at_utc")
    requested = _utc(claim["requested_at_utc"], name="requested_at_utc")
    expires = _utc(claim["expires_at_utc"], name="expires_at_utc")
    if not requested <= now < expires:
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "authorization is not currently valid"
        )
    if (
        type(operator_signature) is not DetachedEd25519AuthoritySignature
        or type(reviewer_signature) is not DetachedEd25519AuthoritySignature
    ):
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "two detached Ed25519 signatures are required"
        )
    if (
        operator_signature.key_id == reviewer_signature.key_id
        or operator_signature.issuer_actor_id == reviewer_signature.issuer_actor_id
        or operator_signature.issuer_system_id == reviewer_signature.issuer_system_id
    ):
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
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
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "signature binding mismatch"
            )
        signed = _utc(signature.signed_at_utc, name="signed_at_utc")
        if not requested <= signed < expires or signed > now:
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "signature timestamp is outside authorization window"
            )
        try:
            verifier.verify(payload=payload, signature=signature, at_utc=now_utc)
        except AsymmetricAuthorityError as exc:
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "Ed25519 verification failed"
            ) from exc
    return claim


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskStagingDeploymentStatusAuthorizationReceipt:
    status_authorization_ledger_root_path_sha256: str
    deployment_status_key_sha256: str
    deployment_status_authorization_payload_sha256: str
    deployment_status_state_observation_sha256: str
    staging_deployment_status_plan_sha256: str
    post_staging_deployment_attestation_sha256: str
    completion_source_receipt_sha256: str
    deployment_authorization_sha256: str
    deployment_state_observation_sha256: str
    staging_deployment_plan_sha256: str
    deploy_readiness_evaluation_sha256: str
    post_release_attestation_sha256: str
    deployment_intent_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    upstream_merge_transaction_lock_sha256: str
    release_transaction_lock_sha256: str
    transaction_lock_sha256: str
    recovery_lock_sha256: str | None
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    source_remote_observation_sha256: str
    staging_deployment_status_plan_config_sha256: str
    deployment_status_intent_sha256: str
    remote_deployment_status_state_sha256: str
    deployment_status_authorization_config_sha256: str
    repository: str
    repository_id: str
    deployment_environment: str
    merge_commit_sha: str
    deployment_identity: str
    deployment_ref: str
    deployment_task: str
    deployment_payload_sha256: str
    deployment_description_sha256: str
    deployment_id: int
    deployment_node_id_sha256: str
    completion_source: str
    source_action: str
    source_remote_write_performed: bool
    source_attested_at_utc: str
    deployment_status_state: str
    deployment_status_environment: str
    deployment_status_description: str
    deployment_status_description_sha256: str
    deployment_status_body: str
    deployment_status_body_sha256: str
    deployment_status_auto_inactive: bool
    deployment_status_log_url: str | None
    deployment_status_environment_url: str | None
    required_remote_state_class: str
    operator_actor_id: str
    operator_system_id: str
    operator_key_id: str
    reviewer_actor_id: str
    reviewer_system_id: str
    reviewer_key_id: str
    requested_at_utc: str
    expires_at_utc: str
    reserved_at_utc: str
    host_status_guard_committed: bool = True
    deployment_status_state_observation_authenticated: bool = True
    staging_deployment_status_plan_authenticated: bool = True
    status_lane_clear: bool = True
    deployment_status_authorization_config_host_pinned: bool = True
    dual_external_ed25519_authorized: bool = True
    first_deployment_status_authorized: bool = True
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
    authorization_scope: str = PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_AUTHORIZATION_SCOPE
    authority: str = PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_AUTHORIZATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_AUTHORIZATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_AUTHORIZATION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_AUTHORIZATION_AUTHORITY
            or self.authorization_scope
            != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_AUTHORIZATION_SCOPE
        ):
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "receipt identity is unsupported"
            )
        for name in (
            "status_authorization_ledger_root_path_sha256",
            "deployment_status_key_sha256",
            "deployment_status_authorization_payload_sha256",
            "deployment_status_state_observation_sha256",
            "staging_deployment_status_plan_sha256",
            "post_staging_deployment_attestation_sha256",
            "completion_source_receipt_sha256",
            "deployment_authorization_sha256",
            "deployment_state_observation_sha256",
            "staging_deployment_plan_sha256",
            "deploy_readiness_evaluation_sha256",
            "post_release_attestation_sha256",
            "deployment_intent_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
            "upstream_merge_transaction_lock_sha256",
            "release_transaction_lock_sha256",
            "transaction_lock_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "source_remote_observation_sha256",
            "staging_deployment_status_plan_config_sha256",
            "deployment_status_intent_sha256",
            "remote_deployment_status_state_sha256",
            "deployment_status_authorization_config_sha256",
            "deployment_payload_sha256",
            "deployment_description_sha256",
            "deployment_node_id_sha256",
            "deployment_status_description_sha256",
            "deployment_status_body_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        if self.recovery_lock_sha256 is not None:
            _hex64(self.recovery_lock_sha256, name="recovery_lock_sha256")
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        if self.deployment_status_key_sha256 != self.deployment_status_intent_sha256:
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "replay key must equal Deployment Status intent"
            )
        if (
            not isinstance(self.repository, str)
            or shared_auth._REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or shared_auth._REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.deployment_environment != "staging"
            or self.deployment_task != "deploy"
            or self.deployment_identity != f"modelrig-staging-{self.merge_commit_sha}"
            or self.deployment_ref != f"modelrig-rsi-{self.merge_commit_sha}"
            or isinstance(self.deployment_id, bool)
            or not isinstance(self.deployment_id, int)
            or self.deployment_id < 1
            or self.completion_source not in {"transaction", "recovery"}
            or self.source_action
            not in {"execute_exact_staging_deployment", "finalize_existing_state"}
            or not isinstance(self.source_remote_write_performed, bool)
            or self.required_remote_state_class != "clear"
            or self.deployment_status_state != "in_progress"
            or self.deployment_status_environment != "staging"
            or self.deployment_status_auto_inactive is not False
            or self.deployment_status_log_url is not None
            or self.deployment_status_environment_url is not None
        ):
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "receipt projection is invalid"
            )
        if self.completion_source == "transaction":
            if (
                self.source_action != "execute_exact_staging_deployment"
                or self.source_remote_write_performed is not True
                or self.recovery_lock_sha256 is not None
            ):
                raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                    "normal completion source is inconsistent"
                )
        elif (
            self.source_action != "finalize_existing_state"
            or self.source_remote_write_performed is not False
            or self.recovery_lock_sha256 is None
        ):
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "recovered completion source is inconsistent"
            )
        expected_description = (
            "ModelRig exact RSI staging verification in progress; "
            f"deployment={self.deployment_id}; sha={self.merge_commit_sha[:12]}"
        )
        if (
            self.deployment_status_description != expected_description
            or hashlib.sha256(
                self.deployment_status_description.encode("utf-8")
            ).hexdigest()
            != self.deployment_status_description_sha256
            or self.deployment_status_body
            != plan_boundary._status_body(
                state=self.deployment_status_state,
                description=self.deployment_status_description,
                environment=self.deployment_status_environment,
                auto_inactive=self.deployment_status_auto_inactive,
            )
            or hashlib.sha256(
                self.deployment_status_body.encode("utf-8")
            ).hexdigest()
            != self.deployment_status_body_sha256
        ):
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "deterministic Deployment Status request is invalid"
            )
        for name in ("operator_actor_id", "reviewer_actor_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or shared_auth._ACTOR.fullmatch(value) is None:
                raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
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
                raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                    f"{name} is invalid"
                )
        if (
            self.operator_actor_id == self.reviewer_actor_id
            or self.operator_system_id == self.reviewer_system_id
            or self.operator_key_id == self.reviewer_key_id
        ):
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "receipt signers are not independent"
            )
        source_time = _utc(self.source_attested_at_utc, name="source_attested_at_utc")
        requested = _utc(self.requested_at_utc, name="requested_at_utc")
        expires = _utc(self.expires_at_utc, name="expires_at_utc")
        reserved = _utc(self.reserved_at_utc, name="reserved_at_utc")
        if (
            requested < source_time
            or not requested <= reserved < expires
            or (expires - requested).total_seconds() > _MAX_AUTH_SECONDS
        ):
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "receipt timestamps are invalid"
            )
        required_true = (
            "host_status_guard_committed",
            "deployment_status_state_observation_authenticated",
            "staging_deployment_status_plan_authenticated",
            "status_lane_clear",
            "deployment_status_authorization_config_host_pinned",
            "dual_external_ed25519_authorized",
            "first_deployment_status_authorized",
            "deployment_status_mutation_authorized",
            "remote_write_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
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
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "authorization grants forbidden extra authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def authorization_authenticated(self) -> bool:
        return _get_live_staging_deployment_status_authorization_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskStagingDeploymentStatusAuthorizationLedger:
    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path]:
        digest = _hex64(key, name="deployment_status_key_sha256")
        return self.root / f"{digest}.json", self.root / f".{digest}.lock"

    def acquire(
        self,
        *,
        observation: PilotExactTaskStagingDeploymentStatusStateObservationReceipt,
        payload: bytes,
        config_sha256: str,
        operator_signature: DetachedEd25519AuthoritySignature,
        reviewer_signature: DetachedEd25519AuthoritySignature,
    ) -> bytes:
        key = observation.deployment_status_intent_sha256
        final, lock = self._paths(key)
        if final.exists() or final.is_symlink() or lock.exists() or lock.is_symlink():
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "Deployment Status intent already consumed or needs recovery"
            )
        lock_payload = _canonical(
            {
                "schema": (
                    "kaliv-rsi-dc-l16-exact-task-staging-deployment-status-authorization-lock/v1"
                ),
                "ledger_scope": PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_AUTHORIZATION_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "deployment_status_key_sha256": key,
                "deployment_status_state_observation_sha256": observation.sha256,
                "staging_deployment_status_plan_sha256": observation.staging_deployment_status_plan_sha256,
                "deployment_status_intent_sha256": observation.deployment_status_intent_sha256,
                "remote_deployment_status_state_sha256": observation.remote_deployment_status_state_sha256,
                "deployment_status_authorization_payload_sha256": hashlib.sha256(
                    payload
                ).hexdigest(),
                "deployment_status_authorization_config_sha256": config_sha256,
                "repository": observation.repository,
                "repository_id": observation.repository_id,
                "deployment_id": observation.deployment_id,
                "deployment_node_id_sha256": observation.deployment_node_id_sha256,
                "deployment_status_state": observation.deployment_status_state_planned,
                "deployment_status_environment": observation.deployment_status_environment_planned,
                "deployment_status_description_sha256": observation.deployment_status_description_sha256,
                "deployment_status_body_sha256": observation.deployment_status_body_sha256,
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
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "Deployment Status authorization could not be durably consumed"
            ) from exc
        return lock_payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskStagingDeploymentStatusAuthorizationReceipt,
        lock_payload: bytes,
        observation: PilotExactTaskStagingDeploymentStatusStateObservationReceipt,
        config: PilotExactTaskStagingDeploymentStatusAuthorizationConfig,
        plan: Any,
    ) -> PilotExactTaskStagingDeploymentStatusAuthorizationReceipt:
        final, lock = self._paths(receipt.deployment_status_key_sha256)
        try:
            observed_lock = lock.read_bytes()
        except OSError as exc:
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "Deployment Status authorization lock is unavailable"
            ) from exc
        if final.exists() or final.is_symlink() or observed_lock != lock_payload:
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "durable Deployment Status authorization state changed"
            )
        final_payload = receipt.canonical_json().encode("utf-8")
        try:
            create_once_file(final, final_payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "Deployment Status authorization receipt could not be published"
            ) from exc
        parsed = PilotExactTaskStagingDeploymentStatusAuthorizationReceipt.from_mapping(
            json.loads(final_payload.decode("utf-8"))
        )
        _mark_staging_deployment_status_authorization_authenticated(
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
            raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
                "Deployment Status authorization lost live provenance"
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
        receipt: PilotExactTaskStagingDeploymentStatusAuthorizationReceipt,
        *,
        observation: PilotExactTaskStagingDeploymentStatusStateObservationReceipt,
        config: PilotExactTaskStagingDeploymentStatusAuthorizationConfig,
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
            or observation.sha256
            != receipt.deployment_status_state_observation_sha256
            or observation.remote_state_class != "clear"
            or observation.status_lane_clear is not True
            or plan.plan_authenticated is not True
            or plan.sha256 != receipt.staging_deployment_status_plan_sha256
            or config.sha256
            != receipt.deployment_status_authorization_config_sha256
            or _read_bound(final_path) != final_payload
            or _read_bound(lock_path) != lock_payload
        ):
            return None
        return MappingProxyType(
            {
                "deployment_status_state_observation": observation,
                "staging_deployment_status_plan": plan,
                "deployment_status_authorization_config": config,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_staging_deployment_status_authorization_authenticated,
    _get_live_staging_deployment_status_authorization_inputs,
) = _live_registry()


def _authorize_verified_pilot_exact_task_staging_deployment_status(
    *,
    deployment_status_state_observation: PilotExactTaskStagingDeploymentStatusStateObservationReceipt,
    deployment_status_config: PilotExactTaskStagingDeploymentStatusAuthorizationConfig,
    authorization_payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    ledger: _PilotExactTaskStagingDeploymentStatusAuthorizationLedger,
    transport: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskStagingDeploymentStatusAuthorizationReceipt:
    observation = _require_live_clear_state(deployment_status_state_observation)
    plan = _status_plan(observation)
    if type(deployment_status_config) is not PilotExactTaskStagingDeploymentStatusAuthorizationConfig:
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "exact Deployment Status config is required"
        )
    _validate_config_for_observation(deployment_status_config, observation)
    _fresh_revalidate_clear_lane(observation, transport)
    reserved_at = now_provider()
    claim = _verify_claim_and_signatures(
        observation=observation,
        config=deployment_status_config,
        payload=authorization_payload,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
        verifier=verifier,
        now_utc=reserved_at,
    )
    lock_payload = ledger.acquire(
        observation=observation,
        payload=authorization_payload,
        config_sha256=deployment_status_config.sha256,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
    )
    # Critical race closure: durable consumption happens before the second
    # double observation. Drift burns the status-intent slot and publishes no authority.
    _fresh_revalidate_clear_lane(observation, transport)
    receipt = PilotExactTaskStagingDeploymentStatusAuthorizationReceipt(
        status_authorization_ledger_root_path_sha256=ledger.root_sha256,
        deployment_status_key_sha256=observation.deployment_status_intent_sha256,
        deployment_status_authorization_payload_sha256=hashlib.sha256(
            authorization_payload
        ).hexdigest(),
        deployment_status_state_observation_sha256=observation.sha256,
        staging_deployment_status_plan_sha256=observation.staging_deployment_status_plan_sha256,
        post_staging_deployment_attestation_sha256=observation.post_staging_deployment_attestation_sha256,
        completion_source_receipt_sha256=observation.completion_source_receipt_sha256,
        deployment_authorization_sha256=observation.deployment_authorization_sha256,
        deployment_state_observation_sha256=observation.deployment_state_observation_sha256,
        staging_deployment_plan_sha256=observation.staging_deployment_plan_sha256,
        deploy_readiness_evaluation_sha256=observation.deploy_readiness_evaluation_sha256,
        post_release_attestation_sha256=observation.post_release_attestation_sha256,
        deployment_intent_sha256=observation.deployment_intent_sha256,
        execution_nonce_sha256=observation.execution_nonce_sha256,
        development_task_sha256=observation.development_task_sha256,
        candidate_patch_sha256=observation.candidate_patch_sha256,
        pr_intent_sha256=observation.pr_intent_sha256,
        upstream_merge_transaction_lock_sha256=observation.upstream_merge_transaction_lock_sha256,
        release_transaction_lock_sha256=observation.release_transaction_lock_sha256,
        transaction_lock_sha256=observation.transaction_lock_sha256,
        recovery_lock_sha256=observation.recovery_lock_sha256,
        publisher_credential_config_sha256=observation.publisher_credential_config_sha256,
        publisher_credential_path_sha256=observation.publisher_credential_path_sha256,
        source_remote_observation_sha256=observation.source_remote_observation_sha256,
        staging_deployment_status_plan_config_sha256=observation.staging_deployment_status_plan_config_sha256,
        deployment_status_intent_sha256=observation.deployment_status_intent_sha256,
        remote_deployment_status_state_sha256=observation.remote_deployment_status_state_sha256,
        deployment_status_authorization_config_sha256=deployment_status_config.sha256,
        repository=observation.repository,
        repository_id=observation.repository_id,
        deployment_environment=observation.deployment_environment,
        merge_commit_sha=observation.merge_commit_sha,
        deployment_identity=observation.deployment_identity,
        deployment_ref=observation.deployment_ref,
        deployment_task=observation.deployment_task,
        deployment_payload_sha256=observation.deployment_payload_sha256,
        deployment_description_sha256=observation.deployment_description_sha256,
        deployment_id=observation.deployment_id,
        deployment_node_id_sha256=observation.deployment_node_id_sha256,
        completion_source=observation.completion_source,
        source_action=observation.source_action,
        source_remote_write_performed=observation.source_remote_write_performed,
        source_attested_at_utc=observation.source_attested_at_utc,
        deployment_status_state=observation.deployment_status_state_planned,
        deployment_status_environment=observation.deployment_status_environment_planned,
        deployment_status_description=plan.deployment_status_description,
        deployment_status_description_sha256=observation.deployment_status_description_sha256,
        deployment_status_body=plan.deployment_status_body,
        deployment_status_body_sha256=observation.deployment_status_body_sha256,
        deployment_status_auto_inactive=False,
        deployment_status_log_url=None,
        deployment_status_environment_url=None,
        required_remote_state_class="clear",
        operator_actor_id=claim["operator_actor_id"],
        operator_system_id=claim["operator_system_id"],
        operator_key_id=claim["operator_key_id"],
        reviewer_actor_id=claim["reviewer_actor_id"],
        reviewer_system_id=claim["reviewer_system_id"],
        reviewer_key_id=claim["reviewer_key_id"],
        requested_at_utc=claim["requested_at_utc"],
        expires_at_utc=claim["expires_at_utc"],
        reserved_at_utc=reserved_at,
    )
    return ledger.commit(
        receipt=receipt,
        lock_payload=lock_payload,
        observation=observation,
        config=deployment_status_config,
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
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "platform is unsupported"
        )
    except PhysicalHostStateError as exc:
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "Deployment Status authorization ledger is not host-admin controlled"
        ) from exc


def _canonical_config() -> PilotExactTaskStagingDeploymentStatusAuthorizationConfig:
    config_path, _keyring_path, _ledger_root = _canonical_paths()
    first = _read_host_authority_file(config_path)
    second = _read_host_authority_file(config_path)
    if first != second:
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "config changed while being read"
        )
    return _parse_config(second)


def _canonical_runtime():
    config_path, keyring_path, ledger_root = _canonical_paths()
    first_config = _read_host_authority_file(config_path)
    second_config = _read_host_authority_file(config_path)
    if first_config != second_config:
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "config changed while being read"
        )
    first_keyring = _read_host_authority_file(keyring_path)
    second_keyring = _read_host_authority_file(keyring_path)
    if first_keyring != second_keyring:
        raise PilotExactTaskStagingDeploymentStatusAuthorizationError(
            "keyring changed while being read"
        )
    config = _parse_config(second_config)
    verifier, _keyring_sha = _parse_keyring(second_keyring)
    return (
        config,
        verifier,
        _PilotExactTaskStagingDeploymentStatusAuthorizationLedger(ledger_root),
    )


def build_pilot_exact_task_staging_deployment_status_authorization_payload(
    deployment_status_state_observation: PilotExactTaskStagingDeploymentStatusStateObservationReceipt,
    requested_at_utc: str,
    expires_at_utc: str,
    operator_actor_id: str,
    operator_system_id: str,
    operator_key_id: str,
    reviewer_actor_id: str,
    reviewer_system_id: str,
    reviewer_key_id: str,
) -> bytes:
    """Build exact bytes for two independent first-status authority signers."""
    return _build_authorization_payload(
        deployment_status_state_observation=deployment_status_state_observation,
        deployment_status_config=_canonical_config(),
        requested_at_utc=requested_at_utc,
        expires_at_utc=expires_at_utc,
        operator_actor_id=operator_actor_id,
        operator_system_id=operator_system_id,
        operator_key_id=operator_key_id,
        reviewer_actor_id=reviewer_actor_id,
        reviewer_system_id=reviewer_system_id,
        reviewer_key_id=reviewer_key_id,
    )


def authorize_pilot_exact_task_staging_deployment_status(
    deployment_status_state_observation: PilotExactTaskStagingDeploymentStatusStateObservationReceipt,
    authorization_payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
) -> PilotExactTaskStagingDeploymentStatusAuthorizationReceipt:
    """Reserve one exact first staging Deployment Status; perform no GitHub mutation."""
    config, verifier, ledger = _canonical_runtime()
    credential, credential_digest, credential_path = (
        publication_tx_boundary._canonical_credential()
    )
    transport = state_boundary._GitHubStagingDeploymentStatusStateObserver(
        credential=credential,
        credential_config_sha256=credential_digest,
        credential_path=credential_path,
    )
    return _authorize_verified_pilot_exact_task_staging_deployment_status(
        deployment_status_state_observation=deployment_status_state_observation,
        deployment_status_config=config,
        authorization_payload=authorization_payload,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
        verifier=verifier,
        ledger=ledger,
        transport=transport,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
