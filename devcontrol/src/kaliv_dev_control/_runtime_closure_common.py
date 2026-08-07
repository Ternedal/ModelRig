"""Private canonical-path and durable atomic-file primitives for runtime closure."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .catalog import CatalogError
from .contract import DevelopmentTask
from .durable_publication import DurablePublicationError, sync_directory
from .streaming_publication import (
    StreamingPublicationError,
    publish_stream_once,
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")

RUNTIME_CLOSURE_SCHEMA = "kaliv-development-runtime-closure-manifest/v1"
SIGNED_RUNTIME_CLOSURE_SCHEMA = (
    "kaliv-development-signed-runtime-closure-manifest/v1"
)
RUNTIME_CLOSURE_STAGING_SCHEMA = (
    "kaliv-development-runtime-closure-staging-receipt/v1"
)
RUNTIME_CLOSURE_SIGNATURE_ALGORITHM = "hmac-sha256"
_AUTHORITY_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_MAX_FILE_BYTES = 512 * 1024 * 1024
_MAX_CLOSURE_BYTES = 2 * 1024 * 1024 * 1024
_MAX_CLOSURE_FILES = 512
_RESERVED_WINDOWS_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


class RuntimeClosureError(CatalogError):
    """A signed runtime closure is invalid, changed or staged unsafely."""


def _closure_canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _closure_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _closure_task_sha(task: DevelopmentTask) -> str:
    return _closure_sha256(task.canonical_json().encode("utf-8"))


def _closure_is_linkish(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def _closure_has_linkish_component(path: Path) -> bool:
    current = path.absolute()
    while True:
        if _closure_is_linkish(current):
            return True
        if current.parent == current:
            return False
        current = current.parent


def _closure_canonical_directory(path: Path, *, name: str) -> Path:
    raw = Path(path)
    if not raw.is_absolute():
        raise RuntimeClosureError(f"{name} must be absolute")
    if _closure_has_linkish_component(raw):
        raise RuntimeClosureError(f"{name} must not contain links or junctions")
    resolved = raw.resolve()
    if not resolved.is_dir():
        raise RuntimeClosureError(f"{name} must be an existing directory")
    return resolved


def _closure_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _closure_canonical_source(path: Path, trusted_root: Path) -> Path:
    raw = Path(path)
    if not raw.is_absolute() or _closure_has_linkish_component(raw):
        raise RuntimeClosureError("runtime source must be absolute and link-free")
    resolved = raw.resolve()
    if not _closure_inside(resolved, trusted_root):
        raise RuntimeClosureError(
            "runtime source is outside the operator-controlled root"
        )
    if not resolved.is_file() or _closure_is_linkish(resolved):
        raise RuntimeClosureError("runtime source must be a regular file")
    return resolved


def _closure_file_hash_and_size(path: Path, *, maximum: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            if size > maximum:
                raise RuntimeClosureError("runtime closure exceeds its byte budget")
            digest.update(chunk)
    if size == 0:
        raise RuntimeClosureError("runtime closure files must not be empty")
    return digest.hexdigest(), size


def trusted_runtime_root_sha256(path: Path) -> str:
    root = _closure_canonical_directory(path, name="trusted runtime root")
    canonical = os.path.normcase(os.fspath(root))
    return _closure_sha256(
        b"kaliv-runtime-source-path/v1\0"
        + canonical.encode("utf-8", "surrogatepass")
    )


def _closure_relative_path(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("/")
        or "\\" in value
        or "\0" in value
        or len(value.encode("utf-8")) > 1024
    ):
        raise RuntimeClosureError(f"{name} is invalid")
    relative = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise RuntimeClosureError(f"{name} is invalid")
    for part in relative.parts:
        if (
            ":" in part
            or part.endswith((" ", "."))
            or part.casefold().split(".", 1)[0] in _RESERVED_WINDOWS_NAMES
        ):
            raise RuntimeClosureError(f"{name} is not portable to Windows")
    return relative.as_posix()


def _closure_working_directory(value: Any) -> str:
    return (
        "."
        if value == "."
        else _closure_relative_path(value, name="working directory")
    )


def _closure_secure_directory_chain(root: Path, relative: PurePosixPath) -> Path:
    current = root
    for part in relative.parts:
        if part in {"", ".", ".."}:
            raise RuntimeClosureError("runtime staging directory is invalid")
        current = current / part
        try:
            current.mkdir()
        except FileExistsError:
            pass
        if _closure_is_linkish(current) or not current.is_dir():
            raise RuntimeClosureError(
                "runtime staging directory changed to a link or non-directory"
            )
    return current


def _closure_staged_mode() -> int:
    # Windows uses the lifetime guard for immutability; Unix staging remains 0555.
    return 0o755 if os.name == "nt" else 0o555


def _closure_fix_staged_mode(path: Path) -> None:
    """Apply and durably flush the staged mode before evidence is returned."""

    descriptor = -1
    try:
        # Windows requires a write-capable handle for FlushFileBuffers. Unix can
        # fsync an already locked 0555 file through a read-only descriptor, which
        # keeps repeated deterministic staging idempotent for unprivileged users.
        access = os.O_RDWR if os.name == "nt" else os.O_RDONLY
        flags = access | getattr(os, "O_BINARY", 0)
        descriptor = os.open(path, flags)
        os.chmod(path, _closure_staged_mode())
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        sync_directory(path.parent)
    except (OSError, DurablePublicationError) as exc:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise RuntimeClosureError(
            "staged runtime permissions could not be made durable"
        ) from exc


def _closure_publish_exact_file(
    source: Path,
    destination: Path,
    *,
    expected_sha256: str,
    expected_size: int,
    maximum: int,
) -> None:
    def validate_existing(path: Path, *, concurrent: bool) -> None:
        if (
            _closure_is_linkish(path)
            or not path.is_file()
            or path.stat().st_nlink != 1
        ):
            if concurrent:
                raise RuntimeClosureError(
                    "concurrent runtime staging produced an unsafe destination"
                )
            raise RuntimeClosureError(
                "staged runtime destination is not a single-link regular file"
            )
        digest, size = _closure_file_hash_and_size(path, maximum=maximum)
        if digest != expected_sha256 or size != expected_size:
            if concurrent:
                raise RuntimeClosureError(
                    "concurrent runtime staging produced an unsafe destination"
                )
            raise RuntimeClosureError(
                "staged runtime destination already has different bytes"
            )
        _closure_fix_staged_mode(path)

    if _closure_is_linkish(destination):
        raise RuntimeClosureError("staged runtime destination is a link")
    if destination.exists():
        validate_existing(destination, concurrent=False)
        return

    try:
        published_here = publish_stream_once(
            source,
            destination,
            expected_sha256=expected_sha256,
            expected_size=expected_size,
            maximum=maximum,
            validate_existing=lambda path: validate_existing(
                path, concurrent=True
            ),
        )
    except StreamingPublicationError as exc:
        if exc.code == "source_exceeds_budget":
            raise RuntimeClosureError(
                "runtime closure exceeds its staging byte budget"
            ) from exc
        if exc.code == "source_changed":
            raise RuntimeClosureError(
                "runtime source changed while staging"
            ) from exc
        raise RuntimeClosureError(
            "runtime closure publication was not durable"
        ) from exc
    except OSError as exc:
        raise RuntimeClosureError(
            "runtime closure publication failed"
        ) from exc

    if published_here:
        try:
            _closure_fix_staged_mode(destination)
        except RuntimeClosureError:
            try:
                os.chmod(destination, 0o755)
                destination.unlink()
                sync_directory(destination.parent)
            except (OSError, DurablePublicationError):
                pass
            raise
