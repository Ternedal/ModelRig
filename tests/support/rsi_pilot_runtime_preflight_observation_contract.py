"""Adversarial contract for ADR-DC-022 runtime-preflight observation packet."""
from __future__ import annotations

import hashlib
import inspect
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))

import kaliv_dev_control  # noqa: E402
from kaliv_dev_control import catalog  # noqa: E402
from kaliv_dev_control.improvement_pilot_integration_human_selection import (  # noqa: E402
    _verify_pilot_integration_human_selection,
    build_pilot_integration_human_selection,
)
from kaliv_dev_control.improvement_pilot_preflight_requirements import (  # noqa: E402
    build_pilot_preflight_requirements,
)
import kaliv_dev_control.improvement_pilot_runtime_preflight_observation as observation  # noqa: E402
from rsi_pilot_integration_human_selection_contract import (  # noqa: E402
    _authority,
    _candidate,
    _scope,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-runtime-preflight-observation-packet-v1.schema.json"
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
        selection_id="selection-022",
        selection_maker_actor_id="anders",
        selected_at_utc="2026-09-14T08:00:00Z",
        notes=("Exact candidate only.",),
    )
    verifier, signature = _authority(selection)
    return _verify_pilot_integration_human_selection(
        candidate_proof=candidate,
        selection=selection,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:01:00Z",
    )


def _evidence() -> dict[str, str]:
    return {
        name: hashlib.sha256(("adr-dc-022:" + name).encode("utf-8")).hexdigest()
        for name in EVIDENCE_FIELDS
    }


def _packet():
    proof = _selection_proof()
    requirements = build_pilot_preflight_requirements(scope_proof=_scope())
    return observation.build_pilot_runtime_preflight_observation_packet(
        selection_proof=proof,
        preflight_requirements=requirements,
        observation_id="preflight-observation-022",
        observer_actor_id="runtime.observer",
        observed_at_utc="2026-09-14T08:02:00Z",
        evidence_sha256=_evidence(),
    )


def _reject(fragment: str, fn) -> None:
    try:
        fn()
    except observation.PilotRuntimePreflightObservationError as exc:
        assert fragment in str(exc), str(exc)
        return
    raise AssertionError(f"ADR-DC-022 unexpectedly accepted invalid input: {fragment}")


def run_contract() -> None:
    assert catalog.modelrig_command_catalog().command_ids == ()

    packet = _packet()
    assert packet.schema == observation.PILOT_RUNTIME_PREFLIGHT_OBSERVATION_SCHEMA
    assert packet.authority == observation.PILOT_RUNTIME_PREFLIGHT_OBSERVATION_AUTHORITY
    assert packet.selection_proof_sha256 == packet.selection_proof.sha256
    assert packet.preflight_requirements_sha256 == packet.preflight_requirements.sha256
    assert packet.observation_set_complete is True
    assert packet.evidence_verified is False
    assert packet.integration_ready is False
    assert packet.preflight_observed is False
    assert packet.preflight_satisfied is False
    assert packet.pilot_start_authorized is False
    assert packet.product_pilot_started is False
    assert packet.local_commit_authorized is False
    assert packet.remote_write_authorized is False
    assert packet.push_authorized is False
    assert packet.pr_mutation_authorized is False
    assert packet.merge_authorized is False
    assert packet.release_authorized is False
    assert packet.deploy_authorized is False
    assert packet.production_activation_authorized is False
    assert observation.PilotRuntimePreflightObservationPacket.from_mapping(
        packet.to_dict()
    ) == packet

    candidate = packet.selection_proof.selection.candidate_proof
    requirements = packet.preflight_requirements
    assert candidate.trial_scope_sha256 == requirements.trial_scope_sha256
    assert candidate.operator_surface == requirements.operator_surface
    assert candidate.selected_pilot_task_id == requirements.selected_pilot_task_id
    assert candidate.workspace_root_path_sha256 == requirements.workspace_root_path_sha256
    assert candidate.local_commits_allowed == requirements.local_commits_allowed

    missing_evidence = _evidence()
    del missing_evidence["receipt_binding_evidence_sha256"]
    _reject(
        "evidence digest set mismatch",
        lambda: observation.build_pilot_runtime_preflight_observation_packet(
            selection_proof=packet.selection_proof,
            preflight_requirements=packet.preflight_requirements,
            observation_id="preflight-observation-022",
            observer_actor_id="runtime.observer",
            observed_at_utc="2026-09-14T08:02:00Z",
            evidence_sha256=missing_evidence,
        ),
    )

    invalid_digest = _evidence()
    invalid_digest["network_write_block_evidence_sha256"] = "not-a-digest"
    _reject(
        "network_write_block_evidence_sha256 is invalid",
        lambda: observation.build_pilot_runtime_preflight_observation_packet(
            selection_proof=packet.selection_proof,
            preflight_requirements=packet.preflight_requirements,
            observation_id="preflight-observation-022",
            observer_actor_id="runtime.observer",
            observed_at_utc="2026-09-14T08:02:00Z",
            evidence_sha256=invalid_digest,
        ),
    )

    rebound_requirements = replace(
        packet.preflight_requirements,
        workspace_root_path_sha256="f" * 64,
    )
    _reject(
        "workspace_root_path_sha256",
        lambda: observation.build_pilot_runtime_preflight_observation_packet(
            selection_proof=packet.selection_proof,
            preflight_requirements=rebound_requirements,
            observation_id="preflight-observation-022",
            observer_actor_id="runtime.observer",
            observed_at_utc="2026-09-14T08:02:00Z",
            evidence_sha256=_evidence(),
        ),
    )

    _reject(
        "predates verified human selection",
        lambda: observation.build_pilot_runtime_preflight_observation_packet(
            selection_proof=packet.selection_proof,
            preflight_requirements=packet.preflight_requirements,
            observation_id="preflight-observation-022",
            observer_actor_id="runtime.observer",
            observed_at_utc="2026-09-14T07:59:59Z",
            evidence_sha256=_evidence(),
        ),
    )

    for field in (
        "evidence_verified",
        "integration_ready",
        "preflight_observed",
        "preflight_satisfied",
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
            "authority boundary",
            lambda field=field: observation.PilotRuntimePreflightObservationPacket.from_mapping(
                {**packet.to_dict(), field: True}
            ),
        )

    tampered_selection = packet.to_dict()
    tampered_selection["selection_proof"] = dict(tampered_selection["selection_proof"])
    tampered_selection["selection_proof"]["candidate_proof_sha256"] = "f" * 64
    try:
        observation.PilotRuntimePreflightObservationPacket.from_mapping(tampered_selection)
    except ValueError:
        pass
    else:
        raise AssertionError("tampered ADR-DC-021 selection proof was accepted")

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    properties = schema["properties"]
    assert set(properties) == set(packet.to_dict())
    assert properties["schema"]["const"] == observation.PILOT_RUNTIME_PREFLIGHT_OBSERVATION_SCHEMA
    assert properties["observation_set_complete"]["const"] is True
    for field in (
        "evidence_verified",
        "integration_ready",
        "preflight_observed",
        "preflight_satisfied",
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
        assert properties[field]["const"] is False, field
    assert properties["authority"]["const"] == observation.PILOT_RUNTIME_PREFLIGHT_OBSERVATION_AUTHORITY

    root_source = inspect.getsource(kaliv_dev_control)
    assert "improvement_pilot_runtime_preflight_observation" not in root_source
    source = inspect.getsource(observation).lower()
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
