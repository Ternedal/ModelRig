"""``video_generate``: text-to-video from inside the chat turn (#2419 follow-up, Anders 20/11).

Same seam as ``image_generate_tool`` and the same decisions: a read-class
ToolGate tool behind its own literal switch, asynchronous (the job is queued
and the app's bubble polls it), nothing leaves the rig, the prompt is never in
a log line or an event. The shared path (``_submit_media_job``) is the image
tool's; this module only states what differs for video:

- **Gate** ``KALIV_VIDEO_TOOL_ENABLED=1``; default profile ``KALIV_VIDEO_TOOL_PROFILE``.
- **Modality** ``video``, task **``text_to_video`` only.** The executor does not
  serve image-to-video yet (#2366: ``NOT_SERVED_TASKS``), so the tool does not
  offer it -- a job the executor would never pick up would only wait 24 h and
  expire. When i2v is served, this is the one place to add it (and the model
  learns about it through the description, not through guessing).
- **Switches below the tool:** the job API refuses a video profile unless
  ``KALIV_MEDIA_VIDEO=1`` (``video_not_enabled``); that answer is relayed as a
  text result like every other rig-side condition.
- **Extra argument** ``frames`` (the profile's own bounds decide; the executor's
  validator is applied at submit, as for size).
- **Honesty towards Anders' goal:** these are short clips (the profile's frame
  budget), not the 15-minute pieces the video chain is for (12/11). The tool is
  the chat entry point for the seam; the length is the pipeline's to grow.
"""
from __future__ import annotations

import dataclasses
import os
from typing import Callable, Mapping

from .image_generate_tool import (
    STATUS_URL_PREFIX,
    VIDEO_JOB_REFERENCE_SCHEMA,
    _submit_media_job,
)
from .tools import Tool, ToolDenied

TOOL_NAME = "video_generate"
VIDEO_TOOL_FLAG = "KALIV_VIDEO_TOOL_ENABLED"
VIDEO_TOOL_PROFILE_ENV = "KALIV_VIDEO_TOOL_PROFILE"
VIDEO_TASK = "text_to_video"

_ALLOWED_ARGS = frozenset({"prompt", "profile_id", "width", "height", "frames", "seed"})
_INT_ARGS = ("width", "height", "frames", "seed")
_MAX_PROMPT_CHARS = 4000

__all__ = ["TOOL_NAME", "VIDEO_GENERATE_CAPABILITY", "video_tool_enabled", "register_video_generate_tool",
           "system_rule_if_registered", "STATUS_URL_PREFIX"]


def video_tool_enabled() -> bool:
    """Exactly ``1`` opts in (``activation_readiness`` reads this literal)."""
    return os.getenv("KALIV_VIDEO_TOOL_ENABLED", "").strip() == "1"


VIDEO_GENERATE_CAPABILITY = Tool(
    name=TOOL_NAME,
    risk="read",
    idempotent=False,  # two runs are two renders
    schedulable=False,
    unschedulable_because=(
        "en video kl. 03:00 holder GPU'en i minutter og skriver et asset uden nogen til at "
        "se det; bed om det i samtalen i stedet"
    ),
    network="none",
    sensitivity="private",
    description=(
        "Generate one short video clip on the rig from a text prompt (text-to-video "
        "only; it cannot animate an existing picture yet) and show it in this "
        "conversation. Write the prompt in English, concrete, ONE main subject and one "
        "simple motion; no names, text or logos. Rendering takes minutes: tell the user "
        "the clip is on its way. Never claim it is finished."
    ),
    params={
        "type": "object",
        "properties": {
            "prompt": {"type": "string",
                       "description": "English, concrete, one subject, one motion; max 4000 chars"},
            "profile_id": {"type": "string",
                           "description": "optional: an enabled video profile; default is configured on the rig"},
            "width": {"type": "integer", "description": "optional, must be a size the profile allows"},
            "height": {"type": "integer", "description": "optional, must be a size the profile allows"},
            "frames": {"type": "integer", "description": "optional, within the profile's frame budget"},
            "seed": {"type": "integer", "description": "optional, for 'the same again but…'"},
        },
        "required": ["prompt"],
    },
)

SYSTEM_RULE = (
    "When the user asks for a video, a clip or an animation (Danish: 'video', 'klip', "
    "'lav en video af', 'animer'), call video_generate with an English, concrete prompt "
    "that has one subject and one motion; then tell the user the clip is on its way in "
    "this conversation and that it takes a few minutes. Never describe it as finished. "
    "It cannot animate an existing picture yet; say so if asked."
)


def _validate_args(args: object) -> dict:
    if not isinstance(args, dict):
        raise ToolDenied("video_generate: args skal være et objekt")
    unknown = set(args) - _ALLOWED_ARGS
    if unknown:
        raise ToolDenied("video_generate: ukendte argumenter afvises: " + ", ".join(sorted(unknown)))
    prompt = args.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ToolDenied("video_generate: prompt mangler")
    if len(prompt) > _MAX_PROMPT_CHARS:
        raise ToolDenied("video_generate: prompt er for lang")
    profile_id = args.get("profile_id")
    if profile_id is not None and (not isinstance(profile_id, str) or not profile_id.strip()):
        raise ToolDenied("video_generate: profile_id skal være en ikke-tom streng")
    clean: dict = {"prompt": prompt, "profile_id": profile_id.strip() if isinstance(profile_id, str) else None}
    for key in _INT_ARGS:
        value = args.get(key)
        if value is None:
            clean[key] = None
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            raise ToolDenied(f"video_generate: {key} skal være et heltal")
        clean[key] = value
    return clean


def _run_video_generate(args: dict, *, service_getter: Callable[[], object] | None = None,
                        env: Mapping[str, str] | None = None) -> str:
    """Queue one text-to-video job. Returns a job reference line followed by text for the model."""
    clean = _validate_args(args)
    return _submit_media_job(
        clean, service_getter=service_getter, env=env, modality="video", task=VIDEO_TASK,
        profile_env=VIDEO_TOOL_PROFILE_ENV, schema=VIDEO_JOB_REFERENCE_SCHEMA, kind="video",
        params_keys=_INT_ARGS,
        text=lambda job_id, profile_id: (
            f"Videojob {job_id} er sat i kø på riggen (profil {profile_id}). "
            "Klippet tager nogle minutter og vises i samtalen, når det er klar. Sig til brugeren, "
            "at det er på vej — påstå ikke, at det er færdigt, og gentag ikke prompten."
        ),
    )


def system_rule_if_registered() -> str | None:
    """The system-prompt line, only while the tool is live (follows REGISTRY, not the flag)."""
    from . import tools as _tools

    return SYSTEM_RULE if TOOL_NAME in _tools.REGISTRY else None


def register_video_generate_tool() -> bool:
    """Register the tool iff the gate is on. Idempotent; refuses to shadow another registration."""
    if not video_tool_enabled():
        return False
    from . import tools as _tools

    existing = _tools.REGISTRY.get(TOOL_NAME)
    if existing is not None:
        if getattr(existing, "run", None) is _run_video_generate:
            return True
        raise RuntimeError(f"{TOOL_NAME} is already registered by another component")
    _tools.REGISTRY[TOOL_NAME] = dataclasses.replace(VIDEO_GENERATE_CAPABILITY, run=_run_video_generate)
    return True
