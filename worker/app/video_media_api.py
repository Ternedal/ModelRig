"""Default-off loopback-only media gallery API for operator testing.

This is NOT a remote-app authorization solution. LAN/Android/Quest exposure
requires integration with the worker's existing authenticated client mechanism.
"""
from __future__ import annotations

import ipaddress
import os
import stat

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, Response

from .video_media_catalog import MediaCatalog
from .video_media_client_projection import gallery_item_for_client
from .video_media_stream import iter_open_media_bytes, media_response_plan
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
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise HTTPException(400, "Invalid pagination")
        try:
            items = catalog().list_items(limit=limit, offset=offset)
        except (ValueError, OSError):
            raise HTTPException(503, "Media catalog unavailable")
        try:
            projected = [gallery_item_for_client(item, url_prefix="/experimental/media") for item in items]
        except (ValueError, KeyError, TypeError):
            raise HTTPException(503, "Media catalog unavailable")
        return {"schema": "kaliv-media-gallery/v1", "items": projected, "limit": limit, "offset": offset}

    @router.api_route("/{media_id}", methods=["GET", "HEAD"])
    def media(request: Request, media_id: str):
        operator_only(request)
        try:
            resolved = catalog().resolve(media_id)
        except ValueError:
            raise HTTPException(404, "Unknown media")
        except OSError:
            raise HTTPException(503, "Media catalog unavailable")
        if resolved is None:
            raise HTTPException(404, "Unknown media")
        path, metadata = resolved
        source = None
        try:
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags)
            try:
                source = os.fdopen(fd, "rb")
            except BaseException:
                os.close(fd)
                raise
            file_info = os.fstat(source.fileno())
            if not stat.S_ISREG(file_info.st_mode):
                raise ValueError("Media is not a regular file")
            status, headers, start, length = media_response_plan(
                size=file_info.st_size, mime_type=metadata["mime_type"],
                range_header=request.headers.get("range"), method=request.method
            )
        except OSError:
            if source is not None:
                source.close()
            raise HTTPException(503, "External media storage unavailable")
        except (ValueError, KeyError):
            if source is not None:
                source.close()
            raise HTTPException(404, "Media unavailable")
        if request.method == "HEAD" or status == 416:
            source.close()
            return Response(status_code=status, headers=headers)
        return StreamingResponse(
            iter_open_media_bytes(source, start, length), status_code=status, headers=headers
        )

    return router


def mount_media_operator_api(app) -> None:
    if os.getenv("KALIV_EXPERIMENTAL_MEDIA_OPERATOR_API", "0") == "1":
        app.include_router(build_media_router())
