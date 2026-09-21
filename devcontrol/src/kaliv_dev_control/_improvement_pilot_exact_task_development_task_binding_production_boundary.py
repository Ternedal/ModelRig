"""Production host boundary for ADR-DC-035 exact DevelopmentTask binding."""
from __future__ import annotations

import os
from collections import OrderedDict
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
_MAX_LIVE_BINDINGS = 1024

# Process-local, exact-object provenance for production host-registry resolution.
# Strong references deliberately prevent Python object-id reuse from authenticating
# a different object. The registry is bounded; oldest-entry eviction only revokes
# authority and therefore fails closed. The exact live ADR-DC-033 receipt is kept
# separately because ADR-DC-034 requirements themselves are intentionally reloadable.
_LIVE_BINDINGS: OrderedDict[int, tuple[int, str, Any, Any]] = OrderedDict()


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


def _mark_transaction_authenticated(binding: Any, admission_receipt: Any) -> None:
    try:
        if (
            getattr(admission_receipt, "transaction_authenticated", False) is not True
            or binding.admission_receipt_sha256 != admission_receipt.sha256
            or binding.execution_nonce_sha256 != admission_receipt.execution_nonce_sha256
        ):
            raise PilotExactTaskDevelopmentTaskBindingProductionBoundaryError(
                "task binding provenance does not match the exact live ADR-DC-033 receipt"
            )
        digest = binding.sha256
    except (AttributeError, TypeError, ValueError) as exc:
        if isinstance(exc, PilotExactTaskDevelopmentTaskBindingProductionBoundaryError):
            raise
        raise PilotExactTaskDevelopmentTaskBindingProductionBoundaryError(
            "task binding provenance identity is invalid"
        ) from exc

    key = id(binding)
    existing = _LIVE_BINDINGS.get(key)
    if existing is not None and existing[2] is not binding:
        raise PilotExactTaskDevelopmentTaskBindingProductionBoundaryError(
            "task binding process identity collided unexpectedly"
        )
    _LIVE_BINDINGS[key] = (os.getpid(), digest, binding, admission_receipt)
    _LIVE_BINDINGS.move_to_end(key)
    while len(_LIVE_BINDINGS) > _MAX_LIVE_BINDINGS:
        _LIVE_BINDINGS.popitem(last=False)


def _is_transaction_authenticated_for_receipt(
    binding: Any,
    admission_receipt: Any,
) -> bool:
    entry = _LIVE_BINDINGS.get(id(binding))
    if entry is None:
        return False
    pid, digest, exact_binding, exact_receipt = entry
    if (
        pid != os.getpid()
        or exact_binding is not binding
        or exact_receipt is not admission_receipt
    ):
        return False
    try:
        return (
            binding.sha256 == digest
            and getattr(admission_receipt, "transaction_authenticated", False) is True
            and binding.admission_receipt_sha256 == admission_receipt.sha256
            and binding.execution_nonce_sha256 == admission_receipt.execution_nonce_sha256
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _is_transaction_authenticated(binding: Any) -> bool:
    entry = _LIVE_BINDINGS.get(id(binding))
    if entry is None:
        return False
    return _is_transaction_authenticated_for_receipt(binding, entry[3])


def require_live_pilot_exact_task_development_task_binding(
    binding: Any,
    admission_receipt: Any,
) -> Any:
    """Return binding only when exact live host-registry provenance still exists."""
    if not _is_transaction_authenticated_for_receipt(binding, admission_receipt):
        raise PilotExactTaskDevelopmentTaskBindingProductionBoundaryError(
            "exact live ADR-DC-035 binding/ADR-DC-033 receipt identity is required"
        )
    return binding


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_LIVE_BINDINGS.clear)


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

    binding_type = implementation.PilotExactTaskDevelopmentTaskBinding
    if not hasattr(binding_type, "transaction_authenticated"):
        setattr(
            binding_type,
            "transaction_authenticated",
            property(_is_transaction_authenticated),
        )

    def bind_pilot_exact_task_development_task(
        *,
        plan_requirements: Any,
        admission_receipt: Any,
    ) -> Any:
        try:
            payload = _read_host_controlled_registry()
            bound = implementation._bind_verified_development_task(
                plan_requirements=plan_requirements,
                admission_receipt=admission_receipt,
                registry_payload=payload,
            )
            _mark_transaction_authenticated(bound, admission_receipt)
            return bound
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
    implementation.require_live_pilot_exact_task_development_task_binding = (
        require_live_pilot_exact_task_development_task_binding
    )
    setattr(implementation, marker, True)


__all__: list[str] = []