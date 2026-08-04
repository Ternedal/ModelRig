"""Public publisher authorization boundary with crash-durable replay state.

The legacy v1 HMAC classes remain temporarily available for compatibility tests
and migration only. New authority must use the verification-only Ed25519 v2
lease boundary exported below. Private signing material is never accepted here.
"""
from __future__ import annotations

from ._publisher_authorization_legacy import *
from .publisher_authorization_v2 import (
    AsymmetricPublisherAuthorizationLease,
    AsymmetricPublisherAuthorizationVerifier,
    PUBLISHER_AUTHORIZATION_LEASE_V2_SCHEMA,
    build_asymmetric_publisher_authorization_payload,
)
from .publisher_replay_h4 import (
    PUBLISHER_REPLAY_RECOVERY_SCHEMA,
    PublisherReplayLedger,
    PublisherReplayRecoveryReceipt,
)

__all__ = [name for name in globals() if not name.startswith("_")]
