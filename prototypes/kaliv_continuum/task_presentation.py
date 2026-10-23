"""Stable read-only client presentation of Continuum task state.

These are UI hints, not authorization decisions. The server-side policy
authority remains responsible for permission checks and approval issuance.
"""
from continuum_state import State

_PRESENTATION = {
    State.QUEUED: ("queued", False, False),
    State.PLANNING: ("planning", False, False),
    State.AWAITING_APPROVAL: ("approval_required", True, False),
    State.EXECUTING: ("running", False, False),
    State.VERIFYING: ("verifying", False, False),
    State.COMPLETED: ("completed", False, True),
    State.RETRYABLE_FAILED: ("retryable_error", False, False),
    State.TERMINAL_FAILED: ("failed", False, True),
    State.CANCELLED: ("cancelled", False, True),
}

def present(state):
    state = State(state)
    label, awaiting_approval, terminal = _PRESENTATION[state]
    return {
        "phase": label,
        "awaiting_approval": awaiting_approval,
        "terminal": terminal,
        "can_request_approval": awaiting_approval,
        "is_running": state in (State.EXECUTING, State.VERIFYING),
    }
