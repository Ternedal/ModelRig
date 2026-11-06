"""C6: read-only recovery inventory for the C:/Z: hand-off (ChatGPT 6689780350 P1).

Anders, 6 Nov 2026: media is generated in the private work area on the internal disk (C:) and
published on the external volume (Z:): copy into a staged file on Z:, sync, publish, and only then
remove the copy on C:. A crash or a failed publication can leave pieces on either disk. This module
ties each piece to its job, using the hand-off receipt the executor stored before the copy started
(``image_jobs_handoff``), and says what happened. It changes nothing.

**Per job with a receipt**, the evidence is:

- the work-area file the receipt names, checked by name and by identity (``st_dev``, ``st_ino``,
  size) and, once the receipt is ``copied``, by SHA-256;
- staged ``.kaliv-*.tmp`` files on the volume: a complete one has the receipt's SHA-256; a partial
  one is a byte-exact prefix of the work-area file;
- the job's asset on the volume (the job-keyed id, or the completed job's asset id): present,
  indexed, and its SHA-256;
- the volume's root identity against the one recorded at hand-off;
- for image-to-video, the source asset: present and indexed, and its SHA-256 if one was recorded.

**Classes** (``classification``), decided only when the evidence is unambiguous:

| class | meaning |
|---|---|
| ``interrupted_copy`` | the copy started and never finished; the work-area file is intact |
| ``crash_after_sync_before_publication`` | a complete, synced copy is staged; nothing is published |
| ``publication_failed`` | the copy finished, publication failed, the work-area file was kept |
| ``crash_after_publication_before_cleanup`` | published and indexed once (same SHA-256); the work-area copy is still there |
| ``published_unindexed`` | the file is published (same SHA-256) but the gallery index was not updated; the work-area copy is kept |
| ``volume_changed`` | the volume's root is not the one the job handed over to: nothing on it is correlated |
| ``unknown`` | anything else, including two candidates for one piece |

``source`` is ``present``, ``missing``, ``changed`` or ``unverified`` (no hash was recorded).
Pieces no job claims are listed under ``unattributed``, as ``unknown``.

**Never:** a prompt, an owner or job parameters in the output (only the job id, its state and error
code, file names, sizes, ids and hashes); a link or reparse point followed; a file name used that is
not a plain name; any change to any file. While an executor runs, nothing is classified (its files
are in flight): the report says so and stops.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import time
from pathlib import Path

from .media_gallery_catalog import GalleryUnavailable, _index
from .media_gallery_store import ExternalMediaSink
from .media_generation_contract import MAX_ARTIFACT_BYTES, ArtifactSinkUnavailable
from .media_repair import RepairRefused, _scratch_dir, executors_running
from .media_work_area import PrivateWorkArea

SCHEMA = "kaliv-media-recovery-inventory/v1"
_TEMP = re.compile(r"[.]kaliv-[A-Za-z0-9_-]{8,}[.]tmp\Z")
_PLAIN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_ASSET = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_CHUNK = 1024 * 1024
_NOFOLLOW = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)


def _is_reparse(info) -> bool:
    return bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _regular(path: Path):
    """lstat of a plain regular file (not a link or reparse point), or None."""
    try:
        info = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode) or _is_reparse(info):
        return None
    return info


def _hash(path: Path, expected, limit: int | None = None) -> str | None:
    """SHA-256 of the file at ``path`` (of its first ``limit`` bytes), read through a handle that
    is checked to be the same file as ``expected`` before and after. None if it is not."""
    try:
        fd = os.open(path, _NOFOLLOW)
    except OSError:
        return None
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or (before.st_dev, before.st_ino) != (expected.st_dev, expected.st_ino)
                or before.st_size > MAX_ARTIFACT_BYTES):
            return None
        digest, remaining = hashlib.sha256(), before.st_size if limit is None else min(limit, before.st_size)
        if limit is not None and limit > before.st_size:
            return None
        while remaining:
            chunk = os.read(fd, min(_CHUNK, remaining))
            if not chunk:
                return None
            digest.update(chunk)
            remaining -= len(chunk)
        after = os.fstat(fd)
        if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            return None
        return digest.hexdigest()
    finally:
        os.close(fd)


def _read_jobs(job_db: str) -> tuple[list[dict], dict[str, dict]]:
    """Job rows (id, state, error, asset id, the source asset id only) and hand-off receipts."""
    if not os.path.isfile(job_db) or os.path.islink(job_db):
        raise RepairRefused("job_db_missing")
    try:
        db = sqlite3.connect(Path(job_db).resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise RepairRefused("job_db_unreadable") from exc
    try:
        rows = db.execute("SELECT id, state, error, asset_id, params FROM image_jobs").fetchall()
        has_receipts = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                                  "AND name='image_jobs_handoff'").fetchone() is not None
        receipts = dict(db.execute("SELECT job_id, record FROM image_jobs_handoff").fetchall()) if has_receipts else {}
    except sqlite3.Error as exc:
        raise RepairRefused("job_db_unreadable") from exc
    finally:
        db.close()
    jobs = []
    for job_id, state, error, asset_id, params in rows:
        try:
            source = json.loads(params).get("input_asset_id")  # the only parameter read, never output
        except (TypeError, ValueError, AttributeError):
            source = None
        jobs.append({"id": job_id, "state": state, "error": error, "asset_id": asset_id,
                     "source_asset_id": source if isinstance(source, str) and _ASSET.fullmatch(source) else None})
    parsed = {}
    for job_id, record in receipts.items():
        try:
            value = json.loads(record)
        except ValueError:
            continue
        if isinstance(value, dict):
            parsed[job_id] = value
    return jobs, parsed


def recovery_inventory(sink: ExternalMediaSink, job_db: str, *, work_area: PrivateWorkArea, output_dir: str,
                       lease_dir: str) -> dict:
    """Read-only: what the C:/Z: hand-off left behind, job by job. See the module docstring."""
    root = sink._root()  # ArtifactSinkUnavailable: nothing is inspected
    output = Path(_scratch_dir(work_area, output_dir))
    report = {"schema": SCHEMA, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    running = executors_running(lease_dir)
    if running:
        report.update(status="executor_running", executors_running=running, jobs=[], unattributed=[])
        return report
    jobs, receipts = _read_jobs(job_db)
    try:
        indexed = {item["id"] for item in _index(root)} if (root / "gallery-index.json").exists() else set()
    except GalleryUnavailable as exc:
        raise ArtifactSinkUnavailable("repair_index_unavailable") from exc
    volume_now = os.stat(sink.volume_root)
    temps = {}
    for entry in sorted(os.scandir(root), key=lambda e: e.name):
        info = _regular(Path(entry.path)) if _TEMP.fullmatch(entry.name) else None
        if info is not None:
            temps[entry.name] = info
    work_files = {}
    for entry in sorted(os.scandir(output), key=lambda e: e.name):
        info = _regular(Path(entry.path)) if _PLAIN_NAME.fullmatch(entry.name) else None
        work_files[entry.name] = info  # None: a link, a folder or an odd name, never followed
    temp_hash: dict[str, str | None] = {}
    claimed_temps: set[str] = set()
    claimed_files: set[str] = set()
    results = []
    for job in jobs:
        receipt = receipts.get(job["id"])
        if receipt is None:
            continue
        entry = _classify(job, receipt, sink=sink, root=root, indexed=indexed, volume_now=volume_now,
                          output=output, work_files=work_files, temps=temps, temp_hash=temp_hash)
        claimed_temps.update(entry.pop("_temps"))
        claimed_files.update(entry.pop("_files"))
        if entry["classification"] != "clean" or entry["source"] in ("missing", "changed"):
            results.append(entry)
    unattributed = ([{"where": "work_area", "name": name, "classification": "unknown",
                      "kind": "file" if info is not None else "other"}
                     for name, info in work_files.items() if name not in claimed_files]
                    + [{"where": "volume", "name": name, "classification": "unknown", "size_bytes": info.st_size}
                       for name, info in temps.items() if name not in claimed_temps])
    sink._root()
    work_area.require(str(output))
    report.update(status="ok", executors_running=[], jobs=results, unattributed=unattributed,
                  counts={"jobs_with_receipt": len(receipts), "listed": len(results),
                          "unattributed": len(unattributed)})
    return report


def _classify(job: dict, receipt: dict, *, sink, root: Path, indexed: set[str], volume_now, output: Path,
              work_files: dict, temps: dict, temp_hash: dict) -> dict:
    stage, recorded = receipt.get("stage"), receipt.get("output") or {}
    sha, size = receipt.get("sha256"), receipt.get("size")
    entry = {"job_id": job["id"], "state": job["state"], "error": job["error"], "stage": stage,
             "work_file": None, "staged": None, "asset": None, "source": "none", "_temps": set(), "_files": set()}

    # The volume the job handed over to.
    volume = receipt.get("volume")
    if isinstance(volume, dict) and (volume.get("dev"), volume.get("ino")) != (volume_now.st_dev, volume_now.st_ino):
        entry["classification"] = "volume_changed"
        return entry

    # The work-area file the receipt names.
    name = recorded.get("name") if isinstance(recorded.get("name"), str) else None
    work_info = work_files.get(name) if name and _PLAIN_NAME.fullmatch(name) else None
    if name in work_files:
        entry["_files"].add(name)
    if work_info is None:
        entry["work_file"] = {"name": name, "status": "absent" if name not in work_files else "not_a_plain_file"}
    elif (work_info.st_dev, work_info.st_ino, work_info.st_size) != (recorded.get("dev"), recorded.get("ino"),
                                                                     recorded.get("size")):
        entry["work_file"] = {"name": name, "status": "changed"}
    else:
        status = "intact"
        if sha is not None:
            status = "intact" if _hash(output / name, work_info) == sha else "changed"
        entry["work_file"] = {"name": name, "status": status, "size_bytes": work_info.st_size}
    work_intact = entry["work_file"]["status"] == "intact"

    # Staged copies on the volume: a complete one by hash, a partial one as a prefix of the work file.
    complete, partial = [], []
    for temp, info in temps.items():
        if temp not in temp_hash:
            temp_hash[temp] = _hash(root / temp, info)
        if sha is not None and temp_hash[temp] == sha:
            complete.append(temp)
        elif (work_intact and 0 < info.st_size < work_info.st_size
              and _hash(output / name, work_info, limit=info.st_size) == temp_hash[temp]):
            partial.append(temp)
    entry["_temps"].update(complete + partial)
    if len(complete) + len(partial) > 1:
        entry["staged"] = {"status": "ambiguous", "names": sorted(complete + partial)}
    elif complete:
        entry["staged"] = {"status": "complete", "name": complete[0]}
    elif partial:
        entry["staged"] = {"status": "partial", "name": partial[0], "size_bytes": temps[partial[0]].st_size}
    else:
        entry["staged"] = {"status": "absent"}

    # The published asset.
    asset_id = job["asset_id"] if job["state"] == "completed" and job["asset_id"] else _job_asset(sink, job["id"])
    asset_path = root / f"{asset_id}.mp4" if asset_id else None
    asset_info = _regular(asset_path) if asset_path else None
    if asset_info is None:
        entry["asset"] = {"status": "absent"}
    else:
        same = sha is not None and _hash(asset_path, asset_info) == sha
        entry["asset"] = {"status": "same" if same else "different", "asset_id": asset_id,
                          "indexed": asset_id in indexed}

    # The source of an image-to-video job.
    source_id = job.get("source_asset_id")
    if source_id:
        source_path = root / f"{source_id}.png"
        source_info = _regular(source_path)
        if source_info is None or source_id not in indexed:
            entry["source"] = "missing"
        elif receipt.get("source_sha256"):
            entry["source"] = "present" if _hash(source_path, source_info) == receipt["source_sha256"] else "changed"
        else:
            entry["source"] = "unverified"

    entry["classification"] = _decide(job, stage, entry, work_intact)
    return entry


def _job_asset(sink: ExternalMediaSink, job_id: str) -> str | None:
    try:
        return sink.job_asset_id(job_id)
    except ValueError:
        return None


def _decide(job: dict, stage: str, entry: dict, work_intact: bool) -> str:
    staged, asset, work = entry["staged"]["status"], entry["asset"]["status"], entry["work_file"]["status"]
    if staged == "ambiguous" or asset == "different":
        return "unknown"
    if asset == "same":
        if work == "intact" and not entry["asset"]["indexed"]:
            return "published_unindexed"  # the gallery index was not updated (registration failed)
        if work == "intact":
            return "crash_after_publication_before_cleanup"
        if work == "absent" and staged == "absent" and job["state"] == "completed":
            return "clean"
        return "unknown"
    if job["state"] == "completed":
        return "unknown"  # completed without its asset: the existing C6 report lists it too
    if stage == "copying" and work_intact and staged in ("partial", "absent"):
        return "interrupted_copy"
    if stage == "copied" and work_intact and staged == "complete":
        return "crash_after_sync_before_publication"
    if stage == "copied" and work_intact and staged == "absent":
        return "publication_failed"
    if work == "absent" and staged == "absent" and job["state"] in ("failed", "cancelled"):
        return "clean"  # a failed or cancelled job that left nothing
    return "unknown"
