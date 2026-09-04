#!/usr/bin/env python3
"""Build a deterministic BodyRig M2.1 facial-behavior profile from tracking JSON."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bodyrig.face_behavior import (  # noqa: E402
    FaceBehaviorError,
    build_face_behavior,
    canonical_face_behavior_json,
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Build renderer-neutral facial-behavior priors from BodyRig tracking JSON. "
            "This does not reconstruct facial identity geometry or emit VRM morph commands."
        )
    )
    result.add_argument("tracking_json", type=Path, help="M1.1 bodyrig.tracking/v1 JSON input")
    result.add_argument("output_json", type=Path, help="Destination facial-behavior JSON")
    return result


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FaceBehaviorError(f"tracking input cannot be read: {type(exc).__name__}") from exc
    except json.JSONDecodeError as exc:
        raise FaceBehaviorError(f"tracking input is not valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise FaceBehaviorError("tracking input must contain a JSON object")
    return value


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
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
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise FaceBehaviorError(f"facial-behavior output cannot be written: {type(exc).__name__}") from exc


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    input_path = args.tracking_json.resolve()
    output_path = args.output_json.resolve()
    if input_path == output_path:
        print("ERROR: input and output paths must differ", file=sys.stderr)
        return 2
    try:
        profile = build_face_behavior(_read(input_path))
        _write(output_path, canonical_face_behavior_json(profile))
    except FaceBehaviorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(
        f"BodyRig facial behavior written: {output_path} | "
        f"id={profile['id']} | expression_coverage={profile['observation']['expression_coverage']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
