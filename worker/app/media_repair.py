"""C6: reconcile the media volume with the job database, plus two explicit operator repairs.

**What can be left behind.** A crash or a lost volume can leave three kinds of residue on the
media volume:
- **A published file the index does not list.** The executor stopped between publication and
  registration, or after registration but before ``complete()``.
- **A staged or temporary ``.kaliv-<hex>.tmp`` file.** The sink does not touch the volume while
  it is gone (#2347). C2's end-to-end test shows that case.
- **An index entry whose file is missing.**

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


def reconcile(sink: ExternalMediaSink, job_db: str, *, lease_dir: str | None = None,
              minimum_age_seconds: int = DEFAULT_MINIMUM_AGE_S) -> dict:
    """Read-only report of what the volume and the job database disagree on."""
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
        "counts": {"jobs": len(jobs), "indexed": len(indexed), "unindexed": len(unindexed),
                   "adoptable": sum(1 for u in unindexed if u["status"] == "adoptable"),
                   "indexed_but_missing": len(missing), "stale_temporary_files": len(stale)},
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
