"""Operator tool for media volume residue (C6). Read-only by default; each repair names one item.

  python scripts/media_volume_repair.py report      --media-root R --volume-root V --job-db DB [--lease-dir L]
  python scripts/media_volume_repair.py adopt       --asset ID  --media-root R --volume-root V --job-db DB --lease-dir L
  python scripts/media_volume_repair.py remove-temp --name N --device D --inode I --media-root R --volume-root V --lease-dir L

``report`` prints JSON and changes nothing. ``adopt`` and ``remove-temp`` refuse while any media
executor holds its lock, and hold every executor lock for as long as they run.

Exit codes:
- 0: done;
- 1: refused, with the reason on stderr and nothing changed;
- 2: usage;
- 75: the media volume is not there.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "worker"))

from app.media_gallery_store import ExternalMediaSink  # noqa: E402
from app.media_generation_contract import ArtifactSinkUnavailable  # noqa: E402
from app.media_repair import DEFAULT_MINIMUM_AGE_S, RepairRefused, adopt, reconcile, remove_stale_temp  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("report", "adopt", "remove-temp"):
        p = sub.add_parser(name)
        p.add_argument("--media-root", required=True)
        p.add_argument("--volume-root", required=True)
        p.add_argument("--lease-dir", required=name != "report")
        p.add_argument("--min-age-hours", type=float, default=DEFAULT_MINIMUM_AGE_S / 3600)
        if name in ("report", "adopt"):
            p.add_argument("--job-db", required=True)
        if name == "adopt":
            p.add_argument("--asset", required=True)
        if name == "remove-temp":
            p.add_argument("--name", required=True)
            p.add_argument("--device", type=int, required=True)
            p.add_argument("--inode", type=int, required=True)
    args = parser.parse_args(argv)
    age = int(args.min_age_hours * 3600)
    sink = ExternalMediaSink(args.media_root, args.volume_root)
    try:
        if args.command == "report":
            result = reconcile(sink, args.job_db, lease_dir=args.lease_dir, minimum_age_seconds=age)
        elif args.command == "adopt":
            result = adopt(sink, args.job_db, args.asset, lease_dir=args.lease_dir)
        else:
            result = remove_stale_temp(sink, args.name, device=args.device, inode=args.inode,
                                       lease_dir=args.lease_dir, minimum_age_seconds=age)
    except ArtifactSinkUnavailable as exc:
        print(f"media volume unavailable: {exc}", file=sys.stderr)
        return 75
    except (RepairRefused, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
