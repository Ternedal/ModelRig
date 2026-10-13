"""Real Ed25519 signed-fixture tests for atomic replay reservation."""
import base64
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kaliv_producer_attestation_envelope import canonical_signed_payload
from kaliv_producer_signature_verifier import AttestationVerificationError
from kaliv_durable_attestation_replay_ledger import ReplayLedgerError
from kaliv_verified_attestation_reservation import verify_and_reserve_attestation

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ImportError:
    Ed25519PrivateKey = None


@unittest.skipUnless(Ed25519PrivateKey is not None, "cryptography not installed")
class VerifiedReservationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "ledger.sqlite3"
        private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        self.private = private
        public = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
        self.evidence = b"independent-evidence-fixture"
        self.heads = {"ModelRig": "1" * 64, "BodyRig": "2" * 64,
                      "VisionRig": "3" * 64, "VoiceRig": "4" * 64}
        self.envelope = {
            "schema": "kaliv-producer-attestation/v1",
            "release_id": "release-test",
            "gate": "voicerig_physical_acceptance",
            "producer": "trusted-runner",
            "run_id": "run-1",
            "evidence_sha256": hashlib.sha256(self.evidence).hexdigest(),
            "repository_heads": self.heads,
            "signature": {"algorithm": "Ed25519", "key_id": "key-1", "value": "pending"},
        }
        self.sign()
        self.args = {
            "expected_release_id": "release-test",
            "expected_gate": "voicerig_physical_acceptance",
            "expected_producer": "trusted-runner",
            "expected_run_id": "run-1",
            "expected_repository_heads": self.heads,
            "trusted_keys": {"voicerig_physical_acceptance": {"key-1": public}},
            "coordinator_database": self.path,
        }

    def sign(self):
        signed = self.private.sign(canonical_signed_payload(self.envelope))
        self.envelope["signature"]["value"] = base64.b64encode(signed).decode("ascii")

    def reserve(self, **changes):
        args = {**self.args, **changes}
        return verify_and_reserve_attestation(
            json.dumps(self.envelope).encode(), self.evidence, **args)

    def test_valid_signature_reserves_once_but_never_authorizes(self):
        result = self.reserve()
        self.assertTrue(result["replay_durably_committed"])
        self.assertFalse(result["release_ready"])
        self.assertFalse(result["production_activation"])
        self.assertFalse(result["independent_provenance_verified"])
        with self.assertRaises(ReplayLedgerError):
            self.reserve()

    def test_wrong_producer_does_not_create_ledger(self):
        with self.assertRaises(AttestationVerificationError):
            self.reserve(expected_producer="attacker")
        self.assertFalse(self.path.exists())

    def test_tampered_evidence_does_not_create_ledger(self):
        self.envelope["evidence_sha256"] = "f" * 64
        with self.assertRaises(AttestationVerificationError):
            self.reserve()
        self.assertFalse(self.path.exists())

    def test_untrusted_signer_does_not_create_ledger(self):
        with self.assertRaises(AttestationVerificationError):
            self.reserve(trusted_keys={})
        self.assertFalse(self.path.exists())

    def test_valid_signature_cannot_use_forged_ledger_schema(self):
        import sqlite3
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "CREATE TABLE accepted_attestations "
                "(release_id TEXT, gate TEXT, producer TEXT, run_id TEXT, evidence_sha256 TEXT)"
            )
        with self.assertRaisesRegex(ReplayLedgerError, "schema is not trusted"):
            self.reserve()
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute(
                "SELECT count(*) FROM accepted_attestations"
            ).fetchone()[0], 0)

    def test_wrong_run_does_not_create_ledger(self):
        with self.assertRaises(AttestationVerificationError):
            self.reserve(expected_run_id="other")
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
