"""Opt-in generation profiles for Ollama; no V1 runtime wiring.

A caller must explicitly select a profile; this module never infers intent from
user text, changes global Ollama configuration, or truncates completed answers.
Tool use and safety-sensitive routes should retain their existing settings until
separately evaluated.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ResponseMode(str, Enum):
    VOICE_BRIEF = "voice_brief"
    CHAT_BRIEF = "chat_brief"
    DETAILED = "detailed"
    REASONING = "reasoning"


@dataclass(frozen=True)
class GenerationProfile:
    think: bool
    num_predict: int
    system_guidance: str

    def options(self) -> dict[str, int]:
        return {"num_predict": self.num_predict}


PROFILES: dict[ResponseMode, GenerationProfile] = {
    ResponseMode.VOICE_BRIEF: GenerationProfile(
        think=False,
        num_predict=128,
        system_guidance="Svar naturligt på dansk, helst i højst to korte sætninger. "
                        "Vær præcis; hvis emnet kræver mere forklaring, så spørg om uddybning.",
    ),
    ResponseMode.CHAT_BRIEF: GenerationProfile(
        think=False,
        num_predict=256,
        system_guidance="Svar klart på dansk. Vær kortfattet, men udelad ikke nødvendige oplysninger.",
    ),
    ResponseMode.DETAILED: GenerationProfile(
        think=False,
        num_predict=1024,
        system_guidance="Svar på dansk med den nødvendige faglige dybde.",
    ),
    ResponseMode.REASONING: GenerationProfile(
        think=True,
        num_predict=2048,
        system_guidance="Svar på dansk. Prioritér korrekthed og færdig besvarelse.",
    ),
}


def resolve_profile(mode: ResponseMode | str) -> GenerationProfile:
    """Explicit selection only; reject unknown modes rather than guessing."""
    return PROFILES[ResponseMode(mode)]


def apply_profile(
    payload: dict[str, Any], mode: ResponseMode | str
) -> dict[str, Any]:
    """Return a new Ollama request; never mutate caller-owned nested mappings.

    Guidance is appended to an existing system instruction, not substituted.
    If the caller supplies a hard ceiling lower than the profile ceiling, keep
    that ceiling. All other options and explicit stream value are preserved.
    """
    profile = resolve_profile(mode)
    result = dict(payload)
    raw_options = payload.get("options")
    if raw_options is not None and not isinstance(raw_options, dict):
        raise TypeError("options must be an object")
    options = dict(raw_options or {})
    existing = options.get("num_predict")
    if isinstance(existing, int) and not isinstance(existing, bool) and existing > 0:
        options["num_predict"] = min(existing, profile.num_predict)
    elif existing is None:
        options["num_predict"] = profile.num_predict
    else:
        raise ValueError("num_predict must be a positive integer")
    result["options"] = options
    result["think"] = profile.think
    existing_system = payload.get("system")
    if existing_system is not None and not isinstance(existing_system, str):
        raise TypeError("system must be a string")
    result["system"] = (
        (existing_system.rstrip() + "\n\n") if existing_system else ""
    ) + profile.system_guidance
    return result
