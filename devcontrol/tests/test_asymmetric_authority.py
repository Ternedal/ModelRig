from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "devcontrol" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kaliv_dev_control.asymmetric_authority import (
    ASYMMETRIC_AUTHORITY_ALGORITHM,
    AsymmetricAuthorityError,
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
    authority_signing_message,
)

KEY_ID = "authority-ed25519-2026-a"
ACTOR = "operator.authority"
EPOCH = 7
SIGNED = "2026-08-04T09:00:00Z"
VERIFIED = "2026-08-04T09:01:00Z"
PAYLOAD = b'{"authority":"offline-only","operation":"verify"}'


def make_fixture(*, revoked_at_utc: str | None = None, keyring_epoch: int = EPOCH):
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    trusted = TrustedEd25519AuthorityKey(
        key_id=KEY_ID,
        issuer_actor_id=ACTOR,
        public_key_hex=public_key.hex(),
        valid_from_utc="2026-01-01T00:00:00Z",
        valid_until_utc="2027-01-01T00:00:00Z",
        keyring_epoch=keyring_epoch,
        revoked_at_utc=revoked_at_utc,
    )
    message = authority_signing_message(
        key_id=KEY_ID,
        keyring_epoch=keyring_epoch,
        payload=PAYLOAD,
    )
    signature = DetachedEd25519AuthoritySignature(
        key_id=KEY_ID,
        issuer_actor_id=ACTOR,
        keyring_epoch=keyring_epoch,
        payload_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
        signature_hex=private_key.sign(message).hex(),
        signed_at_utc=SIGNED,
    )
    return trusted, signature


class AsymmetricAuthorityTests(unittest.TestCase):
    def test_valid_detached_signature_uses_public_key_only(self) -> None:
        trusted, signature = make_fixture()
        verifier = Ed25519AuthorityVerifier(
            {KEY_ID: trusted}, minimum_keyring_epoch=EPOCH
        )
        self.assertEqual(
            verifier.verify(payload=PAYLOAD, signature=signature, at_utc=VERIFIED),
            hashlib.sha256(PAYLOAD).hexdigest(),
        )
        self.assertEqual(signature.algorithm, ASYMMETRIC_AUTHORITY_ALGORITHM)

    def test_payload_and_signature_tampering_fail_closed(self) -> None:
        trusted, signature = make_fixture()
        verifier = Ed25519AuthorityVerifier(
            {KEY_ID: trusted}, minimum_keyring_epoch=EPOCH
        )
        with self.assertRaisesRegex(AsymmetricAuthorityError, "payload hash mismatch"):
            verifier.verify(payload=PAYLOAD + b"!", signature=signature, at_utc=VERIFIED)
        tampered = DetachedEd25519AuthoritySignature.from_mapping(
            {**signature.to_dict(), "signature_hex": "00" * 64}
        )
        with self.assertRaisesRegex(AsymmetricAuthorityError, "signature is invalid"):
            verifier.verify(payload=PAYLOAD, signature=tampered, at_utc=VERIFIED)

    def test_revoked_key_is_rejected_even_for_pre_revocation_signature(self) -> None:
        trusted, signature = make_fixture(revoked_at_utc="2026-08-04T09:00:30Z")
        verifier = Ed25519AuthorityVerifier(
            {KEY_ID: trusted}, minimum_keyring_epoch=EPOCH
        )
        with self.assertRaisesRegex(AsymmetricAuthorityError, "key is revoked"):
            verifier.verify(payload=PAYLOAD, signature=signature, at_utc=VERIFIED)

    def test_stale_keyring_epoch_and_future_signature_fail_closed(self) -> None:
        trusted, signature = make_fixture(keyring_epoch=EPOCH - 1)
        verifier = Ed25519AuthorityVerifier(
            {KEY_ID: trusted}, minimum_keyring_epoch=EPOCH
        )
        with self.assertRaisesRegex(AsymmetricAuthorityError, "epoch is stale"):
            verifier.verify(payload=PAYLOAD, signature=signature, at_utc=VERIFIED)

        trusted, signature = make_fixture()
        future = DetachedEd25519AuthoritySignature.from_mapping(
            {**signature.to_dict(), "signed_at_utc": "2026-08-04T09:02:00Z"}
        )
        verifier = Ed25519AuthorityVerifier(
            {KEY_ID: trusted}, minimum_keyring_epoch=EPOCH
        )
        with self.assertRaisesRegex(AsymmetricAuthorityError, "from the future"):
            verifier.verify(payload=PAYLOAD, signature=future, at_utc=VERIFIED)

    def test_evidence_roundtrips_canonically(self) -> None:
        trusted, signature = make_fixture()
        self.assertEqual(
            TrustedEd25519AuthorityKey.from_mapping(
                json.loads(trusted.canonical_json())
            ),
            trusted,
        )
        self.assertEqual(
            DetachedEd25519AuthoritySignature.from_mapping(
                json.loads(signature.canonical_json())
            ),
            signature,
        )

    def test_runtime_module_contains_no_private_key_or_signer_boundary(self) -> None:
        source = (
            SRC / "kaliv_dev_control" / "asymmetric_authority.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("Ed25519PrivateKey", source)
        self.assertNotIn("class Ed25519AuthorityIssuer", source)
        self.assertNotIn("private_key", source)
        self.assertNotIn("load_private", source)


if __name__ == "__main__":
    unittest.main()
