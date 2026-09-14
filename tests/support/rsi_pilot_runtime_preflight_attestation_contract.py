"""Adversarial contract for ADR-DC-022 host-attested runtime preflight."""
from __future__ import annotations

import hashlib
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
from kaliv_dev_control.improvement_pilot_runtime_preflight_attestation import (  # noqa: E402
    PILOT_RUNTIME_PREFLIGHT_ISSUER_SYSTEM_ID,
    PILOT_RUNTIME_PREFLIGHT_OBSERVATION_AUTHORITY,
    PILOT_RUNTIME_PREFLIGHT_OBSERVATION_SCHEMA,
    PILOT_RUNTIME_PREFLIGHT_PROOF_AUTHORITY,
    PILOT_RUNTIME_PREFLIGHT_PROOF_SCHEMA,
    PilotRuntimePreflightError,
    PilotRuntimePreflightObservation,
    PilotRuntimePreflightProof,
    _verify_pilot_runtime_preflight,
    build_pilot_runtime_preflight_observation,
    verify_pilot_runtime_preflight,
)
from rsi_pilot_integration_human_selection_contract import (  # noqa: E402
    _authority as _selection_authority,
    _candidate,
    _scope,
)

OBSERVATION_SCHEMA = (
    ROOT / "devcontrol" / "schemas" / "rsi-pilot-runtime-preflight-observation-v1.schema.json"
)
PROOF_SCHEMA = (
    ROOT / "devcontrol" / "schemas" / "rsi-pilot-runtime-preflight-proof-v1.schema.json"
)


def _selection_proof():
    candidate = _candidate()
    selection = build_pilot_integration_human_selection(
        candidate_proof=candidate,
        selection_id="selection-022",
        selection_maker_actor_id="anders",
        selected_at_utc="2026-09-14T08:10:00Z",
        notes=("Exact candidate selected for preflight evidence only.",),
    )
    verifier, signature = _selection_authority(selection)
    return _verify_pilot_integration_human_selection(
        candidate_proof=candidate,
        selection=selection,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:11:00Z",
    )


def _observation(*, all_green: bool = True):
    selection_proof = _selection_proof()
    requirements = build_pilot_preflight_requirements(scope_proof=_scope())
    return selection_proof, requirements, build_pilot_runtime_preflight_observation(
        selection_proof=selection_proof,
        requirements=requirements,
        observation_id="preflight-observation-022",
        observer_actor_id="host-observer",
        observer_host_id="modelrig-host-001",
        observed_at_utc="2026-09-14T08:12:00Z",
        runtime_receipt_sha256="8" * 64,
        feature_flag_off_observed=all_green,
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


def _authority(observation: PilotRuntimePreflightObservation):
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("22" * 32))
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    policy = asymmetric_authority_key_custody_policy_sha256()
    key = TrustedEd25519AuthorityKey(
        key_id="preflight-key-001",
        issuer_actor_id=observation.observer_actor_id,
        issuer_system_id=PILOT_RUNTIME_PREFLIGHT_ISSUER_SYSTEM_ID,
        public_key_hex=public_hex,
        valid_from_utc="2026-09-14T00:00:00Z",
        valid_until_utc="2027-09-14T00:00:00Z",
        keyring_epoch=1,
        custody_policy_sha256=policy,
    )
    verifier = Ed25519AuthorityVerifier({key.key_id: key}, minimum_keyring_epoch=1)
    payload = observation.canonical_json().encode("utf-8")
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
        signed_at_utc=observation.observed_at_utc,
    )
    return verifier, signature


def _reject(callable_) -> None:
    try:
        callable_()
    except PilotRuntimePreflightError:
        return
    raise AssertionError("runtime preflight unexpectedly accepted invalid input")


def run_contract() -> None:
    selection_proof, requirements, observation = _observation()
    assert observation.schema == PILOT_RUNTIME_PREFLIGHT_OBSERVATION_SCHEMA
    assert observation.authority == PILOT_RUNTIME_PREFLIGHT_OBSERVATION_AUTHORITY
    assert observation.selection_proof_sha256 == selection_proof.sha256
    assert observation.requirements_sha256 == requirements.sha256
    assert observation.candidate_proof_sha256 == selection_proof.candidate_proof_sha256
    assert observation.all_checks_satisfied is True
    assert observation.preflight_observed is False
    assert observation.preflight_satisfied is False
    assert observation.pilot_start_authorized is False
    assert observation.production_activation_authorized is False
    assert PilotRuntimePreflightObservation.from_mapping(observation.to_dict()) == observation

    verifier, signature = _authority(observation)
    proof = _verify_pilot_runtime_preflight(
        selection_proof=selection_proof,
        requirements=requirements,
        observation=observation,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:13:00Z",
    )
    assert proof.schema == PILOT_RUNTIME_PREFLIGHT_PROOF_SCHEMA
    assert proof.authority == PILOT_RUNTIME_PREFLIGHT_PROOF_AUTHORITY
    assert proof.preflight_observed is True
    assert proof.preflight_satisfied is True
    assert proof.integration_ready is False
    assert proof.pilot_start_authorized is False
    assert proof.product_pilot_started is False
    assert proof.remote_write_authorized is False
    assert proof.push_authorized is False
    assert proof.pr_mutation_authorized is False
    assert proof.merge_authorized is False
    assert proof.release_authorized is False
    assert proof.deploy_authorized is False
    assert proof.production_activation_authorized is False
    assert PilotRuntimePreflightProof.from_mapping(proof.to_dict()) == proof

    _reject(lambda: verify_pilot_runtime_preflight(
        selection_proof=selection_proof,
        requirements=requirements,
        observation=observation,
        signature=signature,
        verifier=verifier,
    ))

    fail_selection, fail_requirements, failed = _observation(all_green=False)
    fail_verifier, fail_signature = _authority(failed)
    failed_proof = _verify_pilot_runtime_preflight(
        selection_proof=fail_selection,
        requirements=fail_requirements,
        observation=failed,
        signature=fail_signature,
        verifier=fail_verifier,
        now_provider=lambda: "2026-09-14T08:13:00Z",
    )
    assert failed_proof.preflight_observed is True
    assert failed_proof.preflight_satisfied is False
    assert failed_proof.pilot_start_authorized is False

    rebound_requirements = replace(requirements, trial_id="trial-022-rebound")
    _reject(lambda: build_pilot_runtime_preflight_observation(
        selection_proof=selection_proof,
        requirements=rebound_requirements,
        observation_id="preflight-observation-rebound",
        observer_actor_id="host-observer",
        observer_host_id="modelrig-host-001",
        observed_at_utc="2026-09-14T08:12:00Z",
        runtime_receipt_sha256="8" * 64,
        feature_flag_off_observed=True,
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
    ))

    tampered = observation.to_dict()
    tampered["feature_flag_name"] = "KALIV_DEVCONTROL_PILOT_ALT"
    tampered_observation = PilotRuntimePreflightObservation.from_mapping(tampered)
    _reject(lambda: _verify_pilot_runtime_preflight(
        selection_proof=selection_proof,
        requirements=requirements,
        observation=tampered_observation,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:13:00Z",
    ))

    wrong_actor_signature = replace(signature, issuer_actor_id="mallory")
    _reject(lambda: _verify_pilot_runtime_preflight(
        selection_proof=selection_proof,
        requirements=requirements,
        observation=observation,
        signature=wrong_actor_signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:13:00Z",
    ))
    wrong_domain_signature = replace(
        signature,
        issuer_system_id="kaliv-rsi-unrelated-authority-v1",
    )
    _reject(lambda: _verify_pilot_runtime_preflight(
        selection_proof=selection_proof,
        requirements=requirements,
        observation=observation,
        signature=wrong_domain_signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:13:00Z",
    ))

    for field in (
        "integration_ready",
        "pilot_start_authorized",
        "product_pilot_started",
        "remote_write_authorized",
        "push_authorized",
        "pr_mutation_authorized",
        "merge_authorized",
        "release_authorized",
        "deploy_authorized",
        "production_activation_authorized",
    ):
        _reject(lambda field=field: PilotRuntimePreflightProof.from_mapping({
            **proof.to_dict(),
            field: True,
        }))

    _reject(lambda: PilotRuntimePreflightProof.from_mapping({
        **proof.to_dict(),
        "preflight_satisfied": False,
    }))

    nested_tamper = proof.to_dict()
    nested_tamper["observation"] = dict(nested_tamper["observation"])
    nested_tamper["observation"]["runtime_receipt_sha256"] = "9" * 64
    _reject(lambda: PilotRuntimePreflightProof.from_mapping(nested_tamper))

    observation_schema = json.loads(OBSERVATION_SCHEMA.read_text(encoding="utf-8"))
    obs_props = observation_schema["properties"]
    assert obs_props["schema"]["const"] == PILOT_RUNTIME_PREFLIGHT_OBSERVATION_SCHEMA
    assert obs_props["preflight_observed"]["const"] is False
    assert obs_props["preflight_satisfied"]["const"] is False
    assert obs_props["pilot_start_authorized"]["const"] is False
    assert obs_props["production_activation_authorized"]["const"] is False
    assert obs_props["authority"]["const"] == PILOT_RUNTIME_PREFLIGHT_OBSERVATION_AUTHORITY

    proof_schema = json.loads(PROOF_SCHEMA.read_text(encoding="utf-8"))
    proof_props = proof_schema["properties"]
    assert proof_props["schema"]["const"] == PILOT_RUNTIME_PREFLIGHT_PROOF_SCHEMA
    assert proof_props["issuer_system_id"]["const"] == PILOT_RUNTIME_PREFLIGHT_ISSUER_SYSTEM_ID
    assert proof_props["preflight_observed"]["const"] is True
    assert proof_props["preflight_satisfied"]["type"] == "boolean"
    assert proof_props["pilot_start_authorized"]["const"] is False
    assert proof_props["production_activation_authorized"]["const"] is False
    assert proof_props["authority"]["const"] == PILOT_RUNTIME_PREFLIGHT_PROOF_AUTHORITY


if __name__ == "__main__":
    run_contract()
