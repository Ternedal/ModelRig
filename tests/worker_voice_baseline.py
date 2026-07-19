#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
import sys
import tempfile
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "worker"
sys.path.insert(0, str(WORKER))

spec = importlib.util.spec_from_file_location(
    "voice_baseline",
    ROOT / "scripts" / "voice_baseline.py",
)
vb = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = vb
spec.loader.exec_module(vb)

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


manifest_path = ROOT / "eval" / "voice_baseline_manifest.v1.json"
manifest_a = vb.load_manifest(manifest_path)
manifest_b = vb.load_manifest(manifest_path)
check(manifest_a["schema"] == vb.MANIFEST_SCHEMA, "manifest schema is versioned")
check(len(manifest_a["turns"]) == 20, "manifest contains exactly twenty fixed turns")
check(manifest_a["sha256"] == manifest_b["sha256"], "manifest hash is deterministic")
check(
    len({turn["id"] for turn in manifest_a["turns"]}) == 20,
    "all voice turn ids are unique",
)
check(
    all(Path(turn["audio_path"]).parts[:2] == ("validation", "voice-fixtures") for turn in manifest_a["turns"]),
    "audio fixtures live in the local validation namespace",
)

check(
    vb.normalize_danish("  ØL, Æble & ÅBEN! ") == "øl æble og åben",
    "Danish normalization preserves national characters",
)
exact = vb.score_transcript("Hvad er klokken?", "hvad er klokken")
check(exact["wer"] == 0.0 and exact["cer"] == 0.0, "punctuation and case do not count as ASR errors")
substitution = vb.score_transcript("fyrre og fireogfyrre", "fyrre og femogfyrre")
check(substitution["substitutions"] == 1, "WER records substitutions")
insertion = vb.score_transcript("hej verden", "hej lille verden")
check(insertion["insertions"] == 1, "WER records insertions")
deletion = vb.score_transcript("hej lille verden", "hej verden")
check(deletion["deletions"] == 1, "WER records deletions")
check(vb._percentile([1, 2, 3, 4], 0.50) == 2, "latency p50 uses nearest rank")
check(vb._percentile([1, 2, 3, 4], 0.95) == 4, "latency p95 uses nearest rank")

for good in (
    "http://127.0.0.1:8099",
    "http://localhost:8099/",
    "http://[::1]:8099",
):
    try:
        vb.parse_worker_url(good)
    except vb.VoiceBaselineError:
        accepted = False
    else:
        accepted = True
    check(accepted, f"loopback worker URL is accepted: {good}")

check(
    vb.parse_worker_url("http://[::1]:8099")[2] == "http://[::1]:8099",
    "IPv6 loopback remains a valid bracketed URL",
)

for bad in (
    "https://127.0.0.1:8099",
    "http://192.168.1.10:8099",
    "http://user:pass@127.0.0.1:8099",
    "http://127.0.0.1:8099/api",
    "http://127.0.0.1:8099?token=x",
):
    try:
        vb.parse_worker_url(bad)
    except vb.VoiceBaselineError:
        rejected = True
    else:
        rejected = False
    check(rejected, f"non-canonical worker URL is rejected: {bad}")

with tempfile.TemporaryDirectory(prefix="voice-baseline-wav-") as temp_dir:
    wav_path = Path(temp_dir) / "fixture.wav"
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(b"\x00\x00" * 8_000)
    inspected = vb.inspect_wav(wav_path)
    check(inspected["sample_rate_hz"] == 16_000, "WAV validator requires 16 kHz")
    check(inspected["channels"] == 1, "WAV validator requires mono")
    check(inspected["duration_s"] == 0.5, "WAV duration is measured")
    check(len(inspected["sha256"]) == 64, "WAV content is hash-bound")

    wrong_rate = Path(temp_dir) / "wrong.wav"
    with wave.open(str(wrong_rate), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8_000)
        wav.writeframes(b"\x00\x00" * 4_000)
    try:
        vb.inspect_wav(wrong_rate)
    except vb.VoiceBaselineError:
        invalid_rate = True
    else:
        invalid_rate = False
    check(invalid_rate, "non-16-kHz WAV fails closed")


class FixtureHandler(BaseHTTPRequestHandler):
    mode = "valid"
    requests: list[dict] = []

    def log_message(self, _format: str, *_args) -> None:
        return

    def _json(self, value: dict) -> None:
        raw = json.dumps(value).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self._json({"status": "ok", "version": "test"})
        elif self.path == "/voice/asr/status":
            self._json({"available": True, "model": "fake-whisper", "device": "cpu"})
        elif self.path == "/voice/tts/status":
            self._json({"available": True, "voice": "fake-piper"})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/voice/converse/stream":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).requests.append(payload)
        audio = base64.b64encode(b"RIFF-fake-audio").decode("ascii")
        if type(self).mode == "chunk_before_transcript":
            events = [
                {"type": "chunk", "index": 0, "text": "Svar.", "audio_base64": audio},
                {"type": "done", "reply": "Svar.", "model": "fake"},
            ]
        elif type(self).mode == "error":
            events = [{"type": "error", "status": 503, "detail": "fake failure"}]
        else:
            events = [
                {"type": "transcript", "text": "Hvad er klokken lige nu"},
                {
                    "type": "chunk",
                    "index": 0,
                    "text": "Klokken er tolv.",
                    "audio_base64": audio,
                    "synth_s": 0.1,
                    "ttfa_s": 0.2,
                },
                {
                    "type": "done",
                    "reply": "Klokken er tolv.",
                    "model": "fake-model",
                    "via_cloud": False,
                    "language": "da",
                    "time_to_first_audio_s": 0.2,
                    "total_s": 0.4,
                },
            ]
        raw = b"".join(json.dumps(event).encode("utf-8") + b"\n" for event in events)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except BrokenPipeError:
            return


server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
server_thread = threading.Thread(target=server.serve_forever, daemon=True)
server_thread.start()
fixture_url = f"http://127.0.0.1:{server.server_address[1]}"
try:
    check(vb.get_json(fixture_url, "/healthz", 5)["status"] == "ok", "health JSON is read over loopback")
    FixtureHandler.mode = "valid"
    stream = vb.stream_turn(
        fixture_url,
        audio_bytes=b"fake wav bytes",
        language="da",
        model="test-model",
        timeout_s=5,
    )
    check(stream["transcript"] == "Hvad er klokken lige nu", "stream captures transcript event")
    check(stream["first_chunk_ms"] is not None, "stream measures first audio arrival")
    check(stream["terminal"] == "done", "stream requires terminal done")
    check(stream["done"]["reply_characters"] > 0, "report stores reply metadata without full reply")
    check(stream["done"]["reply_sha256"] and len(stream["done"]["reply_sha256"]) == 64,
          "reply is hash-bound")
    check(FixtureHandler.requests[-1]["model"] == "test-model", "requested model is forwarded explicitly")
    check("llm_api_key" not in FixtureHandler.requests[-1], "harness never sends a cloud key")

    aborted_transcript = vb.stream_turn(
        fixture_url,
        audio_bytes=b"fake wav bytes",
        language="da",
        model=None,
        timeout_s=5,
        abort_after="transcript",
    )
    check(aborted_transcript["aborted"] and not aborted_transcript["chunks"],
          "connection can be aborted immediately after transcript")

    aborted_chunk = vb.stream_turn(
        fixture_url,
        audio_bytes=b"fake wav bytes",
        language="da",
        model=None,
        timeout_s=5,
        abort_after="first_chunk",
    )
    check(aborted_chunk["aborted"] and len(aborted_chunk["chunks"]) == 1,
          "connection can be aborted after first audio chunk")

    FixtureHandler.mode = "chunk_before_transcript"
    try:
        vb.stream_turn(
            fixture_url,
            audio_bytes=b"fake wav bytes",
            language="da",
            model=None,
            timeout_s=5,
        )
    except vb.ProtocolError:
        bad_order = True
    else:
        bad_order = False
    check(bad_order, "chunk-before-transcript violates the protocol")

    FixtureHandler.mode = "error"
    try:
        vb.stream_turn(
            fixture_url,
            audio_bytes=b"fake wav bytes",
            language="da",
            model=None,
            timeout_s=5,
        )
    except vb.VoiceBaselineError as exc:
        surfaced_error = "fake failure" in str(exc)
    else:
        surfaced_error = False
    check(surfaced_error, "stream error event becomes a bounded harness error")
finally:
    server.shutdown()
    server.server_close()
    server_thread.join(timeout=5)


state = {
    "transcript": None,
    "transcript_ms": None,
    "first_chunk_ms": None,
    "done_ms": None,
    "chunks": [],
    "reply_audio_bytes": 0,
    "done": None,
    "error_event": None,
    "terminal": None,
}
vb._record_event(state, {"type": "transcript", "text": "hej"}, 10)
vb._record_event(
    state,
    {
        "type": "chunk",
        "index": 0,
        "text": "hej",
        "audio_base64": base64.b64encode(b"a").decode(),
    },
    20,
)
vb._record_event(state, {"type": "done", "reply": "hej"}, 30)
try:
    vb._record_event(state, {"type": "done", "reply": "igen"}, 40)
except vb.ProtocolError:
    event_after_done = True
else:
    event_after_done = False
check(event_after_done, "events after terminal state are rejected")

manual_example = ROOT / "eval" / "voice_manual_observations.example.json"
try:
    vb.load_manual_observations(manual_example)
except vb.VoiceBaselineError:
    manual_template_pending = True
else:
    manual_template_pending = False
check(
    not manual_template_pending,
    "manual observation template has the complete versioned structure",
)
manual = vb.load_manual_observations(manual_example)
manual_summary = vb._manual_summary(manual)
check(manual_summary["provided"] and not manual_summary["passed"],
      "pending manual observations cannot pass the gate")

old_temp_entries = vb._voice_temp_entries
samples = iter([{"old", "new"}, {"old"}])
vb._voice_temp_entries = lambda: next(samples, {"old"})
try:
    cleanup = vb.wait_for_cleanup({"old"}, timeout_s=1, poll_s=0.001)
finally:
    vb._voice_temp_entries = old_temp_entries
check(cleanup["clean"], "cleanup poll waits until new voice temp entries disappear")

with tempfile.TemporaryDirectory(prefix="voice-report-") as temp_dir:
    report_path = Path(temp_dir) / "nested" / "report.json"
    vb._write_json_atomic(report_path, {"schema": vb.REPORT_SCHEMA, "value": "blå"})
    parsed = json.loads(report_path.read_text(encoding="utf-8"))
    leftovers = list(report_path.parent.glob(report_path.name + ".*.tmp"))
    check(parsed["value"] == "blå", "atomic report writer preserves UTF-8")
    check(not leftovers, "atomic report writer leaves no temp file")

missing_args = argparse.Namespace(
    manifest=manifest_path,
    worker_url="http://127.0.0.1:8099",
    manual_observations=None,
    model=None,
    language="da",
    repetitions=1,
    cold_start_confirmed=False,
    cold_turn="turn-01",
    cancellation_probes=0,
    timeout=5.0,
    cleanup_timeout=1.0,
    max_wer=-1.0,
    max_warm_first_audio_ms=0.0,
    validate_only=False,
    require_manual=False,
)
missing_report, missing_exit = vb.run_baseline(missing_args)
check(missing_exit == 2, "missing audio fixtures use environment exit 2")
check(missing_report["gate"]["passed"] is False, "missing audio fixtures fail the gate")
check(len(missing_report["missing_audio"]) == 20, "all missing fixture paths are reported")
check(missing_report["worker"]["asr_status"] is None,
      "missing fixtures fail before contacting the worker")

source = (ROOT / "scripts" / "voice_baseline.py").read_text(encoding="utf-8")
check("llm_api_key" not in source, "harness source cannot accept or send an LLM API key")
check("127.0.0.1" in source and "loopback-only" in source,
      "harness documents and enforces loopback execution")
check("reply_sha256" in source and "reply_characters" in source,
      "model replies are represented as bounded metadata")

print(f"\n===== VOICE BASELINE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
