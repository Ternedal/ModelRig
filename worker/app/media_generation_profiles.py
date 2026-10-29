"""Model profiles: which local generator models may run, with what limits.

ModelRig #2296 (6490650598): the generator layer is profile-driven, not
hard-coded to one model. A profile is data, validated fail-closed; it names a
backend, a pinned model revision, request limits and GPU requirements. Model
names in a profile are candidates, not claims of supported functionality.

Safe defaults:
- No profile ships with ModelRig. Profiles are JSON files in an operator
  directory, and nothing runs unless KALIV_MEDIA_PROFILES_ENABLED lists it.
- A profile that is not "rig-qualified" also needs
  KALIV_MEDIA_ALLOW_CANDIDATE_PROFILES=1.
- Unknown keys, backends, pipelines, tasks or MIME types are refused. There is
  no dynamic class loading beyond DIFFUSERS_PIPELINES.
- The model revision must be a pinned 40-hex commit. Loading is offline only.

Nothing here imports torch or diffusers.
"""
from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from .media_generation_contract import ARTIFACT_TYPES, TASKS, GenerationError, GenerationRequest

SCHEMA = "kaliv-media-profile/v1"
QUALIFICATIONS = ("candidate", "offline-tested", "rig-qualified")
BACKENDS = {"diffusers": "image", "comfyui": "video"}
DIFFUSERS_PIPELINES = frozenset({"QwenImagePipeline", "StableDiffusionXLPipeline", "FluxPipeline"})
MODALITY_TASKS = {
    "image": frozenset({"text_to_image", "image_to_image"}),
    "video": frozenset({"text_to_video", "image_to_video"}),
}
MODALITY_OUTPUTS = {"image": frozenset({"image/png"}), "video": frozenset({"video/mp4"})}
ENABLED_ENV = "KALIV_MEDIA_PROFILES_ENABLED"
ALLOW_CANDIDATES_ENV = "KALIV_MEDIA_ALLOW_CANDIDATE_PROFILES"
MAX_PROFILE_BYTES = 64 * 1024
MAX_PROFILES = 32

_PROFILE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,47}")
_REVISION = re.compile(r"[0-9a-f]{40}")
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")
_LICENSE = re.compile(r"[a-z0-9][a-z0-9.+-]{0,63}")
_DEVICE = re.compile(r"cuda:(?:[0-9]|1[0-5])")
_ASSET_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")

_TOP_KEYS = frozenset({
    "schema", "profile_id", "modality", "tasks", "backend", "pipeline", "model_id",
    "revision", "limits", "outputs", "resources", "qualification", "license",
})
_LIMIT_KEYS = frozenset({"max_prompt_chars", "sizes", "max_steps", "max_frames"})
_RESOURCE_KEYS = frozenset({"min_usable_gib", "reserve_gib", "devices", "cpu_offload"})


@dataclass(frozen=True)
class Limits:
    max_prompt_chars: int
    sizes: tuple[tuple[int, int], ...]
    max_steps: int
    max_frames: int | None


@dataclass(frozen=True)
class Resources:
    min_usable_gib: float
    reserve_gib: float
    devices: tuple[str, ...]
    cpu_offload: bool


@dataclass(frozen=True)
class ModelProfile:
    profile_id: str
    modality: str
    tasks: frozenset[str]
    backend: str
    pipeline: str | None
    model_id: str
    revision: str
    limits: Limits
    outputs: frozenset[str]
    resources: Resources
    qualification: str
    license: str


def _fail(reason: str) -> GenerationError:
    return GenerationError(f"invalid model profile: {reason}")


def _strict_int(value: object, low: int, high: int, name: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise _fail(f"{name} must be an integer in {low}..{high}")
    return value


def _strict_number(value: object, low: float, high: float, name: str, *, low_open: bool = False) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise _fail(f"{name} must be a finite number")
    if value > high or value < low or (low_open and value == low):
        raise _fail(f"{name} out of range")
    return float(value)


def _string(value: object, pattern: re.Pattern[str], name: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise _fail(f"{name} is malformed")
    return value


def _exact_keys(obj: object, allowed: frozenset[str], name: str) -> Mapping[str, object]:
    if not isinstance(obj, dict):
        raise _fail(f"{name} must be an object")
    unknown = set(obj) - allowed
    missing = allowed - set(obj)
    if unknown:
        raise _fail(f"{name} has unknown keys {sorted(unknown)}")
    if missing:
        raise _fail(f"{name} is missing {sorted(missing)}")
    return obj


def parse_profile(obj: object) -> ModelProfile:
    data = _exact_keys(obj, _TOP_KEYS, "profile")
    if data["schema"] != SCHEMA:
        raise _fail("unsupported schema")
    profile_id = _string(data["profile_id"], _PROFILE_ID, "profile_id")
    modality = data["modality"]
    if modality not in MODALITY_TASKS:
        raise _fail("unknown modality")
    backend = data["backend"]
    if backend not in BACKENDS:
        raise _fail("unknown backend")
    if BACKENDS[backend] != modality:
        raise _fail(f"backend {backend} does not serve {modality}")
    pipeline = data["pipeline"]
    if backend == "diffusers":
        if pipeline not in DIFFUSERS_PIPELINES:
            raise _fail("pipeline is not on the diffusers allowlist")
    elif pipeline is not None:
        raise _fail("pipeline is only valid for the diffusers backend")

    tasks = data["tasks"]
    if not isinstance(tasks, list) or not tasks or len(set(tasks)) != len(tasks):
        raise _fail("tasks must be a non-empty list without duplicates")
    if any(task not in TASKS for task in tasks):
        raise _fail("unknown task")
    if not set(tasks) <= MODALITY_TASKS[modality]:
        raise _fail(f"tasks do not match modality {modality}")

    model_id = _string(data["model_id"], _MODEL_ID, "model_id")
    if "://" in model_id or ".." in model_id.split("/"):
        raise _fail("model_id must be a repository id or a relative local name")
    revision = _string(data["revision"], _REVISION, "revision (pin a 40-hex commit)")

    raw_limits = _exact_keys(data["limits"], _LIMIT_KEYS, "limits")
    sizes = raw_limits["sizes"]
    if not isinstance(sizes, list) or not 1 <= len(sizes) <= 16:
        raise _fail("limits.sizes must list 1..16 [width, height] pairs")
    parsed_sizes = []
    for pair in sizes:
        if not isinstance(pair, list) or len(pair) != 2:
            raise _fail("limits.sizes entries must be [width, height]")
        width = _strict_int(pair[0], 64, 2048, "width")
        height = _strict_int(pair[1], 64, 2048, "height")
        if width % 8 or height % 8:
            raise _fail("sizes must be multiples of 8")
        parsed_sizes.append((width, height))
    if len(set(parsed_sizes)) != len(parsed_sizes):
        raise _fail("limits.sizes has duplicates")
    max_frames = raw_limits["max_frames"]
    if modality == "video":
        max_frames = _strict_int(max_frames, 1, 1024, "limits.max_frames")
    elif max_frames is not None:
        raise _fail("limits.max_frames is only valid for video")
    limits = Limits(
        max_prompt_chars=_strict_int(raw_limits["max_prompt_chars"], 1, 8000, "limits.max_prompt_chars"),
        sizes=tuple(parsed_sizes),
        max_steps=_strict_int(raw_limits["max_steps"], 1, 200, "limits.max_steps"),
        max_frames=max_frames,
    )

    outputs = data["outputs"]
    if not isinstance(outputs, list) or not outputs or len(set(outputs)) != len(outputs):
        raise _fail("outputs must be a non-empty list without duplicates")
    if any(mime not in ARTIFACT_TYPES for mime in outputs):
        raise _fail("unsupported output type")
    if not set(outputs) <= MODALITY_OUTPUTS[modality]:
        raise _fail(f"outputs do not match modality {modality}")

    raw_resources = _exact_keys(data["resources"], _RESOURCE_KEYS, "resources")
    devices = raw_resources["devices"]
    if not isinstance(devices, list) or not devices or len(set(devices)) != len(devices):
        raise _fail("resources.devices must be a non-empty list without duplicates")
    for device in devices:
        _string(device, _DEVICE, "resources.devices entry")
    if type(raw_resources["cpu_offload"]) is not bool:
        raise _fail("resources.cpu_offload must be a boolean")
    resources = Resources(
        min_usable_gib=_strict_number(raw_resources["min_usable_gib"], 0, 128, "resources.min_usable_gib", low_open=True),
        reserve_gib=_strict_number(raw_resources["reserve_gib"], 0, 64, "resources.reserve_gib"),
        devices=tuple(devices),
        cpu_offload=raw_resources["cpu_offload"],
    )

    qualification = data["qualification"]
    if qualification not in QUALIFICATIONS:
        raise _fail("unknown qualification")
    license_ = _string(data["license"], _LICENSE, "license")

    return ModelProfile(
        profile_id=profile_id, modality=modality, tasks=frozenset(tasks), backend=backend,
        pipeline=pipeline, model_id=model_id, revision=revision, limits=limits,
        outputs=frozenset(outputs), resources=resources, qualification=qualification, license=license_,
    )


def load_profile_dir(directory: str) -> dict[str, ModelProfile]:
    """Read every *.json profile in an operator directory. Any invalid file fails the whole set."""
    path = Path(directory)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise _fail("profile directory must be an existing absolute non-symlink directory")
    profiles: dict[str, ModelProfile] = {}
    files = sorted(p for p in path.iterdir() if p.suffix == ".json")
    if len(files) > MAX_PROFILES:
        raise _fail("too many profile files")
    for file in files:
        if file.is_symlink() or not file.is_file():
            raise _fail(f"{file.name} is not a regular file")
        if file.stat().st_size > MAX_PROFILE_BYTES:
            raise _fail(f"{file.name} is too large")
        try:
            obj = json.loads(file.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _fail(f"{file.name} is not valid JSON") from exc
        try:
            profile = parse_profile(obj)
        except GenerationError as exc:
            raise GenerationError(f"{file.name}: {exc}") from None
        if profile.profile_id in profiles:
            raise _fail(f"duplicate profile_id {profile.profile_id}")
        profiles[profile.profile_id] = profile
    return profiles


def enabled_profiles(profiles: Mapping[str, ModelProfile], env: Mapping[str, str] | None = None) -> dict[str, ModelProfile]:
    """The profiles an operator explicitly enabled. Empty unless the environment says otherwise."""
    env = os.environ if env is None else env
    raw = env.get(ENABLED_ENV, "").strip()
    if not raw:
        return {}
    wanted = [item.strip() for item in raw.split(",")]
    if any(not item for item in wanted) or len(set(wanted)) != len(wanted):
        raise GenerationError(f"{ENABLED_ENV} must be a comma-separated list of distinct profile ids")
    unknown = [item for item in wanted if item not in profiles]
    if unknown:
        raise GenerationError(f"{ENABLED_ENV} names unknown profiles {unknown}")
    allow_candidates = env.get(ALLOW_CANDIDATES_ENV, "0") == "1"
    blocked = [item for item in wanted if profiles[item].qualification != "rig-qualified" and not allow_candidates]
    if blocked:
        raise GenerationError(f"profiles {blocked} are not rig-qualified; set {ALLOW_CANDIDATES_ENV}=1 to run candidates")
    return {item: profiles[item] for item in wanted}


def validate_request(profile: ModelProfile, request: GenerationRequest) -> GenerationRequest:
    """Check a request against its profile's limits and fill defaults. Raises before any GPU work."""
    if not isinstance(request, GenerationRequest):
        raise GenerationError("not a generation request")
    if request.profile_id != profile.profile_id:
        raise GenerationError("request is for another profile")
    if request.task not in profile.tasks:
        raise GenerationError("task not supported by this profile")
    if not isinstance(request.prompt, str) or not request.prompt.strip():
        raise GenerationError("prompt required")
    if len(request.prompt) > profile.limits.max_prompt_chars:
        raise GenerationError("prompt too long for this profile")
    if request.extra:
        raise GenerationError("extra parameters are not accepted in v1")

    if (request.width is None) != (request.height is None):
        raise GenerationError("width and height must be given together")
    if request.width is None:
        width, height = profile.limits.sizes[0]
    else:
        if type(request.width) is not int or type(request.height) is not int:
            raise GenerationError("width and height must be integers")
        width, height = request.width, request.height
        if (width, height) not in profile.limits.sizes:
            raise GenerationError("size not allowed by this profile")

    steps = request.steps
    if steps is None:
        steps = min(30, profile.limits.max_steps)
    elif type(steps) is not int or not 1 <= steps <= profile.limits.max_steps:
        raise GenerationError("steps out of range for this profile")

    if request.seed is not None and (type(request.seed) is not int or not 0 <= request.seed < 2**32):
        raise GenerationError("seed must be an integer in 0..2^32-1")

    frames = request.frames
    if profile.modality == "video":
        if frames is None:
            frames = profile.limits.max_frames
        elif type(frames) is not int or not 1 <= frames <= profile.limits.max_frames:
            raise GenerationError("frames out of range for this profile")
    elif frames is not None:
        raise GenerationError("frames are only valid for video")

    needs_input = request.task in ("image_to_image", "image_to_video")
    if needs_input:
        if not isinstance(request.input_asset_id, str) or not _ASSET_ID.fullmatch(request.input_asset_id):
            raise GenerationError("input_asset_id required for this task")
    elif request.input_asset_id is not None:
        raise GenerationError("input_asset_id is only valid for image-to-* tasks")

    return replace(request, width=width, height=height, steps=steps, frames=frames)
