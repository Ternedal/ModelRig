from __future__ import annotations

from . import core as _core


class Agent3PolicyEngine(_core.PolicyEngine):
    """Load-bearing Agent 3.0 policy aligned with the existing V2 ToolGate.

    A cloud-originated read is not harmless: its result is returned to a cloud
    model and therefore leaves the rig. Agent v2 already requires a confirmation
    for every cloud-originated tool call. Agent 3.0 must ask first as well;
    otherwise the adapter's immediate consumption of V2's internal confirmation
    would silently bypass the card the user was supposed to see.
    """

    def evaluate(
        self,
        step: _core.AgentStep,
        *,
        proactive: bool = False,
        allow_private_cloud: bool = False,
    ) -> _core.PolicyDecision:
        if proactive and step.risk != _core.RiskClass.READ:
            return _core.PolicyDecision("block", "Proactive runs are read-only")

        if step.egress == _core.EgressClass.CLOUD:
            if step.sensitivity == _core.Sensitivity.SECRET:
                return _core.PolicyDecision("block", "Secret data may never leave the rig")
            if step.sensitivity == _core.Sensitivity.PRIVATE and not allow_private_cloud:
                return _core.PolicyDecision("block", "Private data needs explicit cloud consent")
            # Consent answers whether this data class may be sent to cloud. The
            # confirmation answers whether THIS concrete tool call may run now.
            return _core.PolicyDecision(
                "confirm",
                "Cloud tool output/action requires a fresh confirmation",
            )

        if step.risk in {
            _core.RiskClass.WRITE,
            _core.RiskClass.DESTRUCTIVE,
            _core.RiskClass.ADMIN,
        }:
            return _core.PolicyDecision(
                "confirm",
                f"{step.risk.value} requires a fresh confirmation",
            )
        return _core.PolicyDecision("execute", "Local read-only step allowed")


def install() -> None:
    """Install before any orchestrator instance is constructed.

    Kept as a tiny package-level hook so this safety correction can remain an
    isolated checkpoint without rewriting the large experimental core module.
    Agent3Orchestrator resolves PolicyEngine when __init__ runs, so replacing the
    module global here affects every normal import path and direct test instance.
    """

    _core.PolicyEngine = Agent3PolicyEngine
