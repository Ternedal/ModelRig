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

    def inspect_temporary_files(self) -> list[str]:
        """List potential abandoned writer files without deleting anything."""
        import stat
        root = self._root()
        candidates = []
        import re
        for entry in root.iterdir():
            # Only our tempfile naming convention, not arbitrary similarly named files.
            if not re.fullmatch(r"[.]kaliv-[A-Za-z0-9_-]{8,}[.]tmp", entry.name):
                continue
            if entry.is_symlink():
                continue
            try:
                info = entry.lstat()
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode):
                candidates.append(entry.name)
        self._root()
        return sorted(candidates)

    def publish_and_register_for_job(self, job_key: str, data: bytes, extension: str) -> str:
        """Publish then register, retrying safely after interrupted registration.

        The caller must retain the original bytes for retries. A crash after
        publication leaves an unindexed asset that this method can adopt.
        """
        from .media_gallery_index_writer import register_asset
        asset_id = self.publish_for_job(job_key, data, extension)
        register_asset(self.media_root, self.volume_root, asset_id, extension, len(data))
        return asset_id

    def publish_for_job(self, job_key: str, data: bytes, extension: str) -> str:
        """Idempotent publication with a deterministic, opaque asset ID.

        A repeated job can reuse its exact bytes, but cannot overwrite a
        different artifact. The caller must still reconcile the gallery index.
        """
        import hashlib
        import hmac
        import re
        if not isinstance(job_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_key):
            raise ValueError("invalid_job_key")
        if type(data) is not bytes or not data or len(data) > MAX_ARTIFACT_BYTES:
            raise ValueError("invalid_artifact_bytes")
        if extension not in _EXTENSIONS:
            raise ValueError("invalid_artifact_extension")
        asset_id = hashlib.sha256(("kaliv-media-job-v1:" + job_key).encode("utf-8")).hexdigest()[:32]
        root = self._root()
        destination = root / (asset_id + extension)
        # A job key identifies one artifact, regardless of media type.
        # Reject an existing sibling extension before treating a retry as new.
        for other_extension in _EXTENSIONS - {extension}:
            sibling = root / (asset_id + other_extension)
            if sibling.exists() or sibling.is_symlink():
                raise ArtifactSinkUnavailable("asset_job_conflict")
        # A retry is only successful if the complete existing artifact matches.
        # Never follow links and never replace an existing destination.
        def matches() -> bool:
            import stat
            if destination.is_symlink():
                return False
            try:
                fd = os.open(destination, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
            except FileNotFoundError:
                return False
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_size != len(data):
                    return False
                digest = hashlib.sha256()
                while True:
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                return hmac.compare_digest(digest.digest(), hashlib.sha256(data).digest())
            finally:
                os.close(fd)
        if destination.exists() or destination.is_symlink():
            if matches():
                return asset_id
            raise ArtifactSinkUnavailable("asset_job_conflict")
        temporary = None
        try:
            self._root()
            with tempfile.NamedTemporaryFile(mode="wb", prefix=".kaliv-", suffix=".tmp",
                                             dir=root, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            self._root()
            try:
                os.link(temporary, destination, follow_symlinks=False)
            except FileExistsError:
                if not matches():
                    raise ArtifactSinkUnavailable("asset_job_conflict")
            return asset_id
        except OSError as exc:
            raise ArtifactSinkUnavailable("external_media_write_failed") from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

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
            # A check-then-replace sequence can overwrite an existing asset if
            # another writer wins the race. Hard-link creation is atomic and
            # fails if the destination already exists, including on NTFS.
            try:
                os.link(temp_name, destination, follow_symlinks=False)
            except FileExistsError as exc:
                raise ArtifactSinkUnavailable("asset_collision") from exc
            try:
                temp_name.unlink()
            except OSError:
                # The asset is already durably linked; a leftover temporary
                # name is a cleanup issue, not a failed publication.
                pass
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
