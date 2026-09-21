"""Adversarial contract for ADR-DC-031 exact-task revalidation observation."""
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
import kaliv_dev_control.improvement_pilot_exact_task_execution_revalidation_observation as obs  # noqa: E402
from rsi_pilot_execution_admission_attestation_contract import (  # noqa: E402
    _authority as admission_authority,
    _claim as admission_claim,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-execution-revalidation-observation-packet-v1.schema.json"
)


def _human_authority(claim: auth.PilotExactTaskExecutionAuthorization):
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("31" * 32))
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    policy = asymmetric_authority_key_custody_policy_sha256()
    key = TrustedEd25519AuthorityKey(
        key_id="exact-task-revalidation-human-key-001",
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


def _authorization_proof():
    temp, admission = admission_claim(all_green=True)
    admission_verifier, admission_signature = admission_authority(admission)
    admission_proof = att._verify_pilot_execution_admission_attestation(
        attestation=admission,
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
    claim = auth.build_pilot_exact_task_execution_authorization(
        execution_requirements=requirements,
        authorization_id="exact-task-execution-authorization-031",
        execution_authorizer_actor_id=human_actor,
        authorized_at_utc="2026-09-14T08:32:00Z",
        expires_at_utc="2026-09-14T08:42:00Z",
        execution_nonce_sha256=hashlib.sha256(b"execution-nonce-031").hexdigest(),
        notes=("manual exact-task execution revalidation only",),
    )
    verifier, signature = _human_authority(claim)
    proof = auth._verify_pilot_exact_task_execution_authorization(
        execution_requirements=requirements,
        authorization=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:33:00Z",
    )
    return temp, proof


def _evidence(proof: auth.PilotExactTaskExecutionAuthorizationProof) -> dict[str, str]:
    values = {
        field: hashlib.sha256(f"ADR-031:{field}".encode("utf-8")).hexdigest()
        for field in obs.EVIDENCE_FIELDS
    }
    values["fresh_human_task_execution_authorization_evidence_sha256"] = proof.sha256
    values["one_shot_execution_nonce_evidence_sha256"] = proof.execution_nonce_sha256
    return values


def _reject(fn) -> None:
    try:
        fn()
    except (
        obs.PilotExactTaskExecutionRevalidationObservationError,
        ValueError,
        TypeError,
    ):
        return
    raise AssertionError("ADR-DC-031 unexpectedly accepted invalid input")


def run_contract() -> None:
    assert catalog.modelrig_command_catalog().command_ids == ()
    temp, proof = _authorization_proof()
    try:
        evidence = _evidence(proof)
        packet = obs.build_pilot_exact_task_execution_revalidation_observation_packet(
            execution_authorization_proof=proof,
            observation_id="exact-task-revalidation-observation-031",
            observer_actor_id="dc-l16-revalidation-observer",
            observed_at_utc="2026-09-14T08:34:00Z",
            evidence_sha256=evidence,
        )
        assert len(obs.EVIDENCE_FIELDS) == 25
        assert packet.execution_authorization_proof is proof
        assert packet.execution_authorization_proof_sha256 == proof.sha256
        assert packet.execution_authorization_signature_sha256 == proof.signature_sha256
        assert packet.execution_requirements_sha256 == proof.execution_requirements_sha256
        assert packet.admission_attestation_proof_sha256 == proof.admission_attestation_proof_sha256
        assert packet.admission_attestation_signature_sha256 == proof.admission_attestation_signature_sha256
        assert packet.start_receipt_sha256 == proof.start_receipt_sha256
        assert packet.execution_nonce_sha256 == proof.execution_nonce_sha256
        assert (
            packet.fresh_human_task_execution_authorization_evidence_sha256
            == proof.sha256
        )
        assert packet.one_shot_execution_nonce_evidence_sha256 == proof.execution_nonce_sha256
        assert packet.observation_set_complete is True
        assert packet.human_authorization_proof_bound is True
        assert packet.evidence_verified is False
        assert packet.task_execution_admission_observed is False
        assert packet.task_execution_authorized is False
        assert packet.task_execution_started is False
        assert packet.local_commit_authorized is False
        assert packet.production_activation_authorized is False
        replayed = obs.PilotExactTaskExecutionRevalidationObservationPacket.from_mapping(
            packet.to_dict()
        )
        assert replayed == packet
        assert replayed.sha256 == packet.sha256

        missing = dict(evidence)
        missing.pop(obs.EVIDENCE_FIELDS[-1])
        _reject(
            lambda: obs.build_pilot_exact_task_execution_revalidation_observation_packet(
                execution_authorization_proof=proof,
                observation_id="exact-task-revalidation-observation-031",
                observer_actor_id="dc-l16-revalidation-observer",
                observed_at_utc="2026-09-14T08:34:00Z",
                evidence_sha256=missing,
            )
        )
        extra = {**evidence, "unexpected_evidence_sha256": "1" * 64}
        _reject(
            lambda: obs.build_pilot_exact_task_execution_revalidation_observation_packet(
                execution_authorization_proof=proof,
                observation_id="exact-task-revalidation-observation-031",
                observer_actor_id="dc-l16-revalidation-observer",
                observed_at_utc="2026-09-14T08:34:00Z",
                evidence_sha256=extra,
            )
        )
        zero = {**evidence, obs.EVIDENCE_FIELDS[0]: "0" * 64}
        _reject(
            lambda: obs.build_pilot_exact_task_execution_revalidation_observation_packet(
                execution_authorization_proof=proof,
                observation_id="exact-task-revalidation-observation-031",
                observer_actor_id="dc-l16-revalidation-observer",
                observed_at_utc="2026-09-14T08:34:00Z",
                evidence_sha256=zero,
            )
        )
        wrong_human = {
            **evidence,
            "fresh_human_task_execution_authorization_evidence_sha256": "1" * 64,
        }
        _reject(
            lambda: obs.build_pilot_exact_task_execution_revalidation_observation_packet(
                execution_authorization_proof=proof,
                observation_id="exact-task-revalidation-observation-031",
                observer_actor_id="dc-l16-revalidation-observer",
                observed_at_utc="2026-09-14T08:34:00Z",
                evidence_sha256=wrong_human,
            )
        )
        wrong_nonce = {
            **evidence,
            "one_shot_execution_nonce_evidence_sha256": "2" * 64,
        }
        _reject(
            lambda: obs.build_pilot_exact_task_execution_revalidation_observation_packet(
                execution_authorization_proof=proof,
                observation_id="exact-task-revalidation-observation-031",
                observer_actor_id="dc-l16-revalidation-observer",
                observed_at_utc="2026-09-14T08:34:00Z",
                evidence_sha256=wrong_nonce,
            )
        )
        _reject(
            lambda: obs.build_pilot_exact_task_execution_revalidation_observation_packet(
                execution_authorization_proof=proof,
                observation_id="exact-task-revalidation-observation-031",
                observer_actor_id="dc-l16-revalidation-observer",
                observed_at_utc="2026-09-14T08:32:59Z",
                evidence_sha256=evidence,
            )
        )
        _reject(
            lambda: obs.build_pilot_exact_task_execution_revalidation_observation_packet(
                execution_authorization_proof=proof,
                observation_id="exact-task-revalidation-observation-031",
                observer_actor_id="dc-l16-revalidation-observer",
                observed_at_utc="2026-09-14T08:42:01Z",
                evidence_sha256=evidence,
            )
        )

        rebound = packet.to_dict()
        rebound["selected_pilot_task_id"] = "different.task"
        _reject(
            lambda: obs.PilotExactTaskExecutionRevalidationObservationPacket.from_mapping(
                rebound
            )
        )
        forged_nested = packet.to_dict()
        forged_nested["execution_authorization_proof"] = {
            **forged_nested["execution_authorization_proof"],
            "task_execution_authorized": True,
        }
        _reject(
            lambda: obs.PilotExactTaskExecutionRevalidationObservationPacket.from_mapping(
                forged_nested
            )
        )
        for field in (
            "evidence_verified",
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
                lambda field=field: obs.PilotExactTaskExecutionRevalidationObservationPacket.from_mapping(
                    {**packet.to_dict(), field: True}
                )
            )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(packet.to_dict())
        assert schema["additionalProperties"] is False
        assert props["execution_authorization_proof"]["$ref"] == (
            "rsi-pilot-exact-task-execution-authorization-proof-v1.schema.json"
        )
        assert props["schema"]["const"] == (
            obs.PILOT_EXACT_TASK_EXECUTION_REVALIDATION_OBSERVATION_SCHEMA
        )
        assert props["authority"]["const"] == (
            obs.PILOT_EXACT_TASK_EXECUTION_REVALIDATION_OBSERVATION_AUTHORITY
        )
        assert props["observation_set_complete"]["const"] is True
        assert props["human_authorization_proof_bound"]["const"] is True
        for field in (
            "evidence_verified",
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
            assert props[field]["const"] is False

        root_source = inspect.getsource(kaliv_dev_control)
        assert "improvement_pilot_exact_task_execution_revalidation_observation" not in root_source
        source = inspect.getsource(obs).lower()
        for forbidden in (
            "subprocess",
            "socket",
            "requests",
            "urllib",
            "git push",
            "merge_pull_request",
            "create_pull_request",
            "open(",
            "read_text",
            "read_bytes",
            "write_text",
            "write_bytes",
        ):
            assert forbidden not in source, forbidden
    finally:
        temp.cleanup()


if __name__ == "__main__":
    run_contract()
