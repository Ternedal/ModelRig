"""Runtime binding for the Person Profile registry (#752).

ModelRig owns persona execution. When a person is selected and has an
active Person Revision, that revision's personality -- system
instructions, default language, style notes -- is what the model speaks
with, and it takes precedence over whatever persona text a client sends.
When no person is selected, nothing changes: the client's system prompt
is used exactly as before.

The three bindings (body, voice, personality) come from the same approved
revision by construction; this module only reads the personality, and it
reads it through active_bindings(), never from a component list directly.
"""

from __future__ import annotations

import os
from typing import Any

from .person_api import registry_path
from .person_registry import PersonRegistry

_cache: dict[str, Any] = {"path": None, "mtime": None, "registry": None}


def _registry() -> PersonRegistry | None:
    path = registry_path()
    if not os.path.exists(path):
        _cache.update(path=None, mtime=None, registry=None)
        return None
    mtime = os.path.getmtime(path)
    if _cache["registry"] is None or _cache["path"] != path or _cache["mtime"] != mtime:
        _cache.update(path=path, mtime=mtime, registry=PersonRegistry(path))
    return _cache["registry"]


def compose_personality_prompt(personality: dict[str, Any]) -> str:
    """One system prompt from a personality revision. Instructions first,
    then the default language as an explicit instruction, then style."""
    parts = [str(personality.get("system_instructions", "")).strip()]
    language = str(personality.get("default_language", "")).strip()
    if language:
        parts.append(f"Svar som udgangspunkt på {language}, medmindre brugeren beder om andet.")
    style = str(personality.get("style_notes", "")).strip()
    if style:
        parts.append("Stil: " + style)
    return "\n\n".join(p for p in parts if p)


def active_person() -> dict[str, Any] | None:
    """Selected person's resolved bindings, or None when no person is
    selected or the selected one has no active revision."""
    try:
        registry = _registry()
        if registry is None:
            return None
        return registry.active_bindings()
    except Exception:
        # A corrupt or unreadable store must never take the chat down; it
        # just does not bind a persona this turn. Loading is inside the try
        # on purpose -- a bad JSON file fails at construction, not at read.
        _cache.update(path=None, mtime=None, registry=None)
        return None


def resolve_system_prompt(client_system: str | None) -> tuple[str | None, dict[str, Any] | None]:
    """(system prompt to use, person descriptor or None).

    Registry wins when it has an active person; otherwise the client's own
    prompt, unchanged. The descriptor lets the turn report which person
    answered, so a client can show it and an operator can trust it.
    """
    bindings = active_person()
    if bindings is None:
        return (client_system or None), None
    prompt = compose_personality_prompt(bindings["personality"])
    descriptor = {
        "person_id": bindings["person_id"],
        "display_name": bindings["display_name"],
        "person_revision": bindings["person_revision"],
        "personality_revision": bindings["personality"]["id"],
    }
    return (prompt or (client_system or None)), descriptor


UNBOUND_SOURCES = {"", "unbound", "none", "-"}


def active_voice_source() -> str | None:
    """The selected person's voice source id (a VoiceRig voice id), or None
    when no person is active or the voice candidate is still unbound. Read
    through active_bindings() like the personality, so the voice can only
    ever be the one the active Person Revision names."""
    bindings = active_person()
    if bindings is None:
        return None
    source = str(bindings["voice"].get("source_id", "")).strip()
    return None if source.lower() in UNBOUND_SOURCES else source
