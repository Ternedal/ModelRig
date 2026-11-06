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

First version: images only, published job-keyed through ExternalMediaSink.
A video profile for this device is a configuration error (exit 78) until a
staged video sink exists; there is no bytes fallback.

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
from .media_generation_contract import ArtifactSinkUnavailable, GenerationError
from .media_generation_profiles import ModelProfile, enabled_profiles, load_profile_dir
from .media_volume import VOLUME_ID_ENV, MediaVolumeConfigError, MountedMediaVolume, media_volume_from_env
from .media_work_area import MediaWorkAreaConfigError, PrivateWorkArea, work_area_from_env

SWITCH_ENV = "KALIV_MEDIA_EXECUTOR"
JOB_DB_ENV = "KALIV_MEDIA_JOB_DB"
MEDIA_ROOT_ENV = "KALIV_MEDIA_ROOT"
VOLUME_ROOT_ENV = "KALIV_MEDIA_VOLUME_ROOT"
WORK_ROOT_ENV = "KALIV_MEDIA_WORK_ROOT"
PROFILE_DIR_ENV = "KALIV_MEDIA_PROFILE_DIR"
IDLE_ENV = "KALIV_MEDIA_IDLE_UNLOAD_S"


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


def default_adapter_factory(device: str, lease_dir: str, env: Mapping[str, str]) -> Callable[[ModelProfile], object]:
    def factory(profile: ModelProfile):
        if profile.backend == "diffusers":
            from .diffusers_image_adapter import DiffusersImageAdapter
            return DiffusersImageAdapter(profile, device=device, lease_dir=lease_dir, env=env)
        raise ExecutorConfigError(f"{profile.profile_id}: backend {profile.backend} is not served by this executor yet")
    return factory


def build_from_env(device: str, env: Mapping[str, str] | None = None, *,
                   adapter_factory: Callable[[ModelProfile], object] | None = None,
                   volume_probe=None, work_probe=None) -> MediaExecutor:
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
    sink = ExternalMediaSink(media_root, str(volume.root))

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
    return MediaExecutor(store, gpu_uuid=gpu_uuid, lease_dir=lease_dir, profiles=mine,
                         adapter_factory=adapter_factory or default_adapter_factory(device, lease_dir, env),
                         image_sink=sink, video_sink=None, idle_unload_s=idle)


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
    try:
        return executor.run(idle_sleep=lambda: time.sleep(poll))
    except GpuLeaseError as exc:  # the lease directory became unusable: configuration, not a crash
        print(f"media executor: GPU lease configuration refused: {exc}", file=sys.stderr)
        return EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main())
