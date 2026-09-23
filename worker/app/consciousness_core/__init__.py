"""Consciousness Core runtime boundary.

C4 is deliberately dormant and route-less. Importing this package grants no
model, memory, tool, scheduler, body, voice, or persistence authority.
"""

from .contracts import CognitiveProfile, ThoughtProposal, ThoughtRequest
from .embodiment import (
    EmbodimentContractError,
    EmbodimentObservation,
    EmbodimentState,
    InferredEmbodimentState,
    MockEmbodimentObserver,
    PerformedBodyStateRef,
    SemanticBodyIntent,
    infer_embodiment_state,
    normalize_embodiment_state,
)
from .experience import (
    ExperienceCandidate,
    ExperienceMemoryError,
    Memory4ExperienceBridge,
    MemoryContextSnapshot,
    MemoryDurableReceiptRef,
    MemoryHandoffDecision,
    plan_memory_handoff,
)
from .personality import (
    IdentityTrait,
    PersonalityEvidence,
    PersonalityIdentitySnapshot,
    PersonalityModel,
    PersonalityResolverError,
    PersonalityState,
    PersonalityStateTrait,
    ResolvedTrait,
    TransientTraitModifier,
    resolve_personality_model,
    resolve_personality_state,
)
from .metacognition import (
    MetacognitionContractError,
    MetacognitiveState,
    OutcomeObservation,
    PredictionRecord,
    PredictionResolution,
    apply_resolution,
    initial_metacognitive_state,
    prediction_from_proposal,
    resolve_prediction,
)
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
    "EmbodimentContractError",
    "EmbodimentObservation",
    "EmbodimentState",
    "ExperienceCandidate",
    "InferredEmbodimentState",
    "MockEmbodimentObserver",
    "PerformedBodyStateRef",
    "SemanticBodyIntent",
    "ExperienceMemoryError",
    "IdentityTrait",
    "Memory4ExperienceBridge",
    "MemoryContextSnapshot",
    "MemoryDurableReceiptRef",
    "MemoryHandoffDecision",
    "MetacognitionContractError",
    "PersonalityEvidence",
    "PersonalityIdentitySnapshot",
    "PersonalityModel",
    "PersonalityResolverError",
    "PersonalityState",
    "PersonalityStateTrait",
    "ResolvedTrait",
    "TransientTraitModifier",
    "MetacognitiveState",
    "OutcomeObservation",
    "PredictionRecord",
    "PredictionResolution",
    "ConsciousnessCoreRuntime",
    "OllamaThoughtEngine",
    "ThoughtEngine",
    "ThoughtEngineContractError",
    "ThoughtProposal",
    "ThoughtRequest",
    "compose_runtime",
    "apply_resolution",
    "enabled",
    "infer_embodiment_state",
    "initial_metacognitive_state",
    "normalize_embodiment_state",
    "plan_memory_handoff",
    "prediction_from_proposal",
    "resolve_personality_model",
    "resolve_personality_state",
    "resolve_prediction",
]
