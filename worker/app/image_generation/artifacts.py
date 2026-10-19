"""Private, owner-scoped artifact store for opt-in image jobs.

Store only already-decoded/re-encoded trusted PNG bytes. This module does not
sanitize untrusted image bytes and must not be mounted as a public file server.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from .storage_policy import require_external_media_root
from pathlib import Path


class ImageArtifactStore:
    def __init__(
        self, root: Path, *, max_bytes: int = 16_000_000,
        external_volume: Path | None = None,
        require_external_volume: bool = False,
    ):
        if not 1 <= max_bytes <= 32_000_000:
            raise ValueError("Invalid artifact size limit")
        if require_external_volume and external_volume is None:
            raise ValueError("External volume must be configured")
        if external_volume is not None:
            root = require_external_media_root(root, mounted_volume=external_volume)
        supplied_root = Path(root).absolute()
        if supplied_root.is_symlink():
            raise ValueError("Artifact root cannot be a symlink")
        self.root = supplied_root.resolve()
        self.max_bytes = max_bytes
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    @staticmethod
    def _owner_hash(owner_id: str) -> str:
        if not isinstance(owner_id, str) or not 1 <= len(owner_id) <= 128:
            raise ValueError("Invalid owner")
        return hashlib.sha256(owner_id.encode("utf-8")).hexdigest()

    def put_png(self, owner_id: str, data: bytes) -> str:
        if not isinstance(data, bytes) or not 1 <= len(data) <= self.max_bytes:
            raise ValueError("Invalid artifact payload")
        # Only call this after a full trusted image decode and re-encode.
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("PNG payload required")
        directory = self.root / self._owner_hash(owner_id)
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.is_symlink():
            raise ValueError("Artifact owner directory cannot be a symlink")
        artifact_id = str(uuid.uuid4())
        fd, temp_name = tempfile.mkstemp(prefix=".upload-", dir=directory)
        try:
            with os.fdopen(fd, "wb") as handle:
                os.chmod(temp_name, 0o600)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, directory / (artifact_id + ".png"))
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return artifact_id

    def get_png(self, owner_id: str, artifact_id: str) -> bytes | None:
        try:
            safe_id = str(uuid.UUID(artifact_id))
        except (ValueError, TypeError, AttributeError):
            return None
        directory = self.root / self._owner_hash(owner_id)
        if directory.is_symlink():
            return None
        path = directory / (safe_id + ".png")
        try:
            if path.is_symlink():
                return None
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags)
            with os.fdopen(fd, "rb") as handle:
                payload = handle.read(self.max_bytes + 1)
        except (FileNotFoundError, IsADirectoryError):
            return None
        if len(payload) > self.max_bytes:
            raise ValueError("Stored artifact exceeds size limit")
        return payload
