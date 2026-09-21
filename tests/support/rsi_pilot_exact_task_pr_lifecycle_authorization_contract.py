"""Adversarial contract for ADR-DC-053 exact PR lifecycle authorization."""
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
    improvement_pilot_exact_task_post_publication_attestation as post_attestation,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_pr_lifecycle_authorization as lifecycle,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_remote_publication_transaction as transaction,
)
from rsi_pilot_exact_task_remote_publication_transaction_contract import (  # noqa: E402
    _Transport,
    _live_authorization,
    _reader,
    _transaction_ledger,
)
from rsi_pilot_exact_task_remote_state_observation_contract import _Observer  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pr-lifecycle-authorization-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-053 unexpectedly accepted unsafe lifecycle authority")


class _ReadOnlyTransport:
    def __init__(self, state):
        self.state = state
        self.calls = []

    def observe(self, intent):
        self.calls.append(intent.pr_intent_sha256)
        return dict(self.state)


def _ledger(prefix: str):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, lifecycle._PilotExactTaskPrLifecycleAuthorizationLedger(root)


def _authority(payload: bytes, *, signed_at="2026-09-15T09:30:11Z"):
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    custody = asymmetric_authority_key_custody_policy_sha256()
    trusted = TrustedEd25519AuthorityKey(
        key_id="pr-lifecycle-key-1",
        issuer_actor_id="lifecycle.operator",
        issuer_system_id="offline-lifecycle-authority",
        public_key_hex=public.hex(),
        valid_from_utc="2026-01-01T00:00:00Z",
        valid_until_utc="2027-01-01T00:00:00Z",
        keyring_epoch=1,
        custody_policy_sha256=custody,
    )
    message = authority_signing_message(
        key_id=trusted.key_id,
        issuer_actor_id=trusted.issuer_actor_id,
        issuer_system_id=trusted.issuer_system_id,
        keyring_epoch=trusted.keyring_epoch,
        custody_policy_sha256=custody,
        payload=payload,
    )
    signature = DetachedEd25519AuthoritySignature(
        key_id=trusted.key_id,
        issuer_actor_id=trusted.issuer_actor_id,
        issuer_system_id=trusted.issuer_system_id,
        keyring_epoch=trusted.keyring_epoch,
        custody_policy_sha256=custody,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        signature_hex=private.sign(message).hex(),
        signed_at_utc=signed_at,
    )
    return Ed25519AuthorityVerifier({trusted.key_id: trusted}, minimum_keyring_epoch=1), signature


def _live_post_attestation():
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
    del mechanical, ready, task, observation
    tx_temp, tx_ledger = _transaction_ledger("rsi-exact-task-pr-lifecycle-tx-")
    recovery_temp = tempfile.TemporaryDirectory(prefix="rsi-exact-task-pr-lifecycle-recovery-")
    recovery_root = Path(recovery_temp.name) / "ledger"
    recovery_root.mkdir()
    observer = _Observer((good, dict(good), dict(good), dict(good)))
    publisher = _Transport()
    calls, reader = _reader(
        fixture,
        local_transaction,
        identity,
        commit_payload,
        index_payload,
    )
    times = iter(
        (
            "2026-09-15T09:29:50Z",
            "2026-09-15T09:29:51Z",
            "2026-09-15T09:29:52Z",
            "2026-09-15T09:29:53Z",
        )
    )
    with patch.object(fixture["git_runner"], "run", side_effect=reader):
        transaction_receipt = transaction._execute_verified_pilot_exact_task_remote_publication(
            remote_publication_authorization=authorization,
            ledger=tx_ledger,
            observer=observer,
            transport=publisher,
            now_provider=lambda: next(times),
        )
    assert calls
    exact = {
        "base_sha": plan.base_sha,
        "head_sha": plan.predicted_commit_sha,
        "pull_request": {
            "number": transaction_receipt.pull_request_number,
            "api_url": transaction_receipt.pull_request_api_url,
        },
    }
    remote = _ReadOnlyTransport(exact)
    attestation = post_attestation._attest_verified_pilot_exact_task_post_publication(
        execution_nonce_sha256=authorization.execution_nonce_sha256,
        transaction_ledger_root=tx_ledger.root,
        recovery_ledger_root=recovery_root,
        authorization_ledger_root=Path(auth_temp.name) / "ledger",
        local_transaction_ledger_root=Path(local_transaction_temp.name) / "ledger",
        transport=remote,
        now_provider=lambda: "2026-09-15T09:30:00Z",
    )
    assert len(remote.calls) == 2
    assert attestation.attestation_authenticated is True
    return (
        live,
        tx_temp,
        recovery_temp,
        attestation,
        plan,
        authorization,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    live, tx_temp, recovery_temp, attestation, plan, authorization = _live_post_attestation()
    config = lifecycle.PilotExactTaskPrLifecycleConfig(
        repository=attestation.repository,
        repository_id=attestation.repository_id,
        reviewer_usernames=("reviewer-one", "reviewer-two"),
        reviewer_team_slugs=("modelrig-reviewers",),
    )
    payload = lifecycle._build_authorization_payload(
        post_publication_attestation=attestation,
        config=config,
        requested_at_utc="2026-09-15T09:30:10Z",
        expires_at_utc="2026-09-15T09:35:00Z",
        authorizer_actor_id="lifecycle.operator",
        authorizer_system_id="offline-lifecycle-authority",
        authorizer_key_id="pr-lifecycle-key-1",
    )
    verifier, signature = _authority(payload)
    ledger_temp, ledger = _ledger("rsi-exact-task-pr-lifecycle-ledger-")
    try:
        receipt = lifecycle._authorize_verified_pilot_exact_task_pr_lifecycle(
            post_publication_attestation=attestation,
            lifecycle_config=config,
            authorization_payload=payload,
            signature=signature,
            verifier=verifier,
            ledger=ledger,
            now_provider=lambda: "2026-09-15T09:30:20Z",
        )
        assert receipt.authorization_authenticated is True
        assert receipt.lifecycle_key_sha256 == authorization.execution_nonce_sha256
        assert receipt.post_publication_attestation_sha256 == attestation.sha256
        assert receipt.lifecycle_config_sha256 == config.sha256
        assert receipt.reviewer_set_sha256 == config.reviewer_set_sha256
        assert receipt.pr_intent_sha256 == plan.pr_intent_sha256
        assert receipt.predicted_commit_sha == plan.predicted_commit_sha
        assert receipt.pull_request_number == attestation.pull_request_number
        assert receipt.reviewer_usernames == config.reviewer_usernames
        assert receipt.reviewer_team_slugs == config.reviewer_team_slugs
        assert receipt.host_lifecycle_guard_committed is True
        assert receipt.post_publication_attestation_authenticated is True
        assert receipt.post_publication_verified is True
        assert receipt.external_ed25519_authorized is True
        assert receipt.ready_for_review_authorized is True
        assert receipt.reviewer_request_authorized is True
        assert receipt.remote_write_authorized is True
        assert receipt.pr_mutation_authorized is True
        assert receipt.push_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False

        final, lock = ledger._paths(authorization.execution_nonce_sha256)
        assert final.is_file()
        assert lock.is_file()
        _reject(
            lambda: ledger.acquire(
                attestation=attestation,
                payload=payload,
                config_sha256=config.sha256,
                reviewer_set_sha256=config.reviewer_set_sha256,
            )
        )

        reloaded = lifecycle.PilotExactTaskPrLifecycleAuthorizationReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.authorization_authenticated is False

        for field, value in (
            ("host_lifecycle_guard_committed", False),
            ("post_publication_verified", False),
            ("ready_for_review_authorized", False),
            ("reviewer_request_authorized", False),
            ("remote_write_authorized", False),
            ("pr_mutation_authorized", False),
            ("push_authorized", True),
            ("merge_authorized", True),
            ("release_authorized", True),
            ("deploy_authorized", True),
            ("production_activation_authorized", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    lifecycle.PilotExactTaskPrLifecycleAuthorizationReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        # A reloaded ADR-DC-052 receipt cannot mint lifecycle authority.
        reloaded_attestation = (
            post_attestation.PilotExactTaskPostPublicationAttestationReceipt.from_mapping(
                attestation.to_dict()
            )
        )
        assert reloaded_attestation.attestation_authenticated is False
        other_temp, other_ledger = _ledger("rsi-exact-task-pr-lifecycle-reloaded-")
        try:
            _reject(
                lambda: lifecycle._authorize_verified_pilot_exact_task_pr_lifecycle(
                    post_publication_attestation=reloaded_attestation,
                    lifecycle_config=config,
                    authorization_payload=payload,
                    signature=signature,
                    verifier=verifier,
                    ledger=other_ledger,
                    now_provider=lambda: "2026-09-15T09:30:20Z",
                )
            )
        finally:
            other_temp.cleanup()

        # Caller cannot substitute another reviewer set under the same signature.
        wrong_config = lifecycle.PilotExactTaskPrLifecycleConfig(
            repository=attestation.repository,
            repository_id=attestation.repository_id,
            reviewer_usernames=("attacker-reviewer",),
            reviewer_team_slugs=(),
        )
        wrong_temp, wrong_ledger = _ledger("rsi-exact-task-pr-lifecycle-wrong-config-")
        try:
            _reject(
                lambda: lifecycle._authorize_verified_pilot_exact_task_pr_lifecycle(
                    post_publication_attestation=attestation,
                    lifecycle_config=wrong_config,
                    authorization_payload=payload,
                    signature=signature,
                    verifier=verifier,
                    ledger=wrong_ledger,
                    now_provider=lambda: "2026-09-15T09:30:20Z",
                )
            )
            assert not wrong_ledger._paths(attestation.execution_nonce_sha256)[1].exists()
        finally:
            wrong_temp.cleanup()

        # Invalid/stale signatures fail before durable lifecycle consumption.
        bad_signature = DetachedEd25519AuthoritySignature.from_mapping(
            {**signature.to_dict(), "signature_hex": "00" * 64}
        )
        bad_temp, bad_ledger = _ledger("rsi-exact-task-pr-lifecycle-bad-signature-")
        try:
            _reject(
                lambda: lifecycle._authorize_verified_pilot_exact_task_pr_lifecycle(
                    post_publication_attestation=attestation,
                    lifecycle_config=config,
                    authorization_payload=payload,
                    signature=bad_signature,
                    verifier=verifier,
                    ledger=bad_ledger,
                    now_provider=lambda: "2026-09-15T09:30:20Z",
                )
            )
            _reject(
                lambda: lifecycle._authorize_verified_pilot_exact_task_pr_lifecycle(
                    post_publication_attestation=attestation,
                    lifecycle_config=config,
                    authorization_payload=payload,
                    signature=signature,
                    verifier=verifier,
                    ledger=bad_ledger,
                    now_provider=lambda: "2026-09-15T09:35:01Z",
                )
            )
            assert not bad_ledger._paths(attestation.execution_nonce_sha256)[1].exists()
        finally:
            bad_temp.cleanup()

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert schema["properties"]["ready_for_review_authorized"]["const"] is True
        assert schema["properties"]["reviewer_request_authorized"]["const"] is True
        assert schema["properties"]["push_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        public = inspect.signature(lifecycle.authorize_pilot_exact_task_pr_lifecycle).parameters
        assert tuple(public) == (
            "post_publication_attestation",
            "authorization_payload",
            "signature",
        )
        source = inspect.getsource(lifecycle)
        assert "markpullrequestreadyforreview" not in source.lower()
        assert "request_pull_request_reviewers" not in source
        assert 'method="POST"' not in source
        assert "merge_pull_request" not in source
        assert "merge_authorized: bool = False" in source
    finally:
        ledger_temp.cleanup()
        recovery_temp.cleanup()
        tx_temp.cleanup()
        (
            source_temp,
            admission_ledger_temp,
            capability_temp,
            reservation_temp,
            execution_temp,
            local_auth_temp,
            local_transaction_temp,
            auth_temp,
            *_rest,
        ) = live
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
