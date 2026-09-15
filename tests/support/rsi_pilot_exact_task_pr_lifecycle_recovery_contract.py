"""Adversarial contract for ADR-DC-055 exact PR lifecycle recovery."""
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
    improvement_pilot_exact_task_pr_lifecycle_recovery as recovery,
)
from rsi_pilot_exact_task_pr_lifecycle_transaction_contract import (  # noqa: E402
    _Transport,
    _live_lifecycle_authorization,
    _transaction_ledger,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pr-lifecycle-recovery-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-055 unexpectedly accepted unsafe lifecycle recovery")


def _recovery_ledger(prefix: str):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, recovery._PilotExactTaskPrLifecycleRecoveryLedger(root)


def _roots(live, lifecycle_auth_temp):
    local_transaction_temp = live[6]
    publication_auth_temp = live[7]
    return (
        Path(lifecycle_auth_temp.name) / "ledger",
        Path(publication_auth_temp.name) / "ledger",
        Path(local_transaction_temp.name) / "ledger",
    )


class _RecoveryTransport:
    def __init__(self, *, draft: bool, usernames=(), teams=()):
        self.draft = draft
        self.usernames = tuple(usernames)
        self.teams = tuple(teams)
        self.calls: list[str] = []
        self.scripted: list[tuple[bool, tuple[str, ...], tuple[str, ...]]] = []

    def _state(self, intent):
        return recovery._LifecycleRemoteState(
            pull_request_node_id="PR_kwDOEXACTNODE1234",
            draft=self.draft,
            reviewer_usernames=self.usernames,
            reviewer_team_slugs=self.teams,
            repository=intent.repository,
            repository_id=intent.repository_id,
            base_branch=intent.base_branch,
            base_sha=intent.exact_task_base_sha,
            head_branch=intent.head_branch,
            head_sha=intent.predicted_commit_sha,
            pull_request_number=intent.pull_request_number,
            pull_request_api_url=intent.pull_request_api_url,
            maintainer_can_modify=False,
            state="open",
        )

    def observe(self, intent):
        self.calls.append("observe")
        if self.scripted:
            draft, usernames, teams = self.scripted.pop(0)
            old = self.draft, self.usernames, self.teams
            self.draft, self.usernames, self.teams = draft, usernames, teams
            state = self._state(intent)
            self.draft, self.usernames, self.teams = old
            return state
        return self._state(intent)

    def request_reviewers(self, intent):
        self.calls.append("request-reviewers")
        if self.draft is not False:
            raise AssertionError("test transport reviewer request requires non-draft")
        self.usernames = intent.reviewer_usernames
        self.teams = intent.reviewer_team_slugs


def _dual_authority(payload: bytes):
    custody = asymmetric_authority_key_custody_policy_sha256()
    definitions = (
        (
            bytes(range(1, 33)),
            "lifecycle-recovery-op-1",
            "recovery.operator",
            "offline-recovery-operator",
        ),
        (
            bytes(range(33, 65)),
            "lifecycle-recovery-review-1",
            "recovery.reviewer",
            "offline-recovery-reviewer",
        ),
    )
    keys = {}
    signatures = []
    for raw_private, key_id, actor_id, system_id in definitions:
        private = Ed25519PrivateKey.from_private_bytes(raw_private)
        public = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        trusted = TrustedEd25519AuthorityKey(
            key_id=key_id,
            issuer_actor_id=actor_id,
            issuer_system_id=system_id,
            public_key_hex=public.hex(),
            valid_from_utc="2026-01-01T00:00:00Z",
            valid_until_utc="2027-01-01T00:00:00Z",
            keyring_epoch=1,
            custody_policy_sha256=custody,
        )
        keys[key_id] = trusted
        message = authority_signing_message(
            key_id=trusted.key_id,
            issuer_actor_id=trusted.issuer_actor_id,
            issuer_system_id=trusted.issuer_system_id,
            keyring_epoch=trusted.keyring_epoch,
            custody_policy_sha256=custody,
            payload=payload,
        )
        signatures.append(
            DetachedEd25519AuthoritySignature(
                key_id=trusted.key_id,
                issuer_actor_id=trusted.issuer_actor_id,
                issuer_system_id=trusted.issuer_system_id,
                keyring_epoch=trusted.keyring_epoch,
                custody_policy_sha256=custody,
                payload_sha256=hashlib.sha256(payload).hexdigest(),
                signature_hex=private.sign(message).hex(),
                signed_at_utc="2026-09-15T09:32:10Z",
            )
        )
    verifier = Ed25519AuthorityVerifier(keys, minimum_keyring_epoch=1)
    return verifier, signatures[0], signatures[1]


def _payload(state):
    return recovery._build_recovery_payload(
        state=state,
        requested_at_utc="2026-09-15T09:32:00Z",
        expires_at_utc="2026-09-15T09:37:00Z",
        operator_actor_id="recovery.operator",
        operator_system_id="offline-recovery-operator",
        operator_key_id="lifecycle-recovery-op-1",
        reviewer_actor_id="recovery.reviewer",
        reviewer_system_id="offline-recovery-reviewer",
        reviewer_key_id="lifecycle-recovery-review-1",
    )


def _observe(
    *,
    authorization,
    ledger,
    lifecycle_auth_root,
    publication_auth_root,
    local_root,
    transport,
    now="2026-09-15T09:31:40Z",
):
    return recovery._observe_verified_recovery_state(
        execution_nonce_sha256=authorization.execution_nonce_sha256,
        transaction_ledger_root=ledger.root,
        lifecycle_authorization_ledger_root=lifecycle_auth_root,
        publication_authorization_ledger_root=publication_auth_root,
        local_transaction_ledger_root=local_root,
        transport=transport,
        now_provider=lambda: now,
    )


def _prepare_ready_marked(authorization, attestation, ledger):
    tx_transport = _Transport(authorization, attestation)
    pre = tx_transport._state()
    lock = ledger.acquire(
        authorization=authorization,
        pre_state_sha256=pre.sha256,
        credential_config_sha256="a" * 64,
        credential_path_sha256="b" * 64,
    )
    tx_transport.ready = True
    ready = tx_transport._state()
    ready_payload = ledger.mark_ready(
        authorization=authorization,
        node_id=ready.pull_request_node_id,
        state_sha256=ready.sha256,
        ready_at_utc="2026-09-15T09:31:10Z",
    )
    return lock, ready_payload, tx_transport, ready


def _cleanup_bundle(bundle):
    (
        live,
        publication_tx_temp,
        publication_recovery_temp,
        lifecycle_auth_temp,
        *_rest,
    ) = bundle
    lifecycle_auth_temp.cleanup()
    publication_recovery_temp.cleanup()
    publication_tx_temp.cleanup()
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        local_auth_temp,
        local_transaction_temp,
        publication_auth_temp,
        *_tail,
    ) = live
    publication_auth_temp.cleanup()
    local_transaction_temp.cleanup()
    local_auth_temp.cleanup()
    execution_temp.cleanup()
    reservation_temp.cleanup()
    capability_temp.cleanup()
    admission_ledger_temp.cleanup()
    source_temp.cleanup()


def run_contract() -> None:
    if os.name == "nt":
        return

    bundle = _live_lifecycle_authorization()
    (
        live,
        _publication_tx_temp,
        _publication_recovery_temp,
        lifecycle_auth_temp,
        attestation,
        _plan,
        _publication_auth,
        _config,
        authorization,
    ) = bundle
    lifecycle_auth_root, publication_auth_root, local_root = _roots(
        live, lifecycle_auth_temp
    )

    # lock-only + still-draft is observable but never auto-authorizable.
    manual_temp, manual_ledger = _transaction_ledger(
        "rsi-exact-task-pr-lifecycle-recovery-manual-"
    )
    try:
        tx_transport = _Transport(authorization, attestation)
        pre = tx_transport._state()
        manual_ledger.acquire(
            authorization=authorization,
            pre_state_sha256=pre.sha256,
            credential_config_sha256="a" * 64,
            credential_path_sha256="b" * 64,
        )
        manual_remote = _RecoveryTransport(draft=True)
        manual, _intent = _observe(
            authorization=authorization,
            ledger=manual_ledger,
            lifecycle_auth_root=lifecycle_auth_root,
            publication_auth_root=publication_auth_root,
            local_root=local_root,
            transport=manual_remote,
        )
        assert manual.durable_transaction_state == "lock_only"
        assert manual.remote_lifecycle_state == "draft_empty"
        assert manual.action_required == "manual_intervention"
        assert manual.manual_intervention_required is True
        _reject(lambda: _payload(manual))
    finally:
        manual_temp.cleanup()

    # ready marker + no reviewers may request only the exact missing reviewer set.
    request_tx_temp, request_tx_ledger = _transaction_ledger(
        "rsi-exact-task-pr-lifecycle-recovery-request-tx-"
    )
    request_recovery_temp, request_recovery_ledger = _recovery_ledger(
        "rsi-exact-task-pr-lifecycle-recovery-request-"
    )
    try:
        _lock, _ready_payload, _tx_transport, _ready = _prepare_ready_marked(
            authorization, attestation, request_tx_ledger
        )
        remote = _RecoveryTransport(draft=False)
        state, _intent = _observe(
            authorization=authorization,
            ledger=request_tx_ledger,
            lifecycle_auth_root=lifecycle_auth_root,
            publication_auth_root=publication_auth_root,
            local_root=local_root,
            transport=remote,
        )
        assert state.durable_transaction_state == "ready_marked"
        assert state.remote_lifecycle_state == "ready_empty"
        assert state.action_required == "request_missing_reviewers"
        assert state.manual_intervention_required is False

        payload = _payload(state)
        verifier, operator_sig, reviewer_sig = _dual_authority(payload)
        times = iter(
            (
                "2026-09-15T09:32:20Z",
                "2026-09-15T09:32:21Z",
                "2026-09-15T09:32:22Z",
                "2026-09-15T09:32:23Z",
            )
        )
        receipt = recovery._recover_verified_pilot_exact_task_pr_lifecycle(
            authorization_payload=payload,
            operator_signature=operator_sig,
            reviewer_signature=reviewer_sig,
            verifier=verifier,
            transaction_ledger_root=request_tx_ledger.root,
            lifecycle_authorization_ledger_root=lifecycle_auth_root,
            publication_authorization_ledger_root=publication_auth_root,
            local_transaction_ledger_root=local_root,
            recovery_ledger=request_recovery_ledger,
            read_transport=remote,
            write_transport=remote,
            now_provider=lambda: next(times),
        )
        assert receipt.recovery_authenticated is True
        assert receipt.recovery_action == "request_missing_reviewers"
        assert receipt.durable_transaction_state == "ready_marked"
        assert receipt.remote_write_performed is True
        assert receipt.reviewer_usernames == authorization.reviewer_usernames
        assert receipt.reviewer_team_slugs == authorization.reviewer_team_slugs
        assert remote.calls.count("request-reviewers") == 1
        assert remote.usernames == authorization.reviewer_usernames
        assert remote.teams == authorization.reviewer_team_slugs
        assert receipt.ready_for_review_authorized is False
        assert receipt.reviewer_request_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.push_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False

        final, lock = request_recovery_ledger._paths(
            authorization.execution_nonce_sha256
        )
        assert final.is_file()
        assert lock.is_file()
        reloaded = recovery.PilotExactTaskPrLifecycleRecoveryReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.recovery_authenticated is False

        for field, value in (
            ("host_recovery_guard_committed", False),
            ("dual_ed25519_recovery_authorized", False),
            ("ready_for_review_verified", False),
            ("reviewer_requests_verified", False),
            ("ready_for_review_authorized", True),
            ("reviewer_request_authorized", True),
            ("remote_write_authorized", True),
            ("pr_mutation_authorized", True),
            ("push_authorized", True),
            ("merge_authorized", True),
            ("release_authorized", True),
            ("deploy_authorized", True),
            ("production_activation_authorized", True),
            ("nonce_reusable", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    recovery.PilotExactTaskPrLifecycleRecoveryReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        # Same payload cannot use one signer twice.
        _reject(
            lambda: recovery._verify_dual_signatures(
                payload=payload,
                operator_signature=operator_sig,
                reviewer_signature=operator_sig,
                verifier=verifier,
                at_utc="2026-09-15T09:32:20Z",
            )
        )
    finally:
        request_recovery_temp.cleanup()
        request_tx_temp.cleanup()

    # Ready marker + exact remote reviewers can finalize without a write.
    final_tx_temp, final_tx_ledger = _transaction_ledger(
        "rsi-exact-task-pr-lifecycle-recovery-final-tx-"
    )
    final_recovery_temp, final_recovery_ledger = _recovery_ledger(
        "rsi-exact-task-pr-lifecycle-recovery-final-"
    )
    try:
        _lock, _ready_payload, tx_transport, _ready = _prepare_ready_marked(
            authorization, attestation, final_tx_ledger
        )
        tx_transport.usernames = authorization.reviewer_usernames
        tx_transport.teams = authorization.reviewer_team_slugs
        exact = tx_transport._state()
        final_tx_ledger.mark_reviewers(
            authorization=authorization,
            final_state_sha256=exact.sha256,
            reviewers_requested_at_utc="2026-09-15T09:31:20Z",
        )
        remote = _RecoveryTransport(
            draft=False,
            usernames=authorization.reviewer_usernames,
            teams=authorization.reviewer_team_slugs,
        )
        state, _intent = _observe(
            authorization=authorization,
            ledger=final_tx_ledger,
            lifecycle_auth_root=lifecycle_auth_root,
            publication_auth_root=publication_auth_root,
            local_root=local_root,
            transport=remote,
        )
        assert state.durable_transaction_state == "reviewers_marked"
        assert state.action_required == "finalize_existing_state"
        payload = _payload(state)
        verifier, operator_sig, reviewer_sig = _dual_authority(payload)
        times = iter(
            (
                "2026-09-15T09:32:20Z",
                "2026-09-15T09:32:21Z",
                "2026-09-15T09:32:22Z",
                "2026-09-15T09:32:23Z",
            )
        )
        receipt = recovery._recover_verified_pilot_exact_task_pr_lifecycle(
            authorization_payload=payload,
            operator_signature=operator_sig,
            reviewer_signature=reviewer_sig,
            verifier=verifier,
            transaction_ledger_root=final_tx_ledger.root,
            lifecycle_authorization_ledger_root=lifecycle_auth_root,
            publication_authorization_ledger_root=publication_auth_root,
            local_transaction_ledger_root=local_root,
            recovery_ledger=final_recovery_ledger,
            read_transport=remote,
            write_transport=None,
            now_provider=lambda: next(times),
        )
        assert receipt.recovery_action == "finalize_existing_state"
        assert receipt.remote_write_performed is False
        assert "request-reviewers" not in remote.calls
    finally:
        final_recovery_temp.cleanup()
        final_tx_temp.cleanup()

    # Remote drift after recovery consumption burns the recovery slot.
    drift_tx_temp, drift_tx_ledger = _transaction_ledger(
        "rsi-exact-task-pr-lifecycle-recovery-drift-tx-"
    )
    drift_recovery_temp, drift_recovery_ledger = _recovery_ledger(
        "rsi-exact-task-pr-lifecycle-recovery-drift-"
    )
    try:
        _prepare_ready_marked(authorization, attestation, drift_tx_ledger)
        remote = _RecoveryTransport(draft=False)
        state, _intent = _observe(
            authorization=authorization,
            ledger=drift_tx_ledger,
            lifecycle_auth_root=lifecycle_auth_root,
            publication_auth_root=publication_auth_root,
            local_root=local_root,
            transport=remote,
        )
        payload = _payload(state)
        verifier, operator_sig, reviewer_sig = _dual_authority(payload)
        remote.scripted = [
            (False, (), ()),
            (
                False,
                authorization.reviewer_usernames,
                authorization.reviewer_team_slugs,
            ),
        ]
        times = iter(
            (
                "2026-09-15T09:32:20Z",
                "2026-09-15T09:32:21Z",
                "2026-09-15T09:32:22Z",
            )
        )
        _reject(
            lambda: recovery._recover_verified_pilot_exact_task_pr_lifecycle(
                authorization_payload=payload,
                operator_signature=operator_sig,
                reviewer_signature=reviewer_sig,
                verifier=verifier,
                transaction_ledger_root=drift_tx_ledger.root,
                lifecycle_authorization_ledger_root=lifecycle_auth_root,
                publication_authorization_ledger_root=publication_auth_root,
                local_transaction_ledger_root=local_root,
                recovery_ledger=drift_recovery_ledger,
                read_transport=remote,
                write_transport=remote,
                now_provider=lambda: next(times),
            )
        )
        final, lock = drift_recovery_ledger._paths(
            authorization.execution_nonce_sha256
        )
        assert lock.is_file()
        assert not final.exists()
    finally:
        drift_recovery_temp.cleanup()
        drift_tx_temp.cleanup()

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    sample_fields = set(
        recovery.PilotExactTaskPrLifecycleRecoveryReceipt.__dataclass_fields__
    )
    assert set(schema["properties"]) == sample_fields
    assert set(schema["required"]) == sample_fields
    assert schema["properties"]["merge_authorized"]["const"] is False
    assert schema["properties"]["production_activation_authorized"]["const"] is False
    assert schema["properties"]["nonce_reusable"]["const"] is False

    public_observe = inspect.signature(
        recovery.observe_pilot_exact_task_pr_lifecycle_recovery
    ).parameters
    assert tuple(public_observe) == ("execution_nonce_sha256",)
    public_recover = inspect.signature(
        recovery.recover_pilot_exact_task_pr_lifecycle
    ).parameters
    assert tuple(public_recover) == (
        "authorization_payload",
        "operator_signature",
        "reviewer_signature",
    )
    source = inspect.getsource(recovery)
    assert "markPullRequestReadyForReview" not in source
    assert "merge_pull_request" not in source
    assert "enable_auto_merge" not in source
    assert "push_authorized: bool = False" in source
    assert "merge_authorized: bool = False" in source
    assert "production_activation_authorized: bool = False" in source

    _cleanup_bundle(bundle)


if __name__ == "__main__":
    run_contract()
