#!/usr/bin/env python3
"""Body asset delivery (Unity renderer roadmap, slice A).

The worker serves the active body's validated avatar, thumbnail and
motions -- resolved from the selected person's body revision when it names
an installed bodyid, otherwise from the store's current selection -- and
only through BodyRig's own validated paths. Every served member is
sha256-checked against the inspection; unknown motion names 404; a person
naming an uninstalled body is a 409, not a silent fallback.
"""

from __future__ import annotations

import hashlib
import os
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

from app import person_runtime  # noqa: E402
from app.body_assets import BODY_STORE_ENV, build_body_router  # noqa: E402
from app.person_api import PERSONS_STORE_ENV  # noqa: E402
from app.person_registry import PersonRegistry  # noqa: E402

FULL_REVIEW = {"body_voice": True, "voice_personality": True, "body_personality": True, "overall": True}


class BodyAssetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        base = Path(self.dir.name)
        self.store_root = base / "bodyrig-profiles"
        os.environ[BODY_STORE_ENV] = str(self.store_root)
        os.environ[PERSONS_STORE_ENV] = str(base / "persons.json")
        person_runtime._cache.update(path=None, mtime=None, registry=None)
        identity = build_identity_bundle(tracking_fixture())
        self.body_id = identity["id"]
        self.package = build_mrbody(
            identity, display_name="Kaliv body", avatar_vrm=vrm_fixture("kaliv"),
            thumbnail_png=png_fixture(), builder_revision="4" * 40)
        self.store = MRBodyProfileStore(self.store_root)
        self.store.install(self.package)
        app = FastAPI()
        app.include_router(build_body_router())
        self.c = TestClient(app)

    def tearDown(self) -> None:
        os.environ.pop(BODY_STORE_ENV, None)
        os.environ.pop(PERSONS_STORE_ENV, None)
        self.dir.cleanup()

    def _select_current(self) -> None:
        MRBodyCurrentProfileStore(self.store).select(self.body_id)

    def _person_with_body(self, body_source: str) -> None:
        reg = PersonRegistry(Path(self.dir.name) / "persons.json")
        p = reg.create_person("Kaliv")
        b = reg.add_body_revision(p.person_id, body_source).id
        v = reg.add_voice_revision(p.person_id, "unbound").id
        pe = reg.add_personality_revision(p.person_id, system_instructions="Du er Kaliv.", default_language="dansk").id
        rev = reg.propose_person_revision(p.person_id, body=b, voice=v, personality=pe, review=FULL_REVIEW, reviewer="Anders")
        reg.activate(p.person_id, rev.id)
        reg.select(p.person_id)

    def test_no_selection_is_404_not_a_guess(self) -> None:
        r = self.c.get("/body/active")
        self.assertEqual(r.status_code, 404)

    def test_unconfigured_store_is_503(self) -> None:
        os.environ.pop(BODY_STORE_ENV, None)
        self.assertEqual(self.c.get("/body/active").status_code, 503)

    def test_current_selection_serves_manifest_and_verified_members(self) -> None:
        self._select_current()
        m = self.c.get("/body/active")
        self.assertEqual(m.status_code, 200)
        manifest = m.json()
        self.assertEqual(manifest["body_id"], self.body_id)
        self.assertEqual(manifest["source"], "current")
        self.assertEqual(manifest["name"], "Kaliv body")
        self.assertEqual(manifest["motions"], {})  # fixture carries no motions
        avatar = self.c.get("/body/active/avatar.vrm")
        self.assertEqual(avatar.status_code, 200)
        self.assertEqual(avatar.headers["content-type"].split(";")[0], "model/gltf-binary")
        self.assertEqual(avatar.content, vrm_fixture("kaliv"))
        self.assertEqual(avatar.headers["X-BodyRig-Body-ID"], self.body_id)
        self.assertEqual(avatar.headers["X-BodyRig-Member-SHA256"], hashlib.sha256(avatar.content).hexdigest())
        thumb = self.c.get("/body/active/thumbnail.png")
        self.assertEqual(thumb.status_code, 200)
        self.assertEqual(thumb.content, png_fixture())

    def test_person_body_wins_over_current(self) -> None:
        self._select_current()
        self._person_with_body(self.body_id)
        manifest = self.c.get("/body/active").json()
        self.assertEqual(manifest["source"], "person")
        self.assertEqual(manifest["body_id"], self.body_id)

    def test_person_naming_uninstalled_body_is_409(self) -> None:
        self._select_current()
        self._person_with_body("bodyid-" + "f" * 24)
        r = self.c.get("/body/active")
        self.assertEqual(r.status_code, 409)
        self.assertIn("not installed", r.json()["detail"])

    def test_unbound_person_body_falls_back_to_current(self) -> None:
        self._select_current()
        self._person_with_body("unbound")
        self.assertEqual(self.c.get("/body/active").json()["source"], "current")

    def test_session_path_caches_but_downloads_stay_fresh(self) -> None:
        import time
        from app import body_assets
        self._select_current()
        body_assets._resolved.update(at=0.0, key=None, body=None)
        first = body_assets.resolve_active_body(max_age_s=2.0)
        second = body_assets.resolve_active_body(max_age_s=2.0)
        self.assertIs(first, second)  # within the age: the same resolution
        fresh = body_assets.resolve_active_body()
        self.assertIsNot(fresh, first)  # no age: re-validated
        # A person selecting a different body invalidates the key immediately.
        self._person_with_body("bodyid-" + "f" * 24)
        with self.assertRaises(Exception):
            body_assets.resolve_active_body(max_age_s=2.0)
        body_assets._resolved.update(at=0.0, key=None, body=None)

    def test_unknown_and_absent_motions_are_404(self) -> None:
        self._select_current()
        self.assertEqual(self.c.get("/body/active/motions/idle.vrma").status_code, 404)
        self.assertEqual(self.c.get("/body/active/motions/evil.vrma").status_code, 404)
        self.assertEqual(self.c.get("/body/active/motions/../manifest.vrma").status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
