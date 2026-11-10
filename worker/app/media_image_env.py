"""Read-only checks of the image engine's environment on the rig (#2275 backlog item 4).

The media executor renders images with diffusers (``diffusers_image_adapter``). Before any profile is
enabled, the operator runs ``scripts/media_image_env_check.py`` in the media venv. It reports, as JSON:

- the installed versions against the pins in ``deploy/media-image-requirements.txt``;
- CUDA: available, device names, compute capability, bfloat16 support (the adapter loads in bf16);
- for every allowlisted pipeline: the class exists, ``__call__`` takes the arguments the adapter
  passes, and the source resets and checks the interrupt flag that cancellation relies on
  (``self._interrupt = False`` / ``if self.interrupt``), plus ``enable_model_cpu_offload``;
- for information, the offline switches in this shell (the executor sets them itself);
- with a profile: that its pinned snapshot is complete in the local Hugging Face cache.

It never downloads, never loads weights and never touches a GPU beyond querying its properties.
torch and diffusers are imported only inside the functions, never at module level.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

from .media_generation_profiles import DIFFUSERS_PIPELINES, ModelProfile

ENV_FORMAT = "kaliv-media-image-env/v1"
# Must match deploy/media-image-requirements.txt (tests/worker_media_image_env.py checks both).
PINNED_VERSIONS = {
    "torch": "2.8.0",
    "diffusers": "0.35.2",
    "transformers": "4.56.2",
    "accelerate": "1.10.1",
    "safetensors": "0.6.2",
    "huggingface_hub": "0.35.3",
}
# What DiffusersImageAdapter.render passes to the pipeline.
PIPELINE_CALL_ARGS = ("prompt", "num_inference_steps", "width", "height", "generator", "callback_on_step_end")
INTERRUPT_RESET = "self._interrupt = False"
INTERRUPT_CHECK = "if self.interrupt"


def load_modules() -> dict[str, ModuleType | str]:
    """The installed engine modules, or the import error's type name for a missing one."""
    found: dict[str, ModuleType | str] = {}
    try:
        import torch
        found["torch"] = torch
    except Exception as exc:  # an import failure is a finding, not a crash
        found["torch"] = type(exc).__name__
    try:
        import diffusers
        found["diffusers"] = diffusers
    except Exception as exc:
        found["diffusers"] = type(exc).__name__
    try:
        import transformers
        found["transformers"] = transformers
    except Exception as exc:
        found["transformers"] = type(exc).__name__
    try:
        import accelerate
        found["accelerate"] = accelerate
    except Exception as exc:
        found["accelerate"] = type(exc).__name__
    try:
        import safetensors
        found["safetensors"] = safetensors
    except Exception as exc:
        found["safetensors"] = type(exc).__name__
    try:
        import huggingface_hub
        found["huggingface_hub"] = huggingface_hub
    except Exception as exc:
        found["huggingface_hub"] = type(exc).__name__
    return found


def _check(checks: list[dict[str, Any]], name: str, ok: bool, detail: Any) -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})


def _error_text(error: BaseException) -> str:
    first = str(error).splitlines()[0][:160] if str(error) else ""
    return f"{type(error).__name__}: {first}" if first else type(error).__name__


def _public_version(value: object) -> str:
    return str(value).split("+", 1)[0]


def check_environment(modules: Mapping[str, ModuleType | str], env: Mapping[str, str]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for name, pinned in PINNED_VERSIONS.items():
        module = modules.get(name)
        if not isinstance(module, ModuleType):
            _check(checks, f"version:{name}", False, f"not importable ({module or 'missing'})")
            continue
        installed = getattr(module, "__version__", None)
        _check(checks, f"version:{name}", _public_version(installed) == pinned,
               {"installed": installed, "pinned": pinned})

    torch = modules.get("torch")
    if isinstance(torch, ModuleType):
        try:
            available = bool(torch.cuda.is_available())
            devices = []
            for index in range(int(torch.cuda.device_count()) if available else 0):
                major, minor = torch.cuda.get_device_capability(index)
                devices.append({
                    "index": index,
                    "name": str(torch.cuda.get_device_name(index)),
                    "capability": f"{major}.{minor}",
                    # bf16 tensor cores start with Ampere (8.0); the adapter loads in bfloat16.
                    "bf16": major >= 8,
                    "total_gib": round(torch.cuda.get_device_properties(index).total_memory / 2 ** 30, 2),
                })
            _check(checks, "cuda:available", available, {"devices": devices})
            _check(checks, "cuda:bf16", bool(devices) and all(d["bf16"] for d in devices),
                   "no CUDA device" if not devices
                   else [d["name"] for d in devices if not d["bf16"]] or "every device supports bfloat16")
        except Exception as exc:
            _check(checks, "cuda:available", False, f"query failed ({type(exc).__name__})")

    diffusers = modules.get("diffusers")
    for pipeline in sorted(DIFFUSERS_PIPELINES):
        if not isinstance(diffusers, ModuleType):
            _check(checks, f"pipeline:{pipeline}", False, "diffusers is not importable")
            continue
        try:
            # diffusers resolves pipelines lazily: a broken transitive dependency raises here, not at
            # import time, and must become a failed check rather than end the report (Codex #2366).
            cls = getattr(diffusers, pipeline, None)
        except Exception as exc:
            _check(checks, f"pipeline:{pipeline}", False, f"cannot import ({_error_text(exc)})")
            continue
        if cls is None:
            _check(checks, f"pipeline:{pipeline}", False, "not in this diffusers")
            continue
        problems = []
        try:
            parameters = inspect.signature(cls.__call__).parameters
            problems += [f"__call__ lacks {arg}" for arg in PIPELINE_CALL_ARGS if arg not in parameters]
            source = inspect.getsource(cls.__call__)
            if INTERRUPT_RESET not in source:
                problems.append("__call__ does not reset the interrupt flag")
            if INTERRUPT_CHECK not in source:
                problems.append("__call__ does not check the interrupt flag between steps")
        except (TypeError, OSError, ValueError) as exc:
            problems.append(f"cannot inspect __call__ ({type(exc).__name__})")
        if not hasattr(cls, "enable_model_cpu_offload"):
            problems.append("no enable_model_cpu_offload")
        _check(checks, f"pipeline:{pipeline}", not problems, problems or "callbacks and interrupt as the adapter expects")

    return checks


def offline_info(env: Mapping[str, str]) -> dict[str, str]:
    """Information only: the executor sets both itself, whatever the operator's shell has."""
    return {name: env.get(name) or "unset" for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")}


def hub_cache(env: Mapping[str, str], modules: Mapping[str, ModuleType | str]) -> Path:
    hub = modules.get("huggingface_hub")
    constants = getattr(hub, "constants", None) if isinstance(hub, ModuleType) else None
    cache = getattr(constants, "HF_HUB_CACHE", None)
    if cache:
        return Path(cache)
    if env.get("HF_HUB_CACHE"):
        return Path(env["HF_HUB_CACHE"])
    if env.get("HF_HOME"):
        return Path(env["HF_HOME"]) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


# Components that always carry weights; any other component with a model config.json does too.
WEIGHTED_COMPONENTS = ("unet", "transformer", "vae", "text_encoder", "text_encoder_2")
# The default (variant=None) safetensors names: the adapter calls from_pretrained without a variant,
# so fp16/other variant files do not count. Pickle .bin weights are deliberately not accepted.
DEFAULT_WEIGHTS = {"diffusers": "diffusion_pytorch_model.safetensors", "transformers": "model.safetensors"}


def _missing_default_weights(name: str, part: Path, library: object) -> list[str]:
    """What is missing of the weights from_pretrained (no variant) loads for one component."""
    weights = DEFAULT_WEIGHTS.get(str(library), DEFAULT_WEIGHTS["diffusers"])
    if (part / weights).is_file():
        return []
    index = part / f"{weights}.index.json"
    if not index.is_file():
        return [f"{name}/ has no {weights} (variant-only or missing weights)"]
    try:
        weight_map = json.loads(index.read_text(encoding="utf-8")).get("weight_map")
        shards = sorted(set(weight_map.values()))
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError, TypeError) as exc:
        return [f"{name}/{index.name} unreadable ({type(exc).__name__})"]
    if not shards or not all(isinstance(shard, str) and shard and "/" not in shard and "\\" not in shard
                             for shard in shards):
        return [f"{name}/{index.name} lists no valid shards"]
    absent = [shard for shard in shards if not (part / shard).is_file()]
    return [f"{name}/ lacks shard {shard}" for shard in absent]


def check_profile_snapshot(profile: ModelProfile, cache: Path) -> list[dict[str, Any]]:
    """The pinned revision is in the local cache with every component model_index.json names."""
    checks: list[dict[str, Any]] = []
    folder = cache / ("models--" + profile.model_id.replace("/", "--")) / "snapshots" / profile.revision
    index = folder / "model_index.json"
    if not index.is_file():
        _check(checks, f"snapshot:{profile.profile_id}", False, f"no model_index.json for revision {profile.revision}")
        return checks
    try:
        components = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _check(checks, f"snapshot:{profile.profile_id}", False, f"model_index.json unreadable ({type(exc).__name__})")
        return checks
    missing = []
    for name, value in sorted(components.items()):
        if name.startswith("_") or not isinstance(value, list) or len(value) != 2 or value[0] is None:
            continue  # metadata or an optional component the pipeline does not use
        part = folder / name
        if not part.is_dir():
            missing.append(f"{name}/")
            continue
        has_config = any((part / config).is_file() for config in ("config.json", "scheduler_config.json",
                                                                  "tokenizer_config.json", "preprocessor_config.json"))
        if not has_config:
            missing.append(f"{name}/ has no config")
        if (part / "config.json").is_file() or name in WEIGHTED_COMPONENTS:
            missing += _missing_default_weights(name, part, value[0])
    _check(checks, f"snapshot:{profile.profile_id}", not missing, missing or f"complete at {folder.name}")
    return checks


def report(checks: list[dict[str, Any]], env: Mapping[str, str]) -> dict[str, Any]:
    return {"format": ENV_FORMAT, "ok": bool(checks) and all(c["ok"] for c in checks), "checks": checks,
            "offline_switches_in_this_shell": offline_info(env)}
