"""Default-off loopback-only media gallery API for operator testing.

This is NOT a remote-app authorization solution. LAN/Android/Quest exposure
requires integration with the worker's existing authenticated client mechanism.
"""
from __future__ import annotations

import ipaddress
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, Response

from .video_media_catalog import MediaCatalog
from .video_media_stream import iter_media_bytes, media_response_plan
from .video_storage import MediaStorageUnavailable


def build_media_router() -> APIRouter:
    router = APIRouter(prefix="/experimental/media", tags=["experimental-media"])

    def operator_only(request: Request) -> None:
        host = request.client.host if request.client else ""
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            raise HTTPException(403, "Local operator only")
        if not address.is_loopback:
            raise HTTPException(403, "Local operator only")

    def catalog() -> MediaCatalog:
        try:
            return MediaCatalog.on_external_volume()
        except (OSError, ValueError, MediaStorageUnavailable):
            raise HTTPException(503, "External media storage unavailable")

    @router.get("")
    def gallery(request: Request, limit: int = 50, offset: int = 0):
        operator_only(request)
        try:
            items = catalog().list_items(limit=limit, offset=offset)
        except ValueError:
            raise HTTPException(400, "Invalid pagination")
        return {"schema": "kaliv-media-gallery/v1", "items": items, "limit": limit, "offset": offset}

    @router.api_route("/{media_id}", methods=["GET", "HEAD"])
    def media(request: Request, media_id: str):
        operator_only(request)
        try:
            resolved = catalog().resolve(media_id)
        except ValueError:
            raise HTTPException(404, "Unknown media")
        if resolved is None:
            raise HTTPException(404, "Unknown media")
        path, metadata = resolved
        try:
            size = path.stat().st_size
            status, headers, start, length = media_response_plan(
                size=size, mime_type=metadata["mime_type"],
                range_header=request.headers.get("range"), method=request.method
            )
        except (OSError, ValueError, KeyError):
            raise HTTPException(404, "Media unavailable")
        if request.method == "HEAD" or status == 416:
            return Response(status_code=status, headers=headers)
        return StreamingResponse(
            iter_media_bytes(path, start, length), status_code=status, headers=headers
        )

    return router


def mount_media_operator_api(app) -> None:
    if os.getenv("KALIV_EXPERIMENTAL_MEDIA_OPERATOR_API", "0") == "1":
        app.include_router(build_media_router())
