"""Verify the model files ComfyUI will load against the profile's pins (G3, ModelRig #2296).

A comfyui profile can pin weights: [{path, sha256, bytes}], relative to ComfyUI's
models directory. Before ComfyUI starts, every pinned file must be a regular file
(not a symlink), inside the models directory after resolving, of exactly the
pinned size, and its SHA-256 must match. Together with the template binding in
comfy_workflow_template (a pinned graph may only load pinned files), the graph
that runs can only read pinned bytes.

Hashing ~10 GB on every start is slow, so an operator MAY opt in to caching
verified results in a JSON file keyed by (real path, st_dev, st_ino, size,
mtime_ns): any change to the file re-hashes it, and a cache that is missing or
unreadable is ignored (a re-hash, never an acceptance). The default is no cache:
every start re-hashes. Threat model for the cache: a trusted local filesystem.
An actor who rewrites a file in place and restores its size and mtime under the
same inode defeats the cache; such an actor can edit the profile as well.

A matching hash only proves which file ComfyUI loads if its lookup cannot reach
another file of the same name: check_lookup_is_unambiguous() refuses an
extra_model_paths file, links in the models tree, and duplicate pinned names.
Stdlib only; nothing is imported from torch.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
from pathlib import Path
from typing import Iterable

from .media_generation_contract import GenerationError
from .media_generation_profiles import WeightPin

CHUNK = 16 * 1024 * 1024
CACHE_VERSION = 1


class WeightsMismatch(GenerationError):
    """A pinned model file is missing, replaced, resized or modified."""


def _load_cache(cache_path: str | None) -> dict[str, str]:
    if cache_path is None:
        return {}
    try:
        with open(cache_path, encoding="utf-8") as handle:
            data = json.load(handle)
        entries = data.get("entries") if data.get("version") == CACHE_VERSION else None
        return {k: v for k, v in entries.items() if isinstance(k, str) and isinstance(v, str)} \
            if isinstance(entries, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def _store_cache(cache_path: str | None, entries: dict[str, str]) -> None:
    if cache_path is None:
        return
    tmp = f"{cache_path}.tmp-{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"version": CACHE_VERSION, "entries": entries}, handle, sort_keys=True)
        os.replace(tmp, cache_path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass  # best-effort: a missing cache only costs a re-hash


def check_lookup_is_unambiguous(comfy_root: str | Path, models_directory: str | Path, pins) -> None:
    """ComfyUI must be able to find each pinned name in exactly one place: the pinned file.

    ComfyUI (a) reads <root>/extra_model_paths.yaml on its own if it exists, (b) searches every
    model folder recursively and treats some folders as aliases (unet/ for diffusion_models/),
    and (c) follows links. A file-name match proves which file loads only if none of those can
    point it elsewhere (#2296 6636684138), so: no extra paths file, no links anywhere in the
    models tree, and no second file anywhere under it with a pinned name.
    """
    if Path(comfy_root, "extra_model_paths.yaml").exists() or Path(comfy_root, "extra_model_paths.yml").exists():
        raise WeightsMismatch("ComfyUI has extra model paths configured: lookups are not limited to the verified models directory")
    root = Path(models_directory)
    pinned = {pin.path: pin.path.rsplit("/", 1)[-1] for pin in pins}
    names = set(pinned.values())
    for current, dirs, files in os.walk(root, followlinks=False):
        for entry in dirs + files:
            if os.path.islink(os.path.join(current, entry)):
                raise WeightsMismatch(f"the models directory contains a link ComfyUI would follow: "
                                      f"{os.path.relpath(os.path.join(current, entry), root)}")
        for name in files:
            if name in names:
                relative = os.path.relpath(os.path.join(current, name), root).replace(os.sep, "/")
                if relative not in pinned:
                    raise WeightsMismatch(f"a second file named like a pinned weight would be found by ComfyUI: {relative}")


def verify_weights(models_directory: str | Path, pins: Iterable[WeightPin], *, cache_path: str | None = None,
                   comfy_root: str | Path | None = None) -> None:
    """Raise WeightsMismatch unless every pinned file matches. Names the file, never its contents.

    With comfy_root (ComfyUI's main.py directory), also proves the lookup is unambiguous.
    The cache is an opt-in optimisation for a trusted local filesystem (see the module docstring);
    without cache_path every file is re-hashed.
    """
    pins = tuple(pins)
    root = Path(models_directory)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise WeightsMismatch("models directory must be an existing absolute non-symlink directory")
    root = root.resolve(strict=True)
    if comfy_root is not None:
        check_lookup_is_unambiguous(comfy_root, root, pins)
    cache = _load_cache(cache_path)
    changed = False
    for pin in pins:
        candidate = root / pin.path
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            raise WeightsMismatch(f"pinned model file is missing: {pin.path}") from None
        if resolved != candidate or root not in resolved.parents:
            raise WeightsMismatch(f"pinned model file is a link or outside the models directory: {pin.path}")
        try:
            fd = os.open(candidate, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
        except OSError:
            raise WeightsMismatch(f"pinned model file cannot be opened safely: {pin.path}") from None
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise WeightsMismatch(f"pinned model file is not a regular file: {pin.path}")
            if info.st_size != pin.bytes:
                raise WeightsMismatch(f"pinned model file has the wrong size: {pin.path}")
            key = f"{resolved}|{info.st_dev}|{info.st_ino}|{info.st_size}|{info.st_mtime_ns}"
            cached = cache.get(key)
            if cached is not None and hmac.compare_digest(cached, pin.sha256):
                continue
            digest = hashlib.sha256()
            while True:
                chunk = os.read(fd, CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
            after = os.fstat(fd)
            if (after.st_size, after.st_mtime_ns) != (info.st_size, info.st_mtime_ns):
                raise WeightsMismatch(f"pinned model file changed while it was verified: {pin.path}")
            actual = digest.hexdigest()
            if not hmac.compare_digest(actual, pin.sha256):
                raise WeightsMismatch(f"pinned model file does not match its SHA-256: {pin.path}")
            cache[key] = actual
            changed = True
        finally:
            os.close(fd)
    if changed:
        _store_cache(cache_path, cache)
