"""Model-agnostic contract between generation and the rest of Kaliv media.

ModelRig #2296, ownership split 6490545753: Claude owns generator adapters and
GPU admission; ChatGPT owns gallery persistence, the media store and routes.
This module is the seam. A generator produces a RenderedArtifact and hands
the bytes to an ArtifactSink; it never writes to disk, never knows where or
how an artifact is stored, and never exposes a route.

Nothing here imports torch, diffusers or a web framework.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable

TASKS = ("text_to_image", "image_to_image", "text_to_video", "image_to_video")

# MIME type -> file extension. A generator may only produce these.
ARTIFACT_TYPES: Mapping[str, str] = {"image/png": ".png", "video/mp4": ".mp4"}

MAX_ARTIFACT_BYTES = 512 * 1024 * 1024


class GenerationError(ValueError):
    """A request or artifact was refused. The message never contains a prompt."""


class ArtifactSinkUnavailable(RuntimeError):
    """The sink cannot accept artifacts (for example the external volume is gone).

    This is a fatal safety event for an executor: stop, do not fall back to
    another disk, and leave the job for recover_interrupted().
    """


@dataclass(frozen=True)
class GenerationRequest:
    profile_id: str
    task: str
    prompt: str
    width: int | None = None
    height: int | None = None
    steps: int | None = None
    seed: int | None = None
    input_asset_id: str | None = None
    frames: int | None = None
    extra: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RenderedArtifact:
    data: bytes
    mime_type: str

    def __post_init__(self) -> None:
        if type(self.data) is not bytes or not self.data or len(self.data) > MAX_ARTIFACT_BYTES:
            raise GenerationError("artifact data must be non-empty bytes within the size limit")
        if self.mime_type not in ARTIFACT_TYPES:
            raise GenerationError("unsupported artifact type")

    @property
    def extension(self) -> str:
        return ARTIFACT_TYPES[self.mime_type]


@runtime_checkable
class ArtifactSink(Protocol):
    """Implemented by the media store (ChatGPT, #2296 slice 1).

    publish() stores the bytes and returns an opaque asset id. It raises
    ArtifactSinkUnavailable when it cannot store safely.
    """

    def publish(self, data: bytes, extension: str) -> str: ...


@runtime_checkable
class GeneratorAdapter(Protocol):
    """One backend (diffusers, ComfyUI, ...) driven by a ModelProfile."""

    profile_id: str

    def load(self) -> None: ...

    def render(self, request: GenerationRequest) -> RenderedArtifact: ...

    def close(self) -> None: ...
