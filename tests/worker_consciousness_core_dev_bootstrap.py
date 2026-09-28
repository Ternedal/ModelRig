from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.consciousness_core.dev_bootstrap import (
    DevSelfBootstrapError,
    ensure_dev_self_state,
)
from app.consciousness_core.self_state import SelfStateStore
from app.person_registry import PersonRegistry, REVIEW_CHECKS


class DevConsciousnessBootstrapTests(unittest.TestCase):
    def active_person(self, root: Path):
        registry = PersonRegistry(root / "persons.json")
        person = registry.create_person("Kaliv")
        body = registry.add_body_revision(person.person_id, "body:kaliv:v1")
        voice = registry.add_voice_revision(person.person_id, "voice:kaliv:v1")
        personality = registry.add_personality_revision(
            person.person_id,
            system_instructions="Be Kaliv.",
            default_language="da",
        )
        revision = registry.propose_person_revision(
            person.person_id,
            body=body.id,
            voice=voice.id,
            personality=personality.id,
            review={key: True for key in REVIEW_CHECKS},
            reviewer="operator",
        )
        registry.activate(person.person_id, revision.id)
        registry.select(person.person_id)
        return registry, person, revision

    def test_bootstrap_is_idempotent_and_stable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, person, revision = self.active_person(root)
            store = SelfStateStore(root / "self.json")

            first = ensure_dev_self_state(store=store, registry=registry)
            second = ensure_dev_self_state(store=store, registry=registry)

            self.assertEqual(first["status"], "bootstrapped")
            self.assertEqual(second["status"], "existing")
            self.assertEqual(first["self_id"], second["self_id"])
            self.assertEqual(first["person_id"], person.person_id)
            self.assertEqual(first["person_revision"], revision.id)
            self.assertFalse(first["production_activation"])

    def test_missing_active_person_fails_without_writing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry = PersonRegistry(root / "persons.json")
            registry.create_person("Not selected")
            store = SelfStateStore(root / "self.json")

            with self.assertRaises(DevSelfBootstrapError):
                ensure_dev_self_state(store=store, registry=registry)
            self.assertIsNone(store.read())

    def test_existing_state_refuses_person_revision_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, person, first_revision = self.active_person(root)
            store = SelfStateStore(root / "self.json")
            ensure_dev_self_state(store=store, registry=registry)

            body = registry.add_body_revision(person.person_id, "body:kaliv:v2")
            current = registry.active_bindings()
            second_revision = registry.propose_person_revision(
                person.person_id,
                body=body.id,
                voice=current["voice"]["id"],
                personality=current["personality"]["id"],
                review={key: True for key in REVIEW_CHECKS},
                reviewer="operator",
            )
            registry.activate(person.person_id, second_revision.id)

            with self.assertRaises(DevSelfBootstrapError):
                ensure_dev_self_state(store=store, registry=registry)
            self.assertEqual(store.read().person_revision, first_revision.id)


if __name__ == "__main__":
    unittest.main()
