#!/usr/bin/env python3
"""scripts/person_create.py drives the real router end to end (#752):
one call creates identity, three candidates, a reviewed revision,
activates and selects -- and refuses to approve without --reviewed."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "scripts"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import person_bind  # noqa: E402
import person_create  # noqa: E402
from app.person_api import build_person_router  # noqa: E402
from app.person_registry import PersonRegistry  # noqa: E402


class PersonCreateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.reg = PersonRegistry(Path(self.dir.name) / "persons.json")
        app = FastAPI()
        app.include_router(build_person_router(self.reg))
        client = TestClient(app)

        def call(method, path, body):
            r = client.request(method, path, json=body)
            if r.status_code >= 400:
                raise SystemExit(f"{method} {path} -> {r.status_code}: {r.text}")
            return r.json()

        self.call = call

    def tearDown(self) -> None:
        self.dir.cleanup()

    def test_end_to_end_creates_activates_and_selects(self) -> None:
        result = person_create.run(
            self.call, name="Kaliv", instructions="Du er Kaliv.", language="dansk",
            style="korte svar", body_source="unbound", voice_source="unbound",
            reviewer="Anders", reviewed=True, note="foerste", select=True)
        self.assertEqual(result["person_revision"], "person-r0001")
        self.assertEqual(result["active"]["display_name"], "Kaliv")
        self.assertEqual(result["active"]["personality"]["style_notes"], "korte svar")
        self.assertEqual(self.reg.selected_person_id, result["person_id"])
        self.assertEqual(self.reg.get(result["person_id"]).active_person_revision, "person-r0001")

    def test_bind_makes_a_new_revision_and_moves_the_triple_whole(self) -> None:
        created = person_create.run(
            self.call, name="Kaliv", instructions="Du er Kaliv.", language="dansk", style="",
            body_source="unbound", voice_source="unbound", reviewer="Anders", reviewed=True, note="", select=True)
        pid = created["person_id"]
        bound = person_bind.run(self.call, person_id=pid, body="bodyid-" + "a" * 24, voice="kaliv.mrvoice",
                                reviewer="Anders", reviewed=True, note="virkelig krop og stemme")
        self.assertEqual(bound["previous_revision"], "person-r0001")
        self.assertEqual(bound["person_revision"], "person-r0002")
        self.assertEqual((bound["body"], bound["voice"], bound["personality"]), ("body-r0002", "voice-r0002", "personality-r0001"))
        person = self.reg.get(pid)
        self.assertEqual(person.active_person_revision, "person-r0002")
        # r0001 is untouched: immutable history.
        self.assertEqual(person.revision("person-r0001").voice, "voice-r0001")
        # Voice only, later: body candidate carried over from the active revision.
        again = person_bind.run(self.call, person_id=pid, body=None, voice="kaliv-v2.mrvoice",
                                reviewer="Anders", reviewed=True, note="")
        self.assertEqual((again["body"], again["voice"]), ("body-r0002", "voice-r0003"))

    def test_bind_refuses_without_reviewed_or_without_anything(self) -> None:
        created = person_create.run(
            self.call, name="Alva", instructions="x", language="dansk", style="",
            body_source="unbound", voice_source="unbound", reviewer="Anders", reviewed=True, note="", select=False)
        with self.assertRaises(SystemExit):
            person_bind.run(self.call, person_id=created["person_id"], body=None, voice="v.mrvoice",
                            reviewer="Anders", reviewed=False, note="")
        with self.assertRaises(SystemExit):
            person_bind.run(self.call, person_id=created["person_id"], body=None, voice=None,
                            reviewer="Anders", reviewed=True, note="")
        self.assertEqual(self.reg.get(created["person_id"]).active_person_revision, "person-r0001")

    def test_refuses_without_reviewed(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            person_create.run(
                self.call, name="Kaliv", instructions="x", language="dansk", style="",
                body_source="unbound", voice_source="unbound", reviewer="Anders",
                reviewed=False, note="", select=True)
        self.assertIn("--reviewed", str(ctx.exception))
        self.assertEqual(self.reg.list_persons(), [])

    def test_no_select_activates_but_leaves_selection_alone(self) -> None:
        result = person_create.run(
            self.call, name="Alva", instructions="Du er Alva.", language="dansk", style="",
            body_source="unbound", voice_source="unbound", reviewer="Anders",
            reviewed=True, note="", select=False)
        self.assertIsNone(self.reg.selected_person_id)
        self.assertIsNone(result["active"])
        self.assertEqual(self.reg.get(result["person_id"]).active_person_revision, "person-r0001")


if __name__ == "__main__":
    unittest.main(verbosity=2)
