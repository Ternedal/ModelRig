#!/usr/bin/env python3
"""Runtime binding of the Person Profile registry (#752).

With no person selected the client's system prompt is used unchanged --
nothing about today's chat moves until an operator selects a person.
With a selected person that has an active revision, the registry's
personality wins, the descriptor names who answered, and a corrupt store
degrades to the client prompt rather than taking the chat down.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app import person_runtime  # noqa: E402
from app.person_api import PERSONS_STORE_ENV  # noqa: E402
from app.person_registry import PersonRegistry  # noqa: E402

FULL_REVIEW = {"body_voice": True, "voice_personality": True, "body_personality": True, "overall": True}


class PersonRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.store = Path(self.dir.name) / "persons.json"
        os.environ[PERSONS_STORE_ENV] = str(self.store)
        person_runtime._cache.update(path=None, mtime=None, registry=None)

    def tearDown(self) -> None:
        os.environ.pop(PERSONS_STORE_ENV, None)
        self.dir.cleanup()

    def _activate_kaliv(self) -> str:
        reg = PersonRegistry(self.store)
        p = reg.create_person("Kaliv")
        b = reg.add_body_revision(p.person_id, "bodyid-1").id
        v = reg.add_voice_revision(p.person_id, "voice-1").id
        pe = reg.add_personality_revision(
            p.person_id, system_instructions="Du er Kaliv, en rolig assistent.",
            default_language="dansk", style_notes="korte svar").id
        rev = reg.propose_person_revision(
            p.person_id, body=b, voice=v, personality=pe, review=FULL_REVIEW, reviewer="Anders")
        reg.activate(p.person_id, rev.id)
        reg.select(p.person_id)
        return p.person_id

    def test_no_store_means_client_prompt_unchanged(self) -> None:
        prompt, person = person_runtime.resolve_system_prompt("client persona")
        self.assertEqual(prompt, "client persona")
        self.assertIsNone(person)
        self.assertEqual(person_runtime.resolve_system_prompt(None), (None, None))

    def test_selected_person_without_active_revision_does_not_bind(self) -> None:
        reg = PersonRegistry(self.store)
        p = reg.create_person("Kaliv")
        reg.select(p.person_id)
        prompt, person = person_runtime.resolve_system_prompt("client persona")
        self.assertEqual(prompt, "client persona")
        self.assertIsNone(person)

    def test_active_person_wins_over_client_prompt(self) -> None:
        pid = self._activate_kaliv()
        prompt, person = person_runtime.resolve_system_prompt("client persona")
        self.assertIn("Du er Kaliv, en rolig assistent.", prompt)
        self.assertIn("dansk", prompt)
        self.assertIn("Stil: korte svar", prompt)
        self.assertNotIn("client persona", prompt)
        self.assertEqual(person["person_id"], pid)
        self.assertEqual(person["person_revision"], "person-r0001")
        self.assertEqual(person["personality_revision"], "personality-r0001")

    def test_registry_changes_are_picked_up_without_restart(self) -> None:
        pid = self._activate_kaliv()
        person_runtime.resolve_system_prompt(None)
        reg = PersonRegistry(self.store)
        pe2 = reg.add_personality_revision(
            pid, system_instructions="Du er Kaliv v2.", default_language="dansk").id
        rev2 = reg.propose_person_revision(
            pid, body="body-r0001", voice="voice-r0001", personality=pe2,
            review=FULL_REVIEW, reviewer="Anders")
        reg.activate(pid, rev2.id)
        # Ensure the mtime moves even on coarse filesystems.
        os.utime(self.store, None)
        prompt, person = person_runtime.resolve_system_prompt(None)
        self.assertIn("Du er Kaliv v2.", prompt)
        self.assertEqual(person["person_revision"], rev2.id)

    def test_corrupt_store_degrades_to_client_prompt(self) -> None:
        self.store.write_text("{not json", encoding="utf-8")
        prompt, person = person_runtime.resolve_system_prompt("client persona")
        self.assertEqual(prompt, "client persona")
        self.assertIsNone(person)

    def test_compose_prompt_orders_instructions_language_style(self) -> None:
        text = person_runtime.compose_personality_prompt({
            "system_instructions": "A", "default_language": "engelsk", "style_notes": "B"})
        self.assertLess(text.index("A"), text.index("engelsk"))
        self.assertLess(text.index("engelsk"), text.index("Stil: B"))
        self.assertEqual(person_runtime.compose_personality_prompt({"system_instructions": "X"}), "X")


if __name__ == "__main__":
    unittest.main(verbosity=2)
