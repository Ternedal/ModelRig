"""Inert requirements manifest for a future DC-L16 pilot preflight.

The manifest is derived only from an already verified ADR-DC-016 single-trial
scope.  It describes checks that a later, separately authorized runtime
preflight must prove.  It performs no host observation, reads no feature flag,
registers no command, starts no pilot, and grants no execution authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .improvement_pilot_trial_scope import (
    PILOT_TRIAL_SCOPE_AUTHORITY,
    PilotTrialScopeProof,
)

PILOT_PREFLIGHT_REQUIREMENTS_SCHEMA = (
    "kaliv-rsi-dc-l16-pilot-preflight-requirements/v1"
)
PILOT_PREFLIGHT_REQUIREMENTS_AUTHORITY = (
    "dc-l16-pilot-preflight-requirements-only"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ALLOWED_DECISIONS = {"go", "go_with_conditions"}

_FIELDS = {
    "schema",
    "trial_scope_sha256",
    "decision_proof_sha256",
    "campaign_id",
    "source_task_id",
    "source_task_sha256",
    "repository",
    "base_sha",
    "requested_main_sha",
    "decision_id",
    "decision",
    "trial_id",
    "operator_surface",
    "selected_pilot_task_id",
    "workspace_root_path_sha256",
    "local_commits_allowed",
    "decision_notes",
    "conditional_go",
    "pilot_scope_verified",
    "feature_flag_off_observation_required",
    "pilot_runtime_verification_required",
    "native_windows_isolation_required",
    "trusted_git_closure_required",
    "kill_switch_prearm_required",
    "restart_revoke_prearm_required",
    "network_write_block_required",
    "credentials_absent_required",
    "unattended_cadence_forbidden",
    "off_state_import_block_required",
    "exact_source_binding_required",
    "receipt_binding_required",
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
    "authority",
}


class PilotPreflightRequirementsError(ValueError):
    """The preflight requirements manifest is malformed or over-authorizing."""


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
        raise PilotPreflightRequirementsError(
            "pilot preflight requirements are not canonical JSON"
        ) from exc


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotPreflightRequirementsError(f"{name} is invalid")
    return value


def _hex(value: Any, *, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PilotPreflightRequirementsError(f"{name} is invalid")
    return value


def _notes(value: Any) -> tuple[str, ...]:
    if not isinstance(value, tuple) or len(value) > 32:
        raise PilotPreflightRequirementsError("decision_notes are invalid")
    for item in value:
        if (
            not isinstance(item, str)
            or not item
            or item.strip() != item
            or "\0" in item
            or len(item.encode("utf-8")) > 4096
        ):
            raise PilotPreflightRequirementsError("decision_notes are invalid")
    return value


def _strict(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _FIELDS:
        raise PilotPreflightRequirementsError(
            "pilot preflight requirements fields mismatch"
        )
    return value


def _require_inert_scope(value: Any) -> PilotTrialScopeProof:
    if type(value) is not PilotTrialScopeProof:
        raise PilotPreflightRequirementsError("exact PilotTrialScopeProof is required")
    if (
        value.authority != PILOT_TRIAL_SCOPE_AUTHORITY
        or value.decision not in _ALLOWED_DECISIONS
        or value.human_pilot_go_verified is not True
        or value.pilot_scope_verified is not True
        or value.pilot_runtime_verified is not False
        or value.feature_flag_off_observed is not False
        or value.pilot_start_authorized is not False
        or value.product_pilot_started is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotPreflightRequirementsError(
            "pilot trial scope is not an inert verified DC-L16 scope"
        )
    return value


@dataclass(frozen=True, slots=True)
class PilotPreflightRequirements:
    trial_scope_sha256: str
    decision_proof_sha256: str
    campaign_id: str
    source_task_id: str
    source_task_sha256: str
    repository: str
    base_sha: str
    requested_main_sha: str
    decision_id: str
    decision: str
    trial_id: str
    operator_surface: str
    selected_pilot_task_id: str
    workspace_root_path_sha256: str
    local_commits_allowed: bool
    decision_notes: tuple[str, ...]
    conditional_go: bool
    pilot_scope_verified: bool = True
    feature_flag_off_observation_required: bool = True
    pilot_runtime_verification_required: bool = True
    native_windows_isolation_required: bool = True
    trusted_git_closure_required: bool = True
    kill_switch_prearm_required: bool = True
    restart_revoke_prearm_required: bool = True
    network_write_block_required: bool = True
    credentials_absent_required: bool = True
    unattended_cadence_forbidden: bool = True
    off_state_import_block_required: bool = True
    exact_source_binding_required: bool = True
    receipt_binding_required: bool = True
    preflight_observed: bool = False
    preflight_satisfied: bool = False
    pilot_start_authorized: bool = False
    product_pilot_started: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_PREFLIGHT_REQUIREMENTS_AUTHORITY
    schema: str = PILOT_PREFLIGHT_REQUIREMENTS_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_PREFLIGHT_REQUIREMENTS_SCHEMA:
            raise PilotPreflightRequirementsError(
                "pilot preflight requirements schema is unsupported"
            )
        for name, value, pattern in (
            ("trial_scope_sha256", self.trial_scope_sha256, _HEX64),
            ("decision_proof_sha256", self.decision_proof_sha256, _HEX64),
            ("source_task_sha256", self.source_task_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("requested_main_sha", self.requested_main_sha, _HEX40),
            ("workspace_root_path_sha256", self.workspace_root_path_sha256, _HEX64),
        ):
            _hex(value, name=name, pattern=pattern)
        for name, value in (
            ("campaign_id", self.campaign_id),
            ("decision_id", self.decision_id),
            ("trial_id", self.trial_id),
            ("operator_surface", self.operator_surface),
            ("selected_pilot_task_id", self.selected_pilot_task_id),
        ):
            _identifier(value, name=name)
        if not isinstance(self.source_task_id, str) or not 1 <= len(self.source_task_id) <= 64:
            raise PilotPreflightRequirementsError("source_task_id is invalid")
        if self.repository != "Ternedal/ModelRig":
            raise PilotPreflightRequirementsError("repository is unsupported")
        if self.decision not in _ALLOWED_DECISIONS:
            raise PilotPreflightRequirementsError(
                "preflight requirements require a positive human GO decision"
            )
        if type(self.local_commits_allowed) is not bool:
            raise PilotPreflightRequirementsError(
                "local_commits_allowed must be boolean"
            )
        notes = _notes(self.decision_notes)
        expected_conditional = self.decision == "go_with_conditions"
        if self.conditional_go is not expected_conditional:
            raise PilotPreflightRequirementsError("conditional GO state is invalid")
        if expected_conditional and not notes:
            raise PilotPreflightRequirementsError(
                "conditional GO must preserve explicit decision notes"
            )
        required_true = (
            self.pilot_scope_verified,
            self.feature_flag_off_observation_required,
            self.pilot_runtime_verification_required,
            self.native_windows_isolation_required,
            self.trusted_git_closure_required,
            self.kill_switch_prearm_required,
            self.restart_revoke_prearm_required,
            self.network_write_block_required,
            self.credentials_absent_required,
            self.unattended_cadence_forbidden,
            self.off_state_import_block_required,
            self.exact_source_binding_required,
            self.receipt_binding_required,
        )
        required_false = (
            self.preflight_observed,
            self.preflight_satisfied,
            self.pilot_start_authorized,
            self.product_pilot_started,
            self.remote_write_authorized,
            self.push_authorized,
            self.pr_mutation_authorized,
            self.merge_authorized,
            self.release_authorized,
            self.deploy_authorized,
            self.production_activation_authorized,
        )
        if (
            any(value is not True for value in required_true)
            or any(value is not False for value in required_false)
            or self.authority != PILOT_PREFLIGHT_REQUIREMENTS_AUTHORITY
        ):
            raise PilotPreflightRequirementsError(
                "pilot preflight requirements authority boundary is invalid"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotPreflightRequirements":
        data = dict(_strict(value))
        notes = data.get("decision_notes")
        if not isinstance(notes, list):
            raise PilotPreflightRequirementsError("decision_notes must be an array")
        data["decision_notes"] = tuple(notes)
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "trial_scope_sha256": self.trial_scope_sha256,
            "decision_proof_sha256": self.decision_proof_sha256,
            "campaign_id": self.campaign_id,
            "source_task_id": self.source_task_id,
            "source_task_sha256": self.source_task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "requested_main_sha": self.requested_main_sha,
            "decision_id": self.decision_id,
            "decision": self.decision,
            "trial_id": self.trial_id,
            "operator_surface": self.operator_surface,
            "selected_pilot_task_id": self.selected_pilot_task_id,
            "workspace_root_path_sha256": self.workspace_root_path_sha256,
            "local_commits_allowed": self.local_commits_allowed,
            "decision_notes": list(self.decision_notes),
            "conditional_go": self.conditional_go,
            "pilot_scope_verified": self.pilot_scope_verified,
            "feature_flag_off_observation_required": self.feature_flag_off_observation_required,
            "pilot_runtime_verification_required": self.pilot_runtime_verification_required,
            "native_windows_isolation_required": self.native_windows_isolation_required,
            "trusted_git_closure_required": self.trusted_git_closure_required,
            "kill_switch_prearm_required": self.kill_switch_prearm_required,
            "restart_revoke_prearm_required": self.restart_revoke_prearm_required,
            "network_write_block_required": self.network_write_block_required,
            "credentials_absent_required": self.credentials_absent_required,
            "unattended_cadence_forbidden": self.unattended_cadence_forbidden,
            "off_state_import_block_required": self.off_state_import_block_required,
            "exact_source_binding_required": self.exact_source_binding_required,
            "receipt_binding_required": self.receipt_binding_required,
            "preflight_observed": self.preflight_observed,
            "preflight_satisfied": self.preflight_satisfied,
            "pilot_start_authorized": self.pilot_start_authorized,
            "product_pilot_started": self.product_pilot_started,
            "remote_write_authorized": self.remote_write_authorized,
            "push_authorized": self.push_authorized,
            "pr_mutation_authorized": self.pr_mutation_authorized,
            "merge_authorized": self.merge_authorized,
            "release_authorized": self.release_authorized,
            "deploy_authorized": self.deploy_authorized,
            "production_activation_authorized": self.production_activation_authorized,
            "authority": self.authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def build_pilot_preflight_requirements(
    *, scope_proof: PilotTrialScopeProof
) -> PilotPreflightRequirements:
    """Derive immutable future-preflight requirements from one inert trial scope."""
    proof = _require_inert_scope(scope_proof)
    return PilotPreflightRequirements(
        trial_scope_sha256=proof.sha256,
        decision_proof_sha256=proof.decision_proof_sha256,
        campaign_id=proof.campaign_id,
        source_task_id=proof.source_task_id,
        source_task_sha256=proof.source_task_sha256,
        repository=proof.repository,
        base_sha=proof.base_sha,
        requested_main_sha=proof.requested_main_sha,
        decision_id=proof.decision_id,
        decision=proof.decision,
        trial_id=proof.trial_id,
        operator_surface=proof.operator_surface,
        selected_pilot_task_id=proof.selected_pilot_task_id,
        workspace_root_path_sha256=proof.workspace_root_path_sha256,
        local_commits_allowed=proof.local_commits_allowed,
        decision_notes=proof.decision_notes,
        conditional_go=proof.conditional_go,
    )


__all__ = [
    "PILOT_PREFLIGHT_REQUIREMENTS_SCHEMA",
    "PILOT_PREFLIGHT_REQUIREMENTS_AUTHORITY",
    "PilotPreflightRequirementsError",
    "PilotPreflightRequirements",
    "build_pilot_preflight_requirements",
]
