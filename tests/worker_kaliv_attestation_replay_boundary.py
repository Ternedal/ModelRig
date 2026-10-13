"""Producer/run binding and replay preflight negative tests."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kaliv_attestation_replay_boundary import verify_attestation_with_replay_boundary
from kaliv_producer_signature_verifier import AttestationVerificationError


class ReplayBoundaryTests(unittest.TestCase):
    def setUp(self):
        import hashlib
        self.heads = {"ModelRig": "1" * 64, "BodyRig": "2" * 64,
                      "VisionRig": "3" * 64, "VoiceRig": "4" * 64}
        self.envelope = {
            "schema": "kaliv-producer-attestation/v1",
            "release_id": "release-1",
            "gate": "voicerig_physical_acceptance",
            "producer": "runner-a",
            "run_id": "run-1",
            "evidence_sha256": hashlib.sha256(b"evidence").hexdigest(),
            "repository_heads": self.heads,
            "signature": {"algorithm": "Ed25519", "key_id": "key", "value": "untrusted"},
        }
        self.kwargs = {
            "evidence": b"evidence",
            "expected_release_id": "release-1",
            "expected_gate": "voicerig_physical_acceptance",
            "expected_producer": "runner-a",
            "expected_run_id": "run-1",
            "expected_repository_heads": self.heads,
            "trusted_keys": {},
            "previously_accepted": set(),
        }

    def check(self, **overrides):
        args = {**self.kwargs, "raw": json.dumps(self.envelope).encode(), **overrides}
        return verify_attestation_with_replay_boundary(**args)

    def test_untrusted_signature_cannot_authorize(self):
        with self.assertRaises(AttestationVerificationError):
            self.check()

    def test_mismatched_producer_rejected(self):
        with self.assertRaisesRegex(AttestationVerificationError, "Producer/run"):
            self.check(expected_producer="runner-b")

    def test_mismatched_run_rejected(self):
        with self.assertRaisesRegex(AttestationVerificationError, "Producer/run"):
            self.check(expected_run_id="run-2")

    def test_replayed_tuple_rejected_before_signature_check(self):
        with self.assertRaisesRegex(AttestationVerificationError, "Previously accepted"):
            self.check(previously_accepted={("release-1", "voicerig_physical_acceptance", "runner-a", "run-1")})

    def test_missing_expected_identity_rejected(self):
        with self.assertRaisesRegex(AttestationVerificationError, "Missing independently"):
            self.check(expected_producer="")


if __name__ == "__main__":
    unittest.main()
