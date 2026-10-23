"""Read-only Swarm execution simulator with deterministic receipts.

Never calls external tools. A production worker must use canonical policy,
scoped approvals, idempotency, timeouts and bounded retries.
"""
from dataclasses import dataclass
from swarm_plan import Plan, schedule

@dataclass(frozen=True)
class Receipt:
    step_id: str
    capability: str
    wave: int
    status: str

def simulate(plan: Plan, *, allowed_capabilities, max_steps=32, max_cost=100):
    """Validate all capabilities before returning a non-executing schedule."""
    waves = schedule(plan, max_steps=max_steps, max_cost=max_cost)
    allowed = frozenset(allowed_capabilities)
    if any(step.capability not in allowed for step in plan.steps):
        raise PermissionError("plan contains unauthorized capability")
    steps = {step.step_id: step for step in plan.steps}
    return tuple(
        Receipt(step_id=step_id, capability=steps[step_id].capability,
                wave=index, status="planned_only")
        for index, wave in enumerate(waves) for step_id in wave
    )
