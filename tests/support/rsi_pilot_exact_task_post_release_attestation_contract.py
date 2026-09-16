"""Adversarial contract for ADR-DC-069 exact post-release attestation."""
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
from source_code import code_of  # noqa: E402

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_post_release_attestation as post_release,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_release_recovery as recovery,
)
from rsi_pilot_exact_task_post_merge_attestation_contract import _cleanup_case  # noqa: E402
from rsi_pilot_exact_task_release_authorization_contract import _dual_authority  # noqa: E402
import rsi_pilot_exact_task_release_recovery_contract as recovery_contract  # noqa: E402
import rsi_pilot_exact_task_release_transaction_contract_base as tx_contract  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-post-release-attestation-v1.schema.json"
SOURCE = ROOT / "devcontrol" / "src" / "kaliv_dev_control" / "improvement_pilot_exact_task_post_release_attestation.py"


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-069 unexpectedly accepted unsafe post-release state")


class _Observer:
    def __init__(self, authority, release_id, node_hash, *, state_class="exact_existing"):
        self.authority = authority
        self.release_id = release_id
        self.node_hash = node_hash
        self.state_class = state_class
        self.credential_config_sha256 = authority.publisher_credential_config_sha256
        self.credential_path_sha256 = authority.publisher_credential_path_sha256
        self.calls = 0

    def observe(self, authority):
        self.calls += 1
        assert authority.sha256 == self.authority.sha256
        if self.state_class == "clear":
            return recovery._ReleaseRecoveryRemoteState(repository=authority.repository, repository_id=authority.repository_id, tag_state="absent", tag_target_sha=None, release_state="absent", release_id=None, release_node_id_sha256=None, remote_state_class="clear")
        return recovery._ReleaseRecoveryRemoteState(repository=authority.repository, repository_id=authority.repository_id, tag_state="exact", tag_target_sha=authority.tag_target_sha, release_state="exact-draft", release_id=self.release_id, release_node_id_sha256=self.node_hash, remote_state_class="exact_existing")


def _recovery_root(prefix: str):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, root


def _attest(authority, auth_temp, tx_temp, recovery_root, observer, now):
    return post_release._attest_verified_pilot_exact_task_post_release(execution_nonce_sha256=authority.execution_nonce_sha256, transaction_ledger_root=Path(tx_temp.name) / "ledger", recovery_ledger_root=recovery_root, release_authorization_ledger_root=Path(auth_temp.name) / "ledger", transport=observer, now_provider=lambda: now)


def run_contract() -> None:
    if os.name == "nt":
        return

    case, auth_temp, plan, authority = tx_contract._live_authority()
    tx_temp, tx_ledger = tx_contract._ledger("rsi-exact-task-post-release-tx-")
    recovery_temp, recovery_root = _recovery_root("rsi-exact-task-post-release-empty-")
    try:
        tx_transport = tx_contract._Transport(plan, authority)
        tx_receipt = tx_contract._execute(authority, tx_transport, tx_ledger)
        observer = _Observer(authority, tx_receipt.release_id, tx_receipt.release_node_id_sha256)
        receipt = _attest(authority, auth_temp, tx_temp, recovery_root, observer, "2026-09-15T09:45:00Z")
        assert receipt.attestation_authenticated is True
        assert receipt.completion_source == "transaction"
        assert receipt.completion_source_receipt_sha256 == tx_receipt.sha256
        assert receipt.source_action == "execute_exact_release"
        assert receipt.source_remote_write_performed is True
        assert receipt.release_id == tx_receipt.release_id
        assert receipt.release_node_id_sha256 == tx_receipt.release_node_id_sha256
        assert receipt.exact_remote_release_verified is True
        assert receipt.post_release_verified is True
        assert observer.calls == 2
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False

        reloaded = post_release.PilotExactTaskPostReleaseAttestationReceipt.from_mapping(receipt.to_dict())
        assert reloaded == receipt
        assert reloaded.attestation_authenticated is False

        drift = _Observer(authority, tx_receipt.release_id, tx_receipt.release_node_id_sha256, state_class="clear")
        _reject(lambda: _attest(authority, auth_temp, tx_temp, recovery_root, drift, "2026-09-15T09:45:01Z"))
        cred = _Observer(authority, tx_receipt.release_id, tx_receipt.release_node_id_sha256)
        cred.credential_config_sha256 = "9" * 64
        _reject(lambda: _attest(authority, auth_temp, tx_temp, recovery_root, cred, "2026-09-15T09:45:01Z"))
        _reject(lambda: _attest(authority, auth_temp, tx_temp, recovery_root, observer, "2026-09-15T09:44:00Z"))
    finally:
        recovery_temp.cleanup(); tx_temp.cleanup(); auth_temp.cleanup(); _cleanup_case(case)

    case, auth_temp, _plan, authority = tx_contract._live_authority()
    tx_temp, _tx = recovery_contract._open_tx(authority, release_marker=True)
    rec_temp, rec_ledger = recovery_contract._ledger("rsi-exact-task-post-release-recovery-")
    try:
        transport = recovery_contract._Transport(authority, state_class="exact_existing")
        state = recovery_contract._inspect(authority, auth_temp, tx_temp, transport)
        payload = recovery_contract._payload(state)
        verifier, op_sig, review_sig = _dual_authority(payload, signed_at="2026-09-15T09:45:10Z")
        recovery_receipt = recovery_contract._recover(authority, auth_temp, tx_temp, transport, rec_ledger, payload, verifier, op_sig, review_sig)
        observer = _Observer(authority, recovery_receipt.release_id, recovery_receipt.release_node_id_sha256)
        receipt = _attest(authority, auth_temp, tx_temp, Path(rec_temp.name) / "ledger", observer, "2026-09-15T09:46:00Z")
        assert receipt.completion_source == "recovery"
        assert receipt.completion_source_receipt_sha256 == recovery_receipt.sha256
        assert receipt.recovery_lock_sha256 is not None
        assert receipt.source_action == "finalize_existing_state"
        assert receipt.source_remote_write_performed is False
        assert receipt.release_id == recovery_receipt.release_id
        assert receipt.release_node_id_sha256 == recovery_receipt.release_node_id_sha256
    finally:
        rec_temp.cleanup(); tx_temp.cleanup(); auth_temp.cleanup(); _cleanup_case(case)

    case, auth_temp, _plan, authority = tx_contract._live_authority()
    tx_temp, _tx = recovery_contract._open_tx(authority)
    recovery_temp, recovery_root = _recovery_root("rsi-exact-task-post-release-none-")
    try:
        _reject(lambda: _attest(authority, auth_temp, tx_temp, recovery_root, _Observer(authority, 8801, "d" * 64), "2026-09-15T09:46:00Z"))
    finally:
        recovery_temp.cleanup(); tx_temp.cleanup(); auth_temp.cleanup(); _cleanup_case(case)

    case, auth_temp, plan, authority = tx_contract._live_authority()
    tx_temp, tx_ledger = tx_contract._ledger("rsi-exact-task-post-release-tamper-")
    recovery_temp, recovery_root = _recovery_root("rsi-exact-task-post-release-tamper-rec-")
    try:
        tx_transport = tx_contract._Transport(plan, authority)
        tx_receipt = tx_contract._execute(authority, tx_transport, tx_ledger)
        receipt = _attest(authority, auth_temp, tx_temp, recovery_root, _Observer(authority, tx_receipt.release_id, tx_receipt.release_node_id_sha256), "2026-09-15T09:46:00Z")
        for field, value in (("durable_completion_verified", False), ("exact_remote_release_verified", False), ("exact_tag_target_verified", False), ("exact_draft_release_verified", False), ("double_observation_matched", False), ("post_release_verified", False), ("tag_write_authorized", True), ("release_mutation_authorized", True), ("release_authorized", True), ("remote_write_authorized", True), ("merge_authorized", True), ("push_authorized", True), ("pr_mutation_authorized", True), ("review_submission_authorized", True), ("review_thread_mutation_authorized", True), ("deploy_authorized", True), ("production_activation_authorized", True), ("product_pilot_started", True), ("nonce_reusable", True)):
            _reject(lambda field=field, value=value: post_release.PilotExactTaskPostReleaseAttestationReceipt.from_mapping({**receipt.to_dict(), field: value}))

        schema = json.loads(code_of(SCHEMA))
        receipt_fields = set(post_release.PilotExactTaskPostReleaseAttestationReceipt.__dataclass_fields__)
        assert set(schema["properties"]) == receipt_fields
        assert set(schema["required"]) == receipt_fields
        assert len(receipt_fields) == 61

        signature = inspect.signature(post_release.attest_pilot_exact_task_post_release)
        assert list(signature.parameters) == ["execution_nonce_sha256"]

        source_text = code_of(SOURCE)
        assert 'method="POST"' not in source_text
        assert 'method="PUT"' not in source_text
        assert 'method="PATCH"' not in source_text
        assert 'method="DELETE"' not in source_text
        assert "create_tag(" not in source_text
        assert "create_release(" not in source_text
        assert "merge_pull_request" not in source_text
        assert "enable_auto_merge" not in source_text
    finally:
        recovery_temp.cleanup(); tx_temp.cleanup(); auth_temp.cleanup(); _cleanup_case(case)


if __name__ == "__main__":
    run_contract()
