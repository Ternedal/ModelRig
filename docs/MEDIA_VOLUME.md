# Verified media volume (G1)

The verified media volume is where generated media is **published**: the gallery, its index and every staged file. `worker/app/media_volume.py` is the production check for it. `MountedMediaVolume` implements the `VerifiedMediaVolume` protocol in `media_generation_contract`.

**Generation happens elsewhere (Anders, 6 Nov 2026, #2275).** ComfyUI's working folders and the job database live in a private work area on the internal disk. A finished file is checked, copied into a staged file on this volume, synced, and published to the gallery in one atomic step; only then is the copy on the internal disk removed. So nothing partial is ever visible in the gallery, and a finished file is never deleted before it is published. That work area is a separate check (`docs/MEDIA_WORK_AREA.md`); this module does not cover it.

**Status: wired into the media executor's entry point** (`media_executor_main.build_from_env`).
- **The volume:** `KALIV_MEDIA_VOLUME_ROOT` plus `KALIV_MEDIA_VOLUME_ID` build one `MountedMediaVolume` at start.
- **The job store's guard:** checks it before every access (the work area, then `volume.verify()`, then the gallery root), so the executor never claims a job it could not publish. The job database itself is in the work area, not here.
- **The gallery sink:** uses its root.
- **Exit codes:** a configuration that can never work is exit 78; a missing, foreign or swapped disk is exit 75.
- **Video stays default-off:** `media_executor_main` keeps exit 78 for video until the staged sink, image-to-video and the rig evidence are in.

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
- on Windows, it is a local drive: not a network drive (`GetDriveTypeW`) and not a `subst` letter (`QueryDosDeviceW`). Many SMB shares report NTFS, so the filesystem check alone would not catch them. This is checked first, so either case is 78 (`media_volume_remote_refused`, `media_volume_subst_refused`);
- its filesystem is on the list above;
- the marker matches the configured id.

The root's identity (`st_dev`, `st_ino`) is pinned. On Windows, `st_dev` is the volume serial number. On Linux, the mount instance (the mount id in `/proc/self/mountinfo`) is pinned too.

**On every `verify()` and `require()`:** all of the start checks again, plus the pinned identity and mount instance.

**Once a check has failed, that verifier is done for good.** While the volume is still wrong, the check raises the real reason. Once it looks right again, it raises `media_volume_lost`. Only a new verifier, which means an executor restart (exit 75), resumes. So a disk that went away and came back is never silently used again.

| What happens to the disk | Detected by |
|---|---|
| Replaced by another disk or folder at the same path | the identity changes |
| The same disk unplugged and plugged back in, seen while it was gone | the observed loss sticks: `media_volume_lost` until restart |
| The same disk mounted again, on Linux | the mount id changes: `media_volume_remounted` |
| The same disk unplugged and plugged back in between two checks, on Windows | **not detectable.** Windows has no mount-session id: the volume serial, its GUID and the root's file id all survive. The executor checks before every claim and at each step of the hand-off, so the window is short. Writes through handles of the old mount are expected to fail, so a copy in flight fails and its C: copy is kept. That is not yet proven on the rig. |

**`require(path)` additionally refuses:**
- a path that is relative or contains `.` or `..`;
- a path outside the root, including a sibling that only shares the root's string prefix;
- a missing path;
- a path that is not canonical, i.e. one that resolves through a symlink, a junction or an 8.3 alias;
- any component that is a symlink or a reparse point;
- any component on another device, e.g. a bind mount or a mounted folder from the internal disk;
- a FIFO or device;
- on Windows: UNC and `\\?\` / `\\.\` paths, alternate data streams, trailing dots or spaces, and reserved names (`NUL`, `COM1` and so on).

**`require_descriptor(fd, path)`** is for a reader that has already opened a file, such as the gallery (#2275 6702693683). Call it right after the open and before any byte is served. A path check proves where a name pointed when it was walked, but the descriptor is what is read. It refuses:

| Situation between the check and the open | Reason |
|---|---|
| The descriptor is on another device: a parent swapped for a link to another disk, a Windows reparse point (Windows has no `O_NOFOLLOW`), or an unmount that let the mount point or drive letter fall back to the system disk | `media_descriptor_other_device` |
| The descriptor is not a regular file or directory | `media_descriptor_not_file_or_directory` |
| The descriptor is not the file a verified walk of `path` finds after the open, e.g. a parent was a link to elsewhere *on the same volume* at the open and was swapped back | `media_descriptor_not_path` |
| The descriptor cannot be read (closed) | `media_descriptor_unavailable` |

It also runs `verify()`, so a lost or remounted volume refuses first. Any `require()` reason, for example `media_path_not_canonical` while a parent is still a link, refuses too.

## Error classes and exit codes

| Error | Meaning | Executor exit |
|---|---|---|
| `MediaVolumeConfigError` | The configuration can never work: a bad id or root, a refused or unknown filesystem, the system disk, or a network or `subst` drive | 78 |
| `ArtifactSinkUnavailable` | The volume is not usable right now: missing, not mounted, wrong or missing marker, identity changed, mounted again (`media_volume_remounted`), lost earlier (`media_volume_lost`), or a refused path | 75 |

A missing marker counts as 75, because a wrong disk looks exactly the same. The reason string says which check failed. It never contains a prompt.

## Integration

```python
volume = media_volume_from_env()                       # KALIV_MEDIA_VOLUME_ROOT / _ID
sink = ExternalStagedVideoSink(media_root, verified_volume_root=volume.root)   # #2347
# The executor calls volume.verify() before it claims a job, so no render is
# wasted on a volume that cannot take the result. ComfyUI's folders and the job
# database are in the work area on the internal disk, not here.
```

## Limits

`verify()` and `require()` are checks, not handles. A process running as the same OS user could swap a directory between the check and its use. A reader that opens first and then calls `require_descriptor` is bound to what it actually opened. Writers still rely on the work area. The private work area on the internal disk, where ComfyUI writes (rig item 9 in `MEDIA_VIDEO_GENERATION.md`), is the guard against that.

## Tests

- `tests/worker_media_volume.py` runs anywhere. It uses real directories, files and symlinks. A fake probe stands in only for mount points, filesystem types, the system device, a foreign `st_dev` and the reparse attribute. On Linux it also runs the real probe against the `/dev/shm` mount.
- `tests/support/windows_media_volume_contract.py` runs on the Windows gate with the real probe. It covers NTFS, the refused system drive, junctions, alternate data streams, trailing-dot aliases, 8.3 names and a changed marker. For `require_descriptor` it checks three cases: an open file on the volume passes, a descriptor on the system drive is refused, and a file opened through a junction that is then swapped for a folder is refused. The three are mandatory: if any of them cannot run (for example, the workspace is on the system drive or `mklink /J` fails), the contract FAILS instead of passing with a "not run" (ChatGPT, #2275 6704220238). These cases run only once this branch is in a PR; they have not run yet.
- **Rig (C3, R14):** unplug the disk while an executor runs, then plug it back in. Expect exit 75, then a clean restart.
