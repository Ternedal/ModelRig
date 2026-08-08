"""Authenticated publisher replay recovery authority (H6).

The supported recovery path requires two independent detached Ed25519
signatures over one exact durable-state snapshot and one exact recovery action.
No private key, shared secret, credential, Git transport, network client,
repository writer, pull-request writer, merge, release or deployment capability
is accepted or implemented here.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ._publisher_authorization_legacy import (
    PublisherAuthorizationError,
    _MAX_ARTIFACT_BYTES,
    _actor,
    _canonical,
    _has_linkish_component,
    _hex,
    _identifier,
    _strict,
    _utc,
)
from .asymmetric_authority import (
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    AsymmetricAuthorityError,
    asymmetric_authority_key_custody_policy_sha256,
)
from .durable_publication import DurablePublicationError, create_once_file
from .publisher_authorization_chain_v2 import (
    PublisherReplayLedgerV2 as _PublisherReplayLedgerV2,
    PublisherReplayRecoveryReceiptV2,
)
from .publisher_authorization_v2 import AsymmetricPublisherAuthorizationLease

PUBLISHER_REPLAY_RECOVERY_STATE_V1_SCHEMA = (
    "kaliv-development-publisher-replay-recovery-state/v1"
)
PUBLISHER_REPLAY_RECOVERY_AUTHORIZATION_V1_SCHEMA = (
    "kaliv-development-publisher-replay-recovery-authorization/v1"
)
_RECOVERY_PAYLOAD_SCHEMA = (
    "kaliv-development-publisher-replay-recovery-authorization-payload/v1"
)
_RECOVERY_POLICY_DOMAIN = b"kaliv-publisher-replay-recovery-policy/v1\0"
_MAX_RECOVERY_SECONDS = 10 * 60
_ACTION_STATES = {
    "finalize_prepared": {"prepared"},
    "acknowledge_committed": {"committed", "committed_locked"},
    "tombstone_uncertain": {"reserved", "partial"},
}

PUBLISHER_REPLAY_RECOVERY_POLICY = (
    "Require one exact byte-hashed durable replay-state snapshot before recovery.",
    "Bind the exact lease, invocation nonce, ledger, action and observed files.",
    "Require separate Ed25519 operator and independent reviewer signatures.",
    "Reject operator or reviewer identity overlap with developer, semantic reviewer, publisher or lease issuer.",
    "Limit recovery authorization to one short-lived window of at most ten minutes.",
    "Durably publish the exact authorization before any recovery mutation.",
    "Never make a consumed or uncertain invocation nonce reusable.",
    "Keep credentials, remotes, network writes, pull-request mutation, merge, release and deployment outside recovery.",
)


def publisher_replay_recovery_policy_sha256() -> str:
    payload = json.dumps(
        list(PUBLISHER_REPLAY_RECOVERY_POLICY),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(_RECOVERY_POLICY_DOMAIN + payload).hexdigest()


def _optional_hash(value: Any, *, present: bool, name: str) -> str | None:
    if not isinstance(present, bool):
        raise PublisherAuthorizationError(f"{name} presence flag is invalid")
    if present:
        return _hex(value, name=f"{name} hash")
    if value is not None:
        raise PublisherAuthorizationError(
            f"{name} hash must be null when the file is absent"
        )
    return None


def _file_hash(path: Path) -> tuple[bool, str | None]:
    if path.is_symlink() or _has_linkish_component(path.parent):
        raise PublisherAuthorizationError(
            "publisher replay recovery state contains a link"
        )
    if not path.exists():
        return False, None
    if not path.is_file():
        raise PublisherAuthorizationError(
            "publisher replay recovery state contains a non-file"
        )
    payload = path.read_bytes()
    if len(payload) > _MAX_ARTIFACT_BYTES:
        raise PublisherAuthorizationError(
            "publisher replay recovery state file exceeds its byte bound"
        )
    return True, hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class PublisherReplayRecoveryStateV1:
    lease_sha256: str
    invocation_nonce: str
    ledger_id: str
    observed_at_utc: str
    state: str
    final_present: bool
    final_sha256: str | None
    pending_present: bool
    pending_sha256: str | None
    reservation_present: bool
    reservation_sha256: str | None
    recovery_present: bool
    recovery_sha256: str | None
    schema: str = PUBLISHER_REPLAY_RECOVERY_STATE_V1_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PUBLISHER_REPLAY_RECOVERY_STATE_V1_SCHEMA:
            raise PublisherAuthorizationError(
                "unsupported publisher replay recovery state schema"
            )
        _hex(self.lease_sha256, name="recovery state lease hash")
        _hex(self.invocation_nonce, name="recovery state invocation nonce")
        _identifier(self.ledger_id, name="recovery state ledger ID")
        _utc(self.observed_at_utc, name="recovery state observation time")
        allowed_states = set().union(*_ACTION_STATES.values()) | {
            "absent", "tombstoned", "conflict"
        }
        if self.state not in allowed_states:
            raise PublisherAuthorizationError(
                "publisher replay recovery state is invalid"
            )
        _optional_hash(
            self.final_sha256,
            present=self.final_present,
            name="final replay entry",
        )
        _optional_hash(
            self.pending_sha256,
            present=self.pending_present,
            name="pending replay entry",
        )
        _optional_hash(
            self.reservation_sha256,
            present=self.reservation_present,
            name="replay reservation",
        )
        _optional_hash(
            self.recovery_sha256,
            present=self.recovery_present,
            name="recovery receipt",
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "PublisherReplayRecoveryStateV1":
        data = _strict(
            value,
            name="publisher replay recovery state",
            fields={
                "schema",
                "lease_sha256",
                "invocation_nonce",
                "ledger_id",
                "observed_at_utc",
                "state",
                "final_present",
                "final_sha256",
                "pending_present",
                "pending_sha256",
                "reservation_present",
                "reservation_sha256",
                "recovery_present",
                "recovery_sha256",
            },
        )
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "lease_sha256": self.lease_sha256,
            "invocation_nonce": self.invocation_nonce,
            "ledger_id": self.ledger_id,
            "observed_at_utc": self.observed_at_utc,
            "state": self.state,
            "final_present": self.final_present,
            "final_sha256": self.final_sha256,
            "pending_present": self.pending_present,
            "pending_sha256": self.pending_sha256,
            "reservation_present": self.reservation_present,
            "reservation_sha256": self.reservation_sha256,
            "recovery_present": self.recovery_present,
            "recovery_sha256": self.recovery_sha256,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def build_publisher_replay_recovery_authorization_payload(
    *,
    state: PublisherReplayRecoveryStateV1,
    action: str,
    requested_at_utc: str,
    expires_at_utc: str,
    operator_actor_id: str,
    operator_system_id: str,
    operator_key_id: str,
    reviewer_actor_id: str,
    reviewer_system_id: str,
    reviewer_key_id: str,
) -> bytes:
    if not isinstance(state, PublisherReplayRecoveryStateV1):
        raise PublisherAuthorizationError(
            "recovery authorization requires an exact durable state"
        )
    if action not in _ACTION_STATES or state.state not in _ACTION_STATES[action]:
        raise PublisherAuthorizationError(
            "recovery action is not valid for the observed durable state"
        )
    requested = _utc(requested_at_utc, name="recovery request time")
    expires = _utc(expires_at_utc, name="recovery authorization expiry")
    observed = _utc(state.observed_at_utc, name="recovery state observation time")
    if observed > requested or expires <= requested:
        raise PublisherAuthorizationError(
            "recovery authorization time ordering is invalid"
        )
    if (expires - requested).total_seconds() > _MAX_RECOVERY_SECONDS:
        raise PublisherAuthorizationError(
            "recovery authorization exceeds ten minutes"
        )
    operator = _actor(operator_actor_id, name="recovery operator")
    reviewer = _actor(reviewer_actor_id, name="recovery reviewer")
    operator_system = _identifier(
        operator_system_id, name="recovery operator system"
    )
    reviewer_system = _identifier(
        reviewer_system_id, name="recovery reviewer system"
    )
    operator_key = _identifier(operator_key_id, name="recovery operator key")
    reviewer_key = _identifier(reviewer_key_id, name="recovery reviewer key")
    if (
        operator == reviewer
        or operator_system == reviewer_system
        or operator_key == reviewer_key
    ):
        raise PublisherAuthorizationError(
            "recovery operator and reviewer must be independent"
        )
    payload = {
        "schema": _RECOVERY_PAYLOAD_SCHEMA,
        "state": state.to_dict(),
        "state_sha256": state.sha256,
        "action": action,
        "requested_at_utc": requested_at_utc,
        "expires_at_utc": expires_at_utc,
        "operator_actor_id": operator,
        "operator_system_id": operator_system,
        "operator_key_id": operator_key,
        "reviewer_actor_id": reviewer,
        "reviewer_system_id": reviewer_system,
        "reviewer_key_id": reviewer_key,
        "recovery_policy_sha256": publisher_replay_recovery_policy_sha256(),
        "custody_policy_sha256": (
            asymmetric_authority_key_custody_policy_sha256()
        ),
        "nonce_reusable": False,
    }
    return _canonical(payload).encode("utf-8")


@dataclass(frozen=True, slots=True)
class PublisherReplayRecoveryAuthorizationV1:
    state: PublisherReplayRecoveryStateV1
    state_sha256: str
    action: str
    requested_at_utc: str
    expires_at_utc: str
    operator_actor_id: str
    operator_system_id: str
    operator_key_id: str
    reviewer_actor_id: str
    reviewer_system_id: str
    reviewer_key_id: str
    recovery_policy_sha256: str
    custody_policy_sha256: str
    operator_signature: DetachedEd25519AuthoritySignature
    reviewer_signature: DetachedEd25519AuthoritySignature
    nonce_reusable: bool = False
    schema: str = PUBLISHER_REPLAY_RECOVERY_AUTHORIZATION_V1_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PUBLISHER_REPLAY_RECOVERY_AUTHORIZATION_V1_SCHEMA:
            raise PublisherAuthorizationError(
                "unsupported publisher replay recovery authorization schema"
            )
        if not isinstance(self.state, PublisherReplayRecoveryStateV1):
            raise PublisherAuthorizationError(
                "recovery authorization state is invalid"
            )
        _hex(self.state_sha256, name="recovery authorization state hash")
        if self.state_sha256 != self.state.sha256:
            raise PublisherAuthorizationError(
                "recovery authorization state hash is inconsistent"
            )
        expected_payload = build_publisher_replay_recovery_authorization_payload(
            state=self.state,
            action=self.action,
            requested_at_utc=self.requested_at_utc,
            expires_at_utc=self.expires_at_utc,
            operator_actor_id=self.operator_actor_id,
            operator_system_id=self.operator_system_id,
            operator_key_id=self.operator_key_id,
            reviewer_actor_id=self.reviewer_actor_id,
            reviewer_system_id=self.reviewer_system_id,
            reviewer_key_id=self.reviewer_key_id,
        )
        payload = self.unsigned_payload()
        if payload != expected_payload:
            raise PublisherAuthorizationError(
                "recovery authorization payload is inconsistent"
            )
        if not isinstance(
            self.operator_signature, DetachedEd25519AuthoritySignature
        ) or not isinstance(
            self.reviewer_signature, DetachedEd25519AuthoritySignature
        ):
            raise PublisherAuthorizationError(
                "recovery authorization signatures are invalid"
            )
        for signature, actor, system, key, role in (
            (
                self.operator_signature,
                self.operator_actor_id,
                self.operator_system_id,
                self.operator_key_id,
                "operator",
            ),
            (
                self.reviewer_signature,
                self.reviewer_actor_id,
                self.reviewer_system_id,
                self.reviewer_key_id,
                "reviewer",
            ),
        ):
            if (
                signature.issuer_actor_id != actor
                or signature.issuer_system_id != system
                or signature.key_id != key
                or signature.payload_sha256
                != hashlib.sha256(payload).hexdigest()
            ):
                raise PublisherAuthorizationError(
                    f"recovery {role} signature binding is inconsistent"
                )
        if (
            self.operator_actor_id == self.reviewer_actor_id
            or self.operator_system_id == self.reviewer_system_id
            or self.operator_key_id == self.reviewer_key_id
        ):
            raise PublisherAuthorizationError(
                "recovery operator and reviewer must be independent"
            )
        if self.nonce_reusable is not False:
            raise PublisherAuthorizationError(
                "recovery authorization can never make a nonce reusable"
            )

    @classmethod
    def from_signed_payload(
        cls,
        *,
        unsigned_payload: bytes,
        operator_signature: DetachedEd25519AuthoritySignature,
        reviewer_signature: DetachedEd25519AuthoritySignature,
    ) -> "PublisherReplayRecoveryAuthorizationV1":
        if not isinstance(unsigned_payload, bytes):
            raise PublisherAuthorizationError(
                "recovery authorization payload must be bytes"
            )
        try:
            data = json.loads(unsigned_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PublisherAuthorizationError(
                "recovery authorization payload is invalid"
            ) from exc
        if (
            not isinstance(data, Mapping)
            or _canonical(data).encode("utf-8") != unsigned_payload
        ):
            raise PublisherAuthorizationError(
                "recovery authorization payload is not canonical"
            )
        data = _strict(
            data,
            name="recovery authorization payload",
            fields={
                "schema",
                "state",
                "state_sha256",
                "action",
                "requested_at_utc",
                "expires_at_utc",
                "operator_actor_id",
                "operator_system_id",
                "operator_key_id",
                "reviewer_actor_id",
                "reviewer_system_id",
                "reviewer_key_id",
                "recovery_policy_sha256",
                "custody_policy_sha256",
                "nonce_reusable",
            },
        )
        if data["schema"] != _RECOVERY_PAYLOAD_SCHEMA:
            raise PublisherAuthorizationError(
                "unsupported recovery authorization payload schema"
            )
        expected = build_publisher_replay_recovery_authorization_payload(
            state=PublisherReplayRecoveryStateV1.from_mapping(data["state"]),
            action=data["action"],
            requested_at_utc=data["requested_at_utc"],
            expires_at_utc=data["expires_at_utc"],
            operator_actor_id=data["operator_actor_id"],
            operator_system_id=data["operator_system_id"],
            operator_key_id=data["operator_key_id"],
            reviewer_actor_id=data["reviewer_actor_id"],
            reviewer_system_id=data["reviewer_system_id"],
            reviewer_key_id=data["reviewer_key_id"],
        )
        if expected != unsigned_payload:
            raise PublisherAuthorizationError(
                "recovery authorization payload is inconsistent"
            )
        return cls(
            state=PublisherReplayRecoveryStateV1.from_mapping(data["state"]),
            state_sha256=data["state_sha256"],
            action=data["action"],
            requested_at_utc=data["requested_at_utc"],
            expires_at_utc=data["expires_at_utc"],
            operator_actor_id=data["operator_actor_id"],
            operator_system_id=data["operator_system_id"],
            operator_key_id=data["operator_key_id"],
            reviewer_actor_id=data["reviewer_actor_id"],
            reviewer_system_id=data["reviewer_system_id"],
            reviewer_key_id=data["reviewer_key_id"],
            recovery_policy_sha256=data["recovery_policy_sha256"],
            custody_policy_sha256=data["custody_policy_sha256"],
            operator_signature=operator_signature,
            reviewer_signature=reviewer_signature,
            nonce_reusable=data["nonce_reusable"],
        )

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PublisherReplayRecoveryAuthorizationV1":
        data = _strict(
            value,
            name="publisher replay recovery authorization",
            fields={
                "schema",
                "state",
                "state_sha256",
                "action",
                "requested_at_utc",
                "expires_at_utc",
                "operator_actor_id",
                "operator_system_id",
                "operator_key_id",
                "reviewer_actor_id",
                "reviewer_system_id",
                "reviewer_key_id",
                "recovery_policy_sha256",
                "custody_policy_sha256",
                "operator_signature",
                "reviewer_signature",
                "nonce_reusable",
            },
        )
        return cls(
            schema=data["schema"],
            state=PublisherReplayRecoveryStateV1.from_mapping(data["state"]),
            state_sha256=data["state_sha256"],
            action=data["action"],
            requested_at_utc=data["requested_at_utc"],
            expires_at_utc=data["expires_at_utc"],
            operator_actor_id=data["operator_actor_id"],
            operator_system_id=data["operator_system_id"],
            operator_key_id=data["operator_key_id"],
            reviewer_actor_id=data["reviewer_actor_id"],
            reviewer_system_id=data["reviewer_system_id"],
            reviewer_key_id=data["reviewer_key_id"],
            recovery_policy_sha256=data["recovery_policy_sha256"],
            custody_policy_sha256=data["custody_policy_sha256"],
            operator_signature=DetachedEd25519AuthoritySignature.from_mapping(
                data["operator_signature"]
            ),
            reviewer_signature=DetachedEd25519AuthoritySignature.from_mapping(
                data["reviewer_signature"]
            ),
            nonce_reusable=data["nonce_reusable"],
        )

    def _payload_mapping(self) -> dict[str, Any]:
        return {
            "schema": _RECOVERY_PAYLOAD_SCHEMA,
            "state": self.state.to_dict(),
            "state_sha256": self.state_sha256,
            "action": self.action,
            "requested_at_utc": self.requested_at_utc,
            "expires_at_utc": self.expires_at_utc,
            "operator_actor_id": self.operator_actor_id,
            "operator_system_id": self.operator_system_id,
            "operator_key_id": self.operator_key_id,
            "reviewer_actor_id": self.reviewer_actor_id,
            "reviewer_system_id": self.reviewer_system_id,
            "reviewer_key_id": self.reviewer_key_id,
            "recovery_policy_sha256": self.recovery_policy_sha256,
            "custody_policy_sha256": self.custody_policy_sha256,
            "nonce_reusable": self.nonce_reusable,
        }

    def unsigned_payload(self) -> bytes:
        return _canonical(self._payload_mapping()).encode("utf-8")

    def to_dict(self) -> dict[str, Any]:
        data = self._payload_mapping()
        data["schema"] = self.schema
        data["operator_signature"] = self.operator_signature.to_dict()
        data["reviewer_signature"] = self.reviewer_signature.to_dict()
        return data

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class PublisherReplayRecoveryAuthorizationVerifierV1:
    def __init__(
        self,
        *,
        operator_verifier: Ed25519AuthorityVerifier,
        reviewer_verifier: Ed25519AuthorityVerifier,
    ) -> None:
        if not isinstance(operator_verifier, Ed25519AuthorityVerifier):
            raise PublisherAuthorizationError(
                "recovery operator verifier must be Ed25519"
            )
        if not isinstance(reviewer_verifier, Ed25519AuthorityVerifier):
            raise PublisherAuthorizationError(
                "recovery reviewer verifier must be Ed25519"
            )
        self._operator_verifier = operator_verifier
        self._reviewer_verifier = reviewer_verifier

    def verify(
        self,
        *,
        authorization: PublisherReplayRecoveryAuthorizationV1,
        lease: AsymmetricPublisherAuthorizationLease,
        current_state: PublisherReplayRecoveryStateV1,
        at_utc: str,
    ) -> PublisherReplayRecoveryAuthorizationV1:
        if not isinstance(
            authorization, PublisherReplayRecoveryAuthorizationV1
        ):
            raise PublisherAuthorizationError(
                "recovery requires authenticated authorization"
            )
        if not isinstance(lease, AsymmetricPublisherAuthorizationLease):
            raise PublisherAuthorizationError(
                "recovery authorization lease is invalid"
            )
        if authorization.state.canonical_json() != current_state.canonical_json():
            raise PublisherAuthorizationError(
                "durable recovery state changed after authorization"
            )
        if (
            current_state.lease_sha256 != lease.sha256
            or current_state.invocation_nonce != lease.invocation_nonce
        ):
            raise PublisherAuthorizationError(
                "recovery authorization is bound to another lease"
            )
        if (
            authorization.recovery_policy_sha256
            != publisher_replay_recovery_policy_sha256()
            or authorization.custody_policy_sha256
            != asymmetric_authority_key_custody_policy_sha256()
        ):
            raise PublisherAuthorizationError(
                "recovery authorization policy is unsupported"
            )
        requested = _utc(
            authorization.requested_at_utc, name="recovery request time"
        )
        expires = _utc(
            authorization.expires_at_utc,
            name="recovery authorization expiry",
        )
        observed = _utc(
            authorization.state.observed_at_utc,
            name="recovery state observation time",
        )
        verified = _utc(at_utc, name="recovery verification time")
        if not (observed <= requested <= verified < expires):
            raise PublisherAuthorizationError(
                "recovery authorization is not currently valid"
            )
        payload = authorization.unsigned_payload()
        try:
            self._operator_verifier.verify(
                payload=payload,
                signature=authorization.operator_signature,
                at_utc=at_utc,
            )
            self._reviewer_verifier.verify(
                payload=payload,
                signature=authorization.reviewer_signature,
                at_utc=at_utc,
            )
        except AsymmetricAuthorityError as exc:
            raise PublisherAuthorizationError(
                f"recovery signature verification failed: {exc}"
            ) from exc
        request = lease.signed_request.request
        excluded = {
            request.publisher_actor_id,
            lease.issuer_actor_id,
            request.readiness.semantic_review_request.developer_actor_id,
            request.readiness.reviewer_actor_id,
        }
        if (
            authorization.operator_actor_id in excluded
            or authorization.reviewer_actor_id in excluded
        ):
            raise PublisherAuthorizationError(
                "recovery actors must be separate from prior authority roles"
            )
        return authorization


class PublisherReplayLedgerV3(_PublisherReplayLedgerV2):
    """H6 ledger: recovery requires dual asymmetric authorization."""

    def observe_recovery_state(
        self,
        *,
        lease: AsymmetricPublisherAuthorizationLease,
        observed_at_utc: str,
    ) -> PublisherReplayRecoveryStateV1:
        if not isinstance(lease, AsymmetricPublisherAuthorizationLease):
            raise PublisherAuthorizationError(
                "recovery state lease is invalid"
            )
        _utc(observed_at_utc, name="recovery state observation time")
        final, pending, reservation, recovery = self._paths(
            lease.invocation_nonce
        )
        final_present, final_sha = _file_hash(final)
        pending_present, pending_sha = _file_hash(pending)
        reservation_present, reservation_sha = _file_hash(reservation)
        recovery_present, recovery_sha = _file_hash(recovery)
        return PublisherReplayRecoveryStateV1(
            lease_sha256=lease.sha256,
            invocation_nonce=lease.invocation_nonce,
            ledger_id=self._ledger_id,
            observed_at_utc=observed_at_utc,
            state=self._state(lease.invocation_nonce),
            final_present=final_present,
            final_sha256=final_sha,
            pending_present=pending_present,
            pending_sha256=pending_sha,
            reservation_present=reservation_present,
            reservation_sha256=reservation_sha,
            recovery_present=recovery_present,
            recovery_sha256=recovery_sha,
        )

    def recover(self, **_: Any) -> PublisherReplayRecoveryReceiptV2:
        raise PublisherAuthorizationError(
            "unauthenticated recovery is disabled; use recover_authenticated"
        )

    def recover_authenticated(
        self,
        *,
        lease: AsymmetricPublisherAuthorizationLease,
        authorization: PublisherReplayRecoveryAuthorizationV1,
        authorization_verifier: PublisherReplayRecoveryAuthorizationVerifierV1,
        recovered_at_utc: str,
    ) -> PublisherReplayRecoveryReceiptV2:
        if not isinstance(
            authorization_verifier,
            PublisherReplayRecoveryAuthorizationVerifierV1,
        ):
            raise PublisherAuthorizationError(
                "recovery requires the dual Ed25519 verifier"
            )
        current_state = self.observe_recovery_state(
            lease=lease,
            observed_at_utc=authorization.state.observed_at_utc,
        )
        authorization_verifier.verify(
            authorization=authorization,
            lease=lease,
            current_state=current_state,
            at_utc=recovered_at_utc,
        )
        auth_path = (
            self._root
            / f"{lease.invocation_nonce}.v2.recovery-authorization.json"
        )
        payload = authorization.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PublisherAuthorizationError(
                "recovery authorization exceeds its byte bound"
            )
        if auth_path.exists():
            if (
                auth_path.is_symlink()
                or not auth_path.is_file()
                or auth_path.read_bytes() != payload
            ):
                raise PublisherAuthorizationError(
                    "recovery authorization conflicts with durable evidence"
                )
        else:
            try:
                create_once_file(auth_path, payload)
            except (FileExistsError, DurablePublicationError) as exc:
                raise PublisherAuthorizationError(
                    "recovery authorization was not durably published"
                ) from exc
        return super().recover(
            lease=lease,
            action=authorization.action,
            recovery_authorization_sha256=authorization.sha256,
            operator_actor_id=authorization.operator_actor_id,
            recovered_at_utc=recovered_at_utc,
        )


def load_publisher_replay_recovery_authorization_v1(
    path: Path,
) -> PublisherReplayRecoveryAuthorizationV1:
    output = Path(path)
    if (
        not output.is_absolute()
        or output.is_symlink()
        or not output.is_file()
        or _has_linkish_component(output.parent)
    ):
        raise PublisherAuthorizationError(
            "recovery authorization path is unsafe"
        )
    payload = output.read_bytes()
    if len(payload) > _MAX_ARTIFACT_BYTES:
        raise PublisherAuthorizationError(
            "recovery authorization exceeds its byte bound"
        )
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublisherAuthorizationError(
            "recovery authorization is invalid"
        ) from exc
    value = PublisherReplayRecoveryAuthorizationV1.from_mapping(data)
    if value.canonical_json().encode("utf-8") != payload:
        raise PublisherAuthorizationError(
            "recovery authorization is not canonical"
        )
    return value


def write_publisher_replay_recovery_authorization_v1(
    path: Path,
    authorization: PublisherReplayRecoveryAuthorizationV1,
) -> str:
    if not isinstance(
        authorization, PublisherReplayRecoveryAuthorizationV1
    ):
        raise PublisherAuthorizationError(
            "recovery authorization output is invalid"
        )
    output = Path(path)
    if (
        not output.is_absolute()
        or output.exists()
        or not output.parent.is_dir()
        or _has_linkish_component(output.parent)
    ):
        raise PublisherAuthorizationError(
            "recovery authorization output path is unsafe or exists"
        )
    payload = authorization.canonical_json().encode("utf-8")
    try:
        create_once_file(output, payload)
    except (FileExistsError, DurablePublicationError) as exc:
        raise PublisherAuthorizationError(
            "recovery authorization could not be durably published"
        ) from exc
    return authorization.sha256


__all__ = [
    "PUBLISHER_REPLAY_RECOVERY_STATE_V1_SCHEMA",
    "PUBLISHER_REPLAY_RECOVERY_AUTHORIZATION_V1_SCHEMA",
    "PUBLISHER_REPLAY_RECOVERY_POLICY",
    "PublisherReplayRecoveryStateV1",
    "PublisherReplayRecoveryAuthorizationV1",
    "PublisherReplayRecoveryAuthorizationVerifierV1",
    "PublisherReplayLedgerV3",
    "build_publisher_replay_recovery_authorization_payload",
    "publisher_replay_recovery_policy_sha256",
    "load_publisher_replay_recovery_authorization_v1",
    "write_publisher_replay_recovery_authorization_v1",
]
