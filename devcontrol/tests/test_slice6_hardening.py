from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from kaliv_dev_control.physical_isolation import (
    PhysicalIsolationError,
    WindowsPhysicalIsolationVerifier,
)
from test_slice6 import SECRET, report


class Slice6HardeningTests(unittest.TestCase):
    def test_direct_constructor_rejects_non_probe_objects(self):
        with self.assertRaisesRegex(PhysicalIsolationError, "invalid result"):
            report(probes=("not-a-probe",))

    @unittest.skipIf(not hasattr(os, "symlink"), "symlink support unavailable")
    def test_evidence_root_rejects_symlink_component(self):
        with tempfile.TemporaryDirectory() as directory:
            outer = Path(directory)
            target = outer / "target"
            target.mkdir()
            link = outer / "evidence-link"
            try:
                os.symlink(target, link, target_is_directory=True)
            except OSError:
                self.skipTest("directory symlinks are unavailable to this account")
            with self.assertRaisesRegex(PhysicalIsolationError, "non-symlink"):
                WindowsPhysicalIsolationVerifier(
                    link,
                    {"operator-key-2026": SECRET},
                )

    def test_signed_schema_reference_exists_locally(self):
        schemas = Path(__file__).resolve().parents[1] / "schemas"
        signed = json.loads(
            (schemas / "windows-isolation-signed-report-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        reference = signed["properties"]["report"]["$ref"]
        self.assertEqual(reference, "windows-isolation-physical-report-v1.schema.json")
        self.assertTrue((schemas / reference).is_file())


if __name__ == "__main__":
    unittest.main()
