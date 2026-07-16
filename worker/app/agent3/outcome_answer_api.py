from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .core import AgentRunStore
from .outcome_answer import OutcomeAnswerError, TypedOutcomeAnswerer


class OutcomeAnswerPreviewReq(BaseModel):
    answer_model: str | None = Field(default=None, max_length=200)
    max_context_chars: int = Field(default=12_000, ge=0, le=20_000)
    max_context_steps: int = Field(default=50, ge=0, le=200)


def _context_receipt(preview) -> dict[str, Any]:
    return {
        "target": preview.context.target.value,
        "included_step_ids": list(preview.context.included_step_ids),
        "excluded_step_ids": list(preview.context.excluded_step_ids),
        "character_count": preview.context.character_count,
        "sha256": preview.context.sha256,
    }


def build_outcome_answer_router(
    run_store: AgentRunStore,
    answerer: TypedOutcomeAnswerer | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/experimental/agent3", tags=["experimental-agent3-answer"])
    answerer = answerer or TypedOutcomeAnswerer()

    @router.post("/runs/{run_id}/answer-preview")
    async def preview(run_id: str, req: OutcomeAnswerPreviewReq) -> dict[str, Any]:
        run = run_store.load(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        try:
            result = await answerer.preview(
                run,
                model=req.answer_model,
                max_context_chars=req.max_context_chars,
                max_context_steps=req.max_context_steps,
            )
        except OutcomeAnswerError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        # Preview is deliberately detached from AgentRun.answer. The API makes
        # that boundary explicit so clients cannot mistake synthesis for a
        # persisted or automatically delivered chat response.
        return {
            "run_id": run.id,
            "run_state": run.state.value,
            "answer": result.answer,
            "limitations": list(result.limitations),
            "answer_model": result.model,
            "context": _context_receipt(result),
            "prompt_sha256": result.prompt_sha256,
            "executed": False,
            "persisted": False,
            "delivered_to_chat": False,
        }

    return router
