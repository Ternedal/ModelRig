from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from .core import (
    AgentRun,
    AgentRunStore,
    AgentStep,
    EgressClass,
    RiskClass,
    Sensitivity,
)
from .plan_store import PlanStore, PlanStoreError
from .replan_planner import ReadReplanProposal, ReplanPlannerError, TypedReadReplanPlanner
from .replan_runtime import PersistentReadReplanner, ReplanJournalError, plan_digest
from .replanner import ReplanError


class ReplanPreviewError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredReplanPreview:
    run_id: str
    before_digest: str
    revision: int
    replan_count: int
    rationale: str
    prompt_sha256: str
    model: str | None
    window_start: int
    window_end: int
    removable_step_ids: tuple[str, ...]
    immutable_prefix_ids: tuple[str, ...]
    immutable_tail_ids: tuple[str, ...]
    steps: tuple[dict[str, Any], ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @staticmethod
    def from_json(raw: str) -> "StoredReplanPreview":
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ReplanPreviewError("stored replan preview is invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ReplanPreviewError("stored replan preview is not an object")
        expected = {
            "run_id",
            "before_digest",
            "revision",
            "replan_count",
            "rationale",
            "prompt_sha256",
            "model",
            "window_start",
            "window_end",
            "removable_step_ids",
            "immutable_prefix_ids",
            "immutable_tail_ids",
            "steps",
        }
        if set(payload) != expected:
            raise ReplanPreviewError("stored replan preview has an unsupported schema")
        try:
            steps = tuple(payload["steps"])
            if not all(isinstance(item, dict) for item in steps):
                raise TypeError("steps")
            return StoredReplanPreview(
                run_id=str(payload["run_id"]),
                before_digest=str(payload["before_digest"]),
                revision=int(payload["revision"]),
                replan_count=int(payload["replan_count"]),
                rationale=str(payload["rationale"]),
                prompt_sha256=str(payload["prompt_sha256"]),
                model=None if payload["model"] is None else str(payload["model"]),
                window_start=int(payload["window_start"]),
                window_end=int(payload["window_end"]),
                removable_step_ids=tuple(str(value) for value in payload["removable_step_ids"]),
                immutable_prefix_ids=tuple(str(value) for value in payload["immutable_prefix_ids"]),
                immutable_tail_ids=tuple(str(value) for value in payload["immutable_tail_ids"]),
                steps=steps,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ReplanPreviewError("stored replan preview has invalid field types") from exc


def _step_payload(step: AgentStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "tool": step.tool,
        "args": step.args,
        "risk": step.risk.value,
        "sensitivity": step.sensitivity.value,
        "egress": step.egress.value,
        "origin": step.origin,
        "conversation_id": step.conversation_id,
        "summary": step.summary,
    }


def _step_from_payload(payload: dict[str, Any]) -> AgentStep:
    expected = {
        "id",
        "tool",
        "args",
        "risk",
        "sensitivity",
        "egress",
        "origin",
        "conversation_id",
        "summary",
    }
    if set(payload) != expected or not isinstance(payload.get("args"), dict):
        raise ReplanPreviewError("stored replacement step has an unsupported schema")
    try:
        return AgentStep(
            id=str(payload["id"]),
            tool=str(payload["tool"]),
            args=dict(payload["args"]),
            risk=RiskClass(payload["risk"]),
            sensitivity=Sensitivity(payload["sensitivity"]),
            egress=EgressClass(payload["egress"]),
            origin=str(payload["origin"]),
            conversation_id=(
                None
                if payload["conversation_id"] is None
                else str(payload["conversation_id"])
            ),
            summary=str(payload["summary"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ReplanPreviewError("stored replacement step has invalid field types") from exc


class ReplanPreviewService:
    """Create and atomically consume reviewed LLM read-replan previews."""

    def __init__(
        self,
        run_store: AgentRunStore,
        replanner: PersistentReadReplanner,
        planner: TypedReadReplanPlanner,
        preview_store: PlanStore,
    ):
        self.run_store = run_store
        self.replanner = replanner
        self.planner = planner
        self.preview_store = preview_store

    def _recover_or_raise(self, run_id: str) -> None:
        self.replanner.recover(run_id)
        if self.replanner.journal.conflicts(run_id):
            raise ReplanPreviewError("run has an unresolved replan recovery conflict")

    async def preview(
        self,
        run_id: str,
        *,
        model: str | None = None,
    ) -> tuple[str, int, StoredReplanPreview, ReadReplanProposal]:
        try:
            self._recover_or_raise(run_id)
            run = self.run_store.load(run_id)
            if run is None:
                raise KeyError(run_id)
            revision, replan_count = self.replanner.journal.revision_state(run_id)
            before_digest = plan_digest(run)
            proposal = await self.planner.preview(
                run,
                replan_count=replan_count,
                model=model,
            )
        except KeyError:
            raise
        except (ReplanPlannerError, ReplanError, ReplanJournalError) as exc:
            raise ReplanPreviewError(str(exc)) from exc

        stored = StoredReplanPreview(
            run_id=run_id,
            before_digest=before_digest,
            revision=revision,
            replan_count=replan_count,
            rationale=proposal.rationale,
            prompt_sha256=proposal.prompt_sha256,
            model=model,
            window_start=proposal.window.start,
            window_end=proposal.window.end,
            removable_step_ids=proposal.window.removable_step_ids,
            immutable_prefix_ids=proposal.window.immutable_prefix_ids,
            immutable_tail_ids=proposal.window.immutable_tail_ids,
            steps=tuple(_step_payload(step) for step in proposal.steps),
        )
        preview_id, ttl = self.preview_store.save(stored.to_json())
        return preview_id, ttl, stored, proposal

    def apply(self, preview_id: str) -> tuple[AgentRun, dict[str, Any], StoredReplanPreview]:
        # Consume first. A crash or stale run after this point requires a fresh
        # preview and can never replay the old model proposal.
        try:
            stored = StoredReplanPreview.from_json(self.preview_store.consume(preview_id))
        except PlanStoreError as exc:
            raise ReplanPreviewError(str(exc)) from exc

        try:
            self._recover_or_raise(stored.run_id)
            run = self.run_store.load(stored.run_id)
            if run is None:
                raise KeyError(stored.run_id)
            revision, replan_count = self.replanner.journal.revision_state(stored.run_id)
            if plan_digest(run) != stored.before_digest:
                raise ReplanPreviewError("replan preview is stale because the run changed")
            if revision != stored.revision or replan_count != stored.replan_count:
                raise ReplanPreviewError("replan preview is stale because revision state changed")

            window = self.replanner.policy.window(run)
            if (
                window.start != stored.window_start
                or window.end != stored.window_end
                or window.removable_step_ids != stored.removable_step_ids
                or window.immutable_prefix_ids != stored.immutable_prefix_ids
                or window.immutable_tail_ids != stored.immutable_tail_ids
            ):
                raise ReplanPreviewError("replan preview window no longer matches the run")

            steps = [_step_from_payload(payload) for payload in stored.steps]
            revised, receipt = self.replanner.apply(
                stored.run_id,
                steps,
                reason=stored.rationale,
            )
        except KeyError:
            raise
        except (ReplanError, ReplanJournalError) as exc:
            raise ReplanPreviewError(str(exc)) from exc

        if (
            receipt.from_revision != stored.revision
            or receipt.removed_step_ids != stored.removable_step_ids
            or receipt.immutable_prefix_ids != stored.immutable_prefix_ids
            or receipt.immutable_tail_ids != stored.immutable_tail_ids
        ):
            # The authoritative replan has already been persisted. Marking this as
            # an error is safer than pretending the preview receipt matched; the
            # journal remains the source of truth for operator review.
            raise ReplanPreviewError("committed replan receipt does not match reviewed preview")

        # Keep the service contract identical to the eventual HTTP shape: tuples
        # become JSON arrays and no Python-specific container leaks to callers.
        receipt_payload = json.loads(json.dumps(receipt.to_dict(), ensure_ascii=False))
        return revised, receipt_payload, stored
