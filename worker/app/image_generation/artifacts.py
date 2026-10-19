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
        volume_marker: str | None = None,
    ):
        if not 1 <= max_bytes <= 32_000_000:
            raise ValueError("Invalid artifact size limit")
        if require_external_volume and external_volume is None:
            raise ValueError("External volume must be configured")
        if volume_marker is not None:
            if external_volume is None:
                raise ValueError("Volume marker requires an external volume")
            if not isinstance(volume_marker, str) or not 16 <= len(volume_marker) <= 128:
                raise ValueError("Invalid volume marker")
            marker_path = Path(external_volume) / ".modelrig-volume-id"
            if marker_path.is_symlink() or not marker_path.is_file():
                raise ValueError("External volume identity marker is missing")
            if marker_path.stat().st_size > 256:
                raise ValueError("External volume identity marker is oversized")
            if marker_path.read_text(encoding="utf-8").strip() != volume_marker:
                raise ValueError("External volume identity mismatch")
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


    def get_thumbnail_png(
        self, owner_id: str, artifact_id: str, *, max_edge: int = 320,
    ) -> bytes | None:
        """Produce a metadata-free bounded thumbnail; no local thumbnail cache."""
        if not 32 <= max_edge <= 512:
            raise ValueError("Invalid thumbnail dimension")
        source = self.get_png(owner_id, artifact_id)
        if source is None:
            return None
        # Decoder dependency is optional in V1 and fails closed when absent.
        try:
            from PIL import Image, ImageOps
        except ImportError as exc:
            raise RuntimeError("Image decoder is unavailable") from exc
        import io
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(source)) as original:
                original.load()
                if original.format != "PNG":
                    raise ValueError("Stored image is not PNG")
                image = ImageOps.exif_transpose(original)
                image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                image.convert("RGB").save(output, format="PNG")
                result = output.getvalue()
        if len(result) > self.max_bytes:
            raise ValueError("Thumbnail exceeds storage size limit")
        return result

    def list_png_ids(self, owner_id: str, *, limit: int = 100, offset: int = 0) -> list[str]:
        """List only this owner's private artifacts, newest filename first.

        No arbitrary filesystem paths, raw owner names or absolute locations
        are returned to the mobile/VR client.
        """
        if not 1 <= limit <= 200 or not 0 <= offset <= 10000:
            raise ValueError("Invalid gallery pagination")
        directory = self.root / self._owner_hash(owner_id)
        if directory.is_symlink() or not directory.is_dir():
            return []
        records: list[tuple[int, str]] = []
        for path in directory.iterdir():
            if path.is_symlink() or not path.is_file() or path.suffix != ".png":
                continue
            try:
                artifact_id = str(uuid.UUID(path.stem))
                if artifact_id != path.stem:
                    continue
                stat = path.stat()
                if not 0 < stat.st_size <= self.max_bytes:
                    continue
                records.append((stat.st_mtime_ns, artifact_id))
            except (OSError, ValueError):
                continue
        records.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [artifact_id for _, artifact_id in records[offset:offset + limit]]


def external_image_artifact_store(root: Path, *, external_volume: Path, volume_marker: str, max_bytes: int = 16_000_000) -> ImageArtifactStore:
    """Production-facing constructor: never permit local disk fallback."""
    return ImageArtifactStore(root, max_bytes=max_bytes, external_volume=external_volume, require_external_volume=True, volume_marker=volume_marker)
