from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import kaliv_dev_control.publisher_recovery_authorization as recovery_module
import kaliv_dev_control.publisher_recovery_authorization_strict as strict_module
import kaliv_dev_control.publisher_recovery_primary as primary_module
import kaliv_dev_control.publisher_recovery_receipt_v3 as receipt_module
from kaliv_dev_control.durable_publication import create_once_file
from kaliv_dev_control.publisher_authorization import (
    PUBLISHER_REPLAY_RECOVERY_RECEIPT_V3_SCHEMA,
    PublisherAuthorizationError,
    PublisherReplayLedgerEntryV2,
    PublisherReplayLedgerV2,
    PublisherReplayLedgerV3,
    PublisherReplayRecoveryAuthorizationV1,
    PublisherReplayRecoveryAuthorizationVerifierV1,
    PublisherReplayRecoveryReceiptV3,
    build_publisher_replay_recovery_authorization_payload,
    load_publisher_replay_recovery_receipt_v3,
    write_publisher_replay_recovery_receipt_v3,
)
from test_publisher_authorization_chain_v2 import LEDGER_ID
from test_publisher_recovery_authorization_h6 import (
    AUTH_EXPIRES,
    OBSERVED,
    OPERATOR,
    OPERATOR_KEY_ID,
    OPERATOR_SYSTEM,
    RECOVERED,
    REQUESTED,
    REVIEWER,
    REVIEWER_KEY_ID,
    REVIEWER_SYSTEM,
    _authority,
    _lease,
    _signature,
)


def _authorization_for_action(ledger, lease, *, action: str):
    state = ledger.observe_recovery_state(
        lease=lease,
        observed_at_utc=OBSERVED,
    )
    payload = build_publisher_replay_recovery_authorization_payload(
        state=state,
        action=action,
        requested_at_utc=REQUESTED,
        expires_at_utc=AUTH_EXPIRES,
        operator_actor_id=OPERATOR,
        operator_system_id=OPERATOR_SYSTEM,
        operator_key_id=OPERATOR_KEY_ID,
        reviewer_actor_id=REVIEWER,
        reviewer_system_id=REVIEWER_SYSTEM,
        reviewer_key_id=REVIEWER_KEY_ID,
    )
    operator_private, operator_verifier = _authority(
        private_byte=0x66,
        actor=OPERATOR,
        system=OPERATOR_SYSTEM,
        key_id=OPERATOR_KEY_ID,
        epoch=11,
    )
    reviewer_private, reviewer_verifier = _authority(
        private_byte=0x77,
        actor=REVIEWER,
        system=REVIEWER_SYSTEM,
        key_id=REVIEWER_KEY_ID,
        epoch=12,
    )
    authorization = PublisherReplayRecoveryAuthorizationV1.from_signed_payload(
        unsigned_payload=payload,
        operator_signature=_signature(
            private_key=operator_private,
            payload=payload,
            actor=OPERATOR,
            system=OPERATOR_SYSTEM,
            key_id=OPERATOR_KEY_ID,
            epoch=11,
        ),
        reviewer_signature=_signature(
            private_key=reviewer_private,
            payload=payload,
            actor=REVIEWER,
            system=REVIEWER_SYSTEM,
            key_id=REVIEWER_KEY_ID,
            epoch=12,
        ),
    )
    verifier = PublisherReplayRecoveryAuthorizationVerifierV1(
        operator_verifier=operator_verifier,
        reviewer_verifier=reviewer_verifier,
    )
    return state, authorization, verifier


def _entry(lease):
    return PublisherReplayLedgerEntryV2.from_lease(
        lease=lease,
        ledger_id=LEDGER_ID,
        consumed_at_utc=OBSERVED,
    )


class PublisherReplayRecoveryReceiptV3H7Tests(unittest.TestCase):
    def _recover_case(
        self,
        *,
        action: str,
        expected_before: str,
        expected_after: str,
        expected_verified: bool,
    ) -> PublisherReplayRecoveryReceiptV3:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name).resolve()
        _, lease, _ = _lease()
        ledger = PublisherReplayLedgerV2(root=root, ledger_id=LEDGER_ID)
        final, pending, lock, _ = ledger._paths(lease.invocation_nonce)
        entry = _entry(lease)
        payload = entry.canonical_json().encode("utf-8")

        if action == "finalize_prepared":
            create_once_file(lock, b"reserved")
            create_once_file(pending, payload)
        elif action == "acknowledge_committed":
            create_once_file(final, payload)
            create_once_file(lock, b"reserved")
        else:
            create_once_file(lock, b"reserved")

        state, authorization, verifier = _authorization_for_action(
            ledger,
            lease,
            action=action,
        )
        self.assertEqual(state.state, expected_before)
        receipt = ledger.recover_authenticated(
            lease=lease,
            authorization=authorization,
            authorization_verifier=verifier,
            recovered_at_utc=RECOVERED,
        )
        self.assertIsInstance(receipt, PublisherReplayRecoveryReceiptV3)
        self.assertEqual(receipt.action, action)
        self.assertEqual(receipt.state_before, expected_before)
        self.assertEqual(receipt.state_after, expected_after)
        self.assertIs(receipt.entry_verified, expected_verified)
        self.assertTrue(receipt.authorization_embedded)
        self.assertFalse(receipt.nonce_reusable)
        self.assertEqual(
            receipt.authorization.canonical_json(),
            authorization.canonical_json(),
        )
        self.assertEqual(receipt.authorization_sha256, authorization.sha256)
        self.assertEqual(
            receipt.core_receipt.recovery_authorization_sha256,
            authorization.sha256,
        )

        path = root / f"{lease.invocation_nonce}.v3.recovery.json"
        self.assertTrue(path.is_file())
        loaded = load_publisher_replay_recovery_receipt_v3(path)
        self.assertEqual(loaded.canonical_json(), receipt.canonical_json())
        self.assertEqual(
            path.read_bytes(),
            receipt.canonical_json().encode("utf-8"),
        )
        return receipt

    def test_all_three_authenticated_transitions_emit_receipt_v3(self):
        cases = (
            ("finalize_prepared", "prepared", "committed", True),
            (
                "acknowledge_committed",
                "committed_locked",
                "committed",
                True,
            ),
            (
                "tombstone_uncertain",
                "reserved",
                "tombstoned",
                False,
            ),
        )
        for action, before, after, verified in cases:
            with self.subTest(action=action):
                self._recover_case(
                    action=action,
                    expected_before=before,
                    expected_after=after,
                    expected_verified=verified,
                )

    def test_receipt_v3_rejects_tampering_and_is_create_once(self):
        receipt = self._recover_case(
            action="tombstone_uncertain",
            expected_before="reserved",
            expected_after="tombstoned",
            expected_verified=False,
        )
        with self.assertRaisesRegex(
            PublisherAuthorizationError,
            "bindings are inconsistent",
        ):
            replace(receipt, authorization_sha256="0" * 64)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "recovery-v3.json"
            self.assertEqual(
                write_publisher_replay_recovery_receipt_v3(path, receipt),
                receipt.sha256,
            )
            with self.assertRaises(PublisherAuthorizationError):
                write_publisher_replay_recovery_receipt_v3(path, receipt)

    def test_schema_verifier_and_ledger_are_single_public_contracts(self):
        receipt = self._recover_case(
            action="tombstone_uncertain",
            expected_before="reserved",
            expected_after="tombstoned",
            expected_verified=False,
        )
        schema = json.loads(
            (
                Path(__file__).parents[1]
                / "schemas"
                / "development-publisher-replay-recovery-receipt-v3.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(set(schema["required"]), set(receipt.to_dict()))
        self.assertEqual(set(schema["properties"]), set(receipt.to_dict()))
        self.assertEqual(
            PUBLISHER_REPLAY_RECOVERY_RECEIPT_V3_SCHEMA,
            "kaliv-development-publisher-replay-recovery-receipt/v3",
        )
        self.assertIs(
            primary_module.PublisherReplayRecoveryAuthorizationVerifierV1,
            PublisherReplayRecoveryAuthorizationVerifierV1,
        )
        self.assertIs(
            strict_module.PublisherReplayRecoveryAuthorizationVerifierV1,
            PublisherReplayRecoveryAuthorizationVerifierV1,
        )
        self.assertIs(PublisherReplayLedgerV2, PublisherReplayLedgerV3)
        self.assertIs(PublisherReplayLedgerV3, primary_module.PublisherReplayLedgerV3)
        self.assertTrue(
            issubclass(
                PublisherReplayLedgerV3,
                recovery_module.PublisherReplayLedgerV3,
            )
        )
        self.assertIsNot(
            PublisherReplayLedgerV3.recover_authenticated,
            recovery_module.PublisherReplayLedgerV3.recover_authenticated,
        )
        self.assertIn(
            "recover_authenticated",
            primary_module.PublisherReplayLedgerV3.__dict__,
        )
        self.assertNotIn(
            "class PublisherReplayRecoveryAuthorizationVerifierV1",
            inspect.getsource(strict_module),
        )

    def test_receipt_module_is_passive_and_has_no_authority_surface(self):
        source = inspect.getsource(receipt_module)
        for forbidden in (
            "recover_authenticated =",
            "_h7_receipt_v3_installed",
            "setattr(PublisherReplayLedger",
            "Ed25519PrivateKey",
            "from_private_bytes",
            "load_pem_private_key",
            "import hmac",
            "github_token",
            "api.github.com",
            "import requests",
            "import socket",
            "subprocess",
            "git push",
            "pull_request",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
