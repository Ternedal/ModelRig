from __future__ import annotations

import hashlib
import inspect
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kaliv_dev_control.asymmetric_authority import (
    AsymmetricAuthorityError,
    DetachedEd25519AuthoritySignature,
    TrustedEd25519AuthorityKey,
    asymmetric_authority_key_custody_policy_sha256,
    authority_signing_message,
)
from kaliv_dev_control.publisher_keyring_state import (
    PublisherExternalKeyringState,
    RollbackSafeEd25519AuthorityVerifier,
)

KEY_ID = "publisher-key-001"
ACTOR = "publisher-authority@example.invalid"
SYSTEM = "publisher-authority-hsm"
POLICY = asymmetric_authority_key_custody_policy_sha256()
PAYLOAD = b"exact publisher authorization payload"
AT = "2026-08-08T06:00:00Z"


class MutableProvider:
    def __init__(self, state: PublisherExternalKeyringState) -> None:
        self.state = state
        self.reads = 0

    def read_current(self) -> PublisherExternalKeyringState:
        self.reads += 1
        return self.state


def state(
    generation: int,
    *,
    minimum_epoch: int = 3,
    revoked: tuple[str, ...] = (),
    observed: str = "2026-08-08T05:59:00Z",
) -> PublisherExternalKeyringState:
    return PublisherExternalKeyringState(
        authority_domain="publisher-authorization",
        generation=generation,
        minimum_keyring_epoch=minimum_epoch,
        revoked_key_ids=revoked,
        observed_at_utc=observed,
    )


def fixture() -> tuple[
    RollbackSafeEd25519AuthorityVerifier,
    MutableProvider,
    DetachedEd25519AuthoritySignature,
]:
    private = Ed25519PrivateKey.generate()
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    trusted = TrustedEd25519AuthorityKey(
        key_id=KEY_ID,
        issuer_actor_id=ACTOR,
        issuer_system_id=SYSTEM,
        public_key_hex=public_hex,
        valid_from_utc="2026-01-01T00:00:00Z",
        valid_until_utc="2027-01-01T00:00:00Z",
        keyring_epoch=3,
        custody_policy_sha256=POLICY,
    )
    message = authority_signing_message(
        key_id=KEY_ID,
        issuer_actor_id=ACTOR,
        issuer_system_id=SYSTEM,
        keyring_epoch=3,
        custody_policy_sha256=POLICY,
        payload=PAYLOAD,
    )
    signature = DetachedEd25519AuthoritySignature(
        key_id=KEY_ID,
        issuer_actor_id=ACTOR,
        issuer_system_id=SYSTEM,
        keyring_epoch=3,
        custody_policy_sha256=POLICY,
        payload_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
        signature_hex=private.sign(message).hex(),
        signed_at_utc="2026-08-08T05:58:00Z",
    )
    provider = MutableProvider(state(1))
    verifier = RollbackSafeEd25519AuthorityVerifier(
        {KEY_ID: trusted},
        authority_domain="publisher-authorization",
        state_provider=provider,
    )
    return verifier, provider, signature


class PublisherKeyringStateTests(unittest.TestCase):
    def test_provider_is_read_for_every_verification(self) -> None:
        verifier, provider, signature = fixture()
        verifier.verify(payload=PAYLOAD, signature=signature, at_utc=AT)
        verifier.verify(payload=PAYLOAD, signature=signature, at_utc=AT)
        self.assertEqual(provider.reads, 2)

    def test_generation_rollback_fails_closed(self) -> None:
        verifier, provider, signature = fixture()
        provider.state = state(2)
        verifier.verify(payload=PAYLOAD, signature=signature, at_utc=AT)
        provider.state = state(1)
        with self.assertRaisesRegex(AsymmetricAuthorityError, "rolled back"):
            verifier.verify(payload=PAYLOAD, signature=signature, at_utc=AT)

    def test_same_generation_drift_fails_closed(self) -> None:
        verifier, provider, signature = fixture()
        verifier.verify(payload=PAYLOAD, signature=signature, at_utc=AT)
        provider.state = state(1, observed="2026-08-08T05:59:01Z")
        with self.assertRaisesRegex(AsymmetricAuthorityError, "drifted"):
            verifier.verify(payload=PAYLOAD, signature=signature, at_utc=AT)

    def test_external_minimum_epoch_fails_closed(self) -> None:
        verifier, provider, signature = fixture()
        provider.state = state(2, minimum_epoch=4)
        with self.assertRaisesRegex(AsymmetricAuthorityError, "minimum"):
            verifier.verify(payload=PAYLOAD, signature=signature, at_utc=AT)

    def test_external_revocation_fails_closed(self) -> None:
        verifier, provider, signature = fixture()
        provider.state = state(2, revoked=(KEY_ID,))
        with self.assertRaisesRegex(AsymmetricAuthorityError, "externally revoked"):
            verifier.verify(payload=PAYLOAD, signature=signature, at_utc=AT)

    def test_module_has_no_local_anchor_or_signing_capability(self) -> None:
        import kaliv_dev_control.publisher_keyring_state as module

        source = inspect.getsource(module)
        for forbidden in (
            "Path(",
            "open(",
            "read_text",
            "read_bytes",
            "requests.",
            "urllib",
            "subprocess",
            "Ed25519PrivateKey",
            ".sign(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
