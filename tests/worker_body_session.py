#!/usr/bin/env python3
"""Live render frames (Unity renderer roadmap, slice B).

The session follows the turn: thinking, waiting_for_tool, speaking with an
audio-envelope mouth derived from the synthesized WAV, back to idle when the
track runs out, interrupted on demand. Every frame is core's v0.1 wire.
With no active body the routes answer 404 and the hooks are no-ops.
"""

from __future__ import annotations

import json
import math
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "tests" / "support"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from bodyrig.identity import build_identity_bundle  # noqa: E402
from bodyrig.mrbody import build_mrbody  # noqa: E402
from bodyrig.profile_selection import MRBodyCurrentProfileStore  # noqa: E402
from bodyrig.profile_store import MRBodyProfileStore  # noqa: E402
from bodyrig_fixtures import png_fixture, tracking_fixture, vrm_fixture  # noqa: E402

from app import body_session  # noqa: E402
from app.body_assets import BODY_STORE_ENV  # noqa: E402
from app.body_session import build_body_session_router  # noqa: E402


def tone_wav(duration_ms: int = 400, sr: int = 16000) -> bytes:
    n = sr * duration_ms // 1000
    samples = b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * 220 * i / sr))) for i in range(n))
    header = b"RIFF" + struct.pack("<I", 36 + len(samples)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16)
    header += b"data" + struct.pack("<I", len(samples))
    return header + samples


class BodySessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.store_root = Path(self.dir.name) / "bodyrig-profiles"
        os.environ[BODY_STORE_ENV] = str(self.store_root)
        os.environ.pop("KALIV_PERSONS_STORE", None)
        body_session._session = None
        identity = build_identity_bundle(tracking_fixture())
        self.body_id = identity["id"]
        store = MRBodyProfileStore(self.store_root)
        store.install(build_mrbody(identity, display_name="Kaliv body", avatar_vrm=vrm_fixture("k"),
                                   thumbnail_png=png_fixture(), builder_revision="5" * 40))
        self.store = store
        app = FastAPI()
        app.include_router(build_body_session_router())
        self.c = TestClient(app)

    def tearDown(self) -> None:
        body_session._session = None
        os.environ.pop(BODY_STORE_ENV, None)
        self.dir.cleanup()

    def _select(self) -> None:
        MRBodyCurrentProfileStore(self.store).select(self.body_id)

    def test_no_active_body_is_404_and_hooks_are_noops(self) -> None:
        self.assertEqual(self.c.get("/body/state").status_code, 404)
        self.assertEqual(self.c.post("/body/interrupt").status_code, 404)
        body_session.note_state("thinking")  # must not raise
        self.assertIsNone(body_session._session)

    def test_frames_are_v01_wire_and_follow_the_turn(self) -> None:
        self._select()
        f = self.c.get("/body/state").json()
        self.assertEqual((f["type"], f["version"]), ("bodyrig.render_frame", "0.1"))
        self.assertEqual(f["state"], "idle")
        self.assertEqual(f["body_id"], self.body_id)
        self.assertTrue(f["session_id"].startswith("body-"))
        body_session.note_state("thinking")
        self.assertEqual(self.c.get("/body/state").json()["state"], "thinking")
        body_session.note_state("waiting_for_tool")
        self.assertEqual(self.c.get("/body/state").json()["state"], "waiting_for_tool")
        self.assertEqual(self.c.post("/body/state/listening").json()["state"], "listening")
        self.assertEqual(self.c.post("/body/state/dancing").status_code, 422)

    def test_speech_moves_the_mouth_and_ends_itself(self) -> None:
        self._select()
        session = body_session.current_session()
        duration = session.speak(utterance_id="u1", wav_bytes=tone_wav(400))
        self.assertGreater(duration, 300)
        start = session.started_ms
        now = body_session._now_ms()
        mid = session.frame(timestamp_ms=now + 100)
        self.assertEqual(mid["state"], "speaking")
        self.assertEqual(mid["speech_timing_mode"], "audio_envelope")
        self.assertGreater(mid["mouth_open"], 0.0)
        after = session.frame(timestamp_ms=now + duration + 50)
        self.assertEqual(after["state"], "idle")
        self.assertEqual(after["mouth_open"], 0.0)
        self.assertIsNotNone(start)

    def test_interrupt_clears_speech_immediately(self) -> None:
        self._select()
        session = body_session.current_session()
        session.speak(utterance_id="u2", wav_bytes=tone_wav(2000))
        self.assertEqual(session.frame()["state"], "speaking")
        r = self.c.post("/body/interrupt")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["state"], "interrupted")
        f = session.frame()
        self.assertEqual(f["mouth_open"], 0.0)
        self.assertEqual(f["visemes"], [])

    def test_note_speech_reads_the_wav_from_disk(self) -> None:
        self._select()
        wav_path = Path(self.dir.name) / "chunk.wav"
        wav_path.write_bytes(tone_wav(300))
        body_session.note_speech(utterance_id="turn-0", wav_path=str(wav_path))
        self.assertEqual(self.c.get("/body/state").json()["state"], "speaking")

    def test_sse_stream_emits_frames(self) -> None:
        self._select()
        r = self.c.get("/body/frames", params={"limit": 2})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("text/event-stream"))
        lines = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
        self.assertEqual(self.c.get("/body/frames", params={"limit": 0}).status_code, 422)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["type"], "bodyrig.render_frame")
        self.assertGreaterEqual(lines[1]["timestamp_ms"], lines[0]["timestamp_ms"])

    def test_playback_report_reanchors_the_mouth_to_the_phone(self) -> None:
        self._select()
        session = body_session.current_session()
        duration = session.speak(utterance_id="s1", wav_bytes=tone_wav(400))
        synth_now = body_session._now_ms()
        # Synthesis-time approximation: the utterance would end at synth_now + duration.
        # The phone starts playing 5 s later and says so.
        import time as _t
        _t.sleep(0.05)
        r = self.c.post("/body/speech/s1/started")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["state"], "speaking")
        # Re-anchored: still speaking well past the synthesis-time end.
        frame = session.frame(timestamp_ms=synth_now + duration + 20)
        self.assertEqual(frame["state"], "speaking")
        self.assertGreater(frame["mouth_open"], 0.0)
        r = self.c.post("/body/speech/s1/ended")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(session.frame()["state"], "idle")
        self.assertEqual(self.c.post("/body/speech/never-synthesized/started").status_code, 404)

    def test_interrupt_forgets_pending_tracks(self) -> None:
        self._select()
        session = body_session.current_session()
        session.speak(utterance_id="s2", wav_bytes=tone_wav(300))
        session.interrupt()
        self.assertEqual(self.c.post("/body/speech/s2/started").status_code, 404)

    def test_cues_are_off_by_default(self) -> None:
        self._select()
        os.environ.pop("KALIV_BODY_CUES", None)
        session = body_session.current_session()
        session.set_state("thinking")
        f = session.frame()
        self.assertEqual((f["state"], f["emotion"], f["gesture"]), ("thinking", "neutral", None))
        session.speak(utterance_id="c0", wav_bytes=tone_wav(300), sentence="x" * 200)
        self.assertIsNone(session.frame()["gesture"])

    def test_cues_when_enabled_are_the_documented_policy_and_nothing_more(self) -> None:
        self._select()
        os.environ["KALIV_BODY_CUES"] = "1"
        try:
            session = body_session.current_session()
            session.set_state("thinking")
            f = session.frame()
            self.assertEqual((f["state"], f["emotion"]), ("thinking", "curious"))
            # A short sentence: speaking, no gesture. A long one: explain.
            session.speak(utterance_id="c1", wav_bytes=tone_wav(300), sentence="Ja.")
            f = session.frame()
            self.assertEqual((f["state"], f["gesture"], f["emotion"]), ("speaking", None, "neutral"))
            session.end_speech("c1")
            session.speak(utterance_id="c2", wav_bytes=tone_wav(300), sentence="Det er fordi " + "forklaring " * 8)
            f = session.frame()
            self.assertEqual((f["state"], f["gesture"]), ("speaking", "explain"))
            # Back to idle clears everything: no lingering gesture or emotion.
            session.end_speech("c2")
            session.set_state("idle")
            f = session.frame()
            self.assertEqual((f["state"], f["gesture"], f["emotion"]), ("idle", None, "neutral"))
            # Interrupt is neutral too -- the interruption rule.
            session.speak(utterance_id="c3", wav_bytes=tone_wav(500), sentence="x" * 100)
            session.interrupt()
            f = session.frame()
            self.assertEqual((f["state"], f["gesture"], f["mouth_open"]), ("interrupted", None, 0.0))
        finally:
            os.environ.pop("KALIV_BODY_CUES", None)

    def test_session_is_replaced_when_the_active_body_changes(self) -> None:
        self._select()
        first = body_session.current_session()
        identity = build_identity_bundle(tracking_fixture("another-source.mov"))
        self.store.install(build_mrbody(identity, display_name="Alva body", avatar_vrm=vrm_fixture("a"),
                                        thumbnail_png=png_fixture(), builder_revision="6" * 40))
        MRBodyCurrentProfileStore(self.store).select(identity["id"])
        second = body_session.current_session()
        self.assertNotEqual(first.session_id, second.session_id)
        self.assertEqual(second.body_id, identity["id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
