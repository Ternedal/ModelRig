from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from .capability_graph import CapabilityGraph
from .core import AgentRun, EgressClass, RouteKind, Sensitivity


@dataclass(frozen=True)
class CapabilityBlocker:
    capability_id: str
    state: str
    reason: str


@dataclass(frozen=True)
class CapabilityReceipt:
    schema: str
    graph_sha256: str
    plan_sha256: str
    route: str
    allowed: bool
    required_capability_ids: tuple[str, ...]
    blockers: tuple[CapabilityBlocker, ...]
    production_activation: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_capability_ids"] = list(self.required_capability_ids)
        payload["blockers"] = [asdict(blocker) for blocker in self.blockers]
        return payload


def _sha256(payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def capability_graph_sha256(graph: CapabilityGraph) -> str:
    payload = graph.to_dict()
    payload["nodes"] = sorted(payload["nodes"], key=lambda node: node["id"])
    payload["edges"] = sorted(
        payload["edges"],
        key=lambda edge: (edge["source"], edge["target"], edge["relation"]),
    )
    return _sha256(payload)


def agent_run_plan_sha256(run: AgentRun) -> str:
    """Identify the PLAN, so a finished run can be matched to what was approved.

    This digest answers one question: "is this the plan the operator reviewed?"
    It therefore covers only what the operator was shown and agreed to -- the
    route, and each step's action, arguments and risk axes.

    It must NOT cover anything that changes by executing the plan, and it used
    to cover two such things:

      step.id     _clone_steps mints a fresh uuid4 per step when the run is
                  created from the approved template (AgentStep.cloned_for_retry).
      step.state  PENDING while under review, SUCCEEDED once the step has run.

    Both change by construction, so the durable receipt stored against a
    finished run could never equal the receipt shown at preview. Preview and
    start agreed only because both hash the still-pending template. The
    consequence was that the capability receipt -- the record that exists to
    prove which plan actually ran -- could not bind any completed run to its
    approval, and the read-only pilot failed 20/20 on the rig with
    "durable capability receipt is not bound to the reviewed plan".

    A step's identity, for this purpose, is what it DOES. If execution state
    ever needs attesting, it belongs in a separate digest, so a verifier can ask
    "was this the approved plan?" and "how did it go?" independently.
    """
    return _sha256(
        {
            "route": {
                "kind": run.route.kind.value,
                "uses_cloud": run.route.uses_cloud,
                "uses_rig": run.route.uses_rig,
                "uses_tools": run.route.uses_tools,
                "uses_rag": run.route.uses_rag,
            },
            "voice": run.request.voice,
            "steps": [
                {
                    "tool": step.tool,
                    "args": step.args,
                    "risk": step.risk.value,
                    "sensitivity": step.sensitivity.value,
                    "egress": step.egress.value,
                    "origin": step.origin,
                    "conversation_id": step.conversation_id,
                }
                for step in run.steps
            ],
        }
    )


def evaluate_run_capabilities(
    graph: CapabilityGraph,
    run: AgentRun,
) -> CapabilityReceipt:
    """Evaluate a stored run against a read-only graph; never route or execute."""
    if graph.schema != "kaliv-agent3-capability-graph/v1":
        raise ValueError(f"unsupported capability graph schema: {graph.schema}")
    if graph.production_activation:
        raise ValueError("capability evidence must never activate production")

    nodes = {node.id: node for node in graph.nodes}
    required: set[str] = set()
    blockers: list[CapabilityBlocker] = []

    if run.route.kind in {RouteKind.UNAVAILABLE, RouteKind.ASK_BEFORE_DOWNGRADE}:
        blockers.append(
            CapabilityBlocker(
                "route",
                "blocked",
                f"route {run.route.kind.value} is not executable",
            )
        )
    if run.route.uses_rig:
        required.update(("rig", "worker"))
    if run.route.uses_cloud:
        required.add("cloud")
    if run.route.uses_rag:
        required.add("rag")
    if run.request.voice:
        required.add("voice")
    if run.route.uses_tools or run.steps:
        required.add("tool_gate")

    for step in run.steps:
        tool_id = f"tool:{step.tool}"
        required.add(tool_id)
        if step.egress == EgressClass.CLOUD:
            required.add("cloud")
        if step.egress == EgressClass.CLOUD and step.sensitivity == Sensitivity.SECRET:
            blockers.append(
                CapabilityBlocker(
                    tool_id,
                    "blocked",
                    "secret tool data may never use cloud egress",
                )
            )
        node = nodes.get(tool_id)
        if node is not None:
            graph_risk = node.metadata.get("risk")
            if graph_risk != step.risk.value:
                blockers.append(
                    CapabilityBlocker(
                        tool_id,
                        "blocked",
                        "stored step risk does not match code-owned capability risk",
                    )
                )

    for capability_id in sorted(required):
        node = nodes.get(capability_id)
        if node is None:
            blockers.append(
                CapabilityBlocker(
                    capability_id,
                    "missing",
                    "required capability is absent from the graph",
                )
            )
        elif node.state != "ready":
            blockers.append(
                CapabilityBlocker(
                    capability_id,
                    node.state,
                    node.reason,
                )
            )

    deduped: list[CapabilityBlocker] = []
    seen: set[tuple[str, str, str]] = set()
    for blocker in blockers:
        key = (blocker.capability_id, blocker.state, blocker.reason)
        if key not in seen:
            seen.add(key)
            deduped.append(blocker)

    return CapabilityReceipt(
        schema="kaliv-agent3-capability-receipt/v1",
        graph_sha256=capability_graph_sha256(graph),
        plan_sha256=agent_run_plan_sha256(run),
        route=run.route.kind.value,
        allowed=not deduped,
        required_capability_ids=tuple(sorted(required)),
        blockers=tuple(deduped),
        production_activation=False,
    )
