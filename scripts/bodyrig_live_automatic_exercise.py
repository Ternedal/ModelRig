#!/usr/bin/env python3
"""Drive the real #846 live BodyRig path without human visual attestation.

The exercise runs on the physical rig after the Unity live machine proof has
launched the renderer. It uses only existing production endpoints:

* authenticated body state reports on the backend;
* the worker's loopback TTS endpoint to create deterministic spoken input;
* authenticated /api/v1/voice/converse/stream for the real ASR -> LLM -> TTS
  path that calls BodySession.note_speech;
* authenticated playback-start + interrupt + idle reports.

Unity independently observes only frames applied by BodyRigFrameSource and
writes live-quality-receipt.json. This driver then create-only seals the
machine run and quality receipt digests into live-automatic-exercise-receipt.json.
The bearer token is read only from an environment variable and is never
serialized.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

SCHEMA = "bodyrig.live_automatic_exercise/v0.1"
RUN_SCHEMA = "bodyrig.unity_live_run/v0.1"
QUALITY_SCHEMA = "bodyrig.unity_live_quality/v0.1"
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
BODY_ID_RE = re.compile(r"^bodyid-[0-9a-f]{24}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ExerciseError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _origin(raw: str, *, label: str, require_loopback: bool = False) -> str:
    value = raw.strip().rstrip("/")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ExerciseError(f"{label} must be an absolute http(s) origin")
    if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ExerciseError(f"{label} must be a clean origin without credentials/path/query/fragment")
    if require_loopback and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ExerciseError(f"{label} must remain loopback-only")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _request_json(
    *, method: str, url: str, payload: dict[str, Any] | None = None,
    token: str | None = None, timeout: float = 60.0,
) -> Any:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", errors="replace").replace("\r", " ").replace("\n", " ")
        raise ExerciseError(f"{method} {urllib.parse.urlsplit(url).path} failed HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ExerciseError(f"{method} {urllib.parse.urlsplit(url).path} failed: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExerciseError(f"{method} {urllib.parse.urlsplit(url).path} returned invalid JSON") from exc


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path, *, schema: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ExerciseError(f"required receipt is missing or irregular: {path.name}")
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ExerciseError(f"receipt is unexpectedly large: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExerciseError(f"receipt is invalid JSON: {path.name}") from exc
    if not isinstance(value, dict) or value.get("schema") != schema:
        raise ExerciseError(f"receipt schema mismatch: {path.name}")
    if value.get("production_activation") is not False:
        raise ExerciseError(f"receipt unexpectedly activated production: {path.name}")
    return value


def _write_create_only(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise ExerciseError(f"exercise receipt destination already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")
    fd, temporary_raw = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_raw)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            raise ExerciseError("exercise receipt destination appeared before commit")
        temporary.replace(path)
        temporary = Path()
    finally:
        if temporary and temporary.exists():
            temporary.unlink(missing_ok=True)


def _wait_for(path: Path, *, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while not path.is_file():
        if time.monotonic() >= deadline:
            raise ExerciseError(f"Unity did not produce {path.name} within {timeout_s:.0f}s")
        time.sleep(0.2)


def _voice_first_chunk(
    *, rig_origin: str, token: str, audio: bytes, model: str | None, timeout_s: float,
) -> str:
    payload: dict[str, Any] = {
        "audio_base64": base64.b64encode(audio).decode("ascii"),
        "language": "da",
    }
    if model:
        payload["model"] = model
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        rig_origin + "/api/v1/voice/converse/stream",
        data=body,
        method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/x-ndjson",
        },
    )
    try:
        response = _OPENER.open(request, timeout=timeout_s)
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", errors="replace").replace("\r", " ").replace("\n", " ")
        raise ExerciseError(f"voice converse failed HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ExerciseError(f"voice converse failed: {exc}") from exc
    try:
        for raw in response:
            if len(raw) > 32 * 1024 * 1024:
                raise ExerciseError("voice NDJSON event exceeded bounded size")
            try:
                event = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ExerciseError("voice converse emitted invalid NDJSON") from exc
            if not isinstance(event, dict):
                continue
            if event.get("type") == "error":
                raise ExerciseError(f"voice converse pipeline failed: {event.get('detail', 'unknown error')}")
            if event.get("type") == "chunk":
                utterance = event.get("utterance_id")
                audio_b64 = event.get("audio_base64")
                if not isinstance(utterance, str) or not utterance or len(utterance) > 80:
                    raise ExerciseError("voice chunk did not carry a valid utterance_id")
                if not isinstance(audio_b64, str) or not audio_b64:
                    raise ExerciseError("voice chunk did not carry playable audio")
                return utterance
        raise ExerciseError("voice converse ended without a spoken chunk")
    finally:
        response.close()


def run_exercise(
    *, evidence_dir: Path, rig_url: str, worker_url: str, token_env: str,
    model: str | None, quality_timeout_s: float,
) -> Path:
    evidence_dir = evidence_dir.expanduser().resolve()
    if not evidence_dir.is_dir() or evidence_dir.is_symlink():
        raise ExerciseError("evidence directory is missing or irregular")
    rig_origin = _origin(rig_url, label="rig URL")
    worker_origin = _origin(worker_url, label="worker URL", require_loopback=True)
    token = os.environ.get(token_env, "")
    if not token.strip():
        raise ExerciseError(f"{token_env} is not set; token is accepted only from process environment")

    run_path = evidence_dir / "live-run-receipt.json"
    quality_path = evidence_dir / "live-quality-receipt.json"
    exercise_path = evidence_dir / "live-automatic-exercise-receipt.json"
    run = _load(run_path, schema=RUN_SCHEMA)
    if run.get("rig_url") != rig_origin:
        raise ExerciseError("machine run rig URL differs from exercise rig URL")
    candidate = run.get("candidate_git_sha")
    profile = run.get("profile")
    if not isinstance(candidate, str) or not GIT_SHA_RE.fullmatch(candidate):
        raise ExerciseError("machine run candidate SHA is invalid")
    if not isinstance(profile, dict):
        raise ExerciseError("machine run profile is missing")
    body_id = profile.get("body_id")
    package_sha = profile.get("package_sha256")
    if not isinstance(body_id, str) or not BODY_ID_RE.fullmatch(body_id):
        raise ExerciseError("machine run body_id is invalid")
    if not isinstance(package_sha, str) or not SHA256_RE.fullmatch(package_sha):
        raise ExerciseError("machine run package SHA is invalid")

    # Explicit idle gives the collector a deterministic start state. Waiting
    # before the voice turn guarantees >80 live frames / >5s and spans at least
    # one complete maximum scheduler blink period (5.2s).
    _request_json(method="POST", url=rig_origin + "/api/v1/body/state/idle", token=token)
    time.sleep(0.35)
    _request_json(method="POST", url=rig_origin + "/api/v1/body/state/listening", token=token)
    time.sleep(5.5)

    with tempfile.TemporaryDirectory(prefix="bodyrig-live-exercise-") as temp:
        input_wav = Path(temp) / "input.wav"
        _request_json(
            method="POST",
            url=worker_origin + "/voice/tts/synthesize",
            payload={"text": "Hej Kaliv. Svar med en kort sætning.", "out_path": str(input_wav)},
            timeout=90.0,
        )
        if not input_wav.is_file() or input_wav.stat().st_size < 128:
            raise ExerciseError("loopback VoiceRig TTS did not produce the input WAV")
        utterance = _voice_first_chunk(
            rig_origin=rig_origin,
            token=token,
            audio=input_wav.read_bytes(),
            model=model,
            timeout_s=180.0,
        )

    # Re-anchor to real playback truth, give the live renderer multiple speaking
    # frames, then hard-interrupt twice: the second interrupt closes the race
    # where a cancelling voice stream could finish one late synthesis callback.
    quoted = urllib.parse.quote(utterance, safe="")
    _request_json(method="POST", url=rig_origin + f"/api/v1/body/speech/{quoted}/started", token=token)
    time.sleep(0.40)
    _request_json(method="POST", url=rig_origin + "/api/v1/body/interrupt", token=token)
    time.sleep(0.45)
    _request_json(method="POST", url=rig_origin + "/api/v1/body/interrupt", token=token)
    time.sleep(0.45)
    _request_json(method="POST", url=rig_origin + "/api/v1/body/state/idle", token=token)

    _wait_for(quality_path, timeout_s=quality_timeout_s)
    quality = _load(quality_path, schema=QUALITY_SCHEMA)
    if quality.get("candidate_git_sha") != candidate or quality.get("body_id") != body_id:
        raise ExerciseError("Unity quality receipt candidate/body binding mismatch")
    if quality.get("package_sha256") != package_sha or quality.get("source_url") != rig_origin:
        raise ExerciseError("Unity quality receipt package/source binding mismatch")

    receipt = {
        "schema": SCHEMA,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "production_activation": False,
        "candidate_git_sha": candidate,
        "body_id": body_id,
        "package_sha256": package_sha,
        "rig_url": rig_origin,
        "token_source": "environment",
        "states_driven": ["idle", "listening", "speaking", "interrupted", "idle"],
        "voice_chunk_observed": True,
        "playback_reanchored": True,
        "interrupt_sent": True,
        "idle_restored": True,
        "bindings": {
            "live_run_sha256": _sha(run_path),
            "live_quality_sha256": _sha(quality_path),
        },
    }
    _write_create_only(exercise_path, receipt)
    return exercise_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--rig-url", default="http://127.0.0.1:8080")
    parser.add_argument("--worker-url", default="http://127.0.0.1:8099")
    parser.add_argument("--token-env", default="BODYRIG_RIG_TOKEN")
    parser.add_argument("--model")
    parser.add_argument("--quality-timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()
    try:
        path = run_exercise(
            evidence_dir=args.evidence_dir,
            rig_url=args.rig_url,
            worker_url=args.worker_url,
            token_env=args.token_env,
            model=args.model,
            quality_timeout_s=args.quality_timeout_seconds,
        )
    except ExerciseError as exc:
        print(f"BODYRIG LIVE AUTOMATIC EXERCISE: FAIL — {exc}")
        return 1
    print("BODYRIG LIVE AUTOMATIC EXERCISE: PASS")
    print(f"  receipt: {path}")
    print("production_activation=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
