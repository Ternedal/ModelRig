"""Negative tests for untrusted producer attestation envelope parsing."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kaliv_producer_attestation_envelope import (
    AttestationEnvelopeError, canonical_signed_payload, parse_envelope,
)


def example():
    return {
        "schema": "kaliv-producer-attestation/v1",
        "release_id": "r1",
        "gate": "voicerig_physical_acceptance",
        "producer": "voice-runner",
        "run_id": "run-1",
        "evidence_sha256": "a" * 64,
        "repository_heads": {
            "ModelRig": "1" * 64, "BodyRig": "2" * 64,
            "VisionRig": "3" * 64, "VoiceRig": "4" * 64,
        },
        "signature": {"algorithm": "Ed25519", "key_id": "external-key", "value": "unverified"},
    }


class EnvelopeTests(unittest.TestCase):
    def encode(self, obj):
        return json.dumps(obj).encode()

    def test_valid_shape_is_not_a_verified_attestation(self):
        result = parse_envelope(self.encode(example()))
        self.assertEqual(result["signature"]["value"], "unverified")
        self.assertNotIn(b"unverified", canonical_signed_payload(result))

    def test_duplicate_top_level_key_rejected(self):
        raw = self.encode(example())
        raw = raw[:-1] + b',"gate":"forged"}'
        with self.assertRaises(AttestationEnvelopeError):
            parse_envelope(raw)

    def test_duplicate_nested_key_rejected(self):
        raw = self.encode(example()).replace(b'"algorithm": "Ed25519"', b'"algorithm": "Ed25519", "algorithm": "none"')
        with self.assertRaises(AttestationEnvelopeError):
            parse_envelope(raw)

    def test_missing_repo_rejected(self):
        item = example()
        del item["repository_heads"]["VoiceRig"]
        with self.assertRaises(AttestationEnvelopeError):
            parse_envelope(self.encode(item))

    def test_extra_authority_flag_rejected(self):
        item = example()
        item["release_ready"] = True
        with self.assertRaises(AttestationEnvelopeError):
            parse_envelope(self.encode(item))

    def test_algorithm_downgrade_rejected(self):
        item = example()
        item["signature"]["algorithm"] = "none"
        with self.assertRaises(AttestationEnvelopeError):
            parse_envelope(self.encode(item))

    def test_invalid_digest_rejected(self):
        item = example()
        item["evidence_sha256"] = "A" * 64
        with self.assertRaises(AttestationEnvelopeError):
            parse_envelope(self.encode(item))

    def test_oversize_rejected(self):
        with self.assertRaises(AttestationEnvelopeError):
            parse_envelope(self.encode(example()), max_bytes=10)

    def test_canonical_payload_stable_under_key_reordering(self):
        item = example()
        reversed_item = dict(reversed(list(item.items())))
        self.assertEqual(canonical_signed_payload(parse_envelope(self.encode(item))),
                         canonical_signed_payload(parse_envelope(self.encode(reversed_item))))


if __name__ == "__main__":
    unittest.main()
