"""Public publisher-authorization boundary.

Only verification-only Ed25519 authority is supported. Retained v1 HMAC
parsers and issuers live exclusively under
``kaliv_dev_control._compatibility_v1`` and are absent from this namespace.

H9 exposes one physically primary authenticated replay/recovery ledger. It
preserves H6 dual-signature authorization, H7 canonical receipt v3 and H8's
receipt-only finalizer without import-time class mutation.
This module contains no private key, shared secret, credential, transport,
GitHub client, repository writer, merge, release or deployment authority.
"""
from __future__ import annotations

from ._publisher_authorization_legacy import (
    PublisherAuthorizationError,
    PublisherCredentialPolicy,
    RemoteRepositoryIdentity,
    publisher_authorization_policy_sha256,
    publisher_credential_policy_rules_sha256,
)
from .publisher_authorization_v2 import (
    AsymmetricPublisherAuthorizationLease,
    AsymmetricPublisherAuthorizationVerifier,
    PUBLISHER_AUTHORIZATION_LEASE_V2_SCHEMA,
    build_asymmetric_publisher_authorization_payload,
)
from .publisher_authorization_chain_v2 import (
    PUBLISHER_POSTCONDITION_RECEIPT_V2_SCHEMA,
    PUBLISHER_PREFLIGHT_RECEIPT_V2_SCHEMA,
    PUBLISHER_REPLAY_LEDGER_ENTRY_V2_SCHEMA,
    PUBLISHER_REPLAY_RECOVERY_V2_SCHEMA,
    PublisherAuthorizationVerifierV2,
    PublisherPostconditionGateV2,
    PublisherPostconditionReceiptV2,
    PublisherPreflightGateV2,
    PublisherPreflightReceiptV2,
    PublisherReplayLedgerEntryV2,
    PublisherReplayRecoveryReceiptV2,
    load_publisher_postcondition_receipt_v2,
    load_publisher_preflight_receipt_v2,
    load_publisher_replay_ledger_entry_v2,
    load_publisher_replay_recovery_receipt_v2,
    write_publisher_postcondition_receipt_v2,
    write_publisher_preflight_receipt_v2,
    write_publisher_replay_ledger_entry_v2,
    write_publisher_replay_recovery_receipt_v2,
)
from .publisher_recovery_authorization import (
    PUBLISHER_REPLAY_RECOVERY_AUTHORIZATION_V1_SCHEMA,
    PUBLISHER_REPLAY_RECOVERY_POLICY,
    PUBLISHER_REPLAY_RECOVERY_STATE_V1_SCHEMA,
    PublisherReplayRecoveryAuthorizationV1,
    PublisherReplayRecoveryStateV1,
    build_publisher_replay_recovery_authorization_payload,
    load_publisher_replay_recovery_authorization_v1,
    publisher_replay_recovery_policy_sha256,
    write_publisher_replay_recovery_authorization_v1,
)
from .publisher_recovery_primary import (
    PublisherReplayLedgerV3,
    PublisherReplayRecoveryAuthorizationVerifierV1,
)
from .publisher_recovery_receipt_v3 import (
    PUBLISHER_REPLAY_RECOVERY_RECEIPT_V3_SCHEMA,
    PublisherReplayRecoveryReceiptV3,
    load_publisher_replay_recovery_receipt_v3,
    write_publisher_replay_recovery_receipt_v3,
)
from .publisher_recovery_receipt_finalizer import (
    finalize_missing_publisher_replay_recovery_receipt_v3,
)

# Retain the former read-only accessor without duplicating it in canonical v3
# evidence. The value is exactly the embedded authorization SHA-256.
setattr(
    PublisherReplayRecoveryReceiptV3,
    "recovery_authorization_sha256",
    property(lambda receipt: receipt.authorization_sha256),
)

# Compatibility name for existing public consumers. Both public names resolve
# to the physically implemented H9 ledger. Raw recover() remains disabled.
PublisherReplayLedgerV2 = PublisherReplayLedgerV3

__all__ = [
    "PublisherAuthorizationError",
    "PublisherCredentialPolicy",
    "RemoteRepositoryIdentity",
    "publisher_authorization_policy_sha256",
    "publisher_credential_policy_rules_sha256",
    "AsymmetricPublisherAuthorizationLease",
    "AsymmetricPublisherAuthorizationVerifier",
    "PUBLISHER_AUTHORIZATION_LEASE_V2_SCHEMA",
    "build_asymmetric_publisher_authorization_payload",
    "PUBLISHER_POSTCONDITION_RECEIPT_V2_SCHEMA",
    "PUBLISHER_PREFLIGHT_RECEIPT_V2_SCHEMA",
    "PUBLISHER_REPLAY_LEDGER_ENTRY_V2_SCHEMA",
    "PUBLISHER_REPLAY_RECOVERY_V2_SCHEMA",
    "PublisherAuthorizationVerifierV2",
    "PublisherPostconditionGateV2",
    "PublisherPostconditionReceiptV2",
    "PublisherPreflightGateV2",
    "PublisherPreflightReceiptV2",
    "PublisherReplayLedgerEntryV2",
    "PublisherReplayLedgerV2",
    "PublisherReplayRecoveryReceiptV2",
    "load_publisher_postcondition_receipt_v2",
    "load_publisher_preflight_receipt_v2",
    "load_publisher_replay_ledger_entry_v2",
    "load_publisher_replay_recovery_receipt_v2",
    "write_publisher_postcondition_receipt_v2",
    "write_publisher_preflight_receipt_v2",
    "write_publisher_replay_ledger_entry_v2",
    "write_publisher_replay_recovery_receipt_v2",
    "PUBLISHER_REPLAY_RECOVERY_AUTHORIZATION_V1_SCHEMA",
    "PUBLISHER_REPLAY_RECOVERY_POLICY",
    "PUBLISHER_REPLAY_RECOVERY_STATE_V1_SCHEMA",
    "PUBLISHER_REPLAY_RECOVERY_RECEIPT_V3_SCHEMA",
    "PublisherReplayLedgerV3",
    "PublisherReplayRecoveryAuthorizationV1",
    "PublisherReplayRecoveryAuthorizationVerifierV1",
    "PublisherReplayRecoveryReceiptV3",
    "PublisherReplayRecoveryStateV1",
    "build_publisher_replay_recovery_authorization_payload",
    "finalize_missing_publisher_replay_recovery_receipt_v3",
    "load_publisher_replay_recovery_authorization_v1",
    "load_publisher_replay_recovery_receipt_v3",
    "publisher_replay_recovery_policy_sha256",
    "write_publisher_replay_recovery_authorization_v1",
    "write_publisher_replay_recovery_receipt_v3",
]
