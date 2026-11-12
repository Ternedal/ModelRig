#!/usr/bin/env python3
"""Drive one end-to-end latency turn for the Kaliv V1 voice measurement.

The worker's qualification route measures from "audio accepted" to "playback of
the reply started", but nothing called it: no client sends the audio, plays the
reply and reports the start. This is that client, for the rig.

One run is one turn:

1. take one spoken utterance (recorded from the microphone now, or a WAV the
   operator recorded just before);
2. POST it to ``/experimental/e2e-latency/voice`` with ``outward_kind: voice``;
3. start playing the reply on this machine, and only then report the start;
4. check the three source receipts with the latency qualifier.

It measures ADR-SYS-001's V1 scope: to the first spoken answer, with no body.
The reply is played on the rig, so the number does not include a phone or the
network to it. The run record says so.

The tool talks to the worker on loopback only. It starts, stops and activates
nothing. The worker must already run with the qualification flag set.
"""
from __future__ import annotations

import sys

# Run from the candidate checkout: leave no bytecode behind for the freeze gate.
sys.dont_write_bytecode = True

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import shlex
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

RUN_SCHEMA = "kaliv-system/end-to-end-latency-voice-driver-run/v1"
TURN_PATH = "/experimental/e2e-latency/voice"
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_MAX_WAV_BYTES = 16 * 1024 * 1024
_MAX_REPLY_BYTES = 64 * 1024 * 1024
NOT_MEASURED = (
    "microphone capture and upload of the utterance",
    "the network between a phone and the rig",
    "playback on a phone",
    "output latency of the playback device",
)


class DriverError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Worker
# --------------------------------------------------------------------------

def loopback_url(raw: str) -> str:
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme != "http" or parsed.hostname not in _LOOPBACK_HOSTS:
        raise DriverError("worker URL must be a plain http loopback URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise DriverError("worker URL must be an origin without credentials or query")
    if parsed.path not in ("", "/"):
        raise DriverError("worker URL must be an origin without a path")
    try:
        port = parsed.port
    except ValueError as exc:
        raise DriverError("worker URL has an invalid port") from exc
    if port is None:
        raise DriverError("worker URL must name an explicit port")
    return raw.rstrip("/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def post_json(url: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
    data = b"" if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            raw = response.read(_MAX_REPLY_BYTES + 1)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = str(json.loads(exc.read(4096).decode("utf-8")).get("detail", ""))
        except Exception:
            pass
        raise DriverError(f"the worker answered {exc.code}: {detail or exc.reason}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise DriverError(f"the worker cannot be reached: {getattr(exc, 'reason', exc)}") from exc
    if len(raw) > _MAX_REPLY_BYTES:
        raise DriverError("the worker's answer is too large")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DriverError("the worker's answer is not JSON") from exc
    if not isinstance(value, dict):
        raise DriverError("the worker's answer is not an object")
    return value


# --------------------------------------------------------------------------
# Audio
# --------------------------------------------------------------------------

def wav_seconds(path: Path) -> float:
    """Length of a PCM WAV in seconds. Raises DriverError if it is not one."""
    try:
        with wave.open(str(path), "rb") as handle:
            frames, rate = handle.getnframes(), handle.getframerate()
    except (wave.Error, EOFError, OSError) as exc:
        raise DriverError(f"{path.name} is not a readable PCM WAV file") from exc
    if rate <= 0 or frames <= 0:
        raise DriverError(f"{path.name} holds no audio")
    return frames / rate


def record_microphone_windows(path: Path, seconds: float) -> None:
    """Record the default microphone to a 16 kHz mono WAV through MCI."""
    if os.name != "nt":
        raise DriverError("--record-seconds needs Windows; record a WAV and pass --wav")
    import ctypes

    winmm = ctypes.windll.winmm

    def send(command: str) -> None:
        error = winmm.mciSendStringW(command, None, 0, None)
        if error:
            buffer = ctypes.create_unicode_buffer(256)
            winmm.mciGetErrorStringW(error, buffer, 255)
            raise DriverError(f"microphone recording failed: {buffer.value or error}")

    alias = "kalivlatencyrec"
    send(f"open new type waveaudio alias {alias}")
    try:
        send(
            f"set {alias} time format ms bitspersample 16 channels 1 "
            "samplespersec 16000 bytespersec 32000 alignment 2"
        )
        send(f"record {alias}")
        time.sleep(seconds)
        send(f"stop {alias}")
        send(f'save {alias} "{path}"')
    finally:
        winmm.mciSendStringW(f"close {alias}", None, 0, None)


def play_wav_windows(path: Path) -> None:
    """Start playing on the default output and return at once."""
    if os.name != "nt":
        raise DriverError("playback needs Windows, or --player-command")
    import winsound

    try:
        winsound.PlaySound(
            str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
        )
    except RuntimeError as exc:
        raise DriverError(f"the reply could not be played: {exc}") from exc


def player_from_command(template: str) -> Callable[[Path], None]:
    """A player that starts ``template`` with ``{wav}`` replaced by the file."""
    if "{wav}" not in template:
        raise DriverError("--player-command must contain {wav}")

    def play(path: Path) -> None:
        command = [part.replace("{wav}", str(path)) for part in shlex.split(template, posix=os.name != "nt")]
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise DriverError(f"the reply could not be played: {exc}") from exc

    return play


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# One turn
# --------------------------------------------------------------------------

def _load_qualifier() -> Any:
    script = Path(__file__).resolve().parent / "kaliv_end_to_end_latency_qualifier.py"
    spec = importlib.util.spec_from_file_location("_kaliv_end_to_end_latency_qualifier", script)
    if spec is None or spec.loader is None:
        raise DriverError("the latency qualifier cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _used_inputs(journal: Path) -> set[str]:
    try:
        lines = journal.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    used = set()
    for line in lines:
        try:
            used.add(str(json.loads(line)["sha256"]))
        except (ValueError, KeyError, TypeError):
            continue
    return used


def run_turn(
    *,
    worker_url: str,
    language: str,
    timeout: float,
    wav: Path | None,
    record_seconds: float | None,
    max_input_age_seconds: float,
    record: Callable[[Path, float], None] = record_microphone_windows,
    play: Callable[[Path], None] = play_wav_windows,
    player_label: str = "winsound on the default output device",
    sleep: Callable[[float], None] = time.sleep,
    out: Callable[[str], None] = print,
    qualifier: Any | None = None,
) -> dict[str, Any]:
    """Run one voice turn and return the driver's run record."""
    worker = loopback_url(worker_url)
    if (wav is None) == (record_seconds is None):
        raise DriverError("give exactly one of --wav and --record-seconds")

    with tempfile.TemporaryDirectory(prefix="kaliv-e2e-latency-driver-") as scratch_raw:
        scratch = Path(scratch_raw)
        if record_seconds is not None:
            if not 1 <= record_seconds <= 30:
                raise DriverError("--record-seconds must be between 1 and 30")
            source = scratch / "utterance.wav"
            out(f"Tal nu. Optager i {record_seconds:g} sekunder ...")
            record(source, record_seconds)
            out("Optagelsen er slut.")
            input_record: dict[str, Any] = {"mode": "recorded-live", "seconds": record_seconds}
        else:
            source = wav
            try:
                age = time.time() - source.stat().st_mtime
            except OSError as exc:
                raise DriverError("the WAV file cannot be read") from exc
            # A file from last week is a replay of an old event, and the
            # receipts say this is not one.
            if age > max_input_age_seconds:
                raise DriverError(
                    f"the WAV file is {age:.0f} seconds old; record the utterance again "
                    f"(limit {max_input_age_seconds:.0f} seconds)"
                )
            input_record = {"mode": "supplied-file", "age_seconds": round(max(age, 0.0), 1)}
        try:
            audio = source.read_bytes()
        except OSError as exc:
            raise DriverError("the utterance cannot be read") from exc
        if not audio or len(audio) > _MAX_WAV_BYTES:
            raise DriverError("the utterance must be a nonempty WAV of at most 16 MB")
        input_record["wav_seconds"] = round(wav_seconds(source), 2)
        input_record["sha256"] = _sha256(audio)
        input_record["bytes"] = len(audio)

        turn = post_json(
            worker + TURN_PATH,
            {
                "audio_base64": base64.b64encode(audio).decode("ascii"),
                "language": language,
                "outward_kind": "voice",
            },
            timeout,
        )
        utterance = turn.get("utterance_id")
        started_path = turn.get("playback_started_path")
        receipts = turn.get("source_receipts")
        if (
            turn.get("outward_kind") != "voice"
            or not isinstance(utterance, str)
            or started_path != f"{TURN_PATH}/{utterance}/started"
            or not isinstance(receipts, dict)
            or set(receipts) != {"perception", "cognition", "outward"}
        ):
            # An older worker ignores outward_kind and binds the reply to a
            # body. That would be a voice+body measurement, not this one.
            raise DriverError("the worker did not answer with a voice-only turn")
        paths = {name: Path(str(value)) for name, value in receipts.items()}
        evidence_dir = paths["perception"].parent
        evidence_root = evidence_dir.parent
        # The record and the replay journal are written beside the receipts,
        # so the worker's paths decide where this tool writes. Accept only
        # what the route produces: three absolute paths in one directory.
        if (
            not all(path.is_absolute() for path in paths.values())
            or {path.parent for path in paths.values()} != {evidence_dir}
            or not paths["perception"].is_file()
            or not paths["cognition"].is_file()
        ):
            raise DriverError("the worker's receipt paths are not one evidence directory")

        # The same recording posted twice is a replay. The journal lives in the
        # worker's evidence root, which is only known from its answer, so the
        # check comes here: before playback, and so before any playback start
        # is reported. A replayed recording never becomes a measurement.
        journal = evidence_root / "driver-used-inputs.jsonl"
        if input_record["sha256"] in _used_inputs(journal):
            raise DriverError(
                "this recording has been used before; no playback start is reported. "
                "Record a new utterance."
            )
        with journal.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "sha256": input_record["sha256"],
                        "qualification_id": turn.get("qualification_id"),
                        "used_at": datetime.now(timezone.utc).isoformat(),
                    },
                    sort_keys=True,
                )
                + "\n"
            )

        try:
            reply = base64.b64decode(str(turn.get("audio_base64", "")), validate=True)
        except Exception as exc:
            raise DriverError("the worker's reply audio is not valid base64") from exc
        if not reply:
            raise DriverError("the worker sent no reply audio")
        reply_path = scratch / "reply.wav"
        reply_path.write_bytes(reply)
        reply_seconds = wav_seconds(reply_path)

        # Playback first, the report second. If the reply cannot be played,
        # nothing is reported and the turn stays unmeasured.
        play(reply_path)
        started = post_json(worker + started_path, None, 30.0)
        receipt = started.get("qualification_outward_receipt")
        if started.get("ok") is not True or not isinstance(receipt, dict):
            raise DriverError("the worker did not confirm the playback start")
        out("Svaret afspilles ...")
        sleep(reply_seconds + 0.3)

    qual = _load_qualifier() if qualifier is None else qualifier
    try:
        verdict = qual.qualify_receipts(
            evidence_root=evidence_root,
            perception_path=paths["perception"],
            cognition_path=paths["cognition"],
            outward_path=paths["outward"],
        )
    except qual.EndToEndLatencyQualificationError as exc:
        raise DriverError(f"the latency qualifier refuses the receipts: {exc}") from exc
    if verdict.get("outward_kind") != "voice":
        raise DriverError("the receipts do not describe a voice-only measurement")

    record_value = {
        "schema": RUN_SCHEMA,
        "qualification_id": turn.get("qualification_id"),
        "event_id": turn.get("event_id"),
        "utterance_id": utterance,
        "candidate_git_sha": verdict["candidate_git_sha"],
        "outward_kind": "voice",
        "input": input_record,
        "reply": {"sha256": _sha256(reply), "bytes": len(reply), "wav_seconds": round(reply_seconds, 2)},
        "playback": {
            "where": "on the machine that ran this driver",
            "player": player_label,
            "reported_after_playback_began": True,
        },
        "source_receipts": {
            name: {"path": str(path), "sha256": _sha256(path.read_bytes())}
            for name, path in paths.items()
        },
        "measured_ms": {
            "perception_to_cognition": verdict["perception_to_cognition_ms"],
            "cognition_to_outward": verdict["cognition_to_outward_ms"],
            "end_to_end": verdict["end_to_end_ms"],
        },
        "not_measured": list(NOT_MEASURED),
        "expected_release_evidence_ref": verdict["release_evidence_ref"],
        "note": (
            "This record is not a qualification verdict. Run "
            "kaliv_end_to_end_latency_qualifier.py on the three receipts."
        ),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "production_activation": False,
    }
    record_path = evidence_dir / "rig_driver_run.json"
    tmp = record_path.with_name(record_path.name + ".tmp")
    tmp.write_text(json.dumps(record_value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, record_path)
    record_value["record_path"] = str(record_path)
    record_value["qualifier_command"] = [
        "python",
        "scripts/kaliv_end_to_end_latency_qualifier.py",
        "--evidence-root", str(evidence_root),
        "--perception", str(paths["perception"]),
        "--cognition", str(paths["cognition"]),
        "--outward", str(paths["outward"]),
        "--report", str(evidence_dir / "latency-verdict.json"),
    ]
    return record_value


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--worker-url", default="http://127.0.0.1:8099")
    parser.add_argument("--language", default="da")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--record-seconds", type=float, help="record the microphone for this long (Windows)"
    )
    source.add_argument("--wav", type=Path, help="a WAV recorded just now, never used before")
    parser.add_argument(
        "--max-input-age-seconds",
        type=float,
        default=600.0,
        help="how old a --wav file may be (default: ten minutes)",
    )
    parser.add_argument(
        "--player-command",
        help="play the reply with this command instead of winsound; {wav} is the file",
    )
    parser.add_argument(
        "--timeout", type=float, default=600.0, help="seconds to wait for ASR, cognition and TTS"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        options: dict[str, Any] = {}
        if args.player_command:
            options["play"] = player_from_command(args.player_command)
            options["player_label"] = "operator command: " + args.player_command
        record = run_turn(
            worker_url=args.worker_url,
            language=args.language,
            timeout=args.timeout,
            wav=args.wav,
            record_seconds=args.record_seconds,
            max_input_age_seconds=args.max_input_age_seconds,
            # Prompts go to stderr, so stdout carries the record alone.
            out=lambda message: print(message, file=sys.stderr, flush=True),
            **options,
        )
    except DriverError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    command = record.pop("qualifier_command")
    print(json.dumps(record, indent=2, sort_keys=True))
    print()
    print("Kvalificér de tre kvitteringer:")
    print("  " + " ".join(f'"{part}"' if " " in part else part for part in command))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
