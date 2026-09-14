"""Production host boundary for ADR-DC-035 exact DevelopmentTask binding."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
)
from .improvement_physical_authority_keyring import (
    PhysicalRequestAuthorityKeyringError,
    _read_keyring_bytes,
)

_POSIX_REGISTRY = Path(
    "/etc/modelrig/devcontrol/authority/rsi-pilot-exact-task-development-task-registry-v1.json"
)
_WINDOWS_REGISTRY = Path(
    r"C:\Program Files\ModelRig\DevControl\authority\rsi-pilot-exact-task-development-task-registry-v1.json"
)


class PilotExactTaskDevelopmentTaskBindingProductionBoundaryError(ValueError):
    """Production exact-task registry state is unsafe or unavailable."""


def _canonical_registry_path() -> Path:
    if os.name == "posix":
        return _POSIX_REGISTRY
    if os.name == "nt":
        return _WINDOWS_REGISTRY
    raise PilotExactTaskDevelopmentTaskBindingProductionBoundaryError(
        "exact-task DevelopmentTask registry is unsupported on this platform"
    )


def _read_host_controlled_registry() -> bytes:
    try:
        _require_elevated_operator()
        return _read_keyring_bytes(
            _canonical_registry_path(),
            require_host_control=True,
        )
    except (PhysicalHostStateError, PhysicalRequestAuthorityKeyringError) as exc:
        raise PilotExactTaskDevelopmentTaskBindingProductionBoundaryError(
            "canonical exact-task DevelopmentTask registry is not host-admin controlled"
        ) from exc


def install_pilot_exact_task_development_task_binding_production_boundary(
    implementation: Any,
) -> None:
    if implementation is None:
        raise PilotExactTaskDevelopmentTaskBindingProductionBoundaryError(
            "exact-task DevelopmentTask binding implementation is unavailable"
        )
    marker = "_production_pilot_exact_task_development_task_binding_boundary_installed"
    if getattr(implementation, marker, False):
        return

    def bind_pilot_exact_task_development_task(
        *,
        plan_requirements: Any,
        admission_receipt: Any,
    ) -> Any:
        try:
            payload = _read_host_controlled_registry()
            return implementation._bind_verified_development_task(
                plan_requirements=plan_requirements,
                admission_receipt=admission_receipt,
                registry_payload=payload,
            )
        except (
            PilotExactTaskDevelopmentTaskBindingProductionBoundaryError,
            ValueError,
            TypeError,
            AttributeError,
        ) as exc:
            if isinstance(exc, implementation.PilotExactTaskDevelopmentTaskBindingError):
                raise
            raise implementation.PilotExactTaskDevelopmentTaskBindingError(
                "host-controlled exact DevelopmentTask binding failed closed"
            ) from exc

    implementation.bind_pilot_exact_task_development_task = (
        bind_pilot_exact_task_development_task
    )
    setattr(implementation, marker, True)


__all__: list[str] = []
