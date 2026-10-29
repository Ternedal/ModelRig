"""Text-to-video through one supervised ComfyUI (ModelRig #2296 slice 2, design 6493077060).

Default-off and not wired anywhere. The adapter never opens a socket itself
(HTTP lives in comfy_supervisor), never chooses where an artifact is stored
and never writes outside the file object the sink hands it.

load():   verify the pinned template (SHA-256 over the exact bytes that are
          parsed), then start the supervisor (GPU lease for ComfyUI's life).
render_to(request, sink_file):
          VRAM re-check -> empty queue (single tenant) -> bind slot values
          -> submit -> poll history with the profile deadline (interrupt on
          timeout) -> exactly one MP4 in the ComfyUI output dir, validated
          (no symlinks, unchanged over a settle window before the copy and
          during it, ftyp header, size cap) -> copied into sink_file ->
          ComfyUI's copy removed.
close():  stop the supervisor.

image_to_video needs input-asset retrieval (ChatGPT's asset service) and is
not supported here.
"""
from __future__ import annotations

import os
import stat
import time
from pathlib import Path
from typing import BinaryIO

from .comfy_supervisor import ComfyBusy, ComfySupervisor, ComfySupervisorError
from .comfy_workflow_template import MAX_TEMPLATE_BYTES, WorkflowTemplate, load_template
from .media_generation_contract import GenerationError, GenerationRequest, RenderedArtifact
from .media_generation_profiles import ModelProfile, validate_request

MIME = "video/mp4"
COPY_CHUNK = 1024 * 1024


class ComfyVideoAdapter:
    def __init__(self, profile: ModelProfile, *, supervisor: ComfySupervisor, template_dir: str,
                 output_directory: str, poll_s: float = 1.0, settle_s: float = 0.5,
                 settle_rounds: int = 10):
        if profile.backend != "comfyui" or profile.backend_options is None:
            raise GenerationError("ComfyVideoAdapter needs a comfyui profile")
        if supervisor.port != profile.backend_options.port:
            raise GenerationError("supervisor port does not match the profile")
        if Path(output_directory) != Path(supervisor.launch.output_directory):
            raise GenerationError("output directory must be the one ComfyUI writes to")
        if type(poll_s) not in (int, float) or not 0.01 <= poll_s <= 10:
            raise GenerationError("poll interval must be 0.01..10 seconds")
        if type(settle_s) not in (int, float) or not 0.01 <= settle_s <= 10:
            raise GenerationError("settle window must be 0.01..10 seconds")
        if type(settle_rounds) is not int or not 1 <= settle_rounds <= 100:
            raise GenerationError("settle rounds must be 1..100")
        self.settle_s = float(settle_s)
        self.settle_rounds = settle_rounds
        self.profile = profile
        self.profile_id = profile.profile_id
        self.options = profile.backend_options
        self.supervisor = supervisor
        self.template_dir = template_dir
        self.output_directory = Path(output_directory)
        self.poll_s = float(poll_s)
        self._template: WorkflowTemplate | None = None

    # --- lifecycle --------------------------------------------------------
    def _read_template(self) -> bytes:
        directory = Path(self.template_dir)
        if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
            raise GenerationError("template directory must be an existing absolute non-symlink directory")
        path = directory / self.options.template_name
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(path, flags)
        except OSError:
            raise GenerationError("workflow template is missing or a symlink") from None
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise GenerationError("workflow template must be a regular file")
            raw = handle.read(MAX_TEMPLATE_BYTES + 1)
        return raw

    def load(self) -> None:
        if self._template is not None:
            raise GenerationError("adapter already loaded")
        template = load_template(self._read_template(), self.options.template_sha256)
        self.supervisor.start()
        self._template = template

    def close(self) -> bool:
        """Stop ComfyUI. True once it has exited and the lease is released."""
        self._template = None
        self.supervisor.stop()  # raises (lease kept) if ComfyUI will not exit
        return not self.supervisor.running

    def render(self, request: GenerationRequest) -> RenderedArtifact:
        raise GenerationError("video is written to a staged sink file; use render_to()")

    # --- one job ------------------------------------------------------------
    def render_to(self, request: GenerationRequest, sink_file: BinaryIO) -> str:
        if self._template is None:
            raise GenerationError("adapter not loaded")
        request = validate_request(self.profile, request)
        if request.task != "text_to_video":
            raise GenerationError("only text_to_video is supported")
        try:
            # One job per ComfyUI, from admission to cleanup (#2316 review 5700997784):
            # a concurrent second call is refused here and never submitted.
            with self.supervisor.job_slot():
                return self._render_one(request, sink_file)
        except ComfyBusy:
            raise GenerationError("ComfyUI is busy with another job: refused, not queued") from None

    def _render_one(self, request: GenerationRequest, sink_file: BinaryIO) -> str:
        self.supervisor.require_media_volume()  # ArtifactSinkUnavailable propagates: fatal
        try:
            self.supervisor.check_budget()
            if not self.supervisor.queue_is_empty():
                raise GenerationError("ComfyUI queue is not empty: refusing to share it")
            before = self._mp4_names()
            prompt_id = self.supervisor.submit(self._template.bind(request, fps=self.options.fps))
            outputs = self._wait(prompt_id)
        except ComfySupervisorError as exc:
            raise GenerationError("ComfyUI unavailable") from exc
        source = self._single_output(outputs, before)
        self.supervisor.require_media_volume()  # still the same verified volume after the render
        self._wait_quiescent(source)
        self._copy_validated(source, sink_file)
        source.unlink()
        return MIME

    def _wait(self, prompt_id: str) -> dict:
        deadline = time.monotonic() + self.options.max_render_seconds
        while True:
            record = self.supervisor.history(prompt_id)
            if record is not None:
                status = record.get("status")
                if not isinstance(status, dict):
                    raise GenerationError("ComfyUI history is malformed")
                if status.get("status_str") == "error":
                    raise GenerationError("ComfyUI reported an error")
                if status.get("completed") is True and status.get("status_str") == "success":
                    outputs = record.get("outputs")
                    if not isinstance(outputs, dict):
                        raise GenerationError("ComfyUI history has no outputs")
                    return outputs
            if time.monotonic() >= deadline:
                try:
                    self.supervisor.interrupt()
                except ComfySupervisorError:
                    pass  # stop() interrupts again and terminates if needed
                raise GenerationError("render exceeded the profile deadline")
            time.sleep(self.poll_s)

    def _mp4_names(self) -> set[str]:
        return {entry.name for entry in os.scandir(self.output_directory) if entry.name.endswith(".mp4")}

    def _single_output(self, outputs: dict, before: set[str]) -> Path:
        entries = []
        for node in outputs.values():
            if not isinstance(node, dict):
                raise GenerationError("ComfyUI output node is malformed")
            for key in ("videos", "gifs", "images"):
                items = node.get(key, [])
                if not isinstance(items, list):
                    raise GenerationError("ComfyUI output list is malformed")
                entries += [item for item in items if isinstance(item, dict) and item.get("type") == "output"]
        if len(entries) != 1:
            raise GenerationError("expected exactly one ComfyUI output file")
        name, subfolder = entries[0].get("filename"), entries[0].get("subfolder", "")
        if not isinstance(name, str) or not isinstance(subfolder, str) or subfolder:
            raise GenerationError("ComfyUI output must be a file name in the output directory root")
        if Path(name).name != name or name in ("", ".", "..") or "\\" in name or ":" in name \
                or not name.endswith(".mp4"):
            raise GenerationError("ComfyUI output name is not a plain .mp4 file name")
        if name in before:
            raise GenerationError("ComfyUI output already existed before this job")
        return self.output_directory / name

    def _wait_quiescent(self, source: Path) -> None:
        """ComfyUI may report success before its writer has closed the file: wait until it stops changing."""
        def snapshot():
            try:
                info = os.stat(source, follow_symlinks=False)
            except OSError:
                raise GenerationError("ComfyUI output is missing") from None
            if stat.S_ISLNK(info.st_mode):
                raise GenerationError("ComfyUI output is a symlink")
            return info.st_ino, info.st_size, info.st_mtime_ns

        previous = snapshot()
        for _ in range(self.settle_rounds):
            time.sleep(self.settle_s)
            current = snapshot()
            if current == previous:
                return
            previous = current
        raise GenerationError("ComfyUI output is still being written")

    def _copy_validated(self, source: Path, sink_file: BinaryIO) -> None:
        limit = self.options.max_output_bytes
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        if self.output_directory.is_symlink():
            raise GenerationError("ComfyUI output directory must not be a symlink")
        try:
            fd = os.open(source, flags)
        except OSError:
            raise GenerationError("ComfyUI output is missing or a symlink") from None
        with os.fdopen(fd, "rb") as handle:
            first = os.fstat(handle.fileno())
            if not stat.S_ISREG(first.st_mode) or not 12 <= first.st_size <= limit:
                raise GenerationError("ComfyUI output is not a regular file within the size cap")
            header = handle.read(12)
            if header[4:8] != b"ftyp" or int.from_bytes(header[:4], "big") < 8:
                raise GenerationError("ComfyUI output is not an MP4 container")
            sink_file.write(header)
            copied = len(header)
            while True:
                chunk = handle.read(COPY_CHUNK)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > limit:
                    raise GenerationError("ComfyUI output grew past the size cap")
                sink_file.write(chunk)
            last = os.fstat(handle.fileno())
        if (copied != first.st_size or last.st_size != first.st_size
                or last.st_mtime_ns != first.st_mtime_ns or last.st_ino != first.st_ino):
            raise GenerationError("ComfyUI output changed while it was copied")
        sink_file.flush()
