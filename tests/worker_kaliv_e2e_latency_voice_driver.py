#!/usr/bin/env python3
"""Contract for scripts/kaliv_e2e_latency_voice_driver.py.

The driver is run against the real qualification routes, served over real HTTP
on loopback, with the voice backends and the cognitive session replaced by the
fakes of the route test. Microphone and speaker are injected.
"""
from __future__ import annotations

import importlib.util
import io
import inspect
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import wave
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import uvicorn
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


driver = _load("kaliv_e2e_latency_voice_driver", ROOT / "scripts" / "kaliv_e2e_latency_voice_driver.py")
route_test = _load("e2e_latency_voice_route_support", ROOT / "tests" / "worker_e2e_latency_voice_route.py")
voice = route_test.voice


def write_wav(path: Path, *, seconds: float = 0.2, fill: int = 0) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(bytes([fill]) * (2 * int(16000 * seconds)))


class VoiceDriverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="e2e-latency-driver-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.root = self.base / "evidence"
        self.root.mkdir()
        self.tts_available = True
        patches = [
            patch.dict(
                os.environ,
                {
                    voice.FLAG: "1",
                    voice.SHA_ENV: route_test.CANDIDATE,
                    voice.ROOT_ENV: str(self.root),
                },
                clear=False,
            ),
            patch.object(voice.voice_asr, "is_available", lambda: True),
            patch.object(voice.voice_tts, "is_available", lambda: self.tts_available),
            patch.object(voice.voice_asr, "transcribe_wav", lambda path, language: {"text": "hej"}),
            patch.object(
                voice.voice_tts,
                "synthesize_to_wav",
                lambda text, out_path: write_wav(Path(out_path), seconds=0.3, fill=7) or {},
            ),
            patch.object(voice, "load_cognitive_profile", lambda: SimpleNamespace(profile=object())),
            # The driver asks for the voice measurement: no body may be touched.
            patch.object(voice.body_session, "current_session", route_test._no_body),
            patch.object(voice.body_session, "note_speech", route_test._no_body),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

        self.app = FastAPI()
        self.assertTrue(voice.mount(self.app))
        self.app.state.consciousness_session = route_test.FakeCognitiveSession()
        self.server = uvicorn.Server(
            uvicorn.Config(self.app, host="127.0.0.1", port=0, log_level="error", lifespan="off")
        )
        thread = threading.Thread(target=self.server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 30
        while not self.server.started:
            self.assertLess(time.monotonic(), deadline, "the test server did not start")
            time.sleep(0.02)
        port = self.server.servers[0].sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"

        def stop() -> None:
            self.server.should_exit = True
            thread.join(timeout=30)

        self.addCleanup(stop)
        self.played: list[dict] = []
        self.slept: list[float] = []
        self.printed: list[str] = []

    def outward_files(self) -> list[Path]:
        return sorted(self.root.glob("e2e-*/outward_started.json"))

    def play(self, path: Path) -> None:
        # At the moment playback begins, nothing may have been reported yet.
        self.played.append({"bytes": path.read_bytes(), "reported_before": len(self.outward_files())})

    def turn(self, **overrides) -> dict:
        arguments = {
            "worker_url": self.url,
            "language": "da",
            "timeout": 30.0,
            "wav": None,
            "record_seconds": None,
            "max_input_age_seconds": 600.0,
            "play": self.play,
            "player_label": "test speaker",
            "sleep": self.slept.append,
            "out": self.printed.append,
        }
        arguments.update(overrides)
        return driver.run_turn(**arguments)

    def fresh_wav(self, name: str = "utterance.wav", *, fill: int = 1) -> Path:
        path = self.base / name
        write_wav(path, fill=fill)
        return path

    def refused(self, fragment: str, **overrides) -> None:
        with self.assertRaises(driver.DriverError) as caught:
            self.turn(**overrides)
        self.assertIn(fragment, str(caught.exception))

    def test_one_turn_from_a_fresh_recording(self) -> None:
        source = self.fresh_wav()
        record = self.turn(wav=source)

        self.assertEqual(record["schema"], driver.RUN_SCHEMA)
        self.assertEqual(record["outward_kind"], "voice")
        self.assertEqual(record["candidate_git_sha"], route_test.CANDIDATE)
        self.assertEqual(record["input"]["sha256"], driver._sha256(source.read_bytes()))
        self.assertEqual(record["measured_ms"]["end_to_end"], 2_300)
        self.assertEqual(record["not_measured"], list(driver.NOT_MEASURED))
        self.assertIn("playback on a phone", record["not_measured"])
        self.assertIs(record["production_activation"], False)

        # Where the audio came from. The file is named like the driver's own
        # recording; it is still a file the operator supplied.
        self.assertEqual(source.name, "utterance.wav")
        self.assertEqual(record["input"]["source"], "operator_supplied_wav")
        self.assertIs(record["input"]["live_utterance_verified"], False)
        self.assertEqual(
            record["input"]["live_utterance"],
            "attested by the operator who ran the driver; not verified",
        )
        self.assertNotIn("mode", record["input"])

        # The clock stops at dispatch of playback, and the record says so.
        self.assertEqual(record["playback"]["start_event"], "dispatch")
        self.assertIs(record["playback"]["reported_after_dispatch"], True)
        self.assertIs(record["playback"]["audible_onset_measured"], False)
        self.assertNotIn("reported_after_playback_began", record["playback"])
        self.assertTrue(any("became audible" in line for line in record["not_measured"]))
        self.assertTrue(any("spoken live" in line for line in record["not_measured"]))

        # The worker's own statement of the limits is bound by hash.
        sidecar = Path(record["scope_sidecar"]["path"])
        self.assertEqual(sidecar.name, "voice_outward_scope.json")
        self.assertEqual(sidecar.parent, Path(record["record_path"]).parent)
        self.assertEqual(record["scope_sidecar"]["sha256"], driver._sha256(sidecar.read_bytes()))
        scope = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertEqual(scope["not_measured"], record["not_measured"])
        self.assertEqual(tuple(scope["not_measured"]), route_test.voice.VOICE_NOT_MEASURED)

        # The reply was played, and the start was reported only after that.
        self.assertEqual(len(self.played), 1)
        self.assertEqual(self.played[0]["reported_before"], 0)
        self.assertEqual(driver._sha256(self.played[0]["bytes"]), record["reply"]["sha256"])
        self.assertEqual(len(self.outward_files()), 1)
        # The driver waits for the reply to finish before it exits.
        self.assertEqual(len(self.slept), 1)
        self.assertGreaterEqual(self.slept[0], 0.3)

        receipts = record["source_receipts"]
        for name in ("perception", "cognition", "outward"):
            path = Path(receipts[name]["path"])
            self.assertEqual(driver._sha256(path.read_bytes()), receipts[name]["sha256"])
        outward = json.loads(Path(receipts["outward"]["path"]).read_text(encoding="utf-8"))
        self.assertEqual(outward["details"]["outward_kind"], "voice")
        self.assertIsNone(outward["details"]["body_runtime_id"])

        # The record lies beside the receipts, and the printed command is the
        # qualifier's own command line for exactly these files.
        record_path = Path(record["record_path"])
        self.assertEqual(record_path.parent, Path(receipts["outward"]["path"]).parent)
        on_disk = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["expected_release_evidence_ref"], record["expected_release_evidence_ref"])
        command = record["qualifier_command"]
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = driver._load_qualifier().main(command[2:])
        verdict = json.loads(stream.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(verdict["state"], "MEASURED")
        self.assertEqual(verdict["outward_kind"], "voice")
        self.assertEqual(verdict["release_evidence_ref"], record["expected_release_evidence_ref"])

    def test_a_recording_is_used_once(self) -> None:
        source = self.fresh_wav()
        self.turn(wav=source)
        self.refused("has been used before", wav=source)
        self.assertEqual(len(self.played), 1, "a replayed recording is never played back")
        self.assertEqual(len(self.outward_files()), 1, "and no playback start is reported for it")
        # A new recording is fine.
        self.turn(wav=self.fresh_wav("second.wav", fill=2))
        self.assertEqual(len(self.outward_files()), 2)

    def test_an_old_or_broken_recording_is_refused_before_the_worker_is_asked(self) -> None:
        stale = self.fresh_wav("stale.wav")
        old = time.time() - 3600
        os.utime(stale, (old, old))
        self.refused("record the utterance again", wav=stale)
        not_wav = self.base / "notes.wav"
        not_wav.write_bytes(b"this is not audio")
        self.refused("not a readable PCM WAV", wav=not_wav)
        self.refused("cannot be read", wav=self.base / "missing.wav")
        self.assertEqual(list(self.root.iterdir()), [], "the worker was never asked")

    def test_recording_from_the_microphone(self) -> None:
        recorded: list[float] = []

        def record(path: Path, seconds: float) -> None:
            recorded.append(seconds)
            write_wav(path, fill=3)

        record_value = self.turn(record_seconds=4.0, record=record)
        self.assertEqual(recorded, [4.0])
        self.assertEqual(record_value["input"]["source"], "recorded_by_driver")
        self.assertEqual(record_value["input"]["seconds"], 4.0)
        # Recording through the input device proves no live speech either.
        self.assertIs(record_value["input"]["live_utterance_verified"], False)
        self.assertEqual(record_value["input"]["live_utterance"], driver.LIVE_UTTERANCE)
        self.assertTrue(any("Tal nu" in line for line in self.printed))
        for seconds in (0.5, 31.0):
            self.refused("between 1 and 30", record_seconds=seconds, record=record)
        self.refused("exactly one of", wav=self.fresh_wav(), record_seconds=4.0, record=record)
        self.refused("exactly one of")

    def test_the_source_of_the_utterance_follows_from_the_input_alone(self) -> None:
        # Nothing lets a caller name the source or claim live speech: the
        # record derives both from which input was given.
        claims = ("source", "mode", "live", "provenance", "attest", "replay")
        for name in inspect.signature(driver.run_turn).parameters:
            self.assertFalse(any(word in name for word in claims), name)
        options = [
            option
            for action in driver.build_parser()._actions
            for option in action.option_strings
        ]
        self.assertIn("--wav", options)
        self.assertIn("--record-seconds", options)
        for option in options:
            self.assertFalse(any(word in option for word in claims), option)

    def sidecar_changed(self, change):
        """Let the turn run, then alter the worker's scope sidecar."""
        real = driver.post_json
        earlier = set(self.root.glob("*/voice_outward_scope.json"))

        def post(url: str, payload, timeout: float) -> dict:
            answer = real(url, payload, timeout)
            if url.endswith("/started"):
                (path,) = set(self.root.glob("*/voice_outward_scope.json")) - earlier
                change(path)
            return answer

        return patch.object(driver, "post_json", post)

    def test_a_scope_sidecar_that_says_less_is_refused(self) -> None:
        def edit(update):
            def change(path: Path) -> None:
                scope = json.loads(path.read_text(encoding="utf-8"))
                update(scope)
                path.write_text(json.dumps(scope), encoding="utf-8")
            return change

        cases = (
            ("an older worker's shorter list", edit(lambda scope: scope["not_measured"].pop())),
            ("audible onset claimed", edit(lambda scope: scope.update(audible_onset_measured=True))),
            ("audible onset unstated", edit(lambda scope: scope.pop("audible_onset_measured"))),
            ("live speech claimed", edit(lambda scope: scope.update(live_utterance_verified=True))),
            ("live speech unstated", edit(lambda scope: scope.pop("live_utterance_verified"))),
            ("another measurement", edit(lambda scope: scope.update(outward_kind="voice+body"))),
            ("another utterance", edit(lambda scope: scope.update(utterance_id="e2e-" + "9" * 32 + "-0"))),
            ("no sidecar", lambda path: path.unlink()),
            ("not JSON", lambda path: path.write_text("limits: none", encoding="utf-8")),
            ("a list", lambda path: path.write_text("[]", encoding="utf-8")),
        )
        for index, (label, change) in enumerate(cases):
            with self.subTest(label), self.sidecar_changed(change):
                self.refused("scope sidecar", wav=self.fresh_wav(f"s{index}.wav", fill=40 + index))
        self.assertEqual(list(self.root.glob("*/rig_driver_run.json")), [], "no run record")

    def test_no_playback_no_report(self) -> None:
        def broken(_path: Path) -> None:
            raise driver.DriverError("the reply could not be played: no audio device")

        self.refused("could not be played", wav=self.fresh_wav(), play=broken)
        self.assertEqual(self.outward_files(), [], "a reply that did not play is never reported")
        self.assertEqual(list(self.root.glob("e2e-*/rig_driver_run.json")), [])

    def test_a_worker_that_refuses_is_reported_plainly(self) -> None:
        self.tts_available = False
        self.refused("voice qualification backend unavailable", wav=self.fresh_wav())
        self.assertEqual(self.played, [])
        self.refused("cannot be reached", wav=self.fresh_wav("b.wav", fill=4), worker_url="http://127.0.0.1:9")

    def test_only_a_loopback_worker(self) -> None:
        for url in ("http://192.168.1.20:8099", "https://127.0.0.1:8099", "http://127.0.0.1", "http://127.0.0.1:8099/x"):
            self.refused("worker URL", wav=self.fresh_wav(), worker_url=url)

    def test_a_worker_without_the_voice_measurement_is_refused(self) -> None:
        # An older worker ignores outward_kind and answers a body-bound turn.
        def old_answer(url: str, payload, timeout: float) -> dict:
            return {
                "utterance_id": "e2e-" + "0" * 32 + "-0",
                "source_receipts": {"perception": "p", "cognition": "c", "outward": "o"},
                "audio_base64": "AAAA",
            }

        with patch.object(driver, "post_json", old_answer):
            self.refused("did not answer with a voice-only turn", wav=self.fresh_wav())
        self.assertEqual(self.played, [])

        # An answer that looks like this measurement but says it is body-bound.
        utterance = "e2e-" + "1" * 32 + "-0"

        def body_bound(url: str, payload, timeout: float) -> dict:
            return {
                "utterance_id": utterance,
                "outward_kind": "voice+body",
                "playback_started_path": f"{driver.TURN_PATH}/{utterance}/started",
                "source_receipts": {"perception": "p", "cognition": "c", "outward": "o"},
                "audio_base64": "AAAA",
            }

        with patch.object(driver, "post_json", body_bound):
            self.refused("did not answer with a voice-only turn", wav=self.fresh_wav("c.wav", fill=5))
        self.assertEqual(self.played, [])

        # A voice answer whose receipt paths are not one real evidence
        # directory. The driver writes beside the receipts, so it must not
        # follow such paths.
        elsewhere = self.base / "elsewhere"
        elsewhere.mkdir()
        cases = (
            {"perception": "p.json", "cognition": "c.json", "outward": "o.json"},
            {
                "perception": str(self.root / "missing" / "p.json"),
                "cognition": str(self.root / "missing" / "c.json"),
                "outward": str(self.root / "missing" / "o.json"),
            },
            {
                "perception": str(elsewhere / "p.json"),
                "cognition": str(self.base / "c.json"),
                "outward": str(elsewhere / "o.json"),
            },
        )
        (elsewhere / "p.json").write_text("{}", encoding="utf-8")
        (self.base / "c.json").write_text("{}", encoding="utf-8")
        for index, receipts in enumerate(cases):
            def odd_paths(url: str, payload, timeout: float, receipts=receipts) -> dict:
                return {
                    "utterance_id": utterance,
                    "outward_kind": "voice",
                    "playback_started_path": f"{driver.TURN_PATH}/{utterance}/started",
                    "source_receipts": receipts,
                    "audio_base64": "AAAA",
                }

            with patch.object(driver, "post_json", odd_paths):
                self.refused(
                    "not one evidence directory",
                    wav=self.fresh_wav(f"d{index}.wav", fill=10 + index),
                )
        # Relative paths that do exist where the driver happens to run.
        (elsewhere / "c.json").write_text("{}", encoding="utf-8")
        relative = {"perception": "p.json", "cognition": "c.json", "outward": "o.json"}

        def relative_paths(url: str, payload, timeout: float) -> dict:
            return {
                "utterance_id": utterance,
                "outward_kind": "voice",
                "playback_started_path": f"{driver.TURN_PATH}/{utterance}/started",
                "source_receipts": relative,
                "audio_base64": "AAAA",
            }

        source = self.fresh_wav("relative.wav", fill=20)
        previous = Path.cwd()
        os.chdir(elsewhere)
        try:
            with patch.object(driver, "post_json", relative_paths):
                self.refused("not one evidence directory", wav=source)
        finally:
            os.chdir(previous)
        self.assertEqual(self.played, [])
        self.assertEqual(
            sorted(path.name for path in self.base.rglob("driver-used-inputs.jsonl")), [],
            "nothing is written when the paths are refused",
        )

    def test_the_command_line_runs_a_turn_and_leaves_no_bytecode(self) -> None:
        # The driver is run from the candidate checkout, and the freeze gate
        # refuses a checkout with stray bytecode.
        import subprocess

        scripts = self.base / "copy" / "scripts"
        scripts.mkdir(parents=True)
        for name in ("kaliv_e2e_latency_voice_driver.py", "kaliv_end_to_end_latency_qualifier.py"):
            shutil.copy(ROOT / "scripts" / name, scripts / name)
        environment = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
        completed = subprocess.run(
            [
                sys.executable,
                str(scripts / "kaliv_e2e_latency_voice_driver.py"),
                "--worker-url", self.url,
                "--wav", str(self.fresh_wav("cli.wav", fill=6)),
                "--player-command", f'"{sys.executable}" -c pass {{wav}}',
            ],
            capture_output=True,
            text=True,
            env=environment,
            timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout[-400:] + completed.stderr[-400:])
        printed, _, tail = completed.stdout.partition("\n\nKvalific")
        record = json.loads(printed)
        self.assertEqual(record["outward_kind"], "voice")
        self.assertEqual(record["playback"]["player"].split(":")[0], "operator command")
        self.assertIn("kaliv_end_to_end_latency_qualifier.py", tail)
        self.assertIn("--outward", tail)
        self.assertEqual(list((self.base / "copy").rglob("__pycache__")), [])

    def test_command_line(self) -> None:
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = driver.main(["--worker-url", "http://10.0.0.5:8099", "--wav", str(self.fresh_wav())])
        self.assertEqual(code, 2)
        self.assertIn("worker URL", json.loads(stream.getvalue())["error"])
        with self.assertRaises(driver.DriverError):
            driver.player_from_command("ffplay -autoexit")
        marker = self.base / "played.txt"
        play = driver.player_from_command(
            f'"{sys.executable}" -c "import sys,pathlib; pathlib.Path(sys.argv[2]).write_text(sys.argv[1])" {{wav}} "{marker}"'
        )
        play(self.base / "reply.wav")
        deadline = time.monotonic() + 30
        while not marker.exists():
            self.assertLess(time.monotonic(), deadline, "the player command did not run")
            time.sleep(0.05)
        self.assertEqual(marker.read_text(), str(self.base / "reply.wav"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
