"""Negative verification tests that do not require a crypto backend."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kaliv_producer_signature_verifier import (
    AttestationVerificationError, verify_producer_attestation,
)


class SignatureBoundaryTests(unittest.TestCase):
    def test_malformed_input_fails_closed(self):
        with self.assertRaises(AttestationVerificationError):
            verify_producer_attestation(
                b'{"release_ready":true}', b"evidence",
                expected_release_id="release-1",
                expected_gate="voicerig_physical_acceptance",
                expected_repository_heads={},
                trusted_keys={},
            )

    def test_untrusted_gate_cannot_authorize(self):
        import hashlib
        item = {
            "schema": "kaliv-producer-attestation/v1",
            "release_id": "release-1",
            "gate": "voicerig_physical_acceptance",
            "producer": "runner",
            "run_id": "run-1",
            "evidence_sha256": hashlib.sha256(b"evidence").hexdigest(),
            "repository_heads": {
                "ModelRig": "1" * 64, "BodyRig": "2" * 64,
                "VisionRig": "3" * 64, "VoiceRig": "4" * 64,
            },
            "signature": {"algorithm": "Ed25519", "key_id": "untrusted", "value": "invalid"},
        }
        with self.assertRaises(AttestationVerificationError):
            verify_producer_attestation(
                json.dumps(item).encode(), b"evidence",
                expected_release_id="release-1",
                expected_gate="voicerig_physical_acceptance",
                expected_repository_heads=item["repository_heads"],
                trusted_keys={},
            )


if __name__ == "__main__":
    unittest.main()
