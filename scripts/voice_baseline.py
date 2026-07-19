#!/usr/bin/env python3
"""Measure the existing Kaliv voice pipeline without changing production behavior.

The harness calls the worker's loopback-only ``/voice/converse/stream`` endpoint
with a fixed, versioned Danish WAV manifest. It validates the NDJSON protocol,
computes ASR WER/CER, measures transcript/first-audio/done latency, performs
connection-cancellation cleanup probes, and writes an atomic machine-readable
report. Raw input audio and full model replies are never copied into the report.

The physical rig is required for real ASR/TTS/LLM measurements. CI exercises the
manifest, scoring, protocol parser, loopback policy and report lifecycle against
a controlled local fixture server.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import math
import os
import platform
import re
import shutil
import statistics
import subprocess
import tempfile
import time
import unicodedata
import urllib.parse
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPORT_SCHEMA = "kaliv-voice-baseline/v1"
MANIFEST_SCHEMA = "kaliv-voice-baseline-manifest/v1"
MANUAL_SCHEMA = "kaliv-voice-manual-observations/v1"
DEFAULT_MANIFEST = Path("eval/voice_baseline_manifest.v1.json")
DEFAULT_REPORT = Path("validation/voice-baseline-latest.json")
DEFAULT_WORKER_URL = "http://127.0.0.1:8099"
MAX_EVENT_LINE_BYTES = 32 * 1024 * 1024
MAX_AUDIO_BYTES = 25 * 1024 * 1024
EXPECTED_SAMPLE_RATE = 16_000
EXPECTED_CHANNELS = 1
EXPECTED_SAMPLE_WIDTH = 2
VOICE_TEMP_PREFIXES = ("alva_voice_", "alva_voice_stream_", "alva_voice_up_")


class VoiceBaselineError(RuntimeError):
    """The harness cannot produce trustworthy voice evidence."""


class ProtocolError(VoiceBaselineError):
    """The streaming endpoint violated its documented NDJSON contract."""


def _safe_error(exc: Exception) -> dict[str, str]:
    return {
        "type": type(exc).__name__,
        "message": str(exc).replace("\r", " ").replace("\n", " ")[:500],
    }


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(payload)
        temp = Path(handle.name)
    temp.replace(path)


def _git_sha(root: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = proc.stdout.strip()
    if proc.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", value):
        return value
    return None


def _nvidia_snapshot() -> list[dict[str, Any]]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return []
    try:
        proc = subprocess.run(
            [
                executable,
                "--query-gpu=index,name,driver_version,memory.total,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    result: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        parts = [item.strip() for item in line.split(",")]
        if len(parts) != 5:
            continue
        try:
            result.append(
                {
                    "index": int(parts[0]),
                    "name": parts[1],
                    "driver_version": parts[2],
                    "memory_total_bytes": int(parts[3]) * 1024 * 1024,
                    "memory_used_bytes": int(parts[4]) * 1024 * 1024,
                }
            )
        except ValueError:
            continue
    return result


_WORD_RE = re.compile(r"[^\wæøå]+", re.IGNORECASE | re.UNICODE)


def normalize_danish(text: str) -> str:
    """Normalize display differences while preserving ASR word choices."""

    value = unicodedata.normalize("NFKC", text).casefold().replace("&", " og ")
    value = value.replace("_", " ")
    value = _WORD_RE.sub(" ", value)
    return " ".join(value.split())


def _edit_counts(reference: list[str], hypothesis: list[str]) -> dict[str, int]:
    """Levenshtein distance with deterministic S/D/I backtracking."""

    rows = len(reference) + 1
    cols = len(hypothesis) + 1
    distance = [[0] * cols for _ in range(rows)]
    operation = [[""] * cols for _ in range(rows)]
    for i in range(1, rows):
        distance[i][0] = i
        operation[i][0] = "D"
    for j in range(1, cols):
        distance[0][j] = j
        operation[0][j] = "I"

    for i in range(1, rows):
        for j in range(1, cols):
            if reference[i - 1] == hypothesis[j - 1]:
                distance[i][j] = distance[i - 1][j - 1]
                operation[i][j] = "C"
                continue
            candidates = (
                (distance[i - 1][j - 1] + 1, "S", 0),
                (distance[i - 1][j] + 1, "D", 1),
                (distance[i][j - 1] + 1, "I", 2),
            )
            best = min(candidates, key=lambda item: (item[0], item[2]))
            distance[i][j] = best[0]
            operation[i][j] = best[1]

    counts = {"substitutions": 0, "deletions": 0, "insertions": 0}
    i = len(reference)
    j = len(hypothesis)
    while i or j:
        current = operation[i][j]
        if current == "C":
            i -= 1
            j -= 1
        elif current == "S":
            counts["substitutions"] += 1
            i -= 1
            j -= 1
        elif current == "D":
            counts["deletions"] += 1
            i -= 1
        elif current == "I":
            counts["insertions"] += 1
            j -= 1
        else:
            raise VoiceBaselineError("edit-distance backtracking failed")
    counts["distance"] = distance[-1][-1]
    return counts


def score_transcript(reference: str, hypothesis: str) -> dict[str, Any]:
    ref_norm = normalize_danish(reference)
    hyp_norm = normalize_danish(hypothesis)
    ref_words = ref_norm.split()
    hyp_words = hyp_norm.split()
    word_counts = _edit_counts(ref_words, hyp_words)
    ref_chars = list(ref_norm.replace(" ", ""))
    hyp_chars = list(hyp_norm.replace(" ", ""))
    char_counts = _edit_counts(ref_chars, hyp_chars)
    return {
        "reference_normalized": ref_norm,
        "hypothesis_normalized": hyp_norm,
        "reference_words": len(ref_words),
        "hypothesis_words": len(hyp_words),
        **word_counts,
        "wer": round(word_counts["distance"] / max(1, len(ref_words)), 6),
        "cer": round(char_counts["distance"] / max(1, len(ref_chars)), 6),
        "char_distance": char_counts["distance"],
        "reference_characters": len(ref_chars),
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[rank], 3)


def summarize_numbers(values: Iterable[float | int | None]) -> dict[str, float | None]:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return {"min": None, "mean": None, "p50": None, "p95": None, "max": None}
    return {
        "min": round(min(clean), 3),
        "mean": round(statistics.fmean(clean), 3),
        "p50": _percentile(clean, 0.50),
        "p95": _percentile(clean, 0.95),
        "max": round(max(clean), 3),
    }


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise VoiceBaselineError(f"manifest cannot be read: {path}") from exc
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VoiceBaselineError("manifest is not valid UTF-8 JSON") from exc
    if not isinstance(manifest, dict):
        raise VoiceBaselineError("manifest must be a JSON object")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise VoiceBaselineError("manifest schema is not supported")
    if manifest.get("language") != "da":
        raise VoiceBaselineError("manifest language must be da")
    turns = manifest.get("turns")
    if not isinstance(turns, list) or len(turns) != 20:
        raise VoiceBaselineError("manifest must contain exactly 20 turns")

    ids: set[str] = set()
    for index, turn in enumerate(turns):
        if not isinstance(turn, dict):
            raise VoiceBaselineError(f"turns[{index}] must be an object")
        turn_id = turn.get("id")
        reference = turn.get("reference")
        audio_path = turn.get("audio_path")
        category = turn.get("category")
        if not isinstance(turn_id, str) or not re.fullmatch(r"turn-\d{2}", turn_id):
            raise VoiceBaselineError(f"turns[{index}].id is invalid")
        if turn_id in ids:
            raise VoiceBaselineError(f"duplicate turn id: {turn_id}")
        ids.add(turn_id)
        if not isinstance(reference, str) or not normalize_danish(reference):
            raise VoiceBaselineError(f"{turn_id} has an empty reference")
        if not isinstance(category, str) or not category.strip():
            raise VoiceBaselineError(f"{turn_id} has no category")
        if not isinstance(audio_path, str) or not audio_path.strip():
            raise VoiceBaselineError(f"{turn_id} has no audio_path")
        candidate = Path(audio_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise VoiceBaselineError(f"{turn_id} audio_path must be repository-relative")

    canonical = dict(manifest)
    canonical.pop("sha256", None)
    manifest_hash = _sha256_bytes(_canonical_json(canonical))
    declared_hash = manifest.get("sha256")
    if declared_hash is not None and declared_hash != manifest_hash:
        raise VoiceBaselineError("manifest sha256 does not match its contents")
    return {**canonical, "sha256": manifest_hash, "_path": str(path)}


def resolve_audio_path(root: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise VoiceBaselineError("audio path escaped the repository")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise VoiceBaselineError("audio path escaped the repository") from exc
    return resolved


def inspect_wav(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise VoiceBaselineError(f"audio fixture cannot be read: {path}") from exc
    if len(raw) > MAX_AUDIO_BYTES:
        raise VoiceBaselineError(f"audio fixture exceeds {MAX_AUDIO_BYTES} bytes: {path}")
    try:
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frames = wav.getnframes()
            compression = wav.getcomptype()
    except (wave.Error, EOFError) as exc:
        raise VoiceBaselineError(f"audio fixture is not a readable WAV: {path}") from exc
    if channels != EXPECTED_CHANNELS:
        raise VoiceBaselineError(f"{path} must be mono")
    if sample_width != EXPECTED_SAMPLE_WIDTH:
        raise VoiceBaselineError(f"{path} must be 16-bit PCM")
    if sample_rate != EXPECTED_SAMPLE_RATE:
        raise VoiceBaselineError(f"{path} must be 16 kHz")
    if compression != "NONE":
        raise VoiceBaselineError(f"{path} must be uncompressed PCM")
    duration_s = frames / max(1, sample_rate)
    if duration_s < 0.25 or duration_s > 30:
        raise VoiceBaselineError(f"{path} duration must be between 0.25 and 30 seconds")
    return {
        "sha256": _sha256_bytes(raw),
        "bytes": len(raw),
        "channels": channels,
        "sample_width_bytes": sample_width,
        "sample_rate_hz": sample_rate,
        "frames": frames,
        "duration_s": round(duration_s, 3),
        "_raw": raw,
    }


def parse_worker_url(raw: str) -> tuple[str, int, str]:
    try:
        parsed = urllib.parse.urlsplit(raw.strip())
    except ValueError as exc:
        raise VoiceBaselineError("worker URL is invalid") from exc
    if parsed.scheme != "http":
        raise VoiceBaselineError("worker URL must use http over loopback")
    if parsed.username is not None or parsed.password is not None:
        raise VoiceBaselineError("worker URL must not contain credentials")
    host = (parsed.hostname or "").lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise VoiceBaselineError("worker URL must be loopback-only")
    if parsed.query or parsed.fragment:
        raise VoiceBaselineError("worker URL must not contain query or fragment")
    base_path = parsed.path.rstrip("/")
    if base_path not in {"", "/"}:
        raise VoiceBaselineError("worker URL must not contain an API path")
    port = parsed.port or 80
    display_host = f"[{host}]" if ":" in host else host
    return host, port, f"http://{display_host}:{port}"


def _connection(host: str, port: int, timeout_s: float) -> http.client.HTTPConnection:
    return http.client.HTTPConnection(host, port, timeout=timeout_s)


def get_json(worker_url: str, path: str, timeout_s: float) -> dict[str, Any]:
    host, port, _ = parse_worker_url(worker_url)
    connection = _connection(host, port, timeout_s)
    response: http.client.HTTPResponse | None = None
    try:
        connection.request("GET", path, headers={"Accept": "application/json"})
        response = connection.getresponse()
        raw = response.read(MAX_EVENT_LINE_BYTES + 1)
        status = response.status
    finally:
        if response is not None:
            response.close()
        connection.close()
    if len(raw) > MAX_EVENT_LINE_BYTES:
        raise VoiceBaselineError(f"{path} response is too large")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VoiceBaselineError(f"{path} did not return JSON") from exc
    if status != 200 or not isinstance(payload, dict):
        raise VoiceBaselineError(f"{path} returned HTTP {status}")
    return payload


def _record_event(state: dict[str, Any], event: dict[str, Any], elapsed_ms: float) -> None:
    event_type = event.get("type")
    if not isinstance(event_type, str):
        raise ProtocolError("voice event has no string type")
    if state["terminal"]:
        raise ProtocolError("voice stream emitted an event after terminal state")

    if event_type == "transcript":
        if state["transcript"] is not None or state["chunks"]:
            raise ProtocolError("transcript must appear exactly once before chunks")
        text = event.get("text")
        if not isinstance(text, str):
            raise ProtocolError("transcript text is invalid")
        state["transcript"] = text
        state["transcript_ms"] = round(elapsed_ms, 3)
        return

    if event_type == "chunk":
        if state["transcript"] is None:
            raise ProtocolError("audio chunk arrived before transcript")
        index = event.get("index")
        if index != len(state["chunks"]):
            raise ProtocolError("audio chunks are not contiguous and ordered")
        audio_b64 = event.get("audio_base64")
        if not isinstance(audio_b64, str) or not audio_b64:
            raise ProtocolError("audio chunk is missing audio_base64")
        try:
            audio_bytes = base64.b64decode(audio_b64, validate=True)
        except Exception as exc:
            raise ProtocolError("audio chunk contains invalid base64") from exc
        if not audio_bytes:
            raise ProtocolError("audio chunk is empty")
        if state["first_chunk_ms"] is None:
            state["first_chunk_ms"] = round(elapsed_ms, 3)
        state["reply_audio_bytes"] += len(audio_bytes)
        state["chunks"].append(
            {
                "index": index,
                "text_characters": len(str(event.get("text") or "")),
                "audio_bytes": len(audio_bytes),
                "synth_s": event.get("synth_s"),
                "server_ttfa_s": event.get("ttfa_s"),
                "received_ms": round(elapsed_ms, 3),
            }
        )
        return

    if event_type == "done":
        if state["transcript"] is None:
            raise ProtocolError("done arrived before transcript")
        reply = event.get("reply")
        if not isinstance(reply, str):
            raise ProtocolError("done reply is invalid")
        state["terminal"] = "done"
        state["done_ms"] = round(elapsed_ms, 3)
        state["done"] = {
            "reply_sha256": _sha256_bytes(reply.encode("utf-8")),
            "reply_characters": len(reply),
            "model": event.get("model"),
            "via_cloud": bool(event.get("via_cloud", False)),
            "language": event.get("language"),
            "pipeline_time_to_first_audio_s": event.get("time_to_first_audio_s"),
            "pipeline_total_s": event.get("total_s"),
        }
        return

    if event_type == "error":
        state["terminal"] = "error"
        state["done_ms"] = round(elapsed_ms, 3)
        state["error_event"] = {
            "status": event.get("status"),
            "detail": str(event.get("detail") or "")[:500],
        }
        return

    raise ProtocolError(f"unknown voice event type: {event_type}")


def stream_turn(
    worker_url: str,
    *,
    audio_bytes: bytes,
    language: str,
    model: str | None,
    timeout_s: float,
    abort_after: str | None = None,
) -> dict[str, Any]:
    if abort_after not in {None, "transcript", "first_chunk"}:
        raise VoiceBaselineError("abort_after is invalid")
    host, port, _ = parse_worker_url(worker_url)
    payload: dict[str, Any] = {
        "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
        "language": language,
    }
    if model:
        payload["model"] = model
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    connection = _connection(host, port, timeout_s)
    started = time.perf_counter()
    state: dict[str, Any] = {
        "response_headers_ms": None,
        "transcript": None,
        "transcript_ms": None,
        "first_chunk_ms": None,
        "done_ms": None,
        "chunks": [],
        "reply_audio_bytes": 0,
        "done": None,
        "error_event": None,
        "terminal": None,
        "aborted": False,
        "abort_after": abort_after,
    }
    response: http.client.HTTPResponse | None = None
    try:
        connection.request(
            "POST",
            "/voice/converse/stream",
            body=body,
            headers={
                "Accept": "application/x-ndjson",
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
        )
        response = connection.getresponse()
        state["response_headers_ms"] = round((time.perf_counter() - started) * 1000, 3)
        if response.status != 200:
            raw = response.read(4096)
            raise VoiceBaselineError(
                f"voice stream returned HTTP {response.status}: "
                f"{raw.decode('utf-8', errors='replace')[:300]}"
            )
        content_type = response.getheader("Content-Type") or ""
        if "application/x-ndjson" not in content_type:
            raise ProtocolError("voice stream content type is not application/x-ndjson")

        while True:
            raw_line = response.readline(MAX_EVENT_LINE_BYTES + 1)
            if not raw_line:
                break
            if len(raw_line) > MAX_EVENT_LINE_BYTES:
                raise ProtocolError("voice event line exceeds the size limit")
            if not raw_line.strip():
                continue
            try:
                event = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProtocolError("voice event is not valid UTF-8 JSON") from exc
            if not isinstance(event, dict):
                raise ProtocolError("voice event must be a JSON object")
            _record_event(state, event, (time.perf_counter() - started) * 1000)
            if abort_after == "transcript" and state["transcript"] is not None:
                state["aborted"] = True
                break
            if abort_after == "first_chunk" and state["first_chunk_ms"] is not None:
                state["aborted"] = True
                break
            if state["terminal"]:
                extra = response.readline(MAX_EVENT_LINE_BYTES + 1)
                if extra and extra.strip():
                    raise ProtocolError("voice stream continued after terminal event")
                break
    finally:
        if response is not None:
            response.close()
        connection.close()

    if state["aborted"]:
        return state
    if state["terminal"] is None:
        raise ProtocolError("voice stream ended without done or error")
    if state["terminal"] == "error":
        raise VoiceBaselineError(
            f"voice stream error {state['error_event']['status']}: "
            f"{state['error_event']['detail']}"
        )
    if state["first_chunk_ms"] is None:
        raise ProtocolError("successful voice stream produced no audio chunk")
    return state


def _voice_temp_entries() -> set[str]:
    root = Path(tempfile.gettempdir())
    try:
        entries = list(root.iterdir())
    except OSError:
        return set()
    return {
        str(entry.resolve())
        for entry in entries
        if any(entry.name.startswith(prefix) for prefix in VOICE_TEMP_PREFIXES)
    }


def wait_for_cleanup(
    before: set[str],
    *,
    timeout_s: float,
    poll_s: float = 0.25,
) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + timeout_s
    current = _voice_temp_entries()
    while time.monotonic() < deadline:
        leaked = sorted(current - before)
        if not leaked:
            return {
                "clean": True,
                "wait_ms": round((time.monotonic() - started) * 1000, 3),
                "remaining": [],
            }
        time.sleep(poll_s)
        current = _voice_temp_entries()
    return {
        "clean": False,
        "wait_ms": round((time.monotonic() - started) * 1000, 3),
        "remaining": sorted(current - before),
    }


def _turn_result(
    turn: dict[str, Any],
    *,
    repetition: int,
    phase: str,
    audio: dict[str, Any],
    stream: dict[str, Any],
) -> dict[str, Any]:
    transcript = str(stream["transcript"])
    return {
        "id": turn["id"],
        "category": turn["category"],
        "repetition": repetition,
        "phase": phase,
        "audio": {key: value for key, value in audio.items() if not key.startswith("_")},
        "transcript_sha256": _sha256_bytes(transcript.encode("utf-8")),
        "transcript_characters": len(transcript),
        "score": score_transcript(turn["reference"], transcript),
        "latency_ms": {
            "response_headers": stream["response_headers_ms"],
            "transcript": stream["transcript_ms"],
            "first_audio": stream["first_chunk_ms"],
            "done": stream["done_ms"],
        },
        "pipeline": stream["done"],
        "chunks": stream["chunks"],
        "reply_audio_bytes": stream["reply_audio_bytes"],
        "error": None,
    }


def _aggregate_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [run for run in runs if run.get("error") is None]
    reference_words = sum(run["score"]["reference_words"] for run in completed)
    word_distance = sum(run["score"]["distance"] for run in completed)
    reference_chars = sum(run["score"]["reference_characters"] for run in completed)
    char_distance = sum(run["score"]["char_distance"] for run in completed)
    return {
        "runs": len(runs),
        "completed": len(completed),
        "errors": len(runs) - len(completed),
        "wer_micro": round(word_distance / max(1, reference_words), 6),
        "wer_macro": (
            round(statistics.fmean(run["score"]["wer"] for run in completed), 6)
            if completed
            else None
        ),
        "cer_micro": round(char_distance / max(1, reference_chars), 6),
        "latency_ms": {
            metric: summarize_numbers(run["latency_ms"].get(metric) for run in completed)
            for metric in ("response_headers", "transcript", "first_audio", "done")
        },
        "pipeline_time_to_first_audio_s": summarize_numbers(
            (run["pipeline"] or {}).get("pipeline_time_to_first_audio_s")
            for run in completed
        ),
        "pipeline_total_s": summarize_numbers(
            (run["pipeline"] or {}).get("pipeline_total_s") for run in completed
        ),
    }


def load_manual_observations(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VoiceBaselineError("manual observation file is invalid") from exc
    if not isinstance(value, dict) or value.get("schema") != MANUAL_SCHEMA:
        raise VoiceBaselineError("manual observation schema is not supported")
    trials = value.get("trials")
    if not isinstance(trials, list) or len(trials) < 5:
        raise VoiceBaselineError("manual observations require at least five trials")
    required = {
        "id",
        "trigger",
        "recognized",
        "playback_stopped",
        "stale_audio_resumed",
        "ui_terminal_state",
        "stop_latency_ms",
    }
    for index, trial in enumerate(trials):
        if not isinstance(trial, dict) or not required.issubset(trial):
            raise VoiceBaselineError(f"manual trial {index} is incomplete")
    return value


def _manual_trial_passes(trial: dict[str, Any]) -> bool:
    latency = trial.get("stop_latency_ms")
    latency_valid = (
        isinstance(latency, (int, float))
        and not isinstance(latency, bool)
        and 0 <= float(latency) <= 30_000
    )
    return (
        trial.get("recognized") is True
        and trial.get("playback_stopped") is True
        and trial.get("stale_audio_resumed") is False
        and trial.get("ui_terminal_state") in {"cancelled", "idle"}
        and latency_valid
    )


def _manual_summary(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {
            "provided": False,
            "trials": 0,
            "passed": None,
            "stop_latency_ms": summarize_numbers([]),
        }
    trials = value["trials"]
    return {
        "provided": True,
        "trials": len(trials),
        "passed": all(_manual_trial_passes(trial) for trial in trials),
        "stop_latency_ms": summarize_numbers(
            trial.get("stop_latency_ms")
            for trial in trials
            if isinstance(trial.get("stop_latency_ms"), (int, float))
            and not isinstance(trial.get("stop_latency_ms"), bool)
        ),
    }


def run_baseline(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    root = Path(__file__).resolve().parents[1]
    manifest_path = args.manifest.resolve()
    manifest = load_manifest(manifest_path)
    _, _, worker_url = parse_worker_url(args.worker_url)
    manual = load_manual_observations(args.manual_observations)

    turn_assets: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for turn in manifest["turns"]:
        path = resolve_audio_path(root, turn["audio_path"])
        if not path.exists():
            missing.append(str(path))
            continue
        turn_assets[turn["id"]] = inspect_wav(path)

    manifest_display_path = (
        str(manifest_path.relative_to(root))
        if manifest_path.is_relative_to(root)
        else str(manifest_path)
    )
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest": {
            "schema": MANIFEST_SCHEMA,
            "dataset_version": manifest.get("dataset_version"),
            "sha256": manifest["sha256"],
            "path": manifest_display_path,
            "turns": len(manifest["turns"]),
        },
        "build": {
            "version": (root / "VERSION").read_text(encoding="utf-8").strip(),
            "git_sha": _git_sha(root),
        },
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "nvidia": _nvidia_snapshot(),
        },
        "worker": {
            "url": worker_url,
            "asr_status": None,
            "tts_status": None,
            "health": None,
        },
        "configuration": {
            "model": args.model,
            "language": args.language,
            "repetitions": args.repetitions,
            "cold_start_confirmed": args.cold_start_confirmed,
            "cold_turn": args.cold_turn,
            "cancellation_probes": args.cancellation_probes,
            "timeout_s": args.timeout,
            "cleanup_timeout_s": args.cleanup_timeout,
            "max_wer": args.max_wer if args.max_wer >= 0 else None,
            "max_warm_first_audio_ms": (
                args.max_warm_first_audio_ms
                if args.max_warm_first_audio_ms > 0
                else None
            ),
        },
        "missing_audio": missing,
        "cold_probe": None,
        "runs": [],
        "cancellation_probes": [],
        "manual_observations": manual,
        "summary": None,
        "gate": None,
        "error": None,
    }

    if args.validate_only:
        report["summary"] = {
            "manifest_valid": True,
            "audio_present": len(turn_assets),
            "audio_missing": len(missing),
        }
        report["gate"] = {"passed": not missing, "mode": "validate_only"}
        return report, 0 if not missing else 1

    if missing:
        report["error"] = {
            "type": "MissingAudioFixtures",
            "message": f"{len(missing)} manifest audio fixtures are missing",
        }
        report["summary"] = {"runs": 0, "completed": 0, "errors": len(missing)}
        report["gate"] = {"passed": False}
        return report, 2

    try:
        report["worker"]["health"] = get_json(worker_url, "/healthz", args.timeout)
        report["worker"]["asr_status"] = get_json(
            worker_url, "/voice/asr/status", args.timeout
        )
        report["worker"]["tts_status"] = get_json(
            worker_url, "/voice/tts/status", args.timeout
        )
    except Exception as exc:
        report["error"] = _safe_error(exc)
        report["summary"] = {"runs": 0, "completed": 0, "errors": 1}
        report["gate"] = {"passed": False}
        return report, 2

    turns_by_id = {turn["id"]: turn for turn in manifest["turns"]}
    if args.cold_turn not in turns_by_id:
        raise VoiceBaselineError(f"cold turn does not exist: {args.cold_turn}")

    if args.cold_start_confirmed:
        cold_turn = turns_by_id[args.cold_turn]
        audio = turn_assets[args.cold_turn]
        try:
            stream = stream_turn(
                worker_url,
                audio_bytes=audio["_raw"],
                language=args.language,
                model=args.model,
                timeout_s=args.timeout,
            )
            report["cold_probe"] = _turn_result(
                cold_turn,
                repetition=1,
                phase="cold_probe",
                audio=audio,
                stream=stream,
            )
        except Exception as exc:
            report["cold_probe"] = {
                "id": cold_turn["id"],
                "phase": "cold_probe",
                "error": _safe_error(exc),
            }

    runs: list[dict[str, Any]] = []
    for repetition in range(1, args.repetitions + 1):
        for turn in manifest["turns"]:
            audio = turn_assets[turn["id"]]
            try:
                stream = stream_turn(
                    worker_url,
                    audio_bytes=audio["_raw"],
                    language=args.language,
                    model=args.model,
                    timeout_s=args.timeout,
                )
                runs.append(
                    _turn_result(
                        turn,
                        repetition=repetition,
                        phase="warm",
                        audio=audio,
                        stream=stream,
                    )
                )
            except Exception as exc:
                runs.append(
                    {
                        "id": turn["id"],
                        "category": turn["category"],
                        "repetition": repetition,
                        "phase": "warm",
                        "audio": {
                            key: value
                            for key, value in audio.items()
                            if not key.startswith("_")
                        },
                        "error": _safe_error(exc),
                    }
                )
    report["runs"] = runs

    cancellation_results: list[dict[str, Any]] = []
    probe_turn = turns_by_id[args.cold_turn]
    probe_audio = turn_assets[probe_turn["id"]]
    for index in range(args.cancellation_probes):
        trigger = "transcript" if index % 2 == 0 else "first_chunk"
        before = _voice_temp_entries()
        started = time.perf_counter()
        item: dict[str, Any] = {
            "index": index + 1,
            "trigger": trigger,
            "aborted": False,
            "worker_healthy": False,
            "cleanup": None,
            "latency_ms": None,
            "error": None,
        }
        try:
            state = stream_turn(
                worker_url,
                audio_bytes=probe_audio["_raw"],
                language=args.language,
                model=args.model,
                timeout_s=args.timeout,
                abort_after=trigger,
            )
            item["aborted"] = bool(state["aborted"])
            item["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
            item["cleanup"] = wait_for_cleanup(before, timeout_s=args.cleanup_timeout)
            get_json(worker_url, "/healthz", args.timeout)
            item["worker_healthy"] = True
        except Exception as exc:
            item["error"] = _safe_error(exc)
        cancellation_results.append(item)
    report["cancellation_probes"] = cancellation_results

    summary = _aggregate_runs(runs)
    manual_summary = _manual_summary(manual)
    summary["cold_probe_completed"] = bool(
        report["cold_probe"] and report["cold_probe"].get("error") is None
    )
    summary["cancellation"] = {
        "probes": len(cancellation_results),
        "passed": sum(
            bool(item.get("aborted"))
            and bool((item.get("cleanup") or {}).get("clean"))
            and bool(item.get("worker_healthy"))
            and item.get("error") is None
            for item in cancellation_results
        ),
        "errors": sum(item.get("error") is not None for item in cancellation_results),
    }
    summary["manual"] = manual_summary
    report["summary"] = summary

    gate_ok = (
        summary["errors"] == 0
        and summary["completed"] == len(manifest["turns"]) * args.repetitions
        and summary["cancellation"]["passed"] == args.cancellation_probes
    )
    if args.cold_start_confirmed:
        gate_ok = gate_ok and summary["cold_probe_completed"]
    if args.max_wer >= 0:
        gate_ok = gate_ok and summary["wer_micro"] <= args.max_wer
    if args.max_warm_first_audio_ms > 0:
        p95 = summary["latency_ms"]["first_audio"]["p95"]
        gate_ok = gate_ok and p95 is not None and p95 <= args.max_warm_first_audio_ms
    if args.require_manual:
        gate_ok = gate_ok and manual_summary["provided"] and manual_summary["passed"]

    report["gate"] = {
        "passed": bool(gate_ok),
        "max_wer": args.max_wer if args.max_wer >= 0 else None,
        "max_warm_first_audio_ms": (
            args.max_warm_first_audio_ms
            if args.max_warm_first_audio_ms > 0
            else None
        ),
        "manual_required": args.require_manual,
    }
    return report, 0 if gate_ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--worker-url", default=DEFAULT_WORKER_URL)
    parser.add_argument("--language", default="da")
    parser.add_argument("--model")
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--cold-turn", default="turn-01")
    parser.add_argument("--cold-start-confirmed", action="store_true")
    parser.add_argument("--cancellation-probes", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--cleanup-timeout", type=float, default=15.0)
    parser.add_argument("--manual-observations", type=Path)
    parser.add_argument("--require-manual", action="store_true")
    parser.add_argument(
        "--max-wer",
        type=float,
        default=-1.0,
        help="optional micro-WER gate; negative means report only",
    )
    parser.add_argument(
        "--max-warm-first-audio-ms",
        type=float,
        default=0.0,
        help="optional warm first-audio p95 gate; zero means report only",
    )
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)

    if args.language != "da":
        parser.error("--language must be da for this versioned baseline")
    if args.repetitions < 1 or args.repetitions > 10:
        parser.error("--repetitions must be between 1 and 10")
    if args.cancellation_probes < 0 or args.cancellation_probes > 20:
        parser.error("--cancellation-probes must be between 0 and 20")
    if args.timeout <= 0 or args.timeout > 900:
        parser.error("--timeout must be between 0 and 900 seconds")
    if args.cleanup_timeout <= 0 or args.cleanup_timeout > 120:
        parser.error("--cleanup-timeout must be between 0 and 120 seconds")
    if args.max_wer > 1:
        parser.error("--max-wer cannot exceed 1")
    if args.max_warm_first_audio_ms < 0:
        parser.error("--max-warm-first-audio-ms cannot be negative")
    if args.require_manual and args.manual_observations is None:
        parser.error("--require-manual needs --manual-observations")

    try:
        report, exit_code = run_baseline(args)
    except Exception as exc:
        report = {
            "schema": REPORT_SCHEMA,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "error": _safe_error(exc),
            "summary": {"runs": 0, "completed": 0, "errors": 1},
            "gate": {"passed": False},
        }
        exit_code = 2
    _write_json_atomic(args.report, report)
    print(f"report: {args.report}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
