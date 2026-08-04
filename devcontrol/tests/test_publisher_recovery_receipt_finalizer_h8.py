from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import kaliv_dev_control.publisher_recovery_primary as primary_module
import kaliv_dev_control.publisher_recovery_receipt_finalizer as finalizer_module
from kaliv_dev_control.durable_publication import (
    DurablePublicationError,
    create_once_file,
)
from kaliv_dev_control.publisher_authorization import (
    PublisherAuthorizationError,
    PublisherReplayLedgerV2,
    PublisherReplayRecoveryReceiptV3,
    finalize_missing_publisher_replay_recovery_receipt_v3,
    load_publisher_replay_recovery_authorization_v1,
    load_publisher_replay_recovery_receipt_v2,
)
from test_publisher_authorization_chain_v2 import LEDGER_ID
from test_publisher_recovery_authorization_h6 import (
    RECOVERED,
    _lease,
)
from test_publisher_recovery_receipt_v3_h7 import (
    _authorization_for_action,
    _entry,
)

FINALIZED_AFTER_EXPIRY = "2026-08-05T12:00:00Z"


class PublisherRecoveryReceiptFinalizerH8Tests(unittest.TestCase):
    def _crash_after_core(
        self,
        *,
        action: str,
    ):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name).resolve()
        _, lease, _ = _lease()
        ledger = PublisherReplayLedgerV2(root=root, ledger_id=LEDGER_ID)
        final, pending, reservation, _ = ledger._paths(
            lease.invocation_nonce
        )
        entry = _entry(lease)
        payload = entry.canonical_json().encode("utf-8")

        if action == "finalize_prepared":
            create_once_file(reservation, b"reserved")
            create_once_file(pending, payload)
        elif action == "acknowledge_committed":
            create_once_file(final, payload)
            create_once_file(reservation, b"reserved")
        elif action == "tombstone_uncertain":
            create_once_file(reservation, b"reserved")
        else:
            raise AssertionError(f"unsupported test action: {action}")

        _, authorization, verifier = _authorization_for_action(
            ledger,
            lease,
            action=action,
        )
        with patch.object(
            primary_module,
            "create_once_file",
            side_effect=DurablePublicationError("simulated v3 crash"),
        ):
            with self.assertRaisesRegex(
                PublisherAuthorizationError,
                "receipt v3 was not durably published",
            ):
                ledger.recover_authenticated(
                    lease=lease,
                    authorization=authorization,
                    authorization_verifier=verifier,
                    recovered_at_utc=RECOVERED,
                )

        authorization_path = (
            root
            / f"{lease.invocation_nonce}.v2.recovery-authorization.json"
        )
        core_path = root / f"{lease.invocation_nonce}.v2.recovery.json"
        v3_path = root / f"{lease.invocation_nonce}.v3.recovery.json"
        self.assertTrue(authorization_path.is_file())
        self.assertTrue(core_path.is_file())
        self.assertFalse(v3_path.exists())
        return (
            root,
            ledger,
            lease,
            authorization,
            verifier,
            authorization_path,
            core_path,
            v3_path,
        )

    @staticmethod
    def _durable_fingerprint(state):
        data = state.to_dict()
        data.pop("observed_at_utc")
        return data

    def test_finalizes_all_three_crash_states_without_recovery_replay(self):
        cases = (
            ("finalize_prepared", "committed", True),
            ("acknowledge_committed", "committed", True),
            ("tombstone_uncertain", "tombstoned", False),
        )
        for action, state_after, entry_verified in cases:
            with self.subTest(action=action):
                (
                    _,
                    ledger,
                    lease,
                    authorization,
                    verifier,
                    authorization_path,
                    core_path,
                    v3_path,
                ) = self._crash_after_core(action=action)
                before = ledger.observe_recovery_state(
                    lease=lease,
                    observed_at_utc=FINALIZED_AFTER_EXPIRY,
                )
                durable_authorization = (
                    load_publisher_replay_recovery_authorization_v1(
                        authorization_path
                    )
                )
                core_receipt = load_publisher_replay_recovery_receipt_v2(
                    core_path
                )

                receipt = (
                    finalize_missing_publisher_replay_recovery_receipt_v3(
                        ledger=ledger,
                        lease=lease,
                        authorization_verifier=verifier,
                        finalized_at_utc=FINALIZED_AFTER_EXPIRY,
                    )
                )
                self.assertIsInstance(
                    receipt,
                    PublisherReplayRecoveryReceiptV3,
                )
                self.assertEqual(receipt.action, action)
                self.assertEqual(receipt.state_after, state_after)
                self.assertIs(receipt.entry_verified, entry_verified)
                self.assertFalse(receipt.nonce_reusable)
                self.assertEqual(
                    receipt.authorization.canonical_json(),
                    authorization.canonical_json(),
                )
                self.assertEqual(
                    receipt.authorization.canonical_json(),
                    durable_authorization.canonical_json(),
                )
                self.assertEqual(
                    receipt.core_receipt.canonical_json(),
                    core_receipt.canonical_json(),
                )
                self.assertEqual(
                    v3_path.read_bytes(),
                    receipt.canonical_json().encode("utf-8"),
                )

                after = ledger.observe_recovery_state(
                    lease=lease,
                    observed_at_utc=FINALIZED_AFTER_EXPIRY,
                )
                self.assertEqual(
                    self._durable_fingerprint(after),
                    self._durable_fingerprint(before),
                )

    def test_finalizer_refuses_existing_receipt_and_state_drift(self):
        (
            _,
            ledger,
            lease,
            _,
            verifier,
            _,
            _,
            _,
        ) = self._crash_after_core(action="acknowledge_committed")
        finalize_missing_publisher_replay_recovery_receipt_v3(
            ledger=ledger,
            lease=lease,
            authorization_verifier=verifier,
            finalized_at_utc=FINALIZED_AFTER_EXPIRY,
        )
        with self.assertRaisesRegex(
            PublisherAuthorizationError,
            "already exists",
        ):
            finalize_missing_publisher_replay_recovery_receipt_v3(
                ledger=ledger,
                lease=lease,
                authorization_verifier=verifier,
                finalized_at_utc=FINALIZED_AFTER_EXPIRY,
            )

        (
            _,
            drift_ledger,
            drift_lease,
            _,
            drift_verifier,
            _,
            _,
            drift_v3_path,
        ) = self._crash_after_core(action="tombstone_uncertain")
        _, _, reservation, _ = drift_ledger._paths(
            drift_lease.invocation_nonce
        )
        create_once_file(reservation, b"post-recovery drift")
        with self.assertRaisesRegex(
            PublisherAuthorizationError,
            "durable post-state is inconsistent",
        ):
            finalize_missing_publisher_replay_recovery_receipt_v3(
                ledger=drift_ledger,
                lease=drift_lease,
                authorization_verifier=drift_verifier,
                finalized_at_utc=FINALIZED_AFTER_EXPIRY,
            )
        self.assertFalse(drift_v3_path.exists())

    def test_finalizer_refuses_tampered_durable_evidence_and_early_time(self):
        (
            _,
            ledger,
            lease,
            _,
            verifier,
            authorization_path,
            _,
            v3_path,
        ) = self._crash_after_core(action="finalize_prepared")
        authorization_path.write_bytes(authorization_path.read_bytes() + b"\n")
        with self.assertRaises(PublisherAuthorizationError):
            finalize_missing_publisher_replay_recovery_receipt_v3(
                ledger=ledger,
                lease=lease,
                authorization_verifier=verifier,
                finalized_at_utc=FINALIZED_AFTER_EXPIRY,
            )
        self.assertFalse(v3_path.exists())

        (
            _,
            early_ledger,
            early_lease,
            _,
            early_verifier,
            _,
            _,
            early_v3_path,
        ) = self._crash_after_core(action="finalize_prepared")
        with self.assertRaisesRegex(
            PublisherAuthorizationError,
            "predates the recovery transition",
        ):
            finalize_missing_publisher_replay_recovery_receipt_v3(
                ledger=early_ledger,
                lease=early_lease,
                authorization_verifier=early_verifier,
                finalized_at_utc="2026-08-04T06:49:59Z",
            )
        self.assertFalse(early_v3_path.exists())

    def test_finalizer_api_has_no_transition_or_transport_surface(self):
        parameters = inspect.signature(
            finalize_missing_publisher_replay_recovery_receipt_v3
        ).parameters
        self.assertEqual(
            set(parameters),
            {
                "ledger",
                "lease",
                "authorization_verifier",
                "finalized_at_utc",
            },
        )
        source = inspect.getsource(finalizer_module)
        for forbidden in (
            "recover_authenticated(",
            ".recover(",
            "_H6_RECOVER_AUTHENTICATED",
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
