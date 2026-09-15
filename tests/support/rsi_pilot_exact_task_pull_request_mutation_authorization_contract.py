"""Adversarial contract for ADR-DC-055 human PR-mutation authority."""
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
    _improvement_pilot_exact_task_pull_request_mutation_authorization_impl as auth_impl,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_pull_request_mutation_authorization as auth,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_pull_request_mutation_requirements as pr_requirements,
)
from rsi_pilot_exact_task_pull_request_mutation_requirements_contract import (  # noqa: E402
    _completed_transaction,
)

CLAIM_SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-pull-request-mutation-authorization-v1.schema.json"
)
PROOF_SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-pull-request-mutation-authorization-proof-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        auth.PilotExactTaskPullRequestMutationAuthorizationError,
        ValueError,
        TypeError,
    ):
        return
    raise AssertionError("ADR-DC-055 unexpectedly accepted invalid PR authority")


def _material():
    (
        material,
        ledger_temp,
        broker_temp,
        reservation_receipt,
        credential_capability,
        remote_transaction,
    ) = _completed_transaction()
    requirements = pr_requirements._materialize_verified_pilot_exact_task_pull_request_mutation_requirements(
        remote_publication_write_transaction=remote_transaction,
        now_provider=lambda: "2026-09-15T06:22:00Z",
    )
    assert requirements.requirements_authenticated is True
    return (
        material,
        ledger_temp,
        broker_temp,
        reservation_receipt,
        credential_capability,
        remote_transaction,
        requirements,
    )


def _human_authority(claim: auth.PilotExactTaskPullRequestMutationAuthorization):
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("55" * 32))
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    policy = asymmetric_authority_key_custody_policy_sha256()
    key = TrustedEd25519AuthorityKey(
        key_id="exact-pr-mutation-human-key-001",
        issuer_actor_id=claim.pr_mutation_authorizer_actor_id,
        issuer_system_id=(
            auth.PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_AUTHORIZATION_ISSUER_SYSTEM_ID
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


def _claim(requirements):
    return auth.build_pilot_exact_task_pull_request_mutation_authorization(
        pull_request_mutation_requirements=requirements,
        authorization_id="exact-pr-mutation-authorization-055",
        pr_mutation_authorizer_actor_id="pr-mutation-human",
        authorized_at_utc="2026-09-15T06:23:00Z",
        expires_at_utc="2026-09-15T06:33:00Z",
        pr_mutation_nonce_sha256=hashlib.sha256(
            b"pull-request-mutation-nonce-055"
        ).hexdigest(),
        notes=("authorize exact draft PR creation only",),
    )


def run_contract() -> None:
    if os.name == "nt":
        return
    material = _material()
    requirements = material[-1]
    source_material = material[0]
    try:
        claim = _claim(requirements)
        assert claim.pull_request_mutation_requirements is requirements
        assert claim.pull_request_mutation_requirements_sha256 == requirements.sha256
        assert (
            claim.remote_publication_write_transaction_sha256
            == requirements.remote_publication_write_transaction_sha256
        )
        assert claim.repository == "Ternedal/ModelRig"
        assert claim.api_host == "api.github.com"
        assert claim.base_ref == "main"
        assert claim.head_ref == requirements.head_ref
        assert claim.head_branch == requirements.head_branch
        assert claim.predicted_commit_sha == requirements.predicted_commit_sha
        assert claim.pr_mutation_nonce_sha256 != claim.remote_publication_nonce_sha256
        for field in (
            "draft_pull_request_required",
            "create_only_pull_request_required",
            "existing_open_pull_request_absent_required",
            "same_repository_head_required",
            "exact_base_ref_required",
            "exact_head_ref_required",
            "exact_head_sha_required",
            "one_shot_pr_mutation_required",
            "fresh_pull_request_state_observation_before_write_required",
            "one_shot_pr_mutation_reservation_required",
            "host_pinned_pr_credential_capability_required",
            "merge_separately_authorized_required",
        ):
            assert getattr(claim, field) is True
        for field in (
            "human_pr_mutation_authorization_verified",
            "pr_mutation_authorization_consumed",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "pull_request_create_authorized",
            "pull_request_update_authorized",
            "ready_for_review_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(claim, field) is False
        assert auth.PilotExactTaskPullRequestMutationAuthorization.from_mapping(
            claim.to_dict()
        ) == claim

        verifier, signature = _human_authority(claim)
        proof = auth._verify_pilot_exact_task_pull_request_mutation_authorization(
            pull_request_mutation_requirements=requirements,
            authorization=claim,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-15T06:24:00Z",
        )
        assert proof.authorization == claim
        assert proof.authorization_sha256 == claim.sha256
        assert proof.pull_request_mutation_requirements_sha256 == requirements.sha256
        assert proof.predicted_commit_sha == requirements.predicted_commit_sha
        assert (
            proof.remote_publication_nonce_sha256
            == requirements.remote_publication_nonce_sha256
        )
        assert proof.pr_mutation_nonce_sha256 == claim.pr_mutation_nonce_sha256
        assert proof.human_pr_mutation_authorization_verified is True
        assert proof.pr_mutation_authorization_consumed is False
        assert proof.pr_mutation_authorized is False
        assert proof.pull_request_create_authorized is False
        assert proof.pull_request_update_authorized is False
        assert proof.ready_for_review_authorized is False
        assert proof.merge_authorized is False
        assert proof.release_authorized is False
        assert proof.deploy_authorized is False
        assert proof.production_activation_authorized is False
        reloaded_proof = auth.PilotExactTaskPullRequestMutationAuthorizationProof.from_mapping(
            proof.to_dict()
        )
        assert reloaded_proof == proof
        assert reloaded_proof.sha256 == proof.sha256

        # Structural replay remains auditable, but cannot mint/verify new authority.
        reloaded_requirements = (
            pr_requirements.PilotExactTaskPullRequestMutationRequirements.from_mapping(
                requirements.to_dict()
            )
        )
        assert reloaded_requirements.requirements_authenticated is False
        _reject(
            lambda: auth.build_pilot_exact_task_pull_request_mutation_authorization(
                pull_request_mutation_requirements=reloaded_requirements,
                authorization_id="reloaded-must-not-authorize",
                pr_mutation_authorizer_actor_id="pr-mutation-human",
                authorized_at_utc="2026-09-15T06:23:00Z",
                expires_at_utc="2026-09-15T06:33:00Z",
                pr_mutation_nonce_sha256=hashlib.sha256(b"reload-pr").hexdigest(),
            )
        )
        _reject(
            lambda: auth._verify_pilot_exact_task_pull_request_mutation_authorization(
                pull_request_mutation_requirements=reloaded_requirements,
                authorization=claim,
                signature=signature,
                verifier=verifier,
                now_provider=lambda: "2026-09-15T06:24:00Z",
            )
        )

        reused_nonce = claim.to_dict()
        reused_nonce["pr_mutation_nonce_sha256"] = claim.remote_publication_nonce_sha256
        _reject(
            lambda: auth.PilotExactTaskPullRequestMutationAuthorization.from_mapping(
                reused_nonce
            )
        )
        too_long = claim.to_dict()
        too_long["expires_at_utc"] = "2026-09-15T06:33:01Z"
        _reject(
            lambda: auth.PilotExactTaskPullRequestMutationAuthorization.from_mapping(
                too_long
            )
        )
        predates_requirements = claim.to_dict()
        predates_requirements["authorized_at_utc"] = "2026-09-15T06:21:59Z"
        _reject(
            lambda: auth.PilotExactTaskPullRequestMutationAuthorization.from_mapping(
                predates_requirements
            )
        )
        tampered_head = claim.to_dict()
        tampered_head["head_branch"] = "main"
        _reject(
            lambda: auth.PilotExactTaskPullRequestMutationAuthorization.from_mapping(
                tampered_head
            )
        )
        tampered_commit = claim.to_dict()
        tampered_commit["predicted_commit_sha"] = "f" * 40
        _reject(
            lambda: auth.PilotExactTaskPullRequestMutationAuthorization.from_mapping(
                tampered_commit
            )
        )

        # Production never accepts a caller-selected fixture verifier.
        _reject(
            lambda: auth.verify_pilot_exact_task_pull_request_mutation_authorization(
                pull_request_mutation_requirements=requirements,
                authorization=claim,
                signature=signature,
                verifier=verifier,
            )
        )

        for field in (
            "draft_pull_request_required",
            "create_only_pull_request_required",
            "existing_open_pull_request_absent_required",
            "same_repository_head_required",
            "exact_base_ref_required",
            "exact_head_ref_required",
            "exact_head_sha_required",
            "one_shot_pr_mutation_required",
            "fresh_pull_request_state_observation_before_write_required",
            "one_shot_pr_mutation_reservation_required",
            "host_pinned_pr_credential_capability_required",
            "merge_separately_authorized_required",
        ):
            changed = claim.to_dict()
            changed[field] = False
            _reject(
                lambda changed=changed: auth.PilotExactTaskPullRequestMutationAuthorization.from_mapping(
                    changed
                )
            )
        for field in (
            "human_pr_mutation_authorization_verified",
            "pr_mutation_authorization_consumed",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "pull_request_create_authorized",
            "pull_request_update_authorized",
            "ready_for_review_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            changed = claim.to_dict()
            changed[field] = True
            _reject(
                lambda changed=changed: auth.PilotExactTaskPullRequestMutationAuthorization.from_mapping(
                    changed
                )
            )

        claim_schema = json.loads(CLAIM_SCHEMA.read_text(encoding="utf-8"))
        proof_schema = json.loads(PROOF_SCHEMA.read_text(encoding="utf-8"))
        assert set(claim_schema["properties"]) == set(claim.to_dict())
        assert set(claim_schema["required"]) == set(claim.to_dict())
        assert set(proof_schema["properties"]) == set(proof.to_dict())
        assert set(proof_schema["required"]) == set(proof.to_dict())
        assert claim_schema["properties"]["pr_mutation_authorized"]["const"] is False
        assert claim_schema["properties"]["pull_request_create_authorized"]["const"] is False
        assert proof_schema["properties"]["human_pr_mutation_authorization_verified"]["const"] is True
        assert proof_schema["properties"]["pr_mutation_authorized"]["const"] is False
        assert proof_schema["properties"]["merge_authorized"]["const"] is False
        assert proof_schema["properties"]["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            auth.verify_pilot_exact_task_pull_request_mutation_authorization
        ).parameters
        assert tuple(public_parameters) == (
            "pull_request_mutation_requirements",
            "authorization",
            "signature",
            "verifier",
        )

        source = inspect.getsource(auth_impl)
        for forbidden in (
            "requests",
            "urllib",
            "subprocess",
            "create_pull_request",
            "update_pull_request",
            "merge_pull_request",
            "ready_for_review",
        ):
            assert forbidden not in source
    finally:
        material[2].cleanup()
        material[1].cleanup()
        source_material[6].cleanup()
        source_material[5].cleanup()
        source_material[4].cleanup()
        source_material[3].cleanup()
        source_material[2].cleanup()
        source_material[1].cleanup()
        source_material[0].cleanup()


if __name__ == "__main__":
    run_contract()
