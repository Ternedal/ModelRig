"""Adversarial contract for ADR-DC-020 inert product integration selection candidates."""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control.improvement_pilot_integration_selection_candidate import (  # noqa: E402
    INVENTORY_GIT_BLOB_SHA,
    INVENTORY_SOURCE_HEAD_SHA,
    PILOT_INTEGRATION_SELECTION_CANDIDATE_AUTHORITY,
    PILOT_INTEGRATION_SELECTION_CANDIDATE_SCHEMA,
    SELECTION_REQUIREMENTS_GIT_BLOB_SHA,
    PilotIntegrationSelectionCandidateError,
    PilotIntegrationSelectionCandidateProof,
    validate_pilot_integration_selection_candidate,
)
from kaliv_dev_control.improvement_pilot_trial_scope import (  # noqa: E402
    PilotTrialScopeProof,
)

INVENTORY = ROOT / "docs" / "devcontrol" / "dc-l16" / "product-integration-inventory.json"
REQUIREMENTS = ROOT / "docs" / "devcontrol" / "dc-l16" / "product-integration-selection-requirements.json"
SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-product-integration-selection-candidate-proof-v1.schema.json"


def _scope(*, surface: str = "desktop.control-center", local_commits: bool = False) -> PilotTrialScopeProof:
    return PilotTrialScopeProof(
        decision_proof_sha256="1" * 64,
        decision_sha256="2" * 64,
        signature_sha256="3" * 64,
        campaign_id="campaign-020",
        source_task_id="source-task",
        source_task_sha256="4" * 64,
        repository="Ternedal/ModelRig",
        base_sha="5" * 40,
        requested_main_sha="6" * 40,
        decision_id="decision-020",
        decision_maker_actor_id="anders",
        decision="go",
        trial_id="trial-020",
        operator_surface=surface,
        selected_pilot_task_id="task-local-001",
        workspace_root_path_sha256="7" * 64,
        local_commits_allowed=local_commits,
        decision_notes=(),
    )


def _candidate(*, scope: PilotTrialScopeProof | None = None, local_policy: str = "forbid") -> PilotIntegrationSelectionCandidateProof:
    return validate_pilot_integration_selection_candidate(
        scope_proof=scope or _scope(),
        inventory_bytes=INVENTORY.read_bytes(),
        selection_requirements_bytes=REQUIREMENTS.read_bytes(),
        feature_flag_name="KALIV_DEVCONTROL_PILOT_ENABLED",
        product_route="/api/v1/devcontrol/pilot",
        runtime_observer_id="devcontrol.runtime-observer.v1",
        task_registry_id="devcontrol.pilot-registry.v1",
        workspace_policy_id="devcontrol.workspace-local.v1",
        review_authorization_roles_id="devcontrol.review-roles.v1",
        kill_revoke_cleanup_id="devcontrol.kill-revoke-cleanup.v1",
        local_commit_policy=local_policy,
    )


def _reject(callable_) -> None:
    try:
        callable_()
    except PilotIntegrationSelectionCandidateError:
        return
    raise AssertionError("candidate validation unexpectedly accepted invalid input")


def run_contract() -> None:
    proof = _candidate()
    assert proof.schema == PILOT_INTEGRATION_SELECTION_CANDIDATE_SCHEMA
    assert proof.authority == PILOT_INTEGRATION_SELECTION_CANDIDATE_AUTHORITY
    assert proof.inventory_source_head_sha == INVENTORY_SOURCE_HEAD_SHA
    assert proof.inventory_git_blob_sha == INVENTORY_GIT_BLOB_SHA
    assert proof.selection_requirements_git_blob_sha == SELECTION_REQUIREMENTS_GIT_BLOB_SHA
    assert proof.operator_surface == "desktop.control-center"
    assert proof.candidate_id == proof.operator_surface
    assert proof.candidate_path.endswith("ControlCenterDialog.kt")
    assert proof.feature_flag_name == "KALIV_DEVCONTROL_PILOT_ENABLED"
    assert proof.product_route == "/api/v1/devcontrol/pilot"
    assert proof.local_commit_policy == "forbid"
    assert proof.human_pilot_go_verified is True
    assert proof.pilot_scope_verified is True
    assert proof.source_inventory_verified is True
    assert proof.selection_requirements_verified is True
    assert proof.design_candidate_validated is True
    assert proof.human_selection_recorded is False
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
    assert len(proof.sha256) == 64
    assert PilotIntegrationSelectionCandidateProof.from_mapping(proof.to_dict()) == proof

    local = _candidate(scope=_scope(local_commits=True), local_policy="allow-local-only")
    assert local.local_commits_allowed is True
    assert local.local_commit_policy == "allow-local-only"

    stale_inventory = INVENTORY.read_bytes() + b"\n"
    _reject(lambda: validate_pilot_integration_selection_candidate(
        scope_proof=_scope(),
        inventory_bytes=stale_inventory,
        selection_requirements_bytes=REQUIREMENTS.read_bytes(),
        feature_flag_name="KALIV_DEVCONTROL_PILOT_ENABLED",
        product_route="/api/v1/devcontrol/pilot",
        runtime_observer_id="devcontrol.runtime-observer.v1",
        task_registry_id="devcontrol.pilot-registry.v1",
        workspace_policy_id="devcontrol.workspace-local.v1",
        review_authorization_roles_id="devcontrol.review-roles.v1",
        kill_revoke_cleanup_id="devcontrol.kill-revoke-cleanup.v1",
        local_commit_policy="forbid",
    ))

    _reject(lambda: _candidate(scope=_scope(surface="custom.future.surface")))
    _reject(lambda: _candidate(scope=_scope(local_commits=False), local_policy="allow-local-only"))

    for forbidden_flag in ("KALIV_AGENT3_ENABLED", "KALIV_AGENT4_OPERATOR_API"):
        _reject(lambda flag=forbidden_flag: validate_pilot_integration_selection_candidate(
            scope_proof=_scope(),
            inventory_bytes=INVENTORY.read_bytes(),
            selection_requirements_bytes=REQUIREMENTS.read_bytes(),
            feature_flag_name=flag,
            product_route="/api/v1/devcontrol/pilot",
            runtime_observer_id="devcontrol.runtime-observer.v1",
            task_registry_id="devcontrol.pilot-registry.v1",
            workspace_policy_id="devcontrol.workspace-local.v1",
            review_authorization_roles_id="devcontrol.review-roles.v1",
            kill_revoke_cleanup_id="devcontrol.kill-revoke-cleanup.v1",
            local_commit_policy="forbid",
        ))

    _reject(lambda: validate_pilot_integration_selection_candidate(
        scope_proof=_scope(),
        inventory_bytes=INVENTORY.read_bytes(),
        selection_requirements_bytes=REQUIREMENTS.read_bytes(),
        feature_flag_name="KALIV_DEVCONTROL_PILOT_ENABLED",
        product_route="/api/v1/control-center/status",
        runtime_observer_id="devcontrol.runtime-observer.v1",
        task_registry_id="devcontrol.pilot-registry.v1",
        workspace_policy_id="devcontrol.workspace-local.v1",
        review_authorization_roles_id="devcontrol.review-roles.v1",
        kill_revoke_cleanup_id="devcontrol.kill-revoke-cleanup.v1",
        local_commit_policy="forbid",
    ))

    for field in (
        "human_selection_recorded",
        "integration_ready",
        "preflight_observed",
        "preflight_satisfied",
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
        _reject(lambda field=field: PilotIntegrationSelectionCandidateProof.from_mapping({
            **proof.to_dict(), field: True,
        }))

    _reject(lambda: PilotIntegrationSelectionCandidateProof.from_mapping({
        **proof.to_dict(), "candidate_git_blob_sha": "f" * 40,
    }))

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    properties = schema["properties"]
    assert properties["schema"]["const"] == PILOT_INTEGRATION_SELECTION_CANDIDATE_SCHEMA
    assert properties["inventory_source_head_sha"]["const"] == INVENTORY_SOURCE_HEAD_SHA
    assert properties["inventory_git_blob_sha"]["const"] == INVENTORY_GIT_BLOB_SHA
    assert properties["selection_requirements_git_blob_sha"]["const"] == SELECTION_REQUIREMENTS_GIT_BLOB_SHA
    assert properties["human_selection_recorded"]["const"] is False
    assert properties["integration_ready"]["const"] is False
    assert properties["pilot_start_authorized"]["const"] is False
    assert properties["production_activation_authorized"]["const"] is False
    assert properties["authority"]["const"] == PILOT_INTEGRATION_SELECTION_CANDIDATE_AUTHORITY


if __name__ == "__main__":
    run_contract()
