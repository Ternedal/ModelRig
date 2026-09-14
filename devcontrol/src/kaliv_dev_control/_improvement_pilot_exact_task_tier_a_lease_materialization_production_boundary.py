"""Production host boundary for ADR-DC-036 Tier-A lease materialization."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
)
from ._tier_a_materialization import LeasedCatalogMaterializer
from .improvement_physical_authority_keyring import (
    PhysicalRequestAuthorityKeyringError,
    _read_keyring_bytes,
)
from .physical_isolation import WindowsPhysicalIsolationVerifier
from .runtime_closure_builder import modelrig_version_check_closure_catalog

_WINDOWS_PROFILE = Path(
    r"C:\Program Files\ModelRig\DevControl\authority\rsi-pilot-exact-task-tier-a-version-check-profile-v1.json"
)
_WINDOWS_EVIDENCE_ROOT = Path(
    r"C:\Program Files\ModelRig\DevControl\state\rsi-pilot-exact-task-tier-a-physical-evidence-v1"
)
_FIXED_PROCESS_MEMORY_BYTES = 128 * 1024 * 1024
_FIXED_ACTIVE_PROCESS_LIMIT = 1


class PilotExactTaskTierALeaseProductionBoundaryError(ValueError):
    """Production ADR-DC-036 host state is unsafe or unavailable."""


def _require_windows_host() -> None:
    if os.name != "nt":
        raise PilotExactTaskTierALeaseProductionBoundaryError(
            "ADR-DC-036 production materialization is Windows-only"
        )


def _canonical_profile_path() -> Path:
    return _WINDOWS_PROFILE


def _canonical_evidence_root() -> Path:
    return _WINDOWS_EVIDENCE_ROOT


def _read_host_controlled_profile() -> bytes:
    try:
        _require_elevated_operator()
        return _read_keyring_bytes(
            _canonical_profile_path(),
            require_host_control=True,
        )
    except (PhysicalHostStateError, PhysicalRequestAuthorityKeyringError) as exc:
        raise PilotExactTaskTierALeaseProductionBoundaryError(
            "canonical ADR-DC-036 profile is not host-admin controlled"
        ) from exc


def install_pilot_exact_task_tier_a_lease_production_boundary(
    implementation: Any,
) -> None:
    if implementation is None:
        raise PilotExactTaskTierALeaseProductionBoundaryError(
            "ADR-DC-036 implementation is unavailable"
        )
    marker = "_production_pilot_exact_task_tier_a_lease_boundary_installed"
    if getattr(implementation, marker, False):
        return

    def materialize_pilot_exact_task_tier_a_lease(
        *,
        development_task_binding: Any,
        admission_receipt: Any,
    ) -> Any:
        try:
            _require_windows_host()
            exact_binding, live_receipt = implementation._require_live_scope(
                development_task_binding,
                admission_receipt,
            )
            profile = implementation._parse_profile_payload(
                _read_host_controlled_profile()
            )
            if (
                profile.process_memory_bytes != _FIXED_PROCESS_MEMORY_BYTES
                or profile.active_process_limit != _FIXED_ACTIVE_PROCESS_LIMIT
            ):
                raise PilotExactTaskTierALeaseProductionBoundaryError(
                    "ADR-DC-036 native process limits are not the reviewed fixed limits"
                )
            verifier = WindowsPhysicalIsolationVerifier(
                _canonical_evidence_root(),
                profile.physical_keyring,
                max_age=profile.physical_max_age,
                max_file_bytes=profile.physical_max_file_bytes,
            )
            catalog = modelrig_version_check_closure_catalog()
            leased_registry = LeasedCatalogMaterializer(
                catalog,
                verifier,
            ).materialize(
                exact_binding.development_task,
                profile.toolchain,
                profile.attestation,
            )
            return implementation._materialize_verified_tier_a_lease(
                development_task_binding=exact_binding,
                admission_receipt=live_receipt,
                profile=profile,
                leased_registry=leased_registry,
            )
        except (
            PilotExactTaskTierALeaseProductionBoundaryError,
            ValueError,
            TypeError,
            AttributeError,
            OSError,
        ) as exc:
            if isinstance(
                exc,
                implementation.PilotExactTaskTierALeaseMaterializationError,
            ):
                raise
            raise implementation.PilotExactTaskTierALeaseMaterializationError(
                "host-controlled ADR-DC-036 Tier-A lease materialization failed closed"
            ) from exc

    implementation.materialize_pilot_exact_task_tier_a_lease = (
        materialize_pilot_exact_task_tier_a_lease
    )
    setattr(implementation, marker, True)


__all__: list[str] = []
