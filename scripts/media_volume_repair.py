"""Operator tool for media volume residue (C6). Read-only by default; each repair names one item.

  python scripts/media_volume_repair.py report      --media-root R --volume-root V --job-db DB [--lease-dir L]
                                                    [--work-root W --work-dir D1 [--work-dir D2 ...]]
  python scripts/media_volume_repair.py adopt       --asset ID  --media-root R --volume-root V --volume-id ID
                                                    --job-db DB --lease-dir L
  python scripts/media_volume_repair.py remove-temp --name N --device D --inode I --media-root R --volume-root V
                                                    --volume-id ID --lease-dir L
  python scripts/media_volume_repair.py remove-work-file --work-root W --work-dir D --path P --device D --inode I
                                                    --job-db DB --lease-dir L
  python scripts/media_volume_repair.py inventory   --media-root R --volume-root V --job-db DB --lease-dir L
                                                    --work-root W --work-dir <ComfyUI output folder>

``inventory`` ties what the C:/Z: hand-off left behind to its job, using the hand-off receipts
(docs/MEDIA_REPAIR.md). It is read-only, and classifies nothing while an executor runs.

The work area (Anders, 6 Nov 2026; docs/MEDIA_WORK_AREA.md) is the private folder on the internal
disk where media is generated. ``--work-dir`` names one of its scratch folders (ComfyUI's input,
output or temp); never the work root itself.

``report`` prints JSON and changes nothing. ``adopt`` and ``remove-temp`` refuse while any media
executor holds its lock, and hold every executor lock for as long as they run.

``adopt`` and ``remove-temp`` write on the media volume, so they first verify it as the executor
does (G1, docs/MEDIA_VOLUME.md): ``--volume-id`` (default ``KALIV_MEDIA_VOLUME_ID``) must match the
volume's ``.kaliv-media-volume`` marker, the root must be a mounted local disk (no network or
``subst`` letter, not the system disk), and the pinned identity is checked again immediately before
the repair. ``report``, ``inventory`` and ``remove-work-file`` do not write on the volume and are
unchanged.

Exit codes:
- 0: done;
- 1: refused, with the reason on stderr and nothing changed;
- 2: usage;
- 75: the media volume is not there (or the work area failed its checks), or it is not the pinned
  volume: marker missing or another id, identity changed, remounted;
- 78: the volume can never be right as configured: invalid id, network or ``subst`` drive,
  unsupported filesystem, the system disk.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "worker"))

from app.media_gallery_store import ExternalMediaSink  # noqa: E402
from app.media_generation_contract import ArtifactSinkUnavailable  # noqa: E402
from app.media_volume import VOLUME_ID_ENV, MediaVolumeConfigError, MountedMediaVolume  # noqa: E402
from app.media_repair import (DEFAULT_MINIMUM_AGE_S, RepairRefused, adopt, reconcile, remove_stale_temp,  # noqa: E402
                              remove_work_file)
from app.media_recovery_inventory import recovery_inventory  # noqa: E402
from app.media_work_area import MediaWorkAreaConfigError, PrivateWorkArea  # noqa: E402


_WRITES_ON_VOLUME = ("adopt", "remove-temp")


def main(argv: list[str], *, volume_probe=None) -> int:
    """``volume_probe`` is the G1 ``SystemProbe`` seam for tests; the default is the real system."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("report", "adopt", "remove-temp", "remove-work-file", "inventory"):
        p = sub.add_parser(name)
        if name != "remove-work-file":
            p.add_argument("--media-root", required=True)
            p.add_argument("--volume-root", required=True)
        if name in _WRITES_ON_VOLUME:
            p.add_argument("--volume-id", default=os.environ.get(VOLUME_ID_ENV) or None,
                           help=f"the id in <volume root>/.kaliv-media-volume (default: {VOLUME_ID_ENV})")
        p.add_argument("--lease-dir", required=name not in ("report",))
        p.add_argument("--min-age-hours", type=float, default=DEFAULT_MINIMUM_AGE_S / 3600)
        if name in ("report", "adopt", "remove-work-file", "inventory"):
            p.add_argument("--job-db", required=True)
        if name == "adopt":
            p.add_argument("--asset", required=True)
        if name in ("report", "remove-work-file", "inventory"):
            p.add_argument("--work-root", required=name != "report")
            p.add_argument("--work-dir", action="append", default=[], required=name != "report")
        if name == "remove-work-file":
            p.add_argument("--path", required=True)
        if name in ("remove-temp", "remove-work-file"):
            if name == "remove-temp":
                p.add_argument("--name", required=True)
            p.add_argument("--device", type=int, required=True)
            p.add_argument("--inode", type=int, required=True)
    args = parser.parse_args(argv)
    age = int(args.min_age_hours * 3600)
    work_root = getattr(args, "work_root", None)
    if args.command == "report" and bool(work_root) != bool(args.work_dir):
        parser.error("--work-root and --work-dir go together")
    if args.command in ("remove-work-file", "inventory") and len(args.work_dir) != 1:
        parser.error(f"{args.command} takes exactly one --work-dir")
    if args.command in _WRITES_ON_VOLUME and not args.volume_id:
        parser.error(f"{args.command} writes on the media volume: --volume-id or {VOLUME_ID_ENV} is required")
    try:
        area = PrivateWorkArea(work_root) if work_root else None
    except MediaWorkAreaConfigError as exc:
        print(f"work area refused: {exc}", file=sys.stderr)
        return 75
    try:
        if args.command == "remove-work-file":
            result = remove_work_file(area, args.work_dir[0], args.path, device=args.device, inode=args.inode,
                                      lease_dir=args.lease_dir, job_db=args.job_db, minimum_age_seconds=age)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        volume = None
        if args.command in _WRITES_ON_VOLUME:
            # G1 before anything on the volume is touched: the marker, its id and the pinned identity.
            volume = MountedMediaVolume(args.volume_root, args.volume_id, probe=volume_probe)
        # A root MountedMediaVolume accepted is canonical (media_volume_root_not_canonical): it names
        # the same directory as args.volume_root, which the sink checks again by path.
        sink = ExternalMediaSink(args.media_root, args.volume_root)
        if args.command == "inventory":
            result = recovery_inventory(sink, args.job_db, work_area=area, output_dir=args.work_dir[0],
                                        lease_dir=args.lease_dir)
        elif args.command == "report":
            result = reconcile(sink, args.job_db, lease_dir=args.lease_dir, minimum_age_seconds=age,
                               work_area=area, work_dirs=args.work_dir)
        elif args.command == "adopt":
            volume.verify()  # again, immediately before the write: still the pinned, mounted, marked disk
            result = adopt(sink, args.job_db, args.asset, lease_dir=args.lease_dir)
        else:
            volume.verify()
            result = remove_stale_temp(sink, args.name, device=args.device, inode=args.inode,
                                       lease_dir=args.lease_dir, minimum_age_seconds=age)
    except MediaVolumeConfigError as exc:
        print(f"media volume refused: {exc}", file=sys.stderr)
        return 78
    except ArtifactSinkUnavailable as exc:
        print(f"{'work area' if str(exc).startswith('media_work') else 'media volume'} unavailable: {exc}",
              file=sys.stderr)
        return 75
    except (RepairRefused, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
