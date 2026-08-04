"""Crash-durable, fail-closed publisher nonce consumption and recovery."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ._publisher_authorization_legacy import (
    PublisherAuthorizationError,
    PublisherAuthorizationLease,
    PublisherAuthorizationVerifier,
    PublisherReplayLedgerEntry,
    PublisherRequestVerifier,
    SemanticReviewVerifier,
    _MAX_ARTIFACT_BYTES,
    _actor,
    _canonical,
    _has_linkish_component,
    _hex,
    _identifier,
    _load_canonical,
    _sha256_bytes,
    _strict,
    _utc,
)
from .contract import DevelopmentTask
from .durable_publication import (
    DurablePublicationError,
    create_once_file,
    unlink_durable,
)

PUBLISHER_REPLAY_RECOVERY_SCHEMA = (
    "kaliv-development-publisher-replay-recovery-receipt/v1"
)
_ACTIONS = {"finalize_prepared", "acknowledge_committed", "tombstone_uncertain"}
_STATES = {
    "absent",
    "reserved",
    "partial",
    "prepared",
    "committed",
    "committed_locked",
    "tombstoned",
    "conflict",
}


@dataclass(frozen=True, slots=True)
class PublisherReplayRecoveryReceipt:
    lease_sha256: str
    invocation_nonce: str
    ledger_id: str
    recovery_authorization_sha256: str
    operator_actor_id: str
    recovered_at_utc: str
    action: str
    state_before: str
    state_after: str
    entry_verified: bool
    nonce_reusable: bool = False
    schema: str = PUBLISHER_REPLAY_RECOVERY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PUBLISHER_REPLAY_RECOVERY_SCHEMA:
            raise PublisherAuthorizationError("unsupported replay recovery schema")
        _hex(self.lease_sha256, name="replay recovery lease hash")
        _hex(self.invocation_nonce, name="replay recovery invocation nonce")
        _identifier(self.ledger_id, name="replay recovery ledger ID")
        _hex(
            self.recovery_authorization_sha256,
            name="replay recovery authorization hash",
        )
        _actor(self.operator_actor_id, name="replay recovery operator")
        _utc(self.recovered_at_utc, name="replay recovery time")
        if self.action not in _ACTIONS:
            raise PublisherAuthorizationError("replay recovery action is invalid")
        if self.state_before not in _STATES or self.state_after not in _STATES:
            raise PublisherAuthorizationError("replay recovery state is invalid")
        if not isinstance(self.entry_verified, bool):
            raise PublisherAuthorizationError("replay recovery verification flag is invalid")
        if self.nonce_reusable is not False:
            raise PublisherAuthorizationError("replay recovery can never make a nonce reusable")
        if self.action == "tombstone_uncertain":
            if self.state_after != "tombstoned" or self.entry_verified is not False:
                raise PublisherAuthorizationError("replay tombstone receipt is inconsistent")
        elif self.state_after != "committed" or self.entry_verified is not True:
            raise PublisherAuthorizationError("replay commit recovery receipt is inconsistent")

    @classmethod
    def from_mapping(cls, value: Any) -> "PublisherReplayRecoveryReceipt":
        fields = {
            "schema",
            "lease_sha256",
            "invocation_nonce",
            "ledger_id",
            "recovery_authorization_sha256",
            "operator_actor_id",
            "recovered_at_utc",
            "action",
            "state_before",
            "state_after",
            "entry_verified",
            "nonce_reusable",
        }
        data = _strict(value, name="replay recovery receipt", fields=fields)
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "lease_sha256": self.lease_sha256,
            "invocation_nonce": self.invocation_nonce,
            "ledger_id": self.ledger_id,
            "recovery_authorization_sha256": self.recovery_authorization_sha256,
            "operator_actor_id": self.operator_actor_id,
            "recovered_at_utc": self.recovered_at_utc,
            "action": self.action,
            "state_before": self.state_before,
            "state_after": self.state_after,
            "entry_verified": self.entry_verified,
            "nonce_reusable": self.nonce_reusable,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_bytes(self.canonical_json().encode("utf-8"))


class PublisherReplayLedger:
    """Durable nonce ledger whose uncertain crash states remain consumed."""

    def __init__(self, *, root: Path, ledger_id: str) -> None:
        self._root = Path(root)
        self._ledger_id = _identifier(ledger_id, name="publisher replay ledger ID")
        if (
            not self._root.is_absolute()
            or not self._root.is_dir()
            or _has_linkish_component(self._root)
        ):
            raise PublisherAuthorizationError(
                "publisher replay ledger root must be an absolute link-free directory"
            )
        self._root = self._root.resolve()

    def _paths(self, invocation_nonce: str) -> tuple[Path, Path, Path, Path]:
        nonce = _hex(invocation_nonce, name="invocation nonce")
        return (
            self._root / f"{nonce}.json",
            self._root / f".{nonce}.pending.json",
            self._root / f".{nonce}.lock",
            self._root / f"{nonce}.recovery.json",
        )

    def _entry(self, path: Path) -> PublisherReplayLedgerEntry:
        entry = _load_canonical(
            path,
            PublisherReplayLedgerEntry.from_mapping,
            name="publisher replay ledger entry",
        )
        if entry.ledger_id != self._ledger_id:
            raise PublisherAuthorizationError(
                "replay ledger entry belongs to another ledger"
            )
        return entry

    def _state(self, invocation_nonce: str) -> str:
        final, pending, lock, recovery = self._paths(invocation_nonce)
        if final.exists():
            try:
                self._entry(final)
            except PublisherAuthorizationError:
                return "conflict"
            return "committed_locked" if pending.exists() or lock.exists() else "committed"
        if recovery.exists():
            try:
                receipt = _load_canonical(
                    recovery,
                    PublisherReplayRecoveryReceipt.from_mapping,
                    name="publisher replay recovery receipt",
                )
            except PublisherAuthorizationError:
                return "conflict"
            if (
                receipt.invocation_nonce != invocation_nonce
                or receipt.ledger_id != self._ledger_id
                or receipt.state_after != "tombstoned"
            ):
                return "conflict"
            return "tombstoned"
        if pending.exists():
            try:
                self._entry(pending)
            except PublisherAuthorizationError:
                return "partial"
            return "prepared"
        return "reserved" if lock.exists() else "absent"

    def consume_once(
        self,
        *,
        lease: PublisherAuthorizationLease,
        task: DevelopmentTask,
        authorization_verifier: PublisherAuthorizationVerifier,
        publisher_verifier: PublisherRequestVerifier,
        semantic_verifier: SemanticReviewVerifier,
        control_plane_root: Path,
        consumed_at_utc: str,
    ) -> PublisherReplayLedgerEntry:
        if not isinstance(authorization_verifier, PublisherAuthorizationVerifier):
            raise PublisherAuthorizationError(
                "replay consumption requires an authorization verifier"
            )
        authorization_verifier.verify(
            lease=lease,
            task=task,
            publisher_verifier=publisher_verifier,
            semantic_verifier=semantic_verifier,
            control_plane_root=Path(control_plane_root),
            at_utc=consumed_at_utc,
        )
        entry = PublisherReplayLedgerEntry.from_lease(
            lease=lease,
            ledger_id=self._ledger_id,
            consumed_at_utc=consumed_at_utc,
        )
        entry.verify_against(lease)
        payload = entry.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PublisherAuthorizationError(
                "replay ledger entry exceeds its byte bound"
            )
        final, pending, lock, recovery = self._paths(lease.invocation_nonce)
        if any(path.exists() or path.is_symlink() for path in (final, pending, lock, recovery)):
            raise PublisherAuthorizationError(
                "invocation nonce has already been consumed or requires recovery"
            )
        reservation = _canonical(
            {
                "schema": "kaliv-development-publisher-replay-reservation/v1",
                "lease_sha256": lease.sha256,
                "invocation_nonce": lease.invocation_nonce,
                "ledger_id": self._ledger_id,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, reservation)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PublisherAuthorizationError(
                "invocation nonce has already been consumed or could not be durably reserved"
            ) from exc
        try:
            create_once_file(pending, payload)
            create_once_file(final, payload)
            verified = self._entry(final)
            verified.verify_against(lease)
            unlink_durable(pending)
            unlink_durable(lock)
        except Exception as exc:
            raise PublisherAuthorizationError(
                "nonce consumption is durable but requires explicit recovery"
            ) from exc
        return entry

    def load(self, invocation_nonce: str) -> PublisherReplayLedgerEntry:
        final, _, _, _ = self._paths(invocation_nonce)
        if final.exists():
            return self._entry(final)
        state = self._state(invocation_nonce)
        if state != "absent":
            raise PublisherAuthorizationError(
                "invocation nonce is consumed but has no usable entry"
            )
        raise PublisherAuthorizationError("publisher replay ledger entry is missing")

    def recover(
        self,
        *,
        lease: PublisherAuthorizationLease,
        action: str,
        recovery_authorization_sha256: str,
        operator_actor_id: str,
        recovered_at_utc: str,
    ) -> PublisherReplayRecoveryReceipt:
        if not isinstance(lease, PublisherAuthorizationLease):
            raise PublisherAuthorizationError("replay recovery lease is invalid")
        if action not in _ACTIONS:
            raise PublisherAuthorizationError("replay recovery action is invalid")
        authorization = _hex(
            recovery_authorization_sha256,
            name="replay recovery authorization hash",
        )
        operator = _actor(operator_actor_id, name="replay recovery operator")
        _utc(recovered_at_utc, name="replay recovery time")
        nonce = lease.invocation_nonce
        final, pending, lock, recovery = self._paths(nonce)
        state_before = self._state(nonce)

        if action == "finalize_prepared":
            if state_before != "prepared":
                raise PublisherAuthorizationError(
                    "finalize recovery requires one verified prepared entry"
                )
            entry = self._entry(pending)
            entry.verify_against(lease)
            payload = entry.canonical_json().encode("utf-8")
            try:
                create_once_file(final, payload)
                self._entry(final).verify_against(lease)
                unlink_durable(pending)
                unlink_durable(lock)
            except (FileExistsError, DurablePublicationError) as exc:
                raise PublisherAuthorizationError(
                    "replay finalize recovery was not durable"
                ) from exc
            state_after = "committed"
            verified = True
        elif action == "acknowledge_committed":
            if state_before not in {"committed", "committed_locked"}:
                raise PublisherAuthorizationError(
                    "commit acknowledgement requires a verified committed entry"
                )
            self._entry(final).verify_against(lease)
            try:
                unlink_durable(pending)
                unlink_durable(lock)
            except DurablePublicationError as exc:
                raise PublisherAuthorizationError(
                    "replay commit cleanup was not durable"
                ) from exc
            state_after = "committed"
            verified = True
        else:
            if state_before not in {"reserved", "partial"}:
                raise PublisherAuthorizationError(
                    "tombstone recovery requires uncertain consumed state"
                )
            receipt = PublisherReplayRecoveryReceipt(
                lease_sha256=lease.sha256,
                invocation_nonce=nonce,
                ledger_id=self._ledger_id,
                recovery_authorization_sha256=authorization,
                operator_actor_id=operator,
                recovered_at_utc=recovered_at_utc,
                action=action,
                state_before=state_before,
                state_after="tombstoned",
                entry_verified=False,
            )
            try:
                create_once_file(
                    recovery,
                    receipt.canonical_json().encode("utf-8"),
                )
            except (FileExistsError, DurablePublicationError) as exc:
                raise PublisherAuthorizationError(
                    "replay tombstone recovery was not durable"
                ) from exc
            try:
                unlink_durable(pending)
                unlink_durable(lock)
            except DurablePublicationError:
                pass
            if self._state(nonce) != "tombstoned":
                raise PublisherAuthorizationError(
                    "replay tombstone recovery postcondition failed"
                )
            return receipt

        receipt = PublisherReplayRecoveryReceipt(
            lease_sha256=lease.sha256,
            invocation_nonce=nonce,
            ledger_id=self._ledger_id,
            recovery_authorization_sha256=authorization,
            operator_actor_id=operator,
            recovered_at_utc=recovered_at_utc,
            action=action,
            state_before=state_before,
            state_after=state_after,
            entry_verified=verified,
        )
        if recovery.exists():
            existing = _load_canonical(
                recovery,
                PublisherReplayRecoveryReceipt.from_mapping,
                name="publisher replay recovery receipt",
            )
            if existing.canonical_json() != receipt.canonical_json():
                raise PublisherAuthorizationError(
                    "replay recovery receipt conflicts with existing evidence"
                )
        else:
            try:
                create_once_file(
                    recovery,
                    receipt.canonical_json().encode("utf-8"),
                )
            except (FileExistsError, DurablePublicationError) as exc:
                raise PublisherAuthorizationError(
                    "replay recovery receipt was not durably published"
                ) from exc
        if self._state(nonce) != "committed":
            raise PublisherAuthorizationError("replay recovery postcondition failed")
        return receipt
