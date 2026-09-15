"""Adversarial contract for ADR-DC-060 ready-for-review human authorization."""
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
from kaliv_dev_control import (  # noqa: E402
    _improvement_pilot_exact_task_pr_ready_for_review_authorization_impl as auth_impl,
)
from kaliv_dev_control import improvement_pilot_exact_task_pr_create_transaction as pr_create  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_ready_for_review_authorization as ready_auth  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_review_handoff_requirements as handoff  # noqa: E402
from rsi_pilot_exact_task_pr_review_handoff_requirements_contract import (  # noqa: E402
    _live_transaction,
    _reader,
)

CLAIM_SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-pr-ready-for-review-authorization-v1.schema.json"
)
PROOF_SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-pr-ready-for-review-authorization-proof-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        ready_auth.PilotExactTaskPrReadyAuthorizationError,
        handoff.PilotExactTaskPrReviewHandoffRequirementsError,
        ValueError,
        TypeError,
    ):
        return
    raise AssertionError("ADR-DC-060 unexpectedly accepted unsafe ready authority")


def _human_authority(claim: ready_auth.PilotExactTaskPrReadyAuthorization):
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("60" * 32))
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    policy = asymmetric_authority_key_custody_policy_sha256()
    key = TrustedEd25519AuthorityKey(
        key_id="exact-pr-ready-human-key-001",
        issuer_actor_id=claim.ready_for_review_authorizer_actor_id,
        issuer_system_id=ready_auth.PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_ISSUER_SYSTEM_ID,
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

    tx, _pr_requirements, identity, cleanup = _live_transaction()
    try:
        review_requirements = handoff._materialize_verified_pilot_exact_task_pr_review_handoff_requirements(
            pr_create_transaction=tx,
            reader=_reader,
            now_provider=lambda: "2026-09-15T06:24:00Z",
        )
        assert review_requirements.requirements_authenticated is True
        prior = ready_auth._prior_nonces(review_requirements)
        assert set(prior) == {
            "execution_nonce_sha256",
            "local_write_nonce_sha256",
            "remote_publication_nonce_sha256",
            "pr_mutation_nonce_sha256",
        }
        assert len(set(prior.values())) == 4
        assert prior["pr_mutation_nonce_sha256"] == tx.pr_mutation_nonce_sha256

        ready_nonce = hashlib.sha256(b"ready-for-review-nonce-060").hexdigest()
        assert ready_nonce not in set(prior.values())
        claim = ready_auth.build_pilot_exact_task_pr_ready_authorization(
            review_handoff_requirements=review_requirements,
            authorization_id="exact-pr-ready-authorization-060",
            ready_for_review_authorizer_actor_id=(
                review_requirements.required_ready_for_review_authorizer_actor_id
            ),
            authorized_at_utc="2026-09-15T06:24:10Z",
            expires_at_utc="2026-09-15T06:34:00Z",
            ready_for_review_nonce_sha256=ready_nonce,
            notes=("authorize exact ready-for-review handoff only",),
        )
        assert claim.review_handoff_requirements is review_requirements
        assert claim.review_handoff_requirements_sha256 == review_requirements.sha256
        assert claim.pr_create_transaction_sha256 == tx.sha256
        assert claim.predicted_commit_sha == identity.predicted_commit_sha
        assert claim.pr_mutation_nonce_sha256 == tx.pr_mutation_nonce_sha256
        assert claim.ready_for_review_nonce_sha256 == ready_nonce
        assert claim.ready_for_review_authorizer_actor_id == (
            review_requirements.required_ready_for_review_authorizer_actor_id
        )
        for name, value in prior.items():
            assert getattr(claim, name) == value

        verifier, signature = _human_authority(claim)
        proof = ready_auth._verify_pilot_exact_task_pr_ready_authorization(
            review_handoff_requirements=review_requirements,
            authorization=claim,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-15T06:24:20Z",
        )
        assert proof.authorization_sha256 == claim.sha256
        assert proof.signature_sha256 == signature.sha256
        assert proof.issuer_actor_id == claim.ready_for_review_authorizer_actor_id
        assert proof.review_handoff_requirements_sha256 == review_requirements.sha256
        assert proof.pr_create_transaction_sha256 == tx.sha256
        assert proof.predicted_commit_sha == identity.predicted_commit_sha
        assert proof.review_handoff_plan_sha256 == review_requirements.review_handoff_plan_sha256
        assert proof.ready_for_review_nonce_sha256 == ready_nonce
        assert proof.human_ready_for_review_authorization_verified is True

        for field in (
            "one_shot_ready_for_review_required",
            "fresh_pr_state_revalidation_before_ready_required",
            "reviewer_mutation_separate_authority_required",
            "label_mutation_separate_authority_required",
            "merge_separate_authority_required",
        ):
            assert getattr(proof, field) is True
        for field in (
            "ready_for_review_authorization_consumed",
            "ready_for_review_authorized",
            "ready_for_review_performed",
            "reviewer_mutation_authorized",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(proof, field) is False

        claim_reloaded = ready_auth.PilotExactTaskPrReadyAuthorization.from_mapping(
            claim.to_dict()
        )
        assert claim_reloaded == claim
        assert claim_reloaded.sha256 == claim.sha256
        proof_reloaded = ready_auth.PilotExactTaskPrReadyAuthorizationProof.from_mapping(
            proof.to_dict()
        )
        assert proof_reloaded == proof
        assert proof_reloaded.sha256 == proof.sha256

        reloaded_requirements = handoff.PilotExactTaskPrReviewHandoffRequirements.from_mapping(
            review_requirements.to_dict()
        )
        assert reloaded_requirements.requirements_authenticated is False
        _reject(lambda: ready_auth.build_pilot_exact_task_pr_ready_authorization(
            review_handoff_requirements=reloaded_requirements,
            authorization_id="reloaded-ready-auth-060",
            ready_for_review_authorizer_actor_id=(
                review_requirements.required_ready_for_review_authorizer_actor_id
            ),
            authorized_at_utc="2026-09-15T06:24:10Z",
            expires_at_utc="2026-09-15T06:34:00Z",
            ready_for_review_nonce_sha256=ready_nonce,
        ))

        for reused in (
            prior["execution_nonce_sha256"],
            prior["pr_mutation_nonce_sha256"],
        ):
            _reject(lambda reused=reused: ready_auth.build_pilot_exact_task_pr_ready_authorization(
                review_handoff_requirements=review_requirements,
                authorization_id="reused-ready-nonce-060",
                ready_for_review_authorizer_actor_id=(
                    review_requirements.required_ready_for_review_authorizer_actor_id
                ),
                authorized_at_utc="2026-09-15T06:24:10Z",
                expires_at_utc="2026-09-15T06:34:00Z",
                ready_for_review_nonce_sha256=reused,
            ))

        _reject(lambda: ready_auth.build_pilot_exact_task_pr_ready_authorization(
            review_handoff_requirements=review_requirements,
            authorization_id="wrong-ready-actor-060",
            ready_for_review_authorizer_actor_id="another-human-actor",
            authorized_at_utc="2026-09-15T06:24:10Z",
            expires_at_utc="2026-09-15T06:34:00Z",
            ready_for_review_nonce_sha256=ready_nonce,
        ))
        _reject(lambda: ready_auth._verify_pilot_exact_task_pr_ready_authorization(
            review_handoff_requirements=review_requirements,
            authorization=claim,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-15T06:34:01Z",
        ))

        # Production facade must not accept a caller-selected verifier.
        _reject(lambda: ready_auth.verify_pilot_exact_task_pr_ready_authorization(
            review_handoff_requirements=review_requirements,
            authorization=claim,
            signature=signature,
            verifier=verifier,
        ))

        claim_schema = json.loads(CLAIM_SCHEMA.read_text(encoding="utf-8"))
        proof_schema = json.loads(PROOF_SCHEMA.read_text(encoding="utf-8"))
        assert set(claim_schema["properties"]) == set(claim.to_dict())
        assert set(claim_schema["required"]) == set(claim.to_dict())
        assert set(proof_schema["properties"]) == set(proof.to_dict())
        assert set(proof_schema["required"]) == set(proof.to_dict())
        assert claim_schema["properties"]["human_ready_for_review_authorization_verified"]["const"] is False
        assert proof_schema["properties"]["human_ready_for_review_authorization_verified"]["const"] is True
        assert proof_schema["properties"]["ready_for_review_authorized"]["const"] is False
        assert proof_schema["properties"]["merge_authorized"]["const"] is False
        assert proof_schema["properties"]["production_activation_authorized"]["const"] is False

        build_parameters = inspect.signature(
            ready_auth.build_pilot_exact_task_pr_ready_authorization
        ).parameters
        assert tuple(build_parameters) == (
            "review_handoff_requirements",
            "authorization_id",
            "ready_for_review_authorizer_actor_id",
            "authorized_at_utc",
            "expires_at_utc",
            "ready_for_review_nonce_sha256",
            "notes",
        )
        verify_parameters = inspect.signature(
            ready_auth.verify_pilot_exact_task_pr_ready_authorization
        ).parameters
        assert tuple(verify_parameters) == (
            "review_handoff_requirements",
            "authorization",
            "signature",
            "verifier",
        )

        source = inspect.getsource(auth_impl)
        assert "create_pull_request(" not in source
        assert "update_pull_request(" not in source
        assert "mark_pull_request_ready_for_review(" not in source
        assert "request_pull_request_reviewers(" not in source
        assert "merge_pull_request(" not in source
        assert "urllib.request" not in source
        assert "requests." not in source
        assert "ready_for_review_authorized: bool = False" in source
        assert "production_activation_authorized: bool = False" in source

        reloaded_tx = pr_create.PilotExactTaskPrCreateTransaction.from_mapping(tx.to_dict())
        assert reloaded_tx.transaction_authenticated is False
    finally:
        for temp in cleanup:
            temp.cleanup()


if __name__ == "__main__":
    run_contract()
