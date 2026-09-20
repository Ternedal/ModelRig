"""ADR-DC-099 inert product-pilot start gap evaluation.

This boundary binds the restored ADR-DC-096 product-pilot start requirements to
ADR-DC-098 end-to-end authority lineage and evaluates the currently implemented
ModelRig product seam. It is evidence-only: it cannot authorize or start a
product pilot and it intentionally records every remaining product blocker.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping

from .improvement_pilot_exact_task_product_pilot_start_requirements import (
    PilotExactTaskProductPilotStartRequirements,
)
from .improvement_pilot_exact_task_product_pilot_lineage_attestation import (
    PilotExactTaskProductPilotLineageAttestationReceipt,
)

PILOT_EXACT_TASK_PRODUCT_PILOT_START_GAP_EVALUATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-start-gap-evaluation/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_GAP_EVALUATION_AUTHORITY = (
    "dc-l16-product-pilot-start-gap-evidence-only"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_GAP_EVALUATION_SCOPE = (
    "inert-requirements-lineage-product-gap-evaluation-v1"
)

IMPLEMENTED_OPERATOR_SURFACE = "desktop.control-center"
IMPLEMENTED_FEATURE_FLAG_NAME = "KALIV_DEVCONTROL_PILOT"
IMPLEMENTED_PRODUCT_ROUTE = "/api/v1/experimental/devcontrol-pilot/status"

IMPLEMENTATION_HANDOFF_GIT_BLOB_SHA = "780f0f52fcdb31a642e49f599e7629d3eb969f58"
UI_OBSERVER_HANDOFF_GIT_BLOB_SHA = "efafa6054bfe2bb265ec4f94bca649bef8d2d926"
BACKEND_STATUS_SOURCE_GIT_BLOB_SHA = "ddbdbb0aba2c95a63d42d6b89aeb5fbd85fd134d"
DESKTOP_OBSERVER_SOURCE_GIT_BLOB_SHA = "a3389801f3c7217b3d72bf85e2e87996d6f0a0b5"

_IMPLEMENTATION_PROFILE = {
    "operator_surface": IMPLEMENTED_OPERATOR_SURFACE,
    "feature_flag_name": IMPLEMENTED_FEATURE_FLAG_NAME,
    "product_route": IMPLEMENTED_PRODUCT_ROUTE,
    "implementation_handoff_git_blob_sha": IMPLEMENTATION_HANDOFF_GIT_BLOB_SHA,
    "ui_observer_handoff_git_blob_sha": UI_OBSERVER_HANDOFF_GIT_BLOB_SHA,
    "backend_status_source_git_blob_sha": BACKEND_STATUS_SOURCE_GIT_BLOB_SHA,
    "desktop_observer_source_git_blob_sha": DESKTOP_OBSERVER_SOURCE_GIT_BLOB_SHA,
    "feature_flag_default_off": True,
    "status_observer_implemented": True,
    "manual_refresh_only": True,
    "fresh_human_product_pilot_go_verified": False,
    "task_registry_ready": False,
    "runtime_preflight_satisfied": False,
    "executor_wired": False,
    "start_control_present": False,
    "kill_switch_runtime_wired": False,
    "revoke_runtime_wired": False,
    "restart_recovery_runtime_wired": False,
    "canonical_workspace_product_binding_verified": False,
    "native_windows_isolation_product_reverified": False,
    "trusted_git_closure_product_reverified": False,
    "local_only_product_execution_exercised": False,
    "network_write_block_product_verified": False,
    "credentials_absent_product_verified": False,
    "cancel_timeout_crash_recovery_verified": False,
    "workspace_reset_artifact_verification_verified": False,
    "physical_product_entrypoint_exercised": False,
    "remote_transport_available": False,
    "status_surface_credentials_present": False,
}

KNOWN_BLOCKER_CODES = (
    "operator-surface-scope-drift",
    "feature-flag-scope-drift",
    "product-route-scope-drift",
    "fresh-human-product-pilot-go-missing",
    "task-registry-not-ready",
    "runtime-preflight-not-satisfied",
    "product-executor-not-wired",
    "product-start-control-absent",
    "kill-switch-runtime-not-wired",
    "revoke-runtime-not-wired",
    "restart-recovery-runtime-not-wired",
    "canonical-workspace-product-binding-not-verified",
    "native-windows-isolation-not-product-reverified",
    "trusted-git-closure-not-product-reverified",
    "local-only-product-execution-not-exercised",
    "product-start-network-write-block-not-verified",
    "product-start-credentials-absence-not-verified",
    "cancel-timeout-crash-recovery-not-verified",
    "workspace-reset-artifact-verification-not-verified",
    "physical-product-entrypoint-not-exercised",
    "requirements-not-satisfied",
)

_FIXED_BLOCKERS = KNOWN_BLOCKER_CODES[3:]
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class PilotExactTaskProductPilotStartGapEvaluationError(ValueError):
    """The gap inputs or receipt are inconsistent or over-authorizing."""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskProductPilotStartGapEvaluationError(
            "product-pilot gap evidence is not canonical JSON"
        ) from exc


IMPLEMENTATION_PROFILE_SHA256 = hashlib.sha256(
    _canonical(_IMPLEMENTATION_PROFILE).encode("utf-8")
).hexdigest()


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None:
        raise PilotExactTaskProductPilotStartGapEvaluationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise PilotExactTaskProductPilotStartGapEvaluationError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise PilotExactTaskProductPilotStartGapEvaluationError(f"{name} is invalid")
    return value


def _route(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or "\x00" in value
        or len(value.encode("utf-8")) > 512
    ):
        raise PilotExactTaskProductPilotStartGapEvaluationError(f"{name} is invalid")
    return value


def _replay(value: Any, cls: type, *, name: str) -> Any:
    if type(value) is not cls:
        raise PilotExactTaskProductPilotStartGapEvaluationError(
            f"exact {name} is required"
        )
    try:
        replayed = cls.from_mapping(value.to_dict())
    except (AttributeError, TypeError, ValueError) as exc:
        raise PilotExactTaskProductPilotStartGapEvaluationError(
            f"{name} replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskProductPilotStartGapEvaluationError(
            f"{name} replay identity mismatch"
        )
    return value


def _blockers(
    *,
    operator_surface_matches: bool,
    feature_flag_scope_matches: bool,
    product_route_scope_matches: bool,
) -> tuple[str, ...]:
    values: list[str] = []
    if not operator_surface_matches:
        values.append("operator-surface-scope-drift")
    if not feature_flag_scope_matches:
        values.append("feature-flag-scope-drift")
    if not product_route_scope_matches:
        values.append("product-route-scope-drift")
    values.extend(_FIXED_BLOCKERS)
    return tuple(values)


@dataclass(frozen=True, slots=True)
class PilotExactTaskProductPilotStartGapEvaluationReceipt:
    requirements_sha256: str
    lineage_attestation_sha256: str
    post_production_activation_attestation_sha256: str
    production_activation_candidate_sha256: str
    repository: str
    merge_commit_sha: str
    signed_operator_surface: str
    implemented_operator_surface: str
    signed_feature_flag_name: str
    implemented_feature_flag_name: str
    signed_product_route: str
    implemented_product_route: str
    implementation_handoff_git_blob_sha: str
    ui_observer_handoff_git_blob_sha: str
    backend_status_source_git_blob_sha: str
    desktop_observer_source_git_blob_sha: str
    implementation_profile_sha256: str
    blocker_codes: tuple[str, ...]
    requirements_lineage_bound: bool = True
    implementation_profile_pinned: bool = True
    operator_surface_matches: bool = True
    feature_flag_scope_matches: bool = False
    product_route_scope_matches: bool = False
    feature_flag_default_off: bool = True
    status_observer_implemented: bool = True
    manual_refresh_only: bool = True
    fresh_human_product_pilot_go_verified: bool = False
    task_registry_ready: bool = False
    runtime_preflight_satisfied: bool = False
    executor_wired: bool = False
    start_control_present: bool = False
    kill_switch_runtime_wired: bool = False
    revoke_runtime_wired: bool = False
    restart_recovery_runtime_wired: bool = False
    canonical_workspace_product_binding_verified: bool = False
    native_windows_isolation_product_reverified: bool = False
    trusted_git_closure_product_reverified: bool = False
    local_only_product_execution_exercised: bool = False
    network_write_block_product_verified: bool = False
    credentials_absent_product_verified: bool = False
    cancel_timeout_crash_recovery_verified: bool = False
    workspace_reset_artifact_verification_verified: bool = False
    physical_product_entrypoint_exercised: bool = False
    remote_transport_available: bool = False
    status_surface_credentials_present: bool = False
    requirements_satisfied: bool = False
    product_capabilities_satisfied: bool = False
    product_pilot_start_ready: bool = False
    product_pilot_start_authorized: bool = False
    product_pilot_started: bool = False
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    nonce_reusable: bool = False
    evaluation_scope: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_GAP_EVALUATION_SCOPE
    authority: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_GAP_EVALUATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_GAP_EVALUATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCT_PILOT_START_GAP_EVALUATION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PRODUCT_PILOT_START_GAP_EVALUATION_AUTHORITY
            or self.evaluation_scope
            != PILOT_EXACT_TASK_PRODUCT_PILOT_START_GAP_EVALUATION_SCOPE
        ):
            raise PilotExactTaskProductPilotStartGapEvaluationError(
                "product-pilot gap receipt identity is unsupported"
            )
        for name in (
            "requirements_sha256",
            "lineage_attestation_sha256",
            "post_production_activation_attestation_sha256",
            "production_activation_candidate_sha256",
            "implementation_profile_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        for name in (
            "implementation_handoff_git_blob_sha",
            "ui_observer_handoff_git_blob_sha",
            "backend_status_source_git_blob_sha",
            "desktop_observer_source_git_blob_sha",
        ):
            _hex40(getattr(self, name), name=name)
        if self.repository != "Ternedal/ModelRig":
            raise PilotExactTaskProductPilotStartGapEvaluationError(
                "product-pilot gap repository is unsupported"
            )
        for name in (
            "signed_operator_surface",
            "implemented_operator_surface",
            "signed_feature_flag_name",
            "implemented_feature_flag_name",
        ):
            _identifier(getattr(self, name), name=name)
        _route(self.signed_product_route, name="signed_product_route")
        _route(self.implemented_product_route, name="implemented_product_route")
        if (
            self.implemented_operator_surface != IMPLEMENTED_OPERATOR_SURFACE
            or self.implemented_feature_flag_name != IMPLEMENTED_FEATURE_FLAG_NAME
            or self.implemented_product_route != IMPLEMENTED_PRODUCT_ROUTE
            or self.implementation_handoff_git_blob_sha
            != IMPLEMENTATION_HANDOFF_GIT_BLOB_SHA
            or self.ui_observer_handoff_git_blob_sha
            != UI_OBSERVER_HANDOFF_GIT_BLOB_SHA
            or self.backend_status_source_git_blob_sha
            != BACKEND_STATUS_SOURCE_GIT_BLOB_SHA
            or self.desktop_observer_source_git_blob_sha
            != DESKTOP_OBSERVER_SOURCE_GIT_BLOB_SHA
            or self.implementation_profile_sha256 != IMPLEMENTATION_PROFILE_SHA256
        ):
            raise PilotExactTaskProductPilotStartGapEvaluationError(
                "implemented product profile identity mismatch"
            )
        expected_operator = (
            self.signed_operator_surface == self.implemented_operator_surface
        )
        expected_flag = (
            self.signed_feature_flag_name == self.implemented_feature_flag_name
        )
        expected_route = self.signed_product_route == self.implemented_product_route
        if (
            type(self.operator_surface_matches) is not bool
            or type(self.feature_flag_scope_matches) is not bool
            or type(self.product_route_scope_matches) is not bool
            or self.operator_surface_matches is not expected_operator
            or self.feature_flag_scope_matches is not expected_flag
            or self.product_route_scope_matches is not expected_route
        ):
            raise PilotExactTaskProductPilotStartGapEvaluationError(
                "product integration scope comparison mismatch"
            )
        if type(self.blocker_codes) is not tuple:
            raise PilotExactTaskProductPilotStartGapEvaluationError(
                "blocker_codes must be an immutable tuple"
            )
        expected_blockers = _blockers(
            operator_surface_matches=expected_operator,
            feature_flag_scope_matches=expected_flag,
            product_route_scope_matches=expected_route,
        )
        if self.blocker_codes != expected_blockers:
            raise PilotExactTaskProductPilotStartGapEvaluationError(
                "product-pilot blocker set mismatch"
            )
        required_true = (
            "requirements_lineage_bound",
            "implementation_profile_pinned",
            "feature_flag_default_off",
            "status_observer_implemented",
            "manual_refresh_only",
        )
        forced_false = (
            "fresh_human_product_pilot_go_verified",
            "task_registry_ready",
            "runtime_preflight_satisfied",
            "executor_wired",
            "start_control_present",
            "kill_switch_runtime_wired",
            "revoke_runtime_wired",
            "restart_recovery_runtime_wired",
            "canonical_workspace_product_binding_verified",
            "native_windows_isolation_product_reverified",
            "trusted_git_closure_product_reverified",
            "local_only_product_execution_exercised",
            "network_write_block_product_verified",
            "credentials_absent_product_verified",
            "cancel_timeout_crash_recovery_verified",
            "workspace_reset_artifact_verification_verified",
            "physical_product_entrypoint_exercised",
            "remote_transport_available",
            "status_surface_credentials_present",
            "requirements_satisfied",
            "product_capabilities_satisfied",
            "product_pilot_start_ready",
            "product_pilot_start_authorized",
            "product_pilot_started",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskProductPilotStartGapEvaluationError(
                "required gap evidence must remain true"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductPilotStartGapEvaluationError(
                "gap evidence cannot grant readiness or mutation authority"
            )

    def to_dict(self) -> dict[str, Any]:
        value = {name: getattr(self, name) for name in self.__dataclass_fields__}
        value["blocker_codes"] = list(self.blocker_codes)
        return value

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskProductPilotStartGapEvaluationReceipt":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductPilotStartGapEvaluationError(
                "product-pilot gap receipt fields mismatch"
            )
        data = dict(value)
        blockers = data.get("blocker_codes")
        if not isinstance(blockers, (list, tuple)):
            raise PilotExactTaskProductPilotStartGapEvaluationError(
                "blocker_codes must be an array"
            )
        data["blocker_codes"] = tuple(blockers)
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def evaluate_pilot_exact_task_product_pilot_start_gaps(
    *,
    requirements: PilotExactTaskProductPilotStartRequirements,
    lineage_attestation: PilotExactTaskProductPilotLineageAttestationReceipt,
) -> PilotExactTaskProductPilotStartGapEvaluationReceipt:
    exact_requirements = _replay(
        requirements,
        PilotExactTaskProductPilotStartRequirements,
        name="ADR-DC-096 product-pilot start requirements",
    )
    exact_lineage = _replay(
        lineage_attestation,
        PilotExactTaskProductPilotLineageAttestationReceipt,
        name="ADR-DC-098 product-pilot lineage attestation",
    )
    if (
        exact_requirements.post_production_activation_attestation_sha256
        != exact_lineage.post_production_activation_attestation_sha256
        or exact_requirements.production_activation_candidate_sha256
        != exact_lineage.production_activation_candidate_sha256
        or exact_requirements.repository != exact_lineage.repository
        or exact_requirements.merge_commit_sha != exact_lineage.merge_commit_sha
    ):
        raise PilotExactTaskProductPilotStartGapEvaluationError(
            "ADR-DC-096 requirements and ADR-DC-098 lineage are not the same product-pilot source"
        )
    operator_matches = (
        exact_lineage.operator_surface == IMPLEMENTED_OPERATOR_SURFACE
    )
    flag_matches = (
        exact_lineage.feature_flag_name == IMPLEMENTED_FEATURE_FLAG_NAME
    )
    route_matches = exact_lineage.product_route == IMPLEMENTED_PRODUCT_ROUTE
    return PilotExactTaskProductPilotStartGapEvaluationReceipt(
        requirements_sha256=exact_requirements.sha256,
        lineage_attestation_sha256=exact_lineage.sha256,
        post_production_activation_attestation_sha256=(
            exact_lineage.post_production_activation_attestation_sha256
        ),
        production_activation_candidate_sha256=(
            exact_lineage.production_activation_candidate_sha256
        ),
        repository=exact_lineage.repository,
        merge_commit_sha=exact_lineage.merge_commit_sha,
        signed_operator_surface=exact_lineage.operator_surface,
        implemented_operator_surface=IMPLEMENTED_OPERATOR_SURFACE,
        signed_feature_flag_name=exact_lineage.feature_flag_name,
        implemented_feature_flag_name=IMPLEMENTED_FEATURE_FLAG_NAME,
        signed_product_route=exact_lineage.product_route,
        implemented_product_route=IMPLEMENTED_PRODUCT_ROUTE,
        implementation_handoff_git_blob_sha=IMPLEMENTATION_HANDOFF_GIT_BLOB_SHA,
        ui_observer_handoff_git_blob_sha=UI_OBSERVER_HANDOFF_GIT_BLOB_SHA,
        backend_status_source_git_blob_sha=BACKEND_STATUS_SOURCE_GIT_BLOB_SHA,
        desktop_observer_source_git_blob_sha=DESKTOP_OBSERVER_SOURCE_GIT_BLOB_SHA,
        implementation_profile_sha256=IMPLEMENTATION_PROFILE_SHA256,
        blocker_codes=_blockers(
            operator_surface_matches=operator_matches,
            feature_flag_scope_matches=flag_matches,
            product_route_scope_matches=route_matches,
        ),
        operator_surface_matches=operator_matches,
        feature_flag_scope_matches=flag_matches,
        product_route_scope_matches=route_matches,
    )


__all__ = [
    "PILOT_EXACT_TASK_PRODUCT_PILOT_START_GAP_EVALUATION_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_START_GAP_EVALUATION_AUTHORITY",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_START_GAP_EVALUATION_SCOPE",
    "IMPLEMENTED_OPERATOR_SURFACE",
    "IMPLEMENTED_FEATURE_FLAG_NAME",
    "IMPLEMENTED_PRODUCT_ROUTE",
    "IMPLEMENTATION_HANDOFF_GIT_BLOB_SHA",
    "UI_OBSERVER_HANDOFF_GIT_BLOB_SHA",
    "BACKEND_STATUS_SOURCE_GIT_BLOB_SHA",
    "DESKTOP_OBSERVER_SOURCE_GIT_BLOB_SHA",
    "IMPLEMENTATION_PROFILE_SHA256",
    "KNOWN_BLOCKER_CODES",
    "PilotExactTaskProductPilotStartGapEvaluationError",
    "PilotExactTaskProductPilotStartGapEvaluationReceipt",
    "evaluate_pilot_exact_task_product_pilot_start_gaps",
]
