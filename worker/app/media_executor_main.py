"""Entry point of one media executor process (G2b, ModelRig #2296 6636146026).

    python -m app.media_executor_main --device cuda:N

Started by the appliance's Go supervisor (never by the API worker: the
boundary test forbids the worker entry point to import the generation layer,
and this process must be able to die with exit 70 without taking the API
down). Default-off: without KALIV_MEDIA_EXECUTOR=1 it refuses to run.

Configuration (all from the environment; shared names agreed in 6636684138):
  KALIV_MEDIA_EXECUTOR=1              master switch
  KALIV_MEDIA_WORK_ROOT               the private work area on the internal disk (docs/MEDIA_WORK_AREA.md)
  KALIV_MEDIA_JOB_DB                  absolute path of the job SQLite (ImageJobStore), in the work area
  KALIV_MEDIA_ROOT                    gallery media directory on the external volume
  KALIV_MEDIA_VOLUME_ROOT             the verified (mounted) volume root (G1: docs/MEDIA_VOLUME.md)
  KALIV_MEDIA_VOLUME_ID               the id in <volume root>/.kaliv-media-volume
  KALIV_MEDIA_PROFILE_DIR             operator profile directory
  KALIV_MEDIA_PROFILES_ENABLED, KALIV_MEDIA_ALLOW_CANDIDATE_PROFILES, KALIV_GPU_LEASE_DIR,
  KALIV_GPU_DEVICE_UUIDS, CUDA_DEVICE_ORDER, HF_HUB_OFFLINE, TRANSFORMERS_OFFLINE  (existing)
  KALIV_MEDIA_IDLE_UNLOAD_S           optional, default 300

Video (text-to-video through the supervised ComfyUI; docs/MEDIA_VIDEO_GENERATION.md) is
default-off behind its own switch. An enabled video profile for this device is a
configuration error (exit 78) unless all of this holds:
  KALIV_MEDIA_VIDEO=1                 the video switch (separate from the master switch)
  KALIV_COMFY_PYTHON                  absolute python of the pinned ComfyUI environment
  KALIV_COMFY_MAIN                    absolute path of that ComfyUI's main.py
  KALIV_COMFY_DIR                     the ComfyUI folder in the work area; each executor uses its own
                                      cuda<N>/ in it, with existing input/, output/, temp/ and user/
  KALIV_COMFY_TEMPLATE_DIR            the operator's workflow template directory
  KALIV_COMFY_WEIGHTS_CACHE           optional: the weight-hash cache file, in the work area
  and every served video profile is text_to_video only (image_to_video needs the owner-gated
  source reader, not wired here), uses the comfyui backend, and pins comfyui_version and weights.
Images are published job-keyed through ExternalMediaSink; video through ExternalStagedVideoSink,
with the pinned G1 volume verified before every staging and adoption. There is no bytes fallback.

Where things live (Anders, 6 Nov 2026, #2275 6686905826): media is generated in
the private work area on the internal disk, and published on the external volume.
The job database, which holds prompts until retention blanks them, is in the work
area. The executor still refuses to claim a job while the volume is not there, so
no render is wasted on a result it cannot publish.

Exit codes are MediaExecutor's: 0, 70, 73, 75 (also: the volume is not there
at start), 76, 78 (also: any configuration error, including the switch off and a
work area that fails its checks at start).
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sqlite3
import stat
import sys
import time
from pathlib import Path
from typing import Callable, Mapping

from .gpu_lease import GpuLeaseError, check_lease_dir, device_uuid_map, lease_dir_from_env, parse_cuda_device
from .image_job_store import ImageJobError, ImageJobStore
from .media_executor import EXIT_CONFIG, EXIT_SINK_UNAVAILABLE, ExecutorConfigError, MediaExecutor
from .media_gallery_store import ExternalMediaSink
from .media_generation_contract import MAX_ARTIFACT_BYTES, ArtifactSinkUnavailable, GenerationError
from .media_generation_profiles import ModelProfile, enabled_profiles, load_profile_dir
from .media_staged_video_sink import ExternalStagedVideoSink
from .media_volume import VOLUME_ID_ENV, MediaVolumeConfigError, MountedMediaVolume, media_volume_from_env
from .media_work_area import MediaWorkAreaConfigError, PrivateWorkArea, work_area_from_env

SWITCH_ENV = "KALIV_MEDIA_EXECUTOR"
JOB_DB_ENV = "KALIV_MEDIA_JOB_DB"
MEDIA_ROOT_ENV = "KALIV_MEDIA_ROOT"
VOLUME_ROOT_ENV = "KALIV_MEDIA_VOLUME_ROOT"
WORK_ROOT_ENV = "KALIV_MEDIA_WORK_ROOT"
PROFILE_DIR_ENV = "KALIV_MEDIA_PROFILE_DIR"
IDLE_ENV = "KALIV_MEDIA_IDLE_UNLOAD_S"
VIDEO_SWITCH_ENV = "KALIV_MEDIA_VIDEO"
COMFY_PYTHON_ENV = "KALIV_COMFY_PYTHON"
COMFY_MAIN_ENV = "KALIV_COMFY_MAIN"
COMFY_DIR_ENV = "KALIV_COMFY_DIR"
COMFY_TEMPLATE_DIR_ENV = "KALIV_COMFY_TEMPLATE_DIR"
COMFY_WEIGHTS_CACHE_ENV = "KALIV_COMFY_WEIGHTS_CACHE"
COMFY_FOLDERS = ("input", "output", "temp", "user")


def _absolute(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "")
    if not value or not Path(value).is_absolute():
        raise ExecutorConfigError(f"{name} must be an absolute path")
    return value


def _on_one_device(work: PrivateWorkArea, volume: MountedMediaVolume) -> bool:
    """Whether the work area is on the media volume's device."""
    return work.device == os.stat(volume.root).st_dev


def _check_job_db(path: str) -> None:
    """An existing job database must be a regular file. A directory, a link (which could lead out
    of the work area) or a FIFO (which SQLite would block on) is a configuration error: exit 78,
    never a crash the supervisor restarts (#2337 review 4477759300). A missing file is fine: the
    store creates it, and refuses a missing parent itself."""
    try:
        mode = os.lstat(path).st_mode
    except (FileNotFoundError, NotADirectoryError):
        return
    except PermissionError:
        raise ExecutorConfigError(f"{JOB_DB_ENV} cannot be inspected (permission denied)") from None
    if not stat.S_ISREG(mode):
        raise ExecutorConfigError(f"{JOB_DB_ENV} must be a regular file, not a directory, link or device")


OFFLINE_FLAGS = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")  # what DiffusersImageAdapter.load() requires


class VideoConfig:
    """The checked ComfyUI side of one executor (built only when video is switched on)."""

    def __init__(self, *, python: str, main_py: str, comfy_dir: str, template_dir: str,
                 weights_cache: str | None, work: PrivateWorkArea, gpu_uuid: str):
        self.python, self.main_py, self.comfy_dir, self.template_dir = python, main_py, comfy_dir, template_dir
        self.weights_cache, self.work, self.gpu_uuid = weights_cache, work, gpu_uuid
        self.folders = {name: os.path.join(comfy_dir, name) for name in COMFY_FOLDERS}


def _comfy_device_folder(device: str) -> str:
    """``cuda:1`` -> ``cuda1``: this executor's own folder under ``KALIV_COMFY_DIR``.

    The supervisor gives every executor the same environment (``executorsFrom``), so one
    ``KALIV_COMFY_DIR`` would make two GPUs' ComfyUI processes share their input, output, temp and
    user folders (Codex #2366 4520670217). Each executor uses ``<KALIV_COMFY_DIR>/cuda<N>/``."""
    return f"cuda{parse_cuda_device(device)}"


def _check_comfy_ports(enabled: Mapping[str, ModelProfile]) -> None:
    """Every enabled ComfyUI video profile, on every GPU: one GPU each, and no two on one port.

    Each executor sees only its own profiles when serving, so a port shared between GPUs would pass
    both starts. The second ComfyUI would then refuse the port, and that executor's jobs would fail
    (Codex #2366 4520747821). All enabled profiles are checked, so every executor refuses the
    same configuration before it opens the queue."""
    owners: dict[int, str] = {}
    for profile_id, profile in sorted(enabled.items()):
        if profile.modality != "video" or profile.backend != "comfyui" or profile.backend_options is None:
            continue
        if len(profile.resources.devices) != 1:
            raise ExecutorConfigError(f"{profile_id}: a ComfyUI video profile serves exactly one GPU (its port is "
                                      "fixed); write one profile per GPU, each with its own port")
        port = profile.backend_options.port
        if port in owners:
            raise ExecutorConfigError(f"{owners[port]} and {profile_id} use the same ComfyUI port {port}")
        owners[port] = profile_id


def _video_config(env: Mapping[str, str], video: Mapping[str, ModelProfile], work: PrivateWorkArea,
                  gpu_uuid: str, device: str) -> VideoConfig:
    """Fail closed (78) unless every served video profile and the ComfyUI side are fully specified."""
    if env.get(VIDEO_SWITCH_ENV) != "1":
        raise ExecutorConfigError(f"{VIDEO_SWITCH_ENV}=1 is required for the video profile(s) "
                                  f"{', '.join(sorted(video))}: video is off")
    for profile_id, profile in sorted(video.items()):
        options = profile.backend_options
        if profile.backend != "comfyui" or options is None:
            raise ExecutorConfigError(f"{profile_id}: video is served through the supervised ComfyUI only")
        if "image_to_video" in profile.tasks:
            raise ExecutorConfigError(f"{profile_id}: image_to_video is not served yet (the owner-gated source "
                                      "reader is not wired); a served video profile lists text_to_video only")
        if options.comfyui_version is None or not options.weights:
            raise ExecutorConfigError(f"{profile_id}: a served video profile must pin comfyui_version and weights")
    python = _absolute(env, COMFY_PYTHON_ENV)
    main_py = _absolute(env, COMFY_MAIN_ENV)
    device_folder = _comfy_device_folder(device)
    comfy_dir = os.path.join(_absolute(env, COMFY_DIR_ENV), device_folder)
    template_dir = _absolute(env, COMFY_TEMPLATE_DIR_ENV)
    if not os.path.isfile(python):  # a venv's python is a link on POSIX: that is fine
        raise ExecutorConfigError(f"{COMFY_PYTHON_ENV} must be an existing file")
    if not os.path.isfile(main_py) or os.path.islink(main_py):
        raise ExecutorConfigError(f"{COMFY_MAIN_ENV} must be an existing file, not a link")
    if os.path.basename(main_py) != "main.py":
        raise ExecutorConfigError(f"{COMFY_MAIN_ENV} must name ComfyUI's main.py")
    if not os.path.isdir(template_dir) or os.path.islink(template_dir):
        raise ExecutorConfigError(f"{COMFY_TEMPLATE_DIR_ENV} must be an existing directory, not a link")
    # ComfyUI writes frames, the unfinished MP4 and temp files here: the private work area on the
    # internal disk (Anders, 6 Nov 2026), checked here and again by the supervisor before every job.
    for name in COMFY_FOLDERS:
        folder = os.path.join(comfy_dir, name)
        try:
            work.require(folder)
        except ArtifactSinkUnavailable as exc:
            raise ExecutorConfigError(f"{COMFY_DIR_ENV}/{device_folder}/{name} must be an existing folder in the "
                                      f"work area ({exc})") from None
        # require() also accepts a regular file. ComfyUI would only fail on it after a job was
        # claimed (ComfyLaunch.argv), so a file here is refused at start (Codex #2366 4520670221).
        if not os.path.isdir(folder) or os.path.islink(folder):
            raise ExecutorConfigError(f"{COMFY_DIR_ENV}/{device_folder}/{name} must be a directory, not a file "
                                      "or a link")
    weights_cache = env.get(COMFY_WEIGHTS_CACHE_ENV) or None
    if weights_cache is not None:
        _absolute(env, COMFY_WEIGHTS_CACHE_ENV)
        try:
            work.require(os.path.dirname(weights_cache))
        except ArtifactSinkUnavailable as exc:
            raise ExecutorConfigError(f"{COMFY_WEIGHTS_CACHE_ENV} must be in an existing folder in the work area "
                                      f"({exc})") from None
    return VideoConfig(python=python, main_py=main_py, comfy_dir=comfy_dir, template_dir=template_dir,
                       weights_cache=weights_cache, work=work, gpu_uuid=gpu_uuid)


def default_adapter_factory(device: str, lease_dir: str, env: Mapping[str, str], *,
                            video: VideoConfig | None = None, supervisor_class=None,
                            image_adapter_factory: Callable[[ModelProfile], object] | None = None,
                            ) -> Callable[[ModelProfile], object]:
    """``supervisor_class`` and ``image_adapter_factory`` exist for the tests (a fake ComfyUI child,
    a fake image pipeline); production passes neither."""
    def factory(profile: ModelProfile):
        if profile.backend == "diffusers":
            if image_adapter_factory is not None:
                return image_adapter_factory(profile)
            from .diffusers_image_adapter import DiffusersImageAdapter
            return DiffusersImageAdapter(profile, device=device, lease_dir=lease_dir, env=env)
        if profile.backend == "comfyui" and video is not None:
            from .comfy_supervisor import ComfyLaunch, ComfySupervisor
            from .comfy_video_adapter import ComfyVideoAdapter
            folders = video.folders
            launch = ComfyLaunch(python_executable=video.python, main_py=video.main_py,
                                 port=profile.backend_options.port, input_directory=folders["input"],
                                 output_directory=folders["output"], temp_directory=folders["temp"],
                                 user_directory=folders["user"])
            supervisor = (supervisor_class or ComfySupervisor)(
                gpu_uuid=video.gpu_uuid, lease_dir=lease_dir, launch=launch, work_area=video.work,
                reserve_gib=profile.resources.reserve_gib, min_usable_gib=profile.resources.min_usable_gib,
                base_env=env)
            return ComfyVideoAdapter(profile, supervisor=supervisor, template_dir=video.template_dir,
                                     output_directory=folders["output"], weights_cache=video.weights_cache)
        raise ExecutorConfigError(f"{profile.profile_id}: backend {profile.backend} is not served by this executor yet")
    return factory


class PinnedVolumeSink:
    """The image sink, with the pinned G1 volume verified immediately before every write.

    ``ExternalMediaSink`` checks its root by path only. Wrapped here, a volume that is unplugged,
    swapped for another disk or remounted after the job's last database access raises
    ``ArtifactSinkUnavailable`` (exit 75) before any byte is written or indexed. A swap inside the
    sink's own write remains the documented check-then-use window of a path check
    (docs/MEDIA_VOLUME.md, Limits)."""

    def __init__(self, sink, volume):
        self._sink, self._volume = sink, volume

    def publish(self, data: bytes, extension: str) -> str:
        self._volume.verify()
        return self._sink.publish(data, extension)

    def publish_and_register_for_job(self, job_key: str, data: bytes, extension: str) -> str:
        self._volume.verify()
        return self._sink.publish_and_register_for_job(job_key, data, extension)

    def __getattr__(self, name):  # read-only helpers (inspection) pass through unchanged
        return getattr(self._sink, name)


class PinnedStagedVideoSink:
    """The staged video sink, with the pinned G1 volume verified before staging and before adoption.

    ``ExternalStagedVideoSink`` re-checks its root by path; this adds the pinned identity, as
    ``PinnedVolumeSink`` does for images, so a disk swapped during a render gets nothing."""

    def __init__(self, sink, volume):
        self._sink, self._volume = sink, volume

    @contextlib.contextmanager
    def staged(self, extension: str):
        self._volume.verify()
        with self._sink.staged(extension) as output:
            yield output

    def adopt(self, handle, mime_type: str) -> str:
        self._volume.verify()
        return self._sink.adopt(handle, mime_type)

    def adopt_for_job(self, handle, mime_type: str, job_key: str) -> str:
        self._volume.verify()
        return self._sink.adopt_for_job(handle, mime_type, job_key)


def build_from_env(device: str, env: Mapping[str, str] | None = None, *,
                   adapter_factory: Callable[[ModelProfile], object] | None = None,
                   volume_probe=None, work_probe=None, supervisor_class=None,
                   image_adapter_factory: Callable[[ModelProfile], object] | None = None) -> MediaExecutor:
    """Everything the executor needs, from the environment. Raises ExecutorConfigError or
    ArtifactSinkUnavailable (the volume is not there); never creates a missing directory."""
    env = os.environ if env is None else env
    if env.get(SWITCH_ENV) != "1":
        raise ExecutorConfigError(f"{SWITCH_ENV}=1 is required: the media executor is off")
    try:
        index = parse_cuda_device(device)
        gpu_uuid = device_uuid_map(env).get(index)
        lease_dir = lease_dir_from_env(env)
        check_lease_dir(lease_dir)  # relative, missing, symlinked or writable by others: 78, not exit 1 later
    except GpuLeaseError as exc:
        raise ExecutorConfigError(str(exc)) from None
    if gpu_uuid is None:
        raise ExecutorConfigError(f"no GPU UUID is configured for {device}")
    job_db = _absolute(env, JOB_DB_ENV)
    media_root = _absolute(env, MEDIA_ROOT_ENV)
    _absolute(env, VOLUME_ROOT_ENV)
    if not env.get(VOLUME_ID_ENV):
        raise ExecutorConfigError(f"{VOLUME_ID_ENV} is required (the id in the volume's marker)")
    profile_dir = _absolute(env, PROFILE_DIR_ENV)
    try:
        profiles = enabled_profiles(load_profile_dir(profile_dir), env)
    except GenerationError as exc:
        raise ExecutorConfigError(str(exc)) from None
    mine = {pid: p for pid, p in profiles.items() if device in p.resources.devices}
    if not mine:
        raise ExecutorConfigError(f"no enabled profile allows {device}")
    if any(p.backend == "diffusers" for p in mine.values()) and any(env.get(f) != "1" for f in OFFLINE_FLAGS):
        # The adapter refuses to load without them; checked here so a missing setting is exit 78
        # and leaves the queue untouched, instead of failing every claimed job (#2337 review 4477167705).
        raise ExecutorConfigError(f"{' and '.join(f + '=1' for f in OFFLINE_FLAGS)} are required (never a download)")
    # Anders, 6 Nov 2026: generate in a private folder on the internal disk. It is local, so a work
    # area that fails its checks at start is a configuration error (78), never "not there right now".
    try:
        work = work_area_from_env(env, probe=work_probe)
    except MediaWorkAreaConfigError as exc:
        raise ExecutorConfigError(str(exc)) from None
    # G1: the production volume check. A configuration that can never work (a malformed id, a FAT
    # volume, the system disk) is 78; a volume that is not usable right now is 75. Its identity is
    # pinned here, so a disk unplugged or swapped while the executor runs stops it until a restart.
    try:
        volume = media_volume_from_env(env, probe=volume_probe)
    except MediaVolumeConfigError as exc:
        raise ExecutorConfigError(str(exc)) from None
    if _on_one_device(work, volume):
        raise ExecutorConfigError(f"{WORK_ROOT_ENV} must not be on the media volume: media is generated on the "
                                  "internal disk and published on the external one")
    # The job database (prompts until retention blanks them) lives where media is generated: in the
    # work area. Checked, never moved: a folder outside it, behind a link or on another device is 78.
    job_dir = os.path.dirname(job_db)
    try:
        work.require(job_dir)
    except ArtifactSinkUnavailable as exc:
        raise ExecutorConfigError(f"{JOB_DB_ENV} must be in an existing folder in the work area ({exc})") from None
    # Video: everything is checked before the job database is first looked at, like the rest.
    video_profiles = {pid: p for pid, p in mine.items() if p.modality == "video"}
    if video_profiles:
        _check_comfy_ports(profiles)  # all enabled profiles, every GPU: not only this executor's
    video = _video_config(env, video_profiles, work, gpu_uuid, device) if video_profiles else None
    sink = ExternalMediaSink(media_root, str(volume.root))
    # The sink itself only knows the root's path (mount and containment checks, no marker or pinned
    # identity). G1 is checked again immediately before every write, so a disk replaced after
    # begin_publish() and before publication gets nothing (Codex #2357 4503161823).
    published_through = PinnedVolumeSink(sink, volume)

    def guard() -> None:
        work.require(job_dir)  # still the pinned, private work area, and the same folder in it
        volume.verify()  # mounted, marked, the pinned identity: no claim without the publication volume
        sink._root()  # the gallery root is a canonical directory inside it

    # Both are verified before the job database is first looked at (nothing inspected or created)
    # and again before EVERY later access, so a volume that goes away while the executor runs stops
    # it (75) before it claims another job, instead of rendering one it cannot publish
    # (#2337 review 4477083808), and a work area that changes stops it too.
    guard()
    _check_job_db(job_db)
    # The database file and its sidecars must be private too: on Windows a file moved in from
    # elsewhere on the same disk keeps the ACL it had there (docs/MEDIA_WORK_AREA.md: copy, never move).
    for existing in (job_db, job_db + "-wal", job_db + "-shm", job_db + "-journal"):
        if os.path.lexists(existing):
            try:
                work.require(existing)
            except ArtifactSinkUnavailable as exc:
                raise ExecutorConfigError(f"{JOB_DB_ENV} is not private in the work area ({exc}); copy it "
                                          "into the work area instead of moving it") from None
    try:
        store = ImageJobStore(job_db, volume_guard=guard)
    except ImageJobError as exc:
        raise ExecutorConfigError(str(exc)) from None
    except sqlite3.DatabaseError as exc:
        if getattr(exc, "sqlite_errorname", None) != "SQLITE_NOTADB":
            raise  # e.g. locked: transient, so exit 1 and the supervisor's back-off restart
        raise ExecutorConfigError(f"{JOB_DB_ENV} is not a SQLite database") from None
    try:
        idle = float(env.get(IDLE_ENV, "300"))
    except ValueError:
        raise ExecutorConfigError(f"{IDLE_ENV} must be a number of seconds") from None
    video_sink = None
    if video is not None:
        largest = max(p.backend_options.max_output_bytes for p in video_profiles.values())
        video_sink = PinnedStagedVideoSink(
            ExternalStagedVideoSink(media_root, str(volume.root), max_bytes=min(largest, MAX_ARTIFACT_BYTES)), volume)
    factory = adapter_factory or default_adapter_factory(device, lease_dir, env, video=video,
                                                         supervisor_class=supervisor_class,
                                                         image_adapter_factory=image_adapter_factory)
    return MediaExecutor(store, gpu_uuid=gpu_uuid, lease_dir=lease_dir, profiles=mine, adapter_factory=factory,
                         image_sink=published_through, video_sink=video_sink, idle_unload_s=idle,
                         volume_root=str(volume.root))


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.media_executor_main")
    parser.add_argument("--device", required=True, help="cuda:N (CUDA_DEVICE_ORDER=PCI_BUS_ID)")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args(argv)
    try:
        executor = build_from_env(args.device, env)
    except ExecutorConfigError as exc:
        print(f"media executor: configuration refused: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except ArtifactSinkUnavailable as exc:  # a reason code, never a prompt
        print(f"media executor: the external media volume is not available ({exc})", file=sys.stderr)
        return EXIT_SINK_UNAVAILABLE
    poll = min(max(args.poll_seconds, 0.1), 30.0)
    gpu = getattr(executor, "gpu_uuid", None)

    def diagnostics(event: dict) -> None:
        # One JSON line per lifecycle event on stderr, which modelrig-supervisor writes to the
        # executor's log: job ids, profile ids, outcomes, counts and codes; never a prompt.
        print("kaliv-media-event " + json.dumps({"gpu": gpu, **event}, sort_keys=True), file=sys.stderr, flush=True)
    if hasattr(getattr(executor, "events", None), "sink"):
        executor.events.sink = diagnostics
    try:
        return executor.run(idle_sleep=lambda: time.sleep(poll))
    except GpuLeaseError as exc:  # the lease directory became unusable: configuration, not a crash
        print(f"media executor: GPU lease configuration refused: {exc}", file=sys.stderr)
        return EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main())
