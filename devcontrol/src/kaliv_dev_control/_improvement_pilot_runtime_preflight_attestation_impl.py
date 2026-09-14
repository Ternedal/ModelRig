"""Host-attested runtime preflight evidence for one human-selected DC-L16 candidate.

ADR-DC-022 verifies a separately signed host observation against exact ADR-DC-021
human-selection proof and ADR-DC-017 requirements. It can establish only
preflight evidence. It does not integrate product code, register commands, start
a pilot, mutate Git/GitHub, or authorize remote/production activity.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .asymmetric_authority import (
    AsymmetricAuthorityError,
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
)
from .improvement_pilot_integration_human_selection import (
    PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_AUTHORITY,
    PilotIntegrationHumanSelectionProof,
)
from .improvement_pilot_preflight_requirements import (
    PILOT_PREFLIGHT_REQUIREMENTS_AUTHORITY,
    PilotPreflightRequirements,
)

PILOT_RUNTIME_PREFLIGHT_OBSERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-pilot-runtime-preflight-observation/v1"
)
PILOT_RUNTIME_PREFLIGHT_PROOF_SCHEMA = (
    "kaliv-rsi-dc-l16-pilot-runtime-preflight-proof/v1"
)
PILOT_RUNTIME_PREFLIGHT_OBSERVATION_AUTHORITY = (
    "dc-l16-pilot-runtime-preflight-observation-claim-only"
)
PILOT_RUNTIME_PREFLIGHT_PROOF_AUTHORITY = (
    "verified-dc-l16-pilot-runtime-preflight-only"
)
PILOT_RUNTIME_PREFLIGHT_ISSUER_SYSTEM_ID = (
    "kaliv-rsi-dc-l16-pilot-runtime-preflight-observer-v1"
)

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_CHECK_FIELDS = (
    "feature_flag_off_observed",
    "pilot_runtime_verified",
    "native_windows_isolation_verified",
    "trusted_git_closure_verified",
    "kill_switch_prearmed",
    "restart_revoke_prearmed",
    "network_write_block_verified",
    "credentials_absent_verified",
    "unattended_cadence_forbidden_verified",
    "off_state_import_block_verified",
    "exact_source_binding_verified",
    "receipt_binding_verified",
)

_OBSERVATION_FIELDS = {
    "schema",
    "observation_id",
    "selection_proof_sha256",
    "selection_sha256",
    "candidate_proof_sha256",
    "requirements_sha256",
    "trial_scope_sha256",
    "repository",
    "base_sha",
    "requested_main_sha",
    "trial_id",
    "operator_surface",
    "selected_pilot_task_id",
    "workspace_root_path_sha256",
    "candidate_id",
    "candidate_git_blob_sha",
    "feature_flag_name",
    "product_route",
    "runtime_observer_id",
    "task_registry_id",
    "workspace_policy_id",
    "kill_revoke_cleanup_id",
    "local_commit_policy",
    "observer_actor_id",
    "observer_host_id",
    "observed_at_utc",
    "runtime_receipt_sha256",
    *_CHECK_FIELDS,
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

_PROOF_FIELDS = {
    "schema",
    "observation_sha256",
    "signature_sha256",
    "key_id",
    "issuer_actor_id",
    "issuer_system_id",
    "selection_proof",
    "requirements",
    "observation",
    "verified_at_utc",
    "selection_proof_sha256",
    "requirements_sha256",
    "candidate_proof_sha256",
    "preflight_observed",
    "preflight_satisfied",
    "integration_ready",
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


class PilotRuntimePreflightError(ValueError):
    """Runtime preflight evidence is malformed, stale, untrusted or over-authorizing."""


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
        raise PilotRuntimePreflightError("runtime preflight evidence is not canonical JSON") from exc


def _strict(value: Any, *, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PilotRuntimePreflightError(f"{name} fields mismatch")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotRuntimePreflightError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise PilotRuntimePreflightError(f"{name} is invalid")
    return value


def _hex(value: Any, *, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PilotRuntimePreflightError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotRuntimePreflightError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotRuntimePreflightError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_selection(value: Any) -> PilotIntegrationHumanSelectionProof:
    if type(value) is not PilotIntegrationHumanSelectionProof:
        raise PilotRuntimePreflightError("exact PilotIntegrationHumanSelectionProof is required")
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
        raise PilotRuntimePreflightError("human integration selection proof is not inert verified evidence")
    try:
        replayed = PilotIntegrationHumanSelectionProof.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotRuntimePreflightError("human selection proof replay validation failed") from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotRuntimePreflightError("human selection proof replay identity mismatch")
    return value


def _require_requirements(value: Any) -> PilotPreflightRequirements:
    if type(value) is not PilotPreflightRequirements:
        raise PilotRuntimePreflightError("exact PilotPreflightRequirements is required")
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
        raise PilotRuntimePreflightError("preflight requirements are not inert exact evidence")
    try:
        replayed = PilotPreflightRequirements.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotRuntimePreflightError("preflight requirements replay validation failed") from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotRuntimePreflightError("preflight requirements replay identity mismatch")
    return value


def _bind_selection_requirements(
    *,
    selection_proof: PilotIntegrationHumanSelectionProof,
    requirements: PilotPreflightRequirements,
) -> tuple[PilotIntegrationHumanSelectionProof, PilotPreflightRequirements]:
    selection = _require_selection(selection_proof)
    req = _require_requirements(requirements)
    candidate = selection.selection.candidate_proof
    expected = {
        "trial_scope_sha256": candidate.trial_scope_sha256,
        "decision_proof_sha256": candidate.decision_proof_sha256,
        "repository": candidate.repository,
        "base_sha": candidate.base_sha,
        "requested_main_sha": candidate.requested_main_sha,
        "trial_id": candidate.trial_id,
        "operator_surface": candidate.operator_surface,
        "selected_pilot_task_id": candidate.selected_pilot_task_id,
        "workspace_root_path_sha256": candidate.workspace_root_path_sha256,
        "local_commits_allowed": candidate.local_commits_allowed,
    }
    if any(getattr(req, name) != item for name, item in expected.items()):
        raise PilotRuntimePreflightError("preflight requirements are not exactly bound to the human-selected candidate")
    return selection, req


@dataclass(frozen=True, slots=True)
class PilotRuntimePreflightObservation:
    observation_id: str
    selection_proof_sha256: str
    selection_sha256: str
    candidate_proof_sha256: str
    requirements_sha256: str
    trial_scope_sha256: str
    repository: str
    base_sha: str
    requested_main_sha: str
    trial_id: str
    operator_surface: str
    selected_pilot_task_id: str
    workspace_root_path_sha256: str
    candidate_id: str
    candidate_git_blob_sha: str
    feature_flag_name: str
    product_route: str
    runtime_observer_id: str
    task_registry_id: str
    workspace_policy_id: str
    kill_revoke_cleanup_id: str
    local_commit_policy: str
    observer_actor_id: str
    observer_host_id: str
    observed_at_utc: str
    runtime_receipt_sha256: str
    feature_flag_off_observed: bool
    pilot_runtime_verified: bool
    native_windows_isolation_verified: bool
    trusted_git_closure_verified: bool
    kill_switch_prearmed: bool
    restart_revoke_prearmed: bool
    network_write_block_verified: bool
    credentials_absent_verified: bool
    unattended_cadence_forbidden_verified: bool
    off_state_import_block_verified: bool
    exact_source_binding_verified: bool
    receipt_binding_verified: bool
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
    authority: str = PILOT_RUNTIME_PREFLIGHT_OBSERVATION_AUTHORITY
    schema: str = PILOT_RUNTIME_PREFLIGHT_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_RUNTIME_PREFLIGHT_OBSERVATION_SCHEMA:
            raise PilotRuntimePreflightError("runtime preflight observation schema is unsupported")
        _identifier(self.observation_id, name="observation_id")
        for name, value, pattern in (
            ("selection_proof_sha256", self.selection_proof_sha256, _HEX64),
            ("selection_sha256", self.selection_sha256, _HEX64),
            ("candidate_proof_sha256", self.candidate_proof_sha256, _HEX64),
            ("requirements_sha256", self.requirements_sha256, _HEX64),
            ("trial_scope_sha256", self.trial_scope_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("requested_main_sha", self.requested_main_sha, _HEX40),
            ("workspace_root_path_sha256", self.workspace_root_path_sha256, _HEX64),
            ("candidate_git_blob_sha", self.candidate_git_blob_sha, _HEX40),
            ("runtime_receipt_sha256", self.runtime_receipt_sha256, _HEX64),
        ):
            _hex(value, name=name, pattern=pattern)
        for name, value in (
            ("trial_id", self.trial_id),
            ("operator_surface", self.operator_surface),
            ("selected_pilot_task_id", self.selected_pilot_task_id),
            ("candidate_id", self.candidate_id),
            ("runtime_observer_id", self.runtime_observer_id),
            ("task_registry_id", self.task_registry_id),
            ("workspace_policy_id", self.workspace_policy_id),
            ("kill_revoke_cleanup_id", self.kill_revoke_cleanup_id),
            ("observer_host_id", self.observer_host_id),
        ):
            _identifier(value, name=name)
        _actor(self.observer_actor_id, name="observer_actor_id")
        _utc(self.observed_at_utc, name="observed_at_utc")
        if self.repository != "Ternedal/ModelRig":
            raise PilotRuntimePreflightError("repository is unsupported")
        for name in _CHECK_FIELDS:
            if type(getattr(self, name)) is not bool:
                raise PilotRuntimePreflightError(f"{name} must be boolean")
        if (
            self.integration_ready is not False
            or self.preflight_observed is not False
            or self.preflight_satisfied is not False
            or self.pilot_start_authorized is not False
            or self.product_pilot_started is not False
            or self.remote_write_authorized is not False
            or self.push_authorized is not False
            or self.pr_mutation_authorized is not False
            or self.merge_authorized is not False
            or self.release_authorized is not False
            or self.deploy_authorized is not False
            or self.production_activation_authorized is not False
            or self.authority != PILOT_RUNTIME_PREFLIGHT_OBSERVATION_AUTHORITY
        ):
            raise PilotRuntimePreflightError("runtime preflight observation authority boundary is invalid")

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotRuntimePreflightObservation":
        return cls(**dict(_strict(value, fields=_OBSERVATION_FIELDS, name="runtime preflight observation")))

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in _OBSERVATION_FIELDS}

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def all_checks_satisfied(self) -> bool:
        return all(getattr(self, name) is True for name in _CHECK_FIELDS)


def _observation_matches(
    *,
    selection_proof: PilotIntegrationHumanSelectionProof,
    requirements: PilotPreflightRequirements,
    observation: PilotRuntimePreflightObservation,
) -> bool:
    candidate = selection_proof.selection.candidate_proof
    expected = {
        "selection_proof_sha256": selection_proof.sha256,
        "selection_sha256": selection_proof.selection_sha256,
        "candidate_proof_sha256": selection_proof.candidate_proof_sha256,
        "requirements_sha256": requirements.sha256,
        "trial_scope_sha256": requirements.trial_scope_sha256,
        "repository": candidate.repository,
        "base_sha": candidate.base_sha,
        "requested_main_sha": candidate.requested_main_sha,
        "trial_id": candidate.trial_id,
        "operator_surface": candidate.operator_surface,
        "selected_pilot_task_id": candidate.selected_pilot_task_id,
        "workspace_root_path_sha256": candidate.workspace_root_path_sha256,
        "candidate_id": candidate.candidate_id,
        "candidate_git_blob_sha": candidate.candidate_git_blob_sha,
        "feature_flag_name": candidate.feature_flag_name,
        "product_route": candidate.product_route,
        "runtime_observer_id": candidate.runtime_observer_id,
        "task_registry_id": candidate.task_registry_id,
        "workspace_policy_id": candidate.workspace_policy_id,
        "kill_revoke_cleanup_id": candidate.kill_revoke_cleanup_id,
        "local_commit_policy": candidate.local_commit_policy,
    }
    return all(getattr(observation, name) == item for name, item in expected.items())


def build_pilot_runtime_preflight_observation(
    *,
    selection_proof: PilotIntegrationHumanSelectionProof,
    requirements: PilotPreflightRequirements,
    observation_id: str,
    observer_actor_id: str,
    observer_host_id: str,
    observed_at_utc: str,
    runtime_receipt_sha256: str,
    feature_flag_off_observed: bool,
    pilot_runtime_verified: bool,
    native_windows_isolation_verified: bool,
    trusted_git_closure_verified: bool,
    kill_switch_prearmed: bool,
    restart_revoke_prearmed: bool,
    network_write_block_verified: bool,
    credentials_absent_verified: bool,
    unattended_cadence_forbidden_verified: bool,
    off_state_import_block_verified: bool,
    exact_source_binding_verified: bool,
    receipt_binding_verified: bool,
) -> PilotRuntimePreflightObservation:
    """Build exact externally-signable host-observation bytes; grants no authority."""
    selection, req = _bind_selection_requirements(
        selection_proof=selection_proof,
        requirements=requirements,
    )
    candidate = selection.selection.candidate_proof
    return PilotRuntimePreflightObservation(
        observation_id=observation_id,
        selection_proof_sha256=selection.sha256,
        selection_sha256=selection.selection_sha256,
        candidate_proof_sha256=selection.candidate_proof_sha256,
        requirements_sha256=req.sha256,
        trial_scope_sha256=req.trial_scope_sha256,
        repository=candidate.repository,
        base_sha=candidate.base_sha,
        requested_main_sha=candidate.requested_main_sha,
        trial_id=candidate.trial_id,
        operator_surface=candidate.operator_surface,
        selected_pilot_task_id=candidate.selected_pilot_task_id,
        workspace_root_path_sha256=candidate.workspace_root_path_sha256,
        candidate_id=candidate.candidate_id,
        candidate_git_blob_sha=candidate.candidate_git_blob_sha,
        feature_flag_name=candidate.feature_flag_name,
        product_route=candidate.product_route,
        runtime_observer_id=candidate.runtime_observer_id,
        task_registry_id=candidate.task_registry_id,
        workspace_policy_id=candidate.workspace_policy_id,
        kill_revoke_cleanup_id=candidate.kill_revoke_cleanup_id,
        local_commit_policy=candidate.local_commit_policy,
        observer_actor_id=observer_actor_id,
        observer_host_id=observer_host_id,
        observed_at_utc=observed_at_utc,
        runtime_receipt_sha256=runtime_receipt_sha256,
        feature_flag_off_observed=feature_flag_off_observed,
        pilot_runtime_verified=pilot_runtime_verified,
        native_windows_isolation_verified=native_windows_isolation_verified,
        trusted_git_closure_verified=trusted_git_closure_verified,
        kill_switch_prearmed=kill_switch_prearmed,
        restart_revoke_prearmed=restart_revoke_prearmed,
        network_write_block_verified=network_write_block_verified,
        credentials_absent_verified=credentials_absent_verified,
        unattended_cadence_forbidden_verified=unattended_cadence_forbidden_verified,
        off_state_import_block_verified=off_state_import_block_verified,
        exact_source_binding_verified=exact_source_binding_verified,
        receipt_binding_verified=receipt_binding_verified,
    )


@dataclass(frozen=True, slots=True)
class PilotRuntimePreflightProof:
    observation_sha256: str
    signature_sha256: str
    key_id: str
    issuer_actor_id: str
    issuer_system_id: str
    selection_proof: PilotIntegrationHumanSelectionProof
    requirements: PilotPreflightRequirements
    observation: PilotRuntimePreflightObservation
    verified_at_utc: str
    selection_proof_sha256: str
    requirements_sha256: str
    candidate_proof_sha256: str
    preflight_observed: bool = True
    preflight_satisfied: bool = False
    integration_ready: bool = False
    pilot_start_authorized: bool = False
    product_pilot_started: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_RUNTIME_PREFLIGHT_PROOF_AUTHORITY
    schema: str = PILOT_RUNTIME_PREFLIGHT_PROOF_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_RUNTIME_PREFLIGHT_PROOF_SCHEMA:
            raise PilotRuntimePreflightError("runtime preflight proof schema is unsupported")
        _hex(self.observation_sha256, name="observation_sha256", pattern=_HEX64)
        _hex(self.signature_sha256, name="signature_sha256", pattern=_HEX64)
        _identifier(self.key_id, name="key_id")
        _actor(self.issuer_actor_id, name="issuer_actor_id")
        _identifier(self.issuer_system_id, name="issuer_system_id")
        if self.issuer_system_id != PILOT_RUNTIME_PREFLIGHT_ISSUER_SYSTEM_ID:
            raise PilotRuntimePreflightError("runtime preflight proof issuer system is invalid")
        selection, req = _bind_selection_requirements(
            selection_proof=self.selection_proof,
            requirements=self.requirements,
        )
        if type(self.observation) is not PilotRuntimePreflightObservation:
            raise PilotRuntimePreflightError("exact PilotRuntimePreflightObservation is required")
        if not _observation_matches(
            selection_proof=selection,
            requirements=req,
            observation=self.observation,
        ):
            raise PilotRuntimePreflightError("runtime preflight proof observation binding mismatch")
        if self.observation_sha256 != self.observation.sha256:
            raise PilotRuntimePreflightError("runtime preflight proof observation hash mismatch")
        if self.selection_proof_sha256 != selection.sha256:
            raise PilotRuntimePreflightError("runtime preflight proof selection hash mismatch")
        if self.requirements_sha256 != req.sha256:
            raise PilotRuntimePreflightError("runtime preflight proof requirements hash mismatch")
        if self.candidate_proof_sha256 != selection.candidate_proof_sha256:
            raise PilotRuntimePreflightError("runtime preflight proof candidate hash mismatch")
        if self.issuer_actor_id != self.observation.observer_actor_id:
            raise PilotRuntimePreflightError("runtime preflight proof signer mismatch")
        verified = _utc(self.verified_at_utc, name="verified_at_utc")
        observed = _utc(self.observation.observed_at_utc, name="observed_at_utc")
        if verified < observed:
            raise PilotRuntimePreflightError("runtime preflight proof timing is invalid")
        expected_satisfied = self.observation.all_checks_satisfied
        if (
            self.preflight_observed is not True
            or self.preflight_satisfied is not expected_satisfied
            or self.integration_ready is not False
            or self.pilot_start_authorized is not False
            or self.product_pilot_started is not False
            or self.remote_write_authorized is not False
            or self.push_authorized is not False
            or self.pr_mutation_authorized is not False
            or self.merge_authorized is not False
            or self.release_authorized is not False
            or self.deploy_authorized is not False
            or self.production_activation_authorized is not False
            or self.authority != PILOT_RUNTIME_PREFLIGHT_PROOF_AUTHORITY
        ):
            raise PilotRuntimePreflightError("runtime preflight proof authority boundary is invalid")

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotRuntimePreflightProof":
        data = dict(_strict(value, fields=_PROOF_FIELDS, name="runtime preflight proof"))
        for name in ("selection_proof", "requirements", "observation"):
            if not isinstance(data.get(name), Mapping):
                raise PilotRuntimePreflightError(f"{name} must be an object")
        data["selection_proof"] = PilotIntegrationHumanSelectionProof.from_mapping(data["selection_proof"])
        data["requirements"] = PilotPreflightRequirements.from_mapping(data["requirements"])
        data["observation"] = PilotRuntimePreflightObservation.from_mapping(data["observation"])
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "observation_sha256": self.observation_sha256,
            "signature_sha256": self.signature_sha256,
            "key_id": self.key_id,
            "issuer_actor_id": self.issuer_actor_id,
            "issuer_system_id": self.issuer_system_id,
            "selection_proof": self.selection_proof.to_dict(),
            "requirements": self.requirements.to_dict(),
            "observation": self.observation.to_dict(),
            "verified_at_utc": self.verified_at_utc,
            "selection_proof_sha256": self.selection_proof_sha256,
            "requirements_sha256": self.requirements_sha256,
            "candidate_proof_sha256": self.candidate_proof_sha256,
            "preflight_observed": self.preflight_observed,
            "preflight_satisfied": self.preflight_satisfied,
            "integration_ready": self.integration_ready,
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


def _verify_pilot_runtime_preflight(
    *,
    selection_proof: PilotIntegrationHumanSelectionProof,
    requirements: PilotPreflightRequirements,
    observation: PilotRuntimePreflightObservation,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_provider: Callable[[], str],
) -> PilotRuntimePreflightProof:
    selection, req = _bind_selection_requirements(
        selection_proof=selection_proof,
        requirements=requirements,
    )
    if type(observation) is not PilotRuntimePreflightObservation:
        raise PilotRuntimePreflightError("exact PilotRuntimePreflightObservation is required")
    if not _observation_matches(
        selection_proof=selection,
        requirements=req,
        observation=observation,
    ):
        raise PilotRuntimePreflightError("runtime preflight observation binding mismatch")
    if not isinstance(signature, DetachedEd25519AuthoritySignature):
        raise PilotRuntimePreflightError("detached Ed25519 runtime preflight signature is required")
    if not isinstance(verifier, Ed25519AuthorityVerifier):
        raise PilotRuntimePreflightError("Ed25519 runtime preflight verifier is required")
    if signature.issuer_system_id != PILOT_RUNTIME_PREFLIGHT_ISSUER_SYSTEM_ID:
        raise PilotRuntimePreflightError("runtime preflight signature belongs to another issuer system")
    if signature.issuer_actor_id != observation.observer_actor_id:
        raise PilotRuntimePreflightError("runtime preflight signer must be the observer actor")
    if signature.signed_at_utc != observation.observed_at_utc:
        raise PilotRuntimePreflightError("runtime preflight signature time does not match observation")
    verified_at = now_provider()
    if _utc(verified_at, name="runtime preflight verification time") < _utc(
        observation.observed_at_utc,
        name="observed_at_utc",
    ):
        raise PilotRuntimePreflightError("runtime preflight verification predates observation")
    try:
        verified_payload_sha256 = verifier.verify(
            payload=observation.canonical_json().encode("utf-8"),
            signature=signature,
            at_utc=verified_at,
        )
    except AsymmetricAuthorityError as exc:
        raise PilotRuntimePreflightError("runtime preflight authority verification failed") from exc
    if verified_payload_sha256 != observation.sha256:
        raise PilotRuntimePreflightError("runtime preflight verified payload hash mismatch")
    return PilotRuntimePreflightProof(
        observation_sha256=observation.sha256,
        signature_sha256=signature.sha256,
        key_id=signature.key_id,
        issuer_actor_id=signature.issuer_actor_id,
        issuer_system_id=signature.issuer_system_id,
        selection_proof=selection,
        requirements=req,
        observation=observation,
        verified_at_utc=verified_at,
        selection_proof_sha256=selection.sha256,
        requirements_sha256=req.sha256,
        candidate_proof_sha256=selection.candidate_proof_sha256,
        preflight_satisfied=observation.all_checks_satisfied,
    )


def verify_pilot_runtime_preflight(
    *,
    selection_proof: PilotIntegrationHumanSelectionProof,
    requirements: PilotPreflightRequirements,
    observation: PilotRuntimePreflightObservation,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier | None = None,
) -> PilotRuntimePreflightProof:
    """Injectable compatibility surface replaced by the production facade."""
    if verifier is None:
        raise PilotRuntimePreflightError("runtime preflight verifier is unavailable outside production facade")
    return _verify_pilot_runtime_preflight(
        selection_proof=selection_proof,
        requirements=requirements,
        observation=observation,
        signature=signature,
        verifier=verifier,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_RUNTIME_PREFLIGHT_OBSERVATION_SCHEMA",
    "PILOT_RUNTIME_PREFLIGHT_PROOF_SCHEMA",
    "PILOT_RUNTIME_PREFLIGHT_OBSERVATION_AUTHORITY",
    "PILOT_RUNTIME_PREFLIGHT_PROOF_AUTHORITY",
    "PILOT_RUNTIME_PREFLIGHT_ISSUER_SYSTEM_ID",
    "PilotRuntimePreflightError",
    "PilotRuntimePreflightObservation",
    "PilotRuntimePreflightProof",
    "build_pilot_runtime_preflight_observation",
    "verify_pilot_runtime_preflight",
]
