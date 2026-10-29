"""Fail-closed external-volume staging and atomic adoption for large media.

This module does not expose routes, import a generator, or fall back to local
storage. The configured root must be an already-mounted dedicated volume.
"""
from __future__ import annotations

import contextlib
import os
import re
import stat
import uuid
from pathlib import Path

_ID = re.compile(r"[a-f0-9]{32}\Z")
_EXTENSIONS = {".mp4": "video/mp4", ".png": "image/png"}
_MAX_VIDEO_BYTES = 64 * 1024 * 1024 * 1024


class MediaStoreUnavailable(RuntimeError):
    pass


class StagedFileArtifactSink:
    def __init__(self, root: str | Path):
        self._root = Path(root)
        self._validate_root()

    def _validate_root(self) -> Path:
        root = self._root
        try:
            if not root.is_absolute() or root.is_symlink() or not root.is_dir():
                raise MediaStoreUnavailable("invalid_media_root")
            resolved = root.resolve(strict=True)
            if resolved != root or resolved == Path(resolved.anchor):
                raise MediaStoreUnavailable("unsafe_media_root")
            if not os.path.ismount(root):
                raise MediaStoreUnavailable("external_media_not_mounted")
            return root
        except OSError as exc:
            raise MediaStoreUnavailable("external_media_unavailable") from exc

    @contextlib.contextmanager
    def staged(self, extension: str):
        if extension not in _EXTENSIONS:
            raise ValueError("unsupported_extension")
        root = self._validate_root()
        staging = root / ".staging"
        staging.mkdir(mode=0o700, exist_ok=True)
        if staging.is_symlink() or not staging.is_dir() or staging.resolve() != staging:
            raise MediaStoreUnavailable("unsafe_staging_directory")
        path = staging / (uuid.uuid4().hex + extension + ".part")
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        try:
            yield path
        finally:
            path.unlink(missing_ok=True)

    def adopt(self, staged_path: str | Path, mime_type: str) -> str:
        root = self._validate_root()
        path = Path(staged_path)
        staging = root / ".staging"
        if staging.is_symlink() or not staging.is_dir() or staging.resolve() != staging:
            raise MediaStoreUnavailable("unsafe_staging_directory")
        if not path.is_absolute() or path.parent != staging:
            raise MediaStoreUnavailable("unowned_staging_path")
        if not path.name.endswith(".part") or not _ID.fullmatch(path.name.split(".", 1)[0]):
            raise MediaStoreUnavailable("invalid_staging_name")
        extension = Path(path.stem).suffix
        if _EXTENSIONS.get(extension) != mime_type:
            raise MediaStoreUnavailable("mime_mismatch")
        try:
            if path.is_symlink():
                raise MediaStoreUnavailable("symlink_refused")
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= _MAX_VIDEO_BYTES:
                raise MediaStoreUnavailable("invalid_staged_file")
            if not os.path.ismount(root):
                raise MediaStoreUnavailable("external_media_not_mounted")
            asset_id = uuid.uuid4().hex
            destination = root / (asset_id + extension)
            # A completed producer must have closed its handle before adopt.
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                opened = os.fstat(fd)
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    raise MediaStoreUnavailable("staged_file_changed")
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(path, destination)
            directory_fd = os.open(root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return asset_id
        except OSError as exc:
            raise MediaStoreUnavailable("adoption_failed") from exc
