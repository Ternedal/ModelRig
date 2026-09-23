"""Replaceable external ThoughtEngine adapters for Consciousness Core C4."""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Mapping, Protocol

from pydantic import ValidationError

from .contracts import CognitiveProfile, ThoughtProposal, ThoughtRequest


ChatFn = Callable[[list[dict[str, str]], str | None], Awaitable[str]]


class ThoughtEngineContractError(RuntimeError):
    """Untrusted engine output did not satisfy the C0-C3 proposal contract."""


class ThoughtEngine(Protocol):
    async def think(
        self,
        request: ThoughtRequest,
        cognitive_profile: CognitiveProfile,
    ) -> ThoughtProposal | Mapping[str, Any]: ...


class _DuplicateJsonKeyError(ValueError):
    pass


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError("duplicate JSON key in ThoughtEngine output")
        result[key] = value
    return result


def _strict_json_object(raw: str) -> dict[str, Any]:
    value = raw.strip()
    if not value or value.startswith("```"):
        raise ThoughtEngineContractError("ThoughtEngine must return one raw JSON object")
    try:
        payload = json.loads(value, object_pairs_hook=_reject_duplicate_json_keys)
    except (json.JSONDecodeError, _DuplicateJsonKeyError, TypeError) as exc:
        raise ThoughtEngineContractError(
            "ThoughtEngine did not return valid unambiguous JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise ThoughtEngineContractError("ThoughtEngine output must be one JSON object")
    return payload


class OllamaThoughtEngine:
    """One external model call that can only propose cognition.

    The adapter has no tool registry, Memory 4 writer, Agent 3 executor,
    scheduler, Person/Profile mutation, BodyRig mutation, or persistence handle.
    """

    def __init__(self, chat_fn: ChatFn) -> None:
        self._chat_fn = chat_fn

    async def think(
        self,
        request: ThoughtRequest,
        cognitive_profile: CognitiveProfile,
    ) -> ThoughtProposal:
        system = (
            "You are an external replaceable ThoughtEngine used by Kaliv Consciousness Core. "
            "You are NOT the identity, memory authority, action executor, scheduler, body, or voice. "
            "Return exactly one raw JSON object and no markdown. "
            "The object MUST match kaliv-consciousness-core/thought-proposal/v1. "
            "actions and state_mutations MUST be empty arrays. "
            "authority.identity, authority.persistent_state, authority.durable_memory, "
            "and authority.action MUST all be false. "
            "candidate_intentions are proposals only; required_authority names the external "
            "authority that would be needed later. Do not claim execution occurred."
        )
        payload = {
            "thought_request": request.model_dump(mode="json"),
            "cognitive_profile": cognitive_profile.model_dump(mode="json"),
        }
        raw = await self._chat_fn(
            [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
                },
            ],
            cognitive_profile.model,
        )
        parsed = _strict_json_object(raw)
        try:
            proposal = ThoughtProposal.model_validate(parsed)
        except ValidationError as exc:
            raise ThoughtEngineContractError(
                "ThoughtEngine proposal failed strict validation"
            ) from exc
        if proposal.request_id != request.request_id:
            raise ThoughtEngineContractError(
                "ThoughtEngine proposal is bound to the wrong request"
            )
        return proposal
