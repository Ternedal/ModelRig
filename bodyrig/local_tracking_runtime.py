"""Supported provenance-bound runtime for the BodyRig M1.1 local tracker.

``local_tracking.MediaPipePyAVTrackingBackend`` is the engine adapter. This
module is the supported ingestion boundary: it verifies exact installed runtime
versions and revalidates the configured model assets around every operation so
the stable tracking receipt cannot claim one engine/model identity while using
another.
"""
from __future__ import annotations

import importlib.metadata
import os

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


class LocalTrackingBackend(MediaPipePyAVTrackingBackend):
    """Exact-version, model-immutable supported M1.1 local backend."""

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
        super().__init__(config)
        # Instance identity is what bodyrig.tracking serializes into provenance.
        self.backend_version = (
            f"adapter={BACKEND_VERSION};pyav={av_version};mediapipe={mp_version}"
        )
        self._expected_model_revision = self.model_revision

    def _assert_model_assets(self) -> None:
        current = self.config.model_revision()
        if current != self._expected_model_revision:
            raise LocalTrackingRuntimeError(
                "tracking model assets changed after backend construction"
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
