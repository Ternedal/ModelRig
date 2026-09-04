#!/usr/bin/env python3
"""Build one unified BodyRig M2.4 identity bundle from tracking/v1 JSON."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bodyrig.fingerprint import DEFAULT_CREATED_AT, FingerprintConfig  # noqa: E402
from bodyrig.identity import build_identity_bundle, canonical_identity_json  # noqa: E402
from bodyrig.shape import ShapeConfig  # noqa: E402


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Build one deterministic BodyRig unified identity from canonical tracking JSON. "
            "The output binds motion, source-relative shape and facial behavior; it contains no source video."
        )
    )
    result.add_argument("tracking_json", type=Path, help="M1.1 bodyrig.tracking/v1 JSON input")
    result.add_argument("output_json", type=Path, help="Destination identity-bundle JSON")
    result.add_argument("--gesture-speed-threshold", type=float, default=1.0)
    result.add_argument("--gesture-max-gap-us", type=int, default=180_000)
    result.add_argument("--min-gesture-duration-us", type=int, default=100_000)
    result.add_argument("--motion-min-point-confidence", type=float, default=0.2)
    result.add_argument("--shape-min-point-confidence", type=float, default=0.35)
    result.add_argument("--shape-min-samples", type=int, default=3)
    result.add_argument(
        "--created-at",
        default=DEFAULT_CREATED_AT,
        help="Deterministic motion-manifest timestamp; wall-clock time is never injected automatically.",
    )
    return result


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    tracking = json.loads(args.tracking_json.read_text(encoding="utf-8"))
    fingerprint_config = FingerprintConfig(
        gesture_speed_threshold=args.gesture_speed_threshold,
        gesture_max_gap_us=args.gesture_max_gap_us,
        min_gesture_duration_us=args.min_gesture_duration_us,
        min_point_confidence=args.motion_min_point_confidence,
        created_at=args.created_at,
    )
    shape_config = ShapeConfig(
        min_point_confidence=args.shape_min_point_confidence,
        min_samples=args.shape_min_samples,
    )
    bundle = build_identity_bundle(
        tracking,
        fingerprint_config=fingerprint_config,
        shape_config=shape_config,
    )
    _atomic_write(args.output_json.resolve(), canonical_identity_json(bundle))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
