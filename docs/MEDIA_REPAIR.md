# Media volume repair (C6)

A crash, or a lost volume, can leave three kinds of residue on the media volume. `scripts/media_volume_repair.py` reports all of them. It also performs two repairs, one named item at a time. **Nothing is deleted or adopted automatically.**

## The report (read-only)

```powershell
& $GenPy scripts\media_volume_repair.py report --media-root $Gallery --volume-root $VolumeRoot --job-db $JobDb --lease-dir $LeaseDir
```

The report is JSON, schema `kaliv-media-repair-report/v1`. It never contains a prompt, an owner or job parameters. The job database is opened read-only, and only after the volume has been verified.

| Field | What it is | What to do |
|---|---|---|
| `unindexed_assets` | A published file that the gallery index does not list. Its `status` decides the action, see the rows below | — |
| `status: adoptable` | The job **completed** with exactly this asset; only the index row is missing | `adopt` |
| `status: job_failed` with `job_error: interrupted during publication` | The executor stopped while publishing. The job is failed; the owner resubmits | Leave it; report it upstream if it repeats |
| `status: no_job` | No job in this database produced the file | Investigate; never adopt |
| `indexed_but_missing` | An index row whose file is gone | Investigate the volume |
| `completed_jobs_without_asset` | A completed job whose asset is neither indexed nor on disk | Investigate |
| `stale_temporary_files` | A `.kaliv-*.tmp` file older than `--min-age-hours` (default 6), with its `device` and `inode` | `remove-temp` |
| `quarantined` | A file the tool captured but could not put back under its name (rare) | Inspect it by hand |
| `executors_running` | GPUs whose media executor is running right now | The two repairs refuse while this list is not empty |

## The two repairs

Each repair does three things before it acts:
- it refuses while any media executor holds its lock;
- it holds every executor lock while it runs, so none can start meanwhile;
- it re-checks the volume.

```powershell
# Register one adoptable asset (and only an adoptable one).
& $GenPy scripts\media_volume_repair.py adopt --asset <asset_id> --media-root $Gallery --volume-root $VolumeRoot --job-db $JobDb --lease-dir $LeaseDir

# Remove one stale temp file, using the device and inode from the report.
& $GenPy scripts\media_volume_repair.py remove-temp --name <.kaliv-...tmp> --device <device> --inode <inode> --media-root $Gallery --volume-root $VolumeRoot --lease-dir $LeaseDir
```

`remove-temp` refuses in any of these cases:
- the name is not a `.kaliv-*.tmp` name;
- the file is younger than the minimum age;
- its device or inode differ from the ones named.

It captures the file by an atomic rename, then checks it again. If it is not the named file, it is put back without overwriting anything.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Done |
| 1 | Refused, with the reason on stderr; nothing changed |
| 2 | Usage |
| 75 | The media volume is not there |

## Relation to G1

The volume check here is the gallery's own (`ExternalMediaSink._root`). When G1 (`MountedMediaVolume`, `docs/MEDIA_VOLUME.md`) is wired in, the tool should also take `KALIV_MEDIA_VOLUME_ID` and verify the marker and the pinned identity.
