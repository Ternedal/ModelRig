"""``image_generate``: text-to-image from inside the chat turn (#2419, slice A).

Anders, 17/11: image generation is something you *say* to Kaliv in the
conversation, not a separate "Medier" screen. The architecture already has the
right seam -- ToolGate (``tools.py``, "the REGISTRY IS CODE") is the one place
the model can *do* things, and ``/tools/chat/stream`` already carries phases to
the app. This tool reuses the whole 17/11 chain unchanged: ``MediaJobService``
(same validation, quotas, profile allow-list), the executor, the profiles, the
gallery. No new surface towards the phone beyond a bubble type.

**Decisions (Anders, 19/11 22:33 on #2275):**

1. ``risk="read"``, no confirmation card. The job writes a file on the media
   volume and uses the GPU, but has no external effect, is cancellable and
   quota-bound; a card per image would kill the conversation (and #662: a 60 s
   TTL against a planner with p95 38 s). It is *not* replayable, so
   ``idempotent=False`` is stated explicitly -- running it twice renders twice.
2. **Asynchronous.** The tool queues the job and returns at once; the first
   line of its result is a machine-readable job reference that
   ``main_impl`` lifts into the turn result as ``media_jobs`` so the app can
   draw a bubble that polls ``GET /api/v1/media/jobs/{id}``.
3. Built as a draft during the freeze; lands after the V1 tag.

**Gate.** ToolGate is a deny-list: a tool in REGISTRY is live the moment
``KALIV_TOOLS_ENABLED=1``. So this tool is registered only when
``KALIV_IMAGE_TOOL_ENABLED`` is exactly ``1`` -- the same pattern as
``web_research_mount.py``. With the gate off the model never sees it.

**Fail-closed, but the chat continues as text.** ``KALIV_MEDIA_JOBS_API`` off,
no usable media configuration, no enabled image profile, a profile the executor
would refuse: all of these are *results* ("not available: <code>"), never
exceptions, because an exception out of a tool ends the turn with an HTTP error
(``main_impl._tools_chat_turn``). Only a malformed argument set from the model
is a ``ToolDenied`` -- that is the model's error, as for ``web_research``.

**Never in a log line or an event:** the prompt. The result text repeats
neither the prompt nor the parameters.

**Owner.** ``media_job_api.OWNER`` ("installation"), the same constant as the
job and gallery routes, so the asset the bubble later fetches is the one
``owns_completed_asset`` serves. The tool never reads an owner from the model.
"""
from __future__ import annotations

import dataclasses
import json
import os
from typing import Callable, Mapping

from fastapi import HTTPException

from .tools import Tool, ToolDenied

TOOL_NAME = "image_generate"
IMAGE_TASK = "text_to_image"
IMAGE_TOOL_FLAG = "KALIV_IMAGE_TOOL_ENABLED"
IMAGE_TOOL_PROFILE_ENV = "KALIV_IMAGE_TOOL_PROFILE"
JOB_REFERENCE_SCHEMA = "kaliv-image-job-ref/v1"
VIDEO_JOB_REFERENCE_SCHEMA = "kaliv-video-job-ref/v1"
# schema -> kind. ``parse_job_reference`` accepts exactly these; the app's bubble
# reads ``kind`` to know whether to show a picture or a player.
JOB_REFERENCE_SCHEMAS = {JOB_REFERENCE_SCHEMA: "image", VIDEO_JOB_REFERENCE_SCHEMA: "video"}
STATUS_URL_PREFIX = "/api/v1/media/jobs/"

_ALLOWED_ARGS = frozenset({"prompt", "profile_id", "width", "height", "seed"})
_INT_ARGS = ("width", "height", "seed")
_MAX_PROMPT_CHARS = 4000

# Store error strings (image_job_store.ImageJobError) -> public codes. Mirrors
# media_job_api._ERRORS without importing a private name.
_STORE_ERRORS = {
    "image job queue full": "queue_full",
    "owner image job limit reached": "owner_limit",
}


def image_tool_enabled() -> bool:
    """Exactly ``1`` opts in; anything else is off (``activation_readiness`` reads this literal)."""
    return os.getenv("KALIV_IMAGE_TOOL_ENABLED", "").strip() == "1"


IMAGE_GENERATE_CAPABILITY = Tool(
    name=TOOL_NAME,
    risk="read",
    # A read with a side effect that is NOT replayable (F-717): two runs are two
    # renders. Said explicitly so recovery escalates rather than re-renders.
    idempotent=False,
    schedulable=False,
    unschedulable_because=(
        "et billede kl. 03:00 bruger GPU'en og skriver et asset uden nogen til at "
        "se det; bed om det i samtalen i stedet"
    ),
    # In-process: the job store is a local database, the executor is a separate
    # local process. Nothing leaves the rig (D4).
    network="none",
    sensitivity="private",  # the prompt is yours; the result points at your own gallery
    description=(
        "Generate one image on the rig from a text prompt and show it in this "
        "conversation. Write the prompt in English, concrete, with ONE main "
        "subject (put anything else 'in the background'); no names, text or "
        "logos. The image renders in the background: tell the user it is on its "
        "way. Never claim it is finished."
    ),
    params={
        "type": "object",
        "properties": {
            "prompt": {"type": "string",
                       "description": "English, concrete, one main subject; max 4000 chars"},
            "profile_id": {"type": "string",
                           "description": "optional: an enabled image profile; default is configured on the rig"},
            "width": {"type": "integer", "description": "optional, must be a size the profile allows"},
            "height": {"type": "integer", "description": "optional, must be a size the profile allows"},
            "seed": {"type": "integer", "description": "optional, for 'the same again but…'"},
        },
        "required": ["prompt"],
    },
)


# ---------------------------------------------------------------------------
# Service access
# ---------------------------------------------------------------------------
_production_service: list[Callable[[], object]] = []


def _production_service_getter() -> Callable[[], object] | None:
    """The configured MediaJobService getter, or None when the job API is switched off.

    Reuses ``media_job_api.cached_service`` so a work area fixed after the worker
    started is picked up on the next call, exactly as the routes do.
    """
    from .media_job_api import SWITCH_ENV, cached_service

    if os.getenv(SWITCH_ENV, "0").strip() != "1":
        return None
    if not _production_service:
        _production_service.append(cached_service())
    return _production_service[0]


def _unavailable(code: str, modality: str = "image") -> str:
    """The text result for a rig-side refusal; names what was asked for, so a
    refused clip is not relayed to the user as "billedgenerering"."""
    what = "Videogenerering" if modality == "video" else "Billedgenerering"
    return (f"{what} er ikke tilgængelig lige nu ({code}). "
            "Fortsæt samtalen som tekst og sig det til brugeren.")


# ---------------------------------------------------------------------------
# The tool
# ---------------------------------------------------------------------------
def _validate_args(args: object) -> dict:
    if not isinstance(args, dict):
        raise ToolDenied("image_generate: args skal være et objekt")
    unknown = set(args) - _ALLOWED_ARGS
    if unknown:
        raise ToolDenied("image_generate: ukendte argumenter afvises: " + ", ".join(sorted(unknown)))
    prompt = args.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ToolDenied("image_generate: prompt mangler")
    if len(prompt) > _MAX_PROMPT_CHARS:
        raise ToolDenied("image_generate: prompt er for lang")
    profile_id = args.get("profile_id")
    if profile_id is not None and (not isinstance(profile_id, str) or not profile_id.strip()):
        raise ToolDenied("image_generate: profile_id skal være en ikke-tom streng")
    clean: dict = {"prompt": prompt, "profile_id": profile_id.strip() if isinstance(profile_id, str) else None}
    for key in _INT_ARGS:
        value = args.get(key)
        if value is None:
            clean[key] = None
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            raise ToolDenied(f"image_generate: {key} skal være et heltal")
        clean[key] = value
    return clean


def _choose_profile(service, requested: str | None, env: Mapping[str, str], *,
                    modality: str = "image", profile_env: str = IMAGE_TOOL_PROFILE_ENV,
                    task: str | None = None) -> tuple[str | None, str | None]:
    """(profile_id, error_code). Explicit > configured default > the sole enabled profile of the modality.

    With ``task`` the choice is among the profiles that list it. That matters for
    video: a ComfyUI template renders exactly one task, so text-to-video and
    image-to-video are two profiles on the rig, and "the sole video profile" or
    one configured default cannot serve both. The configured default wins for the
    task it lists; for the other task the sole profile that lists it is used. An
    explicitly requested profile is never second-guessed here -- the job API
    answers ``task_not_served`` for it.
    """
    enabled = {pid: p for pid, p in service.profiles.items() if getattr(p, "modality", None) == modality}
    if requested is not None:
        return (requested, None) if requested in enabled else (None, "profile_not_enabled")
    serving = enabled if task is None else {pid: p for pid, p in enabled.items() if task in getattr(p, "tasks", ())}
    configured = env.get(profile_env, "").strip()
    if configured:
        if configured not in enabled:
            return None, "configured_profile_not_enabled"
        if configured in serving:
            return configured, None
    if len(serving) == 1:
        return next(iter(serving)), None
    if not enabled:
        return None, f"no_{modality}_profile"
    return None, ("task_not_served" if not serving else "profile_required")


def _submit_media_job(clean: dict, *, service_getter: Callable[[], object] | None, env: Mapping[str, str] | None,
                      modality: str, task: str | None, profile_env: str, schema: str, kind: str,
                      params_keys: tuple[str, ...], text: Callable[[str, str], str]) -> str:
    """The shared path for image_generate and video_generate: queue one job, answer as text.

    Every rig-side condition is a text result with a code; only the caller's
    argument validation raises. ``text(job_id, profile_id)`` is the sentence the
    model relays; the first line is the machine-readable job reference the app
    turns into a bubble.
    """
    from .image_job_store import ImageJobError
    from .media_job_api import OWNER, MediaJobsUnavailable, SubmitRequest

    env = os.environ if env is None else env
    getter = service_getter if service_getter is not None else _production_service_getter()
    if getter is None:
        return _unavailable("media_jobs_api_off", modality)
    try:
        service = getter()
    except MediaJobsUnavailable as exc:
        return _unavailable(str(exc) or "media_jobs_unavailable", modality)

    profile_id, code = _choose_profile(service, clean["profile_id"], env, modality=modality, profile_env=profile_env,
                                       task=task)
    if code is not None:
        return _unavailable(code, modality)

    try:
        body = SubmitRequest(profile_id=profile_id, prompt=clean["prompt"], task=task,
                             **{key: clean.get(key) for key in params_keys})
    except ValueError:
        return _unavailable("invalid_request", modality)
    try:
        profile, generation = service.request_for(body)
    except HTTPException as exc:
        return _unavailable(str(exc.detail), modality)

    params = {key: clean[key] for key in params_keys if clean.get(key) is not None}
    # The task follows the job. Without it the executor falls back to the profile's
    # alphabetically first task, and for a profile that also lists image_to_image that
    # is the wrong one: the job would fail with "input_asset_id required for this task".
    params["task"] = generation.task
    try:
        created = service.store.submit(OWNER, clean["prompt"], profile_id=profile.profile_id, params=params)
    except ImageJobError as exc:
        return _unavailable(_STORE_ERRORS.get(str(exc), "invalid_request"), modality)
    except Exception:  # a store that cannot be reached: a code, never a path
        return _unavailable("media_jobs_store_unavailable", modality)

    job_id = created["job_id"]
    reference = {
        "schema": schema,
        "kind": kind,
        "job_id": job_id,
        "state": created.get("state", "queued"),
        "profile_id": profile.profile_id,
        "status_url": STATUS_URL_PREFIX + job_id,
    }
    return json.dumps(reference, ensure_ascii=False, sort_keys=True) + "\n" + text(job_id, profile.profile_id)


def _run_image_generate(args: dict, *, service_getter: Callable[[], object] | None = None,
                        env: Mapping[str, str] | None = None) -> str:
    """Queue one image job. Returns a job reference line followed by text for the model."""
    clean = _validate_args(args)
    return _submit_media_job(
        clean, service_getter=service_getter, env=env, modality="image", task=IMAGE_TASK,
        profile_env=IMAGE_TOOL_PROFILE_ENV, schema=JOB_REFERENCE_SCHEMA, kind="image",
        params_keys=_INT_ARGS,
        text=lambda job_id, profile_id: (
            f"Billedjob {job_id} er sat i kø på riggen (profil {profile_id}). "
            "Billedet vises i samtalen, når det er klar. Sig til brugeren, at det er på vej — "
            "påstå ikke, at det er færdigt, og gentag ikke prompten."
        ),
    )


def parse_job_reference(result: str) -> dict | None:
    """The job reference on the first line of a successful result, or None.

    ``main_impl`` calls this with the gate's result (``wrap_as_data`` envelope
    included) to lift the reference into the turn result as ``media_jobs``. Anything that
    is not exactly the schema above is None: an "unavailable" text, a parse
    error, a different schema.
    """
    if not isinstance(result, str) or not result:
        return None
    # The gate hands the result on inside the ``wrap_as_data`` envelope; the
    # reference is then the second line. Either form is accepted, nothing deeper.
    lines = result.split("\n", 2)
    first = ""
    for candidate in lines[:2]:
        if candidate.strip().startswith("{"):
            first = candidate.strip()
            break
    if not first:
        return None
    try:
        data = json.loads(first)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("schema") not in JOB_REFERENCE_SCHEMAS:
        return None
    job_id = data.get("job_id")
    if not isinstance(job_id, str) or len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
        return None
    if data.get("status_url") != STATUS_URL_PREFIX + job_id:
        return None
    kind = data.get("kind") or JOB_REFERENCE_SCHEMAS[data["schema"]]
    return {"job_id": job_id, "kind": kind, "state": data.get("state"), "profile_id": data.get("profile_id"),
            "status_url": data["status_url"]}


SYSTEM_RULE = (
    "When the user asks for a picture, an image or a drawing (Danish: 'billede', "
    "'tegn', 'lav et billede af'), call image_generate with an English, concrete "
    "prompt that has one main subject; then tell the user the image is on its way "
    "in this conversation. Never describe the image as finished."
)


def system_rule_if_registered() -> str | None:
    """The one-line nudge for the turn's system prompt, only while the tool is live.

    Sent unconditionally it would teach the model to call a tool that is not
    there (-> unknown tool, the turn ends with a 404). So the rule follows the
    REGISTRY, not the flag: registered = the model is told, absent = silence.
    """
    from . import tools as _tools

    return SYSTEM_RULE if TOOL_NAME in _tools.REGISTRY else None


def register_image_generate_tool() -> bool:
    """Register the tool iff the gate is on. Idempotent; refuses to shadow another registration."""
    if not image_tool_enabled():
        return False
    from . import tools as _tools

    existing = _tools.REGISTRY.get(TOOL_NAME)
    if existing is not None:
        if getattr(existing, "run", None) is _run_image_generate:
            return True
        raise RuntimeError(f"{TOOL_NAME} is already registered by another component")
    _tools.REGISTRY[TOOL_NAME] = dataclasses.replace(IMAGE_GENERATE_CAPABILITY, run=_run_image_generate)
    return True
