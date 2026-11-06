"""Text-to-video through one supervised ComfyUI (ModelRig #2296 slice 2, design 6493077060).

Default-off and not wired anywhere. The adapter never opens a socket itself
(HTTP lives in comfy_supervisor), never chooses where an artifact is stored
and never writes outside the file object the sink hands it.

load():   verify the pinned template (SHA-256 over the exact bytes that are
          parsed), then start the supervisor (GPU lease for ComfyUI's life).
render_to(request, sink_file):
          VRAM re-check -> empty queue (single tenant) -> bind slot values
          -> submit -> poll history with the profile deadline (interrupt on
          timeout) -> exactly one MP4 in the ComfyUI output dir (in the
          private work area on the internal disk; Anders, 6 Nov), validated
          (no symlinks, unchanged over a settle window before the copy and
          during it, ftyp header, size cap) -> copied into sink_file (a
          staged file on the external media volume, published by the sink
          only after the copy is complete and checked) -> ComfyUI's output
          removed.
          Cleanup (#2316 reviews 4415046066, 5702562074): after the job --
          success or failure -- remove exactly the files that are provably
          the job's: named by ComfyUI in THIS prompt's history (type
          "output", plain name, output root), new since the pre-submit
          snapshot, and still the same inode (dev, ino) recorded when the
          history arrived. Neither POSIX nor Windows can "unlink if still
          this inode" atomically, so the file is first renamed to a random
          name in the same directory (atomic: it captures exactly what
          carries the name at that instant); the identity is checked on the
          captured file; ours is deleted, anything else is put back without
          overwriting (POSIX link, Windows rename -- both refuse an existing
          target) or, if the name has meanwhile been taken, left under the
          quarantine name and reported. A replaced file is never deleted, and
          a file without a file id (st_ino 0) is never treated as the job's.
          Foreign files created mid-job and anything that existed before are
          kept. Cleanup never raises: it cannot mask the render's own error. A symlink is
          removed as a link, its target never. If the work area cannot be
          verified at cleanup time, nothing is touched. Every cleanup is
          reported in last_cleanup and failures are logged (file names only;
          they are generated, never a prompt).
          Stated limit: a write that arrives after a timeout interrupt is not
          in the history and is left in place (reported as untracked).
close():  stop the supervisor.

image_to_video (#2296 6635978072): render_to(..., source_png=bytes). The caller
(the executor) reads the source through ChatGPT's owner-gated reader; the adapter
only receives bytes. It bounds the decode (IHDR: at most 4096 px per side), creates kaliv-src-<16 hex>.png exclusively (O_EXCL, O_NOFOLLOW, 0600,
fsync) in ComfyUI's input directory right after verifying that directory is in
the private work area, binds the template's image slot to that name, and removes the
file after the job -- success, failure or cancel -- with the same rename-capture
identity check as the outputs: a replaced file is never deleted.
"""
from __future__ import annotations

import logging
import os
import secrets
import stat
import time
from pathlib import Path
from typing import BinaryIO, Callable

from .comfy_supervisor import ComfyBusy, ComfySupervisor, ComfySupervisorError, ComfyVramShortage
from .comfy_weights import check_lookup_is_unambiguous, check_weights_unchanged, verify_weights
from .comfy_workflow_template import MAX_TEMPLATE_BYTES, WorkflowTemplate, load_template
from .media_generation_contract import GenerationCancelled, GenerationError, GenerationRequest, RenderedArtifact
from .media_generation_profiles import ModelProfile, validate_request

MIME = "video/mp4"
COPY_CHUNK = 1024 * 1024
DRAIN_SECONDS = 30  # how long an interrupted job may take to leave ComfyUI's queue
_log = logging.getLogger("kaliv.media.comfy")


# Decoder-side bound for an image_to_video source (#2296 6636684138: agreed with ChatGPT, whose
# reader validates the PNG container). ComfyUI decodes with PIL; bytes alone do not bound memory.
MAX_SOURCE_AXIS = 4096  # so at most 16.8 MP
MAX_SOURCE_BYTES = 64 * 1024 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# APNG: ComfyUI's LoadImage decodes and concatenates EVERY frame, so IHDR's size alone does not
# bound memory (#2346 review 4489553700: 100 frames at 4096x4096 fit in 5 MB of APNG).
_ANIMATION_CHUNKS = frozenset({b"acTL", b"fcTL", b"fdAT"})


def check_source_png(data: object) -> None:
    """Refuse a source that is not a single-frame PNG whose first chunk is a well-formed IHDR
    within the caps. Not a full validation (CRCs are the reader's); a bound on what ComfyUI may
    decode: one frame of at most MAX_SOURCE_AXIS per side."""
    if type(data) is not bytes or not 8 + 25 <= len(data) <= MAX_SOURCE_BYTES:
        raise GenerationError("the source image must be PNG bytes within the size limit")
    if data[:8] != _PNG_SIGNATURE or data[8:16] != b"\x00\x00\x00\x0dIHDR":
        raise GenerationError("the source image is not a PNG")
    width, height = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if not (1 <= width <= MAX_SOURCE_AXIS and 1 <= height <= MAX_SOURCE_AXIS):
        raise GenerationError(f"the source image must be 1..{MAX_SOURCE_AXIS} px per side")
    offset = 8
    while offset + 12 <= len(data):
        length, kind = int.from_bytes(data[offset:offset + 4], "big"), data[offset + 4:offset + 8]
        if kind in _ANIMATION_CHUNKS:
            raise GenerationError("the source image must be a single-frame PNG (animated PNG refused)")
        if kind == b"IEND":
            return
        offset += 12 + length
    raise GenerationError("the source image is not a complete PNG")


class ComfyVideoAdapter:
    def __init__(self, profile: ModelProfile, *, supervisor: ComfySupervisor, template_dir: str,
                 output_directory: str, poll_s: float = 1.0, settle_s: float = 0.5,
                 settle_rounds: int = 10, weights_cache: str | None = None):
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
        self.weights_cache = weights_cache
        self._template: WorkflowTemplate | None = None
        self.last_cleanup: dict[str, list[str]] = {}
        # True once an interrupt could not be confirmed drained: this ComfyUI must not take another
        # job. The executor unloads (and so restarts) the adapter (#2318 review 4469472651).
        self.needs_restart = False
        self._verified_weights: tuple = ()

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
        if self.needs_restart:
            raise GenerationError("this adapter needs a restart: create a new one")
        pins = self.options.weights
        template = load_template(self._read_template(), self.options.template_sha256,
                                 pinned_files=[pin.path for pin in pins] if pins else None)
        if template.task not in self.profile.tasks:
            raise GenerationError(f"the template renders {template.task}, which this profile does not list")
        verified = ()
        if pins:  # before ComfyUI starts: nothing unpinned is ever loaded (G3)
            launch = self.supervisor.launch
            verified = verify_weights(launch.resolved_models_directory, pins, cache_path=self.weights_cache,
                                      comfy_root=Path(launch.main_py).parent)
        budget = self.supervisor.start()
        if not self._version_ok(budget):
            self.supervisor.stop()  # proven stop: the lease goes with ComfyUI
            raise GenerationError("ComfyUI version does not match the profile pin")
        self._verified_weights = verified
        self._template = template

    def _weights_still_verified(self) -> None:
        """Before every job: the files hashed at load are still those files, and the lookup is
        still unambiguous (no embedding or same-named file added since). ComfyUI reads weights
        when a job runs, so a start-time check alone would leave the resident lifetime open.
        A failure refuses the job before submit and marks this ComfyUI for a restart, which
        re-verifies from scratch."""
        pins = self.options.weights
        if not pins:
            return
        launch = self.supervisor.launch
        try:
            check_weights_unchanged(launch.resolved_models_directory, self._verified_weights)
            check_lookup_is_unambiguous(Path(launch.main_py).parent, launch.resolved_models_directory, pins)
        except GenerationError:
            self.needs_restart = True
            raise

    def _version_ok(self, budget) -> bool:
        pin = self.options.comfyui_version
        return pin is None or getattr(budget, "comfyui_version", None) == pin

    def close(self) -> bool:
        """Stop ComfyUI. True once it has exited and the lease is released."""
        self._template = None
        self.supervisor.stop()  # raises (lease kept) if ComfyUI will not exit
        return not self.supervisor.running

    def render(self, request: GenerationRequest) -> RenderedArtifact:
        raise GenerationError("video is written to a staged sink file; use render_to()")

    # --- one job ------------------------------------------------------------
    def render_to(self, request: GenerationRequest, sink_file: BinaryIO, *,
                  should_cancel: Callable[[], bool] | None = None, source_png: bytes | None = None) -> str:
        """Render into sink_file. should_cancel is polled with the history; True interrupts
        ComfyUI and raises GenerationCancelled (the normal cleanup still runs).
        source_png: the source image, required exactly for image_to_video."""
        if self._template is None:
            raise GenerationError("adapter not loaded")
        request = validate_request(self.profile, request)
        if request.task != self._template.task:
            raise GenerationError(f"this adapter's template renders {self._template.task} only")
        if request.task == "image_to_video":
            check_source_png(source_png)  # before the job slot, the volume or anything on disk
        elif source_png is not None:
            raise GenerationError("a source image is only valid for image_to_video")
        try:
            # One job per ComfyUI, from admission to cleanup (#2316 review 5700997784):
            # a concurrent second call is refused here and never submitted.
            with self.supervisor.job_slot():
                return self._render_one(request, sink_file, should_cancel, source_png)
        except ComfyBusy:
            raise GenerationError("ComfyUI is busy with another job: refused, not queued") from None

    def _render_one(self, request: GenerationRequest, sink_file: BinaryIO,
                    should_cancel: Callable[[], bool] | None = None, source_png: bytes | None = None) -> str:
        self.supervisor.require_work_area()  # ArtifactSinkUnavailable propagates: fatal
        before = self._entry_names()  # snapshot before anything is submitted
        owned: list[tuple[str, int, int]] = []  # (name, st_dev, st_ino) attested by THIS prompt's history
        staged: list[tuple[str, int, int]] = []  # the source file this job created, once it exists
        try:
            return self._render_and_hand_over(request, sink_file, before, owned, should_cancel, source_png, staged)
        finally:
            try:
                self._remove_job_outputs(before, owned)
            except Exception as exc:  # never mask the render's own result or error
                _log.warning("comfy cleanup raised %s; outputs left in place", type(exc).__name__)
            if staged:
                try:
                    self._remove_staged_source(*staged[0])
                except Exception as exc:
                    self.last_cleanup["source"] = f"failed: {type(exc).__name__}"
                    _log.warning("comfy source cleanup raised %s; source left in place", type(exc).__name__)

    def _render_and_hand_over(self, request: GenerationRequest, sink_file: BinaryIO, before: set[str],
                              owned: list, should_cancel: Callable[[], bool] | None = None,
                              source_png: bytes | None = None, staged: list | None = None) -> str:
        try:
            if not self._version_ok(self.supervisor.check_budget()):
                raise GenerationError("ComfyUI version does not match the profile pin")
            self._weights_still_verified()
            if not self.supervisor.queue_is_empty():
                raise GenerationError("ComfyUI queue is not empty: refusing to share it")
            source_file = None
            if source_png is not None:
                source_file = self._stage_source(source_png, staged)  # records itself before any write
            prompt_id = self.supervisor.submit(self._template.bind(request, fps=self.options.fps,
                                                                   source_file=source_file))
            outputs = self._wait(prompt_id, should_cancel)
        except ComfyVramShortage:
            raise  # before submit: transient, the executor re-queues the job (G4)
        except ComfySupervisorError as exc:
            raise GenerationError("ComfyUI unavailable") from exc
        owned.extend(self._attested_outputs(outputs, before))  # recorded before any validation can fail
        source = self._single_output(outputs, before)
        self.supervisor.require_work_area()  # still the same private work area after the render
        self._wait_quiescent(source)
        self._copy_validated(source, sink_file)
        return MIME

    @staticmethod
    def _history_entries(outputs: object):
        if not isinstance(outputs, dict):
            return
        for node in outputs.values():
            if isinstance(node, dict):
                for key in ("videos", "gifs", "images"):
                    items = node.get(key, [])
                    if isinstance(items, list):
                        yield from (item for item in items if isinstance(item, dict))

    def _attested_outputs(self, outputs: object, before: set[str]) -> list[tuple[str, int, int]]:
        """Files ComfyUI says THIS prompt wrote to the output root, with their identity right now."""
        found = []
        for item in self._history_entries(outputs):
            name, subfolder = item.get("filename"), item.get("subfolder", "")
            if item.get("type") != "output" or subfolder != "" or not isinstance(name, str):
                continue
            if Path(name).name != name or name in ("", ".", "..") or "\\" in name or ":" in name or name in before:
                continue
            try:
                info = os.stat(self.output_directory / name, follow_symlinks=False)
            except OSError:
                continue  # named but not there: nothing to clean
            if not stat.S_ISDIR(info.st_mode) and info.st_ino != 0:  # no file id: identity unprovable, kept
                found.append((name, info.st_dev, info.st_ino))
        return found

    def _remove_job_outputs(self, before: set[str], owned: list[tuple[str, int, int]]) -> None:
        """Remove exactly the job-owned files; keep and report everything else."""
        report: dict[str, list[str]] = {"removed": [], "kept_replaced": [], "untracked": [], "failed": []}
        self.last_cleanup = report
        try:
            self.supervisor.require_work_area()
        except Exception:
            report["failed"] = [name for name, _, _ in owned]
            _log.warning("comfy cleanup skipped: work area not verified; left %s", report["failed"])
            return  # replaced or no longer private: touch nothing in whatever is there now
        # POSIX: stat and unlink through one directory fd (no path re-resolution between
        # the identity check and the unlink). Windows has no dir_fd: same check by path.
        use_fd = all(f in os.supports_dir_fd for f in (os.stat, os.unlink, os.rename, os.link))
        dir_fd = None
        try:
            if use_fd:
                dir_fd = os.open(self.output_directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                                 | getattr(os, "O_NOFOLLOW", 0))
        except OSError as exc:
            report["failed"] = [name for name, _, _ in owned]
            _log.warning("comfy cleanup failed: output directory unavailable (%s)", type(exc).__name__)
            return
        try:
            for name, dev, ino in owned:
                outcome = self._delete_if_same(name, dev, ino, dir_fd)
                if outcome == "removed" or outcome == "gone":
                    report["removed"].append(name)
                elif outcome.startswith("kept"):
                    report["kept_replaced"].append(name if outcome == "kept" else f"{name} (now {outcome[5:]})")
                else:
                    error, _, moved = outcome.partition(":")
                    report["failed"].append(f"{name} (now {moved})" if moved else name)
                    _log.warning("comfy cleanup failed for %s (%s)%s", name, error, f"; left as {moved}" if moved else "")
            owned_names = {name for name, _, _ in owned}
            try:
                now = os.listdir(dir_fd) if dir_fd is not None else os.listdir(self.output_directory)
                report["untracked"] = sorted(n for n in now if n not in before and n not in owned_names)
            except OSError:
                pass
        finally:
            if dir_fd is not None:
                os.close(dir_fd)
        if report["kept_replaced"] or report["untracked"]:
            _log.warning("comfy cleanup kept files it cannot prove are this job's: replaced=%s untracked=%s",
                         report["kept_replaced"], report["untracked"])

    def _wait(self, prompt_id: str, should_cancel: Callable[[], bool] | None = None) -> dict:
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
            if should_cancel is not None and should_cancel():
                self._interrupt_and_drain()
                raise GenerationCancelled("cancelled while rendering")
            if time.monotonic() >= deadline:
                self._interrupt_and_drain()
                raise GenerationError("render exceeded the profile deadline")
            time.sleep(self.poll_s)

    def _interrupt_and_drain(self) -> None:
        """Interrupt, then wait (bounded) until ComfyUI's queue is empty, so the next job on this
        resident ComfyUI is not refused as "queue not empty" while the interrupt is still landing.
        If the drain cannot be confirmed (interrupt or queue check failed, or the deadline passed),
        mark the adapter for a restart instead of letting it take more jobs."""
        try:
            self.supervisor.interrupt()
        except ComfySupervisorError:
            self.needs_restart = True
            return
        until = time.monotonic() + DRAIN_SECONDS
        while time.monotonic() < until:
            try:
                if self.supervisor.queue_is_empty():
                    return
            except ComfySupervisorError:
                break
            time.sleep(self.poll_s)
        self.needs_restart = True
        _log.warning("comfy queue not confirmed drained after an interrupt; the adapter needs a restart")

    def _delete_if_same(self, name: str, dev: int, ino: int, dir_fd: int | None,
                        directory: Path | None = None) -> str:
        """Delete `name` only if it is still the file with (dev, ino); never delete anything else.

        Returns "removed", "gone", "kept", "kept:<quarantine name>", or the error type name
        ("<error>:<quarantine name>" once the file has been captured and is left there).
        """
        quarantine = f".kaliv-cleanup-{secrets.token_hex(8)}"
        base = self.output_directory if directory is None else directory
        here = (lambda n: n) if dir_fd is not None else (lambda n: base / n)
        fd_args = {"src_dir_fd": dir_fd, "dst_dir_fd": dir_fd} if dir_fd is not None else {}
        try:
            os.rename(here(name), here(quarantine), **fd_args)  # atomic within one directory
        except FileNotFoundError:
            return "gone"
        except OSError as exc:
            return type(exc).__name__  # e.g. still open on Windows: left in place
        try:
            info = os.stat(here(quarantine), dir_fd=dir_fd, follow_symlinks=False)
            if (info.st_dev, info.st_ino) == (dev, ino):
                os.unlink(here(quarantine), dir_fd=dir_fd)  # ours; a symlink goes as a link
                return "removed"
        except OSError as exc:
            return f"{type(exc).__name__}:{quarantine}"  # captured, not deleted: say where it is
        # Not ours: put it back under its name without overwriting anything.
        try:
            if os.name == "nt":
                os.rename(here(quarantine), here(name))  # Windows rename refuses an existing target
            else:
                os.link(here(quarantine), here(name), follow_symlinks=False, **fd_args)  # refuses one too
                os.unlink(here(quarantine), dir_fd=dir_fd)
            return "kept"
        except OSError:
            return f"kept:{quarantine}"  # its name was taken meanwhile: left, unharmed, and reported

    def _stage_source(self, data: bytes, staged: list) -> str:
        """Create the job's source image in ComfyUI's input directory: exclusively, in the
        verified work area, flushed. Appends (name, st_dev, st_ino) to `staged` right after the
        exclusive create and BEFORE any fallible write, so the caller's cleanup always sees it
        (#2346 review 4484574398). The identity is the created file's own (fstat), checked
        against the name with os.stat -- the call the cleanup repeats -- before it is recorded
        and again after the write: a file swapped in meanwhile is refused and never submitted,
        and the cleanup keeps it instead of deleting it as job-owned (#2346 review 4484574409)."""
        directory = Path(self.supervisor.launch.input_directory)
        self.supervisor.work_area.require(str(directory))  # right before the write
        name = f"kaliv-src-{secrets.token_hex(8)}.png"
        path = directory / name
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        fd = os.open(path, flags, 0o600)
        try:
            created = os.fstat(fd)
            named = os.stat(path, follow_symlinks=False)
            if not stat.S_ISREG(named.st_mode) or (named.st_dev, named.st_ino) != (created.st_dev, created.st_ino):
                raise GenerationError("the staged source image was replaced while it was created")
            staged.append((name, created.st_dev, created.st_ino))  # recorded before anything can fail
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        info = os.stat(path, follow_symlinks=False)
        if (not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != (created.st_dev, created.st_ino)
                or info.st_size != len(data)):
            raise GenerationError("the staged source image changed while it was written")
        return name

    def _remove_staged_source(self, name: str, dev: int, ino: int) -> None:
        """Remove the staged source only if it is still the file this job created."""
        directory = Path(self.supervisor.launch.input_directory)
        try:
            self.supervisor.work_area.require(str(directory))
        except Exception:
            self.last_cleanup["source"] = f"failed: {name} (work area not verified)"
            return  # replaced or no longer private: touch nothing in whatever is there now
        if ino == 0:  # no file id: identity unprovable, kept (as for outputs)
            self.last_cleanup["source"] = f"kept: {name}"
            return
        outcome = self._delete_if_same(name, dev, ino, None, directory=directory)
        self.last_cleanup["source"] = outcome if outcome in ("removed", "gone") else f"{outcome}: {name}"
        if outcome not in ("removed", "gone"):
            _log.warning("comfy source cleanup kept or failed on %s (%s)", name, outcome)

    def _entry_names(self) -> set[str]:
        return {entry.name for entry in os.scandir(self.output_directory)}

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
        # The bytes must be durable on the publication volume before the work-area copy is removed:
        # render_to's cleanup runs as soon as this returns (Anders, 6 Nov: work on C:, publish to Z:).
        # A delayed write error (disk full, I/O error) surfaces here and fails the job, never a
        # silent success. The staged sink's handle has sync() and deliberately no fileno (#2347).
        sync = getattr(sink_file, "sync", None)
        if callable(sync):
            sync()
            return
        try:
            fileno = sink_file.fileno()
        except (AttributeError, OSError):  # an in-memory sink (tests) has nothing to sync
            return
        os.fsync(fileno)
