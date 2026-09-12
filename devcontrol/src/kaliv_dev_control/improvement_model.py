"""One-shot model bridge for non-authorizing RSI improvement proposals.

The caller supplies the chat function.  DevControl therefore does not import a
product runtime, HTTP client or model provider, and importing this module has no
side effects.  The model gets exactly one generation attempt; recursive retries
belong to a later, separately governed slice.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Mapping

from .improvement_binding import proposal_from_model_json
from .improvement_proposal import (
    ImprovementProposal,
    ImprovementProposalError,
    render_improvement_prompt,
)

ChatFn = Callable[[list[dict[str, str]], str], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class ImprovementModelResult:
    model: str
    proposal: ImprovementProposal
    raw_response: str
    raw_response_sha256: str


async def generate_bound_improvement_proposal(
    brief: Mapping[str, Any],
    *,
    model: str,
    chat: ChatFn,
    max_response_chars: int = 64_000,
) -> ImprovementModelResult:
    """Ask one model once, then fail-closed bind its JSON to the exact brief."""

    if not isinstance(model, str) or not model or model.strip() != model:
        raise ImprovementProposalError("model must be a non-empty canonical string")
    if not callable(chat):
        raise ImprovementProposalError("chat must be callable")
    if isinstance(max_response_chars, bool) or not isinstance(max_response_chars, int):
        raise ImprovementProposalError("max_response_chars must be an integer")
    if not 1_024 <= max_response_chars <= 1_000_000:
        raise ImprovementProposalError("max_response_chars must be in 1024..1000000")

    prompt = render_improvement_prompt(brief)
    messages = [
        {
            "role": "system",
            "content": (
                "Du er et proposal-only udviklingsanalyseled. Returner kun det "
                "JSON-objekt brugeren kræver. Ingen markdown og ingen prosa."
            ),
        },
        {"role": "user", "content": prompt},
    ]
    raw = await chat(messages, model)
    if not isinstance(raw, str):
        raise ImprovementProposalError("model response must be text")
    if not raw or not raw.strip():
        raise ImprovementProposalError("model returned an empty proposal")
    if len(raw) > max_response_chars:
        raise ImprovementProposalError("model proposal exceeds response limit")

    proposal = proposal_from_model_json(raw, brief=brief)
    return ImprovementModelResult(
        model=model,
        proposal=proposal,
        raw_response=raw,
        raw_response_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )
