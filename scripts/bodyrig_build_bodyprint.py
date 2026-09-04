#!/usr/bin/env python3
"""Build a deterministic BodyRig M1.2 bodyprint from an M1.1 tracking JSON file."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bodyrig.fingerprint import (  # noqa: E402
    FingerprintConfig,
    FingerprintError,
    build_bodyprint,
    canonical_bodyprint_json,
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Build a deterministic BodyRig v0.1 bodyprint package from normalized tracking JSON."
    )
    result.add_argument("tracking_json", type=Path, help="M1.1 bodyrig.tracking/v1 JSON input")
    result.add_argument("output_json", type=Path, help="Destination bodyprint JSON")
    result.add_argument(
        "--gesture-speed-threshold",
        type=float,
        default=1.0,
        help="Torso-normalized wrist speed threshold (units/second; default: 1.0)",
    )
    result.add_argument(
        "--gesture-max-gap-us",
        type=int,
        default=180_000,
        help="Maximum gap merged inside one gesture candidate (default: 180000)",
    )
    result.add_argument(
        "--min-gesture-duration-us",
        type=int,
        default=100_000,
        help="Minimum accepted gesture duration (default: 100000)",
    )
    result.add_argument(
        "--min-point-confidence",
        type=float,
        default=0.2,
        help="Minimum landmark confidence used for style measurements (default: 0.2)",
    )
    result.add_argument(
        "--created-at",
        default="1970-01-01T00:00:00+00:00",
        help=(
            "Manifest timestamp. Keep the default or pin an explicit value for reproducible output; "
            "wall-clock time is intentionally not injected automatically."
        ),
    )
    return result


def _read_tracking(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FingerprintError(f"tracking input cannot be read: {type(exc).__name__}") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FingerprintError(f"tracking input is not valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise FingerprintError("tracking input must contain a JSON object")
    return value


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)  # type: ignore[possibly-undefined]
        except Exception:
            pass
        raise FingerprintError(f"bodyprint output cannot be written: {type(exc).__name__}") from exc


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    input_path = args.tracking_json.resolve()
    output_path = args.output_json.resolve()
    if input_path == output_path:
        print("ERROR: input and output paths must differ", file=sys.stderr)
        return 2
    try:
        tracking = _read_tracking(input_path)
        config = FingerprintConfig(
            gesture_speed_threshold=args.gesture_speed_threshold,
            gesture_max_gap_us=args.gesture_max_gap_us,
            min_gesture_duration_us=args.min_gesture_duration_us,
            min_point_confidence=args.min_point_confidence,
            created_at=args.created_at,
        )
        package = build_bodyprint(tracking, config=config)
        content = canonical_bodyprint_json(package)
        _atomic_write(output_path, content)
    except FingerprintError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(
        f"BodyRig bodyprint written: {output_path} | "
        f"id={package['manifest']['id']} | gestures={len(package['gestures'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
