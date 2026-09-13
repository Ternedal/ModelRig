"""Adversarial contract for ADR-DC-016 inert single-trial scope projection."""
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
from kaliv_dev_control.improvement_human_pilot_decision import (  # noqa: E402
    HUMAN_PILOT_DECISION_ISSUER_SYSTEM_ID,
    HumanPilotDecisionProof,
)
import kaliv_dev_control.improvement_pilot_trial_scope as scope  # noqa: E402


def _proof(
    *,
    decision: str = "go",
    local_commits_allowed: bool = False,
    notes: tuple[str, ...] = (),
) -> HumanPilotDecisionProof:
    go = decision in {"go", "go_with_conditions"}
    if decision in {"go_with_conditions", "no_go"} and not notes:
        notes = ("explicit-condition-or-reason",)
    return HumanPilotDecisionProof(
        decision_sha256="1" * 64,
        signature_sha256="2" * 64,
        key_id="pilot-key-001",
        issuer_actor_id="human.pilot.authority",
        issuer_system_id=HUMAN_PILOT_DECISION_ISSUER_SYSTEM_ID,
        completion_proof_sha256="3" * 64,
        campaign_id="campaign-001",
        task_id="RSI_TASK_001",
        task_sha256="4" * 64,
        repository="Ternedal/ModelRig",
        base_sha="5" * 40,
        requested_main_sha="6" * 40,
        decision_id="pilot-decision-001",
        decision_maker_actor_id="human.pilot.authority",
        decision=decision,
        operator_surface="desktop.control-center",
        allowed_task_ids=("pilot.task.alpha", "pilot.task.beta"),
        workspace_root_path_sha256="7" * 64,
        local_commits_allowed=local_commits_allowed,
        notes=notes,
        decided_at_utc="2026-09-13T20:00:00Z",
        verified_at_utc="2026-09-13T20:01:00Z",
        pilot_go_authorized=go,
    )


def _project(
    proof: HumanPilotDecisionProof,
    **overrides,
):
    values = {
        "decision_proof": proof,
        "trial_id": "pilot-trial-001",
        "selected_pilot_task_id": "pilot.task.alpha",
        "operator_surface": "desktop.control-center",
        "workspace_root_path_sha256": "7" * 64,
        "local_commits_requested": False,
    }
    values.update(overrides)
    return scope.project_single_pilot_trial_scope(**values)


def _expect(fragment: str, fn) -> None:
    try:
        fn()
    except scope.PilotTrialScopeError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(f"expected PilotTrialScopeError containing {fragment!r}")


def _schema_properties() -> set[str]:
    path = ROOT / "devcontrol" / "schemas" / "rsi-pilot-trial-scope-proof-v1.schema.json"
    with path.open("r", encoding="utf-8") as handle:
        return set(json.load(handle)["properties"])


def run_contract() -> None:
    assert catalog.modelrig_command_catalog().command_ids == ()

    proof = _proof()
    projected = _project(proof)
    assert projected.decision_proof_sha256 == proof.sha256
    assert projected.decision_sha256 == proof.decision_sha256
    assert projected.signature_sha256 == proof.signature_sha256
    assert projected.selected_pilot_task_id == "pilot.task.alpha"
    assert projected.operator_surface == proof.operator_surface
    assert projected.workspace_root_path_sha256 == proof.workspace_root_path_sha256
    assert projected.local_commits_allowed is False
    assert projected.human_pilot_go_verified is True
    assert projected.conditional_go is False
    assert projected.feature_flag_default_off is True
    assert projected.local_only_scope_confirmed is True
    assert projected.kill_switch_required is True
    assert projected.restart_revoke_required is True
    assert projected.unattended_cadence_allowed is False
    assert projected.remote_write_authorized is False
    assert projected.push_authorized is False
    assert projected.pr_mutation_authorized is False
    assert projected.merge_authorized is False
    assert projected.release_authorized is False
    assert projected.deploy_authorized is False
    assert projected.production_activation_authorized is False
    assert projected.pilot_scope_verified is True
    assert projected.pilot_runtime_verified is False
    assert projected.feature_flag_off_observed is False
    assert projected.pilot_start_authorized is False
    assert projected.product_pilot_started is False
    assert projected.authority == "verified-dc-l16-single-trial-scope-only"

    conditional = _project(
        _proof(
            decision="go_with_conditions",
            local_commits_allowed=True,
            notes=("only-after-local-runtime-preflight",),
        ),
        local_commits_requested=True,
    )
    assert conditional.conditional_go is True
    assert conditional.decision_notes == ("only-after-local-runtime-preflight",)
    assert conditional.local_commits_allowed is True
    assert conditional.pilot_start_authorized is False

    stripped = conditional.to_dict()
    stripped["decision_notes"] = []
    _expect(
        "conditional GO must preserve explicit decision notes",
        lambda: scope.PilotTrialScopeProof.from_mapping(stripped),
    )

    narrowed = _project(
        _proof(local_commits_allowed=True),
        local_commits_requested=False,
    )
    assert narrowed.local_commits_allowed is False

    _expect("positive non-starting GO", lambda: _project(_proof(decision="no_go")))
    _expect(
        "not in the human allowlist",
        lambda: _project(proof, selected_pilot_task_id="pilot.task.gamma"),
    )
    _expect(
        "operator surface",
        lambda: _project(proof, operator_surface="cli"),
    )
    _expect(
        "workspace differs",
        lambda: _project(proof, workspace_root_path_sha256="8" * 64),
    )
    _expect(
        "local commit authority exceeds",
        lambda: _project(proof, local_commits_requested=True),
    )

    escalated = projected.to_dict()
    escalated["pilot_start_authorized"] = True
    _expect("authority boundary", lambda: scope.PilotTrialScopeProof.from_mapping(escalated))

    runtime_claim = projected.to_dict()
    runtime_claim["pilot_runtime_verified"] = True
    _expect("authority boundary", lambda: scope.PilotTrialScopeProof.from_mapping(runtime_claim))

    flag_claim = projected.to_dict()
    flag_claim["feature_flag_off_observed"] = True
    _expect("authority boundary", lambda: scope.PilotTrialScopeProof.from_mapping(flag_claim))

    assert _schema_properties() == set(projected.to_dict())

    root_source = inspect.getsource(kaliv_dev_control)
    assert "improvement_pilot_trial_scope" not in root_source
    source = inspect.getsource(scope)
    for forbidden in (
        "tier_a_execution",
        "subprocess",
        "git push",
        "merge_pull_request",
        "production_activation=true",
    ):
        assert forbidden not in source.lower(), forbidden


if __name__ == "__main__":
    run_contract()
