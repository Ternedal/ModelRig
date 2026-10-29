"""Default-off external-volume artifact sink shared with the gallery.

The operator supplies a trusted mounted volume and an existing media directory.
Never create a missing root on an internal disk. No network or HTTP routes.
"""
from __future__ import annotations

import os
import secrets
import tempfile
from pathlib import Path

from .media_generation_contract import ArtifactSinkUnavailable, MAX_ARTIFACT_BYTES

_EXTENSIONS = {".png", ".mp4"}


class ExternalMediaSink:
    def __init__(self, media_root: str | Path, verified_volume_root: str | Path):
        self.media_root = Path(media_root)
        self.volume_root = Path(verified_volume_root)

    def _root(self) -> Path:
        from .media_gallery_catalog import GalleryUnavailable, _root
        try:
            return _root(self.media_root, verified_volume_root=self.volume_root)
        except (GalleryUnavailable, OSError, RuntimeError) as exc:
            raise ArtifactSinkUnavailable("external_media_unavailable") from exc

    def publish(self, data: bytes, extension: str) -> str:
        if type(data) is not bytes or not data or len(data) > MAX_ARTIFACT_BYTES:
            raise ValueError("invalid_artifact_bytes")
        if extension not in _EXTENSIONS:
            raise ValueError("invalid_artifact_extension")
        root = self._root()
        asset_id = secrets.token_hex(16)
        destination = root / (asset_id + extension)
        temp_name = None
        try:
            # Recheck mount immediately before writing; never fall back.
            self._root()
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=".kaliv-", suffix=".tmp", dir=root, delete=False
            ) as handle:
                temp_name = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            self._root()
            if destination.exists() or destination.is_symlink():
                raise ArtifactSinkUnavailable("asset_collision")
            os.replace(temp_name, destination)
            temp_name = None
            return asset_id
        except OSError as exc:
            raise ArtifactSinkUnavailable("external_media_write_failed") from exc
        finally:
            if temp_name is not None:
                try:
                    temp_name.unlink(missing_ok=True)
                except OSError:
                    pass
