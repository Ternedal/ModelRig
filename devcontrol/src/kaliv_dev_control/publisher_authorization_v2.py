"""Asymmetric publisher-authorization lease v2.

This module builds and verifies publisher authorization leases using detached
Ed25519 evidence. It intentionally contains no private-key type, signer, private
key loader, credential adapter, transport or repository-write capability.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .asymmetric_authority import (
    ASYMMETRIC_AUTHORITY_ALGORITHM,
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
)
from .contract import DevelopmentTask, MergeAuthority
from .publisher_dry_run import (
    PublisherDryRunError,
    PublisherRequestVerifier,
    SignedPublisherRequest,
)
from .semantic_review import SemanticReviewVerifier
from ._publisher_authorization_legacy import (
    PublisherAuthorizationError,
    PublisherCredentialPolicy,
    RemoteRepositoryIdentity,
    _actor,
    _canonical,
    _identifier,
    _sha256_bytes,
    _strict,
    _utc,
    publisher_authorization_policy_sha256,
)

PUBLISHER_AUTHORIZATION_LEASE_V2_SCHEMA = (
    "kaliv-development-publisher-authorization-lease/v2"
)
_MAX_LEASE_SECONDS = 15 * 60


def _lease_unsigned_payload(
    *,
    signed_request: SignedPublisherRequest,
    remote_repository: RemoteRepositoryIdentity,
    credential_policy: PublisherCredentialPolicy,
    issued_at_utc: str,
    expires_at_utc: str,
    issuer_actor_id: str,
    issuer_system_id: str,
    issuer_key_id: str,
) -> dict[str, Any]:
    request = signed_request.request
    return {
        "schema": PUBLISHER_AUTHORIZATION_LEASE_V2_SCHEMA,
        "signed_request": signed_request.to_dict(),
        "signed_request_sha256": signed_request.sha256,
        "request_sha256": request.sha256,
        "readiness_sha256": request.readiness_sha256,
        "task_sha256": request.task_sha256,
        "invocation_nonce": request.invocation_nonce,
        "remote_repository": remote_repository.to_dict(),
        "remote_repository_sha256": remote_repository.sha256,
        "credential_policy": credential_policy.to_dict(),
        "credential_policy_sha256": credential_policy.sha256,
        "authorization_policy_sha256": publisher_authorization_policy_sha256(),
        "issued_at_utc": issued_at_utc,
        "expires_at_utc": expires_at_utc,
        "issuer_actor_id": issuer_actor_id,
        "issuer_system_id": issuer_system_id,
        "issuer_key_id": issuer_key_id,
        "algorithm": ASYMMETRIC_AUTHORITY_ALGORITHM,
        "one_time": True,
        "maximum_uses": 1,
        "draft_only": True,
        "merge_authority": "human",
    }


def build_asymmetric_publisher_authorization_payload(
    *,
    signed_request: SignedPublisherRequest,
    task: DevelopmentTask,
    publisher_verifier: PublisherRequestVerifier,
    semantic_verifier: SemanticReviewVerifier,
    control_plane_root: Path,
    remote_repository: RemoteRepositoryIdentity,
    issued_at_utc: str,
    expires_at_utc: str,
    issuer_actor_id: str,
    issuer_system_id: str,
    issuer_key_id: str,
) -> bytes:
    """Build the exact canonical bytes an offline signer must sign."""

    if not isinstance(task, DevelopmentTask):
        raise PublisherAuthorizationError("authorization payload requires a task")
    if task.merge_authority is not MergeAuthority.HUMAN:
        raise PublisherAuthorizationError("merge authority must remain human")
    if not isinstance(publisher_verifier, PublisherRequestVerifier):
        raise PublisherAuthorizationError(
            "authorization payload requires a publisher verifier"
        )
    try:
        request = publisher_verifier.verify(
            signed_request=signed_request,
            task=task,
            semantic_verifier=semantic_verifier,
            control_plane_root=Path(control_plane_root),
        )
    except PublisherDryRunError as exc:
        raise PublisherAuthorizationError(
            f"publisher request verification failed: {exc}"
        ) from exc
    if not isinstance(remote_repository, RemoteRepositoryIdentity):
        raise PublisherAuthorizationError(
            "authorization payload requires remote identity"
        )
    if remote_repository.repository != request.repository:
        raise PublisherAuthorizationError(
            "remote repository does not match publisher request"
        )
    issued = _utc(issued_at_utc, name="lease issue time")
    expires = _utc(expires_at_utc, name="lease expiry time")
    duration = int((expires - issued).total_seconds())
    if not 1 <= duration <= _MAX_LEASE_SECONDS:
        raise PublisherAuthorizationError(
            "authorization lease lifetime is invalid"
        )
    issuer = _actor(issuer_actor_id, name="authorization issuer actor")
    _identifier(issuer_system_id, name="authorization issuer system")
    _identifier(issuer_key_id, name="authorization issuer key ID")
    developer = request.readiness.semantic_review_request.developer_actor_id
    reviewer = request.readiness.reviewer_actor_id
    publisher = request.publisher_actor_id
    if issuer in {developer, reviewer, publisher}:
        raise PublisherAuthorizationError(
            "authorization issuer must be separate from developer, reviewer and publisher"
        )
    policy = PublisherCredentialPolicy.for_request(
        signed_request=signed_request,
        remote_repository=remote_repository,
    )
    unsigned = _lease_unsigned_payload(
        signed_request=signed_request,
        remote_repository=remote_repository,
        credential_policy=policy,
        issued_at_utc=issued_at_utc,
        expires_at_utc=expires_at_utc,
        issuer_actor_id=issuer,
        issuer_system_id=issuer_system_id,
        issuer_key_id=issuer_key_id,
    )
    return _canonical(unsigned).encode("utf-8")


@dataclass(frozen=True, slots=True)
class AsymmetricPublisherAuthorizationLease:
    signed_request: SignedPublisherRequest
    signed_request_sha256: str
    request_sha256: str
    readiness_sha256: str
    task_sha256: str
    invocation_nonce: str
    remote_repository: RemoteRepositoryIdentity
    remote_repository_sha256: str
    credential_policy: PublisherCredentialPolicy
    credential_policy_sha256: str
    authorization_policy_sha256: str
    issued_at_utc: str
    expires_at_utc: str
    issuer_actor_id: str
    issuer_system_id: str
    issuer_key_id: str
    algorithm: str
    signature: DetachedEd25519AuthoritySignature
    one_time: bool = True
    maximum_uses: int = 1
    draft_only: bool = True
    merge_authority: str = "human"
    schema: str = PUBLISHER_AUTHORIZATION_LEASE_V2_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PUBLISHER_AUTHORIZATION_LEASE_V2_SCHEMA:
            raise PublisherAuthorizationError(
                "unsupported asymmetric publisher authorization lease schema"
            )
        if not isinstance(self.signed_request, SignedPublisherRequest):
            raise PublisherAuthorizationError(
                "authorization lease signed request is invalid"
            )
        if not isinstance(self.remote_repository, RemoteRepositoryIdentity):
            raise PublisherAuthorizationError(
                "authorization lease remote repository is invalid"
            )
        if not isinstance(self.credential_policy, PublisherCredentialPolicy):
            raise PublisherAuthorizationError(
                "authorization lease credential policy is invalid"
            )
        if not isinstance(
            self.signature, DetachedEd25519AuthoritySignature
        ):
            raise PublisherAuthorizationError(
                "authorization lease signature is invalid"
            )
        _actor(self.issuer_actor_id, name="authorization issuer actor")
        _identifier(self.issuer_system_id, name="authorization issuer system")
        _identifier(self.issuer_key_id, name="authorization issuer key ID")
        if self.algorithm != ASYMMETRIC_AUTHORITY_ALGORITHM:
            raise PublisherAuthorizationError(
                "authorization signature algorithm is unsupported"
            )
        issued = _utc(self.issued_at_utc, name="lease issue time")
        expires = _utc(self.expires_at_utc, name="lease expiry time")
        duration = int((expires - issued).total_seconds())
        if not 1 <= duration <= _MAX_LEASE_SECONDS:
            raise PublisherAuthorizationError(
                "authorization lease lifetime is invalid"
            )
        request = self.signed_request.request
        if (
            self.signed_request_sha256 != self.signed_request.sha256
            or self.request_sha256 != request.sha256
            or self.readiness_sha256 != request.readiness_sha256
            or self.task_sha256 != request.task_sha256
            or self.invocation_nonce != request.invocation_nonce
            or self.remote_repository_sha256 != self.remote_repository.sha256
            or self.remote_repository.repository != request.repository
            or self.credential_policy_sha256 != self.credential_policy.sha256
            or self.credential_policy
            != PublisherCredentialPolicy.for_request(
                signed_request=self.signed_request,
                remote_repository=self.remote_repository,
            )
        ):
            raise PublisherAuthorizationError(
                "authorization lease identities are inconsistent"
            )
        if (
            self.authorization_policy_sha256
            != publisher_authorization_policy_sha256()
        ):
            raise PublisherAuthorizationError(
                "authorization policy is unsupported"
            )
        developer = (
            request.readiness.semantic_review_request.developer_actor_id
        )
        reviewer = request.readiness.reviewer_actor_id
        publisher = request.publisher_actor_id
        if self.issuer_actor_id in {developer, reviewer, publisher}:
            raise PublisherAuthorizationError(
                "authorization issuer must be separate from developer, reviewer and publisher"
            )
        if (
            self.signature.key_id != self.issuer_key_id
            or self.signature.issuer_actor_id != self.issuer_actor_id
            or self.signature.signed_at_utc != self.issued_at_utc
        ):
            raise PublisherAuthorizationError(
                "authorization signature identity is inconsistent"
            )
        if (
            self.one_time is not True
            or self.maximum_uses != 1
            or self.draft_only is not True
            or self.merge_authority != "human"
        ):
            raise PublisherAuthorizationError(
                "authorization lease authority boundary is invalid"
            )
        unsigned = self.unsigned_json().encode("utf-8")
        if self.signature.payload_sha256 != hashlib.sha256(unsigned).hexdigest():
            raise PublisherAuthorizationError(
                "authorization signature payload hash is inconsistent"
            )

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "AsymmetricPublisherAuthorizationLease":
        fields = {
            "schema",
            "signed_request",
            "signed_request_sha256",
            "request_sha256",
            "readiness_sha256",
            "task_sha256",
            "invocation_nonce",
            "remote_repository",
            "remote_repository_sha256",
            "credential_policy",
            "credential_policy_sha256",
            "authorization_policy_sha256",
            "issued_at_utc",
            "expires_at_utc",
            "issuer_actor_id",
            "issuer_system_id",
            "issuer_key_id",
            "algorithm",
            "signature",
            "one_time",
            "maximum_uses",
            "draft_only",
            "merge_authority",
        }
        data = _strict(
            value,
            name="asymmetric publisher authorization lease",
            fields=fields,
        )
        return cls(
            schema=data["schema"],
            signed_request=SignedPublisherRequest.from_mapping(
                data["signed_request"]
            ),
            signed_request_sha256=data["signed_request_sha256"],
            request_sha256=data["request_sha256"],
            readiness_sha256=data["readiness_sha256"],
            task_sha256=data["task_sha256"],
            invocation_nonce=data["invocation_nonce"],
            remote_repository=RemoteRepositoryIdentity.from_mapping(
                data["remote_repository"]
            ),
            remote_repository_sha256=data["remote_repository_sha256"],
            credential_policy=PublisherCredentialPolicy.from_mapping(
                data["credential_policy"]
            ),
            credential_policy_sha256=data["credential_policy_sha256"],
            authorization_policy_sha256=data[
                "authorization_policy_sha256"
            ],
            issued_at_utc=data["issued_at_utc"],
            expires_at_utc=data["expires_at_utc"],
            issuer_actor_id=data["issuer_actor_id"],
            issuer_system_id=data["issuer_system_id"],
            issuer_key_id=data["issuer_key_id"],
            algorithm=data["algorithm"],
            signature=DetachedEd25519AuthoritySignature.from_mapping(
                data["signature"]
            ),
            one_time=data["one_time"],
            maximum_uses=data["maximum_uses"],
            draft_only=data["draft_only"],
            merge_authority=data["merge_authority"],
        )

    @classmethod
    def from_signed_payload(
        cls,
        *,
        unsigned_payload: bytes,
        signature: DetachedEd25519AuthoritySignature,
    ) -> "AsymmetricPublisherAuthorizationLease":
        if not isinstance(unsigned_payload, bytes) or not unsigned_payload:
            raise PublisherAuthorizationError(
                "authorization unsigned payload is invalid"
            )
        try:
            parsed = json.loads(unsigned_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PublisherAuthorizationError(
                "authorization unsigned payload is invalid"
            ) from exc
        if (
            not isinstance(parsed, Mapping)
            or _canonical(parsed).encode("utf-8") != unsigned_payload
        ):
            raise PublisherAuthorizationError(
                "authorization unsigned payload is not canonical"
            )
        return cls.from_mapping(
            {**dict(parsed), "signature": signature.to_dict()}
        )

    def unsigned_dict(self) -> dict[str, Any]:
        return _lease_unsigned_payload(
            signed_request=self.signed_request,
            remote_repository=self.remote_repository,
            credential_policy=self.credential_policy,
            issued_at_utc=self.issued_at_utc,
            expires_at_utc=self.expires_at_utc,
            issuer_actor_id=self.issuer_actor_id,
            issuer_system_id=self.issuer_system_id,
            issuer_key_id=self.issuer_key_id,
        )

    def unsigned_json(self) -> str:
        return _canonical(self.unsigned_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.unsigned_dict(),
            "signature": self.signature.to_dict(),
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_bytes(self.canonical_json().encode("utf-8"))


class AsymmetricPublisherAuthorizationVerifier:
    """Verify v2 leases with public keys only."""

    def __init__(
        self,
        authority_verifier: Ed25519AuthorityVerifier,
    ) -> None:
        if not isinstance(authority_verifier, Ed25519AuthorityVerifier):
            raise PublisherAuthorizationError(
                "authorization verifier requires an Ed25519 authority verifier"
            )
        self._authority_verifier = authority_verifier

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
                "authorization verification requires a v2 lease"
            )
        unsigned = lease.unsigned_json().encode("utf-8")
        self._authority_verifier.verify(
            payload=unsigned,
            signature=lease.signature,
            at_utc=at_utc,
        )
        try:
            publisher_verifier.verify(
                signed_request=lease.signed_request,
                task=task,
                semantic_verifier=semantic_verifier,
                control_plane_root=Path(control_plane_root),
            )
        except PublisherDryRunError as exc:
            raise PublisherAuthorizationError(
                f"publisher request verification failed: {exc}"
            ) from exc
        current = _utc(at_utc, name="authorization verification time")
        issued = _utc(lease.issued_at_utc, name="lease issue time")
        expires = _utc(lease.expires_at_utc, name="lease expiry time")
        if current < issued or current >= expires:
            raise PublisherAuthorizationError(
                "authorization lease is not currently valid"
            )
        return lease


__all__ = [
    "AsymmetricPublisherAuthorizationLease",
    "AsymmetricPublisherAuthorizationVerifier",
    "PUBLISHER_AUTHORIZATION_LEASE_V2_SCHEMA",
    "build_asymmetric_publisher_authorization_payload",
]
