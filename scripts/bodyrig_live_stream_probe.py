#!/usr/bin/env python3
"""Probe the real ModelRig BodyRig stream before launching Unity.

The probe is deliberately renderer-free: it proves that one authenticated rig
URL serves the expected active body and a bounded sequence of valid v0.1 render
frames. The device token is read from an environment variable and is never
written to the receipt or accepted on the command line.

Render-frame `data:` is required to be the canonical v0.1 object with no
compatibility stripping. Body/session identity is carried separately in the
`X-BodyRig-*` response headers and is bound into the preflight receipt.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bodyrig import render_frame_from_mapping  # noqa: E402

SCHEMA = "bodyrig.live_stream_probe/v0.1"
BODY_ID_RE = re.compile(r"^bodyid-[0-9a-f]{24}$")
SESSION_ID_RE = re.compile(r"^body-[0-9a-f]{12}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class ProbeError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    """Fail closed before a Bearer token can be replayed to another URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


_NO_REDIRECT_OPENER = build_opener(_NoRedirect)


def _canonical_base_url(raw: str) -> str:
    parts = urlsplit(raw.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ProbeError("base URL must be absolute http/https")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ProbeError("base URL must not contain credentials, query or fragment")
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _request(url: str, token: str, *, accept: str, timeout: float) -> tuple[bytes, dict[str, str]]:
    req = Request(
        url,
        method="GET",
        headers={"Authorization": "Bearer " + token, "Accept": accept},
    )
    try:
        # Redirects are intentionally disabled. A rig endpoint that redirects
        # is a configuration error; following it could replay the device token
        # to a different origin before we had a chance to inspect the target.
        with _NO_REDIRECT_OPENER.open(req, timeout=timeout) as response:  # noqa: S310 - operator-selected rig URL
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            headers = {name.lower(): value for name, value in response.headers.items()}
    except HTTPError as exc:
        raise ProbeError(f"rig returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise ProbeError("rig is unreachable") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ProbeError("rig response exceeds safety cap")
    return raw, headers


def _json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ProbeError(f"{label} must be a JSON object")
    return value


def _parse_sse(raw: bytes, *, expected_count: int) -> list[dict[str, Any]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProbeError("frame stream is not UTF-8") from exc
    payloads: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            value = json.loads(line[6:])
        except json.JSONDecodeError as exc:
            raise ProbeError("frame stream contains malformed data JSON") from exc
        if not isinstance(value, dict):
            raise ProbeError("frame SSE data must be a JSON object")
        try:
            render_frame_from_mapping(value)
        except Exception as exc:
            raise ProbeError("frame stream violates canonical render_frame v0.1") from exc
        payloads.append(value)
        if len(payloads) == expected_count:
            break
    if len(payloads) != expected_count:
        raise ProbeError(f"expected {expected_count} SSE frames, got {len(payloads)}")
    return payloads


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ProbeError("cannot resolve repository HEAD") from exc
    sha = result.stdout.strip()
    if not GIT_SHA_RE.fullmatch(sha):
        raise ProbeError("repository HEAD is not a canonical git SHA")
    return sha


def run_probe(
    *,
    base_url: str,
    token: str,
    expected_body_id: str,
    expected_package_sha256: str,
    frame_count: int,
    timeout: float,
) -> dict[str, Any]:
    base = _canonical_base_url(base_url)
    if not token.strip():
        raise ProbeError("device token environment variable is empty")
    if not BODY_ID_RE.fullmatch(expected_body_id):
        raise ProbeError("expected body id is invalid")
    if not SHA256_RE.fullmatch(expected_package_sha256):
        raise ProbeError("expected package SHA-256 is invalid")
    if frame_count < 2 or frame_count > 100:
        raise ProbeError("frame count must be between 2 and 100")
    if timeout <= 0 or timeout > 60:
        raise ProbeError("timeout must be > 0 and <= 60 seconds")

    active_raw, _active_headers = _request(
        base + "/api/v1/body/active", token, accept="application/json", timeout=timeout
    )
    active = _json_object(active_raw, label="active body manifest")
    if active.get("schema") != "modelrig-body-assets/v1":
        raise ProbeError("active body manifest schema mismatch")
    if active.get("body_id") != expected_body_id:
        raise ProbeError("rig active body differs from the prepared renderer body")
    if active.get("package_sha256") != expected_package_sha256:
        raise ProbeError("rig active package differs from the prepared renderer package")

    query = urlencode({"limit": frame_count})
    frame_raw, frame_headers = _request(
        base + "/api/v1/body/frames?" + query,
        token,
        accept="text/event-stream",
        timeout=timeout,
    )
    frame_body_id = frame_headers.get("x-bodyrig-body-id", "")
    frame_session_id = frame_headers.get("x-bodyrig-session-id", "")
    if frame_body_id != expected_body_id:
        raise ProbeError("frame stream BodyRig body header differs from active body")
    if SESSION_ID_RE.fullmatch(frame_session_id) is None:
        raise ProbeError("frame stream BodyRig session header is missing or invalid")

    frames = _parse_sse(frame_raw, expected_count=frame_count)
    timestamps = [int(frame["timestamp_ms"]) for frame in frames]
    if any(b <= a for a, b in zip(timestamps, timestamps[1:])):
        raise ProbeError("frame timestamps are not strictly increasing")

    return {
        "schema": SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "production_activation": False,
        "candidate_git_sha": _git_head(),
        "base_url": base,
        "token_source": "environment",
        "active_body_id": expected_body_id,
        "active_package_sha256": expected_package_sha256,
        "frame_identity": {
            "body_id": frame_body_id,
            "session_id": frame_session_id,
        },
        "frame_count": len(frames),
        "first_timestamp_ms": timestamps[0],
        "last_timestamp_ms": timestamps[-1],
        "states_observed": sorted({str(frame["state"]) for frame in frames}),
        "canonical_frame_validation": True,
    }


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    if path.exists():
        raise ProbeError("receipt destination already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists():
        raise ProbeError("temporary receipt destination already exists")
    raw = (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode("utf-8")
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token-env", default="BODYRIG_RIG_TOKEN")
    parser.add_argument("--expected-body-id", required=True)
    parser.add_argument("--expected-package-sha256", required=True)
    parser.add_argument("--frame-count", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    token = os.environ.get(args.token_env, "")
    try:
        receipt = run_probe(
            base_url=args.base_url,
            token=token,
            expected_body_id=args.expected_body_id,
            expected_package_sha256=args.expected_package_sha256,
            frame_count=args.frame_count,
            timeout=args.timeout,
        )
        _write_receipt(args.output.expanduser().resolve(), receipt)
    except ProbeError as exc:
        print(f"BODYRIG LIVE STREAM PROBE: FAIL — {exc}", file=sys.stderr)
        return 1
    print(f"BODYRIG LIVE STREAM PROBE: PASS — {receipt['frame_count']} frames from {receipt['base_url']}")
    print(str(args.output.expanduser().resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
