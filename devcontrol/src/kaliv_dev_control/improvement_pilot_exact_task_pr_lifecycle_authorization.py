"""ADR-DC-053 exact one-shot PR lifecycle authorization.

This boundary consumes one fresh live ADR-DC-052 post-publication attestation and
an externally signed, host-pinned lifecycle policy. It reserves exactly one
lifecycle slot for the already-created deterministic draft pull request.

It performs no GitHub mutation itself. The only authority it may issue is to
mark that exact draft PR ready for review and request the exact host-pinned
reviewer set. Push, merge, release, deployment and production activation remain
forbidden.
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
    asymmetric_authority_key_custody_policy_sha256,
)
from .durable_publication import DurablePublicationError, create_once_file
from .improvement_physical_authority_keyring import (
    PhysicalRequestAuthorityKeyringError,
    _read_keyring_bytes,
)
from . import improvement_pilot_exact_task_post_publication_attestation as attestation_boundary
from .improvement_pilot_exact_task_post_publication_attestation import (
    PILOT_EXACT_TASK_POST_PUBLICATION_ATTESTATION_AUTHORITY,
    PilotExactTaskPostPublicationAttestationReceipt,
)

PILOT_EXACT_TASK_PR_LIFECYCLE_AUTHORIZATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-lifecycle-authorization-receipt/v1"
)
PILOT_EXACT_TASK_PR_LIFECYCLE_AUTHORIZATION_AUTHORITY = (
    "externally-authorized-one-dc-l16-exact-pr-lifecycle-only"
)
PILOT_EXACT_TASK_PR_LIFECYCLE_AUTHORIZATION_SCOPE = (
    "ready-for-review-and-exact-reviewer-request-only-v1"
)
PILOT_EXACT_TASK_PR_LIFECYCLE_CONFIG_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-lifecycle-config/v1"
)
PILOT_EXACT_TASK_PR_LIFECYCLE_KEYRING_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-lifecycle-keyring/v1"
)
PILOT_EXACT_TASK_PR_LIFECYCLE_CLAIM_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-lifecycle-authorization-claim/v1"
)
PILOT_EXACT_TASK_PR_LIFECYCLE_LEDGER_SCOPE = "canonical-host-local-v1"
_POLICY_DOMAIN = b"kaliv-rsi-dc-l16-exact-task-pr-lifecycle-authorization-policy/v1\0"
_MAX_AUTH_SECONDS = 10 * 60
_MAX_FILE_BYTES = 1024 * 1024
_GITHUB_API_ROOT = "https://api.github.com"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_USERNAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$")
_TEAM = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-pr-lifecycle-authorization-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-pr-lifecycle-authorization-ledger-v1"
)
_POSIX_CONFIG = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-pilot-exact-task-pr-lifecycle-config-v1.json"
)
_WINDOWS_CONFIG = Path(
    r"C:\Program Files\ModelRig\DevControl\authority\rsi-pilot-exact-task-pr-lifecycle-config-v1.json"
)
_POSIX_KEYRING = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-pilot-exact-task-pr-lifecycle-keyring-v1.json"
)
_WINDOWS_KEYRING = Path(
    r"C:\Program Files\ModelRig\DevControl\authority\rsi-pilot-exact-task-pr-lifecycle-keyring-v1.json"
)

PILOT_EXACT_TASK_PR_LIFECYCLE_AUTHORIZATION_POLICY = (
    "Accept only one exact live ADR-DC-052 post-publication attestation.",
    "Resolve reviewer usernames and team slugs only from one host-admin-pinned canonical lifecycle config.",
    "Require one detached Ed25519 authorization over the exact attestation, PR identity, reviewer set and short validity window.",
    "Durably consume the exact execution nonce before issuing lifecycle authority.",
    "Authorize only ready-for-review transition plus exact reviewer requests for the already-attested draft PR.",
    "Never authorize push, merge, release, deployment or production activation.",
)


class PilotExactTaskPrLifecycleAuthorizationError(ValueError):
    """PR lifecycle authorization is stale, replayed, untrusted or over-broad."""


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
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "PR lifecycle evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrLifecycleAuthorizationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrLifecycleAuthorizationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrLifecycleAuthorizationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskPrLifecycleAuthorizationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _branch(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or value.strip() != value
        or _BRANCH.fullmatch(value) is None
        or value.endswith(("/", ".", ".lock"))
        or "@{" in value
        or "\\" in value
    ):
        raise PilotExactTaskPrLifecycleAuthorizationError(f"{name} is invalid")
    return value


def pilot_exact_task_pr_lifecycle_authorization_policy_sha256() -> str:
    payload = json.dumps(
        list(PILOT_EXACT_TASK_PR_LIFECYCLE_AUTHORIZATION_POLICY),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(_POLICY_DOMAIN + payload).hexdigest()


def _reviewer_set_sha256(usernames: tuple[str, ...], teams: tuple[str, ...]) -> str:
    return hashlib.sha256(
        _canonical(
            {
                "reviewer_usernames": list(usernames),
                "reviewer_team_slugs": list(teams),
            }
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class PilotExactTaskPrLifecycleConfig:
    repository: str
    repository_id: str
    reviewer_usernames: tuple[str, ...]
    reviewer_team_slugs: tuple[str, ...]
    ready_for_review: bool = True
    schema: str = PILOT_EXACT_TASK_PR_LIFECYCLE_CONFIG_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PR_LIFECYCLE_CONFIG_SCHEMA:
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "PR lifecycle config schema is unsupported"
            )
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PilotExactTaskPrLifecycleAuthorizationError("lifecycle repository is invalid")
        if not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None:
            raise PilotExactTaskPrLifecycleAuthorizationError("lifecycle repository_id is invalid")
        if self.ready_for_review is not True:
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "lifecycle config must require ready-for-review"
            )
        if not isinstance(self.reviewer_usernames, tuple) or not isinstance(
            self.reviewer_team_slugs, tuple
        ):
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "reviewer sets must be immutable tuples"
            )
        if len(self.reviewer_usernames) > 20 or len(self.reviewer_team_slugs) > 20:
            raise PilotExactTaskPrLifecycleAuthorizationError("reviewer set is oversized")
        if not self.reviewer_usernames and not self.reviewer_team_slugs:
            raise PilotExactTaskPrLifecycleAuthorizationError("reviewer set must be non-empty")
        if list(self.reviewer_usernames) != sorted(set(self.reviewer_usernames)):
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "reviewer usernames must be sorted and unique"
            )
        if list(self.reviewer_team_slugs) != sorted(set(self.reviewer_team_slugs)):
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "reviewer team slugs must be sorted and unique"
            )
        for value in self.reviewer_usernames:
            if not isinstance(value, str) or _USERNAME.fullmatch(value) is None:
                raise PilotExactTaskPrLifecycleAuthorizationError(
                    "reviewer username is invalid or not canonical lowercase"
                )
        for value in self.reviewer_team_slugs:
            if not isinstance(value, str) or _TEAM.fullmatch(value) is None:
                raise PilotExactTaskPrLifecycleAuthorizationError(
                    "reviewer team slug is invalid or not canonical lowercase"
                )

    @property
    def reviewer_set_sha256(self) -> str:
        return _reviewer_set_sha256(self.reviewer_usernames, self.reviewer_team_slugs)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "repository_id": self.repository_id,
            "reviewer_usernames": list(self.reviewer_usernames),
            "reviewer_team_slugs": list(self.reviewer_team_slugs),
            "ready_for_review": self.ready_for_review,
            "schema": self.schema,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrLifecycleConfig":
        expected = {
            "repository",
            "repository_id",
            "reviewer_usernames",
            "reviewer_team_slugs",
            "ready_for_review",
            "schema",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "PR lifecycle config fields mismatch"
            )
        usernames = value.get("reviewer_usernames")
        teams = value.get("reviewer_team_slugs")
        if not isinstance(usernames, list) or not isinstance(teams, list):
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "PR lifecycle reviewer sets are invalid"
            )
        data = dict(value)
        data["reviewer_usernames"] = tuple(usernames)
        data["reviewer_team_slugs"] = tuple(teams)
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _parse_config(payload: bytes) -> PilotExactTaskPrLifecycleConfig:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskPrLifecycleAuthorizationError("PR lifecycle config is invalid")
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "PR lifecycle config JSON is invalid"
        ) from exc
    config = PilotExactTaskPrLifecycleConfig.from_mapping(raw)
    if config.canonical_json().encode("utf-8") != payload:
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "PR lifecycle config is not canonical JSON"
        )
    return config


def _parse_keyring(payload: bytes) -> tuple[Ed25519AuthorityVerifier, str]:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskPrLifecycleAuthorizationError("PR lifecycle keyring is invalid")
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "PR lifecycle keyring JSON is invalid"
        ) from exc
    if (
        not isinstance(raw, dict)
        or set(raw) != {"schema", "minimum_keyring_epoch", "keys"}
        or raw.get("schema") != PILOT_EXACT_TASK_PR_LIFECYCLE_KEYRING_SCHEMA
    ):
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "PR lifecycle keyring fields/schema mismatch"
        )
    epoch = raw["minimum_keyring_epoch"]
    keys_raw = raw["keys"]
    if (
        isinstance(epoch, bool)
        or not isinstance(epoch, int)
        or epoch < 1
        or not isinstance(keys_raw, list)
        or not 1 <= len(keys_raw) <= 64
    ):
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "PR lifecycle keyring content is invalid"
        )
    keys: dict[str, TrustedEd25519AuthorityKey] = {}
    for item in keys_raw:
        try:
            key = TrustedEd25519AuthorityKey.from_mapping(item)
        except Exception as exc:
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "PR lifecycle trusted key is invalid"
            ) from exc
        if key.key_id in keys:
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "PR lifecycle key IDs are duplicated"
            )
        keys[key.key_id] = key
    if list(keys) != sorted(keys):
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "PR lifecycle keyring keys must be sorted by key_id"
        )
    canonical = _canonical(
        {
            "schema": PILOT_EXACT_TASK_PR_LIFECYCLE_KEYRING_SCHEMA,
            "minimum_keyring_epoch": epoch,
            "keys": [keys[key_id].to_dict() for key_id in sorted(keys)],
        }
    ).encode("utf-8")
    if canonical != payload:
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "PR lifecycle keyring is not canonical JSON"
        )
    return (
        Ed25519AuthorityVerifier(keys, minimum_keyring_epoch=epoch),
        hashlib.sha256(payload).hexdigest(),
    )


def _read_host_authority_file(path: Path) -> bytes:
    try:
        payload = _read_keyring_bytes(Path(path), require_host_control=True)
    except PhysicalRequestAuthorityKeyringError as exc:
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "PR lifecycle authority file is not host-admin controlled"
        ) from exc
    if not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "PR lifecycle authority file is invalid"
        )
    return payload


def _require_live_attestation(
    value: Any,
) -> PilotExactTaskPostPublicationAttestationReceipt:
    if type(value) is not PilotExactTaskPostPublicationAttestationReceipt:
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "exact ADR-DC-052 post-publication attestation is required"
        )
    try:
        replayed = PilotExactTaskPostPublicationAttestationReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "ADR-DC-052 attestation replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "ADR-DC-052 attestation identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_POST_PUBLICATION_ATTESTATION_AUTHORITY
        or value.attestation_authenticated is not True
        or value.post_publication_verified is not True
        or value.durable_completion_verified is not True
        or value.remote_base_verified is not True
        or value.remote_exact_head_verified is not True
        or value.draft_pr_verified is not True
        or value.double_observation_matched is not True
        or value.ready_for_review_authorized is not False
        or value.reviewer_request_authorized is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "ADR-DC-053 requires one fresh unconsumed read-only ADR-DC-052 attestation"
        )
    if attestation_boundary._get_live_post_publication_attestation_inputs(value) is None:
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "ADR-DC-052 live provenance is unavailable"
        )
    return value


def _validate_config_for_attestation(
    config: PilotExactTaskPrLifecycleConfig,
    attestation: PilotExactTaskPostPublicationAttestationReceipt,
) -> None:
    if (
        config.repository != attestation.repository
        or config.repository_id != attestation.repository_id
    ):
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "host-pinned lifecycle config targets another repository"
        )


def _build_authorization_payload(
    *,
    post_publication_attestation: PilotExactTaskPostPublicationAttestationReceipt,
    config: PilotExactTaskPrLifecycleConfig,
    requested_at_utc: str,
    expires_at_utc: str,
    authorizer_actor_id: str,
    authorizer_system_id: str,
    authorizer_key_id: str,
) -> bytes:
    attestation = _require_live_attestation(post_publication_attestation)
    if type(config) is not PilotExactTaskPrLifecycleConfig:
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "exact host-pinned lifecycle config is required"
        )
    _validate_config_for_attestation(config, attestation)
    if not isinstance(authorizer_actor_id, str) or _ACTOR.fullmatch(authorizer_actor_id) is None:
        raise PilotExactTaskPrLifecycleAuthorizationError("authorizer actor is invalid")
    for value, name in (
        (authorizer_system_id, "authorizer system"),
        (authorizer_key_id, "authorizer key"),
    ):
        if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
            raise PilotExactTaskPrLifecycleAuthorizationError(f"{name} is invalid")
    requested = _utc(requested_at_utc, name="requested_at_utc")
    expires = _utc(expires_at_utc, name="expires_at_utc")
    attested = _utc(attestation.attested_at_utc, name="attested_at_utc")
    if requested < attested or expires <= requested:
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "PR lifecycle authorization time window is invalid"
        )
    if (expires - requested).total_seconds() > _MAX_AUTH_SECONDS:
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "PR lifecycle authorization lifetime is too long"
        )
    claim = {
        "schema": PILOT_EXACT_TASK_PR_LIFECYCLE_CLAIM_SCHEMA,
        "authorization_policy_sha256": pilot_exact_task_pr_lifecycle_authorization_policy_sha256(),
        "custody_policy_sha256": asymmetric_authority_key_custody_policy_sha256(),
        "post_publication_attestation_sha256": attestation.sha256,
        "remote_observation_sha256": attestation.remote_observation_sha256,
        "completion_source_receipt_sha256": attestation.completion_source_receipt_sha256,
        "lifecycle_config_sha256": config.sha256,
        "reviewer_set_sha256": config.reviewer_set_sha256,
        "execution_nonce_sha256": attestation.execution_nonce_sha256,
        "development_task_sha256": attestation.development_task_sha256,
        "candidate_patch_sha256": attestation.candidate_patch_sha256,
        "pr_intent_sha256": attestation.pr_intent_sha256,
        "repository": attestation.repository,
        "repository_id": attestation.repository_id,
        "base_branch": attestation.base_branch,
        "head_branch": attestation.head_branch,
        "predicted_commit_sha": attestation.predicted_commit_sha,
        "pull_request_number": attestation.pull_request_number,
        "pull_request_api_url": attestation.pull_request_api_url,
        "reviewer_usernames": list(config.reviewer_usernames),
        "reviewer_team_slugs": list(config.reviewer_team_slugs),
        "ready_for_review": True,
        "request_reviewers": True,
        "authorizer_actor_id": authorizer_actor_id,
        "authorizer_system_id": authorizer_system_id,
        "authorizer_key_id": authorizer_key_id,
        "requested_at_utc": requested_at_utc,
        "expires_at_utc": expires_at_utc,
    }
    return _canonical(claim).encode("utf-8")


def _parse_claim(payload: bytes) -> dict[str, Any]:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "PR lifecycle authorization payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "PR lifecycle authorization payload is invalid JSON"
        ) from exc
    expected = {
        "schema",
        "authorization_policy_sha256",
        "custody_policy_sha256",
        "post_publication_attestation_sha256",
        "remote_observation_sha256",
        "completion_source_receipt_sha256",
        "lifecycle_config_sha256",
        "reviewer_set_sha256",
        "execution_nonce_sha256",
        "development_task_sha256",
        "candidate_patch_sha256",
        "pr_intent_sha256",
        "repository",
        "repository_id",
        "base_branch",
        "head_branch",
        "predicted_commit_sha",
        "pull_request_number",
        "pull_request_api_url",
        "reviewer_usernames",
        "reviewer_team_slugs",
        "ready_for_review",
        "request_reviewers",
        "authorizer_actor_id",
        "authorizer_system_id",
        "authorizer_key_id",
        "requested_at_utc",
        "expires_at_utc",
    }
    if (
        not isinstance(raw, dict)
        or set(raw) != expected
        or _canonical(raw).encode("utf-8") != payload
    ):
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "PR lifecycle authorization payload fields/canonical form mismatch"
        )
    if (
        raw["schema"] != PILOT_EXACT_TASK_PR_LIFECYCLE_CLAIM_SCHEMA
        or raw["authorization_policy_sha256"]
        != pilot_exact_task_pr_lifecycle_authorization_policy_sha256()
        or raw["custody_policy_sha256"] != asymmetric_authority_key_custody_policy_sha256()
        or raw["ready_for_review"] is not True
        or raw["request_reviewers"] is not True
    ):
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "PR lifecycle authorization policy is unsupported"
        )
    for name in (
        "post_publication_attestation_sha256",
        "remote_observation_sha256",
        "completion_source_receipt_sha256",
        "lifecycle_config_sha256",
        "reviewer_set_sha256",
        "execution_nonce_sha256",
        "development_task_sha256",
        "candidate_patch_sha256",
        "pr_intent_sha256",
    ):
        _hex64(raw[name], name=name)
    _hex40(raw["predicted_commit_sha"], name="predicted_commit_sha")
    _utc(raw["requested_at_utc"], name="requested_at_utc")
    _utc(raw["expires_at_utc"], name="expires_at_utc")
    return raw


def _verify_claim(
    *,
    attestation: PilotExactTaskPostPublicationAttestationReceipt,
    config: PilotExactTaskPrLifecycleConfig,
    payload: bytes,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_utc: str,
) -> dict[str, Any]:
    exact = _require_live_attestation(attestation)
    _validate_config_for_attestation(config, exact)
    claim = _parse_claim(payload)
    expected = _build_authorization_payload(
        post_publication_attestation=exact,
        config=config,
        requested_at_utc=claim["requested_at_utc"],
        expires_at_utc=claim["expires_at_utc"],
        authorizer_actor_id=claim["authorizer_actor_id"],
        authorizer_system_id=claim["authorizer_system_id"],
        authorizer_key_id=claim["authorizer_key_id"],
    )
    if expected != payload:
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "PR lifecycle authorization claim is not bound to exact attestation/config"
        )
    if type(signature) is not DetachedEd25519AuthoritySignature:
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "detached Ed25519 lifecycle authorization signature is required"
        )
    payload_sha = hashlib.sha256(payload).hexdigest()
    if (
        signature.payload_sha256 != payload_sha
        or signature.issuer_actor_id != claim["authorizer_actor_id"]
        or signature.issuer_system_id != claim["authorizer_system_id"]
        or signature.key_id != claim["authorizer_key_id"]
    ):
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "PR lifecycle authorization signature binding mismatch"
        )
    now = _utc(now_utc, name="authorization verification time")
    requested = _utc(claim["requested_at_utc"], name="requested_at_utc")
    expires = _utc(claim["expires_at_utc"], name="expires_at_utc")
    if not (requested <= now < expires):
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "PR lifecycle authorization is not currently valid"
        )
    try:
        verifier.verify(payload=payload, signature=signature, at_utc=now_utc)
    except AsymmetricAuthorityError as exc:
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "PR lifecycle Ed25519 authorization verification failed"
        ) from exc
    return claim


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrLifecycleAuthorizationReceipt:
    lifecycle_ledger_root_path_sha256: str
    lifecycle_key_sha256: str
    lifecycle_authorization_payload_sha256: str
    post_publication_attestation_sha256: str
    lifecycle_config_sha256: str
    reviewer_set_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    repository: str
    repository_id: str
    base_branch: str
    head_branch: str
    predicted_commit_sha: str
    pull_request_number: int
    pull_request_api_url: str
    reviewer_usernames: tuple[str, ...]
    reviewer_team_slugs: tuple[str, ...]
    authorizer_actor_id: str
    authorizer_system_id: str
    authorizer_key_id: str
    requested_at_utc: str
    expires_at_utc: str
    reserved_at_utc: str
    host_lifecycle_guard_committed: bool = True
    post_publication_attestation_authenticated: bool = True
    post_publication_verified: bool = True
    lifecycle_config_host_pinned: bool = True
    external_ed25519_authorized: bool = True
    ready_for_review_authorized: bool = True
    reviewer_request_authorized: bool = True
    remote_write_authorized: bool = True
    push_authorized: bool = False
    pr_mutation_authorized: bool = True
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    product_pilot_started: bool = False
    authorization_scope: str = PILOT_EXACT_TASK_PR_LIFECYCLE_AUTHORIZATION_SCOPE
    authority: str = PILOT_EXACT_TASK_PR_LIFECYCLE_AUTHORIZATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PR_LIFECYCLE_AUTHORIZATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_LIFECYCLE_AUTHORIZATION_SCHEMA
            or self.authority != PILOT_EXACT_TASK_PR_LIFECYCLE_AUTHORIZATION_AUTHORITY
            or self.authorization_scope != PILOT_EXACT_TASK_PR_LIFECYCLE_AUTHORIZATION_SCOPE
        ):
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "PR lifecycle authorization receipt identity is unsupported"
            )
        for name in (
            "lifecycle_ledger_root_path_sha256",
            "lifecycle_key_sha256",
            "lifecycle_authorization_payload_sha256",
            "post_publication_attestation_sha256",
            "lifecycle_config_sha256",
            "reviewer_set_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        if self.lifecycle_key_sha256 != self.execution_nonce_sha256:
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "lifecycle replay key must equal execution nonce"
            )
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PilotExactTaskPrLifecycleAuthorizationError("repository is invalid")
        if not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None:
            raise PilotExactTaskPrLifecycleAuthorizationError("repository_id is invalid")
        _branch(self.base_branch, name="base_branch")
        _branch(self.head_branch, name="head_branch")
        if (
            isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/{self.pull_request_number}"
        ):
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "pull-request identity is invalid"
            )
        config = PilotExactTaskPrLifecycleConfig(
            repository=self.repository,
            repository_id=self.repository_id,
            reviewer_usernames=self.reviewer_usernames,
            reviewer_team_slugs=self.reviewer_team_slugs,
        )
        if config.reviewer_set_sha256 != self.reviewer_set_sha256:
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "reviewer set hash is inconsistent"
            )
        requested = _utc(self.requested_at_utc, name="requested_at_utc")
        expires = _utc(self.expires_at_utc, name="expires_at_utc")
        reserved = _utc(self.reserved_at_utc, name="reserved_at_utc")
        if not (requested <= reserved < expires):
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "PR lifecycle receipt timestamps are invalid"
            )
        required_true = (
            "host_lifecycle_guard_committed",
            "post_publication_attestation_authenticated",
            "post_publication_verified",
            "lifecycle_config_host_pinned",
            "external_ed25519_authorized",
            "ready_for_review_authorized",
            "reviewer_request_authorized",
            "remote_write_authorized",
            "pr_mutation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "PR lifecycle authorization evidence/authority is incomplete"
            )
        forced_false = (
            "push_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "product_pilot_started",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "PR lifecycle authorization grants forbidden higher authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def authorization_authenticated(self) -> bool:
        return _get_live_pr_lifecycle_authorization_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }
        result["reviewer_usernames"] = list(self.reviewer_usernames)
        result["reviewer_team_slugs"] = list(self.reviewer_team_slugs)
        return result

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrLifecycleAuthorizationReceipt":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):  # type: ignore[attr-defined]
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "PR lifecycle authorization receipt fields mismatch"
            )
        data = dict(value)
        if not isinstance(data.get("reviewer_usernames"), list) or not isinstance(
            data.get("reviewer_team_slugs"), list
        ):
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "PR lifecycle receipt reviewer sets are invalid"
            )
        data["reviewer_usernames"] = tuple(data["reviewer_usernames"])
        data["reviewer_team_slugs"] = tuple(data["reviewer_team_slugs"])
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskPrLifecycleAuthorizationLedger:
    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path]:
        digest = _hex64(key, name="lifecycle_key_sha256")
        return self.root / f"{digest}.json", self.root / f".{digest}.lock"

    def acquire(
        self,
        *,
        attestation: PilotExactTaskPostPublicationAttestationReceipt,
        payload: bytes,
        config_sha256: str,
        reviewer_set_sha256: str,
    ) -> bytes:
        key = attestation.execution_nonce_sha256
        final, lock = self._paths(key)
        if final.exists() or final.is_symlink() or lock.exists() or lock.is_symlink():
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "PR lifecycle nonce already consumed or needs recovery"
            )
        lock_payload = _canonical(
            {
                "schema": "kaliv-rsi-dc-l16-exact-task-pr-lifecycle-authorization-lock/v1",
                "ledger_scope": PILOT_EXACT_TASK_PR_LIFECYCLE_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "lifecycle_key_sha256": key,
                "post_publication_attestation_sha256": attestation.sha256,
                "lifecycle_authorization_payload_sha256": hashlib.sha256(payload).hexdigest(),
                "lifecycle_config_sha256": config_sha256,
                "reviewer_set_sha256": reviewer_set_sha256,
                "pull_request_number": attestation.pull_request_number,
                "predicted_commit_sha": attestation.predicted_commit_sha,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, lock_payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "PR lifecycle authorization could not be durably consumed"
            ) from exc
        return lock_payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskPrLifecycleAuthorizationReceipt,
        lock_payload: bytes,
        attestation: PilotExactTaskPostPublicationAttestationReceipt,
        config: PilotExactTaskPrLifecycleConfig,
    ) -> PilotExactTaskPrLifecycleAuthorizationReceipt:
        final, lock = self._paths(receipt.lifecycle_key_sha256)
        try:
            observed_lock = lock.read_bytes()
        except OSError as exc:
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "PR lifecycle authorization lock is unavailable"
            ) from exc
        if final.exists() or final.is_symlink() or observed_lock != lock_payload:
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "PR lifecycle durable state changed before finalization"
            )
        final_payload = receipt.canonical_json().encode("utf-8")
        try:
            create_once_file(final, final_payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "PR lifecycle authorization receipt could not be durably published"
            ) from exc
        parsed = PilotExactTaskPrLifecycleAuthorizationReceipt.from_mapping(
            json.loads(final_payload.decode("utf-8"))
        )
        _mark_pr_lifecycle_authorization_authenticated(
            parsed,
            attestation=attestation,
            config=config,
            final_path=final,
            final_payload=final_payload,
            lock_path=lock,
            lock_payload=lock_payload,
        )
        if parsed.authorization_authenticated is not True:
            raise PilotExactTaskPrLifecycleAuthorizationError(
                "PR lifecycle authorization lost live provenance"
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
    records: dict[
        int,
        tuple[
            int,
            str,
            weakref.ReferenceType[Any],
            weakref.ReferenceType[Any],
            PilotExactTaskPrLifecycleConfig,
            Path,
            bytes,
            Path,
            bytes,
        ],
    ] = {}

    def mark(
        receipt: Any,
        *,
        attestation: PilotExactTaskPostPublicationAttestationReceipt,
        config: PilotExactTaskPrLifecycleConfig,
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
            weakref.ref(attestation),
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
            attestation_ref,
            config,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
        ) = entry
        attestation = attestation_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or attestation is None
            or receipt.sha256 != digest
            or attestation.attestation_authenticated is not True
            or receipt.post_publication_attestation_sha256 != attestation.sha256
            or receipt.lifecycle_config_sha256 != config.sha256
            or _read_bound(final_path) != final_payload
            or _read_bound(lock_path) != lock_payload
        ):
            return None
        return MappingProxyType(
            {
                "post_publication_attestation": attestation,
                "lifecycle_config": config,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_pr_lifecycle_authorization_authenticated,
    _get_live_pr_lifecycle_authorization_inputs,
) = _live_registry()


def _authorize_verified_pilot_exact_task_pr_lifecycle(
    *,
    post_publication_attestation: PilotExactTaskPostPublicationAttestationReceipt,
    lifecycle_config: PilotExactTaskPrLifecycleConfig,
    authorization_payload: bytes,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    ledger: _PilotExactTaskPrLifecycleAuthorizationLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskPrLifecycleAuthorizationReceipt:
    attestation = _require_live_attestation(post_publication_attestation)
    if type(lifecycle_config) is not PilotExactTaskPrLifecycleConfig:
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "exact lifecycle config is required"
        )
    _validate_config_for_attestation(lifecycle_config, attestation)
    reserved_at = now_provider()
    claim = _verify_claim(
        attestation=attestation,
        config=lifecycle_config,
        payload=authorization_payload,
        signature=signature,
        verifier=verifier,
        now_utc=reserved_at,
    )
    lock_payload = ledger.acquire(
        attestation=attestation,
        payload=authorization_payload,
        config_sha256=lifecycle_config.sha256,
        reviewer_set_sha256=lifecycle_config.reviewer_set_sha256,
    )
    attestation_again = _require_live_attestation(attestation)
    if attestation_again is not attestation:
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "ADR-DC-052 live attestation changed after lifecycle consumption"
        )
    receipt = PilotExactTaskPrLifecycleAuthorizationReceipt(
        lifecycle_ledger_root_path_sha256=ledger.root_sha256,
        lifecycle_key_sha256=attestation.execution_nonce_sha256,
        lifecycle_authorization_payload_sha256=hashlib.sha256(authorization_payload).hexdigest(),
        post_publication_attestation_sha256=attestation.sha256,
        lifecycle_config_sha256=lifecycle_config.sha256,
        reviewer_set_sha256=lifecycle_config.reviewer_set_sha256,
        execution_nonce_sha256=attestation.execution_nonce_sha256,
        development_task_sha256=attestation.development_task_sha256,
        candidate_patch_sha256=attestation.candidate_patch_sha256,
        pr_intent_sha256=attestation.pr_intent_sha256,
        repository=attestation.repository,
        repository_id=attestation.repository_id,
        base_branch=attestation.base_branch,
        head_branch=attestation.head_branch,
        predicted_commit_sha=attestation.predicted_commit_sha,
        pull_request_number=attestation.pull_request_number,
        pull_request_api_url=attestation.pull_request_api_url,
        reviewer_usernames=lifecycle_config.reviewer_usernames,
        reviewer_team_slugs=lifecycle_config.reviewer_team_slugs,
        authorizer_actor_id=claim["authorizer_actor_id"],
        authorizer_system_id=claim["authorizer_system_id"],
        authorizer_key_id=claim["authorizer_key_id"],
        requested_at_utc=claim["requested_at_utc"],
        expires_at_utc=claim["expires_at_utc"],
        reserved_at_utc=reserved_at,
    )
    return ledger.commit(
        receipt=receipt,
        lock_payload=lock_payload,
        attestation=attestation,
        config=lifecycle_config,
    )


def _canonical_paths() -> tuple[Path, Path, Path]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            return _POSIX_CONFIG, _POSIX_KEYRING, _require_host_controlled_ledger_root(_POSIX_LEDGER)
        if os.name == "nt":
            return _WINDOWS_CONFIG, _WINDOWS_KEYRING, _require_host_controlled_ledger_root(_WINDOWS_LEDGER)
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "PR lifecycle authorization platform is unsupported"
        )
    except PhysicalHostStateError as exc:
        raise PilotExactTaskPrLifecycleAuthorizationError(
            "PR lifecycle ledger is not host-admin controlled"
        ) from exc


def _canonical_config() -> PilotExactTaskPrLifecycleConfig:
    config_path, _keyring_path, _ledger_root = _canonical_paths()
    return _parse_config(_read_host_authority_file(config_path))


def _canonical_runtime() -> tuple[
    PilotExactTaskPrLifecycleConfig,
    Ed25519AuthorityVerifier,
    _PilotExactTaskPrLifecycleAuthorizationLedger,
]:
    config_path, keyring_path, ledger_root = _canonical_paths()
    config = _parse_config(_read_host_authority_file(config_path))
    verifier, _keyring_sha = _parse_keyring(_read_host_authority_file(keyring_path))
    return config, verifier, _PilotExactTaskPrLifecycleAuthorizationLedger(ledger_root)


def build_pilot_exact_task_pr_lifecycle_authorization_payload(
    post_publication_attestation: PilotExactTaskPostPublicationAttestationReceipt,
    requested_at_utc: str,
    expires_at_utc: str,
    authorizer_actor_id: str,
    authorizer_system_id: str,
    authorizer_key_id: str,
) -> bytes:
    """Build exact bytes for an external lifecycle-authority signer."""
    return _build_authorization_payload(
        post_publication_attestation=post_publication_attestation,
        config=_canonical_config(),
        requested_at_utc=requested_at_utc,
        expires_at_utc=expires_at_utc,
        authorizer_actor_id=authorizer_actor_id,
        authorizer_system_id=authorizer_system_id,
        authorizer_key_id=authorizer_key_id,
    )


def authorize_pilot_exact_task_pr_lifecycle(
    post_publication_attestation: PilotExactTaskPostPublicationAttestationReceipt,
    authorization_payload: bytes,
    signature: DetachedEd25519AuthoritySignature,
) -> PilotExactTaskPrLifecycleAuthorizationReceipt:
    """Reserve one exact PR lifecycle slot; perform no GitHub mutation."""
    config, verifier, ledger = _canonical_runtime()
    return _authorize_verified_pilot_exact_task_pr_lifecycle(
        post_publication_attestation=post_publication_attestation,
        lifecycle_config=config,
        authorization_payload=authorization_payload,
        signature=signature,
        verifier=verifier,
        ledger=ledger,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
