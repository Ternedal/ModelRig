from __future__ import annotations

import hashlib
import inspect
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import kaliv_dev_control.publisher_authorization as public_authorization
import kaliv_dev_control.publisher_recovery_authorization as recovery_module
from kaliv_dev_control.asymmetric_authority import (
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
    asymmetric_authority_key_custody_policy_sha256,
    authority_signing_message,
)
from kaliv_dev_control.durable_publication import create_once_file
from kaliv_dev_control.publisher_authorization import PublisherAuthorizationError
from kaliv_dev_control.publisher_recovery_authorization import (
    PUBLISHER_REPLAY_RECOVERY_AUTHORIZATION_V1_SCHEMA,
    PUBLISHER_REPLAY_RECOVERY_STATE_V1_SCHEMA,
    PublisherReplayLedgerV3,
    PublisherReplayRecoveryAuthorizationV1,
    PublisherReplayRecoveryAuthorizationVerifierV1,
    build_publisher_replay_recovery_authorization_payload,
    load_publisher_replay_recovery_authorization_v1,
    write_publisher_replay_recovery_authorization_v1,
)
from test_publisher_authorization_chain_v2 import (
    KEY_VALID_FROM,
    KEY_VALID_UNTIL,
    LEDGER_ID,
    MATERIALIZED,
    PUBLISHER,
    _lease_v2,
)
from test_slice10j_publisher_dry_run import make_artifacts

OPERATOR = "publisher.recovery.operator"
OPERATOR_SYSTEM = "offline-recovery-operator"
OPERATOR_KEY_ID = "publisher-recovery-operator-ed25519-h6"
REVIEWER = "publisher.recovery.reviewer"
REVIEWER_SYSTEM = "offline-recovery-reviewer"
REVIEWER_KEY_ID = "publisher-recovery-reviewer-ed25519-h6"
OBSERVED = MATERIALIZED
REQUESTED = "2026-08-04T06:49:00Z"
RECOVERED = "2026-08-04T06:50:00Z"
AUTH_EXPIRES = "2026-08-04T06:54:00Z"


def _authority(
    *,
    private_byte: int,
    actor: str,
    system: str,
    key_id: str,
    epoch: int,
):
    private_key = Ed25519PrivateKey.from_private_bytes(
        bytes([private_byte]) * 32
    )
    public_key_hex = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    custody = asymmetric_authority_key_custody_policy_sha256()
    trusted = TrustedEd25519AuthorityKey(
        key_id=key_id,
        issuer_actor_id=actor,
        issuer_system_id=system,
        public_key_hex=public_key_hex,
        valid_from_utc=KEY_VALID_FROM,
        valid_until_utc=KEY_VALID_UNTIL,
        keyring_epoch=epoch,
        custody_policy_sha256=custody,
    )
    return private_key, Ed25519AuthorityVerifier(
        {key_id: trusted},
        minimum_keyring_epoch=epoch,
    )


def _signature(
    *,
    private_key,
    payload: bytes,
    actor: str,
    system: str,
    key_id: str,
    epoch: int,
) -> DetachedEd25519AuthoritySignature:
    custody = asymmetric_authority_key_custody_policy_sha256()
    return DetachedEd25519AuthoritySignature(
        key_id=key_id,
        issuer_actor_id=actor,
        issuer_system_id=system,
        keyring_epoch=epoch,
        custody_policy_sha256=custody,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        signature_hex=private_key.sign(
            authority_signing_message(
                key_id=key_id,
                issuer_actor_id=actor,
                issuer_system_id=system,
                keyring_epoch=epoch,
                custody_policy_sha256=custody,
                payload=payload,
            )
        ).hex(),
        signed_at_utc=REQUESTED,
    )


def _lease():
    (
        task,
        semantic_verifier,
        _,
        request,
        signed_request,
        publisher_verifier,
        _,
    ) = make_artifacts()
    _, lease, lease_verifier = _lease_v2(
        task=task,
        semantic_verifier=semantic_verifier,
        request=request,
        signed_request=signed_request,
        publisher_verifier=publisher_verifier,
    )
    return task, lease, lease_verifier


def _authorization(ledger, lease, *, operator_actor=OPERATOR):
    state = ledger.observe_recovery_state(
        lease=lease,
        observed_at_utc=OBSERVED,
    )
    operator_system = (
        OPERATOR_SYSTEM
        if operator_actor == OPERATOR
        else "overlap-recovery-operator"
    )
    operator_key_id = (
        OPERATOR_KEY_ID
        if operator_actor == OPERATOR
        else "overlap-recovery-operator-key"
    )
    payload = build_publisher_replay_recovery_authorization_payload(
        state=state,
        action="tombstone_uncertain",
        requested_at_utc=REQUESTED,
        expires_at_utc=AUTH_EXPIRES,
        operator_actor_id=operator_actor,
        operator_system_id=operator_system,
        operator_key_id=operator_key_id,
        reviewer_actor_id=REVIEWER,
        reviewer_system_id=REVIEWER_SYSTEM,
        reviewer_key_id=REVIEWER_KEY_ID,
    )
    operator_private, operator_verifier = _authority(
        private_byte=0x66,
        actor=operator_actor,
        system=operator_system,
        key_id=operator_key_id,
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
            actor=operator_actor,
            system=operator_system,
            key_id=operator_key_id,
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


class PublisherReplayRecoveryAuthorizationH6Tests(unittest.TestCase):
    def test_public_ledger_disables_raw_recovery(self):
        self.assertIs(
            public_authorization.PublisherReplayLedgerV2,
            PublisherReplayLedgerV3,
        )
        with tempfile.TemporaryDirectory() as directory:
            _, lease, _ = _lease()
            ledger = public_authorization.PublisherReplayLedgerV2(
                root=Path(directory).resolve(),
                ledger_id=LEDGER_ID,
            )
            with self.assertRaisesRegex(
                PublisherAuthorizationError,
                "unauthenticated recovery is disabled",
            ):
                ledger.recover(
                    lease=lease,
                    action="tombstone_uncertain",
                    recovery_authorization_sha256="a" * 64,
                    operator_actor_id=OPERATOR,
                    recovered_at_utc=RECOVERED,
                )

    def test_dual_signature_tombstone_is_durable_and_irreversible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            _, lease, _ = _lease()
            ledger = PublisherReplayLedgerV3(
                root=root,
                ledger_id=LEDGER_ID,
            )
            _, _, lock, _ = ledger._paths(lease.invocation_nonce)
            create_once_file(lock, b"reserved")
            state, authorization, verifier = _authorization(ledger, lease)
            self.assertEqual(state.state, "reserved")
            receipt = ledger.recover_authenticated(
                lease=lease,
                authorization=authorization,
                authorization_verifier=verifier,
                recovered_at_utc=RECOVERED,
            )
            self.assertEqual(
                receipt.recovery_authorization_sha256,
                authorization.sha256,
            )
            self.assertEqual(receipt.state_after, "tombstoned")
            self.assertFalse(receipt.nonce_reusable)
            auth_path = (
                root
                / f"{lease.invocation_nonce}.v2.recovery-authorization.json"
            )
            self.assertEqual(
                auth_path.read_bytes(),
                authorization.canonical_json().encode("utf-8"),
            )
            with self.assertRaisesRegex(
                PublisherAuthorizationError,
                "state changed",
            ):
                ledger.recover_authenticated(
                    lease=lease,
                    authorization=authorization,
                    authorization_verifier=verifier,
                    recovered_at_utc=RECOVERED,
                )

    def test_state_drift_fails_before_authorization_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            _, lease, _ = _lease()
            ledger = PublisherReplayLedgerV3(
                root=root,
                ledger_id=LEDGER_ID,
            )
            _, pending, lock, _ = ledger._paths(lease.invocation_nonce)
            create_once_file(lock, b"reserved")
            _, authorization, verifier = _authorization(ledger, lease)
            create_once_file(pending, b"changed-after-approval")
            with self.assertRaisesRegex(
                PublisherAuthorizationError,
                "state changed",
            ):
                ledger.recover_authenticated(
                    lease=lease,
                    authorization=authorization,
                    authorization_verifier=verifier,
                    recovered_at_utc=RECOVERED,
                )
            self.assertFalse(
                (
                    root
                    / f"{lease.invocation_nonce}.v2.recovery-authorization.json"
                ).exists()
            )

    def test_prior_role_overlap_and_expiry_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            _, lease, _ = _lease()
            ledger = PublisherReplayLedgerV3(
                root=root,
                ledger_id=LEDGER_ID,
            )
            _, _, lock, _ = ledger._paths(lease.invocation_nonce)
            create_once_file(lock, b"reserved")
            _, authorization, verifier = _authorization(
                ledger,
                lease,
                operator_actor=PUBLISHER,
            )
            with self.assertRaisesRegex(
                PublisherAuthorizationError,
                "separate from prior authority roles",
            ):
                ledger.recover_authenticated(
                    lease=lease,
                    authorization=authorization,
                    authorization_verifier=verifier,
                    recovered_at_utc=RECOVERED,
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            _, lease, _ = _lease()
            ledger = PublisherReplayLedgerV3(
                root=root,
                ledger_id=LEDGER_ID,
            )
            _, _, lock, _ = ledger._paths(lease.invocation_nonce)
            create_once_file(lock, b"reserved")
            _, authorization, verifier = _authorization(ledger, lease)
            with self.assertRaisesRegex(
                PublisherAuthorizationError,
                "not currently valid",
            ):
                ledger.recover_authenticated(
                    lease=lease,
                    authorization=authorization,
                    authorization_verifier=verifier,
                    recovered_at_utc=AUTH_EXPIRES,
                )

    def test_wrong_reviewer_signature_and_action_state_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            _, lease, _ = _lease()
            ledger = PublisherReplayLedgerV3(
                root=root,
                ledger_id=LEDGER_ID,
            )
            _, _, lock, _ = ledger._paths(lease.invocation_nonce)
            create_once_file(lock, b"reserved")
            state, authorization, verifier = _authorization(ledger, lease)
            forged = replace(
                authorization.reviewer_signature,
                signature_hex="00" * 64,
            )
            tampered = replace(
                authorization,
                reviewer_signature=forged,
            )
            with self.assertRaisesRegex(
                PublisherAuthorizationError,
                "signature verification failed",
            ):
                ledger.recover_authenticated(
                    lease=lease,
                    authorization=tampered,
                    authorization_verifier=verifier,
                    recovered_at_utc=RECOVERED,
                )
            with self.assertRaisesRegex(
                PublisherAuthorizationError,
                "not valid for the observed",
            ):
                build_publisher_replay_recovery_authorization_payload(
                    state=state,
                    action="finalize_prepared",
                    requested_at_utc=REQUESTED,
                    expires_at_utc=AUTH_EXPIRES,
                    operator_actor_id=OPERATOR,
                    operator_system_id=OPERATOR_SYSTEM,
                    operator_key_id=OPERATOR_KEY_ID,
                    reviewer_actor_id=REVIEWER,
                    reviewer_system_id=REVIEWER_SYSTEM,
                    reviewer_key_id=REVIEWER_KEY_ID,
                )

    def test_schema_roundtrip_create_once_and_no_signer_surface(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            _, lease, _ = _lease()
            ledger = PublisherReplayLedgerV3(
                root=root,
                ledger_id=LEDGER_ID,
            )
            _, _, lock, _ = ledger._paths(lease.invocation_nonce)
            create_once_file(lock, b"reserved")
            state, authorization, _ = _authorization(ledger, lease)
            for value, schema_name in (
                (
                    state,
                    "development-publisher-replay-recovery-state-v1.schema.json",
                ),
                (
                    authorization,
                    "development-publisher-replay-recovery-authorization-v1.schema.json",
                ),
            ):
                schema = json.loads(
                    (
                        Path(__file__).parents[1]
                        / "schemas"
                        / schema_name
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(set(schema["required"]), set(value.to_dict()))
                self.assertEqual(set(schema["properties"]), set(value.to_dict()))
            path = root / "authorization.json"
            self.assertEqual(
                write_publisher_replay_recovery_authorization_v1(
                    path, authorization
                ),
                authorization.sha256,
            )
            self.assertEqual(
                load_publisher_replay_recovery_authorization_v1(
                    path
                ).canonical_json(),
                authorization.canonical_json(),
            )
            with self.assertRaises(PublisherAuthorizationError):
                write_publisher_replay_recovery_authorization_v1(
                    path, authorization
                )

        source = inspect.getsource(recovery_module)
        for forbidden in (
            "Ed25519PrivateKey",
            "from_private_bytes",
            "load_pem_private_key",
            "import hmac",
            "github_token",
            "api.github.com",
            "import requests",
            "import socket",
        ):
            self.assertNotIn(forbidden, source)
        self.assertEqual(
            PUBLISHER_REPLAY_RECOVERY_STATE_V1_SCHEMA,
            "kaliv-development-publisher-replay-recovery-state/v1",
        )
        self.assertEqual(
            PUBLISHER_REPLAY_RECOVERY_AUTHORIZATION_V1_SCHEMA,
            "kaliv-development-publisher-replay-recovery-authorization/v1",
        )


if __name__ == "__main__":
    unittest.main()
