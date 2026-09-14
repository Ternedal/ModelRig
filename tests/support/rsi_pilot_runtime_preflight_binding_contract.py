"""Adversarial contract for ADR-DC-022 inert runtime-preflight binding."""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control.improvement_pilot_integration_human_selection import (  # noqa: E402
    _verify_pilot_integration_human_selection,
    build_pilot_integration_human_selection,
)
from kaliv_dev_control.improvement_pilot_preflight_requirements import (  # noqa: E402
    build_pilot_preflight_requirements,
)
from kaliv_dev_control.improvement_pilot_runtime_preflight_binding import (  # noqa: E402
    PILOT_RUNTIME_PREFLIGHT_BINDING_AUTHORITY,
    PILOT_RUNTIME_PREFLIGHT_BINDING_SCHEMA,
    PilotRuntimePreflightBindingError,
    PilotRuntimePreflightBindingPlan,
    bind_pilot_runtime_preflight,
)
from rsi_pilot_integration_human_selection_contract import (  # noqa: E402
    _authority,
    _candidate,
    _scope,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-runtime-preflight-binding-plan-v1.schema.json"
)


def _reject(callable_) -> None:
    try:
        callable_()
    except PilotRuntimePreflightBindingError:
        return
    raise AssertionError("runtime preflight binding unexpectedly accepted invalid input")


def _evidence():
    scope = _scope()
    requirements = build_pilot_preflight_requirements(scope_proof=scope)
    candidate = _candidate()
    assert candidate.trial_scope_sha256 == scope.sha256
    selection = build_pilot_integration_human_selection(
        candidate_proof=candidate,
        selection_id="selection-022",
        selection_maker_actor_id="anders",
        selected_at_utc="2026-09-14T08:10:00Z",
        notes=("Bind this exact selected candidate to preflight requirements.",),
    )
    verifier, signature = _authority(selection)
    proof = _verify_pilot_integration_human_selection(
        candidate_proof=candidate,
        selection=selection,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:11:00Z",
    )
    return requirements, proof


def run_contract() -> None:
    requirements, selection_proof = _evidence()
    plan = bind_pilot_runtime_preflight(
        requirements=requirements,
        human_selection_proof=selection_proof,
    )
    candidate = selection_proof.selection.candidate_proof

    assert plan.schema == PILOT_RUNTIME_PREFLIGHT_BINDING_SCHEMA
    assert plan.authority == PILOT_RUNTIME_PREFLIGHT_BINDING_AUTHORITY
    assert plan.requirements == requirements
    assert plan.human_selection_proof == selection_proof
    assert plan.requirements_sha256 == requirements.sha256
    assert plan.human_selection_proof_sha256 == selection_proof.sha256
    assert plan.operator_surface == requirements.operator_surface
    assert plan.operator_surface == candidate.operator_surface
    assert plan.selected_pilot_task_id == candidate.selected_pilot_task_id
    assert plan.workspace_root_path_sha256 == candidate.workspace_root_path_sha256
    assert plan.feature_flag_name == candidate.feature_flag_name
    assert plan.product_route == candidate.product_route
    assert plan.runtime_observer_id == candidate.runtime_observer_id
    assert plan.task_registry_id == candidate.task_registry_id
    assert plan.workspace_policy_id == candidate.workspace_policy_id
    assert plan.review_authorization_roles_id == candidate.review_authorization_roles_id
    assert plan.kill_revoke_cleanup_id == candidate.kill_revoke_cleanup_id
    assert plan.local_commit_policy == candidate.local_commit_policy
    assert plan.preflight_requirements_verified is True
    assert plan.human_selection_recorded is True
    assert plan.candidate_selection_verified is True
    assert plan.preflight_binding_verified is True
    assert plan.integration_ready is False
    assert plan.preflight_observed is False
    assert plan.preflight_satisfied is False
    assert plan.pilot_start_authorized is False
    assert plan.product_pilot_started is False
    assert plan.remote_write_authorized is False
    assert plan.push_authorized is False
    assert plan.pr_mutation_authorized is False
    assert plan.merge_authorized is False
    assert plan.release_authorized is False
    assert plan.deploy_authorized is False
    assert plan.production_activation_authorized is False
    assert len(plan.sha256) == 64
    assert PilotRuntimePreflightBindingPlan.from_mapping(plan.to_dict()) == plan

    wrong_surface = replace(requirements, operator_surface="android.control-center")
    _reject(lambda: bind_pilot_runtime_preflight(
        requirements=wrong_surface,
        human_selection_proof=selection_proof,
    ))

    wrong_main = replace(requirements, requested_main_sha="f" * 40)
    _reject(lambda: bind_pilot_runtime_preflight(
        requirements=wrong_main,
        human_selection_proof=selection_proof,
    ))

    wrong_local_commit_scope = replace(requirements, local_commits_allowed=True)
    _reject(lambda: bind_pilot_runtime_preflight(
        requirements=wrong_local_commit_scope,
        human_selection_proof=selection_proof,
    ))

    _reject(lambda: PilotRuntimePreflightBindingPlan.from_mapping({
        **plan.to_dict(),
        "requirements_sha256": "f" * 64,
    }))
    _reject(lambda: PilotRuntimePreflightBindingPlan.from_mapping({
        **plan.to_dict(),
        "human_selection_proof_sha256": "e" * 64,
    }))
    _reject(lambda: PilotRuntimePreflightBindingPlan.from_mapping({
        **plan.to_dict(),
        "feature_flag_name": "KALIV_DEVCONTROL_REBOUND",
    }))

    for field in (
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
        _reject(lambda field=field: PilotRuntimePreflightBindingPlan.from_mapping({
            **plan.to_dict(),
            field: True,
        }))

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    properties = schema["properties"]
    assert properties["schema"]["const"] == PILOT_RUNTIME_PREFLIGHT_BINDING_SCHEMA
    assert properties["preflight_requirements_verified"]["const"] is True
    assert properties["human_selection_recorded"]["const"] is True
    assert properties["candidate_selection_verified"]["const"] is True
    assert properties["preflight_binding_verified"]["const"] is True
    assert properties["integration_ready"]["const"] is False
    assert properties["preflight_observed"]["const"] is False
    assert properties["preflight_satisfied"]["const"] is False
    assert properties["pilot_start_authorized"]["const"] is False
    assert properties["product_pilot_started"]["const"] is False
    assert properties["production_activation_authorized"]["const"] is False
    assert properties["authority"]["const"] == PILOT_RUNTIME_PREFLIGHT_BINDING_AUTHORITY


if __name__ == "__main__":
    run_contract()
