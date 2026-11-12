"""Operator preflight for the C:/Z: media layout (R17). Read-only; prints JSON evidence.

  python scripts/media_work_area_preflight.py --work-root W --job-db DB --volume-root V --volume-id ID
                                              [--pid N ...] [--min-free-gib-work 5] [--min-free-gib-volume 20]

Without arguments the four paths and the id come from KALIV_MEDIA_WORK_ROOT, KALIV_MEDIA_JOB_DB,
KALIV_MEDIA_VOLUME_ROOT and KALIV_MEDIA_VOLUME_ID. Exit codes: 0 every check passed, 1 at least one
failed (see "checks"), 2 usage. See worker/app/media_preflight.py and docs/MEDIA_WORK_AREA.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "worker"))

from app.media_preflight import preflight  # noqa: E402


def main(argv: list[str], env=None) -> int:
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work-root", default=env.get("KALIV_MEDIA_WORK_ROOT"))
    parser.add_argument("--job-db", default=env.get("KALIV_MEDIA_JOB_DB"))
    parser.add_argument("--volume-root", default=env.get("KALIV_MEDIA_VOLUME_ROOT"))
    parser.add_argument("--volume-id", default=env.get("KALIV_MEDIA_VOLUME_ID"))
    parser.add_argument("--pid", type=int, action="append", default=[], help="a process that must run as this account")
    parser.add_argument("--min-free-gib-work", type=float, default=5.0)
    parser.add_argument("--min-free-gib-volume", type=float, default=20.0)
    args = parser.parse_args(argv)
    missing = [name for name in ("work_root", "job_db", "volume_root", "volume_id") if not getattr(args, name)]
    if missing:
        parser.error("missing: " + ", ".join("--" + name.replace("_", "-") for name in missing))
    report = preflight(work_root=args.work_root, job_db=args.job_db, volume_root=args.volume_root,
                       volume_id=args.volume_id, pids=args.pid, min_free_gib_work=args.min_free_gib_work,
                       min_free_gib_volume=args.min_free_gib_volume, env=env)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
