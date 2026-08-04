"""Historical publisher-authorization v1 compatibility tests.

All v1/HMAC imports are intentionally internal. Normal consumers must use the
public Ed25519/v2 boundary.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kaliv_dev_control._compatibility_v1.publisher_authorization import (
    HmacPublisherAuthorizationIssuer,
    PublisherAuthorizationError,
    PublisherAuthorizationVerifier,
    PublisherPostconditionReceipt,
    PublisherPreflightReceipt,
    PublisherReplayLedger,
    RemoteRepositoryIdentity,
    TrustedAuthorizationIssuerKey,
)
from test_slice10h_semantic_review import ROOT
from test_slice10j_publisher_dry_run import make_artifacts

ISSUER = "publisher.authorization.issuer"
ISSUER_SYSTEM = "offline-authorization-service-v1"
ISSUER_KEY_ID = "publisher-authorization-key-2026"
ISSUER_SECRET = b"a" * 32
REPOSITORY_ID = "900000001"
LEDGER_ID = "publisher-replay-ledger-primary"
ISSUED = "2026-08-04T06:45:00Z"
CONSUMED = "2026-08-04T06:46:00Z"
CHECKED = "2026-08-04T06:47:00Z"
OBSERVED = "2026-08-04T06:48:00Z"
EXPIRES = "2026-08-04T06:55:00Z"


def make_authorization(directory: Path):
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
    lease = HmacPublisherAuthorizationIssuer(
        key_id=ISSUER_KEY_ID,
        issuer_actor_id=ISSUER,
        issuer_system_id=ISSUER_SYSTEM,
        secret=ISSUER_SECRET,
    ).issue(
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
    replay = ledger.consume_once(
        lease=lease,
        task=task,
        authorization_verifier=verifier,
        publisher_verifier=publisher_verifier,
        semantic_verifier=semantic_verifier,
        control_plane_root=ROOT,
        consumed_at_utc=CONSUMED,
    )
    preflight = PublisherPreflightReceipt.from_consumed_lease(
        lease=lease,
        replay_entry=replay,
        task=task,
        authorization_verifier=verifier,
        publisher_verifier=publisher_verifier,
        semantic_verifier=semantic_verifier,
        control_plane_root=ROOT,
        checked_at_utc=CHECKED,
    )
    postcondition = PublisherPostconditionReceipt.from_preflight_without_execution(
        preflight=preflight,
        observed_at_utc=OBSERVED,
    )
    return (
        task,
        semantic_verifier,
        publisher_verifier,
        lease,
        verifier,
        ledger,
        replay,
        preflight,
        postcondition,
    )


class HistoricalPublisherAuthorizationV1Tests(unittest.TestCase):
    def test_internal_v1_chain_still_verifies_retained_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (
                task,
                semantic_verifier,
                publisher_verifier,
                lease,
                verifier,
                ledger,
                replay,
                preflight,
                postcondition,
            ) = make_authorization(Path(directory).resolve())
            self.assertEqual(
                verifier.verify(
                    lease=lease,
                    task=task,
                    publisher_verifier=publisher_verifier,
                    semantic_verifier=semantic_verifier,
                    control_plane_root=ROOT,
                    at_utc=CONSUMED,
                ).sha256,
                lease.sha256,
            )
            self.assertEqual(ledger.load(lease.invocation_nonce).sha256, replay.sha256)
            preflight.verify(
                task=task,
                authorization_verifier=verifier,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=ROOT,
            )
            self.assertEqual(postcondition.execution_state, "not_executed")
            self.assertFalse(postcondition.repository_write_performed)
            self.assertFalse(postcondition.network_write_performed)

    def test_internal_v1_replay_and_wrong_secret_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (
                task,
                semantic_verifier,
                publisher_verifier,
                lease,
                verifier,
                ledger,
                _,
                _,
                _,
            ) = make_authorization(Path(directory).resolve())
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
            wrong = PublisherAuthorizationVerifier(
                {
                    ISSUER_KEY_ID: TrustedAuthorizationIssuerKey(
                        issuer_actor_id=ISSUER,
                        secret=b"x" * 32,
                    )
                }
            )
            with self.assertRaises(PublisherAuthorizationError):
                wrong.verify(
                    lease=lease,
                    task=task,
                    publisher_verifier=publisher_verifier,
                    semantic_verifier=semantic_verifier,
                    control_plane_root=ROOT,
                    at_utc=CONSUMED,
                )

    def test_implementation_is_physically_under_internal_package(self) -> None:
        self.assertTrue(
            HmacPublisherAuthorizationIssuer.__module__.startswith(
                "kaliv_dev_control._compatibility_v1."
            )
        )
        self.assertTrue(
            PublisherAuthorizationVerifier.__module__.startswith(
                "kaliv_dev_control._compatibility_v1."
            )
        )


if __name__ == "__main__":
    unittest.main()
