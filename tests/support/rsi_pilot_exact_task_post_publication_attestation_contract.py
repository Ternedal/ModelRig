"""Adversarial contract for ADR-DC-052 exact post-publication attestation."""
from __future__ import annotations

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

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_post_publication_attestation as attestation,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_remote_publication_recovery as recovery,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_remote_publication_transaction as transaction,
)
from rsi_pilot_exact_task_remote_publication_recovery_contract import (  # noqa: E402
    _RecoveryTransport,
    _authority,
    _payload,
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
    / "rsi-pilot-exact-task-post-publication-attestation-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-052 unexpectedly accepted unsafe attestation")


class _ReadOnlyTransport:
    def __init__(self, states):
        self.states = list(states)
        self.calls = []

    def observe(self, intent):
        self.calls.append((intent.pr_intent_sha256, intent.predicted_commit_sha))
        if not self.states:
            raise AssertionError("unexpected extra post-publication observation")
        return self.states.pop(0)


def _exact_remote(plan, number):
    return {
        "base_sha": plan.base_sha,
        "head_sha": plan.predicted_commit_sha,
        "pull_request": {
            "number": number,
            "api_url": f"https://api.github.com/repos/{plan.repository}/pulls/{number}",
        },
    }


def _empty_ledger(prefix):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, root


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
    del mechanical, ready, task, observation
    auth_root = Path(auth_temp.name) / "ledger"
    local_root = Path(local_transaction_temp.name) / "ledger"

    tx_temp, tx_ledger = _transaction_ledger(
        "rsi-exact-task-post-publication-normal-tx-"
    )
    empty_recovery_temp, empty_recovery_root = _empty_ledger(
        "rsi-exact-task-post-publication-empty-recovery-"
    )
    try:
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
                "2026-09-15T09:10:00Z",
                "2026-09-15T09:10:01Z",
                "2026-09-15T09:10:02Z",
                "2026-09-15T09:10:03Z",
            )
        )
        with patch.object(fixture["git_runner"], "run", side_effect=reader):
            tx_receipt = transaction._execute_verified_pilot_exact_task_remote_publication(
                remote_publication_authorization=authorization,
                ledger=tx_ledger,
                observer=observer,
                transport=publisher,
                now_provider=lambda: next(times),
            )
        assert calls
        exact = _exact_remote(plan, 4242)
        remote = _ReadOnlyTransport((exact, dict(exact)))
        receipt = attestation._attest_verified_pilot_exact_task_post_publication(
            execution_nonce_sha256=authorization.execution_nonce_sha256,
            transaction_ledger_root=tx_ledger.root,
            recovery_ledger_root=empty_recovery_root,
            authorization_ledger_root=auth_root,
            local_transaction_ledger_root=local_root,
            transport=remote,
            now_provider=lambda: "2026-09-15T09:10:10Z",
        )
        assert receipt.attestation_authenticated is True
        assert receipt.completion_source == "transaction"
        assert receipt.completion_source_receipt_sha256 == tx_receipt.sha256
        assert receipt.remote_publication_authorization_sha256 == authorization.sha256
        assert receipt.remote_publication_plan_sha256 == plan.sha256
        assert receipt.pr_intent_sha256 == plan.pr_intent_sha256
        assert receipt.execution_nonce_sha256 == authorization.execution_nonce_sha256
        assert receipt.development_task_sha256 == plan.development_task_sha256
        assert receipt.candidate_patch_sha256 == plan.candidate_patch_sha256
        assert receipt.task_id == plan.task_id
        assert receipt.repository == plan.repository
        assert receipt.repository_id == plan.repository_id
        assert receipt.base_branch == plan.base_branch
        assert receipt.head_branch == plan.head_branch
        assert receipt.exact_task_base_sha == plan.base_sha
        assert receipt.predicted_commit_sha == plan.predicted_commit_sha
        assert receipt.root_tree_sha == plan.root_tree_sha
        assert receipt.pull_request_number == 4242
        assert receipt.pull_request_api_url.endswith("/pulls/4242")
        assert receipt.durable_completion_verified is True
        assert receipt.deterministic_pr_intent_reconstructed is True
        assert receipt.remote_base_verified is True
        assert receipt.remote_exact_head_verified is True
        assert receipt.draft_pr_verified is True
        assert receipt.double_observation_matched is True
        assert receipt.post_publication_verified is True
        assert receipt.ready_for_review_authorized is False
        assert receipt.reviewer_request_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert len(remote.calls) == 2

        reloaded = attestation.PilotExactTaskPostPublicationAttestationReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.attestation_authenticated is False

        for field, value in (
            ("durable_completion_verified", False),
            ("double_observation_matched", False),
            ("post_publication_verified", False),
            ("ready_for_review_authorized", True),
            ("reviewer_request_authorized", True),
            ("remote_write_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("merge_authorized", True),
            ("release_authorized", True),
            ("deploy_authorized", True),
            ("production_activation_authorized", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    attestation.PilotExactTaskPostPublicationAttestationReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        drift = _ReadOnlyTransport(
            (
                exact,
                {
                    "base_sha": plan.base_sha,
                    "head_sha": None,
                    "pull_request": None,
                },
            )
        )
        _reject(
            lambda: attestation._attest_verified_pilot_exact_task_post_publication(
                execution_nonce_sha256=authorization.execution_nonce_sha256,
                transaction_ledger_root=tx_ledger.root,
                recovery_ledger_root=empty_recovery_root,
                authorization_ledger_root=auth_root,
                local_transaction_ledger_root=local_root,
                transport=drift,
                now_provider=lambda: "2026-09-15T09:10:11Z",
            )
        )
        _reject(
            lambda: attestation._attest_verified_pilot_exact_task_post_publication(
                execution_nonce_sha256=authorization.execution_nonce_sha256,
                transaction_ledger_root=tx_ledger.root,
                recovery_ledger_root=empty_recovery_root,
                authorization_ledger_root=auth_root,
                local_transaction_ledger_root=local_root,
                transport=_ReadOnlyTransport((exact, exact)),
                now_provider=lambda: "2026-09-15T09:09:59Z",
            )
        )
    finally:
        empty_recovery_temp.cleanup()
        tx_temp.cleanup()

    tx2_temp, tx2_ledger = _transaction_ledger(
        "rsi-exact-task-post-publication-recovery-tx-"
    )
    recovery_temp, recovery_root = _empty_ledger(
        "rsi-exact-task-post-publication-recovery-ledger-"
    )
    try:
        tx2_ledger.acquire(authorization=authorization, plan=plan)
        remote_recovery = _RecoveryTransport(
            base_sha=plan.base_sha,
            head_sha=plan.predicted_commit_sha,
            repository=plan.repository,
        )
        state, _intent = recovery._observe_verified_recovery_state(
            execution_nonce_sha256=authorization.execution_nonce_sha256,
            transaction_ledger_root=tx2_ledger.root,
            authorization_ledger_root=auth_root,
            local_transaction_ledger_root=local_root,
            transport=remote_recovery,
            now_provider=lambda: "2026-09-15T08:40:00Z",
        )
        payload = _payload(state)
        verifier, operator_signature, reviewer_signature = _authority(payload)
        recovery_ledger = recovery._PilotExactTaskRemotePublicationRecoveryLedger(
            recovery_root
        )
        recovery_times = iter(
            (
                "2026-09-15T08:40:20Z",
                "2026-09-15T08:40:21Z",
                "2026-09-15T08:40:22Z",
                "2026-09-15T08:40:23Z",
                "2026-09-15T08:40:24Z",
                "2026-09-15T08:40:25Z",
                "2026-09-15T08:40:26Z",
            )
        )
        recovery_receipt = recovery._recover_verified_pilot_exact_task_remote_publication(
            authorization_payload=payload,
            operator_signature=operator_signature,
            reviewer_signature=reviewer_signature,
            verifier=verifier,
            transaction_ledger_root=tx2_ledger.root,
            authorization_ledger_root=auth_root,
            local_transaction_ledger_root=local_root,
            recovery_ledger=recovery_ledger,
            transport=remote_recovery,
            now_provider=lambda: next(recovery_times),
        )
        exact_recovered = _exact_remote(plan, 5151)
        recovered_remote = _ReadOnlyTransport(
            (exact_recovered, dict(exact_recovered))
        )
        recovered = attestation._attest_verified_pilot_exact_task_post_publication(
            execution_nonce_sha256=authorization.execution_nonce_sha256,
            transaction_ledger_root=tx2_ledger.root,
            recovery_ledger_root=recovery_root,
            authorization_ledger_root=auth_root,
            local_transaction_ledger_root=local_root,
            transport=recovered_remote,
            now_provider=lambda: "2026-09-15T09:12:00Z",
        )
        assert recovered.attestation_authenticated is True
        assert recovered.completion_source == "recovery"
        assert recovered.completion_source_receipt_sha256 == recovery_receipt.sha256
        assert recovered.pull_request_number == 5151
        assert recovered.predicted_commit_sha == plan.predicted_commit_sha
        assert recovered.root_tree_sha == plan.root_tree_sha
        assert recovered.post_publication_verified is True
        assert recovered.remote_write_authorized is False
        assert recovered.pr_mutation_authorized is False
        assert recovered.merge_authorized is False
    finally:
        recovery_temp.cleanup()
        tx2_temp.cleanup()

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert set(schema["properties"]) == set(receipt.to_dict())
    assert set(schema["required"]) == set(receipt.to_dict())
    assert schema["properties"]["ready_for_review_authorized"]["const"] is False
    assert schema["properties"]["pr_mutation_authorized"]["const"] is False
    assert schema["properties"]["merge_authorized"]["const"] is False
    assert schema["properties"]["production_activation_authorized"]["const"] is False

    public = inspect.signature(attestation.attest_pilot_exact_task_post_publication).parameters
    assert tuple(public) == ("execution_nonce_sha256",)
    source = inspect.getsource(attestation)
    assert "create_draft_pr(" not in source
    assert "push_exact_commit" not in source
    assert 'method="POST"' not in source
    assert "ready_for_review_authorized: bool = False" in source
    assert "merge_authorized: bool = False" in source

    local_transaction_temp.cleanup()
    local_auth_temp.cleanup()
    execution_temp.cleanup()
    reservation_temp.cleanup()
    capability_temp.cleanup()
    admission_ledger_temp.cleanup()
    source_temp.cleanup()
    auth_temp.cleanup()


if __name__ == "__main__":
    run_contract()
