"""Adversarial contract for ADR-DC-021 human integration selection."""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
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
    PILOT_INTEGRATION_HUMAN_SELECTION_AUTHORITY,
    PILOT_INTEGRATION_HUMAN_SELECTION_INTENT,
    PILOT_INTEGRATION_HUMAN_SELECTION_ISSUER_SYSTEM_ID,
    PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_AUTHORITY,
    PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_SCHEMA,
    PILOT_INTEGRATION_HUMAN_SELECTION_SCHEMA,
    PilotIntegrationHumanSelection,
    PilotIntegrationHumanSelectionError,
    PilotIntegrationHumanSelectionProof,
    _verify_pilot_integration_human_selection,
    build_pilot_integration_human_selection,
    verify_pilot_integration_human_selection,
)
from kaliv_dev_control.improvement_pilot_integration_selection_candidate import (  # noqa: E402
    PilotIntegrationSelectionCandidateProof,
    validate_pilot_integration_selection_candidate,
)
from kaliv_dev_control.improvement_pilot_trial_scope import PilotTrialScopeProof  # noqa: E402

INVENTORY = ROOT / "docs" / "devcontrol" / "dc-l16" / "product-integration-inventory.json"
REQUIREMENTS = ROOT / "docs" / "devcontrol" / "dc-l16" / "product-integration-selection-requirements.json"
CLAIM_SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-product-integration-human-selection-v1.schema.json"
PROOF_SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-product-integration-human-selection-proof-v1.schema.json"


def _scope() -> PilotTrialScopeProof:
    return PilotTrialScopeProof(
        decision_proof_sha256="1" * 64,
        decision_sha256="2" * 64,
        signature_sha256="3" * 64,
        campaign_id="campaign-021",
        source_task_id="source-task",
        source_task_sha256="4" * 64,
        repository="Ternedal/ModelRig",
        base_sha="5" * 40,
        requested_main_sha="6" * 40,
        decision_id="decision-021",
        decision_maker_actor_id="anders",
        decision="go",
        trial_id="trial-021",
        operator_surface="desktop.control-center",
        selected_pilot_task_id="task-local-001",
        workspace_root_path_sha256="7" * 64,
        local_commits_allowed=False,
        decision_notes=(),
    )


def _candidate() -> PilotIntegrationSelectionCandidateProof:
    return validate_pilot_integration_selection_candidate(
        scope_proof=_scope(),
        inventory_bytes=INVENTORY.read_bytes(),
        selection_requirements_bytes=REQUIREMENTS.read_bytes(),
        feature_flag_name="KALIV_DEVCONTROL_PILOT_ENABLED",
        product_route="/api/v1/devcontrol/pilot",
        runtime_observer_id="devcontrol.runtime-observer.v1",
        task_registry_id="devcontrol.pilot-registry.v1",
        workspace_policy_id="devcontrol.workspace-local.v1",
        review_authorization_roles_id="devcontrol.review-roles.v1",
        kill_revoke_cleanup_id="devcontrol.kill-revoke-cleanup.v1",
        local_commit_policy="forbid",
    )


def _authority(selection: PilotIntegrationHumanSelection):
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("11" * 32))
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    policy = asymmetric_authority_key_custody_policy_sha256()
    key = TrustedEd25519AuthorityKey(
        key_id="selection-key-001",
        issuer_actor_id=selection.selection_maker_actor_id,
        issuer_system_id=PILOT_INTEGRATION_HUMAN_SELECTION_ISSUER_SYSTEM_ID,
        public_key_hex=public_hex,
        valid_from_utc="2026-09-14T00:00:00Z",
        valid_until_utc="2027-09-14T00:00:00Z",
        keyring_epoch=1,
        custody_policy_sha256=policy,
    )
    verifier = Ed25519AuthorityVerifier(
        {key.key_id: key},
        minimum_keyring_epoch=1,
    )
    payload = selection.canonical_json().encode("utf-8")
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
        signed_at_utc=selection.selected_at_utc,
    )
    return verifier, signature


def _reject(callable_) -> None:
    try:
        callable_()
    except PilotIntegrationHumanSelectionError:
        return
    raise AssertionError("human integration selection unexpectedly accepted invalid input")


def run_contract() -> None:
    candidate = _candidate()
    selection = build_pilot_integration_human_selection(
        candidate_proof=candidate,
        selection_id="selection-021",
        selection_maker_actor_id="anders",
        selected_at_utc="2026-09-14T08:00:00Z",
        notes=("Explicitly selects only the exact validated candidate.",),
    )
    assert selection.schema == PILOT_INTEGRATION_HUMAN_SELECTION_SCHEMA
    assert selection.authority == PILOT_INTEGRATION_HUMAN_SELECTION_AUTHORITY
    assert selection.human_selection_intent == PILOT_INTEGRATION_HUMAN_SELECTION_INTENT
    assert selection.candidate_proof == candidate
    assert selection.candidate_proof_sha256 == candidate.sha256
    assert selection.human_selection_recorded is False
    assert selection.integration_ready is False
    assert selection.pilot_start_authorized is False
    assert selection.production_activation_authorized is False
    assert PilotIntegrationHumanSelection.from_mapping(selection.to_dict()) == selection

    verifier, signature = _authority(selection)
    proof = _verify_pilot_integration_human_selection(
        candidate_proof=candidate,
        selection=selection,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:01:00Z",
    )
    assert proof.schema == PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_SCHEMA
    assert proof.authority == PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_AUTHORITY
    assert proof.selection == selection
    assert proof.selection_sha256 == selection.sha256
    assert proof.candidate_proof_sha256 == candidate.sha256
    assert proof.human_selection_recorded is True
    assert proof.candidate_selection_verified is True
    assert proof.integration_ready is False
    assert proof.preflight_observed is False
    assert proof.preflight_satisfied is False
    assert proof.pilot_start_authorized is False
    assert proof.product_pilot_started is False
    assert proof.remote_write_authorized is False
    assert proof.push_authorized is False
    assert proof.pr_mutation_authorized is False
    assert proof.merge_authorized is False
    assert proof.release_authorized is False
    assert proof.deploy_authorized is False
    assert proof.production_activation_authorized is False
    assert PilotIntegrationHumanSelectionProof.from_mapping(proof.to_dict()) == proof

    _reject(lambda: verify_pilot_integration_human_selection(
        candidate_proof=candidate,
        selection=selection,
        signature=signature,
        verifier=verifier,
    ))

    tampered = selection.to_dict()
    tampered["candidate_proof"] = dict(tampered["candidate_proof"])
    tampered["candidate_proof"]["feature_flag_name"] = "KALIV_DEVCONTROL_PILOT_ALT"
    _reject(lambda: PilotIntegrationHumanSelection.from_mapping(tampered))

    alternate = replace(candidate, feature_flag_name="KALIV_DEVCONTROL_PILOT_ALT")
    rebound = build_pilot_integration_human_selection(
        candidate_proof=alternate,
        selection_id="selection-021-alt",
        selection_maker_actor_id="anders",
        selected_at_utc=selection.selected_at_utc,
    )
    _reject(lambda: _verify_pilot_integration_human_selection(
        candidate_proof=alternate,
        selection=rebound,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:01:00Z",
    ))

    wrong_actor_signature = replace(signature, issuer_actor_id="mallory")
    _reject(lambda: _verify_pilot_integration_human_selection(
        candidate_proof=candidate,
        selection=selection,
        signature=wrong_actor_signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:01:00Z",
    ))
    wrong_domain_signature = replace(
        signature,
        issuer_system_id="kaliv-rsi-unrelated-authority-v1",
    )
    _reject(lambda: _verify_pilot_integration_human_selection(
        candidate_proof=candidate,
        selection=selection,
        signature=wrong_domain_signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:01:00Z",
    ))

    for field in (
        "integration_ready", "preflight_observed", "preflight_satisfied",
        "pilot_start_authorized", "product_pilot_started",
        "remote_write_authorized", "push_authorized", "pr_mutation_authorized",
        "merge_authorized", "release_authorized", "deploy_authorized",
        "production_activation_authorized",
    ):
        _reject(lambda field=field: PilotIntegrationHumanSelectionProof.from_mapping({
            **proof.to_dict(),
            field: True,
        }))

    claim_schema = json.loads(CLAIM_SCHEMA.read_text(encoding="utf-8"))
    claim_props = claim_schema["properties"]
    assert claim_props["schema"]["const"] == PILOT_INTEGRATION_HUMAN_SELECTION_SCHEMA
    assert claim_props["human_selection_intent"]["const"] == PILOT_INTEGRATION_HUMAN_SELECTION_INTENT
    assert claim_props["human_selection_recorded"]["const"] is False
    assert claim_props["integration_ready"]["const"] is False
    assert claim_props["pilot_start_authorized"]["const"] is False
    assert claim_props["production_activation_authorized"]["const"] is False
    assert claim_props["authority"]["const"] == PILOT_INTEGRATION_HUMAN_SELECTION_AUTHORITY

    proof_schema = json.loads(PROOF_SCHEMA.read_text(encoding="utf-8"))
    proof_props = proof_schema["properties"]
    assert proof_props["schema"]["const"] == PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_SCHEMA
    assert proof_props["issuer_system_id"]["const"] == PILOT_INTEGRATION_HUMAN_SELECTION_ISSUER_SYSTEM_ID
    assert proof_props["human_selection_recorded"]["const"] is True
    assert proof_props["candidate_selection_verified"]["const"] is True
    assert proof_props["integration_ready"]["const"] is False
    assert proof_props["pilot_start_authorized"]["const"] is False
    assert proof_props["production_activation_authorized"]["const"] is False
    assert proof_props["authority"]["const"] == PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_AUTHORITY

    from rsi_pilot_runtime_preflight_observation_contract import (  # noqa: E402
        run_contract as run_preflight_observation_contract,
    )
    run_preflight_observation_contract()


if __name__ == "__main__":
    run_contract()
