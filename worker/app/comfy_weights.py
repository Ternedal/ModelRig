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
import re
import secrets
import stat
from pathlib import Path
from typing import Iterable

from .media_generation_contract import GenerationError
from .media_generation_profiles import WeightPin

CHUNK = 16 * 1024 * 1024
_DIGEST = re.compile(r"[0-9a-f]{64}")  # a cached value is only ever compared if it is one
CACHE_VERSION = 1
MAX_CACHE_BYTES = 1024 * 1024
# Non-blocking, so a FIFO (or a file swapped for one) cannot hang the open before fstat rejects
# it (#2328 review 4472123700). Regular files ignore O_NONBLOCK. Windows has neither flag nor FIFOs.
_READ_FLAGS = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
               | getattr(os, "O_BINARY", 0))


class WeightsMismatch(GenerationError):
    """A pinned model file is missing, replaced, resized or modified."""


def _load_cache(cache_path: str | None) -> dict[str, str]:
    if cache_path is None:
        return {}
    try:
        fd = os.open(cache_path, _READ_FLAGS)
        try:  # a FIFO reads as empty and a directory raises: both end as "no cache"
            raw = b""
            while len(raw) <= MAX_CACHE_BYTES:
                chunk = os.read(fd, MAX_CACHE_BYTES + 1 - len(raw))
                if not chunk:
                    break
                raw += chunk
        finally:
            os.close(fd)
        if len(raw) > MAX_CACHE_BYTES:
            return {}
        data = json.loads(raw.decode("utf-8"))
        entries = data.get("entries") if data.get("version") == CACHE_VERSION else None
        # Anything else is dropped, not compared: hmac.compare_digest raises on a non-ASCII
        # string, which would turn a malformed cache into a failed load (#2328 review 4472955385).
        return {k: v for k, v in entries.items() if isinstance(k, str) and isinstance(v, str)
                and _DIGEST.fullmatch(v)} if isinstance(entries, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def _store_cache(cache_path: str | None, entries: dict[str, str]) -> None:
    if cache_path is None:
        return
    tmp = f"{cache_path}.tmp-{os.getpid()}-{secrets.token_hex(4)}"
    try:
        # O_EXCL: never write through something already there (a FIFO would block the open).
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_BINARY", 0), 0o600)
    except OSError:
        return  # best-effort: a missing cache only costs a re-hash
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
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

    Names are compared case-insensitively: on the rig's Windows, a lookup of "wan.safetensors"
    also opens "unet/WAN.safetensors" (#2328 review 4472405235, rig OS).

    No unpinned file may sit in models/embeddings: ComfyUI's tokenizer loads one for any
    "embedding:<name>" in a text, extension or not (#2328 review 4472675615). The template and
    bind() also refuse the reference; this keeps the guarantee independent of prompt parsing.
    """
    if Path(comfy_root, "extra_model_paths.yaml").exists() or Path(comfy_root, "extra_model_paths.yml").exists():
        raise WeightsMismatch("ComfyUI has extra model paths configured: lookups are not limited to the verified models directory")
    root = Path(models_directory)
    pinned = {pin.path: pin.path.rsplit("/", 1)[-1] for pin in pins}
    names = {name.casefold() for name in pinned.values()}
    for current, dirs, files in os.walk(root, followlinks=False):
        for entry in dirs + files:
            if os.path.islink(os.path.join(current, entry)):
                raise WeightsMismatch(f"the models directory contains a link ComfyUI would follow: "
                                      f"{os.path.relpath(os.path.join(current, entry), root)}")
        in_embeddings = os.path.relpath(current, root).replace(os.sep, "/").split("/")[0].casefold() == "embeddings"
        for name in files:
            if in_embeddings:
                relative = os.path.relpath(os.path.join(current, name), root).replace(os.sep, "/")
                if relative not in pinned:
                    raise WeightsMismatch(f"an unpinned embedding could be loaded by a prompt: {relative}")
            if name.casefold() in names:
                relative = os.path.relpath(os.path.join(current, name), root).replace(os.sep, "/")
                if relative not in pinned:
                    raise WeightsMismatch(f"a second file named like a pinned weight would be found by ComfyUI: {relative}")


def verify_weights(models_directory: str | Path, pins: Iterable[WeightPin], *, cache_path: str | None = None,
                   comfy_root: str | Path | None = None) -> tuple[tuple[str, int, int, int, int], ...]:
    """Raise WeightsMismatch unless every pinned file matches. Names the file, never its contents.

    With comfy_root (ComfyUI's main.py directory), also proves the lookup is unambiguous.
    The cache is an opt-in optimisation for a trusted local filesystem (see the module docstring);
    without cache_path every file is re-hashed.

    Returns the identity of each verified file, (path, st_dev, st_ino, size, mtime_ns), for
    check_weights_unchanged(): ComfyUI reads weights when a job runs, not when it starts.
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
    verified: list[tuple[str, int, int, int, int]] = []
    for pin in pins:
        candidate = root / pin.path
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            raise WeightsMismatch(f"pinned model file is missing: {pin.path}") from None
        if resolved != candidate or root not in resolved.parents:
            raise WeightsMismatch(f"pinned model file is a link or outside the models directory: {pin.path}")
        try:
            fd = os.open(candidate, _READ_FLAGS)
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
                verified.append(_identity(candidate, pin.path, info))
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
            verified.append(_identity(candidate, pin.path, info))
        finally:
            os.close(fd)
    if changed:
        _store_cache(cache_path, cache)
    return tuple(verified)


def _identity(candidate: Path, path: str, info: os.stat_result) -> tuple[str, int, int, int, int]:
    """The verified file's identity as os.lstat reports it -- the call check_weights_unchanged
    repeats, so both sides come from the same API (on Windows fstat and lstat may differ in
    how they report the file id). It must describe the file that was hashed."""
    now = os.lstat(candidate)
    if not stat.S_ISREG(now.st_mode) or (now.st_size, now.st_mtime_ns) != (info.st_size, info.st_mtime_ns):
        raise WeightsMismatch(f"pinned model file changed while it was verified: {path}")
    return (path, now.st_dev, now.st_ino, now.st_size, now.st_mtime_ns)


def check_weights_unchanged(models_directory: str | Path, verified) -> None:
    """Raise WeightsMismatch if a file verified at start is no longer the same file.

    ComfyUI loads a model when the first job that needs it runs, so a start-time hash alone
    leaves the whole resident lifetime open. Before every job each pinned path must still be a
    regular file with the inode, size and mtime that were hashed: a rewrite, a replacement by
    rename, or a deletion is caught without re-hashing. Stated limit: a change between this
    check and ComfyUI's read, or one that restores size, inode and mtime, needs write access to
    the models directory, which only the operator may have.
    """
    root = Path(models_directory)
    for path, dev, ino, size, mtime_ns in verified:
        try:
            info = os.lstat(root / path)
        except OSError:
            raise WeightsMismatch(f"pinned model file changed since it was verified: {path}") from None
        if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (dev, ino, size, mtime_ns):
            raise WeightsMismatch(f"pinned model file changed since it was verified: {path}")
