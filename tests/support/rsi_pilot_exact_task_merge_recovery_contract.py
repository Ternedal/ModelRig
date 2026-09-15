"""Adversarial contract for ADR-DC-061 exact merge recovery/finalization."""
from __future__ import annotations
import hashlib
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / 'tests' / 'support'
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / 'devcontrol' / 'src'
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from kaliv_dev_control.asymmetric_authority import DetachedEd25519AuthoritySignature, Ed25519AuthorityVerifier, TrustedEd25519AuthorityKey, asymmetric_authority_key_custody_policy_sha256, authority_signing_message
from kaliv_dev_control import improvement_pilot_exact_task_merge_recovery as recovery
from kaliv_dev_control import improvement_pilot_exact_task_merge_transaction as merge_tx
from rsi_pilot_exact_task_merge_transaction_contract import _Transport as _MergeTransport, _live_merge_authorization, _transaction_ledger
from rsi_pilot_exact_task_pr_lifecycle_recovery_contract import _cleanup_bundle
SCHEMA = ROOT / 'devcontrol' / 'schemas' / 'rsi-pilot-exact-task-merge-recovery-v1.schema.json'

def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError('ADR-DC-061 unexpectedly accepted unsafe merge recovery')

def _recovery_ledger(prefix: str):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / 'ledger'
    root.mkdir()
    return (temp, recovery._PilotExactTaskMergeRecoveryLedger(root))

class _RecoveryTransport:
    def __init__(self, authorization, *, merged: bool, merge_sha: str | None=None):
        self.authorization = authorization
        self.credential_config_sha256 = 'a' * 64
        self.credential_path_sha256 = 'b' * 64
        self.merge_sha = merge_sha or 'c' * 40
        if self.merge_sha in {authorization.base_sha, authorization.head_sha}:
            self.merge_sha = 'd' * 40
        self.merged = merged
        self.scripted = []
        self.calls = []

    def _state(self, *, merged=None, merge_sha=None):
        is_merged = self.merged if merged is None else merged
        sha = self.merge_sha if merge_sha is None else merge_sha
        return recovery._MergeRecoveryRemoteState(repository=self.authorization.repository, repository_id=self.authorization.repository_id, base_branch=self.authorization.base_branch, base_ref_sha=sha if is_merged else self.authorization.base_sha, head_branch=self.authorization.head_branch, head_sha=self.authorization.head_sha, pull_request_number=self.authorization.pull_request_number, pull_request_api_url=self.authorization.pull_request_api_url, pull_request_node_id_sha256=self.authorization.pull_request_node_id_sha256, state='closed' if is_merged else 'open', draft=False, merged=is_merged, maintainer_can_modify=False, merge_commit_sha=sha if is_merged else None, merge_commit_parent_sha=self.authorization.base_sha if is_merged else None)

    def observe(self, authorization):
        self.calls.append('observe')
        assert authorization.sha256 == self.authorization.sha256
        if self.scripted:
            return self.scripted.pop(0)
        return self._state()

def _acquire_lock(ledger, authorization, evaluation):
    pre = _MergeTransport(authorization)._pre()
    return ledger.acquire(authorization=authorization, pre_state_sha256=pre.sha256, fresh_readiness_sha256=evaluation.sha256, credential_config_sha256='a' * 64, credential_path_sha256='b' * 64)

def _roots(tx_temp, auth_temp):
    return (Path(tx_temp.name) / 'ledger', Path(auth_temp.name) / 'ledger')

def _observe(authorization, tx_temp, auth_temp, transport, *, now='2026-09-15T09:40:00Z'):
    tx_root, auth_root = _roots(tx_temp, auth_temp)
    return recovery._observe_verified_recovery_state(execution_nonce_sha256=authorization.execution_nonce_sha256, transaction_ledger_root=tx_root, merge_authorization_ledger_root=auth_root, transport=transport, now_provider=lambda: now)

def _payload(state):
    return recovery._build_recovery_payload(state=state, requested_at_utc='2026-09-15T09:40:00Z', expires_at_utc='2026-09-15T09:45:00Z', operator_actor_id='merge.recovery.operator', operator_system_id='offline-merge-recovery-operator', operator_key_id='merge-recovery-op-1', reviewer_actor_id='merge.recovery.reviewer', reviewer_system_id='offline-merge-recovery-reviewer', reviewer_key_id='merge-recovery-review-1')

def _dual_authority(payload: bytes, *, signed_at='2026-09-15T09:40:10Z'):
    custody = asymmetric_authority_key_custody_policy_sha256()
    definitions = ((bytes(range(1, 33)), 'merge-recovery-op-1', 'merge.recovery.operator', 'offline-merge-recovery-operator'), (bytes(range(33, 65)), 'merge-recovery-review-1', 'merge.recovery.reviewer', 'offline-merge-recovery-reviewer'))
    keys = {}
    signatures = []
    for raw_private, key_id, actor_id, system_id in definitions:
        private = Ed25519PrivateKey.from_private_bytes(raw_private)
        public = private.public_key().public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
        trusted = TrustedEd25519AuthorityKey(key_id=key_id, issuer_actor_id=actor_id, issuer_system_id=system_id, public_key_hex=public.hex(), valid_from_utc='2026-01-01T00:00:00Z', valid_until_utc='2027-01-01T00:00:00Z', keyring_epoch=1, custody_policy_sha256=custody)
        keys[key_id] = trusted
        message = authority_signing_message(key_id=trusted.key_id, issuer_actor_id=trusted.issuer_actor_id, issuer_system_id=trusted.issuer_system_id, keyring_epoch=trusted.keyring_epoch, custody_policy_sha256=custody, payload=payload)
        signatures.append(DetachedEd25519AuthoritySignature(key_id=trusted.key_id, issuer_actor_id=trusted.issuer_actor_id, issuer_system_id=trusted.issuer_system_id, keyring_epoch=trusted.keyring_epoch, custody_policy_sha256=custody, payload_sha256=hashlib.sha256(payload).hexdigest(), signature_hex=private.sign(message).hex(), signed_at_utc=signed_at))
    return (Ed25519AuthorityVerifier(keys, minimum_keyring_epoch=1), signatures[0], signatures[1])

def _recover(*, payload, op_sig, review_sig, verifier, tx_temp, auth_temp, recovery_ledger, transport, times=('2026-09-15T09:40:20Z', '2026-09-15T09:40:21Z', '2026-09-15T09:40:22Z')):
    tx_root, auth_root = _roots(tx_temp, auth_temp)
    clock = iter(times)
    return recovery._recover_verified_pilot_exact_task_merge(authorization_payload=payload, operator_signature=op_sig, reviewer_signature=review_sig, verifier=verifier, transaction_ledger_root=tx_root, merge_authorization_ledger_root=auth_root, recovery_ledger=recovery_ledger, transport=transport, now_provider=lambda: next(clock))

def run_contract() -> None:
    if os.name == 'nt':
        return
    bundle, upstream_tx_temp, upstream_recovery_temp, auth_temp, _source, _ready_review, _policy, evaluation, authorization = _live_merge_authorization()
    tx_temp, tx_ledger = _transaction_ledger('rsi-exact-task-merge-recovery-source-')
    recovery_temp, recovery_ledger = _recovery_ledger('rsi-exact-task-merge-recovery-')
    try:
        _acquire_lock(tx_ledger, authorization, evaluation)
        transport = _RecoveryTransport(authorization, merged=True)
        state, durable_auth = _observe(authorization, tx_temp, auth_temp, transport)
        assert durable_auth.sha256 == authorization.sha256
        assert durable_auth.authorization_authenticated is False
        assert state.durable_transaction_state == 'lock_only'
        assert state.remote_merge_state == 'merged_exact'
        assert state.action_required == 'finalize_exact_merge'
        assert state.manual_intervention_required is False
        assert state.merged_marker_present is False
        assert state.merge_response_sha256 is None
        assert state.merge_commit_sha == transport.merge_sha
        payload = _payload(state)
        verifier, op_sig, review_sig = _dual_authority(payload)
        receipt = _recover(payload=payload, op_sig=op_sig, review_sig=review_sig, verifier=verifier, tx_temp=tx_temp, auth_temp=auth_temp, recovery_ledger=recovery_ledger, transport=transport)
        assert receipt.recovery_authenticated is True
        assert receipt.recovery_key_sha256 == authorization.execution_nonce_sha256
        assert receipt.merge_authorization_sha256 == authorization.sha256
        assert receipt.merge_commit_sha == transport.merge_sha
        assert receipt.source_merged_marker_present is False
        assert receipt.source_merge_response_sha256 is None
        assert receipt.recovery_guard_committed is True
        assert receipt.dual_external_ed25519_authorized is True
        assert receipt.exact_remote_merge_verified is True
        assert receipt.exact_base_parent_verified is True
        assert receipt.transaction_finalization_recovered is True
        assert receipt.merged is True
        assert receipt.merge_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False
        reloaded = recovery.PilotExactTaskMergeRecoveryReceipt.from_mapping(receipt.to_dict())
        assert reloaded == receipt
        assert reloaded.recovery_authenticated is False
        _reject(lambda: _recover(payload=payload, op_sig=op_sig, review_sig=review_sig, verifier=verifier, tx_temp=tx_temp, auth_temp=auth_temp, recovery_ledger=recovery_ledger, transport=transport))
        manual_tx_temp, manual_ledger = _transaction_ledger('rsi-exact-task-merge-recovery-manual-')
        try:
            _acquire_lock(manual_ledger, authorization, evaluation)
            manual_transport = _RecoveryTransport(authorization, merged=False)
            manual_state, _ = _observe(authorization, manual_tx_temp, auth_temp, manual_transport)
            assert manual_state.durable_transaction_state == 'lock_only'
            assert manual_state.remote_merge_state == 'open_unmerged_exact'
            assert manual_state.action_required == 'manual_intervention'
            assert manual_state.manual_intervention_required is True
            _reject(lambda: _payload(manual_state))
        finally:
            manual_tx_temp.cleanup()
        marked_tx_temp, marked_ledger = _transaction_ledger('rsi-exact-task-merge-recovery-marked-')
        marked_recovery_temp, marked_recovery_ledger = _recovery_ledger('rsi-exact-task-merge-recovery-marked-final-')
        try:
            lock_payload = _acquire_lock(marked_ledger, authorization, evaluation)
            marked_transport = _RecoveryTransport(authorization, merged=True)
            response = {'sha': marked_transport.merge_sha, 'merged': True, 'message': 'Pull Request successfully merged'}
            response_sha = hashlib.sha256(merge_tx._canonical(response).encode('utf-8')).hexdigest()
            marked_ledger.mark_merged(authorization=authorization, lock_payload=lock_payload, merge_commit_sha=marked_transport.merge_sha, merge_response_sha256=response_sha, merged_at_utc='2026-09-15T09:39:50Z')
            marked_state, _ = _observe(authorization, marked_tx_temp, auth_temp, marked_transport)
            assert marked_state.durable_transaction_state == 'merged_marked'
            assert marked_state.merged_marker_present is True
            assert marked_state.merge_response_sha256 == response_sha
            marked_payload = _payload(marked_state)
            marked_verifier, marked_op, marked_review = _dual_authority(marked_payload)
            marked_receipt = _recover(payload=marked_payload, op_sig=marked_op, review_sig=marked_review, verifier=marked_verifier, tx_temp=marked_tx_temp, auth_temp=auth_temp, recovery_ledger=marked_recovery_ledger, transport=marked_transport)
            assert marked_receipt.source_merged_marker_present is True
            assert marked_receipt.source_merge_response_sha256 == response_sha
        finally:
            marked_recovery_temp.cleanup()
            marked_tx_temp.cleanup()
        mismatch_tx_temp, mismatch_ledger = _transaction_ledger('rsi-exact-task-merge-recovery-mismatch-')
        try:
            mismatch_lock = _acquire_lock(mismatch_ledger, authorization, evaluation)
            marker_sha = 'e' * 40
            if marker_sha in {authorization.base_sha, authorization.head_sha, transport.merge_sha}:
                marker_sha = 'f' * 40
            mismatch_ledger.mark_merged(authorization=authorization, lock_payload=mismatch_lock, merge_commit_sha=marker_sha, merge_response_sha256='d' * 64, merged_at_utc='2026-09-15T09:39:50Z')
            _reject(lambda: _observe(authorization, mismatch_tx_temp, auth_temp, _RecoveryTransport(authorization, merged=True, merge_sha=transport.merge_sha)))
        finally:
            mismatch_tx_temp.cleanup()
        drift_tx_temp, drift_ledger = _transaction_ledger('rsi-exact-task-merge-recovery-drift-source-')
        drift_recovery_temp, drift_recovery_ledger = _recovery_ledger('rsi-exact-task-merge-recovery-drift-')
        try:
            _acquire_lock(drift_ledger, authorization, evaluation)
            stable_transport = _RecoveryTransport(authorization, merged=True)
            drift_state, _ = _observe(authorization, drift_tx_temp, auth_temp, stable_transport)
            drift_payload = _payload(drift_state)
            drift_verifier, drift_op, drift_review = _dual_authority(drift_payload)
            drift_transport = _RecoveryTransport(authorization, merged=True)
            drift_transport.scripted = [drift_transport._state(merged=True), drift_transport._state(merged=False)]
            _reject(lambda: _recover(payload=drift_payload, op_sig=drift_op, review_sig=drift_review, verifier=drift_verifier, tx_temp=drift_tx_temp, auth_temp=auth_temp, recovery_ledger=drift_recovery_ledger, transport=drift_transport))
            final, lock = drift_recovery_ledger._paths(authorization.execution_nonce_sha256)
            assert lock.exists()
            assert not final.exists()
        finally:
            drift_recovery_temp.cleanup()
            drift_tx_temp.cleanup()
        signer_temp, signer_ledger = _recovery_ledger('rsi-exact-task-merge-recovery-signer-')
        try:
            _reject(lambda: _recover(payload=payload, op_sig=op_sig, review_sig=op_sig, verifier=verifier, tx_temp=tx_temp, auth_temp=auth_temp, recovery_ledger=signer_ledger, transport=transport))
        finally:
            signer_temp.cleanup()
        expiry_temp, expiry_ledger = _recovery_ledger('rsi-exact-task-merge-recovery-expiry-')
        try:
            _reject(lambda: _recover(payload=payload, op_sig=op_sig, review_sig=review_sig, verifier=verifier, tx_temp=tx_temp, auth_temp=auth_temp, recovery_ledger=expiry_ledger, transport=transport, times=('2026-09-15T09:45:00Z',)))
        finally:
            expiry_temp.cleanup()
        for field, value in (('recovery_guard_committed', False), ('dual_external_ed25519_authorized', False), ('exact_remote_merge_verified', False), ('exact_base_parent_verified', False), ('transaction_finalization_recovered', False), ('merged', False), ('merge_authorized', True), ('remote_write_authorized', True), ('review_submission_authorized', True), ('review_thread_mutation_authorized', True), ('ready_for_review_authorized', True), ('reviewer_request_authorized', True), ('push_authorized', True), ('pr_mutation_authorized', True), ('release_authorized', True), ('deploy_authorized', True), ('production_activation_authorized', True), ('product_pilot_started', True), ('nonce_reusable', True)):
            _reject(lambda field=field, value=value: recovery.PilotExactTaskMergeRecoveryReceipt.from_mapping({**receipt.to_dict(), field: value}))
        schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
        receipt_fields = set(recovery.PilotExactTaskMergeRecoveryReceipt.__dataclass_fields__)
        assert set(schema['properties']) == receipt_fields
        assert set(schema['required']) == receipt_fields
        assert schema['properties']['merge_authorized']['const'] is False
        assert schema['properties']['remote_write_authorized']['const'] is False
        assert schema['properties']['release_authorized']['const'] is False
        assert schema['properties']['production_activation_authorized']['const'] is False
        assert schema['properties']['nonce_reusable']['const'] is False
        build_public = inspect.signature(recovery.build_pilot_exact_task_merge_recovery_payload).parameters
        assert tuple(build_public) == ('state', 'requested_at_utc', 'expires_at_utc', 'operator_actor_id', 'operator_system_id', 'operator_key_id', 'reviewer_actor_id', 'reviewer_system_id', 'reviewer_key_id')
        observe_public = inspect.signature(recovery.observe_pilot_exact_task_merge_recovery_state).parameters
        assert tuple(observe_public) == ('execution_nonce_sha256',)
        recover_public = inspect.signature(recovery.recover_pilot_exact_task_merge).parameters
        assert tuple(recover_public) == ('authorization_payload', 'operator_signature', 'reviewer_signature')
        source_text = inspect.getsource(recovery)
        assert 'method="PUT"' not in source_text
        assert 'merge_pull_request' not in source_text
        assert 'enable_auto_merge' not in source_text
        assert 'subprocess' not in source_text
        assert 'Ed25519PrivateKey' not in source_text
        assert 'merge_authorized: bool = False' in source_text
        assert 'remote_write_authorized: bool = False' in source_text
        assert 'production_activation_authorized: bool = False' in source_text
    finally:
        recovery_temp.cleanup()
        tx_temp.cleanup()
        auth_temp.cleanup()
        upstream_recovery_temp.cleanup()
        upstream_tx_temp.cleanup()
        _cleanup_bundle(bundle)

if __name__ == '__main__':
    run_contract()
