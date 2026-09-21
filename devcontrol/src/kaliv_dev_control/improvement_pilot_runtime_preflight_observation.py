"""Exact-bound, non-authorizing DC-L16 runtime-preflight observation packet.

ADR-DC-022 binds twelve evidence digests to one verified ADR-DC-021 human
product-integration selection and one exact ADR-DC-017 requirements manifest.
It performs no host I/O and deliberately does *not* claim that any evidence has
been independently verified.  A later host-controlled verifier must do that.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .improvement_pilot_integration_human_selection import (
    PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_AUTHORITY,
    PilotIntegrationHumanSelectionProof,
)
from .improvement_pilot_preflight_requirements import (
    PILOT_PREFLIGHT_REQUIREMENTS_AUTHORITY,
    PilotPreflightRequirements,
)

PILOT_RUNTIME_PREFLIGHT_OBSERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-runtime-preflight-observation-packet/v1"
)
PILOT_RUNTIME_PREFLIGHT_OBSERVATION_AUTHORITY = (
    "dc-l16-runtime-preflight-observation-packet-only"
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")

_EVIDENCE_FIELDS = (
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

_FIELDS = {
    "schema",
    "selection_proof",
    "selection_proof_sha256",
    "preflight_requirements",
    "preflight_requirements_sha256",
    "observation_id",
    "observer_actor_id",
    "observed_at_utc",
    *_EVIDENCE_FIELDS,
    "observation_set_complete",
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
    "authority",
}


class PilotRuntimePreflightObservationError(ValueError):
    """Observation packet is malformed, rebound or over-authorizing."""


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
        raise PilotRuntimePreflightObservationError(
            "runtime preflight observation packet is not canonical JSON"
        ) from exc


def _strict(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _FIELDS:
        raise PilotRuntimePreflightObservationError(
            "runtime preflight observation packet fields mismatch"
        )
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise PilotRuntimePreflightObservationError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotRuntimePreflightObservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PilotRuntimePreflightObservationError(f"{name} is invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise PilotRuntimePreflightObservationError(f"{name} is invalid") from exc
    if parsed.tzinfo != timezone.utc or parsed.microsecond != 0:
        raise PilotRuntimePreflightObservationError(f"{name} must be canonical UTC seconds")
    return parsed


def _require_selection(
    value: Any,
) -> PilotIntegrationHumanSelectionProof:
    if type(value) is not PilotIntegrationHumanSelectionProof:
        raise PilotRuntimePreflightObservationError(
            "exact PilotIntegrationHumanSelectionProof is required"
        )
    if (
        value.authority != PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_AUTHORITY
        or value.human_selection_recorded is not True
        or value.candidate_selection_verified is not True
        or value.integration_ready is not False
        or value.preflight_observed is not False
        or value.preflight_satisfied is not False
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
        raise PilotRuntimePreflightObservationError(
            "human integration selection proof authority boundary is invalid"
        )
    return value


def _require_requirements(value: Any) -> PilotPreflightRequirements:
    if type(value) is not PilotPreflightRequirements:
        raise PilotRuntimePreflightObservationError(
            "exact PilotPreflightRequirements is required"
        )
    required = (
        value.pilot_scope_verified,
        value.feature_flag_off_observation_required,
        value.pilot_runtime_verification_required,
        value.native_windows_isolation_required,
        value.trusted_git_closure_required,
        value.kill_switch_prearm_required,
        value.restart_revoke_prearm_required,
        value.network_write_block_required,
        value.credentials_absent_required,
        value.unattended_cadence_forbidden,
        value.off_state_import_block_required,
        value.exact_source_binding_required,
        value.receipt_binding_required,
    )
    if (
        value.authority != PILOT_PREFLIGHT_REQUIREMENTS_AUTHORITY
        or any(item is not True for item in required)
        or value.preflight_observed is not False
        or value.preflight_satisfied is not False
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
        raise PilotRuntimePreflightObservationError(
            "pilot preflight requirements authority boundary is invalid"
        )
    return value


def _require_same_scope(
    *,
    selection: PilotIntegrationHumanSelectionProof,
    requirements: PilotPreflightRequirements,
) -> None:
    candidate = selection.selection.candidate_proof
    checks = (
        ("trial_scope_sha256", candidate.trial_scope_sha256, requirements.trial_scope_sha256),
        ("decision_proof_sha256", candidate.decision_proof_sha256, requirements.decision_proof_sha256),
        ("repository", candidate.repository, requirements.repository),
        ("base_sha", candidate.base_sha, requirements.base_sha),
        ("requested_main_sha", candidate.requested_main_sha, requirements.requested_main_sha),
        ("trial_id", candidate.trial_id, requirements.trial_id),
        ("operator_surface", candidate.operator_surface, requirements.operator_surface),
        ("selected_pilot_task_id", candidate.selected_pilot_task_id, requirements.selected_pilot_task_id),
        ("workspace_root_path_sha256", candidate.workspace_root_path_sha256, requirements.workspace_root_path_sha256),
        ("local_commits_allowed", candidate.local_commits_allowed, requirements.local_commits_allowed),
    )
    mismatch = next((name for name, left, right in checks if left != right), None)
    if mismatch is not None:
        raise PilotRuntimePreflightObservationError(
            f"selection/preflight scope binding mismatch: {mismatch}"
        )
    expected_policy = "allow-local-only" if requirements.local_commits_allowed else "forbid"
    if candidate.local_commit_policy != expected_policy:
        raise PilotRuntimePreflightObservationError(
            "selection/preflight local commit policy mismatch"
        )


@dataclass(frozen=True, slots=True)
class PilotRuntimePreflightObservationPacket:
    selection_proof: PilotIntegrationHumanSelectionProof
    selection_proof_sha256: str
    preflight_requirements: PilotPreflightRequirements
    preflight_requirements_sha256: str
    observation_id: str
    observer_actor_id: str
    observed_at_utc: str
    feature_flag_off_evidence_sha256: str
    pilot_runtime_evidence_sha256: str
    native_windows_isolation_evidence_sha256: str
    trusted_git_closure_evidence_sha256: str
    kill_switch_prearm_evidence_sha256: str
    restart_revoke_prearm_evidence_sha256: str
    network_write_block_evidence_sha256: str
    credentials_absent_evidence_sha256: str
    unattended_cadence_evidence_sha256: str
    off_state_import_block_evidence_sha256: str
    exact_source_binding_evidence_sha256: str
    receipt_binding_evidence_sha256: str
    observation_set_complete: bool = True
    evidence_verified: bool = False
    integration_ready: bool = False
    preflight_observed: bool = False
    preflight_satisfied: bool = False
    pilot_start_authorized: bool = False
    product_pilot_started: bool = False
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_RUNTIME_PREFLIGHT_OBSERVATION_AUTHORITY
    schema: str = PILOT_RUNTIME_PREFLIGHT_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_RUNTIME_PREFLIGHT_OBSERVATION_SCHEMA:
            raise PilotRuntimePreflightObservationError(
                "runtime preflight observation packet schema is unsupported"
            )
        selection = _require_selection(self.selection_proof)
        requirements = _require_requirements(self.preflight_requirements)
        _hex64(self.selection_proof_sha256, name="selection_proof_sha256")
        _hex64(self.preflight_requirements_sha256, name="preflight_requirements_sha256")
        if self.selection_proof_sha256 != selection.sha256:
            raise PilotRuntimePreflightObservationError("selection proof hash mismatch")
        if self.preflight_requirements_sha256 != requirements.sha256:
            raise PilotRuntimePreflightObservationError("preflight requirements hash mismatch")
        _require_same_scope(selection=selection, requirements=requirements)
        _identifier(self.observation_id, name="observation_id")
        _identifier(self.observer_actor_id, name="observer_actor_id")
        observed = _utc(self.observed_at_utc, name="observed_at_utc")
        verified_selection_at = _utc(
            selection.verified_at_utc,
            name="selection verified_at_utc",
        )
        if observed < verified_selection_at:
            raise PilotRuntimePreflightObservationError(
                "runtime preflight observation predates verified human selection"
            )
        for name in _EVIDENCE_FIELDS:
            _hex64(getattr(self, name), name=name)
        if (
            self.observation_set_complete is not True
            or self.evidence_verified is not False
            or self.integration_ready is not False
            or self.preflight_observed is not False
            or self.preflight_satisfied is not False
            or self.pilot_start_authorized is not False
            or self.product_pilot_started is not False
            or self.local_commit_authorized is not False
            or self.remote_write_authorized is not False
            or self.push_authorized is not False
            or self.pr_mutation_authorized is not False
            or self.merge_authorized is not False
            or self.release_authorized is not False
            or self.deploy_authorized is not False
            or self.production_activation_authorized is not False
            or self.authority != PILOT_RUNTIME_PREFLIGHT_OBSERVATION_AUTHORITY
        ):
            raise PilotRuntimePreflightObservationError(
                "runtime preflight observation packet authority boundary is invalid"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotRuntimePreflightObservationPacket":
        data = dict(_strict(value))
        selection = data.get("selection_proof")
        requirements = data.get("preflight_requirements")
        if not isinstance(selection, Mapping):
            raise PilotRuntimePreflightObservationError("selection proof is invalid")
        if not isinstance(requirements, Mapping):
            raise PilotRuntimePreflightObservationError("preflight requirements are invalid")
        data["selection_proof"] = PilotIntegrationHumanSelectionProof.from_mapping(selection)
        data["preflight_requirements"] = PilotPreflightRequirements.from_mapping(requirements)
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "selection_proof": self.selection_proof.to_dict(),
            "selection_proof_sha256": self.selection_proof_sha256,
            "preflight_requirements": self.preflight_requirements.to_dict(),
            "preflight_requirements_sha256": self.preflight_requirements_sha256,
            "observation_id": self.observation_id,
            "observer_actor_id": self.observer_actor_id,
            "observed_at_utc": self.observed_at_utc,
            **{name: getattr(self, name) for name in _EVIDENCE_FIELDS},
            "observation_set_complete": self.observation_set_complete,
            "evidence_verified": self.evidence_verified,
            "integration_ready": self.integration_ready,
            "preflight_observed": self.preflight_observed,
            "preflight_satisfied": self.preflight_satisfied,
            "pilot_start_authorized": self.pilot_start_authorized,
            "product_pilot_started": self.product_pilot_started,
            "local_commit_authorized": self.local_commit_authorized,
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


def build_pilot_runtime_preflight_observation_packet(
    *,
    selection_proof: PilotIntegrationHumanSelectionProof,
    preflight_requirements: PilotPreflightRequirements,
    observation_id: str,
    observer_actor_id: str,
    observed_at_utc: str,
    evidence_sha256: Mapping[str, str],
) -> PilotRuntimePreflightObservationPacket:
    """Bind a complete evidence-digest set without verifying host truth."""
    selection = _require_selection(selection_proof)
    requirements = _require_requirements(preflight_requirements)
    _require_same_scope(selection=selection, requirements=requirements)
    if not isinstance(evidence_sha256, Mapping) or set(evidence_sha256) != set(_EVIDENCE_FIELDS):
        raise PilotRuntimePreflightObservationError(
            "runtime preflight evidence digest set mismatch"
        )
    return PilotRuntimePreflightObservationPacket(
        selection_proof=selection,
        selection_proof_sha256=selection.sha256,
        preflight_requirements=requirements,
        preflight_requirements_sha256=requirements.sha256,
        observation_id=observation_id,
        observer_actor_id=observer_actor_id,
        observed_at_utc=observed_at_utc,
        **{name: evidence_sha256[name] for name in _EVIDENCE_FIELDS},
    )


__all__ = [
    "PILOT_RUNTIME_PREFLIGHT_OBSERVATION_SCHEMA",
    "PILOT_RUNTIME_PREFLIGHT_OBSERVATION_AUTHORITY",
    "PilotRuntimePreflightObservationError",
    "PilotRuntimePreflightObservationPacket",
    "build_pilot_runtime_preflight_observation_packet",
]
