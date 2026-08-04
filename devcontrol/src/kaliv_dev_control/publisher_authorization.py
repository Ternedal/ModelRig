"""Public publisher authorization boundary.

The supported authority surface is Ed25519 verification-only. The original v1
HMAC objects remain module attributes solely so historical evidence tests can
load and verify retained artifacts during migration; they are deliberately
excluded from ``__all__`` and are not a supported issuance API.

New downstream evidence must use the H5C v2 replay, preflight, postcondition and
recovery classes exported below. Private signing material is never accepted by
that path.
"""
from __future__ import annotations

# Retained exact v1 artifact parsers and compatibility objects. Do not add the
# HMAC issuer or shared-secret key types to the supported export list below.
from ._publisher_authorization_legacy import *  # noqa: F403
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
    PublisherReplayLedgerV2,
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
from .publisher_replay_h4 import (
    PUBLISHER_REPLAY_RECOVERY_SCHEMA,
    PublisherReplayLedger,
    PublisherReplayRecoveryReceipt,
)

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
]
