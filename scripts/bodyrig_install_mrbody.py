#!/usr/bin/env python3
"""Atomically install one validated `.mrbody` package into a local profile store."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bodyrig.profile_store import MRBodyProfileStore  # noqa: E402


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Validate a `.mrbody` V1 package, stage it as a same-directory temporary sibling, "
            "revalidate the staged bytes, and atomically replace <bodyid>.mrbody. "
            "No archive payload is extracted or activated."
        )
    )
    result.add_argument("package", type=Path, help="Untrusted `.mrbody` archive to install")
    result.add_argument("store", type=Path, help="Local BodyRig profile-store directory")
    result.add_argument(
        "--expected-id",
        default=None,
        help="Optional canonical bodyid-* that package manifest and provenance must bind",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    receipt = MRBodyProfileStore(args.store).install_file(
        args.package,
        expected_identity_id=args.expected_id,
    )
    print(
        json.dumps(
            {
                "body_id": receipt.body_id,
                "filename": receipt.filename,
                "name": receipt.name,
                "package_sha256": receipt.package_sha256,
                "size_bytes": receipt.size_bytes,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
