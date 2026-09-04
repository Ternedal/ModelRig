#!/usr/bin/env python3
"""Voice binding of the Person Profile registry (#752).

ModelRig asks VoiceRig for the selected person's voice with VoiceRig's own
voice_package field and verifies the answer against X-VoiceRig-Package. With no person (or an unbound voice)
the request is unchanged. An older VoiceRig that rejects the named package
(404) gets one retry without it and the result says voice_bound=False --
Kaliv still speaks, and the mismatch is reported, not hidden.
"""

from __future__ import annotations

import io
import json
import os
import struct
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app import person_runtime, voice_tts  # noqa: E402
from app.person_api import PERSONS_STORE_ENV  # noqa: E402
from app.person_registry import PersonRegistry  # noqa: E402

FULL_REVIEW = {"body_voice": True, "voice_personality": True, "body_personality": True, "overall": True}


def _wav_bytes() -> bytes:
    sr, frames = 16000, 160
    data = b"\x00\x00" * frames
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16)
    header += b"data" + struct.pack("<I", len(data))
    return header + data


class _Resp:
    def __init__(self, package: str):
        self._raw = _wav_bytes()
        self.headers = {"X-VoiceRig-Voice": "Kaliv", "X-VoiceRig-Voice-ID": "vid-" + package, "X-VoiceRig-Package": package}

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class PersonVoiceBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.store = Path(self.dir.name) / "persons.json"
        os.environ[PERSONS_STORE_ENV] = str(self.store)
        person_runtime._cache.update(path=None, mtime=None, registry=None)
        self.requests: list[dict] = []
        self._orig = voice_tts.urllib.request.urlopen

    def tearDown(self) -> None:
        voice_tts.urllib.request.urlopen = self._orig
        os.environ.pop(PERSONS_STORE_ENV, None)
        self.dir.cleanup()

    def _fake_voicerig(self, serves_package: str, unknown_package: bool = False):
        def urlopen(req, timeout=None):
            payload = json.loads(req.data.decode("utf-8"))
            self.requests.append(payload)
            if unknown_package and "voice_package" in payload:
                raise urllib.error.HTTPError(req.full_url, 404, "Den valgte stemmeprofil findes ikke.", {}, io.BytesIO(b"{}"))
            return _Resp(serves_package)
        voice_tts.urllib.request.urlopen = urlopen

    def _person_with_voice(self, source: str) -> None:
        reg = PersonRegistry(self.store)
        p = reg.create_person("Kaliv")
        b = reg.add_body_revision(p.person_id, "unbound").id
        v = reg.add_voice_revision(p.person_id, source).id
        pe = reg.add_personality_revision(p.person_id, system_instructions="Du er Kaliv.", default_language="dansk").id
        rev = reg.propose_person_revision(p.person_id, body=b, voice=v, personality=pe, review=FULL_REVIEW, reviewer="Anders")
        reg.activate(p.person_id, rev.id)
        reg.select(p.person_id)

    def _synth(self) -> dict:
        out = Path(self.dir.name) / "out.wav"
        return voice_tts._synthesize_voicerig("hej", str(out))

    def test_no_person_means_request_unchanged(self) -> None:
        self._fake_voicerig("default.mrvoice")
        res = self._synth()
        self.assertEqual(self.requests, [{"text": "hej"}])
        self.assertIsNone(res["requested_voice_package"])
        self.assertIsNone(res["voice_bound"])

    def test_unbound_voice_candidate_does_not_request_a_voice(self) -> None:
        self._person_with_voice("unbound")
        self._fake_voicerig("default.mrvoice")
        res = self._synth()
        self.assertEqual(self.requests, [{"text": "hej"}])
        self.assertIsNone(res["voice_bound"])

    def test_person_voice_is_requested_and_verified(self) -> None:
        self._person_with_voice("kaliv.mrvoice")
        self._fake_voicerig("kaliv.mrvoice")
        res = self._synth()
        self.assertEqual(self.requests, [{"text": "hej", "voice_package": "kaliv.mrvoice"}])
        self.assertEqual(res["requested_voice_package"], "kaliv.mrvoice")
        self.assertTrue(res["voice_bound"])

    def test_mismatch_is_reported_not_hidden(self) -> None:
        self._person_with_voice("kaliv.mrvoice")
        self._fake_voicerig("somebody-else.mrvoice")
        res = self._synth()
        self.assertFalse(res["voice_bound"])
        self.assertEqual(res["package"], "somebody-else.mrvoice")

    def test_unknown_package_gets_one_retry_with_the_default(self) -> None:
        self._person_with_voice("kaliv.mrvoice")
        self._fake_voicerig("default.mrvoice", unknown_package=True)
        res = self._synth()
        self.assertEqual([r.get("voice_package") for r in self.requests], ["kaliv.mrvoice", None])
        self.assertFalse(res["voice_bound"])
        self.assertEqual(res["provider"], "voicerig")


if __name__ == "__main__":
    unittest.main(verbosity=2)
