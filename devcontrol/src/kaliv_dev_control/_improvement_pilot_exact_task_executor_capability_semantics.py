"""Narrow ADR-DC-036 from launch-plan authority to capability-only authority.

ADR-DC-034 now requires an exact host-resolved GitWorkspaceSnapshot before an
execution plan may be considered materialized.  ADR-DC-036 deliberately does not
run trusted-Git evidence commands, so it cannot honestly claim that state yet.
This adapter keeps the already-reviewed value model but changes the canonical
`execution_plan_materialized` invariant from true to false.  The later launch-plan
boundary must be the first layer allowed to set it true after freezing workspace
state.
"""
from __future__ import annotations

from typing import Any


class PilotExactTaskExecutorCapabilitySemanticsError(ValueError):
    """ADR-DC-036 capability-only semantics could not be installed safely."""


def _replace_init_default(cls: type, field_name: str, value: Any) -> None:
    init = cls.__init__
    defaults = list(init.__defaults__ or ())
    names = tuple(init.__code__.co_varnames[1 : init.__code__.co_argcount])
    start = len(names) - len(defaults)
    try:
        absolute = names.index(field_name)
    except ValueError as exc:
        raise PilotExactTaskExecutorCapabilitySemanticsError(
            f"capability constructor is missing {field_name}"
        ) from exc
    index = absolute - start
    if not 0 <= index < len(defaults):
        raise PilotExactTaskExecutorCapabilitySemanticsError(
            f"capability constructor default is unavailable for {field_name}"
        )
    defaults[index] = value
    init.__defaults__ = tuple(defaults)


def install_pilot_exact_task_executor_capability_only_semantics(
    implementation: Any,
) -> None:
    if implementation is None:
        raise PilotExactTaskExecutorCapabilitySemanticsError(
            "executor capability implementation is unavailable"
        )
    marker = "_pilot_exact_task_executor_capability_only_semantics_installed"
    if getattr(implementation, marker, False):
        return

    cls = implementation.PilotExactTaskExecutorCapability
    fields = getattr(cls, "__dataclass_fields__", None)
    if not isinstance(fields, dict) or "execution_plan_materialized" not in fields:
        raise PilotExactTaskExecutorCapabilitySemanticsError(
            "executor capability dataclass layout is unsupported"
        )
    original_post_init = cls.__post_init__
    _replace_init_default(cls, "execution_plan_materialized", False)
    fields["execution_plan_materialized"].default = False

    def capability_only_post_init(self: Any) -> None:
        if self.execution_plan_materialized is not False:
            raise implementation.PilotExactTaskExecutorCapabilityError(
                "ADR-DC-036 cannot claim a materialized execution plan before the exact workspace snapshot boundary"
            )

        # Reuse every existing identity/authority invariant unchanged.  The old
        # validator predates ADR-034's workspace-snapshot hardening and expects
        # this one flag true, so expose that value only during validation and
        # restore capability-only state before construction returns.
        object.__setattr__(self, "execution_plan_materialized", True)
        try:
            original_post_init(self)
        finally:
            object.__setattr__(self, "execution_plan_materialized", False)

    cls.__post_init__ = capability_only_post_init
    setattr(implementation, marker, True)


__all__: list[str] = []
