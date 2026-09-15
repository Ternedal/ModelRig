"""Adversarial contract for ADR-DC-068 human reviewer-request authorization."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from pathlib import Path

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
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_handoff_requirements as handoff  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_request_authorization as reviewer_auth  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_target_attestation as target  # noqa: E402
from rsi_pilot_exact_task_pr_reviewer_target_attestation_contract import _live_handoff  # noqa: E402

CLAIM_SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-pr-reviewer-request-authorization-v1.schema.json"
)
PROOF_SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-pr-reviewer-request-authorization-proof-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        reviewer_auth.PilotExactTaskPrReviewerRequestAuthorizationError,
        target.PilotExactTaskPrReviewerTargetAttestationError,
        handoff.PilotExactTaskPrReviewerHandoffRequirementsError,
        ValueError,
        TypeError,
    ):
        return
    raise AssertionError("ADR-DC-068 unexpectedly accepted unsafe reviewer authority")


def _human_authority(
    claim: reviewer_auth.PilotExactTaskPrReviewerRequestAuthorization,
):
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("68" * 32))
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    policy = asymmetric_authority_key_custody_policy_sha256()
    key = TrustedEd25519AuthorityKey(
        key_id="exact-pr-reviewer-request-human-key-001",
        issuer_actor_id=claim.reviewer_request_authorizer_actor_id,
        issuer_system_id=(
            reviewer_auth.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_ISSUER_SYSTEM_ID
        ),
        public_key_hex=public_hex,
        valid_from_utc="2026-09-15T00:00:00Z",
        valid_until_utc="2027-09-15T00:00:00Z",
        keyring_epoch=1,
        custody_policy_sha256=policy,
    )
    verifier = Ed25519AuthorityVerifier({key.key_id: key}, minimum_keyring_epoch=1)
    payload = claim.canonical_json().encode("utf-8")
    message = authority_signing_message(
        key_id=key.key_id,
        issuer_actor_id=key.issuer_actor_id,
        issuer_system_id=key.issuer_system_id,
        keyring_epoch=key.keyring_epoch,
        custody_policy_sha256=policy,
        payload=payload,
    )
    signature = DetachedEd25519AuthoritySignature(
        key_id=key.key_id,
        issuer_actor_id=key.issuer_actor_id,
        issuer_system_id=key.issuer_system_id,
        keyring_epoch=key.keyring_epoch,
        custody_policy_sha256=policy,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        signature_hex=private.sign(message).hex(),
        signed_at_utc=claim.authorized_at_utc,
    )
    return verifier, signature


def run_contract() -> None:
    if os.name == "nt":
        return

    reviewer_requirements, cleanup = _live_handoff()
    try:
        policy = target.PilotExactTaskPrReviewerTargetPolicy(
            policy_epoch=1,
            reviewer_login="modelrig-reviewer",
            reviewer_user_id=246813579,
        )
        target_attestation = target._attest_verified_pilot_exact_task_pr_reviewer_target(
            reviewer_handoff_requirements=reviewer_requirements,
            reviewer_target_policy=policy,
            now_provider=lambda: "2026-09-15T06:25:11Z",
        )
        assert target_attestation.attestation_authenticated is True

        prior = reviewer_auth._prior_nonces(target_attestation)
        assert set(prior) == {
            "execution_nonce_sha256",
            "local_write_nonce_sha256",
            "remote_publication_nonce_sha256",
            "pr_mutation_nonce_sha256",
            "ready_for_review_nonce_sha256",
        }
        assert len(set(prior.values())) == 5
        reviewer_nonce = hashlib.sha256(b"reviewer-request-nonce-068").hexdigest()
        assert reviewer_nonce not in set(prior.values())

        claim = reviewer_auth.build_pilot_exact_task_pr_reviewer_request_authorization(
            reviewer_target_attestation=target_attestation,
            authorization_id="exact-pr-reviewer-request-authorization-068",
            reviewer_request_authorizer_actor_id=(
                target_attestation.required_reviewer_authorizer_actor_id
            ),
            authorized_at_utc="2026-09-15T06:25:20Z",
            expires_at_utc="2026-09-15T06:35:00Z",
            reviewer_request_nonce_sha256=reviewer_nonce,
            notes=("authorize exact host-pinned reviewer request only",),
        )
        assert claim.reviewer_target_attestation is target_attestation
        assert claim.reviewer_target_attestation_sha256 == target_attestation.sha256
        assert claim.reviewer_handoff_requirements_sha256 == reviewer_requirements.sha256
        assert claim.ready_transaction_sha256 == reviewer_requirements.ready_transaction_sha256
        assert claim.predicted_commit_sha == target_attestation.predicted_commit_sha
        assert claim.reviewer_login == "modelrig-reviewer"
        assert claim.reviewer_user_id == 246813579
        assert claim.reviewer_request_nonce_sha256 == reviewer_nonce
        assert claim.reviewer_request_authorizer_actor_id == (
            target_attestation.required_reviewer_authorizer_actor_id
        )
        for name, value in prior.items():
            assert getattr(claim, name) == value

        verifier, signature = _human_authority(claim)
        proof = reviewer_auth._verify_pilot_exact_task_pr_reviewer_request_authorization(
            reviewer_target_attestation=target_attestation,
            authorization=claim,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-15T06:25:30Z",
        )
        assert proof.authorization_sha256 == claim.sha256
        assert proof.signature_sha256 == signature.sha256
        assert proof.issuer_actor_id == claim.reviewer_request_authorizer_actor_id
        assert proof.reviewer_target_attestation_sha256 == target_attestation.sha256
        assert proof.reviewer_handoff_requirements_sha256 == reviewer_requirements.sha256
        assert proof.ready_transaction_sha256 == reviewer_requirements.ready_transaction_sha256
        assert proof.predicted_commit_sha == target_attestation.predicted_commit_sha
        assert proof.reviewer_target_policy_sha256 == policy.sha256
        assert proof.reviewer_login == "modelrig-reviewer"
        assert proof.reviewer_user_id == 246813579
        assert proof.reviewer_request_nonce_sha256 == reviewer_nonce
        assert proof.human_reviewer_request_authorization_verified is True

        for field in (
            "one_shot_reviewer_request_required",
            "reviewer_identity_observation_required",
            "reviewer_requestability_observation_required",
            "fresh_pr_state_revalidation_before_reviewer_request_required",
            "reviewer_request_transaction_required",
            "team_reviewers_forbidden",
            "self_review_forbidden",
            "label_mutation_separate_authority_required",
            "merge_separate_authority_required",
        ):
            assert getattr(proof, field) is True
        for field in (
            "reviewer_request_authorization_consumed",
            "reviewer_mutation_authorized",
            "reviewer_request_performed",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(proof, field) is False

        claim_reloaded = reviewer_auth.PilotExactTaskPrReviewerRequestAuthorization.from_mapping(
            claim.to_dict()
        )
        assert claim_reloaded == claim
        assert claim_reloaded.sha256 == claim.sha256
        proof_reloaded = reviewer_auth.PilotExactTaskPrReviewerRequestAuthorizationProof.from_mapping(
            proof.to_dict()
        )
        assert proof_reloaded == proof
        assert proof_reloaded.sha256 == proof.sha256

        reloaded_target = target.PilotExactTaskPrReviewerTargetAttestation.from_mapping(
            target_attestation.to_dict()
        )
        assert reloaded_target.attestation_authenticated is False
        _reject(lambda: reviewer_auth.build_pilot_exact_task_pr_reviewer_request_authorization(
            reviewer_target_attestation=reloaded_target,
            authorization_id="reloaded-reviewer-request-auth-068",
            reviewer_request_authorizer_actor_id=(
                target_attestation.required_reviewer_authorizer_actor_id
            ),
            authorized_at_utc="2026-09-15T06:25:20Z",
            expires_at_utc="2026-09-15T06:35:00Z",
            reviewer_request_nonce_sha256=reviewer_nonce,
        ))

        for reused in (
            prior["execution_nonce_sha256"],
            prior["ready_for_review_nonce_sha256"],
        ):
            _reject(lambda reused=reused: reviewer_auth.build_pilot_exact_task_pr_reviewer_request_authorization(
                reviewer_target_attestation=target_attestation,
                authorization_id="reused-reviewer-request-nonce-068",
                reviewer_request_authorizer_actor_id=(
                    target_attestation.required_reviewer_authorizer_actor_id
                ),
                authorized_at_utc="2026-09-15T06:25:20Z",
                expires_at_utc="2026-09-15T06:35:00Z",
                reviewer_request_nonce_sha256=reused,
            ))

        _reject(lambda: reviewer_auth.build_pilot_exact_task_pr_reviewer_request_authorization(
            reviewer_target_attestation=target_attestation,
            authorization_id="wrong-reviewer-request-actor-068",
            reviewer_request_authorizer_actor_id="another-human-actor",
            authorized_at_utc="2026-09-15T06:25:20Z",
            expires_at_utc="2026-09-15T06:35:00Z",
            reviewer_request_nonce_sha256=reviewer_nonce,
        ))
        _reject(lambda: reviewer_auth._verify_pilot_exact_task_pr_reviewer_request_authorization(
            reviewer_target_attestation=target_attestation,
            authorization=claim,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-15T06:35:01Z",
        ))

        # Production facade must not accept a caller-selected verifier.
        _reject(lambda: reviewer_auth.verify_pilot_exact_task_pr_reviewer_request_authorization(
            reviewer_target_attestation=target_attestation,
            authorization=claim,
            signature=signature,
            verifier=verifier,
        ))

        claim_schema = json.loads(CLAIM_SCHEMA.read_text(encoding="utf-8"))
        proof_schema = json.loads(PROOF_SCHEMA.read_text(encoding="utf-8"))
        assert set(claim_schema["properties"]) == set(
            reviewer_auth.PilotExactTaskPrReviewerRequestAuthorization.__dataclass_fields__
        )
        assert set(claim_schema["required"]) == set(claim_schema["properties"])
        assert set(proof_schema["properties"]) == set(
            reviewer_auth.PilotExactTaskPrReviewerRequestAuthorizationProof.__dataclass_fields__
        )
        assert set(proof_schema["required"]) == set(proof_schema["properties"])

        assert tuple(inspect.signature(
            reviewer_auth.verify_pilot_exact_task_pr_reviewer_request_authorization
        ).parameters) == (
            "reviewer_target_attestation",
            "authorization",
            "signature",
            "verifier",
        )
        source = inspect.getsource(reviewer_auth)
        assert "request_pull_request_reviewers(" not in source
        assert "merge_pull_request(" not in source
    finally:
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()
