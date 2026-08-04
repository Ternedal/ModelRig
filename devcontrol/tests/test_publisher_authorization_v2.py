from __future__ import annotations

import hashlib
import inspect
import json
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import kaliv_dev_control.publisher_authorization_v2 as authorization_v2_module
from kaliv_dev_control.asymmetric_authority import (
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
    authority_signing_message,
)
from kaliv_dev_control.publisher_authorization import (
    PublisherAuthorizationError,
    RemoteRepositoryIdentity,
)
from kaliv_dev_control.publisher_authorization_v2 import (
    AsymmetricPublisherAuthorizationLease,
    AsymmetricPublisherAuthorizationVerifier,
    PUBLISHER_AUTHORIZATION_LEASE_V2_SCHEMA,
    build_asymmetric_publisher_authorization_payload,
)
from test_slice10h_semantic_review import ROOT
from test_slice10j_publisher_dry_run import make_artifacts

ISSUER = "publisher.authorization.issuer"
ISSUER_SYSTEM = "offline-authorization-service-v2"
ISSUER_KEY_ID = "publisher-authorization-ed25519-2026"
REPOSITORY_ID = "900000001"
ISSUED = "2026-08-04T06:45:00Z"
VERIFIED = "2026-08-04T06:46:00Z"
EXPIRES = "2026-08-04T06:55:00Z"
KEY_VALID_FROM = "2026-08-01T00:00:00Z"
KEY_VALID_UNTIL = "2027-08-01T00:00:00Z"
KEYRING_EPOCH = 7


def make_v2_authorization():
    (
        task,
        semantic_verifier,
        _,
        request,
        signed_request,
        publisher_verifier,
        _,
    ) = make_artifacts()
    remote = RemoteRepositoryIdentity.github(
        repository=request.repository,
        repository_id=REPOSITORY_ID,
    )
    payload = build_asymmetric_publisher_authorization_payload(
        signed_request=signed_request,
        task=task,
        publisher_verifier=publisher_verifier,
        semantic_verifier=semantic_verifier,
        control_plane_root=ROOT,
        remote_repository=remote,
        issued_at_utc=ISSUED,
        expires_at_utc=EXPIRES,
        issuer_actor_id=ISSUER,
        issuer_system_id=ISSUER_SYSTEM,
        issuer_key_id=ISSUER_KEY_ID,
    )
    private_key = Ed25519PrivateKey.generate()
    public_key_hex = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    signature = DetachedEd25519AuthoritySignature(
        key_id=ISSUER_KEY_ID,
        issuer_actor_id=ISSUER,
        keyring_epoch=KEYRING_EPOCH,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        signature_hex=private_key.sign(
            authority_signing_message(
                key_id=ISSUER_KEY_ID,
                keyring_epoch=KEYRING_EPOCH,
                payload=payload,
            )
        ).hex(),
        signed_at_utc=ISSUED,
    )
    lease = AsymmetricPublisherAuthorizationLease.from_signed_payload(
        unsigned_payload=payload,
        signature=signature,
    )
    trusted = TrustedEd25519AuthorityKey(
        key_id=ISSUER_KEY_ID,
        issuer_actor_id=ISSUER,
        public_key_hex=public_key_hex,
        valid_from_utc=KEY_VALID_FROM,
        valid_until_utc=KEY_VALID_UNTIL,
        keyring_epoch=KEYRING_EPOCH,
    )
    verifier = AsymmetricPublisherAuthorizationVerifier(
        Ed25519AuthorityVerifier(
            {ISSUER_KEY_ID: trusted},
            minimum_keyring_epoch=KEYRING_EPOCH,
        )
    )
    return (
        task,
        semantic_verifier,
        request,
        signed_request,
        publisher_verifier,
        remote,
        payload,
        lease,
        trusted,
        verifier,
    )


class AsymmetricPublisherAuthorizationV2Tests(unittest.TestCase):
    def test_v2_lease_verifies_with_public_key_only(self) -> None:
        (
            task,
            semantic_verifier,
            request,
            signed_request,
            publisher_verifier,
            remote,
            payload,
            lease,
            trusted,
            verifier,
        ) = make_v2_authorization()

        self.assertEqual(lease.schema, PUBLISHER_AUTHORIZATION_LEASE_V2_SCHEMA)
        self.assertEqual(lease.algorithm, "ed25519")
        self.assertEqual(lease.signed_request.sha256, signed_request.sha256)
        self.assertEqual(lease.request_sha256, request.sha256)
        self.assertEqual(lease.remote_repository.sha256, remote.sha256)
        self.assertEqual(
            lease.signature.payload_sha256, hashlib.sha256(payload).hexdigest()
        )
        self.assertEqual(
            trusted.public_key_hex, trusted.to_dict()["public_key_hex"]
        )
        self.assertEqual(
            verifier.verify(
                lease=lease,
                task=task,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=ROOT,
                at_utc=VERIFIED,
            ).sha256,
            lease.sha256,
        )
        self.assertEqual(
            AsymmetricPublisherAuthorizationLease.from_mapping(
                json.loads(lease.canonical_json())
            ),
            lease,
        )

    def test_tampering_wrong_key_revocation_and_epoch_fail_closed(self) -> None:
        (
            task,
            semantic_verifier,
            _,
            _,
            publisher_verifier,
            _,
            payload,
            lease,
            trusted,
            verifier,
        ) = make_v2_authorization()

        changed = bytearray(payload)
        changed[-1] ^= 1
        with self.assertRaises(PublisherAuthorizationError):
            AsymmetricPublisherAuthorizationLease.from_signed_payload(
                unsigned_payload=bytes(changed),
                signature=lease.signature,
            )

        wrong_private = Ed25519PrivateKey.generate()
        wrong_public = wrong_private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        ).hex()
        wrong_verifier = AsymmetricPublisherAuthorizationVerifier(
            Ed25519AuthorityVerifier(
                {
                    ISSUER_KEY_ID: TrustedEd25519AuthorityKey(
                        key_id=ISSUER_KEY_ID,
                        issuer_actor_id=ISSUER,
                        public_key_hex=wrong_public,
                        valid_from_utc=KEY_VALID_FROM,
                        valid_until_utc=KEY_VALID_UNTIL,
                        keyring_epoch=KEYRING_EPOCH,
                    )
                },
                minimum_keyring_epoch=KEYRING_EPOCH,
            )
        )
        with self.assertRaises(Exception):
            wrong_verifier.verify(
                lease=lease,
                task=task,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=ROOT,
                at_utc=VERIFIED,
            )

        revoked_verifier = AsymmetricPublisherAuthorizationVerifier(
            Ed25519AuthorityVerifier(
                {
                    ISSUER_KEY_ID: TrustedEd25519AuthorityKey(
                        key_id=trusted.key_id,
                        issuer_actor_id=trusted.issuer_actor_id,
                        public_key_hex=trusted.public_key_hex,
                        valid_from_utc=trusted.valid_from_utc,
                        valid_until_utc=trusted.valid_until_utc,
                        keyring_epoch=trusted.keyring_epoch,
                        revoked_at_utc=VERIFIED,
                    )
                },
                minimum_keyring_epoch=KEYRING_EPOCH,
            )
        )
        with self.assertRaises(Exception):
            revoked_verifier.verify(
                lease=lease,
                task=task,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=ROOT,
                at_utc=VERIFIED,
            )

        stale_verifier = AsymmetricPublisherAuthorizationVerifier(
            Ed25519AuthorityVerifier(
                {ISSUER_KEY_ID: trusted},
                minimum_keyring_epoch=KEYRING_EPOCH + 1,
            )
        )
        with self.assertRaises(Exception):
            stale_verifier.verify(
                lease=lease,
                task=task,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=ROOT,
                at_utc=VERIFIED,
            )

        with self.assertRaisesRegex(
            PublisherAuthorizationError, "not currently valid"
        ):
            verifier.verify(
                lease=lease,
                task=task,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=ROOT,
                at_utc=EXPIRES,
            )

    def test_schema_and_no_private_signing_surface(self) -> None:
        *_, lease, _, _ = make_v2_authorization()
        schema = json.loads(
            (
                ROOT
                / "devcontrol"
                / "schemas"
                / "development-publisher-authorization-lease-v2.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(set(schema["required"]), set(lease.to_dict()))
        self.assertEqual(set(schema["properties"]), set(lease.to_dict()))
        self.assertEqual(
            set(schema["properties"]["signature"]["required"]),
            set(lease.signature.to_dict()),
        )
        source = inspect.getsource(authorization_v2_module)
        for forbidden in (
            "Ed25519PrivateKey",
            "private_key",
            "load_pem_private_key",
            "from_private_bytes",
            "def sign",
            "class Signer",
            "import hmac",
        ):
            self.assertNotIn(forbidden, source)
        parameters = set(
            inspect.signature(
                build_asymmetric_publisher_authorization_payload
            ).parameters
        )
        for forbidden in (
            "secret",
            "private_key",
            "token",
            "credential",
            "github",
            "transport",
            "remote_client",
        ):
            self.assertNotIn(forbidden, parameters)


if __name__ == "__main__":
    unittest.main()
