#!/usr/bin/env python3
"""Build a deterministic BodyRig M1.3 shape profile from M1.1 tracking JSON."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bodyrig.shape import ShapeConfig, ShapeProfileError, build_shape_profile, canonical_shape_json  # noqa: E402


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Build a source-relative BodyRig shape profile from normalized tracking JSON. "
            "Output is not metric anthropometry or photorealistic reconstruction."
        )
    )
    result.add_argument("tracking_json", type=Path, help="M1.1 bodyrig.tracking/v1 JSON input")
    result.add_argument("output_json", type=Path, help="Destination shape-profile JSON")
    result.add_argument("--min-point-confidence", type=float, default=0.35)
    result.add_argument("--min-samples", type=int, default=3)
    return result


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ShapeProfileError(f"tracking input cannot be read: {type(exc).__name__}") from exc
    except json.JSONDecodeError as exc:
        raise ShapeProfileError(f"tracking input is not valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ShapeProfileError("tracking input must contain a JSON object")
    return value


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise ShapeProfileError(f"shape output cannot be written: {type(exc).__name__}") from exc


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    input_path = args.tracking_json.resolve()
    output_path = args.output_json.resolve()
    if input_path == output_path:
        print("ERROR: input and output paths must differ", file=sys.stderr)
        return 2
    try:
        profile = build_shape_profile(
            _read(input_path),
            config=ShapeConfig(
                min_point_confidence=args.min_point_confidence,
                min_samples=args.min_samples,
            ),
        )
        _write(output_path, canonical_shape_json(profile))
    except ShapeProfileError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(
        f"BodyRig shape profile written: {output_path} | "
        f"id={profile['id']} | measurements={len(profile['measurements'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
