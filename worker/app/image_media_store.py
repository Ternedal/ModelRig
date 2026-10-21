"""Fail-closed external-media storage for future image-generation jobs.

This module deliberately does not expose HTTP routes or start model inference.
It is safe to import without an external drive attached.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import tempfile
import uuid

_ASSET_ID = re.compile(r"^[0-9a-f]{32}$")
_ALLOWED = {".png", ".webp", ".jpg", ".jpeg"}


class MediaStorageError(RuntimeError):
    pass


def _real(path: Path) -> Path:
    return path.resolve(strict=True)


class ExternalMediaStore:
    """Storage gate: caller supplies explicit external volume roots.

    external_roots must be configured by deployment, not by the client.
    Never infer an external drive from the presence of a writable directory.
    """

    def __init__(self, root: str, external_roots: list[str], *, min_free_bytes: int = 2 * 1024**3):
        if not root or not Path(root).is_absolute() or not external_roots:
            raise MediaStorageError("explicit absolute media root and external roots required")
        candidate = Path(root)
        if candidate.is_symlink() or not candidate.is_dir():
            raise MediaStorageError("media root must be an existing real directory")
        self.root = _real(candidate)
        permitted = []
        for item in external_roots:
            p = Path(item)
            if not p.is_absolute() or p.is_symlink() or not p.is_dir():
                continue
            permitted.append(_real(p))
        if not any(self.root == p or p in self.root.parents for p in permitted):
            raise MediaStorageError("media root is outside configured external volumes")
        if min_free_bytes < 0:
            raise ValueError("min_free_bytes must be nonnegative")
        self.min_free_bytes = min_free_bytes
        self._check_free()

    def _check_free(self) -> None:
        import shutil
        if shutil.disk_usage(self.root).free < self.min_free_bytes:
            raise MediaStorageError("external media volume below free-space floor")

    def publish(self, data: bytes, extension: str = ".png") -> dict[str, str | int]:
        if extension not in _ALLOWED or not data:
            raise MediaStorageError("invalid media payload or extension")
        self._check_free()
        asset_id = uuid.uuid4().hex
        final = self.root / (asset_id + extension)
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
        path = self.root / (asset_id + extension)
        if path.is_symlink() or not path.is_file() or path.resolve().parent != self.root:
            raise MediaStorageError("asset not found or unsafe")
        return path
