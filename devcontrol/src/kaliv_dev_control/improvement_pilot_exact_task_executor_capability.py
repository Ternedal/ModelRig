"""Public host-pinned facade for ADR-DC-036 executor capability materialization."""
from __future__ import annotations

from . import _improvement_pilot_exact_task_executor_capability_impl as _implementation
from . import _improvement_pilot_exact_task_executor_capability_production_boundary as _production
from ._improvement_pilot_exact_task_executor_capability_live_guard import (
    install_pilot_exact_task_executor_capability_live_guard,
)
from ._improvement_pilot_exact_task_executor_capability_secret_custody import (
    install_pilot_exact_task_executor_secret_custody,
)
from ._improvement_pilot_exact_task_executor_capability_semantics import (
    install_pilot_exact_task_executor_capability_only_semantics,
)

install_pilot_exact_task_executor_capability_only_semantics(_implementation)
install_pilot_exact_task_executor_capability_live_guard(_implementation)
install_pilot_exact_task_executor_secret_custody(_production)
_production.install_pilot_exact_task_executor_capability_production_boundary(
    _implementation
)

PILOT_EXACT_TASK_EXECUTOR_CAPABILITY_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_EXECUTOR_CAPABILITY_SCHEMA
)
PILOT_EXACT_TASK_EXECUTOR_CAPABILITY_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_EXECUTOR_CAPABILITY_AUTHORITY
)
PILOT_EXACT_TASK_EXECUTOR_PROCESS_MEMORY_BYTES = (
    _implementation.PILOT_EXACT_TASK_EXECUTOR_PROCESS_MEMORY_BYTES
)
PILOT_EXACT_TASK_EXECUTOR_ACTIVE_PROCESS_LIMIT = (
    _implementation.PILOT_EXACT_TASK_EXECUTOR_ACTIVE_PROCESS_LIMIT
)
PilotExactTaskExecutorCapabilityError = (
    _implementation.PilotExactTaskExecutorCapabilityError
)
PilotExactTaskExecutorCapability = _implementation.PilotExactTaskExecutorCapability
materialize_pilot_exact_task_executor_capability = (
    _implementation.materialize_pilot_exact_task_executor_capability
)

# Deterministic seams for adversarial contracts. Production stays host-pinned above.
_materialize_verified_executor_capability = (
    _implementation._materialize_verified_executor_capability
)
_get_live_capability_inputs = _implementation._get_live_capability_inputs
_source_environment_sha256 = _implementation._source_environment_sha256

__all__ = [
    "PILOT_EXACT_TASK_EXECUTOR_CAPABILITY_SCHEMA",
    "PILOT_EXACT_TASK_EXECUTOR_CAPABILITY_AUTHORITY",
    "PILOT_EXACT_TASK_EXECUTOR_PROCESS_MEMORY_BYTES",
    "PILOT_EXACT_TASK_EXECUTOR_ACTIVE_PROCESS_LIMIT",
    "PilotExactTaskExecutorCapabilityError",
    "PilotExactTaskExecutorCapability",
    "materialize_pilot_exact_task_executor_capability",
]

del install_pilot_exact_task_executor_capability_only_semantics
del install_pilot_exact_task_executor_capability_live_guard
del install_pilot_exact_task_executor_secret_custody
del _production
