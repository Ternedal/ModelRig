#!/usr/bin/env python3
"""Person Profile registry contract (#752).

Binds every Done criterion from the issue: persistent multi-person
registry; CRUD/list/select via the API; versioned personality revisions;
immutable approved Person Revisions; atomic activation of
body+voice+personality via active_person_revision; and -- the one that
matters most -- no API path that can switch a single active component.
"""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.person_api import build_person_router, route_inventory  # noqa: E402
from app.person_registry import (  # noqa: E402
    PERSON_ID_RE,
    REVISION_RE,
    Invalid,
    PersonRegistry,
)

FULL_REVIEW = {"body_voice": True, "voice_personality": True, "body_personality": True, "overall": True}


def _seed(reg: PersonRegistry) -> tuple[str, str, str, str]:
    p = reg.create_person("Kaliv")
    b = reg.add_body_revision(p.person_id, "bodyid-abc123")
    v = reg.add_voice_revision(p.person_id, "voice-kaliv-01")
    pe = reg.add_personality_revision(
        p.person_id, system_instructions="Du er Kaliv.", default_language="da")
    return p.person_id, b.id, v.id, pe.id


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "persons.json"
        self.reg = PersonRegistry(self.path)

    def tearDown(self) -> None:
        self.dir.cleanup()

    def test_identity_formats(self) -> None:
        pid, b, v, pe = _seed(self.reg)
        self.assertRegex(pid, PERSON_ID_RE)
        for rev in (b, v, pe):
            self.assertRegex(rev, REVISION_RE)
        self.assertEqual((b, v, pe), ("body-r0001", "voice-r0001", "personality-r0001"))

    def test_component_revisions_do_not_change_the_active_person(self) -> None:
        pid, b, v, pe = _seed(self.reg)
        rev = self.reg.propose_person_revision(
            pid, body=b, voice=v, personality=pe, review=FULL_REVIEW, reviewer="Anders")
        self.reg.activate(pid, rev.id)
        self.reg.select(pid)
        # A new, "better" voice arrives. Nothing active moves.
        self.reg.add_voice_revision(pid, "voice-kaliv-02")
        self.reg.add_personality_revision(
            pid, system_instructions="Nyt udkast", default_language="da")
        bindings = self.reg.active_bindings()
        self.assertEqual(bindings["voice"]["id"], v)
        self.assertEqual(bindings["personality"]["id"], pe)
        self.assertEqual(self.reg.get(pid).active_person_revision, rev.id)

    def test_person_revision_requires_the_full_compatibility_review(self) -> None:
        pid, b, v, pe = _seed(self.reg)
        for missing in FULL_REVIEW:
            review = dict(FULL_REVIEW)
            review[missing] = False
            with self.assertRaises(Invalid) as ctx:
                self.reg.propose_person_revision(
                    pid, body=b, voice=v, personality=pe, review=review, reviewer="Anders")
            self.assertIn(missing, str(ctx.exception))
        # "Voice too young for the body" is exactly the case: no revision, no activation.
        self.assertEqual(self.reg.get(pid).person_revisions, [])

    def test_activation_is_atomic_and_only_via_person_revision(self) -> None:
        pid, b, v, pe = _seed(self.reg)
        v2 = self.reg.add_voice_revision(pid, "voice-kaliv-02").id
        r1 = self.reg.propose_person_revision(
            pid, body=b, voice=v, personality=pe, review=FULL_REVIEW, reviewer="Anders")
        r2 = self.reg.propose_person_revision(
            pid, body=b, voice=v2, personality=pe, review=FULL_REVIEW, reviewer="Anders")
        self.reg.select(pid)
        self.reg.activate(pid, r1.id)
        self.assertEqual(self.reg.active_bindings()["voice"]["id"], v)
        self.reg.activate(pid, r2.id)
        bindings = self.reg.active_bindings()
        # All three bindings come from r2 -- the voice moved WITH the revision.
        self.assertEqual(bindings["person_revision"], r2.id)
        self.assertEqual((bindings["body"]["id"], bindings["voice"]["id"], bindings["personality"]["id"]), (b, v2, pe))
        # And the domain object has no per-component active field at all.
        person = self.reg.get(pid)
        for name in vars(person):
            self.assertNotIn(name, {"active_body", "active_voice", "active_personality"})

    def test_approved_person_revisions_are_immutable(self) -> None:
        pid, b, v, pe = _seed(self.reg)
        rev = self.reg.propose_person_revision(
            pid, body=b, voice=v, personality=pe, review=FULL_REVIEW, reviewer="Anders")
        # No method mutates an existing revision; the only way to a different
        # triple is a NEW revision with its own review.
        methods = [m for m in dir(self.reg) if not m.startswith("_")]
        self.assertFalse(any("update" in m or "edit" in m or "modify" in m for m in methods), methods)
        again = self.reg.propose_person_revision(
            pid, body=b, voice=v, personality=pe, review=FULL_REVIEW, reviewer="Anders")
        self.assertNotEqual(again.id, rev.id)
        self.assertEqual(self.reg.get(pid).revision(rev.id).voice, v)

    def test_persistence_roundtrip(self) -> None:
        pid, b, v, pe = _seed(self.reg)
        rev = self.reg.propose_person_revision(
            pid, body=b, voice=v, personality=pe, review=FULL_REVIEW, reviewer="Anders")
        self.reg.activate(pid, rev.id)
        self.reg.select(pid)
        reopened = PersonRegistry(self.path)
        self.assertEqual(reopened.selected_person_id, pid)
        self.assertEqual(reopened.active_bindings()["person_revision"], rev.id)
        self.assertEqual(reopened.get(pid).display_name, "Kaliv")

    def test_multiple_persons_are_independent(self) -> None:
        a = self.reg.create_person("Kaliv").person_id
        b = self.reg.create_person("Alva").person_id
        self.reg.add_body_revision(a, "bodyid-a")
        self.assertEqual(len(self.reg.get(b).body_revisions), 0)
        self.assertEqual({p.person_id for p in self.reg.list_persons()}, {a, b})


class ApiContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        reg = PersonRegistry(Path(self.dir.name) / "persons.json")
        app = FastAPI()
        self.router = build_person_router(reg)
        app.include_router(self.router)
        self.c = TestClient(app)

    def tearDown(self) -> None:
        self.dir.cleanup()

    def test_no_route_can_activate_a_single_component(self) -> None:
        paths = [p for _, p in route_inventory(self.router)]
        offenders = [p for p in paths if re.search(r"(body|voice|personality)[^/]*/(activate|select|active)", p)]
        self.assertEqual(offenders, [], offenders)
        activations = [p for m, p in route_inventory(self.router) if p.endswith("/activate")]
        self.assertEqual(activations, ["/persons/{person_id}/activate"])

    def test_crud_list_select_and_activate_through_http(self) -> None:
        r = self.c.post("/persons", json={"display_name": "Kaliv"})
        self.assertEqual(r.status_code, 201)
        pid = r.json()["person_id"]
        b = self.c.post(f"/persons/{pid}/body-revisions", json={"source_id": "bodyid-x"}).json()["id"]
        v = self.c.post(f"/persons/{pid}/voice-revisions", json={"source_id": "voice-x"}).json()["id"]
        pe = self.c.post(f"/persons/{pid}/personality-revisions", json={
            "system_instructions": "Du er Kaliv.", "default_language": "da", "style_notes": "kort"}).json()["id"]
        bad = self.c.post(f"/persons/{pid}/person-revisions", json={
            "body": b, "voice": v, "personality": pe, "reviewer": "Anders",
            "review": {"body_voice": True, "voice_personality": True, "body_personality": True, "overall": False}})
        self.assertEqual(bad.status_code, 422)
        good = self.c.post(f"/persons/{pid}/person-revisions", json={
            "body": b, "voice": v, "personality": pe, "reviewer": "Anders", "review": FULL_REVIEW})
        self.assertEqual(good.status_code, 201)
        rev = good.json()["id"]
        self.assertEqual(self.c.post(f"/persons/{pid}/activate", json={"person_revision": "person-r9999"}).status_code, 404)
        self.assertEqual(self.c.post(f"/persons/{pid}/activate", json={"person_revision": rev}).status_code, 200)
        self.assertEqual(self.c.post("/persons/select", json={"person_id": pid}).status_code, 200)
        active = self.c.get("/persons/active").json()
        self.assertEqual(active["active"]["person_revision"], rev)
        self.assertEqual(active["active"]["personality"]["style_notes"], "kort")
        self.assertEqual(len(self.c.get("/persons").json()["persons"]), 1)
        self.assertEqual(self.c.get("/persons/person-doesnotexist").status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
