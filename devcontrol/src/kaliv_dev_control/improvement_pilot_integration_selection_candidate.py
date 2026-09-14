"""Fail-closed candidate validation for a future DC-L16 product integration selection.

ADR-DC-020 deliberately stops before human selection authority.  The caller may
propose concrete product-design values, but this module only proves that the
proposal is structurally complete, exact-bound to ADR-DC-018/019 evidence and no
broader than one verified ADR-DC-016 trial scope.

It does not record a human selection, observe runtime state, enable a feature
flag, register a command, start a pilot or authorize any product/remote action.
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

PILOT_INTEGRATION_SELECTION_CANDIDATE_SCHEMA = (
    "kaliv-rsi-dc-l16-product-integration-selection-candidate-proof/v1"
)
PILOT_INTEGRATION_SELECTION_CANDIDATE_AUTHORITY = (
    "dc-l16-product-integration-selection-candidate-only"
)

INVENTORY_SCHEMA = "kaliv-rsi-dc-l16-product-integration-inventory/v1"
SELECTION_REQUIREMENTS_SCHEMA = (
    "kaliv-rsi-dc-l16-product-integration-selection-requirements/v1"
)
INVENTORY_SOURCE_HEAD_SHA = "30be16b320acd6655c07ab1476cceaead547e3e3"
INVENTORY_GIT_BLOB_SHA = "babad0dfc82ad359ee053817bae2674a8f8b38a0"
SELECTION_REQUIREMENTS_GIT_BLOB_SHA = "36253b5a0ee8807f51eaeb8c0cf10276e0bc7a63"

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_FLAG = re.compile(r"^KALIV_[A-Z0-9_]{3,96}$")
_ROUTE = re.compile(r"^/api/v1/[a-z0-9][a-z0-9/_-]{1,127}$")
_FORBIDDEN_FLAG_NAMES = {
    "KALIV_AGENT3_ENABLED",
    "KALIV_AGENT4_OPERATOR_API",
}

_EXPECTED_CANDIDATES = {
    "desktop.control-center": {
        "kind": "operator-ui-candidate",
        "path": "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/ControlCenterDialog.kt",
        "git_blob_sha": "0a9498ac0fe61ea742a47c1d6be1cf7886992321",
    },
    "android.control-center": {
        "kind": "operator-ui-candidate",
        "path": "android/app/src/main/java/dk/ternedal/modelrig/ui/ControlCenterScreen.kt",
        "git_blob_sha": "82643d7cefe9a9c249e8e7cc8b480d9989b38606",
    },
    "backend.local-api-host-pattern": {
        "kind": "route-host-pattern-candidate",
        "path": "backend/internal/httpapi/server.go",
        "git_blob_sha": "6085d525ff86a3d2b5c7cdece20bcaeace896e85",
    },
}

_FIELDS = {
    "schema",
    "trial_scope_sha256",
    "decision_proof_sha256",
    "repository",
    "base_sha",
    "requested_main_sha",
    "trial_id",
    "operator_surface",
    "selected_pilot_task_id",
    "workspace_root_path_sha256",
    "local_commits_allowed",
    "inventory_source_head_sha",
    "inventory_git_blob_sha",
    "selection_requirements_git_blob_sha",
    "candidate_id",
    "candidate_kind",
    "candidate_path",
    "candidate_git_blob_sha",
    "feature_flag_name",
    "product_route",
    "runtime_observer_id",
    "task_registry_id",
    "workspace_policy_id",
    "review_authorization_roles_id",
    "kill_revoke_cleanup_id",
    "local_commit_policy",
    "human_pilot_go_verified",
    "pilot_scope_verified",
    "source_inventory_verified",
    "selection_requirements_verified",
    "design_candidate_validated",
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
    "authority",
}


class PilotIntegrationSelectionCandidateError(ValueError):
    """A proposed integration selection is malformed, stale or over-authorizing."""


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
        raise PilotIntegrationSelectionCandidateError(
            "integration selection candidate is not canonical JSON"
        ) from exc


def _git_blob_sha(raw: bytes) -> str:
    header = f"blob {len(raw)}\0".encode("ascii")
    return hashlib.sha1(header + raw).hexdigest()


def _load_exact_json(raw: Any, *, name: str, expected_blob_sha: str) -> dict[str, Any]:
    if type(raw) is not bytes:
        raise PilotIntegrationSelectionCandidateError(f"{name} must be exact raw bytes")
    if _git_blob_sha(raw) != expected_blob_sha:
        raise PilotIntegrationSelectionCandidateError(f"{name} exact Git blob identity mismatch")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PilotIntegrationSelectionCandidateError(f"{name} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise PilotIntegrationSelectionCandidateError(f"{name} root must be an object")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotIntegrationSelectionCandidateError(f"{name} is invalid")
    return value


def _require_inert_scope(value: Any) -> PilotTrialScopeProof:
    if type(value) is not PilotTrialScopeProof:
        raise PilotIntegrationSelectionCandidateError("exact PilotTrialScopeProof is required")
    if (
        value.authority != PILOT_TRIAL_SCOPE_AUTHORITY
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
        raise PilotIntegrationSelectionCandidateError(
            "pilot trial scope is not an inert verified positive human scope"
        )
    return value


def _verify_inventory(value: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    if value.get("schema") != INVENTORY_SCHEMA or value.get("repository") != "Ternedal/ModelRig":
        raise PilotIntegrationSelectionCandidateError("inventory identity mismatch")
    if value.get("source_parent_sha") != "7cc350fc50baad9f48fae88f76b6ad17b3a3817f":
        raise PilotIntegrationSelectionCandidateError("inventory source parent mismatch")
    candidates = value.get("candidate_surfaces")
    if not isinstance(candidates, list) or len(candidates) != len(_EXPECTED_CANDIDATES):
        raise PilotIntegrationSelectionCandidateError("inventory candidate set mismatch")
    resolved: dict[str, dict[str, str]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise PilotIntegrationSelectionCandidateError("inventory candidate is malformed")
        candidate_id = candidate.get("candidate_id")
        expected = _EXPECTED_CANDIDATES.get(candidate_id)
        if expected is None:
            raise PilotIntegrationSelectionCandidateError("inventory contains an unknown candidate")
        if candidate.get("selected") is not False:
            raise PilotIntegrationSelectionCandidateError("inventory must remain non-selecting")
        for key in ("kind", "path", "git_blob_sha"):
            if candidate.get(key) != expected[key]:
                raise PilotIntegrationSelectionCandidateError(
                    f"inventory candidate source mismatch: {candidate_id}:{key}"
                )
        resolved[candidate_id] = expected
    if set(resolved) != set(_EXPECTED_CANDIDATES):
        raise PilotIntegrationSelectionCandidateError("inventory candidate set is incomplete")
    authority = value.get("authority_state")
    if not isinstance(authority, dict):
        raise PilotIntegrationSelectionCandidateError("inventory authority state is missing")
    if authority.get("normal_command_catalog_empty") is not True:
        raise PilotIntegrationSelectionCandidateError("inventory command catalog boundary is invalid")
    for key in (
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
        if authority.get(key) is not False:
            raise PilotIntegrationSelectionCandidateError(f"inventory over-authorizes: {key}")
    if authority.get("authority") != "dc-l16-product-integration-inventory-only":
        raise PilotIntegrationSelectionCandidateError("inventory authority label mismatch")
    return resolved


def _verify_requirements(value: Mapping[str, Any]) -> None:
    if (
        value.get("schema") != SELECTION_REQUIREMENTS_SCHEMA
        or value.get("repository") != "Ternedal/ModelRig"
    ):
        raise PilotIntegrationSelectionCandidateError("selection requirements identity mismatch")
    source = value.get("source_inventory")
    if not isinstance(source, dict):
        raise PilotIntegrationSelectionCandidateError("selection requirements source binding missing")
    if source.get("source_head_sha") != INVENTORY_SOURCE_HEAD_SHA:
        raise PilotIntegrationSelectionCandidateError("requirements inventory head mismatch")
    if source.get("inventory_git_blob_sha") != INVENTORY_GIT_BLOB_SHA:
        raise PilotIntegrationSelectionCandidateError("requirements inventory blob mismatch")
    if source.get("candidate_ids") != list(_EXPECTED_CANDIDATES):
        raise PilotIntegrationSelectionCandidateError("requirements candidate IDs mismatch")
    binding = value.get("binding_requirements")
    decisions = value.get("product_design_decisions_required")
    selection = value.get("selection_state")
    authority = value.get("authority_state")
    if not isinstance(binding, dict) or not binding or any(item is not True for item in binding.values()):
        raise PilotIntegrationSelectionCandidateError("selection binding requirements were weakened")
    if not isinstance(decisions, dict) or not decisions or any(item is not True for item in decisions.values()):
        raise PilotIntegrationSelectionCandidateError("required product decisions were weakened")
    if not isinstance(selection, dict) or not selection or any(item is not False for item in selection.values()):
        raise PilotIntegrationSelectionCandidateError("requirements manifest already records a selection")
    if not isinstance(authority, dict) or authority.get("normal_command_catalog_empty") is not True:
        raise PilotIntegrationSelectionCandidateError("requirements authority state is invalid")
    for key, item in authority.items():
        if key in {"normal_command_catalog_empty", "authority"}:
            continue
        if item is not False:
            raise PilotIntegrationSelectionCandidateError(f"requirements over-authorize: {key}")
    if authority.get("authority") != "dc-l16-product-integration-selection-requirements-only":
        raise PilotIntegrationSelectionCandidateError("requirements authority label mismatch")


@dataclass(frozen=True, slots=True)
class PilotIntegrationSelectionCandidateProof:
    trial_scope_sha256: str
    decision_proof_sha256: str
    repository: str
    base_sha: str
    requested_main_sha: str
    trial_id: str
    operator_surface: str
    selected_pilot_task_id: str
    workspace_root_path_sha256: str
    local_commits_allowed: bool
    inventory_source_head_sha: str
    inventory_git_blob_sha: str
    selection_requirements_git_blob_sha: str
    candidate_id: str
    candidate_kind: str
    candidate_path: str
    candidate_git_blob_sha: str
    feature_flag_name: str
    product_route: str
    runtime_observer_id: str
    task_registry_id: str
    workspace_policy_id: str
    review_authorization_roles_id: str
    kill_revoke_cleanup_id: str
    local_commit_policy: str
    human_pilot_go_verified: bool = True
    pilot_scope_verified: bool = True
    source_inventory_verified: bool = True
    selection_requirements_verified: bool = True
    design_candidate_validated: bool = True
    human_selection_recorded: bool = False
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
    authority: str = PILOT_INTEGRATION_SELECTION_CANDIDATE_AUTHORITY
    schema: str = PILOT_INTEGRATION_SELECTION_CANDIDATE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_INTEGRATION_SELECTION_CANDIDATE_SCHEMA:
            raise PilotIntegrationSelectionCandidateError("selection candidate schema is unsupported")
        for name, value, pattern in (
            ("trial_scope_sha256", self.trial_scope_sha256, _HEX64),
            ("decision_proof_sha256", self.decision_proof_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("requested_main_sha", self.requested_main_sha, _HEX40),
            ("workspace_root_path_sha256", self.workspace_root_path_sha256, _HEX64),
            ("inventory_source_head_sha", self.inventory_source_head_sha, _HEX40),
            ("inventory_git_blob_sha", self.inventory_git_blob_sha, _HEX40),
            ("selection_requirements_git_blob_sha", self.selection_requirements_git_blob_sha, _HEX40),
            ("candidate_git_blob_sha", self.candidate_git_blob_sha, _HEX40),
        ):
            if not isinstance(value, str) or pattern.fullmatch(value) is None:
                raise PilotIntegrationSelectionCandidateError(f"{name} is invalid")
        for name, value in (
            ("trial_id", self.trial_id),
            ("operator_surface", self.operator_surface),
            ("selected_pilot_task_id", self.selected_pilot_task_id),
            ("candidate_id", self.candidate_id),
            ("runtime_observer_id", self.runtime_observer_id),
            ("task_registry_id", self.task_registry_id),
            ("workspace_policy_id", self.workspace_policy_id),
            ("review_authorization_roles_id", self.review_authorization_roles_id),
            ("kill_revoke_cleanup_id", self.kill_revoke_cleanup_id),
        ):
            _identifier(value, name=name)
        if self.repository != "Ternedal/ModelRig":
            raise PilotIntegrationSelectionCandidateError("repository is unsupported")
        if type(self.local_commits_allowed) is not bool:
            raise PilotIntegrationSelectionCandidateError("local_commits_allowed must be boolean")
        if _FLAG.fullmatch(self.feature_flag_name) is None or self.feature_flag_name in _FORBIDDEN_FLAG_NAMES:
            raise PilotIntegrationSelectionCandidateError("feature_flag_name is invalid or reuses foreign authority")
        if _ROUTE.fullmatch(self.product_route) is None or "devcontrol" not in self.product_route:
            raise PilotIntegrationSelectionCandidateError("product_route must be an explicit DC-L16 DevControl route")
        expected_local_policy = "allow-local-only" if self.local_commits_allowed else "forbid"
        if self.local_commit_policy != expected_local_policy:
            raise PilotIntegrationSelectionCandidateError("local commit policy broadens or contradicts trial scope")
        required_true = (
            self.human_pilot_go_verified,
            self.pilot_scope_verified,
            self.source_inventory_verified,
            self.selection_requirements_verified,
            self.design_candidate_validated,
        )
        required_false = (
            self.human_selection_recorded,
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
            or self.authority != PILOT_INTEGRATION_SELECTION_CANDIDATE_AUTHORITY
        ):
            raise PilotIntegrationSelectionCandidateError("selection candidate authority boundary is invalid")

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotIntegrationSelectionCandidateProof":
        if not isinstance(value, Mapping) or set(value) != _FIELDS:
            raise PilotIntegrationSelectionCandidateError("selection candidate proof fields mismatch")
        return cls(**dict(value))

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in _FIELDS}

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def validate_pilot_integration_selection_candidate(
    *,
    scope_proof: PilotTrialScopeProof,
    inventory_bytes: bytes,
    selection_requirements_bytes: bytes,
    feature_flag_name: str,
    product_route: str,
    runtime_observer_id: str,
    task_registry_id: str,
    workspace_policy_id: str,
    review_authorization_roles_id: str,
    kill_revoke_cleanup_id: str,
    local_commit_policy: str,
) -> PilotIntegrationSelectionCandidateProof:
    """Validate one inert proposed selection without recording human selection authority."""
    scope = _require_inert_scope(scope_proof)
    inventory = _load_exact_json(
        inventory_bytes,
        name="product integration inventory",
        expected_blob_sha=INVENTORY_GIT_BLOB_SHA,
    )
    requirements = _load_exact_json(
        selection_requirements_bytes,
        name="product integration selection requirements",
        expected_blob_sha=SELECTION_REQUIREMENTS_GIT_BLOB_SHA,
    )
    candidates = _verify_inventory(inventory)
    _verify_requirements(requirements)

    candidate = candidates.get(scope.operator_surface)
    if candidate is None:
        raise PilotIntegrationSelectionCandidateError(
            "operator surface is absent from exact inventory; fresh exact-source inventory is required"
        )

    for name, value in (
        ("runtime_observer_id", runtime_observer_id),
        ("task_registry_id", task_registry_id),
        ("workspace_policy_id", workspace_policy_id),
        ("review_authorization_roles_id", review_authorization_roles_id),
        ("kill_revoke_cleanup_id", kill_revoke_cleanup_id),
    ):
        _identifier(value, name=name)
    if not isinstance(feature_flag_name, str) or _FLAG.fullmatch(feature_flag_name) is None:
        raise PilotIntegrationSelectionCandidateError("feature_flag_name is invalid")
    if feature_flag_name in _FORBIDDEN_FLAG_NAMES:
        raise PilotIntegrationSelectionCandidateError("feature flag reuses unrelated Agent authority")
    if not isinstance(product_route, str) or _ROUTE.fullmatch(product_route) is None:
        raise PilotIntegrationSelectionCandidateError("product_route is invalid")
    if "devcontrol" not in product_route:
        raise PilotIntegrationSelectionCandidateError("product_route must be explicitly DevControl-scoped")

    expected_local_policy = "allow-local-only" if scope.local_commits_allowed else "forbid"
    if local_commit_policy != expected_local_policy:
        raise PilotIntegrationSelectionCandidateError(
            "local commit policy differs from or broadens the exact trial scope"
        )

    return PilotIntegrationSelectionCandidateProof(
        trial_scope_sha256=scope.sha256,
        decision_proof_sha256=scope.decision_proof_sha256,
        repository=scope.repository,
        base_sha=scope.base_sha,
        requested_main_sha=scope.requested_main_sha,
        trial_id=scope.trial_id,
        operator_surface=scope.operator_surface,
        selected_pilot_task_id=scope.selected_pilot_task_id,
        workspace_root_path_sha256=scope.workspace_root_path_sha256,
        local_commits_allowed=scope.local_commits_allowed,
        inventory_source_head_sha=INVENTORY_SOURCE_HEAD_SHA,
        inventory_git_blob_sha=INVENTORY_GIT_BLOB_SHA,
        selection_requirements_git_blob_sha=SELECTION_REQUIREMENTS_GIT_BLOB_SHA,
        candidate_id=scope.operator_surface,
        candidate_kind=candidate["kind"],
        candidate_path=candidate["path"],
        candidate_git_blob_sha=candidate["git_blob_sha"],
        feature_flag_name=feature_flag_name,
        product_route=product_route,
        runtime_observer_id=runtime_observer_id,
        task_registry_id=task_registry_id,
        workspace_policy_id=workspace_policy_id,
        review_authorization_roles_id=review_authorization_roles_id,
        kill_revoke_cleanup_id=kill_revoke_cleanup_id,
        local_commit_policy=local_commit_policy,
    )


__all__ = [
    "PILOT_INTEGRATION_SELECTION_CANDIDATE_SCHEMA",
    "PILOT_INTEGRATION_SELECTION_CANDIDATE_AUTHORITY",
    "INVENTORY_SOURCE_HEAD_SHA",
    "INVENTORY_GIT_BLOB_SHA",
    "SELECTION_REQUIREMENTS_GIT_BLOB_SHA",
    "PilotIntegrationSelectionCandidateError",
    "PilotIntegrationSelectionCandidateProof",
    "validate_pilot_integration_selection_candidate",
]
