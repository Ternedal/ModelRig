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
# The V2 registry is the source of truth for what a tool IS; this maps its
# vocabulary onto Agent 3's finer one. Every V2 class must appear here --
# tests/worker_agent3_risk_parity.py fails if V2 grows one that does not.
def _sensitivity_of(name: str, tool: object) -> str:
    """Where this tool's RESULT may travel, as the registry declares it.

    Same shape as _impact_of, and the same reason: this is the V2/Agent-3
    boundary, so objects arrive here that are not real Tools. A tool that
    declares nothing cannot be classified, and Agent 3 does not guess where an
    answer may go.
    """
    declared = getattr(tool, "sensitivity", None)
    if declared:
        return str(declared)
    # The registry's own default, applied at the boundary for objects that are
    # not real Tools -- the same move _impact_of makes. Tool.sensitivity is a
    # dataclass field defaulting to "operational" on purpose: the conservative
    # middle, which a tool argues its way OUT of in either direction. So this is
    # not a new guess; it is the same rule, one layer out.
    #
    # The bug was never the default. It was that a name-keyed table BEAT the
    # declaration: a tool declaring itself secret came out private, because a
    # dict four hundred lines away said so. That table is gone.
    return "operational"


def _impact_of(name: str, tool: object) -> str:
    """What the registry says this tool DOES (F-614).

    The same rule Tool.__post_init__ applies -- impact, or risk if the tool has
    nothing sharper to say -- applied here at the V2/Agent-3 boundary, because
    this is where objects arrive that are not real Tools: adapters, doubles, and
    whatever the registry grows into next.

    It is not a fallback that guesses. A real Tool always has impact, because
    the dataclass sets it. A double that cares about being destructive declares
    it. A tool that declares NEITHER cannot be classified, and an unclassifiable
    action stops the plan -- the last time this layer had a fallback, "WRITE if
    it says write, else READ" turned a screenshot into a read.
    """
    impact = getattr(tool, "impact", None)
    if impact:
        return str(impact)
    risk = getattr(tool, "risk", None)
    if risk:
        return str(risk)
    raise Agent3PlanError(
        f"{name} erklærer hverken impact eller risk: Agent 3 planlægger ikke "
        "noget den ikke kan klassificere"
    )


# The registry's vocabulary, mapped onto Agent 3's. Every member of tools.Impact
# must appear: worker_agent3_risk_parity.py fails if the registry grows a class
# this layer cannot name, because the alternative is a fallback quietly choosing
# one -- and the last fallback turned a screenshot into a READ.
_V2_RISK: dict[str, RiskClass] = {
    "read": RiskClass.READ,
    "write": RiskClass.WRITE,
    "desktop": RiskClass.DESKTOP,
    "destructive": RiskClass.DESTRUCTIVE,
    "admin": RiskClass.ADMIN,
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
            # Read from the tool, not from a table over here keyed by its name
            # (F-614). The name-keyed table lived four hundred lines from the
            # definition, in TWO byte-identical copies, and the gate that
            # decides at 03:00 consulted neither -- which is how a model
            # deletion became schedulable (F-604).
            risk = _V2_RISK.get(_impact_of(call.tool, tool))
            if risk is None:
                raise Agent3PlanError(
                    f"ukendt risikoklasse {tool.impact!r} for {call.tool}: "
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
            # From the tool, not from a table over here keyed by its name
            # (F-614, second axis). The name-keyed table WON over the
            # declaration: a tool declaring itself secret was classified
            # private, because a dict four hundred lines from the definition
            # said so. Verified before deleting it -- it did.
            #
            # secret is blocked from cloud; private is merely gated. That is the
            # F-511 downgrade wearing a different hat, and I left it standing
            # this afternoon while removing the identical table for risk, twenty
            # lines up. I fixed the axis I was looking at.
            sensitivity = _V2_SENSITIVITY.get(_sensitivity_of(call.tool, tool))
            if sensitivity is None:
                raise Agent3PlanError(
                    f"ukendt følsomhedsklasse {tool.sensitivity!r} for {call.tool}: "
                    "Agent 3 gætter ikke på hvor et svar må rejse hen"
                )
            # Stamped from the registry, like risk and sensitivity: recovery
            # reads the step, not a registry that may have moved since (F-614).
            idempotent = bool(getattr(tool, "idempotent", False))
            summary = tool.human_summary(call.args)
            steps.append(
                AgentStep(
                    tool=call.tool,
                    args=dict(call.args),
                    risk=risk,
                    sensitivity=sensitivity,
                    egress=egress,
                    origin=origin,
                    idempotent=idempotent,
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
