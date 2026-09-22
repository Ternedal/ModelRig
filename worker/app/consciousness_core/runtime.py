"""Dormant C4 runtime composition for Consciousness Core.

No route imports this module. The factory returns None unless the exact opt-in
value KALIV_CONSCIOUSNESS_CORE_ENABLED=1 is present. Even when enabled, the
runtime can only validate a ThoughtRequest, invoke an injected ThoughtEngine,
and validate/return a ThoughtProposal.
"""
from __future__ import annotations

import os
from typing import Any, Mapping

from pydantic import ValidationError

from .contracts import CognitiveProfile, ThoughtProposal, ThoughtRequest
from .thought_engine import (
    ChatFn,
    OllamaThoughtEngine,
    ThoughtEngine,
    ThoughtEngineContractError,
)

CONSCIOUSNESS_CORE_FLAG = "KALIV_CONSCIOUSNESS_CORE_ENABLED"


def enabled(env: Mapping[str, str] | None = None) -> bool:
    """Fail closed: only the exact string '1' opts C4 in."""
    if env is None:
        return os.getenv("KALIV_CONSCIOUSNESS_CORE_ENABLED", "0") == "1"
    return env.get("KALIV_CONSCIOUSNESS_CORE_ENABLED", "0") == "1"


class ConsciousnessCoreRuntime:
    """One bounded thought-turn adapter with zero execution/persistence authority."""

    def __init__(self, engine: ThoughtEngine) -> None:
        self._engine = engine

    async def think(
        self,
        request: ThoughtRequest | Mapping[str, Any],
        cognitive_profile: CognitiveProfile | Mapping[str, Any],
        *,
        context: Mapping[str, Any] | None = None,
    ) -> ThoughtProposal:
        try:
            req = (
                request
                if isinstance(request, ThoughtRequest)
                else ThoughtRequest.model_validate(request)
            )
            profile = (
                cognitive_profile
                if isinstance(cognitive_profile, CognitiveProfile)
                else CognitiveProfile.model_validate(cognitive_profile)
            )
        except ValidationError as exc:
            raise ThoughtEngineContractError(
                "invalid Consciousness Core thought input"
            ) from exc

        if context is None:
            proposal_raw = await self._engine.think(req, profile)
        else:
            if not isinstance(context, Mapping):
                raise ThoughtEngineContractError("thought context must be a mapping")
            proposal_raw = await self._engine.think(req, profile, context=context)
        try:
            proposal = (
                proposal_raw
                if isinstance(proposal_raw, ThoughtProposal)
                else ThoughtProposal.model_validate(proposal_raw)
            )
        except ValidationError as exc:
            raise ThoughtEngineContractError(
                "ThoughtEngine proposal failed strict validation"
            ) from exc

        if proposal.request_id != req.request_id:
            raise ThoughtEngineContractError(
                "ThoughtEngine proposal is bound to the wrong request"
            )
        return proposal


def compose_runtime(
    *,
    env: Mapping[str, str] | None = None,
    chat_fn: ChatFn | None = None,
) -> ConsciousnessCoreRuntime | None:
    """Compose C4 only after exact opt-in; flag-off performs no provider import/call."""
    if not enabled(env):
        return None

    if chat_fn is None:
        # Lazy import is part of the dormant boundary. With the flag off even the
        # provider module is not resolved by this factory.
        from .. import ollama_client

        chat_fn = ollama_client.chat

    return ConsciousnessCoreRuntime(OllamaThoughtEngine(chat_fn))
