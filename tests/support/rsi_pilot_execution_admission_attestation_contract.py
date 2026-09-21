"""Adversarial contract for ADR-DC-028 execution-admission host attestation."""
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
import kaliv_dev_control.improvement_pilot_execution_admission_requirements as req  # noqa: E402
import kaliv_dev_control.improvement_pilot_execution_admission_observation as obs  # noqa: E402
import kaliv_dev_control.improvement_pilot_execution_admission_attestation as att  # noqa: E402
from rsi_pilot_execution_admission_requirements_contract import _receipt  # noqa: E402
from rsi_pilot_execution_admission_observation_contract import _evidence  # noqa: E402

CLAIM_SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-execution-admission-attestation-v1.schema.json"
)
PROOF_SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-execution-admission-attestation-proof-v1.schema.json"
)


def _packet():
    temp, receipt = _receipt()
    requirements = req.build_pilot_execution_admission_requirements(receipt)
    packet = obs.build_pilot_execution_admission_observation_packet(
        admission_requirements=requirements,
        observation_id="execution-admission-observation-028",
        observer_actor_id="execution-admission-observer",
        observed_at_utc="2026-09-14T08:29:00Z",
        evidence_sha256=_evidence(),
    )
    return temp, packet


def _results(*, all_green: bool = True) -> dict[str, bool]:
    values = {name: True for name in att.RESULT_FIELDS}
    if not all_green:
        values[att.RESULT_FIELDS[0]] = False
    return values


def _claim(*, all_green: bool = True):
    temp, packet = _packet()
    claim = att.build_pilot_execution_admission_attestation(
        packet=packet,
        attestation_id="execution-admission-attestation-028",
        observer_host_id="modelrig-host-001",
        attested_at_utc="2026-09-14T08:30:00Z",
        results=_results(all_green=all_green),
    )
    return temp, claim


def _authority(claim: att.PilotExecutionAdmissionAttestation):
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("28" * 32))
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    policy = asymmetric_authority_key_custody_policy_sha256()
    key = TrustedEd25519AuthorityKey(
        key_id="execution-admission-attestation-key-001",
        issuer_actor_id=claim.packet.observer_actor_id,
        issuer_system_id=att.PILOT_EXECUTION_ADMISSION_ATTESTATION_ISSUER_SYSTEM_ID,
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


def _reject(fn) -> None:
    try:
        fn()
    except (att.PilotExecutionAdmissionAttestationError, ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-028 unexpectedly accepted invalid input")


def run_contract() -> None:
    assert catalog.modelrig_command_catalog().command_ids == ()

    temp, claim = _claim()
    try:
        assert claim.schema == att.PILOT_EXECUTION_ADMISSION_ATTESTATION_SCHEMA
        assert claim.authority == att.PILOT_EXECUTION_ADMISSION_ATTESTATION_AUTHORITY
        assert claim.packet_sha256 == claim.packet.sha256
        assert claim.start_receipt_sha256 == claim.packet.start_receipt_sha256
        assert claim.packet.observation_set_complete is True
        assert claim.packet.evidence_verified is False
        assert claim.all_checks_satisfied is True
        assert claim.host_attestation_verified is False
        assert claim.execution_admission_observed is False
        assert claim.execution_admission_satisfied is False
        assert claim.task_execution_authorized is False
        assert claim.product_pilot_started is False
        assert claim.local_commit_authorized is False
        assert claim.production_activation_authorized is False
        assert att.PilotExecutionAdmissionAttestation.from_mapping(claim.to_dict()) == claim

        verifier, signature = _authority(claim)
        proof = att._verify_pilot_execution_admission_attestation(
            attestation=claim,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-14T08:31:00Z",
        )
        assert proof.schema == att.PILOT_EXECUTION_ADMISSION_ATTESTATION_PROOF_SCHEMA
        assert proof.authority == att.PILOT_EXECUTION_ADMISSION_ATTESTATION_PROOF_AUTHORITY
        assert proof.attestation == claim
        assert proof.packet_sha256 == claim.packet.sha256
        assert proof.start_receipt_sha256 == claim.packet.start_receipt_sha256
        assert proof.host_attestation_verified is True
        assert proof.execution_admission_observed is True
        assert proof.execution_admission_satisfied is True
        assert proof.task_execution_authorized is False
        assert proof.integration_ready is False
        assert proof.product_pilot_started is False
        assert proof.local_commit_authorized is False
        assert proof.remote_write_authorized is False
        assert proof.push_authorized is False
        assert proof.pr_mutation_authorized is False
        assert proof.merge_authorized is False
        assert proof.release_authorized is False
        assert proof.deploy_authorized is False
        assert proof.production_activation_authorized is False
        assert att.PilotExecutionAdmissionAttestationProof.from_mapping(
            proof.to_dict()
        ) == proof

        # Public production facade must reject a caller-selected verifier.
        _reject(
            lambda: att.verify_pilot_execution_admission_attestation(
                attestation=claim,
                signature=signature,
                verifier=verifier,
            )
        )

        # A cryptographically valid failed check remains observed but unsatisfied.
        failed_temp, failed_claim = _claim(all_green=False)
        try:
            failed_verifier, failed_signature = _authority(failed_claim)
            failed_proof = att._verify_pilot_execution_admission_attestation(
                attestation=failed_claim,
                signature=failed_signature,
                verifier=failed_verifier,
                now_provider=lambda: "2026-09-14T08:31:00Z",
            )
            assert failed_proof.host_attestation_verified is True
            assert failed_proof.execution_admission_observed is True
            assert failed_proof.execution_admission_satisfied is False
            assert failed_proof.task_execution_authorized is False
        finally:
            failed_temp.cleanup()

        bad_results = _results()
        bad_results.pop(att.RESULT_FIELDS[-1])
        _reject(
            lambda: att.build_pilot_execution_admission_attestation(
                packet=claim.packet,
                attestation_id="missing-result",
                observer_host_id="modelrig-host-001",
                attested_at_utc="2026-09-14T08:30:00Z",
                results=bad_results,
            )
        )
        bad_type = _results()
        bad_type[att.RESULT_FIELDS[0]] = 1  # bool-safe contract
        _reject(
            lambda: att.build_pilot_execution_admission_attestation(
                packet=claim.packet,
                attestation_id="bad-result-type",
                observer_host_id="modelrig-host-001",
                attested_at_utc="2026-09-14T08:30:00Z",
                results=bad_type,
            )
        )
        _reject(
            lambda: att.build_pilot_execution_admission_attestation(
                packet=claim.packet,
                attestation_id="early-attestation",
                observer_host_id="modelrig-host-001",
                attested_at_utc="2026-09-14T08:28:59Z",
                results=_results(),
            )
        )
        for field in (
            "host_attestation_verified",
            "execution_admission_observed",
            "execution_admission_satisfied",
            "task_execution_authorized",
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
                lambda field=field: att.PilotExecutionAdmissionAttestation.from_mapping(
                    {**claim.to_dict(), field: True}
                )
            )

        claim_schema = json.loads(CLAIM_SCHEMA.read_text(encoding="utf-8"))
        proof_schema = json.loads(PROOF_SCHEMA.read_text(encoding="utf-8"))
        assert set(claim_schema["properties"]) == set(claim.to_dict())
        assert set(proof_schema["properties"]) == set(proof.to_dict())
        assert claim_schema["additionalProperties"] is False
        assert proof_schema["additionalProperties"] is False
        assert (
            claim_schema["properties"]["packet"]["$ref"]
            == "rsi-pilot-execution-admission-observation-packet-v1.schema.json"
        )
        assert (
            proof_schema["properties"]["attestation"]["$ref"]
            == "rsi-pilot-execution-admission-attestation-v1.schema.json"
        )
        assert proof_schema["properties"]["host_attestation_verified"]["const"] is True
        assert proof_schema["properties"]["execution_admission_observed"]["const"] is True
        for field in (
            "task_execution_authorized",
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
            assert proof_schema["properties"][field]["const"] is False

        root_source = inspect.getsource(kaliv_dev_control)
        assert "improvement_pilot_execution_admission_attestation" not in root_source
        source = inspect.getsource(att).lower()
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

    # Keep ADR-DC-029 transitively wired through ADR-DC-028 and the same
    # Stage-B support entrypoint instead of expanding the locked top-level inventory.
    from rsi_pilot_exact_task_execution_admission_requirements_contract import (
        run_contract as run_exact_task_execution_admission_requirements_contract,
    )

    run_exact_task_execution_admission_requirements_contract()


if __name__ == "__main__":
    run_contract()
