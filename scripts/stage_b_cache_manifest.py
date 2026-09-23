#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable

MANIFEST_NAME = ".modelrig-stage-b-cache-manifest.json"
SCHEMA = "modelrig-stage-b-cache/v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class CacheManifestError(RuntimeError):
    pass


def _validated_head_sha(value: str) -> str:
    value = value.strip()
    if not _SHA_RE.fullmatch(value):
        raise CacheManifestError(
            "Stage-B cache head SHA must be exactly 40 lowercase hexadecimal characters"
        )
    return value


def _real_directory(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise CacheManifestError(f"{label} must be a real directory")
    return path.resolve()


def _payload_files(root: Path) -> list[tuple[str, Path]]:
    root = _real_directory(root, "Stage-B cache root")
    proof_cache = root / "proofs.json"
    start_ledger = root / "start-ledger"
    if proof_cache.is_symlink() or not proof_cache.is_file():
        raise CacheManifestError("Stage-B cache root must contain a real proofs.json file")
    _real_directory(start_ledger, "Stage-B start-ledger")

    payload: list[tuple[str, Path]] = []
    for directory, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        directory_path = Path(directory)
        for dirname in dirnames:
            candidate = directory_path / dirname
            if candidate.is_symlink():
                raise CacheManifestError(
                    f"Stage-B cache payload must not contain symlink directory: "
                    f"{candidate.relative_to(root).as_posix()}"
                )
        for filename in filenames:
            candidate = directory_path / filename
            relative = candidate.relative_to(root).as_posix()
            if relative == MANIFEST_NAME:
                continue
            if candidate.is_symlink() or not candidate.is_file():
                raise CacheManifestError(
                    f"Stage-B cache payload entry must be a real file: {relative}"
                )
            payload.append((relative, candidate))

    payload.sort(key=lambda item: item[0])
    return payload


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _content_digest(payload: Iterable[tuple[str, Path]]) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for relative, path in payload:
        file_digest = _file_sha256(path)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
        digest.update(b"\n")
        count += 1
    return digest.hexdigest(), count


def create_manifest(root: Path, head_sha: str) -> dict[str, object]:
    root = _real_directory(root, "Stage-B cache root")
    head_sha = _validated_head_sha(head_sha)
    manifest_path = root / MANIFEST_NAME
    if manifest_path.exists() or manifest_path.is_symlink():
        raise CacheManifestError("Stage-B cache manifest target must not already exist")

    content_sha256, file_count = _content_digest(_payload_files(root))
    manifest: dict[str, object] = {
        "schema": SCHEMA,
        "head_sha": head_sha,
        "content_sha256": content_sha256,
        "file_count": file_count,
    }
    temporary = root / f"{MANIFEST_NAME}.tmp"
    if temporary.exists() or temporary.is_symlink():
        raise CacheManifestError("Stage-B cache manifest temporary target is unsafe")
    temporary.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, manifest_path)
    return manifest


def verify_manifest(root: Path, expected_head_sha: str) -> dict[str, object]:
    root = _real_directory(root, "Stage-B cache root")
    expected_head_sha = _validated_head_sha(expected_head_sha)
    manifest_path = root / MANIFEST_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise CacheManifestError("Stage-B cache manifest is missing or unsafe")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CacheManifestError("Stage-B cache manifest is unreadable") from exc
    if not isinstance(manifest, dict):
        raise CacheManifestError("Stage-B cache manifest must be a JSON object")
    if manifest.get("schema") != SCHEMA:
        raise CacheManifestError("Stage-B cache manifest schema mismatch")
    if manifest.get("head_sha") != expected_head_sha:
        raise CacheManifestError("Stage-B cache manifest exact-head SHA mismatch")

    content_sha256, file_count = _content_digest(_payload_files(root))
    if manifest.get("content_sha256") != content_sha256:
        raise CacheManifestError("Stage-B cache payload digest mismatch")
    if manifest.get("file_count") != file_count:
        raise CacheManifestError("Stage-B cache payload file-count mismatch")
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create or verify an exact-head Stage-B cache manifest."
    )
    parser.add_argument("mode", choices=("create", "verify"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--head-sha", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.mode == "create":
            manifest = create_manifest(args.root, args.head_sha)
        else:
            manifest = verify_manifest(args.root, args.head_sha)
    except CacheManifestError as exc:
        print(f"Stage-B cache manifest error: {exc}", file=sys.stderr)
        return 1

    print(
        f"Stage-B cache manifest {args.mode} OK: "
        f"head={manifest['head_sha']} files={manifest['file_count']} "
        f"digest={manifest['content_sha256']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
