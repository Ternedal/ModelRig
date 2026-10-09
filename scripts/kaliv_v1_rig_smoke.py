#!/usr/bin/env python3
"""Read-only Kaliv V1 checkout, backend, worker and voice status smoke."""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True
import argparse
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
    return {"status": "PASS" if match and clean else "BLOCKED",
            "matches_expected": bool(match), "clean": bool(clean)}


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
    parser.add_argument("--backend-url", default="http://127.0.0.1:8080")
    parser.add_argument("--worker-url", default="http://127.0.0.1:8099")
    args = parser.parse_args(argv)
    try:
        report = smoke(
            root=Path(__file__).resolve().parents[1],
            expected_sha=args.expected_modelrig_sha,
            backend_url=args.backend_url, worker_url=args.worker_url)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["ready_for_real_voice_fixture_tests"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
