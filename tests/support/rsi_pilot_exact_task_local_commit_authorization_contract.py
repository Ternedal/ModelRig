"""Adversarial contract for ADR-DC-044 human exact local-commit authority."""
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
    _improvement_pilot_exact_task_local_commit_authorization_impl as auth_impl,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_authorization as auth,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_object_identity as object_identity,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_write_requirements as write_requirements,
)
from rsi_pilot_exact_task_local_commit_object_identity_contract import (  # noqa: E402
    _identity_reader,
    _live_plan,
)

CLAIM_SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-local-commit-authorization-v1.schema.json"
)
PROOF_SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-local-commit-authorization-proof-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (auth.PilotExactTaskLocalCommitAuthorizationError, ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-044 unexpectedly accepted invalid authority")


def _material():
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        evaluation,
        execution_receipt,
        execution_plan,
        local_plan,
        task,
        fixture,
        staged,
    ) = _live_plan()
    blob_sha = "1" * 40
    index_payload = f"100644 {blob_sha} 0\tVERSION\0".encode("ascii")
    _calls, reader = _identity_reader(
        workspace=fixture["workspace"],
        base_sha=task.base_sha,
        staged=staged,
        index_payload=index_payload,
    )
    with patch.object(fixture["git_runner"], "run", side_effect=reader):
        identity = (
            object_identity._materialize_verified_pilot_exact_task_local_commit_object_identity(
                local_commit_plan=local_plan,
                now_provider=lambda: "2026-09-15T06:10:00Z",
            )
        )
    requirements = (
        write_requirements.materialize_pilot_exact_task_local_commit_write_requirements(
            identity
        )
    )
    return (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        identity,
        requirements,
    )


def _human_authority(claim: auth.PilotExactTaskLocalCommitAuthorization):
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("44" * 32))
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    policy = asymmetric_authority_key_custody_policy_sha256()
    key = TrustedEd25519AuthorityKey(
        key_id="exact-local-commit-human-key-001",
        issuer_actor_id=claim.local_commit_authorizer_actor_id,
        issuer_system_id=auth.PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ISSUER_SYSTEM_ID,
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


def _claim(requirements: write_requirements.PilotExactTaskLocalCommitWriteRequirements):
    return auth.build_pilot_exact_task_local_commit_authorization(
        local_commit_write_requirements=requirements,
        authorization_id="exact-local-commit-authorization-044",
        local_commit_authorizer_actor_id=requirements.execution_authorizer_actor_id,
        authorized_at_utc="2026-09-15T06:11:00Z",
        expires_at_utc="2026-09-15T06:21:00Z",
        local_write_nonce_sha256=hashlib.sha256(b"local-write-nonce-044").hexdigest(),
        notes=("one exact local commit write only",),
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
        identity,
        requirements,
    ) = _material()
    try:
        claim = _claim(requirements)
        assert claim.local_commit_write_requirements is requirements
        assert claim.local_commit_write_requirements_sha256 == requirements.sha256
        assert claim.local_commit_object_identity_sha256 == identity.sha256
        assert claim.execution_nonce_sha256 == requirements.execution_nonce_sha256
        assert claim.execution_authorizer_actor_id == requirements.execution_authorizer_actor_id
        assert claim.local_commit_authorizer_actor_id == requirements.execution_authorizer_actor_id
        assert claim.predicted_commit_sha == requirements.predicted_commit_sha
        assert claim.local_write_nonce_sha256 != claim.execution_nonce_sha256
        assert claim.one_shot_local_write_required is True
        assert claim.local_write_authorization_consumed is False
        assert claim.human_local_commit_authorization_verified is False
        assert claim.git_object_write_authorized is False
        assert claim.local_ref_update_authorized is False
        assert claim.local_commit_authorized is False
        assert claim.local_commit_created is False
        assert claim.push_authorized is False
        assert claim.production_activation_authorized is False
        assert auth.PilotExactTaskLocalCommitAuthorization.from_mapping(
            claim.to_dict()
        ) == claim

        verifier, signature = _human_authority(claim)
        proof = auth._verify_pilot_exact_task_local_commit_authorization(
            local_commit_write_requirements=requirements,
            authorization=claim,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-15T06:12:00Z",
        )
        assert proof.authorization == claim
        assert proof.authorization_sha256 == claim.sha256
        assert proof.local_commit_write_requirements_sha256 == requirements.sha256
        assert proof.local_commit_object_identity_sha256 == identity.sha256
        assert proof.execution_nonce_sha256 == requirements.execution_nonce_sha256
        assert proof.local_write_nonce_sha256 == claim.local_write_nonce_sha256
        assert proof.predicted_commit_sha == requirements.predicted_commit_sha
        assert proof.human_local_commit_authorization_verified is True
        assert proof.one_shot_local_write_required is True
        assert proof.local_write_authorization_consumed is False
        assert proof.git_object_write_authorized is False
        assert proof.local_ref_update_authorized is False
        assert proof.local_commit_authorized is False
        assert proof.local_commit_created is False
        assert proof.remote_write_authorized is False
        assert proof.push_authorized is False
        assert proof.pr_mutation_authorized is False
        assert proof.merge_authorized is False
        assert proof.release_authorized is False
        assert proof.deploy_authorized is False
        assert proof.production_activation_authorized is False
        assert auth.PilotExactTaskLocalCommitAuthorizationProof.from_mapping(
            proof.to_dict()
        ) == proof

        # Production never accepts a caller-selected verifier.
        _reject(
            lambda: auth.verify_pilot_exact_task_local_commit_authorization(
                local_commit_write_requirements=requirements,
                authorization=claim,
                signature=signature,
                verifier=verifier,
            )
        )

        wrong_actor = claim.to_dict()
        wrong_actor["local_commit_authorizer_actor_id"] = "different-human"
        _reject(lambda: auth.PilotExactTaskLocalCommitAuthorization.from_mapping(wrong_actor))

        reused_nonce = claim.to_dict()
        reused_nonce["local_write_nonce_sha256"] = claim.execution_nonce_sha256
        _reject(lambda: auth.PilotExactTaskLocalCommitAuthorization.from_mapping(reused_nonce))

        too_long = claim.to_dict()
        too_long["expires_at_utc"] = "2026-09-15T06:21:01Z"
        _reject(lambda: auth.PilotExactTaskLocalCommitAuthorization.from_mapping(too_long))

        predates_identity = claim.to_dict()
        predates_identity["authorized_at_utc"] = "2026-09-15T06:09:59Z"
        _reject(
            lambda: auth.PilotExactTaskLocalCommitAuthorization.from_mapping(
                predates_identity
            )
        )

        rebound = claim.to_dict()
        rebound["predicted_commit_sha"] = "a" * 40
        _reject(lambda: auth.PilotExactTaskLocalCommitAuthorization.from_mapping(rebound))

        forged_requirements = claim.to_dict()
        forged_requirements["local_commit_write_requirements"] = {
            **forged_requirements["local_commit_write_requirements"],
            "local_commit_authorized": True,
        }
        _reject(
            lambda: auth.PilotExactTaskLocalCommitAuthorization.from_mapping(
                forged_requirements
            )
        )

        changed_claim = claim.to_dict()
        changed_claim["notes"] = ["changed after signature"]
        changed = auth.PilotExactTaskLocalCommitAuthorization.from_mapping(changed_claim)
        _reject(
            lambda: auth._verify_pilot_exact_task_local_commit_authorization(
                local_commit_write_requirements=requirements,
                authorization=changed,
                signature=signature,
                verifier=verifier,
                now_provider=lambda: "2026-09-15T06:12:00Z",
            )
        )

        for field in (
            "git_object_write_authorized",
            "local_ref_update_authorized",
            "local_commit_authorized",
            "local_commit_created",
            "integration_ready",
            "product_pilot_started",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            _reject(
                lambda field=field: auth.PilotExactTaskLocalCommitAuthorizationProof.from_mapping(
                    {**proof.to_dict(), field: True}
                )
            )

        claim_schema = json.loads(CLAIM_SCHEMA.read_text(encoding="utf-8"))
        proof_schema = json.loads(PROOF_SCHEMA.read_text(encoding="utf-8"))
        assert set(claim_schema["properties"]) == set(claim.to_dict())
        assert set(proof_schema["properties"]) == set(proof.to_dict())
        assert set(claim_schema["required"]) == set(claim.to_dict())
        assert set(proof_schema["required"]) == set(proof.to_dict())
        assert claim_schema["additionalProperties"] is False
        assert proof_schema["additionalProperties"] is False
        assert claim_schema["properties"]["local_commit_write_requirements"]["$ref"] == (
            "rsi-pilot-exact-task-local-commit-write-requirements-v1.schema.json"
        )
        assert proof_schema["properties"]["human_local_commit_authorization_verified"]["const"] is True
        for field in (
            "git_object_write_authorized",
            "local_ref_update_authorized",
            "local_commit_authorized",
            "local_commit_created",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert proof_schema["properties"][field]["const"] is False

        facade_source = inspect.getsource(auth).lower()
        impl_source = inspect.getsource(auth_impl).lower()
        for forbidden in (
            "subprocess",
            "shell=true",
            '"write-tree"',
            '"commit-tree"',
            '("commit",',
            '("update-ref",',
            '("push",',
            "merge_pull_request",
            "create_pull_request",
        ):
            assert forbidden not in facade_source, forbidden
            assert forbidden not in impl_source, forbidden
    finally:
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
