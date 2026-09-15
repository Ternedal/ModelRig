"""ADR-DC-045 replay-safe admission for one exact human-authorized local commit.

This boundary is allowed to durably reserve the fresh ADR-DC-044 local-commit
nonce exactly once on the canonical host. It fresh-revalidates the live
ADR-DC-042 object identity and frozen workspace before and after the durable
reservation.

It does not consume the authorization for Git writes, write Git objects, move
refs, create a commit, push, mutate a PR, merge, release, deploy, or activate
production. A later separate write-consumption boundary must require the exact
live receipt returned by this transaction.
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
from typing import Any, Callable, Mapping
from ._improvement_pilot_start_consumption_impl import _path_sha256, _safe_ledger_root
from .durable_publication import DurablePublicationError, create_once_file
from . import improvement_pilot_exact_task_local_commit_authorization as authorization_boundary
from .improvement_pilot_exact_task_local_commit_authorization import PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_PROOF_AUTHORITY, PilotExactTaskLocalCommitAuthorizationProof
from . import improvement_pilot_exact_task_local_commit_object_identity as identity_boundary
from .improvement_pilot_exact_task_local_commit_object_identity import PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_IDENTITY_AUTHORITY, PilotExactTaskLocalCommitObjectIdentity
from .tier_a_command_receipt import GitWorkspaceSnapshot, _GitWorkspaceEvidence
from .trusted_git_runtime_model import _has_linkish_component
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ADMISSION_RECEIPT_SCHEMA = 'kaliv-rsi-dc-l16-exact-task-local-commit-authorization-admission-receipt/v1'
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ADMISSION_AUTHORITY = 'host-admitted-one-dc-l16-exact-local-commit-authorization-only'
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ADMISSION_LEDGER_SCOPE = 'canonical-host-local-v1'
_MAX_ARTIFACT_BYTES = 1024 * 1024
_HEX40 = re.compile('^[0-9a-f]{40}$')
_HEX64 = re.compile('^[0-9a-f]{64}$')
_ID = re.compile('^[A-Z][A-Z0-9_-]{2,63}$')
_REPOSITORY = re.compile('^[^/\\s]+/[^/\\s]+$')
_UTC = re.compile('^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z$')

class PilotExactTaskLocalCommitAuthorizationAdmissionError(ValueError):
    """The exact local-commit authorization cannot be admitted safely."""

def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError('local-commit authorization admission is not canonical JSON') from exc

def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == '0' * 40:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError(f'{name} is invalid')
    return value

def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == '0' * 64:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError(f'{name} is invalid')
    return value

def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError(f'{name} must be canonical UTC seconds')
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError(f'{name} is invalid') from exc

def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime('%Y-%m-%dT%H:%M:%SZ')

def _read_bound_file(path: Path) -> bytes | None:
    candidate = Path(path)
    if not candidate.is_absolute() or _has_linkish_component(candidate):
        return None
    try:
        payload = candidate.read_bytes()
    except OSError:
        return None
    if not payload or len(payload) > _MAX_ARTIFACT_BYTES:
        return None
    return payload

def _require_verified_proof(value: Any) -> PilotExactTaskLocalCommitAuthorizationProof:
    if type(value) is not PilotExactTaskLocalCommitAuthorizationProof:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError('exact ADR-DC-044 human local-commit authorization proof is required')
    try:
        replayed = PilotExactTaskLocalCommitAuthorizationProof.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError('ADR-DC-044 proof replay validation failed') from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError('ADR-DC-044 proof replay identity mismatch')
    if value.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_PROOF_AUTHORITY or value.human_local_commit_authorization_verified is not True or value.one_shot_local_commit_required is not True or (value.local_commit_authorization_consumed is not False) or (value.git_object_write_authorized is not False) or (value.local_ref_update_authorized is not False) or (value.local_commit_authorized is not False) or (value.local_commit_created is not False) or (value.remote_write_authorized is not False) or (value.push_authorized is not False) or (value.pr_mutation_authorized is not False) or (value.merge_authorized is not False) or (value.release_authorized is not False) or (value.deploy_authorized is not False) or (value.production_activation_authorized is not False):
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError('admission requires one verified inert ADR-DC-044 proof')
    return value

def _stable_proof_mapping(proof: PilotExactTaskLocalCommitAuthorizationProof) -> dict[str, Any]:
    exact = _require_verified_proof(proof)
    data = exact.to_dict()
    data.pop('verified_at_utc', None)
    return data

def require_fresh_local_commit_authorization_proof_identity(supplied: PilotExactTaskLocalCommitAuthorizationProof, fresh: PilotExactTaskLocalCommitAuthorizationProof) -> None:
    if _stable_proof_mapping(supplied) != _stable_proof_mapping(fresh):
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError('fresh ADR-DC-044 proof identity does not match supplied proof')

def _require_live_object_identity_for_proof(proof: PilotExactTaskLocalCommitAuthorizationProof, object_identity: Any) -> tuple[PilotExactTaskLocalCommitObjectIdentity, Mapping[str, Any]]:
    exact_proof = _require_verified_proof(proof)
    if type(object_identity) is not PilotExactTaskLocalCommitObjectIdentity:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError('exact live ADR-DC-042 object identity is required')
    try:
        replayed = PilotExactTaskLocalCommitObjectIdentity.from_mapping(object_identity.to_dict())
    except Exception as exc:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError('ADR-DC-042 identity replay validation failed') from exc
    if replayed != object_identity or replayed.sha256 != object_identity.sha256:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError('ADR-DC-042 identity replay mismatch')
    if object_identity.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_IDENTITY_AUTHORITY or object_identity.identity_authenticated is not True or object_identity.git_object_write_authorized is not False or (object_identity.local_ref_update_authorized is not False) or (object_identity.local_commit_authorized is not False) or (object_identity.local_commit_created is not False) or (object_identity.remote_write_authorized is not False) or (object_identity.push_authorized is not False) or (object_identity.pr_mutation_authorized is not False) or (object_identity.merge_authorized is not False) or (object_identity.release_authorized is not False) or (object_identity.deploy_authorized is not False) or (object_identity.production_activation_authorized is not False):
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError('admission requires one live inert ADR-DC-042 identity')
    inputs = identity_boundary._get_live_local_commit_object_identity_inputs(object_identity)
    if inputs is None:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError('ADR-DC-042 live identity inputs are unavailable')
    requirements = exact_proof.authorization.authorization_requirements
    if object_identity.sha256 != exact_proof.local_commit_object_identity_sha256 or object_identity.sha256 != requirements.local_commit_object_identity_sha256 or object_identity.local_commit_plan_sha256 != requirements.local_commit_plan_sha256 or (object_identity.development_task_sha256 != requirements.development_task_sha256) or (object_identity.task_id != requirements.task_id) or (object_identity.repository != requirements.repository) or (object_identity.base_sha != requirements.base_sha) or (object_identity.root_tree_sha != requirements.root_tree_sha) or (object_identity.predicted_commit_sha != requirements.predicted_commit_sha) or (object_identity.commit_payload_sha256 != requirements.commit_payload_sha256) or (object_identity.index_manifest_sha256 != requirements.index_manifest_sha256) or (object_identity.commit_subject_sha256 != requirements.commit_subject_sha256):
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError('ADR-DC-044 proof is not bound to the exact live ADR-DC-042 identity')
    return (object_identity, inputs)

def _fresh_workspace_snapshot(inputs: Mapping[str, Any]) -> GitWorkspaceSnapshot:
    try:
        return _GitWorkspaceEvidence(Path(inputs['workspace_root']), inputs['task'], inputs['git_runner']).snapshot()
    except Exception as exc:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError('fresh local-commit admission workspace snapshot failed') from exc

def _require_snapshot_matches_identity(identity: PilotExactTaskLocalCommitObjectIdentity, inputs: Mapping[str, Any], snapshot: GitWorkspaceSnapshot) -> None:
    plan = inputs.get('local_commit_plan')
    planned = getattr(plan, 'post_execution_workspace_snapshot', None)
    if type(planned) is not GitWorkspaceSnapshot or snapshot != planned or snapshot.sha256 != identity.post_execution_workspace_snapshot_sha256 or (snapshot.head_sha != identity.base_sha) or (snapshot.staged_patch_sha256 != identity.candidate_patch_sha256) or (snapshot.staged_patch_bytes != identity.candidate_patch_bytes) or (snapshot.staged_patch_bytes <= 0) or (snapshot.unstaged_patch_bytes != 0) or (snapshot.untracked_path_count != 0):
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError('workspace no longer matches the exact ADR-DC-042 identity')

def _revalidate_object_identity(identity: PilotExactTaskLocalCommitObjectIdentity, inputs: Mapping[str, Any]) -> None:
    try:
        object_format = identity_boundary._read_object_format(inputs)
        index_payload = identity_boundary._read_index_manifest(inputs)
        entries = identity_boundary._parse_index_manifest(index_payload)
        root_tree_sha = identity_boundary._root_tree_sha(entries)
        commit_payload = identity_boundary._commit_payload(tree_sha=root_tree_sha, parent_sha=identity.base_sha, subject=identity.commit_subject, epoch_seconds=identity.commit_epoch_seconds)
        predicted_commit_sha = identity_boundary._git_sha1('commit', commit_payload)
    except Exception as exc:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError('fresh ADR-DC-042 object identity revalidation failed') from exc
    if object_format != identity.object_format or hashlib.sha256(index_payload).hexdigest() != identity.index_manifest_sha256 or len(entries) != identity.index_entry_count or (root_tree_sha != identity.root_tree_sha) or (hashlib.sha256(commit_payload).hexdigest() != identity.commit_payload_sha256) or (predicted_commit_sha != identity.predicted_commit_sha):
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError('fresh Git object identity no longer matches ADR-DC-042')

def _admission_key(proof: PilotExactTaskLocalCommitAuthorizationProof) -> str:
    exact = _require_verified_proof(proof)
    return _hex64(exact.local_commit_nonce_sha256, name='local_commit_nonce_sha256')

def _transaction_registry():
    records: dict[int, tuple[int, str, Path, bytes, Path, bytes, weakref.ReferenceType[Any], weakref.ReferenceType[Any]]] = {}
    def mark(receipt: Any, identity: PilotExactTaskLocalCommitObjectIdentity, *, lock_path: Path, lock_payload: bytes, receipt_path: Path, receipt_payload: bytes) -> None:
        key = id(receipt)
        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)
        records[key] = (os.getpid(), receipt.sha256, lock_path, lock_payload, receipt_path, receipt_payload, weakref.ref(receipt, cleanup), weakref.ref(identity))
    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, lock_path, lock_payload, receipt_path, receipt_payload, receipt_ref, identity_ref = entry
        identity = identity_ref()
        if pid != os.getpid() or receipt_ref() is not receipt or identity is None or (identity.identity_authenticated is not True):
            return None
        try:
            if receipt.sha256 != digest:
                return None
        except (AttributeError, TypeError, ValueError):
            return None
        if _read_bound_file(lock_path) != lock_payload or _read_bound_file(receipt_path) != receipt_payload:
            return None
        return {'object_identity': identity}
    if hasattr(os, 'register_at_fork'):
        os.register_at_fork(after_in_child=records.clear)
    return (mark, get)
_mark_admission_authenticated, _get_live_local_commit_authorization_admission_inputs = _transaction_registry()

@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskLocalCommitAuthorizationAdmissionReceipt:
    ledger_root_path_sha256: str
    admission_key_sha256: str
    authorization_proof: PilotExactTaskLocalCommitAuthorizationProof
    authorization_proof_sha256: str
    authorization_sha256: str
    authorization_signature_sha256: str
    authorization_requirements_sha256: str
    requirements_key_sha256: str
    local_commit_object_identity_sha256: str
    local_commit_plan_sha256: str
    development_task_sha256: str
    task_id: str
    repository: str
    base_sha: str
    root_tree_sha: str
    predicted_commit_sha: str
    commit_payload_sha256: str
    index_manifest_sha256: str
    index_entry_count: int
    commit_subject_sha256: str
    local_commit_nonce_sha256: str
    fresh_verified_at_utc: str
    admitted_at_utc: str
    pre_admission_workspace_snapshot_sha256: str
    post_lock_workspace_snapshot_sha256: str
    object_format: str
    ledger_scope: str = PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ADMISSION_LEDGER_SCOPE
    host_replay_guard_committed: bool = True
    human_local_commit_authorization_verified: bool = True
    local_commit_authorization_admitted: bool = True
    local_commit_authorization_consumed: bool = False
    one_shot_local_commit_required: bool = True
    exact_object_identity_revalidated: bool = True
    fresh_workspace_snapshot_matched: bool = True
    git_object_write_authorized: bool = False
    local_ref_update_authorized: bool = False
    local_commit_authorized: bool = False
    local_commit_created: bool = False
    integration_ready: bool = False
    product_pilot_started: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ADMISSION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ADMISSION_RECEIPT_SCHEMA
    def __post_init__(self) -> None:
        proof = _require_verified_proof(self.authorization_proof)
        if self.schema != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ADMISSION_RECEIPT_SCHEMA or self.ledger_scope != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ADMISSION_LEDGER_SCOPE or self.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ADMISSION_AUTHORITY:
            raise PilotExactTaskLocalCommitAuthorizationAdmissionError('local-commit admission receipt schema/scope/authority is unsupported')
        for name in ('ledger_root_path_sha256', 'admission_key_sha256', 'authorization_proof_sha256', 'authorization_sha256', 'authorization_signature_sha256', 'authorization_requirements_sha256', 'requirements_key_sha256', 'local_commit_object_identity_sha256', 'local_commit_plan_sha256', 'development_task_sha256', 'commit_payload_sha256', 'index_manifest_sha256', 'commit_subject_sha256', 'local_commit_nonce_sha256', 'pre_admission_workspace_snapshot_sha256', 'post_lock_workspace_snapshot_sha256'):
            _hex64(getattr(self, name), name=name)
        for name in ('base_sha', 'root_tree_sha', 'predicted_commit_sha'):
            _hex40(getattr(self, name), name=name)
        if not isinstance(self.task_id, str) or _ID.fullmatch(self.task_id) is None:
            raise PilotExactTaskLocalCommitAuthorizationAdmissionError('task_id is invalid')
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PilotExactTaskLocalCommitAuthorizationAdmissionError('repository is invalid')
        if isinstance(self.index_entry_count, bool) or not isinstance(self.index_entry_count, int) or self.index_entry_count < 1 or (self.index_entry_count > 1000000):
            raise PilotExactTaskLocalCommitAuthorizationAdmissionError('index_entry_count is invalid')
        if self.object_format != 'sha1':
            raise PilotExactTaskLocalCommitAuthorizationAdmissionError('object_format is unsupported')
        fresh_verified = _utc(self.fresh_verified_at_utc, name='fresh_verified_at_utc')
        admitted = _utc(self.admitted_at_utc, name='admitted_at_utc')
        if admitted < fresh_verified:
            raise PilotExactTaskLocalCommitAuthorizationAdmissionError('admission predates fresh ADR-DC-044 verification')
        requirements = proof.authorization.authorization_requirements
        expected = {'authorization_proof_sha256': proof.sha256, 'authorization_sha256': proof.authorization_sha256, 'authorization_signature_sha256': proof.signature_sha256, 'authorization_requirements_sha256': proof.authorization_requirements_sha256, 'requirements_key_sha256': proof.requirements_key_sha256, 'local_commit_object_identity_sha256': proof.local_commit_object_identity_sha256, 'local_commit_plan_sha256': requirements.local_commit_plan_sha256, 'development_task_sha256': requirements.development_task_sha256, 'task_id': requirements.task_id, 'repository': requirements.repository, 'base_sha': requirements.base_sha, 'root_tree_sha': requirements.root_tree_sha, 'predicted_commit_sha': proof.predicted_commit_sha, 'commit_payload_sha256': requirements.commit_payload_sha256, 'index_manifest_sha256': requirements.index_manifest_sha256, 'index_entry_count': requirements.index_entry_count, 'commit_subject_sha256': requirements.commit_subject_sha256, 'local_commit_nonce_sha256': proof.local_commit_nonce_sha256, 'object_format': requirements.object_format}
        mismatch = next((name for name, value in expected.items() if getattr(self, name) != value), None)
        if mismatch is not None:
            raise PilotExactTaskLocalCommitAuthorizationAdmissionError(f'local-commit admission receipt binding mismatch: {mismatch}')
        if self.admission_key_sha256 != self.local_commit_nonce_sha256:
            raise PilotExactTaskLocalCommitAuthorizationAdmissionError('admission key must equal the signed local-commit nonce')
        if self.pre_admission_workspace_snapshot_sha256 != requirements.post_execution_workspace_snapshot_sha256 or self.post_lock_workspace_snapshot_sha256 != requirements.post_execution_workspace_snapshot_sha256:
            raise PilotExactTaskLocalCommitAuthorizationAdmissionError('admission workspace snapshot binding mismatch')
        required_true = ('host_replay_guard_committed', 'human_local_commit_authorization_verified', 'local_commit_authorization_admitted', 'one_shot_local_commit_required', 'exact_object_identity_revalidated', 'fresh_workspace_snapshot_matched')
        forced_false = ('local_commit_authorization_consumed', 'git_object_write_authorized', 'local_ref_update_authorized', 'local_commit_authorized', 'local_commit_created', 'integration_ready', 'product_pilot_started', 'remote_write_authorized', 'push_authorized', 'pr_mutation_authorized', 'merge_authorized', 'release_authorized', 'deploy_authorized', 'production_activation_authorized')
        if any((getattr(self, name) is not True for name in required_true)):
            raise PilotExactTaskLocalCommitAuthorizationAdmissionError('required admission evidence is not satisfied')
        if any((getattr(self, name) is not False for name in forced_false)):
            raise PilotExactTaskLocalCommitAuthorizationAdmissionError('admission receipt cannot grant Git write/publication authority')
    @classmethod
    def from_mapping(cls, value: Any) -> 'PilotExactTaskLocalCommitAuthorizationAdmissionReceipt':
        if not isinstance(value, Mapping):
            raise PilotExactTaskLocalCommitAuthorizationAdmissionError('admission receipt must be an object')
        if set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskLocalCommitAuthorizationAdmissionError('admission receipt fields mismatch')
        data = dict(value)
        proof = data.get('authorization_proof')
        if not isinstance(proof, Mapping):
            raise PilotExactTaskLocalCommitAuthorizationAdmissionError('authorization_proof must be an object')
        data['authorization_proof'] = PilotExactTaskLocalCommitAuthorizationProof.from_mapping(proof)
        return cls(**data)
    def to_dict(self) -> dict[str, Any]:
        return {name: self.authorization_proof.to_dict() if name == 'authorization_proof' else getattr(self, name) for name in self.__dataclass_fields__}
    def canonical_json(self) -> str:
        return _canonical(self.to_dict())
    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode('utf-8')).hexdigest()
    @property
    def admission_authenticated(self) -> bool:
        return _get_live_local_commit_authorization_admission_inputs(self) is not None

class _PilotExactTaskLocalCommitAuthorizationAdmissionLedger:
    """Create-once host-local replay ledger keyed by local-commit nonce."""
    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)
    def _lock_path(self, key: str) -> Path:
        return self.root / f"{_hex64(key, name='admission key')}.lock.json"
    def _receipt_path(self, key: str) -> Path:
        return self.root / f"{_hex64(key, name='admission key')}.receipt.json"
    def reserve(self, *, key: str, proof: PilotExactTaskLocalCommitAuthorizationProof, identity: PilotExactTaskLocalCommitObjectIdentity) -> tuple[Path, bytes]:
        lock = self._lock_path(key)
        payload = _canonical({'schema': 'kaliv-rsi-dc-l16-exact-task-local-commit-authorization-admission-lock/v1', 'ledger_scope': PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ADMISSION_LEDGER_SCOPE, 'ledger_root_path_sha256': self.root_sha256, 'admission_key_sha256': key, 'authorization_proof_sha256': proof.sha256, 'authorization_sha256': proof.authorization_sha256, 'authorization_signature_sha256': proof.signature_sha256, 'authorization_requirements_sha256': proof.authorization_requirements_sha256, 'requirements_key_sha256': proof.requirements_key_sha256, 'local_commit_object_identity_sha256': identity.sha256, 'predicted_commit_sha': identity.predicted_commit_sha, 'root_tree_sha': identity.root_tree_sha, 'index_manifest_sha256': identity.index_manifest_sha256}).encode('utf-8')
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskLocalCommitAuthorizationAdmissionError('local-commit authorization nonce was already admitted or could not be durably reserved') from exc
        if _read_bound_file(lock) != payload:
            raise PilotExactTaskLocalCommitAuthorizationAdmissionError('local-commit authorization admission lock read-back mismatch')
        return (lock, payload)
    def publish(self, *, key: str, receipt: PilotExactTaskLocalCommitAuthorizationAdmissionReceipt) -> tuple[Path, bytes]:
        path = self._receipt_path(key)
        payload = receipt.canonical_json().encode('utf-8')
        if not payload or len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskLocalCommitAuthorizationAdmissionError('local-commit admission receipt exceeds byte bound')
        try:
            create_once_file(path, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskLocalCommitAuthorizationAdmissionError('local-commit admission receipt publication failed closed') from exc
        if _read_bound_file(path) != payload:
            raise PilotExactTaskLocalCommitAuthorizationAdmissionError('local-commit admission receipt read-back mismatch')
        parsed = PilotExactTaskLocalCommitAuthorizationAdmissionReceipt.from_mapping(json.loads(payload.decode('utf-8', errors='strict')))
        if parsed != receipt or parsed.sha256 != receipt.sha256:
            raise PilotExactTaskLocalCommitAuthorizationAdmissionError('published local-commit admission receipt identity mismatch')
        return (path, payload)

def _admit_verified_pilot_exact_task_local_commit_authorization(*, supplied_proof: PilotExactTaskLocalCommitAuthorizationProof, fresh_proof: PilotExactTaskLocalCommitAuthorizationProof, object_identity: PilotExactTaskLocalCommitObjectIdentity, ledger: _PilotExactTaskLocalCommitAuthorizationAdmissionLedger, now_provider: Callable[[], str]) -> PilotExactTaskLocalCommitAuthorizationAdmissionReceipt:
    supplied = _require_verified_proof(supplied_proof)
    fresh = _require_verified_proof(fresh_proof)
    require_fresh_local_commit_authorization_proof_identity(supplied, fresh)
    identity, inputs = _require_live_object_identity_for_proof(supplied, object_identity)
    pre = _fresh_workspace_snapshot(inputs)
    _require_snapshot_matches_identity(identity, inputs, pre)
    _revalidate_object_identity(identity, inputs)
    post_evidence = _fresh_workspace_snapshot(inputs)
    _require_snapshot_matches_identity(identity, inputs, post_evidence)
    if post_evidence != pre or post_evidence.sha256 != pre.sha256:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError('workspace changed during fresh local-commit identity revalidation')
    first_now = now_provider()
    first_instant = _utc(first_now, name='local-commit admission time')
    fresh_instant = _utc(fresh.verified_at_utc, name='fresh proof verified_at_utc')
    if first_instant < fresh_instant:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError('local-commit admission predates fresh human proof verification')
    if first_instant >= _utc(supplied.authorization.expires_at_utc, name='authorization expires_at_utc'):
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError('human local-commit authorization expired before admission')
    key = _admission_key(supplied)
    lock_path, lock_payload = ledger.reserve(key=key, proof=supplied, identity=identity)
    post_lock = _fresh_workspace_snapshot(inputs)
    _require_snapshot_matches_identity(identity, inputs, post_lock)
    if post_lock != pre or post_lock.sha256 != pre.sha256:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError('workspace changed after durable local-commit nonce admission; nonce remains burned')
    admitted_at = now_provider()
    if _utc(admitted_at, name='admitted_at_utc') < first_instant:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError('local-commit admission clock moved backwards after durable nonce reservation')
    if _utc(admitted_at, name='admitted_at_utc') >= _utc(supplied.authorization.expires_at_utc, name='authorization expires_at_utc'):
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError('human local-commit authorization expired after durable nonce reservation; nonce remains burned')
    requirements = supplied.authorization.authorization_requirements
    receipt = PilotExactTaskLocalCommitAuthorizationAdmissionReceipt(ledger_root_path_sha256=ledger.root_sha256, admission_key_sha256=key, authorization_proof=supplied, authorization_proof_sha256=supplied.sha256, authorization_sha256=supplied.authorization_sha256, authorization_signature_sha256=supplied.signature_sha256, authorization_requirements_sha256=supplied.authorization_requirements_sha256, requirements_key_sha256=supplied.requirements_key_sha256, local_commit_object_identity_sha256=identity.sha256, local_commit_plan_sha256=identity.local_commit_plan_sha256, development_task_sha256=identity.development_task_sha256, task_id=identity.task_id, repository=identity.repository, base_sha=identity.base_sha, root_tree_sha=identity.root_tree_sha, predicted_commit_sha=identity.predicted_commit_sha, commit_payload_sha256=identity.commit_payload_sha256, index_manifest_sha256=identity.index_manifest_sha256, index_entry_count=identity.index_entry_count, commit_subject_sha256=identity.commit_subject_sha256, local_commit_nonce_sha256=supplied.local_commit_nonce_sha256, fresh_verified_at_utc=fresh.verified_at_utc, admitted_at_utc=admitted_at, pre_admission_workspace_snapshot_sha256=pre.sha256, post_lock_workspace_snapshot_sha256=post_lock.sha256, object_format=requirements.object_format)
    receipt_path, receipt_payload = ledger.publish(key=key, receipt=receipt)
    _mark_admission_authenticated(receipt, identity, lock_path=lock_path, lock_payload=lock_payload, receipt_path=receipt_path, receipt_payload=receipt_payload)
    if receipt.admission_authenticated is not True:
        raise PilotExactTaskLocalCommitAuthorizationAdmissionError('live local-commit admission provenance was not established')
    return receipt

def admit_pilot_exact_task_local_commit_authorization(*, authorization_proof: PilotExactTaskLocalCommitAuthorizationProof, authorization_signature: Any, object_identity: PilotExactTaskLocalCommitObjectIdentity) -> PilotExactTaskLocalCommitAuthorizationAdmissionReceipt:
    raise PilotExactTaskLocalCommitAuthorizationAdmissionError('production local-commit authorization admission boundary is not installed')
__all__ = ['PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ADMISSION_RECEIPT_SCHEMA', 'PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ADMISSION_AUTHORITY', 'PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ADMISSION_LEDGER_SCOPE', 'PilotExactTaskLocalCommitAuthorizationAdmissionError', 'PilotExactTaskLocalCommitAuthorizationAdmissionReceipt', 'admit_pilot_exact_task_local_commit_authorization']
