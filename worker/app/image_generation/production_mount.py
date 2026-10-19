"""Explicit, fail-closed integration boundary for experimental image routes.

Production callers must provide trusted identity resolution and a configured
service. Importing this module never exposes endpoints.
"""
from __future__ import annotations

from collections.abc import Callable
from fastapi import FastAPI

from .api import build_image_router
from .artifacts import ImageArtifactStore
from .service import ImageGenerationService


def mount_experimental_images(
    app: FastAPI,
    *,
    enabled: bool = False,
    authenticated_owner: Callable | None = None,
    service: ImageGenerationService | None = None,
    artifact_store: ImageArtifactStore | None = None,
) -> bool:
    """Mount only after the operator explicitly opts in and supplies all guards.

    The caller owns the authentication dependency and must ensure it validates
    credentials server-side; a client-provided owner string is never sufficient.
    No automatic mount, localhost bypass or internal-disk fallback is allowed.
    """
    if not enabled:
        return False
    if not callable(authenticated_owner):
        raise RuntimeError("Experimental image API requires trusted authentication")
    if not isinstance(service, ImageGenerationService):
        raise RuntimeError("Experimental image API requires a configured service")
    if not isinstance(artifact_store, ImageArtifactStore):
        raise RuntimeError("Experimental image API requires an external artifact store")
    if (not artifact_store._require_external_volume
            or artifact_store._external_volume is None
            or artifact_store._volume_marker is None):
        raise RuntimeError("Experimental image API requires a marked external volume")
    artifact_store._assert_volume_available()
    app.include_router(build_image_router(
        service, authenticated_owner=authenticated_owner, artifact_store=artifact_store
    ))
    return True
