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

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ImportError:
    Ed25519PrivateKey = None

from kaliv_producer_attestation_envelope import canonical_signed_payload


@unittest.skipUnless(Ed25519PrivateKey is not None, "cryptography backend not installed")
class RealSignatureTests(unittest.TestCase):
    """Deterministic private-key fixture; never use this key for production."""

    def setUp(self):
        import hashlib
        self.private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        self.public = self.private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.evidence = b"test-only-evidence"
        self.heads = {
            "ModelRig": "1" * 64, "BodyRig": "2" * 64,
            "VisionRig": "3" * 64, "VoiceRig": "4" * 64,
        }
        self.item = {
            "schema": "kaliv-producer-attestation/v1",
            "release_id": "release-test",
            "gate": "voicerig_physical_acceptance",
            "producer": "test-producer",
            "run_id": "test-run",
            "evidence_sha256": hashlib.sha256(self.evidence).hexdigest(),
            "repository_heads": self.heads,
            "signature": {"algorithm": "Ed25519", "key_id": "test-key", "value": "pending"},
        }
        self.sign()

    def sign(self):
        import base64
        signature = self.private.sign(canonical_signed_payload(self.item))
        self.item["signature"]["value"] = base64.b64encode(signature).decode("ascii")

    def verify(self, **changes):
        kwargs = dict(
            raw=json.dumps(self.item).encode(),
            evidence=self.evidence,
            expected_release_id="release-test",
            expected_gate="voicerig_physical_acceptance",
            expected_repository_heads=self.heads,
            trusted_keys={"voicerig_physical_acceptance": {"test-key": self.public}},
        )
        kwargs.update(changes)
        return verify_producer_attestation(**kwargs)

    def test_real_signature_is_valid_but_never_authorizes(self):
        result = self.verify()
        self.assertTrue(result["signature_valid"])
        self.assertTrue(result["evidence_digest_valid"])
        for field in ("independent_provenance_verified", "human_approval_verified",
                      "release_ready", "production_activation"):
            self.assertFalse(result[field])

    def test_modified_evidence_rejected(self):
        with self.assertRaises(AttestationVerificationError):
            self.verify(evidence=b"altered")

    def test_modified_signed_producer_rejected(self):
        self.item["producer"] = "attacker"
        with self.assertRaises(AttestationVerificationError):
            self.verify()

    def test_wrong_release_id_rejected(self):
        with self.assertRaises(AttestationVerificationError):
            self.verify(expected_release_id="different")

    def test_wrong_repository_head_rejected(self):
        with self.assertRaises(AttestationVerificationError):
            self.verify(expected_repository_heads={**self.heads, "VoiceRig": "f" * 64})

    def test_untrusted_key_rejected(self):
        with self.assertRaises(AttestationVerificationError):
            self.verify(trusted_keys={})

    def test_cross_gate_key_rejected(self):
        with self.assertRaises(AttestationVerificationError):
            self.verify(trusted_keys={"bodyrig_photoreal_likeness": {"test-key": self.public}})

    def test_signature_substitution_rejected(self):
        import base64
        self.item["signature"]["value"] = base64.b64encode(bytes(64)).decode("ascii")
        with self.assertRaises(AttestationVerificationError):
            self.verify()

    def test_reassigned_key_id_rejected(self):
        self.item["signature"]["key_id"] = "other-key"
        with self.assertRaises(AttestationVerificationError):
            self.verify()


if __name__ == "__main__":
    unittest.main()
