# Media volume repair (C6)

A crash, or a lost volume, can leave three kinds of residue on the media volume, and leftovers in the private work area on the internal disk (Anders, 6 Nov 2026; `docs/MEDIA_WORK_AREA.md`). `scripts/media_volume_repair.py` reports all of them. It also performs three repairs, one named item at a time. **Nothing is deleted or adopted automatically.**

## The report (read-only)

```powershell
& $GenPy scripts\media_volume_repair.py report --media-root $Gallery --volume-root $VolumeRoot --job-db $JobDb --lease-dir $LeaseDir `
    --work-root $WorkRoot --work-dir "$WorkRoot\comfy\output" --work-dir "$WorkRoot\comfy\temp" --work-dir "$WorkRoot\comfy\input"
```

`--work-root` and `--work-dir` are optional, but they go together. Each `--work-dir` must be a scratch folder inside the verified, private work area, never the work root itself.

The report is JSON, schema `kaliv-media-repair-report/v1`. It never contains a prompt, an owner or job parameters. The job database is opened read-only, and only after the volume has been verified.

| Field | What it is | What to do |
|---|---|---|
| `unindexed_assets` | A published file that the gallery index does not list. Its `status` decides the action, see the rows below | — |
| `status: adoptable` | The job **completed** with exactly this asset; only the index row is missing | `adopt` |
| `status: job_failed` with `job_error: interrupted_during_publication` | The executor stopped while publishing. The job is failed; the owner resubmits | Leave it; report it upstream if it repeats |
| `status: no_job` | No job in this database produced the file | Investigate; never adopt |
| `indexed_but_missing` | An index row whose file is gone | Investigate the volume |
| `completed_jobs_without_asset` | A completed job whose asset is neither indexed nor on disk | Investigate |
| `stale_temporary_files` | A `.kaliv-*.tmp` file older than `--min-age-hours` (default 6), with its `device` and `inode` | `remove-temp` |
| `quarantined` | A file the tool captured but could not put back under its name (rare) | Inspect it by hand |
| `executors_running` | GPUs whose media executor is running right now | The repairs refuse while this list is not empty |
| `work_area_residue` | A file older than `--min-age-hours` in a named work-area scratch folder, with its folder, relative path, `device` and `inode`. Links are listed with `kind: link`, never followed and never removable. The job database and its `-wal`, `-shm` and `-journal` files are never listed | `remove-work-file` for a `kind: file` entry. `null` when no work area was named |

## The three repairs

Each repair does three things before it acts:
- it refuses while any media executor holds its lock;
- it holds every executor lock while it runs, so none can start meanwhile;
- it re-checks the volume.

```powershell
# Register one adoptable asset (and only an adoptable one).
& $GenPy scripts\media_volume_repair.py adopt --asset <asset_id> --media-root $Gallery --volume-root $VolumeRoot --job-db $JobDb --lease-dir $LeaseDir

# Remove one stale temp file, using the device and inode from the report.
& $GenPy scripts\media_volume_repair.py remove-temp --name <.kaliv-...tmp> --device <device> --inode <inode> --media-root $Gallery --volume-root $VolumeRoot --lease-dir $LeaseDir

# Remove one leftover file from a work-area scratch folder, using the folder, path, device and inode from the report.
& $GenPy scripts\media_volume_repair.py remove-work-file --work-root $WorkRoot --work-dir "$WorkRoot\comfy\output" --path <path> --device <device> --inode <inode> --job-db $JobDb --lease-dir $LeaseDir
```

`remove-work-file` checks the work area again (canonical, private, no links) and refuses:
- a path that is absolute, has `..`, a drive or a stream;
- anything that is not a `kind: file` entry of the current report, or is younger than the minimum age;
- the job database or its sidecar files;
- a file whose device or inode differ from the ones named.

It captures, checks and removes the file exactly like `remove-temp`.

`remove-temp` refuses in any of these cases:
- the name is not a `.kaliv-*.tmp` name;
- the file is younger than the minimum age;
- its device or inode differ from the ones named.

It captures the file by an atomic rename, then checks it again. If it is not the named file, it is put back without overwriting anything.

## The recovery inventory (read-only)

The video hand-off from the work area (C:) to the volume (Z:) is: copy into a staged file, sync, publish, then remove the copy on C:. Before the copy starts, the executor stores a **hand-off receipt** for the job (table `image_jobs_handoff`). The receipt holds the output's name, `st_dev`, `st_ino` and size, the volume root's identity, and the SHA-256 once copied. `inventory` uses it to tie each leftover to its job:

```powershell
& $GenPy scripts\media_volume_repair.py inventory --media-root $Gallery --volume-root $VolumeRoot --job-db $JobDb `
    --lease-dir $LeaseDir --work-root $WorkRoot --work-dir "$WorkRoot\comfy\output"
```

The output is JSON, schema `kaliv-media-recovery-inventory/v1`. It lists one entry per job that left something behind:

| `classification` | What happened | Evidence |
|---|---|---|
| `interrupted_copy` | the copy started and never finished | the work file is intact; the staged temp, if any, is a byte-exact prefix of it |
| `crash_after_sync_before_publication` | a complete, synced copy was never published | a staged temp with the receipt's SHA-256; the work file is intact |
| `publication_failed` | publication failed after the copy; the work file was kept | the work file is intact; nothing is staged or published |
| `crash_after_publication_before_cleanup` | published and indexed once; the work copy was not yet removed | the job's asset has the receipt's SHA-256 and is indexed; the work file is intact |
| `published_unindexed` | the file was published, but the gallery index was not updated | the job's asset has the receipt's SHA-256 and is not indexed; the work file is intact |
| `volume_changed` | the volume root is not the one the job handed over to | nothing on it is correlated |
| `unknown` | anything else, including two candidates for one piece or a changed file | — |

`source` (image-to-video) is `present`, `missing` (not on the volume, or not indexed), `changed` (another SHA-256 than recorded) or `unverified`. Pieces no job claims are under `unattributed`.

**What it never does:**
- change a file;
- follow a link or reparse point;
- use a file name that is not a plain name;
- show a prompt, an owner or job parameters.

While an executor runs it classifies nothing (`status: executor_running`), because its files are in flight. The inventory says what happened; what to do stays the operator's choice. The repairs above remove one named item at a time. **Nothing is retried or republished automatically**, and the owner resubmits.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Done |
| 1 | Refused, with the reason on stderr; nothing changed |
| 2 | Usage |
| 75 | The media volume is not there, or the work area failed its checks |

## Relation to G1

The volume check here is the gallery's own (`ExternalMediaSink._root`). The work area check is `PrivateWorkArea`, the same one the executor uses. Still open: the tool should also take `KALIV_MEDIA_VOLUME_ID` and verify G1's marker and pinned identity (`MountedMediaVolume`, `docs/MEDIA_VOLUME.md`) before a repair on the volume.
