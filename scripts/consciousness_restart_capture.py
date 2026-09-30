#!/usr/bin/env python3
"""Capture before/after Consciousness runtime status around a real worker restart."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

STATUS_SCHEMA = "kaliv-consciousness-core/runtime-status/v1"
CAPTURE_SCHEMA = "kaliv-consciousness-core/restart-capture/v1"
DEFAULT_WORKER_URL = "http://127.0.0.1:8099"
DEFAULT_DIR = Path("validation/consciousness-restart")
MAX_RESPONSE_BYTES = 256 * 1024
SHA40 = re.compile(r"^[0-9a-f]{40}$")
RUNTIME_REF = re.compile(r"^runtime-instance:[0-9a-f]{32}$")


class RestartCaptureError(RuntimeError):
    pass


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temp = Path(handle.name)
    temp.replace(path)


def _read_json(path: Path, label: str) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RestartCaptureError(f"{label} cannot be read") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise RestartCaptureError(f"{label} is too large")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RestartCaptureError(f"{label} is not valid JSON") from exc
    if not isinstance(value, Mapping):
        raise RestartCaptureError(f"{label} must be a JSON object")
    return value


def _git(root: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RestartCaptureError("Git identity could not be inspected") from exc
    if proc.returncode != 0:
        raise RestartCaptureError("Git identity command failed")
    return proc.stdout.strip()


def candidate_identity(root: Path) -> dict[str, Any]:
    sha = _git(root, "rev-parse", "HEAD")
    if SHA40.fullmatch(sha) is None:
        raise RestartCaptureError("exact Git SHA is unavailable")
    dirty = _git(root, "status", "--porcelain")
    if dirty:
        raise RestartCaptureError("restart evidence requires a clean working tree")
    branch = _git(root, "branch", "--show-current")
    return {"git_sha": sha, "branch": branch or None, "working_tree_clean": True}


def normalize_worker_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RestartCaptureError("worker URL must be HTTP(S)")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RestartCaptureError("worker URL must be loopback")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RestartCaptureError("worker URL contains forbidden components")
    if parsed.path not in {"", "/"}:
        raise RestartCaptureError("worker URL must not contain a path")
    return value.strip().rstrip("/")


def fetch_status(worker_url: str, *, timeout: float) -> Mapping[str, Any]:
    base = normalize_worker_url(worker_url)
    request = urllib.request.Request(
        base + "/experimental/consciousness/status",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        raise RestartCaptureError(f"status endpoint returned HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RestartCaptureError("status endpoint could not be reached") from exc
    if status != 200:
        raise RestartCaptureError("status endpoint did not return HTTP 200")
    if len(payload) > MAX_RESPONSE_BYTES:
        raise RestartCaptureError("status response exceeded size bound")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RestartCaptureError("status response was not valid JSON") from exc
    if not isinstance(value, Mapping):
        raise RestartCaptureError("status response must be an object")
    if value.get("schema") != STATUS_SCHEMA:
        raise RestartCaptureError("status schema mismatch")
    runtime_ref = value.get("runtime_instance_ref")
    if not isinstance(runtime_ref, str) or RUNTIME_REF.fullmatch(runtime_ref) is None:
        raise RestartCaptureError("status lacks a valid runtime_instance_ref")
    if value.get("production_activation") is not False:
        raise RestartCaptureError("status overclaimed production activation")
    return value


def capture_before(*, root: Path, worker_url: str, timeout: float) -> dict[str, Any]:
    return {
        "schema": CAPTURE_SCHEMA,
        "phase": "before",
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "candidate": candidate_identity(root),
        "status": dict(fetch_status(worker_url, timeout=timeout)),
        "restart_proven": False,
        "production_activation": False,
    }


def capture_after(
    *,
    root: Path,
    worker_url: str,
    timeout: float,
    before: Mapping[str, Any],
) -> dict[str, Any]:
    if before.get("schema") != CAPTURE_SCHEMA or before.get("phase") != "before":
        raise RestartCaptureError("before capture schema/phase mismatch")
    prior_candidate = before.get("candidate")
    prior_status = before.get("status")
    if not isinstance(prior_candidate, Mapping) or not isinstance(prior_status, Mapping):
        raise RestartCaptureError("before capture is incomplete")

    current_candidate = candidate_identity(root)
    if current_candidate.get("git_sha") != prior_candidate.get("git_sha"):
        raise RestartCaptureError("Git SHA changed across restart boundary")
    current_status = dict(fetch_status(worker_url, timeout=timeout))
    if current_status["runtime_instance_ref"] == prior_status.get("runtime_instance_ref"):
        raise RestartCaptureError("worker runtime instance did not change")

    return {
        "schema": CAPTURE_SCHEMA,
        "phase": "after",
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "candidate": current_candidate,
        "before_runtime_instance_ref": prior_status.get("runtime_instance_ref"),
        "status": current_status,
        "restart_proven": True,
        "production_activation": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("before", "after"))
    parser.add_argument("--worker-url", default=os.environ.get("MODELRIG_WORKER_URL", DEFAULT_WORKER_URL))
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    before_path = args.dir / "before.json"
    after_path = args.dir / "after.json"

    try:
        if args.phase == "before":
            result = capture_before(root=root, worker_url=args.worker_url, timeout=args.timeout)
            _atomic_write(before_path, result)
        else:
            before = _read_json(before_path, "before capture")
            result = capture_after(
                root=root,
                worker_url=args.worker_url,
                timeout=args.timeout,
                before=before,
            )
            _atomic_write(after_path, result)
    except RestartCaptureError as exc:
        print(json.dumps({
            "state": "INVALID",
            "phase": args.phase,
            "error": str(exc),
            "production_activation": False,
        }, sort_keys=True))
        return 2

    print(json.dumps({
        "state": "CAPTURED",
        "phase": args.phase,
        "path": str(before_path if args.phase == "before" else after_path),
        "restart_proven": bool(result["restart_proven"]),
        "production_activation": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
