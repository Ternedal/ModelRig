"""ADR-DC-036 exact, non-executing Tier-A lease materialization.

The production facade supplies only host-pinned profile data and the existing
Tier-A materializer. This module binds the resulting leased command registry to
the exact ADR-DC-035 DevelopmentTask and the same live ADR-DC-033 admission.
It does not build a runtime closure, launch a process, mutate Git, or consume the
execution admission.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Mapping

from ._improvement_pilot_start_consumption_impl import _path_sha256
from ._tier_a_lease import TierAExecutionLease
from ._tier_a_materialization import LeasedCommandRegistry
from ._tier_a_path_authority import workspace_root_authority_sha256
from .catalog import (
    IsolationAttestation,
    IsolationBoundary,
    NetworkMode,
    ToolBinding,
    Toolchain,
)
from .improvement_pilot_exact_task_development_task_binding import (
    PILOT_EXACT_TASK_DEVELOPMENT_TASK_BINDING_AUTHORITY,
    PilotExactTaskDevelopmentTaskBinding,
)
from .improvement_pilot_exact_task_execution_admission import (
    PILOT_EXACT_TASK_EXECUTION_ADMISSION_AUTHORITY,
    PilotExactTaskExecutionAdmissionReceipt,
)
from .runtime_closure_builder import (
    VERSION_CHECK_COMMAND_ID,
    VERSION_CHECK_TOOL_ID,
    modelrig_version_check_closure_catalog,
)
from .tier_a_authority import tier_a_toolhost_sha256

PILOT_EXACT_TASK_TIER_A_PROFILE_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-tier-a-version-check-profile/v1"
)
PILOT_EXACT_TASK_TIER_A_LEASE_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-tier-a-lease-materialization/v1"
)
PILOT_EXACT_TASK_TIER_A_LEASE_AUTHORITY = (
    "host-materialized-one-exact-tier-a-lease-only"
)
PILOT_EXACT_TASK_TIER_A_PROFILE_ID = "modelrig-version-check-v1"
_MAX_PROFILE_BYTES = 512 * 1024
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_LIVE_CAPABILITY_TOKEN = object()


class PilotExactTaskTierALeaseMaterializationError(ValueError):
    """ADR-DC-036 Tier-A lease materialization is malformed or unsafe."""


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
        raise PilotExactTaskTierALeaseMaterializationError(
            "Tier-A materialization evidence is not canonical JSON"
        ) from exc


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskTierALeaseMaterializationError(f"{name} is invalid")
    return value


def _integer(value: Any, *, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise PilotExactTaskTierALeaseMaterializationError(f"{name} is invalid")
    return value


def _absolute_path(value: Any, *, name: str) -> Path:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\0" in value
    ):
        raise PilotExactTaskTierALeaseMaterializationError(f"{name} is invalid")
    path = Path(value)
    if not path.is_absolute():
        raise PilotExactTaskTierALeaseMaterializationError(f"{name} must be absolute")
    return path


def _attestation_sha256(value: IsolationAttestation) -> str:
    if type(value) is not IsolationAttestation:
        raise PilotExactTaskTierALeaseMaterializationError(
            "exact IsolationAttestation is required"
        )
    return _sha256_text(value.canonical_json())


def _require_binding(value: Any) -> PilotExactTaskDevelopmentTaskBinding:
    if type(value) is not PilotExactTaskDevelopmentTaskBinding:
        raise PilotExactTaskTierALeaseMaterializationError(
            "exact ADR-DC-035 DevelopmentTask binding is required"
        )
    try:
        replayed = PilotExactTaskDevelopmentTaskBinding.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskTierALeaseMaterializationError(
            "ADR-DC-035 binding replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskTierALeaseMaterializationError(
            "ADR-DC-035 binding replay identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_DEVELOPMENT_TASK_BINDING_AUTHORITY
        or value.host_registry_verified is not True
        or value.pilot_task_mapping_verified is not True
        or value.development_task_materialized is not True
        or value.single_fixed_command_verified is not True
        or value.execution_plan_materialized is not False
        or value.execution_consumed is not False
        or value.task_execution_started is not False
        or value.task_execution_completed is not False
        or value.integration_ready is not False
        or value.product_pilot_started is not False
        or value.local_commit_authorized is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskTierALeaseMaterializationError(
            "Tier-A lease requires one inert exact ADR-DC-035 binding"
        )
    return value


def _require_live_receipt(value: Any) -> PilotExactTaskExecutionAdmissionReceipt:
    if type(value) is not PilotExactTaskExecutionAdmissionReceipt:
        raise PilotExactTaskTierALeaseMaterializationError(
            "exact live ADR-DC-033 admission receipt is required"
        )
    try:
        replayed = PilotExactTaskExecutionAdmissionReceipt.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskTierALeaseMaterializationError(
            "ADR-DC-033 receipt replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskTierALeaseMaterializationError(
            "ADR-DC-033 receipt replay identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_EXECUTION_ADMISSION_AUTHORITY
        or value.task_execution_authorized is not True
        or value.task_execution_started is not False
        or value.execution_consumed is not False
        or value.transaction_authenticated is not True
    ):
        raise PilotExactTaskTierALeaseMaterializationError(
            "Tier-A lease materialization requires the exact live unconsumed admission"
        )
    return value


def _require_live_scope(
    binding: PilotExactTaskDevelopmentTaskBinding,
    receipt: PilotExactTaskExecutionAdmissionReceipt,
) -> tuple[PilotExactTaskDevelopmentTaskBinding, PilotExactTaskExecutionAdmissionReceipt]:
    exact = _require_binding(binding)
    live = _require_live_receipt(receipt)
    requirements = exact.plan_requirements
    if (
        exact.admission_receipt_sha256 != live.sha256
        or exact.execution_nonce_sha256 != live.execution_nonce_sha256
        or exact.selected_pilot_task_id != live.selected_pilot_task_id
        or exact.workspace_root_path_sha256 != live.workspace_root_path_sha256
        or requirements.admission_receipt_sha256 != live.sha256
        or requirements.admission_receipt.to_dict() != live.to_dict()
    ):
        raise PilotExactTaskTierALeaseMaterializationError(
            "ADR-DC-035 binding is not bound to this exact live ADR-DC-033 receipt"
        )
    return exact, live


@dataclass(frozen=True, slots=True)
class _TierAMaterializationProfile:
    profile_sha256: str
    toolchain: Toolchain
    attestation: IsolationAttestation
    workspace_root: Path
    control_plane_root: Path
    physical_keyring: Mapping[str, bytes]
    physical_max_age: timedelta
    physical_max_file_bytes: int
    process_memory_bytes: int
    active_process_limit: int


def _parse_profile_payload(payload: Any) -> _TierAMaterializationProfile:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_PROFILE_BYTES:
        raise PilotExactTaskTierALeaseMaterializationError(
            "host Tier-A profile bytes are missing or oversized"
        )
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskTierALeaseMaterializationError(
            "host Tier-A profile is invalid JSON"
        ) from exc
    fields = {
        "schema",
        "profile_id",
        "tool_binding",
        "workspace_root",
        "control_plane_root",
        "isolation_attestation",
        "physical_verifier",
        "process_memory_bytes",
        "active_process_limit",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PilotExactTaskTierALeaseMaterializationError(
            "host Tier-A profile fields mismatch"
        )
    if (
        value.get("schema") != PILOT_EXACT_TASK_TIER_A_PROFILE_SCHEMA
        or value.get("profile_id") != PILOT_EXACT_TASK_TIER_A_PROFILE_ID
    ):
        raise PilotExactTaskTierALeaseMaterializationError(
            "host Tier-A profile schema/profile is unsupported"
        )
    raw_binding = value.get("tool_binding")
    if not isinstance(raw_binding, Mapping) or set(raw_binding) != {
        "tool_id",
        "executable",
        "executable_sha256",
    }:
        raise PilotExactTaskTierALeaseMaterializationError(
            "host Tier-A tool binding fields mismatch"
        )
    if raw_binding.get("tool_id") != VERSION_CHECK_TOOL_ID:
        raise PilotExactTaskTierALeaseMaterializationError(
            "host Tier-A profile may bind only the reviewed version-check tool"
        )
    try:
        toolchain = Toolchain(
            (
                ToolBinding(
                    raw_binding["tool_id"],
                    raw_binding["executable"],
                    raw_binding["executable_sha256"],
                ),
            )
        )
        attestation = IsolationAttestation.from_mapping(value["isolation_attestation"])
    except Exception as exc:
        raise PilotExactTaskTierALeaseMaterializationError(
            "host Tier-A toolchain/attestation is invalid"
        ) from exc

    raw_verifier = value.get("physical_verifier")
    if not isinstance(raw_verifier, Mapping) or set(raw_verifier) != {
        "max_age_seconds",
        "max_file_bytes",
        "trusted_keys",
    }:
        raise PilotExactTaskTierALeaseMaterializationError(
            "host Tier-A physical verifier fields mismatch"
        )
    max_age_seconds = _integer(
        raw_verifier["max_age_seconds"],
        name="physical_verifier.max_age_seconds",
        low=1,
        high=366 * 24 * 60 * 60,
    )
    max_file_bytes = _integer(
        raw_verifier["max_file_bytes"],
        name="physical_verifier.max_file_bytes",
        low=1024,
        high=16_000_000,
    )
    raw_keys = raw_verifier.get("trusted_keys")
    if not isinstance(raw_keys, list) or not 1 <= len(raw_keys) <= 32:
        raise PilotExactTaskTierALeaseMaterializationError(
            "host Tier-A physical verifier key list is invalid"
        )
    keyring: dict[str, bytes] = {}
    previous: str | None = None
    canonical_keys: list[dict[str, str]] = []
    for raw_key in raw_keys:
        if not isinstance(raw_key, Mapping) or set(raw_key) != {"key_id", "secret_hex"}:
            raise PilotExactTaskTierALeaseMaterializationError(
                "host Tier-A physical verifier key fields mismatch"
            )
        key_id = raw_key.get("key_id")
        secret_hex = raw_key.get("secret_hex")
        if not isinstance(key_id, str) or _KEY_ID.fullmatch(key_id) is None:
            raise PilotExactTaskTierALeaseMaterializationError(
                "host Tier-A physical verifier key id is invalid"
            )
        if previous is not None and key_id <= previous:
            raise PilotExactTaskTierALeaseMaterializationError(
                "host Tier-A physical verifier keys must be sorted and unique"
            )
        previous = key_id
        if not isinstance(secret_hex, str) or len(secret_hex) % 2:
            raise PilotExactTaskTierALeaseMaterializationError(
                "host Tier-A physical verifier key secret is invalid"
            )
        try:
            secret = bytes.fromhex(secret_hex)
        except ValueError as exc:
            raise PilotExactTaskTierALeaseMaterializationError(
                "host Tier-A physical verifier key secret is invalid"
            ) from exc
        if not 32 <= len(secret) <= 4096:
            raise PilotExactTaskTierALeaseMaterializationError(
                "host Tier-A physical verifier key secret is outside bounds"
            )
        keyring[key_id] = secret
        canonical_keys.append({"key_id": key_id, "secret_hex": secret_hex})

    workspace_root = _absolute_path(value["workspace_root"], name="workspace_root")
    control_plane_root = _absolute_path(
        value["control_plane_root"], name="control_plane_root"
    )
    process_memory_bytes = _integer(
        value["process_memory_bytes"],
        name="process_memory_bytes",
        low=64 * 1024 * 1024,
        high=8 * 1024 * 1024 * 1024,
    )
    active_process_limit = _integer(
        value["active_process_limit"],
        name="active_process_limit",
        low=1,
        high=64,
    )

    canonical = {
        "schema": PILOT_EXACT_TASK_TIER_A_PROFILE_SCHEMA,
        "profile_id": PILOT_EXACT_TASK_TIER_A_PROFILE_ID,
        "tool_binding": raw_binding,
        "workspace_root": value["workspace_root"],
        "control_plane_root": value["control_plane_root"],
        "isolation_attestation": attestation.to_dict(),
        "physical_verifier": {
            "max_age_seconds": max_age_seconds,
            "max_file_bytes": max_file_bytes,
            "trusted_keys": canonical_keys,
        },
        "process_memory_bytes": process_memory_bytes,
        "active_process_limit": active_process_limit,
    }
    canonical_bytes = _canonical(canonical).encode("utf-8")
    if payload != canonical_bytes:
        raise PilotExactTaskTierALeaseMaterializationError(
            "host Tier-A profile is not canonical JSON"
        )
    return _TierAMaterializationProfile(
        profile_sha256=hashlib.sha256(payload).hexdigest(),
        toolchain=toolchain,
        attestation=attestation,
        workspace_root=workspace_root,
        control_plane_root=control_plane_root,
        physical_keyring=keyring,
        physical_max_age=timedelta(seconds=max_age_seconds),
        physical_max_file_bytes=max_file_bytes,
        process_memory_bytes=process_memory_bytes,
        active_process_limit=active_process_limit,
    )


@dataclass(frozen=True, slots=True)
class PilotExactTaskTierALeaseMaterialization:
    development_task_binding: PilotExactTaskDevelopmentTaskBinding
    development_task_binding_sha256: str
    admission_receipt_sha256: str
    execution_nonce_sha256: str
    profile_sha256: str
    catalog_sha256: str
    toolchain_sha256: str
    isolation_attestation: IsolationAttestation
    isolation_attestation_sha256: str
    execution_lease: TierAExecutionLease
    execution_lease_sha256: str
    fixed_command_id: str
    workspace_root_path_sha256: str
    workspace_root_authority_sha256: str
    toolhost_sha256: str
    process_memory_bytes: int
    active_process_limit: int
    host_profile_verified: bool = True
    reviewed_catalog_verified: bool = True
    exact_toolchain_materialized: bool = True
    isolation_attestation_verified: bool = True
    execution_lease_materialized: bool = True
    workspace_authority_verified: bool = True
    toolhost_authority_verified: bool = True
    runtime_closure_materialized: bool = False
    execution_plan_materialized: bool = False
    execution_consumed: bool = False
    task_execution_started: bool = False
    task_execution_completed: bool = False
    integration_ready: bool = False
    product_pilot_started: bool = False
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_TIER_A_LEASE_AUTHORITY
    schema: str = PILOT_EXACT_TASK_TIER_A_LEASE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_TIER_A_LEASE_SCHEMA:
            raise PilotExactTaskTierALeaseMaterializationError(
                "Tier-A lease materialization schema unsupported"
            )
        binding = _require_binding(self.development_task_binding)
        if type(self.isolation_attestation) is not IsolationAttestation:
            raise PilotExactTaskTierALeaseMaterializationError(
                "Tier-A materialization isolation attestation is invalid"
            )
        if type(self.execution_lease) is not TierAExecutionLease:
            raise PilotExactTaskTierALeaseMaterializationError(
                "Tier-A materialization execution lease is invalid"
            )
        for name in (
            "development_task_binding_sha256",
            "admission_receipt_sha256",
            "execution_nonce_sha256",
            "profile_sha256",
            "catalog_sha256",
            "toolchain_sha256",
            "isolation_attestation_sha256",
            "execution_lease_sha256",
            "workspace_root_path_sha256",
            "workspace_root_authority_sha256",
            "toolhost_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _integer(
            self.process_memory_bytes,
            name="process_memory_bytes",
            low=64 * 1024 * 1024,
            high=8 * 1024 * 1024 * 1024,
        )
        _integer(
            self.active_process_limit,
            name="active_process_limit",
            low=1,
            high=64,
        )
        expected = {
            "development_task_binding_sha256": binding.sha256,
            "admission_receipt_sha256": binding.admission_receipt_sha256,
            "execution_nonce_sha256": binding.execution_nonce_sha256,
            "fixed_command_id": binding.fixed_command_id,
            "workspace_root_path_sha256": binding.workspace_root_path_sha256,
            "isolation_attestation_sha256": _attestation_sha256(
                self.isolation_attestation
            ),
            "execution_lease_sha256": self.execution_lease.sha256,
            "catalog_sha256": self.execution_lease.catalog_sha256,
            "toolchain_sha256": self.execution_lease.toolchain_sha256,
            "workspace_root_authority_sha256": (
                self.execution_lease.workspace_root_sha256
            ),
            "toolhost_sha256": self.execution_lease.toolhost_sha256,
        }
        mismatch = next(
            (name for name, item in expected.items() if getattr(self, name) != item),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskTierALeaseMaterializationError(
                f"Tier-A lease materialization identity mismatch: {mismatch}"
            )
        task = binding.development_task
        attestation = self.isolation_attestation
        lease = self.execution_lease
        task_sha256 = hashlib.sha256(task.canonical_json().encode("utf-8")).hexdigest()
        if (
            self.fixed_command_id != VERSION_CHECK_COMMAND_ID
            or attestation.task_id != task.task_id
            or attestation.task_sha256 != task_sha256
            or attestation.repository != task.repository
            or attestation.base_sha != task.base_sha
            or attestation.catalog_sha256 != self.catalog_sha256
            or attestation.toolchain_sha256 != self.toolchain_sha256
            or attestation.boundary is not IsolationBoundary.OS_ISOLATED
            or attestation.network_mode is not NetworkMode.DENY
            or lease.task_id != task.task_id
            or lease.task_sha256 != task_sha256
            or lease.repository != task.repository
            or lease.base_sha != task.base_sha
        ):
            raise PilotExactTaskTierALeaseMaterializationError(
                "Tier-A lease materialization is not exact-bound to the DevelopmentTask"
            )
        try:
            lease.verify_attestation(attestation)
        except Exception as exc:
            raise PilotExactTaskTierALeaseMaterializationError(
                "Tier-A execution lease is not bound to the exact isolation attestation"
            ) from exc
        required_true = (
            "host_profile_verified",
            "reviewed_catalog_verified",
            "exact_toolchain_materialized",
            "isolation_attestation_verified",
            "execution_lease_materialized",
            "workspace_authority_verified",
            "toolhost_authority_verified",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskTierALeaseMaterializationError(
                "Tier-A lease verification flags must stay true"
            )
        forced_false = (
            "runtime_closure_materialized",
            "execution_plan_materialized",
            "execution_consumed",
            "task_execution_started",
            "task_execution_completed",
            "integration_ready",
            "product_pilot_started",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskTierALeaseMaterializationError(
                "Tier-A lease materialization cannot grant execution/publication authority"
            )
        if self.authority != PILOT_EXACT_TASK_TIER_A_LEASE_AUTHORITY:
            raise PilotExactTaskTierALeaseMaterializationError(
                "Tier-A lease materialization authority invalid"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskTierALeaseMaterialization":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskTierALeaseMaterializationError(
                "Tier-A lease materialization fields mismatch"
            )
        data = dict(value)
        try:
            data["development_task_binding"] = (
                PilotExactTaskDevelopmentTaskBinding.from_mapping(
                    data["development_task_binding"]
                )
            )
            data["isolation_attestation"] = IsolationAttestation.from_mapping(
                data["isolation_attestation"]
            )
            data["execution_lease"] = TierAExecutionLease.from_mapping(
                data["execution_lease"]
            )
        except Exception as exc:
            raise PilotExactTaskTierALeaseMaterializationError(
                "Tier-A lease materialization nested evidence is invalid"
            ) from exc
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name in self.__dataclass_fields__:
            if name == "development_task_binding":
                result[name] = self.development_task_binding.to_dict()
            elif name == "isolation_attestation":
                result[name] = self.isolation_attestation.to_dict()
            elif name == "execution_lease":
                result[name] = self.execution_lease.to_dict()
            else:
                result[name] = getattr(self, name)
        return result

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class PilotExactTaskTierALeaseCapability:
    """Live process-local capability. Durable evidence cannot recreate its registry."""

    __slots__ = (
        "evidence",
        "_registry",
        "workspace_root",
        "control_plane_root",
        "process_memory_bytes",
        "active_process_limit",
        "_token",
    )

    def __init__(
        self,
        *,
        evidence: PilotExactTaskTierALeaseMaterialization,
        registry: LeasedCommandRegistry,
        workspace_root: Path,
        control_plane_root: Path,
        process_memory_bytes: int,
        active_process_limit: int,
        _token: object,
    ) -> None:
        if _token is not _LIVE_CAPABILITY_TOKEN:
            raise PilotExactTaskTierALeaseMaterializationError(
                "Tier-A lease capability may only be issued by the live materialization boundary"
            )
        if type(evidence) is not PilotExactTaskTierALeaseMaterialization:
            raise PilotExactTaskTierALeaseMaterializationError(
                "Tier-A lease capability evidence is invalid"
            )
        if not isinstance(registry, LeasedCommandRegistry):
            raise PilotExactTaskTierALeaseMaterializationError(
                "Tier-A lease capability registry is invalid"
            )
        self.evidence = evidence
        self._registry = registry
        self.workspace_root = Path(workspace_root)
        self.control_plane_root = Path(control_plane_root)
        self.process_memory_bytes = process_memory_bytes
        self.active_process_limit = active_process_limit
        self._token = _token

    @property
    def capability_authenticated(self) -> bool:
        return self._token is _LIVE_CAPABILITY_TOKEN

    @property
    def leased_registry(self) -> LeasedCommandRegistry:
        if not self.capability_authenticated:
            raise PilotExactTaskTierALeaseMaterializationError(
                "Tier-A lease capability lost live provenance"
            )
        return self._registry


def _materialize_verified_tier_a_lease(
    *,
    development_task_binding: PilotExactTaskDevelopmentTaskBinding,
    admission_receipt: PilotExactTaskExecutionAdmissionReceipt,
    profile: _TierAMaterializationProfile,
    leased_registry: LeasedCommandRegistry,
) -> PilotExactTaskTierALeaseCapability:
    binding, _ = _require_live_scope(development_task_binding, admission_receipt)
    if not isinstance(profile, _TierAMaterializationProfile):
        raise PilotExactTaskTierALeaseMaterializationError(
            "exact host Tier-A materialization profile is required"
        )
    if not isinstance(leased_registry, LeasedCommandRegistry):
        raise PilotExactTaskTierALeaseMaterializationError(
            "existing Tier-A LeasedCommandRegistry is required"
        )
    if binding.fixed_command_id != VERSION_CHECK_COMMAND_ID:
        raise PilotExactTaskTierALeaseMaterializationError(
            "first controlled Tier-A lease is limited to modelrig.version.check"
        )

    reviewed_catalog = modelrig_version_check_closure_catalog()
    if (
        leased_registry.catalog.sha256 != reviewed_catalog.sha256
        or leased_registry.catalog.command_ids != (VERSION_CHECK_COMMAND_ID,)
        or leased_registry.toolchain.sha256 != profile.toolchain.sha256
        or leased_registry.attestation.to_dict() != profile.attestation.to_dict()
    ):
        raise PilotExactTaskTierALeaseMaterializationError(
            "leased registry does not match the host-pinned reviewed Tier-A profile"
        )
    task = binding.development_task
    try:
        template = leased_registry.resolve(task, binding.fixed_command_id)
    except Exception as exc:
        raise PilotExactTaskTierALeaseMaterializationError(
            "leased registry cannot resolve the exact fixed command"
        ) from exc
    if template.command_id != VERSION_CHECK_COMMAND_ID:
        raise PilotExactTaskTierALeaseMaterializationError(
            "leased registry resolved an unexpected command"
        )
    if template.max_timeout_seconds > task.budget.max_runtime_seconds:
        raise PilotExactTaskTierALeaseMaterializationError(
            "reviewed command timeout exceeds the signed task budget"
        )

    try:
        workspace = profile.workspace_root.resolve(strict=True)
        control = profile.control_plane_root.resolve(strict=True)
        path_sha256 = _path_sha256(workspace)
        workspace_authority = workspace_root_authority_sha256(workspace)
        toolhost = tier_a_toolhost_sha256(control)
    except Exception as exc:
        raise PilotExactTaskTierALeaseMaterializationError(
            "canonical workspace/control-plane authority could not be resolved"
        ) from exc
    lease = leased_registry.lease
    if (
        path_sha256 != binding.workspace_root_path_sha256
        or workspace_authority != lease.workspace_root_sha256
        or toolhost != lease.toolhost_sha256
    ):
        raise PilotExactTaskTierALeaseMaterializationError(
            "Tier-A workspace/toolhost authority does not match the signed pilot scope"
        )

    evidence = PilotExactTaskTierALeaseMaterialization(
        development_task_binding=binding,
        development_task_binding_sha256=binding.sha256,
        admission_receipt_sha256=binding.admission_receipt_sha256,
        execution_nonce_sha256=binding.execution_nonce_sha256,
        profile_sha256=profile.profile_sha256,
        catalog_sha256=reviewed_catalog.sha256,
        toolchain_sha256=profile.toolchain.sha256,
        isolation_attestation=profile.attestation,
        isolation_attestation_sha256=_attestation_sha256(profile.attestation),
        execution_lease=lease,
        execution_lease_sha256=lease.sha256,
        fixed_command_id=binding.fixed_command_id,
        workspace_root_path_sha256=path_sha256,
        workspace_root_authority_sha256=workspace_authority,
        toolhost_sha256=toolhost,
        process_memory_bytes=profile.process_memory_bytes,
        active_process_limit=profile.active_process_limit,
    )
    return PilotExactTaskTierALeaseCapability(
        evidence=evidence,
        registry=leased_registry,
        workspace_root=workspace,
        control_plane_root=control,
        process_memory_bytes=profile.process_memory_bytes,
        active_process_limit=profile.active_process_limit,
        _token=_LIVE_CAPABILITY_TOKEN,
    )


def materialize_pilot_exact_task_tier_a_lease(*args: Any, **kwargs: Any) -> PilotExactTaskTierALeaseCapability:
    raise PilotExactTaskTierALeaseMaterializationError(
        "production host-pinned Tier-A lease materialization boundary is not installed"
    )
