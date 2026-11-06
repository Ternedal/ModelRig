"""C6: reconcile the media volume with the job database, plus two explicit operator repairs.

**What can be left behind.** A crash or a lost volume can leave three kinds of residue on the
media volume:
- **A published file the index does not list.** The executor stopped between publication and
  registration, or after registration but before ``complete()``.
- **A staged or temporary ``.kaliv-<hex>.tmp`` file.** The sink does not touch the volume while
  it is gone (#2347). C2's end-to-end test shows that case.
- **An index entry whose file is missing.**

**The work area on the internal disk** (Anders, 6 Nov 2026; ``docs/MEDIA_WORK_AREA.md``) can hold
residue too: a render's output, ComfyUI's temp files or a staged source image, left by a crash
before the adapter's cleanup ran. ``reconcile(..., work_area=, work_dirs=)`` lists files older than
the minimum age in the named scratch folders, and ``remove_work_file`` removes one of them, named
exactly, by the same capture-check-remove steps as ``remove_stale_temp``. The job database and its
``-wal``, ``-shm`` and ``-journal`` files are never listed and never removed.

**Automation.** None of this is deleted or adopted automatically: ``inspect_unindexed_assets``
says so, and Anders' rule is no automatic deletion. ``reconcile()`` is read-only.

**The two repairs.** An operator runs each one per item, naming it exactly, and only while no
executor runs:
- ``adopt``: register an unindexed file whose job is **completed with that asset**. Any other
  state is reported, never adopted.
- ``remove_stale_temp``: remove one ``.kaliv-*.tmp`` file that matches the device and inode from
  the report and is older than the minimum age. The file is first captured by rename, then
  re-checked, then removed. Anything else is put back.

**Privacy.** The report never contains a prompt, an owner or job parameters. The job database is
opened read-only, and only ``id``, ``state``, ``asset_id``, ``error`` and ``updated`` are read.
"""
from __future__ import annotations

import os
import re
import secrets
import sqlite3
import stat
import time
from contextlib import contextmanager
from pathlib import Path

from .gpu_lease import EXECUTOR_SUFFIX, ExecutorAlreadyRunning, acquire_executor_lock
from .media_gallery_catalog import GalleryUnavailable, _index
from .media_gallery_index_writer import register_asset
from .media_gallery_store import ExternalMediaSink
from .media_generation_contract import ArtifactSinkUnavailable
from .media_work_area import PrivateWorkArea

SCHEMA = "kaliv-media-repair-report/v1"
DEFAULT_MINIMUM_AGE_S = 6 * 3600
_TEMP = re.compile(r"[.]kaliv-[A-Za-z0-9_-]{8,}[.]tmp\Z")
_QUARANTINE = re.compile(r"[.]kaliv-repair-[0-9a-f]{16}[.]quarantine\Z")
_EXTENSION_KIND = {".png": "image", ".mp4": "video"}


class RepairRefused(RuntimeError):
    """The repair was not performed. The message says why; nothing was changed."""


def _jobs(job_db: str) -> list[dict]:
    """The job rows, read-only, without prompts, owners or parameters."""
    if not os.path.isfile(job_db) or os.path.islink(job_db):
        raise RepairRefused("job_db_missing")
    uri = Path(job_db).resolve().as_uri() + "?mode=ro"
    try:
        db = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise RepairRefused("job_db_unreadable") from exc
    try:
        rows = db.execute("SELECT id, state, asset_id, error, updated FROM image_jobs").fetchall()
    except sqlite3.Error as exc:
        raise RepairRefused("job_db_unreadable") from exc
    finally:
        db.close()
    return [{"id": r[0], "state": r[1], "asset_id": r[2], "error": r[3], "updated": r[4]} for r in rows]


def executors_running(lease_dir: str) -> list[str]:
    """The GPU UUIDs whose executor lock is held right now (probing takes and releases it)."""
    running = []
    try:
        names = sorted(os.listdir(lease_dir))
    except OSError as exc:
        raise RepairRefused("lease_dir_unreadable") from exc
    for name in names:
        if not name.endswith(EXECUTOR_SUFFIX):
            continue
        gpu = name[:-len(EXECUTOR_SUFFIX)]
        try:
            lock = acquire_executor_lock(gpu, lease_dir=lease_dir)
        except ExecutorAlreadyRunning:
            running.append(gpu)
            continue
        except Exception:
            running.append(gpu)  # cannot prove it is free: treat as running
            continue
        lock.release()
    return running


_JOB_DB_SIDECARS = ("", "-wal", "-shm", "-journal")
_MAX_WORK_ENTRIES = 10_000


def _job_db_files(job_db: str | None) -> set[str]:
    if not job_db:
        return set()
    base = os.path.normcase(os.path.abspath(job_db))
    return {base + suffix for suffix in _JOB_DB_SIDECARS}


def _scratch_dir(area: PrivateWorkArea, directory: str) -> str:
    """A scratch folder that is an existing directory inside the verified work area, never its root."""
    area.require(directory)  # ArtifactSinkUnavailable: canonical, inside, private, no links
    path = os.path.normpath(directory)
    if not os.path.isdir(path) or os.path.normcase(path) == os.path.normcase(str(area.root)):
        raise RepairRefused("not_a_work_scratch_directory")
    return path


def work_area_residue(area: PrivateWorkArea, directories, *, job_db: str | None = None,
                      minimum_age_seconds: int = DEFAULT_MINIMUM_AGE_S) -> list[dict]:
    """Files older than the minimum age in the named scratch folders of the work area. Read-only.

    Links are reported and never followed; directories are walked. Never lists the job database or
    its sidecar files. Each entry carries what ``remove_work_file`` needs to name it exactly."""
    excluded = _job_db_files(job_db)
    now = time.time()
    found: list[dict] = []
    for directory in directories:
        top = _scratch_dir(area, directory)
        pending = [top]
        while pending:
            current = pending.pop()
            try:
                entries = sorted(os.scandir(current), key=lambda e: e.name)
            except OSError as exc:
                raise RepairRefused("work_directory_unreadable") from exc
            for entry in entries:
                if len(found) >= _MAX_WORK_ENTRIES:
                    raise RepairRefused("work_area_residue_too_large")
                path = entry.path
                if os.path.normcase(os.path.abspath(path)) in excluded:
                    continue
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode) and not entry.is_symlink() and not _is_reparse(info):
                    pending.append(path)
                    continue
                kind = ("file" if stat.S_ISREG(info.st_mode) and not _is_reparse(info)
                        else "link" if entry.is_symlink() or _is_reparse(info) else "other")
                if kind == "file" and now - info.st_mtime < minimum_age_seconds:
                    continue
                found.append({"directory": top, "path": os.path.relpath(path, top), "kind": kind,
                              "size_bytes": info.st_size if kind == "file" else None,
                              "age_hours": round((now - info.st_mtime) / 3600, 1),
                              "device": info.st_dev, "inode": info.st_ino})
    return found


def _is_reparse(info) -> bool:
    return bool(getattr(info, "st_file_attributes", 0) & 0x400)


def reconcile(sink: ExternalMediaSink, job_db: str, *, lease_dir: str | None = None,
              minimum_age_seconds: int = DEFAULT_MINIMUM_AGE_S, work_area: PrivateWorkArea | None = None,
              work_dirs=()) -> dict:
    """Read-only report of what the volume and the job database disagree on, and of what is left
    in the work area's scratch folders when ``work_area`` and ``work_dirs`` are given."""
    root = sink._root()  # ArtifactSinkUnavailable: nothing is inspected
    jobs = _jobs(job_db)
    by_asset = {j["asset_id"]: j for j in jobs if j["asset_id"]}
    by_key = {sink.job_asset_id(j["id"]): j for j in jobs if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", j["id"])}
    try:
        indexed = _index(root) if (root / "gallery-index.json").exists() else []
    except GalleryUnavailable as exc:
        raise ArtifactSinkUnavailable("repair_index_unavailable") from exc

    unindexed = []
    for name in sink.inspect_unindexed_assets():
        asset_id, extension = name[:32], name[32:]
        job = by_asset.get(asset_id) or by_key.get(asset_id)
        if job is None:
            status = "no_job"
        elif job["state"] == "completed" and job["asset_id"] == asset_id:
            status = "adoptable"  # the job finished with this asset; only the index row is missing
        else:
            status = f"job_{job['state']}"
        size = (root / name).lstat().st_size
        unindexed.append({"asset_id": asset_id, "extension": extension, "size_bytes": size, "status": status,
                          "job_id": job["id"] if job else None,
                          "job_error": job["error"] if job else None})

    missing = [{"asset_id": item["id"], "kind": item["kind"]} for item in indexed
               if not (root / (item["id"] + (".mp4" if item["kind"] == "video" else ".png"))).is_file()]
    indexed_ids = {item["id"] for item in indexed}
    completed_unpublished = [{"job_id": j["id"], "asset_id": j["asset_id"]} for j in jobs
                             if j["state"] == "completed" and j["asset_id"] and j["asset_id"] not in indexed_ids
                             and not any(u["asset_id"] == j["asset_id"] for u in unindexed)]
    stale = sink.inspect_temporary_file_candidates(minimum_age_seconds=minimum_age_seconds)
    quarantined = sorted(p.name for p in root.iterdir() if _QUARANTINE.fullmatch(p.name))
    residue = (work_area_residue(work_area, work_dirs, job_db=job_db, minimum_age_seconds=minimum_age_seconds)
               if work_area is not None else None)
    if residue is not None:
        for directory in work_dirs:
            top = os.path.normpath(directory)
            quarantined += sorted(os.path.join(top, n) for n in os.listdir(top) if _QUARANTINE.fullmatch(n))
    sink._root()
    return {
        "schema": SCHEMA,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "minimum_age_seconds": minimum_age_seconds,
        "executors_running": executors_running(lease_dir) if lease_dir else None,
        "unindexed_assets": unindexed,
        "indexed_but_missing": missing,
        "completed_jobs_without_asset": completed_unpublished,
        "stale_temporary_files": stale,
        "quarantined": quarantined,
        "work_area_residue": residue,
        "counts": {"jobs": len(jobs), "indexed": len(indexed), "unindexed": len(unindexed),
                   "adoptable": sum(1 for u in unindexed if u["status"] == "adoptable"),
                   "indexed_but_missing": len(missing), "stale_temporary_files": len(stale),
                   "work_area_residue": len(residue) if residue is not None else None},
    }


@contextmanager
def _executors_held(lease_dir: str):
    """Hold every known executor lock for the whole repair, so no executor can start meanwhile.

    One that is running already refuses the repair.
    """
    held = []
    try:
        try:
            names = sorted(os.listdir(lease_dir))
        except OSError as exc:
            raise RepairRefused("lease_dir_unreadable") from exc
        for name in names:
            if name.endswith(EXECUTOR_SUFFIX):
                try:
                    held.append(acquire_executor_lock(name[:-len(EXECUTOR_SUFFIX)], lease_dir=lease_dir))
                except Exception:
                    raise RepairRefused("executor_running") from None
        yield
    finally:
        for lock in held:
            lock.release()


def adopt(sink: ExternalMediaSink, job_db: str, asset_id: str, *, lease_dir: str) -> dict:
    """Register one unindexed asset whose job completed with exactly that asset."""
    with _executors_held(lease_dir):
        return _adopt(sink, job_db, asset_id)


def _adopt(sink: ExternalMediaSink, job_db: str, asset_id: str) -> dict:
    report = reconcile(sink, job_db)
    entry = next((u for u in report["unindexed_assets"] if u["asset_id"] == asset_id), None)
    if entry is None:
        raise RepairRefused("not_an_unindexed_asset")
    if entry["status"] != "adoptable":
        raise RepairRefused(f"not_adoptable:{entry['status']}")
    try:
        register_asset(sink.media_root, sink.volume_root, asset_id, entry["extension"], entry["size_bytes"])
    except (GalleryUnavailable, ValueError) as exc:
        raise RepairRefused(f"register_refused:{exc}") from exc
    return {"adopted": asset_id, "kind": _EXTENSION_KIND[entry["extension"]], "job_id": entry["job_id"]}


def remove_stale_temp(sink: ExternalMediaSink, name: str, *, device: int, inode: int, lease_dir: str,
                      minimum_age_seconds: int = DEFAULT_MINIMUM_AGE_S) -> dict:
    """Remove one stale temporary file, but only the exact one the operator named."""
    if type(name) is not str or not _TEMP.fullmatch(name):
        raise RepairRefused("not_a_temporary_name")
    with _executors_held(lease_dir):
        return _remove(sink, name, device, inode, minimum_age_seconds)


def _remove(sink: ExternalMediaSink, name: str, device: int, inode: int, minimum_age_seconds: int) -> dict:
    root = sink._root()
    current = {c["name"]: c for c in sink.inspect_temporary_file_candidates(minimum_age_seconds=minimum_age_seconds)}
    candidate = current.get(name)
    if candidate is None:
        raise RepairRefused("not_a_stale_candidate")
    if (candidate["device"], candidate["inode"]) != (device, inode):
        raise RepairRefused("identity_changed")
    original = root / name
    captured = root / f".kaliv-repair-{secrets.token_hex(8)}.quarantine"
    try:
        os.rename(original, captured)  # atomic: captures exactly the file under that name now
    except OSError as exc:
        raise RepairRefused("capture_failed") from exc
    info = os.lstat(captured)
    if stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == (device, inode):
        sink._root()
        os.unlink(captured)
        return {"removed": name, "size_bytes": info.st_size}
    # Not the file the operator named: put it back without overwriting anything.
    try:
        if os.name == "nt":
            os.rename(captured, original)  # refuses an existing target on Windows
        else:
            os.link(captured, original)  # refuses an existing target
            os.unlink(captured)
    except OSError:
        raise RepairRefused(f"identity_changed; left as {captured.name}") from None
    raise RepairRefused("identity_changed")


def remove_work_file(area: PrivateWorkArea, directory: str, relative: str, *, device: int, inode: int,
                     lease_dir: str, job_db: str | None = None,
                     minimum_age_seconds: int = DEFAULT_MINIMUM_AGE_S) -> dict:
    """Remove one residue file from a work-area scratch folder, but only the exact one named."""
    if (type(relative) is not str or not relative or os.path.isabs(relative)
            or any(part in ("", ".", "..") or ":" in part for part in relative.replace("\\", "/").split("/"))):
        raise RepairRefused("not_a_relative_path")
    with _executors_held(lease_dir):
        return _remove_work(area, directory, relative, device, inode, job_db, minimum_age_seconds)


def _remove_work(area, directory, relative, device, inode, job_db, minimum_age_seconds) -> dict:
    top = _scratch_dir(area, directory)
    current = {(c["directory"], c["path"]): c
               for c in work_area_residue(area, [top], job_db=job_db, minimum_age_seconds=minimum_age_seconds)}
    candidate = current.get((top, os.path.normpath(relative)))
    if candidate is None or candidate["kind"] != "file":
        raise RepairRefused("not_a_residue_file")
    if (candidate["device"], candidate["inode"]) != (device, inode):
        raise RepairRefused("identity_changed")
    original = os.path.join(top, os.path.normpath(relative))
    parent = os.path.dirname(original)
    area.require(parent)
    captured = os.path.join(parent, f".kaliv-repair-{secrets.token_hex(8)}.quarantine")
    try:
        os.rename(original, captured)  # atomic: captures exactly the file under that name now
    except OSError as exc:
        raise RepairRefused("capture_failed") from exc
    info = os.lstat(captured)
    if stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == (device, inode):
        area.require(parent)
        os.unlink(captured)
        return {"removed": os.path.normpath(relative), "directory": top, "size_bytes": info.st_size}
    try:
        if os.name == "nt":
            os.rename(captured, original)  # refuses an existing target on Windows
        else:
            os.link(captured, original)  # refuses an existing target
            os.unlink(captured)
    except OSError:
        raise RepairRefused(f"identity_changed; left as {os.path.basename(captured)}") from None
    raise RepairRefused("identity_changed")
