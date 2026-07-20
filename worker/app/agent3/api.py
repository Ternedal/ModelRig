from __future__ import annotations

import json
import os
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import capability_probe


def _build_code_identity() -> str:
    from ..build_identity import code_fingerprint

    return code_fingerprint()

from .core import (
    Agent3Orchestrator,
    AgentRun,
    AgentRunStore,
    AgentStep,
    CapabilitySnapshot,
    ConfirmationError,
    RouteKind,
    RunConflict,
    TurnRequest,
)
from .integration import Agent3PlanError, PlannedToolCall, V2ToolAdapter
from .replan_runtime import (
    PersistentReadReplanner,
    ReplanJournal,
    ReplanJournalError,
)
from .replanner import ReadSuffixReplanner, ReplanError
from .review_orchestrator import (
    ReadReviewStore,
    ReviewingAgent3Orchestrator,
)
from .routing import StrictTurnRouter
from .validation_gate import evaluate_configured_report


class PlanStepReq(BaseModel):
    tool: str = Field(min_length=1, max_length=100)
    args: dict[str, Any] = Field(default_factory=dict)


class StartReq(BaseModel):
    """Shared request facts for the test-only explicit-plan fixture.

    Production run creation is server-authored through /plan followed by the
    single-use /plans/{plan_id}/start endpoint. Deliberately no plan field.
    """

    message: str = Field(min_length=1, max_length=20_000)
    mode: str = Field(default="rig", pattern="^(rig|cloud)$")
    tools: bool = True
    rag: bool = False
    has_image: bool = False
    voice: bool = False
    allow_rag_cloud: bool = False
    allow_private_cloud: bool = False
    auto_cloud_fallback: bool = False
    cloud_ready: bool = False
    conversation_id: str | None = None
    proactive: bool = False
    review_reads: bool = False


class ExplicitStartReq(StartReq):
    """Test fixture only; never mounted by the production entrypoint."""

    plan: list[PlanStepReq] = Field(default_factory=list, max_length=12)


class RetryReq(BaseModel):
    """The only client-owned retry fact is whether its cloud key is ready."""

    model_config = ConfigDict(extra="forbid")
    cloud_ready: bool = False


class ConfirmReq(BaseModel):
    step_id: str
    decision: str = Field(pattern="^(approve|deny)$")
    digest: str


class ReplanReq(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    # Empty is valid: it means the remaining pending read window is unnecessary.
    plan: list[PlanStepReq] = Field(default_factory=list, max_length=12)


class CancelReq(BaseModel):
    reason: str | None = None


def _run_payload(run: AgentRun) -> dict[str, Any]:
    data = json.loads(run.to_json())
    # Confirmation digests are intentionally returned: the client must echo the
    # digest it showed. Results/args remain visible because this API is protected
    # by the backend or loopback-only when called directly.
    return data


def _clone_steps(run: AgentRun) -> list[AgentStep]:
    """Clone the validated original plan with fresh step IDs and no old results."""
    # Clone via the step itself, which keeps every declared property. Listing
    # fields here is how retry dropped idempotent (F-715): a copy that names
    # what it keeps forgets the next field added.
    return [step.cloned_for_retry() for step in run.steps]


def _default_caps(req: StartReq | RetryReq, adapter: V2ToolAdapter) -> CapabilitySnapshot:
    """Measure the rig; do not describe it from memory (F-302).

    rig_reachable/worker_ready/rag_ready were hardcoded True here -- three
    facts nobody checked -- so plans were built on a rig that was assumed to
    exist. tools_ready was always measured, which is why the fix is small: the
    pattern was right, it just stopped after one field.

    cloud_ready stays a client input because it is the one fact the client
    genuinely owns: the cloud key lives in the client, not on the rig. It is a
    client capability, not a measurement of this machine -- and it can only
    make a plan FAIL later, never unlock anything the gate protects.
    """
    tools_ready = bool(adapter.tools.GATE.enabled and not adapter.tools.GATE.state_error)
    rig = capability_probe.measure()
    return CapabilitySnapshot(
        rig_reachable=rig["rig_reachable"],
        worker_ready=rig["worker_ready"],
        tools_ready=tools_ready,
        cloud_ready=req.cloud_ready,
        rag_ready=rig["rag_ready"],
        voice_ready=False,
    )


ValidationProvider = Callable[[], dict[str, Any]]


def build_router(
    orchestrator: Agent3Orchestrator,
    adapter: V2ToolAdapter,
    capability_provider: Callable[[StartReq | RetryReq, V2ToolAdapter], CapabilitySnapshot] = _default_caps,
    validation_provider: ValidationProvider | None = None,
    worker_version: str | None = None,
    replan_service: PersistentReadReplanner | None = None,
    *,
    allow_client_plans: bool = False,
) -> APIRouter:
    router = APIRouter(prefix="/experimental/agent3", tags=["experimental-agent3"])
    orchestrator.router = StrictTurnRouter()
    validation_provider = validation_provider or (
        lambda: evaluate_configured_report(
            current_version=worker_version, current_code=_build_code_identity())
    )
    reviewing = isinstance(orchestrator, ReviewingAgent3Orchestrator)

    def read_review(run_id: str) -> dict[str, Any]:
        if not reviewing:
            return {"enabled": False, "waiting": False}
        return orchestrator.review_store.get(run_id)

    def response(run: AgentRun, **extra: Any) -> dict[str, Any]:
        payload = {"run": _run_payload(run), "read_review": read_review(run.id)}
        payload.update(extra)
        return payload

    def start_steps(
        request: TurnRequest,
        caps: CapabilitySnapshot,
        steps: list[AgentStep],
        *,
        proactive: bool,
        allow_private_cloud: bool,
        review_reads: bool,
    ) -> AgentRun:
        if review_reads and not reviewing:
            raise HTTPException(status_code=501, detail="read review is not mounted")
        kwargs = {
            "proactive": proactive,
            "allow_private_cloud": allow_private_cloud,
        }
        if reviewing:
            kwargs["review_reads"] = review_reads
        return orchestrator.start_with_steps(request, caps, steps, **kwargs)

    def recover_or_block(run_id: str) -> list[dict[str, Any]]:
        """Resolve any write-ahead replan before the run may move again."""
        if replan_service is None:
            return []
        try:
            outcomes = replan_service.recover(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        conflicts = replan_service.journal.conflicts(run_id)
        if conflicts:
            raise HTTPException(
                status_code=409,
                detail="run has an unresolved replan recovery conflict",
            )
        return outcomes

    @router.get("/status")
    def status() -> dict[str, Any]:
        validation = validation_provider()
        return {
            "enabled": True,
            "experimental": True,
            "planner": "server-authored-plan-token",
            "client_plan_route": allow_client_plans,
            "replanner": (
                "explicit-pending-read-window" if replan_service is not None else "disabled"
            ),
            "read_review": "opt-in-persistent" if reviewing else "disabled",
            "production_tools_path_untouched": True,
            "max_steps": orchestrator.max_steps,
            "worker_version": worker_version,
            # What this worker RAN, not what it calls itself (F-508). The
            # harness is on the other end of an HTTP connection and cannot hash
            # the rig's files, so the rig has to say. Two trees can carry the
            # same semver; every commit that does not bump makes another one.
            "code_sha256": _build_code_identity(),
            "rig_validation": validation,
            # Promotion evidence is advisory in this draft. Even a valid report
            # cannot activate production routing or tool execution by itself.
            "production_activation": False,
        }

    def start_explicit(req: ExplicitStartReq) -> dict[str, Any]:
        """Exercise the low-level adapter in tests without exposing it in production."""
        caps = capability_provider(req, adapter)
        if not req.plan:
            raise HTTPException(status_code=422, detail="the test fixture requires a plan")
        if not req.tools:
            raise HTTPException(status_code=400, detail="an explicit tool plan requires tools=true")
        request = TurnRequest(
            message=req.message,
            mode=req.mode,
            tools=req.tools,
            rag=req.rag,
            has_image=req.has_image,
            voice=req.voice,
            allow_rag_cloud=req.allow_rag_cloud,
            auto_cloud_fallback=req.auto_cloud_fallback,
            conversation_id=req.conversation_id,
        )
        route = orchestrator.router.route(request, caps)
        if route.kind in {RouteKind.UNAVAILABLE, RouteKind.ASK_BEFORE_DOWNGRADE}:
            run = start_steps(
                request,
                caps,
                [],
                proactive=req.proactive,
                allow_private_cloud=req.allow_private_cloud,
                review_reads=req.review_reads,
            )
            return response(run)
        try:
            calls = [PlannedToolCall(step.tool, step.args) for step in req.plan]
            steps = adapter.build_steps(calls, route, req.conversation_id)
            run = start_steps(
                request,
                caps,
                steps,
                proactive=req.proactive,
                allow_private_cloud=req.allow_private_cloud,
                review_reads=req.review_reads,
            )
        except Agent3PlanError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return response(run)

    if allow_client_plans:
        router.add_api_route(
            "/runs",
            start_explicit,
            methods=["POST"],
            include_in_schema=False,
        )


    @router.post("/runs/{run_id}/retry")
    def retry(run_id: str, req: RetryReq) -> dict[str, Any]:
        original = orchestrator.store.load(run_id)
        if original is None:
            raise HTTPException(status_code=404, detail="original run not found")
        caps = capability_provider(req, adapter)
        request = TurnRequest(
            message=original.request.message,
            mode=original.request.mode,
            tools=original.request.tools,
            rag=original.request.rag,
            has_image=original.request.has_image,
            voice=original.request.voice,
            allow_rag_cloud=original.request.allow_rag_cloud,
            auto_cloud_fallback=original.request.auto_cloud_fallback,
            retry_of_run_id=original.id,
            original_route=original.route.kind,
            conversation_id=original.request.conversation_id,
        )
        original_review = read_review(original.id)["enabled"]
        run = start_steps(
            request,
            caps,
            _clone_steps(original),
            proactive=original.proactive,
            allow_private_cloud=original.allow_private_cloud,
            review_reads=bool(original_review),
        )
        return response(run)

    @router.get("/runs")
    def list_runs(limit: int = 50) -> dict[str, Any]:
        return {"runs": [_run_payload(run) for run in orchestrator.store.recent(limit)]}

    @router.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        recovery = recover_or_block(run_id)
        run = orchestrator.store.load(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return response(run, replan_recovery=recovery)

    @router.get("/runs/{run_id}/events")
    def get_events(run_id: str, limit: int = 200) -> dict[str, Any]:
        if orchestrator.store.load(run_id) is None:
            raise HTTPException(status_code=404, detail="run not found")
        return {"events": orchestrator.store.events(run_id, limit)}

    @router.get("/runs/{run_id}/replans")
    def get_replans(run_id: str) -> dict[str, Any]:
        if replan_service is None:
            raise HTTPException(status_code=501, detail="replanner is not mounted")
        recovery = recover_or_block(run_id)
        if orchestrator.store.load(run_id) is None:
            raise HTTPException(status_code=404, detail="run not found")
        revision, replan_count = replan_service.journal.revision_state(run_id)
        return {
            "revision": revision,
            "replan_count": replan_count,
            "transactions": replan_service.journal.history(run_id),
            "replan_recovery": recovery,
        }

    def replan(run_id: str, req: ReplanReq) -> dict[str, Any]:
        if replan_service is None:
            raise HTTPException(status_code=501, detail="replanner is not mounted")
        recover_or_block(run_id)
        run = orchestrator.store.load(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        try:
            calls = [PlannedToolCall(step.tool, step.args) for step in req.plan]
            replacement_steps = adapter.build_steps(
                calls,
                run.route,
                run.request.conversation_id,
            )
            revised, receipt = replan_service.apply(
                run_id,
                replacement_steps,
                reason=req.reason,
            )
        except Agent3PlanError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (ReplanError, ReplanJournalError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return response(revised, replan=receipt.to_dict())

    @router.post("/runs/{run_id}/confirm")
    def confirm(run_id: str, req: ConfirmReq) -> dict[str, Any]:
        recover_or_block(run_id)
        try:
            run = orchestrator.confirm(run_id, req.step_id, req.decision, req.digest)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except ConfirmationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return response(run)

    @router.post("/runs/{run_id}/resume")
    def resume(run_id: str) -> dict[str, Any]:
        recover_or_block(run_id)
        try:
            run = orchestrator.advance(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except RunConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return response(run)

    @router.post("/runs/{run_id}/cancel")
    def cancel(run_id: str, _req: CancelReq | None = None) -> dict[str, Any]:
        recover_or_block(run_id)
        try:
            run = orchestrator.cancel(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        return response(run)

    # The raw replacement-plan door, behind the same flag as the explicit-start
    # fixture and off by default (F-608).
    #
    # The initial plan is server-authored: a model writes it, the server stores
    # it, and the client gets a short-lived single-use id. Then this route let
    # the client hand in a replacement plan for the rest of the read window.
    # Constrained to fresh pending reads, so not an escalation -- but "the plan
    # is server-authored" was true of the door I had just fixed and false of
    # this one, and ACTIVATION_READINESS said SAFE the entire time, because it
    # read the door I had checked rather than the property.
    #
    # Production replanning goes through /runs/{id}/replan-preview: the server
    # authors the replacement, stores it, and the client applies it by consuming
    # a single-use preview id. Kaliv and the desktop client already do exactly
    # that. This door had no callers at all -- it existed because it was built
    # first, and nothing ever went back to close it.
    if allow_client_plans:
        router.add_api_route(
            "/runs/{run_id}/replan",
            replan,
            methods=["POST"],
            include_in_schema=False,
        )

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


def build_default_runtime() -> tuple[Agent3Orchestrator, V2ToolAdapter]:
    from .. import paths as _paths

    adapter = V2ToolAdapter()
    db_path = _paths.resolve("./kaliv-agent3.db", env="KALIV_AGENT3_DB")
    review_path = _paths.resolve(
        "./kaliv-agent3-read-reviews.db",
        env="KALIV_AGENT3_REVIEW_DB",
    )
    store = AgentRunStore(db_path)
    orchestrator = ReviewingAgent3Orchestrator(
        store=store,
        executor=adapter.execute,
        review_store=ReadReviewStore(review_path),
    )
    orchestrator.router = StrictTurnRouter()
    return orchestrator, adapter


def build_default_replanner(orchestrator: Agent3Orchestrator) -> PersistentReadReplanner:
    from .. import paths as _paths

    journal_path = _paths.resolve(
        "./kaliv-agent3-replans.db",
        env="KALIV_AGENT3_REPLAN_DB",
    )
    max_replans = _bounded_env_int("KALIV_AGENT3_MAX_REPLANS", 3, low=0, high=20)
    return PersistentReadReplanner(
        orchestrator.store,
        ReplanJournal(journal_path),
        ReadSuffixReplanner(
            max_steps=orchestrator.max_steps,
            max_replans=max_replans,
        ),
    )


def mount_agent3(app: FastAPI) -> bool:
    """Mount once, only when the explicit feature flag is enabled."""
    if os.getenv("KALIV_AGENT3_ENABLED", "0") != "1":
        return False
    if getattr(app.state, "agent3_mounted", False):
        return True
    orchestrator, adapter = build_default_runtime()
    replan_service = build_default_replanner(orchestrator)
    app.include_router(
        build_router(
            orchestrator,
            adapter,
            worker_version=getattr(app, "version", None),
            replan_service=replan_service,
        )
    )
    # The planner surface (/plan -> /plans/{id}/start) is the DOCUMENTED
    # production creation path (see StartReq's docstring), yet it lived on
    # its own router that nothing included -- the same orphaned-wiring
    # failure as the mount itself, one layer down. The earlier diagnosis
    # ("rewrite the model_eval producer to a chat->runs flow") was wrong:
    # the producer's target route was right all along; only the wiring was
    # missing.
    from .planner import build_planner_router  # local: avoids import cycles
    app.include_router(
        build_planner_router(adapter, orchestrator=orchestrator)
    )
    # Third instance of the same orphaned-wiring class (mount -> planner ->
    # memory): build_memory_router existed, was suite-tested in isolation,
    # and had ZERO callers -- the rig-evidence harness calls POST /memory,
    # POST /memory/context-preview and DELETE /memory/{id}, so the ps1's
    # step 1 died in 404 on rig day. Found by auditing the harness'
    # complete route contract against the mounted table (openapi lens).
    from .. import paths as _paths
    from .memory import MemoryStore
    from .memory_api import build_memory_router
    memory_path = _paths.resolve(
        "./kaliv-agent3-memory.db", env="KALIV_AGENT3_MEMORY_DB"
    )
    memory_store = MemoryStore(str(memory_path))
    app.include_router(build_memory_router(memory_store))
    app.state.agent3_memory_store = memory_store
    app.state.agent3_mounted = True
    app.state.agent3_orchestrator = orchestrator
    app.state.agent3_replanner = replan_service
    app.state.agent3_read_review_store = orchestrator.review_store
    return True
