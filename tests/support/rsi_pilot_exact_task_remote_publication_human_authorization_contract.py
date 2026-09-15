"""Adversarial contract for ADR-DC-051 human remote-publication authorization."""
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

from kaliv_dev_control import improvement_pilot_exact_task_remote_head_observation as observation  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_remote_publication_authorization as authorization  # noqa: E402
from kaliv_dev_control.asymmetric_authority import (  # noqa: E402
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
    asymmetric_authority_key_custody_policy_sha256,
    authority_signing_message,
)
from rsi_pilot_exact_task_remote_head_observation_contract import (  # noqa: E402
    _live_requirements,
    _reader,
)

CLAIM_SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-remote-publication-human-authorization-v1.schema.json"
PROOF_SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-remote-publication-human-authorization-proof-v1.schema.json"
ISSUER = "human.remote-publication.authorizer"
ISSUER_SYSTEM = authorization.PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ISSUER_SYSTEM_ID
KEY_ID = "remote-publication-human-key-2026"
EPOCH = 1
CUSTODY = asymmetric_authority_key_custody_policy_sha256()


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-051 unexpectedly accepted unsafe authority")


def _live_observation():
    values = _live_requirements()
    (
        source_temp, admission_ledger_temp, capability_temp, reservation_temp,
        execution_temp, local_admission_temp, consume_temp, object_ledger_temp,
        ref_ledger_temp, ref_receipt, identity, task, fixture, base_reader,
        requirements,
    ) = values
    calls, fixed, reader = _reader(
        base_reader=base_reader,
        requirements=requirements,
        operation_root=fixture["git_runner"].operation_root,
        first=task.base_sha,
    )
    times = iter(("2026-09-15T05:34:13Z", "2026-09-15T05:34:14Z"))
    with patch.object(fixture["git_runner"], "run", side_effect=reader):
        remote_observation = observation._observe_verified_pilot_exact_task_remote_head(
            requirements=requirements,
            now_provider=lambda: next(times),
        )
    assert calls.count(fixed) == 2
    assert remote_observation.observation_authenticated is True
    return (*values, remote_observation)


def _authority(claim):
    private = Ed25519PrivateKey.generate()
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    trusted = TrustedEd25519AuthorityKey(
        key_id=KEY_ID,
        issuer_actor_id=ISSUER,
        issuer_system_id=ISSUER_SYSTEM,
        public_key_hex=public_hex,
        valid_from_utc="2026-09-01T00:00:00Z",
        valid_until_utc="2027-09-01T00:00:00Z",
        keyring_epoch=EPOCH,
        custody_policy_sha256=CUSTODY,
    )
    payload = claim.canonical_json().encode("utf-8")
    message = authority_signing_message(
        key_id=KEY_ID,
        issuer_actor_id=ISSUER,
        issuer_system_id=ISSUER_SYSTEM,
        keyring_epoch=EPOCH,
        custody_policy_sha256=CUSTODY,
        payload=payload,
    )
    signature = DetachedEd25519AuthoritySignature(
        key_id=KEY_ID,
        issuer_actor_id=ISSUER,
        issuer_system_id=ISSUER_SYSTEM,
        keyring_epoch=EPOCH,
        custody_policy_sha256=CUSTODY,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        signature_hex=private.sign(message).hex(),
        signed_at_utc=claim.authorized_at_utc,
    )
    verifier = Ed25519AuthorityVerifier({KEY_ID: trusted}, minimum_keyring_epoch=EPOCH)
    return signature, verifier


def run_contract() -> None:
    if os.name == "nt":
        return
    values = _live_observation()
    (
        source_temp, admission_ledger_temp, capability_temp, reservation_temp,
        execution_temp, local_admission_temp, consume_temp, object_ledger_temp,
        ref_ledger_temp, ref_receipt, identity, task, fixture, base_reader,
        requirements, remote_observation,
    ) = values
    try:
        nonce = hashlib.sha256(b"adr-dc-051-remote-publication-nonce").hexdigest()
        claim = authorization.build_pilot_exact_task_remote_publication_authorization(
            remote_head_observation=remote_observation,
            authorization_id="remote-publication-authorization-051",
            remote_publication_authorizer_actor_id=ISSUER,
            authorized_at_utc="2026-09-15T05:35:00Z",
            expires_at_utc="2026-09-15T05:42:00Z",
            remote_publication_nonce_sha256=nonce,
            notes=("reviewed exact remote branch publication",),
        )
        assert claim.remote_head_observation_sha256 == remote_observation.sha256
        assert claim.observation_key_sha256 == remote_observation.observation_key_sha256
        assert claim.requirements_sha256 == requirements.sha256
        assert claim.local_commit_sha == identity.predicted_commit_sha
        assert claim.destination_ref == requirements.destination_ref
        assert claim.remote_head_sha == task.base_sha
        assert claim.remote_publication_nonce_sha256 == nonce
        assert claim.remote_publication_nonce_sha256 != requirements.local_commit_nonce_sha256
        assert claim.one_shot_remote_publication_required is True
        assert claim.fresh_remote_head_revalidation_before_push_required is True
        assert claim.human_remote_publication_authorization_verified is False
        assert claim.remote_publication_authorization_consumed is False
        assert claim.remote_write_authorized is False
        assert claim.push_authorized is False
        assert claim.pr_mutation_authorized is False
        assert claim.production_activation_authorized is False

        signature, verifier = _authority(claim)
        proof = authorization._verify_pilot_exact_task_remote_publication_authorization(
            authorization=claim,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-15T05:36:00Z",
        )
        assert proof.authorization_sha256 == claim.sha256
        assert proof.signature_sha256 == signature.sha256
        assert proof.remote_head_observation_sha256 == remote_observation.sha256
        assert proof.observation_key_sha256 == remote_observation.observation_key_sha256
        assert proof.local_commit_sha == identity.predicted_commit_sha
        assert proof.destination_ref == requirements.destination_ref
        assert proof.remote_publication_nonce_sha256 == nonce
        assert proof.human_remote_publication_authorization_verified is True
        assert proof.remote_publication_authorization_consumed is False
        assert proof.remote_write_authorized is False
        assert proof.push_authorized is False
        assert proof.pr_mutation_authorized is False
        assert proof.production_activation_authorized is False

        reloaded_claim = authorization.PilotExactTaskRemotePublicationAuthorization.from_mapping(claim.to_dict())
        reloaded_proof = authorization.PilotExactTaskRemotePublicationAuthorizationProof.from_mapping(proof.to_dict())
        assert reloaded_claim == claim and reloaded_claim.sha256 == claim.sha256
        assert reloaded_proof == proof and reloaded_proof.sha256 == proof.sha256

        reloaded_observation = observation.PilotExactTaskRemoteHeadObservation.from_mapping(remote_observation.to_dict())
        assert reloaded_observation.observation_authenticated is False
        _reject(lambda: authorization.build_pilot_exact_task_remote_publication_authorization(
            remote_head_observation=reloaded_observation,
            authorization_id="remote-publication-authorization-051-reloaded",
            remote_publication_authorizer_actor_id=ISSUER,
            authorized_at_utc="2026-09-15T05:35:00Z",
            expires_at_utc="2026-09-15T05:42:00Z",
            remote_publication_nonce_sha256=hashlib.sha256(b"reloaded-051").hexdigest(),
        ))

        for field, value in (
            ("remote_publication_authorization_consumed", True),
            ("human_remote_publication_authorization_verified", True),
            ("remote_write_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("production_activation_authorized", True),
            ("fresh_remote_head_revalidation_before_push_required", False),
        ):
            _reject(lambda field=field, value=value: authorization.PilotExactTaskRemotePublicationAuthorization.from_mapping({**claim.to_dict(), field: value}))

        for field, value in (
            ("remote_publication_authorization_consumed", True),
            ("human_remote_publication_authorization_verified", False),
            ("remote_write_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("production_activation_authorized", True),
            ("fresh_remote_head_revalidation_before_push_required", False),
        ):
            _reject(lambda field=field, value=value: authorization.PilotExactTaskRemotePublicationAuthorizationProof.from_mapping({**proof.to_dict(), field: value}))

        _reject(lambda: authorization.build_pilot_exact_task_remote_publication_authorization(
            remote_head_observation=remote_observation,
            authorization_id="remote-publication-authorization-051-too-long",
            remote_publication_authorizer_actor_id=ISSUER,
            authorized_at_utc="2026-09-15T05:35:00Z",
            expires_at_utc="2026-09-15T05:46:00Z",
            remote_publication_nonce_sha256=hashlib.sha256(b"too-long-051").hexdigest(),
        ))
        _reject(lambda: authorization.build_pilot_exact_task_remote_publication_authorization(
            remote_head_observation=remote_observation,
            authorization_id="remote-publication-authorization-051-stale-observation",
            remote_publication_authorizer_actor_id=ISSUER,
            authorized_at_utc="2026-09-15T05:44:15Z",
            expires_at_utc="2026-09-15T05:50:00Z",
            remote_publication_nonce_sha256=hashlib.sha256(b"stale-observation-051").hexdigest(),
        ))
        _reject(lambda: authorization.build_pilot_exact_task_remote_publication_authorization(
            remote_head_observation=remote_observation,
            authorization_id="remote-publication-authorization-051-reused-local-nonce",
            remote_publication_authorizer_actor_id=ISSUER,
            authorized_at_utc="2026-09-15T05:35:00Z",
            expires_at_utc="2026-09-15T05:42:00Z",
            remote_publication_nonce_sha256=requirements.local_commit_nonce_sha256,
        ))
        _reject(lambda: authorization._verify_pilot_exact_task_remote_publication_authorization(
            authorization=claim,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-15T05:42:00Z",
        ))

        claim_schema = json.loads(CLAIM_SCHEMA.read_text(encoding="utf-8"))
        proof_schema = json.loads(PROOF_SCHEMA.read_text(encoding="utf-8"))
        assert set(claim_schema["properties"]) == set(claim.to_dict())
        assert set(claim_schema["required"]) == set(claim.to_dict())
        assert set(proof_schema["properties"]) == set(proof.to_dict())
        assert set(proof_schema["required"]) == set(proof.to_dict())
        assert proof_schema["properties"]["human_remote_publication_authorization_verified"]["const"] is True
        assert proof_schema["properties"]["push_authorized"]["const"] is False

        public_verify = inspect.signature(authorization.verify_pilot_exact_task_remote_publication_authorization).parameters
        assert tuple(public_verify) == ("authorization", "signature")
        source = inspect.getsource(authorization)
        assert "Ed25519PrivateKey" not in source
        assert "subprocess" not in source
        assert "shell=True" not in source
        assert '("push",' not in source
        assert '"ls-remote"' not in source
    finally:
        ref_ledger_temp.cleanup()
        object_ledger_temp.cleanup()
        consume_temp.cleanup()
        local_admission_temp.cleanup()
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
