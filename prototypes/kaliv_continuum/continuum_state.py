"""Dependency-free Continuum task transition model. Prototype only; no runtime wiring."""
from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional

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

def transition(task: Task, target: State, *, expected_revision: int, approval_token: Optional[str] = None) -> Task:
    """Optimistic concurrency; approval is explicit and cannot be inherited implicitly."""
    if expected_revision != task.revision:
        raise ValueError("stale task revision")
    if target not in ALLOWED[task.state]:
        raise ValueError(f"invalid transition: {task.state} -> {target}")
    if target == State.EXECUTING and task.requires_approval and not (task.approved or approval_token):
        raise PermissionError("approval required")
    if target == State.EXECUTING and task.requires_approval and task.state != State.AWAITING_APPROVAL:
        raise PermissionError("approval checkpoint required")
    return replace(task, state=target, revision=task.revision + 1,
                   approved=task.approved or bool(approval_token))
