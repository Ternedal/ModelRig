# Verified media volume (G1)

The verified media volume is where generated media is **published**: the gallery, its index and every staged file. `worker/app/media_volume.py` is the production check for it. `MountedMediaVolume` implements the `VerifiedMediaVolume` protocol in `media_generation_contract`.

**Generation happens elsewhere (Anders, 6 Nov 2026, #2275).** ComfyUI's working folders and the job database live in a private work area on the internal disk. A finished file is copied into a staged file on this volume, checked, and published to the gallery in one atomic step; only then is the copy on the internal disk removed. So nothing partial is ever visible in the gallery. That work area is a separate check, added with the wiring; this module does not cover it.

**Status: it exists but is not wired in yet.** Nothing calls it; wiring it into the executor is a separate PR. Video stays default-off, and `media_executor_main` keeps exit 78 for video until that PR and the rig evidence are in.

## Operator setup (once per disk)

Use one external disk with NTFS, ReFS, ext4, xfs or btrfs. FAT32 and exFAT are refused: they reuse file ids after a rename, so cleanup could not rule out deleting a file it does not own.

Write the volume id into a marker at the disk's root.

**Windows**, where the root is the drive letter:
```powershell
$Id = "kaliv-media-" + [guid]::NewGuid().ToString("N").Substring(0, 12)
Set-Content -Path "E:\.kaliv-media-volume" -Value $Id -NoNewline -Encoding ascii
$Id
```

**Linux or WSL**, where the root is the mount point:
```bash
id="kaliv-media-$(head -c6 /dev/urandom | od -An -tx1 | tr -d ' \n')"
printf %s "$id" | sudo tee /mnt/kaliv-media/.kaliv-media-volume >/dev/null; echo "$id"
```

Then configure the worker:

| Setting | Value |
|---|---|
| `KALIV_MEDIA_VOLUME_ROOT` | The mount point, exactly as the system reports it, e.g. `E:\` or `/mnt/kaliv-media`. It must not contain a symlink, a junction or an 8.3 short name. |
| `KALIV_MEDIA_VOLUME_ID` | The id printed above: 8 to 64 characters, letters, digits and `-`. |

The id ties the configuration to that one disk. Another disk mounted at the same letter or path does not have the marker, so it is refused.

## What is checked

**At start (construction):**
- the root is canonical and is a directory;
- it is a mount point;
- it is not the system volume;
- its filesystem is on the list above;
- the marker matches the configured id.

The root's identity (`st_dev`, `st_ino`) is pinned. On Windows, `st_dev` is the volume serial number.

**On every `verify()` and `require()`:** all of the start checks again, plus the pinned identity. If the disk was unplugged, replugged or replaced, the identity has changed and the check fails until the executor restarts. That restart is exit 75.

**`require(path)` additionally refuses:**
- a path that is relative or contains `.` or `..`;
- a path outside the root, including a sibling that only shares the root's string prefix;
- a missing path;
- a path that is not canonical, i.e. one that resolves through a symlink, a junction or an 8.3 alias;
- any component that is a symlink or a reparse point;
- any component on another device, e.g. a bind mount or a mounted folder from the internal disk;
- a FIFO or device;
- on Windows: UNC and `\\?\` / `\\.\` paths, alternate data streams, trailing dots or spaces, and reserved names (`NUL`, `COM1` and so on).

## Error classes and exit codes

| Error | Meaning | Executor exit |
|---|---|---|
| `MediaVolumeConfigError` | The configuration can never work: a bad id or root, a refused or unknown filesystem, or the system disk | 78 |
| `ArtifactSinkUnavailable` | The volume is not usable right now: missing, not mounted, wrong or missing marker, identity changed, or a refused path | 75 |

A missing marker counts as 75, because a wrong disk looks exactly the same. The reason string says which check failed. It never contains a prompt.

## Integration (the follow-up wiring PR)

```python
volume = media_volume_from_env()                       # KALIV_MEDIA_VOLUME_ROOT / _ID
sink = ExternalStagedVideoSink(media_root, verified_volume_root=volume.root)   # #2347
# The executor calls volume.verify() before it claims a job, so no render is
# wasted on a volume that cannot take the result. ComfyUI's folders and the job
# database are in the work area on the internal disk, not here.
```

## Limits

These are checks, not handles. A process running as the same OS user could swap a directory between the check and its use. The private work area on the internal disk, where ComfyUI writes (rig item 9 in `MEDIA_VIDEO_GENERATION.md`), is the guard against that.

## Tests

- `tests/worker_media_volume.py` runs anywhere. It uses real directories, files and symlinks. A fake probe stands in only for mount points, filesystem types, the system device, a foreign `st_dev` and the reparse attribute. On Linux it also runs the real probe against the `/dev/shm` mount.
- `tests/support/windows_media_volume_contract.py` runs on the Windows gate with the real probe. It covers NTFS, the refused system drive, junctions, alternate data streams, trailing-dot aliases, 8.3 names and a changed marker.
- **Rig (C3, R14):** unplug the disk while an executor runs, then plug it back in. Expect exit 75, then a clean restart.
