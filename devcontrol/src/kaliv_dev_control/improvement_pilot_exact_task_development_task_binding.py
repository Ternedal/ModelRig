"""Public host-pinned facade for ADR-DC-035 exact DevelopmentTask binding."""
from __future__ import annotations

from . import _improvement_pilot_exact_task_development_task_binding_impl as _implementation
from ._improvement_pilot_exact_task_development_task_binding_production_boundary import (
    install_pilot_exact_task_development_task_binding_production_boundary,
)

install_pilot_exact_task_development_task_binding_production_boundary(_implementation)

PILOT_EXACT_TASK_DEVELOPMENT_TASK_REGISTRY_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_DEVELOPMENT_TASK_REGISTRY_SCHEMA
)
PILOT_EXACT_TASK_DEVELOPMENT_TASK_BINDING_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_DEVELOPMENT_TASK_BINDING_SCHEMA
)
PILOT_EXACT_TASK_DEVELOPMENT_TASK_BINDING_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_DEVELOPMENT_TASK_BINDING_AUTHORITY
)
PilotExactTaskDevelopmentTaskBindingError = (
    _implementation.PilotExactTaskDevelopmentTaskBindingError
)
PilotExactTaskDevelopmentTaskBinding = (
    _implementation.PilotExactTaskDevelopmentTaskBinding
)
bind_pilot_exact_task_development_task = (
    _implementation.bind_pilot_exact_task_development_task
)

# Deterministic seams for adversarial contracts. Production stays host-pinned above.
_parse_registry_payload = _implementation._parse_registry_payload
_bind_verified_development_task = _implementation._bind_verified_development_task
_task_sha256 = _implementation._task_sha256

__all__ = [
    "PILOT_EXACT_TASK_DEVELOPMENT_TASK_REGISTRY_SCHEMA",
    "PILOT_EXACT_TASK_DEVELOPMENT_TASK_BINDING_SCHEMA",
    "PILOT_EXACT_TASK_DEVELOPMENT_TASK_BINDING_AUTHORITY",
    "PilotExactTaskDevelopmentTaskBindingError",
    "PilotExactTaskDevelopmentTaskBinding",
    "bind_pilot_exact_task_development_task",
]

del install_pilot_exact_task_development_task_binding_production_boundary
