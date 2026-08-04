"""Public publisher-authorization boundary.

Only the Ed25519/v2 authority path is supported here. Retained v1 HMAC parsers
and issuers live exclusively under ``kaliv_dev_control._compatibility_v1`` and
are deliberately absent from this module namespace.

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
