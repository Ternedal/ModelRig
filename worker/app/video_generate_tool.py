"""``video_generate``: text-to-video from inside the chat turn (#2419 follow-up, Anders 20/11).

Same seam as ``image_generate_tool`` and the same decisions: a read-class
ToolGate tool behind its own literal switch, asynchronous (the job is queued
and the app's bubble polls it), nothing leaves the rig, the prompt is never in
a log line or an event. The shared path (``_submit_media_job``) is the image
tool's; this module only states what differs for video:

- **Gate** ``KALIV_VIDEO_TOOL_ENABLED=1``; default profile ``KALIV_VIDEO_TOOL_PROFILE``.
- **Modality** ``video``; task ``text_to_video``, or ``image_to_video`` when the
  model names ``source_image_job_id`` -- the word ``latest`` (the newest finished
  picture; what a later turn uses, since the model no longer sees the id then)
  or the job id image_generate returned in this same turn. The tool resolves it
  to the completed asset *of this owner* through the store;
  anything else (unknown job, not finished, not ours, not an image) is a text
  result. The executor's owner-gated reader checks ownership again at claim.
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

import contextvars
import dataclasses
import os
import re
from typing import Callable, Mapping

from .image_generate_tool import (
    ArgMistake,
    _arg_name,
    int_arg,
    STATUS_URL_PREFIX,
    VIDEO_JOB_REFERENCE_SCHEMA,
    _submit_media_job,
)
from .tools import Tool, ToolDenied

TOOL_NAME = "video_generate"
VIDEO_TOOL_FLAG = "KALIV_VIDEO_TOOL_ENABLED"
VIDEO_TOOL_PROFILE_ENV = "KALIV_VIDEO_TOOL_PROFILE"
VIDEO_TASK = "text_to_video"

_ALLOWED_ARGS = frozenset({"prompt", "profile_id", "width", "height", "frames", "seed", "source_image_job_id"})
I2V_TASK = "image_to_video"
LATEST_SOURCE = "latest"

# The image jobs shown in the conversation this turn belongs to, oldest first, as the client
# sent them (``conversation_image_jobs`` on the turn) -- or None when the client sent none.
# "latest" means the newest picture OF THIS CONVERSATION when the client says which those are;
# only without it does the tool fall back to the owner's newest picture anywhere, which can be
# another conversation's (review 6004386187). Set by the turn, read by the tool on its worker
# thread (``asyncio.to_thread`` carries the context).
CONVERSATION_IMAGE_JOBS: contextvars.ContextVar[tuple[str, ...] | None] = contextvars.ContextVar(
    "kaliv_conversation_image_jobs", default=None)
MAX_CONVERSATION_IMAGE_JOBS = 32
_JOB_ID_RE = re.compile(r"[0-9a-f]{32}")


def conversation_image_jobs(raw: object) -> tuple[str, ...] | None:
    """What a client sent as ``conversation_image_jobs``, made safe: well-formed job ids only,
    in order, without repeats, the newest ``MAX_CONVERSATION_IMAGE_JOBS``. ``None`` (the field
    was not sent: an older client) stays None; a list with nothing usable is an empty tuple --
    "this conversation has no pictures" -- which is an answer, not the absence of one.
    Ownership is not decided here: every id is looked up for OWNER when it is used.
    """
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)):
        return ()
    seen: dict[str, None] = {}
    for item in raw[-4 * MAX_CONVERSATION_IMAGE_JOBS:]:
        if isinstance(item, str) and _JOB_ID_RE.fullmatch(item):
            seen.pop(item, None)  # a repeat counts at its latest position
            seen[item] = None
    return tuple(seen)[-MAX_CONVERSATION_IMAGE_JOBS:]
UNREADABLE_SOURCE = "\x00unreadable"  # never a value a model can send: JSON strings reach us decoded, ids are hex


def _unreadable_source() -> str:
    return ("Videogenerering blev ikke startet (source_not_understood): source_image_job_id skal være "
            "ordet latest eller det 32-tegns job-id, image_generate gav. Kald værktøjet igen med "
            "source_image_job_id='latest' for det seneste færdige billede, eller sig det til brugeren.")
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
        "Generate one short video clip on the rig and show it in this conversation: "
        "from a text prompt, or -- when the user wants a picture from this conversation "
        "animated -- from that picture by passing source_image_job_id: the word latest for "
        "the newest picture of this conversation, or the id image_generate returned. The picture "
        "must be finished first; if it is still rendering the tool says so. Write the prompt in English, concrete, ONE main "
        "subject and one simple motion; no names, text or logos. Rendering takes minutes: "
        "tell the user the clip is on its way. Never claim it is finished."
    ),
    params={
        "type": "object",
        "properties": {
            "prompt": {"type": "string",
                       "description": "English, concrete, one subject, one motion; max 4000 chars"},
            "profile_id": {"type": "string",
                           "description": "leave out: the rig has a default. Only when the user names a video "
                                          "profile; never a person, persona or revision id"},
            "width": {"type": "integer", "description": "leave out unless the user asks for a size; the rig's default always works"},
            "height": {"type": "integer", "description": "leave out unless the user asks for a size; the rig's default always works"},
            "frames": {"type": "integer", "description": "leave out unless the user asks for a length; within the profile's frame budget"},
            "seed": {"type": "integer", "description": "optional, for 'the same again but…'"},
            "source_image_job_id": {"type": "string",
                                    "description": "optional: animate a finished picture -- 'latest' for the newest one of this conversation, or the 32-hex id from image_generate"},
        },
        "required": ["prompt"],
    },
)

SYSTEM_RULE = (
    "When the user asks for a video, a clip or an animation (Danish: 'video', 'klip', "
    "'lav en video af', 'animer'), call video_generate with an English, concrete prompt "
    "that has one subject and one motion; then tell the user the clip is on its way in "
    "this conversation and that it takes a few minutes. Never describe it as finished. "
    "To animate a picture made earlier ('lav en video af det billede'), pass "
    "source_image_job_id='latest'; describe only the motion in the prompt. If the tool "
    "answers that there is no finished picture, or that the picture is not finished yet, "
    "say so instead of inventing one."
)


def _validate_args(args: object) -> dict:
    if not isinstance(args, dict):
        raise ToolDenied("video_generate: args skal være et objekt")
    unknown = set(args) - _ALLOWED_ARGS
    if unknown:
        raise ArgMistake("ukendte argumenter: " + ", ".join(sorted(_arg_name(k) for k in unknown)))
    prompt = args.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ArgMistake("prompt mangler")
    if len(prompt) > _MAX_PROMPT_CHARS:
        raise ArgMistake("prompt er for lang")
    profile_id = args.get("profile_id")
    if profile_id is not None and not isinstance(profile_id, str):
        raise ArgMistake("profile_id skal være en streng")
    # An empty string is how a model leaves an optional argument out; it means "the rig's default",
    # not a refusal that ends the turn.
    clean: dict = {"prompt": prompt, "profile_id": (profile_id.strip() or None) if isinstance(profile_id, str) else None}
    source = args.get("source_image_job_id")
    if source is not None:
        if not isinstance(source, str):
            raise ArgMistake("source_image_job_id skal være et job-id eller ordet latest")
        if source.strip().lower() == LATEST_SOURCE:
            source = LATEST_SOURCE
        elif len(source) != 32 or any(c not in "0123456789abcdef" for c in source):
            # Not ToolDenied: that ends the whole turn with an HTTP error, and a small model
            # writing "det billede" or an id it made up is the likeliest mistake here. It gets
            # a text result it can act on (call again with "latest") or relay.
            source = UNREADABLE_SOURCE
    clean["source_image_job_id"] = source
    for key in _INT_ARGS:
        clean[key] = int_arg(key, args.get(key))
    return clean


def _run_video_generate(args: dict, *, service_getter: Callable[[], object] | None = None,
                        env: Mapping[str, str] | None = None) -> str:
    """Queue one text-to-video job. Returns a job reference line followed by text for the model."""
    from .image_generate_tool import _arg_mistake
    try:
        clean = _validate_args(args)
    except ArgMistake as mistake:
        return _arg_mistake(TOOL_NAME, "video", mistake)
    task = VIDEO_TASK
    params_keys: tuple[str, ...] = _INT_ARGS
    if clean["source_image_job_id"] == UNREADABLE_SOURCE:
        return _unreadable_source()
    if clean["source_image_job_id"] is not None:
        asset_id, refusal = _resolve_source(clean["source_image_job_id"], service_getter)
        if refusal is not None:
            return refusal  # an "unavailable" text with its code
        clean["input_asset_id"] = asset_id
        task = I2V_TASK
        params_keys = _INT_ARGS + ("input_asset_id",)
    return _submit_media_job(
        clean, service_getter=service_getter, env=env, modality="video", task=task,
        profile_env=VIDEO_TOOL_PROFILE_ENV, schema=VIDEO_JOB_REFERENCE_SCHEMA, kind="video",
        params_keys=params_keys,
        text=lambda job_id, profile_id: (
            f"Videojobbet er sat i kø på riggen (profil {profile_id}). "
            "Klippet tager nogle minutter og vises i samtalen, når det er klar. Sig til brugeren, "
            "at det er på vej — påstå ikke, at det er færdigt, gentag ikke prompten, og nævn ikke job-id'et."
        ),
    )


_SOURCE_TEXT = {
    "no_source_image": "der er ikke noget færdigt billede at lave video af. Sig det til brugeren i stedet for at finde på et",
    "source_job_not_completed": "billedet er ikke færdigt endnu. Sig til brugeren, at de kan bede om videoen, når billedet er der",
    "source_job_not_found": "det job-id findes ikke. Kald værktøjet igen med source_image_job_id='latest', eller sig det til brugeren",
}


def _source_refusal(code: str) -> str:
    """A source the clip cannot be made from, as text the model can act on. Codes without a
    sentence of their own keep the plain refusal."""
    from .image_generate_tool import _unavailable
    if code in _SOURCE_TEXT:
        return f"Videogenerering blev ikke startet ({code}): {_SOURCE_TEXT[code]}."
    return _unavailable(code, "video")


def _newest_picture(service, image_profiles: list[str]) -> tuple[dict | None, str | None]:
    """The job ``latest`` names, or a refusal code. Never an older picture in place of the newest.

    With the conversation's pictures known (the client sent them): the newest of THOSE that
    exists for this owner and is, or is becoming, a picture. Without: the owner's newest such
    job anywhere. In both, a newest picture that is still rendering is ``source_job_not_completed``
    -- the user most likely means that one, and animating the one before it would be a
    different picture than they asked about.
    """
    from .image_job_store import ACTIVE_STATES
    from .media_job_api import OWNER

    shown = CONVERSATION_IMAGE_JOBS.get()
    if shown is None:
        job = service.store.newest_picture_for(OWNER, image_profiles)
    else:
        job = None
        for job_id in reversed(shown):
            candidate = service.store.get(job_id, OWNER)
            # Not ours, gone, another modality, or it never became a picture: not what "that
            # picture" can mean. Look further back in the same conversation.
            if (candidate is None or candidate.get("profile_id") not in image_profiles
                    or candidate.get("state") not in ("completed", *ACTIVE_STATES)):
                continue
            job = candidate
            break
    if job is None:
        return None, "no_source_image"
    if job.get("state") != "completed":
        return None, "source_job_not_completed"
    return job, None


def _resolve_source(job_id: str, service_getter: Callable[[], object] | None) -> tuple[str | None, str | None]:
    """``(asset_id, None)`` for a completed image job of this owner, else ``(None, refusal-text)``.

    Looked up through the same store the job will be queued in, for OWNER only:
    the model names a job id or the word ``latest``, never an asset or an owner.
    ``latest`` is the newest picture of this conversation when the client says which
    pictures those are, else the owner's newest anywhere (``_newest_picture``) -- the
    way "make a video of that picture" works in a later turn, where the model no
    longer sees the id ``image_generate`` returned (tool results are not part of
    the history the clients send). Not found / not ours / not finished / not an
    image -> a code the model relays; the executor's reader re-checks ownership at
    claim time regardless.
    """
    from .image_generate_tool import _production_service_getter, _unavailable
    from .media_job_api import OWNER, MediaJobsUnavailable

    getter = service_getter if service_getter is not None else _production_service_getter()
    if getter is None:
        return None, _unavailable("media_jobs_api_off", "video")
    try:
        service = getter()
    except MediaJobsUnavailable as exc:
        return None, _unavailable(str(exc) or "media_jobs_unavailable", "video")
    try:
        if job_id == LATEST_SOURCE:
            image_profiles = [pid for pid, p in service.profiles.items() if getattr(p, "modality", None) == "image"]
            job, code = _newest_picture(service, image_profiles)
            if code is not None:
                return None, _source_refusal(code)
        else:
            job = service.store.get(job_id, OWNER)
    except Exception:  # noqa: BLE001 -- a store that cannot be reached: a code, never a path
        return None, _unavailable("media_jobs_store_unavailable", "video")
    if job is None:
        return None, _source_refusal("source_job_not_found")
    if job.get("state") != "completed" or not job.get("asset_id"):
        return None, _source_refusal("source_job_not_completed")
    source_profile = service.profiles.get(job.get("profile_id"))
    if source_profile is None:
        return None, _unavailable("source_profile_not_enabled", "video")
    if getattr(source_profile, "modality", None) != "image":
        return None, _unavailable("source_not_an_image", "video")
    if not service.store.owns_completed_asset(OWNER, job["asset_id"]):
        return None, _unavailable("source_not_found", "video")
    return job["asset_id"], None


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
