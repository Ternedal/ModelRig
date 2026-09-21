"""Adversarial contract for ADR-DC-051 exact remote-publication recovery."""
from __future__ import annotations

import hashlib
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

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from kaliv_dev_control.asymmetric_authority import (  # noqa: E402
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
    asymmetric_authority_key_custody_policy_sha256,
    authority_signing_message,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_remote_publication_recovery as recovery,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_remote_publication_transaction as transaction,
)
from rsi_pilot_exact_task_remote_publication_transaction_contract import (  # noqa: E402
    _live_authorization,
    _transaction_ledger,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-remote-publication-recovery-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-051 unexpectedly accepted unsafe recovery")


class _RecoveryTransport:
    def __init__(self, *, base_sha: str, head_sha: str | None, repository: str, pr=None, drift_after=0):
        self.base_sha = base_sha
        self.head_sha = head_sha
        self.repository = repository
        self.pr = pr
        self.calls = []
        self.drift_after = drift_after

    def observe(self, intent):
        self.calls.append(("observe", intent.pr_intent_sha256))
        if self.drift_after and len([c for c in self.calls if c[0] == "observe"]) > self.drift_after:
            return {"base_sha": intent.base_sha, "head_sha": None, "pull_request": None}
        return {"base_sha": self.base_sha, "head_sha": self.head_sha, "pull_request": self.pr}

    def create_draft_pr(self, intent):
        self.calls.append(("create-pr", intent.pr_intent_sha256))
        number = 5151
        self.pr = {
            "number": number,
            "api_url": f"https://api.github.com/repos/{intent.repository}/pulls/{number}",
        }
        return dict(self.pr)


def _authority(payload: bytes):
    custody = asymmetric_authority_key_custody_policy_sha256()
    fixtures = []
    for seed, key_id, actor, system, signed_at in (
        (bytes(range(1, 33)), "recovery-operator-key", "recovery.operator", "recovery-operator-host", "2026-09-15T08:40:11Z"),
        (bytes(range(33, 65)), "recovery-reviewer-key", "recovery.reviewer", "recovery-reviewer-host", "2026-09-15T08:40:12Z"),
    ):
        private = Ed25519PrivateKey.from_private_bytes(seed)
        public = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        trusted = TrustedEd25519AuthorityKey(
            key_id=key_id,
            issuer_actor_id=actor,
            issuer_system_id=system,
            public_key_hex=public.hex(),
            valid_from_utc="2026-01-01T00:00:00Z",
            valid_until_utc="2027-01-01T00:00:00Z",
            keyring_epoch=1,
            custody_policy_sha256=custody,
        )
        message = authority_signing_message(
            key_id=key_id,
            issuer_actor_id=actor,
            issuer_system_id=system,
            keyring_epoch=1,
            custody_policy_sha256=custody,
            payload=payload,
        )
        signature = DetachedEd25519AuthoritySignature(
            key_id=key_id,
            issuer_actor_id=actor,
            issuer_system_id=system,
            keyring_epoch=1,
            custody_policy_sha256=custody,
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            signature_hex=private.sign(message).hex(),
            signed_at_utc=signed_at,
        )
        fixtures.append((trusted, signature))
    verifier = Ed25519AuthorityVerifier(
        {trusted.key_id: trusted for trusted, _signature in fixtures},
        minimum_keyring_epoch=1,
    )
    return verifier, fixtures[0][1], fixtures[1][1]


def _roots(auth_temp, local_transaction_temp):
    return Path(auth_temp.name) / "ledger", Path(local_transaction_temp.name) / "ledger"


def _payload(state):
    return recovery.build_pilot_exact_task_remote_publication_recovery_payload(
        state,
        state.action_required,
        "2026-09-15T08:40:10Z",
        "2026-09-15T08:45:00Z",
        "recovery.operator",
        "recovery-operator-host",
        "recovery-operator-key",
        "recovery.reviewer",
        "recovery-reviewer-host",
        "recovery-reviewer-key",
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    live = _live_authorization()
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        local_auth_temp,
        local_transaction_temp,
        auth_temp,
        identity,
        local_transaction,
        mechanical,
        ready,
        task,
        fixture,
        index_payload,
        commit_payload,
        plan,
        observation,
        authorization,
        good,
    ) = live
    del mechanical, ready, task, fixture, index_payload, commit_payload, observation, good
    tx_temp, tx_ledger = _transaction_ledger("rsi-exact-task-remote-recovery-tx-")
    recovery_temp = tempfile.TemporaryDirectory(prefix="rsi-exact-task-remote-recovery-ledger-")
    recovery_root = Path(recovery_temp.name) / "ledger"
    recovery_root.mkdir()
    recovery_ledger = recovery._PilotExactTaskRemotePublicationRecoveryLedger(recovery_root)
    auth_root, local_root = _roots(auth_temp, local_transaction_temp)
    try:
        # Simulate crash after the exact push reached GitHub but before ADR-DC-050
        # could persist its pushed marker. The transaction lock remains durable.
        lock_payload = tx_ledger.acquire(authorization=authorization, plan=plan)
        assert lock_payload
        remote = _RecoveryTransport(
            base_sha=plan.base_sha,
            head_sha=plan.predicted_commit_sha,
            repository=plan.repository,
        )
        state, reconstructed = recovery._observe_verified_recovery_state(
            execution_nonce_sha256=authorization.execution_nonce_sha256,
            transaction_ledger_root=tx_ledger.root,
            authorization_ledger_root=auth_root,
            local_transaction_ledger_root=local_root,
            transport=remote,
            now_provider=lambda: "2026-09-15T08:40:00Z",
        )
        assert state.durable_transaction_state == "lock_only"
        assert state.remote_head_state == "exact"
        assert state.action_required == "create_missing_pr"
        assert state.manual_intervention_required is False
        assert reconstructed.pr_intent_sha256 == authorization.pr_intent_sha256
        assert reconstructed.root_tree_sha == identity.root_tree_sha
        assert reconstructed.pr_title == plan.pr_title
        assert reconstructed.pr_body == plan.pr_body

        payload = _payload(state)
        verifier, operator_signature, reviewer_signature = _authority(payload)
        times = iter(("2026-09-15T08:40:20Z", "2026-09-15T08:40:21Z", "2026-09-15T08:40:22Z", "2026-09-15T08:40:23Z", "2026-09-15T08:40:24Z"))
        receipt = recovery._recover_verified_pilot_exact_task_remote_publication(
            authorization_payload=payload,
            operator_signature=operator_signature,
            reviewer_signature=reviewer_signature,
            verifier=verifier,
            transaction_ledger_root=tx_ledger.root,
            authorization_ledger_root=auth_root,
            local_transaction_ledger_root=local_root,
            recovery_ledger=recovery_ledger,
            transport=remote,
            now_provider=lambda: next(times),
        )
        assert receipt.recovery_authenticated is True
        assert receipt.recovery_action == "create_missing_pr"
        assert receipt.durable_transaction_state == "lock_only"
        assert receipt.remote_write_performed is True
        assert receipt.pull_request_number == 5151
        assert receipt.predicted_commit_sha == plan.predicted_commit_sha
        assert receipt.root_tree_sha == identity.root_tree_sha
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False
        assert [call[0] for call in remote.calls].count("create-pr") == 1

        reloaded = recovery.PilotExactTaskRemotePublicationRecoveryReceipt.from_mapping(receipt.to_dict())
        assert reloaded == receipt
        assert reloaded.recovery_authenticated is False
        _reject(lambda: recovery_ledger.acquire(state=state, authorization_payload=payload, operator_signature=operator_signature, reviewer_signature=reviewer_signature))

        for field, value in (
            ("remote_write_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("merge_authorized", True),
            ("release_authorized", True),
            ("deploy_authorized", True),
            ("production_activation_authorized", True),
            ("nonce_reusable", True),
        ):
            _reject(lambda field=field, value=value: recovery.PilotExactTaskRemotePublicationRecoveryReceipt.from_mapping({**receipt.to_dict(), field: value}))

        # A durable pushed marker plus an already-existing exact PR is local
        # finalization only: no further remote write is permitted or needed.
        tx2_temp, tx2_ledger = _transaction_ledger("rsi-exact-task-remote-recovery-existing-")
        rec2_temp = tempfile.TemporaryDirectory(prefix="rsi-exact-task-remote-recovery-existing-ledger-")
        try:
            rec2_root = Path(rec2_temp.name) / "ledger"
            rec2_root.mkdir()
            lock2 = tx2_ledger.acquire(authorization=authorization, plan=plan)
            tx2_ledger.mark_pushed(
                authorization=authorization,
                plan=plan,
                push_result_sha256="c" * 64,
                pushed_at_utc="2026-09-15T08:39:00Z",
                lock_payload=lock2,
            )
            existing = {
                "number": 6161,
                "api_url": f"https://api.github.com/repos/{plan.repository}/pulls/6161",
            }
            remote2 = _RecoveryTransport(
                base_sha=plan.base_sha,
                head_sha=plan.predicted_commit_sha,
                repository=plan.repository,
                pr=existing,
            )
            state2, _ = recovery._observe_verified_recovery_state(
                execution_nonce_sha256=authorization.execution_nonce_sha256,
                transaction_ledger_root=tx2_ledger.root,
                authorization_ledger_root=auth_root,
                local_transaction_ledger_root=local_root,
                transport=remote2,
                now_provider=lambda: "2026-09-15T08:40:00Z",
            )
            assert state2.durable_transaction_state == "pushed_marked"
            assert state2.action_required == "finalize_existing_pr"
            payload2 = _payload(state2)
            verifier2, op2, rev2 = _authority(payload2)
            times2 = iter(("2026-09-15T08:40:20Z", "2026-09-15T08:40:21Z", "2026-09-15T08:40:22Z", "2026-09-15T08:40:23Z"))
            receipt2 = recovery._recover_verified_pilot_exact_task_remote_publication(
                authorization_payload=payload2,
                operator_signature=op2,
                reviewer_signature=rev2,
                verifier=verifier2,
                transaction_ledger_root=tx2_ledger.root,
                authorization_ledger_root=auth_root,
                local_transaction_ledger_root=local_root,
                recovery_ledger=recovery._PilotExactTaskRemotePublicationRecoveryLedger(rec2_root),
                transport=remote2,
                now_provider=lambda: next(times2),
            )
            assert receipt2.recovery_action == "finalize_existing_pr"
            assert receipt2.remote_write_performed is False
            assert not any(call[0] == "create-pr" for call in remote2.calls)
        finally:
            rec2_temp.cleanup()
            tx2_temp.cleanup()

        # Lock-only + absent remote head is intentionally not auto-recoverable.
        tx3_temp, tx3_ledger = _transaction_ledger("rsi-exact-task-remote-recovery-absent-")
        try:
            tx3_ledger.acquire(authorization=authorization, plan=plan)
            absent = _RecoveryTransport(
                base_sha=plan.base_sha,
                head_sha=None,
                repository=plan.repository,
            )
            state3, _ = recovery._observe_verified_recovery_state(
                execution_nonce_sha256=authorization.execution_nonce_sha256,
                transaction_ledger_root=tx3_ledger.root,
                authorization_ledger_root=auth_root,
                local_transaction_ledger_root=local_root,
                transport=absent,
                now_provider=lambda: "2026-09-15T08:40:00Z",
            )
            assert state3.action_required == "manual_intervention"
            assert state3.manual_intervention_required is True
            _reject(lambda: _payload(state3))
        finally:
            tx3_temp.cleanup()

        # Recovery state drift after the signed decision is durably consumed burns
        # the recovery slot and never creates a PR.
        tx4_temp, tx4_ledger = _transaction_ledger("rsi-exact-task-remote-recovery-drift-")
        rec4_temp = tempfile.TemporaryDirectory(prefix="rsi-exact-task-remote-recovery-drift-ledger-")
        try:
            rec4_root = Path(rec4_temp.name) / "ledger"
            rec4_root.mkdir()
            tx4_ledger.acquire(authorization=authorization, plan=plan)
            stable = _RecoveryTransport(base_sha=plan.base_sha, head_sha=plan.predicted_commit_sha, repository=plan.repository)
            signed_state, _ = recovery._observe_verified_recovery_state(
                execution_nonce_sha256=authorization.execution_nonce_sha256,
                transaction_ledger_root=tx4_ledger.root,
                authorization_ledger_root=auth_root,
                local_transaction_ledger_root=local_root,
                transport=stable,
                now_provider=lambda: "2026-09-15T08:40:00Z",
            )
            payload4 = _payload(signed_state)
            verifier4, op4, rev4 = _authority(payload4)
            drifting = _RecoveryTransport(base_sha=plan.base_sha, head_sha=plan.predicted_commit_sha, repository=plan.repository, drift_after=1)
            times4 = iter(("2026-09-15T08:40:20Z", "2026-09-15T08:40:21Z", "2026-09-15T08:40:22Z"))
            ledger4 = recovery._PilotExactTaskRemotePublicationRecoveryLedger(rec4_root)
            _reject(lambda: recovery._recover_verified_pilot_exact_task_remote_publication(
                authorization_payload=payload4,
                operator_signature=op4,
                reviewer_signature=rev4,
                verifier=verifier4,
                transaction_ledger_root=tx4_ledger.root,
                authorization_ledger_root=auth_root,
                local_transaction_ledger_root=local_root,
                recovery_ledger=ledger4,
                transport=drifting,
                now_provider=lambda: next(times4),
            ))
            final4, lock4 = ledger4._paths(authorization.execution_nonce_sha256)
            assert lock4.is_file()
            assert not final4.exists()
            assert not any(call[0] == "create-pr" for call in drifting.calls)
        finally:
            rec4_temp.cleanup()
            tx4_temp.cleanup()

        # Same signer in both roles is rejected even with a valid signature.
        _reject(lambda: recovery._verify_dual_signatures(
            payload=payload,
            operator_signature=operator_signature,
            reviewer_signature=operator_signature,
            verifier=verifier,
            at_utc="2026-09-15T08:40:20Z",
        ))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert schema["properties"]["push_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        public = inspect.signature(recovery.recover_pilot_exact_task_remote_publication).parameters
        assert tuple(public) == ("authorization_payload", "operator_signature", "reviewer_signature")
        source = inspect.getsource(recovery)
        assert "git push" not in source.lower()
        assert '("push",' not in source
        assert "merge_pull" not in source
        assert "production_activation_authorized: bool = False" in source
    finally:
        recovery_temp.cleanup()
        tx_temp.cleanup()
        auth_temp.cleanup()
        local_transaction_temp.cleanup()
        local_auth_temp.cleanup()
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
