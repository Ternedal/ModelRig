"""Private canonical-path and atomic-file primitives for runtime closure."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .catalog import CatalogError
from .contract import DevelopmentTask

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
    return "." if value == "." else _closure_relative_path(value, name="working directory")


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


def _closure_fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _closure_publish_exact_file(
    source: Path,
    destination: Path,
    *,
    expected_sha256: str,
    expected_size: int,
    maximum: int,
) -> None:
    if _closure_is_linkish(destination):
        raise RuntimeClosureError("staged runtime destination is a link")
    if destination.exists():
        if not destination.is_file() or destination.stat().st_nlink != 1:
            raise RuntimeClosureError(
                "staged runtime destination is not a single-link regular file"
            )
        digest, size = _closure_file_hash_and_size(destination, maximum=maximum)
        if digest != expected_sha256 or size != expected_size:
            raise RuntimeClosureError(
                "staged runtime destination already has different bytes"
            )
        return

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".kaliv-stage-", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as output, source.open(
            "rb"
        ) as input_file:
            digest = hashlib.sha256()
            size = 0
            while chunk := input_file.read(1024 * 1024):
                size += len(chunk)
                if size > maximum:
                    raise RuntimeClosureError(
                        "runtime closure exceeds its staging byte budget"
                    )
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if size != expected_size or digest.hexdigest() != expected_sha256:
            raise RuntimeClosureError("runtime source changed while staging")
        try:
            os.link(temporary, destination)
        except FileExistsError:
            existing_hash, existing_size = _closure_file_hash_and_size(
                destination, maximum=maximum
            )
            if (
                destination.stat().st_nlink != 1
                or existing_hash != expected_sha256
                or existing_size != expected_size
            ):
                raise RuntimeClosureError(
                    "concurrent runtime staging produced an unsafe destination"
                )
        else:
            temporary.unlink()
            _closure_fsync_directory(destination.parent)
            try:
                os.chmod(destination, 0o555)
            except OSError as exc:
                try:
                    os.chmod(destination, 0o755)
                    destination.unlink()
                except OSError:
                    pass
                raise RuntimeClosureError(
                    "staged runtime permissions could not be fixed"
                ) from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
