"""Inert single-trial scope projection for a future DC-L16 pilot.

This module can only narrow an already verified positive human pilot decision.
It does not inspect product runtime state, enable a feature flag, register a
command, execute a task, or authorize pilot start.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .improvement_human_pilot_decision import (
    HUMAN_PILOT_DECISION_PROOF_AUTHORITY,
    HumanPilotDecisionProof,
)

PILOT_TRIAL_SCOPE_SCHEMA = "kaliv-rsi-dc-l16-single-trial-scope-proof/v1"
PILOT_TRIAL_SCOPE_AUTHORITY = "verified-dc-l16-single-trial-scope-only"

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ALLOWED_DECISIONS = {"go", "go_with_conditions"}

_FIELDS = {
    "schema",
    "decision_proof_sha256",
    "decision_sha256",
    "signature_sha256",
    "campaign_id",
    "source_task_id",
    "source_task_sha256",
    "repository",
    "base_sha",
    "requested_main_sha",
    "decision_id",
    "decision_maker_actor_id",
    "decision",
    "trial_id",
    "operator_surface",
    "selected_pilot_task_id",
    "workspace_root_path_sha256",
    "local_commits_allowed",
    "decision_notes",
    "human_pilot_go_verified",
    "conditional_go",
    "feature_flag_default_off",
    "local_only_scope_confirmed",
    "kill_switch_required",
    "restart_revoke_required",
    "unattended_cadence_allowed",
    "remote_write_authorized",
    "push_authorized",
    "pr_mutation_authorized",
    "merge_authorized",
    "release_authorized",
    "deploy_authorized",
    "production_activation_authorized",
    "pilot_scope_verified",
    "pilot_runtime_verified",
    "feature_flag_off_observed",
    "pilot_start_authorized",
    "product_pilot_started",
    "authority",
}


class PilotTrialScopeError(ValueError):
    """The requested trial scope is invalid or broader than human authority."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PilotTrialScopeError("pilot trial scope is not canonical JSON") from exc


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotTrialScopeError(f"{name} is invalid")
    return value


def _hex(value: Any, *, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PilotTrialScopeError(f"{name} is invalid")
    return value


def _notes(value: Any) -> tuple[str, ...]:
    if not isinstance(value, tuple) or len(value) > 32:
        raise PilotTrialScopeError("decision_notes are invalid")
    for item in value:
        if (
            not isinstance(item, str)
            or not item
            or item.strip() != item
            or "\0" in item
            or len(item.encode("utf-8")) > 4096
        ):
            raise PilotTrialScopeError("decision_notes are invalid")
    return value


def _strict(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _FIELDS:
        raise PilotTrialScopeError("pilot trial scope proof fields mismatch")
    return value


def _require_positive_human_decision(value: Any) -> HumanPilotDecisionProof:
    if type(value) is not HumanPilotDecisionProof:
        raise PilotTrialScopeError("exact HumanPilotDecisionProof is required")
    if (
        value.authority != HUMAN_PILOT_DECISION_PROOF_AUTHORITY
        or value.human_pilot_decision_recorded is not True
        or value.decision not in _ALLOWED_DECISIONS
        or value.pilot_go_authorized is not True
        or value.product_pilot_started is not False
        or value.feature_flag_default_off is not True
        or value.remote_write_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotTrialScopeError(
            "human pilot decision proof is not a positive non-starting GO authority"
        )
    return value


@dataclass(frozen=True, slots=True)
class PilotTrialScopeProof:
    decision_proof_sha256: str
    decision_sha256: str
    signature_sha256: str
    campaign_id: str
    source_task_id: str
    source_task_sha256: str
    repository: str
    base_sha: str
    requested_main_sha: str
    decision_id: str
    decision_maker_actor_id: str
    decision: str
    trial_id: str
    operator_surface: str
    selected_pilot_task_id: str
    workspace_root_path_sha256: str
    local_commits_allowed: bool
    decision_notes: tuple[str, ...]
    human_pilot_go_verified: bool = True
    conditional_go: bool = False
    feature_flag_default_off: bool = True
    local_only_scope_confirmed: bool = True
    kill_switch_required: bool = True
    restart_revoke_required: bool = True
    unattended_cadence_allowed: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    pilot_scope_verified: bool = True
    pilot_runtime_verified: bool = False
    feature_flag_off_observed: bool = False
    pilot_start_authorized: bool = False
    product_pilot_started: bool = False
    authority: str = PILOT_TRIAL_SCOPE_AUTHORITY
    schema: str = PILOT_TRIAL_SCOPE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_TRIAL_SCOPE_SCHEMA:
            raise PilotTrialScopeError("pilot trial scope proof schema is unsupported")
        for name, value, pattern in (
            ("decision_proof_sha256", self.decision_proof_sha256, _HEX64),
            ("decision_sha256", self.decision_sha256, _HEX64),
            ("signature_sha256", self.signature_sha256, _HEX64),
            ("source_task_sha256", self.source_task_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("requested_main_sha", self.requested_main_sha, _HEX40),
            ("workspace_root_path_sha256", self.workspace_root_path_sha256, _HEX64),
        ):
            _hex(value, name=name, pattern=pattern)
        for name, value in (
            ("campaign_id", self.campaign_id),
            ("decision_id", self.decision_id),
            ("decision_maker_actor_id", self.decision_maker_actor_id),
            ("trial_id", self.trial_id),
            ("operator_surface", self.operator_surface),
            ("selected_pilot_task_id", self.selected_pilot_task_id),
        ):
            _identifier(value, name=name)
        if not isinstance(self.source_task_id, str) or not 1 <= len(self.source_task_id) <= 64:
            raise PilotTrialScopeError("source_task_id is invalid")
        if self.repository != "Ternedal/ModelRig":
            raise PilotTrialScopeError("repository is unsupported")
        if self.decision not in _ALLOWED_DECISIONS:
            raise PilotTrialScopeError("scope proof requires a positive human GO decision")
        if type(self.local_commits_allowed) is not bool:
            raise PilotTrialScopeError("local_commits_allowed must be boolean")
        notes = _notes(self.decision_notes)
        expected_conditional = self.decision == "go_with_conditions"
        if expected_conditional and not notes:
            raise PilotTrialScopeError("conditional GO must preserve explicit decision notes")
        if (
            self.human_pilot_go_verified is not True
            or self.conditional_go is not expected_conditional
            or self.feature_flag_default_off is not True
            or self.local_only_scope_confirmed is not True
            or self.kill_switch_required is not True
            or self.restart_revoke_required is not True
            or self.unattended_cadence_allowed is not False
            or self.remote_write_authorized is not False
            or self.push_authorized is not False
            or self.pr_mutation_authorized is not False
            or self.merge_authorized is not False
            or self.release_authorized is not False
            or self.deploy_authorized is not False
            or self.production_activation_authorized is not False
            or self.pilot_scope_verified is not True
            or self.pilot_runtime_verified is not False
            or self.feature_flag_off_observed is not False
            or self.pilot_start_authorized is not False
            or self.product_pilot_started is not False
            or self.authority != PILOT_TRIAL_SCOPE_AUTHORITY
        ):
            raise PilotTrialScopeError("pilot trial scope proof authority boundary is invalid")

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotTrialScopeProof":
        data = dict(_strict(value))
        notes = data.get("decision_notes")
        if not isinstance(notes, list):
            raise PilotTrialScopeError("decision_notes must be an array")
        data["decision_notes"] = tuple(notes)
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "decision_proof_sha256": self.decision_proof_sha256,
            "decision_sha256": self.decision_sha256,
            "signature_sha256": self.signature_sha256,
            "campaign_id": self.campaign_id,
            "source_task_id": self.source_task_id,
            "source_task_sha256": self.source_task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "requested_main_sha": self.requested_main_sha,
            "decision_id": self.decision_id,
            "decision_maker_actor_id": self.decision_maker_actor_id,
            "decision": self.decision,
            "trial_id": self.trial_id,
            "operator_surface": self.operator_surface,
            "selected_pilot_task_id": self.selected_pilot_task_id,
            "workspace_root_path_sha256": self.workspace_root_path_sha256,
            "local_commits_allowed": self.local_commits_allowed,
            "decision_notes": list(self.decision_notes),
            "human_pilot_go_verified": self.human_pilot_go_verified,
            "conditional_go": self.conditional_go,
            "feature_flag_default_off": self.feature_flag_default_off,
            "local_only_scope_confirmed": self.local_only_scope_confirmed,
            "kill_switch_required": self.kill_switch_required,
            "restart_revoke_required": self.restart_revoke_required,
            "unattended_cadence_allowed": self.unattended_cadence_allowed,
            "remote_write_authorized": self.remote_write_authorized,
            "push_authorized": self.push_authorized,
            "pr_mutation_authorized": self.pr_mutation_authorized,
            "merge_authorized": self.merge_authorized,
            "release_authorized": self.release_authorized,
            "deploy_authorized": self.deploy_authorized,
            "production_activation_authorized": self.production_activation_authorized,
            "pilot_scope_verified": self.pilot_scope_verified,
            "pilot_runtime_verified": self.pilot_runtime_verified,
            "feature_flag_off_observed": self.feature_flag_off_observed,
            "pilot_start_authorized": self.pilot_start_authorized,
            "product_pilot_started": self.product_pilot_started,
            "authority": self.authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def project_single_pilot_trial_scope(
    *,
    decision_proof: HumanPilotDecisionProof,
    trial_id: str,
    selected_pilot_task_id: str,
    operator_surface: str,
    workspace_root_path_sha256: str,
    local_commits_requested: bool,
) -> PilotTrialScopeProof:
    """Narrow one positive human decision to one inert trial scope."""
    proof = _require_positive_human_decision(decision_proof)
    _identifier(trial_id, name="trial_id")
    _identifier(selected_pilot_task_id, name="selected_pilot_task_id")
    _identifier(operator_surface, name="operator_surface")
    _hex(
        workspace_root_path_sha256,
        name="workspace_root_path_sha256",
        pattern=_HEX64,
    )
    if type(local_commits_requested) is not bool:
        raise PilotTrialScopeError("local_commits_requested must be boolean")
    if operator_surface != proof.operator_surface:
        raise PilotTrialScopeError("pilot operator surface exceeds or differs from human scope")
    if workspace_root_path_sha256 != proof.workspace_root_path_sha256:
        raise PilotTrialScopeError("pilot workspace differs from human scope")
    if selected_pilot_task_id not in proof.allowed_task_ids:
        raise PilotTrialScopeError("pilot task is not in the human allowlist")
    if local_commits_requested and not proof.local_commits_allowed:
        raise PilotTrialScopeError("local commit authority exceeds the human decision")
    return PilotTrialScopeProof(
        decision_proof_sha256=proof.sha256,
        decision_sha256=proof.decision_sha256,
        signature_sha256=proof.signature_sha256,
        campaign_id=proof.campaign_id,
        source_task_id=proof.task_id,
        source_task_sha256=proof.task_sha256,
        repository=proof.repository,
        base_sha=proof.base_sha,
        requested_main_sha=proof.requested_main_sha,
        decision_id=proof.decision_id,
        decision_maker_actor_id=proof.decision_maker_actor_id,
        decision=proof.decision,
        trial_id=trial_id,
        operator_surface=operator_surface,
        selected_pilot_task_id=selected_pilot_task_id,
        workspace_root_path_sha256=workspace_root_path_sha256,
        local_commits_allowed=local_commits_requested,
        decision_notes=proof.notes,
        conditional_go=proof.decision == "go_with_conditions",
    )


__all__ = [
    "PILOT_TRIAL_SCOPE_SCHEMA",
    "PILOT_TRIAL_SCOPE_AUTHORITY",
    "PilotTrialScopeError",
    "PilotTrialScopeProof",
    "project_single_pilot_trial_scope",
]
