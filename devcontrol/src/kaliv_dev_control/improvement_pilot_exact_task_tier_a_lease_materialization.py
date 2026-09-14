"""Public host-pinned facade for ADR-DC-036 Tier-A lease materialization."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from . import _improvement_pilot_exact_task_tier_a_lease_materialization_impl as _implementation
from ._improvement_pilot_exact_task_tier_a_lease_materialization_production_boundary import (
    install_pilot_exact_task_tier_a_lease_production_boundary,
)
from ._tier_a_materialization import LeasedCommandRegistry
from ._tier_a_path_authority import workspace_root_authority_sha256
from .runtime_closure_builder import VERSION_CHECK_COMMAND_ID
from .tier_a_authority import tier_a_toolhost_sha256

install_pilot_exact_task_tier_a_lease_production_boundary(_implementation)

PILOT_EXACT_TASK_TIER_A_PROFILE_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_TIER_A_PROFILE_SCHEMA
)
PILOT_EXACT_TASK_TIER_A_LEASE_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_TIER_A_LEASE_SCHEMA
)
PILOT_EXACT_TASK_TIER_A_LEASE_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_TIER_A_LEASE_AUTHORITY
)
PILOT_EXACT_TASK_TIER_A_PROFILE_ID = (
    _implementation.PILOT_EXACT_TASK_TIER_A_PROFILE_ID
)
PILOT_EXACT_TASK_TIER_A_REVIEWED_CATALOG_SHA256 = (
    "b687f940160ba6ca7a14ae84f8315da851a9698b0c50039f8bb6d02dfee458c4"
)
PILOT_EXACT_TASK_TIER_A_PROCESS_MEMORY_BYTES = 128 * 1024 * 1024
PILOT_EXACT_TASK_TIER_A_ACTIVE_PROCESS_LIMIT = 1
PilotExactTaskTierALeaseMaterializationError = (
    _implementation.PilotExactTaskTierALeaseMaterializationError
)

_PUBLIC_CAPABILITY_TOKEN = object()


def _validate_internal_evidence(
    inner: Any,
) -> _implementation.PilotExactTaskTierALeaseMaterialization:
    if type(inner) is not _implementation.PilotExactTaskTierALeaseMaterialization:
        raise PilotExactTaskTierALeaseMaterializationError(
            "ADR-DC-036 durable evidence has an invalid implementation type"
        )
    if (
        inner.catalog_sha256 != PILOT_EXACT_TASK_TIER_A_REVIEWED_CATALOG_SHA256
        or inner.isolation_attestation.catalog_sha256
        != PILOT_EXACT_TASK_TIER_A_REVIEWED_CATALOG_SHA256
        or inner.execution_lease.catalog_sha256
        != PILOT_EXACT_TASK_TIER_A_REVIEWED_CATALOG_SHA256
        or inner.fixed_command_id != VERSION_CHECK_COMMAND_ID
        or inner.process_memory_bytes
        != PILOT_EXACT_TASK_TIER_A_PROCESS_MEMORY_BYTES
        or inner.active_process_limit
        != PILOT_EXACT_TASK_TIER_A_ACTIVE_PROCESS_LIMIT
    ):
        raise PilotExactTaskTierALeaseMaterializationError(
            "ADR-DC-036 evidence is not the reviewed fixed Tier-A capability"
        )
    return inner


class PilotExactTaskTierALeaseMaterialization:
    """Hardened durable ADR-DC-036 evidence; never a live execution capability."""

    __slots__ = ("__inner",)

    def __init__(self, inner: Any) -> None:
        object.__setattr__(
            self,
            "_PilotExactTaskTierALeaseMaterialization__inner",
            _validate_internal_evidence(inner),
        )

    def __setattr__(self, name: str, value: Any) -> None:
        del name, value
        raise PilotExactTaskTierALeaseMaterializationError(
            "ADR-DC-036 durable evidence is immutable"
        )

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
    ) -> "PilotExactTaskTierALeaseMaterialization":
        return cls(
            _implementation.PilotExactTaskTierALeaseMaterialization.from_mapping(
                value
            )
        )

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self.__inner, name)

    def __eq__(self, other: object) -> bool:
        return (
            type(other) is PilotExactTaskTierALeaseMaterialization
            and self.__inner == other.__inner
        )

    def to_dict(self) -> dict[str, Any]:
        return self.__inner.to_dict()

    def canonical_json(self) -> str:
        return self.__inner.canonical_json()

    @property
    def sha256(self) -> str:
        return self.__inner.sha256


class PilotExactTaskTierALeaseCapability:
    """Sealed process-local handle over the existing leased Tier-A registry."""

    __slots__ = ("evidence", "__inner", "__token", "__sealed")

    def __init__(
        self,
        *,
        evidence: PilotExactTaskTierALeaseMaterialization,
        inner: Any,
        _token: object,
    ) -> None:
        if _token is not _PUBLIC_CAPABILITY_TOKEN:
            raise PilotExactTaskTierALeaseMaterializationError(
                "ADR-DC-036 capability can only be issued by the public production facade"
            )
        if type(evidence) is not PilotExactTaskTierALeaseMaterialization:
            raise PilotExactTaskTierALeaseMaterializationError(
                "ADR-DC-036 capability evidence is invalid"
            )
        if type(inner) is not _implementation.PilotExactTaskTierALeaseCapability:
            raise PilotExactTaskTierALeaseMaterializationError(
                "ADR-DC-036 internal capability is invalid"
            )
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(self, "_PilotExactTaskTierALeaseCapability__inner", inner)
        object.__setattr__(self, "_PilotExactTaskTierALeaseCapability__token", _token)
        object.__setattr__(self, "_PilotExactTaskTierALeaseCapability__sealed", True)
        self._validate_live_authority()

    def __setattr__(self, name: str, value: Any) -> None:
        del name, value
        if getattr(
            self,
            "_PilotExactTaskTierALeaseCapability__sealed",
            False,
        ):
            raise PilotExactTaskTierALeaseMaterializationError(
                "ADR-DC-036 capability is immutable"
            )
        raise PilotExactTaskTierALeaseMaterializationError(
            "ADR-DC-036 capability fields cannot be caller-assigned"
        )

    @classmethod
    def _from_internal(cls, inner: Any) -> "PilotExactTaskTierALeaseCapability":
        if type(inner) is not _implementation.PilotExactTaskTierALeaseCapability:
            raise PilotExactTaskTierALeaseMaterializationError(
                "ADR-DC-036 internal capability is invalid"
            )
        evidence = PilotExactTaskTierALeaseMaterialization(inner.evidence)
        return cls(
            evidence=evidence,
            inner=inner,
            _token=_PUBLIC_CAPABILITY_TOKEN,
        )

    def _validate_live_authority(self) -> LeasedCommandRegistry:
        if (
            self.__token is not _PUBLIC_CAPABILITY_TOKEN
            or self.__inner.capability_authenticated is not True
        ):
            raise PilotExactTaskTierALeaseMaterializationError(
                "ADR-DC-036 capability lost process-local provenance"
            )
        registry = self.__inner.leased_registry
        evidence = self.evidence
        if (
            not isinstance(registry, LeasedCommandRegistry)
            or registry.catalog.sha256 != evidence.catalog_sha256
            or registry.catalog.command_ids != (VERSION_CHECK_COMMAND_ID,)
            or registry.toolchain.sha256 != evidence.toolchain_sha256
            or registry.attestation.to_dict()
            != evidence.isolation_attestation.to_dict()
            or registry.lease.sha256 != evidence.execution_lease_sha256
            or self.__inner.process_memory_bytes
            != PILOT_EXACT_TASK_TIER_A_PROCESS_MEMORY_BYTES
            or self.__inner.active_process_limit
            != PILOT_EXACT_TASK_TIER_A_ACTIVE_PROCESS_LIMIT
        ):
            raise PilotExactTaskTierALeaseMaterializationError(
                "ADR-DC-036 live registry drifted from its durable evidence"
            )
        workspace = Path(self.__inner.workspace_root)
        control = Path(self.__inner.control_plane_root)
        if (
            workspace_root_authority_sha256(workspace)
            != evidence.workspace_root_authority_sha256
            or tier_a_toolhost_sha256(control) != evidence.toolhost_sha256
        ):
            raise PilotExactTaskTierALeaseMaterializationError(
                "ADR-DC-036 live workspace/toolhost authority drifted"
            )
        return registry

    @property
    def capability_authenticated(self) -> bool:
        try:
            self._validate_live_authority()
        except (ValueError, TypeError, OSError):
            return False
        return True

    @property
    def workspace_root(self) -> Path:
        self._validate_live_authority()
        return Path(self.__inner.workspace_root)

    @property
    def control_plane_root(self) -> Path:
        self._validate_live_authority()
        return Path(self.__inner.control_plane_root)

    @property
    def process_memory_bytes(self) -> int:
        self._validate_live_authority()
        return PILOT_EXACT_TASK_TIER_A_PROCESS_MEMORY_BYTES

    @property
    def active_process_limit(self) -> int:
        self._validate_live_authority()
        return PILOT_EXACT_TASK_TIER_A_ACTIVE_PROCESS_LIMIT


def _extract_live_leased_registry(
    capability: PilotExactTaskTierALeaseCapability,
) -> LeasedCommandRegistry:
    """Private handoff seam for a later host-owned materialization boundary."""

    if type(capability) is not PilotExactTaskTierALeaseCapability:
        raise PilotExactTaskTierALeaseMaterializationError(
            "exact live ADR-DC-036 capability is required"
        )
    return capability._validate_live_authority()


def materialize_pilot_exact_task_tier_a_lease(
    *,
    development_task_binding: Any,
    admission_receipt: Any,
) -> PilotExactTaskTierALeaseCapability:
    inner = _implementation.materialize_pilot_exact_task_tier_a_lease(
        development_task_binding=development_task_binding,
        admission_receipt=admission_receipt,
    )
    return PilotExactTaskTierALeaseCapability._from_internal(inner)


# Deterministic seams for adversarial contracts. Production authority stays pinned.
_parse_profile_payload = _implementation._parse_profile_payload
_materialize_verified_tier_a_lease = _implementation._materialize_verified_tier_a_lease
_require_live_scope = _implementation._require_live_scope

__all__ = [
    "PILOT_EXACT_TASK_TIER_A_PROFILE_SCHEMA",
    "PILOT_EXACT_TASK_TIER_A_LEASE_SCHEMA",
    "PILOT_EXACT_TASK_TIER_A_LEASE_AUTHORITY",
    "PILOT_EXACT_TASK_TIER_A_PROFILE_ID",
    "PILOT_EXACT_TASK_TIER_A_REVIEWED_CATALOG_SHA256",
    "PILOT_EXACT_TASK_TIER_A_PROCESS_MEMORY_BYTES",
    "PILOT_EXACT_TASK_TIER_A_ACTIVE_PROCESS_LIMIT",
    "PilotExactTaskTierALeaseMaterializationError",
    "PilotExactTaskTierALeaseMaterialization",
    "PilotExactTaskTierALeaseCapability",
    "materialize_pilot_exact_task_tier_a_lease",
]

del install_pilot_exact_task_tier_a_lease_production_boundary
