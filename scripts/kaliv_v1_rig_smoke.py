#!/usr/bin/env python3
"""Read-only Kaliv V1 checkout, backend, worker and voice status smoke."""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True
import argparse
import hashlib
import http.client
import json
import os
import re
import stat
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import voice_runtime_preflight as voice  # noqa: E402

SCHEMA = "kaliv-v1-readonly-rig-smoke/v1"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
UNTESTED = (
    "real_danish_wav_asr_tts", "voicerig_cuda_human_listening",
    "visionrig_physical_camera", "bodyrig_held_out_photoreal",
    "bodyrig_windows_quest", "android_arcore_live_body",
    "consciousness_restart", "end_to_end_latency", "recovery_soak",
    "repository_authority",
)


def safe_root(root: Path) -> bool:
    """Reject symlink and Windows junction/reparse checkout roots and ancestors."""
    if not root.is_absolute() or not root.is_dir():
        return False
    try:
        for component in (root, *root.parents):
            if component.is_symlink():
                return False
            is_junction = getattr(component, "is_junction", None)
            if is_junction is not None and is_junction():
                return False
            attrs = getattr(component.lstat(), "st_file_attributes", 0)
            if attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                return False
    except (OSError, ValueError):
        return False
    return True


def _git(root: Path, *args: str, text: bool = False):
    """Use a sanitized Git environment, never an operator's alternate index.

    GIT_INDEX_FILE / GIT_DIR / GIT_WORK_TREE / GIT_CONFIG_* and related
    variables otherwise override the inspected checkout even with -C root.
    Inherit only non-GIT variables needed for Git executable discovery and
    Windows runtime startup; force optional locks off for read-only listing.
    """
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith("GIT_")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        ["git", "--no-replace-objects", "-C", str(root),
         "-c", "core.fsmonitor=false", *args],
        capture_output=True, text=text, timeout=20, check=False, env=env,
    )


def tracked_bytes_match(root: Path) -> bool:
    """Verify the HEAD tree, staging index, nonignored extras and disk bytes.

    git status may execute configured external clean filters or trust index
    flags that hide changed files. Only read Git object/index listings and
    hash disk bytes; no filters, hooks or mutable state are consulted.
    """
    try:
        tree = _git(root, "ls-tree", "-r", "-z", "HEAD")
        index = _git(root, "ls-files", "--stage", "-z")
        extras = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    except (OSError, subprocess.TimeoutExpired):
        return False
    if (tree.returncode or index.returncode or extras.returncode
            or not isinstance(tree.stdout, bytes)
            or not isinstance(index.stdout, bytes)
            or not isinstance(extras.stdout, bytes) or extras.stdout):
        return False
    index_blobs = {}
    for entry in (x for x in index.stdout.split(b"\0") if x):
        head, sep, filename = entry.partition(b"\t")
        fields = head.split()
        if not sep or len(fields) != 3 or fields[2] != b"0" or filename in index_blobs:
            return False
        index_blobs[filename] = (fields[0], fields[1])
    records = [entry for entry in tree.stdout.split(b"\0") if entry]
    if not records or len(records) != len(index_blobs):
        return False
    seen = set()
    for record in records:
        header, sep, filename = record.partition(b"\t")
        fields = header.split()
        if not sep or len(fields) != 3 or fields[1] != b"blob":
            return False
        mode, _, expected_sha = fields
        if (mode not in (b"100644", b"100755", b"120000")
                or filename in seen or index_blobs.get(filename) != (mode, expected_sha)):
            return False
        seen.add(filename)
        try:
            path = Path(filename.decode("utf-8"))
            if path.is_absolute() or ".." in path.parts or not path.parts:
                return False
            local = root / path
            parent = root
            for component in path.parts[:-1]:
                parent = parent / component
                if parent.is_symlink():
                    return False
            if mode == b"120000":
                if not local.is_symlink():
                    return False
                body = local.readlink().as_posix().encode("utf-8")
                digest = hashlib.sha1(
                    b"blob " + str(len(body)).encode("ascii") + b"\0" + body
                ).hexdigest()
            else:
                if local.is_symlink() or not local.is_file():
                    return False
                size = local.stat().st_size
                hasher = hashlib.sha1()
                hasher.update(b"blob " + str(size).encode("ascii") + b"\0")
                with local.open("rb") as fd:
                    while True:
                        block = fd.read(1024 * 1024)
                        if not block:
                            break
                        hasher.update(block)
                digest = hasher.hexdigest()
            if digest != expected_sha.decode("ascii"):
                return False
        except (OSError, UnicodeError, ValueError):
            return False
    return True


def checkout_identity(root: Path, expected_sha: str) -> dict:
    if not SHA40.fullmatch(expected_sha):
        raise ValueError("expected ModelRig SHA must be lowercase 40-hex")
    if not safe_root(root):
        return {"status": "BLOCKED", "matches_expected": False,
                "clean": False, "tracked_bytes_match": False}
    try:
        toplevel = _git(root, "rev-parse", "--show-toplevel", text=True)
        head = _git(root, "rev-parse", "HEAD", text=True)
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "UNVERIFIED", "matches_expected": False,
                "clean": False, "tracked_bytes_match": False}
    valid = toplevel.returncode == 0 and head.returncode == 0
    try:
        valid = valid and Path(toplevel.stdout.strip()).resolve() == root.resolve()
    except (OSError, ValueError):
        valid = False
    matched = bool(valid and head.stdout.strip() == expected_sha)
    tracked = bool(matched and tracked_bytes_match(root))
    try:
        last_head = _git(root, "rev-parse", "HEAD", text=True)
        stable = last_head.returncode == 0 and last_head.stdout.strip() == expected_sha
    except (OSError, subprocess.TimeoutExpired):
        stable = False
    verified = bool(tracked and stable and safe_root(root))
    return {"status": "PASS" if verified else "BLOCKED",
            "matches_expected": bool(matched and stable), "clean": verified,
            "tracked_bytes_match": verified}


def health(base: str, expected_service: str) -> dict:
    req = urllib.request.Request(
        base + "/healthz", method="GET", headers={"Accept": "application/json"})
    try:
        with voice._open_worker_status(req) as response:
            if response.status != 200:
                return {"status": "BLOCKED", "reason": "non-200 health status"}
            raw = response.read(voice.MAX_STATUS_BYTES + 1)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
            OSError, http.client.HTTPException):
        return {"status": "BLOCKED", "reason": "health endpoint unavailable"}
    if len(raw) > voice.MAX_STATUS_BYTES:
        return {"status": "BLOCKED", "reason": "oversized health response"}
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {"status": "BLOCKED", "reason": "invalid health JSON"}
    if (not isinstance(payload, dict) or payload.get("status") != "ok"
            or payload.get("service") != expected_service):
        return {"status": "BLOCKED", "reason": "health service/status mismatch"}
    return {"status": "PASS"}


def availability(base: str, path: str) -> dict:
    try:
        payload = voice.query_worker(base, path)
    except ValueError:
        return {"status": "BLOCKED", "reason": "voice status probe failed"}
    return {"status": "PASS" if payload["available"] is True else "BLOCKED",
            "available": payload["available"]}


def smoke(*, root: Path, expected_sha: str, backend_url: str, worker_url: str) -> dict:
    # Validate both URLs BEFORE issuing a request; no proxy, redirects or remote hosts.
    backend = voice.worker_base(backend_url)
    worker = voice.worker_base(worker_url)
    before = checkout_identity(root, expected_sha)
    probes = {
        "backend": health(backend, "modelrig-server"),
        "worker": health(worker, "modelrig-worker"),
        "asr": availability(worker, voice.ENDPOINTS["asr"]),
        "tts": availability(worker, voice.ENDPOINTS["tts"]),
    }
    source = checkout_identity(root, expected_sha)
    if before["status"] != "PASS":
        source = {**source, "status": "BLOCKED"}
    ready = source["status"] == "PASS" and all(
        item["status"] == "PASS" for item in probes.values())
    return {
        "schema": SCHEMA, "source": source, "probes": probes,
        "ready_for_real_voice_fixture_tests": ready,
        "physical_gates": {gate: "NOT_TESTED" for gate in UNTESTED},
        "release_gate_satisfied": False, "production_activation": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-modelrig-sha", required=True)
    parser.add_argument("--checkout-root", type=Path, help="absolute path to a separate clean checkout to inspect (read-only)")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8080")
    parser.add_argument("--worker-url", default="http://127.0.0.1:8099")
    args = parser.parse_args(argv)
    root = args.checkout_root or Path(__file__).resolve().parents[1]
    if not safe_root(root):
        parser.error("--checkout-root must be absolute and free of symlinks, junctions and reparse ancestors")
    try:
        report = smoke(
            root=root,
            expected_sha=args.expected_modelrig_sha,
            backend_url=args.backend_url, worker_url=args.worker_url)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["ready_for_real_voice_fixture_tests"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
