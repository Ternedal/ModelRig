"""Dependency-free Continuum task transition model. Prototype only; no runtime wiring.

No caller-supplied token can authorize a transition. A verified approval must
be supplied by the transactional store, never directly by an API client.
"""
from dataclasses import dataclass, replace
from enum import Enum

class State(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    RETRYABLE_FAILED = "retryable_failed"
    TERMINAL_FAILED = "terminal_failed"
    CANCELLED = "cancelled"

ALLOWED = {
    State.QUEUED: {State.PLANNING, State.CANCELLED},
    State.PLANNING: {State.AWAITING_APPROVAL, State.EXECUTING, State.RETRYABLE_FAILED, State.TERMINAL_FAILED, State.CANCELLED},
    State.AWAITING_APPROVAL: {State.EXECUTING, State.CANCELLED},
    State.EXECUTING: {State.VERIFYING, State.RETRYABLE_FAILED, State.TERMINAL_FAILED, State.CANCELLED},
    State.VERIFYING: {State.COMPLETED, State.RETRYABLE_FAILED, State.TERMINAL_FAILED},
    State.RETRYABLE_FAILED: {State.PLANNING, State.CANCELLED},
    State.COMPLETED: set(),
    State.TERMINAL_FAILED: set(),
    State.CANCELLED: set(),
}

@dataclass(frozen=True)
class Task:
    task_id: str
    state: State = State.QUEUED
    revision: int = 0
    approved: bool = False
    requires_approval: bool = True

def transition(task: Task, target: State, *, expected_revision: int,
               verified_approval: bool = False) -> Task:
    """Pure state validation. Only a trusted transactional caller may verify grants."""
    if expected_revision != task.revision:
        raise ValueError("stale task revision")
    if target not in ALLOWED[task.state]:
        raise ValueError(f"invalid transition: {task.state} -> {target}")
    if target == State.EXECUTING and task.requires_approval:
        if task.state != State.AWAITING_APPROVAL:
            raise PermissionError("approval checkpoint required")
        if verified_approval is not True:
            raise PermissionError("verified approval required")
    return replace(task, state=target, revision=task.revision + 1,
                   approved=(verified_approval is True and target == State.EXECUTING))
