#!/usr/bin/env python3
"""Read-only JSONL inspection of generation jobs and external media receipts.

This command never changes job state, files or the gallery index. It does not
mount volumes or attempt automatic recovery.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.image_job_store import ImageJobStore  # noqa: E402
from app.media_gallery_store import ExternalMediaSink  # noqa: E402
from app.media_generation_reconciliation import inspect_generation_consistency  # noqa: E402



class ReadOnlyImageJobStore(ImageJobStore):
    """Use SQLite URI mode=ro; bypass the mutating schema setup in __init__."""

    def __init__(self, db_path: Path):
        self.path = db_path
        self._volume_guard = None
        self._snapshot_connection = None

    @contextmanager
    def snapshot(self):
        """Pin a single SQLite read transaction for all pagination queries."""
        if self._snapshot_connection is not None:
            raise RuntimeError("reconciliation_snapshot_already_active")
        connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro",
                                     uri=True, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN")
            self._snapshot_connection = connection
            yield
        finally:
            self._snapshot_connection = None
            connection.close()

    @contextmanager
    def _db(self):
        if self._snapshot_connection is not None:
            yield self._snapshot_connection
            return
        connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro",
                                     uri=True, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs-db", required=True, type=Path,
                        help="Existing jobs SQLite database (never created by this command)")
    parser.add_argument("--volume-root", required=True, type=Path,
                        help="Existing mounted external volume")
    parser.add_argument("--media-root", required=True, type=Path,
                        help="Gallery directory within the external volume")
    parser.add_argument("--limit", type=int, default=100,
                        help="Number of jobs per page (1..1000)")
    parser.add_argument("--offset", type=int, default=0,
                        help="Starting offset (0..1000000)")
    parser.add_argument("--all", action="store_true",
                        help="Scan all pages, stopping on the first incomplete page")
    parser.add_argument("--fail-on-conflict", action="store_true",
                        help="Exit 1 when findings require operator investigation")
    args = parser.parse_args(argv)

    # sqlite3.connect creates an absent DB; prevent a diagnostic from
    # accidentally creating a fresh database and reporting no jobs.
    if not args.jobs_db.is_file() or args.jobs_db.is_symlink():
        parser.error("--jobs-db must refer to an existing regular file, not a symlink")
    if not 1 <= args.limit <= 1000 or not 0 <= args.offset <= 1000000:
        parser.error("invalid --limit or --offset")
    try:
        jobs = ReadOnlyImageJobStore(args.jobs_db)
        sink = ExternalMediaSink(args.media_root, args.volume_root)
        offset = args.offset
        conflict = False
        # Even a single-page inspection uses one pinned SQLite read snapshot.
        with jobs.snapshot():
            while True:
                findings = inspect_generation_consistency(jobs, sink, limit=args.limit, offset=offset)
                for finding in findings:
                    print(json.dumps(finding, sort_keys=True))
                    status = finding["status"]
                    # Benign pre-publication states and verified completed receipts
                    # are not alarms. Everything else warrants investigation.
                    if status not in {"consistent", "completed_legacy_indexed",
                                      "no_job_artifact", "publishing_without_job_artifact"}:
                        conflict = True
                if not args.all or len(findings) < args.limit:
                    break
                offset += args.limit
                if offset > 1000000:
                    raise ValueError("reconciliation_page_limit_exceeded")
    except (OSError, RuntimeError, ValueError, sqlite3.DatabaseError) as exc:
        print(f"reconciliation unavailable: {exc}", file=sys.stderr)
        return 2
    return 1 if args.fail_on_conflict and conflict else 0


if __name__ == "__main__":
    raise SystemExit(main())
