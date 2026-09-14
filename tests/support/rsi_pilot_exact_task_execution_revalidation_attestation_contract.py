"""Adversarial contract for ADR-DC-032 exact-task revalidation attestation."""
from __future__ import annotations

import hashlib
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

from kaliv_dev_control import catalog  # noqa: E402
from kaliv_dev_control.asymmetric_authority import (  # noqa: E402
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
    asymmetric_authority_key_custody_policy_sha256,
    authority_signing_message,
)
import kaliv_dev_control.improvement_pilot_execution_admission_attestation as admission  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_admission_requirements as req  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_authorization as auth  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_revalidation_observation as obs  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_revalidation_attestation as verify  # noqa: E402
from kaliv_dev_control._improvement_pilot_exact_task_execution_revalidation_attestation_production_boundary import (  # noqa: E402
    _verify_execution_authorization_provenance,
)
from rsi_pilot_execution_admission_attestation_contract import (  # noqa: E402
    _authority as admission_authority,
    _claim as admission_claim,
)
from rsi_pilot_exact_task_execution_revalidation_observation_contract import (  # noqa: E402
    _evidence,
    _human_authority,
)

CLAIM_SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-execution-revalidation-attestation-v1.schema.json"
)
PROOF_SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-execution-revalidation-attestation-proof-v1.schema.json"
)


def _material():
    temp, admission_claim_value = admission_claim(all_green=True)
    admission_verifier, admission_signature = admission_authority(
        admission_claim_value
    )
    admission_proof = admission._verify_pilot_execution_admission_attestation(
        attestation=admission_claim_value,
        signature=admission_signature,
        verifier=admission_verifier,
        now_provider=lambda: "2026-09-14T08:31:00Z",
    )
    requirements = req.build_pilot_exact_task_execution_admission_requirements(
        admission_proof
    )
    human_actor = (
        requirements.admission_attestation_proof.attestation.packet.admission_requirements
        .start_receipt.authorization_proof.authorization.start_authorizer_actor_id
    )
    authorization = auth.build_pilot_exact_task_execution_authorization(
        execution_requirements=requirements,
        authorization_id="exact-task-execution-authorization-032",
        execution_authorizer_actor_id=human_actor,
        authorized_at_utc="2026-09-14T08:32:00Z",
        expires_at_utc="2026-09-14T08:42:00Z",
        execution_nonce_sha256=hashlib.sha256(b"execution-nonce-032").hexdigest(),
        notes=("manual exact-task execution revalidation attestation only",),
    )
    human_verifier, human_signature = _human_authority(authorization)
    authorization_proof = auth._verify_pilot_exact_task_execution_authorization(
        execution_requirements=requirements,
        authorization=authorization,
        signature=human_signature,
        verifier=human_verifier,
        now_provider=lambda: "2026-09-14T08:33:00Z",
    )
    packet = obs.build_pilot_exact_task_execution_revalidation_observation_packet(
        execution_authorization_proof=authorization_proof,
        observation_id="exact-task-revalidation-observation-032",
        observer_actor_id="dc-l16-revalidation-observer",
        observed_at_utc="2026-09-14T08:34:00Z",
        evidence_sha256=_evidence(authorization_proof),
    )
    return (
        temp,
        admission_verifier,
        admission_signature,
        human_verifier,
        human_signature,
        authorization_proof,
        packet,
    )


def _host_authority(
    claim: verify.PilotExactTaskExecutionRevalidationAttestation,
):
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("32" * 32))
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    policy = asymmetric_authority_key_custody_policy_sha256()
    key = TrustedEd25519AuthorityKey(
        key_id="exact-task-revalidation-attestor-key-001",
        issuer_actor_id=claim.packet.observer_actor_id,
        issuer_system_id=(
            verify.PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_ISSUER_SYSTEM_ID
        ),
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
        signed_at_utc=claim.attested_at_utc,
    )
    return verifier, signature


def _claim(packet, *, all_green: bool = True):
    results = {field: True for field in verify.RESULT_FIELDS}
    if not all_green:
        results["trusted_git_closure_revalidated"] = False
    return verify.build_pilot_exact_task_execution_revalidation_attestation(
        packet=packet,
        attestation_id="exact-task-revalidation-attestation-032",
        observer_host_id="modelrig-authority-host-032",
        attested_at_utc="2026-09-14T08:35:00Z",
        results=results,
    )


def _reject(fn) -> None:
    try:
        fn()
    except (
        verify.PilotExactTaskExecutionRevalidationAttestationError,
        ValueError,
        TypeError,
    ):
        return
    raise AssertionError("ADR-DC-032 unexpectedly accepted invalid input")


def run_contract() -> None:
    assert catalog.modelrig_command_catalog().command_ids == ()
    (
        temp,
        admission_verifier,
        admission_signature,
        human_verifier,
        human_signature,
        authorization_proof,
        packet,
    ) = _material()
    try:
        assert len(verify.RESULT_FIELDS) == 25
        _verify_execution_authorization_provenance(
            proof=authorization_proof,
            execution_authorization_signature=human_signature,
            admission_attestation_signature=admission_signature,
            admission_verifier=admission_verifier,
            human_verifier=human_verifier,
            now_provider=lambda: "2026-09-14T08:36:00Z",
        )

        claim = _claim(packet)
        assert claim.packet is packet
        assert claim.packet_sha256 == packet.sha256
        assert claim.execution_authorization_proof_sha256 == (
            packet.execution_authorization_proof_sha256
        )
        assert claim.execution_authorization_signature_sha256 == (
            packet.execution_authorization_signature_sha256
        )
        assert claim.admission_attestation_proof_sha256 == (
            packet.admission_attestation_proof_sha256
        )
        assert claim.admission_attestation_signature_sha256 == (
            packet.admission_attestation_signature_sha256
        )
        assert claim.execution_nonce_sha256 == packet.execution_nonce_sha256
        assert claim.all_checks_satisfied is True
        assert claim.host_attestation_verified is False
        assert claim.execution_revalidation_observed is False
        assert claim.execution_revalidation_satisfied is False
        assert claim.task_execution_admission_observed is False
        assert claim.task_execution_authorized is False
        assert claim.task_execution_started is False
        assert claim.local_commit_authorized is False
        assert claim.production_activation_authorized is False
        assert verify.PilotExactTaskExecutionRevalidationAttestation.from_mapping(
            claim.to_dict()
        ) == claim

        verifier, signature = _host_authority(claim)
        proof = verify._verify_pilot_exact_task_execution_revalidation_attestation(
            attestation=claim,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-14T08:36:00Z",
        )
        assert proof.host_attestation_verified is True
        assert proof.execution_revalidation_observed is True
        assert proof.execution_revalidation_satisfied is True
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
        replayed = verify.PilotExactTaskExecutionRevalidationAttestationProof.from_mapping(
            proof.to_dict()
        )
        assert replayed == proof
        assert replayed.sha256 == proof.sha256

        failed_claim = _claim(packet, all_green=False)
        failed_verifier, failed_signature = _host_authority(failed_claim)
        failed_proof = verify._verify_pilot_exact_task_execution_revalidation_attestation(
            attestation=failed_claim,
            signature=failed_signature,
            verifier=failed_verifier,
            now_provider=lambda: "2026-09-14T08:36:00Z",
        )
        assert failed_proof.host_attestation_verified is True
        assert failed_proof.execution_revalidation_observed is True
        assert failed_proof.execution_revalidation_satisfied is False
        assert failed_proof.task_execution_authorized is False

        # Public production facade rejects caller-selected trust even with all
        # detached upstream provenance supplied.
        _reject(
            lambda: verify.verify_pilot_exact_task_execution_revalidation_attestation(
                attestation=claim,
                signature=signature,
                execution_authorization_signature=human_signature,
                admission_attestation_signature=admission_signature,
                verifier=verifier,
            )
        )
        # Both upstream detached signatures are mandatory before host trust lookup.
        _reject(
            lambda: verify.verify_pilot_exact_task_execution_revalidation_attestation(
                attestation=claim,
                signature=signature,
                admission_attestation_signature=admission_signature,
            )
        )
        _reject(
            lambda: verify.verify_pilot_exact_task_execution_revalidation_attestation(
                attestation=claim,
                signature=signature,
                execution_authorization_signature=human_signature,
            )
        )

        # Fresh provenance rejects swapped/mismatched detached signatures.
        _reject(
            lambda: _verify_execution_authorization_provenance(
                proof=authorization_proof,
                execution_authorization_signature=admission_signature,
                admission_attestation_signature=admission_signature,
                admission_verifier=admission_verifier,
                human_verifier=human_verifier,
                now_provider=lambda: "2026-09-14T08:36:00Z",
            )
        )
        _reject(
            lambda: _verify_execution_authorization_provenance(
                proof=authorization_proof,
                execution_authorization_signature=human_signature,
                admission_attestation_signature=human_signature,
                admission_verifier=admission_verifier,
                human_verifier=human_verifier,
                now_provider=lambda: "2026-09-14T08:36:00Z",
            )
        )

        bool_unsafe = claim.to_dict()
        bool_unsafe[verify.RESULT_FIELDS[0]] = 1
        _reject(
            lambda: verify.PilotExactTaskExecutionRevalidationAttestation.from_mapping(
                bool_unsafe
            )
        )

        rebound = claim.to_dict()
        rebound["execution_nonce_sha256"] = "1" * 64
        _reject(
            lambda: verify.PilotExactTaskExecutionRevalidationAttestation.from_mapping(
                rebound
            )
        )

        forged_packet = claim.to_dict()
        forged_packet["packet"] = {
            **forged_packet["packet"],
            "task_execution_authorized": True,
        }
        _reject(
            lambda: verify.PilotExactTaskExecutionRevalidationAttestation.from_mapping(
                forged_packet
            )
        )

        impossible = {**proof.to_dict(), "execution_revalidation_satisfied": False}
        _reject(
            lambda: verify.PilotExactTaskExecutionRevalidationAttestationProof.from_mapping(
                impossible
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
                lambda field=field: verify.PilotExactTaskExecutionRevalidationAttestationProof.from_mapping(
                    {**proof.to_dict(), field: True}
                )
            )

        claim_schema = json.loads(CLAIM_SCHEMA.read_text(encoding="utf-8"))
        proof_schema = json.loads(PROOF_SCHEMA.read_text(encoding="utf-8"))
        assert set(claim_schema["properties"]) == set(claim.to_dict())
        assert set(proof_schema["properties"]) == set(proof.to_dict())
        assert claim_schema["additionalProperties"] is False
        assert proof_schema["additionalProperties"] is False
        assert claim_schema["properties"]["packet"]["$ref"] == (
            "rsi-pilot-exact-task-execution-revalidation-observation-packet-v1.schema.json"
        )
        assert proof_schema["properties"]["host_attestation_verified"]["const"] is True
        assert proof_schema["properties"]["execution_revalidation_observed"]["const"] is True
        assert proof_schema["properties"]["execution_revalidation_satisfied"]["type"] == "boolean"
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
    finally:
        temp.cleanup()


if __name__ == "__main__":
    run_contract()
