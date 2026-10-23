"""Deterministic, bounded Swarm DAG planner prototype.

This module schedules *descriptions* of work only. It never executes tools.
A separate policy authority must approve capabilities and side effects.
"""
from dataclasses import dataclass
from typing import Tuple

@dataclass(frozen=True)
class Step:
    step_id: str
    capability: str
    dependencies: Tuple[str, ...] = ()
    estimated_cost: int = 1

@dataclass(frozen=True)
class Plan:
    steps: Tuple[Step, ...]

def schedule(plan: Plan, *, max_steps=32, max_cost=100):
    """Return topological execution waves, rejecting invalid or over-budget DAGs."""
    if not isinstance(plan, Plan) or not 1 <= len(plan.steps) <= max_steps:
        raise ValueError("invalid step count")
    ids = [s.step_id for s in plan.steps]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("duplicate or empty step id")
    by_id = {s.step_id: s for s in plan.steps}
    total = 0
    for step in plan.steps:
        if not isinstance(step.capability, str) or not step.capability:
            raise ValueError("missing capability")
        if type(step.estimated_cost) is not int or step.estimated_cost < 0:
            raise ValueError("invalid cost")
        total += step.estimated_cost
        if len(set(step.dependencies)) != len(step.dependencies):
            raise ValueError("duplicate dependencies")
        if any(dep not in by_id or dep == step.step_id for dep in step.dependencies):
            raise ValueError("invalid dependency")
    if total > max_cost:
        raise ValueError("budget exceeded")
    remaining = set(ids)
    completed = set()
    waves = []
    while remaining:
        ready = tuple(i for i in ids if i in remaining
                      and set(by_id[i].dependencies).issubset(completed))
        if not ready:
            raise ValueError("cyclic dependency")
        waves.append(ready)
        completed.update(ready)
        remaining.difference_update(ready)
    return tuple(waves)
