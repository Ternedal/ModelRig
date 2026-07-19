from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .. import tools
from .core import AgentRun, RunState, StepState

SCHEMA = "kaliv-agent3-termination/v1"
_TERMINAL_RUNS = {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}
_SEMANTICS = {
    "none": "none",
    "cooperative": "cooperative",
    "forceable": "runtime",
}


def _tool_semantics(name: str) -> tuple[str | None, str | None]:
    tool = tools.REGISTRY.get(name)
    if tool is None:
        return None, "tool_is_not_in_registry"
    declared = str(getattr(tool, "cancellation", "none"))
    mapped = _SEMANTICS.get(declared)
    if mapped is None:
        return None, "unknown_registry_cancellation_semantics"
    return mapped, None


def termination_view(run: AgentRun) -> dict[str, Any]:
    """Server-authored truth for plan, model stream and active tool termination.

    The current Agent 3 executor is synchronous and exposes no per-call handle.
    Registry cancellation metadata describes the tool family; it is not proof
    that this particular execution can be stopped. The response therefore
    remains fail-closed even for cooperative/forceable declarations until a
    concrete runtime handle is bound and tested.
    """

    active = run.steps[run.current_step] if run.current_step < len(run.steps) else None
    executing = active is not None and active.state == StepState.EXECUTING
    completed_after_cancel = (
        active is not None and active.state == StepState.COMPLETED_AFTER_CANCEL
    )
    plan_can_request = run.state not in _TERMINAL_RUNS

    if active is None:
        active_tool = None
    else:
        semantics, semantics_error = _tool_semantics(active.tool)
        if completed_after_cancel:
            request_state, reason = "terminal", "tool_completed_after_plan_cancel"
        elif not executing:
            request_state, reason = "not_active", "tool_is_not_executing"
        elif semantics_error is not None:
            request_state, reason = "unavailable", semantics_error
        elif semantics == "none":
            request_state, reason = (
                "unavailable",
                "synchronous_tool_has_no_cancellation_handle",
            )
        else:
            request_state, reason = (
                "unavailable",
                "declared_semantics_but_runtime_handle_not_bound",
            )
        active_tool = {
            "step_id": active.id,
            "tool": active.tool,
            "state": active.state.value,
            "semantics": semantics,
            "handle_present": False,
            "can_request": False,
            "request_state": request_state,
            "reason": reason,
        }

    return {
        "schema": SCHEMA,
        "plan": {
            "state": "available" if plan_can_request else "terminal",
            "can_request": plan_can_request,
            "request_scope": "plan",
            "effect": (
                "prevent_future_steps_active_tool_continues"
                if executing
                else "prevent_future_steps"
            ),
            "reason": (
                "plan_stop_is_available" if plan_can_request else "run_is_terminal"
            ),
        },
        "model_stream": {
            "state": "not_active",
            "active": False,
            "can_request": False,
            "handle_present": False,
            "reason": "agent3_run_has_no_model_stream_handle",
        },
        "active_tool": active_tool,
        "production_activation": False,
    }


def install_termination_contract(app: FastAPI) -> None:
    """Attach the receipt to the isolated Agent 3 HTTP surface exactly once."""

    if getattr(app.state, "agent3_termination_contract_mounted", False):
        return

    @app.middleware("http")
    async def agent3_termination_receipt(request: Request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith("/experimental/agent3/"):
            return response
        if "application/json" not in response.headers.get("content-type", ""):
            return response

        body = b"".join([chunk async for chunk in response.body_iterator])
        payload = json.loads(body)
        if isinstance(payload, dict) and isinstance(payload.get("run"), dict):
            run = AgentRun.from_json(
                json.dumps(payload["run"], ensure_ascii=False, sort_keys=True)
            )
            payload["termination"] = termination_view(run)

        headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in {"content-length", "content-type"}
        }
        return JSONResponse(
            payload,
            status_code=response.status_code,
            headers=headers,
            background=response.background,
        )

    app.state.agent3_termination_contract_mounted = True
