"""Adversarial contract for ADR-DC-044 human local-commit authorization."""
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

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_authorization as authorization,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_authorization_requirements as requirements,
)
from kaliv_dev_control.asymmetric_authority import (  # noqa: E402
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
    asymmetric_authority_key_custody_policy_sha256,
    authority_signing_message,
)
from rsi_pilot_exact_task_execution_plan_contract import _git_reader  # noqa: E402
from rsi_pilot_exact_task_local_commit_authorization_requirements_contract import (  # noqa: E402
    _live_identity,
)

CLAIM_SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-local-commit-human-authorization-v1.schema.json"
)
PROOF_SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-local-commit-human-authorization-proof-v1.schema.json"
)

ISSUER = "human.local-commit.authorizer"
ISSUER_SYSTEM = (
    authorization.PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ISSUER_SYSTEM_ID
)
KEY_ID = "local-commit-human-key-2026"
KEYRING_EPOCH = 1
CUSTODY = asymmetric_authority_key_custody_policy_sha256()


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-044 unexpectedly accepted invalid authority")


def _manifest():
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
        identity,
        task,
        fixture,
        staged,
    ) = _live_identity()
    _calls, reader = _git_reader(
        workspace=fixture["workspace"],
        base_sha=task.base_sha,
        staged=staged,
    )
    with patch.object(fixture["git_runner"], "run", side_effect=reader):
        manifest = (
            requirements._build_verified_pilot_exact_task_local_commit_authorization_requirements(
                object_identity=identity,
                now_provider=lambda: "2026-09-15T05:32:00Z",
            )
        )
    return (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        manifest,
        identity,
        execution_receipt,
    )


def _authority(claim):
    private_key = Ed25519PrivateKey.generate()
    public_key_hex = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    trusted = TrustedEd25519AuthorityKey(
        key_id=KEY_ID,
        issuer_actor_id=ISSUER,
        issuer_system_id=ISSUER_SYSTEM,
        public_key_hex=public_key_hex,
        valid_from_utc="2026-09-01T00:00:00Z",
        valid_until_utc="2027-09-01T00:00:00Z",
        keyring_epoch=KEYRING_EPOCH,
        custody_policy_sha256=CUSTODY,
    )
    payload = claim.canonical_json().encode("utf-8")
    message = authority_signing_message(
        key_id=KEY_ID,
        issuer_actor_id=ISSUER,
        issuer_system_id=ISSUER_SYSTEM,
        keyring_epoch=KEYRING_EPOCH,
        custody_policy_sha256=CUSTODY,
        payload=payload,
    )
    signature = DetachedEd25519AuthoritySignature(
        key_id=KEY_ID,
        issuer_actor_id=ISSUER,
        issuer_system_id=ISSUER_SYSTEM,
        keyring_epoch=KEYRING_EPOCH,
        custody_policy_sha256=CUSTODY,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        signature_hex=private_key.sign(message).hex(),
        signed_at_utc=claim.authorized_at_utc,
    )
    verifier = Ed25519AuthorityVerifier(
        {KEY_ID: trusted},
        minimum_keyring_epoch=KEYRING_EPOCH,
    )
    return trusted, signature, verifier


def run_contract() -> None:
    if os.name == "nt":
        return

    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        manifest,
        identity,
        execution_receipt,
    ) = _manifest()
    try:
        nonce = hashlib.sha256(b"adr-dc-044-local-commit-nonce").hexdigest()
        claim = authorization.build_pilot_exact_task_local_commit_authorization(
            authorization_requirements=manifest,
            authorization_id="local-commit-authorization-044",
            local_commit_authorizer_actor_id=ISSUER,
            authorized_at_utc="2026-09-15T05:33:00Z",
            expires_at_utc="2026-09-15T05:40:00Z",
            local_commit_nonce_sha256=nonce,
            notes=("reviewed exact predicted local commit",),
        )
        assert claim.authorization_requirements_sha256 == manifest.sha256
        assert claim.requirements_key_sha256 == manifest.requirements_key_sha256
        assert claim.local_commit_object_identity_sha256 == identity.sha256
        assert claim.predicted_commit_sha == identity.predicted_commit_sha
        assert claim.local_commit_nonce_sha256 == nonce
        assert claim.local_commit_nonce_sha256 != execution_receipt.execution_nonce_sha256
        assert claim.one_shot_local_commit_required is True
        assert claim.local_commit_authorization_consumed is False
        assert claim.human_local_commit_authorization_verified is False
        assert claim.git_object_write_authorized is False
        assert claim.local_ref_update_authorized is False
        assert claim.local_commit_authorized is False
        assert claim.local_commit_created is False
        assert claim.push_authorized is False
        assert claim.production_activation_authorized is False

        _trusted, signature, verifier = _authority(claim)
        proof = authorization._verify_pilot_exact_task_local_commit_authorization(
            authorization=claim,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-15T05:34:00Z",
        )
        assert proof.authorization_sha256 == claim.sha256
        assert proof.signature_sha256 == signature.sha256
        assert proof.issuer_actor_id == ISSUER
        assert proof.issuer_system_id == ISSUER_SYSTEM
        assert proof.authorization_requirements_sha256 == manifest.sha256
        assert proof.requirements_key_sha256 == manifest.requirements_key_sha256
        assert proof.local_commit_object_identity_sha256 == identity.sha256
        assert proof.predicted_commit_sha == identity.predicted_commit_sha
        assert proof.local_commit_nonce_sha256 == nonce
        assert proof.human_local_commit_authorization_verified is True
        assert proof.local_commit_authorization_consumed is False
        assert proof.git_object_write_authorized is False
        assert proof.local_ref_update_authorized is False
        assert proof.local_commit_authorized is False
        assert proof.local_commit_created is False
        assert proof.remote_write_authorized is False
        assert proof.production_activation_authorized is False

        reloaded_claim = (
            authorization.PilotExactTaskLocalCommitAuthorization.from_mapping(
                claim.to_dict()
            )
        )
        reloaded_proof = (
            authorization.PilotExactTaskLocalCommitAuthorizationProof.from_mapping(
                proof.to_dict()
            )
        )
        assert reloaded_claim == claim
        assert reloaded_claim.sha256 == claim.sha256
        assert reloaded_proof == proof
        assert reloaded_proof.sha256 == proof.sha256

        for field, value in (
            ("local_commit_authorization_consumed", True),
            ("human_local_commit_authorization_verified", True),
            ("git_object_write_authorized", True),
            ("local_ref_update_authorized", True),
            ("local_commit_authorized", True),
            ("local_commit_created", True),
            ("push_authorized", True),
            ("production_activation_authorized", True),
            ("predicted_commit_sha", "a" * 40),
        ):
            _reject(
                lambda field=field, value=value: (
                    authorization.PilotExactTaskLocalCommitAuthorization.from_mapping(
                        {**claim.to_dict(), field: value}
                    )
                )
            )

        for field, value in (
            ("local_commit_authorization_consumed", True),
            ("git_object_write_authorized", True),
            ("local_ref_update_authorized", True),
            ("local_commit_authorized", True),
            ("local_commit_created", True),
            ("production_activation_authorized", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    authorization.PilotExactTaskLocalCommitAuthorizationProof.from_mapping(
                        {**proof.to_dict(), field: value}
                    )
                )
            )

        _reject(
            lambda: authorization.build_pilot_exact_task_local_commit_authorization(
                authorization_requirements=manifest,
                authorization_id="local-commit-authorization-044-bad-nonce",
                local_commit_authorizer_actor_id=ISSUER,
                authorized_at_utc="2026-09-15T05:33:00Z",
                expires_at_utc="2026-09-15T05:40:00Z",
                local_commit_nonce_sha256=execution_receipt.execution_nonce_sha256,
            )
        )
        _reject(
            lambda: authorization.build_pilot_exact_task_local_commit_authorization(
                authorization_requirements=manifest,
                authorization_id="local-commit-authorization-044-too-long",
                local_commit_authorizer_actor_id=ISSUER,
                authorized_at_utc="2026-09-15T05:33:00Z",
                expires_at_utc="2026-09-15T05:43:01Z",
                local_commit_nonce_sha256=hashlib.sha256(b"other nonce").hexdigest(),
            )
        )
        _reject(
            lambda: authorization._verify_pilot_exact_task_local_commit_authorization(
                authorization=claim,
                signature=signature,
                verifier=verifier,
                now_provider=lambda: "2026-09-15T05:40:00Z",
            )
        )

        wrong_private = Ed25519PrivateKey.generate()
        wrong_public = wrong_private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        ).hex()
        wrong_trusted = TrustedEd25519AuthorityKey(
            key_id=KEY_ID,
            issuer_actor_id=ISSUER,
            issuer_system_id=ISSUER_SYSTEM,
            public_key_hex=wrong_public,
            valid_from_utc="2026-09-01T00:00:00Z",
            valid_until_utc="2027-09-01T00:00:00Z",
            keyring_epoch=KEYRING_EPOCH,
            custody_policy_sha256=CUSTODY,
        )
        wrong_verifier = Ed25519AuthorityVerifier(
            {KEY_ID: wrong_trusted},
            minimum_keyring_epoch=KEYRING_EPOCH,
        )
        _reject(
            lambda: authorization._verify_pilot_exact_task_local_commit_authorization(
                authorization=claim,
                signature=signature,
                verifier=wrong_verifier,
                now_provider=lambda: "2026-09-15T05:34:00Z",
            )
        )

        claim_schema = json.loads(CLAIM_SCHEMA.read_text(encoding="utf-8"))
        proof_schema = json.loads(PROOF_SCHEMA.read_text(encoding="utf-8"))
        assert set(claim_schema["properties"]) == set(claim.to_dict())
        assert set(claim_schema["required"]) == set(claim.to_dict())
        assert set(proof_schema["properties"]) == set(proof.to_dict())
        assert set(proof_schema["required"]) == set(proof.to_dict())
        assert claim_schema["properties"]["human_local_commit_authorization_verified"]["const"] is False
        assert claim_schema["properties"]["local_commit_authorized"]["const"] is False
        assert proof_schema["properties"]["human_local_commit_authorization_verified"]["const"] is True
        assert proof_schema["properties"]["local_commit_authorized"]["const"] is False
        assert proof_schema["properties"]["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            authorization.verify_pilot_exact_task_local_commit_authorization
        ).parameters
        assert tuple(public_parameters) == ("authorization", "signature")

        impl_source = inspect.getsource(
            sys.modules[
                "kaliv_dev_control._improvement_pilot_exact_task_local_commit_authorization_impl"
            ]
        )
        facade_source = inspect.getsource(authorization)
        assert "Ed25519PrivateKey" not in impl_source
        assert "Ed25519PrivateKey" not in facade_source
        assert ".run(" not in impl_source
        assert "subprocess" not in impl_source
        assert "shell=True" not in impl_source
        assert '"write-tree"' not in impl_source
        assert '"commit-tree"' not in impl_source
        assert '("commit",' not in impl_source
        assert '("update-ref",' not in impl_source
        assert '("push",' not in impl_source
        assert "verifier" not in public_parameters
    finally:
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
