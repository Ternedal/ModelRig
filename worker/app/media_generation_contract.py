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
from typing import BinaryIO, ContextManager, Mapping, Protocol, runtime_checkable

TASKS = ("text_to_image", "image_to_image", "text_to_video", "image_to_video")

# MIME type -> file extension. A generator may only produce these.
ARTIFACT_TYPES: Mapping[str, str] = {"image/png": ".png", "video/mp4": ".mp4"}

MAX_ARTIFACT_BYTES = 512 * 1024 * 1024

MAX_FILE_NAME = 255  # characters; no NTFS or ext4 file name is longer


def is_plain_file_name(name: object) -> bool:
    """A file name directly inside one directory. This one rule is used wherever such a name is
    accepted: the video adapter's output and the hand-off receipt that records it, so a render the
    adapter accepts is never lost to a receipt that refuses its name (Codex #2357 4504060850).

    A str of 1-255 characters, not "." or "..", with no path separator, no drive colon, no
    control character and no unpaired surrogate (which SQLite cannot store). Spaces and any
    other Unicode are fine: a workflow may name its output "rød drage.mp4"."""
    return (type(name) is str and 0 < len(name) <= MAX_FILE_NAME and name not in (".", "..")
            and not any(c in "/\\:" or ord(c) < 0x20 or 0x7f <= ord(c) <= 0x9f or 0xd800 <= ord(c) <= 0xdfff
                        for c in name))


class GenerationError(ValueError):
    """A request or artifact was refused. The message never contains a prompt."""


class SourceImageUnavailable(GenerationError):
    """The source image is absent, invalid or not authorized for this job."""


class GenerationCancelled(GenerationError):
    """The job's owner cancelled it while it was rendering; nothing is published."""


class ArtifactSinkUnavailable(RuntimeError):
    """The sink cannot accept artifacts (for example the external volume is gone).

    This is a fatal safety event for an executor: stop, do not fall back to
    another disk, and leave the job for recovery (recover_gpu() at the next start).
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
class StagedFileArtifactSink(Protocol):
    """Optional sink for artifacts too large for bytes (video). ChatGPT implements it (#2296 6494148463).

    Use, and only this way:

        with sink.staged(".mp4") as output:          # an exclusive new file on the verified volume
            mime = adapter.render_to(request, output)  # the adapter only writes into the handle
            asset_id = sink.adopt(output, mime)        # inside the context: promote + register

    Required by the seam (tests/support/staged_sink_conformance.py checks them):
    - staged() hands out a writable binary handle; the generator never sees a path.
    - The handle may offer sync(): fsync of what was written, without a path or
      descriptor. A generator that removes its own copy of the media (the work
      area on the internal disk; Anders, 6 Nov 2026) calls it first, so the copy
      is durable on the volume before its source goes.
    - adopt() accepts only a live handle this sink issued, only "video/mp4",
      only within the size bound, flushes/fsyncs and atomically promotes it,
      and returns an asset id only after durable registration.
    - adopt() twice, or with a foreign or closed handle, is refused.
    - Leaving the context after adopt() keeps the asset; leaving it without
      adopt() (or on any error) publishes nothing and removes the staged file.
    - No publish(bytes) fallback for video. Raise ArtifactSinkUnavailable when
      the verified volume is not there.
    """

    def staged(self, extension: str) -> ContextManager[BinaryIO]: ...

    def adopt(self, handle: BinaryIO, mime_type: str) -> str: ...


@runtime_checkable
class JobKeyedArtifactSink(Protocol):
    """Optional capability: publication keyed by the job id (ExternalMediaSink, #2313).

    The asset id is derived from job_key, so a retry after an interrupted completion
    finds the same asset and reconciliation can correlate job and artifact. Generators
    use it whenever a sink offers it, and fall back to publish() otherwise.
    """

    def publish_and_register_for_job(self, job_key: str, data: bytes, extension: str) -> str: ...


@runtime_checkable
class JobKeyedStagedSink(Protocol):
    """Optional capability for staged video: adopt keyed by the job id (proposed, #2318 6633945476)."""

    def adopt_for_job(self, handle: BinaryIO, mime_type: str, job_key: str) -> str: ...


@runtime_checkable
class VerifiedMediaVolume(Protocol):
    """The external-media mount check (#2316 review 5700997784; production: media_volume, G1).

    require(path) returns only if path lies on the verified, currently mounted
    external media volume, and raises ArtifactSinkUnavailable otherwise. This is
    where media is PUBLISHED: the gallery and every staged file. Generation
    happens in the MediaWorkArea below (Anders, 6 Nov 2026, #2275).
    """

    def require(self, path: str) -> None: ...


@runtime_checkable
class MediaWorkArea(Protocol):
    """Where media is GENERATED: a private folder on the internal disk (Anders, 6 Nov 2026, #2275).

    require(path) returns only if path lies in the verified private work area,
    and raises ArtifactSinkUnavailable otherwise. ComfyUI's input/output/temp/user
    folders and the staged source image must pass it. Finished media leaves it
    only by being copied into a staged file on the VerifiedMediaVolume, checked
    and published there in one atomic step; then the copy here is removed.
    Production: media_work_area.PrivateWorkArea.
    """

    def require(self, path: str) -> None: ...


@runtime_checkable
class GeneratorAdapter(Protocol):
    """One backend (diffusers, ComfyUI, ...) driven by a ModelProfile."""

    profile_id: str

    def load(self) -> None: ...

    def render(self, request: GenerationRequest) -> RenderedArtifact: ...

    def close(self) -> bool:
        """Unload. True once the GPU lease is released; False while GPU memory is not proven free
        (the lease is then kept, so no cooperating executor can take the GPU)."""
        ...
