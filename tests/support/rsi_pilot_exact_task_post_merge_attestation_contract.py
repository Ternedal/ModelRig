"""Adversarial contract for ADR-DC-062 exact post-merge attestation."""
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
    improvement_pilot_exact_task_post_merge_attestation as post_merge,
)
from rsi_pilot_exact_task_merge_recovery_contract import (  # noqa: E402
    _RecoveryTransport,
    _dual_authority as _recovery_dual_authority,
    _observe as _observe_recovery,
    _payload as _recovery_payload,
    _recover as _recover_merge,
    _recovery_ledger,
)
from rsi_pilot_exact_task_merge_transaction_contract import (  # noqa: E402
    _Transport as _MergeTransport,
    _fresh_sequence,
    _live_merge_authorization,
    _run as _run_merge,
    _transaction_ledger,
)
from rsi_pilot_exact_task_pr_lifecycle_recovery_contract import (  # noqa: E402
    _cleanup_bundle,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-post-merge-attestation-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-062 unexpectedly accepted unsafe post-merge state")


def _attest(
    authorization,
    tx_temp,
    auth_temp,
    recovery_temp,
    transport,
    *,
    now="2026-09-15T09:41:00Z",
):
    return post_merge._attest_verified_pilot_exact_task_post_merge(
        execution_nonce_sha256=authorization.execution_nonce_sha256,
        transaction_ledger_root=Path(tx_temp.name) / "ledger",
        recovery_ledger_root=Path(recovery_temp.name) / "ledger",
        merge_authorization_ledger_root=Path(auth_temp.name) / "ledger",
        transport=transport,
        now_provider=lambda: now,
    )


def _normal_completion():
    (
        bundle,
        upstream_tx_temp,
        upstream_recovery_temp,
        auth_temp,
        _source,
        ready_review,
        policy,
        _evaluation,
        authorization,
    ) = _live_merge_authorization()
    tx_temp, tx_ledger = _transaction_ledger("rsi-exact-task-post-merge-tx-")
    recovery_temp, _recovery_ledger_value = _recovery_ledger(
        "rsi-exact-task-post-merge-empty-recovery-"
    )
    merge_transport = _MergeTransport(authorization)
    receipt = _run_merge(
        authorization,
        merge_transport,
        tx_ledger,
        _fresh_sequence(
            ready_review,
            policy,
            "2026-09-15T09:34:35Z",
            "2026-09-15T09:34:45Z",
        ),
    )
    observer = _RecoveryTransport(
        authorization,
        merged=True,
        merge_sha=receipt.merge_commit_sha,
    )
    return (
        bundle,
        upstream_tx_temp,
        upstream_recovery_temp,
        auth_temp,
        tx_temp,
        recovery_temp,
        authorization,
        receipt,
        observer,
    )


def _recovered_completion():
    (
        bundle,
        upstream_tx_temp,
        upstream_recovery_temp,
        auth_temp,
        _source,
        _ready_review,
        _policy,
        evaluation,
        authorization,
    ) = _live_merge_authorization()
    tx_temp, tx_ledger = _transaction_ledger(
        "rsi-exact-task-post-merge-recovery-source-"
    )
    recovery_temp, recovery_ledger = _recovery_ledger(
        "rsi-exact-task-post-merge-recovery-final-"
    )
    pre = _MergeTransport(authorization)._pre()
    tx_ledger.acquire(
        authorization=authorization,
        pre_state_sha256=pre.sha256,
        fresh_readiness_sha256=evaluation.sha256,
        credential_config_sha256="a" * 64,
        credential_path_sha256="b" * 64,
    )
    observer = _RecoveryTransport(authorization, merged=True)
    state, _durable = _observe_recovery(
        authorization,
        tx_temp,
        auth_temp,
        observer,
    )
    payload = _recovery_payload(state)
    verifier, op_sig, review_sig = _recovery_dual_authority(payload)
    receipt = _recover_merge(
        payload=payload,
        op_sig=op_sig,
        review_sig=review_sig,
        verifier=verifier,
        tx_temp=tx_temp,
        auth_temp=auth_temp,
        recovery_ledger=recovery_ledger,
        transport=observer,
    )
    return (
        bundle,
        upstream_tx_temp,
        upstream_recovery_temp,
        auth_temp,
        tx_temp,
        recovery_temp,
        authorization,
        receipt,
        observer,
    )


def _cleanup_case(case) -> None:
    (
        bundle,
        upstream_tx_temp,
        upstream_recovery_temp,
        auth_temp,
        tx_temp,
        recovery_temp,
        *_rest,
    ) = case
    recovery_temp.cleanup()
    tx_temp.cleanup()
    auth_temp.cleanup()
    upstream_recovery_temp.cleanup()
    upstream_tx_temp.cleanup()
    _cleanup_bundle(bundle)


def run_contract() -> None:
    if os.name == "nt":
        return

    normal = _normal_completion()
    try:
        (
            _bundle,
            _up_tx,
            _up_recovery,
            auth_temp,
            tx_temp,
            recovery_temp,
            authorization,
            source_receipt,
            observer,
        ) = normal
        receipt = _attest(
            authorization,
            tx_temp,
            auth_temp,
            recovery_temp,
            observer,
        )
        assert receipt.attestation_authenticated is True
        assert receipt.completion_source == "transaction"
        assert receipt.completion_source_receipt_sha256 == source_receipt.sha256
        assert receipt.merge_authorization_sha256 == authorization.sha256
        assert receipt.execution_nonce_sha256 == authorization.execution_nonce_sha256
        assert receipt.repository == authorization.repository
        assert receipt.repository_id == authorization.repository_id
        assert receipt.base_branch == authorization.base_branch
        assert receipt.authorized_base_sha == authorization.base_sha
        assert receipt.head_branch == authorization.head_branch
        assert receipt.head_sha == authorization.head_sha
        assert receipt.pull_request_number == authorization.pull_request_number
        assert receipt.pull_request_node_id_sha256 == authorization.pull_request_node_id_sha256
        assert receipt.merge_method == "squash"
        assert receipt.merge_commit_sha == source_receipt.merge_commit_sha
        assert receipt.source_merged_marker_present is True
        assert receipt.source_merge_response_sha256 == source_receipt.merge_response_sha256
        assert receipt.publisher_credential_config_sha256 == "a" * 64
        assert receipt.publisher_credential_path_sha256 == "b" * 64
        assert receipt.durable_completion_verified is True
        assert receipt.exact_remote_merge_verified is True
        assert receipt.exact_base_parent_verified is True
        assert receipt.double_observation_matched is True
        assert receipt.post_merge_verified is True
        assert receipt.merge_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False

        reloaded = post_merge.PilotExactTaskPostMergeAttestationReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.attestation_authenticated is False

        drift = _RecoveryTransport(
            authorization,
            merged=True,
            merge_sha=source_receipt.merge_commit_sha,
        )
        drift.scripted = [
            drift._state(merged=True),
            drift._state(merged=False),
        ]
        _reject(
            lambda: _attest(
                authorization,
                tx_temp,
                auth_temp,
                recovery_temp,
                drift,
            )
        )

        wrong_credential = _RecoveryTransport(
            authorization,
            merged=True,
            merge_sha=source_receipt.merge_commit_sha,
        )
        wrong_credential.credential_config_sha256 = "c" * 64
        _reject(
            lambda: _attest(
                authorization,
                tx_temp,
                auth_temp,
                recovery_temp,
                wrong_credential,
            )
        )

        _reject(
            lambda: _attest(
                authorization,
                tx_temp,
                auth_temp,
                recovery_temp,
                observer,
                now="2026-09-15T09:34:00Z",
            )
        )

        dual_temp, recovery_ledger = _recovery_ledger("rsi-post-merge-dual-temp-")
        try:
            dual_final, _dual_lock = recovery_ledger._paths(
                authorization.execution_nonce_sha256
            )
            dual_final.write_text("{}", encoding="utf-8")
            _reject(
                lambda: _attest(
                    authorization,
                    tx_temp,
                    auth_temp,
                    dual_temp,
                    observer,
                )
            )
        finally:
            dual_temp.cleanup()

        for field, value in (
            ("durable_completion_verified", False),
            ("exact_remote_merge_verified", False),
            ("exact_base_parent_verified", False),
            ("double_observation_matched", False),
            ("post_merge_verified", False),
            ("merge_authorized", True),
            ("remote_write_authorized", True),
            ("review_submission_authorized", True),
            ("review_thread_mutation_authorized", True),
            ("ready_for_review_authorized", True),
            ("reviewer_request_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("release_authorized", True),
            ("deploy_authorized", True),
            ("production_activation_authorized", True),
            ("product_pilot_started", True),
            ("nonce_reusable", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    post_merge.PilotExactTaskPostMergeAttestationReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )
    finally:
        _cleanup_case(normal)

    recovered = _recovered_completion()
    try:
        (
            _bundle,
            _up_tx,
            _up_recovery,
            auth_temp,
            tx_temp,
            recovery_temp,
            authorization,
            source_receipt,
            observer,
        ) = recovered
        receipt = _attest(
            authorization,
            tx_temp,
            auth_temp,
            recovery_temp,
            observer,
        )
        assert receipt.attestation_authenticated is True
        assert receipt.completion_source == "recovery"
        assert receipt.completion_source_receipt_sha256 == source_receipt.sha256
        assert receipt.merge_commit_sha == source_receipt.merge_commit_sha
        assert (
            receipt.source_merged_marker_present
            == source_receipt.source_merged_marker_present
        )
        assert (
            receipt.source_merge_response_sha256
            == source_receipt.source_merge_response_sha256
        )
    finally:
        _cleanup_case(recovered)

    no_source = _recovered_completion()
    try:
        (
            _bundle,
            _up_tx,
            _up_recovery,
            auth_temp,
            tx_temp,
            recovery_temp,
            authorization,
            _source_receipt,
            observer,
        ) = no_source
        final, lock = post_merge.recovery_boundary._PilotExactTaskMergeRecoveryLedger(
            Path(recovery_temp.name) / "ledger"
        )._paths(authorization.execution_nonce_sha256)
        final.unlink()
        _reject(
            lambda: _attest(
                authorization,
                tx_temp,
                auth_temp,
                recovery_temp,
                observer,
            )
        )
        assert lock.exists()
    finally:
        _cleanup_case(no_source)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    receipt_fields = set(
        post_merge.PilotExactTaskPostMergeAttestationReceipt.__dataclass_fields__
    )
    assert set(schema["properties"]) == receipt_fields
    assert set(schema["required"]) == receipt_fields
    assert len(receipt_fields) == 52
    assert schema["properties"]["merge_authorized"]["const"] is False
    assert schema["properties"]["release_authorized"]["const"] is False
    assert schema["properties"]["production_activation_authorized"]["const"] is False

    public = inspect.signature(
        post_merge.attest_pilot_exact_task_post_merge
    ).parameters
    assert tuple(public) == ("execution_nonce_sha256",)
    source_text = inspect.getsource(post_merge)
    assert "urllib" not in source_text
    assert "subprocess" not in source_text
    assert "merge_pull_request" not in source_text
    assert "enable_auto_merge" not in source_text
    assert "create_once_file" not in source_text
    assert "merge_authorized: bool = False" in source_text
    assert "release_authorized: bool = False" in source_text
    assert "production_activation_authorized: bool = False" in source_text


if __name__ == "__main__":
    run_contract()
