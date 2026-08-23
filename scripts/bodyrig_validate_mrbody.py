#!/usr/bin/env python3
"""Validate an untrusted `.mrbody` V1 archive without extracting it."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bodyrig.mrbody import validate_mrbody  # noqa: E402


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Validate a `.mrbody` V1 ZIP completely before extraction. "
            "This performs structural VRM/PNG checks only and does not prove visual/rig quality."
        )
    )
    result.add_argument("package", type=Path, help="`.mrbody` archive to validate")
    result.add_argument(
        "--expected-id",
        help="Optional canonical bodyid-* that both manifest and embedded provenance must bind",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    inspection = validate_mrbody(
        args.package.read_bytes(),
        expected_identity_id=args.expected_id,
    )
    summary = {
        "body_id": inspection.body_id,
        "identity_content_id": inspection.identity_content_id,
        "name": inspection.name,
        "payload_sizes": dict(inspection.payload_sizes),
        "validated": True,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
