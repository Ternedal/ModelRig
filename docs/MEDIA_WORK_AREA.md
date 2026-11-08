# Private work area on the internal disk

**Anders' decision, 6 Nov 2026 (#2275 6686905826):** media is generated on the internal disk and published on the external one. The two disks each have one job:

| | Where | What is there | Checked by |
|---|---|---|---|
| **Work area** | a private folder on the internal disk (C:) | ComfyUI's input, output, temp and user folders (partial frames and videos), the staged source image of an image-to-video job, the job database | `worker/app/media_work_area.py`, `PrivateWorkArea` |
| **Publication volume** | the external disk (for example Z:) | the gallery, its index, staged files | `worker/app/media_volume.py`, `MountedMediaVolume` (G1, `docs/MEDIA_VOLUME.md`) |

**The hand-off** (the executor holds the adapter's copy with `adapter.holding_outputs()` until publication is done):
1. A finished file is checked (size, MP4 header, unchanged while copied) and copied from the work area into a staged file on the publication volume (#2347).
2. The staged file is synced (`fsync`, through the staged handle's `sync()`, #2347, which reveals no path). A delayed write error, such as a full disk, fails the job here; it is never a silent success.
3. The staged file is published to the gallery in one atomic rename on that volume, keyed by the job, and registered in the index. A job can never be published twice.
4. **Only then** is the copy in the work area removed.

The copy between the two disks is **not** atomic, which is why the gallery never sees a file until it is complete, synced and published.

**When publication does not succeed.**
- The owner cancelled before publication: the work-area copy is removed (the owner's choice).
- Anything else once the render is finished (the volume could not take the copy, it went away, the sink refused it, registration failed): the work-area copy is **kept** for recovery. The adapter reports it in `last_cleanup["kept_for_recovery"]`, and C6 lists it.
- A render that fails before it is finished, or turns out not to be a valid MP4 within the size cap, leaves no finished file. Its output is removed at once, so failed renders do not pile up.
- **Hand-off receipts:** before the first byte is copied, the executor stores a receipt for the job (`image_jobs_handoff`). It names the output, its `st_dev`, `st_ino` and size, and the volume root's identity. After the sync it adds the SHA-256. If a receipt cannot be stored, the job fails before anything is copied. C6's `inventory` uses the receipts to tie leftovers to their job (`docs/MEDIA_REPAIR.md`).

**Where a crash leaves things.** A crashed job is failed at the next start (`interrupted_by_restart` or `interrupted_during_publication`), and the owner resubmits. Nothing partial ever reaches the gallery, and a finished file is never only on a disk where it could be lost: until it is published, the work-area copy exists.

| Crash | In the work area | On the publication volume |
|---|---|---|
| During the render or the copy | the render's output, ComfyUI's temp, the staged source image | a partial staged `.kaliv-*.tmp`, never indexed |
| After the sync, before publication | the finished render | a complete staged `.kaliv-*.tmp`, never indexed |
| After publication, before the work-area copy is removed | the finished render | the published asset, once |

`scripts/media_volume_repair.py` reports all of these (C6); nothing is deleted or republished automatically. An operator removes each leftover by name, and the owner resubmits. A removal that fails is logged and reported in the adapter's `last_cleanup`, never ignored.

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

On Windows, every folder and file that is used must itself be private, not only the root. Anyone may traverse on Windows, and a subfolder or file can carry its own grants. A file **moved** in from elsewhere on the same disk keeps the ACL it had there, so at start the job database and its `-wal`, `-shm` and `-journal` files are checked as well (exit 78 if another user could read them).

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

**Moving an existing job database** from the old place: stop the executor, so that its lock is free. **Copy** the file (never move it: a move on the same disk keeps its old permissions, and the executor then refuses it) (and its `-wal` and `-shm` files, if present) into `state`. Start the executor, and check that the queue is as before. Then delete the old copy. Nothing moves it automatically.

## Accounts (a deployment gate)

Only the executor's account (plus SYSTEM and Administrators) can open the work area, and so the job database. Anything else that reads the job database, such as the gallery routes in the API worker, must run as **that same account**. No broader ACL is granted to make another account work.

- **Verified in code (main `cc2b28a6`):** `modelrig-supervisor` starts the worker, the server and the media executor itself, with `exec.Command` and no change of credentials (`backend/cmd/modelrig-supervisor/main.go`, `executor.go`). So on the appliance all three run as the supervisor's account.
- **Not verified:** a worker or route started some other way, for example by hand or as a separate service. The OS then denies it access to the job database, which fails closed.
- **Rig preflight (R17, before enabling media; the full pack is `docs/MEDIA_R17_DEPLOYMENT_PROOF.md`, and `scripts/media_work_area_preflight.py --pid ...` checks the same programmatically):**

```powershell
whoami /user
icacls $env:KALIV_MEDIA_WORK_ROOT
icacls "$env:KALIV_MEDIA_WORK_ROOT\state\jobs.sqlite3"
Get-CimInstance Win32_Process -Filter "Name LIKE 'modelrig-%' OR (Name='python.exe' AND CommandLine LIKE '%media_executor_main%')" |
  ForEach-Object { "{0} {1} {2}" -f $_.ProcessId, $_.Name, (Invoke-CimMethod -InputObject $_ -MethodName GetOwner).User }
```

Expected: `modelrig-supervisor`, `modelrig-worker-windows-x64`, `modelrig-server-windows-x64` and the executor's `python.exe` all have the same owner as `whoami`. The two ACLs list only that account's SID, `NT AUTHORITY\SYSTEM` and the Administrators group.

## Privacy and retention

- **Prompts are on the internal disk** while they are kept. Retention blanks them 30 days after a job finishes (#2340). The private ACL is what keeps other users of the machine out.
- **Partial media is on the internal disk** while a job runs: ComfyUI's frames, the unfinished MP4, and the staged source image.
- **After a crash**, residue can remain in the work area: a render's output that was not yet removed, ComfyUI's temp files, a staged source image. See the crash table above; C6 reports it.
- Media never reaches the cloud; that rule is unchanged.

## Output names on Windows

ComfyUI names its output in the work area. That name is used in two places: the adapter opens the file by it, and the hand-off receipt records it so C6 can find the file after a crash. **The published file on Z: never carries it:** the sink names the file after a new asset id.

A Linux name check does not prove a Windows name safe (ChatGPT #2357 6716735710). The two places therefore share one rule, `is_plain_file_name`. The adapter adds one more check before it opens anything by name: the name must be one the directory itself lists. Each case is handled like this:

| Case | Example | What happens |
|---|---|---|
| Device name, any case, any extension | `CON.mp4`, `nul.mp4`, `COM1.mp4`, `LPT¹.mp4`, `aux .mp4` | Refused by the rule before any filesystem call, so nothing opens a device |
| Character Win32 refuses | `a?b.mp4`, `a"b.mp4`, `a|b.mp4` | Refused by the rule |
| Trailing space or dot (Win32 strips them, so `x.mp4.` would open `x.mp4`) | `x.mp4.` | Refused by the rule. A video output must also end in `.mp4` |
| Longer than NTFS allows | more than 255 UTF-16 code units; an emoji is two | Refused by the rule. The limit is counted in UTF-16, as NTFS counts it |
| 8.3 alias or another case of an existing name | `KALIV_~1.MP4` for `kaliv_00001_.mp4` | Not listed by the directory, so it is refused. Cleanup skips such a name, so it never deletes the older file the alias reaches |
| Spaces, accents, any script, emoji | `rød drage 🐉.mp4` | Accepted. The receipt keeps the exact name; nothing is normalized |

**On a refusal:**
- The adapter fails the job with a `GenerationError`.
- No byte reaches Z:, and no receipt names the file.
- Cleanup deletes only names it accepts and the directory lists, and only a file or a link (removing a link leaves its target alone). A directory, FIFO, socket or device node is never the render. Like a file it cannot tie to the job, it is kept and reported as untracked.
- The operator's workflow template picks the name through its `filename_prefix`. Keep that prefix free of the refused cases above, and a refusal then means ComfyUI reported a name it did not write.

**Rig check (with R1):**
1. Set the workflow's `filename_prefix` to `rød drage 🐉` and run one video job.
2. Expect the file to be published on Z: under an asset id.
3. Expect the receipt to hold the exact name.
4. Expect nothing left in the work area.

The Linux tests cannot show this, because ext4 has no device names, no 8.3 aliases and is case-sensitive.

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
- `tests/worker_comfy_video_adapter.py` and `tests/worker_image_job_store.py` cover the output-name rule: device names, Win32-refused characters, a trailing dot or space, the UTF-16 length, and a name the directory does not list. Windows' alias lookup is simulated, because ext4 has none.
- Rig (runbook): R1 and R5 use this setup, and R1 adds the Unicode output name above. R14 still unplugs the publication volume.
