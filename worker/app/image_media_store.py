"""Fail-closed image asset storage on an explicitly mounted media volume."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid

_ASSET_ID = re.compile(r"^[0-9a-f]{32}$")
_ALLOWED = {".png", ".webp", ".jpg", ".jpeg"}


class MediaStorageError(RuntimeError):
    pass


class ExternalMediaStore:
    """Require a separate mounted filesystem selected by deployment.

    A mount point is not proof of a physically external disk. Deployment must
    additionally validate the actual backing device, especially on Windows/WSL.
    """

    def __init__(self, root: str, external_roots: list[str], *, min_free_bytes: int = 2 * 1024**3):
        if not root or not Path(root).is_absolute() or not external_roots:
            raise MediaStorageError("absolute media root and external roots required")
        candidate = Path(root)
        if candidate.is_symlink() or not candidate.is_dir():
            raise MediaStorageError("media root must be an existing real directory")
        self.root = candidate.resolve(strict=True)
        allowed = False
        self._mount = None
        for item in external_roots:
            p = Path(item)
            if not p.is_absolute() or p.is_symlink() or not p.is_dir():
                continue
            mounted = p.resolve(strict=True)
            if mounted == Path(mounted.anchor):
                continue
            if not os.path.ismount(mounted):
                continue
            if self.root == mounted or mounted in self.root.parents:
                allowed = True
                self._mount = mounted
                break
        if not allowed:
            raise MediaStorageError("media root is not on a configured mounted volume")
        if min_free_bytes < 0:
            raise ValueError("min_free_bytes must be nonnegative")
        self.min_free_bytes = min_free_bytes
        self._check_free()

    def _check_mount(self) -> None:
        # Recheck every access: an unplugged disk must never cause writes to
        # the now-exposed directory on the system filesystem.
        if (self._mount is None or not os.path.ismount(self._mount)
                or not self.root.is_dir()
                or self.root.is_symlink()
                or self._mount not in (self.root, *self.root.parents)):
            raise MediaStorageError("external media mount is unavailable")
        if self.root.stat().st_dev != self._mount.stat().st_dev:
            raise MediaStorageError("media root no longer belongs to external mount")

    def _check_free(self) -> None:
        self._check_mount()
        if shutil.disk_usage(self.root).free < self.min_free_bytes:
            raise MediaStorageError("media volume below free-space floor")

    def publish(self, data: bytes, extension: str = ".png") -> dict[str, str | int]:
        if extension not in _ALLOWED or not data:
            raise MediaStorageError("invalid media payload or extension")
        self._check_free()
        asset_id = uuid.uuid4().hex
        final = self.root / (asset_id + extension)
        self._check_mount()
        fd, temp_path = tempfile.mkstemp(prefix=".media-", suffix=".part", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            self._check_free()
            os.replace(temp_path, final)
            return {"asset_id": asset_id, "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data), "extension": extension}
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def resolve(self, asset_id: str, extension: str) -> Path:
        if not _ASSET_ID.fullmatch(asset_id) or extension not in _ALLOWED:
            raise MediaStorageError("invalid asset identifier")
        self._check_mount()
        path = self.root / (asset_id + extension)
        if path.is_symlink() or not path.is_file() or path.resolve().parent != self.root:
            raise MediaStorageError("asset not found or unsafe")
        return path
