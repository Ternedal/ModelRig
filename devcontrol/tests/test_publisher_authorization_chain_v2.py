from __future__ import annotations

import hashlib
import inspect
import json
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import kaliv_dev_control.local_candidate_materialization_h5c as local_h5c_module
import kaliv_dev_control.publisher_authorization as public_authorization
import kaliv_dev_control.publisher_authorization_chain_v2 as chain_module
from kaliv_dev_control.asymmetric_authority import (
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
    asymmetric_authority_key_custody_policy_sha256,
    authority_signing_message,
)
from kaliv_dev_control.draft_pr_readiness import (
    AuthenticatedDraftPrReadinessProposal,
)
from kaliv_dev_control.durable_publication import create_once_file
from kaliv_dev_control.local_candidate_materialization_h5c import (
    AsymmetricLocalCandidateMaterializationGate,
    load_asymmetric_local_candidate_receipt,
    materialize_asymmetric_local_candidate,
    verify_asymmetric_local_candidate,
)
from kaliv_dev_control.publisher_authorization import (
    PublisherAuthorizationError,
    RemoteRepositoryIdentity,
)
from kaliv_dev_control.publisher_authorization_chain_v2 import (
    PUBLISHER_POSTCONDITION_RECEIPT_V2_SCHEMA,
    PUBLISHER_PREFLIGHT_RECEIPT_V2_SCHEMA,
    PUBLISHER_REPLAY_LEDGER_ENTRY_V2_SCHEMA,
    PUBLISHER_REPLAY_RECOVERY_V2_SCHEMA,
    PublisherAuthorizationVerifierV2,
    PublisherPostconditionGateV2,
    PublisherPostconditionReceiptV2,
    PublisherPreflightGateV2,
    PublisherPreflightReceiptV2,
    PublisherReplayLedgerV2,
    PublisherReplayRecoveryReceiptV2,
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
from kaliv_dev_control.publisher_dry_run import (
    HmacPublisherRequestSigner,
    PublisherRequest,
    PublisherRequestVerifier,
    TrustedPublisherKey,
)
from kaliv_dev_control.semantic_review import SemanticReviewRequest
from test_slice10g_command_receipt import make_task
from test_slice10h_semantic_review import (
    DEVELOPER,
    ROOT,
    approve,
    make_receipt,
)
from test_slice10j_publisher_dry_run import (
    NONCE,
    PUBLISHER,
    PUBLISHER_KEY_ID,
    PUBLISHER_SECRET,
    PUBLISHER_SYSTEM,
    make_artifacts,
)
from test_slice10l_local_candidate_materialization import git, trusted_git

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
RECOVERY_AUTHORITY = "a" * 64
RECOVERY_OPERATOR = "publisher.recovery.operator"


def _publisher_request_for_patch(task, staged_patch: bytes):
    tier_a_receipt = make_receipt(task, staged_patch)
    review_request = SemanticReviewRequest.from_evidence(
        task=task,
        developer_actor_id=DEVELOPER,
        staged_patch=staged_patch,
        receipt=tier_a_receipt,
        control_plane_root=ROOT,
    )
    _, signed_verdict, semantic_verifier = approve(review_request)
    readiness = AuthenticatedDraftPrReadinessProposal.from_evidence(
        task=task,
        request=review_request,
        signed_verdict=signed_verdict,
        verifier=semantic_verifier,
        control_plane_root=ROOT,
        base_branch="main",
    )
    request = PublisherRequest.from_readiness(
        readiness=readiness,
        task=task,
        semantic_verifier=semantic_verifier,
        control_plane_root=ROOT,
        publisher_actor_id=PUBLISHER,
        publisher_system_id=PUBLISHER_SYSTEM,
        invocation_nonce=NONCE,
    )
    signed_request = HmacPublisherRequestSigner(
        key_id=PUBLISHER_KEY_ID,
        publisher_actor_id=PUBLISHER,
        secret=PUBLISHER_SECRET,
    ).sign(request)
    publisher_verifier = PublisherRequestVerifier(
        {
            PUBLISHER_KEY_ID: TrustedPublisherKey(
                publisher_actor_id=PUBLISHER,
                secret=PUBLISHER_SECRET,
            )
        }
    )
    return semantic_verifier, request, signed_request, publisher_verifier


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
    verifier = PublisherAuthorizationVerifierV2(
        AsymmetricPublisherAuthorizationVerifier(
            Ed25519AuthorityVerifier(
                {ISSUER_KEY_ID: trusted},
                minimum_keyring_epoch=KEYRING_EPOCH,
            )
        )
    )
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
    def test_complete_v2_chain_roundtrips_and_matches_schemas(self):
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

            self.assertEqual(
                replay.schema,
                PUBLISHER_REPLAY_LEDGER_ENTRY_V2_SCHEMA,
            )
            self.assertEqual(
                preflight.schema,
                PUBLISHER_PREFLIGHT_RECEIPT_V2_SCHEMA,
            )
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
                    self.assertEqual(
                        set(schema["required"]),
                        set(value.to_dict()),
                    )
                    self.assertEqual(
                        set(schema["properties"]),
                        set(value.to_dict()),
                    )
                    path = root / f"artifact-{index}.json"
                    self.assertEqual(writer(path, value), value.sha256)
                    self.assertEqual(
                        loader(path).canonical_json(),
                        value.canonical_json(),
                    )
                    with self.assertRaises(PublisherAuthorizationError):
                        writer(path, value)

    def test_v2_replay_is_irreversible_and_recovery_never_reuses_nonce(self):
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
                _,
            ) = make_chain(root)
            self.assertEqual(
                ledger.load(lease.invocation_nonce).sha256,
                replay.sha256,
            )
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

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (
                task,
                semantic_verifier,
                _,
                request,
                signed_request,
                publisher_verifier,
                _,
            ) = make_artifacts()
            _, lease, verifier = _lease_v2(
                task=task,
                semantic_verifier=semantic_verifier,
                request=request,
                signed_request=signed_request,
                publisher_verifier=publisher_verifier,
            )
            ledger = PublisherReplayLedgerV2(root=root, ledger_id=LEDGER_ID)
            _, _, lock, _ = ledger._paths(lease.invocation_nonce)
            create_once_file(lock, b"reserved")
            recovery = ledger.recover(
                lease=lease,
                action="tombstone_uncertain",
                recovery_authorization_sha256=RECOVERY_AUTHORITY,
                operator_actor_id=RECOVERY_OPERATOR,
                recovered_at_utc=MATERIALIZED,
            )
            self.assertIsInstance(
                recovery,
                PublisherReplayRecoveryReceiptV2,
            )
            self.assertEqual(
                recovery.schema,
                PUBLISHER_REPLAY_RECOVERY_V2_SCHEMA,
            )
            self.assertFalse(recovery.nonce_reusable)
            with self.assertRaises(PublisherAuthorizationError):
                ledger.consume_once(
                    lease=lease,
                    task=task,
                    authorization_verifier=verifier,
                    publisher_verifier=publisher_verifier,
                    semantic_verifier=semantic_verifier,
                    control_plane_root=ROOT,
                    consumed_at_utc=CONSUMED,
                )

    def test_public_supported_surface_excludes_hmac_issuance(self):
        self.assertNotIn(
            "HmacPublisherAuthorizationIssuer",
            public_authorization.__all__,
        )
        self.assertNotIn(
            "TrustedAuthorizationIssuerKey",
            public_authorization.__all__,
        )
        for required in (
            "AsymmetricPublisherAuthorizationLease",
            "AsymmetricPublisherAuthorizationVerifier",
            "PublisherAuthorizationVerifierV2",
            "PublisherReplayLedgerV2",
            "PublisherPreflightReceiptV2",
            "PublisherPostconditionReceiptV2",
        ):
            self.assertIn(required, public_authorization.__all__)

        for module in (chain_module, local_h5c_module):
            source = inspect.getsource(module)
            for forbidden in (
                "Ed25519PrivateKey",
                "private_key",
                "load_pem_private_key",
                "from_private_bytes",
                "import hmac",
                "github_token",
                "api.github.com",
                "import requests",
                "import socket",
            ):
                self.assertNotIn(forbidden, source)

    def test_local_candidate_materialization_embeds_v2_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source"
            source.mkdir()
            git(source, "init", "-q")
            git(source, "config", "user.name", "H5C")
            git(source, "config", "user.email", "h5c@example.invalid")
            (source / "tracked.txt").write_text("base\n", encoding="utf-8")
            git(source, "add", "tracked.txt")
            git(source, "commit", "-q", "-m", "base")
            base_sha = git(source, "rev-parse", "HEAD").decode("ascii").strip()
            (source / "tracked.txt").write_text("staged\n", encoding="utf-8")
            git(source, "add", "tracked.txt")
            staged_patch = git(
                source,
                "diff",
                "--cached",
                "--binary",
                "--full-index",
                "--no-color",
                "--no-ext-diff",
                "--no-textconv",
                "--no-renames",
                "--",
            )
            task = make_task(base_sha)
            (
                semantic_verifier,
                request,
                signed_request,
                publisher_verifier,
            ) = _publisher_request_for_patch(task, staged_patch)
            _, lease, verifier = _lease_v2(
                task=task,
                semantic_verifier=semantic_verifier,
                request=request,
                signed_request=signed_request,
                publisher_verifier=publisher_verifier,
            )
            ledger_root = root / "ledger"
            ledger_root.mkdir()
            replay = PublisherReplayLedgerV2(
                root=ledger_root.resolve(),
                ledger_id=LEDGER_ID,
            ).consume_once(
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
            output = root / "materialized"
            output.mkdir()
            runtime = trusted_git()
            receipt = materialize_asymmetric_local_candidate(
                preflight=preflight,
                task=task,
                authorization_verifier=verifier,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=ROOT,
                source_repository=source.resolve(),
                materialization_root=output.resolve(),
                trusted_git=runtime,
                materialized_at_utc=MATERIALIZED,
            )
            self.assertIsInstance(
                receipt.preflight,
                PublisherPreflightReceiptV2,
            )
            self.assertEqual(receipt.preflight.lease.algorithm, "ed25519")
            transaction = output / receipt.transaction_id
            repository = transaction / receipt.repository_relative_path
            receipt_path = transaction / receipt.receipt_relative_path
            self.assertEqual(
                git(output, f"--git-dir={repository}", "remote"),
                b"",
            )
            loaded = load_asymmetric_local_candidate_receipt(receipt_path)
            self.assertEqual(loaded.canonical_json(), receipt.canonical_json())
            verify_asymmetric_local_candidate(
                receipt=loaded,
                task=task,
                authorization_verifier=verifier,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=ROOT,
                source_repository=source.resolve(),
                materialization_root=output.resolve(),
                trusted_git=runtime,
            )
            self.assertTrue(
                AsymmetricLocalCandidateMaterializationGate.valid(
                    receipt=loaded,
                    task=task,
                    authorization_verifier=verifier,
                    publisher_verifier=publisher_verifier,
                    semantic_verifier=semantic_verifier,
                    control_plane_root=ROOT,
                    source_repository=source.resolve(),
                    materialization_root=output.resolve(),
                    trusted_git=runtime,
                )
            )


if __name__ == "__main__":
    unittest.main()
