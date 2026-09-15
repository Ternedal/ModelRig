"""Adversarial contract for ADR-DC-048 human remote-publication authority."""
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
    _improvement_pilot_exact_task_remote_publication_authorization_impl as auth_impl,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_publication_requirements as publication,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_remote_publication_authorization as auth,
)
from rsi_pilot_exact_task_local_commit_publication_requirements_contract import (  # noqa: E402
    _completed_transaction_fixture,
    _verification_reader,
)

CLAIM_SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-remote-publication-authorization-v1.schema.json"
)
PROOF_SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-remote-publication-authorization-proof-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        auth.PilotExactTaskRemotePublicationAuthorizationError,
        ValueError,
        TypeError,
    ):
        return
    raise AssertionError("ADR-DC-048 unexpectedly accepted invalid authority")


def _material():
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        source_reservation_temp,
        transaction_temp,
        identity,
        task,
        fixture,
        staged,
        index_payload,
        _write_reservation,
        completed,
    ) = _completed_transaction_fixture()
    _calls, reader = _verification_reader(
        fixture=fixture,
        task=task,
        identity=identity,
        staged=staged,
        index_payload=index_payload,
        transaction_receipt=completed,
    )
    with patch.object(fixture["git_runner"], "run", side_effect=reader), patch.object(
        publication,
        "_now_utc_seconds",
        return_value="2026-09-15T06:15:00Z",
    ):
        requirements = publication.materialize_pilot_exact_task_local_commit_publication_requirements(
            completed
        )
    assert requirements.verification_authenticated is True
    return (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        source_reservation_temp,
        transaction_temp,
        requirements,
    )


def _human_authority(claim: auth.PilotExactTaskRemotePublicationAuthorization):
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("48" * 32))
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    policy = asymmetric_authority_key_custody_policy_sha256()
    key = TrustedEd25519AuthorityKey(
        key_id="exact-remote-publication-human-key-001",
        issuer_actor_id=claim.remote_publication_authorizer_actor_id,
        issuer_system_id=auth.PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ISSUER_SYSTEM_ID,
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
    return auth.build_pilot_exact_task_remote_publication_authorization(
        local_commit_publication_requirements=requirements,
        authorization_id="exact-remote-publication-authorization-048",
        remote_publication_authorizer_actor_id="remote-publication-human",
        authorized_at_utc="2026-09-15T06:16:00Z",
        expires_at_utc="2026-09-15T06:26:00Z",
        remote_publication_nonce_sha256=hashlib.sha256(
            b"remote-publication-nonce-048"
        ).hexdigest(),
        notes=("authorize exact verified candidate only",),
    )


def run_contract() -> None:
    if os.name == "nt":
        return
    material = _material()
    requirements = material[-1]
    try:
        claim = _claim(requirements)
        assert claim.local_commit_publication_requirements is requirements
        assert claim.local_commit_publication_requirements_sha256 == requirements.sha256
        assert claim.local_commit_write_transaction_sha256 == requirements.local_commit_write_transaction_sha256
        assert claim.local_commit_object_identity_sha256 == requirements.local_commit_object_identity_sha256
        assert claim.predicted_commit_sha == requirements.predicted_commit_sha
        assert claim.local_ref == requirements.local_ref
        assert claim.remote_publication_nonce_sha256 not in {
            claim.execution_nonce_sha256,
            claim.local_write_nonce_sha256,
        }
        assert claim.one_shot_remote_publication_required is True
        assert claim.remote_target_host_pinned_required is True
        assert claim.remote_write_reservation_required is True
        assert claim.remote_branch_compare_and_swap_required is True
        assert claim.no_force_push_required is True
        assert claim.separate_pr_mutation_authorization_required is True
        assert claim.human_remote_publication_authorization_verified is False
        assert claim.remote_publication_authorization_consumed is False
        assert claim.remote_write_authorized is False
        assert claim.push_authorized is False
        assert claim.pr_mutation_authorized is False
        assert claim.merge_authorized is False
        assert claim.release_authorized is False
        assert claim.deploy_authorized is False
        assert claim.production_activation_authorized is False
        assert auth.PilotExactTaskRemotePublicationAuthorization.from_mapping(
            claim.to_dict()
        ) == claim

        verifier, signature = _human_authority(claim)
        proof = auth._verify_pilot_exact_task_remote_publication_authorization(
            local_commit_publication_requirements=requirements,
            authorization=claim,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-15T06:17:00Z",
        )
        assert proof.authorization == claim
        assert proof.authorization_sha256 == claim.sha256
        assert proof.local_commit_publication_requirements_sha256 == requirements.sha256
        assert proof.predicted_commit_sha == requirements.predicted_commit_sha
        assert proof.local_write_nonce_sha256 == requirements.local_write_nonce_sha256
        assert proof.remote_publication_nonce_sha256 == claim.remote_publication_nonce_sha256
        assert proof.human_remote_publication_authorization_verified is True
        assert proof.remote_publication_authorization_consumed is False
        assert proof.remote_write_authorized is False
        assert proof.push_authorized is False
        assert proof.pr_mutation_authorized is False
        assert proof.merge_authorized is False
        assert proof.release_authorized is False
        assert proof.deploy_authorized is False
        assert proof.production_activation_authorized is False
        reloaded_proof = auth.PilotExactTaskRemotePublicationAuthorizationProof.from_mapping(
            proof.to_dict()
        )
        assert reloaded_proof == proof
        assert reloaded_proof.sha256 == proof.sha256

        # Audit replay is structural, but creating/verifying new authority requires live ADR-DC-047.
        reloaded_requirements = publication.PilotExactTaskLocalCommitPublicationRequirements.from_mapping(
            requirements.to_dict()
        )
        assert reloaded_requirements.verification_authenticated is False
        _reject(
            lambda: auth.build_pilot_exact_task_remote_publication_authorization(
                local_commit_publication_requirements=reloaded_requirements,
                authorization_id="reloaded-must-not-authorize",
                remote_publication_authorizer_actor_id="remote-publication-human",
                authorized_at_utc="2026-09-15T06:16:00Z",
                expires_at_utc="2026-09-15T06:26:00Z",
                remote_publication_nonce_sha256=hashlib.sha256(b"reload").hexdigest(),
            )
        )
        _reject(
            lambda: auth._verify_pilot_exact_task_remote_publication_authorization(
                local_commit_publication_requirements=reloaded_requirements,
                authorization=claim,
                signature=signature,
                verifier=verifier,
                now_provider=lambda: "2026-09-15T06:17:00Z",
            )
        )

        reused_local_nonce = claim.to_dict()
        reused_local_nonce["remote_publication_nonce_sha256"] = claim.local_write_nonce_sha256
        _reject(lambda: auth.PilotExactTaskRemotePublicationAuthorization.from_mapping(reused_local_nonce))
        reused_execution_nonce = claim.to_dict()
        reused_execution_nonce["remote_publication_nonce_sha256"] = claim.execution_nonce_sha256
        _reject(lambda: auth.PilotExactTaskRemotePublicationAuthorization.from_mapping(reused_execution_nonce))
        too_long = claim.to_dict()
        too_long["expires_at_utc"] = "2026-09-15T06:26:01Z"
        _reject(lambda: auth.PilotExactTaskRemotePublicationAuthorization.from_mapping(too_long))
        predates_verification = claim.to_dict()
        predates_verification["authorized_at_utc"] = "2026-09-15T06:14:59Z"
        _reject(lambda: auth.PilotExactTaskRemotePublicationAuthorization.from_mapping(predates_verification))
        tampered_commit = claim.to_dict()
        tampered_commit["predicted_commit_sha"] = "f" * 40
        _reject(lambda: auth.PilotExactTaskRemotePublicationAuthorization.from_mapping(tampered_commit))

        # Production never accepts the caller-owned fixture verifier.
        _reject(
            lambda: auth.verify_pilot_exact_task_remote_publication_authorization(
                local_commit_publication_requirements=requirements,
                authorization=claim,
                signature=signature,
                verifier=verifier,
            )
        )

        for field in (
            "one_shot_remote_publication_required",
            "remote_target_host_pinned_required",
            "remote_write_reservation_required",
            "remote_branch_compare_and_swap_required",
            "no_force_push_required",
            "separate_pr_mutation_authorization_required",
        ):
            changed = claim.to_dict()
            changed[field] = False
            _reject(lambda changed=changed: auth.PilotExactTaskRemotePublicationAuthorization.from_mapping(changed))
        for field in (
            "human_remote_publication_authorization_verified",
            "remote_publication_authorization_consumed",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            changed = claim.to_dict()
            changed[field] = True
            _reject(lambda changed=changed: auth.PilotExactTaskRemotePublicationAuthorization.from_mapping(changed))

        claim_schema = json.loads(CLAIM_SCHEMA.read_text(encoding="utf-8"))
        proof_schema = json.loads(PROOF_SCHEMA.read_text(encoding="utf-8"))
        assert set(claim_schema["properties"]) == set(claim.to_dict())
        assert set(claim_schema["required"]) == set(claim.to_dict())
        assert set(proof_schema["properties"]) == set(proof.to_dict())
        assert set(proof_schema["required"]) == set(proof.to_dict())
        assert claim_schema["properties"]["remote_write_authorized"]["const"] is False
        assert claim_schema["properties"]["push_authorized"]["const"] is False
        assert proof_schema["properties"]["human_remote_publication_authorization_verified"]["const"] is True
        assert proof_schema["properties"]["remote_write_authorized"]["const"] is False
        assert proof_schema["properties"]["push_authorized"]["const"] is False
        assert proof_schema["properties"]["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            auth.verify_pilot_exact_task_remote_publication_authorization
        ).parameters
        assert tuple(public_parameters) == (
            "local_commit_publication_requirements",
            "authorization",
            "signature",
            "verifier",
        )
        claim_keys = set(claim.to_dict())
        assert not ({"remote_url", "remote_name", "remote_branch", "target_branch"} & claim_keys)

        source = inspect.getsource(auth_impl)
        for forbidden in (
            "subprocess",
            "shell=True",
            '("push",',
            '("update-ref",',
            "create_pull_request",
            "merge_pull_request",
        ):
            assert forbidden not in source
    finally:
        material[6].cleanup()
        material[5].cleanup()
        material[4].cleanup()
        material[3].cleanup()
        material[2].cleanup()
        material[1].cleanup()
        material[0].cleanup()


if __name__ == "__main__":
    run_contract()
