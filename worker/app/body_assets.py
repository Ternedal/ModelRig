"""Slice A of the Unity renderer roadmap: serve the active body's assets.

Phones and headsets cannot read the rig's file system, so the data-only
renderer handoff (MRBodyRuntimeBinding: validated avatar.vrm, thumbnail,
motions) is exposed over HTTP. Which body: the selected person's body
revision (#752) when it names an installed bodyid, otherwise the profile
store's current M2.7 selection. Both go through BodyRig's own validated
paths -- the store re-validates the archive on every load, and every
member served is checked against the inspection's sha256 once more.

Nothing here interprets the body. The worker forwards bytes and a
manifest; meaning stays in the renderer and in core's render-frame wire.
"""

from __future__ import annotations

import hashlib
import os
import sys
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, Response

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bodyrig.mrbody import OPTIONAL_MOTION_PATHS  # noqa: E402
from bodyrig.profile_selection import (  # noqa: E402
    MRBodyCurrentProfileError,
    MRBodyCurrentProfileStore,
)
from bodyrig.profile_store import (  # noqa: E402
    MRBodyProfileNotFoundError,
    MRBodyProfileStore,
    MRBodyProfileStoreError,
    MRBodyStoredProfile,
)

BODY_STORE_ENV = "KALIV_BODY_STORE"
VRM_MEDIA_TYPE = "model/gltf-binary"
VRMA_MEDIA_TYPE = "model/gltf-binary"


def store_root() -> str | None:
    return os.environ.get(BODY_STORE_ENV) or None


class ActiveBody:
    """One validated body, resolved once per request."""

    def __init__(self, body_id: str, stored: MRBodyStoredProfile, source: str):
        self.body_id = body_id
        self.stored = stored
        self.source = source  # "person" | "current"

    @property
    def present(self) -> set[str]:
        return {path for path, _ in self.stored.inspection.payload_sizes}

    def member(self, path: str) -> bytes:
        if path not in self.present:
            raise KeyError(path)
        with zipfile.ZipFile(BytesIO(self.stored.archive_bytes), "r") as archive:
            data = archive.read(path)
        expected = self.stored.inspection.checksums.get(path)
        if expected and hashlib.sha256(data).hexdigest() != expected.split(":")[-1]:
            raise RuntimeError(f"validated member {path} changed underneath the store")
        return data

    def manifest(self) -> dict[str, Any]:
        present = self.present
        motions = [
            p.removeprefix("motions/").removesuffix(".vrma")
            for p in OPTIONAL_MOTION_PATHS if p in present
        ]
        return {
            "schema": "modelrig-body-assets/v1",
            "body_id": self.body_id,
            "name": self.stored.inspection.name,
            "package_sha256": self.stored.receipt.package_sha256,
            "source": self.source,
            "avatar": "/body/active/avatar.vrm",
            "thumbnail": "/body/active/thumbnail.png",
            "motions": {m: f"/body/active/motions/{m}.vrma" for m in motions},
            "payload_sizes": dict(self.stored.inspection.payload_sizes),
        }


def _person_body_id() -> str | None:
    """The selected person's body source when it names an installed body."""
    try:
        from . import person_runtime
        bindings = person_runtime.active_person()
    except Exception:
        return None
    if bindings is None:
        return None
    source = str(bindings["body"].get("source_id", "")).strip()
    return source if source.startswith("bodyid-") else None


def resolve_active_body() -> ActiveBody:
    root = store_root()
    if root is None:
        raise HTTPException(status_code=503, detail=f"{BODY_STORE_ENV} is not configured")
    store = MRBodyProfileStore(Path(root))
    person_body = _person_body_id()
    if person_body is not None:
        try:
            return ActiveBody(person_body, store.load(person_body), "person")
        except MRBodyProfileNotFoundError:
            raise HTTPException(
                status_code=409,
                detail=f"selected person names {person_body}, which is not installed in the body store",
            )
        except MRBodyProfileStoreError as exc:
            raise HTTPException(status_code=502, detail=f"body store: {exc}")
    try:
        current = MRBodyCurrentProfileStore(store).load_current()
    except MRBodyCurrentProfileError as exc:
        raise HTTPException(status_code=404, detail=f"no current body selected: {exc}")
    except MRBodyProfileStoreError as exc:
        raise HTTPException(status_code=502, detail=f"body store: {exc}")
    return ActiveBody(current.marker.body_id, current.stored, "current")


def build_body_router() -> APIRouter:
    router = APIRouter(prefix="/body", tags=["body"])

    @router.get("/active")
    def active() -> JSONResponse:
        return JSONResponse(resolve_active_body().manifest())

    @router.get("/active/avatar.vrm")
    def avatar() -> Response:
        body = resolve_active_body()
        data = body.member("avatar.vrm")
        return Response(data, media_type=VRM_MEDIA_TYPE, headers=_asset_headers(body, "avatar.vrm"))

    @router.get("/active/thumbnail.png")
    def thumbnail() -> Response:
        body = resolve_active_body()
        data = body.member("thumbnail.png")
        return Response(data, media_type="image/png", headers=_asset_headers(body, "thumbnail.png"))

    @router.get("/active/motions/{name}.vrma")
    def motion(name: str) -> Response:
        path = f"motions/{name}.vrma"
        if path not in OPTIONAL_MOTION_PATHS:
            raise HTTPException(status_code=404, detail="unknown motion")
        body = resolve_active_body()
        try:
            data = body.member(path)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"body has no {name} motion")
        return Response(data, media_type=VRMA_MEDIA_TYPE, headers=_asset_headers(body, path))

    return router


def _asset_headers(body: ActiveBody, path: str) -> dict[str, str]:
    checksum = body.stored.inspection.checksums.get(path, "")
    return {
        "X-BodyRig-Body-ID": body.body_id,
        "X-BodyRig-Package-SHA256": body.stored.receipt.package_sha256,
        "X-BodyRig-Member-SHA256": checksum.split(":")[-1] if checksum else "",
        "Cache-Control": "no-store",
    }
