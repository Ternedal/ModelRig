"""Adversarial contract for ADR-DC-045 local-commit authorization admission."""
from __future__ import annotations
import hashlib
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / 'tests' / 'support'
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / 'devcontrol' / 'src'
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))
from kaliv_dev_control import improvement_pilot_exact_task_local_commit_authorization as authorization
from kaliv_dev_control import improvement_pilot_exact_task_local_commit_authorization_admission as admission
from kaliv_dev_control import improvement_pilot_exact_task_local_commit_authorization_requirements as requirements
from kaliv_dev_control import improvement_pilot_exact_task_local_commit_object_identity as identity_boundary
from rsi_pilot_exact_task_execution_plan_contract import _git_reader
from rsi_pilot_exact_task_local_commit_authorization_requirements_contract import _live_identity
from rsi_pilot_exact_task_local_commit_human_authorization_contract import ISSUER, _authority
from rsi_pilot_exact_task_local_commit_object_identity_contract import _identity_reader
SCHEMA = ROOT / 'devcontrol' / 'schemas' / 'rsi-pilot-exact-task-local-commit-authorization-admission-receipt-v1.schema.json'

def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError('ADR-DC-045 unexpectedly accepted invalid authority')

def _source():
    source_temp, admission_ledger_temp, capability_temp, reservation_temp, execution_temp, evaluation, execution_receipt, execution_plan, local_plan, identity, task, fixture, staged = _live_identity()
    _calls, reader = _git_reader(workspace=fixture['workspace'], base_sha=task.base_sha, staged=staged)
    with patch.object(fixture['git_runner'], 'run', side_effect=reader):
        manifest = requirements._build_verified_pilot_exact_task_local_commit_authorization_requirements(object_identity=identity, now_provider=lambda: '2026-09-15T05:32:00Z')
    nonce = hashlib.sha256(b'adr-dc-045-local-commit-nonce').hexdigest()
    claim = authorization.build_pilot_exact_task_local_commit_authorization(authorization_requirements=manifest, authorization_id='local-commit-authorization-045', local_commit_authorizer_actor_id=ISSUER, authorized_at_utc='2026-09-15T05:33:00Z', expires_at_utc='2026-09-15T05:40:00Z', local_commit_nonce_sha256=nonce, notes=('admit exact predicted commit once',))
    _trusted, signature, verifier = _authority(claim)
    supplied = authorization._verify_pilot_exact_task_local_commit_authorization(authorization=claim, signature=signature, verifier=verifier, now_provider=lambda: '2026-09-15T05:34:00Z')
    fresh = authorization._verify_pilot_exact_task_local_commit_authorization(authorization=claim, signature=signature, verifier=verifier, now_provider=lambda: '2026-09-15T05:34:01Z')
    return (source_temp, admission_ledger_temp, capability_temp, reservation_temp, execution_temp, supplied, fresh, signature, verifier, manifest, identity, task, fixture, staged)

def run_contract() -> None:
    if os.name == 'nt':
        return
    source_temp, admission_ledger_temp, capability_temp, reservation_temp, execution_temp, supplied, fresh, signature, verifier, manifest, identity, task, fixture, staged = _source()
    local_ledger_temp = tempfile.TemporaryDirectory(prefix='rsi-local-commit-auth-admission-')
    try:
        ledger_root = Path(local_ledger_temp.name).resolve()
        ledger = admission._PilotExactTaskLocalCommitAuthorizationAdmissionLedger(ledger_root)
        index_payload = f"100644 {'1' * 40} 0\tVERSION\x00".encode('ascii')
        calls, reader = _identity_reader(workspace=fixture['workspace'], base_sha=task.base_sha, staged=staged, index_payload=index_payload)
        times = iter(('2026-09-15T05:34:02Z', '2026-09-15T05:34:03Z'))
        with patch.object(fixture['git_runner'], 'run', side_effect=reader):
            receipt = admission._admit_verified_pilot_exact_task_local_commit_authorization(supplied_proof=supplied, fresh_proof=fresh, object_identity=identity, ledger=ledger, now_provider=lambda: next(times))
        assert len(calls) == 17
        assert receipt.admission_authenticated is True
        assert receipt.admission_key_sha256 == supplied.local_commit_nonce_sha256
        assert receipt.local_commit_nonce_sha256 == supplied.local_commit_nonce_sha256
        assert receipt.authorization_proof_sha256 == supplied.sha256
        assert receipt.authorization_sha256 == supplied.authorization_sha256
        assert receipt.authorization_signature_sha256 == signature.sha256
        assert receipt.authorization_requirements_sha256 == manifest.sha256
        assert receipt.requirements_key_sha256 == manifest.requirements_key_sha256
        assert receipt.local_commit_object_identity_sha256 == identity.sha256
        assert receipt.local_commit_plan_sha256 == identity.local_commit_plan_sha256
        assert receipt.development_task_sha256 == identity.development_task_sha256
        assert receipt.task_id == identity.task_id
        assert receipt.repository == identity.repository
        assert receipt.base_sha == identity.base_sha
        assert receipt.root_tree_sha == identity.root_tree_sha
        assert receipt.predicted_commit_sha == identity.predicted_commit_sha
        assert receipt.commit_payload_sha256 == identity.commit_payload_sha256
        assert receipt.index_manifest_sha256 == identity.index_manifest_sha256
        assert receipt.index_entry_count == identity.index_entry_count
        assert receipt.commit_subject_sha256 == identity.commit_subject_sha256
        assert receipt.fresh_verified_at_utc == fresh.verified_at_utc
        assert receipt.admitted_at_utc == '2026-09-15T05:34:03Z'
        assert receipt.host_replay_guard_committed is True
        assert receipt.human_local_commit_authorization_verified is True
        assert receipt.local_commit_authorization_admitted is True
        assert receipt.local_commit_authorization_consumed is False
        assert receipt.one_shot_local_commit_required is True
        assert receipt.exact_object_identity_revalidated is True
        assert receipt.fresh_workspace_snapshot_matched is True
        assert receipt.git_object_write_authorized is False
        assert receipt.local_ref_update_authorized is False
        assert receipt.local_commit_authorized is False
        assert receipt.local_commit_created is False
        assert receipt.push_authorized is False
        assert receipt.production_activation_authorized is False
        reloaded = admission.PilotExactTaskLocalCommitAuthorizationAdmissionReceipt.from_mapping(receipt.to_dict())
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.admission_authenticated is False
        replay_calls, replay_reader = _identity_reader(workspace=fixture['workspace'], base_sha=task.base_sha, staged=staged, index_payload=index_payload)
        replay_times = iter(('2026-09-15T05:34:04Z', '2026-09-15T05:34:05Z'))
        with patch.object(fixture['git_runner'], 'run', side_effect=replay_reader):
            _reject(lambda: admission._admit_verified_pilot_exact_task_local_commit_authorization(supplied_proof=supplied, fresh_proof=fresh, object_identity=identity, ledger=ledger, now_provider=lambda: next(replay_times)))
        assert replay_calls
        for field, value in (('host_replay_guard_committed', False), ('local_commit_authorization_admitted', False), ('local_commit_authorization_consumed', True), ('git_object_write_authorized', True), ('local_ref_update_authorized', True), ('local_commit_authorized', True), ('local_commit_created', True), ('push_authorized', True), ('production_activation_authorized', True), ('predicted_commit_sha', 'a' * 40), ('admission_key_sha256', 'b' * 64)):
            _reject(lambda field=field, value=value: admission.PilotExactTaskLocalCommitAuthorizationAdmissionReceipt.from_mapping({**receipt.to_dict(), field: value}))
        reloaded_identity = identity_boundary.PilotExactTaskLocalCommitObjectIdentity.from_mapping(identity.to_dict())
        assert reloaded_identity.identity_authenticated is False
        other_ledger_temp = tempfile.TemporaryDirectory(prefix='rsi-local-commit-auth-admission-reloaded-')
        try:
            _reject(lambda: admission._admit_verified_pilot_exact_task_local_commit_authorization(supplied_proof=supplied, fresh_proof=fresh, object_identity=reloaded_identity, ledger=admission._PilotExactTaskLocalCommitAuthorizationAdmissionLedger(Path(other_ledger_temp.name).resolve()), now_provider=lambda: '2026-09-15T05:34:06Z'))
        finally:
            other_ledger_temp.cleanup()
        schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
        assert set(schema['properties']) == set(receipt.to_dict())
        assert set(schema['required']) == set(receipt.to_dict())
        assert schema['properties']['local_commit_authorization_admitted']['const'] is True
        assert schema['properties']['local_commit_authorization_consumed']['const'] is False
        assert schema['properties']['git_object_write_authorized']['const'] is False
        assert schema['properties']['local_ref_update_authorized']['const'] is False
        assert schema['properties']['local_commit_authorized']['const'] is False
        assert schema['properties']['local_commit_created']['const'] is False
        assert schema['properties']['production_activation_authorized']['const'] is False
        public_parameters = inspect.signature(admission.admit_pilot_exact_task_local_commit_authorization).parameters
        assert tuple(public_parameters) == ('authorization_proof', 'authorization_signature', 'object_identity')
        impl_source = inspect.getsource(sys.modules['kaliv_dev_control._improvement_pilot_exact_task_local_commit_authorization_admission_impl'])
        assert 'create_once_file(' in impl_source
        assert '_read_object_format(' in impl_source
        assert '_read_index_manifest(' in impl_source
        assert 'subprocess' not in impl_source
        assert 'shell=True' not in impl_source
        assert '"write-tree"' not in impl_source
        assert '"commit-tree"' not in impl_source
        assert '("commit",' not in impl_source
        assert '("update-ref",' not in impl_source
        assert '("push",' not in impl_source
        assert '("reset",' not in impl_source
        assert '("clean",' not in impl_source
    finally:
        local_ledger_temp.cleanup()
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()
if __name__ == '__main__':
    run_contract()
