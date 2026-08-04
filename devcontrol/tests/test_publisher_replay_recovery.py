from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import kaliv_dev_control.publisher_replay_h4 as replay_module
from kaliv_dev_control.durable_publication import DurablePublicationError
from kaliv_dev_control.publisher_authorization import (
    HmacPublisherAuthorizationIssuer,
    PUBLISHER_REPLAY_RECOVERY_SCHEMA,
    PublisherAuthorizationError,
    PublisherAuthorizationVerifier,
    PublisherReplayLedger,
    PublisherReplayRecoveryReceipt,
    RemoteRepositoryIdentity,
    TrustedAuthorizationIssuerKey,
)
from test_slice10h_semantic_review import ROOT
from test_slice10j_publisher_dry_run import make_artifacts
from test_slice10k_publisher_authorization import (
    CONSUMED,
    EXPIRES,
    ISSUED,
    ISSUER,
    ISSUER_KEY_ID,
    ISSUER_SECRET,
    ISSUER_SYSTEM,
    LEDGER_ID,
    REPOSITORY_ID,
)

AUTHORIZATION = "b" * 64
OPERATOR = "operator.replay-recovery"
RECOVERED = "2026-08-04T06:49:00Z"


def make_context(directory: Path):
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
    issuer = HmacPublisherAuthorizationIssuer(
        key_id=ISSUER_KEY_ID,
        issuer_actor_id=ISSUER,
        issuer_system_id=ISSUER_SYSTEM,
        secret=ISSUER_SECRET,
    )
    lease = issuer.issue(
        signed_request=signed_request,
        task=task,
        publisher_verifier=publisher_verifier,
        semantic_verifier=semantic_verifier,
        control_plane_root=ROOT,
        remote_repository=remote,
        issued_at_utc=ISSUED,
        expires_at_utc=EXPIRES,
    )
    verifier = PublisherAuthorizationVerifier(
        {
            ISSUER_KEY_ID: TrustedAuthorizationIssuerKey(
                issuer_actor_id=ISSUER,
                secret=ISSUER_SECRET,
            )
        }
    )
    ledger = PublisherReplayLedger(root=directory, ledger_id=LEDGER_ID)
    arguments = {
        "lease": lease,
        "task": task,
        "authorization_verifier": verifier,
        "publisher_verifier": publisher_verifier,
        "semantic_verifier": semantic_verifier,
        "control_plane_root": ROOT,
        "consumed_at_utc": CONSUMED,
    }
    return ledger, lease, arguments


class PublisherReplayRecoveryTests(unittest.TestCase):
    def test_normal_consumption_is_durable_and_create_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            ledger, lease, arguments = make_context(root)
            entry = ledger.consume_once(**arguments)
            self.assertEqual(ledger.load(lease.invocation_nonce), entry)
            self.assertEqual(
                sorted(path.name for path in root.iterdir()),
                [f"{lease.invocation_nonce}.json"],
            )
            with self.assertRaisesRegex(PublisherAuthorizationError, "already been consumed"):
                ledger.consume_once(**arguments)

    def test_prepared_crash_can_only_finalize_the_same_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            ledger, lease, arguments = make_context(root)
            real_create = replay_module.create_once_file
            calls = 0

            def crash_before_final(path, payload, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise DurablePublicationError("simulated crash before final entry")
                return real_create(path, payload, **kwargs)

            with patch.object(replay_module, "create_once_file", side_effect=crash_before_final):
                with self.assertRaisesRegex(PublisherAuthorizationError, "explicit recovery"):
                    ledger.consume_once(**arguments)

            self.assertTrue((root / f".{lease.invocation_nonce}.lock").is_file())
            self.assertTrue((root / f".{lease.invocation_nonce}.pending.json").is_file())
            receipt = ledger.recover(
                lease=lease,
                action="finalize_prepared",
                recovery_authorization_sha256=AUTHORIZATION,
                operator_actor_id=OPERATOR,
                recovered_at_utc=RECOVERED,
            )
            self.assertEqual((receipt.state_before, receipt.state_after), ("prepared", "committed"))
            self.assertTrue(receipt.entry_verified)
            self.assertFalse(receipt.nonce_reusable)
            self.assertEqual(ledger.load(lease.invocation_nonce).lease_sha256, lease.sha256)
            self.assertFalse((root / f".{lease.invocation_nonce}.lock").exists())
            self.assertFalse((root / f".{lease.invocation_nonce}.pending.json").exists())
            self.assertTrue((root / f"{lease.invocation_nonce}.recovery.json").is_file())

    def test_uncertain_reservation_becomes_permanent_tombstone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            ledger, lease, arguments = make_context(root)
            real_create = replay_module.create_once_file
            calls = 0

            def crash_before_pending(path, payload, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise DurablePublicationError("simulated crash before pending entry")
                return real_create(path, payload, **kwargs)

            with patch.object(replay_module, "create_once_file", side_effect=crash_before_pending):
                with self.assertRaisesRegex(PublisherAuthorizationError, "explicit recovery"):
                    ledger.consume_once(**arguments)

            receipt = ledger.recover(
                lease=lease,
                action="tombstone_uncertain",
                recovery_authorization_sha256=AUTHORIZATION,
                operator_actor_id=OPERATOR,
                recovered_at_utc=RECOVERED,
            )
            self.assertEqual((receipt.state_before, receipt.state_after), ("reserved", "tombstoned"))
            self.assertFalse(receipt.nonce_reusable)
            with self.assertRaisesRegex(PublisherAuthorizationError, "consumed"):
                ledger.consume_once(**arguments)
            with self.assertRaisesRegex(PublisherAuthorizationError, "consumed"):
                ledger.load(lease.invocation_nonce)

    def test_invalid_recovery_authority_does_not_change_reserved_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            ledger, lease, arguments = make_context(root)
            real_create = replay_module.create_once_file
            calls = 0

            def crash_before_pending(path, payload, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise DurablePublicationError("simulated crash")
                return real_create(path, payload, **kwargs)

            with patch.object(replay_module, "create_once_file", side_effect=crash_before_pending):
                with self.assertRaises(PublisherAuthorizationError):
                    ledger.consume_once(**arguments)
            lock = root / f".{lease.invocation_nonce}.lock"
            with self.assertRaises(PublisherAuthorizationError):
                ledger.recover(
                    lease=lease,
                    action="tombstone_uncertain",
                    recovery_authorization_sha256="invalid",
                    operator_actor_id=OPERATOR,
                    recovered_at_utc=RECOVERED,
                )
            self.assertTrue(lock.is_file())
            self.assertFalse((root / f"{lease.invocation_nonce}.recovery.json").exists())

    def test_recovery_receipt_matches_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            ledger, lease, _ = make_context(root)
            (root / f".{lease.invocation_nonce}.lock").write_text("reserved", encoding="utf-8")
            receipt = ledger.recover(
                lease=lease,
                action="tombstone_uncertain",
                recovery_authorization_sha256=AUTHORIZATION,
                operator_actor_id=OPERATOR,
                recovered_at_utc=RECOVERED,
            )
            self.assertEqual(receipt.schema, PUBLISHER_REPLAY_RECOVERY_SCHEMA)
            self.assertEqual(
                PublisherReplayRecoveryReceipt.from_mapping(
                    json.loads(receipt.canonical_json())
                ),
                receipt,
            )
            schema = json.loads(
                (
                    ROOT
                    / "devcontrol"
                    / "schemas"
                    / "development-publisher-replay-recovery-receipt-v1.schema.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(set(schema["required"]), set(receipt.to_dict()))


if __name__ == "__main__":
    unittest.main()
