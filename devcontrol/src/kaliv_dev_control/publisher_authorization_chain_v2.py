"""Ed25519-authorized downstream publisher evidence chain (H5C).

This module versions replay, preflight, postcondition and recovery evidence for
``kaliv-development-publisher-authorization-lease/v2``.  It preserves the
crash-durable, one-time nonce semantics from H4 while accepting only the
verification-only Ed25519 authority boundary from H5A/H5B.

No private key, shared secret, credential, Git transport, network client,
repository writer, pull-request writer, merge, release or deployment capability
is accepted or implemented here.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._publisher_authorization_legacy import (
    PublisherAuthorizationError,
    PublisherPostconditionReceipt as _LegacyPublisherPostconditionReceipt,
    PublisherPreflightReceipt as _LegacyPublisherPreflightReceipt,
    PublisherReplayLedgerEntry as _LegacyPublisherReplayLedgerEntry,
    PublisherAuthorizationVerifier as _LegacyPublisherAuthorizationVerifier,
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
from .asymmetric_authority import AsymmetricAuthorityError
from .contract import DevelopmentTask
from .durable_publication import (
    DurablePublicationError,
    create_once_file,
    unlink_durable,
)
from .publisher_authorization_v2 import (
    AsymmetricPublisherAuthorizationLease,
    AsymmetricPublisherAuthorizationVerifier,
)

PUBLISHER_REPLAY_LEDGER_ENTRY_V2_SCHEMA = (
    "kaliv-development-publisher-replay-ledger-entry/v2"
)
PUBLISHER_PREFLIGHT_RECEIPT_V2_SCHEMA = (
    "kaliv-development-publisher-preflight-receipt/v2"
)
PUBLISHER_POSTCONDITION_RECEIPT_V2_SCHEMA = (
    "kaliv-development-publisher-postcondition-receipt/v2"
)
PUBLISHER_REPLAY_RECOVERY_V2_SCHEMA = (
    "kaliv-development-publisher-replay-recovery-receipt/v2"
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


class PublisherAuthorizationVerifierV2(_LegacyPublisherAuthorizationVerifier):
    """Legacy-interface-compatible wrapper around the public-key-only verifier.

    Subclassing the former verifier preserves the already-proven local
    materialization type boundary without granting the wrapper any HMAC keyring
    or shared-secret capability.
    """

    def __init__(
        self,
        verifier: AsymmetricPublisherAuthorizationVerifier,
    ) -> None:
        if not isinstance(verifier, AsymmetricPublisherAuthorizationVerifier):
            raise PublisherAuthorizationError(
                "v2 authorization verifier requires the Ed25519 verifier"
            )
        self._delegate = verifier

    def verify(
        self,
        *,
        lease: AsymmetricPublisherAuthorizationLease,
        task: DevelopmentTask,
        publisher_verifier: PublisherRequestVerifier,
        semantic_verifier: SemanticReviewVerifier,
        control_plane_root: Path,
        at_utc: str,
    ) -> AsymmetricPublisherAuthorizationLease:
        if not isinstance(lease, AsymmetricPublisherAuthorizationLease):
            raise PublisherAuthorizationError(
                "v2 authorization verification requires a v2 lease"
            )
        try:
            return self._delegate.verify(
                lease=lease,
                task=task,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=Path(control_plane_root),
                at_utc=at_utc,
            )
        except PublisherAuthorizationError:
            raise
        except AsymmetricAuthorityError as exc:
            raise PublisherAuthorizationError(
                f"asymmetric authorization verification failed: {exc}"
            ) from exc


@dataclass(frozen=True, slots=True)
class PublisherReplayLedgerEntryV2(_LegacyPublisherReplayLedgerEntry):
    lease: AsymmetricPublisherAuthorizationLease
    schema: str = PUBLISHER_REPLAY_LEDGER_ENTRY_V2_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PUBLISHER_REPLAY_LEDGER_ENTRY_V2_SCHEMA:
            raise PublisherAuthorizationError(
                "unsupported publisher replay ledger v2 schema"
            )
        if not isinstance(self.lease, AsymmetricPublisherAuthorizationLease):
            raise PublisherAuthorizationError("replay ledger v2 lease is invalid")
        for name, value in (
            ("authorization lease hash", self.lease_sha256),
            ("signed publisher request hash", self.signed_request_sha256),
            ("publisher request hash", self.request_sha256),
            ("invocation nonce", self.invocation_nonce),
            ("remote repository hash", self.remote_repository_sha256),
            ("credential policy hash", self.credential_policy_sha256),
        ):
            _hex(value, name=name)
        _identifier(self.ledger_id, name="publisher replay ledger ID")
        _utc(self.consumed_at_utc, name="nonce consumption time")
        consumer = _actor(self.consumer_actor_id, name="nonce consumer actor")
        request = self.lease.signed_request.request
        if (
            self.lease_sha256 != self.lease.sha256
            or self.signed_request_sha256 != self.lease.signed_request_sha256
            or self.request_sha256 != self.lease.request_sha256
            or self.invocation_nonce != self.lease.invocation_nonce
            or self.remote_repository_sha256
            != self.lease.remote_repository_sha256
            or self.credential_policy_sha256
            != self.lease.credential_policy_sha256
            or consumer != request.publisher_actor_id
        ):
            raise PublisherAuthorizationError(
                "replay ledger v2 entry identities are inconsistent"
            )
        if (
            self.outcome != "consumed_once"
            or self.one_time is not True
            or self.maximum_uses != 1
        ):
            raise PublisherAuthorizationError(
                "replay ledger v2 outcome is invalid"
            )

    @classmethod
    def from_lease(
        cls,
        *,
        lease: AsymmetricPublisherAuthorizationLease,
        ledger_id: str,
        consumed_at_utc: str,
    ) -> "PublisherReplayLedgerEntryV2":
        if not isinstance(lease, AsymmetricPublisherAuthorizationLease):
            raise PublisherAuthorizationError(
                "replay ledger v2 requires a v2 lease"
            )
        request = lease.signed_request.request
        return cls(
            lease=lease,
            lease_sha256=lease.sha256,
            signed_request_sha256=lease.signed_request_sha256,
            request_sha256=lease.request_sha256,
            invocation_nonce=lease.invocation_nonce,
            remote_repository_sha256=lease.remote_repository_sha256,
            credential_policy_sha256=lease.credential_policy_sha256,
            ledger_id=ledger_id,
            consumed_at_utc=consumed_at_utc,
            consumer_actor_id=request.publisher_actor_id,
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "PublisherReplayLedgerEntryV2":
        fields = {
            "schema",
            "lease",
            "lease_sha256",
            "signed_request_sha256",
            "request_sha256",
            "invocation_nonce",
            "remote_repository_sha256",
            "credential_policy_sha256",
            "ledger_id",
            "consumed_at_utc",
            "consumer_actor_id",
            "outcome",
            "one_time",
            "maximum_uses",
        }
        data = _strict(
            value,
            name="publisher replay ledger v2 entry",
            fields=fields,
        )
        return cls(
            schema=data["schema"],
            lease=AsymmetricPublisherAuthorizationLease.from_mapping(
                data["lease"]
            ),
            lease_sha256=data["lease_sha256"],
            signed_request_sha256=data["signed_request_sha256"],
            request_sha256=data["request_sha256"],
            invocation_nonce=data["invocation_nonce"],
            remote_repository_sha256=data["remote_repository_sha256"],
            credential_policy_sha256=data["credential_policy_sha256"],
            ledger_id=data["ledger_id"],
            consumed_at_utc=data["consumed_at_utc"],
            consumer_actor_id=data["consumer_actor_id"],
            outcome=data["outcome"],
            one_time=data["one_time"],
            maximum_uses=data["maximum_uses"],
        )

    def verify_against(
        self,
        lease: AsymmetricPublisherAuthorizationLease,
    ) -> None:
        if (
            not isinstance(lease, AsymmetricPublisherAuthorizationLease)
            or lease.sha256 != self.lease_sha256
        ):
            raise PublisherAuthorizationError(
                "replay ledger v2 entry is bound to another lease"
            )
        if self.lease.canonical_json() != lease.canonical_json():
            raise PublisherAuthorizationError(
                "replay ledger v2 embedded lease differs"
            )
        consumed = _utc(self.consumed_at_utc, name="nonce consumption time")
        issued = _utc(lease.issued_at_utc, name="lease issue time")
        expires = _utc(lease.expires_at_utc, name="lease expiry time")
        if consumed < issued or consumed >= expires:
            raise PublisherAuthorizationError(
                "nonce was consumed outside the v2 lease window"
            )


@dataclass(frozen=True, slots=True)
class PublisherPreflightReceiptV2(_LegacyPublisherPreflightReceipt):
    lease: AsymmetricPublisherAuthorizationLease
    replay_entry: PublisherReplayLedgerEntryV2
    schema: str = PUBLISHER_PREFLIGHT_RECEIPT_V2_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PUBLISHER_PREFLIGHT_RECEIPT_V2_SCHEMA:
            raise PublisherAuthorizationError(
                "unsupported publisher preflight v2 schema"
            )
        if not isinstance(self.lease, AsymmetricPublisherAuthorizationLease):
            raise PublisherAuthorizationError("preflight v2 lease is invalid")
        if not isinstance(self.replay_entry, PublisherReplayLedgerEntryV2):
            raise PublisherAuthorizationError(
                "preflight v2 replay entry is invalid"
            )
        for name, value in (
            ("authorization lease hash", self.lease_sha256),
            ("replay entry hash", self.replay_entry_sha256),
            ("signed publisher request hash", self.signed_request_sha256),
            ("publisher request hash", self.request_sha256),
            ("readiness hash", self.readiness_sha256),
            ("task hash", self.task_sha256),
            ("invocation nonce", self.invocation_nonce),
            ("remote repository hash", self.remote_repository_sha256),
            ("credential policy hash", self.credential_policy_sha256),
        ):
            _hex(value, name=name)
        checked = _utc(self.checked_at_utc, name="preflight check time")
        consumed = _utc(
            self.replay_entry.consumed_at_utc,
            name="nonce consumption time",
        )
        expires = _utc(self.lease.expires_at_utc, name="lease expiry time")
        if checked < consumed or checked >= expires:
            raise PublisherAuthorizationError(
                "preflight v2 check is outside the consumed lease window"
            )
        request = self.lease.signed_request.request
        if (
            self.lease_sha256 != self.lease.sha256
            or self.replay_entry_sha256 != self.replay_entry.sha256
            or self.replay_entry.lease_sha256 != self.lease_sha256
            or self.signed_request_sha256 != self.lease.signed_request_sha256
            or self.request_sha256 != self.lease.request_sha256
            or self.readiness_sha256 != self.lease.readiness_sha256
            or self.task_sha256 != self.lease.task_sha256
            or self.invocation_nonce != self.lease.invocation_nonce
            or self.remote_repository_sha256
            != self.lease.remote_repository_sha256
            or self.credential_policy_sha256
            != self.lease.credential_policy_sha256
            or self.authorized_operations != request.requested_operations
        ):
            raise PublisherAuthorizationError(
                "preflight v2 receipt identities are inconsistent"
            )
        if (
            self.lease_valid is not True
            or self.nonce_consumed is not True
            or self.remote_identity_matches is not True
            or self.credential_policy_matches is not True
            or self.exact_draft_only_scope is not True
            or self.credential_material_present is not False
            or self.write_adapter_present is not False
            or self.repository_write_performed is not False
            or self.network_write_performed is not False
            or self.merge_authority != "human"
        ):
            raise PublisherAuthorizationError(
                "preflight v2 authority boundary is invalid"
            )

    @classmethod
    def from_consumed_lease(
        cls,
        *,
        lease: AsymmetricPublisherAuthorizationLease,
        replay_entry: PublisherReplayLedgerEntryV2,
        task: DevelopmentTask,
        authorization_verifier: PublisherAuthorizationVerifierV2,
        publisher_verifier: PublisherRequestVerifier,
        semantic_verifier: SemanticReviewVerifier,
        control_plane_root: Path,
        checked_at_utc: str,
    ) -> "PublisherPreflightReceiptV2":
        if not isinstance(
            authorization_verifier,
            PublisherAuthorizationVerifierV2,
        ):
            raise PublisherAuthorizationError(
                "preflight v2 requires the Ed25519 authorization verifier"
            )
        authorization_verifier.verify(
            lease=lease,
            task=task,
            publisher_verifier=publisher_verifier,
            semantic_verifier=semantic_verifier,
            control_plane_root=Path(control_plane_root),
            at_utc=checked_at_utc,
        )
        replay_entry.verify_against(lease)
        return cls(
            lease=lease,
            lease_sha256=lease.sha256,
            replay_entry=replay_entry,
            replay_entry_sha256=replay_entry.sha256,
            signed_request_sha256=lease.signed_request_sha256,
            request_sha256=lease.request_sha256,
            readiness_sha256=lease.readiness_sha256,
            task_sha256=lease.task_sha256,
            invocation_nonce=lease.invocation_nonce,
            remote_repository_sha256=lease.remote_repository_sha256,
            credential_policy_sha256=lease.credential_policy_sha256,
            checked_at_utc=checked_at_utc,
            authorized_operations=(
                lease.signed_request.request.requested_operations
            ),
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "PublisherPreflightReceiptV2":
        fields = {
            "schema",
            "lease",
            "lease_sha256",
            "replay_entry",
            "replay_entry_sha256",
            "signed_request_sha256",
            "request_sha256",
            "readiness_sha256",
            "task_sha256",
            "invocation_nonce",
            "remote_repository_sha256",
            "credential_policy_sha256",
            "checked_at_utc",
            "authorized_operations",
            "lease_valid",
            "nonce_consumed",
            "remote_identity_matches",
            "credential_policy_matches",
            "exact_draft_only_scope",
            "credential_material_present",
            "write_adapter_present",
            "repository_write_performed",
            "network_write_performed",
            "merge_authority",
        }
        data = _strict(
            value,
            name="publisher preflight v2 receipt",
            fields=fields,
        )
        operations = data["authorized_operations"]
        if not isinstance(operations, list):
            raise PublisherAuthorizationError(
                "preflight v2 operations must be an array"
            )
        return cls(
            schema=data["schema"],
            lease=AsymmetricPublisherAuthorizationLease.from_mapping(
                data["lease"]
            ),
            lease_sha256=data["lease_sha256"],
            replay_entry=PublisherReplayLedgerEntryV2.from_mapping(
                data["replay_entry"]
            ),
            replay_entry_sha256=data["replay_entry_sha256"],
            signed_request_sha256=data["signed_request_sha256"],
            request_sha256=data["request_sha256"],
            readiness_sha256=data["readiness_sha256"],
            task_sha256=data["task_sha256"],
            invocation_nonce=data["invocation_nonce"],
            remote_repository_sha256=data["remote_repository_sha256"],
            credential_policy_sha256=data["credential_policy_sha256"],
            checked_at_utc=data["checked_at_utc"],
            authorized_operations=tuple(operations),
            lease_valid=data["lease_valid"],
            nonce_consumed=data["nonce_consumed"],
            remote_identity_matches=data["remote_identity_matches"],
            credential_policy_matches=data["credential_policy_matches"],
            exact_draft_only_scope=data["exact_draft_only_scope"],
            credential_material_present=data["credential_material_present"],
            write_adapter_present=data["write_adapter_present"],
            repository_write_performed=data["repository_write_performed"],
            network_write_performed=data["network_write_performed"],
            merge_authority=data["merge_authority"],
        )

    def verify(
        self,
        *,
        task: DevelopmentTask,
        authorization_verifier: PublisherAuthorizationVerifierV2,
        publisher_verifier: PublisherRequestVerifier,
        semantic_verifier: SemanticReviewVerifier,
        control_plane_root: Path,
    ) -> None:
        if not isinstance(
            authorization_verifier,
            PublisherAuthorizationVerifierV2,
        ):
            raise PublisherAuthorizationError(
                "preflight v2 requires the Ed25519 authorization verifier"
            )
        authorization_verifier.verify(
            lease=self.lease,
            task=task,
            publisher_verifier=publisher_verifier,
            semantic_verifier=semantic_verifier,
            control_plane_root=Path(control_plane_root),
            at_utc=self.checked_at_utc,
        )
        self.replay_entry.verify_against(self.lease)


class PublisherPreflightGateV2:
    @staticmethod
    def valid(
        *,
        receipt: PublisherPreflightReceiptV2,
        task: DevelopmentTask,
        authorization_verifier: PublisherAuthorizationVerifierV2,
        publisher_verifier: PublisherRequestVerifier,
        semantic_verifier: SemanticReviewVerifier,
        control_plane_root: Path,
    ) -> bool:
        if not isinstance(receipt, PublisherPreflightReceiptV2):
            return False
        try:
            receipt.verify(
                task=task,
                authorization_verifier=authorization_verifier,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=Path(control_plane_root),
            )
        except PublisherAuthorizationError:
            return False
        return True


@dataclass(frozen=True, slots=True)
class PublisherPostconditionReceiptV2(_LegacyPublisherPostconditionReceipt):
    preflight: PublisherPreflightReceiptV2
    schema: str = PUBLISHER_POSTCONDITION_RECEIPT_V2_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PUBLISHER_POSTCONDITION_RECEIPT_V2_SCHEMA:
            raise PublisherAuthorizationError(
                "unsupported publisher postcondition v2 schema"
            )
        if not isinstance(self.preflight, PublisherPreflightReceiptV2):
            raise PublisherAuthorizationError(
                "postcondition v2 preflight is invalid"
            )
        for name, value in (
            ("preflight hash", self.preflight_sha256),
            ("authorization lease hash", self.lease_sha256),
            ("replay entry hash", self.replay_entry_sha256),
            ("publisher request hash", self.request_sha256),
            ("invocation nonce", self.invocation_nonce),
            ("remote repository hash", self.remote_repository_sha256),
            ("credential policy hash", self.credential_policy_sha256),
        ):
            _hex(value, name=name)
        observed = _utc(
            self.observed_at_utc,
            name="postcondition observation time",
        )
        checked = _utc(
            self.preflight.checked_at_utc,
            name="preflight check time",
        )
        expires = _utc(
            self.preflight.lease.expires_at_utc,
            name="lease expiry time",
        )
        if observed < checked or observed >= expires:
            raise PublisherAuthorizationError(
                "postcondition v2 observation is outside the lease window"
            )
        if (
            self.preflight_sha256 != self.preflight.sha256
            or self.lease_sha256 != self.preflight.lease_sha256
            or self.replay_entry_sha256
            != self.preflight.replay_entry_sha256
            or self.request_sha256 != self.preflight.request_sha256
            or self.invocation_nonce != self.preflight.invocation_nonce
            or self.remote_repository_sha256
            != self.preflight.remote_repository_sha256
            or self.credential_policy_sha256
            != self.preflight.credential_policy_sha256
        ):
            raise PublisherAuthorizationError(
                "postcondition v2 receipt identities are inconsistent"
            )
        if (
            self.execution_state != "not_executed"
            or self.postconditions_verified is not False
            or self.repository_state_observed is not False
            or self.network_state_observed is not False
            or self.repository_write_performed is not False
            or self.network_write_performed is not False
            or self.commit_created is not False
            or self.branch_created is not False
            or self.branch_pushed is not False
            or self.pull_request_created is not False
            or self.ready_for_review is not False
            or self.reviewers_requested is not False
            or self.merged is not False
            or self.released is not False
            or self.deployed is not False
            or self.merge_authority != "human"
        ):
            raise PublisherAuthorizationError(
                "postcondition v2 claims unavailable execution or observation"
            )

    @classmethod
    def from_preflight_without_execution(
        cls,
        *,
        preflight: PublisherPreflightReceiptV2,
        observed_at_utc: str,
    ) -> "PublisherPostconditionReceiptV2":
        if not isinstance(preflight, PublisherPreflightReceiptV2):
            raise PublisherAuthorizationError(
                "postcondition v2 requires preflight v2 evidence"
            )
        return cls(
            preflight=preflight,
            preflight_sha256=preflight.sha256,
            lease_sha256=preflight.lease_sha256,
            replay_entry_sha256=preflight.replay_entry_sha256,
            request_sha256=preflight.request_sha256,
            invocation_nonce=preflight.invocation_nonce,
            remote_repository_sha256=preflight.remote_repository_sha256,
            credential_policy_sha256=preflight.credential_policy_sha256,
            observed_at_utc=observed_at_utc,
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "PublisherPostconditionReceiptV2":
        fields = {
            "schema",
            "preflight",
            "preflight_sha256",
            "lease_sha256",
            "replay_entry_sha256",
            "request_sha256",
            "invocation_nonce",
            "remote_repository_sha256",
            "credential_policy_sha256",
            "observed_at_utc",
            "execution_state",
            "postconditions_verified",
            "repository_state_observed",
            "network_state_observed",
            "repository_write_performed",
            "network_write_performed",
            "commit_created",
            "branch_created",
            "branch_pushed",
            "pull_request_created",
            "ready_for_review",
            "reviewers_requested",
            "merged",
            "released",
            "deployed",
            "merge_authority",
        }
        data = _strict(
            value,
            name="publisher postcondition v2 receipt",
            fields=fields,
        )
        return cls(
            schema=data["schema"],
            preflight=PublisherPreflightReceiptV2.from_mapping(
                data["preflight"]
            ),
            preflight_sha256=data["preflight_sha256"],
            lease_sha256=data["lease_sha256"],
            replay_entry_sha256=data["replay_entry_sha256"],
            request_sha256=data["request_sha256"],
            invocation_nonce=data["invocation_nonce"],
            remote_repository_sha256=data["remote_repository_sha256"],
            credential_policy_sha256=data["credential_policy_sha256"],
            observed_at_utc=data["observed_at_utc"],
            execution_state=data["execution_state"],
            postconditions_verified=data["postconditions_verified"],
            repository_state_observed=data["repository_state_observed"],
            network_state_observed=data["network_state_observed"],
            repository_write_performed=data["repository_write_performed"],
            network_write_performed=data["network_write_performed"],
            commit_created=data["commit_created"],
            branch_created=data["branch_created"],
            branch_pushed=data["branch_pushed"],
            pull_request_created=data["pull_request_created"],
            ready_for_review=data["ready_for_review"],
            reviewers_requested=data["reviewers_requested"],
            merged=data["merged"],
            released=data["released"],
            deployed=data["deployed"],
            merge_authority=data["merge_authority"],
        )

    def verify(
        self,
        *,
        task: DevelopmentTask,
        authorization_verifier: PublisherAuthorizationVerifierV2,
        publisher_verifier: PublisherRequestVerifier,
        semantic_verifier: SemanticReviewVerifier,
        control_plane_root: Path,
    ) -> None:
        self.preflight.verify(
            task=task,
            authorization_verifier=authorization_verifier,
            publisher_verifier=publisher_verifier,
            semantic_verifier=semantic_verifier,
            control_plane_root=Path(control_plane_root),
        )


class PublisherPostconditionGateV2:
    @staticmethod
    def valid(
        *,
        receipt: PublisherPostconditionReceiptV2,
        task: DevelopmentTask,
        authorization_verifier: PublisherAuthorizationVerifierV2,
        publisher_verifier: PublisherRequestVerifier,
        semantic_verifier: SemanticReviewVerifier,
        control_plane_root: Path,
    ) -> bool:
        if not isinstance(receipt, PublisherPostconditionReceiptV2):
            return False
        try:
            receipt.verify(
                task=task,
                authorization_verifier=authorization_verifier,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=Path(control_plane_root),
            )
        except PublisherAuthorizationError:
            return False
        return True


@dataclass(frozen=True, slots=True)
class PublisherReplayRecoveryReceiptV2:
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
    schema: str = PUBLISHER_REPLAY_RECOVERY_V2_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PUBLISHER_REPLAY_RECOVERY_V2_SCHEMA:
            raise PublisherAuthorizationError(
                "unsupported replay recovery v2 schema"
            )
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
            raise PublisherAuthorizationError(
                "replay recovery v2 action is invalid"
            )
        if self.state_before not in _STATES or self.state_after not in _STATES:
            raise PublisherAuthorizationError(
                "replay recovery v2 state is invalid"
            )
        if not isinstance(self.entry_verified, bool):
            raise PublisherAuthorizationError(
                "replay recovery v2 verification flag is invalid"
            )
        if self.nonce_reusable is not False:
            raise PublisherAuthorizationError(
                "replay recovery can never make a nonce reusable"
            )
        if self.action == "tombstone_uncertain":
            if (
                self.state_after != "tombstoned"
                or self.entry_verified is not False
            ):
                raise PublisherAuthorizationError(
                    "replay tombstone v2 receipt is inconsistent"
                )
        elif self.state_after != "committed" or self.entry_verified is not True:
            raise PublisherAuthorizationError(
                "replay commit recovery v2 receipt is inconsistent"
            )

    @classmethod
    def from_mapping(
        cls,
        value: Any,
    ) -> "PublisherReplayRecoveryReceiptV2":
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
        data = _strict(
            value,
            name="replay recovery v2 receipt",
            fields=fields,
        )
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "lease_sha256": self.lease_sha256,
            "invocation_nonce": self.invocation_nonce,
            "ledger_id": self.ledger_id,
            "recovery_authorization_sha256": (
                self.recovery_authorization_sha256
            ),
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


class PublisherReplayLedgerV2:
    """Crash-durable nonce ledger for Ed25519 authorization leases only."""

    def __init__(self, *, root: Path, ledger_id: str) -> None:
        self._root = Path(root)
        self._ledger_id = _identifier(
            ledger_id,
            name="publisher replay ledger ID",
        )
        if (
            not self._root.is_absolute()
            or not self._root.is_dir()
            or _has_linkish_component(self._root)
        ):
            raise PublisherAuthorizationError(
                "publisher replay ledger root must be an absolute "
                "link-free directory"
            )
        self._root = self._root.resolve()

    def _paths(self, invocation_nonce: str) -> tuple[Path, Path, Path, Path]:
        nonce = _hex(invocation_nonce, name="invocation nonce")
        return (
            self._root / f"{nonce}.v2.json",
            self._root / f".{nonce}.v2.pending.json",
            self._root / f".{nonce}.v2.lock",
            self._root / f"{nonce}.v2.recovery.json",
        )

    def _entry(self, path: Path) -> PublisherReplayLedgerEntryV2:
        entry = _load_canonical(
            path,
            PublisherReplayLedgerEntryV2.from_mapping,
            name="publisher replay ledger v2 entry",
        )
        if entry.ledger_id != self._ledger_id:
            raise PublisherAuthorizationError(
                "replay ledger v2 entry belongs to another ledger"
            )
        return entry

    def _state(self, invocation_nonce: str) -> str:
        final, pending, lock, recovery = self._paths(invocation_nonce)
        if final.exists():
            try:
                self._entry(final)
            except PublisherAuthorizationError:
                return "conflict"
            return (
                "committed_locked"
                if pending.exists() or lock.exists()
                else "committed"
            )
        if recovery.exists():
            try:
                receipt = _load_canonical(
                    recovery,
                    PublisherReplayRecoveryReceiptV2.from_mapping,
                    name="publisher replay recovery v2 receipt",
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
        lease: AsymmetricPublisherAuthorizationLease,
        task: DevelopmentTask,
        authorization_verifier: PublisherAuthorizationVerifierV2,
        publisher_verifier: PublisherRequestVerifier,
        semantic_verifier: SemanticReviewVerifier,
        control_plane_root: Path,
        consumed_at_utc: str,
    ) -> PublisherReplayLedgerEntryV2:
        if not isinstance(
            authorization_verifier,
            PublisherAuthorizationVerifierV2,
        ):
            raise PublisherAuthorizationError(
                "replay v2 consumption requires the Ed25519 verifier"
            )
        authorization_verifier.verify(
            lease=lease,
            task=task,
            publisher_verifier=publisher_verifier,
            semantic_verifier=semantic_verifier,
            control_plane_root=Path(control_plane_root),
            at_utc=consumed_at_utc,
        )
        entry = PublisherReplayLedgerEntryV2.from_lease(
            lease=lease,
            ledger_id=self._ledger_id,
            consumed_at_utc=consumed_at_utc,
        )
        entry.verify_against(lease)
        payload = entry.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PublisherAuthorizationError(
                "replay ledger v2 entry exceeds its byte bound"
            )
        final, pending, lock, recovery = self._paths(lease.invocation_nonce)
        if any(
            path.exists() or path.is_symlink()
            for path in (final, pending, lock, recovery)
        ):
            raise PublisherAuthorizationError(
                "invocation nonce has already been consumed or "
                "requires recovery"
            )
        reservation = _canonical(
            {
                "schema": (
                    "kaliv-development-publisher-replay-reservation/v2"
                ),
                "lease_sha256": lease.sha256,
                "invocation_nonce": lease.invocation_nonce,
                "ledger_id": self._ledger_id,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, reservation)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PublisherAuthorizationError(
                "invocation nonce has already been consumed or "
                "could not be durably reserved"
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
                "nonce v2 consumption is durable but requires "
                "explicit recovery"
            ) from exc
        return entry

    def load(self, invocation_nonce: str) -> PublisherReplayLedgerEntryV2:
        final, _, _, _ = self._paths(invocation_nonce)
        if final.exists():
            return self._entry(final)
        state = self._state(invocation_nonce)
        if state != "absent":
            raise PublisherAuthorizationError(
                "invocation nonce is consumed but has no usable v2 entry"
            )
        raise PublisherAuthorizationError(
            "publisher replay ledger v2 entry is missing"
        )

    def recover(
        self,
        *,
        lease: AsymmetricPublisherAuthorizationLease,
        action: str,
        recovery_authorization_sha256: str,
        operator_actor_id: str,
        recovered_at_utc: str,
    ) -> PublisherReplayRecoveryReceiptV2:
        if not isinstance(lease, AsymmetricPublisherAuthorizationLease):
            raise PublisherAuthorizationError(
                "replay recovery v2 lease is invalid"
            )
        if action not in _ACTIONS:
            raise PublisherAuthorizationError(
                "replay recovery v2 action is invalid"
            )
        authorization = _hex(
            recovery_authorization_sha256,
            name="replay recovery authorization hash",
        )
        operator = _actor(
            operator_actor_id,
            name="replay recovery operator",
        )
        _utc(recovered_at_utc, name="replay recovery time")
        nonce = lease.invocation_nonce
        final, pending, lock, recovery = self._paths(nonce)
        state_before = self._state(nonce)

        if action == "finalize_prepared":
            if state_before != "prepared":
                raise PublisherAuthorizationError(
                    "finalize recovery requires one verified prepared v2 entry"
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
                    "replay finalize v2 recovery was not durable"
                ) from exc
            state_after = "committed"
            verified = True
        elif action == "acknowledge_committed":
            if state_before not in {"committed", "committed_locked"}:
                raise PublisherAuthorizationError(
                    "commit acknowledgement requires a verified "
                    "committed v2 entry"
                )
            self._entry(final).verify_against(lease)
            try:
                unlink_durable(pending)
                unlink_durable(lock)
            except DurablePublicationError as exc:
                raise PublisherAuthorizationError(
                    "replay commit v2 cleanup was not durable"
                ) from exc
            state_after = "committed"
            verified = True
        else:
            if state_before not in {"reserved", "partial"}:
                raise PublisherAuthorizationError(
                    "tombstone recovery requires uncertain consumed v2 state"
                )
            receipt = PublisherReplayRecoveryReceiptV2(
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
                    "replay tombstone v2 recovery was not durable"
                ) from exc
            try:
                unlink_durable(pending)
                unlink_durable(lock)
            except DurablePublicationError:
                pass
            if self._state(nonce) != "tombstoned":
                raise PublisherAuthorizationError(
                    "replay tombstone v2 postcondition failed"
                )
            return receipt

        receipt = PublisherReplayRecoveryReceiptV2(
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
                PublisherReplayRecoveryReceiptV2.from_mapping,
                name="publisher replay recovery v2 receipt",
            )
            if existing.canonical_json() != receipt.canonical_json():
                raise PublisherAuthorizationError(
                    "replay recovery v2 receipt conflicts with "
                    "existing evidence"
                )
        else:
            try:
                create_once_file(
                    recovery,
                    receipt.canonical_json().encode("utf-8"),
                )
            except (FileExistsError, DurablePublicationError) as exc:
                raise PublisherAuthorizationError(
                    "replay recovery v2 receipt was not durably published"
                ) from exc
        if self._state(nonce) != "committed":
            raise PublisherAuthorizationError(
                "replay recovery v2 postcondition failed"
            )
        return receipt


def load_publisher_replay_ledger_entry_v2(
    path: Path,
) -> PublisherReplayLedgerEntryV2:
    return _load_canonical(
        path,
        PublisherReplayLedgerEntryV2.from_mapping,
        name="publisher replay ledger v2 entry",
    )


def load_publisher_preflight_receipt_v2(
    path: Path,
) -> PublisherPreflightReceiptV2:
    return _load_canonical(
        path,
        PublisherPreflightReceiptV2.from_mapping,
        name="publisher preflight v2 receipt",
    )


def load_publisher_postcondition_receipt_v2(
    path: Path,
) -> PublisherPostconditionReceiptV2:
    return _load_canonical(
        path,
        PublisherPostconditionReceiptV2.from_mapping,
        name="publisher postcondition v2 receipt",
    )


def load_publisher_replay_recovery_receipt_v2(
    path: Path,
) -> PublisherReplayRecoveryReceiptV2:
    return _load_canonical(
        path,
        PublisherReplayRecoveryReceiptV2.from_mapping,
        name="publisher replay recovery v2 receipt",
    )


def _write_v2(path: Path, value: Any, *, name: str) -> str:
    output = Path(path)
    if (
        not output.is_absolute()
        or output.exists()
        or not output.parent.is_dir()
        or _has_linkish_component(output.parent)
    ):
        raise PublisherAuthorizationError(
            f"{name} output path is unsafe or already exists"
        )
    canonical_json = getattr(value, "canonical_json", None)
    if canonical_json is None:
        raise PublisherAuthorizationError(f"{name} output is invalid")
    payload = canonical_json().encode("utf-8")
    if len(payload) > _MAX_ARTIFACT_BYTES:
        raise PublisherAuthorizationError(f"{name} exceeds its byte bound")
    try:
        create_once_file(output, payload)
    except (FileExistsError, DurablePublicationError) as exc:
        raise PublisherAuthorizationError(
            f"{name} could not be durably published"
        ) from exc
    return _sha256_bytes(payload)


def write_publisher_replay_ledger_entry_v2(
    path: Path,
    entry: PublisherReplayLedgerEntryV2,
) -> str:
    if not isinstance(entry, PublisherReplayLedgerEntryV2):
        raise PublisherAuthorizationError(
            "publisher replay ledger v2 output is invalid"
        )
    return _write_v2(
        path,
        entry,
        name="publisher replay ledger v2 entry",
    )


def write_publisher_preflight_receipt_v2(
    path: Path,
    receipt: PublisherPreflightReceiptV2,
) -> str:
    if not isinstance(receipt, PublisherPreflightReceiptV2):
        raise PublisherAuthorizationError(
            "publisher preflight v2 output is invalid"
        )
    return _write_v2(
        path,
        receipt,
        name="publisher preflight v2 receipt",
    )


def write_publisher_postcondition_receipt_v2(
    path: Path,
    receipt: PublisherPostconditionReceiptV2,
) -> str:
    if not isinstance(receipt, PublisherPostconditionReceiptV2):
        raise PublisherAuthorizationError(
            "publisher postcondition v2 output is invalid"
        )
    return _write_v2(
        path,
        receipt,
        name="publisher postcondition v2 receipt",
    )


def write_publisher_replay_recovery_receipt_v2(
    path: Path,
    receipt: PublisherReplayRecoveryReceiptV2,
) -> str:
    if not isinstance(receipt, PublisherReplayRecoveryReceiptV2):
        raise PublisherAuthorizationError(
            "publisher replay recovery v2 output is invalid"
        )
    return _write_v2(
        path,
        receipt,
        name="publisher replay recovery v2 receipt",
    )


__all__ = [
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
