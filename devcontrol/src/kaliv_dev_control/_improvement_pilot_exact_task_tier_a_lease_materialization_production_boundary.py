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
    _validate_windows_acl_snapshot,
    _windows_acl_snapshot,
)
from .physical_isolation import WindowsPhysicalIsolationVerifier
from .runtime_closure_builder import modelrig_version_check_closure_catalog
from .trusted_git_runtime_model import _has_linkish_component

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


def _require_host_controlled_evidence_root() -> Path:
    """Require the fixed evidence directory and its Program Files chain to be protected."""

    _require_windows_host()
    root = Path(os.path.abspath(os.fspath(_canonical_evidence_root())))
    anchor = Path(os.path.abspath(r"C:\Program Files"))
    root_norm = os.path.normcase(os.fspath(root))
    anchor_norm = os.path.normcase(os.fspath(anchor))
    try:
        common = os.path.normcase(os.path.commonpath([root_norm, anchor_norm]))
    except ValueError as exc:
        raise PilotExactTaskTierALeaseProductionBoundaryError(
            "ADR-DC-036 evidence root is outside Program Files"
        ) from exc
    if common != anchor_norm or not root.is_dir() or _has_linkish_component(root):
        raise PilotExactTaskTierALeaseProductionBoundaryError(
            "ADR-DC-036 evidence root is not a safe Program Files directory"
        )

    cursor = root
    while True:
        cursor_norm = os.path.normcase(os.path.abspath(os.fspath(cursor)))
        if not cursor.is_dir() or _has_linkish_component(cursor):
            raise PilotExactTaskTierALeaseProductionBoundaryError(
                "ADR-DC-036 evidence directory chain is unsafe"
            )
        try:
            owner_sid, entries = _windows_acl_snapshot(cursor)
            _validate_windows_acl_snapshot(
                owner_sid,
                entries,
                is_directory=True,
            )
        except PhysicalRequestAuthorityKeyringError as exc:
            raise PilotExactTaskTierALeaseProductionBoundaryError(
                "ADR-DC-036 evidence directory is not host-admin controlled"
            ) from exc
        if cursor_norm == anchor_norm:
            return root
        parent = cursor.parent
        if parent == cursor or not cursor_norm.startswith(anchor_norm):
            raise PilotExactTaskTierALeaseProductionBoundaryError(
                "ADR-DC-036 evidence directory chain escaped Program Files"
            )
        cursor = parent


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
                _require_host_controlled_evidence_root(),
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
