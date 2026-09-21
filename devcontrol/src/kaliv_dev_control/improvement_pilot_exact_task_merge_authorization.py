"""ADR-DC-059 dual-authorized one-shot exact merge authorization.

This boundary accepts only one fresh live ADR-DC-058 merge-readiness evaluation
with ``merge_ready=true`` plus one host-admin-pinned merge config. Two independent
detached Ed25519 signatures must authorize the exact repository/base/head/PR and
fixed merge method. The execution nonce is durably consumed before authority is
published.

This boundary performs no GitHub mutation. It authorizes only one future exact
merge transaction; push, arbitrary PR mutation, release, deploy and production
activation remain forbidden.
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
from . import improvement_pilot_exact_task_merge_readiness_evaluation as readiness_boundary
from . import improvement_pilot_exact_task_pr_lifecycle_authorization as lifecycle_auth_boundary
from .improvement_pilot_exact_task_merge_readiness_evaluation import (
    PILOT_EXACT_TASK_MERGE_READINESS_EVALUATION_AUTHORITY,
    PilotExactTaskMergeReadinessEvaluationReceipt,
)

PILOT_EXACT_TASK_MERGE_AUTHORIZATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-merge-authorization-receipt/v1"
)
PILOT_EXACT_TASK_MERGE_AUTHORIZATION_AUTHORITY = (
    "dual-authorized-one-dc-l16-exact-pr-merge-only"
)
PILOT_EXACT_TASK_MERGE_AUTHORIZATION_SCOPE = "one-shot-exact-squash-merge-only-v1"
PILOT_EXACT_TASK_MERGE_CONFIG_SCHEMA = "kaliv-rsi-dc-l16-exact-task-merge-config/v1"
PILOT_EXACT_TASK_MERGE_KEYRING_SCHEMA = "kaliv-rsi-dc-l16-exact-task-merge-keyring/v1"
PILOT_EXACT_TASK_MERGE_CLAIM_SCHEMA = "kaliv-rsi-dc-l16-exact-task-merge-authorization-claim/v1"
PILOT_EXACT_TASK_MERGE_LEDGER_SCOPE = "canonical-host-local-v1"

_MAX_FILE_BYTES = 1024 * 1024
_MAX_AUTH_SECONDS = 10 * 60
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_GITHUB_API_ROOT = "https://api.github.com"

_POSIX_LEDGER = Path("/var/lib/modelrig/devcontrol/rsi-pilot-exact-task-merge-authorization-ledger-v1")
_WINDOWS_LEDGER = Path(r"C:\Program Files\ModelRig\DevControl\state") / "rsi-pilot-exact-task-merge-authorization-ledger-v1"
_POSIX_CONFIG = Path("/etc/modelrig/devcontrol/authority/rsi-pilot-exact-task-merge-config-v1.json")
_WINDOWS_CONFIG = Path(r"C:\Program Files\ModelRig\DevControl\authority\rsi-pilot-exact-task-merge-config-v1.json")
_POSIX_KEYRING = Path("/etc/modelrig/devcontrol/authority/rsi-pilot-exact-task-merge-keyring-v1.json")
_WINDOWS_KEYRING = Path(r"C:\Program Files\ModelRig\DevControl\authority\rsi-pilot-exact-task-merge-keyring-v1.json")


class PilotExactTaskMergeAuthorizationError(ValueError):
    """Exact merge authorization is stale, replayed, unsigned or over-broad."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskMergeAuthorizationError("merge authorization evidence is not canonical JSON") from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskMergeAuthorizationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskMergeAuthorizationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskMergeAuthorizationError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskMergeAuthorizationError(f"{name} is invalid") from exc


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
        raise PilotExactTaskMergeAuthorizationError(f"{name} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class PilotExactTaskMergeConfig:
    repository: str
    repository_id: str
    base_branch: str = "main"
    merge_method: str = "squash"
    schema: str = PILOT_EXACT_TASK_MERGE_CONFIG_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_MERGE_CONFIG_SCHEMA:
            raise PilotExactTaskMergeAuthorizationError("merge config schema is unsupported")
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PilotExactTaskMergeAuthorizationError("merge config repository is invalid")
        if not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None:
            raise PilotExactTaskMergeAuthorizationError("merge config repository_id is invalid")
        _branch(self.base_branch, name="merge config base_branch")
        if self.merge_method != "squash":
            raise PilotExactTaskMergeAuthorizationError("merge config must pin squash merge")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "repository_id": self.repository_id,
            "base_branch": self.base_branch,
            "merge_method": self.merge_method,
            "schema": self.schema,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskMergeConfig":
        expected = {"repository", "repository_id", "base_branch", "merge_method", "schema"}
        if not isinstance(value, Mapping) or set(value) != expected:
            raise PilotExactTaskMergeAuthorizationError("merge config fields mismatch")
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _parse_config(payload: bytes) -> PilotExactTaskMergeConfig:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskMergeAuthorizationError("merge config payload is invalid")
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskMergeAuthorizationError("merge config JSON is invalid") from exc
    config = PilotExactTaskMergeConfig.from_mapping(raw)
    if config.canonical_json().encode("utf-8") != payload:
        raise PilotExactTaskMergeAuthorizationError("merge config is not canonical JSON")
    return config


def _parse_keyring(payload: bytes) -> tuple[Ed25519AuthorityVerifier, str]:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskMergeAuthorizationError("merge keyring payload is invalid")
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskMergeAuthorizationError("merge keyring JSON is invalid") from exc
    if (
        not isinstance(raw, dict)
        or set(raw) != {"schema", "minimum_keyring_epoch", "keys"}
        or raw.get("schema") != PILOT_EXACT_TASK_MERGE_KEYRING_SCHEMA
    ):
        raise PilotExactTaskMergeAuthorizationError("merge keyring fields/schema mismatch")
    epoch = raw["minimum_keyring_epoch"]
    keys_raw = raw["keys"]
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 1 or not isinstance(keys_raw, list) or not 2 <= len(keys_raw) <= 64:
        raise PilotExactTaskMergeAuthorizationError("merge keyring content is invalid")
    keys: dict[str, TrustedEd25519AuthorityKey] = {}
    for item in keys_raw:
        try:
            key = TrustedEd25519AuthorityKey.from_mapping(item)
        except Exception as exc:
            raise PilotExactTaskMergeAuthorizationError("merge trusted key is invalid") from exc
        if key.key_id in keys:
            raise PilotExactTaskMergeAuthorizationError("merge key IDs are duplicated")
        keys[key.key_id] = key
    if list(keys) != sorted(keys):
        raise PilotExactTaskMergeAuthorizationError("merge keyring keys must be sorted by key_id")
    canonical = _canonical({
        "schema": PILOT_EXACT_TASK_MERGE_KEYRING_SCHEMA,
        "minimum_keyring_epoch": epoch,
        "keys": [keys[key_id].to_dict() for key_id in sorted(keys)],
    }).encode("utf-8")
    if canonical != payload:
        raise PilotExactTaskMergeAuthorizationError("merge keyring is not canonical JSON")
    return Ed25519AuthorityVerifier(keys, minimum_keyring_epoch=epoch), hashlib.sha256(payload).hexdigest()


def _read_host_authority_file(path: Path) -> bytes:
    try:
        payload = lifecycle_auth_boundary._read_host_authority_file(Path(path))
    except Exception as exc:
        raise PilotExactTaskMergeAuthorizationError("merge authority file is not host-admin controlled") from exc
    if not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskMergeAuthorizationError("merge authority file is invalid")
    return payload


def _require_live_merge_ready(value: Any) -> PilotExactTaskMergeReadinessEvaluationReceipt:
    if type(value) is not PilotExactTaskMergeReadinessEvaluationReceipt:
        raise PilotExactTaskMergeAuthorizationError("exact live ADR-DC-058 merge-readiness evaluation is required")
    try:
        replayed = PilotExactTaskMergeReadinessEvaluationReceipt.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskMergeAuthorizationError("ADR-DC-058 evaluation replay validation failed") from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskMergeAuthorizationError("ADR-DC-058 evaluation identity mismatch")
    if (
        value.authority != PILOT_EXACT_TASK_MERGE_READINESS_EVALUATION_AUTHORITY
        or value.evaluation_authenticated is not True
        or value.review_state_attestation_authenticated is not True
        or value.merge_readiness_policy_host_pinned is not True
        or value.merge_readiness_evaluated is not True
        or value.merge_ready is not True
        or value.blocker_codes != ()
        or value.github_review_decision_satisfied is not True
        or value.exact_head_approval_threshold_satisfied is not True
        or value.no_exact_head_changes_requested is not True
        or value.no_unresolved_review_threads is not True
        or value.merge_readiness_authorized is not False
        or value.review_submission_authorized is not False
        or value.review_thread_mutation_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskMergeAuthorizationError("ADR-DC-059 requires one positive fresh ADR-DC-058 evaluation")
    live = readiness_boundary._get_live_merge_readiness_evaluation_inputs(value)
    if live is None or live.get("merge_readiness_policy_sha256") != value.merge_readiness_policy_sha256:
        raise PilotExactTaskMergeAuthorizationError("ADR-DC-058 live provenance is unavailable")
    return value


def _validate_config_for_evaluation(config: PilotExactTaskMergeConfig, evaluation: PilotExactTaskMergeReadinessEvaluationReceipt) -> None:
    if (
        config.repository != evaluation.repository
        or config.repository_id != evaluation.repository_id
        or config.base_branch != evaluation.base_branch
        or config.merge_method != "squash"
    ):
        raise PilotExactTaskMergeAuthorizationError("host merge config does not match exact ADR-DC-058 target")


def _build_authorization_payload(
    *,
    merge_readiness_evaluation: PilotExactTaskMergeReadinessEvaluationReceipt,
    merge_config: PilotExactTaskMergeConfig,
    requested_at_utc: str,
    expires_at_utc: str,
    operator_actor_id: str,
    operator_system_id: str,
    operator_key_id: str,
    reviewer_actor_id: str,
    reviewer_system_id: str,
    reviewer_key_id: str,
) -> bytes:
    evaluation = _require_live_merge_ready(merge_readiness_evaluation)
    _validate_config_for_evaluation(merge_config, evaluation)
    requested = _utc(requested_at_utc, name="requested_at_utc")
    expires = _utc(expires_at_utc, name="expires_at_utc")
    if not requested < expires or (expires - requested).total_seconds() > _MAX_AUTH_SECONDS:
        raise PilotExactTaskMergeAuthorizationError("merge authorization validity window is invalid")
    identities = (
        ("operator_actor_id", operator_actor_id),
        ("operator_system_id", operator_system_id),
        ("operator_key_id", operator_key_id),
        ("reviewer_actor_id", reviewer_actor_id),
        ("reviewer_system_id", reviewer_system_id),
        ("reviewer_key_id", reviewer_key_id),
    )
    for name, value in identities:
        pattern = _ACTOR if name.endswith("actor_id") else _IDENTIFIER
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            raise PilotExactTaskMergeAuthorizationError(f"{name} is invalid")
    if operator_actor_id == reviewer_actor_id or operator_system_id == reviewer_system_id or operator_key_id == reviewer_key_id:
        raise PilotExactTaskMergeAuthorizationError("merge authorization requires independent operator and reviewer identities")
    return _canonical({
        "schema": PILOT_EXACT_TASK_MERGE_CLAIM_SCHEMA,
        "merge_readiness_evaluation_sha256": evaluation.sha256,
        "review_state_attestation_sha256": evaluation.review_state_attestation_sha256,
        "merge_readiness_policy_sha256": evaluation.merge_readiness_policy_sha256,
        "merge_config_sha256": merge_config.sha256,
        "execution_nonce_sha256": evaluation.execution_nonce_sha256,
        "development_task_sha256": evaluation.development_task_sha256,
        "candidate_patch_sha256": evaluation.candidate_patch_sha256,
        "pr_intent_sha256": evaluation.pr_intent_sha256,
        "repository": evaluation.repository,
        "repository_id": evaluation.repository_id,
        "base_branch": evaluation.base_branch,
        "base_sha": evaluation.exact_task_base_sha,
        "head_branch": evaluation.head_branch,
        "head_sha": evaluation.predicted_commit_sha,
        "pull_request_number": evaluation.pull_request_number,
        "pull_request_api_url": evaluation.pull_request_api_url,
        "pull_request_node_id_sha256": evaluation.pull_request_node_id_sha256,
        "merge_method": merge_config.merge_method,
        "requested_at_utc": requested_at_utc,
        "expires_at_utc": expires_at_utc,
        "operator_actor_id": operator_actor_id,
        "operator_system_id": operator_system_id,
        "operator_key_id": operator_key_id,
        "reviewer_actor_id": reviewer_actor_id,
        "reviewer_system_id": reviewer_system_id,
        "reviewer_key_id": reviewer_key_id,
    }).encode("utf-8")


def _parse_claim(payload: bytes) -> dict[str, Any]:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskMergeAuthorizationError("merge authorization payload is invalid")
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskMergeAuthorizationError("merge authorization payload JSON is invalid") from exc
    expected = {
        "schema", "merge_readiness_evaluation_sha256", "review_state_attestation_sha256",
        "merge_readiness_policy_sha256", "merge_config_sha256", "execution_nonce_sha256",
        "development_task_sha256", "candidate_patch_sha256", "pr_intent_sha256", "repository",
        "repository_id", "base_branch", "base_sha", "head_branch", "head_sha",
        "pull_request_number", "pull_request_api_url", "pull_request_node_id_sha256",
        "merge_method", "requested_at_utc", "expires_at_utc", "operator_actor_id",
        "operator_system_id", "operator_key_id", "reviewer_actor_id", "reviewer_system_id",
        "reviewer_key_id",
    }
    if not isinstance(raw, dict) or set(raw) != expected or raw.get("schema") != PILOT_EXACT_TASK_MERGE_CLAIM_SCHEMA or _canonical(raw).encode("utf-8") != payload:
        raise PilotExactTaskMergeAuthorizationError("merge authorization payload fields/canonical form mismatch")
    return raw


def _verify_claim_and_signatures(
    *,
    evaluation: PilotExactTaskMergeReadinessEvaluationReceipt,
    config: PilotExactTaskMergeConfig,
    payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_utc: str,
) -> dict[str, Any]:
    claim = _parse_claim(payload)
    expected_payload = _build_authorization_payload(
        merge_readiness_evaluation=evaluation,
        merge_config=config,
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
        raise PilotExactTaskMergeAuthorizationError("merge authorization payload is not bound to exact evaluation/config")
    now = _utc(now_utc, name="reserved_at_utc")
    requested = _utc(claim["requested_at_utc"], name="requested_at_utc")
    expires = _utc(claim["expires_at_utc"], name="expires_at_utc")
    if not requested <= now < expires:
        raise PilotExactTaskMergeAuthorizationError("merge authorization is not currently valid")
    if type(operator_signature) is not DetachedEd25519AuthoritySignature or type(reviewer_signature) is not DetachedEd25519AuthoritySignature:
        raise PilotExactTaskMergeAuthorizationError("two detached Ed25519 merge signatures are required")
    if operator_signature.key_id == reviewer_signature.key_id or operator_signature.issuer_actor_id == reviewer_signature.issuer_actor_id or operator_signature.issuer_system_id == reviewer_signature.issuer_system_id:
        raise PilotExactTaskMergeAuthorizationError("merge signatures must be independent")
    payload_sha = hashlib.sha256(payload).hexdigest()
    bindings = (
        (operator_signature, claim["operator_actor_id"], claim["operator_system_id"], claim["operator_key_id"]),
        (reviewer_signature, claim["reviewer_actor_id"], claim["reviewer_system_id"], claim["reviewer_key_id"]),
    )
    for signature, actor_id, system_id, key_id in bindings:
        if signature.payload_sha256 != payload_sha or signature.issuer_actor_id != actor_id or signature.issuer_system_id != system_id or signature.key_id != key_id:
            raise PilotExactTaskMergeAuthorizationError("merge signature binding mismatch")
        signed = _utc(signature.signed_at_utc, name="signed_at_utc")
        if not requested <= signed < expires or signed > now:
            raise PilotExactTaskMergeAuthorizationError("merge signature timestamp is outside authorization window")
        try:
            verifier.verify(payload=payload, signature=signature, at_utc=now_utc)
        except AsymmetricAuthorityError as exc:
            raise PilotExactTaskMergeAuthorizationError("merge Ed25519 verification failed") from exc
    return claim


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskMergeAuthorizationReceipt:
    merge_ledger_root_path_sha256: str
    merge_key_sha256: str
    merge_authorization_payload_sha256: str
    merge_readiness_evaluation_sha256: str
    review_state_attestation_sha256: str
    merge_readiness_policy_sha256: str
    merge_config_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    repository: str
    repository_id: str
    base_branch: str
    base_sha: str
    head_branch: str
    head_sha: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_node_id_sha256: str
    merge_method: str
    operator_actor_id: str
    operator_system_id: str
    operator_key_id: str
    reviewer_actor_id: str
    reviewer_system_id: str
    reviewer_key_id: str
    requested_at_utc: str
    expires_at_utc: str
    reserved_at_utc: str
    host_merge_guard_committed: bool = True
    merge_readiness_evaluation_authenticated: bool = True
    merge_ready: bool = True
    merge_config_host_pinned: bool = True
    dual_external_ed25519_authorized: bool = True
    merge_authorized: bool = True
    remote_write_authorized: bool = True
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    ready_for_review_authorized: bool = False
    reviewer_request_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    product_pilot_started: bool = False
    nonce_reusable: bool = False
    authorization_scope: str = PILOT_EXACT_TASK_MERGE_AUTHORIZATION_SCOPE
    authority: str = PILOT_EXACT_TASK_MERGE_AUTHORIZATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_MERGE_AUTHORIZATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_MERGE_AUTHORIZATION_SCHEMA or self.authority != PILOT_EXACT_TASK_MERGE_AUTHORIZATION_AUTHORITY or self.authorization_scope != PILOT_EXACT_TASK_MERGE_AUTHORIZATION_SCOPE:
            raise PilotExactTaskMergeAuthorizationError("merge authorization receipt identity is unsupported")
        for name in (
            "merge_ledger_root_path_sha256", "merge_key_sha256", "merge_authorization_payload_sha256",
            "merge_readiness_evaluation_sha256", "review_state_attestation_sha256",
            "merge_readiness_policy_sha256", "merge_config_sha256", "execution_nonce_sha256",
            "development_task_sha256", "candidate_patch_sha256", "pr_intent_sha256",
            "pull_request_node_id_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.base_sha, name="base_sha")
        _hex40(self.head_sha, name="head_sha")
        if self.merge_key_sha256 != self.execution_nonce_sha256:
            raise PilotExactTaskMergeAuthorizationError("merge replay key must equal execution nonce")
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PilotExactTaskMergeAuthorizationError("merge receipt repository is invalid")
        if not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None:
            raise PilotExactTaskMergeAuthorizationError("merge receipt repository_id is invalid")
        _branch(self.base_branch, name="base_branch")
        _branch(self.head_branch, name="head_branch")
        if isinstance(self.pull_request_number, bool) or not isinstance(self.pull_request_number, int) or self.pull_request_number < 1 or self.pull_request_api_url != f"{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/{self.pull_request_number}":
            raise PilotExactTaskMergeAuthorizationError("merge receipt pull-request identity is invalid")
        if self.merge_method != "squash":
            raise PilotExactTaskMergeAuthorizationError("merge receipt method is not pinned to squash")
        for name in ("operator_actor_id", "reviewer_actor_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
                raise PilotExactTaskMergeAuthorizationError(f"{name} is invalid")
        for name in ("operator_system_id", "operator_key_id", "reviewer_system_id", "reviewer_key_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
                raise PilotExactTaskMergeAuthorizationError(f"{name} is invalid")
        if self.operator_actor_id == self.reviewer_actor_id or self.operator_system_id == self.reviewer_system_id or self.operator_key_id == self.reviewer_key_id:
            raise PilotExactTaskMergeAuthorizationError("merge receipt signers are not independent")
        requested = _utc(self.requested_at_utc, name="requested_at_utc")
        expires = _utc(self.expires_at_utc, name="expires_at_utc")
        reserved = _utc(self.reserved_at_utc, name="reserved_at_utc")
        if not requested <= reserved < expires or (expires - requested).total_seconds() > _MAX_AUTH_SECONDS:
            raise PilotExactTaskMergeAuthorizationError("merge receipt timestamps are invalid")
        required_true = (
            "host_merge_guard_committed", "merge_readiness_evaluation_authenticated", "merge_ready",
            "merge_config_host_pinned", "dual_external_ed25519_authorized", "merge_authorized",
            "remote_write_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskMergeAuthorizationError("merge authorization evidence/authority is incomplete")
        forced_false = (
            "review_submission_authorized", "review_thread_mutation_authorized", "ready_for_review_authorized",
            "reviewer_request_authorized", "push_authorized", "pr_mutation_authorized", "release_authorized",
            "deploy_authorized", "production_activation_authorized", "product_pilot_started", "nonce_reusable",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskMergeAuthorizationError("merge authorization grants forbidden additional authority")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def authorization_authenticated(self) -> bool:
        return _get_live_merge_authorization_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskMergeAuthorizationReceipt":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):  # type: ignore[attr-defined]
            raise PilotExactTaskMergeAuthorizationError("merge authorization receipt fields mismatch")
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskMergeAuthorizationLedger:
    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path]:
        digest = _hex64(key, name="merge_key_sha256")
        return self.root / f"{digest}.json", self.root / f".{digest}.lock"

    def acquire(self, *, evaluation, payload: bytes, config_sha256: str, operator_signature, reviewer_signature) -> bytes:
        key = evaluation.execution_nonce_sha256
        final, lock = self._paths(key)
        if final.exists() or final.is_symlink() or lock.exists() or lock.is_symlink():
            raise PilotExactTaskMergeAuthorizationError("merge nonce already consumed or needs recovery")
        lock_payload = _canonical({
            "schema": "kaliv-rsi-dc-l16-exact-task-merge-authorization-lock/v1",
            "ledger_scope": PILOT_EXACT_TASK_MERGE_LEDGER_SCOPE,
            "ledger_root_path_sha256": self.root_sha256,
            "merge_key_sha256": key,
            "merge_readiness_evaluation_sha256": evaluation.sha256,
            "merge_authorization_payload_sha256": hashlib.sha256(payload).hexdigest(),
            "merge_config_sha256": config_sha256,
            "repository": evaluation.repository,
            "repository_id": evaluation.repository_id,
            "base_branch": evaluation.base_branch,
            "base_sha": evaluation.exact_task_base_sha,
            "head_branch": evaluation.head_branch,
            "head_sha": evaluation.predicted_commit_sha,
            "pull_request_number": evaluation.pull_request_number,
            "merge_method": "squash",
            "operator_signature_sha256": hashlib.sha256(operator_signature.canonical_json().encode("utf-8")).hexdigest(),
            "reviewer_signature_sha256": hashlib.sha256(reviewer_signature.canonical_json().encode("utf-8")).hexdigest(),
        }).encode("utf-8")
        try:
            create_once_file(lock, lock_payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskMergeAuthorizationError("merge authorization could not be durably consumed") from exc
        return lock_payload

    def commit(self, *, receipt, lock_payload: bytes, evaluation, config) -> PilotExactTaskMergeAuthorizationReceipt:
        final, lock = self._paths(receipt.merge_key_sha256)
        try:
            observed_lock = lock.read_bytes()
        except OSError as exc:
            raise PilotExactTaskMergeAuthorizationError("merge authorization lock is unavailable") from exc
        if final.exists() or final.is_symlink() or observed_lock != lock_payload:
            raise PilotExactTaskMergeAuthorizationError("merge authorization durable state changed before finalization")
        final_payload = receipt.canonical_json().encode("utf-8")
        try:
            create_once_file(final, final_payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskMergeAuthorizationError("merge authorization receipt could not be durably published") from exc
        parsed = PilotExactTaskMergeAuthorizationReceipt.from_mapping(json.loads(final_payload.decode("utf-8")))
        _mark_merge_authorization_authenticated(
            parsed, evaluation=evaluation, config=config, final_path=final,
            final_payload=final_payload, lock_path=lock, lock_payload=lock_payload,
        )
        if parsed.authorization_authenticated is not True:
            raise PilotExactTaskMergeAuthorizationError("merge authorization lost live provenance")
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
    records = {}

    def mark(receipt, *, evaluation, config, final_path, final_payload, lock_path, lock_payload):
        key = id(receipt)
        def cleanup(_):
            records.pop(key, None)
        records[key] = (
            os.getpid(), receipt.sha256, weakref.ref(receipt, cleanup), weakref.ref(evaluation),
            config, final_path, final_payload, lock_path, lock_payload,
        )

    def get(receipt):
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, evaluation_ref, config, final_path, final_payload, lock_path, lock_payload = entry
        evaluation = evaluation_ref()
        if (
            pid != os.getpid() or receipt_ref() is not receipt or evaluation is None
            or receipt.sha256 != digest or evaluation.evaluation_authenticated is not True
            or evaluation.sha256 != receipt.merge_readiness_evaluation_sha256 or evaluation.merge_ready is not True
            or config.sha256 != receipt.merge_config_sha256 or _read_bound(final_path) != final_payload
            or _read_bound(lock_path) != lock_payload
        ):
            return None
        return MappingProxyType({"merge_readiness_evaluation": evaluation, "merge_config": config})

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_merge_authorization_authenticated, _get_live_merge_authorization_inputs = _live_registry()


def _authorize_verified_pilot_exact_task_merge(
    *, merge_readiness_evaluation, merge_config, authorization_payload: bytes,
    operator_signature, reviewer_signature, verifier, ledger, now_provider: Callable[[], str],
) -> PilotExactTaskMergeAuthorizationReceipt:
    evaluation = _require_live_merge_ready(merge_readiness_evaluation)
    if type(merge_config) is not PilotExactTaskMergeConfig:
        raise PilotExactTaskMergeAuthorizationError("exact merge config is required")
    _validate_config_for_evaluation(merge_config, evaluation)
    reserved_at = now_provider()
    claim = _verify_claim_and_signatures(
        evaluation=evaluation, config=merge_config, payload=authorization_payload,
        operator_signature=operator_signature, reviewer_signature=reviewer_signature,
        verifier=verifier, now_utc=reserved_at,
    )
    lock_payload = ledger.acquire(
        evaluation=evaluation, payload=authorization_payload, config_sha256=merge_config.sha256,
        operator_signature=operator_signature, reviewer_signature=reviewer_signature,
    )
    if _require_live_merge_ready(evaluation) is not evaluation:
        raise PilotExactTaskMergeAuthorizationError("ADR-DC-058 live evaluation changed after merge consumption")
    receipt = PilotExactTaskMergeAuthorizationReceipt(
        merge_ledger_root_path_sha256=ledger.root_sha256,
        merge_key_sha256=evaluation.execution_nonce_sha256,
        merge_authorization_payload_sha256=hashlib.sha256(authorization_payload).hexdigest(),
        merge_readiness_evaluation_sha256=evaluation.sha256,
        review_state_attestation_sha256=evaluation.review_state_attestation_sha256,
        merge_readiness_policy_sha256=evaluation.merge_readiness_policy_sha256,
        merge_config_sha256=merge_config.sha256,
        execution_nonce_sha256=evaluation.execution_nonce_sha256,
        development_task_sha256=evaluation.development_task_sha256,
        candidate_patch_sha256=evaluation.candidate_patch_sha256,
        pr_intent_sha256=evaluation.pr_intent_sha256,
        repository=evaluation.repository,
        repository_id=evaluation.repository_id,
        base_branch=evaluation.base_branch,
        base_sha=evaluation.exact_task_base_sha,
        head_branch=evaluation.head_branch,
        head_sha=evaluation.predicted_commit_sha,
        pull_request_number=evaluation.pull_request_number,
        pull_request_api_url=evaluation.pull_request_api_url,
        pull_request_node_id_sha256=evaluation.pull_request_node_id_sha256,
        merge_method=merge_config.merge_method,
        operator_actor_id=claim["operator_actor_id"], operator_system_id=claim["operator_system_id"], operator_key_id=claim["operator_key_id"],
        reviewer_actor_id=claim["reviewer_actor_id"], reviewer_system_id=claim["reviewer_system_id"], reviewer_key_id=claim["reviewer_key_id"],
        requested_at_utc=claim["requested_at_utc"], expires_at_utc=claim["expires_at_utc"], reserved_at_utc=reserved_at,
    )
    return ledger.commit(receipt=receipt, lock_payload=lock_payload, evaluation=evaluation, config=merge_config)


def _canonical_paths() -> tuple[Path, Path, Path]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            return _POSIX_CONFIG, _POSIX_KEYRING, _require_host_controlled_ledger_root(_POSIX_LEDGER)
        if os.name == "nt":
            return _WINDOWS_CONFIG, _WINDOWS_KEYRING, _require_host_controlled_ledger_root(_WINDOWS_LEDGER)
        raise PilotExactTaskMergeAuthorizationError("merge authorization platform is unsupported")
    except PhysicalHostStateError as exc:
        raise PilotExactTaskMergeAuthorizationError("merge authorization ledger is not host-admin controlled") from exc


def _canonical_config() -> PilotExactTaskMergeConfig:
    config_path, _keyring_path, _ledger_root = _canonical_paths()
    first = _read_host_authority_file(config_path)
    second = _read_host_authority_file(config_path)
    if first != second:
        raise PilotExactTaskMergeAuthorizationError("merge config changed while being read")
    return _parse_config(second)


def _canonical_runtime():
    config_path, keyring_path, ledger_root = _canonical_paths()
    first_config = _read_host_authority_file(config_path)
    second_config = _read_host_authority_file(config_path)
    if first_config != second_config:
        raise PilotExactTaskMergeAuthorizationError("merge config changed while being read")
    first_keyring = _read_host_authority_file(keyring_path)
    second_keyring = _read_host_authority_file(keyring_path)
    if first_keyring != second_keyring:
        raise PilotExactTaskMergeAuthorizationError("merge keyring changed while being read")
    config = _parse_config(second_config)
    verifier, _keyring_sha = _parse_keyring(second_keyring)
    return config, verifier, _PilotExactTaskMergeAuthorizationLedger(ledger_root)


def build_pilot_exact_task_merge_authorization_payload(
    merge_readiness_evaluation: PilotExactTaskMergeReadinessEvaluationReceipt,
    requested_at_utc: str,
    expires_at_utc: str,
    operator_actor_id: str,
    operator_system_id: str,
    operator_key_id: str,
    reviewer_actor_id: str,
    reviewer_system_id: str,
    reviewer_key_id: str,
) -> bytes:
    """Build exact bytes for two independent external merge-authority signers."""
    return _build_authorization_payload(
        merge_readiness_evaluation=merge_readiness_evaluation,
        merge_config=_canonical_config(),
        requested_at_utc=requested_at_utc, expires_at_utc=expires_at_utc,
        operator_actor_id=operator_actor_id, operator_system_id=operator_system_id, operator_key_id=operator_key_id,
        reviewer_actor_id=reviewer_actor_id, reviewer_system_id=reviewer_system_id, reviewer_key_id=reviewer_key_id,
    )


def authorize_pilot_exact_task_merge(
    merge_readiness_evaluation: PilotExactTaskMergeReadinessEvaluationReceipt,
    authorization_payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
) -> PilotExactTaskMergeAuthorizationReceipt:
    """Reserve one exact merge slot; perform no GitHub mutation."""
    config, verifier, ledger = _canonical_runtime()
    return _authorize_verified_pilot_exact_task_merge(
        merge_readiness_evaluation=merge_readiness_evaluation, merge_config=config,
        authorization_payload=authorization_payload, operator_signature=operator_signature,
        reviewer_signature=reviewer_signature, verifier=verifier, ledger=ledger,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
