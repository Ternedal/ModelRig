"""Inert binding plan between verified human integration selection and runtime preflight.

ADR-DC-022 binds exact ADR-DC-017 preflight requirements to one verified
ADR-DC-021 human product-integration selection.  It does not inspect the host,
read a feature flag, register a command, satisfy preflight or start DC-L16.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .improvement_pilot_integration_human_selection import (
    PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_AUTHORITY,
    PilotIntegrationHumanSelectionProof,
)
from .improvement_pilot_preflight_requirements import (
    PILOT_PREFLIGHT_REQUIREMENTS_AUTHORITY,
    PilotPreflightRequirements,
)

PILOT_RUNTIME_PREFLIGHT_BINDING_SCHEMA = (
    "kaliv-rsi-dc-l16-runtime-preflight-binding-plan/v1"
)
PILOT_RUNTIME_PREFLIGHT_BINDING_AUTHORITY = (
    "dc-l16-runtime-preflight-binding-plan-only"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")

_FIELDS = {
    "schema",
    "requirements_sha256",
    "human_selection_proof_sha256",
    "requirements",
    "human_selection_proof",
    "repository",
    "base_sha",
    "requested_main_sha",
    "trial_id",
    "operator_surface",
    "selected_pilot_task_id",
    "workspace_root_path_sha256",
    "local_commits_allowed",
    "feature_flag_name",
    "product_route",
    "runtime_observer_id",
    "task_registry_id",
    "workspace_policy_id",
    "review_authorization_roles_id",
    "kill_revoke_cleanup_id",
    "local_commit_policy",
    "preflight_requirements_verified",
    "human_selection_recorded",
    "candidate_selection_verified",
    "preflight_binding_verified",
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
    "authority",
}


class PilotRuntimePreflightBindingError(ValueError):
    """The runtime-preflight binding is malformed, mismatched or over-authorizing."""


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
        raise PilotRuntimePreflightBindingError(
            "runtime preflight binding is not canonical JSON"
        ) from exc


def _strict(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _FIELDS:
        raise PilotRuntimePreflightBindingError(
            "runtime preflight binding fields mismatch"
        )
    return value


def _hex(value: Any, *, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PilotRuntimePreflightBindingError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotRuntimePreflightBindingError(f"{name} is invalid")
    return value


def _require_requirements(value: Any) -> PilotPreflightRequirements:
    if type(value) is not PilotPreflightRequirements:
        raise PilotRuntimePreflightBindingError(
            "exact PilotPreflightRequirements is required"
        )
    if (
        value.authority != PILOT_PREFLIGHT_REQUIREMENTS_AUTHORITY
        or value.pilot_scope_verified is not True
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
        raise PilotRuntimePreflightBindingError(
            "preflight requirements are not inert verified requirements"
        )
    try:
        replayed = PilotPreflightRequirements.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotRuntimePreflightBindingError(
            "preflight requirements replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotRuntimePreflightBindingError(
            "preflight requirements replay identity mismatch"
        )
    return value


def _require_selection(
    value: Any,
) -> PilotIntegrationHumanSelectionProof:
    if type(value) is not PilotIntegrationHumanSelectionProof:
        raise PilotRuntimePreflightBindingError(
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
        raise PilotRuntimePreflightBindingError(
            "human integration selection is not inert verified evidence"
        )
    try:
        replayed = PilotIntegrationHumanSelectionProof.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotRuntimePreflightBindingError(
            "human selection proof replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotRuntimePreflightBindingError(
            "human selection proof replay identity mismatch"
        )
    return value


def _verify_cross_binding(
    requirements: PilotPreflightRequirements,
    selection_proof: PilotIntegrationHumanSelectionProof,
) -> None:
    candidate = selection_proof.selection.candidate_proof
    pairs = (
        ("trial_scope_sha256", requirements.trial_scope_sha256, candidate.trial_scope_sha256),
        ("decision_proof_sha256", requirements.decision_proof_sha256, candidate.decision_proof_sha256),
        ("repository", requirements.repository, candidate.repository),
        ("base_sha", requirements.base_sha, candidate.base_sha),
        ("requested_main_sha", requirements.requested_main_sha, candidate.requested_main_sha),
        ("trial_id", requirements.trial_id, candidate.trial_id),
        ("operator_surface", requirements.operator_surface, candidate.operator_surface),
        (
            "selected_pilot_task_id",
            requirements.selected_pilot_task_id,
            candidate.selected_pilot_task_id,
        ),
        (
            "workspace_root_path_sha256",
            requirements.workspace_root_path_sha256,
            candidate.workspace_root_path_sha256,
        ),
        (
            "local_commits_allowed",
            requirements.local_commits_allowed,
            candidate.local_commits_allowed,
        ),
    )
    for name, left, right in pairs:
        if left != right:
            raise PilotRuntimePreflightBindingError(
                f"preflight/selection scope mismatch: {name}"
            )
    expected_policy = (
        "allow-local-only" if requirements.local_commits_allowed else "forbid"
    )
    if candidate.local_commit_policy != expected_policy:
        raise PilotRuntimePreflightBindingError(
            "selection local commit policy does not match preflight scope"
        )


@dataclass(frozen=True, slots=True)
class PilotRuntimePreflightBindingPlan:
    requirements_sha256: str
    human_selection_proof_sha256: str
    requirements: PilotPreflightRequirements
    human_selection_proof: PilotIntegrationHumanSelectionProof
    repository: str
    base_sha: str
    requested_main_sha: str
    trial_id: str
    operator_surface: str
    selected_pilot_task_id: str
    workspace_root_path_sha256: str
    local_commits_allowed: bool
    feature_flag_name: str
    product_route: str
    runtime_observer_id: str
    task_registry_id: str
    workspace_policy_id: str
    review_authorization_roles_id: str
    kill_revoke_cleanup_id: str
    local_commit_policy: str
    preflight_requirements_verified: bool = True
    human_selection_recorded: bool = True
    candidate_selection_verified: bool = True
    preflight_binding_verified: bool = True
    integration_ready: bool = False
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
    authority: str = PILOT_RUNTIME_PREFLIGHT_BINDING_AUTHORITY
    schema: str = PILOT_RUNTIME_PREFLIGHT_BINDING_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_RUNTIME_PREFLIGHT_BINDING_SCHEMA:
            raise PilotRuntimePreflightBindingError(
                "runtime preflight binding schema is unsupported"
            )
        requirements = _require_requirements(self.requirements)
        selection = _require_selection(self.human_selection_proof)
        _verify_cross_binding(requirements, selection)
        _hex(self.requirements_sha256, name="requirements_sha256", pattern=_HEX64)
        _hex(
            self.human_selection_proof_sha256,
            name="human_selection_proof_sha256",
            pattern=_HEX64,
        )
        if self.requirements_sha256 != requirements.sha256:
            raise PilotRuntimePreflightBindingError(
                "preflight requirements hash mismatch"
            )
        if self.human_selection_proof_sha256 != selection.sha256:
            raise PilotRuntimePreflightBindingError(
                "human selection proof hash mismatch"
            )

        candidate = selection.selection.candidate_proof
        expected = {
            "repository": requirements.repository,
            "base_sha": requirements.base_sha,
            "requested_main_sha": requirements.requested_main_sha,
            "trial_id": requirements.trial_id,
            "operator_surface": requirements.operator_surface,
            "selected_pilot_task_id": requirements.selected_pilot_task_id,
            "workspace_root_path_sha256": requirements.workspace_root_path_sha256,
            "local_commits_allowed": requirements.local_commits_allowed,
            "feature_flag_name": candidate.feature_flag_name,
            "product_route": candidate.product_route,
            "runtime_observer_id": candidate.runtime_observer_id,
            "task_registry_id": candidate.task_registry_id,
            "workspace_policy_id": candidate.workspace_policy_id,
            "review_authorization_roles_id": candidate.review_authorization_roles_id,
            "kill_revoke_cleanup_id": candidate.kill_revoke_cleanup_id,
            "local_commit_policy": candidate.local_commit_policy,
        }
        for name, value in expected.items():
            if getattr(self, name) != value:
                raise PilotRuntimePreflightBindingError(
                    f"runtime preflight binding drift: {name}"
                )

        if self.repository != "Ternedal/ModelRig":
            raise PilotRuntimePreflightBindingError("repository is unsupported")
        for name, value, pattern in (
            ("base_sha", self.base_sha, _HEX40),
            ("requested_main_sha", self.requested_main_sha, _HEX40),
            ("workspace_root_path_sha256", self.workspace_root_path_sha256, _HEX64),
        ):
            _hex(value, name=name, pattern=pattern)
        for name, value in (
            ("trial_id", self.trial_id),
            ("operator_surface", self.operator_surface),
            ("selected_pilot_task_id", self.selected_pilot_task_id),
            ("runtime_observer_id", self.runtime_observer_id),
            ("task_registry_id", self.task_registry_id),
            ("workspace_policy_id", self.workspace_policy_id),
            ("review_authorization_roles_id", self.review_authorization_roles_id),
            ("kill_revoke_cleanup_id", self.kill_revoke_cleanup_id),
        ):
            _identifier(value, name=name)
        if type(self.local_commits_allowed) is not bool:
            raise PilotRuntimePreflightBindingError(
                "local_commits_allowed must be boolean"
            )

        required_true = (
            self.preflight_requirements_verified,
            self.human_selection_recorded,
            self.candidate_selection_verified,
            self.preflight_binding_verified,
        )
        required_false = (
            self.integration_ready,
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
            or self.authority != PILOT_RUNTIME_PREFLIGHT_BINDING_AUTHORITY
        ):
            raise PilotRuntimePreflightBindingError(
                "runtime preflight binding authority boundary is invalid"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotRuntimePreflightBindingPlan":
        data = dict(_strict(value))
        if not isinstance(data.get("requirements"), Mapping):
            raise PilotRuntimePreflightBindingError(
                "embedded preflight requirements are invalid"
            )
        if not isinstance(data.get("human_selection_proof"), Mapping):
            raise PilotRuntimePreflightBindingError(
                "embedded human selection proof is invalid"
            )
        data["requirements"] = PilotPreflightRequirements.from_mapping(
            data["requirements"]
        )
        data["human_selection_proof"] = (
            PilotIntegrationHumanSelectionProof.from_mapping(
                data["human_selection_proof"]
            )
        )
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "requirements_sha256": self.requirements_sha256,
            "human_selection_proof_sha256": self.human_selection_proof_sha256,
            "requirements": self.requirements.to_dict(),
            "human_selection_proof": self.human_selection_proof.to_dict(),
            "repository": self.repository,
            "base_sha": self.base_sha,
            "requested_main_sha": self.requested_main_sha,
            "trial_id": self.trial_id,
            "operator_surface": self.operator_surface,
            "selected_pilot_task_id": self.selected_pilot_task_id,
            "workspace_root_path_sha256": self.workspace_root_path_sha256,
            "local_commits_allowed": self.local_commits_allowed,
            "feature_flag_name": self.feature_flag_name,
            "product_route": self.product_route,
            "runtime_observer_id": self.runtime_observer_id,
            "task_registry_id": self.task_registry_id,
            "workspace_policy_id": self.workspace_policy_id,
            "review_authorization_roles_id": self.review_authorization_roles_id,
            "kill_revoke_cleanup_id": self.kill_revoke_cleanup_id,
            "local_commit_policy": self.local_commit_policy,
            "preflight_requirements_verified": self.preflight_requirements_verified,
            "human_selection_recorded": self.human_selection_recorded,
            "candidate_selection_verified": self.candidate_selection_verified,
            "preflight_binding_verified": self.preflight_binding_verified,
            "integration_ready": self.integration_ready,
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


def bind_pilot_runtime_preflight(
    *,
    requirements: PilotPreflightRequirements,
    human_selection_proof: PilotIntegrationHumanSelectionProof,
) -> PilotRuntimePreflightBindingPlan:
    """Bind exact verified selection evidence to exact inert preflight requirements."""
    checked_requirements = _require_requirements(requirements)
    checked_selection = _require_selection(human_selection_proof)
    _verify_cross_binding(checked_requirements, checked_selection)
    candidate = checked_selection.selection.candidate_proof
    return PilotRuntimePreflightBindingPlan(
        requirements_sha256=checked_requirements.sha256,
        human_selection_proof_sha256=checked_selection.sha256,
        requirements=checked_requirements,
        human_selection_proof=checked_selection,
        repository=checked_requirements.repository,
        base_sha=checked_requirements.base_sha,
        requested_main_sha=checked_requirements.requested_main_sha,
        trial_id=checked_requirements.trial_id,
        operator_surface=checked_requirements.operator_surface,
        selected_pilot_task_id=checked_requirements.selected_pilot_task_id,
        workspace_root_path_sha256=checked_requirements.workspace_root_path_sha256,
        local_commits_allowed=checked_requirements.local_commits_allowed,
        feature_flag_name=candidate.feature_flag_name,
        product_route=candidate.product_route,
        runtime_observer_id=candidate.runtime_observer_id,
        task_registry_id=candidate.task_registry_id,
        workspace_policy_id=candidate.workspace_policy_id,
        review_authorization_roles_id=candidate.review_authorization_roles_id,
        kill_revoke_cleanup_id=candidate.kill_revoke_cleanup_id,
        local_commit_policy=candidate.local_commit_policy,
    )


__all__ = [
    "PILOT_RUNTIME_PREFLIGHT_BINDING_SCHEMA",
    "PILOT_RUNTIME_PREFLIGHT_BINDING_AUTHORITY",
    "PilotRuntimePreflightBindingError",
    "PilotRuntimePreflightBindingPlan",
    "bind_pilot_runtime_preflight",
]
