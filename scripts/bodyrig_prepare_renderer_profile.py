#!/usr/bin/env python3
"""Prepare the selected `.mrbody` avatar for a path-based renderer."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bodyrig.profile_store import MRBodyProfileStore  # noqa: E402
from bodyrig.renderer_handoff import MRBodyRendererHandoff  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Freshly validate the current BodyRig profile, stage only its validated "
            "avatar.vrm into a digest-bound renderer directory, and report the exact "
            "BODYRIG_VRM_PATH. No renderer is activated."
        )
    )
    parser.add_argument("store", help="M2.6 archive-only BodyRig profile-store directory")
    args = parser.parse_args()

    handoff = MRBodyRendererHandoff(MRBodyProfileStore(Path(args.store))).prepare_current()
    descriptor = handoff.descriptor.to_mapping()
    result = {
        **descriptor,
        "BODYRIG_VRM_PATH": str(handoff.vrm_path.resolve()),
    }
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
