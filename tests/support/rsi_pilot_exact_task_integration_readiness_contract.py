"""Adversarial contract for ADR-DC-046 semantic integration readiness."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control.asymmetric_authority import (  # noqa: E402
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
    asymmetric_authority_key_custody_policy_sha256,
    authority_signing_message,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_integration_readiness as readiness,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_post_commit_integration_evaluation as integration_eval,
)
from rsi_pilot_exact_task_post_commit_integration_evaluation_contract import (  # noqa: E402
    _evaluation_reader,
    _live_transaction,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-integration-readiness-v1.schema.json"
)
REVIEWER = "external-semantic-reviewer"
REVIEWER_SYSTEM = "external-semantic-review-system"
KEY_ID = "rsi-semantic-review-key-v1"
KEYRING_EPOCH = 7


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-046 unexpectedly accepted unsafe readiness evidence")


def _live_evaluation():
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        auth_temp,
        transaction_temp,
        evaluation,
        execution_receipt,
        execution_plan,
        local_plan,
        identity,
        authorization,
        local_transaction,
        task,
        fixture,
        index_payload,
        payload,
    ) = _live_transaction()
    calls, reader = _evaluation_reader(
        workspace=fixture["workspace"],
        local_ref=local_transaction.local_head_ref,
        base_sha=identity.base_sha,
        predicted_commit_sha=identity.predicted_commit_sha,
        root_tree_sha=identity.root_tree_sha,
        commit_payload=payload,
        index_payload=index_payload,
    )
    with patch.object(fixture["git_runner"], "run", side_effect=reader):
        receipt = integration_eval._evaluate_verified_pilot_exact_task_post_commit_integration(
            local_commit_transaction=local_transaction,
            now_provider=lambda: "2026-09-15T06:40:10Z",
        )
    assert calls
    assert receipt.evaluation_authenticated is True
    return (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        auth_temp,
        transaction_temp,
        evaluation,
        execution_receipt,
        execution_plan,
        local_plan,
        identity,
        authorization,
        local_transaction,
        receipt,
        task,
        fixture,
        index_payload,
        payload,
    )


def _review_authority():
    private_key = Ed25519PrivateKey.generate()
    public_hex = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    custody = asymmetric_authority_key_custody_policy_sha256()
    trusted = TrustedEd25519AuthorityKey(
        key_id=KEY_ID,
        issuer_actor_id=REVIEWER,
        issuer_system_id=REVIEWER_SYSTEM,
        public_key_hex=public_hex,
        valid_from_utc="2026-09-15T00:00:00Z",
        valid_until_utc="2026-09-16T00:00:00Z",
        keyring_epoch=KEYRING_EPOCH,
        custody_policy_sha256=custody,
    )
    keyring_payload = json.dumps(
        {
            "schema": readiness.PILOT_EXACT_TASK_SEMANTIC_ACCEPTANCE_KEYRING_SCHEMA,
            "minimum_keyring_epoch": KEYRING_EPOCH,
            "keys": [trusted.to_dict()],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    verifier, keyring_sha256 = readiness._parse_trusted_keyring_payload(
        keyring_payload
    )
    assert isinstance(verifier, Ed25519AuthorityVerifier)
    assert keyring_sha256 == hashlib.sha256(keyring_payload).hexdigest()
    return private_key, verifier, keyring_sha256


def _assessments(task):
    return tuple(
        readiness.PilotExactTaskSemanticCriterionAssessment(
            criterion_sha256=readiness._criterion_sha256(criterion),
            rationale=f"Externally reviewed and satisfied: {criterion}",
        )
        for criterion in task.acceptance_criteria
    )


def _signature(private_key, payload: bytes, *, signed_at: str):
    custody = asymmetric_authority_key_custody_policy_sha256()
    message = authority_signing_message(
        key_id=KEY_ID,
        issuer_actor_id=REVIEWER,
        issuer_system_id=REVIEWER_SYSTEM,
        keyring_epoch=KEYRING_EPOCH,
        custody_policy_sha256=custody,
        payload=payload,
    )
    return DetachedEd25519AuthoritySignature(
        key_id=KEY_ID,
        issuer_actor_id=REVIEWER,
        issuer_system_id=REVIEWER_SYSTEM,
        keyring_epoch=KEYRING_EPOCH,
        custody_policy_sha256=custody,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        signature_hex=private_key.sign(message).hex(),
        signed_at_utc=signed_at,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        auth_temp,
        transaction_temp,
        evaluation,
        execution_receipt,
        execution_plan,
        local_plan,
        identity,
        authorization,
        local_transaction,
        mechanical,
        task,
        fixture,
        index_payload,
        commit_payload,
    ) = _live_evaluation()
    try:
        private_key, verifier, keyring_sha256 = _review_authority()
        reviewed_at = "2026-09-15T06:41:00Z"
        acceptance_payload = readiness.build_pilot_exact_task_semantic_acceptance_payload(
            mechanical,
            _assessments(task),
            REVIEWER,
            REVIEWER_SYSTEM,
            KEY_ID,
            reviewed_at,
        )
        claim = readiness._parse_semantic_acceptance_payload(acceptance_payload)
        assert claim.post_commit_integration_evaluation_sha256 == mechanical.sha256
        assert claim.local_commit_transaction_sha256 == local_transaction.sha256
        assert claim.execution_nonce_sha256 == identity.execution_nonce_sha256
        assert claim.development_task_sha256 == identity.development_task_sha256
        assert claim.task_id == task.task_id
        assert claim.repository == task.repository
        assert claim.base_sha == task.base_sha
        assert claim.predicted_commit_sha == identity.predicted_commit_sha
        assert claim.candidate_patch_sha256 == identity.candidate_patch_sha256
        assert claim.acceptance_criteria_sha256 == readiness._acceptance_criteria_sha256(
            task.acceptance_criteria
        )
        assert tuple(item.criterion_sha256 for item in claim.criterion_assessments) == tuple(
            readiness._criterion_sha256(item) for item in task.acceptance_criteria
        )
        assert all(item.outcome == "satisfied" for item in claim.criterion_assessments)
        assert claim.remote_publication_authorized is False

        signature = _signature(
            private_key,
            acceptance_payload,
            signed_at=reviewed_at,
        )
        calls, reader = _evaluation_reader(
            workspace=fixture["workspace"],
            local_ref=local_transaction.local_head_ref,
            base_sha=identity.base_sha,
            predicted_commit_sha=identity.predicted_commit_sha,
            root_tree_sha=identity.root_tree_sha,
            commit_payload=commit_payload,
            index_payload=index_payload,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=reader):
            receipt = readiness._evaluate_verified_pilot_exact_task_integration_readiness(
                post_commit_integration_evaluation=mechanical,
                semantic_acceptance_payload=acceptance_payload,
                signature=signature,
                authority_verifier=verifier,
                trusted_reviewer_keyring_sha256=keyring_sha256,
                now_provider=lambda: "2026-09-15T06:41:01Z",
            )

        assert len(calls) == 24
        assert receipt.readiness_authenticated is True
        assert receipt.post_commit_integration_evaluation_sha256 == mechanical.sha256
        assert receipt.local_commit_transaction_sha256 == local_transaction.sha256
        assert receipt.local_commit_object_identity_sha256 == identity.sha256
        assert receipt.execution_nonce_sha256 == identity.execution_nonce_sha256
        assert receipt.development_task_sha256 == identity.development_task_sha256
        assert receipt.task_id == task.task_id
        assert receipt.repository == task.repository
        assert receipt.base_sha == task.base_sha
        assert receipt.local_head_ref == local_transaction.local_head_ref
        assert receipt.predicted_commit_sha == identity.predicted_commit_sha
        assert receipt.root_tree_sha == identity.root_tree_sha
        assert receipt.commit_payload_sha256 == identity.commit_payload_sha256
        assert receipt.candidate_patch_sha256 == identity.candidate_patch_sha256
        assert receipt.acceptance_criteria_sha256 == claim.acceptance_criteria_sha256
        assert receipt.semantic_acceptance_policy_sha256 == (
            readiness.pilot_exact_task_semantic_acceptance_policy_sha256()
        )
        assert receipt.semantic_acceptance_claim_sha256 == claim.sha256
        assert receipt.semantic_acceptance_signature_sha256 == signature.sha256
        assert receipt.trusted_reviewer_keyring_sha256 == keyring_sha256
        assert receipt.reviewer_actor_id == REVIEWER
        assert receipt.reviewer_system_id == REVIEWER_SYSTEM
        assert receipt.reviewer_key_id == KEY_ID
        assert receipt.semantic_acceptance_criteria_evaluated is True
        assert receipt.semantic_acceptance_criteria_all_satisfied is True
        assert receipt.trusted_external_semantic_review_verified is True
        assert receipt.fresh_post_commit_state_revalidated is True
        assert receipt.integration_ready is True
        assert receipt.git_object_write_authorized is False
        assert receipt.local_ref_update_authorized is False
        assert receipt.local_commit_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False

        reloaded = readiness.PilotExactTaskIntegrationReadinessReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.readiness_authenticated is False

        for field, value in (
            ("semantic_acceptance_criteria_evaluated", False),
            ("semantic_acceptance_criteria_all_satisfied", False),
            ("trusted_external_semantic_review_verified", False),
            ("integration_ready", False),
            ("git_object_write_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("merge_authorized", True),
            ("production_activation_authorized", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    readiness.PilotExactTaskIntegrationReadinessReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        reloaded_evaluation = (
            integration_eval.PilotExactTaskPostCommitIntegrationEvaluationReceipt.from_mapping(
                mechanical.to_dict()
            )
        )
        assert reloaded_evaluation.evaluation_authenticated is False
        _reject(
            lambda: readiness.build_pilot_exact_task_semantic_acceptance_payload(
                reloaded_evaluation,
                _assessments(task),
                REVIEWER,
                REVIEWER_SYSTEM,
                KEY_ID,
                reviewed_at,
            )
        )

        bad_signature = DetachedEd25519AuthoritySignature.from_mapping(
            {**signature.to_dict(), "signature_hex": "0" * 128}
        )
        bad_sig_calls, bad_sig_reader = _evaluation_reader(
            workspace=fixture["workspace"],
            local_ref=local_transaction.local_head_ref,
            base_sha=identity.base_sha,
            predicted_commit_sha=identity.predicted_commit_sha,
            root_tree_sha=identity.root_tree_sha,
            commit_payload=commit_payload,
            index_payload=index_payload,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=bad_sig_reader):
            _reject(
                lambda: readiness._evaluate_verified_pilot_exact_task_integration_readiness(
                    post_commit_integration_evaluation=mechanical,
                    semantic_acceptance_payload=acceptance_payload,
                    signature=bad_signature,
                    authority_verifier=verifier,
                    trusted_reviewer_keyring_sha256=keyring_sha256,
                    now_provider=lambda: "2026-09-15T06:41:02Z",
                )
            )
        assert bad_sig_calls == []

        wrong_claim = claim.to_dict()
        wrong_assessments = list(wrong_claim["criterion_assessments"])
        wrong_assessments[0] = {
            **wrong_assessments[0],
            "criterion_sha256": "a" * 64,
        }
        wrong_claim["criterion_assessments"] = wrong_assessments
        wrong_payload = json.dumps(
            wrong_claim,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        wrong_signature = _signature(
            private_key,
            wrong_payload,
            signed_at=reviewed_at,
        )
        _reject(
            lambda: readiness._evaluate_verified_pilot_exact_task_integration_readiness(
                post_commit_integration_evaluation=mechanical,
                semantic_acceptance_payload=wrong_payload,
                signature=wrong_signature,
                authority_verifier=verifier,
                trusted_reviewer_keyring_sha256=keyring_sha256,
                now_provider=lambda: "2026-09-15T06:41:03Z",
            )
        )

        early_payload = readiness.build_pilot_exact_task_semantic_acceptance_payload(
            mechanical,
            _assessments(task),
            REVIEWER,
            REVIEWER_SYSTEM,
            KEY_ID,
            "2026-09-15T06:40:09Z",
        )
        early_signature = _signature(
            private_key,
            early_payload,
            signed_at="2026-09-15T06:40:09Z",
        )
        _reject(
            lambda: readiness._evaluate_verified_pilot_exact_task_integration_readiness(
                post_commit_integration_evaluation=mechanical,
                semantic_acceptance_payload=early_payload,
                signature=early_signature,
                authority_verifier=verifier,
                trusted_reviewer_keyring_sha256=keyring_sha256,
                now_provider=lambda: "2026-09-15T06:41:04Z",
            )
        )

        drift_calls, drift_reader = _evaluation_reader(
            workspace=fixture["workspace"],
            local_ref=local_transaction.local_head_ref,
            base_sha=identity.base_sha,
            predicted_commit_sha=identity.predicted_commit_sha,
            root_tree_sha=identity.root_tree_sha,
            commit_payload=commit_payload,
            index_payload=index_payload,
            dirty_worktree=True,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=drift_reader):
            _reject(
                lambda: readiness._evaluate_verified_pilot_exact_task_integration_readiness(
                    post_commit_integration_evaluation=mechanical,
                    semantic_acceptance_payload=acceptance_payload,
                    signature=signature,
                    authority_verifier=verifier,
                    trusted_reviewer_keyring_sha256=keyring_sha256,
                    now_provider=lambda: "2026-09-15T06:41:05Z",
                )
            )
        assert drift_calls

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert props["integration_ready"]["const"] is True
        assert props["semantic_acceptance_criteria_evaluated"]["const"] is True
        assert props["trusted_external_semantic_review_verified"]["const"] is True
        assert props["remote_write_authorized"]["const"] is False
        assert props["push_authorized"]["const"] is False
        assert props["pr_mutation_authorized"]["const"] is False
        assert props["merge_authorized"]["const"] is False
        assert props["production_activation_authorized"]["const"] is False

        build_parameters = inspect.signature(
            readiness.build_pilot_exact_task_semantic_acceptance_payload
        ).parameters
        assert tuple(build_parameters) == (
            "post_commit_integration_evaluation",
            "criterion_assessments",
            "reviewer_actor_id",
            "reviewer_system_id",
            "reviewer_key_id",
            "reviewed_at_utc",
        )
        public_parameters = inspect.signature(
            readiness.evaluate_pilot_exact_task_integration_readiness
        ).parameters
        assert tuple(public_parameters) == (
            "post_commit_integration_evaluation",
            "semantic_acceptance_payload",
            "signature",
        )

        source = inspect.getsource(readiness)
        assert "Ed25519PrivateKey" not in source
        assert "HmacSemanticReviewVerdictSigner" not in source
        assert "create_once_file" not in source
        assert "subprocess" not in source
        assert "shell=True" not in source
        assert '("write-tree",' not in source
        assert '("hash-object",' not in source
        assert '("update-ref",' not in source
        assert '("commit",' not in source
        assert '("push",' not in source
        assert '("reset",' not in source
        assert '("clean",' not in source
    finally:
        transaction_temp.cleanup()
        auth_temp.cleanup()
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
