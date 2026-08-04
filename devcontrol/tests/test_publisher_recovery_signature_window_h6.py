from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from kaliv_dev_control.durable_publication import create_once_file
from kaliv_dev_control.publisher_authorization import (
    PublisherAuthorizationError,
    PublisherReplayLedgerV2,
    PublisherReplayRecoveryAuthorizationVerifierV1,
)
from test_publisher_authorization_chain_v2 import LEDGER_ID
from test_publisher_recovery_authorization_h6 import (
    RECOVERED,
    _authorization,
    _lease,
)


class PublisherReplayRecoverySignatureWindowH6Tests(unittest.TestCase):
    def test_public_verifier_rejects_signature_before_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            _, lease, _ = _lease()
            ledger = PublisherReplayLedgerV2(
                root=root,
                ledger_id=LEDGER_ID,
            )
            _, _, lock, _ = ledger._paths(lease.invocation_nonce)
            create_once_file(lock, b"reserved")
            _, authorization, base_verifier = _authorization(ledger, lease)
            early_signature = replace(
                authorization.operator_signature,
                signed_at_utc="2026-08-04T06:48:59Z",
            )
            early_authorization = replace(
                authorization,
                operator_signature=early_signature,
            )
            verifier = PublisherReplayRecoveryAuthorizationVerifierV1(
                operator_verifier=base_verifier._operator_verifier,
                reviewer_verifier=base_verifier._reviewer_verifier,
            )
            with self.assertRaisesRegex(
                PublisherAuthorizationError,
                "outside the approval window",
            ):
                ledger.recover_authenticated(
                    lease=lease,
                    authorization=early_authorization,
                    authorization_verifier=verifier,
                    recovered_at_utc=RECOVERED,
                )


if __name__ == "__main__":
    unittest.main()
