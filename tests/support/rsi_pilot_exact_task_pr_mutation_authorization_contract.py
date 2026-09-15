"""Adversarial contract for ADR-DC-054 exact draft PR requirements and authority."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
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
    _improvement_pilot_exact_task_pr_mutation_authorization_impl as auth_impl,
)
from kaliv_dev_control import improvement_pilot_exact_task_pr_mutation_authorization as auth  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_mutation_requirements as pr_requirements  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_remote_publication_credential_capability as capability  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_remote_publication_write_transaction as remote_transaction  # noqa: E402
from rsi_pilot_exact_task_remote_publication_credential_capability_contract import (  # noqa: E402
    _broker_descriptor,
    _reservation_material,
)

REQUIREMENTS_SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-mutation-requirements-v1.schema.json"
CLAIM_SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-mutation-authorization-v1.schema.json"
PROOF_SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-mutation-authorization-proof-v1.schema.json"


def _reject(fn) -> None:
    try:
        fn()
    except (
        pr_requirements.PilotExactTaskPrMutationRequirementsError,
        auth.PilotExactTaskPrMutationAuthorizationError,
        ValueError,
        TypeError,
    ):
        return
    raise AssertionError("ADR-DC-054 unexpectedly accepted unsafe PR authority")


def _human_authority(claim: auth.PilotExactTaskPrMutationAuthorization):
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("54" * 32))
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    policy = asymmetric_authority_key_custody_policy_sha256()
    key = TrustedEd25519AuthorityKey(
        key_id="exact-pr-mutation-human-key-001",
        issuer_actor_id=claim.pr_mutation_authorizer_actor_id,
        issuer_system_id=auth.PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_ISSUER_SYSTEM_ID,
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


def _live_remote_transaction():
    material, ledger_temp, reservation_receipt = _reservation_material()
    (
        source_temp,
        admission_ledger_temp,
        executor_capability_temp,
        local_reservation_temp,
        execution_temp,
        source_reservation_temp,
        transaction_temp,
        identity,
        _task,
        _fixture,
        _staged,
        _index_payload,
        _completed,
        _publication_requirements,
        attestation,
    ) = material
    broker_temp = TemporaryDirectory(prefix="rsi-pr-authority-054-")
    descriptor, _policy_path, _broker_path, _policy = _broker_descriptor(broker_temp)
    credential_capability = capability._materialize_verified_pilot_exact_task_remote_publication_credential_capability(
        remote_write_reservation=reservation_receipt,
        broker_descriptor=descriptor,
        now_provider=lambda: "2026-09-15T06:21:45Z",
    )
    transaction = remote_transaction.PilotExactTaskRemotePublicationWriteTransaction(
        credential_capability_sha256=credential_capability.sha256,
        remote_write_reservation_sha256=reservation_receipt.sha256,
        prewrite_state_observation_sha256=reservation_receipt.fresh_state_observation_sha256,
        target_attestation_sha256=credential_capability.target_attestation_sha256,
        authorization_proof_sha256=credential_capability.authorization_proof_sha256,
        local_commit_publication_requirements_sha256=credential_capability.local_commit_publication_requirements_sha256,
        local_commit_write_transaction_sha256=credential_capability.local_commit_write_transaction_sha256,
        remote_publication_nonce_sha256=credential_capability.remote_publication_nonce_sha256,
        predicted_commit_sha=identity.predicted_commit_sha,
        canonical_remote_url=credential_capability.canonical_remote_url,
        destination_ref=attestation.destination_ref,
        expected_old_remote_sha="0" * 40,
        broker_policy_sha256=credential_capability.broker_policy_sha256,
        broker_executable_path_sha256=credential_capability.broker_executable_path_sha256,
        broker_executable_sha256=credential_capability.broker_executable_sha256,
        push_stdout_sha256=hashlib.sha256(b"synthetic verified push").hexdigest(),
        push_stderr_sha256=hashlib.sha256(b"").hexdigest(),
        push_total_output_bytes=len(b"synthetic verified push"),
        started_at_utc="2026-09-15T06:21:46Z",
        pushed_at_utc="2026-09-15T06:21:47Z",
        verified_at_utc="2026-09-15T06:21:48Z",
    )
    remote_transaction._mark_remote_publication_write_transaction_authenticated(
        transaction,
        credential_capability,
    )
    assert transaction.transaction_authenticated is True
    cleanup = (
        broker_temp,
        ledger_temp,
        transaction_temp,
        source_reservation_temp,
        execution_temp,
        local_reservation_temp,
        executor_capability_temp,
        admission_ledger_temp,
        source_temp,
    )
    return transaction, identity, cleanup


def run_contract() -> None:
    if os.name == "nt":
        return

    transaction, identity, cleanup = _live_remote_transaction()
    try:
        with patch.object(
            pr_requirements,
            "_now_utc_seconds",
            return_value="2026-09-15T06:21:49Z",
        ):
            requirements = pr_requirements.materialize_pilot_exact_task_pr_mutation_requirements(
                transaction
            )
        assert requirements.requirements_authenticated is True
        assert requirements.remote_write_transaction_sha256 == transaction.sha256
        assert requirements.predicted_commit_sha == identity.predicted_commit_sha
        assert requirements.repository == "Ternedal/ModelRig"
        assert requirements.base_branch == "main"
        assert requirements.head_branch == transaction.destination_ref.removeprefix("refs/heads/")
        assert requirements.pr_title == f"RSI candidate {identity.predicted_commit_sha[:12]}"
        assert requirements.prior_remote_publication_authorizer_actor_id == "remote-publication-human"
        assert requirements.create_new_draft_pull_request_required is True
        assert requirements.maintainer_can_modify is False
        assert requirements.pr_mutation_authorized is False
        assert requirements.pull_request_create_authorized is False
        assert requirements.pull_request_created is False

        reloaded = pr_requirements.PilotExactTaskPrMutationRequirements.from_mapping(
            requirements.to_dict()
        )
        assert reloaded == requirements
        assert reloaded.requirements_authenticated is False

        nonce = hashlib.sha256(b"pr-mutation-nonce-054").hexdigest()
        claim = auth.build_pilot_exact_task_pr_mutation_authorization(
            pr_mutation_requirements=requirements,
            authorization_id="exact-pr-mutation-authorization-054",
            pr_mutation_authorizer_actor_id=requirements.prior_remote_publication_authorizer_actor_id,
            authorized_at_utc="2026-09-15T06:22:00Z",
            expires_at_utc="2026-09-15T06:32:00Z",
            pr_mutation_nonce_sha256=nonce,
            notes=("authorize exact deterministic draft PR only",),
        )
        assert claim.pr_mutation_requirements is requirements
        assert claim.pr_plan_sha256 == requirements.pr_plan_sha256
        assert claim.pr_mutation_authorizer_actor_id == "remote-publication-human"
        assert claim.pr_mutation_nonce_sha256 not in {
            claim.execution_nonce_sha256,
            claim.local_write_nonce_sha256,
            claim.remote_publication_nonce_sha256,
        }
        assert claim.pr_mutation_authorized is False
        assert claim.pull_request_create_authorized is False

        verifier, signature = _human_authority(claim)
        proof = auth._verify_pilot_exact_task_pr_mutation_authorization(
            pr_mutation_requirements=requirements,
            authorization=claim,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-15T06:23:00Z",
        )
        assert proof.authorization == claim
        assert proof.pr_mutation_requirements_sha256 == requirements.sha256
        assert proof.remote_write_transaction_sha256 == transaction.sha256
        assert proof.pr_plan_sha256 == requirements.pr_plan_sha256
        assert proof.pr_mutation_nonce_sha256 == nonce
        assert proof.human_pr_mutation_authorization_verified is True
        assert proof.pr_mutation_authorization_consumed is False
        assert proof.pr_mutation_authorized is False
        assert proof.pull_request_create_authorized is False
        assert proof.pull_request_created is False
        assert proof.merge_authorized is False
        assert proof.release_authorized is False
        assert proof.deploy_authorized is False
        assert proof.production_activation_authorized is False

        _reject(
            lambda: auth.build_pilot_exact_task_pr_mutation_authorization(
                pr_mutation_requirements=reloaded,
                authorization_id="exact-pr-mutation-reload-rejected",
                pr_mutation_authorizer_actor_id="remote-publication-human",
                authorized_at_utc="2026-09-15T06:22:00Z",
                expires_at_utc="2026-09-15T06:32:00Z",
                pr_mutation_nonce_sha256=hashlib.sha256(b"reload").hexdigest(),
            )
        )
        _reject(
            lambda: auth.build_pilot_exact_task_pr_mutation_authorization(
                pr_mutation_requirements=requirements,
                authorization_id="exact-pr-mutation-wrong-actor",
                pr_mutation_authorizer_actor_id="different-human",
                authorized_at_utc="2026-09-15T06:22:00Z",
                expires_at_utc="2026-09-15T06:32:00Z",
                pr_mutation_nonce_sha256=hashlib.sha256(b"wrong-actor").hexdigest(),
            )
        )
        _reject(
            lambda: auth.build_pilot_exact_task_pr_mutation_authorization(
                pr_mutation_requirements=requirements,
                authorization_id="exact-pr-mutation-reused-nonce",
                pr_mutation_authorizer_actor_id="remote-publication-human",
                authorized_at_utc="2026-09-15T06:22:00Z",
                expires_at_utc="2026-09-15T06:32:00Z",
                pr_mutation_nonce_sha256=requirements.remote_publication_nonce_sha256,
            )
        )
        _reject(
            lambda: auth.build_pilot_exact_task_pr_mutation_authorization(
                pr_mutation_requirements=requirements,
                authorization_id="exact-pr-mutation-long-window",
                pr_mutation_authorizer_actor_id="remote-publication-human",
                authorized_at_utc="2026-09-15T06:22:00Z",
                expires_at_utc="2026-09-15T06:32:01Z",
                pr_mutation_nonce_sha256=hashlib.sha256(b"long-window").hexdigest(),
            )
        )

        tampered_requirements = requirements.to_dict()
        tampered_requirements["pr_title"] = "tampered title"
        _reject(
            lambda: pr_requirements.PilotExactTaskPrMutationRequirements.from_mapping(
                tampered_requirements
            )
        )
        tampered_claim = claim.to_dict()
        tampered_claim["pr_body"] = claim.pr_body + " tampered"
        _reject(
            lambda: auth.PilotExactTaskPrMutationAuthorization.from_mapping(
                tampered_claim
            )
        )
        for field in (
            "pr_mutation_authorization_consumed",
            "pr_mutation_authorized",
            "pull_request_create_authorized",
            "pull_request_created",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            changed = proof.to_dict()
            changed[field] = True
            _reject(
                lambda changed=changed: auth.PilotExactTaskPrMutationAuthorizationProof.from_mapping(
                    changed
                )
            )

        _reject(
            lambda: auth.verify_pilot_exact_task_pr_mutation_authorization(
                pr_mutation_requirements=requirements,
                authorization=claim,
                signature=signature,
                verifier=verifier,
            )
        )

        requirement_schema = json.loads(REQUIREMENTS_SCHEMA.read_text(encoding="utf-8"))
        claim_schema = json.loads(CLAIM_SCHEMA.read_text(encoding="utf-8"))
        proof_schema = json.loads(PROOF_SCHEMA.read_text(encoding="utf-8"))
        assert set(requirement_schema["properties"]) == set(requirements.to_dict())
        assert set(requirement_schema["required"]) == set(requirements.to_dict())
        assert set(claim_schema["properties"]) == set(claim.to_dict())
        assert set(claim_schema["required"]) == set(claim.to_dict())
        assert set(proof_schema["properties"]) == set(proof.to_dict())
        assert set(proof_schema["required"]) == set(proof.to_dict())

        build_parameters = inspect.signature(
            auth.build_pilot_exact_task_pr_mutation_authorization
        ).parameters
        assert tuple(build_parameters) == (
            "pr_mutation_requirements",
            "authorization_id",
            "pr_mutation_authorizer_actor_id",
            "authorized_at_utc",
            "expires_at_utc",
            "pr_mutation_nonce_sha256",
            "notes",
        )
        for source in (
            inspect.getsource(pr_requirements),
            inspect.getsource(auth_impl),
        ):
            assert "create_pull_request(" not in source
            assert "update_pull_request(" not in source
            assert "mark_pull_request_ready_for_review(" not in source
            assert "merge_pull_request(" not in source
            assert "release_authorized: bool = False" in source
            assert "production_activation_authorized: bool = False" in source
    finally:
        for resource in cleanup:
            resource.cleanup()


if __name__ == "__main__":
    run_contract()
