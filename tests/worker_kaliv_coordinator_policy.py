"""Fail-closed independent coordinator policy parser tests."""
import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kaliv_coordinator_policy import (
    CoordinatorPolicyError, decode_trusted_gate_keys, load_coordinator_policy,
    parse_coordinator_policy,
)


class CoordinatorPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = {
            "schema": "kaliv-independent-coordinator-policy/v1",
            "release_id": "release-1",
            "repository_heads": {
                "ModelRig": "1" * 64, "BodyRig": "2" * 64,
                "VisionRig": "3" * 64, "VoiceRig": "4" * 64,
            },
            "gate_keys": {
                "voicerig_physical_acceptance": {
                    "trusted-voice-key": base64.b64encode(bytes(range(32))).decode("ascii")
                }
            },
        }

    def parse(self):
        return parse_coordinator_policy(json.dumps(self.policy).encode())

    def test_valid_policy_is_only_parsed_not_authorized(self):
        policy = self.parse()
        self.assertEqual(len(decode_trusted_gate_keys(policy)["voicerig_physical_acceptance"]["trusted-voice-key"]), 32)
        self.assertNotIn("release_ready", policy)

    def test_missing_repository_rejected(self):
        del self.policy["repository_heads"]["BodyRig"]
        with self.assertRaises(CoordinatorPolicyError):
            self.parse()

    def test_extra_authorization_flag_rejected(self):
        self.policy["production_activation"] = True
        with self.assertRaises(CoordinatorPolicyError):
            self.parse()

    def test_unexpected_policy_field_rejected(self):
        self.policy["signature_algorithm"] = "RSA"
        with self.assertRaises(CoordinatorPolicyError):
            self.parse()

    def test_invalid_public_key_rejected(self):
        self.policy["gate_keys"]["voicerig_physical_acceptance"]["trusted-voice-key"] = "not-base64"
        with self.assertRaises(CoordinatorPolicyError):
            self.parse()

    def test_duplicate_json_keys_rejected(self):
        raw = b'{"schema":"a","schema":"b"}'
        with self.assertRaises(CoordinatorPolicyError):
            parse_coordinator_policy(raw)

    def test_relative_policy_path_rejected(self):
        with self.assertRaises(CoordinatorPolicyError):
            load_coordinator_policy("policy.json")

    @unittest.skipUnless(os.name == "posix", "POSIX mode checks")
    def test_group_writable_policy_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps(self.policy))
            path.chmod(0o664)
            with self.assertRaises(CoordinatorPolicyError):
                load_coordinator_policy(path)

    @unittest.skipUnless(os.name == "posix", "POSIX mode checks")
    def test_owner_only_policy_loads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps(self.policy))
            path.chmod(0o600)
            self.assertEqual(load_coordinator_policy(path)["release_id"], "release-1")


if __name__ == "__main__":
    unittest.main()
