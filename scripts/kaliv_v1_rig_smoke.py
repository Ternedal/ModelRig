#!/usr/bin/env python3
"""Read-only Kaliv V1 checkout, backend, worker and voice status smoke."""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True
import argparse
import hashlib
import http.client
import json
import re
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


def tracked_bytes_match(root: Path) -> bool:
    """Verify all tracked HEAD blob bytes, not just the mutable Git index."""
    try:
        tree = subprocess.run(
            ["git", "-C", str(root), "ls-tree", "-r", "-z", "HEAD"],
            capture_output=True, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if tree.returncode != 0 or not isinstance(tree.stdout, bytes):
        return False
    records = [record for record in tree.stdout.split(b"\0") if record]
    if not records:
        return False
    for record in records:
        header, sep, raw_name = record.partition(b"\t")
        fields = header.split()
        if not sep or len(fields) != 3 or fields[1] != b"blob":
            return False
        mode, _, expected_sha = fields
        if mode not in (b"100644", b"100755", b"120000"):
            return False
        try:
            name = raw_name.decode("utf-8")
            path = Path(name)
            if not name or path.is_absolute() or ".." in path.parts:
                return False
            local = root / path
            parent = root
            for segment in path.parts[:-1]:
                parent = parent / segment
                if parent.is_symlink():
                    return False
            if mode == b"120000":
                if not local.is_symlink():
                    return False
                content = local.readlink().as_posix().encode("utf-8")
                digest = hashlib.sha1(
                    b"blob " + str(len(content)).encode("ascii") + b"\0" + content
                ).hexdigest()
            else:
                if local.is_symlink() or not local.is_file():
                    return False
                size = local.stat().st_size
                sha = hashlib.sha1()
                sha.update(b"blob " + str(size).encode("ascii") + b"\0")
                with local.open("rb") as reader:
                    while True:
                        block = reader.read(1024 * 1024)
                        if not block:
                            break
                        sha.update(block)
                digest = sha.hexdigest()
            if digest != expected_sha.decode("ascii"):
                return False
        except (OSError, UnicodeError, ValueError):
            return False
    return True


def checkout_identity(root: Path, expected_sha: str) -> dict:
    if not SHA40.fullmatch(expected_sha):
        raise ValueError("expected ModelRig SHA must be lowercase 40-hex")
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False)
        status = subprocess.run(
            ["git", "-C", str(root), "--no-optional-locks", "status", "--porcelain", "--untracked-files=normal"],
            capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "UNVERIFIED", "matches_expected": False, "clean": False}
    valid = head.returncode == 0 and status.returncode == 0
    match = valid and head.stdout.strip() == expected_sha
    clean = valid and not status.stdout.strip()
    tracked = bool(match and clean and tracked_bytes_match(root))
    return {"status": "PASS" if tracked else "BLOCKED",
            "matches_expected": bool(match), "clean": bool(clean),
            "tracked_bytes_match": tracked}


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
    source = checkout_identity(root, expected_sha)
    probes = {
        "backend": health(backend, "modelrig-server"),
        "worker": health(worker, "modelrig-worker"),
        "asr": availability(worker, voice.ENDPOINTS["asr"]),
        "tts": availability(worker, voice.ENDPOINTS["tts"]),
    }
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
    if args.checkout_root is not None and (
        not root.is_absolute() or not root.is_dir() or root.is_symlink()
    ):
        parser.error("--checkout-root must name an existing absolute nonsymlink directory")
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
