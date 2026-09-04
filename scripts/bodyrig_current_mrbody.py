#!/usr/bin/env python3
"""Inspect the current digest-bound BodyRig profile and in-memory runtime payload surface."""
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
            "Resolve and freshly validate the current BodyRig profile. Optionally "
            "inspect the immutable data-only runtime binding; nothing is extracted "
            "or renderer-activated."
        )
    )
    parser.add_argument("store", type=Path, help="M2.6 archive-only profile-store directory")
    parser.add_argument(
        "--runtime-binding",
        action="store_true",
        help="Also bind validated avatar/bodyprint/thumbnail/motion payloads in memory and report sizes",
    )
    args = parser.parse_args()

    selection = MRBodyCurrentProfileStore(MRBodyProfileStore(args.store))
    current = selection.load_current()
    result: dict[str, object] = {
        "body_id": current.marker.body_id,
        "name": current.stored.receipt.name,
        "package_sha256": current.marker.package_sha256,
        "size_bytes": current.stored.receipt.size_bytes,
        "renderer_activated": False,
    }
    if args.runtime_binding:
        binding = selection.bind_current_runtime()
        result["runtime_binding"] = {
            "avatar_vrm_bytes": len(binding.avatar_vrm),
            "bodyprint_json_bytes": len(binding.bodyprint_json),
            "thumbnail_png_bytes": len(binding.thumbnail_png),
            "motions": [
                {"path": path, "bytes": len(payload)} for path, payload in binding.motions
            ],
            "filesystem_extraction": False,
            "vrma_semantics_interpreted": False,
        }
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
