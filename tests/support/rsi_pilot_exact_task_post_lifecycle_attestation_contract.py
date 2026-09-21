"""Adversarial contract for ADR-DC-056 exact post-lifecycle attestation."""
from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_post_lifecycle_attestation as post_lifecycle,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_pr_lifecycle_recovery as lifecycle_recovery,
)
from rsi_pilot_exact_task_pr_lifecycle_recovery_contract import (  # noqa: E402
    _RecoveryTransport,
    _cleanup_bundle,
    _dual_authority,
    _observe,
    _payload,
    _prepare_ready_marked,
    _recovery_ledger,
    _roots,
)
from rsi_pilot_exact_task_pr_lifecycle_transaction_contract import (  # noqa: E402
    _Transport,
    _live_lifecycle_authorization,
    _run,
    _transaction_ledger,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-post-lifecycle-attestation-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError(
        "ADR-DC-056 unexpectedly accepted unsafe post-lifecycle attestation"
    )


def _attest(
    *,
    authorization,
    tx_ledger,
    recovery_ledger,
    lifecycle_auth_root,
    publication_auth_root,
    local_root,
    transport,
    now,
):
    return post_lifecycle._attest_verified_pilot_exact_task_post_lifecycle(
        execution_nonce_sha256=authorization.execution_nonce_sha256,
        transaction_ledger_root=tx_ledger.root,
        recovery_ledger_root=recovery_ledger.root,
        lifecycle_authorization_ledger_root=lifecycle_auth_root,
        publication_authorization_ledger_root=publication_auth_root,
        local_transaction_ledger_root=local_root,
        transport=transport,
        now_provider=lambda: now,
    )


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

    # Normal ADR-DC-054 completion becomes one live read-only attestation.
    tx_temp, tx_ledger = _transaction_ledger(
        "rsi-exact-task-post-lifecycle-tx-"
    )
    empty_recovery_temp, empty_recovery_ledger = _recovery_ledger(
        "rsi-exact-task-post-lifecycle-empty-recovery-"
    )
    try:
        tx_transport = _Transport(authorization, attestation)
        tx_receipt = _run(authorization, tx_transport, tx_ledger)
        assert tx_receipt.transaction_authenticated is True
        remote = _RecoveryTransport(
            draft=False,
            usernames=authorization.reviewer_usernames,
            teams=authorization.reviewer_team_slugs,
        )
        receipt = _attest(
            authorization=authorization,
            tx_ledger=tx_ledger,
            recovery_ledger=empty_recovery_ledger,
            lifecycle_auth_root=lifecycle_auth_root,
            publication_auth_root=publication_auth_root,
            local_root=local_root,
            transport=remote,
            now="2026-09-15T09:31:10Z",
        )
        assert receipt.attestation_authenticated is True
        assert receipt.completion_source == "transaction"
        assert receipt.completion_source_receipt_sha256 == tx_receipt.sha256
        assert receipt.pr_lifecycle_authorization_sha256 == authorization.sha256
        assert receipt.post_publication_attestation_sha256 == (
            authorization.post_publication_attestation_sha256
        )
        assert receipt.lifecycle_config_sha256 == authorization.lifecycle_config_sha256
        assert receipt.reviewer_set_sha256 == authorization.reviewer_set_sha256
        assert receipt.execution_nonce_sha256 == authorization.execution_nonce_sha256
        assert receipt.predicted_commit_sha == authorization.predicted_commit_sha
        assert receipt.pull_request_number == authorization.pull_request_number
        assert receipt.reviewer_usernames == authorization.reviewer_usernames
        assert receipt.reviewer_team_slugs == authorization.reviewer_team_slugs
        assert receipt.ready_marker_sha256 is not None
        assert receipt.reviewers_marker_sha256 is not None
        assert receipt.durable_completion_verified is True
        assert receipt.exact_pr_verified is True
        assert receipt.ready_for_review_verified is True
        assert receipt.reviewer_requests_verified is True
        assert receipt.double_observation_matched is True
        assert receipt.post_lifecycle_verified is True
        assert receipt.review_submission_authorized is False
        assert receipt.review_thread_mutation_authorized is False
        assert receipt.ready_for_review_authorized is False
        assert receipt.reviewer_request_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.draft is False
        assert receipt.nonce_reusable is False
        assert remote.calls == ["observe", "observe"]

        reloaded = (
            post_lifecycle.PilotExactTaskPostLifecycleAttestationReceipt.from_mapping(
                receipt.to_dict()
            )
        )
        assert reloaded == receipt
        assert reloaded.attestation_authenticated is False

        for field, value in (
            ("durable_completion_verified", False),
            ("exact_pr_verified", False),
            ("ready_for_review_verified", False),
            ("reviewer_requests_verified", False),
            ("post_lifecycle_verified", False),
            ("review_submission_authorized", True),
            ("review_thread_mutation_authorized", True),
            ("ready_for_review_authorized", True),
            ("reviewer_request_authorized", True),
            ("remote_write_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("merge_authorized", True),
            ("release_authorized", True),
            ("deploy_authorized", True),
            ("production_activation_authorized", True),
            ("draft", True),
            ("nonce_reusable", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    post_lifecycle.PilotExactTaskPostLifecycleAttestationReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        # Any second durable completion source is ambiguous even before parsing it.
        recovery_final, _recovery_lock = empty_recovery_ledger._paths(
            authorization.execution_nonce_sha256
        )
        recovery_final.write_text("{}", encoding="utf-8")
        _reject(
            lambda: _attest(
                authorization=authorization,
                tx_ledger=tx_ledger,
                recovery_ledger=empty_recovery_ledger,
                lifecycle_auth_root=lifecycle_auth_root,
                publication_auth_root=publication_auth_root,
                local_root=local_root,
                transport=_RecoveryTransport(
                    draft=False,
                    usernames=authorization.reviewer_usernames,
                    teams=authorization.reviewer_team_slugs,
                ),
                now="2026-09-15T09:31:10Z",
            )
        )
        recovery_final.unlink()

        # Remote reviewer drift between observations fails closed.
        drift = _RecoveryTransport(
            draft=False,
            usernames=authorization.reviewer_usernames,
            teams=authorization.reviewer_team_slugs,
        )
        drift.scripted = [
            (
                False,
                authorization.reviewer_usernames,
                authorization.reviewer_team_slugs,
            ),
            (False, (), ()),
        ]
        _reject(
            lambda: _attest(
                authorization=authorization,
                tx_ledger=tx_ledger,
                recovery_ledger=empty_recovery_ledger,
                lifecycle_auth_root=lifecycle_auth_root,
                publication_auth_root=publication_auth_root,
                local_root=local_root,
                transport=drift,
                now="2026-09-15T09:31:10Z",
            )
        )

        # Clock rollback behind durable completion is rejected.
        _reject(
            lambda: _attest(
                authorization=authorization,
                tx_ledger=tx_ledger,
                recovery_ledger=empty_recovery_ledger,
                lifecycle_auth_root=lifecycle_auth_root,
                publication_auth_root=publication_auth_root,
                local_root=local_root,
                transport=_RecoveryTransport(
                    draft=False,
                    usernames=authorization.reviewer_usernames,
                    teams=authorization.reviewer_team_slugs,
                ),
                now="2026-09-15T09:30:59Z",
            )
        )
    finally:
        empty_recovery_temp.cleanup()
        tx_temp.cleanup()

    # ADR-DC-055 missing-reviewer recovery normalizes to the same final evidence.
    recovery_tx_temp, recovery_tx_ledger = _transaction_ledger(
        "rsi-exact-task-post-lifecycle-recovery-tx-"
    )
    lifecycle_recovery_temp, lifecycle_recovery_ledger = _recovery_ledger(
        "rsi-exact-task-post-lifecycle-recovery-"
    )
    try:
        _prepare_ready_marked(authorization, attestation, recovery_tx_ledger)
        remote = _RecoveryTransport(draft=False)
        state, _intent = _observe(
            authorization=authorization,
            ledger=recovery_tx_ledger,
            lifecycle_auth_root=lifecycle_auth_root,
            publication_auth_root=publication_auth_root,
            local_root=local_root,
            transport=remote,
        )
        assert state.action_required == "request_missing_reviewers"
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
        recovery_receipt = lifecycle_recovery._recover_verified_pilot_exact_task_pr_lifecycle(
            authorization_payload=payload,
            operator_signature=operator_sig,
            reviewer_signature=reviewer_sig,
            verifier=verifier,
            transaction_ledger_root=recovery_tx_ledger.root,
            lifecycle_authorization_ledger_root=lifecycle_auth_root,
            publication_authorization_ledger_root=publication_auth_root,
            local_transaction_ledger_root=local_root,
            recovery_ledger=lifecycle_recovery_ledger,
            read_transport=remote,
            write_transport=remote,
            now_provider=lambda: next(times),
        )
        assert recovery_receipt.recovery_authenticated is True
        assert recovery_receipt.reviewers_marker_sha256 is None
        assert remote.usernames == authorization.reviewer_usernames
        assert remote.teams == authorization.reviewer_team_slugs

        receipt = _attest(
            authorization=authorization,
            tx_ledger=recovery_tx_ledger,
            recovery_ledger=lifecycle_recovery_ledger,
            lifecycle_auth_root=lifecycle_auth_root,
            publication_auth_root=publication_auth_root,
            local_root=local_root,
            transport=remote,
            now="2026-09-15T09:32:30Z",
        )
        assert receipt.completion_source == "recovery"
        assert (
            receipt.completion_source_receipt_sha256
            == recovery_receipt.sha256
        )
        assert receipt.ready_marker_sha256 is not None
        assert receipt.reviewers_marker_sha256 is None
        assert receipt.post_lifecycle_verified is True
        assert receipt.attestation_authenticated is True
    finally:
        lifecycle_recovery_temp.cleanup()
        recovery_tx_temp.cleanup()

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    receipt_fields = set(
        post_lifecycle.PilotExactTaskPostLifecycleAttestationReceipt.__dataclass_fields__
    )
    assert set(schema["properties"]) == receipt_fields
    assert set(schema["required"]) == receipt_fields
    assert schema["properties"]["review_submission_authorized"]["const"] is False
    assert schema["properties"]["review_thread_mutation_authorized"]["const"] is False
    assert schema["properties"]["merge_authorized"]["const"] is False
    assert schema["properties"]["production_activation_authorized"]["const"] is False
    assert schema["properties"]["nonce_reusable"]["const"] is False

    public = inspect.signature(
        post_lifecycle.attest_pilot_exact_task_post_lifecycle
    ).parameters
    assert tuple(public) == ("execution_nonce_sha256",)
    source = inspect.getsource(post_lifecycle)
    assert 'method="POST"' not in source
    assert "request_reviewers(" not in source
    assert "mark_ready(" not in source
    assert "markPullRequestReadyForReview" not in source
    assert "merge_pull_request" not in source
    assert "enable_auto_merge" not in source
    assert "merge_authorized: bool = False" in source
    assert "production_activation_authorized: bool = False" in source

    _cleanup_bundle(bundle)


if __name__ == "__main__":
    run_contract()