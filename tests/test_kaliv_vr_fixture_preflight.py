"""Regression tests for downstream Quest fixture preflight (no Unity needed)."""
import json
import struct
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.kaliv_vr_fixture_preflight import inspect


def glb(document):
    payload = json.dumps(document, separators=(",", ":")).encode()
    payload += b" " * (-len(payload) % 4)
    return struct.pack("<4sII", b"glTF", 2, 20 + len(payload)) + struct.pack("<I4s", len(payload), b"JSON") + payload


class FixturePreflightTests(unittest.TestCase):
    def check(self, doc, tmp_path):
        from pathlib import Path
        p = Path(tmp_path) / "avatar.vrm"
        p.write_bytes(glb(doc))
        return inspect(p)

    def test_rejects_plain_glb(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "VRMC_vrm"):
                self.check({"asset": {"version": "2.0"}, "nodes": []}, tmp)

    def test_rejects_wrong_vrm_version(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "1.0"):
                self.check({"extensionsUsed": ["VRMC_vrm"],
                            "extensions": {"VRMC_vrm": {"specVersion": "0.0"}}}, tmp)

    def test_rejects_unrigged_vrm(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "bones"):
                self.check({"extensionsUsed": ["VRMC_vrm"],
                            "extensions": {"VRMC_vrm": {"specVersion": "1.0", "humanoid": {"humanBones": {}}}},
                            "nodes": []}, tmp)


if __name__ == "__main__":
    unittest.main()
