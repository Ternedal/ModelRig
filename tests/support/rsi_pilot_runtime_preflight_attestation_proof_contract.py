"""Adversarial contract for ADR-DC-023 host-attested preflight packet proof."""
from __future__ import annotations

import hashlib
import inspect
import json
import sys
from dataclasses import replace
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
from kaliv_dev_control.improvement_pilot_integration_human_selection import (  # noqa: E402
    _verify_pilot_integration_human_selection,
    build_pilot_integration_human_selection,
)
from kaliv_dev_control.improvement_pilot_preflight_requirements import (  # noqa: E402
    build_pilot_preflight_requirements,
)
from kaliv_dev_control.improvement_pilot_runtime_preflight_observation import (  # noqa: E402
    PilotRuntimePreflightObservationPacket,
    build_pilot_runtime_preflight_observation_packet,
)
import kaliv_dev_control.improvement_pilot_runtime_preflight_attestation as attestation  # noqa: E402
from rsi_pilot_integration_human_selection_contract import (  # noqa: E402
    _authority as _selection_authority,
    _candidate,
    _scope,
)

CLAIM_SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-runtime-preflight-attestation-v1.schema.json"
)
PROOF_SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-runtime-preflight-attestation-proof-v1.schema.json"
)

EVIDENCE_FIELDS = (
    "feature_flag_off_evidence_sha256",
    "pilot_runtime_evidence_sha256",
    "native_windows_isolation_evidence_sha256",
    "trusted_git_closure_evidence_sha256",
    "kill_switch_prearm_evidence_sha256",
    "restart_revoke_prearm_evidence_sha256",
    "network_write_block_evidence_sha256",
    "credentials_absent_evidence_sha256",
    "unattended_cadence_evidence_sha256",
    "off_state_import_block_evidence_sha256",
    "exact_source_binding_evidence_sha256",
    "receipt_binding_evidence_sha256",
)


def _selection_proof():
    candidate = _candidate()
    selection = build_pilot_integration_human_selection(
        candidate_proof=candidate,
        selection_id="selection-023",
        selection_maker_actor_id="anders",
        selected_at_utc="2026-09-14T08:20:00Z",
        notes=("Exact candidate selected for evidence-bound preflight only.",),
    )
    verifier, signature = _selection_authority(selection)
    return _verify_pilot_integration_human_selection(
        candidate_proof=candidate,
        selection=selection,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:21:00Z",
    )


def _evidence() -> dict[str, str]:
    return {
        name: hashlib.sha256(("adr-dc-023:" + name).encode("utf-8")).hexdigest()
        for name in EVIDENCE_FIELDS
    }


def _packet() -> PilotRuntimePreflightObservationPacket:
    selection_proof = _selection_proof()
    requirements = build_pilot_preflight_requirements(scope_proof=_scope())
    return build_pilot_runtime_preflight_observation_packet(
        selection_proof=selection_proof,
        preflight_requirements=requirements,
        observation_id="preflight-packet-023",
        observer_actor_id="host-observer",
        observed_at_utc="2026-09-14T08:22:00Z",
        evidence_sha256=_evidence(),
    )


def _claim(*, all_green: bool = True):
    packet = _packet()
    return attestation.build_pilot_runtime_preflight_attestation(
        packet=packet,
        attestation_id="preflight-attestation-023",
        observer_host_id="modelrig-host-001",
        attested_at_utc="2026-09-14T08:23:00Z",
        feature_flag_off_verified=all_green,
        pilot_runtime_verified=True,
        native_windows_isolation_verified=True,
        trusted_git_closure_verified=True,
        kill_switch_prearmed=True,
        restart_revoke_prearmed=True,
        network_write_block_verified=True,
        credentials_absent_verified=True,
        unattended_cadence_forbidden_verified=True,
        off_state_import_block_verified=True,
        exact_source_binding_verified=True,
        receipt_binding_verified=True,
    )


def _authority(claim: attestation.PilotRuntimePreflightAttestation):
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("23" * 32))
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    policy = asymmetric_authority_key_custody_policy_sha256()
    key = TrustedEd25519AuthorityKey(
        key_id="preflight-attestation-key-001",
        issuer_actor_id=claim.packet.observer_actor_id,
        issuer_system_id=attestation.PILOT_RUNTIME_PREFLIGHT_ATTESTATION_ISSUER_SYSTEM_ID,
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
    except attestation.PilotRuntimePreflightAttestationError:
        return
    raise AssertionError("ADR-DC-023 unexpectedly accepted invalid input")


def run_contract() -> None:
    assert catalog.modelrig_command_catalog().command_ids == ()

    claim = _claim()
    assert claim.schema == attestation.PILOT_RUNTIME_PREFLIGHT_ATTESTATION_SCHEMA
    assert claim.authority == attestation.PILOT_RUNTIME_PREFLIGHT_ATTESTATION_AUTHORITY
    assert claim.packet_sha256 == claim.packet.sha256
    assert claim.packet.observation_set_complete is True
    assert claim.packet.evidence_verified is False
    assert claim.all_checks_satisfied is True
    assert claim.host_attestation_verified is False
    assert claim.preflight_observed is False
    assert claim.preflight_satisfied is False
    assert claim.integration_ready is False
    assert claim.pilot_start_authorized is False
    assert claim.product_pilot_started is False
    assert claim.local_commit_authorized is False
    assert claim.production_activation_authorized is False
    assert attestation.PilotRuntimePreflightAttestation.from_mapping(
        claim.to_dict()
    ) == claim

    verifier, signature = _authority(claim)
    proof = attestation._verify_pilot_runtime_preflight_attestation(
        attestation=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:24:00Z",
    )
    assert proof.schema == attestation.PILOT_RUNTIME_PREFLIGHT_ATTESTATION_PROOF_SCHEMA
    assert proof.authority == attestation.PILOT_RUNTIME_PREFLIGHT_ATTESTATION_PROOF_AUTHORITY
    assert proof.attestation == claim
    assert proof.packet_sha256 == claim.packet.sha256
    assert proof.host_attestation_verified is True
    assert proof.preflight_observed is True
    assert proof.preflight_satisfied is True
    assert proof.integration_ready is False
    assert proof.pilot_start_authorized is False
    assert proof.product_pilot_started is False
    assert proof.local_commit_authorized is False
    assert proof.remote_write_authorized is False
    assert proof.push_authorized is False
    assert proof.pr_mutation_authorized is False
    assert proof.merge_authorized is False
    assert proof.release_authorized is False
    assert proof.deploy_authorized is False
    assert proof.production_activation_authorized is False
    assert attestation.PilotRuntimePreflightAttestationProof.from_mapping(
        proof.to_dict()
    ) == proof

    _reject(
        lambda: attestation.verify_pilot_runtime_preflight_attestation(
            attestation=claim,
            signature=signature,
            verifier=verifier,
        )
    )

    failed_claim = _claim(all_green=False)
    failed_verifier, failed_signature = _authority(failed_claim)
    failed_proof = attestation._verify_pilot_runtime_preflight_attestation(
        attestation=failed_claim,
        signature=failed_signature,
        verifier=failed_verifier,
        now_provider=lambda: "2026-09-14T08:24:00Z",
    )
    assert failed_proof.host_attestation_verified is True
    assert failed_proof.preflight_observed is True
    assert failed_proof.preflight_satisfied is False
    assert failed_proof.pilot_start_authorized is False

    early = claim.to_dict()
    early["attested_at_utc"] = "2026-09-14T08:21:59Z"
    _reject(lambda: attestation.PilotRuntimePreflightAttestation.from_mapping(early))

    packet_tamper = claim.to_dict()
    packet_tamper["packet"] = dict(packet_tamper["packet"])
    packet_tamper["packet"]["network_write_block_evidence_sha256"] = "f" * 64
    _reject(
        lambda: attestation.PilotRuntimePreflightAttestation.from_mapping(
            packet_tamper
        )
    )

    changed_result = replace(claim, feature_flag_off_verified=False)
    _reject(
        lambda: attestation._verify_pilot_runtime_preflight_attestation(
            attestation=changed_result,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-14T08:24:00Z",
        )
    )

    wrong_actor_signature = replace(signature, issuer_actor_id="mallory")
    _reject(
        lambda: attestation._verify_pilot_runtime_preflight_attestation(
            attestation=claim,
            signature=wrong_actor_signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-14T08:24:00Z",
        )
    )
    wrong_domain_signature = replace(
        signature,
        issuer_system_id="kaliv-rsi-unrelated-authority-v1",
    )
    _reject(
        lambda: attestation._verify_pilot_runtime_preflight_attestation(
            attestation=claim,
            signature=wrong_domain_signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-14T08:24:00Z",
        )
    )

    _reject(
        lambda: attestation.PilotRuntimePreflightAttestationProof.from_mapping(
            {**proof.to_dict(), "preflight_satisfied": False}
        )
    )
    for field in (
        "integration_ready",
        "pilot_start_authorized",
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
            lambda field=field: attestation.PilotRuntimePreflightAttestationProof.from_mapping(
                {**proof.to_dict(), field: True}
            )
        )

    claim_schema = json.loads(CLAIM_SCHEMA.read_text(encoding="utf-8"))
    claim_props = claim_schema["properties"]
    assert set(claim_props) == set(claim.to_dict())
    assert claim_props["schema"]["const"] == attestation.PILOT_RUNTIME_PREFLIGHT_ATTESTATION_SCHEMA
    assert claim_props["host_attestation_verified"]["const"] is False
    assert claim_props["preflight_observed"]["const"] is False
    assert claim_props["preflight_satisfied"]["const"] is False
    assert claim_props["pilot_start_authorized"]["const"] is False
    assert claim_props["production_activation_authorized"]["const"] is False
    assert claim_props["authority"]["const"] == attestation.PILOT_RUNTIME_PREFLIGHT_ATTESTATION_AUTHORITY

    proof_schema = json.loads(PROOF_SCHEMA.read_text(encoding="utf-8"))
    proof_props = proof_schema["properties"]
    assert set(proof_props) == set(proof.to_dict())
    assert proof_props["schema"]["const"] == attestation.PILOT_RUNTIME_PREFLIGHT_ATTESTATION_PROOF_SCHEMA
    assert proof_props["issuer_system_id"]["const"] == attestation.PILOT_RUNTIME_PREFLIGHT_ATTESTATION_ISSUER_SYSTEM_ID
    assert proof_props["host_attestation_verified"]["const"] is True
    assert proof_props["preflight_observed"]["const"] is True
    assert proof_props["preflight_satisfied"]["type"] == "boolean"
    assert proof_props["pilot_start_authorized"]["const"] is False
    assert proof_props["production_activation_authorized"]["const"] is False
    assert proof_props["authority"]["const"] == attestation.PILOT_RUNTIME_PREFLIGHT_ATTESTATION_PROOF_AUTHORITY

    root_source = inspect.getsource(kaliv_dev_control)
    assert "improvement_pilot_runtime_preflight_attestation" not in root_source
    source = inspect.getsource(attestation._implementation).lower()
    for forbidden in (
        "subprocess",
        "socket",
        "requests",
        "urllib",
        "git push",
        "merge_pull_request",
    ):
        assert forbidden not in source, forbidden


if __name__ == "__main__":
    run_contract()
