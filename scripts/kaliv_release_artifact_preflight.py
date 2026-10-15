#!/usr/bin/env python3
"""Independent, fail-closed *local artifact* attestation preflight.

This is not a release qualifier. It verifies that a supplied manifest's PASS
references have independently retrieved bytes matching operator-supplied
SHA-256 values. Producer-specific semantic replay and human approval are still
required before release authorization. No network access or production writes.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
import re
import stat
from pathlib import Path

from kaliv_system_release_gate import (
    REQUIRED_GATES,
    SystemReleaseManifestError,
    evaluate_manifest,
)

SHA256 = re.compile(r"^[0-9a-f]{64}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
MAX_BYTES = 16 * 1024 * 1024
MAX_JSON_BYTES = 1024 * 1024
MAX_JSON_DEPTH = 64
SCHEMA = "kaliv-artifact-byte-preflight/v1"

# These are the repositories whose revisions the canonical gate references
# identify, not the repository hosting a downloaded copy of the artifact.
# The two cross-repository gates are produced by ModelRig; evaluate_manifest
# independently validates all FOUR revisions embedded in those references.
GATE_REPOSITORIES = {
    "software_exact_green": "Ternedal/ModelRig",
    "consciousness_live_lifecycle": "Ternedal/ModelRig",
    "visionrig_physical_perception": "Ternedal/VisionRig",
    "voicerig_physical_acceptance": "Ternedal/VoiceRig",
    "bodyrig_photoreal_likeness": "Ternedal/BodyRig",
    "bodyrig_digital_twin_m6": "Ternedal/BodyRig",
    "bodyrig_android_live_body": "Ternedal/ModelRig",
    "end_to_end_latency": "Ternedal/ModelRig",
    "recovery_soak": "Ternedal/ModelRig",
    "repository_authority": "Ternedal/ModelRig",
}
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}


class AttestationError(ValueError):
    pass


def _relative_parts(value: object, gate: str) -> tuple[str, ...]:
    # Use the same portable spelling on Linux and Windows. In particular,
    # drive-relative paths, alternate streams and backslash traversal must
    # not become harmless Linux filenames and dangerous Windows paths.
    if (
        not isinstance(value, str) or not value or len(value) > 1024
        or any(char in value for char in '\\:<>"|?*')
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise AttestationError(f"{gate}: invalid relative path")
    parts = tuple(value.split("/"))
    if any(
        part in {"", ".", ".."} or part.endswith((".", " "))
        or part.split(".", 1)[0].rstrip(" .").upper() in _RESERVED_NAMES
        for part in parts
    ):
        raise AttestationError(f"{gate}: invalid relative path")
    return parts


def _inspect_path(root: Path, parts: tuple[str, ...], gate: str) -> os.stat_result:
    candidate = root
    for part in parts:
        candidate /= part
        info = candidate.lstat()
        # Windows directory junctions are reparse points, not necessarily
        # symlinks. Reject both rather than relying on Path.is_symlink().
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise AttestationError(f"{gate}: symlink artifact path or reparse point")
    if not stat.S_ISREG(info.st_mode):
        raise AttestationError(f"{gate}: unsafe or missing artifact")
    return info


@contextmanager
def _open_artifact(root: Path, parts: tuple[str, ...]):
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with ExitStack() as stack:
        if os.open in os.supports_dir_fd and hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW"):
            # Anchor every directory component to an open descriptor. A
            # parent replaced by a symlink cannot redirect the final open.
            directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            directory = os.open(root, directory_flags)
            stack.callback(os.close, directory)
            for part in parts[:-1]:
                directory = os.open(part, directory_flags, dir_fd=directory)
                stack.callback(os.close, directory)
            fd = os.open(parts[-1], flags, dir_fd=directory)
        else:
            # Platforms without openat require an operator-owned quiescent
            # artifact directory. Before/after path and descriptor identity
            # checks detect ordinary replacement; this is not a concurrent
            # hostile-filesystem security boundary on those platforms.
            fd = os.open(root.joinpath(*parts), flags)
        try:
            artifact = os.fdopen(fd, "rb")
        except BaseException:
            os.close(fd)
            raise
        with artifact:
            yield artifact


def _artifact_hash(root: Path, parts: tuple[str, ...], gate: str) -> tuple[str, int]:
    before = _inspect_path(root, parts, gate)
    with _open_artifact(root, parts) as artifact:
        info = os.fstat(artifact.fileno())
        if not stat.S_ISREG(info.st_mode) or not os.path.samestat(before, info):
            raise AttestationError(f"{gate}: artifact changed during verification")
        if info.st_size > MAX_BYTES:
            raise AttestationError(f"{gate}: artifact exceeds size limit")
        hasher = hashlib.sha256()
        total = 0
        while chunk := artifact.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_BYTES:
                raise AttestationError(f"{gate}: artifact exceeds size limit")
            hasher.update(chunk)
        after = os.fstat(artifact.fileno())
        path_info = _inspect_path(root, parts, gate)
        if (
            not os.path.samestat(info, path_info) or total != info.st_size
            or (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            != (info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        ):
            raise AttestationError(f"{gate}: artifact changed during verification")
    return hasher.hexdigest(), total


def preflight(manifest: dict, attestations: dict, root: Path) -> dict:
    """Check exact one-to-one coverage, bounded regular files, hashes and pins."""
    try:
        verdict = evaluate_manifest(manifest)
    except (SystemReleaseManifestError, ValueError, TypeError, KeyError) as exc:
        raise AttestationError(f"invalid release manifest: {exc}") from exc
    if not verdict.release_ready:
        raise AttestationError("structural release manifest is not fully qualified")
    if not isinstance(attestations, dict) or set(attestations) != set(REQUIRED_GATES):
        raise AttestationError("attestation set must exactly cover required gates")
    if not root.is_dir():
        raise AttestationError("artifact root does not exist")
    root = root.resolve(strict=True)
    checked = []
    verified_artifacts = []
    for gate in REQUIRED_GATES:
        item = attestations[gate]
        if not isinstance(item, dict) or set(item) != {"reference", "path", "sha256", "repository", "git_sha"}:
            raise AttestationError(f"{gate}: invalid attestation fields")
        refs = manifest["gates"][gate]["evidence_refs"]
        if len(refs) != 1 or item["reference"] != refs[0]:
            raise AttestationError(f"{gate}: reference mismatch")
        repo = item["repository"]
        if repo != GATE_REPOSITORIES[gate]:
            raise AttestationError(f"{gate}: evidence repository mismatch")
        if item["git_sha"] != verdict.pinned_repositories[repo]:
            raise AttestationError(f"{gate}: repository pin mismatch")
        if not isinstance(item["git_sha"], str) or not SHA40.fullmatch(item["git_sha"]):
            raise AttestationError(f"{gate}: invalid git SHA")
        digest = item["sha256"]
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise AttestationError(f"{gate}: invalid SHA-256")
        # Canonical reference digests may hash producer payloads rather than
        # the artifact file bytes. Do not equate these independent digests.
        # Producer-specific semantic replay must validate reference payloads.
        parts = _relative_parts(item["path"], gate)
        actual_digest, size = _artifact_hash(root, parts, gate)
        if actual_digest != digest:
            raise AttestationError(f"{gate}: artifact byte hash mismatch")
        checked.append(gate)
        verified_artifacts.append({"gate": gate, **item, "size_bytes": size})
    return {
        "schema": SCHEMA,
        "state": "BYTE_HASHES_VERIFIED_ONLY",
        "release_id": verdict.release_id,
        "pinned_repositories": dict(verdict.pinned_repositories),
        "release_ready": False,
        "production_activation": False,
        "checked_gates": checked,
        "verified_artifacts": verified_artifacts,
        "requires": ["producer_semantic_replay", "human_approval", "trusted_provenance"],
    }


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise AttestationError("duplicate JSON object field")
        result[key] = value
    return result


def _invalid_constant(value: str):
    raise AttestationError(f"invalid JSON constant: {value}")


def _load_json_object(path: Path) -> dict:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    with ExitStack() as stack:
        fd = os.open(path, flags)
        stack.callback(os.close, fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise AttestationError("JSON input must be a regular file")
        if info.st_size > MAX_JSON_BYTES:
            raise AttestationError("JSON input exceeds size limit")
        with os.fdopen(fd, "rb", closefd=False) as source:
            raw = source.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise AttestationError("JSON input exceeds size limit")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_invalid_constant)
    except RecursionError as exc:
        raise AttestationError("JSON input exceeds nesting limit") from exc
    pending = [(value, 1)]
    while pending:
        node, depth = pending.pop()
        if depth > MAX_JSON_DEPTH:
            raise AttestationError("JSON input exceeds nesting limit")
        children = node.values() if isinstance(node, dict) else node if isinstance(node, list) else ()
        pending.extend((child, depth + 1) for child in children if isinstance(child, (dict, list)))
    if not isinstance(value, dict):
        raise AttestationError("JSON input must be an object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("attestations", type=Path)
    parser.add_argument("artifact_root", type=Path)
    args = parser.parse_args(argv)
    try:
        output = preflight(_load_json_object(args.manifest),
                           _load_json_object(args.attestations),
                           args.artifact_root)
    except (ValueError, OSError, KeyError, TypeError, RecursionError) as exc:
        print(json.dumps({"schema": SCHEMA, "state": "INVALID", "release_ready": False,
                          "production_activation": False, "error": str(exc)}))
        return 2
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

