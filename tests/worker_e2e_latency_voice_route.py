#!/usr/bin/env python3
"""Functional contract for the #2063 voice qualification routes.

The mount contract only says the routes exist. This drives them: one real turn
through the handler with the voice backends and the cognitive session replaced
by fakes, and the three source receipts handed to the real latency qualifier.

It pins ADR-SYS-001 D5 and D6 for the ``voice`` measurement: no body session is
created or read, and the outward receipt names no body runtime.
"""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app import e2e_latency_voice as voice  # noqa: E402
from app.consciousness_core.production_lifecycle import TrustedRuntimeClock  # noqa: E402
from app.consciousness_core.session_lifecycle import ProductionCognitiveSession  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "kaliv_end_to_end_latency_qualifier",
    ROOT / "scripts" / "kaliv_end_to_end_latency_qualifier.py",
)
assert _SPEC and _SPEC.loader
qualifier = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = qualifier
_SPEC.loader.exec_module(qualifier)

CANDIDATE = "a" * 40
EVENT_ID = "cevt-" + "b" * 32
AUDIO = base64.b64encode(b"RIFF-not-really-a-wav").decode("ascii")
# Perception, cognition and playback start, in milliseconds on one clock.
TICKS_MS = (10_000, 10_700, 12_300)


class FakeCognitiveSession(ProductionCognitiveSession):
    """The parts of the live session the route uses, and nothing else."""

    def __init__(self) -> None:  # noqa: D401 - deliberately no super().__init__
        ticks = iter(TICKS_MS)
        last = [TICKS_MS[-1]]

        def monotonic_ns() -> int:
            last[0] = next(ticks, last[0] + 1)
            return last[0] * 1_000_000

        self._clock = TrustedRuntimeClock(monotonic_ns=monotonic_ns)
        self.admitted: list[str] = []

    @property
    def trusted_clock(self) -> TrustedRuntimeClock:
        return self._clock

    def submit_reported_user_turn(self, *, turn_id: str, user_text: str, source_ref: str):
        self.admitted.append(user_text)
        return SimpleNamespace(
            cognition_event=SimpleNamespace(event_id=EVENT_ID),
            cognition_event_queued=True,
        )

    async def step(self, *, profile, required_event_id: str):
        return SimpleNamespace(
            supervisor_step=SimpleNamespace(
                plan=SimpleNamespace(decision="RUN", selected_event_ids=(required_event_id,))
            ),
            live_state=SimpleNamespace(
                last_transition_receipt_ref="transition:test:1", completed_cycles=1
            ),
        )

    def consume_response_guidance(self, *, user_turn_event_id: str):
        return SimpleNamespace(text="Hej Anders.")


def _synthesize(text: str, out_path: str) -> dict:
    Path(out_path).write_bytes(b"RIFF-reply-" + text.encode("utf-8"))
    return {}


def _no_body(*_args, **_kwargs):
    raise AssertionError("the voice measurement must not create or read a body session")


class VoiceQualificationRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="e2e-latency-voice-route-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        patches = [
            patch.dict(
                os.environ,
                {
                    voice.FLAG: "1",
                    voice.SHA_ENV: CANDIDATE,
                    voice.ROOT_ENV: str(self.root),
                },
                clear=False,
            ),
            patch.object(voice.voice_asr, "is_available", lambda: True),
            patch.object(voice.voice_tts, "is_available", lambda: True),
            patch.object(voice.voice_asr, "transcribe_wav", lambda path, language: {"text": "hej"}),
            patch.object(voice.voice_tts, "synthesize_to_wav", _synthesize),
            patch.object(voice, "load_cognitive_profile", lambda: SimpleNamespace(profile=object())),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.app = FastAPI()
        self.assertTrue(voice.mount(self.app))
        self.session = FakeCognitiveSession()
        self.app.state.consciousness_session = self.session
        self.client = TestClient(self.app)

    def turn(self, **extra) -> dict:
        response = self.client.post(
            "/experimental/e2e-latency/voice", json={"audio_base64": AUDIO, **extra}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_voice_measurement_needs_no_body_and_claims_none(self) -> None:
        with patch.object(voice.body_session, "current_session", _no_body), patch.object(
            voice.body_session, "note_speech", _no_body
        ):
            turn = self.turn(outward_kind="voice")
            utterance = turn["utterance_id"]
            self.assertEqual(turn["outward_kind"], "voice")
            self.assertEqual(
                turn["playback_started_path"],
                f"/experimental/e2e-latency/voice/{utterance}/started",
            )
            self.assertIs(turn["outward_started"], False)
            self.assertIs(turn["release_gate_satisfied"], False)
            self.assertEqual(base64.b64decode(turn["audio_base64"]), b"RIFF-reply-Hej Anders.")
            receipts = {name: Path(path) for name, path in turn["source_receipts"].items()}
            self.assertTrue(receipts["perception"].is_file())
            self.assertTrue(receipts["cognition"].is_file())
            # Nothing says the reply played until someone reports that it did.
            self.assertFalse(receipts["outward"].exists())

            started = self.client.post(turn["playback_started_path"])
        self.assertEqual(started.status_code, 200, started.text)
        receipt = started.json()["qualification_outward_receipt"]
        self.assertEqual(
            receipt["details"],
            {
                "outward_kind": "voice",
                "started": True,
                "utterance_id": utterance,
                "body_runtime_id": None,
            },
        )
        self.assertEqual(receipt["candidate_git_sha"], CANDIDATE)
        self.assertEqual(receipt["event_id"], EVENT_ID)
        self.assertIs(started.json()["release_gate_satisfied"], False)
        self.assertEqual(json.loads(receipts["outward"].read_text(encoding="utf-8")), receipt)

        # The three files are exactly what the latency qualifier accepts.
        verdict = qualifier.qualify_receipts(
            evidence_root=self.root,
            perception_path=receipts["perception"],
            cognition_path=receipts["cognition"],
            outward_path=receipts["outward"],
        )
        self.assertEqual(verdict["state"], "MEASURED")
        self.assertEqual(verdict["outward_kind"], "voice")
        self.assertEqual(verdict["candidate_git_sha"], CANDIDATE)
        self.assertEqual(verdict["perception_to_cognition_ms"], 700)
        self.assertEqual(verdict["end_to_end_ms"], 2_300)
        self.assertIs(verdict["threshold_applied"], False)

        # What the number does not cover is stated beside the receipt, because
        # the receipt's schema has no field for it.
        scope = json.loads(
            (receipts["outward"].parent / "voice_outward_scope.json").read_text(encoding="utf-8")
        )
        self.assertEqual(scope["schema"], voice.VOICE_SCOPE_SCHEMA)
        self.assertEqual(scope["outward_kind"], "voice")
        self.assertEqual(scope["utterance_id"], utterance)
        self.assertEqual(scope["event_id"], EVENT_ID)
        self.assertIn("playback on a phone", scope["not_measured"])
        self.assertIn("the network between a phone and the rig", scope["not_measured"])
        self.assertIs(scope["production_activation"], False)

        # The stamp is a client's report of dispatch. The route hears nothing.
        self.assertEqual(scope["outward_event"], "client-reported-playback-dispatch")
        self.assertIs(scope["audible_onset_measured"], False)
        self.assertEqual(scope["not_measured"], list(voice.VOICE_NOT_MEASURED))
        self.assertEqual(len(scope["not_measured"]), 6)
        self.assertTrue(any("became audible" in line for line in scope["not_measured"]))
        self.assertTrue(any("spoken live" in line for line in scope["not_measured"]))

        # The route cannot tell live speech from a recording. The sidecar says
        # which receipt fields are the route's own assertion, and all three
        # receipts carry exactly those values whatever audio was posted.
        self.assertIs(scope["live_utterance_verified"], False)
        self.assertEqual(
            scope["receipt_fields_asserted_not_measured"], ["real_event", "simulated", "replay"]
        )
        for name in ("perception", "cognition", "outward"):
            receipt = json.loads(receipts[name].read_text(encoding="utf-8"))
            self.assertEqual(
                [receipt[field] for field in scope["receipt_fields_asserted_not_measured"]],
                [True, False, False],
                name,
            )

    def test_playback_start_is_reported_once(self) -> None:
        with patch.object(voice.body_session, "current_session", _no_body):
            turn = self.turn(outward_kind="voice")
            first = self.client.post(turn["playback_started_path"])
            outward = Path(turn["source_receipts"]["outward"])
            written = outward.read_bytes()
            second = self.client.post(turn["playback_started_path"])
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 404)
        self.assertEqual(outward.read_bytes(), written, "a second report must not move the timestamp")

    def test_unknown_utterances_are_refused(self) -> None:
        for utterance in ("e2e-" + "0" * 32 + "-0", "not-an-utterance", "e2e-" + "0" * 32 + "-1"):
            response = self.client.post(f"/experimental/e2e-latency/voice/{utterance}/started")
            self.assertEqual(response.status_code, 404, utterance)
        self.assertEqual(list(self.root.iterdir()), [], "an unknown utterance writes nothing")

    def test_a_restarted_worker_has_no_pending_start(self) -> None:
        with patch.object(voice.body_session, "current_session", _no_body):
            turn = self.turn(outward_kind="voice")
        restarted = FastAPI()
        self.assertTrue(voice.mount(restarted))
        response = TestClient(restarted).post(turn["playback_started_path"])
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Path(turn["source_receipts"]["outward"]).exists())

    def test_the_default_measurement_still_requires_a_body(self) -> None:
        with patch.object(voice.body_session, "current_session", lambda create=True: None):
            for body in ({"audio_base64": AUDIO}, {"audio_base64": AUDIO, "outward_kind": "voice+body"}):
                response = self.client.post("/experimental/e2e-latency/voice", json=body)
                self.assertEqual(response.status_code, 503, response.text)
                self.assertEqual(response.json()["detail"], "qualification body session unavailable")
        self.assertEqual(self.session.admitted, [], "nothing is admitted without the body it requires")

    def test_the_default_measurement_is_bound_to_the_body_session(self) -> None:
        bound: list[dict] = []

        class FakeBody:
            def bind_e2e_outward(self, **kwargs) -> bool:
                bound.append(kwargs)
                return True

        body = FakeBody()
        spoken: list[str] = []
        with patch.object(voice.body_session, "current_session", lambda create=True: body), patch.object(
            voice.body_session, "note_speech", lambda **kwargs: spoken.append(kwargs["utterance_id"])
        ):
            turn = self.turn()
        utterance = turn["utterance_id"]
        self.assertEqual(turn["outward_kind"], "voice+body")
        self.assertEqual(turn["playback_started_path"], f"/body/speech/{utterance}/started")
        self.assertEqual(spoken, [utterance])
        self.assertEqual(len(bound), 1)
        self.assertEqual(bound[0]["utterance_id"], utterance)
        self.assertEqual(bound[0]["cognition_event_id"], EVENT_ID)
        self.assertEqual(bound[0]["candidate_git_sha"], CANDIDATE)
        # It is the body session that reports this one; the voice route knows nothing of it.
        response = self.client.post(f"/experimental/e2e-latency/voice/{utterance}/started")
        self.assertEqual(response.status_code, 404)

    def test_only_the_two_measurements_exist(self) -> None:
        for kind in ("body", "phone", "", None, 1):
            response = self.client.post(
                "/experimental/e2e-latency/voice",
                json={"audio_base64": AUDIO, "outward_kind": kind},
            )
            self.assertEqual(response.status_code, 422, repr(kind))
        self.assertEqual(self.session.admitted, [])

    def test_pending_starts_are_bounded(self) -> None:
        registry = voice.VoiceOutwardRegistry()
        for index in range(voice._MAX_PENDING_VOICE_OUTWARD + 3):
            registry.bind(
                f"utterance-{index}",
                voice._PendingVoiceOutward(
                    observer=None,  # never started in this test
                    qualification_id=f"q-{index}",
                    receipt_path=self.root / "unused.json",
                    scope_path=self.root / "unused-scope.json",
                ),
            )
        self.assertEqual(len(registry._pending), voice._MAX_PENDING_VOICE_OUTWARD)
        self.assertNotIn("utterance-0", registry._pending, "the oldest pending start is dropped")
        with self.assertRaises(ValueError):
            registry.bind("utterance-5", registry._pending["utterance-5"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
