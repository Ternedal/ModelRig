#!/usr/bin/env python3
"""Build a deterministic BodyRig `.mrbody` V1 archive from a validated M2.4 identity."""
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

from bodyrig.mrbody import OPTIONAL_MOTION_PATHS, MRBodyError, build_mrbody  # noqa: E402


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Build one deterministic `.mrbody` V1 archive from a validated M2.4 identity, "
            "caller-supplied VRM 1.0 GLB and PNG thumbnail. This does not prove visual/rig quality."
        )
    )
    result.add_argument("identity_json", type=Path, help="M2.4 bodyrig.identity_bundle/v0.1 JSON")
    result.add_argument("avatar_vrm", type=Path, help="Caller-supplied VRM 1.0 GLB")
    result.add_argument("thumbnail_png", type=Path, help="Caller-supplied PNG thumbnail")
    result.add_argument("output_mrbody", type=Path, help="Destination `.mrbody` archive")
    result.add_argument("--name", required=True, help="Portable display name (1..160 characters)")
    result.add_argument(
        "--motion",
        action="append",
        default=[],
        metavar="ARCHIVE_PATH=LOCAL_FILE",
        help=(
            "Optional bounded VRMA payload. ARCHIVE_PATH must be one fixed V1 path: "
            + ", ".join(OPTIONAL_MOTION_PATHS)
        ),
    )
    result.add_argument(
        "--builder-revision",
        help="Optional exact 40-character lowercase git SHA recorded in manifest.builder.revision",
    )
    return result


def _parse_motions(values: list[str]) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for value in values:
        archive_path, separator, local_path = value.partition("=")
        if not separator or not archive_path or not local_path:
            raise MRBodyError("--motion must use ARCHIVE_PATH=LOCAL_FILE")
        if archive_path not in OPTIONAL_MOTION_PATHS:
            raise MRBodyError(f"unsupported optional motion path: {archive_path!r}")
        if archive_path in result:
            raise MRBodyError(f"duplicate --motion archive path: {archive_path!r}")
        result[archive_path] = Path(local_path).read_bytes()
    return result


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
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
    identity = json.loads(args.identity_json.read_text(encoding="utf-8"))
    archive = build_mrbody(
        identity,
        display_name=args.name,
        avatar_vrm=args.avatar_vrm.read_bytes(),
        thumbnail_png=args.thumbnail_png.read_bytes(),
        motions=_parse_motions(args.motion),
        builder_revision=args.builder_revision,
    )
    _atomic_write_bytes(args.output_mrbody.resolve(), archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
