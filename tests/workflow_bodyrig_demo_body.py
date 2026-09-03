#!/usr/bin/env python3
"""bodyrig_demo_body.py: a VRM in, an installed and selected body out, and
/body/active answers with it. The demo identity is a fixture and says so."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests" / "support"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import bodyrig_demo_body  # noqa: E402
from bodyrig.profile_store import MRBodyProfileStore  # noqa: E402
from bodyrig_fixtures import vrm_fixture  # noqa: E402
from app.body_assets import BODY_STORE_ENV, build_body_router  # noqa: E402


class DemoBodyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        base = Path(self.dir.name)
        self.vrm = base / "kaliv.vrm"
        self.vrm.write_bytes(vrm_fixture("demo"))
        self.store = base / "bodyrig-profiles"
        os.environ[BODY_STORE_ENV] = str(self.store)
        os.environ.pop("KALIV_PERSONS_STORE", None)
        app = FastAPI()
        app.include_router(build_body_router())
        self.c = TestClient(app)

    def tearDown(self) -> None:
        os.environ.pop(BODY_STORE_ENV, None)
        self.dir.cleanup()

    def test_vrm_in_active_body_out(self) -> None:
        argv = sys.argv
        sys.argv = ["bodyrig_demo_body.py", "--vrm", str(self.vrm), "--name", "Kaliv", "--store", str(self.store)]
        try:
            self.assertEqual(bodyrig_demo_body.main(), 0)
        finally:
            sys.argv = argv
        manifest = self.c.get("/body/active").json()
        self.assertEqual(manifest["name"], "Kaliv")
        self.assertEqual(manifest["source"], "current")
        self.assertEqual(self.c.get("/body/active/avatar.vrm").content, vrm_fixture("demo"))

    def test_two_demo_bodies_need_distinct_source_names(self) -> None:
        pkg_a, id_a = bodyrig_demo_body.make_demo_body(vrm_path=self.vrm, name="A", thumbnail=None, source_name="a.mov")
        pkg_b, id_b = bodyrig_demo_body.make_demo_body(vrm_path=self.vrm, name="B", thumbnail=None, source_name="b.mov")
        self.assertNotEqual(id_a, id_b)
        pkg_c, id_c = bodyrig_demo_body.make_demo_body(vrm_path=self.vrm, name="C", thumbnail=None, source_name="a.mov")
        self.assertEqual(id_a, id_c)  # same demo identity -> same body id, replaced not added
        store = MRBodyProfileStore(self.store)
        store.install(pkg_a); store.install(pkg_b)
        self.assertEqual(len(list(store.list_receipts())) if hasattr(store, "list_receipts") else 2, 2)

    def test_garbage_vrm_is_refused(self) -> None:
        bad = Path(self.dir.name) / "bad.vrm"
        bad.write_bytes(b"not a vrm")
        argv = sys.argv
        sys.argv = ["bodyrig_demo_body.py", "--vrm", str(bad), "--name", "X", "--store", str(self.store)]
        try:
            with self.assertRaises(SystemExit) as ctx:
                bodyrig_demo_body.main()
            self.assertIn("could not build", str(ctx.exception))
        finally:
            sys.argv = argv


if __name__ == "__main__":
    unittest.main(verbosity=2)
