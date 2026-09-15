"""Adversarial contract for ADR-DC-068 exact release recovery."""
from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_release_recovery as recovery,
)
from rsi_pilot_exact_task_post_merge_attestation_contract import (  # noqa: E402
    _cleanup_case,
)
from rsi_pilot_exact_task_release_authorization_contract import (  # noqa: E402
    _dual_authority,
)
from rsi_pilot_exact_task_release_transaction_contract import (  # noqa: E402
    _ledger as _tx_ledger,
    _live_authority,
)

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-release-recovery-v1.schema.json"
SOURCE = ROOT / "devcontrol" / "src" / "kaliv_dev_control" / "improvement_pilot_exact_task_release_recovery.py"


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-068 unexpectedly accepted unsafe release recovery")


def _ledger(prefix: str):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, recovery._PilotExactTaskReleaseRecoveryLedger(root)


class _Transport:
    def __init__(self, authority, *, state_class: str, fail_release: bool = False, scripted: list[str] | None = None):
        self.authority = authority
        self.credential_config_sha256 = authority.publisher_credential_config_sha256
        self.credential_path_sha256 = authority.publisher_credential_path_sha256
        self.state_class = state_class
        self.fail_release = fail_release
        self.scripted = list(scripted or ())
        self.release_id = 8801
        self.node_hash = "d" * 64
        self.calls: list[str] = []

    def _state(self, state_class: str):
        if state_class == "clear":
            return recovery._ReleaseRecoveryRemoteState(repository=self.authority.repository, repository_id=self.authority.repository_id, tag_state="absent", tag_target_sha=None, release_state="absent", release_id=None, release_node_id_sha256=None, remote_state_class="clear")
        if state_class == "tag_only":
            return recovery._ReleaseRecoveryRemoteState(repository=self.authority.repository, repository_id=self.authority.repository_id, tag_state="exact", tag_target_sha=self.authority.tag_target_sha, release_state="absent", release_id=None, release_node_id_sha256=None, remote_state_class="tag_only")
        if state_class == "exact_existing":
            return recovery._ReleaseRecoveryRemoteState(repository=self.authority.repository, repository_id=self.authority.repository_id, tag_state="exact", tag_target_sha=self.authority.tag_target_sha, release_state="exact-draft", release_id=self.release_id, release_node_id_sha256=self.node_hash, remote_state_class="exact_existing")
        raise AssertionError("unsupported recovery test state")

    def observe(self, authority):
        self.calls.append("observe")
        assert authority.sha256 == self.authority.sha256
        state = self.scripted.pop(0) if self.scripted else self.state_class
        return self._state(state)

    def create_release(self, authority):
        self.calls.append("create_release")
        assert authority.sha256 == self.authority.sha256
        if self.fail_release:
            raise ValueError("simulated recovery release failure")
        self.state_class = "exact_existing"
        return self.release_id, self.node_hash


def _roots(auth_temp, tx_temp):
    return Path(auth_temp.name) / "ledger", Path(tx_temp.name) / "ledger"


def _inspect(authority, auth_temp, tx_temp, transport, *, now="2026-09-15T09:45:00Z"):
    auth_root, tx_root = _roots(auth_temp, tx_temp)
    return recovery._observe_verified_recovery_state(execution_nonce_sha256=authority.execution_nonce_sha256, transaction_ledger_root=tx_root, release_authorization_ledger_root=auth_root, transport=transport, now_provider=lambda: now)[0]


def _payload(state):
    return recovery._build_recovery_payload(state=state, requested_at_utc="2026-09-15T09:45:00Z", expires_at_utc="2026-09-15T09:50:00Z", operator_actor_id="release.operator", operator_system_id="offline-release-operator", operator_key_id="release-op-1", reviewer_actor_id="release.reviewer", reviewer_system_id="offline-release-reviewer", reviewer_key_id="release-review-1")


def _recover(authority, auth_temp, tx_temp, transport, recovery_ledger, payload, verifier, op_sig, review_sig, *, now="2026-09-15T09:45:20Z"):
    auth_root, tx_root = _roots(auth_temp, tx_temp)
    return recovery._recover_verified_pilot_exact_task_release(authorization_payload=payload, operator_signature=op_sig, reviewer_signature=review_sig, verifier=verifier, transaction_ledger_root=tx_root, release_authorization_ledger_root=auth_root, recovery_ledger=recovery_ledger, transport=transport, now_provider=lambda: now)


def _open_tx(authority, *, tag_marker=False, release_marker=False):
    tx_temp, tx_ledger = _tx_ledger("rsi-exact-task-release-recovery-tx-")
    lock = tx_ledger.acquire(authorization=authority, locked_at_utc="2026-09-15T09:44:31Z")
    tag = None
    if tag_marker or release_marker:
        tag = tx_ledger.mark_tag(authorization=authority, lock_payload=lock, tag_created_at_utc="2026-09-15T09:44:32Z")
    if release_marker:
        assert tag is not None
        tx_ledger.mark_release(authorization=authority, lock_payload=lock, tag_marker_payload=tag, release_id=8801, release_node_id_sha256="d" * 64, release_created_at_utc="2026-09-15T09:44:33Z")
    return tx_temp, tx_ledger


def run_contract() -> None:
    if os.name == "nt":
        return

    case, auth_temp, _plan, authority = _live_authority()
    tx_temp, _tx = _open_tx(authority)
    try:
        manual = _inspect(authority, auth_temp, tx_temp, _Transport(authority, state_class="clear"))
        assert manual.durable_phase == "lock_only"
        assert manual.remote_state_class == "clear"
        assert manual.action_required == "manual_intervention"
        assert manual.manual_intervention_required is True
        assert manual.remote_write_required is False
        _reject(lambda: _payload(manual))
    finally:
        tx_temp.cleanup(); auth_temp.cleanup(); _cleanup_case(case)

    case, auth_temp, _plan, authority = _live_authority()
    tx_temp, _tx = _open_tx(authority)
    rec_temp, rec_ledger = _ledger("rsi-exact-task-release-recovery-")
    try:
        transport = _Transport(authority, state_class="tag_only")
        state = _inspect(authority, auth_temp, tx_temp, transport)
        assert state.durable_phase == "lock_only"
        assert state.action_required == "create_missing_release"
        payload = _payload(state)
        verifier, op_sig, review_sig = _dual_authority(payload, signed_at="2026-09-15T09:45:10Z")
        receipt = _recover(authority, auth_temp, tx_temp, transport, rec_ledger, payload, verifier, op_sig, review_sig)
        assert receipt.recovery_authenticated is True
        assert receipt.source_remote_state_class == "tag_only"
        assert receipt.action_performed == "create_missing_release"
        assert receipt.remote_write_performed is True
        assert transport.calls.count("create_release") == 1
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        reloaded = recovery.PilotExactTaskReleaseRecoveryReceipt.from_mapping(receipt.to_dict())
        assert reloaded == receipt
        assert reloaded.recovery_authenticated is False
        _reject(lambda: _recover(authority, auth_temp, tx_temp, transport, rec_ledger, payload, verifier, op_sig, review_sig))
    finally:
        rec_temp.cleanup(); tx_temp.cleanup(); auth_temp.cleanup(); _cleanup_case(case)

    case, auth_temp, _plan, authority = _live_authority()
    tx_temp, _tx = _open_tx(authority, release_marker=True)
    rec_temp, rec_ledger = _ledger("rsi-exact-task-release-recovery-finalize-")
    try:
        transport = _Transport(authority, state_class="exact_existing")
        state = _inspect(authority, auth_temp, tx_temp, transport)
        assert state.durable_phase == "release_marked"
        assert state.action_required == "finalize_existing_state"
        payload = _payload(state)
        verifier, op_sig, review_sig = _dual_authority(payload, signed_at="2026-09-15T09:45:10Z")
        receipt = _recover(authority, auth_temp, tx_temp, transport, rec_ledger, payload, verifier, op_sig, review_sig)
        assert receipt.remote_write_performed is False
        assert "create_release" not in transport.calls
    finally:
        rec_temp.cleanup(); tx_temp.cleanup(); auth_temp.cleanup(); _cleanup_case(case)

    case, auth_temp, _plan, authority = _live_authority()
    tx_temp, _tx = _open_tx(authority)
    try:
        transport = _Transport(authority, state_class="tag_only")
        transport.credential_config_sha256 = "9" * 64
        _reject(lambda: _inspect(authority, auth_temp, tx_temp, transport))
    finally:
        tx_temp.cleanup(); auth_temp.cleanup(); _cleanup_case(case)

    case, auth_temp, _plan, authority = _live_authority()
    tx_temp, _tx = _open_tx(authority)
    rec_temp, rec_ledger = _ledger("rsi-exact-task-release-recovery-drift-")
    try:
        transport = _Transport(authority, state_class="tag_only", scripted=["tag_only", "tag_only"])
        state = _inspect(authority, auth_temp, tx_temp, transport)
        payload = _payload(state)
        verifier, op_sig, review_sig = _dual_authority(payload, signed_at="2026-09-15T09:45:10Z")
        transport.scripted = ["tag_only", "tag_only", "clear", "clear"]
        _reject(lambda: _recover(authority, auth_temp, tx_temp, transport, rec_ledger, payload, verifier, op_sig, review_sig))
        final, lock = rec_ledger._paths(authority.execution_nonce_sha256)
        assert lock.exists() and not final.exists()
        assert "create_release" not in transport.calls
    finally:
        rec_temp.cleanup(); tx_temp.cleanup(); auth_temp.cleanup(); _cleanup_case(case)

    case, auth_temp, _plan, authority = _live_authority()
    tx_temp, _tx = _open_tx(authority, tag_marker=True)
    rec_temp, rec_ledger = _ledger("rsi-exact-task-release-recovery-write-fail-")
    try:
        transport = _Transport(authority, state_class="tag_only", fail_release=True)
        state = _inspect(authority, auth_temp, tx_temp, transport)
        payload = _payload(state)
        verifier, op_sig, review_sig = _dual_authority(payload, signed_at="2026-09-15T09:45:10Z")
        _reject(lambda: _recover(authority, auth_temp, tx_temp, transport, rec_ledger, payload, verifier, op_sig, review_sig))
        final, lock = rec_ledger._paths(authority.execution_nonce_sha256)
        assert lock.exists() and not final.exists()
    finally:
        rec_temp.cleanup(); tx_temp.cleanup(); auth_temp.cleanup(); _cleanup_case(case)

    case, auth_temp, _plan, authority = _live_authority()
    tx_temp, _tx = _open_tx(authority, release_marker=True)
    rec_temp, rec_ledger = _ledger("rsi-exact-task-release-recovery-tamper-")
    try:
        transport = _Transport(authority, state_class="exact_existing")
        state = _inspect(authority, auth_temp, tx_temp, transport)
        payload = _payload(state)
        verifier, op_sig, review_sig = _dual_authority(payload, signed_at="2026-09-15T09:45:10Z")
        receipt = _recover(authority, auth_temp, tx_temp, transport, rec_ledger, payload, verifier, op_sig, review_sig)
        for field, value in (("durable_state_verified", False), ("remote_state_verified", False), ("dual_external_ed25519_authorized", False), ("recovery_authority_consumed", False), ("exact_release_finalized", False), ("recovery_completed", False), ("tag_write_authorized", True), ("release_mutation_authorized", True), ("release_authorized", True), ("remote_write_authorized", True), ("merge_authorized", True), ("push_authorized", True), ("pr_mutation_authorized", True), ("review_submission_authorized", True), ("review_thread_mutation_authorized", True), ("deploy_authorized", True), ("production_activation_authorized", True), ("product_pilot_started", True), ("nonce_reusable", True)):
            _reject(lambda field=field, value=value: recovery.PilotExactTaskReleaseRecoveryReceipt.from_mapping({**receipt.to_dict(), field: value}))
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        receipt_fields = set(recovery.PilotExactTaskReleaseRecoveryReceipt.__dataclass_fields__)
        assert set(schema["properties"]) == receipt_fields
        assert set(schema["required"]) == receipt_fields
        assert len(receipt_fields) == 63
        inspect_sig = inspect.signature(recovery.inspect_pilot_exact_task_release_recovery)
        assert list(inspect_sig.parameters) == ["execution_nonce_sha256"]
        recover_sig = inspect.signature(recovery.recover_pilot_exact_task_release)
        assert list(recover_sig.parameters) == ["authorization_payload", "operator_signature", "reviewer_signature"]
        source_text = SOURCE.read_text(encoding="utf-8")
        assert "create_tag(" not in source_text
        assert "/git/refs" not in source_text
        assert 'method="PUT"' not in source_text
        assert 'method="PATCH"' not in source_text
        assert 'method="DELETE"' not in source_text
        assert "merge_pull_request" not in source_text
        assert "enable_auto_merge" not in source_text
    finally:
        rec_temp.cleanup(); tx_temp.cleanup(); auth_temp.cleanup(); _cleanup_case(case)


if __name__ == "__main__":
    run_contract()
