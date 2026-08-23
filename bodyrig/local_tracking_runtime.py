"""Supported provenance-bound runtime for the BodyRig M1.1 local tracker.

``local_tracking.MediaPipePyAVTrackingBackend`` is the engine adapter. This
module is the supported ingestion boundary: it verifies exact installed runtime
versions and snapshots each configured model asset into private per-backend
storage before MediaPipe can open it. The stable tracking receipt therefore
binds the exact bytes the engine actually reads, not a mutable external path.
"""
from __future__ import annotations

import importlib.metadata
import os
from pathlib import Path
import shutil
import stat
import tempfile

from .local_tracking import (
    BACKEND_VERSION,
    LocalTrackingConfig,
    LocalTrackingRuntimeError,
    MediaPipePyAVTrackingBackend,
    _require_runtime,
)

EXPECTED_PYAV_VERSION = "18.1.0"
EXPECTED_MEDIAPIPE_VERSION = "1.0.1"


def _package_version(module: object, distribution: str) -> str:
    value = getattr(module, "__version__", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError as exc:
        raise LocalTrackingRuntimeError(
            f"cannot determine installed {distribution} version"
        ) from exc


def _stable_snapshot(source: Path, destination: Path, label: str) -> None:
    """Copy one exact regular file while proving its identity stayed stable."""
    try:
        before = os.lstat(source)
    except OSError as exc:
        raise LocalTrackingRuntimeError(
            f"{label} cannot be inspected: {type(exc).__name__}"
        ) from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise LocalTrackingRuntimeError(f"{label} must be a non-symlink regular file")

    try:
        with source.open("rb") as reader, destination.open("xb") as writer:
            opened_before = os.fstat(reader.fileno())
            if (opened_before.st_dev, opened_before.st_ino) != (before.st_dev, before.st_ino):
                raise LocalTrackingRuntimeError(f"{label} identity changed before snapshot")
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
            opened_after = os.fstat(reader.fileno())
    except LocalTrackingRuntimeError:
        raise
    except OSError as exc:
        raise LocalTrackingRuntimeError(
            f"{label} cannot be snapshotted: {type(exc).__name__}"
        ) from exc

    try:
        path_after = os.lstat(source)
    except OSError as exc:
        raise LocalTrackingRuntimeError(f"{label} disappeared during snapshot") from exc
    before_id = (opened_before.st_dev, opened_before.st_ino, opened_before.st_size, opened_before.st_mtime_ns)
    after_id = (opened_after.st_dev, opened_after.st_ino, opened_after.st_size, opened_after.st_mtime_ns)
    path_id = (path_after.st_dev, path_after.st_ino, path_after.st_size, path_after.st_mtime_ns)
    if before_id != after_id or after_id != path_id:
        raise LocalTrackingRuntimeError(f"{label} changed during snapshot")
    if destination.stat().st_size != opened_after.st_size:
        raise LocalTrackingRuntimeError(f"{label} snapshot size mismatch")
    try:
        destination.chmod(stat.S_IRUSR)
    except OSError:
        # Read-only permission is defense-in-depth. Exact byte revalidation below
        # remains the authority on platforms where chmod semantics differ.
        pass


class LocalTrackingBackend(MediaPipePyAVTrackingBackend):
    """Exact-version backend whose engine reads immutable per-job model snapshots."""

    def __init__(self, config: LocalTrackingConfig) -> None:
        av, mp = _require_runtime()
        av_version = _package_version(av, "av")
        mp_version = _package_version(mp, "mediapipe")
        if av_version != EXPECTED_PYAV_VERSION:
            raise LocalTrackingRuntimeError(
                f"PyAV version mismatch: expected {EXPECTED_PYAV_VERSION}, got {av_version}"
            )
        if mp_version != EXPECTED_MEDIAPIPE_VERSION:
            raise LocalTrackingRuntimeError(
                "MediaPipe version mismatch: expected "
                f"{EXPECTED_MEDIAPIPE_VERSION}, got {mp_version}"
            )

        original = config.validated()
        self._model_snapshot_dir = tempfile.TemporaryDirectory(prefix="bodyrig-models-")
        root = Path(self._model_snapshot_dir.name).resolve()
        pose = root / "pose.task"
        hand = root / "hand.task"
        face = root / "face.task"
        try:
            _stable_snapshot(Path(original.pose_model), pose, "pose model")
            _stable_snapshot(Path(original.hand_model), hand, "hand model")
            _stable_snapshot(Path(original.face_model), face, "face model")
            snapshot_config = LocalTrackingConfig(
                pose_model=pose,
                hand_model=hand,
                face_model=face,
                frame_stride=original.frame_stride,
                min_detection_confidence=original.min_detection_confidence,
                min_presence_confidence=original.min_presence_confidence,
                min_tracking_confidence=original.min_tracking_confidence,
                delegate=original.delegate,
            )
            super().__init__(snapshot_config)
        except BaseException:
            self._model_snapshot_dir.cleanup()
            raise

        # Instance identity is what bodyrig.tracking serializes into provenance.
        self.backend_version = (
            f"adapter={BACKEND_VERSION};pyav={av_version};mediapipe={mp_version}"
        )
        self._expected_model_revision = self.model_revision

    def _assert_model_assets(self) -> None:
        current = self.config.model_revision()
        if current != self._expected_model_revision:
            raise LocalTrackingRuntimeError(
                "private tracking model snapshot changed after backend construction"
            )

    def inspect(self, source_path: os.PathLike[str] | str):
        self._assert_model_assets()
        result = super().inspect(source_path)
        self._assert_model_assets()
        return result

    def extract(self, source_path: os.PathLike[str] | str):
        self._assert_model_assets()
        for frame in super().extract(source_path):
            yield frame
        self._assert_model_assets()

    def close(self) -> None:
        self._model_snapshot_dir.cleanup()

    def __enter__(self) -> "LocalTrackingBackend":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
