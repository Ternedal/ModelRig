from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .integration import V2ToolAdapter
from .plan_store import PlanStore
from .replan_planner import TypedReadReplanPlanner
from .replan_preview import ReplanPreviewError, ReplanPreviewService
from .replan_runtime import PersistentReadReplanner


class ReplanPreviewReq(BaseModel):
    planner_model: str | None = Field(default=None, max_length=200)


def _step_payload(step) -> dict[str, Any]:
    return {
        "tool": step.tool,
        "args": step.args,
        "risk": step.risk.value,
        "sensitivity": step.sensitivity.value,
        "egress": step.egress.value,
        "summary": step.summary,
    }


def build_replan_preview_router(service: ReplanPreviewService) -> APIRouter:
    router = APIRouter(prefix="/experimental/agent3", tags=["experimental-agent3-replanner"])

    @router.post("/runs/{run_id}/replan-preview")
    async def preview(run_id: str, req: ReplanPreviewReq) -> dict[str, Any]:
        try:
            preview_id, ttl, stored, proposal = await service.preview(
                run_id,
                model=req.planner_model,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except ReplanPreviewError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "preview_id": preview_id,
            "expires_in_seconds": ttl,
            "run_id": stored.run_id,
            "revision": stored.revision,
            "replan_count": stored.replan_count,
            "rationale": stored.rationale,
            "planner_model": stored.model,
            "prompt_sha256": stored.prompt_sha256,
            "observation_characters": proposal.observation_characters,
            "window": {
                "start": stored.window_start,
                "end": stored.window_end,
                "removable_step_ids": stored.removable_step_ids,
                "immutable_prefix_ids": stored.immutable_prefix_ids,
                "immutable_tail_ids": stored.immutable_tail_ids,
            },
            "plan": [_step_payload(step) for step in proposal.steps],
            "executed": False,
        }

    @router.post("/replan-previews/{preview_id}/apply")
    def apply(preview_id: str) -> dict[str, Any]:
        try:
            run, receipt, stored = service.apply(preview_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except ReplanPreviewError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "run": __import__("json").loads(run.to_json()),
            "replan": receipt,
            "preview": {
                "preview_id": preview_id,
                "run_id": stored.run_id,
                "planner_model": stored.model,
                "prompt_sha256": stored.prompt_sha256,
                "rationale": stored.rationale,
            },
        }

    return router


def _bounded_env_int(name: str, default: int, *, low: int, high: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < low or value > high:
        raise RuntimeError(f"{name} must be between {low} and {high}")
    return value


def build_default_replan_preview_service(
    adapter: V2ToolAdapter,
    replanner: PersistentReadReplanner,
) -> ReplanPreviewService:
    from .. import paths as _paths

    db_path = _paths.resolve(
        "./kaliv-agent3-replan-previews.db",
        env="KALIV_AGENT3_REPLAN_PREVIEW_DB",
    )
    ttl = _bounded_env_int(
        "KALIV_AGENT3_REPLAN_PREVIEW_TTL",
        300,
        low=30,
        high=3600,
    )
    observation_chars = _bounded_env_int(
        "KALIV_AGENT3_REPLAN_OBSERVATION_CHARS",
        6000,
        low=256,
        high=20_000,
    )
    return ReplanPreviewService(
        replanner.run_store,
        replanner,
        TypedReadReplanPlanner(
            adapter,
            replanner.policy,
            max_observation_chars=observation_chars,
        ),
        PlanStore(db_path, ttl_seconds=ttl),
    )
