"""Adversarial contract for ADR-DC-024 human pilot-start authorization."""
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
import kaliv_dev_control.improvement_pilot_runtime_preflight_attestation as attestation  # noqa: E402
import kaliv_dev_control.improvement_pilot_start_authorization as start_auth  # noqa: E402
from rsi_pilot_runtime_preflight_attestation_proof_contract import (  # noqa: E402
    _authority as _preflight_authority,
    _claim as _preflight_claim,
)

AUTHORIZATION_SCHEMA = (
    ROOT / "devcontrol" / "schemas" / "rsi-pilot-start-authorization-v1.schema.json"
)
PROOF_SCHEMA = (
    ROOT / "devcontrol" / "schemas" / "rsi-pilot-start-authorization-proof-v1.schema.json"
)


def _preflight_proof(*, all_green: bool = True):
    claim = _preflight_claim(all_green=all_green)
    verifier, signature = _preflight_authority(claim)
    return attestation._verify_pilot_runtime_preflight_attestation(
        attestation=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:24:00Z",
    )


def _authority(authorization: start_auth.PilotStartAuthorization):
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("33" * 32))
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    policy = asymmetric_authority_key_custody_policy_sha256()
    key = TrustedEd25519AuthorityKey(
        key_id="pilot-start-key-001",
        issuer_actor_id=authorization.start_authorizer_actor_id,
        issuer_system_id=start_auth.PILOT_START_AUTHORIZATION_ISSUER_SYSTEM_ID,
        public_key_hex=public_hex,
        valid_from_utc="2026-09-14T00:00:00Z",
        valid_until_utc="2027-09-14T00:00:00Z",
        keyring_epoch=1,
        custody_policy_sha256=policy,
    )
    verifier = Ed25519AuthorityVerifier({key.key_id: key}, minimum_keyring_epoch=1)
    payload = authorization.canonical_json().encode("utf-8")
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
        signed_at_utc=authorization.authorized_at_utc,
    )
    return verifier, signature


def _reject(fn) -> None:
    try:
        fn()
    except start_auth.PilotStartAuthorizationError:
        return
    raise AssertionError("ADR-DC-024 unexpectedly accepted invalid input")


def run_contract() -> None:
    assert catalog.modelrig_command_catalog().command_ids == ()

    preflight = _preflight_proof()
    packet = preflight.attestation.packet
    authorization = start_auth.build_pilot_start_authorization(
        preflight_proof=preflight,
        authorization_id="pilot-start-024",
        start_authorizer_actor_id="anders",
        authorized_at_utc="2026-09-14T08:25:00Z",
        expires_at_utc="2026-09-14T08:35:00Z",
        start_nonce_sha256="a" * 64,
        notes=("Authorize one local pilot start only.",),
    )
    assert start_auth.PILOT_START_AUTHORIZATION_MAX_WINDOW_SECONDS == 900
    assert authorization.schema == start_auth.PILOT_START_AUTHORIZATION_SCHEMA
    assert authorization.authority == start_auth.PILOT_START_AUTHORIZATION_AUTHORITY
    assert authorization.human_start_intent == start_auth.PILOT_START_AUTHORIZATION_INTENT
    assert authorization.preflight_proof == preflight
    assert authorization.preflight_proof_sha256 == preflight.sha256
    assert authorization.attestation_sha256 == preflight.attestation_sha256
    assert authorization.packet_sha256 == preflight.packet_sha256
    assert authorization.selection_proof_sha256 == packet.selection_proof_sha256
    assert authorization.candidate_proof_sha256 == packet.selection_proof.candidate_proof_sha256
    assert authorization.requirements_sha256 == packet.preflight_requirements_sha256
    assert authorization.trial_scope_sha256 == packet.preflight_requirements.trial_scope_sha256
    assert authorization.observer_actor_id == packet.observer_actor_id
    assert authorization.observer_host_id == preflight.attestation.observer_host_id
    assert authorization.start_authorizer_actor_id == "anders"
    assert authorization.start_authorizer_actor_id != authorization.observer_actor_id
    assert authorization.one_shot_start_required is True
    assert authorization.start_consumed is False
    assert authorization.integration_ready is False
    assert authorization.pilot_start_authorized is False
    assert authorization.product_pilot_started is False
    assert authorization.local_commit_authorized is False
    assert authorization.production_activation_authorized is False
    assert start_auth.PilotStartAuthorization.from_mapping(
        authorization.to_dict()
    ) == authorization

    verifier, signature = _authority(authorization)
    proof = start_auth._verify_pilot_start_authorization(
        preflight_proof=preflight,
        authorization=authorization,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:26:00Z",
    )
    assert proof.schema == start_auth.PILOT_START_AUTHORIZATION_PROOF_SCHEMA
    assert proof.authority == start_auth.PILOT_START_AUTHORIZATION_PROOF_AUTHORITY
    assert proof.authorization == authorization
    assert proof.authorization_sha256 == authorization.sha256
    assert proof.pilot_start_authorized is True
    assert proof.one_shot_start_required is True
    assert proof.start_consumed is False
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
    assert start_auth.PilotStartAuthorizationProof.from_mapping(proof.to_dict()) == proof

    _reject(
        lambda: start_auth.verify_pilot_start_authorization(
            preflight_proof=preflight,
            authorization=authorization,
            signature=signature,
            verifier=verifier,
        )
    )

    failed_preflight = _preflight_proof(all_green=False)
    assert failed_preflight.preflight_satisfied is False
    _reject(
        lambda: start_auth.build_pilot_start_authorization(
            preflight_proof=failed_preflight,
            authorization_id="pilot-start-failed-preflight",
            start_authorizer_actor_id="anders",
            authorized_at_utc="2026-09-14T08:25:00Z",
            expires_at_utc="2026-09-14T08:35:00Z",
            start_nonce_sha256="b" * 64,
        )
    )

    _reject(
        lambda: start_auth.build_pilot_start_authorization(
            preflight_proof=preflight,
            authorization_id="pilot-start-wrong-human",
            start_authorizer_actor_id="mallory",
            authorized_at_utc="2026-09-14T08:25:00Z",
            expires_at_utc="2026-09-14T08:35:00Z",
            start_nonce_sha256="b" * 64,
        )
    )
    _reject(
        lambda: start_auth.build_pilot_start_authorization(
            preflight_proof=preflight,
            authorization_id="pilot-start-host-as-human",
            start_authorizer_actor_id=packet.observer_actor_id,
            authorized_at_utc="2026-09-14T08:25:00Z",
            expires_at_utc="2026-09-14T08:35:00Z",
            start_nonce_sha256="b" * 64,
        )
    )
    _reject(
        lambda: start_auth.build_pilot_start_authorization(
            preflight_proof=preflight,
            authorization_id="pilot-start-placeholder-nonce",
            start_authorizer_actor_id="anders",
            authorized_at_utc="2026-09-14T08:25:00Z",
            expires_at_utc="2026-09-14T08:35:00Z",
            start_nonce_sha256="0" * 64,
        )
    )
    _reject(
        lambda: start_auth.build_pilot_start_authorization(
            preflight_proof=preflight,
            authorization_id="pilot-start-too-long",
            start_authorizer_actor_id="anders",
            authorized_at_utc="2026-09-14T08:25:00Z",
            expires_at_utc="2026-09-14T08:41:00Z",
            start_nonce_sha256="b" * 64,
        )
    )
    _reject(
        lambda: start_auth.build_pilot_start_authorization(
            preflight_proof=preflight,
            authorization_id="pilot-start-before-preflight",
            start_authorizer_actor_id="anders",
            authorized_at_utc="2026-09-14T08:23:00Z",
            expires_at_utc="2026-09-14T08:33:00Z",
            start_nonce_sha256="b" * 64,
        )
    )

    _reject(
        lambda: start_auth._verify_pilot_start_authorization(
            preflight_proof=preflight,
            authorization=authorization,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-14T08:36:00Z",
        )
    )
    wrong_actor_signature = replace(signature, issuer_actor_id="mallory")
    _reject(
        lambda: start_auth._verify_pilot_start_authorization(
            preflight_proof=preflight,
            authorization=authorization,
            signature=wrong_actor_signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-14T08:26:00Z",
        )
    )
    wrong_domain_signature = replace(
        signature,
        issuer_system_id="kaliv-rsi-unrelated-authority-v1",
    )
    _reject(
        lambda: start_auth._verify_pilot_start_authorization(
            preflight_proof=preflight,
            authorization=authorization,
            signature=wrong_domain_signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-14T08:26:00Z",
        )
    )

    alternate = start_auth.build_pilot_start_authorization(
        preflight_proof=preflight,
        authorization_id="pilot-start-024-alt",
        start_authorizer_actor_id="anders",
        authorized_at_utc="2026-09-14T08:25:00Z",
        expires_at_utc="2026-09-14T08:35:00Z",
        start_nonce_sha256="c" * 64,
    )
    _reject(
        lambda: start_auth._verify_pilot_start_authorization(
            preflight_proof=preflight,
            authorization=alternate,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-14T08:26:00Z",
        )
    )

    nested_tamper = authorization.to_dict()
    nested_tamper["preflight_proof"] = dict(nested_tamper["preflight_proof"])
    nested_tamper["preflight_proof"]["preflight_satisfied"] = False
    _reject(lambda: start_auth.PilotStartAuthorization.from_mapping(nested_tamper))

    for field in (
        "start_consumed",
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
            lambda field=field: start_auth.PilotStartAuthorizationProof.from_mapping(
                {**proof.to_dict(), field: True}
            )
        )
    _reject(
        lambda: start_auth.PilotStartAuthorizationProof.from_mapping(
            {**proof.to_dict(), "pilot_start_authorized": False}
        )
    )

    authorization_schema = json.loads(AUTHORIZATION_SCHEMA.read_text(encoding="utf-8"))
    auth_props = authorization_schema["properties"]
    assert set(auth_props) == set(authorization.to_dict())
    assert auth_props["schema"]["const"] == start_auth.PILOT_START_AUTHORIZATION_SCHEMA
    assert auth_props["human_start_intent"]["const"] == start_auth.PILOT_START_AUTHORIZATION_INTENT
    assert auth_props["one_shot_start_required"]["const"] is True
    assert auth_props["start_consumed"]["const"] is False
    assert auth_props["pilot_start_authorized"]["const"] is False
    assert auth_props["product_pilot_started"]["const"] is False
    assert auth_props["local_commit_authorized"]["const"] is False
    assert auth_props["production_activation_authorized"]["const"] is False
    assert auth_props["authority"]["const"] == start_auth.PILOT_START_AUTHORIZATION_AUTHORITY

    proof_schema = json.loads(PROOF_SCHEMA.read_text(encoding="utf-8"))
    proof_props = proof_schema["properties"]
    assert set(proof_props) == set(proof.to_dict())
    assert proof_props["schema"]["const"] == start_auth.PILOT_START_AUTHORIZATION_PROOF_SCHEMA
    assert proof_props["issuer_system_id"]["const"] == start_auth.PILOT_START_AUTHORIZATION_ISSUER_SYSTEM_ID
    assert proof_props["one_shot_start_required"]["const"] is True
    assert proof_props["start_consumed"]["const"] is False
    assert proof_props["pilot_start_authorized"]["const"] is True
    assert proof_props["product_pilot_started"]["const"] is False
    assert proof_props["local_commit_authorized"]["const"] is False
    assert proof_props["production_activation_authorized"]["const"] is False
    assert proof_props["authority"]["const"] == start_auth.PILOT_START_AUTHORIZATION_PROOF_AUTHORITY

    root_source = inspect.getsource(kaliv_dev_control)
    assert "improvement_pilot_start_authorization" not in root_source
    source = inspect.getsource(start_auth._implementation).lower()
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
