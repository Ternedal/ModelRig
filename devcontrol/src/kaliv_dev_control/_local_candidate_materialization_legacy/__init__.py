"""Static validation and evidence support for DC-L13 local materialization.

This internal package is projected from the locked historical implementation,
but deliberately excludes its executable Git runner, legacy materialize/verify
gates and all retained v1 compatibility imports. It supplies only deterministic
value objects, canonicalization helpers and repository/object inspection helpers
to the modern TrustedGitRuntime-backed facade.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, TypeVar

from ..contract import DevelopmentTask, MergeAuthority
from ..publisher_authorization import PublisherAuthorizationError
from ..publisher_authorization_chain_v2 import (
    PublisherAuthorizationVerifierV2 as PublisherAuthorizationVerifier,
    PublisherPreflightReceiptV2 as PublisherPreflightReceipt,
)
from ..publisher_dry_run import PublisherRequestVerifier
from ..semantic_review import SemanticReviewVerifier

LOCAL_CANDIDATE_MATERIALIZATION_RECEIPT_SCHEMA = 'kaliv-development-local-candidate-materialization-receipt/v1'

_LOCAL_GIT_EVIDENCE_SCHEMA = 'kaliv-development-local-git-evidence/v1'

_LOCAL_SOURCE_EVIDENCE_SCHEMA = 'kaliv-development-local-source-repository-evidence/v1'

_LOCAL_CANDIDATE_EVIDENCE_SCHEMA = 'kaliv-development-local-candidate-commit-evidence/v1'

_MATERIALIZATION_POLICY_DOMAIN = b'kaliv-local-candidate-materialization-policy/v1\x00'

_TRANSACTION_DOMAIN = b'kaliv-local-candidate-materialization-transaction/v1\x00'

_HEX40 = re.compile('^[0-9a-f]{40}$')

_HEX64 = re.compile('^[0-9a-f]{64}$')

_IDENTIFIER = re.compile('^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$')

_ACTOR_ID = re.compile('^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$')

_UTC_TIMESTAMP = re.compile('^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$')

_MAX_ARTIFACT_BYTES = 128 * 1024 * 1024

_MAX_GIT_OUTPUT_BYTES = 64 * 1024 * 1024

_MAX_OBJECT_BYTES = 32 * 1024 * 1024

_MAX_GIT_EXECUTABLE_BYTES = 512 * 1024 * 1024


class _GitEvidenceRunner(Protocol):
    """Minimal structural contract consumed by static Git evidence helpers."""

    _transaction_root: Path

    def run(
        self,
        args: tuple[str, ...],
        *,
        cwd: Path,
        maximum: int = _MAX_GIT_OUTPUT_BYTES,
        expected_codes: tuple[int, ...] = (0,),
    ) -> bytes: ...

LOCAL_CANDIDATE_MATERIALIZATION_POLICY = ('Accept only one complete Slice 10K preflight receipt that still verifies against the exact task, trusted publisher, trusted authorization issuer, trusted semantic reviewer and current execution authority.', 'Require one absolute link-free local source repository containing the exact authorized base commit without replacement objects or shallow history.', 'Require one absolute regular link-free Git executable whose complete bytes match an operator-supplied SHA-256.', 'Create one new isolated bare SHA-1 repository under an absolute link-free materialization root and never reuse an existing transaction path.', 'Import the exact base only through the local file protocol, apply the exact authenticated binary patch to an isolated index, and reproduce the exact patch bytes from the resulting tree.', 'Use deterministic publisher-bound author and committer metadata plus the exact Slice 10J commit message, then bind the parent, tree, commit object and proposed branch ref.', 'Keep remotes, network writes, pushes, pull-request writes, reviewer requests, ready-for-review, merge, release, settings, deployment and runtime activation absent.', 'Fail closed on any task, authority, signature, lease-time, source-state, Git-tool, patch, object, ref, canonical-byte or local-only-boundary mismatch.')

class LocalCandidateMaterializationError(ValueError):
    """Local Git materialization failed or produced unauthenticated evidence."""

def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def _strict(value: Any, *, name: str, fields: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise LocalCandidateMaterializationError(f'{name} fields mismatch')
    return value

def _clean_text(value: Any, *, name: str, maximum: int, one_line: bool=False) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or ('\x00' in value) or (len(value.encode('utf-8')) > maximum) or (one_line and ('\n' in value or '\r' in value)):
        raise LocalCandidateMaterializationError(f'{name} is invalid')
    return value

def _hex(value: Any, *, name: str, pattern: re.Pattern[str]=_HEX64) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise LocalCandidateMaterializationError(f'{name} is invalid')
    return value

def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise LocalCandidateMaterializationError(f'{name} is invalid')
    return value

def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR_ID.fullmatch(value) is None:
        raise LocalCandidateMaterializationError(f'{name} is invalid')
    return value

def _integer(value: Any, *, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or (not low <= value <= high):
        raise LocalCandidateMaterializationError(f'{name} is invalid')
    return value

def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC_TIMESTAMP.fullmatch(value) is None:
        raise LocalCandidateMaterializationError(f'{name} must be canonical UTC seconds')
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise LocalCandidateMaterializationError(f'{name} is invalid') from exc

def _has_linkish_component(path: Path) -> bool:
    current = path.absolute()
    while True:
        if current.is_symlink():
            return True
        is_junction = getattr(current, 'is_junction', None)
        if is_junction is not None and is_junction():
            return True
        if current.parent == current:
            return False
        current = current.parent

def _existing_link_free_directory(path: Path, *, name: str) -> Path:
    raw = Path(path)
    if not raw.is_absolute():
        raise LocalCandidateMaterializationError(f'{name} must be absolute')
    resolved = Path(os.path.realpath(os.path.abspath(raw)))
    if not resolved.is_dir() or _has_linkish_component(resolved):
        raise LocalCandidateMaterializationError(f'{name} must be an existing link-free directory')
    return resolved

def local_candidate_materialization_policy_sha256() -> str:
    payload = json.dumps(list(LOCAL_CANDIDATE_MATERIALIZATION_POLICY), ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return _sha256_bytes(_MATERIALIZATION_POLICY_DOMAIN + payload)

def _transaction_id(preflight_sha256: str) -> str:
    digest = _sha256_bytes(_TRANSACTION_DOMAIN + _hex(preflight_sha256, name='preflight hash').encode('ascii'))
    return f'candidate-{digest[:32]}'

def _commit_message(task: DevelopmentTask) -> str:
    goal = ' '.join(task.goal.split())
    message = f'devcontrol({task.task_id.lower()}): {goal}'
    if len(message.encode('utf-8')) > 240:
        message = f'devcontrol({task.task_id.lower()}): apply authenticated candidate'
    return _clean_text(message, name='candidate commit message', maximum=240, one_line=True)

def _actor_email(actor_id: str) -> str:
    actor = _actor(actor_id, name='publisher actor')
    local = re.sub('[^A-Za-z0-9._-]', '-', actor).strip('.-').lower()
    if not local:
        raise LocalCandidateMaterializationError('publisher actor cannot produce a commit email')
    local = local[:64]
    return f'{local}@publisher.modelrig.invalid'

def _author_name(actor_id: str) -> str:
    actor = _actor(actor_id, name='publisher actor')
    return _clean_text(f'Kaliv Publisher {actor}', name='candidate author name', maximum=160, one_line=True)

def _git_timestamp(utc_text: str) -> str:
    instant = _utc(utc_text, name='candidate commit time')
    return f'{int(instant.timestamp())} +0000'

def _git_object_id(kind: str, payload: bytes) -> str:
    header = f'{kind} {len(payload)}\x00'.encode('ascii')
    return hashlib.sha1(header + payload, usedforsecurity=False).hexdigest()

def _expected_commit_payload(*, tree_sha: str, parent_sha: str, author_name: str, author_email: str, author_git_timestamp: str, committer_name: str, committer_email: str, committer_git_timestamp: str, message: str) -> bytes:
    return f'tree {tree_sha}\nparent {parent_sha}\nauthor {author_name} <{author_email}> {author_git_timestamp}\ncommitter {committer_name} <{committer_email}> {committer_git_timestamp}\n\n{message}\n'.encode('utf-8')

@dataclass(frozen=True, slots=True)
class LocalGitEvidence:
    executable_sha256: str
    executable_bytes: int
    executable_basename: str
    version: str
    object_format: str = 'sha1'
    schema: str = _LOCAL_GIT_EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != _LOCAL_GIT_EVIDENCE_SCHEMA:
            raise LocalCandidateMaterializationError('unsupported local Git evidence schema')
        _hex(self.executable_sha256, name='local Git executable hash')
        _integer(self.executable_bytes, name='local Git executable bytes', low=1, high=_MAX_GIT_EXECUTABLE_BYTES)
        _clean_text(self.executable_basename, name='local Git executable basename', maximum=255, one_line=True)
        _clean_text(self.version, name='local Git version', maximum=512, one_line=True)
        if self.object_format != 'sha1':
            raise LocalCandidateMaterializationError('local Git object format must remain sha1')

    @classmethod
    def from_mapping(cls, value: Any) -> 'LocalGitEvidence':
        data = _strict(value, name='local Git evidence', fields={'schema', 'executable_sha256', 'executable_bytes', 'executable_basename', 'version', 'object_format'})
        return cls(schema=data['schema'], executable_sha256=data['executable_sha256'], executable_bytes=data['executable_bytes'], executable_basename=data['executable_basename'], version=data['version'], object_format=data['object_format'])

    def to_dict(self) -> dict[str, Any]:
        return {'schema': self.schema, 'executable_sha256': self.executable_sha256, 'executable_bytes': self.executable_bytes, 'executable_basename': self.executable_basename, 'version': self.version, 'object_format': self.object_format}

@dataclass(frozen=True, slots=True)
class LocalSourceRepositoryEvidence:
    path_sha256: str
    repository_kind: str
    state_sha256: str
    state_bytes: int
    base_commit_sha: str
    base_commit_object_sha256: str
    base_commit_object_bytes: int
    base_tree_sha: str
    base_tree_object_sha256: str
    base_tree_object_bytes: int
    source_mutated: bool = False
    object_format: str = 'sha1'
    shallow: bool = False
    schema: str = _LOCAL_SOURCE_EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != _LOCAL_SOURCE_EVIDENCE_SCHEMA:
            raise LocalCandidateMaterializationError('unsupported local source evidence schema')
        for name, value in (('source path hash', self.path_sha256), ('source state hash', self.state_sha256), ('base commit object hash', self.base_commit_object_sha256), ('base tree object hash', self.base_tree_object_sha256)):
            _hex(value, name=name)
        _hex(self.base_commit_sha, name='source base commit SHA', pattern=_HEX40)
        _hex(self.base_tree_sha, name='source base tree SHA', pattern=_HEX40)
        _integer(self.state_bytes, name='source state bytes', low=1, high=_MAX_OBJECT_BYTES)
        _integer(self.base_commit_object_bytes, name='base commit object bytes', low=1, high=_MAX_OBJECT_BYTES)
        _integer(self.base_tree_object_bytes, name='base tree object bytes', low=0, high=_MAX_OBJECT_BYTES)
        if self.repository_kind not in {'bare', 'worktree'}:
            raise LocalCandidateMaterializationError('source repository kind is unsupported')
        if self.object_format != 'sha1' or self.shallow is not False:
            raise LocalCandidateMaterializationError('source repository object boundary is unsupported')
        if self.source_mutated is not False:
            raise LocalCandidateMaterializationError('source repository evidence claims mutation')

    @classmethod
    def from_mapping(cls, value: Any) -> 'LocalSourceRepositoryEvidence':
        data = _strict(value, name='local source repository evidence', fields={'schema', 'path_sha256', 'repository_kind', 'state_sha256', 'state_bytes', 'base_commit_sha', 'base_commit_object_sha256', 'base_commit_object_bytes', 'base_tree_sha', 'base_tree_object_sha256', 'base_tree_object_bytes', 'source_mutated', 'object_format', 'shallow'})
        return cls(schema=data['schema'], path_sha256=data['path_sha256'], repository_kind=data['repository_kind'], state_sha256=data['state_sha256'], state_bytes=data['state_bytes'], base_commit_sha=data['base_commit_sha'], base_commit_object_sha256=data['base_commit_object_sha256'], base_commit_object_bytes=data['base_commit_object_bytes'], base_tree_sha=data['base_tree_sha'], base_tree_object_sha256=data['base_tree_object_sha256'], base_tree_object_bytes=data['base_tree_object_bytes'], source_mutated=data['source_mutated'], object_format=data['object_format'], shallow=data['shallow'])

    def to_dict(self) -> dict[str, Any]:
        return {'schema': self.schema, 'path_sha256': self.path_sha256, 'repository_kind': self.repository_kind, 'state_sha256': self.state_sha256, 'state_bytes': self.state_bytes, 'base_commit_sha': self.base_commit_sha, 'base_commit_object_sha256': self.base_commit_object_sha256, 'base_commit_object_bytes': self.base_commit_object_bytes, 'base_tree_sha': self.base_tree_sha, 'base_tree_object_sha256': self.base_tree_object_sha256, 'base_tree_object_bytes': self.base_tree_object_bytes, 'source_mutated': self.source_mutated, 'object_format': self.object_format, 'shallow': self.shallow}

@dataclass(frozen=True, slots=True)
class LocalCandidateCommitEvidence:
    parent_sha: str
    staged_patch_sha256: str
    staged_patch_bytes: int
    tree_sha: str
    tree_object_sha256: str
    tree_object_bytes: int
    commit_sha: str
    commit_object_sha256: str
    commit_object_bytes: int
    commit_message: str
    commit_message_sha256: str
    author_actor_id: str
    author_name: str
    author_email: str
    author_git_timestamp: str
    committer_actor_id: str
    committer_name: str
    committer_email: str
    committer_git_timestamp: str
    head_branch: str
    branch_ref: str
    branch_target_sha: str
    head_symbolic_ref: str
    exact_patch_reproduced: bool = True
    schema: str = _LOCAL_CANDIDATE_EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != _LOCAL_CANDIDATE_EVIDENCE_SCHEMA:
            raise LocalCandidateMaterializationError('unsupported local candidate evidence schema')
        for name, value in (('candidate parent SHA', self.parent_sha), ('candidate tree SHA', self.tree_sha), ('candidate commit SHA', self.commit_sha), ('candidate branch target SHA', self.branch_target_sha)):
            _hex(value, name=name, pattern=_HEX40)
        for name, value in (('candidate patch hash', self.staged_patch_sha256), ('candidate tree object hash', self.tree_object_sha256), ('candidate commit object hash', self.commit_object_sha256), ('candidate commit message hash', self.commit_message_sha256)):
            _hex(value, name=name)
        _integer(self.staged_patch_bytes, name='candidate patch bytes', low=1, high=_MAX_ARTIFACT_BYTES)
        _integer(self.tree_object_bytes, name='candidate tree object bytes', low=0, high=_MAX_OBJECT_BYTES)
        _integer(self.commit_object_bytes, name='candidate commit object bytes', low=1, high=_MAX_OBJECT_BYTES)
        message = _clean_text(self.commit_message, name='candidate commit message', maximum=240, one_line=True)
        if _sha256_bytes(message.encode('utf-8')) != self.commit_message_sha256:
            raise LocalCandidateMaterializationError('candidate commit message hash is inconsistent')
        author = _actor(self.author_actor_id, name='candidate author actor')
        committer = _actor(self.committer_actor_id, name='candidate committer actor')
        for name, value, maximum in (('candidate author name', self.author_name, 160), ('candidate author email', self.author_email, 200), ('candidate author Git timestamp', self.author_git_timestamp, 64), ('candidate committer name', self.committer_name, 160), ('candidate committer email', self.committer_email, 200), ('candidate committer Git timestamp', self.committer_git_timestamp, 64), ('candidate head branch', self.head_branch, 200), ('candidate branch ref', self.branch_ref, 260), ('candidate symbolic HEAD', self.head_symbolic_ref, 260)):
            _clean_text(value, name=name, maximum=maximum, one_line=True)
        if author != committer:
            raise LocalCandidateMaterializationError('candidate author and committer actors must be identical')
        if self.branch_ref != f'refs/heads/{self.head_branch}' or self.head_symbolic_ref != self.branch_ref or self.branch_target_sha != self.commit_sha or (self.exact_patch_reproduced is not True):
            raise LocalCandidateMaterializationError('candidate branch or patch evidence is inconsistent')
        payload = _expected_commit_payload(tree_sha=self.tree_sha, parent_sha=self.parent_sha, author_name=self.author_name, author_email=self.author_email, author_git_timestamp=self.author_git_timestamp, committer_name=self.committer_name, committer_email=self.committer_email, committer_git_timestamp=self.committer_git_timestamp, message=self.commit_message)
        if len(payload) != self.commit_object_bytes or _sha256_bytes(payload) != self.commit_object_sha256 or _git_object_id('commit', payload) != self.commit_sha:
            raise LocalCandidateMaterializationError('candidate commit object evidence is inconsistent')

    @classmethod
    def from_mapping(cls, value: Any) -> 'LocalCandidateCommitEvidence':
        fields = {'schema', 'parent_sha', 'staged_patch_sha256', 'staged_patch_bytes', 'tree_sha', 'tree_object_sha256', 'tree_object_bytes', 'commit_sha', 'commit_object_sha256', 'commit_object_bytes', 'commit_message', 'commit_message_sha256', 'author_actor_id', 'author_name', 'author_email', 'author_git_timestamp', 'committer_actor_id', 'committer_name', 'committer_email', 'committer_git_timestamp', 'head_branch', 'branch_ref', 'branch_target_sha', 'head_symbolic_ref', 'exact_patch_reproduced'}
        data = _strict(value, name='local candidate evidence', fields=fields)
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {'schema': self.schema, 'parent_sha': self.parent_sha, 'staged_patch_sha256': self.staged_patch_sha256, 'staged_patch_bytes': self.staged_patch_bytes, 'tree_sha': self.tree_sha, 'tree_object_sha256': self.tree_object_sha256, 'tree_object_bytes': self.tree_object_bytes, 'commit_sha': self.commit_sha, 'commit_object_sha256': self.commit_object_sha256, 'commit_object_bytes': self.commit_object_bytes, 'commit_message': self.commit_message, 'commit_message_sha256': self.commit_message_sha256, 'author_actor_id': self.author_actor_id, 'author_name': self.author_name, 'author_email': self.author_email, 'author_git_timestamp': self.author_git_timestamp, 'committer_actor_id': self.committer_actor_id, 'committer_name': self.committer_name, 'committer_email': self.committer_email, 'committer_git_timestamp': self.committer_git_timestamp, 'head_branch': self.head_branch, 'branch_ref': self.branch_ref, 'branch_target_sha': self.branch_target_sha, 'head_symbolic_ref': self.head_symbolic_ref, 'exact_patch_reproduced': self.exact_patch_reproduced}

@dataclass(frozen=True, slots=True)
class LocalCandidateMaterializationReceipt:
    preflight: PublisherPreflightReceipt
    preflight_sha256: str
    lease_sha256: str
    replay_entry_sha256: str
    request_sha256: str
    readiness_sha256: str
    task_sha256: str
    invocation_nonce: str
    materialization_policy_sha256: str
    materialized_at_utc: str
    transaction_id: str
    repository_relative_path: str
    receipt_relative_path: str
    git: LocalGitEvidence
    source: LocalSourceRepositoryEvidence
    candidate: LocalCandidateCommitEvidence
    bare_repository: bool = True
    isolated_index: bool = True
    local_source_only: bool = True
    remote_configured: bool = False
    network_write_performed: bool = False
    remote_push_performed: bool = False
    pull_request_created: bool = False
    ready_for_review: bool = False
    reviewers_requested: bool = False
    merged: bool = False
    released: bool = False
    deployed: bool = False
    merge_authority: str = 'human'
    schema: str = LOCAL_CANDIDATE_MATERIALIZATION_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != LOCAL_CANDIDATE_MATERIALIZATION_RECEIPT_SCHEMA:
            raise LocalCandidateMaterializationError('unsupported local materialization receipt schema')
        if not isinstance(self.preflight, PublisherPreflightReceipt):
            raise LocalCandidateMaterializationError('local materialization preflight is invalid')
        if not isinstance(self.git, LocalGitEvidence):
            raise LocalCandidateMaterializationError('local materialization Git evidence is invalid')
        if not isinstance(self.source, LocalSourceRepositoryEvidence):
            raise LocalCandidateMaterializationError('local materialization source evidence is invalid')
        if not isinstance(self.candidate, LocalCandidateCommitEvidence):
            raise LocalCandidateMaterializationError('local materialization candidate evidence is invalid')
        for name, value in (('preflight hash', self.preflight_sha256), ('lease hash', self.lease_sha256), ('replay entry hash', self.replay_entry_sha256), ('request hash', self.request_sha256), ('readiness hash', self.readiness_sha256), ('task hash', self.task_sha256), ('invocation nonce', self.invocation_nonce), ('materialization policy hash', self.materialization_policy_sha256)):
            _hex(value, name=name)
        _utc(self.materialized_at_utc, name='materialization time')
        _identifier(self.transaction_id, name='materialization transaction ID')
        if self.transaction_id != _transaction_id(self.preflight_sha256):
            raise LocalCandidateMaterializationError('materialization transaction ID is inconsistent')
        if self.repository_relative_path != 'repository.git' or self.receipt_relative_path != 'receipt.json':
            raise LocalCandidateMaterializationError('materialization relative paths are unsupported')
        lease = self.preflight.lease
        request = lease.signed_request.request
        if self.preflight_sha256 != self.preflight.sha256 or self.lease_sha256 != self.preflight.lease_sha256 or self.replay_entry_sha256 != self.preflight.replay_entry_sha256 or (self.request_sha256 != self.preflight.request_sha256) or (self.readiness_sha256 != self.preflight.readiness_sha256) or (self.task_sha256 != self.preflight.task_sha256) or (self.invocation_nonce != self.preflight.invocation_nonce) or (self.materialization_policy_sha256 != local_candidate_materialization_policy_sha256()):
            raise LocalCandidateMaterializationError('local materialization receipt identities are inconsistent')
        if self.source.base_commit_sha != request.base_sha or self.candidate.parent_sha != request.base_sha or self.candidate.staged_patch_sha256 != request.staged_patch_sha256 or (self.candidate.staged_patch_bytes != request.staged_patch_bytes) or (self.candidate.head_branch != request.head_branch) or (self.candidate.author_actor_id != request.publisher_actor_id) or (self.candidate.committer_actor_id != request.publisher_actor_id) or (self.candidate.commit_message != _commit_message(request.readiness.task)) or (self.candidate.author_name != _author_name(request.publisher_actor_id)) or (self.candidate.committer_name != _author_name(request.publisher_actor_id)) or (self.candidate.author_email != _actor_email(request.publisher_actor_id)) or (self.candidate.committer_email != _actor_email(request.publisher_actor_id)) or (self.candidate.author_git_timestamp != _git_timestamp(lease.issued_at_utc)) or (self.candidate.committer_git_timestamp != _git_timestamp(lease.issued_at_utc)):
            raise LocalCandidateMaterializationError('local candidate evidence is not bound to the authorized request')
        materialized = _utc(self.materialized_at_utc, name='materialization time')
        checked = _utc(self.preflight.checked_at_utc, name='preflight check time')
        expires = _utc(lease.expires_at_utc, name='lease expiry time')
        if materialized < checked or materialized >= expires:
            raise LocalCandidateMaterializationError('materialization time is outside the authorized preflight window')
        if self.bare_repository is not True or self.isolated_index is not True or self.local_source_only is not True or (self.remote_configured is not False) or (self.network_write_performed is not False) or (self.remote_push_performed is not False) or (self.pull_request_created is not False) or (self.ready_for_review is not False) or (self.reviewers_requested is not False) or (self.merged is not False) or (self.released is not False) or (self.deployed is not False) or (self.merge_authority != 'human'):
            raise LocalCandidateMaterializationError('local materialization authority boundary is invalid')

    @classmethod
    def from_mapping(cls, value: Any) -> 'LocalCandidateMaterializationReceipt':
        fields = {'schema', 'preflight', 'preflight_sha256', 'lease_sha256', 'replay_entry_sha256', 'request_sha256', 'readiness_sha256', 'task_sha256', 'invocation_nonce', 'materialization_policy_sha256', 'materialized_at_utc', 'transaction_id', 'repository_relative_path', 'receipt_relative_path', 'git', 'source', 'candidate', 'bare_repository', 'isolated_index', 'local_source_only', 'remote_configured', 'network_write_performed', 'remote_push_performed', 'pull_request_created', 'ready_for_review', 'reviewers_requested', 'merged', 'released', 'deployed', 'merge_authority'}
        data = _strict(value, name='local candidate materialization receipt', fields=fields)
        return cls(schema=data['schema'], preflight=PublisherPreflightReceipt.from_mapping(data['preflight']), preflight_sha256=data['preflight_sha256'], lease_sha256=data['lease_sha256'], replay_entry_sha256=data['replay_entry_sha256'], request_sha256=data['request_sha256'], readiness_sha256=data['readiness_sha256'], task_sha256=data['task_sha256'], invocation_nonce=data['invocation_nonce'], materialization_policy_sha256=data['materialization_policy_sha256'], materialized_at_utc=data['materialized_at_utc'], transaction_id=data['transaction_id'], repository_relative_path=data['repository_relative_path'], receipt_relative_path=data['receipt_relative_path'], git=LocalGitEvidence.from_mapping(data['git']), source=LocalSourceRepositoryEvidence.from_mapping(data['source']), candidate=LocalCandidateCommitEvidence.from_mapping(data['candidate']), bare_repository=data['bare_repository'], isolated_index=data['isolated_index'], local_source_only=data['local_source_only'], remote_configured=data['remote_configured'], network_write_performed=data['network_write_performed'], remote_push_performed=data['remote_push_performed'], pull_request_created=data['pull_request_created'], ready_for_review=data['ready_for_review'], reviewers_requested=data['reviewers_requested'], merged=data['merged'], released=data['released'], deployed=data['deployed'], merge_authority=data['merge_authority'])

    def to_dict(self) -> dict[str, Any]:
        return {'schema': self.schema, 'preflight': self.preflight.to_dict(), 'preflight_sha256': self.preflight_sha256, 'lease_sha256': self.lease_sha256, 'replay_entry_sha256': self.replay_entry_sha256, 'request_sha256': self.request_sha256, 'readiness_sha256': self.readiness_sha256, 'task_sha256': self.task_sha256, 'invocation_nonce': self.invocation_nonce, 'materialization_policy_sha256': self.materialization_policy_sha256, 'materialized_at_utc': self.materialized_at_utc, 'transaction_id': self.transaction_id, 'repository_relative_path': self.repository_relative_path, 'receipt_relative_path': self.receipt_relative_path, 'git': self.git.to_dict(), 'source': self.source.to_dict(), 'candidate': self.candidate.to_dict(), 'bare_repository': self.bare_repository, 'isolated_index': self.isolated_index, 'local_source_only': self.local_source_only, 'remote_configured': self.remote_configured, 'network_write_performed': self.network_write_performed, 'remote_push_performed': self.remote_push_performed, 'pull_request_created': self.pull_request_created, 'ready_for_review': self.ready_for_review, 'reviewers_requested': self.reviewers_requested, 'merged': self.merged, 'released': self.released, 'deployed': self.deployed, 'merge_authority': self.merge_authority}

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_bytes(self.canonical_json().encode('utf-8'))

def _source_state(runner: _GitEvidenceRunner, *, source: Path, repository_kind: str) -> bytes:
    refs = runner.run(('-C', os.fspath(source), 'for-each-ref', '--format=%(refname)%00%(objectname)%00'), cwd=runner._transaction_root)
    head = runner.run(('-C', os.fspath(source), 'rev-parse', '--verify', 'HEAD'), cwd=runner._transaction_root, maximum=4096)
    symbolic = runner.run(('-C', os.fspath(source), 'symbolic-ref', '-q', 'HEAD'), cwd=runner._transaction_root, maximum=4096, expected_codes=(0, 1))
    status = b''
    if repository_kind == 'worktree':
        status = runner.run(('-C', os.fspath(source), 'status', '--porcelain=v2', '-z', '--untracked-files=all'), cwd=runner._transaction_root)
    payload = b'refs\x00' + refs + b'\x00head\x00' + head + b'\x00symbolic\x00' + symbolic + b'\x00status\x00' + status
    if not payload or len(payload) > _MAX_OBJECT_BYTES:
        raise LocalCandidateMaterializationError('source repository state exceeds its bound')
    return payload

def _inspect_source(runner: _GitEvidenceRunner, *, source_repository: Path, base_sha: str) -> tuple[Path, LocalSourceRepositoryEvidence]:
    source = _existing_link_free_directory(source_repository, name='local source repository')
    bare_text = runner.run(('-C', os.fspath(source), 'rev-parse', '--is-bare-repository'), cwd=runner._transaction_root, maximum=4096).decode('ascii', errors='strict').strip()
    if bare_text not in {'true', 'false'}:
        raise LocalCandidateMaterializationError('source repository bare state is invalid')
    repository_kind = 'bare' if bare_text == 'true' else 'worktree'
    if repository_kind == 'bare':
        git_dir_text = runner.run(('-C', os.fspath(source), 'rev-parse', '--absolute-git-dir'), cwd=runner._transaction_root, maximum=4096).decode('utf-8', errors='strict').strip()
        git_dir = Path(os.path.realpath(git_dir_text))
        if git_dir != source:
            raise LocalCandidateMaterializationError('bare source Git directory does not match the exact source')
    else:
        git_dir = source / '.git'
        if not git_dir.is_dir() or _has_linkish_component(git_dir):
            raise LocalCandidateMaterializationError('source worktree must contain a standalone link-free .git directory')
        top = runner.run(('-C', os.fspath(source), 'rev-parse', '--show-toplevel'), cwd=runner._transaction_root, maximum=4096).decode('utf-8', errors='strict').strip()
        if Path(os.path.realpath(top)) != source:
            raise LocalCandidateMaterializationError('source worktree top-level does not match the exact source')
    if not (git_dir / 'objects').is_dir() or _has_linkish_component(git_dir / 'objects') or (not (git_dir / 'HEAD').is_file()) or _has_linkish_component(git_dir / 'HEAD') or (not (git_dir / 'config').is_file()) or _has_linkish_component(git_dir / 'config') or (git_dir / 'commondir').exists() or (git_dir / 'objects' / 'info' / 'alternates').exists():
        raise LocalCandidateMaterializationError('source repository storage is not standalone and link-free')
    object_format = runner.run(('-C', os.fspath(source), 'rev-parse', '--show-object-format'), cwd=runner._transaction_root, maximum=4096).decode('ascii', errors='strict').strip()
    if object_format != 'sha1':
        raise LocalCandidateMaterializationError('source repository must use SHA-1 object IDs')
    shallow = runner.run(('-C', os.fspath(source), 'rev-parse', '--is-shallow-repository'), cwd=runner._transaction_root, maximum=4096).decode('ascii', errors='strict').strip()
    if shallow != 'false':
        raise LocalCandidateMaterializationError('source repository must contain non-shallow history')
    runner.run(('-C', os.fspath(source), 'cat-file', '-e', f'{base_sha}^{{commit}}'), cwd=runner._transaction_root, maximum=4096)
    commit_payload = runner.run(('-C', os.fspath(source), 'cat-file', 'commit', base_sha), cwd=runner._transaction_root, maximum=_MAX_OBJECT_BYTES)
    if _git_object_id('commit', commit_payload) != base_sha:
        raise LocalCandidateMaterializationError('source base commit object does not match the authorized SHA')
    tree_sha = runner.run(('-C', os.fspath(source), 'rev-parse', f'{base_sha}^{{tree}}'), cwd=runner._transaction_root, maximum=4096).decode('ascii', errors='strict').strip()
    _hex(tree_sha, name='source base tree SHA', pattern=_HEX40)
    tree_payload = runner.run(('-C', os.fspath(source), 'cat-file', 'tree', tree_sha), cwd=runner._transaction_root, maximum=_MAX_OBJECT_BYTES)
    if _git_object_id('tree', tree_payload) != tree_sha:
        raise LocalCandidateMaterializationError('source base tree object is inconsistent')
    state = _source_state(runner, source=source, repository_kind=repository_kind)
    evidence = LocalSourceRepositoryEvidence(path_sha256=_sha256_bytes(os.fspath(source).encode('utf-8')), repository_kind=repository_kind, state_sha256=_sha256_bytes(state), state_bytes=len(state), base_commit_sha=base_sha, base_commit_object_sha256=_sha256_bytes(commit_payload), base_commit_object_bytes=len(commit_payload), base_tree_sha=tree_sha, base_tree_object_sha256=_sha256_bytes(tree_payload), base_tree_object_bytes=len(tree_payload))
    return (source, evidence)

def _verify_source_unchanged(runner: _GitEvidenceRunner, *, source: Path, evidence: LocalSourceRepositoryEvidence) -> None:
    state = _source_state(runner, source=source, repository_kind=evidence.repository_kind)
    commit_payload = runner.run(('-C', os.fspath(source), 'cat-file', 'commit', evidence.base_commit_sha), cwd=runner._transaction_root, maximum=_MAX_OBJECT_BYTES)
    tree_payload = runner.run(('-C', os.fspath(source), 'cat-file', 'tree', evidence.base_tree_sha), cwd=runner._transaction_root, maximum=_MAX_OBJECT_BYTES)
    if len(state) != evidence.state_bytes or _sha256_bytes(state) != evidence.state_sha256 or len(commit_payload) != evidence.base_commit_object_bytes or (_sha256_bytes(commit_payload) != evidence.base_commit_object_sha256) or (len(tree_payload) != evidence.base_tree_object_bytes) or (_sha256_bytes(tree_payload) != evidence.base_tree_object_sha256):
        raise LocalCandidateMaterializationError('local source repository changed during materialization')

def _verify_transaction_layout(transaction: Path) -> None:
    expected = {'repository.git', 'receipt.json', 'isolated-home', 'isolated-xdg', 'disabled-hooks', 'empty-template', 'empty-global-config'}
    actual = {item.name for item in transaction.iterdir()}
    if actual != expected:
        raise LocalCandidateMaterializationError('local materialization transaction layout is not exact')
    for name in ('isolated-home', 'isolated-xdg', 'disabled-hooks', 'empty-template'):
        directory = transaction / name
        if not directory.is_dir() or _has_linkish_component(directory) or any(directory.iterdir()):
            raise LocalCandidateMaterializationError('local materialization isolation directory is not empty and exact')
    global_config = transaction / 'empty-global-config'
    if not global_config.is_file() or _has_linkish_component(global_config) or global_config.read_bytes() != b'':
        raise LocalCandidateMaterializationError('local materialization global configuration is not empty and exact')

def _repository_args(repository: Path, *args: str) -> tuple[str, ...]:
    return ('--git-dir', os.fspath(repository), *args)

def _inspect_materialized_repository(runner: _GitEvidenceRunner, *, repository: Path, receipt: LocalCandidateMaterializationReceipt) -> None:
    if not repository.is_dir() or _has_linkish_component(repository) or (not (repository / 'objects').is_dir()):
        raise LocalCandidateMaterializationError('materialized bare repository is missing or unsafe')
    is_bare = runner.run(_repository_args(repository, 'rev-parse', '--is-bare-repository'), cwd=runner._transaction_root, maximum=4096).decode('ascii', errors='strict').strip()
    object_format = runner.run(_repository_args(repository, 'rev-parse', '--show-object-format'), cwd=runner._transaction_root, maximum=4096).decode('ascii', errors='strict').strip()
    if is_bare != 'true' or object_format != 'sha1':
        raise LocalCandidateMaterializationError('materialized repository boundary is unsupported')
    candidate = receipt.candidate
    branch_target = runner.run(_repository_args(repository, 'rev-parse', '--verify', candidate.branch_ref), cwd=runner._transaction_root, maximum=4096).decode('ascii', errors='strict').strip()
    symbolic_head = runner.run(_repository_args(repository, 'symbolic-ref', '-q', 'HEAD'), cwd=runner._transaction_root, maximum=4096).decode('utf-8', errors='strict').strip()
    parent = runner.run(_repository_args(repository, 'rev-parse', f'{candidate.commit_sha}^'), cwd=runner._transaction_root, maximum=4096).decode('ascii', errors='strict').strip()
    tree = runner.run(_repository_args(repository, 'rev-parse', f'{candidate.commit_sha}^{{tree}}'), cwd=runner._transaction_root, maximum=4096).decode('ascii', errors='strict').strip()
    refs = runner.run(_repository_args(repository, 'for-each-ref', '--format=%(refname)%00%(objectname)%00'), cwd=runner._transaction_root)
    expected_refs = f'{candidate.branch_ref}\x00{candidate.commit_sha}\x00\n'.encode('utf-8')
    remotes = runner.run(_repository_args(repository, 'remote'), cwd=runner._transaction_root, maximum=4096)
    commit_payload = runner.run(_repository_args(repository, 'cat-file', 'commit', candidate.commit_sha), cwd=runner._transaction_root, maximum=_MAX_OBJECT_BYTES)
    tree_payload = runner.run(_repository_args(repository, 'cat-file', 'tree', candidate.tree_sha), cwd=runner._transaction_root, maximum=_MAX_OBJECT_BYTES)
    patch = runner.run(_repository_args(repository, 'diff', '--binary', '--full-index', '--no-color', '--no-ext-diff', '--no-textconv', '--no-renames', candidate.parent_sha, candidate.commit_sha, '--'), cwd=runner._transaction_root, maximum=_MAX_ARTIFACT_BYTES)
    expected_commit_payload = _expected_commit_payload(tree_sha=candidate.tree_sha, parent_sha=candidate.parent_sha, author_name=candidate.author_name, author_email=candidate.author_email, author_git_timestamp=candidate.author_git_timestamp, committer_name=candidate.committer_name, committer_email=candidate.committer_email, committer_git_timestamp=candidate.committer_git_timestamp, message=candidate.commit_message)
    if branch_target != candidate.commit_sha or symbolic_head != candidate.branch_ref or parent != candidate.parent_sha or (tree != candidate.tree_sha) or (refs != expected_refs) or remotes or (commit_payload != expected_commit_payload) or (len(commit_payload) != candidate.commit_object_bytes) or (_sha256_bytes(commit_payload) != candidate.commit_object_sha256) or (_git_object_id('commit', commit_payload) != candidate.commit_sha) or (len(tree_payload) != candidate.tree_object_bytes) or (_sha256_bytes(tree_payload) != candidate.tree_object_sha256) or (_git_object_id('tree', tree_payload) != candidate.tree_sha) or (len(patch) != candidate.staged_patch_bytes) or (_sha256_bytes(patch) != candidate.staged_patch_sha256):
        raise LocalCandidateMaterializationError('materialized repository no longer matches its receipt')

_T = TypeVar('_T')

def _load_canonical(path: Path, parser: Callable[[Any], _T], *, name: str) -> _T:
    raw_path = Path(path)
    if not raw_path.is_absolute() or _has_linkish_component(raw_path) or (not raw_path.is_file()):
        raise LocalCandidateMaterializationError(f'{name} must be an absolute regular file')
    raw = raw_path.read_bytes()
    if not 2 <= len(raw) <= _MAX_ARTIFACT_BYTES:
        raise LocalCandidateMaterializationError(f'{name} size is invalid')
    try:
        value = parser(json.loads(raw.decode('utf-8')))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalCandidateMaterializationError(f'{name} JSON is invalid') from exc
    canonical_json = getattr(value, 'canonical_json', None)
    if canonical_json is None or raw != canonical_json().encode('utf-8'):
        raise LocalCandidateMaterializationError(f'{name} is not canonical JSON')
    return value

def _write_canonical(path: Path, value: Any, *, name: str, prefix: str) -> str:
    canonical_json = getattr(value, 'canonical_json', None)
    if canonical_json is None:
        raise LocalCandidateMaterializationError(f'{name} output is invalid')
    output = Path(path)
    if not output.is_absolute() or output.exists() or _has_linkish_component(output.parent) or (not output.parent.is_dir()):
        raise LocalCandidateMaterializationError(f'{name} output path is unsafe or already exists')
    payload = canonical_json().encode('utf-8')
    if len(payload) > _MAX_ARTIFACT_BYTES:
        raise LocalCandidateMaterializationError(f'{name} exceeds its byte bound')
    descriptor, temporary_name = tempfile.mkstemp(prefix=prefix, suffix='.tmp', dir=output.parent)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, output)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return _sha256_bytes(payload)
