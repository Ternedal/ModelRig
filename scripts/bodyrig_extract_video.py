#!/usr/bin/env python3
"""Run one explicit local BodyRig M1.1 video ingest job.

This is deliberately not a model downloader. The operator supplies the source
video and three local MediaPipe Tasks model assets. The supported backend binds
installed runtime versions + exact model hashes into the existing stable
``bodyrig.tracking/v1`` provenance and writes canonical JSON atomically.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bodyrig.local_tracking import LocalTrackingConfig  # noqa: E402
from bodyrig.local_tracking_runtime import LocalTrackingBackend  # noqa: E402
from bodyrig.tracking import build_tracking_timeline, canonical_tracking_json  # noqa: E402


def _absolute_file(raw: str, label: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError(f"{label} must be an absolute path")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or path.is_symlink():
        raise argparse.ArgumentTypeError(f"{label} must be a regular non-symlink file")
    return resolved


def _output_path(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("output must be an absolute path")
    parent = path.parent.resolve(strict=True)
    if not parent.is_dir():
        raise argparse.ArgumentTypeError("output parent must be an existing directory")
    return parent / path.name


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Extract one local video into canonical BodyRig M1.1 tracking JSON."
    )
    p.add_argument("--source", required=True, help="absolute local source video path")
    p.add_argument("--pose-model", required=True, help="absolute MediaPipe pose .task path")
    p.add_argument("--hand-model", required=True, help="absolute MediaPipe hand .task path")
    p.add_argument("--face-model", required=True, help="absolute MediaPipe face .task path")
    p.add_argument("--permission-assertion", required=True,
                   help="short provenance statement confirming permission to process the source")
    p.add_argument("--output", required=True, help="absolute output JSON path")
    p.add_argument("--frame-stride", type=int, default=1)
    p.add_argument("--delegate", choices=("cpu", "gpu"), default="cpu")
    p.add_argument("--min-detection-confidence", type=float, default=0.5)
    p.add_argument("--min-presence-confidence", type=float, default=0.5)
    p.add_argument("--min-tracking-confidence", type=float, default=0.5)
    return p


def _same_file_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve(strict=False))) == os.path.normcase(
        str(right.resolve(strict=False))
    )


def _atomic_write(path: Path, text: str) -> None:
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    source = _absolute_file(args.source, "source")
    pose = _absolute_file(args.pose_model, "pose model")
    hand = _absolute_file(args.hand_model, "hand model")
    face = _absolute_file(args.face_model, "face model")
    output = _output_path(args.output)
    if _same_file_path(source, output):
        raise SystemExit("output must not replace the immutable source video")
    if output.exists() and (output.is_symlink() or not output.is_file()):
        raise SystemExit("existing output must be a regular non-symlink file")

    backend = LocalTrackingBackend(
        LocalTrackingConfig(
            pose_model=pose,
            hand_model=hand,
            face_model=face,
            frame_stride=args.frame_stride,
            min_detection_confidence=args.min_detection_confidence,
            min_presence_confidence=args.min_presence_confidence,
            min_tracking_confidence=args.min_tracking_confidence,
            delegate=args.delegate,
        )
    )
    payload = build_tracking_timeline(
        source,
        backend=backend,
        permission_assertion=args.permission_assertion,
    )
    canonical = canonical_tracking_json(payload)
    _atomic_write(output, canonical)
    print(
        f"BodyRig tracking written: {output} | "
        f"frames={len(payload['frames'])} | "
        f"body_coverage={payload['coverage']['body']['coverage']:.3f} | "
        f"hands_coverage={payload['coverage']['hands']['coverage']:.3f} | "
        f"face_coverage={payload['coverage']['face']['coverage']:.3f} | "
        f"backend={payload['backend']['id']} {payload['backend']['version']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
