"""Crash-durable create-once file and directory publication primitives.

The helpers in this module do not decide whether recovery is authorized. They
only provide link-free, no-overwrite commit mechanics. Callers must bind every
recovery decision to their own immutable authority evidence and receipt.
"""
from __future__ import annotations

import ctypes
import errno
import os
import shutil
import stat
import tempfile
from pathlib import Path


class DurablePublicationError(RuntimeError):
    """A durable publication operation could not be proven safe."""


def _is_linkish(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def _has_linkish_component(path: Path) -> bool:
    current = path.absolute()
    while True:
        if _is_linkish(current):
            return True
        if current.parent == current:
            return False
        current = current.parent


def _directory(path: Path, *, name: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise DurablePublicationError(f"{name} must be absolute")
    if _has_linkish_component(candidate):
        raise DurablePublicationError(f"{name} must be link-free")
    resolved = candidate.resolve()
    if not resolved.is_dir():
        raise DurablePublicationError(f"{name} must be an existing directory")
    return resolved


def sync_directory(path: Path) -> None:
    """Persist directory metadata where the platform exposes that primitive."""

    directory = _directory(path, name="directory sync target")
    if os.name == "nt":
        # Windows directory durability is provided by MoveFileExW with
        # MOVEFILE_WRITE_THROUGH at the publication commit point.
        return
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(directory, flags)
    except OSError as exc:
        raise DurablePublicationError("directory could not be opened for sync") from exc
    try:
        os.fsync(descriptor)
    except OSError as exc:
        raise DurablePublicationError("directory sync failed") from exc
    finally:
        os.close(descriptor)


def sync_file(path: Path) -> None:
    candidate = Path(path)
    if (
        not candidate.is_absolute()
        or _has_linkish_component(candidate)
        or not candidate.is_file()
    ):
        raise DurablePublicationError("file sync target is missing or unsafe")
    try:
        descriptor = os.open(candidate, os.O_RDONLY)
    except OSError as exc:
        raise DurablePublicationError("file could not be opened for sync") from exc
    try:
        os.fsync(descriptor)
    except OSError as exc:
        raise DurablePublicationError("file sync failed") from exc
    finally:
        os.close(descriptor)


def sync_tree(root: Path) -> None:
    """Flush every regular file and directory in one link-free tree."""

    tree = _directory(root, name="publication tree")
    directories: list[Path] = [tree]
    for current, names, files in os.walk(tree, topdown=True, followlinks=False):
        base = Path(current)
        names.sort()
        files.sort()
        for name in names:
            child = base / name
            if _is_linkish(child) or not child.is_dir():
                raise DurablePublicationError(
                    "publication tree contains a linked or invalid directory"
                )
            directories.append(child)
        for name in files:
            child = base / name
            if _is_linkish(child) or not child.is_file():
                raise DurablePublicationError(
                    "publication tree contains a linked or invalid file"
                )
            observed = child.stat()
            if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
                raise DurablePublicationError(
                    "publication tree contains a non-regular or aliased file"
                )
            sync_file(child.resolve())
    for directory in sorted(
        directories, key=lambda item: len(item.parts), reverse=True
    ):
        sync_directory(directory.resolve())


def _windows_move_no_replace(source: Path, destination: Path) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    move_file = kernel32.MoveFileExW
    move_file.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    move_file.restype = ctypes.c_int
    movefile_write_through = 0x00000008
    if move_file(str(source), str(destination), movefile_write_through):
        return
    code = ctypes.get_last_error()
    if code in {80, 183}:
        raise FileExistsError(str(destination))
    raise DurablePublicationError(
        f"Windows durable no-replace move failed with error {code}"
    )


def _linux_rename_no_replace(source: Path, destination: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise DurablePublicationError(
            "atomic no-replace directory rename is unavailable"
        )
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    at_fdcwd = -100
    rename_noreplace = 1
    result = renameat2(
        at_fdcwd,
        os.fsencode(source),
        at_fdcwd,
        os.fsencode(destination),
        rename_noreplace,
    )
    if result == 0:
        return
    code = ctypes.get_errno()
    if code == errno.EEXIST:
        raise FileExistsError(str(destination))
    raise DurablePublicationError(
        f"atomic no-replace directory rename failed with errno {code}"
    )


def rename_directory_no_replace(source: Path, destination: Path) -> None:
    """Commit one prepared sibling directory without replacing any name."""

    pending = _directory(source, name="pending publication directory")
    final = Path(destination)
    parent = _directory(final.parent, name="publication parent")
    if pending.parent != parent or final.parent.resolve() != parent:
        raise DurablePublicationError(
            "pending and final publication paths must share one parent"
        )
    if final.is_symlink() or final.exists():
        raise FileExistsError(str(final))
    sync_tree(pending)
    if os.name == "nt":
        _windows_move_no_replace(pending, final)
    elif (
        os.name == "posix"
        and hasattr(os, "uname")
        and os.uname().sysname == "Linux"
    ):
        _linux_rename_no_replace(pending, final)
        sync_directory(parent)
    else:
        raise DurablePublicationError(
            "atomic no-replace directory publication is unsupported"
        )


def create_once_file(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    """Durably publish one immutable file without overwriting an existing name."""

    destination = Path(path)
    if not destination.is_absolute() or not isinstance(payload, bytes):
        raise DurablePublicationError("create-once file inputs are invalid")
    parent = _directory(destination.parent, name="create-once file parent")
    if destination.parent.resolve() != parent or _is_linkish(destination):
        raise DurablePublicationError("create-once file path is unsafe")
    if destination.exists():
        raise FileExistsError(str(destination))
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".pending", dir=parent
    )
    temporary = Path(temporary_name)
    published = False
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        sync_file(temporary.resolve())
        if os.name == "nt":
            _windows_move_no_replace(temporary, destination)
            published = True
        else:
            try:
                os.link(temporary, destination)
            except FileExistsError:
                raise
            except OSError as exc:
                raise DurablePublicationError(
                    "create-once hard-link publication failed"
                ) from exc
            published = True
            sync_directory(parent)
            temporary.unlink()
            sync_directory(parent)
        if not destination.is_file() or _is_linkish(destination):
            raise DurablePublicationError(
                "published create-once file is missing or unsafe"
            )
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            try:
                temporary.unlink()
                if os.name != "nt":
                    sync_directory(parent)
            except OSError:
                if not published:
                    raise


def unlink_durable(path: Path) -> None:
    candidate = Path(path)
    if not candidate.is_absolute() or _has_linkish_component(candidate.parent):
        raise DurablePublicationError("durable unlink path is unsafe")
    parent = _directory(candidate.parent, name="durable unlink parent")
    try:
        candidate.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise DurablePublicationError("durable unlink failed") from exc
    if os.name != "nt":
        sync_directory(parent)


def remove_tree_durable(path: Path) -> None:
    candidate = Path(path)
    if not candidate.is_absolute() or _has_linkish_component(candidate):
        raise DurablePublicationError("durable tree removal path is unsafe")
    parent = _directory(candidate.parent, name="durable tree removal parent")
    if not candidate.exists():
        return
    if not candidate.is_dir():
        raise DurablePublicationError(
            "durable tree removal target is not a directory"
        )
    try:
        shutil.rmtree(candidate)
    except OSError as exc:
        raise DurablePublicationError("durable tree removal failed") from exc
    if os.name != "nt":
        sync_directory(parent)
