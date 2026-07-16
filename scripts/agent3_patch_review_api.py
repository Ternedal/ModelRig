from __future__ import annotations

from pathlib import Path


path = Path("worker/app/agent3/api.py")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one exact api.py block, found {count}: {old[:100]!r}")
    text = text.replace(old, new, 1)


replace_once(
    "from .replanner import ReadSuffixReplanner, ReplanError\n",
    "from .replanner import ReadSuffixReplanner, ReplanError\n"
    "from .review_orchestrator import (\n"
    "    ReadReviewStore,\n"
    "    ReviewingAgent3Orchestrator,\n"
    ")\n",
)
replace_once(
    "    proactive: bool = False\n    plan: list[PlanStepReq] = Field(default_factory=list, max_length=12)\n",
    "    proactive: bool = False\n"
    "    review_reads: bool = False\n"
    "    plan: list[PlanStepReq] = Field(default_factory=list, max_length=12)\n",
)
replace_once(
    "    validation_provider = validation_provider or (\n"
    "        lambda: evaluate_configured_report(current_version=worker_version)\n"
    "    )\n\n"
    "    def recover_or_block(run_id: str) -> list[dict[str, Any]]:\n",
    "    validation_provider = validation_provider or (\n"
    "        lambda: evaluate_configured_report(current_version=worker_version)\n"
    "    )\n"
    "    reviewing = isinstance(orchestrator, ReviewingAgent3Orchestrator)\n\n"
    "    def read_review(run_id: str) -> dict[str, Any]:\n"
    "        if not reviewing:\n"
    "            return {\"enabled\": False, \"waiting\": False}\n"
    "        return orchestrator.review_store.get(run_id)\n\n"
    "    def response(run: AgentRun, **extra: Any) -> dict[str, Any]:\n"
    "        payload = {\"run\": _run_payload(run), \"read_review\": read_review(run.id)}\n"
    "        payload.update(extra)\n"
    "        return payload\n\n"
    "    def start_steps(\n"
    "        request: TurnRequest,\n"
    "        caps: CapabilitySnapshot,\n"
    "        steps: list[AgentStep],\n"
    "        *,\n"
    "        proactive: bool,\n"
    "        allow_private_cloud: bool,\n"
    "        review_reads: bool,\n"
    "    ) -> AgentRun:\n"
    "        if review_reads and not reviewing:\n"
    "            raise HTTPException(status_code=501, detail=\"read review is not mounted\")\n"
    "        kwargs = {\n"
    "            \"proactive\": proactive,\n"
    "            \"allow_private_cloud\": allow_private_cloud,\n"
    "        }\n"
    "        if reviewing:\n"
    "            kwargs[\"review_reads\"] = review_reads\n"
    "        return orchestrator.start_with_steps(request, caps, steps, **kwargs)\n\n"
    "    def recover_or_block(run_id: str) -> list[dict[str, Any]]:\n",
)
replace_once(
    '            "replanner": (\n                "explicit-pending-read-window" if replan_service is not None else "disabled"\n            ),\n',
    '            "replanner": (\n                "explicit-pending-read-window" if replan_service is not None else "disabled"\n            ),\n'
    '            "read_review": "opt-in-persistent" if reviewing else "disabled",\n',
)
replace_once(
    "            run = orchestrator.start_with_steps(\n"
    "                request,\n"
    "                caps,\n"
    "                _clone_steps(original),\n"
    "                proactive=original.proactive,\n"
    "                allow_private_cloud=original.allow_private_cloud,\n"
    "            )\n"
    "            return {\"run\": _run_payload(run)}\n",
    "            original_review = read_review(original.id)[\"enabled\"]\n"
    "            run = start_steps(\n"
    "                request,\n"
    "                caps,\n"
    "                _clone_steps(original),\n"
    "                proactive=original.proactive,\n"
    "                allow_private_cloud=original.allow_private_cloud,\n"
    "                review_reads=bool(original_review),\n"
    "            )\n"
    "            return response(run)\n",
)
replace_once(
    "            run = orchestrator.start_with_steps(\n"
    "                request,\n"
    "                caps,\n"
    "                [],\n"
    "                proactive=req.proactive,\n"
    "                allow_private_cloud=req.allow_private_cloud,\n"
    "            )\n"
    "            return {\"run\": _run_payload(run)}\n",
    "            run = start_steps(\n"
    "                request,\n"
    "                caps,\n"
    "                [],\n"
    "                proactive=req.proactive,\n"
    "                allow_private_cloud=req.allow_private_cloud,\n"
    "                review_reads=req.review_reads,\n"
    "            )\n"
    "            return response(run)\n",
)
replace_once(
    "            run = orchestrator.start_with_steps(\n"
    "                request,\n"
    "                caps,\n"
    "                steps,\n"
    "                proactive=req.proactive,\n"
    "                allow_private_cloud=req.allow_private_cloud,\n"
    "            )\n"
    "        except Agent3PlanError as exc:\n"
    "            raise HTTPException(status_code=400, detail=str(exc)) from exc\n"
    "        return {\"run\": _run_payload(run)}\n",
    "            run = start_steps(\n"
    "                request,\n"
    "                caps,\n"
    "                steps,\n"
    "                proactive=req.proactive,\n"
    "                allow_private_cloud=req.allow_private_cloud,\n"
    "                review_reads=req.review_reads,\n"
    "            )\n"
    "        except Agent3PlanError as exc:\n"
    "            raise HTTPException(status_code=400, detail=str(exc)) from exc\n"
    "        return response(run)\n",
)
replace_once(
    '        return {"run": _run_payload(run), "replan_recovery": recovery}\n',
    '        return response(run, replan_recovery=recovery)\n',
)
replace_once(
    '        return {"run": _run_payload(revised), "replan": receipt.to_dict()}\n',
    '        return response(revised, replan=receipt.to_dict())\n',
)
# confirm, resume and cancel each have the same one-line response.
old = '        return {"run": _run_payload(run)}\n'
if text.count(old) != 3:
    raise SystemExit(f"expected three remaining run responses, found {text.count(old)}")
text = text.replace(old, '        return response(run)\n')
replace_once(
    "    adapter = V2ToolAdapter()\n"
    "    db_path = _paths.resolve(\"./kaliv-agent3.db\", env=\"KALIV_AGENT3_DB\")\n"
    "    store = AgentRunStore(db_path)\n"
    "    orchestrator = Agent3Orchestrator(store=store, executor=adapter.execute)\n",
    "    adapter = V2ToolAdapter()\n"
    "    db_path = _paths.resolve(\"./kaliv-agent3.db\", env=\"KALIV_AGENT3_DB\")\n"
    "    review_path = _paths.resolve(\n"
    "        \"./kaliv-agent3-read-reviews.db\",\n"
    "        env=\"KALIV_AGENT3_REVIEW_DB\",\n"
    "    )\n"
    "    store = AgentRunStore(db_path)\n"
    "    orchestrator = ReviewingAgent3Orchestrator(\n"
    "        store=store,\n"
    "        executor=adapter.execute,\n"
    "        review_store=ReadReviewStore(review_path),\n"
    "    )\n",
)
replace_once(
    "    app.state.agent3_orchestrator = orchestrator\n"
    "    app.state.agent3_replanner = replan_service\n",
    "    app.state.agent3_orchestrator = orchestrator\n"
    "    app.state.agent3_replanner = replan_service\n"
    "    app.state.agent3_read_review_store = orchestrator.review_store\n",
)

path.write_text(text, encoding="utf-8")
