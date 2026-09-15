"""ADR-DC-066 dual-authorized one-shot exact release authorization.

This boundary accepts only one fresh live ADR-DC-065 release-state observation
whose remote release lane is exactly clear. One host-admin-pinned release
authorization config plus two independent detached Ed25519 signatures authorize
only the deterministic lightweight tag and draft/prerelease GitHub Release
already frozen by ADR-DC-064.

The execution nonce is durably consumed before authority is published. This
boundary performs no GitHub mutation. Deployment and production activation
remain forbidden.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
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
from . import improvement_pilot_exact_task_release_state_observation as state_boundary
from . import improvement_pilot_exact_task_remote_publication_transaction as publication_tx_boundary
from .improvement_pilot_exact_task_release_state_observation import (
    PILOT_EXACT_TASK_RELEASE_STATE_OBSERVATION_AUTHORITY,
    PilotExactTaskReleaseStateObservationReceipt,
)

PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-release-authorization-receipt/v1"
)
PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_AUTHORITY = (
    "dual-authorized-one-dc-l16-exact-draft-release-only"
)
PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_SCOPE = (
    "one-shot-exact-tag-and-draft-release-only-v1"
)
PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_CONFIG_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-release-authorization-config/v1"
)
PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_KEYRING_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-release-authorization-keyring/v1"
)
PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_CLAIM_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-release-authorization-claim/v1"
)
PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_LEDGER_SCOPE = "canonical-host-local-v1"

_MAX_FILE_BYTES = 1024 * 1024
_MAX_AUTH_SECONDS = 10 * 60
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-release-authorization-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-release-authorization-ledger-v1"
)
_POSIX_CONFIG = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-pilot-exact-task-release-authorization-config-v1.json"
)
_WINDOWS_CONFIG = (
    Path(r"C:\Program Files\ModelRig\DevControl\authority")
    / "rsi-pilot-exact-task-release-authorization-config-v1.json"
)
_POSIX_KEYRING = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-pilot-exact-task-release-authorization-keyring-v1.json"
)
_WINDOWS_KEYRING = (
    Path(r"C:\Program Files\ModelRig\DevControl\authority")
    / "rsi-pilot-exact-task-release-authorization-keyring-v1.json"
)


class PilotExactTaskReleaseAuthorizationError(ValueError):
    """Exact release authorization is stale, replayed, unsigned or over-broad."""


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
        raise PilotExactTaskReleaseAuthorizationError(
            "release authorization evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskReleaseAuthorizationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskReleaseAuthorizationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskReleaseAuthorizationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskReleaseAuthorizationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _branch(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or value.strip() != value
        or _BRANCH.fullmatch(value) is None
        or value.endswith(("/", ".", ".lock"))
        or "@{" in value
        or "\\" in value
    ):
        raise PilotExactTaskReleaseAuthorizationError(f"{name} is invalid")
    return value


def _tag(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or value.strip() != value
        or _TAG.fullmatch(value) is None
        or value.endswith(("/", ".", ".lock"))
        or ".." in value
        or "@{" in value
        or "\\" in value
    ):
        raise PilotExactTaskReleaseAuthorizationError(f"{name} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class PilotExactTaskReleaseAuthorizationConfig:
    repository: str
    repository_id: str
    release_base_branch: str = "main"
    required_remote_state_class: str = "clear"
    release_draft: bool = True
    release_prerelease: bool = True
    make_latest: bool = False
    schema: str = PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_CONFIG_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_CONFIG_SCHEMA:
            raise PilotExactTaskReleaseAuthorizationError(
                "release authorization config schema is unsupported"
            )
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskReleaseAuthorizationError(
                "release authorization repository identity is invalid"
            )
        _branch(self.release_base_branch, name="release_base_branch")
        if (
            self.required_remote_state_class != "clear"
            or self.release_draft is not True
            or self.release_prerelease is not True
            or self.make_latest is not False
        ):
            raise PilotExactTaskReleaseAuthorizationError(
                "release authorization config weakens fixed conservative scope"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "repository_id": self.repository_id,
            "release_base_branch": self.release_base_branch,
            "required_remote_state_class": self.required_remote_state_class,
            "release_draft": self.release_draft,
            "release_prerelease": self.release_prerelease,
            "make_latest": self.make_latest,
            "schema": self.schema,
        }

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskReleaseAuthorizationConfig":
        expected = {
            "repository",
            "repository_id",
            "release_base_branch",
            "required_remote_state_class",
            "release_draft",
            "release_prerelease",
            "make_latest",
            "schema",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise PilotExactTaskReleaseAuthorizationError(
                "release authorization config fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _parse_config(payload: bytes) -> PilotExactTaskReleaseAuthorizationConfig:
    if (
        not isinstance(payload, bytes)
        or not payload
        or len(payload) > _MAX_FILE_BYTES
    ):
        raise PilotExactTaskReleaseAuthorizationError(
            "release authorization config payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskReleaseAuthorizationError(
            "release authorization config JSON is invalid"
        ) from exc
    config = PilotExactTaskReleaseAuthorizationConfig.from_mapping(raw)
    if config.canonical_json().encode("utf-8") != payload:
        raise PilotExactTaskReleaseAuthorizationError(
            "release authorization config is not canonical JSON"
        )
    return config


def _parse_keyring(payload: bytes) -> tuple[Ed25519AuthorityVerifier, str]:
    if (
        not isinstance(payload, bytes)
        or not payload
        or len(payload) > _MAX_FILE_BYTES
    ):
        raise PilotExactTaskReleaseAuthorizationError(
            "release authorization keyring payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskReleaseAuthorizationError(
            "release authorization keyring JSON is invalid"
        ) from exc
    if (
        not isinstance(raw, dict)
        or set(raw) != {"schema", "minimum_keyring_epoch", "keys"}
        or raw.get("schema") != PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_KEYRING_SCHEMA
    ):
        raise PilotExactTaskReleaseAuthorizationError(
            "release authorization keyring fields/schema mismatch"
        )
    epoch = raw["minimum_keyring_epoch"]
    keys_raw = raw["keys"]
    if (
        isinstance(epoch, bool)
        or not isinstance(epoch, int)
        or epoch < 1
        or not isinstance(keys_raw, list)
        or not 2 <= len(keys_raw) <= 64
    ):
        raise PilotExactTaskReleaseAuthorizationError(
            "release authorization keyring content is invalid"
        )
    keys: dict[str, TrustedEd25519AuthorityKey] = {}
    for item in keys_raw:
        try:
            key = TrustedEd25519AuthorityKey.from_mapping(item)
        except Exception as exc:
            raise PilotExactTaskReleaseAuthorizationError(
                "release trusted key is invalid"
            ) from exc
        if key.key_id in keys:
            raise PilotExactTaskReleaseAuthorizationError(
                "release key IDs are duplicated"
            )
        keys[key.key_id] = key
    if list(keys) != sorted(keys):
        raise PilotExactTaskReleaseAuthorizationError(
            "release keyring keys must be sorted by key_id"
        )
    canonical = _canonical(
        {
            "schema": PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_KEYRING_SCHEMA,
            "minimum_keyring_epoch": epoch,
            "keys": [keys[key_id].to_dict() for key_id in sorted(keys)],
        }
    ).encode("utf-8")
    if canonical != payload:
        raise PilotExactTaskReleaseAuthorizationError(
            "release authorization keyring is not canonical JSON"
        )
    return (
        Ed25519AuthorityVerifier(keys, minimum_keyring_epoch=epoch),
        hashlib.sha256(payload).hexdigest(),
    )


def _read_host_authority_file(path: Path) -> bytes:
    try:
        payload = lifecycle_auth_boundary._read_host_authority_file(Path(path))
    except Exception as exc:
        raise PilotExactTaskReleaseAuthorizationError(
            "release authority file is not host-admin controlled"
        ) from exc
    if not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskReleaseAuthorizationError(
            "release authority file is invalid"
        )
    return payload


def _require_live_clear_state(
    value: Any,
) -> PilotExactTaskReleaseStateObservationReceipt:
    if type(value) is not PilotExactTaskReleaseStateObservationReceipt:
        raise PilotExactTaskReleaseAuthorizationError(
            "exact live ADR-DC-065 release-state observation is required"
        )
    try:
        replayed = PilotExactTaskReleaseStateObservationReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskReleaseAuthorizationError(
            "ADR-DC-065 observation replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskReleaseAuthorizationError(
            "ADR-DC-065 observation identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_RELEASE_STATE_OBSERVATION_AUTHORITY
        or value.observation_authenticated is not True
        or value.release_plan_authenticated is not True
        or value.remote_state_observed is not True
        or value.remote_repository_verified is not True
        or value.tag_state_verified is not True
        or value.release_state_verified is not True
        or value.double_observation_matched is not True
        or value.release_state_acceptable is not True
        or value.remote_state_class != "clear"
        or value.tag_state != "absent"
        or value.release_state != "absent"
        or value.release_id is not None
        or value.release_node_id_sha256 is not None
        or value.release_lane_clear is not True
        or value.exact_existing_release is not False
        or value.tag_write_authorized is not False
        or value.release_mutation_authorized is not False
        or value.release_authorized is not False
        or value.remote_write_authorized is not False
        or value.merge_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskReleaseAuthorizationError(
            "ADR-DC-066 requires one fresh clear ADR-DC-065 release lane"
        )
    live = state_boundary._get_live_release_state_observation_inputs(value)
    if (
        live is None
        or live.get("remote_release_state_sha256")
        != value.remote_release_state_sha256
    ):
        raise PilotExactTaskReleaseAuthorizationError(
            "ADR-DC-065 live provenance is unavailable"
        )
    plan = live.get("release_plan")
    if (
        plan is None
        or getattr(plan, "sha256", None) != value.release_plan_sha256
        or getattr(plan, "plan_authenticated", False) is not True
    ):
        raise PilotExactTaskReleaseAuthorizationError(
            "ADR-DC-064 live plan provenance is unavailable"
        )
    return value


def _validate_config_for_observation(
    config: PilotExactTaskReleaseAuthorizationConfig,
    observation: PilotExactTaskReleaseStateObservationReceipt,
) -> None:
    if (
        config.repository != observation.repository
        or config.repository_id != observation.repository_id
        or config.release_base_branch != observation.release_base_branch
        or config.required_remote_state_class != observation.remote_state_class
        or config.release_draft != observation.release_draft
        or config.release_prerelease != observation.release_prerelease
        or config.make_latest != observation.make_latest
    ):
        raise PilotExactTaskReleaseAuthorizationError(
            "host release authorization config does not match exact ADR-DC-065 target"
        )


def _fresh_revalidate_clear_lane(
    observation: PilotExactTaskReleaseStateObservationReceipt,
    transport: Any,
) -> str:
    """Re-observe the exact ADR-DC-064 release lane twice and require it unchanged."""
    observation = _require_live_clear_state(observation)
    live = state_boundary._get_live_release_state_observation_inputs(observation)
    plan = None if live is None else live.get("release_plan")
    if plan is None or getattr(plan, "plan_authenticated", False) is not True:
        raise PilotExactTaskReleaseAuthorizationError(
            "release plan live provenance vanished during authorization"
        )
    if transport is None or not callable(getattr(transport, "observe", None)):
        raise PilotExactTaskReleaseAuthorizationError(
            "fresh read-only release-state observer is required"
        )
    if (
        getattr(transport, "credential_config_sha256", None)
        != observation.publisher_credential_config_sha256
        or getattr(transport, "credential_path_sha256", None)
        != observation.publisher_credential_path_sha256
    ):
        raise PilotExactTaskReleaseAuthorizationError(
            "fresh release observer credential identity differs from ADR-DC-065"
        )
    try:
        first = state_boundary._normalize_remote_state(transport.observe(plan), plan)
        second = state_boundary._normalize_remote_state(transport.observe(plan), plan)
    except PilotExactTaskReleaseAuthorizationError:
        raise
    except Exception as exc:
        raise PilotExactTaskReleaseAuthorizationError(
            "fresh release-state revalidation failed"
        ) from exc
    if first != second:
        raise PilotExactTaskReleaseAuthorizationError(
            "remote release state changed during fresh authorization revalidation"
        )
    if (
        first.remote_state_class != "clear"
        or first.tag_state != "absent"
        or first.release_state != "absent"
        or first.sha256 != observation.remote_release_state_sha256
    ):
        raise PilotExactTaskReleaseAuthorizationError(
            "remote release lane is no longer the exact clear ADR-DC-065 state"
        )
    return first.sha256


def _build_authorization_payload(
    *,
    release_state_observation: PilotExactTaskReleaseStateObservationReceipt,
    release_config: PilotExactTaskReleaseAuthorizationConfig,
    requested_at_utc: str,
    expires_at_utc: str,
    operator_actor_id: str,
    operator_system_id: str,
    operator_key_id: str,
    reviewer_actor_id: str,
    reviewer_system_id: str,
    reviewer_key_id: str,
) -> bytes:
    observation = _require_live_clear_state(release_state_observation)
    _validate_config_for_observation(release_config, observation)
    requested = _utc(requested_at_utc, name="requested_at_utc")
    expires = _utc(expires_at_utc, name="expires_at_utc")
    if (
        not requested < expires
        or (expires - requested).total_seconds() > _MAX_AUTH_SECONDS
    ):
        raise PilotExactTaskReleaseAuthorizationError(
            "release authorization validity window is invalid"
        )
    identities = (
        ("operator_actor_id", operator_actor_id),
        ("operator_system_id", operator_system_id),
        ("operator_key_id", operator_key_id),
        ("reviewer_actor_id", reviewer_actor_id),
        ("reviewer_system_id", reviewer_system_id),
        ("reviewer_key_id", reviewer_key_id),
    )
    for name, identity in identities:
        pattern = _ACTOR if name.endswith("actor_id") else _IDENTIFIER
        if not isinstance(identity, str) or pattern.fullmatch(identity) is None:
            raise PilotExactTaskReleaseAuthorizationError(f"{name} is invalid")
    if (
        operator_actor_id == reviewer_actor_id
        or operator_system_id == reviewer_system_id
        or operator_key_id == reviewer_key_id
    ):
        raise PilotExactTaskReleaseAuthorizationError(
            "release authorization requires independent operator and reviewer identities"
        )
    return _canonical(
        {
            "schema": PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_CLAIM_SCHEMA,
            "release_state_observation_sha256": observation.sha256,
            "release_plan_sha256": observation.release_plan_sha256,
            "release_readiness_evaluation_sha256": (
                observation.release_readiness_evaluation_sha256
            ),
            "release_intent_sha256": observation.release_intent_sha256,
            "release_plan_config_sha256": observation.release_plan_config_sha256,
            "remote_release_state_sha256": observation.remote_release_state_sha256,
            "release_authorization_config_sha256": release_config.sha256,
            "execution_nonce_sha256": observation.execution_nonce_sha256,
            "development_task_sha256": observation.development_task_sha256,
            "candidate_patch_sha256": observation.candidate_patch_sha256,
            "pr_intent_sha256": observation.pr_intent_sha256,
            "transaction_lock_sha256": observation.transaction_lock_sha256,
            "publisher_credential_config_sha256": (
                observation.publisher_credential_config_sha256
            ),
            "publisher_credential_path_sha256": (
                observation.publisher_credential_path_sha256
            ),
            "repository": observation.repository,
            "repository_id": observation.repository_id,
            "release_base_branch": observation.release_base_branch,
            "merge_commit_sha": observation.merge_commit_sha,
            "release_version": observation.release_version,
            "tag_name": observation.tag_name,
            "tag_target_sha": observation.tag_target_sha,
            "release_name": observation.release_name,
            "release_body_sha256": observation.release_body_sha256,
            "release_draft": True,
            "release_prerelease": True,
            "make_latest": False,
            "remote_state_class": "clear",
            "requested_at_utc": requested_at_utc,
            "expires_at_utc": expires_at_utc,
            "operator_actor_id": operator_actor_id,
            "operator_system_id": operator_system_id,
            "operator_key_id": operator_key_id,
            "reviewer_actor_id": reviewer_actor_id,
            "reviewer_system_id": reviewer_system_id,
            "reviewer_key_id": reviewer_key_id,
        }
    ).encode("utf-8")


def _parse_claim(payload: bytes) -> dict[str, Any]:
    if (
        not isinstance(payload, bytes)
        or not payload
        or len(payload) > _MAX_FILE_BYTES
    ):
        raise PilotExactTaskReleaseAuthorizationError(
            "release authorization payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskReleaseAuthorizationError(
            "release authorization payload JSON is invalid"
        ) from exc
    expected = {
        "schema",
        "release_state_observation_sha256",
        "release_plan_sha256",
        "release_readiness_evaluation_sha256",
        "release_intent_sha256",
        "release_plan_config_sha256",
        "remote_release_state_sha256",
        "release_authorization_config_sha256",
        "execution_nonce_sha256",
        "development_task_sha256",
        "candidate_patch_sha256",
        "pr_intent_sha256",
        "transaction_lock_sha256",
        "publisher_credential_config_sha256",
        "publisher_credential_path_sha256",
        "repository",
        "repository_id",
        "release_base_branch",
        "merge_commit_sha",
        "release_version",
        "tag_name",
        "tag_target_sha",
        "release_name",
        "release_body_sha256",
        "release_draft",
        "release_prerelease",
        "make_latest",
        "remote_state_class",
        "requested_at_utc",
        "expires_at_utc",
        "operator_actor_id",
        "operator_system_id",
        "operator_key_id",
        "reviewer_actor_id",
        "reviewer_system_id",
        "reviewer_key_id",
    }
    if (
        not isinstance(raw, dict)
        or set(raw) != expected
        or raw.get("schema") != PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_CLAIM_SCHEMA
        or _canonical(raw).encode("utf-8") != payload
    ):
        raise PilotExactTaskReleaseAuthorizationError(
            "release authorization payload fields/canonical form mismatch"
        )
    return raw


def _verify_claim_and_signatures(
    *,
    observation: PilotExactTaskReleaseStateObservationReceipt,
    config: PilotExactTaskReleaseAuthorizationConfig,
    payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_utc: str,
) -> dict[str, Any]:
    claim = _parse_claim(payload)
    expected_payload = _build_authorization_payload(
        release_state_observation=observation,
        release_config=config,
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
        raise PilotExactTaskReleaseAuthorizationError(
            "release authorization payload is not bound to exact observation/config"
        )
    now = _utc(now_utc, name="reserved_at_utc")
    requested = _utc(claim["requested_at_utc"], name="requested_at_utc")
    expires = _utc(claim["expires_at_utc"], name="expires_at_utc")
    if not requested <= now < expires:
        raise PilotExactTaskReleaseAuthorizationError(
            "release authorization is not currently valid"
        )
    if (
        type(operator_signature) is not DetachedEd25519AuthoritySignature
        or type(reviewer_signature) is not DetachedEd25519AuthoritySignature
    ):
        raise PilotExactTaskReleaseAuthorizationError(
            "two detached Ed25519 release signatures are required"
        )
    if (
        operator_signature.key_id == reviewer_signature.key_id
        or operator_signature.issuer_actor_id == reviewer_signature.issuer_actor_id
        or operator_signature.issuer_system_id == reviewer_signature.issuer_system_id
    ):
        raise PilotExactTaskReleaseAuthorizationError(
            "release signatures must be independent"
        )
    payload_sha = hashlib.sha256(payload).hexdigest()
    bindings = (
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
    )
    for signature, actor_id, system_id, key_id in bindings:
        if (
            signature.payload_sha256 != payload_sha
            or signature.issuer_actor_id != actor_id
            or signature.issuer_system_id != system_id
            or signature.key_id != key_id
        ):
            raise PilotExactTaskReleaseAuthorizationError(
                "release signature binding mismatch"
            )
        signed = _utc(signature.signed_at_utc, name="signed_at_utc")
        if not requested <= signed < expires or signed > now:
            raise PilotExactTaskReleaseAuthorizationError(
                "release signature timestamp is outside authorization window"
            )
        try:
            verifier.verify(payload=payload, signature=signature, at_utc=now_utc)
        except AsymmetricAuthorityError as exc:
            raise PilotExactTaskReleaseAuthorizationError(
                "release Ed25519 verification failed"
            ) from exc
    return claim


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskReleaseAuthorizationReceipt:
    release_ledger_root_path_sha256: str
    release_key_sha256: str
    release_authorization_payload_sha256: str
    release_state_observation_sha256: str
    release_plan_sha256: str
    release_readiness_evaluation_sha256: str
    release_intent_sha256: str
    release_plan_config_sha256: str
    remote_release_state_sha256: str
    release_authorization_config_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    transaction_lock_sha256: str
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    repository: str
    repository_id: str
    release_base_branch: str
    merge_commit_sha: str
    release_version: str
    tag_name: str
    tag_target_sha: str
    release_name: str
    release_body_sha256: str
    release_draft: bool
    release_prerelease: bool
    make_latest: bool
    operator_actor_id: str
    operator_system_id: str
    operator_key_id: str
    reviewer_actor_id: str
    reviewer_system_id: str
    reviewer_key_id: str
    requested_at_utc: str
    expires_at_utc: str
    reserved_at_utc: str
    host_release_guard_committed: bool = True
    release_state_observation_authenticated: bool = True
    release_plan_authenticated: bool = True
    release_lane_clear: bool = True
    release_authorization_config_host_pinned: bool = True
    dual_external_ed25519_authorized: bool = True
    tag_write_authorized: bool = True
    release_mutation_authorized: bool = True
    release_authorized: bool = True
    remote_write_authorized: bool = True
    merge_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    ready_for_review_authorized: bool = False
    reviewer_request_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    product_pilot_started: bool = False
    nonce_reusable: bool = False
    authorization_scope: str = PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_SCOPE
    authority: str = PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_SCHEMA
            or self.authority != PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_AUTHORITY
            or self.authorization_scope
            != PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_SCOPE
        ):
            raise PilotExactTaskReleaseAuthorizationError(
                "release authorization receipt identity is unsupported"
            )
        for name in (
            "release_ledger_root_path_sha256",
            "release_key_sha256",
            "release_authorization_payload_sha256",
            "release_state_observation_sha256",
            "release_plan_sha256",
            "release_readiness_evaluation_sha256",
            "release_intent_sha256",
            "release_plan_config_sha256",
            "remote_release_state_sha256",
            "release_authorization_config_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
            "transaction_lock_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "release_body_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("merge_commit_sha", "tag_target_sha"):
            _hex40(getattr(self, name), name=name)
        if self.release_key_sha256 != self.execution_nonce_sha256:
            raise PilotExactTaskReleaseAuthorizationError(
                "release replay key must equal execution nonce"
            )
        if self.tag_target_sha != self.merge_commit_sha:
            raise PilotExactTaskReleaseAuthorizationError(
                "release tag target differs from exact merge commit"
            )
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskReleaseAuthorizationError(
                "release authorization repository identity is invalid"
            )
        _branch(self.release_base_branch, name="release_base_branch")
        _tag(self.tag_name, name="tag_name")
        if (
            not isinstance(self.release_version, str)
            or not self.release_version
            or not isinstance(self.release_name, str)
            or not self.release_name
            or self.release_draft is not True
            or self.release_prerelease is not True
            or self.make_latest is not False
        ):
            raise PilotExactTaskReleaseAuthorizationError(
                "release authorization intent projection is invalid"
            )
        for name in ("operator_actor_id", "reviewer_actor_id"):
            identity = getattr(self, name)
            if not isinstance(identity, str) or _ACTOR.fullmatch(identity) is None:
                raise PilotExactTaskReleaseAuthorizationError(f"{name} is invalid")
        for name in (
            "operator_system_id",
            "operator_key_id",
            "reviewer_system_id",
            "reviewer_key_id",
        ):
            identity = getattr(self, name)
            if (
                not isinstance(identity, str)
                or _IDENTIFIER.fullmatch(identity) is None
            ):
                raise PilotExactTaskReleaseAuthorizationError(f"{name} is invalid")
        if (
            self.operator_actor_id == self.reviewer_actor_id
            or self.operator_system_id == self.reviewer_system_id
            or self.operator_key_id == self.reviewer_key_id
        ):
            raise PilotExactTaskReleaseAuthorizationError(
                "release receipt signers are not independent"
            )
        requested = _utc(self.requested_at_utc, name="requested_at_utc")
        expires = _utc(self.expires_at_utc, name="expires_at_utc")
        reserved = _utc(self.reserved_at_utc, name="reserved_at_utc")
        if (
            not requested <= reserved < expires
            or (expires - requested).total_seconds() > _MAX_AUTH_SECONDS
        ):
            raise PilotExactTaskReleaseAuthorizationError(
                "release authorization timestamps are invalid"
            )
        required_true = (
            "host_release_guard_committed",
            "release_state_observation_authenticated",
            "release_plan_authenticated",
            "release_lane_clear",
            "release_authorization_config_host_pinned",
            "dual_external_ed25519_authorized",
            "tag_write_authorized",
            "release_mutation_authorized",
            "release_authorized",
            "remote_write_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskReleaseAuthorizationError(
                "release authorization evidence/authority is incomplete"
            )
        forced_false = (
            "merge_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "ready_for_review_authorized",
            "reviewer_request_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "product_pilot_started",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskReleaseAuthorizationError(
                "release authorization grants forbidden additional authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def authorization_authenticated(self) -> bool:
        return _get_live_release_authorization_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskReleaseAuthorizationReceipt":
        if (
            not isinstance(value, Mapping)
            or set(value) != set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        ):
            raise PilotExactTaskReleaseAuthorizationError(
                "release authorization receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskReleaseAuthorizationLedger:
    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path]:
        digest = _hex64(key, name="release_key_sha256")
        return self.root / f"{digest}.json", self.root / f".{digest}.lock"

    def acquire(
        self,
        *,
        observation: PilotExactTaskReleaseStateObservationReceipt,
        payload: bytes,
        config_sha256: str,
        operator_signature: DetachedEd25519AuthoritySignature,
        reviewer_signature: DetachedEd25519AuthoritySignature,
    ) -> bytes:
        key = observation.execution_nonce_sha256
        final, lock = self._paths(key)
        if (
            final.exists()
            or final.is_symlink()
            or lock.exists()
            or lock.is_symlink()
        ):
            raise PilotExactTaskReleaseAuthorizationError(
                "release nonce already consumed or needs recovery"
            )
        lock_payload = _canonical(
            {
                "schema": (
                    "kaliv-rsi-dc-l16-exact-task-"
                    "release-authorization-lock/v1"
                ),
                "ledger_scope": PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "release_key_sha256": key,
                "release_state_observation_sha256": observation.sha256,
                "release_plan_sha256": observation.release_plan_sha256,
                "release_intent_sha256": observation.release_intent_sha256,
                "remote_release_state_sha256": observation.remote_release_state_sha256,
                "release_authorization_payload_sha256": hashlib.sha256(
                    payload
                ).hexdigest(),
                "release_authorization_config_sha256": config_sha256,
                "repository": observation.repository,
                "repository_id": observation.repository_id,
                "release_base_branch": observation.release_base_branch,
                "merge_commit_sha": observation.merge_commit_sha,
                "tag_name": observation.tag_name,
                "tag_target_sha": observation.tag_target_sha,
                "release_name": observation.release_name,
                "release_body_sha256": observation.release_body_sha256,
                "release_draft": True,
                "release_prerelease": True,
                "make_latest": False,
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
            raise PilotExactTaskReleaseAuthorizationError(
                "release authorization could not be durably consumed"
            ) from exc
        return lock_payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskReleaseAuthorizationReceipt,
        lock_payload: bytes,
        observation: PilotExactTaskReleaseStateObservationReceipt,
        config: PilotExactTaskReleaseAuthorizationConfig,
    ) -> PilotExactTaskReleaseAuthorizationReceipt:
        final, lock = self._paths(receipt.release_key_sha256)
        try:
            observed_lock = lock.read_bytes()
        except OSError as exc:
            raise PilotExactTaskReleaseAuthorizationError(
                "release authorization lock is unavailable"
            ) from exc
        if (
            final.exists()
            or final.is_symlink()
            or observed_lock != lock_payload
        ):
            raise PilotExactTaskReleaseAuthorizationError(
                "release authorization durable state changed before finalization"
            )
        final_payload = receipt.canonical_json().encode("utf-8")
        try:
            create_once_file(final, final_payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskReleaseAuthorizationError(
                "release authorization receipt could not be durably published"
            ) from exc
        parsed = PilotExactTaskReleaseAuthorizationReceipt.from_mapping(
            json.loads(final_payload.decode("utf-8"))
        )
        _mark_release_authorization_authenticated(
            parsed,
            observation=observation,
            config=config,
            final_path=final,
            final_payload=final_payload,
            lock_path=lock,
            lock_payload=lock_payload,
        )
        if parsed.authorization_authenticated is not True:
            raise PilotExactTaskReleaseAuthorizationError(
                "release authorization lost live provenance"
            )
        return parsed


def _read_bound(path: Path) -> bytes | None:
    try:
        payload = Path(path).read_bytes()
    except OSError:
        return None
    if not payload or len(payload) > _MAX_FILE_BYTES:
        return None
    return payload


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: PilotExactTaskReleaseAuthorizationReceipt,
        *,
        observation: PilotExactTaskReleaseStateObservationReceipt,
        config: PilotExactTaskReleaseAuthorizationConfig,
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
            config,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
        ) = entry
        observation = observation_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or observation is None
            or receipt.sha256 != digest
            or observation.observation_authenticated is not True
            or observation.sha256 != receipt.release_state_observation_sha256
            or observation.remote_state_class != "clear"
            or observation.release_lane_clear is not True
            or config.sha256 != receipt.release_authorization_config_sha256
            or _read_bound(final_path) != final_payload
            or _read_bound(lock_path) != lock_payload
        ):
            return None
        return MappingProxyType(
            {
                "release_state_observation": observation,
                "release_authorization_config": config,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_release_authorization_authenticated,
    _get_live_release_authorization_inputs,
) = _live_registry()


def _authorize_verified_pilot_exact_task_release(
    *,
    release_state_observation: PilotExactTaskReleaseStateObservationReceipt,
    release_config: PilotExactTaskReleaseAuthorizationConfig,
    authorization_payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    ledger: _PilotExactTaskReleaseAuthorizationLedger,
    transport: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskReleaseAuthorizationReceipt:
    observation = _require_live_clear_state(release_state_observation)
    if type(release_config) is not PilotExactTaskReleaseAuthorizationConfig:
        raise PilotExactTaskReleaseAuthorizationError(
            "exact release authorization config is required"
        )
    _validate_config_for_observation(release_config, observation)
    _fresh_revalidate_clear_lane(observation, transport)
    reserved_at = now_provider()
    claim = _verify_claim_and_signatures(
        observation=observation,
        config=release_config,
        payload=authorization_payload,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
        verifier=verifier,
        now_utc=reserved_at,
    )
    lock_payload = ledger.acquire(
        observation=observation,
        payload=authorization_payload,
        config_sha256=release_config.sha256,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
    )
    if _require_live_clear_state(observation) is not observation:
        raise PilotExactTaskReleaseAuthorizationError(
            "ADR-DC-065 live observation changed after release consumption"
        )
    _fresh_revalidate_clear_lane(observation, transport)
    receipt = PilotExactTaskReleaseAuthorizationReceipt(
        release_ledger_root_path_sha256=ledger.root_sha256,
        release_key_sha256=observation.execution_nonce_sha256,
        release_authorization_payload_sha256=hashlib.sha256(
            authorization_payload
        ).hexdigest(),
        release_state_observation_sha256=observation.sha256,
        release_plan_sha256=observation.release_plan_sha256,
        release_readiness_evaluation_sha256=(
            observation.release_readiness_evaluation_sha256
        ),
        release_intent_sha256=observation.release_intent_sha256,
        release_plan_config_sha256=observation.release_plan_config_sha256,
        remote_release_state_sha256=observation.remote_release_state_sha256,
        release_authorization_config_sha256=release_config.sha256,
        execution_nonce_sha256=observation.execution_nonce_sha256,
        development_task_sha256=observation.development_task_sha256,
        candidate_patch_sha256=observation.candidate_patch_sha256,
        pr_intent_sha256=observation.pr_intent_sha256,
        transaction_lock_sha256=observation.transaction_lock_sha256,
        publisher_credential_config_sha256=(
            observation.publisher_credential_config_sha256
        ),
        publisher_credential_path_sha256=(
            observation.publisher_credential_path_sha256
        ),
        repository=observation.repository,
        repository_id=observation.repository_id,
        release_base_branch=observation.release_base_branch,
        merge_commit_sha=observation.merge_commit_sha,
        release_version=observation.release_version,
        tag_name=observation.tag_name,
        tag_target_sha=observation.tag_target_sha,
        release_name=observation.release_name,
        release_body_sha256=observation.release_body_sha256,
        release_draft=True,
        release_prerelease=True,
        make_latest=False,
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
        config=release_config,
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
        raise PilotExactTaskReleaseAuthorizationError(
            "release authorization platform is unsupported"
        )
    except PhysicalHostStateError as exc:
        raise PilotExactTaskReleaseAuthorizationError(
            "release authorization ledger is not host-admin controlled"
        ) from exc


def _canonical_config() -> PilotExactTaskReleaseAuthorizationConfig:
    config_path, _keyring_path, _ledger_root = _canonical_paths()
    first = _read_host_authority_file(config_path)
    second = _read_host_authority_file(config_path)
    if first != second:
        raise PilotExactTaskReleaseAuthorizationError(
            "release authorization config changed while being read"
        )
    return _parse_config(second)


def _canonical_runtime():
    config_path, keyring_path, ledger_root = _canonical_paths()
    first_config = _read_host_authority_file(config_path)
    second_config = _read_host_authority_file(config_path)
    if first_config != second_config:
        raise PilotExactTaskReleaseAuthorizationError(
            "release authorization config changed while being read"
        )
    first_keyring = _read_host_authority_file(keyring_path)
    second_keyring = _read_host_authority_file(keyring_path)
    if first_keyring != second_keyring:
        raise PilotExactTaskReleaseAuthorizationError(
            "release authorization keyring changed while being read"
        )
    config = _parse_config(second_config)
    verifier, _keyring_sha = _parse_keyring(second_keyring)
    return (
        config,
        verifier,
        _PilotExactTaskReleaseAuthorizationLedger(ledger_root),
    )


def build_pilot_exact_task_release_authorization_payload(
    release_state_observation: PilotExactTaskReleaseStateObservationReceipt,
    requested_at_utc: str,
    expires_at_utc: str,
    operator_actor_id: str,
    operator_system_id: str,
    operator_key_id: str,
    reviewer_actor_id: str,
    reviewer_system_id: str,
    reviewer_key_id: str,
) -> bytes:
    """Build exact bytes for two independent external release-authority signers."""
    return _build_authorization_payload(
        release_state_observation=release_state_observation,
        release_config=_canonical_config(),
        requested_at_utc=requested_at_utc,
        expires_at_utc=expires_at_utc,
        operator_actor_id=operator_actor_id,
        operator_system_id=operator_system_id,
        operator_key_id=operator_key_id,
        reviewer_actor_id=reviewer_actor_id,
        reviewer_system_id=reviewer_system_id,
        reviewer_key_id=reviewer_key_id,
    )


def authorize_pilot_exact_task_release(
    release_state_observation: PilotExactTaskReleaseStateObservationReceipt,
    authorization_payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
) -> PilotExactTaskReleaseAuthorizationReceipt:
    """Reserve one exact release slot; perform no tag or GitHub Release mutation."""
    config, verifier, ledger = _canonical_runtime()
    credential, credential_digest, credential_path = (
        publication_tx_boundary._canonical_credential()
    )
    transport = state_boundary._GitHubReleaseStateObserver(
        credential=credential,
        credential_config_sha256=credential_digest,
        credential_path=credential_path,
    )
    return _authorize_verified_pilot_exact_task_release(
        release_state_observation=release_state_observation,
        release_config=config,
        authorization_payload=authorization_payload,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
        verifier=verifier,
        ledger=ledger,
        transport=transport,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
