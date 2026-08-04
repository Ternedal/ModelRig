"""Authenticated publisher replay recovery receipt v3 (H7).

H7 consolidates the supported recovery verifier and makes the complete dual
Ed25519 authorization part of the durable recovery receipt.  The retained H6
mutation core remains fail closed and continues to write its v2 transition
receipt; H7 wraps that exact receipt in canonical v3 evidence.

No private key, shared secret, credential, Git transport, network client,
repository writer, pull-request writer, merge, release or deployment capability
is accepted or implemented here.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import publisher_recovery_authorization as _recovery_module
from ._publisher_authorization_legacy import (
    PublisherAuthorizationError,
    _MAX_ARTIFACT_BYTES,
    _actor,
    _canonical,
    _has_linkish_component,
    _hex,
    _identifier,
    _load_canonical,
    _strict,
    _utc,
)
from .durable_publication import DurablePublicationError, create_once_file
from .publisher_authorization_chain_v2 import PublisherReplayRecoveryReceiptV2
from .publisher_authorization_v2 import AsymmetricPublisherAuthorizationLease
from .publisher_recovery_authorization import (
    PublisherReplayLedgerV3,
    PublisherReplayRecoveryAuthorizationV1,
    PublisherReplayRecoveryAuthorizationVerifierV1 as _H6RecoveryVerifier,
    PublisherReplayRecoveryStateV1,
)

PUBLISHER_REPLAY_RECOVERY_RECEIPT_V3_SCHEMA = (
    "kaliv-development-publisher-replay-recovery-receipt/v3"
)


class PublisherReplayRecoveryAuthorizationVerifierV1(_H6RecoveryVerifier):
    """The single supported verifier, including exact signature-time binding."""

    def verify(
        self,
        *,
        authorization: PublisherReplayRecoveryAuthorizationV1,
        lease: AsymmetricPublisherAuthorizationLease,
        current_state: PublisherReplayRecoveryStateV1,
        at_utc: str,
    ) -> PublisherReplayRecoveryAuthorizationV1:
        verified = super().verify(
            authorization=authorization,
            lease=lease,
            current_state=current_state,
            at_utc=at_utc,
        )
        requested = _utc(
            authorization.requested_at_utc,
            name="recovery request time",
        )
        expires = _utc(
            authorization.expires_at_utc,
            name="recovery authorization expiry",
        )
        for signature, role in (
            (authorization.operator_signature, "operator"),
            (authorization.reviewer_signature, "reviewer"),
        ):
            signed = _utc(
                signature.signed_at_utc,
                name=f"recovery {role} signature time",
            )
            if signed < requested or signed >= expires:
                raise PublisherAuthorizationError(
                    f"recovery {role} signature is outside the approval window"
                )
        return verified


@dataclass(frozen=True, slots=True)
class PublisherReplayRecoveryReceiptV3:
    authorization: PublisherReplayRecoveryAuthorizationV1
    authorization_sha256: str
    core_receipt: PublisherReplayRecoveryReceiptV2
    core_receipt_sha256: str
    lease_sha256: str
    invocation_nonce: str
    ledger_id: str
    recovered_at_utc: str
    action: str
    state_before: str
    state_after: str
    entry_verified: bool
    authorization_embedded: bool = True
    nonce_reusable: bool = False
    schema: str = PUBLISHER_REPLAY_RECOVERY_RECEIPT_V3_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PUBLISHER_REPLAY_RECOVERY_RECEIPT_V3_SCHEMA:
            raise PublisherAuthorizationError(
                "unsupported publisher replay recovery receipt v3 schema"
            )
        if not isinstance(
            self.authorization,
            PublisherReplayRecoveryAuthorizationV1,
        ):
            raise PublisherAuthorizationError(
                "recovery receipt v3 authorization is invalid"
            )
        if not isinstance(self.core_receipt, PublisherReplayRecoveryReceiptV2):
            raise PublisherAuthorizationError(
                "recovery receipt v3 core receipt is invalid"
            )
        _hex(self.authorization_sha256, name="recovery authorization hash")
        _hex(self.core_receipt_sha256, name="recovery core receipt hash")
        _hex(self.lease_sha256, name="recovery receipt lease hash")
        _hex(self.invocation_nonce, name="recovery receipt invocation nonce")
        _identifier(self.ledger_id, name="recovery receipt ledger ID")
        _utc(self.recovered_at_utc, name="recovery receipt time")
        if not isinstance(self.entry_verified, bool):
            raise PublisherAuthorizationError(
                "recovery receipt v3 verification flag is invalid"
            )
        if self.authorization_embedded is not True:
            raise PublisherAuthorizationError(
                "recovery receipt v3 must embed the complete authorization"
            )
        if self.nonce_reusable is not False:
            raise PublisherAuthorizationError(
                "recovery receipt v3 can never make a nonce reusable"
            )

        authorization = self.authorization
        core = self.core_receipt
        state = authorization.state
        if (
            self.authorization_sha256 != authorization.sha256
            or self.core_receipt_sha256 != core.sha256
            or core.recovery_authorization_sha256 != authorization.sha256
            or self.lease_sha256 != core.lease_sha256
            or self.lease_sha256 != state.lease_sha256
            or self.invocation_nonce != core.invocation_nonce
            or self.invocation_nonce != state.invocation_nonce
            or self.ledger_id != core.ledger_id
            or self.ledger_id != state.ledger_id
            or self.recovered_at_utc != core.recovered_at_utc
            or self.action != core.action
            or self.action != authorization.action
            or self.state_before != core.state_before
            or self.state_before != state.state
            or self.state_after != core.state_after
            or self.entry_verified is not core.entry_verified
            or core.operator_actor_id != authorization.operator_actor_id
            or core.nonce_reusable is not False
        ):
            raise PublisherAuthorizationError(
                "recovery receipt v3 bindings are inconsistent"
            )

        requested = _utc(
            authorization.requested_at_utc,
            name="recovery request time",
        )
        expires = _utc(
            authorization.expires_at_utc,
            name="recovery authorization expiry",
        )
        recovered = _utc(self.recovered_at_utc, name="recovery receipt time")
        if not (requested <= recovered < expires):
            raise PublisherAuthorizationError(
                "recovery receipt v3 is outside the authorization window"
            )

        expected = {
            "finalize_prepared": ("prepared", "committed", True),
            "acknowledge_committed": (
                {"committed", "committed_locked"},
                "committed",
                True,
            ),
            "tombstone_uncertain": (
                {"reserved", "partial"},
                "tombstoned",
                False,
            ),
        }
        if self.action == "finalize_prepared":
            before, after, verified = expected[self.action]
            valid_before = self.state_before == before
        else:
            before, after, verified = expected.get(
                self.action,
                (set(), "", False),
            )
            valid_before = self.state_before in before
        if (
            not valid_before
            or self.state_after != after
            or self.entry_verified is not verified
        ):
            raise PublisherAuthorizationError(
                "recovery receipt v3 transition is inconsistent"
            )

    @classmethod
    def from_core(
        cls,
        *,
        authorization: PublisherReplayRecoveryAuthorizationV1,
        core_receipt: PublisherReplayRecoveryReceiptV2,
    ) -> "PublisherReplayRecoveryReceiptV3":
        if not isinstance(
            authorization,
            PublisherReplayRecoveryAuthorizationV1,
        ) or not isinstance(core_receipt, PublisherReplayRecoveryReceiptV2):
            raise PublisherAuthorizationError(
                "recovery receipt v3 requires exact authorization and core evidence"
            )
        return cls(
            authorization=authorization,
            authorization_sha256=authorization.sha256,
            core_receipt=core_receipt,
            core_receipt_sha256=core_receipt.sha256,
            lease_sha256=core_receipt.lease_sha256,
            invocation_nonce=core_receipt.invocation_nonce,
            ledger_id=core_receipt.ledger_id,
            recovered_at_utc=core_receipt.recovered_at_utc,
            action=core_receipt.action,
            state_before=core_receipt.state_before,
            state_after=core_receipt.state_after,
            entry_verified=core_receipt.entry_verified,
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "PublisherReplayRecoveryReceiptV3":
        data = _strict(
            value,
            name="publisher replay recovery receipt v3",
            fields={
                "schema",
                "authorization",
                "authorization_sha256",
                "core_receipt",
                "core_receipt_sha256",
                "lease_sha256",
                "invocation_nonce",
                "ledger_id",
                "recovered_at_utc",
                "action",
                "state_before",
                "state_after",
                "entry_verified",
                "authorization_embedded",
                "nonce_reusable",
            },
        )
        return cls(
            schema=data["schema"],
            authorization=(
                PublisherReplayRecoveryAuthorizationV1.from_mapping(
                    data["authorization"]
                )
            ),
            authorization_sha256=data["authorization_sha256"],
            core_receipt=PublisherReplayRecoveryReceiptV2.from_mapping(
                data["core_receipt"]
            ),
            core_receipt_sha256=data["core_receipt_sha256"],
            lease_sha256=data["lease_sha256"],
            invocation_nonce=data["invocation_nonce"],
            ledger_id=data["ledger_id"],
            recovered_at_utc=data["recovered_at_utc"],
            action=data["action"],
            state_before=data["state_before"],
            state_after=data["state_after"],
            entry_verified=data["entry_verified"],
            authorization_embedded=data["authorization_embedded"],
            nonce_reusable=data["nonce_reusable"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "authorization": self.authorization.to_dict(),
            "authorization_sha256": self.authorization_sha256,
            "core_receipt": self.core_receipt.to_dict(),
            "core_receipt_sha256": self.core_receipt_sha256,
            "lease_sha256": self.lease_sha256,
            "invocation_nonce": self.invocation_nonce,
            "ledger_id": self.ledger_id,
            "recovered_at_utc": self.recovered_at_utc,
            "action": self.action,
            "state_before": self.state_before,
            "state_after": self.state_after,
            "entry_verified": self.entry_verified,
            "authorization_embedded": self.authorization_embedded,
            "nonce_reusable": self.nonce_reusable,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def load_publisher_replay_recovery_receipt_v3(
    path: Path,
) -> PublisherReplayRecoveryReceiptV3:
    return _load_canonical(
        Path(path),
        PublisherReplayRecoveryReceiptV3.from_mapping,
        name="publisher replay recovery receipt v3",
    )


def write_publisher_replay_recovery_receipt_v3(
    path: Path,
    receipt: PublisherReplayRecoveryReceiptV3,
) -> str:
    if not isinstance(receipt, PublisherReplayRecoveryReceiptV3):
        raise PublisherAuthorizationError(
            "publisher replay recovery receipt v3 output is invalid"
        )
    output = Path(path)
    if (
        not output.is_absolute()
        or output.exists()
        or not output.parent.is_dir()
        or _has_linkish_component(output.parent)
    ):
        raise PublisherAuthorizationError(
            "publisher replay recovery receipt v3 path is unsafe or exists"
        )
    payload = receipt.canonical_json().encode("utf-8")
    if len(payload) > _MAX_ARTIFACT_BYTES:
        raise PublisherAuthorizationError(
            "publisher replay recovery receipt v3 exceeds its byte bound"
        )
    try:
        create_once_file(output, payload)
    except (FileExistsError, DurablePublicationError) as exc:
        raise PublisherAuthorizationError(
            "publisher replay recovery receipt v3 was not durably published"
        ) from exc
    return receipt.sha256


_H6_RECOVER_AUTHENTICATED = PublisherReplayLedgerV3.recover_authenticated


def _recover_authenticated_h7(
    self: PublisherReplayLedgerV3,
    *,
    lease: AsymmetricPublisherAuthorizationLease,
    authorization: PublisherReplayRecoveryAuthorizationV1,
    authorization_verifier: PublisherReplayRecoveryAuthorizationVerifierV1,
    recovered_at_utc: str,
) -> PublisherReplayRecoveryReceiptV3:
    if not isinstance(
        authorization_verifier,
        PublisherReplayRecoveryAuthorizationVerifierV1,
    ):
        raise PublisherAuthorizationError(
            "recovery requires the consolidated H7 Ed25519 verifier"
        )
    core_receipt = _H6_RECOVER_AUTHENTICATED(
        self,
        lease=lease,
        authorization=authorization,
        authorization_verifier=authorization_verifier,
        recovered_at_utc=recovered_at_utc,
    )
    receipt = PublisherReplayRecoveryReceiptV3.from_core(
        authorization=authorization,
        core_receipt=core_receipt,
    )
    path = self._root / f"{lease.invocation_nonce}.v3.recovery.json"
    payload = receipt.canonical_json().encode("utf-8")
    if len(payload) > _MAX_ARTIFACT_BYTES:
        raise PublisherAuthorizationError(
            "publisher replay recovery receipt v3 exceeds its byte bound"
        )
    if path.exists():
        if (
            path.is_symlink()
            or not path.is_file()
            or path.read_bytes() != payload
        ):
            raise PublisherAuthorizationError(
                "publisher replay recovery receipt v3 conflicts with durable evidence"
            )
    else:
        try:
            create_once_file(path, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PublisherAuthorizationError(
                "publisher replay recovery receipt v3 was not durably published"
            ) from exc
    loaded = load_publisher_replay_recovery_receipt_v3(path)
    if loaded.canonical_json() != receipt.canonical_json():
        raise PublisherAuthorizationError(
            "publisher replay recovery receipt v3 postcondition failed"
        )
    return receipt


# Replace both formerly divergent public/internal verifier references with one
# H7 class, then install receipt-v3 wrapping on the existing H6 ledger class.
# The ledger class identity intentionally remains stable for existing consumers.
_recovery_module.PublisherReplayRecoveryAuthorizationVerifierV1 = (
    PublisherReplayRecoveryAuthorizationVerifierV1
)
if not getattr(PublisherReplayLedgerV3, "_h7_receipt_v3_installed", False):
    PublisherReplayLedgerV3.recover_authenticated = _recover_authenticated_h7
    PublisherReplayLedgerV3._h7_receipt_v3_installed = True


__all__ = [
    "PUBLISHER_REPLAY_RECOVERY_RECEIPT_V3_SCHEMA",
    "PublisherReplayRecoveryAuthorizationVerifierV1",
    "PublisherReplayRecoveryReceiptV3",
    "load_publisher_replay_recovery_receipt_v3",
    "write_publisher_replay_recovery_receipt_v3",
]
