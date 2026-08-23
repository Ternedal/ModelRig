from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .models import BodyCue, SpeechTiming
from .package import MRBodyError, install_package, validate_package
from .runtime import BodyRuntime

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8775
runtime = BodyRuntime()

app = FastAPI(title="BodyRig", version=__version__)


def body_library() -> Path:
    root = os.environ.get("BODYRIG_DATA_DIR")
    if root:
        return Path(root).expanduser().resolve() / "bodies"
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / ".local" / "share"
    return base / "BodyRig" / "bodies"


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=4096)


@app.get("/api/v1/health")
def health() -> dict:
    return {"ok": True, "service": "bodyrig", "version": __version__}


@app.get("/api/v1/bodies")
def list_bodies() -> dict:
    library = body_library()
    bodies = []
    if library.exists():
        for path in sorted(library.glob("*.mrbody")):
            try:
                validated = validate_package(path)
            except MRBodyError:
                continue
            bodies.append({
                "id": validated.manifest["id"],
                "name": validated.manifest["name"],
                "path": str(path),
            })
    return {"bodies": bodies, "active_body_id": runtime.snapshot().active_body_id}


@app.post("/api/v1/bodies/import")
def import_body(request: ImportRequest) -> dict:
    try:
        target = install_package(request.path, body_library())
        validated = validate_package(target)
    except (MRBodyError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"installed": True, "id": validated.manifest["id"], "path": str(target)}


@app.post("/api/v1/bodies/{body_id}/activate")
def activate_body(body_id: str) -> dict:
    library = body_library()
    candidate = library / f"{body_id}.mrbody"
    try:
        validated = validate_package(candidate)
    except (MRBodyError, OSError) as exc:
        raise HTTPException(status_code=404, detail="body not found or invalid") from exc
    state = runtime.activate(validated.manifest["id"])
    return state.__dict__


@app.post("/api/v1/runtime/cue")
def apply_cue(cue: BodyCue) -> dict:
    state = runtime.apply_cue(cue)
    return state.__dict__


@app.post("/api/v1/runtime/speech-timing")
def apply_speech_timing(timing: SpeechTiming) -> dict:
    try:
        state = runtime.apply_speech(timing)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return state.__dict__


@app.get("/api/v1/runtime/state")
def runtime_state() -> dict:
    return runtime.snapshot().__dict__


def run() -> None:
    import uvicorn

    host = os.environ.get("BODYRIG_HOST", DEFAULT_HOST)
    if host not in {"127.0.0.1", "localhost", "::1"} and os.environ.get("BODYRIG_ALLOW_REMOTE") != "1":
        raise SystemExit("BodyRig refuses non-loopback bind unless BODYRIG_ALLOW_REMOTE=1")
    port = int(os.environ.get("BODYRIG_PORT", str(DEFAULT_PORT)))
    uvicorn.run("bodyrig.app:app", host=host, port=port, reload=False)
