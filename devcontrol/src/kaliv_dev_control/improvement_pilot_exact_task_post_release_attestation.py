"""ADR-DC-069 read-only exact post-release attestation.

Normalizes exactly one completed ADR-DC-067 release transaction or one completed
ADR-DC-068 release recovery into a restart-safe exact tag+draft-release
attestation. Durable completion evidence is verified first, then GitHub release
state is observed twice through a credential-bound GET-only observer.

No tag/release mutation, deployment, production activation, or other remote
write authority is granted by this boundary.
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
from ._improvement_pilot_start_consumption_impl import _safe_ledger_root
from . import improvement_pilot_exact_task_release_authorization as auth_boundary
from . import improvement_pilot_exact_task_release_recovery as recovery_boundary
from . import improvement_pilot_exact_task_release_state_observation as state_boundary
from . import improvement_pilot_exact_task_release_transaction as tx_boundary
from . import improvement_pilot_exact_task_remote_publication_transaction as publication_tx_boundary
from .improvement_pilot_exact_task_release_recovery import (
    PilotExactTaskReleaseRecoveryReceipt,
)
from .improvement_pilot_exact_task_release_transaction import (
    PilotExactTaskReleaseTransactionReceipt,
)

PILOT_EXACT_TASK_POST_RELEASE_ATTESTATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-post-release-attestation-receipt/v1"
)
PILOT_EXACT_TASK_POST_RELEASE_ATTESTATION_AUTHORITY = (
    "host-attested-one-dc-l16-exact-post-release-state-only"
)
PILOT_EXACT_TASK_POST_RELEASE_ATTESTATION_SCOPE = (
    "read-only-exact-post-release-verification-v1"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PilotExactTaskPostReleaseAttestationError(ValueError):
    """Durable release completion or exact GitHub release state is untrustworthy."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPostReleaseAttestationError("post-release evidence is not canonical JSON") from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPostReleaseAttestationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPostReleaseAttestationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPostReleaseAttestationError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskPostReleaseAttestationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _payload_sha256(payload: bytes) -> str:
    if not isinstance(payload, bytes) or not payload:
        raise PilotExactTaskPostReleaseAttestationError("durable release payload is missing")
    return hashlib.sha256(payload).hexdigest()


def _read_canonical(path: Path, *, name: str) -> tuple[dict[str, Any], bytes]:
    try:
        return recovery_boundary._read_canonical_object(path, name=name)
    except Exception as exc:
        raise PilotExactTaskPostReleaseAttestationError(f"{name} is unavailable or invalid") from exc


@dataclass(frozen=True, slots=True)
class _ReleaseCompletionEvidence:
    source_kind: str
    source_receipt_sha256: str
    source_completed_at_utc: str
    transaction_lock_sha256: str
    tag_marker_sha256: str | None
    release_marker_sha256: str | None
    recovery_lock_sha256: str | None
    source_final_remote_release_state_sha256: str
    release_id: int
    release_node_id_sha256: str
    source_action: str
    source_remote_write_performed: bool

    def __post_init__(self) -> None:
        if self.source_kind not in {"transaction", "recovery"}:
            raise PilotExactTaskPostReleaseAttestationError("release completion source kind is unsupported")
        for name in ("source_receipt_sha256", "transaction_lock_sha256", "source_final_remote_release_state_sha256", "release_node_id_sha256"):
            _hex64(getattr(self, name), name=name)
        for name in ("tag_marker_sha256", "release_marker_sha256", "recovery_lock_sha256"):
            value = getattr(self, name)
            if value is not None:
                _hex64(value, name=name)
        if isinstance(self.release_id, bool) or not isinstance(self.release_id, int) or self.release_id < 1:
            raise PilotExactTaskPostReleaseAttestationError("release completion release ID is invalid")
        if self.source_kind == "transaction":
            if self.tag_marker_sha256 is None or self.release_marker_sha256 is None or self.recovery_lock_sha256 is not None or self.source_action != "execute_exact_release" or self.source_remote_write_performed is not True:
                raise PilotExactTaskPostReleaseAttestationError("normal release completion phase evidence is incomplete")
        else:
            if self.recovery_lock_sha256 is None or self.source_action not in {"create_missing_release", "finalize_existing_state"}:
                raise PilotExactTaskPostReleaseAttestationError("release recovery completion evidence is incomplete")
        _utc(self.source_completed_at_utc, name="source_completed_at_utc")


def _validate_tx_lock(raw: Mapping[str, Any], *, authorization: Any, ledger_root_sha256: str) -> None:
    expected = {
        "schema": "kaliv-rsi-dc-l16-exact-task-release-transaction-lock/v1",
        "ledger_scope": tx_boundary.PILOT_EXACT_TASK_RELEASE_TRANSACTION_LEDGER_SCOPE,
        "ledger_root_path_sha256": ledger_root_sha256,
        "release_key_sha256": authorization.execution_nonce_sha256,
        "release_authorization_sha256": authorization.sha256,
        "release_authorization_payload_sha256": authorization.release_authorization_payload_sha256,
        "release_state_observation_sha256": authorization.release_state_observation_sha256,
        "release_plan_sha256": authorization.release_plan_sha256,
        "release_intent_sha256": authorization.release_intent_sha256,
        "remote_release_state_sha256": authorization.remote_release_state_sha256,
        "release_authorization_config_sha256": authorization.release_authorization_config_sha256,
        "publisher_credential_config_sha256": authorization.publisher_credential_config_sha256,
        "publisher_credential_path_sha256": authorization.publisher_credential_path_sha256,
        "repository": authorization.repository,
        "repository_id": authorization.repository_id,
        "release_base_branch": authorization.release_base_branch,
        "merge_commit_sha": authorization.merge_commit_sha,
        "tag_name": authorization.tag_name,
        "tag_target_sha": authorization.tag_target_sha,
        "release_name": authorization.release_name,
        "release_body_sha256": authorization.release_body_sha256,
        "release_draft": True,
        "release_prerelease": True,
        "make_latest": False,
    }
    if any(raw.get(name) != value for name, value in expected.items()):
        raise PilotExactTaskPostReleaseAttestationError("ADR-DC-067 transaction lock differs from exact release authority")
    _utc(raw.get("locked_at_utc"), name="locked_at_utc")


def _marker_payloads(*, authorization: Any, tx_ledger: Any) -> tuple[bytes, bytes | None, bytes | None]:
    _final, lock, tag_marker, release_marker = tx_ledger._paths(authorization.execution_nonce_sha256)
    lock_raw, lock_payload = _read_canonical(lock, name="ADR-DC-067 release transaction lock")
    _validate_tx_lock(lock_raw, authorization=authorization, ledger_root_sha256=tx_ledger.root_sha256)
    tag_payload = None
    release_payload = None
    if tag_marker.exists() or tag_marker.is_symlink():
        tag_raw, tag_payload = _read_canonical(tag_marker, name="ADR-DC-067 tag marker")
        if tag_raw.get("schema") != "kaliv-rsi-dc-l16-exact-task-release-transaction-tag-marker/v1" or tag_raw.get("release_authorization_sha256") != authorization.sha256 or tag_raw.get("release_key_sha256") != authorization.execution_nonce_sha256 or tag_raw.get("tag_name") != authorization.tag_name or tag_raw.get("tag_target_sha") != authorization.tag_target_sha:
            raise PilotExactTaskPostReleaseAttestationError("ADR-DC-067 tag marker differs from exact release authority")
        _utc(tag_raw.get("tag_created_at_utc"), name="tag_created_at_utc")
    if release_marker.exists() or release_marker.is_symlink():
        if tag_payload is None:
            raise PilotExactTaskPostReleaseAttestationError("ADR-DC-067 release marker exists without tag marker")
        release_raw, release_payload = _read_canonical(release_marker, name="ADR-DC-067 release marker")
        if release_raw.get("schema") != "kaliv-rsi-dc-l16-exact-task-release-transaction-release-marker/v1" or release_raw.get("release_authorization_sha256") != authorization.sha256 or release_raw.get("release_key_sha256") != authorization.execution_nonce_sha256 or release_raw.get("tag_name") != authorization.tag_name or isinstance(release_raw.get("release_id"), bool) or not isinstance(release_raw.get("release_id"), int) or release_raw["release_id"] < 1:
            raise PilotExactTaskPostReleaseAttestationError("ADR-DC-067 release marker differs from exact release authority")
        _hex64(release_raw.get("release_node_id_sha256"), name="release_node_id_sha256")
        _utc(release_raw.get("release_created_at_utc"), name="release_created_at_utc")
    return lock_payload, tag_payload, release_payload


def _read_completion(*, authorization: Any, transaction_ledger_root: Path, recovery_ledger_root: Path) -> _ReleaseCompletionEvidence:
    key = authorization.execution_nonce_sha256
    tx_ledger = tx_boundary._PilotExactTaskReleaseTransactionLedger(_safe_ledger_root(transaction_ledger_root))
    recovery_ledger = recovery_boundary._PilotExactTaskReleaseRecoveryLedger(_safe_ledger_root(recovery_ledger_root))
    tx_final, _tx_lock, _tx_tag, _tx_release = tx_ledger._paths(key)
    recovery_final, recovery_lock = recovery_ledger._paths(key)
    tx_present = tx_final.exists() or tx_final.is_symlink()
    recovery_present = recovery_final.exists() or recovery_final.is_symlink()
    if tx_present == recovery_present:
        raise PilotExactTaskPostReleaseAttestationError("post-release completion source must be exactly one of ADR-DC-067 or ADR-DC-068")
    lock_payload, tag_payload, release_payload = _marker_payloads(authorization=authorization, tx_ledger=tx_ledger)
    lock_sha = _payload_sha256(lock_payload)
    tag_sha = None if tag_payload is None else _payload_sha256(tag_payload)
    release_sha = None if release_payload is None else _payload_sha256(release_payload)
    if tx_present:
        if tag_sha is None or release_sha is None:
            raise PilotExactTaskPostReleaseAttestationError("completed ADR-DC-067 transaction lacks durable phase markers")
        raw, payload = _read_canonical(tx_final, name="ADR-DC-067 final release transaction receipt")
        try:
            receipt = PilotExactTaskReleaseTransactionReceipt.from_mapping(raw)
        except Exception as exc:
            raise PilotExactTaskPostReleaseAttestationError("ADR-DC-067 final release receipt is invalid") from exc
        if receipt.canonical_json().encode("utf-8") != payload or receipt.release_key_sha256 != key or receipt.execution_nonce_sha256 != key or receipt.release_authorization_sha256 != authorization.sha256 or receipt.release_intent_sha256 != authorization.release_intent_sha256 or receipt.release_plan_sha256 != authorization.release_plan_sha256 or receipt.release_readiness_evaluation_sha256 != authorization.release_readiness_evaluation_sha256 or receipt.release_plan_config_sha256 != authorization.release_plan_config_sha256 or receipt.release_authorization_config_sha256 != authorization.release_authorization_config_sha256 or receipt.transaction_lock_sha256 != lock_sha or receipt.tag_marker_sha256 != tag_sha or receipt.release_marker_sha256 != release_sha or receipt.publisher_credential_config_sha256 != authorization.publisher_credential_config_sha256 or receipt.publisher_credential_path_sha256 != authorization.publisher_credential_path_sha256 or receipt.repository != authorization.repository or receipt.repository_id != authorization.repository_id or receipt.release_base_branch != authorization.release_base_branch or receipt.merge_commit_sha != authorization.merge_commit_sha or receipt.release_version != authorization.release_version or receipt.tag_name != authorization.tag_name or receipt.tag_target_sha != authorization.tag_target_sha or receipt.release_name != authorization.release_name or receipt.release_body_sha256 != authorization.release_body_sha256 or receipt.release_draft is not True or receipt.release_prerelease is not True or receipt.make_latest is not False or receipt.transaction_completed is not True or receipt.release_authorized is not False or receipt.remote_write_authorized is not False or receipt.deploy_authorized is not False or receipt.production_activation_authorized is not False or receipt.nonce_reusable is not False:
            raise PilotExactTaskPostReleaseAttestationError("ADR-DC-067 final receipt is not exact release completion")
        return _ReleaseCompletionEvidence(source_kind="transaction", source_receipt_sha256=receipt.sha256, source_completed_at_utc=receipt.completed_at_utc, transaction_lock_sha256=lock_sha, tag_marker_sha256=tag_sha, release_marker_sha256=release_sha, recovery_lock_sha256=None, source_final_remote_release_state_sha256=receipt.final_remote_release_state_sha256, release_id=receipt.release_id, release_node_id_sha256=receipt.release_node_id_sha256, source_action="execute_exact_release", source_remote_write_performed=True)
    raw, payload = _read_canonical(recovery_final, name="ADR-DC-068 final release recovery receipt")
    recovery_lock_raw, recovery_lock_payload = _read_canonical(recovery_lock, name="ADR-DC-068 release recovery lock")
    try:
        receipt = PilotExactTaskReleaseRecoveryReceipt.from_mapping(raw)
    except Exception as exc:
        raise PilotExactTaskPostReleaseAttestationError("ADR-DC-068 final release recovery receipt is invalid") from exc
    if receipt.canonical_json().encode("utf-8") != payload or recovery_lock_raw.get("schema") != "kaliv-rsi-dc-l16-exact-task-release-recovery-lock/v1" or recovery_lock_raw.get("ledger_scope") != recovery_boundary.PILOT_EXACT_TASK_RELEASE_RECOVERY_LEDGER_SCOPE or recovery_lock_raw.get("ledger_root_path_sha256") != recovery_ledger.root_sha256 or recovery_lock_raw.get("recovery_key_sha256") != key or recovery_lock_raw.get("recovery_state_fingerprint_sha256") != receipt.recovery_state_fingerprint_sha256 or recovery_lock_raw.get("recovery_authorization_payload_sha256") != receipt.recovery_authorization_payload_sha256 or recovery_lock_raw.get("release_authorization_sha256") != receipt.release_authorization_sha256 or recovery_lock_raw.get("action") != receipt.action_performed:
        raise PilotExactTaskPostReleaseAttestationError("ADR-DC-068 recovery lock does not bind final recovery receipt")
    for name in ("operator_signature_sha256", "reviewer_signature_sha256"):
        _hex64(recovery_lock_raw.get(name), name=name)
    if receipt.recovery_key_sha256 != key or receipt.execution_nonce_sha256 != key or receipt.release_authorization_sha256 != authorization.sha256 or receipt.release_intent_sha256 != authorization.release_intent_sha256 or receipt.transaction_lock_sha256 != lock_sha or receipt.tag_marker_sha256 != tag_sha or receipt.release_marker_sha256 != release_sha or receipt.publisher_credential_config_sha256 != authorization.publisher_credential_config_sha256 or receipt.publisher_credential_path_sha256 != authorization.publisher_credential_path_sha256 or receipt.repository != authorization.repository or receipt.repository_id != authorization.repository_id or receipt.release_base_branch != authorization.release_base_branch or receipt.merge_commit_sha != authorization.merge_commit_sha or receipt.release_version != authorization.release_version or receipt.tag_name != authorization.tag_name or receipt.tag_target_sha != authorization.tag_target_sha or receipt.release_name != authorization.release_name or receipt.release_body_sha256 != authorization.release_body_sha256 or receipt.exact_release_finalized is not True or receipt.recovery_completed is not True or receipt.release_authorized is not False or receipt.remote_write_authorized is not False or receipt.deploy_authorized is not False or receipt.production_activation_authorized is not False or receipt.nonce_reusable is not False:
        raise PilotExactTaskPostReleaseAttestationError("ADR-DC-068 final receipt is not exact release completion")
    return _ReleaseCompletionEvidence(source_kind="recovery", source_receipt_sha256=receipt.sha256, source_completed_at_utc=receipt.recovered_at_utc, transaction_lock_sha256=lock_sha, tag_marker_sha256=tag_sha, release_marker_sha256=release_sha, recovery_lock_sha256=_payload_sha256(recovery_lock_payload), source_final_remote_release_state_sha256=receipt.final_remote_release_state_sha256, release_id=receipt.release_id, release_node_id_sha256=receipt.release_node_id_sha256, source_action=receipt.action_performed, source_remote_write_performed=receipt.remote_write_performed)


class _GitHubPostReleaseObserver:
    """Credential-bound GET-only observer for exact completed release state."""

    def __init__(self, *, credential: Any, credential_config_sha256: str, credential_path: Path) -> None:
        self.credential_config_sha256 = _hex64(credential_config_sha256, name="credential_config_sha256")
        self.credential_path = Path(credential_path)
        self.credential_path_sha256 = recovery_boundary._path_sha256(self.credential_path)
        self._observer = state_boundary._GitHubReleaseStateObserver(credential=credential, credential_config_sha256=credential_config_sha256, credential_path=credential_path)

    def observe(self, authorization: Any) -> Any:
        projection = recovery_boundary._GitHubReleaseRecoveryTransport._projection(authorization)
        root = self._observer._repo_root(projection)
        status, repo = self._observer._get_json_or_404(plan=projection, path=root)
        if status != 200 or not isinstance(repo, Mapping) or str(repo.get("id")) != authorization.repository_id or repo.get("full_name") != authorization.repository:
            raise PilotExactTaskPostReleaseAttestationError("GitHub repository identity differs from exact release authority")
        tag_state, tag_target = self._observer._observe_tag(projection)
        release = self._observer._observe_release(projection)
        if tag_state != "exact" or tag_target != authorization.tag_target_sha or release is None:
            raise PilotExactTaskPostReleaseAttestationError("GitHub release state is not exact completed release")
        return recovery_boundary._ReleaseRecoveryRemoteState(repository=authorization.repository, repository_id=authorization.repository_id, tag_state="exact", tag_target_sha=authorization.tag_target_sha, release_state="exact-draft", release_id=release["release_id"], release_node_id_sha256=release["release_node_id_sha256"], remote_state_class="exact_existing")


def _normalize_remote_state(*, value: Any, authorization: Any, completion: _ReleaseCompletionEvidence) -> dict[str, Any]:
    if type(value) is not recovery_boundary._ReleaseRecoveryRemoteState:
        raise PilotExactTaskPostReleaseAttestationError("post-release GitHub observer returned invalid state")
    if value.repository != authorization.repository or value.repository_id != authorization.repository_id or value.remote_state_class != "exact_existing" or value.tag_state != "exact" or value.tag_target_sha != authorization.tag_target_sha or value.release_state != "exact-draft" or value.release_id != completion.release_id or value.release_node_id_sha256 != completion.release_node_id_sha256:
        raise PilotExactTaskPostReleaseAttestationError("GitHub state is not exact completed deterministic release")
    return {"repository": value.repository, "repository_id": value.repository_id, "tag_state": "exact", "tag_target_sha": authorization.tag_target_sha, "release_state": "exact-draft", "release_id": completion.release_id, "release_node_id_sha256": completion.release_node_id_sha256, "release_version": authorization.release_version, "tag_name": authorization.tag_name, "release_name": authorization.release_name, "release_body_sha256": authorization.release_body_sha256, "release_draft": True, "release_prerelease": True, "make_latest": False}


def _live_registry():
    records: dict[int, tuple[int, str, weakref.ReferenceType[Any], str, str, str]] = {}
    def mark(receipt: Any, *, source_kind: str, source_receipt_sha256: str, observation_sha256: str) -> None:
        key = id(receipt)
        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)
        records[key] = (os.getpid(), receipt.sha256, weakref.ref(receipt, cleanup), source_kind, source_receipt_sha256, observation_sha256)
    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, ref, source_kind, source_receipt_sha256, observation_sha256 = entry
        if pid != os.getpid() or ref() is not receipt or receipt.sha256 != digest or receipt.completion_source != source_kind or receipt.completion_source_receipt_sha256 != source_receipt_sha256 or receipt.remote_observation_sha256 != observation_sha256:
            return None
        return MappingProxyType({"completion_source": source_kind, "completion_source_receipt_sha256": source_receipt_sha256, "remote_observation_sha256": observation_sha256})
    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(_mark_post_release_attestation_authenticated, _get_live_post_release_attestation_inputs) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPostReleaseAttestationReceipt:
    completion_source_receipt_sha256: str
    release_authorization_sha256: str
    release_intent_sha256: str
    release_plan_sha256: str
    release_readiness_evaluation_sha256: str
    release_plan_config_sha256: str
    release_authorization_config_sha256: str
    original_remote_release_state_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    upstream_merge_transaction_lock_sha256: str
    transaction_lock_sha256: str
    source_tag_marker_sha256: str | None
    source_release_marker_sha256: str | None
    recovery_lock_sha256: str | None
    source_final_remote_release_state_sha256: str
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    remote_observation_sha256: str
    repository: str
    repository_id: str
    release_base_branch: str
    merge_commit_sha: str
    release_version: str
    tag_name: str
    tag_target_sha: str
    release_name: str
    release_body_sha256: str
    release_id: int
    release_node_id_sha256: str
    completion_source: str
    source_action: str
    source_remote_write_performed: bool
    source_completed_at_utc: str
    attested_at_utc: str
    durable_completion_verified: bool = True
    exact_remote_release_verified: bool = True
    exact_tag_target_verified: bool = True
    exact_draft_release_verified: bool = True
    double_observation_matched: bool = True
    post_release_verified: bool = True
    tag_write_authorized: bool = False
    release_mutation_authorized: bool = False
    release_authorized: bool = False
    remote_write_authorized: bool = False
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
    attestation_scope: str = PILOT_EXACT_TASK_POST_RELEASE_ATTESTATION_SCOPE
    authority: str = PILOT_EXACT_TASK_POST_RELEASE_ATTESTATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_POST_RELEASE_ATTESTATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_POST_RELEASE_ATTESTATION_SCHEMA or self.authority != PILOT_EXACT_TASK_POST_RELEASE_ATTESTATION_AUTHORITY or self.attestation_scope != PILOT_EXACT_TASK_POST_RELEASE_ATTESTATION_SCOPE:
            raise PilotExactTaskPostReleaseAttestationError("post-release attestation identity is unsupported")
        for name in ("completion_source_receipt_sha256", "release_authorization_sha256", "release_intent_sha256", "release_plan_sha256", "release_readiness_evaluation_sha256", "release_plan_config_sha256", "release_authorization_config_sha256", "original_remote_release_state_sha256", "execution_nonce_sha256", "development_task_sha256", "candidate_patch_sha256", "pr_intent_sha256", "upstream_merge_transaction_lock_sha256", "transaction_lock_sha256", "source_final_remote_release_state_sha256", "publisher_credential_config_sha256", "publisher_credential_path_sha256", "remote_observation_sha256", "release_body_sha256", "release_node_id_sha256"):
            _hex64(getattr(self, name), name=name)
        for name in ("source_tag_marker_sha256", "source_release_marker_sha256", "recovery_lock_sha256"):
            value = getattr(self, name)
            if value is not None:
                _hex64(value, name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        _hex40(self.tag_target_sha, name="tag_target_sha")
        if self.tag_target_sha != self.merge_commit_sha or self.release_version != f"rsi-{self.merge_commit_sha}" or self.tag_name != f"modelrig-rsi-{self.merge_commit_sha}" or self.release_name != f"ModelRig RSI {self.merge_commit_sha[:12]}" or self.completion_source not in {"transaction", "recovery"} or self.source_action not in {"execute_exact_release", "create_missing_release", "finalize_existing_state"}:
            raise PilotExactTaskPostReleaseAttestationError("post-release deterministic release identity is invalid")
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None or not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None or not isinstance(self.release_base_branch, str) or _BRANCH.fullmatch(self.release_base_branch) is None or not isinstance(self.tag_name, str) or _TAG.fullmatch(self.tag_name) is None or isinstance(self.release_id, bool) or not isinstance(self.release_id, int) or self.release_id < 1 or not isinstance(self.source_remote_write_performed, bool):
            raise PilotExactTaskPostReleaseAttestationError("post-release repository/release projection is invalid")
        if self.completion_source == "transaction":
            if self.source_action != "execute_exact_release" or self.source_remote_write_performed is not True or self.source_tag_marker_sha256 is None or self.source_release_marker_sha256 is None or self.recovery_lock_sha256 is not None:
                raise PilotExactTaskPostReleaseAttestationError("normal post-release source evidence is inconsistent")
        elif self.recovery_lock_sha256 is None or self.source_action == "execute_exact_release":
            raise PilotExactTaskPostReleaseAttestationError("recovered post-release source evidence is inconsistent")
        source_time = _utc(self.source_completed_at_utc, name="source_completed_at_utc")
        attested = _utc(self.attested_at_utc, name="attested_at_utc")
        if attested < source_time:
            raise PilotExactTaskPostReleaseAttestationError("post-release attestation predates release completion")
        required_true = ("durable_completion_verified", "exact_remote_release_verified", "exact_tag_target_verified", "exact_draft_release_verified", "double_observation_matched", "post_release_verified")
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPostReleaseAttestationError("post-release attestation evidence is incomplete")
        forced_false = ("tag_write_authorized", "release_mutation_authorized", "release_authorized", "remote_write_authorized", "merge_authorized", "push_authorized", "pr_mutation_authorized", "review_submission_authorized", "review_thread_mutation_authorized", "ready_for_review_authorized", "reviewer_request_authorized", "deploy_authorized", "production_activation_authorized", "product_pilot_started", "nonce_reusable")
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPostReleaseAttestationError("read-only post-release attestation retains forbidden authority")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def attestation_authenticated(self) -> bool:
        return _get_live_post_release_attestation_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPostReleaseAttestationReceipt":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskPostReleaseAttestationError("post-release attestation fields mismatch")
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _attest_verified_pilot_exact_task_post_release(*, execution_nonce_sha256: str, transaction_ledger_root: Path, recovery_ledger_root: Path, release_authorization_ledger_root: Path, transport: Any, now_provider: Callable[[], str]) -> PilotExactTaskPostReleaseAttestationReceipt:
    key = _hex64(execution_nonce_sha256, name="execution_nonce_sha256")
    try:
        authorization = recovery_boundary._load_durable_authorization(key, release_authorization_ledger_root)
    except Exception as exc:
        raise PilotExactTaskPostReleaseAttestationError("durable exact release authorization reconstruction failed") from exc
    completion = _read_completion(authorization=authorization, transaction_ledger_root=transaction_ledger_root, recovery_ledger_root=recovery_ledger_root)
    if transport is None or not callable(getattr(transport, "observe", None)):
        raise PilotExactTaskPostReleaseAttestationError("read-only post-release GitHub observer is required")
    if getattr(transport, "credential_config_sha256", None) != authorization.publisher_credential_config_sha256 or getattr(transport, "credential_path_sha256", None) != authorization.publisher_credential_path_sha256:
        raise PilotExactTaskPostReleaseAttestationError("post-release observer credential identity differs from ADR-DC-066")
    try:
        first = _normalize_remote_state(value=transport.observe(authorization), authorization=authorization, completion=completion)
        second = _normalize_remote_state(value=transport.observe(authorization), authorization=authorization, completion=completion)
    except PilotExactTaskPostReleaseAttestationError:
        raise
    except Exception as exc:
        raise PilotExactTaskPostReleaseAttestationError("post-release GitHub observation failed") from exc
    if first != second:
        raise PilotExactTaskPostReleaseAttestationError("GitHub post-release state changed between observations")
    observation_sha = hashlib.sha256(_canonical(first).encode("utf-8")).hexdigest()
    attested_at = now_provider()
    if _utc(attested_at, name="attested_at_utc") < _utc(completion.source_completed_at_utc, name="source_completed_at_utc"):
        raise PilotExactTaskPostReleaseAttestationError("system clock moved backwards after release completion")
    receipt = PilotExactTaskPostReleaseAttestationReceipt(completion_source_receipt_sha256=completion.source_receipt_sha256, release_authorization_sha256=authorization.sha256, release_intent_sha256=authorization.release_intent_sha256, release_plan_sha256=authorization.release_plan_sha256, release_readiness_evaluation_sha256=authorization.release_readiness_evaluation_sha256, release_plan_config_sha256=authorization.release_plan_config_sha256, release_authorization_config_sha256=authorization.release_authorization_config_sha256, original_remote_release_state_sha256=authorization.remote_release_state_sha256, execution_nonce_sha256=key, development_task_sha256=authorization.development_task_sha256, candidate_patch_sha256=authorization.candidate_patch_sha256, pr_intent_sha256=authorization.pr_intent_sha256, upstream_merge_transaction_lock_sha256=authorization.transaction_lock_sha256, transaction_lock_sha256=completion.transaction_lock_sha256, source_tag_marker_sha256=completion.tag_marker_sha256, source_release_marker_sha256=completion.release_marker_sha256, recovery_lock_sha256=completion.recovery_lock_sha256, source_final_remote_release_state_sha256=completion.source_final_remote_release_state_sha256, publisher_credential_config_sha256=authorization.publisher_credential_config_sha256, publisher_credential_path_sha256=authorization.publisher_credential_path_sha256, remote_observation_sha256=observation_sha, repository=authorization.repository, repository_id=authorization.repository_id, release_base_branch=authorization.release_base_branch, merge_commit_sha=authorization.merge_commit_sha, release_version=authorization.release_version, tag_name=authorization.tag_name, tag_target_sha=authorization.tag_target_sha, release_name=authorization.release_name, release_body_sha256=authorization.release_body_sha256, release_id=completion.release_id, release_node_id_sha256=completion.release_node_id_sha256, completion_source=completion.source_kind, source_action=completion.source_action, source_remote_write_performed=completion.source_remote_write_performed, source_completed_at_utc=completion.source_completed_at_utc, attested_at_utc=attested_at)
    _mark_post_release_attestation_authenticated(receipt, source_kind=completion.source_kind, source_receipt_sha256=completion.source_receipt_sha256, observation_sha256=observation_sha)
    if receipt.attestation_authenticated is not True:
        raise PilotExactTaskPostReleaseAttestationError("post-release attestation lost live provenance")
    return receipt


def _canonical_roots() -> tuple[Path, Path, Path]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            roots = (tx_boundary._POSIX_LEDGER, recovery_boundary._POSIX_LEDGER, auth_boundary._POSIX_LEDGER)
        elif os.name == "nt":
            roots = (tx_boundary._WINDOWS_LEDGER, recovery_boundary._WINDOWS_LEDGER, auth_boundary._WINDOWS_LEDGER)
        else:
            raise PilotExactTaskPostReleaseAttestationError("post-release attestation is unsupported on this platform")
        return tuple(_require_host_controlled_ledger_root(Path(root)) for root in roots)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskPostReleaseAttestationError("canonical post-release ledgers are not host-admin controlled") from exc


def attest_pilot_exact_task_post_release(execution_nonce_sha256: str) -> PilotExactTaskPostReleaseAttestationReceipt:
    """Read-only attest one exact durable tag+draft-release completion."""
    try:
        tx_root, recovery_root, auth_root = _canonical_roots()
        credential, digest, path = publication_tx_boundary._canonical_credential()
        transport = _GitHubPostReleaseObserver(credential=credential, credential_config_sha256=digest, credential_path=path)
        return _attest_verified_pilot_exact_task_post_release(execution_nonce_sha256=execution_nonce_sha256, transaction_ledger_root=tx_root, recovery_ledger_root=recovery_root, release_authorization_ledger_root=auth_root, transport=transport, now_provider=_now_utc_seconds)
    except PilotExactTaskPostReleaseAttestationError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskPostReleaseAttestationError("host-controlled post-release attestation failed closed") from exc


__all__ = [
    "PILOT_EXACT_TASK_POST_RELEASE_ATTESTATION_SCHEMA",
    "PILOT_EXACT_TASK_POST_RELEASE_ATTESTATION_AUTHORITY",
    "PILOT_EXACT_TASK_POST_RELEASE_ATTESTATION_SCOPE",
    "PilotExactTaskPostReleaseAttestationError",
    "PilotExactTaskPostReleaseAttestationReceipt",
    "attest_pilot_exact_task_post_release",
]
