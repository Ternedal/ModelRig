#!/usr/bin/env python3
"""Independent, fail-closed *local artifact* attestation preflight.

This is not a release qualifier. It verifies that a supplied manifest's PASS
references have independently retrieved bytes matching operator-supplied
SHA-256 values. Optional replay covers seven producer qualifiers;
remaining semantic checks, trusted provenance and human approval are still
required before release authorization. No network access or production writes.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import hashlib
import importlib
import json
import math
import os
import re
import stat
import tempfile
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
MAX_ERROR_CHARS = 1024
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
# Fixed allowlist: artifact content never selects executable code. These
# existing qualifiers accept data or bounded private receipt snapshots;
# live campaign validators remain outside this offline replay path.
PRODUCER_REPLAY = {
    "software_exact_green": ("kaliv_software_exact_green_qualifier", None, None),
    "consciousness_live_lifecycle": ("consciousness_live_lifecycle_qualifier", None, None),
    "voicerig_physical_acceptance": ("kaliv_voicerig_physical_qualifier", "expected_voicerig_sha", "Ternedal/VoiceRig"),
    "bodyrig_photoreal_likeness": ("kaliv_bodyrig_photoreal_qualifier", "expected_bodyrig_sha", "Ternedal/BodyRig"),
    "bodyrig_digital_twin_m6": ("kaliv_bodyrig_digital_twin_m6_qualifier", "expected_bodyrig_sha", "Ternedal/BodyRig"),
    "end_to_end_latency": ("kaliv_end_to_end_latency_qualifier", None, None),
    "repository_authority": ("kaliv_repository_authority_qualifier", None, None),
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


def _same_snapshot(before: os.stat_result, after: os.stat_result) -> bool:
    return os.path.samestat(before, after) and (
        before.st_size, before.st_mtime_ns, before.st_ctime_ns
    ) == (after.st_size, after.st_mtime_ns, after.st_ctime_ns)


def _artifact_hash(root: Path, parts: tuple[str, ...], gate: str, *,
                   collect_json: bool = False) -> tuple[str, int, bytes | None]:
    before = _inspect_path(root, parts, gate)
    maximum = min(MAX_BYTES, MAX_JSON_BYTES) if collect_json else MAX_BYTES
    chunks = [] if collect_json else None
    with _open_artifact(root, parts) as artifact:
        info = os.fstat(artifact.fileno())
        if not stat.S_ISREG(info.st_mode) or not _same_snapshot(before, info):
            raise AttestationError(f"{gate}: artifact changed during verification")
        if info.st_size > maximum:
            raise AttestationError(f"{gate}: artifact exceeds size limit")
        hasher = hashlib.sha256()
        total = 0
        while chunk := artifact.read(1024 * 1024):
            total += len(chunk)
            if total > maximum:
                raise AttestationError(f"{gate}: artifact exceeds size limit")
            hasher.update(chunk)
            if chunks is not None:
                chunks.append(chunk)
        after = os.fstat(artifact.fileno())
        path_info = _inspect_path(root, parts, gate)
        if (
            total != info.st_size or not _same_snapshot(info, after)
            or not _same_snapshot(info, path_info)
        ):
            raise AttestationError(f"{gate}: artifact changed during verification")
    return hasher.hexdigest(), total, b"".join(chunks) if chunks is not None else None


def _replay_latency(producer, payload: dict, root: Path) -> tuple[dict, list[dict]]:
    """Rerun the unchanged file validator against three bounded byte snapshots."""
    gate = "end_to_end_latency"
    phases = ("perception_received", "cognition_completed", "outward_started")
    sources = payload.get("source_receipts")
    if payload.get("schema") != producer.VERDICT_SCHEMA:
        raise AttestationError("latency artifact must be the canonical v2 verdict")
    if not isinstance(sources, list) or len(sources) != 3:
        raise AttestationError("invalid latency source_receipts")
    loaded = {}
    verified_sources = []
    for item in sources:
        if not isinstance(item, dict) or set(item) != {"phase", "path", "sha256"}:
            raise AttestationError("invalid latency source_receipts fields")
        phase = item["phase"]
        if not isinstance(phase, str) or phase not in phases or phase in loaded:
            raise AttestationError("invalid latency source_receipts phases")
        digest = item["sha256"]
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise AttestationError(f"{phase}: invalid source SHA-256")
        parts = _relative_parts(item["path"], f"{gate}.{phase}")
        actual, size, raw = _artifact_hash(root, parts, f"{gate}.{phase}", collect_json=True)
        if actual != digest:
            raise AttestationError(f"{phase}: source byte hash mismatch")
        _parse_json_object(raw)
        loaded[phase] = (parts, raw)
        verified_sources.append({**item, "size_bytes": size})

    # Keep original relative names because they are part of the producer's
    # canonical reference. Only private temporary files are written. Reusing
    # the real validator avoids inventing a second latency/correlation policy.
    with tempfile.TemporaryDirectory(prefix="kaliv-latency-replay-") as directory:
        snapshot_root = Path(directory)
        for parts, raw in loaded.values():
            target = snapshot_root.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                output.write(raw)
        verdict = producer.qualify_receipts(
            evidence_root=snapshot_root,
            perception_path=Path(*loaded["perception_received"][0]),
            cognition_path=Path(*loaded["cognition_completed"][0]),
            outward_path=Path(*loaded["outward_started"][0]),
        )
    if producer._canonical(verdict) != producer._canonical(payload):
        raise AttestationError("latency verdict does not match source receipts")
    return verdict, verified_sources


def _replay_producer(gate: str, raw: bytes, pins: dict[str, str], expected_ref: str, *, root: Path) -> dict:
    try:
        module_name, pin_argument, repository = PRODUCER_REPLAY[gate]
        producer = importlib.import_module(module_name)
        payload = _parse_json_object(raw)
        verified_sources = None
        if gate == "end_to_end_latency":
            verdict, verified_sources = _replay_latency(producer, payload, root)
            expected_state = "MEASURED"
        else:
            kwargs = {pin_argument: pins[repository]} if pin_argument else {}
            verdict = producer.qualify(payload, **kwargs)
            expected_state = "QUALIFIED"
        if (
            verdict.get("state") != expected_state
            or verdict.get("production_activation") is not False
            or verdict.get("release_gate_satisfied", False) is not False
            or verdict.get("release_ready", False) is not False
        ):
            raise AttestationError("producer verdict is not a bounded qualification")
        if verdict.get("release_evidence_ref") != expected_ref:
            raise AttestationError("producer evidence reference mismatch")
        result = {
            "gate": gate,
            "producer_schema": verdict["schema"],
            "release_evidence_ref": expected_ref,
            "state": "PRODUCER_PAYLOAD_REPLAYED_ONLY",
            "production_activation": False,
        }
        if verified_sources is not None:
            result["verified_source_receipts"] = verified_sources
        return result
    except OverflowError as exc:
        raise AttestationError(
            f"{gate}: producer replay failed: numeric value exceeds supported range"
        ) from exc
    except (ImportError, OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise AttestationError(f"{gate}: producer replay failed: {exc}") from exc


def preflight(manifest: dict, attestations: dict, root: Path, *,
              replay_producers: bool = False) -> dict:
    """Check exact one-to-one coverage, bounded regular files, hashes and pins."""
    if type(replay_producers) is not bool:
        raise AttestationError("replay_producers must be a boolean")
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
    replayed = []
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
        collect_json = replay_producers and gate in PRODUCER_REPLAY
        actual_digest, size, payload = _artifact_hash(root, parts, gate, collect_json=collect_json)
        if actual_digest != digest:
            raise AttestationError(f"{gate}: artifact byte hash mismatch")
        if collect_json:
            # Parse the very bytes that were hashed, without reopening the
            # path after the byte-integrity check (which would introduce a
            # second-read replacement race).
            replayed.append(_replay_producer(gate, payload, verdict.pinned_repositories, refs[0], root=root))
        checked.append(gate)
        verified_artifacts.append({"gate": gate, **item, "size_bytes": size})
    result = {
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
    if replay_producers:
        verified = [item["gate"] for item in replayed]
        result["producer_replay"] = {
            "state": "PARTIAL",
            "complete": False,
            "verified_gates": verified,
            "not_replayed_gates": [gate for gate in REQUIRED_GATES if gate not in verified],
            "verdicts": replayed,
        }
    return result


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise AttestationError("duplicate JSON object field")
        result[key] = value
    return result


def _invalid_constant(value: str):
    raise AttestationError(f"invalid JSON constant: {value}")


def _finite_json_float(value: str) -> float:
    # parse_constant only rejects literal NaN/Infinity. Valid JSON exponent
    # tokens such as 1e999 otherwise silently decode to float infinity.
    number = float(value)
    if not math.isfinite(number):
        raise AttestationError("non-finite JSON number")
    return number


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
            after = os.fstat(fd)
            # Config paths may be explicit operator-selected symlinks. Follow
            # that path for identity checks, without changing their policy.
            path_info = path.stat()
            if (len(raw) != info.st_size or not _same_snapshot(info, after)
                    or not _same_snapshot(info, path_info)):
                raise AttestationError("JSON input changed during verification")
    return _parse_json_object(raw)


def _parse_json_object(raw: bytes) -> dict:
    if len(raw) > MAX_JSON_BYTES:
        raise AttestationError("JSON input exceeds size limit")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_invalid_constant, parse_float=_finite_json_float)
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


def _failure_report(error: Exception) -> dict:
    message = str(error)
    truncated = len(message) > MAX_ERROR_CHARS
    if truncated:
        message = message[:MAX_ERROR_CHARS - 3] + "..."
    result = {
        "schema": SCHEMA, "state": "INVALID", "release_ready": False,
        "production_activation": False, "error": message,
    }
    if truncated:
        result["error_truncated"] = True
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("attestations", type=Path)
    parser.add_argument("artifact_root", type=Path)
    parser.add_argument("--replay-producers", action="store_true",
                        help="Revalidate seven supported producers; other gates remain unreplayed.")
    args = parser.parse_args(argv)
    try:
        output = preflight(_load_json_object(args.manifest),
                           _load_json_object(args.attestations),
                           args.artifact_root, replay_producers=args.replay_producers)
    except (ValueError, OSError, KeyError, TypeError, RecursionError) as exc:
        print(json.dumps(_failure_report(exc)))
        return 2
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
