"""Consciousness Core runtime boundary.

C4 is deliberately dormant and route-less. Importing this package grants no
model, memory, tool, scheduler, body, voice, or persistence authority.
"""

from .contracts import CognitiveProfile, ThoughtProposal, ThoughtRequest
from .runtime import (
    CONSCIOUSNESS_CORE_FLAG,
    ConsciousnessCoreRuntime,
    compose_runtime,
    enabled,
)
from .thought_engine import (
    OllamaThoughtEngine,
    ThoughtEngine,
    ThoughtEngineContractError,
)

__all__ = [
    "CONSCIOUSNESS_CORE_FLAG",
    "CognitiveProfile",
    "ConsciousnessCoreRuntime",
    "OllamaThoughtEngine",
    "ThoughtEngine",
    "ThoughtEngineContractError",
    "ThoughtProposal",
    "ThoughtRequest",
    "compose_runtime",
    "enabled",
]
