"""ADR-DC-096 inert product-pilot start requirements after production activation.

This boundary consumes one fresh live ADR-DC-095 post-production activation
attestation and freezes the requirements a later, separate human-authorized
DC-L16 product-pilot start must satisfy.

It performs no host mutation, task execution, local commit, remote write,
release, deployment, production activation, or product-pilot start.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from . import improvement_pilot_exact_task_post_production_activation_attestation as attestation_boundary

PILOT_EXACT_TASK_PRODUCT_PILOT_START_REQUIREMENTS_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-start-requirements/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_REQUIREMENTS_AUTHORITY = (
    "dc-l16-post-production-product-pilot-start-requirements-only"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_REQUIREMENTS_SCOPE = (
    "inert-post-production-product-pilot-start-requirements-v1"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")


class PilotExactTaskProductPilotStartRequirementsError(ValueError):
    """Product-pilot start requirements are malformed or over-authorizing."""


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
        raise PilotExactTaskProductPilotStartRequirementsError(
            "product-pilot start requirements are not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskProductPilotStartRequirementsError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskProductPilotStartRequirementsError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str):
        raise PilotExactTaskProductPilotStartRequirementsError(f"{name} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PilotExactTaskProductPilotStartRequirementsError(
            f"{name} is invalid"
        ) from exc
    if parsed.tzinfo is None or parsed.microsecond:
        raise PilotExactTaskProductPilotStartRequirementsError(
            f"{name} must use whole UTC seconds"
        )
    return parsed.astimezone(timezone.utc)


def _require_live_attestation(
    value: Any,
) -> attestation_boundary.PilotExactTaskPostProductionActivationAttestationReceipt:
    expected_type = (
        attestation_boundary.PilotExactTaskPostProductionActivationAttestationReceipt
    )
    if type(value) is not expected_type:
        raise PilotExactTaskProductPilotStartRequirementsError(
            "exact ADR-DC-095 post-production activation attestation is required"
        )
    try:
        replayed = expected_type.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskProductPilotStartRequirementsError(
            "ADR-DC-095 attestation replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskProductPilotStartRequirementsError(
            "ADR-DC-095 attestation replay identity mismatch"
        )
    if value.attestation_authenticated is not True:
        raise PilotExactTaskProductPilotStartRequirementsError(
            "fresh live ADR-DC-095 attestation provenance is required"
        )
    if (
        value.production_activation is not True
        or value.production_activation_attested is not True
        or value.durable_completion_verified is not True
        or value.transaction_lock_authenticated is not True
        or value.double_observation_matched is not True
        or value.preflight_receipt_verified is not True
        or value.machine_production_receipt_verified is not True
        or value.required_switches_active is not True
        or value.environment_matches_post_activation is not True
        or value.manual_intervention_required is not False
        or value.production_activation_authorized is not False
        or value.remote_write_authorized is not False
        or value.product_pilot_started is not False
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskProductPilotStartRequirementsError(
            "ADR-DC-095 attestation is not exact inert activated-state evidence"
        )
    return value


def _attestation_binding(
    receipt: attestation_boundary.PilotExactTaskPostProductionActivationAttestationReceipt,
) -> dict[str, Any]:
    live = _require_live_attestation(receipt)
    return {
        "post_production_activation_attestation_sha256": live.sha256,
        "production_activation_completion_source": (
            live.production_activation_completion_source
        ),
        "production_activation_source_receipt_sha256": (
            live.production_activation_source_receipt_sha256
        ),
        "production_activation_authorization_sha256": (
            live.production_activation_authorization_sha256
        ),
        "production_activation_candidate_sha256": (
            live.production_activation_candidate_sha256
        ),
        "environment_after_sha256": live.environment_after_sha256,
        "repository": live.repository,
        "repository_id": live.repository_id,
        "merge_commit_sha": live.merge_commit_sha,
        "promotion_git_sha": live.promotion_git_sha,
        "source_completed_at_utc": live.source_completed_at_utc,
        "post_production_first_observed_at_utc": live.first_observed_at_utc,
        "post_production_second_observed_at_utc": live.second_observed_at_utc,
    }


@dataclass(frozen=True, slots=True)
class PilotExactTaskProductPilotStartRequirements:
    post_production_activation_attestation_sha256: str
    production_activation_completion_source: str
    production_activation_source_receipt_sha256: str
    production_activation_authorization_sha256: str
    production_activation_candidate_sha256: str
    environment_after_sha256: str
    repository: str
    repository_id: str
    merge_commit_sha: str
    promotion_git_sha: str
    source_completed_at_utc: str
    post_production_first_observed_at_utc: str
    post_production_second_observed_at_utc: str
    production_activation: bool = True
    production_activation_attested: bool = True
    post_production_activation_attestation_required: bool = True
    fresh_post_production_activation_attestation_required: bool = True
    fresh_human_product_pilot_go_required: bool = True
    explicit_pilot_scope_required: bool = True
    product_integration_selection_reverification_required: bool = True
    runtime_preflight_reverification_required: bool = True
    allowlisted_task_registry_required: bool = True
    canonical_workspace_revalidation_required: bool = True
    feature_flag_default_off_required: bool = True
    local_only_scope_required: bool = True
    manual_operator_invocation_required: bool = True
    kill_switch_armed_required: bool = True
    revoke_not_asserted_required: bool = True
    restart_recovery_required: bool = True
    network_writes_blocked_required: bool = True
    credentials_absent_required: bool = True
    unattended_cadence_forbidden: bool = True
    general_shell_forbidden: bool = True
    model_defined_commands_forbidden: bool = True
    exact_source_binding_required: bool = True
    exact_toolchain_binding_required: bool = True
    one_shot_start_authorization_required: bool = True
    host_local_replay_guard_required: bool = True
    start_receipt_required: bool = True
    requirements_satisfied: bool = False
    product_pilot_ready: bool = False
    product_pilot_start_authorized: bool = False
    product_pilot_started: bool = False
    task_execution_authorized: bool = False
    local_commit_authorized: bool = False
    promotion_gate_execution_authorized: bool = False
    production_env_mutation_authorized: bool = False
    appliance_restart_authorized: bool = False
    production_receipt_write_authorized: bool = False
    production_activation_authorized: bool = False
    success_deployment_status_authorized: bool = False
    deployment_status_mutation_authorized: bool = False
    deployment_mutation_authorized: bool = False
    deploy_authorized: bool = False
    remote_write_authorized: bool = False
    release_authorized: bool = False
    tag_write_authorized: bool = False
    release_mutation_authorized: bool = False
    merge_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    nonce_reusable: bool = False
    requirements_scope: str = (
        PILOT_EXACT_TASK_PRODUCT_PILOT_START_REQUIREMENTS_SCOPE
    )
    authority: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_REQUIREMENTS_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_REQUIREMENTS_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCT_PILOT_START_REQUIREMENTS_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PRODUCT_PILOT_START_REQUIREMENTS_AUTHORITY
            or self.requirements_scope
            != PILOT_EXACT_TASK_PRODUCT_PILOT_START_REQUIREMENTS_SCOPE
        ):
            raise PilotExactTaskProductPilotStartRequirementsError(
                "product-pilot start requirements identity is unsupported"
            )
        if self.production_activation_completion_source not in {
            "transaction",
            "recovery",
        }:
            raise PilotExactTaskProductPilotStartRequirementsError(
                "production activation completion source is unsupported"
            )
        for name in (
            "post_production_activation_attestation_sha256",
            "production_activation_source_receipt_sha256",
            "production_activation_authorization_sha256",
            "production_activation_candidate_sha256",
            "environment_after_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        _hex40(self.promotion_git_sha, name="promotion_git_sha")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskProductPilotStartRequirementsError(
                "product-pilot start source identity is invalid"
            )
        source_completed = _utc(
            self.source_completed_at_utc,
            name="source_completed_at_utc",
        )
        first = _utc(
            self.post_production_first_observed_at_utc,
            name="post_production_first_observed_at_utc",
        )
        second = _utc(
            self.post_production_second_observed_at_utc,
            name="post_production_second_observed_at_utc",
        )
        if first < source_completed or second < first:
            raise PilotExactTaskProductPilotStartRequirementsError(
                "product-pilot start source timestamps are invalid"
            )

        required_true = (
            "production_activation",
            "production_activation_attested",
            "post_production_activation_attestation_required",
            "fresh_post_production_activation_attestation_required",
            "fresh_human_product_pilot_go_required",
            "explicit_pilot_scope_required",
            "product_integration_selection_reverification_required",
            "runtime_preflight_reverification_required",
            "allowlisted_task_registry_required",
            "canonical_workspace_revalidation_required",
            "feature_flag_default_off_required",
            "local_only_scope_required",
            "manual_operator_invocation_required",
            "kill_switch_armed_required",
            "revoke_not_asserted_required",
            "restart_recovery_required",
            "network_writes_blocked_required",
            "credentials_absent_required",
            "unattended_cadence_forbidden",
            "general_shell_forbidden",
            "model_defined_commands_forbidden",
            "exact_source_binding_required",
            "exact_toolchain_binding_required",
            "one_shot_start_authorization_required",
            "host_local_replay_guard_required",
            "start_receipt_required",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskProductPilotStartRequirementsError(
                "all product-pilot start requirements must stay enabled"
            )

        forced_false = (
            "requirements_satisfied",
            "product_pilot_ready",
            "product_pilot_start_authorized",
            "product_pilot_started",
            "task_execution_authorized",
            "local_commit_authorized",
            "promotion_gate_execution_authorized",
            "production_env_mutation_authorized",
            "appliance_restart_authorized",
            "production_receipt_write_authorized",
            "production_activation_authorized",
            "success_deployment_status_authorized",
            "deployment_status_mutation_authorized",
            "deployment_mutation_authorized",
            "deploy_authorized",
            "remote_write_authorized",
            "release_authorized",
            "tag_write_authorized",
            "release_mutation_authorized",
            "merge_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductPilotStartRequirementsError(
                "requirements manifest cannot grant pilot or mutation authority"
            )

    @classmethod
    def from_mapping(
        cls,
        value: Any,
    ) -> "PilotExactTaskProductPilotStartRequirements":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductPilotStartRequirementsError(
                "product-pilot start requirements fields mismatch"
            )
        return cls(**dict(value))

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def build_pilot_exact_task_product_pilot_start_requirements(
    attestation: (
        attestation_boundary.PilotExactTaskPostProductionActivationAttestationReceipt
    ),
) -> PilotExactTaskProductPilotStartRequirements:
    live = _require_live_attestation(attestation)
    return PilotExactTaskProductPilotStartRequirements(
        **_attestation_binding(live),
    )


__all__ = [
    "PILOT_EXACT_TASK_PRODUCT_PILOT_START_REQUIREMENTS_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_START_REQUIREMENTS_AUTHORITY",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_START_REQUIREMENTS_SCOPE",
    "PilotExactTaskProductPilotStartRequirementsError",
    "PilotExactTaskProductPilotStartRequirements",
    "build_pilot_exact_task_product_pilot_start_requirements",
]
