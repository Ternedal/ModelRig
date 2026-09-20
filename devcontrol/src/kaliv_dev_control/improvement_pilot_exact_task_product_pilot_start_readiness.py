"""ADR-DC-096 v2 authoritative pre-authorization product-pilot start readiness.

The legacy v1 readiness could become positive from post-production activation
alone. v2 closes that authority gap. A positive receipt requires, at the same
time:

* one fresh live ADR-DC-095 post-production activation attestation;
* the exact inert ADR-DC-096 start-requirements manifest rebuilt from that source;
* one live ADR-DC-099 fresh-human-GO task-registry receipt;
* one live authenticated ADR-DC-100 post-production runtime-preflight receipt;
* exact object provenance through ADR-095 -> ADR-098 -> ADR-099 -> ADR-100; and
* <=60 second freshness for post-production state, human GO and runtime preflight.

The receipt means only "ready to request ADR-DC-097 one-shot start
authorization". It performs no durable write, process execution, network I/O,
pilot start, Git/GitHub mutation, deployment or production mutation.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from . import improvement_pilot_exact_task_post_production_activation_attestation as attestation_boundary
from . import improvement_pilot_exact_task_development_task_binding as task_binding_boundary
from . import improvement_pilot_exact_task_product_pilot_start_requirements as requirements_boundary
from . import improvement_pilot_exact_task_product_pilot_lineage_attestation as lineage_boundary
from . import improvement_pilot_exact_task_product_pilot_task_registry as registry_boundary
from . import improvement_pilot_exact_task_product_pilot_runtime_preflight as runtime_boundary

PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-start-readiness-receipt/v2"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_AUTHORITY = (
    "host-evaluated-one-dc-l16-exact-product-pilot-start-readiness-only"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_SCOPE = (
    "fresh-requirements-registry-runtime-bound-product-pilot-start-readiness-v2"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_MAX_AGE_SECONDS = 60

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class PilotExactTaskProductPilotStartReadinessError(ValueError):
    """Required live product-pilot pre-authorization evidence is unsafe."""


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
        raise PilotExactTaskProductPilotStartReadinessError(
            "product-pilot readiness evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskProductPilotStartReadinessError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskProductPilotStartReadinessError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskProductPilotStartReadinessError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str):
        raise PilotExactTaskProductPilotStartReadinessError(f"{name} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PilotExactTaskProductPilotStartReadinessError(
            f"{name} is invalid"
        ) from exc
    if parsed.tzinfo is None or parsed.microsecond:
        raise PilotExactTaskProductPilotStartReadinessError(
            f"{name} must use whole timezone-aware seconds"
        )
    return parsed.astimezone(timezone.utc)


def _utc_seconds(value: Any, *, name: str) -> str:
    return _utc(value, name=name).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _age_seconds(*, earlier: str, later: str, name: str) -> int:
    delta = _utc(later, name=f"{name} later") - _utc(
        earlier, name=f"{name} earlier"
    )
    seconds = int(delta.total_seconds())
    if seconds < 0 or delta.total_seconds() != seconds:
        raise PilotExactTaskProductPilotStartReadinessError(
            f"{name} freshness clock is invalid"
        )
    if seconds > PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_MAX_AGE_SECONDS:
        raise PilotExactTaskProductPilotStartReadinessError(
            f"{name} is stale for product-pilot readiness"
        )
    return seconds


def _validate_source(
    source: attestation_boundary.PilotExactTaskPostProductionActivationAttestationReceipt,
) -> None:
    if (
        type(source)
        is not attestation_boundary.PilotExactTaskPostProductionActivationAttestationReceipt
        or source.attestation_authenticated is not True
    ):
        raise PilotExactTaskProductPilotStartReadinessError(
            "fresh live ADR-DC-095 attestation is required"
        )
    required_true = (
        "production_activation",
        "production_activation_attested",
        "durable_completion_verified",
        "transaction_lock_authenticated",
        "double_observation_matched",
        "preflight_receipt_verified",
        "machine_production_receipt_verified",
        "required_switches_active",
        "environment_matches_post_activation",
    )
    required_false = (
        "manual_intervention_required",
        "production_activation_authorized",
        "remote_write_authorized",
        "product_pilot_started",
        "nonce_reusable",
    )
    if (
        any(getattr(source, name) is not True for name in required_true)
        or any(getattr(source, name) is not False for name in required_false)
    ):
        raise PilotExactTaskProductPilotStartReadinessError(
            "ADR-DC-095 attestation is not inert exact production evidence"
        )


def _require_requirements(
    value: Any,
    source: attestation_boundary.PilotExactTaskPostProductionActivationAttestationReceipt,
) -> requirements_boundary.PilotExactTaskProductPilotStartRequirements:
    if type(value) is not requirements_boundary.PilotExactTaskProductPilotStartRequirements:
        raise PilotExactTaskProductPilotStartReadinessError(
            "exact ADR-DC-096 requirements manifest is required"
        )
    try:
        replayed = requirements_boundary.PilotExactTaskProductPilotStartRequirements.from_mapping(
            value.to_dict()
        )
        expected = (
            requirements_boundary.build_pilot_exact_task_product_pilot_start_requirements(
                source
            )
        )
    except Exception as exc:
        raise PilotExactTaskProductPilotStartReadinessError(
            "ADR-DC-096 requirements manifest could not be revalidated"
        ) from exc
    if (
        replayed != value
        or replayed.sha256 != value.sha256
        or expected != value
        or expected.sha256 != value.sha256
        or value.requirements_satisfied is not False
        or value.product_pilot_ready is not False
        or value.product_pilot_start_authorized is not False
        or value.product_pilot_started is not False
        or value.task_execution_authorized is not False
        or value.remote_write_authorized is not False
        or value.production_activation_authorized is not False
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskProductPilotStartReadinessError(
            "ADR-DC-096 requirements do not exactly match live post-production state"
        )
    return value


def _require_live_registry(value: Any):
    if (
        type(value)
        is not registry_boundary.PilotExactTaskProductPilotTaskRegistryReceipt
        or value.registry_authenticated is not True
        or value.task_registry_ready is not True
        or value.executor_wired is not False
        or value.runtime_preflight_satisfied is not False
        or value.product_pilot_start_ready is not False
        or value.product_pilot_start_authorized is not False
        or value.product_pilot_started is not False
        or value.task_execution_authorized is not False
        or value.remote_write_authorized is not False
        or value.production_activation_authorized is not False
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskProductPilotStartReadinessError(
            "fresh live inert ADR-DC-099 task-registry receipt is required"
        )
    live = registry_boundary._get_live_product_pilot_task_registry_inputs(value)
    if live is None:
        raise PilotExactTaskProductPilotStartReadinessError(
            "ADR-DC-099 live provenance is unavailable"
        )
    return value, live


def _require_live_runtime(value: Any):
    if (
        type(value)
        is not runtime_boundary.PilotExactTaskProductPilotRuntimePreflightReceipt
        or value.preflight_authenticated is not True
        or value.runtime_preflight_satisfied is not True
        or value.product_pilot_start_ready is not False
        or value.product_pilot_start_authorized is not False
        or value.product_pilot_started is not False
        or value.task_execution_authorized is not False
        or value.remote_write_authorized is not False
        or value.production_activation_authorized is not False
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskProductPilotStartReadinessError(
            "fresh live authenticated ADR-DC-100 runtime preflight is required"
        )
    live = runtime_boundary._get_live_runtime_preflight_inputs(value)
    if live is None:
        raise PilotExactTaskProductPilotStartReadinessError(
            "ADR-DC-100 live provenance is unavailable"
        )
    return value, live


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskProductPilotStartReadinessReceipt:
    post_production_activation_attestation_sha256: str
    product_pilot_start_requirements_sha256: str
    product_pilot_lineage_attestation_sha256: str
    product_pilot_task_registry_receipt_sha256: str
    product_pilot_runtime_preflight_receipt_sha256: str
    fresh_human_decision_proof_sha256: str
    host_development_task_registry_sha256: str
    development_task_sha256: str
    production_activation_candidate_sha256: str
    production_activation_completion_source: str
    production_activation_source_receipt_sha256: str
    production_activation_transaction_lock_sha256: str
    environment_after_sha256: str
    output_state_sha256: str
    production_preflight_sha256: str
    machine_production_receipt_sha256: str
    repository: str
    repository_id: str
    merge_commit_sha: str
    promotion_git_sha: str
    operator_surface: str
    selected_pilot_task_id: str
    workspace_root_path_sha256: str
    feature_flag_name: str
    product_route: str
    fixed_command_id: str
    post_production_attested_at_utc: str
    human_go_verified_at_utc: str
    runtime_preflight_verified_at_utc: str
    evaluated_at_utc: str
    attestation_age_seconds: int
    human_go_age_seconds: int
    runtime_preflight_age_seconds: int
    production_activation: bool = True
    production_activation_attested: bool = True
    post_production_state_verified: bool = True
    requirements_manifest_verified: bool = True
    pre_authorization_requirements_satisfied: bool = True
    fresh_human_product_pilot_go_verified: bool = True
    explicit_pilot_scope_verified: bool = True
    product_integration_selection_reverified: bool = True
    runtime_preflight_reverified: bool = True
    allowlisted_task_registry_verified: bool = True
    canonical_workspace_revalidated: bool = True
    feature_flag_default_off_verified: bool = True
    local_only_scope_verified: bool = True
    manual_operator_invocation_verified: bool = True
    kill_switch_armed: bool = True
    revoke_not_asserted: bool = True
    restart_recovery_verified: bool = True
    network_writes_blocked_verified: bool = True
    credentials_absent_verified: bool = True
    unattended_cadence_forbidden_verified: bool = True
    general_shell_forbidden_verified: bool = True
    model_defined_commands_forbidden_verified: bool = True
    exact_source_binding_verified: bool = True
    exact_toolchain_binding_verified: bool = True
    one_shot_start_authorization_required: bool = True
    host_local_replay_guard_required: bool = True
    start_receipt_required: bool = True
    product_pilot_start_ready: bool = True
    product_pilot_start_authorized: bool = False
    product_pilot_started: bool = False
    task_execution_authorized: bool = False
    local_commit_authorized: bool = False
    manual_intervention_required: bool = False
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
    next_boundary_authorization_required: bool = True
    readiness_scope: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_SCOPE
    authority: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_AUTHORITY
            or self.readiness_scope
            != PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_SCOPE
        ):
            raise PilotExactTaskProductPilotStartReadinessError(
                "product-pilot readiness identity is unsupported"
            )
        for name in (
            "post_production_activation_attestation_sha256",
            "product_pilot_start_requirements_sha256",
            "product_pilot_lineage_attestation_sha256",
            "product_pilot_task_registry_receipt_sha256",
            "product_pilot_runtime_preflight_receipt_sha256",
            "fresh_human_decision_proof_sha256",
            "host_development_task_registry_sha256",
            "development_task_sha256",
            "production_activation_candidate_sha256",
            "production_activation_source_receipt_sha256",
            "production_activation_transaction_lock_sha256",
            "environment_after_sha256",
            "output_state_sha256",
            "production_preflight_sha256",
            "machine_production_receipt_sha256",
            "workspace_root_path_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        _hex40(self.promotion_git_sha, name="promotion_git_sha")
        if self.production_activation_completion_source not in {"transaction", "recovery"}:
            raise PilotExactTaskProductPilotStartReadinessError(
                "production activation completion source is unsupported"
            )
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskProductPilotStartReadinessError(
                "product-pilot readiness repository identity is invalid"
            )
        for name in (
            "operator_surface",
            "selected_pilot_task_id",
            "feature_flag_name",
            "fixed_command_id",
        ):
            _identifier(getattr(self, name), name=name)
        if (
            not isinstance(self.product_route, str)
            or not self.product_route.startswith("/")
            or "\x00" in self.product_route
            or len(self.product_route.encode("utf-8")) > 512
        ):
            raise PilotExactTaskProductPilotStartReadinessError(
                "product_route is invalid"
            )

        expected_post = _age_seconds(
            earlier=self.post_production_attested_at_utc,
            later=self.evaluated_at_utc,
            name="post-production attestation",
        )
        expected_human = _age_seconds(
            earlier=self.human_go_verified_at_utc,
            later=self.evaluated_at_utc,
            name="fresh human GO",
        )
        expected_runtime = _age_seconds(
            earlier=self.runtime_preflight_verified_at_utc,
            later=self.evaluated_at_utc,
            name="runtime preflight",
        )
        for supplied, expected, name in (
            (self.attestation_age_seconds, expected_post, "attestation_age_seconds"),
            (self.human_go_age_seconds, expected_human, "human_go_age_seconds"),
            (
                self.runtime_preflight_age_seconds,
                expected_runtime,
                "runtime_preflight_age_seconds",
            ),
        ):
            if type(supplied) is not int or supplied != expected:
                raise PilotExactTaskProductPilotStartReadinessError(
                    f"{name} is inconsistent"
                )

        required_true = (
            "production_activation",
            "production_activation_attested",
            "post_production_state_verified",
            "requirements_manifest_verified",
            "pre_authorization_requirements_satisfied",
            "fresh_human_product_pilot_go_verified",
            "explicit_pilot_scope_verified",
            "product_integration_selection_reverified",
            "runtime_preflight_reverified",
            "allowlisted_task_registry_verified",
            "canonical_workspace_revalidated",
            "feature_flag_default_off_verified",
            "local_only_scope_verified",
            "manual_operator_invocation_verified",
            "kill_switch_armed",
            "revoke_not_asserted",
            "restart_recovery_verified",
            "network_writes_blocked_verified",
            "credentials_absent_verified",
            "unattended_cadence_forbidden_verified",
            "general_shell_forbidden_verified",
            "model_defined_commands_forbidden_verified",
            "exact_source_binding_verified",
            "exact_toolchain_binding_verified",
            "one_shot_start_authorization_required",
            "host_local_replay_guard_required",
            "start_receipt_required",
            "product_pilot_start_ready",
            "next_boundary_authorization_required",
        )
        forced_false = (
            "product_pilot_start_authorized",
            "product_pilot_started",
            "task_execution_authorized",
            "local_commit_authorized",
            "manual_intervention_required",
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
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskProductPilotStartReadinessError(
                "product-pilot readiness lacks mandatory pre-authorization evidence"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductPilotStartReadinessError(
                "product-pilot readiness retains forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def readiness_authenticated(self) -> bool:
        return _get_live_readiness_source(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductPilotStartReadinessError(
                "product-pilot readiness fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: PilotExactTaskProductPilotStartReadinessReceipt,
        *,
        source: attestation_boundary.PilotExactTaskPostProductionActivationAttestationReceipt,
        requirements: requirements_boundary.PilotExactTaskProductPilotStartRequirements,
        task_registry: registry_boundary.PilotExactTaskProductPilotTaskRegistryReceipt,
        runtime_preflight: runtime_boundary.PilotExactTaskProductPilotRuntimePreflightReceipt,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            weakref.ref(source),
            source.sha256,
            requirements,
            task_registry,
            runtime_preflight,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        (
            pid,
            digest,
            receipt_ref,
            source_ref,
            source_digest,
            requirements,
            task_registry,
            runtime_preflight,
        ) = entry
        source = source_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or receipt.sha256 != digest
            or source is None
            or source.sha256 != source_digest
            or source.attestation_authenticated is not True
            or requirements.sha256 != receipt.product_pilot_start_requirements_sha256
            or task_registry.registry_authenticated is not True
            or task_registry.sha256 != receipt.product_pilot_task_registry_receipt_sha256
            or runtime_preflight.preflight_authenticated is not True
            or runtime_preflight.sha256
            != receipt.product_pilot_runtime_preflight_receipt_sha256
        ):
            return None
        return {
            "source": source,
            "requirements": requirements,
            "task_registry": task_registry,
            "runtime_preflight": runtime_preflight,
        }

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_readiness_authenticated, _get_live_readiness_source = _live_registry()


def _evaluate_verified_pilot_exact_task_product_pilot_start_readiness(
    post_production_activation_attestation: (
        attestation_boundary.PilotExactTaskPostProductionActivationAttestationReceipt
    ),
    product_pilot_start_requirements: (
        requirements_boundary.PilotExactTaskProductPilotStartRequirements
    ),
    product_pilot_task_registry_receipt: (
        registry_boundary.PilotExactTaskProductPilotTaskRegistryReceipt
    ),
    product_pilot_runtime_preflight_receipt: (
        runtime_boundary.PilotExactTaskProductPilotRuntimePreflightReceipt
    ),
    *,
    now_provider: Callable[[], str],
) -> PilotExactTaskProductPilotStartReadinessReceipt:
    source = post_production_activation_attestation
    _validate_source(source)
    requirements = _require_requirements(product_pilot_start_requirements, source)
    task_registry, registry_inputs = _require_live_registry(
        product_pilot_task_registry_receipt
    )
    runtime_preflight, runtime_inputs = _require_live_runtime(
        product_pilot_runtime_preflight_receipt
    )

    lineage = registry_inputs["lineage_attestation"]
    lineage_inputs = lineage_boundary._get_live_product_pilot_lineage_inputs(lineage)
    if lineage_inputs is None:
        raise PilotExactTaskProductPilotStartReadinessError(
            "live ADR-DC-098 lineage provenance is unavailable"
        )
    if lineage_inputs.get("post_production_activation_attestation") is not source:
        raise PilotExactTaskProductPilotStartReadinessError(
            "ADR-DC-098 lineage is not object-bound to supplied live ADR-DC-095 source"
        )
    if runtime_inputs.get("task_registry_receipt") is not task_registry:
        raise PilotExactTaskProductPilotStartReadinessError(
            "ADR-DC-100 is not object-bound to supplied live ADR-DC-099 registry"
        )

    fresh_go = registry_inputs["fresh_human_go"]
    development_task = registry_inputs["development_task"]
    if (
        fresh_go.sha256 != task_registry.fresh_human_decision_proof_sha256
        or fresh_go.pilot_go_authorized is not True
        or fresh_go.decision not in {"go", "go_with_conditions"}
        or task_registry.lineage_attestation_sha256 != lineage.sha256
        or runtime_preflight.task_registry_receipt_sha256 != task_registry.sha256
        or runtime_preflight.lineage_attestation_sha256 != lineage.sha256
        or runtime_preflight.post_production_activation_attestation_sha256
        != source.sha256
        or requirements.post_production_activation_attestation_sha256 != source.sha256
        or requirements.production_activation_candidate_sha256
        != source.production_activation_candidate_sha256
        or task_registry.repository != source.repository
        or runtime_preflight.repository != source.repository
        or task_registry.merge_commit_sha != source.merge_commit_sha
        or runtime_preflight.merge_commit_sha != source.merge_commit_sha
        or task_registry.host_development_task_registry_sha256
        != runtime_preflight.host_development_task_registry_sha256
        or task_registry.development_task_sha256
        != runtime_preflight.development_task_sha256
        or task_registry.development_task_sha256
        != task_binding_boundary._task_sha256(development_task)
        or task_registry.operator_surface != runtime_preflight.operator_surface
        or task_registry.selected_pilot_task_id
        != runtime_preflight.selected_pilot_task_id
        or task_registry.workspace_root_path_sha256
        != runtime_preflight.workspace_root_path_sha256
        or task_registry.feature_flag_name != runtime_preflight.feature_flag_name
        or task_registry.product_route != runtime_preflight.product_route
        or task_registry.fixed_command_id != runtime_preflight.fixed_command_id
    ):
        raise PilotExactTaskProductPilotStartReadinessError(
            "ADR-096/098/099/100 exact product-pilot scope binding mismatch"
        )

    evaluated_at = _utc_seconds(now_provider(), name="evaluated_at_utc")
    post_at = _utc_seconds(
        source.second_observed_at_utc,
        name="post_production_attested_at_utc",
    )
    human_at = _utc_seconds(
        fresh_go.verified_at_utc,
        name="human_go_verified_at_utc",
    )
    runtime_at = _utc_seconds(
        runtime_preflight.verified_at_utc,
        name="runtime_preflight_verified_at_utc",
    )
    post_age = _age_seconds(
        earlier=post_at, later=evaluated_at, name="post-production attestation"
    )
    human_age = _age_seconds(
        earlier=human_at, later=evaluated_at, name="fresh human GO"
    )
    runtime_age = _age_seconds(
        earlier=runtime_at, later=evaluated_at, name="runtime preflight"
    )

    receipt = PilotExactTaskProductPilotStartReadinessReceipt(
        post_production_activation_attestation_sha256=source.sha256,
        product_pilot_start_requirements_sha256=requirements.sha256,
        product_pilot_lineage_attestation_sha256=lineage.sha256,
        product_pilot_task_registry_receipt_sha256=task_registry.sha256,
        product_pilot_runtime_preflight_receipt_sha256=runtime_preflight.sha256,
        fresh_human_decision_proof_sha256=fresh_go.sha256,
        host_development_task_registry_sha256=(
            task_registry.host_development_task_registry_sha256
        ),
        development_task_sha256=task_registry.development_task_sha256,
        production_activation_candidate_sha256=(
            source.production_activation_candidate_sha256
        ),
        production_activation_completion_source=(
            source.production_activation_completion_source
        ),
        production_activation_source_receipt_sha256=(
            source.production_activation_source_receipt_sha256
        ),
        production_activation_transaction_lock_sha256=(
            source.production_activation_transaction_lock_sha256
        ),
        environment_after_sha256=source.environment_after_sha256,
        output_state_sha256=source.output_state_sha256,
        production_preflight_sha256=source.production_preflight_sha256,
        machine_production_receipt_sha256=source.machine_production_receipt_sha256,
        repository=source.repository,
        repository_id=source.repository_id,
        merge_commit_sha=source.merge_commit_sha,
        promotion_git_sha=source.promotion_git_sha,
        operator_surface=task_registry.operator_surface,
        selected_pilot_task_id=task_registry.selected_pilot_task_id,
        workspace_root_path_sha256=task_registry.workspace_root_path_sha256,
        feature_flag_name=task_registry.feature_flag_name,
        product_route=task_registry.product_route,
        fixed_command_id=task_registry.fixed_command_id,
        post_production_attested_at_utc=post_at,
        human_go_verified_at_utc=human_at,
        runtime_preflight_verified_at_utc=runtime_at,
        evaluated_at_utc=evaluated_at,
        attestation_age_seconds=post_age,
        human_go_age_seconds=human_age,
        runtime_preflight_age_seconds=runtime_age,
        product_integration_selection_reverified=(
            runtime_preflight.product_integration_selection_reverified
        ),
        canonical_workspace_revalidated=(
            runtime_preflight.canonical_workspace_revalidated
        ),
        feature_flag_default_off_verified=(
            runtime_preflight.feature_flag_default_off_verified
        ),
        local_only_scope_verified=runtime_preflight.local_only_scope_verified,
        manual_operator_invocation_verified=(
            runtime_preflight.manual_operator_invocation_verified
        ),
        kill_switch_armed=runtime_preflight.kill_switch_armed,
        revoke_not_asserted=runtime_preflight.revoke_not_asserted,
        restart_recovery_verified=runtime_preflight.restart_recovery_verified,
        network_writes_blocked_verified=(
            runtime_preflight.network_writes_blocked_verified
        ),
        credentials_absent_verified=runtime_preflight.credentials_absent_verified,
        unattended_cadence_forbidden_verified=(
            runtime_preflight.unattended_cadence_forbidden_verified
        ),
        general_shell_forbidden_verified=(
            runtime_preflight.general_shell_forbidden_verified
        ),
        model_defined_commands_forbidden_verified=(
            runtime_preflight.model_defined_commands_forbidden_verified
        ),
        exact_source_binding_verified=(
            runtime_preflight.exact_source_binding_verified
        ),
        exact_toolchain_binding_verified=(
            runtime_preflight.exact_toolchain_binding_verified
        ),
    )
    _mark_readiness_authenticated(
        receipt,
        source=source,
        requirements=requirements,
        task_registry=task_registry,
        runtime_preflight=runtime_preflight,
    )
    if receipt.readiness_authenticated is not True:
        raise PilotExactTaskProductPilotStartReadinessError(
            "product-pilot readiness lost exact live provenance"
        )
    return receipt


def evaluate_pilot_exact_task_product_pilot_start_readiness(
    post_production_activation_attestation: (
        attestation_boundary.PilotExactTaskPostProductionActivationAttestationReceipt
    ),
    product_pilot_start_requirements: (
        requirements_boundary.PilotExactTaskProductPilotStartRequirements
    ),
    product_pilot_task_registry_receipt: (
        registry_boundary.PilotExactTaskProductPilotTaskRegistryReceipt
    ),
    product_pilot_runtime_preflight_receipt: (
        runtime_boundary.PilotExactTaskProductPilotRuntimePreflightReceipt
    ),
) -> PilotExactTaskProductPilotStartReadinessReceipt:
    """Evaluate complete fresh pre-authorization evidence without starting the pilot."""
    return _evaluate_verified_pilot_exact_task_product_pilot_start_readiness(
        post_production_activation_attestation,
        product_pilot_start_requirements,
        product_pilot_task_registry_receipt,
        product_pilot_runtime_preflight_receipt,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
