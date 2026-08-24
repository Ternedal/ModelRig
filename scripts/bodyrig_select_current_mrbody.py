#!/usr/bin/env python3
"""Select one installed `.mrbody` as the exact digest-bound current profile."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bodyrig.profile_selection import MRBodyCurrentProfileStore  # noqa: E402
from bodyrig.profile_store import MRBodyProfileStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Select an installed BodyRig profile by canonical bodyid. The selection "
            "pins the exact installed package SHA-256 and is written atomically; no "
            "renderer is activated."
        )
    )
    parser.add_argument("store", type=Path, help="M2.6 archive-only profile-store directory")
    parser.add_argument("body_id", help="Canonical bodyid-<24 lowercase hex>")
    args = parser.parse_args()

    selection = MRBodyCurrentProfileStore(MRBodyProfileStore(args.store))
    marker = selection.select(args.body_id)
    print(
        json.dumps(
            {
                "body_id": marker.body_id,
                "marker": str(selection.marker_path),
                "package_sha256": marker.package_sha256,
                "renderer_activated": False,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
