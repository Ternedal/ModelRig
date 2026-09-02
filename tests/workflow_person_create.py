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
