from __future__ import annotations

import json

from .extraction import CompletedMemoryTurn, MemoryCandidate, MemoryCandidateExtractor


_SYSTEM_PROMPT = """You are a local memory-candidate extractor for Kaliv.
Return JSON only. Never return markdown or prose.

Schema:
{
  "schema": "kaliv-memory-candidates/v1",
  "candidates": [
    {
      "subject": "...",
      "predicate": "...",
      "value": "...",
      "kind": "fact|preference|project|relationship|routine|constraint|note",
      "sensitivity": "public|operational|private|secret",
      "source_type": "user_explicit|inferred|tool_observation|imported",
      "confidence": 0.0,
      "evidence": "..."
    }
  ]
}

Rules:
- Extract only information that is plausibly useful beyond this one turn.
- For source_type=user_explicit, value MUST be a verbatim contiguous substring of
  the user's text and evidence MUST be a verbatim user substring containing value.
- If you normalize, summarize, combine, guess or infer anything, use source_type=inferred.
- Never return source_ref, review_status, ids, supersedes ids, operations or write instructions.
- Do not turn assistant claims into user_explicit memory.
- Return at most 16 candidates. An empty candidates list is valid.
"""


def _turn_prompt(turn: CompletedMemoryTurn) -> str:
    # JSON encoding preserves the exact bounded strings while making user text
    # visually separate from the server-owned extraction instruction.
    return json.dumps(
        {
            "completed_turn": {
                "user": turn.user_text,
                "assistant": turn.assistant_text,
            }
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


async def extract_memory_candidates_local(
    turn: CompletedMemoryTurn,
    *,
    model: str | None = None,
) -> tuple[MemoryCandidate, ...]:
    """Extract Memory 4 candidates through the existing local Ollama client only.

    No base URL, API key or cloud-routing argument is exposed here. The neutral
    extractor validates and bounds the turn before this callback can reach the
    local model and validates the returned JSON again before exposing candidates.
    """
    from app import ollama_client

    async def _extract(bounded_turn: CompletedMemoryTurn) -> str:
        return await ollama_client.chat(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _turn_prompt(bounded_turn)},
            ],
            model=model,
        )

    return await MemoryCandidateExtractor(extract=_extract).extract(turn)
