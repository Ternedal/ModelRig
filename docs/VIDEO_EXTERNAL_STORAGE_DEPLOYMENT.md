# Video storage deployment contract (experimental)

Video generation remains disabled by default. This branch must not alter the
current release or enable a ComfyUI worker.

## External volume requirement

Set `KALIV_MEDIA_ROOT` to an **existing, absolute directory on the approved
external data volume** (for example `E:\\Kaliv` on Windows or
`/mnt/kaliv-media/Kaliv` in WSL). The path is operator-configured; do not
assume a drive letter. Set `KALIV_MEDIA_MIN_FREE_GB` to the required free-space
reserve (default 20 GiB).

The dispatcher now checks the configured volume before claiming a job. If it
is missing, read-only or below the free-space reserve, the job remains queued.
There is **no automatic fallback to C:, the repository, or /tmp**.

## Critical deployment requirements not yet enforced end-to-end

1. The existing path must be confirmed by deployment tooling to be on the
   intended physical external disk, not merely a directory or bind mount on
   the system volume. Windows USB drives can report as fixed disks.
2. Configure ComfyUI input, output, temp and model directories on the same
   approved external disk, or another explicitly approved external disk.
   ComfyUI may write large intermediate tensors or videos before ModelRig
   receives an artifact. ModelRig's admission check alone cannot prevent this.
3. Put the video jobs SQLite DB on that volume as well; current
   `VideoJobStore` takes a caller-supplied path and is not wired to the media
   root yet.
4. Validate available space before *and during* long jobs; clean abandoned
   intermediates and avoid following symlinks or junctions into system storage.
5. Verify the volume identity after remount/reboot to avoid accidentally
   writing to a new local directory created at the mount point.
6. The adapter/dispatcher are not yet mounted in production, and no Wan model
   or actual video generation has been tested.

## Operator readiness

Do not enable any experimental video API until the physical volume identity,
ComfyUI directory routing, backend output collector and job ownership model
have passed integration tests. SkyPlayer/VR integration is still pending.
