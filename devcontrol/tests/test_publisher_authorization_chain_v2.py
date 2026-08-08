from __future__ import annotations

import hashlib
import inspect
import json
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import kaliv_dev_control.publisher_authorization as public_authorization
import kaliv_dev_control.publisher_authorization_chain_v2 as chain_module
from kaliv_dev_control.asymmetric_authority import (
    DetachedEd25519AuthoritySignature,
    TrustedEd25519AuthorityKey,
    asymmetric_authority_key_custody_policy_sha256,
    authority_signing_message,
)
from kaliv_dev_control.publisher_authorization import (
    PublisherAuthorizationError,
    RemoteRepositoryIdentity,
)
from kaliv_dev_control.publisher_authorization_chain_v2 import (
    PUBLISHER_POSTCONDITION_RECEIPT_V2_SCHEMA,
    PUBLISHER_PREFLIGHT_RECEIPT_V2_SCHEMA,
    PUBLISHER_REPLAY_LEDGER_ENTRY_V2_SCHEMA,
    PublisherAuthorizationVerifierV2,
    PublisherPostconditionGateV2,
    PublisherPostconditionReceiptV2,
    PublisherPreflightGateV2,
    PublisherPreflightReceiptV2,
    PublisherReplayLedgerV2,
    load_publisher_postcondition_receipt_v2,
    load_publisher_preflight_receipt_v2,
    load_publisher_replay_ledger_entry_v2,
    write_publisher_postcondition_receipt_v2,
    write_publisher_preflight_receipt_v2,
    write_publisher_replay_ledger_entry_v2,
)
from kaliv_dev_control.publisher_authorization_v2 import (
    AsymmetricPublisherAuthorizationLease,
    AsymmetricPublisherAuthorizationVerifier,
    build_asymmetric_publisher_authorization_payload,
)
from kaliv_dev_control.publisher_keyring_state import (
    PublisherExternalKeyringState,
    RollbackSafeEd25519AuthorityVerifier,
)
from test_slice10h_semantic_review import ROOT
from test_slice10j_publisher_dry_run import (
    PUBLISHER,
    make_artifacts,
)

ISSUER = "publisher.authorization.issuer"
ISSUER_SYSTEM = "offline-authorization-service-v2"
ISSUER_KEY_ID = "publisher-authorization-ed25519-h5c"
REPOSITORY_ID = "900000001"
LEDGER_ID = "publisher-replay-ledger-h5c"
ISSUED = "2026-08-04T06:45:00Z"
CONSUMED = "2026-08-04T06:46:00Z"
CHECKED = "2026-08-04T06:47:00Z"
MATERIALIZED = "2026-08-04T06:48:00Z"
EXPIRES = "2026-08-04T06:55:00Z"
KEY_VALID_FROM = "2026-08-01T00:00:00Z"
KEY_VALID_UNTIL = "2027-08-01T00:00:00Z"
KEYRING_EPOCH = 8


class StaticExternalKeyringProvider:
    def __init__(self) -> None:
        self.reads = 0

    def read_current(self) -> PublisherExternalKeyringState:
        self.reads += 1
        return PublisherExternalKeyringState(
            authority_domain="publisher-authorization",
            generation=11,
            minimum_keyring_epoch=KEYRING_EPOCH,
            revoked_key_ids=(),
            observed_at_utc="2026-08-04T06:44:00Z",
        )


def _lease_v2(
    *,
    task,
    semantic_verifier,
    request,
    signed_request,
    publisher_verifier,
):
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
    private_key = Ed25519PrivateKey.from_private_bytes(b"\x55" * 32)
    public_key_hex = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    custody_hash = asymmetric_authority_key_custody_policy_sha256()
    signature = DetachedEd25519AuthoritySignature(
        key_id=ISSUER_KEY_ID,
        issuer_actor_id=ISSUER,
        issuer_system_id=ISSUER_SYSTEM,
        keyring_epoch=KEYRING_EPOCH,
        custody_policy_sha256=custody_hash,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        signature_hex=private_key.sign(
            authority_signing_message(
                key_id=ISSUER_KEY_ID,
                issuer_actor_id=ISSUER,
                issuer_system_id=ISSUER_SYSTEM,
                keyring_epoch=KEYRING_EPOCH,
                custody_policy_sha256=custody_hash,
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
        issuer_system_id=ISSUER_SYSTEM,
        public_key_hex=public_key_hex,
        valid_from_utc=KEY_VALID_FROM,
        valid_until_utc=KEY_VALID_UNTIL,
        keyring_epoch=KEYRING_EPOCH,
        custody_policy_sha256=custody_hash,
    )
    external_provider = StaticExternalKeyringProvider()
    verifier = PublisherAuthorizationVerifierV2(
        AsymmetricPublisherAuthorizationVerifier(
            RollbackSafeEd25519AuthorityVerifier(
                {ISSUER_KEY_ID: trusted},
                authority_domain="publisher-authorization",
                state_provider=external_provider,
            )
        )
    )
    verifier.external_state_provider = external_provider
    return remote, lease, verifier


def make_chain(root: Path):
    (
        task,
        semantic_verifier,
        _,
        request,
        signed_request,
        publisher_verifier,
        _,
    ) = make_artifacts()
    remote, lease, verifier = _lease_v2(
        task=task,
        semantic_verifier=semantic_verifier,
        request=request,
        signed_request=signed_request,
        publisher_verifier=publisher_verifier,
    )
    ledger = PublisherReplayLedgerV2(root=root, ledger_id=LEDGER_ID)
    replay = ledger.consume_once(
        lease=lease,
        task=task,
        authorization_verifier=verifier,
        publisher_verifier=publisher_verifier,
        semantic_verifier=semantic_verifier,
        control_plane_root=ROOT,
        consumed_at_utc=CONSUMED,
    )
    preflight = PublisherPreflightReceiptV2.from_consumed_lease(
        lease=lease,
        replay_entry=replay,
        task=task,
        authorization_verifier=verifier,
        publisher_verifier=publisher_verifier,
        semantic_verifier=semantic_verifier,
        control_plane_root=ROOT,
        checked_at_utc=CHECKED,
    )
    postcondition = PublisherPostconditionReceiptV2.from_preflight_without_execution(
        preflight=preflight,
        observed_at_utc=MATERIALIZED,
    )
    return (
        task,
        semantic_verifier,
        request,
        signed_request,
        publisher_verifier,
        remote,
        lease,
        verifier,
        ledger,
        replay,
        preflight,
        postcondition,
    )


class PublisherAuthorizationChainV2Tests(unittest.TestCase):
    def test_complete_v2_chain_roundtrips_and_matches_schemas(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (
                task,
                semantic_verifier,
                _,
                _,
                publisher_verifier,
                _,
                lease,
                verifier,
                _,
                replay,
                preflight,
                postcondition,
            ) = make_chain(root)
            self.assertEqual(replay.schema, PUBLISHER_REPLAY_LEDGER_ENTRY_V2_SCHEMA)
            self.assertEqual(preflight.schema, PUBLISHER_PREFLIGHT_RECEIPT_V2_SCHEMA)
            self.assertEqual(
                postcondition.schema,
                PUBLISHER_POSTCONDITION_RECEIPT_V2_SCHEMA,
            )
            self.assertEqual(replay.lease.algorithm, "ed25519")
            self.assertEqual(preflight.lease_sha256, lease.sha256)
            self.assertTrue(
                PublisherPreflightGateV2.valid(
                    receipt=preflight,
                    task=task,
                    authorization_verifier=verifier,
                    publisher_verifier=publisher_verifier,
                    semantic_verifier=semantic_verifier,
                    control_plane_root=ROOT,
                )
            )
            self.assertTrue(
                PublisherPostconditionGateV2.valid(
                    receipt=postcondition,
                    task=task,
                    authorization_verifier=verifier,
                    publisher_verifier=publisher_verifier,
                    semantic_verifier=semantic_verifier,
                    control_plane_root=ROOT,
                )
            )
            self.assertGreaterEqual(verifier.external_state_provider.reads, 3)

            values = (
                (
                    replay,
                    "development-publisher-replay-ledger-entry-v2.schema.json",
                    write_publisher_replay_ledger_entry_v2,
                    load_publisher_replay_ledger_entry_v2,
                ),
                (
                    preflight,
                    "development-publisher-preflight-receipt-v2.schema.json",
                    write_publisher_preflight_receipt_v2,
                    load_publisher_preflight_receipt_v2,
                ),
                (
                    postcondition,
                    "development-publisher-postcondition-receipt-v2.schema.json",
                    write_publisher_postcondition_receipt_v2,
                    load_publisher_postcondition_receipt_v2,
                ),
            )
            for index, (value, schema_name, writer, loader) in enumerate(values):
                with self.subTest(schema=schema_name):
                    schema = json.loads(
                        (
                            ROOT / "devcontrol" / "schemas" / schema_name
                        ).read_text(encoding="utf-8")
                    )
                    self.assertEqual(set(schema["required"]), set(value.to_dict()))
                    self.assertEqual(set(schema["properties"]), set(value.to_dict()))
                    path = root / f"artifact-{index}.json"
                    self.assertEqual(writer(path, value), value.sha256)
                    self.assertEqual(
                        loader(path).canonical_json(),
                        value.canonical_json(),
                    )
                    with self.assertRaises(PublisherAuthorizationError):
                        writer(path, value)

    def test_v2_replay_is_one_time_and_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (
                task,
                semantic_verifier,
                _,
                _,
                publisher_verifier,
                _,
                lease,
                verifier,
                ledger,
                replay,
                _,
                postcondition,
            ) = make_chain(root)
            self.assertEqual(ledger.load(lease.invocation_nonce).sha256, replay.sha256)
            with self.assertRaisesRegex(
                PublisherAuthorizationError,
                "already been consumed",
            ):
                ledger.consume_once(
                    lease=lease,
                    task=task,
                    authorization_verifier=verifier,
                    publisher_verifier=publisher_verifier,
                    semantic_verifier=semantic_verifier,
                    control_plane_root=ROOT,
                    consumed_at_utc=CONSUMED,
                )
            self.assertEqual(postcondition.execution_state, "not_executed")
            self.assertFalse(postcondition.repository_write_performed)
            self.assertFalse(postcondition.network_write_performed)
            self.assertFalse(postcondition.pull_request_created)
            self.assertFalse(postcondition.merged)

    def test_modules_expose_no_writer_or_signer_capability(self) -> None:
        source = inspect.getsource(chain_module) + inspect.getsource(
            public_authorization
        )
        for token in (
            "Ed25519PrivateKey",
            "import hmac",
            "requests.",
            "urllib",
            "subprocess",
            "create_pull_request",
            "merge_pull_request",
        ):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
