"""Adversarial contract for ADR-DC-030 human exact-task execution authority."""
from __future__ import annotations

import hashlib
import inspect
import json
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

import kaliv_dev_control  # noqa: E402
from kaliv_dev_control import catalog  # noqa: E402
from kaliv_dev_control.asymmetric_authority import (  # noqa: E402
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
    asymmetric_authority_key_custody_policy_sha256,
    authority_signing_message,
)
import kaliv_dev_control.improvement_pilot_execution_admission_attestation as att  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_admission_requirements as req  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_authorization as auth  # noqa: E402
from kaliv_dev_control._improvement_pilot_exact_task_execution_authorization_production_boundary import (  # noqa: E402
    _verify_admission_attestation_provenance,
)
from rsi_pilot_execution_admission_attestation_contract import (  # noqa: E402
    _authority as admission_authority,
    _claim as admission_claim,
)

CLAIM_SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-execution-authorization-v1.schema.json"
PROOF_SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-execution-authorization-proof-v1.schema.json"


def _admission_material():
    temp, claim = admission_claim(all_green=True)
    verifier, signature = admission_authority(claim)
    proof = att._verify_pilot_execution_admission_attestation(
        attestation=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:31:00Z",
    )
    requirements = req.build_pilot_exact_task_execution_admission_requirements(proof)
    return temp, verifier, signature, proof, requirements


def _human_authority(claim: auth.PilotExactTaskExecutionAuthorization):
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("30" * 32))
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    policy = asymmetric_authority_key_custody_policy_sha256()
    key = TrustedEd25519AuthorityKey(
        key_id="exact-task-execution-human-key-001",
        issuer_actor_id=claim.execution_authorizer_actor_id,
        issuer_system_id=auth.PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_ISSUER_SYSTEM_ID,
        public_key_hex=public_hex,
        valid_from_utc="2026-09-14T00:00:00Z",
        valid_until_utc="2027-09-14T00:00:00Z",
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


def _claim(requirements: req.PilotExactTaskExecutionAdmissionRequirements):
    human_actor = (
        requirements.admission_attestation_proof.attestation.packet.admission_requirements
        .start_receipt.authorization_proof.authorization.start_authorizer_actor_id
    )
    return auth.build_pilot_exact_task_execution_authorization(
        execution_requirements=requirements,
        authorization_id="exact-task-execution-authorization-030",
        execution_authorizer_actor_id=human_actor,
        authorized_at_utc="2026-09-14T08:32:00Z",
        expires_at_utc="2026-09-14T08:42:00Z",
        execution_nonce_sha256=hashlib.sha256(b"execution-nonce-030").hexdigest(),
        notes=("manual exact-task execution only",),
    )


def _reject(fn) -> None:
    try:
        fn()
    except (auth.PilotExactTaskExecutionAuthorizationError, ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-030 unexpectedly accepted invalid input")


def run_contract() -> None:
    assert catalog.modelrig_command_catalog().command_ids == ()
    temp, admission_verifier, admission_signature, admission_proof, requirements = (
        _admission_material()
    )
    try:
        claim = _claim(requirements)
        assert claim.execution_requirements is requirements
        assert claim.execution_requirements_sha256 == requirements.sha256
        assert claim.admission_attestation_proof_sha256 == admission_proof.sha256
        assert claim.admission_attestation_signature_sha256 == admission_proof.signature_sha256
        assert claim.start_receipt_sha256 == admission_proof.start_receipt_sha256
        assert claim.one_shot_execution_required is True
        assert claim.execution_authorization_consumed is False
        assert claim.human_task_execution_authorization_verified is False
        assert claim.task_execution_admission_observed is False
        assert claim.task_execution_authorized is False
        assert claim.task_execution_started is False
        assert claim.local_commit_authorized is False
        assert claim.production_activation_authorized is False
        assert auth.PilotExactTaskExecutionAuthorization.from_mapping(claim.to_dict()) == claim

        _verify_admission_attestation_provenance(
            proof=admission_proof,
            signature=admission_signature,
            verifier=admission_verifier,
            now_provider=lambda: "2026-09-14T08:33:00Z",
        )

        verifier, signature = _human_authority(claim)
        proof = auth._verify_pilot_exact_task_execution_authorization(
            execution_requirements=requirements,
            authorization=claim,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-14T08:33:00Z",
        )
        assert proof.authorization == claim
        assert proof.human_task_execution_authorization_verified is True
        assert proof.one_shot_execution_required is True
        assert proof.execution_authorization_consumed is False
        assert proof.task_execution_admission_observed is False
        assert proof.task_execution_authorized is False
        assert proof.task_execution_started is False
        assert proof.local_commit_authorized is False
        assert proof.remote_write_authorized is False
        assert proof.push_authorized is False
        assert proof.pr_mutation_authorized is False
        assert proof.merge_authorized is False
        assert proof.release_authorized is False
        assert proof.deploy_authorized is False
        assert proof.production_activation_authorized is False
        assert auth.PilotExactTaskExecutionAuthorizationProof.from_mapping(
            proof.to_dict()
        ) == proof

        # Production facade rejects caller-selected human trust.
        _reject(
            lambda: auth.verify_pilot_exact_task_execution_authorization(
                execution_requirements=requirements,
                authorization=claim,
                signature=signature,
                admission_attestation_signature=admission_signature,
                verifier=verifier,
            )
        )
        # Production requires the detached ADR-DC-028 signature for fresh provenance.
        _reject(
            lambda: auth.verify_pilot_exact_task_execution_authorization(
                execution_requirements=requirements,
                authorization=claim,
                signature=signature,
            )
        )

        wrong_actor = claim.to_dict()
        wrong_actor["execution_authorizer_actor_id"] = "different-human"
        _reject(lambda: auth.PilotExactTaskExecutionAuthorization.from_mapping(wrong_actor))

        same_start_nonce = claim.to_dict()
        same_start_nonce["execution_nonce_sha256"] = (
            requirements.admission_attestation_proof.attestation.packet
            .admission_requirements.start_nonce_sha256
        )
        _reject(lambda: auth.PilotExactTaskExecutionAuthorization.from_mapping(same_start_nonce))

        too_long = claim.to_dict()
        too_long["expires_at_utc"] = "2026-09-14T08:42:01Z"
        _reject(lambda: auth.PilotExactTaskExecutionAuthorization.from_mapping(too_long))

        rebound = claim.to_dict()
        rebound["selected_pilot_task_id"] = "different.task"
        _reject(lambda: auth.PilotExactTaskExecutionAuthorization.from_mapping(rebound))

        forged_requirements = claim.to_dict()
        forged_requirements["execution_requirements"] = {
            **forged_requirements["execution_requirements"],
            "task_execution_authorized": True,
        }
        _reject(
            lambda: auth.PilotExactTaskExecutionAuthorization.from_mapping(
                forged_requirements
            )
        )

        changed_claim = claim.to_dict()
        changed_claim["notes"] = ["changed after signature"]
        changed = auth.PilotExactTaskExecutionAuthorization.from_mapping(changed_claim)
        _reject(
            lambda: auth._verify_pilot_exact_task_execution_authorization(
                execution_requirements=requirements,
                authorization=changed,
                signature=signature,
                verifier=verifier,
                now_provider=lambda: "2026-09-14T08:33:00Z",
            )
        )

        for field in (
            "task_execution_admission_observed",
            "task_execution_authorized",
            "task_execution_started",
            "integration_ready",
            "product_pilot_started",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            _reject(
                lambda field=field: auth.PilotExactTaskExecutionAuthorizationProof.from_mapping(
                    {**proof.to_dict(), field: True}
                )
            )

        claim_schema = json.loads(CLAIM_SCHEMA.read_text(encoding="utf-8"))
        proof_schema = json.loads(PROOF_SCHEMA.read_text(encoding="utf-8"))
        assert set(claim_schema["properties"]) == set(claim.to_dict())
        assert set(proof_schema["properties"]) == set(proof.to_dict())
        assert claim_schema["additionalProperties"] is False
        assert proof_schema["additionalProperties"] is False
        assert claim_schema["properties"]["execution_requirements"]["$ref"] == (
            "rsi-pilot-exact-task-execution-admission-requirements-v1.schema.json"
        )
        assert proof_schema["properties"]["human_task_execution_authorization_verified"]["const"] is True
        for field in (
            "task_execution_admission_observed",
            "task_execution_authorized",
            "task_execution_started",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert proof_schema["properties"][field]["const"] is False

        root_source = inspect.getsource(kaliv_dev_control)
        assert "improvement_pilot_exact_task_execution_authorization" not in root_source
        source = inspect.getsource(auth).lower()
        for forbidden in (
            "subprocess",
            "socket",
            "requests",
            "urllib",
            "git push",
            "merge_pull_request",
            "create_pull_request",
        ):
            assert forbidden not in source, forbidden
    finally:
        temp.cleanup()


if __name__ == "__main__":
    run_contract()
