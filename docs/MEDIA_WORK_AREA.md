# Private work area on the internal disk

**Anders' decision, 6 Nov 2026 (#2275 6686905826):** media is generated on the internal disk and published on the external one. The two disks each have one job:

| | Where | What is there | Checked by |
|---|---|---|---|
| **Work area** | a private folder on the internal disk (C:) | ComfyUI's input, output, temp and user folders (partial frames and videos), the staged source image of an image-to-video job, the job database | `worker/app/media_work_area.py`, `PrivateWorkArea` |
| **Publication volume** | the external disk (for example Z:) | the gallery, its index, staged files | `worker/app/media_volume.py`, `MountedMediaVolume` (G1, `docs/MEDIA_VOLUME.md`) |

**The hand-off.**
1. A finished file is checked (size, MP4 header, unchanged while copied) and copied from the work area into a staged file on the publication volume (#2347).
2. The staged file is synced (`fsync`). A delayed write error, such as a full disk, fails the job here; it is never a silent success.
3. Only then is the copy in the work area removed.
4. The staged file is published to the gallery in one atomic rename on that volume. The asset id is derived from the job, so a job can never be published twice.

The copy between the two disks is **not** atomic, which is why the gallery never sees a file until it is complete, synced and published.

**Where a crash leaves things.** A crashed job is failed at the next start ("interrupted by restart"), and the owner resubmits. Nothing partial ever reaches the gallery.

| Crash | In the work area | On the publication volume |
|---|---|---|
| During the render or the copy | the render's output, ComfyUI's temp | a partial staged `.kaliv-*.tmp`, never indexed |
| After the sync, before publication | nothing (already removed) | a complete staged `.kaliv-*.tmp`, never indexed |
| After publication, before the job is recorded | nothing | the published asset, once |

`scripts/media_volume_repair.py` reports all of these (C6); nothing is deleted automatically. A failed job's output is removed from the work area like after any failure, so failed renders do not pile up there. A removal that fails is logged and reported in the adapter's `last_cleanup`, never ignored.

**Status:** the executor's entry point builds the work area at start and keeps the job database in it. Video stays default-off: `media_executor_main` keeps exit 78 for video. When video is wired, the supervisor takes the work area (`ComfySupervisor(work_area=...)`), and ComfyUI's four folders must be inside it.

## What is checked

At start, a failure is exit 78. The folder is local, so a failure there is a configuration that will not fix itself.

- `KALIV_MEDIA_WORK_ROOT` is set, absolute and canonical. That excludes a symlink, a junction, an 8.3 alias, `..`, a UNC path and a `\\?\` prefix.
- It is an existing directory, not a link or reparse point.
- It is on a local disk with stable file ids: NTFS, ReFS, ext4, xfs or btrfs. A network drive or share is refused, and so are FAT32, exFAT and tmpfs. The cleanup after a render deletes only files whose `(st_dev, st_ino)` it recorded, which needs stable file ids.
- It is **private**:
  - **Windows:** owned by the executor's account, SYSTEM or Administrators. No other principal holds any right beyond `SYNCHRONIZE`, `READ_CONTROL` or `FILE_READ_ATTRIBUTES`, so nobody else can list, read, write, delete or re-permission anything. This is the same rule as for credential files.
  - **POSIX:** owned by the executor's user, mode `0700`.
- It is not on the publication volume.
- `KALIV_MEDIA_JOB_DB` is in an existing folder inside the work area. A folder elsewhere, behind a link or on another device is refused.

The root's `(st_dev, st_ino)` is pinned at start. **Before every job-database access**, the work area is checked again, then the publication volume. A work area that changed (another folder at the same path, opened up to other users, replaced by a link) stops the executor (exit 75) before it claims another job. So does a publication volume that is gone or swapped. The restart then refuses with 78 if the work area is still wrong.

On Windows, every folder that is used must itself be private, not only the root. Anyone may traverse on Windows, and a subfolder can carry its own grants.

## Operator setup (once)

Windows, as the account that runs the executor. Groups are named by SID, so this also works on a Danish Windows:

```powershell
$Work = 'C:\Kaliv\media-work'
New-Item -ItemType Directory -Force "$Work\state", "$Work\comfy\input", "$Work\comfy\output", "$Work\comfy\temp", "$Work\comfy\user" | Out-Null
$Me = ([System.Security.Principal.WindowsIdentity]::GetCurrent()).User.Value
icacls $Work /inheritance:r /grant:r "*${Me}:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F"
icacls "$Work\*" /T /C /reset   # everything below inherits exactly that (never /reset the root itself)
icacls $Work
```

The last command should list only that account, `NT AUTHORITY\SYSTEM` and the Administrators group (BUILTIN\Administratorer on a Danish Windows). Then:

```powershell
$env:KALIV_MEDIA_WORK_ROOT = 'C:\Kaliv\media-work'
$env:KALIV_MEDIA_JOB_DB    = 'C:\Kaliv\media-work\state\jobs.sqlite3'
```

Linux or WSL (native only; mixed topologies are not supported):

```bash
install -d -m 700 /var/lib/kaliv/media-work /var/lib/kaliv/media-work/state
export KALIV_MEDIA_WORK_ROOT=/var/lib/kaliv/media-work
export KALIV_MEDIA_JOB_DB=/var/lib/kaliv/media-work/state/jobs.sqlite3
```

**Moving an existing job database** from the old place: stop the executor, so that its lock is free. Copy the file (and its `-wal` and `-shm` files, if present) into `state`. Start the executor, and check that the queue is as before. Then delete the old copy. Nothing moves it automatically.

## Privacy and retention

- **Prompts are on the internal disk** while they are kept. Retention blanks them 30 days after a job finishes (#2340). The private ACL is what keeps other users of the machine out.
- **Partial media is on the internal disk** while a job runs: ComfyUI's frames, the unfinished MP4, and the staged source image.
- **After a crash**, residue can remain in the work area: a render's output that was not yet removed, ComfyUI's temp files, a staged source image. See the crash table above; C6 reports it.
- Media never reaches the cloud; that rule is unchanged.

## Exit codes

| Code | Work area |
|---|---|
| 78 | At start: missing setting, not canonical, a link, not a directory, network or refused filesystem, not private, on the publication volume, or the job database outside it |
| 75 | While running: the work area changed or stopped being private. The restart then gives 78 if it is still wrong |

## Tests

- `tests/worker_media_work_area.py` runs anywhere. It uses real directories, modes, symlinks and FIFOs, and a fake probe only for the filesystem type, a foreign device, a foreign owner and the Windows per-folder ACL. On Linux it also reads a written mountinfo (longest mount wins, escapes) and the real one.
- `tests/worker_media_executor_main.py`:
  - the work area at start (78);
  - the job database inside it;
  - not on the publication volume;
  - a work area opened up while running stops the executor before the next claim (75), with the job still queued.
- `tests/support/windows_media_work_area_contract.py` runs on the Windows gate with the real probe. It covers:
  - NTFS and a local drive;
  - a private folder accepted;
  - a folder Users can read refused;
  - the drive root refused;
  - a subfolder with its own grant refused under a private root;
  - a root opened after start refused;
  - junctions;
  - UNC, `\\?\` and alternate-stream paths.
- Rig (runbook): R1 and R5 use this setup. R14 still unplugs the publication volume.
