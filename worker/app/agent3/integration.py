from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .core import (
    AgentStep,
    EgressClass,
    RiskClass,
    RoutePlan,
    Sensitivity,
)


class Agent3PlanError(RuntimeError):
    pass


# Risk/sensitivity are code-owned. The model or client supplies only tool + args.
_RISK_OVERRIDES: dict[str, RiskClass] = {
    "delete_model": RiskClass.DESTRUCTIVE,
    "pull_model": RiskClass.ADMIN,
}

# The V2 registry is the source of truth for what a tool IS; this maps its
# vocabulary onto Agent 3's finer one. Every V2 class must appear here --
# tests/worker_agent3_risk_parity.py fails if V2 grows one that does not.
_V2_RISK: dict[str, RiskClass] = {
    "read": RiskClass.READ,
    "write": RiskClass.WRITE,
    "desktop": RiskClass.DESKTOP,
}

# V2's vocabulary for where an answer may travel, mapped onto Agent 3's.
# tests/worker_agent3_risk_parity.py fails if V2 grows a class not listed here,
# because the alternative is a fallback quietly choosing one.
_V2_SENSITIVITY: dict[str, Sensitivity] = {
    "public": Sensitivity.PUBLIC,
    "operational": Sensitivity.OPERATIONAL,
    "private": Sensitivity.PRIVATE,
    "secret": Sensitivity.SECRET,
}

_SENSITIVITY: dict[str, Sensitivity] = {
    "current_datetime": Sensitivity.PUBLIC,
    "rig_status": Sensitivity.OPERATIONAL,
    "list_models": Sensitivity.OPERATIONAL,
    "list_documents": Sensitivity.PRIVATE,
    "note_append": Sensitivity.PRIVATE,
    "delete_model": Sensitivity.OPERATIONAL,
    "pull_model": Sensitivity.OPERATIONAL,
}


@dataclass(frozen=True)
class PlannedToolCall:
    tool: str
    args: dict[str, Any]


class V2ToolAdapter:
    """Bridge Agent 3.0 runs to the existing Agent v2 registry and gate.

    Agent 3.0 never executes tool.run directly. Reads go through GATE.propose.
    After an Agent 3.0 approval, writes are proposed to the V2 gate and its
    short-lived internal confirmation is consumed immediately. That keeps the
    existing whitelist, validation, kill switch and audit log load-bearing.
    """

    def __init__(self, tools_module=None):
        if tools_module is None:
            from .. import tools as tools_module  # lazy: avoids import cycles
        self.tools = tools_module

    def is_enabled(self, name: str) -> bool:
        gate = self.tools.GATE
        checker = getattr(gate, "is_enabled", None)
        if callable(checker):
            return bool(checker(name))
        return bool(getattr(gate, "enabled", False) and name in self.tools.REGISTRY)

    def tool_catalog(self) -> list[dict[str, Any]]:
        """Planner-facing catalog. Risk/sensitivity are deliberately omitted."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "params": tool.params,
            }
            for tool in self.tools.REGISTRY.values()
            if self.is_enabled(tool.name)
        ]

    def build_steps(
        self,
        calls: list[PlannedToolCall],
        route: RoutePlan,
        conversation_id: str | None,
    ) -> list[AgentStep]:
        if not route.uses_tools:
            raise Agent3PlanError("a tool plan requires a tools route")
        origin = "cloud" if route.uses_cloud else "local"
        egress = EgressClass.CLOUD if route.uses_cloud else EgressClass.LOCAL
        steps: list[AgentStep] = []
        for call in calls:
            tool = self.tools.REGISTRY.get(call.tool)
            if tool is None:
                raise Agent3PlanError(f"unknown tool: {call.tool}")
            if not self.is_enabled(call.tool):
                raise Agent3PlanError(f"tool disabled: {call.tool}")
            if not isinstance(call.args, dict):
                raise Agent3PlanError(f"arguments for {call.tool} must be an object")
            # Explicit, and fail-closed. The old fallback was "WRITE if the V2
            # tool says write, else READ", which silently downgraded every risk
            # class V2 might grow later -- desktop became a read. A class this
            # layer does not understand must stop the plan, not be guessed at.
            risk = _RISK_OVERRIDES.get(call.tool) or _V2_RISK.get(tool.risk)
            if risk is None:
                raise Agent3PlanError(
                    f"ukendt risikoklasse {tool.risk!r} for {call.tool}: "
                    "Agent 3 planlægger ikke noget den ikke kan klassificere"
                )
            # Sensitivity was the same disease as risk, one axis over (F-511):
            # a table here, a declaration in the V2 registry, and a fallback to
            # PRIVATE. PRIVATE looks conservative and is not -- `secret` is
            # stricter, so a tool declared secret in V2 that this table has not
            # heard of would be DOWNGRADED to private, and private can leave the
            # machine once the egress gate is on. Same shape as desktop reading
            # as READ: the fallback picks a plausible box, and plausible is not
            # the same as true.
            sensitivity = _SENSITIVITY.get(call.tool) or _V2_SENSITIVITY.get(
                tool.sensitivity)
            if sensitivity is None:
                raise Agent3PlanError(
                    f"ukendt følsomhedsklasse {tool.sensitivity!r} for {call.tool}: "
                    "Agent 3 gætter ikke på hvor et svar må rejse hen"
                )
            summary = tool.human_summary(call.args)
            steps.append(
                AgentStep(
                    tool=call.tool,
                    args=dict(call.args),
                    risk=risk,
                    sensitivity=sensitivity,
                    egress=egress,
                    origin=origin,
                    conversation_id=conversation_id,
                    summary=summary,
                )
            )
        return steps

    def execute(self, step: AgentStep) -> Any:
        try:
            result = self.tools.GATE.propose(
                step.tool,
                dict(step.args),
                step.conversation_id,
                origin=step.origin,
            )
        except Exception:
            # Preserve the V2 gate's exact failure semantics and audit entries.
            raise

        status = result.get("status")
        if status == "executed":
            return result.get("result")
        if status != "confirmation_required":
            raise Agent3PlanError(f"unexpected Agent v2 gate status: {status!r}")

        # Agent 3.0 has already persisted and verified the human approval for the
        # immutable step. The V2 gate still gets the final say and may refuse if
        # the kill switch/tool changed while the card was visible.
        confirmed = self.tools.GATE.confirm(result["confirmation_id"], "approve")
        if confirmed.get("status") != "executed":
            raise Agent3PlanError("Agent v2 gate did not execute the approved step")
        return confirmed.get("result")
