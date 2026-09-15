"""ADR-DC-061 dual-authorized recovery for interrupted exact merge transactions.

This boundary never replays a merge. It reconstructs one consumed ADR-DC-060
transaction from durable ADR-DC-059/060 evidence and read-only GitHub state.

A lock-only transaction whose exact PR remains open is manual/fail-closed. If
GitHub already shows the exact authorized squash merge, recovery may finalize
that outcome under two new independent detached Ed25519 signatures. A durable
ADR-DC-060 merged marker, when present, must agree byte-for-byte with the exact
remote merge identity. No release, deploy or production authority follows.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping
from ._improvement_physical_state_host_control import PhysicalHostStateError, _require_elevated_operator, _require_host_controlled_ledger_root
from ._improvement_pilot_start_consumption_impl import _path_sha256, _safe_ledger_root
from .asymmetric_authority import AsymmetricAuthorityError, DetachedEd25519AuthoritySignature, Ed25519AuthorityVerifier, TrustedEd25519AuthorityKey, asymmetric_authority_key_custody_policy_sha256
from .durable_publication import DurablePublicationError, create_once_file
from . import improvement_pilot_exact_task_merge_authorization as auth_boundary
from . import improvement_pilot_exact_task_merge_transaction as tx_boundary
from . import improvement_pilot_exact_task_pr_lifecycle_authorization as lifecycle_auth_boundary
from . import improvement_pilot_exact_task_remote_publication_transaction as publication_tx_boundary
from .improvement_pilot_exact_task_merge_authorization import PILOT_EXACT_TASK_MERGE_AUTHORIZATION_AUTHORITY, PilotExactTaskMergeAuthorizationReceipt
from .improvement_pilot_exact_task_remote_publication_transaction import PilotExactTaskGitHubPublisherCredential
from .trusted_git_runtime_model import _has_linkish_component
PILOT_EXACT_TASK_MERGE_RECOVERY_SCHEMA = 'kaliv-rsi-dc-l16-exact-task-merge-recovery-receipt/v1'
PILOT_EXACT_TASK_MERGE_RECOVERY_AUTHORITY = 'dual-reviewed-dc-l16-exact-merge-recovery-only'
PILOT_EXACT_TASK_MERGE_RECOVERY_SCOPE = 'exact-merged-state-finalization-only-v1'
PILOT_EXACT_TASK_MERGE_RECOVERY_KEYRING_SCHEMA = 'kaliv-rsi-dc-l16-exact-task-merge-recovery-keyring/v1'
PILOT_EXACT_TASK_MERGE_RECOVERY_PAYLOAD_SCHEMA = 'kaliv-rsi-dc-l16-exact-task-merge-recovery-authorization-payload/v1'
PILOT_EXACT_TASK_MERGE_RECOVERY_LEDGER_SCOPE = 'canonical-host-local-v1'
_RECOVERY_POLICY_DOMAIN = b'kaliv-rsi-dc-l16-exact-task-merge-recovery-policy/v1\x00'
_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
_MAX_KEYRING_BYTES = 1024 * 1024
_MAX_API_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_AUTH_SECONDS = 10 * 60
_TIMEOUT_SECONDS = 30.0
_HEX40 = re.compile('^[0-9a-f]{40}$')
_HEX64 = re.compile('^[0-9a-f]{64}$')
_REPOSITORY = re.compile('^[^/\\s]+/[^/\\s]+$')
_REPOSITORY_ID = re.compile('^[1-9][0-9]{0,19}$')
_BRANCH = re.compile('^(?![./])(?!.*\\.\\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$')
_ACTOR = re.compile('^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$')
_IDENTIFIER = re.compile('^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$')
_UTC = re.compile('^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z$')
_GITHUB_API_ROOT = 'https://api.github.com'
_POSIX_LEDGER = Path('/var/lib/modelrig/devcontrol/rsi-pilot-exact-task-merge-recovery-ledger-v1')
_WINDOWS_LEDGER = Path('C:\\Program Files\\ModelRig\\DevControl\\state') / 'rsi-pilot-exact-task-merge-recovery-ledger-v1'
_POSIX_KEYRING = Path('/etc/modelrig/devcontrol/authority/rsi-pilot-exact-task-merge-recovery-keyring-v1.json')
_WINDOWS_KEYRING = Path('C:\\Program Files\\ModelRig\\DevControl\\authority') / 'rsi-pilot-exact-task-merge-recovery-keyring-v1.json'
PILOT_EXACT_TASK_MERGE_RECOVERY_POLICY = ('Recover only one previously consumed ADR-DC-060 merge transaction nonce.', 'Never retry or replay the GitHub merge operation.', 'Require the durable ADR-DC-059 authorization receipt and ADR-DC-060 transaction lock to agree exactly.', 'If the exact PR remains open and unmerged, require manual intervention.', 'Permit automatic finalization only when GitHub proves the exact authorized squash merge already exists.', 'When an ADR-DC-060 merged marker exists, require it to match the exact remote merge commit.', 'Require two independent detached Ed25519 signatures over the exact recovery-state fingerprint.', 'Durably consume recovery authority before publishing a recovery receipt.', 'Never make the nonce reusable and never grant merge, release, deploy or production activation authority.')

class PilotExactTaskMergeRecoveryError(ValueError):
    """Interrupted merge state is ambiguous, unauthenticated or unsafe."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskMergeRecoveryError('merge recovery evidence is not canonical JSON') from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == '0' * 40:
        raise PilotExactTaskMergeRecoveryError(f'{name} is invalid')
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == '0' * 64:
        raise PilotExactTaskMergeRecoveryError(f'{name} is invalid')
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskMergeRecoveryError(f'{name} must be canonical UTC seconds')
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskMergeRecoveryError(f'{name} is invalid') from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime('%Y-%m-%dT%H:%M:%SZ')


def _branch(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or value.strip() != value or _BRANCH.fullmatch(value) is None or value.endswith(('/', '.', '.lock')) or '@{' in value or '\\' in value:
        raise PilotExactTaskMergeRecoveryError(f'{name} is invalid')
    return value


def _read_bytes(path: Path) -> bytes | None:
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


def _read_canonical_object(path: Path, *, name: str) -> tuple[dict[str, Any], bytes]:
    payload = _read_bytes(path)
    if payload is None:
        raise PilotExactTaskMergeRecoveryError(f'{name} is unavailable')
    try:
        raw = json.loads(payload.decode('utf-8', errors='strict'))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskMergeRecoveryError(f'{name} is invalid JSON') from exc
    if not isinstance(raw, dict) or _canonical(raw).encode('utf-8') != payload:
        raise PilotExactTaskMergeRecoveryError(f'{name} is not canonical JSON')
    return (raw, payload)


def _payload_sha256(payload: bytes) -> str:
    if not isinstance(payload, bytes) or not payload:
        raise PilotExactTaskMergeRecoveryError('durable merge payload is missing')
    return hashlib.sha256(payload).hexdigest()


def pilot_exact_task_merge_recovery_policy_sha256() -> str:
    payload = json.dumps(list(PILOT_EXACT_TASK_MERGE_RECOVERY_POLICY), ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(_RECOVERY_POLICY_DOMAIN + payload).hexdigest()

@dataclass(frozen=True, slots=True)
class _MergeRecoveryRemoteState:
    repository: str
    repository_id: str
    base_branch: str
    base_ref_sha: str
    head_branch: str
    head_sha: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_node_id_sha256: str
    state: str
    draft: bool
    merged: bool
    maintainer_can_modify: bool
    merge_commit_sha: str | None
    merge_commit_parent_sha: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None or not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None:
            raise PilotExactTaskMergeRecoveryError('remote recovery repository identity is invalid')
        _branch(self.base_branch, name='base_branch')
        _branch(self.head_branch, name='head_branch')
        _hex40(self.base_ref_sha, name='base_ref_sha')
        _hex40(self.head_sha, name='head_sha')
        _hex64(self.pull_request_node_id_sha256, name='pull_request_node_id_sha256')
        if isinstance(self.pull_request_number, bool) or not isinstance(self.pull_request_number, int) or self.pull_request_number < 1 or self.pull_request_api_url != f'{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/{self.pull_request_number}' or self.maintainer_can_modify is not False or self.draft is not False:
            raise PilotExactTaskMergeRecoveryError('remote recovery PR identity/state is invalid')
        if self.state == 'open' and self.merged is False:
            if self.merge_commit_sha is not None or self.merge_commit_parent_sha is not None:
                raise PilotExactTaskMergeRecoveryError('open PR cannot carry merge commit evidence')
        elif self.state == 'closed' and self.merged is True:
            _hex40(self.merge_commit_sha, name='merge_commit_sha')
            _hex40(self.merge_commit_parent_sha, name='merge_commit_parent_sha')
            if self.base_ref_sha != self.merge_commit_sha:
                raise PilotExactTaskMergeRecoveryError('merged base ref does not equal merge commit')
        else:
            raise PilotExactTaskMergeRecoveryError('remote merge state is neither exact open nor merged')

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict()).encode('utf-8')).hexdigest()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _GitHubMergeRecoveryObserver:
    """Credential-bound GET-only observer for exact post-crash merge state."""

    def __init__(self, *, credential: PilotExactTaskGitHubPublisherCredential, credential_config_sha256: str, credential_path: Path) -> None:
        if type(credential) is not PilotExactTaskGitHubPublisherCredential:
            raise PilotExactTaskMergeRecoveryError('exact publisher credential is required')
        self.credential = credential
        self.credential_id = credential.credential_id
        self.credential_config_sha256 = _hex64(credential_config_sha256, name='credential_config_sha256')
        self.credential_path = Path(credential_path)
        if not self.credential_path.is_absolute() or _has_linkish_component(self.credential_path):
            raise PilotExactTaskMergeRecoveryError('publisher credential path is unsafe')
        self.credential_path_sha256 = _path_sha256(self.credential_path)
        self._opener = urllib.request.build_opener(_NoRedirect())

    @staticmethod
    def _repo_root(authorization: PilotExactTaskMergeAuthorizationReceipt) -> str:
        owner, repo = authorization.repository.split('/', 1)
        return f"/repos/{urllib.parse.quote(owner, safe='')}/{urllib.parse.quote(repo, safe='')}"

    def validate_for(self, authorization: PilotExactTaskMergeAuthorizationReceipt) -> None:
        if type(authorization) is not PilotExactTaskMergeAuthorizationReceipt or self.credential.repository != authorization.repository or self.credential.repository_id != authorization.repository_id:
            raise PilotExactTaskMergeRecoveryError('publisher credential is not bound to exact merge target')

    def _api_json(self, *, authorization: PilotExactTaskMergeAuthorizationReceipt, path: str) -> Any:
        root = self._repo_root(authorization)
        if not isinstance(path, str) or not (path == root or path.startswith(root + '/')) or '..' in path:
            raise PilotExactTaskMergeRecoveryError('recovery GET is outside exact GitHub scope')
        url = _GITHUB_API_ROOT + path
        request = urllib.request.Request(url, method='GET', headers={'Accept': 'application/vnd.github+json', 'Authorization': f'Bearer {self.credential.token}', 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'ModelRig-DevControl-ExactMergeRecovery/1'})
        try:
            response = self._opener.open(request, timeout=_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            raise PilotExactTaskMergeRecoveryError(f'GitHub merge recovery GET failed with HTTP {exc.code}') from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PilotExactTaskMergeRecoveryError('GitHub merge recovery GET failed') from exc
        with response:
            if response.status != 200 or response.geturl() != url:
                raise PilotExactTaskMergeRecoveryError('GitHub recovery response identity/status is unexpected')
            raw = response.read(_MAX_API_RESPONSE_BYTES + 1)
        if not raw or len(raw) > _MAX_API_RESPONSE_BYTES:
            raise PilotExactTaskMergeRecoveryError('GitHub recovery response size is invalid')
        try:
            return json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PilotExactTaskMergeRecoveryError('GitHub recovery response is invalid JSON') from exc

    @staticmethod
    def _node_hash(value: Any) -> str:
        if not isinstance(value, str) or not value:
            raise PilotExactTaskMergeRecoveryError('GitHub pull-request node identity is invalid')
        return hashlib.sha256(value.encode('utf-8')).hexdigest()

    @staticmethod
    def _head_base(value: Mapping[str, Any], *, side: str) -> tuple[str, str, str]:
        item = value.get(side)
        if not isinstance(item, Mapping):
            raise PilotExactTaskMergeRecoveryError(f'GitHub PR {side} identity is invalid')
        repo = item.get('repo')
        if not isinstance(repo, Mapping):
            raise PilotExactTaskMergeRecoveryError(f'GitHub PR {side} repository identity is invalid')
        return (_branch(item.get('ref'), name=f'GitHub PR {side} branch'), _hex40(item.get('sha'), name=f'GitHub PR {side} SHA'), str(repo.get('id')))

    def _repository(self, authorization: PilotExactTaskMergeAuthorizationReceipt) -> None:
        value = self._api_json(authorization=authorization, path=self._repo_root(authorization))
        if not isinstance(value, Mapping) or str(value.get('id')) != authorization.repository_id or value.get('full_name') != authorization.repository:
            raise PilotExactTaskMergeRecoveryError('GitHub repository identity differs from merge authority')

    def _pull(self, authorization: PilotExactTaskMergeAuthorizationReceipt) -> Mapping[str, Any]:
        value = self._api_json(authorization=authorization, path=f'{self._repo_root(authorization)}/pulls/{authorization.pull_request_number}')
        if not isinstance(value, Mapping):
            raise PilotExactTaskMergeRecoveryError('GitHub PR recovery response is invalid')
        return value

    def _ref(self, authorization: PilotExactTaskMergeAuthorizationReceipt) -> str:
        branch = urllib.parse.quote(_branch(authorization.base_branch, name='base branch'), safe='')
        value = self._api_json(authorization=authorization, path=f'{self._repo_root(authorization)}/git/ref/heads/{branch}')
        obj = value.get('object') if isinstance(value, Mapping) else None
        if not isinstance(obj, Mapping) or obj.get('type') != 'commit':
            raise PilotExactTaskMergeRecoveryError('GitHub base ref is invalid')
        return _hex40(obj.get('sha'), name='GitHub base ref SHA')

    def _commit_parent(self, authorization: PilotExactTaskMergeAuthorizationReceipt, sha: str) -> str:
        value = self._api_json(authorization=authorization, path=f"{self._repo_root(authorization)}/commits/{_hex40(sha, name='merge commit SHA')}")
        parents = value.get('parents') if isinstance(value, Mapping) else None
        if not isinstance(parents, list) or len(parents) != 1 or not isinstance(parents[0], Mapping):
            raise PilotExactTaskMergeRecoveryError('squash merge commit does not have exactly one parent')
        return _hex40(parents[0].get('sha'), name='squash merge parent SHA')

    def observe(self, authorization: PilotExactTaskMergeAuthorizationReceipt) -> _MergeRecoveryRemoteState:
        self.validate_for(authorization)
        self._repository(authorization)
        pr = self._pull(authorization)
        head_branch, head_sha, head_repo_id = self._head_base(pr, side='head')
        base_branch, _pr_base_sha, base_repo_id = self._head_base(pr, side='base')
        if head_repo_id != authorization.repository_id or base_repo_id != authorization.repository_id or head_branch != authorization.head_branch or head_sha != authorization.head_sha or base_branch != authorization.base_branch or self._node_hash(pr.get('node_id')) != authorization.pull_request_node_id_sha256:
            raise PilotExactTaskMergeRecoveryError('GitHub PR identity differs from exact merge authority')
        base_ref_sha = self._ref(authorization)
        merged = pr.get('merged')
        state = pr.get('state')
        merge_sha = None
        parent_sha = None
        if state == 'closed' and merged is True:
            merge_sha = _hex40(pr.get('merge_commit_sha'), name='GitHub PR merge commit SHA')
            parent_sha = self._commit_parent(authorization, merge_sha)
        remote = _MergeRecoveryRemoteState(repository=authorization.repository, repository_id=authorization.repository_id, base_branch=base_branch, base_ref_sha=base_ref_sha, head_branch=head_branch, head_sha=head_sha, pull_request_number=authorization.pull_request_number, pull_request_api_url=authorization.pull_request_api_url, pull_request_node_id_sha256=self._node_hash(pr.get('node_id')), state=state, draft=pr.get('draft'), merged=merged, maintainer_can_modify=pr.get('maintainer_can_modify'), merge_commit_sha=merge_sha, merge_commit_parent_sha=parent_sha)
        if remote.state == 'open':
            if remote.base_ref_sha != authorization.base_sha:
                raise PilotExactTaskMergeRecoveryError('open recovery state base moved from authorized SHA')
        elif remote.merge_commit_parent_sha != authorization.base_sha or remote.base_ref_sha != remote.merge_commit_sha:
            raise PilotExactTaskMergeRecoveryError('merged recovery state is not exact authorized squash merge')
        return remote


def _parse_keyring(payload: bytes) -> tuple[Ed25519AuthorityVerifier, str]:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_KEYRING_BYTES:
        raise PilotExactTaskMergeRecoveryError('merge recovery keyring payload is invalid')
    try:
        raw = json.loads(payload.decode('utf-8', errors='strict'))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskMergeRecoveryError('merge recovery keyring JSON is invalid') from exc
    if not isinstance(raw, dict) or set(raw) != {'schema', 'minimum_keyring_epoch', 'keys'} or raw.get('schema') != PILOT_EXACT_TASK_MERGE_RECOVERY_KEYRING_SCHEMA:
        raise PilotExactTaskMergeRecoveryError('merge recovery keyring fields/schema mismatch')
    epoch = raw['minimum_keyring_epoch']
    keys_raw = raw['keys']
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 1 or not isinstance(keys_raw, list) or not 2 <= len(keys_raw) <= 64:
        raise PilotExactTaskMergeRecoveryError('merge recovery keyring content is invalid')
    keys: dict[str, TrustedEd25519AuthorityKey] = {}
    for item in keys_raw:
        try:
            key = TrustedEd25519AuthorityKey.from_mapping(item)
        except Exception as exc:
            raise PilotExactTaskMergeRecoveryError('merge recovery trusted key is invalid') from exc
        if key.key_id in keys:
            raise PilotExactTaskMergeRecoveryError('merge recovery key IDs are duplicated')
        keys[key.key_id] = key
    if list(keys) != sorted(keys):
        raise PilotExactTaskMergeRecoveryError('merge recovery keyring keys must be sorted by key_id')
    canonical = _canonical({'schema': PILOT_EXACT_TASK_MERGE_RECOVERY_KEYRING_SCHEMA, 'minimum_keyring_epoch': epoch, 'keys': [keys[key_id].to_dict() for key_id in sorted(keys)]}).encode('utf-8')
    if canonical != payload:
        raise PilotExactTaskMergeRecoveryError('merge recovery keyring is not canonical JSON')
    return (Ed25519AuthorityVerifier(keys, minimum_keyring_epoch=epoch), hashlib.sha256(payload).hexdigest())


def _read_host_authority_file(path: Path) -> bytes:
    try:
        payload = lifecycle_auth_boundary._read_host_authority_file(Path(path))
    except Exception as exc:
        raise PilotExactTaskMergeRecoveryError('merge recovery authority file is not host-admin controlled') from exc
    if not payload or len(payload) > _MAX_KEYRING_BYTES:
        raise PilotExactTaskMergeRecoveryError('merge recovery authority file is invalid')
    return payload


def _load_durable_authorization(*, key: str, merge_authorization_ledger_root: Path) -> tuple[PilotExactTaskMergeAuthorizationReceipt, bytes]:
    root = _safe_ledger_root(Path(merge_authorization_ledger_root))
    final = root / f'{key}.json'
    raw, payload = _read_canonical_object(final, name='ADR-DC-059 merge authorization receipt')
    try:
        authorization = PilotExactTaskMergeAuthorizationReceipt.from_mapping(raw)
    except Exception as exc:
        raise PilotExactTaskMergeRecoveryError('ADR-DC-059 durable receipt is invalid') from exc
    if authorization.authority != PILOT_EXACT_TASK_MERGE_AUTHORIZATION_AUTHORITY or authorization.execution_nonce_sha256 != key or authorization.merge_key_sha256 != key or authorization.merge_ready is not True or authorization.merge_authorized is not True or authorization.remote_write_authorized is not True or authorization.release_authorized is not False or authorization.deploy_authorized is not False or authorization.production_activation_authorized is not False:
        raise PilotExactTaskMergeRecoveryError('ADR-DC-059 durable receipt is not exact merge authority')
    return (authorization, payload)


def _validate_transaction_lock(raw: Mapping[str, Any], *, payload: bytes, key: str, authorization: PilotExactTaskMergeAuthorizationReceipt, transaction_ledger_root_sha256: str) -> tuple[str, str, str, str]:
    expected = {'schema', 'ledger_scope', 'ledger_root_path_sha256', 'transaction_key_sha256', 'merge_authorization_sha256', 'merge_readiness_evaluation_sha256', 'merge_readiness_policy_sha256', 'merge_config_sha256', 'repository', 'repository_id', 'base_branch', 'base_sha', 'head_branch', 'head_sha', 'pull_request_number', 'merge_method', 'pre_merge_state_sha256', 'pre_lock_fresh_merge_readiness_sha256', 'publisher_credential_config_sha256', 'publisher_credential_path_sha256'}
    if set(raw) != expected or raw.get('schema') != 'kaliv-rsi-dc-l16-exact-task-merge-transaction-lock/v1' or raw.get('ledger_scope') != tx_boundary.PILOT_EXACT_TASK_MERGE_TRANSACTION_LEDGER_SCOPE or raw.get('ledger_root_path_sha256') != transaction_ledger_root_sha256 or raw.get('transaction_key_sha256') != key or raw.get('merge_authorization_sha256') != authorization.sha256 or raw.get('merge_readiness_evaluation_sha256') != authorization.merge_readiness_evaluation_sha256 or raw.get('merge_readiness_policy_sha256') != authorization.merge_readiness_policy_sha256 or raw.get('merge_config_sha256') != authorization.merge_config_sha256 or raw.get('repository') != authorization.repository or raw.get('repository_id') != authorization.repository_id or raw.get('base_branch') != authorization.base_branch or raw.get('base_sha') != authorization.base_sha or raw.get('head_branch') != authorization.head_branch or raw.get('head_sha') != authorization.head_sha or raw.get('pull_request_number') != authorization.pull_request_number or raw.get('merge_method') != 'squash':
        raise PilotExactTaskMergeRecoveryError('ADR-DC-060 transaction lock is not exact')
    pre_state = _hex64(raw.get('pre_merge_state_sha256'), name='pre_merge_state_sha256')
    fresh = _hex64(raw.get('pre_lock_fresh_merge_readiness_sha256'), name='pre_lock_fresh_merge_readiness_sha256')
    credential_config = _hex64(raw.get('publisher_credential_config_sha256'), name='publisher_credential_config_sha256')
    credential_path = _hex64(raw.get('publisher_credential_path_sha256'), name='publisher_credential_path_sha256')
    if _payload_sha256(payload) == '0' * 64:
        raise PilotExactTaskMergeRecoveryError('transaction lock hash is invalid')
    return (pre_state, fresh, credential_config, credential_path)


def _validate_merged_marker(raw: Mapping[str, Any], *, key: str, authorization: PilotExactTaskMergeAuthorizationReceipt) -> tuple[str, str, str]:
    expected = {'schema', 'ledger_scope', 'transaction_key_sha256', 'merge_authorization_sha256', 'merge_commit_sha', 'merge_response_sha256', 'merged_at_utc'}
    if set(raw) != expected or raw.get('schema') != 'kaliv-rsi-dc-l16-exact-task-merge-transaction-merged/v1' or raw.get('ledger_scope') != tx_boundary.PILOT_EXACT_TASK_MERGE_TRANSACTION_LEDGER_SCOPE or raw.get('transaction_key_sha256') != key or raw.get('merge_authorization_sha256') != authorization.sha256:
        raise PilotExactTaskMergeRecoveryError('ADR-DC-060 merged marker is not exact')
    merge_sha = _hex40(raw.get('merge_commit_sha'), name='merged marker commit SHA')
    response_sha = _hex64(raw.get('merge_response_sha256'), name='merged marker response hash')
    merged_at = raw.get('merged_at_utc')
    _utc(merged_at, name='merged_at_utc')
    return (merge_sha, response_sha, merged_at)

@dataclass(frozen=True, slots=True)
class PilotExactTaskMergeRecoveryState:
    transaction_key_sha256: str
    transaction_lock_sha256: str
    source_merged_marker_state_sha256: str
    merge_authorization_sha256: str
    merge_readiness_evaluation_sha256: str
    merge_readiness_policy_sha256: str
    merge_config_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    repository: str
    repository_id: str
    base_branch: str
    authorized_base_sha: str
    head_branch: str
    head_sha: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_node_id_sha256: str
    merge_method: str
    durable_transaction_state: str
    remote_merge_state: str
    action_required: str
    manual_intervention_required: bool
    merged_marker_present: bool
    merge_commit_sha: str | None
    merge_response_sha256: str | None
    remote_state_sha256: str
    observed_at_utc: str

    def __post_init__(self) -> None:
        for name in ('transaction_key_sha256', 'transaction_lock_sha256', 'source_merged_marker_state_sha256', 'merge_authorization_sha256', 'merge_readiness_evaluation_sha256', 'merge_readiness_policy_sha256', 'merge_config_sha256', 'execution_nonce_sha256', 'development_task_sha256', 'candidate_patch_sha256', 'pr_intent_sha256', 'pull_request_node_id_sha256', 'remote_state_sha256'):
            _hex64(getattr(self, name), name=name)
        _hex40(self.authorized_base_sha, name='authorized_base_sha')
        _hex40(self.head_sha, name='head_sha')
        if self.merge_commit_sha is not None:
            _hex40(self.merge_commit_sha, name='merge_commit_sha')
        if self.merge_response_sha256 is not None:
            _hex64(self.merge_response_sha256, name='merge_response_sha256')
        if self.transaction_key_sha256 != self.execution_nonce_sha256:
            raise PilotExactTaskMergeRecoveryError('recovery transaction key must equal execution nonce')
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None or not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None:
            raise PilotExactTaskMergeRecoveryError('recovery repository identity is invalid')
        _branch(self.base_branch, name='base_branch')
        _branch(self.head_branch, name='head_branch')
        if isinstance(self.pull_request_number, bool) or not isinstance(self.pull_request_number, int) or self.pull_request_number < 1 or self.pull_request_api_url != f'{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/{self.pull_request_number}' or self.merge_method != 'squash':
            raise PilotExactTaskMergeRecoveryError('recovery target identity is invalid')
        if self.durable_transaction_state not in {'lock_only', 'merged_marked'}:
            raise PilotExactTaskMergeRecoveryError('recovery durable state is invalid')
        if self.remote_merge_state not in {'open_unmerged_exact', 'merged_exact'}:
            raise PilotExactTaskMergeRecoveryError('recovery remote state is invalid')
        if self.action_required not in {'manual_intervention', 'finalize_exact_merge'}:
            raise PilotExactTaskMergeRecoveryError('recovery action is invalid')
        if self.manual_intervention_required is not (self.action_required == 'manual_intervention'):
            raise PilotExactTaskMergeRecoveryError('manual recovery flag is inconsistent')
        if self.merged_marker_present is not (self.durable_transaction_state == 'merged_marked'):
            raise PilotExactTaskMergeRecoveryError('merged marker flag is inconsistent')
        if self.remote_merge_state == 'open_unmerged_exact':
            if self.action_required != 'manual_intervention' or self.merge_commit_sha is not None or self.merge_response_sha256 is not None or self.merged_marker_present:
                raise PilotExactTaskMergeRecoveryError('open recovery state cannot be auto-finalized')
        elif self.action_required != 'finalize_exact_merge' or self.merge_commit_sha is None:
            raise PilotExactTaskMergeRecoveryError('merged recovery state lacks exact merge identity')
        elif self.merged_marker_present and self.merge_response_sha256 is None:
            raise PilotExactTaskMergeRecoveryError('merged marker recovery lacks response hash')
        elif not self.merged_marker_present and self.merge_response_sha256 is not None:
            raise PilotExactTaskMergeRecoveryError('lock-only recovery cannot invent merge response hash')
        _utc(self.observed_at_utc, name='observed_at_utc')

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @property
    def fingerprint_sha256(self) -> str:
        data = self.to_dict()
        data.pop('observed_at_utc')
        return hashlib.sha256(_canonical(data).encode('utf-8')).hexdigest()


def _observe_verified_recovery_state(*, execution_nonce_sha256: str, transaction_ledger_root: Path, merge_authorization_ledger_root: Path, transport: Any, now_provider: Callable[[], str]) -> tuple[PilotExactTaskMergeRecoveryState, PilotExactTaskMergeAuthorizationReceipt]:
    key = _hex64(execution_nonce_sha256, name='execution_nonce_sha256')
    authorization, _authorization_payload = _load_durable_authorization(key=key, merge_authorization_ledger_root=merge_authorization_ledger_root)
    ledger = tx_boundary._PilotExactTaskMergeTransactionLedger(transaction_ledger_root)
    final, lock, merged = ledger._paths(key)
    if final.exists() or final.is_symlink():
        raise PilotExactTaskMergeRecoveryError('ADR-DC-060 transaction already completed; recovery is not applicable')
    lock_raw, lock_payload = _read_canonical_object(lock, name='ADR-DC-060 transaction lock')
    _pre_state_sha, _fresh_readiness_sha, credential_config_sha, credential_path_sha = _validate_transaction_lock(lock_raw, payload=lock_payload, key=key, authorization=authorization, transaction_ledger_root_sha256=ledger.root_sha256)
    if transport is None or not callable(getattr(transport, 'observe', None)):
        raise PilotExactTaskMergeRecoveryError('read-only merge recovery observer is required')
    if getattr(transport, 'credential_config_sha256', None) != credential_config_sha or getattr(transport, 'credential_path_sha256', None) != credential_path_sha:
        raise PilotExactTaskMergeRecoveryError('recovery credential identity differs from ADR-DC-060 lock')
    merged_present = merged.exists() or merged.is_symlink()
    marker_sha = hashlib.sha256(_canonical({'present': False}).encode('utf-8')).hexdigest()
    marker_merge_sha = None
    marker_response_sha = None
    if merged_present:
        merged_raw, merged_payload = _read_canonical_object(merged, name='ADR-DC-060 merged marker')
        marker_merge_sha, marker_response_sha, _marker_time = _validate_merged_marker(merged_raw, key=key, authorization=authorization)
        marker_sha = hashlib.sha256(_canonical({'present': True, 'payload_sha256': _payload_sha256(merged_payload)}).encode('utf-8')).hexdigest()
    remote = transport.observe(authorization)
    if type(remote) is not _MergeRecoveryRemoteState:
        raise PilotExactTaskMergeRecoveryError('merge recovery observer returned invalid state')
    if remote.repository != authorization.repository or remote.repository_id != authorization.repository_id or remote.base_branch != authorization.base_branch or remote.head_branch != authorization.head_branch or remote.head_sha != authorization.head_sha or remote.pull_request_number != authorization.pull_request_number or remote.pull_request_api_url != authorization.pull_request_api_url or remote.pull_request_node_id_sha256 != authorization.pull_request_node_id_sha256:
        raise PilotExactTaskMergeRecoveryError('remote recovery state differs from durable merge authority')
    if remote.state == 'open':
        if merged_present:
            raise PilotExactTaskMergeRecoveryError('merged marker exists but GitHub PR is still open')
        durable_state = 'lock_only'
        remote_state = 'open_unmerged_exact'
        action = 'manual_intervention'
        merge_commit_sha = None
        merge_response_sha = None
    else:
        merge_commit_sha = _hex40(remote.merge_commit_sha, name='remote merge commit SHA')
        if remote.merge_commit_parent_sha != authorization.base_sha:
            raise PilotExactTaskMergeRecoveryError('remote squash merge parent differs from authorized base')
        if merged_present:
            if marker_merge_sha != merge_commit_sha:
                raise PilotExactTaskMergeRecoveryError('merged marker commit differs from GitHub merge commit')
            durable_state = 'merged_marked'
            merge_response_sha = marker_response_sha
        else:
            durable_state = 'lock_only'
            merge_response_sha = None
        remote_state = 'merged_exact'
        action = 'finalize_exact_merge'
    observed_at = now_provider()
    _utc(observed_at, name='observed_at_utc')
    state = PilotExactTaskMergeRecoveryState(transaction_key_sha256=key, transaction_lock_sha256=_payload_sha256(lock_payload), source_merged_marker_state_sha256=marker_sha, merge_authorization_sha256=authorization.sha256, merge_readiness_evaluation_sha256=authorization.merge_readiness_evaluation_sha256, merge_readiness_policy_sha256=authorization.merge_readiness_policy_sha256, merge_config_sha256=authorization.merge_config_sha256, execution_nonce_sha256=authorization.execution_nonce_sha256, development_task_sha256=authorization.development_task_sha256, candidate_patch_sha256=authorization.candidate_patch_sha256, pr_intent_sha256=authorization.pr_intent_sha256, repository=authorization.repository, repository_id=authorization.repository_id, base_branch=authorization.base_branch, authorized_base_sha=authorization.base_sha, head_branch=authorization.head_branch, head_sha=authorization.head_sha, pull_request_number=authorization.pull_request_number, pull_request_api_url=authorization.pull_request_api_url, pull_request_node_id_sha256=authorization.pull_request_node_id_sha256, merge_method=authorization.merge_method, durable_transaction_state=durable_state, remote_merge_state=remote_state, action_required=action, manual_intervention_required=action == 'manual_intervention', merged_marker_present=merged_present, merge_commit_sha=merge_commit_sha, merge_response_sha256=merge_response_sha, remote_state_sha256=remote.sha256, observed_at_utc=observed_at)
    return (state, authorization)


def _build_recovery_payload(*, state: PilotExactTaskMergeRecoveryState, requested_at_utc: str, expires_at_utc: str, operator_actor_id: str, operator_system_id: str, operator_key_id: str, reviewer_actor_id: str, reviewer_system_id: str, reviewer_key_id: str) -> bytes:
    if type(state) is not PilotExactTaskMergeRecoveryState:
        raise PilotExactTaskMergeRecoveryError('exact merge recovery state is required')
    if state.action_required != 'finalize_exact_merge' or state.manual_intervention_required is not False:
        raise PilotExactTaskMergeRecoveryError('manual merge recovery state cannot mint automatic recovery authority')
    identities = (('operator_actor_id', operator_actor_id), ('operator_system_id', operator_system_id), ('operator_key_id', operator_key_id), ('reviewer_actor_id', reviewer_actor_id), ('reviewer_system_id', reviewer_system_id), ('reviewer_key_id', reviewer_key_id))
    for name, value in identities:
        pattern = _ACTOR if name.endswith('actor_id') else _IDENTIFIER
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            raise PilotExactTaskMergeRecoveryError(f'{name} is invalid')
    if operator_actor_id == reviewer_actor_id or operator_system_id == reviewer_system_id or operator_key_id == reviewer_key_id:
        raise PilotExactTaskMergeRecoveryError('merge recovery requires independent operator/reviewer identities')
    requested = _utc(requested_at_utc, name='requested_at_utc')
    expires = _utc(expires_at_utc, name='expires_at_utc')
    if not requested < expires or (expires - requested).total_seconds() > _MAX_AUTH_SECONDS:
        raise PilotExactTaskMergeRecoveryError('merge recovery authorization window is invalid')
    return _canonical({'schema': PILOT_EXACT_TASK_MERGE_RECOVERY_PAYLOAD_SCHEMA, 'recovery_policy_sha256': pilot_exact_task_merge_recovery_policy_sha256(), 'custody_policy_sha256': asymmetric_authority_key_custody_policy_sha256(), 'transaction_key_sha256': state.transaction_key_sha256, 'recovery_state_fingerprint_sha256': state.fingerprint_sha256, 'action': state.action_required, 'merge_authorization_sha256': state.merge_authorization_sha256, 'merge_readiness_evaluation_sha256': state.merge_readiness_evaluation_sha256, 'merge_readiness_policy_sha256': state.merge_readiness_policy_sha256, 'merge_config_sha256': state.merge_config_sha256, 'execution_nonce_sha256': state.execution_nonce_sha256, 'development_task_sha256': state.development_task_sha256, 'candidate_patch_sha256': state.candidate_patch_sha256, 'pr_intent_sha256': state.pr_intent_sha256, 'repository': state.repository, 'repository_id': state.repository_id, 'base_branch': state.base_branch, 'authorized_base_sha': state.authorized_base_sha, 'head_branch': state.head_branch, 'head_sha': state.head_sha, 'pull_request_number': state.pull_request_number, 'pull_request_api_url': state.pull_request_api_url, 'pull_request_node_id_sha256': state.pull_request_node_id_sha256, 'merge_method': state.merge_method, 'merge_commit_sha': state.merge_commit_sha, 'operator_actor_id': operator_actor_id, 'operator_system_id': operator_system_id, 'operator_key_id': operator_key_id, 'reviewer_actor_id': reviewer_actor_id, 'reviewer_system_id': reviewer_system_id, 'reviewer_key_id': reviewer_key_id, 'requested_at_utc': requested_at_utc, 'expires_at_utc': expires_at_utc}).encode('utf-8')


def build_pilot_exact_task_merge_recovery_payload(state: PilotExactTaskMergeRecoveryState, requested_at_utc: str, expires_at_utc: str, operator_actor_id: str, operator_system_id: str, operator_key_id: str, reviewer_actor_id: str, reviewer_system_id: str, reviewer_key_id: str) -> bytes:
    """Build exact bytes for two independent merge-recovery signers."""
    return _build_recovery_payload(state=state, requested_at_utc=requested_at_utc, expires_at_utc=expires_at_utc, operator_actor_id=operator_actor_id, operator_system_id=operator_system_id, operator_key_id=operator_key_id, reviewer_actor_id=reviewer_actor_id, reviewer_system_id=reviewer_system_id, reviewer_key_id=reviewer_key_id)


def _parse_recovery_payload(payload: bytes) -> dict[str, Any]:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_ARTIFACT_BYTES:
        raise PilotExactTaskMergeRecoveryError('merge recovery authorization payload is invalid')
    try:
        raw = json.loads(payload.decode('utf-8', errors='strict'))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskMergeRecoveryError('merge recovery payload is invalid JSON') from exc
    expected = {'schema', 'recovery_policy_sha256', 'custody_policy_sha256', 'transaction_key_sha256', 'recovery_state_fingerprint_sha256', 'action', 'merge_authorization_sha256', 'merge_readiness_evaluation_sha256', 'merge_readiness_policy_sha256', 'merge_config_sha256', 'execution_nonce_sha256', 'development_task_sha256', 'candidate_patch_sha256', 'pr_intent_sha256', 'repository', 'repository_id', 'base_branch', 'authorized_base_sha', 'head_branch', 'head_sha', 'pull_request_number', 'pull_request_api_url', 'pull_request_node_id_sha256', 'merge_method', 'merge_commit_sha', 'operator_actor_id', 'operator_system_id', 'operator_key_id', 'reviewer_actor_id', 'reviewer_system_id', 'reviewer_key_id', 'requested_at_utc', 'expires_at_utc'}
    if not isinstance(raw, dict) or set(raw) != expected or raw.get('schema') != PILOT_EXACT_TASK_MERGE_RECOVERY_PAYLOAD_SCHEMA or raw.get('recovery_policy_sha256') != pilot_exact_task_merge_recovery_policy_sha256() or raw.get('custody_policy_sha256') != asymmetric_authority_key_custody_policy_sha256() or raw.get('action') != 'finalize_exact_merge' or raw.get('merge_method') != 'squash' or _canonical(raw).encode('utf-8') != payload:
        raise PilotExactTaskMergeRecoveryError('merge recovery payload fields/canonical form mismatch')
    return raw


def _verify_dual_signatures(*, payload: bytes, operator_signature: DetachedEd25519AuthoritySignature, reviewer_signature: DetachedEd25519AuthoritySignature, verifier: Ed25519AuthorityVerifier, at_utc: str) -> dict[str, Any]:
    claim = _parse_recovery_payload(payload)
    if type(operator_signature) is not DetachedEd25519AuthoritySignature or type(reviewer_signature) is not DetachedEd25519AuthoritySignature:
        raise PilotExactTaskMergeRecoveryError('two detached Ed25519 merge recovery signatures are required')
    if operator_signature.key_id == reviewer_signature.key_id or operator_signature.issuer_actor_id == reviewer_signature.issuer_actor_id or operator_signature.issuer_system_id == reviewer_signature.issuer_system_id:
        raise PilotExactTaskMergeRecoveryError('merge recovery signatures must be independent')
    now = _utc(at_utc, name='recovery_at_utc')
    requested = _utc(claim['requested_at_utc'], name='requested_at_utc')
    expires = _utc(claim['expires_at_utc'], name='expires_at_utc')
    if not requested <= now < expires:
        raise PilotExactTaskMergeRecoveryError('merge recovery authorization is not currently valid')
    payload_sha = hashlib.sha256(payload).hexdigest()
    bindings = ((operator_signature, claim['operator_actor_id'], claim['operator_system_id'], claim['operator_key_id']), (reviewer_signature, claim['reviewer_actor_id'], claim['reviewer_system_id'], claim['reviewer_key_id']))
    for signature, actor_id, system_id, key_id in bindings:
        if signature.payload_sha256 != payload_sha or signature.issuer_actor_id != actor_id or signature.issuer_system_id != system_id or signature.key_id != key_id:
            raise PilotExactTaskMergeRecoveryError('merge recovery signature binding mismatch')
        signed = _utc(signature.signed_at_utc, name='signed_at_utc')
        if not requested <= signed < expires or signed > now:
            raise PilotExactTaskMergeRecoveryError('merge recovery signature timestamp is outside authorization window')
        try:
            verifier.verify(payload=payload, signature=signature, at_utc=at_utc)
        except AsymmetricAuthorityError as exc:
            raise PilotExactTaskMergeRecoveryError('merge recovery Ed25519 verification failed') from exc
    return claim

@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskMergeRecoveryReceipt:
    recovery_ledger_root_path_sha256: str
    recovery_key_sha256: str
    recovery_authorization_payload_sha256: str
    recovery_state_fingerprint_sha256: str
    recovery_policy_sha256: str
    transaction_lock_sha256: str
    source_merged_marker_state_sha256: str
    merge_authorization_sha256: str
    merge_readiness_evaluation_sha256: str
    merge_readiness_policy_sha256: str
    merge_config_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    repository: str
    repository_id: str
    base_branch: str
    authorized_base_sha: str
    head_branch: str
    head_sha: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_node_id_sha256: str
    merge_method: str
    durable_transaction_state: str
    source_merged_marker_present: bool
    source_merge_response_sha256: str | None
    merge_commit_sha: str
    final_remote_state_sha256: str
    operator_actor_id: str
    operator_system_id: str
    operator_key_id: str
    reviewer_actor_id: str
    reviewer_system_id: str
    reviewer_key_id: str
    requested_at_utc: str
    expires_at_utc: str
    observed_at_utc: str
    recovered_at_utc: str
    recovery_guard_committed: bool = True
    dual_external_ed25519_authorized: bool = True
    exact_remote_merge_verified: bool = True
    exact_base_parent_verified: bool = True
    transaction_finalization_recovered: bool = True
    merged: bool = True
    merge_authorized: bool = False
    remote_write_authorized: bool = False
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
    recovery_scope: str = PILOT_EXACT_TASK_MERGE_RECOVERY_SCOPE
    authority: str = PILOT_EXACT_TASK_MERGE_RECOVERY_AUTHORITY
    schema: str = PILOT_EXACT_TASK_MERGE_RECOVERY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_MERGE_RECOVERY_SCHEMA or self.authority != PILOT_EXACT_TASK_MERGE_RECOVERY_AUTHORITY or self.recovery_scope != PILOT_EXACT_TASK_MERGE_RECOVERY_SCOPE:
            raise PilotExactTaskMergeRecoveryError('merge recovery receipt identity is unsupported')
        for name in ('recovery_ledger_root_path_sha256', 'recovery_key_sha256', 'recovery_authorization_payload_sha256', 'recovery_state_fingerprint_sha256', 'recovery_policy_sha256', 'transaction_lock_sha256', 'source_merged_marker_state_sha256', 'merge_authorization_sha256', 'merge_readiness_evaluation_sha256', 'merge_readiness_policy_sha256', 'merge_config_sha256', 'execution_nonce_sha256', 'development_task_sha256', 'candidate_patch_sha256', 'pr_intent_sha256', 'pull_request_node_id_sha256', 'final_remote_state_sha256'):
            _hex64(getattr(self, name), name=name)
        if self.source_merge_response_sha256 is not None:
            _hex64(self.source_merge_response_sha256, name='source_merge_response_sha256')
        for name in ('authorized_base_sha', 'head_sha', 'merge_commit_sha'):
            _hex40(getattr(self, name), name=name)
        if self.recovery_key_sha256 != self.execution_nonce_sha256:
            raise PilotExactTaskMergeRecoveryError('recovery key must equal execution nonce')
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None or not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None:
            raise PilotExactTaskMergeRecoveryError('recovery receipt repository identity is invalid')
        _branch(self.base_branch, name='base_branch')
        _branch(self.head_branch, name='head_branch')
        if isinstance(self.pull_request_number, bool) or not isinstance(self.pull_request_number, int) or self.pull_request_number < 1 or self.pull_request_api_url != f'{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/{self.pull_request_number}' or self.merge_method != 'squash' or self.durable_transaction_state not in {'lock_only', 'merged_marked'} or self.source_merged_marker_present is not (self.durable_transaction_state == 'merged_marked'):
            raise PilotExactTaskMergeRecoveryError('recovery receipt target/durable state is invalid')
        if self.source_merged_marker_present is not (self.source_merge_response_sha256 is not None):
            raise PilotExactTaskMergeRecoveryError('source merged marker response binding is inconsistent')
        for name in ('operator_actor_id', 'reviewer_actor_id'):
            value = getattr(self, name)
            if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
                raise PilotExactTaskMergeRecoveryError(f'{name} is invalid')
        for name in ('operator_system_id', 'operator_key_id', 'reviewer_system_id', 'reviewer_key_id'):
            value = getattr(self, name)
            if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
                raise PilotExactTaskMergeRecoveryError(f'{name} is invalid')
        if self.operator_actor_id == self.reviewer_actor_id or self.operator_system_id == self.reviewer_system_id or self.operator_key_id == self.reviewer_key_id:
            raise PilotExactTaskMergeRecoveryError('recovery receipt signers are not independent')
        requested = _utc(self.requested_at_utc, name='requested_at_utc')
        expires = _utc(self.expires_at_utc, name='expires_at_utc')
        observed = _utc(self.observed_at_utc, name='observed_at_utc')
        recovered = _utc(self.recovered_at_utc, name='recovered_at_utc')
        if not requested <= observed <= recovered < expires:
            raise PilotExactTaskMergeRecoveryError('recovery receipt timestamps are invalid')
        required_true = ('recovery_guard_committed', 'dual_external_ed25519_authorized', 'exact_remote_merge_verified', 'exact_base_parent_verified', 'transaction_finalization_recovered', 'merged')
        if any((getattr(self, name) is not True for name in required_true)):
            raise PilotExactTaskMergeRecoveryError('recovery receipt completion evidence is incomplete')
        forced_false = ('merge_authorized', 'remote_write_authorized', 'review_submission_authorized', 'review_thread_mutation_authorized', 'ready_for_review_authorized', 'reviewer_request_authorized', 'push_authorized', 'pr_mutation_authorized', 'release_authorized', 'deploy_authorized', 'production_activation_authorized', 'product_pilot_started', 'nonce_reusable')
        if any((getattr(self, name) is not False for name in forced_false)):
            raise PilotExactTaskMergeRecoveryError('merge recovery retains forbidden authority')

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode('utf-8')).hexdigest()

    @property
    def recovery_authenticated(self) -> bool:
        return _get_live_merge_recovery_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any) -> 'PilotExactTaskMergeRecoveryReceipt':
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskMergeRecoveryError('merge recovery receipt fields mismatch')
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskMergeRecoveryLedger:
    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path]:
        digest = _hex64(key, name='recovery_key_sha256')
        return (self.root / f'{digest}.json', self.root / f'.{digest}.lock')

    def acquire(self, *, state: PilotExactTaskMergeRecoveryState, authorization_payload: bytes, operator_signature: DetachedEd25519AuthoritySignature, reviewer_signature: DetachedEd25519AuthoritySignature) -> bytes:
        final, lock = self._paths(state.execution_nonce_sha256)
        if final.exists() or final.is_symlink() or lock.exists() or lock.is_symlink():
            raise PilotExactTaskMergeRecoveryError('merge recovery nonce already consumed')
        payload = _canonical({'schema': 'kaliv-rsi-dc-l16-exact-task-merge-recovery-lock/v1', 'ledger_scope': PILOT_EXACT_TASK_MERGE_RECOVERY_LEDGER_SCOPE, 'ledger_root_path_sha256': self.root_sha256, 'recovery_key_sha256': state.execution_nonce_sha256, 'recovery_state_fingerprint_sha256': state.fingerprint_sha256, 'recovery_authorization_payload_sha256': hashlib.sha256(authorization_payload).hexdigest(), 'merge_authorization_sha256': state.merge_authorization_sha256, 'merge_commit_sha': state.merge_commit_sha, 'operator_signature_sha256': hashlib.sha256(operator_signature.canonical_json().encode('utf-8')).hexdigest(), 'reviewer_signature_sha256': hashlib.sha256(reviewer_signature.canonical_json().encode('utf-8')).hexdigest()}).encode('utf-8')
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskMergeRecoveryError('merge recovery authorization could not be durably consumed') from exc
        return payload

    def commit(self, *, receipt: PilotExactTaskMergeRecoveryReceipt, lock_payload: bytes) -> PilotExactTaskMergeRecoveryReceipt:
        final, lock = self._paths(receipt.recovery_key_sha256)
        if final.exists() or final.is_symlink() or _read_bytes(lock) != lock_payload:
            raise PilotExactTaskMergeRecoveryError('merge recovery durable state changed before finalization')
        payload = receipt.canonical_json().encode('utf-8')
        try:
            create_once_file(final, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskMergeRecoveryError('merge recovery receipt could not be durably published') from exc
        parsed = PilotExactTaskMergeRecoveryReceipt.from_mapping(json.loads(payload.decode('utf-8')))
        _mark_merge_recovery_authenticated(parsed, final_path=final, final_payload=payload, lock_path=lock, lock_payload=lock_payload)
        if parsed.recovery_authenticated is not True:
            raise PilotExactTaskMergeRecoveryError('merge recovery lost live provenance')
        return parsed


def _live_registry():
    records = {}

    def mark(receipt, *, final_path, final_payload, lock_path, lock_payload):
        key = id(receipt)

        def cleanup(_):
            records.pop(key, None)
        records[key] = (os.getpid(), receipt.sha256, weakref.ref(receipt, cleanup), final_path, final_payload, lock_path, lock_payload)

    def get(receipt):
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, final_path, final_payload, lock_path, lock_payload = entry
        if pid != os.getpid() or receipt_ref() is not receipt or receipt.sha256 != digest or _read_bytes(final_path) != final_payload or _read_bytes(lock_path) != lock_payload:
            return None
        return MappingProxyType({'recovery_key_sha256': receipt.recovery_key_sha256})
    if hasattr(os, 'register_at_fork'):
        os.register_at_fork(after_in_child=records.clear)
    return (mark, get)

_mark_merge_recovery_authenticated, _get_live_merge_recovery_inputs = _live_registry()


def _recover_verified_pilot_exact_task_merge(*, authorization_payload: bytes, operator_signature: DetachedEd25519AuthoritySignature, reviewer_signature: DetachedEd25519AuthoritySignature, verifier: Ed25519AuthorityVerifier, transaction_ledger_root: Path, merge_authorization_ledger_root: Path, recovery_ledger: _PilotExactTaskMergeRecoveryLedger, transport: Any, now_provider: Callable[[], str]) -> PilotExactTaskMergeRecoveryReceipt:
    verified_at = now_provider()
    claim = _verify_dual_signatures(payload=authorization_payload, operator_signature=operator_signature, reviewer_signature=reviewer_signature, verifier=verifier, at_utc=verified_at)
    state, authorization = _observe_verified_recovery_state(execution_nonce_sha256=claim['execution_nonce_sha256'], transaction_ledger_root=transaction_ledger_root, merge_authorization_ledger_root=merge_authorization_ledger_root, transport=transport, now_provider=lambda: verified_at)
    if state.action_required != 'finalize_exact_merge' or state.manual_intervention_required is not False or state.fingerprint_sha256 != claim['recovery_state_fingerprint_sha256'] or state.merge_authorization_sha256 != claim['merge_authorization_sha256'] or state.merge_commit_sha != claim['merge_commit_sha'] or state.repository != claim['repository'] or state.repository_id != claim['repository_id'] or state.base_branch != claim['base_branch'] or state.authorized_base_sha != claim['authorized_base_sha'] or state.head_branch != claim['head_branch'] or state.head_sha != claim['head_sha'] or state.pull_request_number != claim['pull_request_number'] or state.pull_request_api_url != claim['pull_request_api_url'] or state.pull_request_node_id_sha256 != claim['pull_request_node_id_sha256']:
        raise PilotExactTaskMergeRecoveryError('signed merge recovery state no longer matches exact durable/remote state')
    lock_payload = recovery_ledger.acquire(state=state, authorization_payload=authorization_payload, operator_signature=operator_signature, reviewer_signature=reviewer_signature)
    current, current_authorization = _observe_verified_recovery_state(execution_nonce_sha256=state.execution_nonce_sha256, transaction_ledger_root=transaction_ledger_root, merge_authorization_ledger_root=merge_authorization_ledger_root, transport=transport, now_provider=now_provider)
    if current.fingerprint_sha256 != state.fingerprint_sha256 or current.action_required != 'finalize_exact_merge' or current_authorization.sha256 != authorization.sha256:
        raise PilotExactTaskMergeRecoveryError('merge recovery state changed after durable recovery lock')
    recovered_at = now_provider()
    if _utc(recovered_at, name='recovered_at_utc') < _utc(current.observed_at_utc, name='observed_at_utc'):
        raise PilotExactTaskMergeRecoveryError('system clock moved backwards during merge recovery')
    receipt = PilotExactTaskMergeRecoveryReceipt(recovery_ledger_root_path_sha256=recovery_ledger.root_sha256, recovery_key_sha256=state.execution_nonce_sha256, recovery_authorization_payload_sha256=hashlib.sha256(authorization_payload).hexdigest(), recovery_state_fingerprint_sha256=state.fingerprint_sha256, recovery_policy_sha256=pilot_exact_task_merge_recovery_policy_sha256(), transaction_lock_sha256=state.transaction_lock_sha256, source_merged_marker_state_sha256=state.source_merged_marker_state_sha256, merge_authorization_sha256=state.merge_authorization_sha256, merge_readiness_evaluation_sha256=state.merge_readiness_evaluation_sha256, merge_readiness_policy_sha256=state.merge_readiness_policy_sha256, merge_config_sha256=state.merge_config_sha256, execution_nonce_sha256=state.execution_nonce_sha256, development_task_sha256=state.development_task_sha256, candidate_patch_sha256=state.candidate_patch_sha256, pr_intent_sha256=state.pr_intent_sha256, repository=state.repository, repository_id=state.repository_id, base_branch=state.base_branch, authorized_base_sha=state.authorized_base_sha, head_branch=state.head_branch, head_sha=state.head_sha, pull_request_number=state.pull_request_number, pull_request_api_url=state.pull_request_api_url, pull_request_node_id_sha256=state.pull_request_node_id_sha256, merge_method=state.merge_method, durable_transaction_state=state.durable_transaction_state, source_merged_marker_present=state.merged_marker_present, source_merge_response_sha256=state.merge_response_sha256, merge_commit_sha=_hex40(state.merge_commit_sha, name='merge_commit_sha'), final_remote_state_sha256=current.remote_state_sha256, operator_actor_id=claim['operator_actor_id'], operator_system_id=claim['operator_system_id'], operator_key_id=claim['operator_key_id'], reviewer_actor_id=claim['reviewer_actor_id'], reviewer_system_id=claim['reviewer_system_id'], reviewer_key_id=claim['reviewer_key_id'], requested_at_utc=claim['requested_at_utc'], expires_at_utc=claim['expires_at_utc'], observed_at_utc=current.observed_at_utc, recovered_at_utc=recovered_at)
    return recovery_ledger.commit(receipt=receipt, lock_payload=lock_payload)


def _canonical_runtime():
    try:
        _require_elevated_operator()
        if os.name == 'posix':
            tx_root = _require_host_controlled_ledger_root(tx_boundary._POSIX_LEDGER)
            auth_root = _require_host_controlled_ledger_root(auth_boundary._POSIX_LEDGER)
            recovery_root = _require_host_controlled_ledger_root(_POSIX_LEDGER)
            keyring_path = _POSIX_KEYRING
        elif os.name == 'nt':
            tx_root = _require_host_controlled_ledger_root(tx_boundary._WINDOWS_LEDGER)
            auth_root = _require_host_controlled_ledger_root(auth_boundary._WINDOWS_LEDGER)
            recovery_root = _require_host_controlled_ledger_root(_WINDOWS_LEDGER)
            keyring_path = _WINDOWS_KEYRING
        else:
            raise PilotExactTaskMergeRecoveryError('merge recovery platform is unsupported')
        keyring_first = _read_host_authority_file(keyring_path)
        keyring_second = _read_host_authority_file(keyring_path)
        if keyring_first != keyring_second:
            raise PilotExactTaskMergeRecoveryError('merge recovery keyring changed while being read')
        verifier, _keyring_sha = _parse_keyring(keyring_second)
        credential, digest, path = publication_tx_boundary._canonical_credential()
        observer = _GitHubMergeRecoveryObserver(credential=credential, credential_config_sha256=digest, credential_path=path)
        return (tx_root, auth_root, _PilotExactTaskMergeRecoveryLedger(recovery_root), verifier, observer)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskMergeRecoveryError('merge recovery runtime is not host-admin controlled') from exc


def observe_pilot_exact_task_merge_recovery_state(execution_nonce_sha256: str) -> PilotExactTaskMergeRecoveryState:
    """Observe durable/remote merge recovery state without mutating GitHub."""
    tx_root, auth_root, _recovery_ledger, _verifier, observer = _canonical_runtime()
    state, _authorization = _observe_verified_recovery_state(execution_nonce_sha256=execution_nonce_sha256, transaction_ledger_root=tx_root, merge_authorization_ledger_root=auth_root, transport=observer, now_provider=_now_utc_seconds)
    return state


def recover_pilot_exact_task_merge(authorization_payload: bytes, operator_signature: DetachedEd25519AuthoritySignature, reviewer_signature: DetachedEd25519AuthoritySignature) -> PilotExactTaskMergeRecoveryReceipt:
    """Finalize only an already-executed exact merge; never retry the merge."""
    tx_root, auth_root, recovery_ledger, verifier, observer = _canonical_runtime()
    return _recover_verified_pilot_exact_task_merge(authorization_payload=authorization_payload, operator_signature=operator_signature, reviewer_signature=reviewer_signature, verifier=verifier, transaction_ledger_root=tx_root, merge_authorization_ledger_root=auth_root, recovery_ledger=recovery_ledger, transport=observer, now_provider=_now_utc_seconds)

__all__: list[str] = []
