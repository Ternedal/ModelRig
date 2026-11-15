"""Downstream fixture packaging tests; does not qualify a physical Quest avatar."""
import io
import json
import unittest
import zipfile

from scripts.kaliv_vr_fixture_pack import package
from tests.support.bodyrig_fixtures import png_fixture, vrm_fixture
from bodyrig.mrbody import validate_mrbody


class FixturePackageTests(unittest.TestCase):
    def test_builds_standard_validated_mrbody(self):
        vrm = vrm_fixture("kaliv-fixture")
        data = package(vrm, png_fixture(), "Kaliv hologram test")
        inspection = validate_mrbody(data)
        self.assertEqual(inspection.name, "Kaliv hologram test")
        self.assertTrue(inspection.body_id.startswith("bodyid-"))
        self.assertEqual(inspection.identity_content_id, inspection.body_id)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(archive.read("avatar.vrm"), vrm)
            provenance = json.loads(archive.read("provenance.json"))
            self.assertEqual(provenance["pipeline"][0]["stage"], "fixture_packaging")

    def test_deterministic_package(self):
        vrm = vrm_fixture("same")
        a = package(vrm, png_fixture(), "Test")
        b = package(vrm, png_fixture(), "Test")
        self.assertEqual(a, b)

    def test_rejects_plain_glb(self):
        with self.assertRaises(ValueError):
            package(b"not a VRM", png_fixture(), "Test")


if __name__ == "__main__":
    unittest.main()
