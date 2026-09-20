"""ADR-DC-100 fresh post-production product-pilot runtime preflight.

This boundary consumes one live ADR-DC-099 task-registry receipt, binds a fresh
host-observer claim to that exact product-pilot scope, and verifies the claim
with the existing host-pinned ADR-DC-023 runtime-preflight Ed25519 authority.

A verified receipt may establish only current runtime-preflight satisfaction.
It cannot mark the product pilot start-ready, authorize or start the pilot,
execute a task, mutate Git/GitHub, deploy, or reactivate production.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import weakref
from typing import Any, Mapping

from .asymmetric_authority import (
    AsymmetricAuthorityError,
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
)
from . import improvement_pilot_exact_task_product_pilot_task_registry as registry_boundary
from .improvement_pilot_runtime_preflight_attestation import (
    PILOT_RUNTIME_PREFLIGHT_ATTESTATION_ISSUER_SYSTEM_ID,
)
from ._improvement_pilot_runtime_preflight_attestation_production_boundary import (
    PilotRuntimePreflightAttestationProductionBoundaryError,
    _canonical_pilot_runtime_preflight_attestation_verifier,
)

PILOT_EXACT_TASK_PRODUCT_PILOT_RUNTIME_PREFLIGHT_ATTESTATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-runtime-preflight-attestation/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_RUNTIME_PREFLIGHT_ATTESTATION_AUTHORITY = (
    "dc-l16-product-pilot-runtime-preflight-attestation-claim-only"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_RUNTIME_PREFLIGHT_RECEIPT_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-runtime-preflight-receipt/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_RUNTIME_PREFLIGHT_RECEIPT_AUTHORITY = (
    "verified-dc-l16-product-pilot-runtime-preflight-only"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_RUNTIME_PREFLIGHT_MAX_AGE_SECONDS = 60

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")

EVIDENCE_FIELDS = (
    "product_integration_selection_evidence_sha256",
    "task_registry_evidence_sha256",
    "canonical_workspace_evidence_sha256",
    "feature_flag_default_off_evidence_sha256",
    "local_only_scope_evidence_sha256",
    "manual_operator_invocation_evidence_sha256",
    "kill_switch_evidence_sha256",
    "revoke_state_evidence_sha256",
    "restart_recovery_evidence_sha256",
    "network_write_block_evidence_sha256",
    "credentials_absent_evidence_sha256",
    "unattended_cadence_evidence_sha256",
    "general_shell_forbidden_evidence_sha256",
    "model_defined_commands_forbidden_evidence_sha256",
    "exact_source_binding_evidence_sha256",
    "exact_toolchain_binding_evidence_sha256",
)

CHECK_FIELDS = (
    "product_integration_selection_reverified",
    "task_registry_reverified",
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
)


class PilotExactTaskProductPilotRuntimePreflightError(ValueError):
    """Fresh runtime-preflight evidence is stale, rebound or over-authorizing."""


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
        raise PilotExactTaskProductPilotRuntimePreflightError(
            "product-pilot runtime-preflight evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskProductPilotRuntimePreflightError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskProductPilotRuntimePreflightError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskProductPilotRuntimePreflightError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise PilotExactTaskProductPilotRuntimePreflightError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str):
        raise PilotExactTaskProductPilotRuntimePreflightError(f"{name} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PilotExactTaskProductPilotRuntimePreflightError(f"{name} is invalid") from exc
    if parsed.tzinfo is None or parsed.microsecond:
        raise PilotExactTaskProductPilotRuntimePreflightError(
            f"{name} must use whole timezone-aware seconds"
        )
    return parsed.astimezone(timezone.utc)


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_live_registry(value: Any):
    if (
        type(value)
        is not registry_boundary.PilotExactTaskProductPilotTaskRegistryReceipt
        or value.registry_authenticated is not True
    ):
        raise PilotExactTaskProductPilotRuntimePreflightError(
            "fresh live ADR-DC-099 task-registry receipt is required"
        )
    inputs = registry_boundary._get_live_product_pilot_task_registry_inputs(value)
    if inputs is None:
        raise PilotExactTaskProductPilotRuntimePreflightError(
            "ADR-DC-099 live registry provenance is unavailable"
        )
    return value, inputs


def _strict_hashes(value: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != set(EVIDENCE_FIELDS):
        raise PilotExactTaskProductPilotRuntimePreflightError(
            "runtime-preflight evidence digest fields mismatch"
        )
    return {name: _hex64(value[name], name=name) for name in EVIDENCE_FIELDS}


def _strict_checks(value: Mapping[str, bool]) -> dict[str, bool]:
    if not isinstance(value, Mapping) or set(value) != set(CHECK_FIELDS):
        raise PilotExactTaskProductPilotRuntimePreflightError(
            "runtime-preflight check fields mismatch"
        )
    result: dict[str, bool] = {}
    for name in CHECK_FIELDS:
        item = value[name]
        if type(item) is not bool:
            raise PilotExactTaskProductPilotRuntimePreflightError(
                f"{name} must be boolean"
            )
        result[name] = item
    return result


@dataclass(frozen=True, slots=True)
class PilotExactTaskProductPilotRuntimePreflightAttestation:
    task_registry_receipt_sha256: str
    lineage_attestation_sha256: str
    post_production_activation_attestation_sha256: str
    host_development_task_registry_sha256: str
    development_task_sha256: str
    repository: str
    merge_commit_sha: str
    operator_surface: str
    selected_pilot_task_id: str
    workspace_root_path_sha256: str
    feature_flag_name: str
    product_route: str
    fixed_command_id: str
    observer_actor_id: str
    observer_host_id: str
    observed_at_utc: str
    product_integration_selection_evidence_sha256: str
    task_registry_evidence_sha256: str
    canonical_workspace_evidence_sha256: str
    feature_flag_default_off_evidence_sha256: str
    local_only_scope_evidence_sha256: str
    manual_operator_invocation_evidence_sha256: str
    kill_switch_evidence_sha256: str
    revoke_state_evidence_sha256: str
    restart_recovery_evidence_sha256: str
    network_write_block_evidence_sha256: str
    credentials_absent_evidence_sha256: str
    unattended_cadence_evidence_sha256: str
    general_shell_forbidden_evidence_sha256: str
    model_defined_commands_forbidden_evidence_sha256: str
    exact_source_binding_evidence_sha256: str
    exact_toolchain_binding_evidence_sha256: str
    product_integration_selection_reverified: bool
    task_registry_reverified: bool
    canonical_workspace_revalidated: bool
    feature_flag_default_off_verified: bool
    local_only_scope_verified: bool
    manual_operator_invocation_verified: bool
    kill_switch_armed: bool
    revoke_not_asserted: bool
    restart_recovery_verified: bool
    network_writes_blocked_verified: bool
    credentials_absent_verified: bool
    unattended_cadence_forbidden_verified: bool
    general_shell_forbidden_verified: bool
    model_defined_commands_forbidden_verified: bool
    exact_source_binding_verified: bool
    exact_toolchain_binding_verified: bool
    runtime_preflight_satisfied: bool = False
    product_pilot_start_ready: bool = False
    product_pilot_start_authorized: bool = False
    product_pilot_started: bool = False
    task_execution_authorized: bool = False
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    nonce_reusable: bool = False
    authority: str = PILOT_EXACT_TASK_PRODUCT_PILOT_RUNTIME_PREFLIGHT_ATTESTATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_RUNTIME_PREFLIGHT_ATTESTATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCT_PILOT_RUNTIME_PREFLIGHT_ATTESTATION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PRODUCT_PILOT_RUNTIME_PREFLIGHT_ATTESTATION_AUTHORITY
        ):
            raise PilotExactTaskProductPilotRuntimePreflightError(
                "runtime-preflight attestation identity is unsupported"
            )
        for name in (
            "task_registry_receipt_sha256",
            "lineage_attestation_sha256",
            "post_production_activation_attestation_sha256",
            "host_development_task_registry_sha256",
            "development_task_sha256",
            "workspace_root_path_sha256",
            *EVIDENCE_FIELDS,
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        if self.repository != "Ternedal/ModelRig":
            raise PilotExactTaskProductPilotRuntimePreflightError(
                "runtime-preflight repository is unsupported"
            )
        for name in (
            "operator_surface",
            "selected_pilot_task_id",
            "feature_flag_name",
            "fixed_command_id",
            "observer_host_id",
        ):
            _identifier(getattr(self, name), name=name)
        _actor(self.observer_actor_id, name="observer_actor_id")
        if (
            not isinstance(self.product_route, str)
            or not self.product_route.startswith("/")
            or "\x00" in self.product_route
            or len(self.product_route.encode("utf-8")) > 512
        ):
            raise PilotExactTaskProductPilotRuntimePreflightError(
                "product_route is invalid"
            )
        _utc(self.observed_at_utc, name="observed_at_utc")
        for name in CHECK_FIELDS:
            if type(getattr(self, name)) is not bool:
                raise PilotExactTaskProductPilotRuntimePreflightError(
                    f"{name} must be boolean"
                )
        for name in (
            "runtime_preflight_satisfied",
            "product_pilot_start_ready",
            "product_pilot_start_authorized",
            "product_pilot_started",
            "task_execution_authorized",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "nonce_reusable",
        ):
            if getattr(self, name) is not False:
                raise PilotExactTaskProductPilotRuntimePreflightError(
                    "attestation claim cannot grant runtime/start/mutation authority"
                )

    @property
    def all_checks_satisfied(self) -> bool:
        return all(getattr(self, name) is True for name in CHECK_FIELDS)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductPilotRuntimePreflightError(
                "runtime-preflight attestation fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskProductPilotRuntimePreflightReceipt:
    attestation_sha256: str
    signature_sha256: str
    key_id: str
    issuer_actor_id: str
    issuer_system_id: str
    task_registry_receipt_sha256: str
    lineage_attestation_sha256: str
    post_production_activation_attestation_sha256: str
    host_development_task_registry_sha256: str
    development_task_sha256: str
    repository: str
    merge_commit_sha: str
    operator_surface: str
    selected_pilot_task_id: str
    workspace_root_path_sha256: str
    feature_flag_name: str
    product_route: str
    fixed_command_id: str
    observer_actor_id: str
    observer_host_id: str
    observed_at_utc: str
    verified_at_utc: str
    attestation_age_seconds: int
    product_integration_selection_reverified: bool = True
    task_registry_reverified: bool = True
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
    runtime_preflight_satisfied: bool = True
    product_pilot_start_ready: bool = False
    product_pilot_start_authorized: bool = False
    product_pilot_started: bool = False
    task_execution_authorized: bool = False
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    nonce_reusable: bool = False
    next_boundary_authorization_required: bool = True
    authority: str = PILOT_EXACT_TASK_PRODUCT_PILOT_RUNTIME_PREFLIGHT_RECEIPT_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_RUNTIME_PREFLIGHT_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCT_PILOT_RUNTIME_PREFLIGHT_RECEIPT_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PRODUCT_PILOT_RUNTIME_PREFLIGHT_RECEIPT_AUTHORITY
        ):
            raise PilotExactTaskProductPilotRuntimePreflightError(
                "runtime-preflight receipt identity is unsupported"
            )
        for name in (
            "attestation_sha256",
            "signature_sha256",
            "task_registry_receipt_sha256",
            "lineage_attestation_sha256",
            "post_production_activation_attestation_sha256",
            "host_development_task_registry_sha256",
            "development_task_sha256",
            "workspace_root_path_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        for name in (
            "key_id",
            "issuer_system_id",
            "operator_surface",
            "selected_pilot_task_id",
            "feature_flag_name",
            "fixed_command_id",
            "observer_host_id",
        ):
            _identifier(getattr(self, name), name=name)
        _actor(self.issuer_actor_id, name="issuer_actor_id")
        _actor(self.observer_actor_id, name="observer_actor_id")
        if self.issuer_actor_id != self.observer_actor_id:
            raise PilotExactTaskProductPilotRuntimePreflightError(
                "runtime-preflight receipt signer/observer mismatch"
            )
        if self.issuer_system_id != PILOT_RUNTIME_PREFLIGHT_ATTESTATION_ISSUER_SYSTEM_ID:
            raise PilotExactTaskProductPilotRuntimePreflightError(
                "runtime-preflight receipt issuer system is unsupported"
            )
        if self.repository != "Ternedal/ModelRig":
            raise PilotExactTaskProductPilotRuntimePreflightError(
                "runtime-preflight receipt repository is unsupported"
            )
        if (
            not isinstance(self.product_route, str)
            or not self.product_route.startswith("/")
            or "\x00" in self.product_route
        ):
            raise PilotExactTaskProductPilotRuntimePreflightError(
                "runtime-preflight receipt route is invalid"
            )
        observed = _utc(self.observed_at_utc, name="observed_at_utc")
        verified = _utc(self.verified_at_utc, name="verified_at_utc")
        age = int((verified - observed).total_seconds())
        if (
            verified < observed
            or type(self.attestation_age_seconds) is not int
            or self.attestation_age_seconds != age
            or not 0 <= age <= PILOT_EXACT_TASK_PRODUCT_PILOT_RUNTIME_PREFLIGHT_MAX_AGE_SECONDS
        ):
            raise PilotExactTaskProductPilotRuntimePreflightError(
                "runtime-preflight attestation is outside freshness window"
            )
        required_true = (*CHECK_FIELDS, "runtime_preflight_satisfied", "next_boundary_authorization_required")
        forced_false = (
            "product_pilot_start_ready",
            "product_pilot_start_authorized",
            "product_pilot_started",
            "task_execution_authorized",
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
            raise PilotExactTaskProductPilotRuntimePreflightError(
                "runtime-preflight receipt lacks required positive evidence"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductPilotRuntimePreflightError(
                "runtime-preflight receipt grants forbidden authority"
            )

    @property
    def preflight_authenticated(self) -> bool:
        return _get_live_runtime_preflight_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductPilotRuntimePreflightError(
                "runtime-preflight receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: PilotExactTaskProductPilotRuntimePreflightReceipt,
        *,
        task_registry_receipt: registry_boundary.PilotExactTaskProductPilotTaskRegistryReceipt,
        attestation: PilotExactTaskProductPilotRuntimePreflightAttestation,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            task_registry_receipt,
            attestation,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, registry_receipt, attestation = entry
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or receipt.sha256 != digest
            or registry_receipt.registry_authenticated is not True
            or registry_receipt.sha256 != receipt.task_registry_receipt_sha256
            or attestation.sha256 != receipt.attestation_sha256
        ):
            return None
        return {
            "task_registry_receipt": registry_receipt,
            "attestation": attestation,
        }

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_live_runtime_preflight, _get_live_runtime_preflight_inputs = _live_registry()


def build_pilot_exact_task_product_pilot_runtime_preflight_attestation(
    *,
    task_registry_receipt: registry_boundary.PilotExactTaskProductPilotTaskRegistryReceipt,
    observer_actor_id: str,
    observer_host_id: str,
    observed_at_utc: str,
    evidence_sha256: Mapping[str, str],
    checks: Mapping[str, bool],
) -> PilotExactTaskProductPilotRuntimePreflightAttestation:
    registry_receipt, live = _require_live_registry(task_registry_receipt)
    evidence = _strict_hashes(evidence_sha256)
    results = _strict_checks(checks)
    observed = _utc(observed_at_utc, name="observed_at_utc")
    registry_time = _utc(registry_receipt.evaluated_at_utc, name="registry evaluated_at_utc")
    if observed < registry_time:
        raise PilotExactTaskProductPilotRuntimePreflightError(
            "runtime-preflight observation predates fresh task-registry evaluation"
        )
    lineage = live["lineage_attestation"]
    values = {
        "task_registry_receipt_sha256": registry_receipt.sha256,
        "lineage_attestation_sha256": registry_receipt.lineage_attestation_sha256,
        "post_production_activation_attestation_sha256": (
            lineage.post_production_activation_attestation_sha256
        ),
        "host_development_task_registry_sha256": (
            registry_receipt.host_development_task_registry_sha256
        ),
        "development_task_sha256": registry_receipt.development_task_sha256,
        "repository": registry_receipt.repository,
        "merge_commit_sha": registry_receipt.merge_commit_sha,
        "operator_surface": registry_receipt.operator_surface,
        "selected_pilot_task_id": registry_receipt.selected_pilot_task_id,
        "workspace_root_path_sha256": registry_receipt.workspace_root_path_sha256,
        "feature_flag_name": registry_receipt.feature_flag_name,
        "product_route": registry_receipt.product_route,
        "fixed_command_id": registry_receipt.fixed_command_id,
        "observer_actor_id": _actor(observer_actor_id, name="observer_actor_id"),
        "observer_host_id": _identifier(observer_host_id, name="observer_host_id"),
        "observed_at_utc": observed_at_utc,
        **evidence,
        **results,
    }
    return PilotExactTaskProductPilotRuntimePreflightAttestation(**values)


def _verify_pilot_exact_task_product_pilot_runtime_preflight(
    *,
    task_registry_receipt: registry_boundary.PilotExactTaskProductPilotTaskRegistryReceipt,
    attestation: PilotExactTaskProductPilotRuntimePreflightAttestation,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_provider,
) -> PilotExactTaskProductPilotRuntimePreflightReceipt:
    registry_receipt, _live = _require_live_registry(task_registry_receipt)
    if type(attestation) is not PilotExactTaskProductPilotRuntimePreflightAttestation:
        raise PilotExactTaskProductPilotRuntimePreflightError(
            "exact product-pilot runtime-preflight attestation is required"
        )
    replayed = PilotExactTaskProductPilotRuntimePreflightAttestation.from_mapping(
        attestation.to_dict()
    )
    if replayed != attestation or replayed.sha256 != attestation.sha256:
        raise PilotExactTaskProductPilotRuntimePreflightError(
            "runtime-preflight attestation replay identity mismatch"
        )
    expected = {
        "task_registry_receipt_sha256": registry_receipt.sha256,
        "lineage_attestation_sha256": registry_receipt.lineage_attestation_sha256,
        "host_development_task_registry_sha256": registry_receipt.host_development_task_registry_sha256,
        "development_task_sha256": registry_receipt.development_task_sha256,
        "repository": registry_receipt.repository,
        "merge_commit_sha": registry_receipt.merge_commit_sha,
        "operator_surface": registry_receipt.operator_surface,
        "selected_pilot_task_id": registry_receipt.selected_pilot_task_id,
        "workspace_root_path_sha256": registry_receipt.workspace_root_path_sha256,
        "feature_flag_name": registry_receipt.feature_flag_name,
        "product_route": registry_receipt.product_route,
        "fixed_command_id": registry_receipt.fixed_command_id,
    }
    mismatch = next(
        (name for name, value in expected.items() if getattr(attestation, name) != value),
        None,
    )
    if mismatch is not None:
        raise PilotExactTaskProductPilotRuntimePreflightError(
            f"runtime-preflight attestation scope mismatch: {mismatch}"
        )
    if attestation.all_checks_satisfied is not True:
        raise PilotExactTaskProductPilotRuntimePreflightError(
            "runtime-preflight attestation has unsatisfied mandatory checks"
        )
    if type(signature) is not DetachedEd25519AuthoritySignature:
        raise PilotExactTaskProductPilotRuntimePreflightError(
            "detached Ed25519 runtime-preflight signature is required"
        )
    if type(verifier) is not Ed25519AuthorityVerifier:
        raise PilotExactTaskProductPilotRuntimePreflightError(
            "Ed25519 runtime-preflight verifier is required"
        )
    if (
        signature.issuer_system_id != PILOT_RUNTIME_PREFLIGHT_ATTESTATION_ISSUER_SYSTEM_ID
        or signature.issuer_actor_id != attestation.observer_actor_id
        or signature.signed_at_utc != attestation.observed_at_utc
    ):
        raise PilotExactTaskProductPilotRuntimePreflightError(
            "runtime-preflight signature identity/timestamp mismatch"
        )
    verified_at = now_provider()
    observed = _utc(attestation.observed_at_utc, name="observed_at_utc")
    verified = _utc(verified_at, name="verified_at_utc")
    age = int((verified - observed).total_seconds())
    if (
        verified < observed
        or age < 0
        or age > PILOT_EXACT_TASK_PRODUCT_PILOT_RUNTIME_PREFLIGHT_MAX_AGE_SECONDS
    ):
        raise PilotExactTaskProductPilotRuntimePreflightError(
            "runtime-preflight attestation is stale"
        )
    try:
        verified_payload_sha256 = verifier.verify(
            payload=attestation.canonical_json().encode("utf-8"),
            signature=signature,
            at_utc=verified_at,
        )
    except AsymmetricAuthorityError as exc:
        raise PilotExactTaskProductPilotRuntimePreflightError(
            "runtime-preflight authority verification failed"
        ) from exc
    if verified_payload_sha256 != attestation.sha256:
        raise PilotExactTaskProductPilotRuntimePreflightError(
            "runtime-preflight verified payload hash mismatch"
        )
    receipt = PilotExactTaskProductPilotRuntimePreflightReceipt(
        attestation_sha256=attestation.sha256,
        signature_sha256=signature.sha256,
        key_id=signature.key_id,
        issuer_actor_id=signature.issuer_actor_id,
        issuer_system_id=signature.issuer_system_id,
        task_registry_receipt_sha256=registry_receipt.sha256,
        lineage_attestation_sha256=registry_receipt.lineage_attestation_sha256,
        post_production_activation_attestation_sha256=(
            attestation.post_production_activation_attestation_sha256
        ),
        host_development_task_registry_sha256=(
            registry_receipt.host_development_task_registry_sha256
        ),
        development_task_sha256=registry_receipt.development_task_sha256,
        repository=registry_receipt.repository,
        merge_commit_sha=registry_receipt.merge_commit_sha,
        operator_surface=registry_receipt.operator_surface,
        selected_pilot_task_id=registry_receipt.selected_pilot_task_id,
        workspace_root_path_sha256=registry_receipt.workspace_root_path_sha256,
        feature_flag_name=registry_receipt.feature_flag_name,
        product_route=registry_receipt.product_route,
        fixed_command_id=registry_receipt.fixed_command_id,
        observer_actor_id=attestation.observer_actor_id,
        observer_host_id=attestation.observer_host_id,
        observed_at_utc=attestation.observed_at_utc,
        verified_at_utc=verified_at,
        attestation_age_seconds=age,
        **{name: getattr(attestation, name) for name in CHECK_FIELDS},
    )
    _mark_live_runtime_preflight(
        receipt,
        task_registry_receipt=registry_receipt,
        attestation=attestation,
    )
    if receipt.preflight_authenticated is not True:
        raise PilotExactTaskProductPilotRuntimePreflightError(
            "runtime-preflight receipt lost live provenance"
        )
    return receipt


def verify_pilot_exact_task_product_pilot_runtime_preflight(
    *,
    task_registry_receipt: registry_boundary.PilotExactTaskProductPilotTaskRegistryReceipt,
    attestation: PilotExactTaskProductPilotRuntimePreflightAttestation,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier | None = None,
) -> PilotExactTaskProductPilotRuntimePreflightReceipt:
    """Host-pinned fresh runtime-preflight verification; grants no start authority."""
    if verifier is not None:
        raise PilotExactTaskProductPilotRuntimePreflightError(
            "caller-selected runtime-preflight verifier is not production authority"
        )
    try:
        host_verifier = _canonical_pilot_runtime_preflight_attestation_verifier(
            issuer_system_id=PILOT_RUNTIME_PREFLIGHT_ATTESTATION_ISSUER_SYSTEM_ID
        )
    except PilotRuntimePreflightAttestationProductionBoundaryError as exc:
        raise PilotExactTaskProductPilotRuntimePreflightError(
            "host-controlled runtime-preflight authority state is unavailable"
        ) from exc
    return _verify_pilot_exact_task_product_pilot_runtime_preflight(
        task_registry_receipt=task_registry_receipt,
        attestation=attestation,
        signature=signature,
        verifier=host_verifier,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PRODUCT_PILOT_RUNTIME_PREFLIGHT_ATTESTATION_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_RUNTIME_PREFLIGHT_ATTESTATION_AUTHORITY",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_RUNTIME_PREFLIGHT_RECEIPT_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_RUNTIME_PREFLIGHT_RECEIPT_AUTHORITY",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_RUNTIME_PREFLIGHT_MAX_AGE_SECONDS",
    "EVIDENCE_FIELDS",
    "CHECK_FIELDS",
    "PilotExactTaskProductPilotRuntimePreflightError",
    "PilotExactTaskProductPilotRuntimePreflightAttestation",
    "PilotExactTaskProductPilotRuntimePreflightReceipt",
    "build_pilot_exact_task_product_pilot_runtime_preflight_attestation",
    "verify_pilot_exact_task_product_pilot_runtime_preflight",
]
