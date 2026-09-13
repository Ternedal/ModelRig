"""Adversarial contract for ADR-DC-017 pilot preflight requirements."""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

import kaliv_dev_control  # noqa: E402
from kaliv_dev_control import catalog  # noqa: E402
from kaliv_dev_control.improvement_pilot_trial_scope import (  # noqa: E402
    PilotTrialScopeProof,
)
import kaliv_dev_control.improvement_pilot_preflight_requirements as preflight  # noqa: E402


def _scope(
    *,
    decision: str = "go",
    local_commits_allowed: bool = False,
    notes: tuple[str, ...] = (),
) -> PilotTrialScopeProof:
    conditional = decision == "go_with_conditions"
    if conditional and not notes:
        notes = ("runtime-preflight-must-remain-local",)
    return PilotTrialScopeProof(
        decision_proof_sha256="1" * 64,
        decision_sha256="2" * 64,
        signature_sha256="3" * 64,
        campaign_id="campaign-001",
        source_task_id="RSI_TASK_001",
        source_task_sha256="4" * 64,
        repository="Ternedal/ModelRig",
        base_sha="5" * 40,
        requested_main_sha="6" * 40,
        decision_id="pilot-decision-001",
        decision_maker_actor_id="human.pilot.authority",
        decision=decision,
        trial_id="pilot-trial-001",
        operator_surface="desktop.control-center",
        selected_pilot_task_id="pilot.task.alpha",
        workspace_root_path_sha256="7" * 64,
        local_commits_allowed=local_commits_allowed,
        decision_notes=notes,
        conditional_go=conditional,
    )


def _expect(fragment: str, fn) -> None:
    try:
        fn()
    except preflight.PilotPreflightRequirementsError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(
            f"expected PilotPreflightRequirementsError containing {fragment!r}"
        )


def _schema_properties() -> set[str]:
    path = (
        ROOT
        / "devcontrol"
        / "schemas"
        / "rsi-pilot-preflight-requirements-v1.schema.json"
    )
    with path.open("r", encoding="utf-8") as handle:
        return set(json.load(handle)["properties"])


def run_contract() -> None:
    assert catalog.modelrig_command_catalog().command_ids == ()

    scope = _scope()
    manifest = preflight.build_pilot_preflight_requirements(scope_proof=scope)
    assert manifest.trial_scope_sha256 == scope.sha256
    assert manifest.decision_proof_sha256 == scope.decision_proof_sha256
    assert manifest.campaign_id == scope.campaign_id
    assert manifest.selected_pilot_task_id == scope.selected_pilot_task_id
    assert manifest.operator_surface == scope.operator_surface
    assert manifest.workspace_root_path_sha256 == scope.workspace_root_path_sha256
    assert manifest.local_commits_allowed is False
    assert manifest.pilot_scope_verified is True

    for value in (
        manifest.feature_flag_off_observation_required,
        manifest.pilot_runtime_verification_required,
        manifest.native_windows_isolation_required,
        manifest.trusted_git_closure_required,
        manifest.kill_switch_prearm_required,
        manifest.restart_revoke_prearm_required,
        manifest.network_write_block_required,
        manifest.credentials_absent_required,
        manifest.unattended_cadence_forbidden,
        manifest.off_state_import_block_required,
        manifest.exact_source_binding_required,
        manifest.receipt_binding_required,
    ):
        assert value is True

    for value in (
        manifest.preflight_observed,
        manifest.preflight_satisfied,
        manifest.pilot_start_authorized,
        manifest.product_pilot_started,
        manifest.remote_write_authorized,
        manifest.push_authorized,
        manifest.pr_mutation_authorized,
        manifest.merge_authorized,
        manifest.release_authorized,
        manifest.deploy_authorized,
        manifest.production_activation_authorized,
    ):
        assert value is False

    assert manifest.authority == "dc-l16-pilot-preflight-requirements-only"

    conditional_scope = _scope(
        decision="go_with_conditions",
        local_commits_allowed=True,
        notes=("only-after-explicit-runtime-proof",),
    )
    conditional = preflight.build_pilot_preflight_requirements(
        scope_proof=conditional_scope
    )
    assert conditional.conditional_go is True
    assert conditional.decision_notes == ("only-after-explicit-runtime-proof",)
    assert conditional.local_commits_allowed is True
    assert conditional.preflight_satisfied is False
    assert conditional.pilot_start_authorized is False

    tampered = manifest.to_dict()
    tampered["preflight_satisfied"] = True
    _expect(
        "authority boundary",
        lambda: preflight.PilotPreflightRequirements.from_mapping(tampered),
    )

    weakened = manifest.to_dict()
    weakened["network_write_block_required"] = False
    _expect(
        "authority boundary",
        lambda: preflight.PilotPreflightRequirements.from_mapping(weakened),
    )

    false_observation = manifest.to_dict()
    false_observation["preflight_observed"] = True
    _expect(
        "authority boundary",
        lambda: preflight.PilotPreflightRequirements.from_mapping(false_observation),
    )

    stripped = conditional.to_dict()
    stripped["decision_notes"] = []
    _expect(
        "conditional GO must preserve explicit decision notes",
        lambda: preflight.PilotPreflightRequirements.from_mapping(stripped),
    )

    missing = manifest.to_dict()
    del missing["receipt_binding_required"]
    _expect(
        "fields mismatch",
        lambda: preflight.PilotPreflightRequirements.from_mapping(missing),
    )

    _expect(
        "exact PilotTrialScopeProof",
        lambda: preflight.build_pilot_preflight_requirements(scope_proof=object()),
    )

    assert _schema_properties() == set(manifest.to_dict())

    root_source = inspect.getsource(kaliv_dev_control)
    assert "improvement_pilot_preflight_requirements" not in root_source
    source = inspect.getsource(preflight).lower()
    for forbidden in (
        "os.environ",
        "pathlib",
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
