"""One-time publisher authorization and replay evidence without a live writer.

This module deliberately contains no Git transport, GitHub API client, network
request, credential value, repository mutation, pull-request mutation, merge,
release or deployment adapter.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, TypeVar

from .contract import DevelopmentTask, MergeAuthority
from .publisher_dry_run import (
    PublisherDryRunError,
    PublisherRequestVerifier,
    SignedPublisherRequest,
)
from .semantic_review import SemanticReviewVerifier

PUBLISHER_AUTHORIZATION_LEASE_SCHEMA = (
    "kaliv-development-publisher-authorization-lease/v1"
)
PUBLISHER_REPLAY_LEDGER_ENTRY_SCHEMA = (
    "kaliv-development-publisher-replay-ledger-entry/v1"
)
PUBLISHER_PREFLIGHT_RECEIPT_SCHEMA = (
    "kaliv-development-publisher-preflight-receipt/v1"
)
PUBLISHER_POSTCONDITION_RECEIPT_SCHEMA = (
    "kaliv-development-publisher-postcondition-receipt/v1"
)
_REMOTE_REPOSITORY_SCHEMA = "kaliv-development-remote-repository-identity/v1"
_CREDENTIAL_POLICY_SCHEMA = "kaliv-development-publisher-credential-policy/v1"

_AUTHORIZATION_POLICY_DOMAIN = b"kaliv-publisher-authorization-policy/v1\0"
_CREDENTIAL_POLICY_DOMAIN = b"kaliv-publisher-credential-policy/v1\0"
_AUTHORIZATION_SIGNATURE_DOMAIN = b"kaliv-publisher-authorization-lease/v1\0"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ACTOR_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,39}$")
_UTC_TIMESTAMP = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
_MAX_SECRET_BYTES = 4096
_MAX_LEASE_SECONDS = 15 * 60

PUBLISHER_AUTHORIZATION_POLICY = (
    "Accept only one complete Slice 10J signed publisher request that still verifies against the exact task, trusted publisher, trusted semantic reviewer and current execution authority.",
    "Require a separately authenticated authorization issuer who differs from the developer, semantic reviewer and publisher.",
    "Bind one exact invocation nonce, one immutable remote-repository identity and one fixed least-privilege credential policy.",
    "Limit every lease to one use and at most fifteen minutes with an explicit issue and expiry timestamp.",
    "Consume the invocation nonce through one atomic create-once replay-ledger entry before producing preflight evidence.",
    "Keep credentials, Git transport, network writes, reviewer requests, ready-for-review, merge, release, settings, deployment and runtime activation outside this boundary.",
    "Fail closed on any task, authority, signature, time, repository, policy, nonce, replay, canonical-byte or no-write-boundary mismatch.",
)

_ALLOWED_PERMISSIONS = (
    "contents:write:exact-proposed-branch-only",
    "pull_requests:write:create-exact-draft-only",
)
_DENIED_CAPABILITIES = (
    "actions-and-workflows",
    "administration",
    "base-branch-write",
    "checks",
    "deployments",
    "environments",
    "force-push",
    "issues",
    "members",
    "merge",
    "packages",
    "pages",
    "ready-for-review",
    "release",
    "repository-settings",
    "reviewer-requests",
    "secrets-and-variables",
    "tag-write",
    "webhooks",
)


class PublisherAuthorizationError(ValueError):
    """Authorization, replay or receipt evidence is invalid or unsafe."""


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strict(value: Any, *, name: str, fields: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PublisherAuthorizationError(f"{name} fields mismatch")
    return value


def _clean_text(value: Any, *, name: str, maximum: int, one_line: bool = False) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\x00" in value
        or len(value.encode("utf-8")) > maximum
        or (one_line and ("\n" in value or "\r" in value))
    ):
        raise PublisherAuthorizationError(f"{name} is invalid")
    return value


def _hex(value: Any, *, name: str, pattern: re.Pattern[str] = _HEX64) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PublisherAuthorizationError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR_ID.fullmatch(value) is None:
        raise PublisherAuthorizationError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise PublisherAuthorizationError(f"{name} is invalid")
    return value


def _secret(value: Any) -> bytes:
    if not isinstance(value, bytes) or not 32 <= len(value) <= _MAX_SECRET_BYTES:
        raise PublisherAuthorizationError(
            "authorization signing secret must contain 32..4096 bytes"
        )
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC_TIMESTAMP.fullmatch(value) is None:
        raise PublisherAuthorizationError(f"{name} must be canonical UTC seconds")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PublisherAuthorizationError(f"{name} is invalid") from exc
    return parsed


def _has_linkish_component(path: Path) -> bool:
    current = path.absolute()
    while True:
        if current.is_symlink():
            return True
        is_junction = getattr(current, "is_junction", None)
        if is_junction is not None and is_junction():
            return True
        if current.parent == current:
            return False
        current = current.parent


def publisher_authorization_policy_sha256() -> str:
    payload = json.dumps(
        list(PUBLISHER_AUTHORIZATION_POLICY),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(_AUTHORIZATION_POLICY_DOMAIN + payload)


def publisher_credential_policy_rules_sha256() -> str:
    payload = json.dumps(
        {
            "allowed_permissions": list(_ALLOWED_PERMISSIONS),
            "denied_capabilities": list(_DENIED_CAPABILITIES),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(_CREDENTIAL_POLICY_DOMAIN + payload)


def _authorization_signature(
    *, key_id: str, secret: bytes, unsigned_json: str
) -> str:
    payload = (
        _AUTHORIZATION_SIGNATURE_DOMAIN
        + key_id.encode("utf-8")
        + b"\0"
        + unsigned_json.encode("utf-8")
    )
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class RemoteRepositoryIdentity:
    repository: str
    repository_id: str
    provider: str = "github"
    host: str = "github.com"
    schema: str = _REMOTE_REPOSITORY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != _REMOTE_REPOSITORY_SCHEMA:
            raise PublisherAuthorizationError("unsupported remote repository schema")
        if self.provider != "github" or self.host != "github.com":
            raise PublisherAuthorizationError("remote repository provider is unsupported")
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PublisherAuthorizationError("remote repository name is invalid")
        if not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None:
            raise PublisherAuthorizationError("remote repository ID is invalid")

    @classmethod
    def github(
        cls, *, repository: str, repository_id: str
    ) -> "RemoteRepositoryIdentity":
        return cls(repository=repository, repository_id=repository_id)

    @classmethod
    def from_mapping(cls, value: Any) -> "RemoteRepositoryIdentity":
        data = _strict(
            value,
            name="remote repository identity",
            fields={"schema", "provider", "host", "repository", "repository_id"},
        )
        return cls(
            schema=data["schema"],
            provider=data["provider"],
            host=data["host"],
            repository=data["repository"],
            repository_id=data["repository_id"],
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "schema": self.schema,
            "provider": self.provider,
            "host": self.host,
            "repository": self.repository,
            "repository_id": self.repository_id,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_bytes(self.canonical_json().encode("utf-8"))


@dataclass(frozen=True, slots=True)
class PublisherCredentialPolicy:
    remote_repository_sha256: str
    repository: str
    head_branch: str
    allowed_permissions: tuple[str, ...]
    denied_capabilities: tuple[str, ...]
    rules_sha256: str
    token_material_present: bool = False
    reusable_credential_allowed: bool = False
    branch_scope_exact: bool = True
    draft_pr_only: bool = True
    maximum_uses: int = 1
    schema: str = _CREDENTIAL_POLICY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != _CREDENTIAL_POLICY_SCHEMA:
            raise PublisherAuthorizationError("unsupported publisher credential policy schema")
        _hex(self.remote_repository_sha256, name="remote repository hash")
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PublisherAuthorizationError("credential policy repository is invalid")
        _clean_text(self.head_branch, name="credential policy branch", maximum=200, one_line=True)
        if self.allowed_permissions != _ALLOWED_PERMISSIONS:
            raise PublisherAuthorizationError("credential policy permissions are not least privilege")
        if self.denied_capabilities != _DENIED_CAPABILITIES:
            raise PublisherAuthorizationError("credential policy denied capabilities are incomplete")
        if self.rules_sha256 != publisher_credential_policy_rules_sha256():
            raise PublisherAuthorizationError("credential policy rules hash is unsupported")
        if (
            self.token_material_present is not False
            or self.reusable_credential_allowed is not False
            or self.branch_scope_exact is not True
            or self.draft_pr_only is not True
            or self.maximum_uses != 1
        ):
            raise PublisherAuthorizationError("credential policy authority boundary is invalid")

    @classmethod
    def for_request(
        cls,
        *,
        signed_request: SignedPublisherRequest,
        remote_repository: RemoteRepositoryIdentity,
    ) -> "PublisherCredentialPolicy":
        if not isinstance(signed_request, SignedPublisherRequest):
            raise PublisherAuthorizationError("credential policy requires a signed publisher request")
        if not isinstance(remote_repository, RemoteRepositoryIdentity):
            raise PublisherAuthorizationError("credential policy requires a remote repository identity")
        request = signed_request.request
        if remote_repository.repository != request.repository:
            raise PublisherAuthorizationError("remote repository does not match publisher request")
        return cls(
            remote_repository_sha256=remote_repository.sha256,
            repository=request.repository,
            head_branch=request.head_branch,
            allowed_permissions=_ALLOWED_PERMISSIONS,
            denied_capabilities=_DENIED_CAPABILITIES,
            rules_sha256=publisher_credential_policy_rules_sha256(),
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "PublisherCredentialPolicy":
        fields = {
            "schema",
            "remote_repository_sha256",
            "repository",
            "head_branch",
            "allowed_permissions",
            "denied_capabilities",
            "rules_sha256",
            "token_material_present",
            "reusable_credential_allowed",
            "branch_scope_exact",
            "draft_pr_only",
            "maximum_uses",
        }
        data = _strict(value, name="publisher credential policy", fields=fields)
        allowed = data["allowed_permissions"]
        denied = data["denied_capabilities"]
        if not isinstance(allowed, list) or not isinstance(denied, list):
            raise PublisherAuthorizationError("credential policy capability sets must be arrays")
        return cls(
            schema=data["schema"],
            remote_repository_sha256=data["remote_repository_sha256"],
            repository=data["repository"],
            head_branch=data["head_branch"],
            allowed_permissions=tuple(allowed),
            denied_capabilities=tuple(denied),
            rules_sha256=data["rules_sha256"],
            token_material_present=data["token_material_present"],
            reusable_credential_allowed=data["reusable_credential_allowed"],
            branch_scope_exact=data["branch_scope_exact"],
            draft_pr_only=data["draft_pr_only"],
            maximum_uses=data["maximum_uses"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "remote_repository_sha256": self.remote_repository_sha256,
            "repository": self.repository,
            "head_branch": self.head_branch,
            "allowed_permissions": list(self.allowed_permissions),
            "denied_capabilities": list(self.denied_capabilities),
            "rules_sha256": self.rules_sha256,
            "token_material_present": self.token_material_present,
            "reusable_credential_allowed": self.reusable_credential_allowed,
            "branch_scope_exact": self.branch_scope_exact,
            "draft_pr_only": self.draft_pr_only,
            "maximum_uses": self.maximum_uses,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_bytes(self.canonical_json().encode("utf-8"))


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
        "schema": PUBLISHER_AUTHORIZATION_LEASE_SCHEMA,
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
        "algorithm": "hmac-sha256",
        "one_time": True,
        "maximum_uses": 1,
        "draft_only": True,
        "merge_authority": "human",
    }


@dataclass(frozen=True, slots=True)
class PublisherAuthorizationLease:
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
    signature_sha256: str
    one_time: bool = True
    maximum_uses: int = 1
    draft_only: bool = True
    merge_authority: str = "human"
    schema: str = PUBLISHER_AUTHORIZATION_LEASE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PUBLISHER_AUTHORIZATION_LEASE_SCHEMA:
            raise PublisherAuthorizationError("unsupported publisher authorization lease schema")
        if not isinstance(self.signed_request, SignedPublisherRequest):
            raise PublisherAuthorizationError("authorization lease signed request is invalid")
        if not isinstance(self.remote_repository, RemoteRepositoryIdentity):
            raise PublisherAuthorizationError("authorization lease remote repository is invalid")
        if not isinstance(self.credential_policy, PublisherCredentialPolicy):
            raise PublisherAuthorizationError("authorization lease credential policy is invalid")
        for name, value in (
            ("signed publisher request hash", self.signed_request_sha256),
            ("publisher request hash", self.request_sha256),
            ("readiness hash", self.readiness_sha256),
            ("task hash", self.task_sha256),
            ("invocation nonce", self.invocation_nonce),
            ("remote repository hash", self.remote_repository_sha256),
            ("credential policy hash", self.credential_policy_sha256),
            ("authorization policy hash", self.authorization_policy_sha256),
            ("authorization signature", self.signature_sha256),
        ):
            _hex(value, name=name)
        issuer = _actor(self.issuer_actor_id, name="authorization issuer actor")
        _identifier(self.issuer_system_id, name="authorization issuer system")
        _identifier(self.issuer_key_id, name="authorization issuer key ID")
        if self.algorithm != "hmac-sha256":
            raise PublisherAuthorizationError("authorization signature algorithm is unsupported")
        issued = _utc(self.issued_at_utc, name="lease issue time")
        expires = _utc(self.expires_at_utc, name="lease expiry time")
        duration = int((expires - issued).total_seconds())
        if not 1 <= duration <= _MAX_LEASE_SECONDS:
            raise PublisherAuthorizationError("authorization lease lifetime is invalid")
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
            raise PublisherAuthorizationError("authorization lease identities are inconsistent")
        if self.authorization_policy_sha256 != publisher_authorization_policy_sha256():
            raise PublisherAuthorizationError("authorization policy is unsupported")
        developer = request.readiness.semantic_review_request.developer_actor_id
        reviewer = request.readiness.reviewer_actor_id
        publisher = request.publisher_actor_id
        if issuer in {developer, reviewer, publisher}:
            raise PublisherAuthorizationError(
                "authorization issuer must be separate from developer, reviewer and publisher"
            )
        if (
            self.one_time is not True
            or self.maximum_uses != 1
            or self.draft_only is not True
            or self.merge_authority != "human"
        ):
            raise PublisherAuthorizationError("authorization lease authority boundary is invalid")

    @classmethod
    def from_mapping(cls, value: Any) -> "PublisherAuthorizationLease":
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
            "signature_sha256",
            "one_time",
            "maximum_uses",
            "draft_only",
            "merge_authority",
        }
        data = _strict(value, name="publisher authorization lease", fields=fields)
        return cls(
            schema=data["schema"],
            signed_request=SignedPublisherRequest.from_mapping(data["signed_request"]),
            signed_request_sha256=data["signed_request_sha256"],
            request_sha256=data["request_sha256"],
            readiness_sha256=data["readiness_sha256"],
            task_sha256=data["task_sha256"],
            invocation_nonce=data["invocation_nonce"],
            remote_repository=RemoteRepositoryIdentity.from_mapping(data["remote_repository"]),
            remote_repository_sha256=data["remote_repository_sha256"],
            credential_policy=PublisherCredentialPolicy.from_mapping(data["credential_policy"]),
            credential_policy_sha256=data["credential_policy_sha256"],
            authorization_policy_sha256=data["authorization_policy_sha256"],
            issued_at_utc=data["issued_at_utc"],
            expires_at_utc=data["expires_at_utc"],
            issuer_actor_id=data["issuer_actor_id"],
            issuer_system_id=data["issuer_system_id"],
            issuer_key_id=data["issuer_key_id"],
            algorithm=data["algorithm"],
            signature_sha256=data["signature_sha256"],
            one_time=data["one_time"],
            maximum_uses=data["maximum_uses"],
            draft_only=data["draft_only"],
            merge_authority=data["merge_authority"],
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

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "signature_sha256": self.signature_sha256}

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_bytes(self.canonical_json().encode("utf-8"))


@dataclass(frozen=True, slots=True)
class TrustedAuthorizationIssuerKey:
    issuer_actor_id: str
    secret: bytes

    def __post_init__(self) -> None:
        _actor(self.issuer_actor_id, name="trusted authorization issuer actor")
        _secret(self.secret)


class HmacPublisherAuthorizationIssuer:
    def __init__(
        self,
        *,
        key_id: str,
        issuer_actor_id: str,
        issuer_system_id: str,
        secret: bytes,
    ) -> None:
        self._key_id = _identifier(key_id, name="authorization issuer key ID")
        self._issuer_actor_id = _actor(
            issuer_actor_id, name="authorization issuer actor"
        )
        self._issuer_system_id = _identifier(
            issuer_system_id, name="authorization issuer system"
        )
        self._secret = _secret(secret)

    def issue(
        self,
        *,
        signed_request: SignedPublisherRequest,
        task: DevelopmentTask,
        publisher_verifier: PublisherRequestVerifier,
        semantic_verifier: SemanticReviewVerifier,
        control_plane_root: Path,
        remote_repository: RemoteRepositoryIdentity,
        issued_at_utc: str,
        expires_at_utc: str,
    ) -> PublisherAuthorizationLease:
        if not isinstance(task, DevelopmentTask):
            raise PublisherAuthorizationError("authorization issuance requires a task")
        if task.merge_authority is not MergeAuthority.HUMAN:
            raise PublisherAuthorizationError("merge authority must remain human")
        if not isinstance(publisher_verifier, PublisherRequestVerifier):
            raise PublisherAuthorizationError("authorization issuance requires a publisher verifier")
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
            raise PublisherAuthorizationError("authorization issuance requires remote identity")
        if remote_repository.repository != request.repository:
            raise PublisherAuthorizationError("remote repository does not match publisher request")
        issued = _utc(issued_at_utc, name="lease issue time")
        expires = _utc(expires_at_utc, name="lease expiry time")
        duration = int((expires - issued).total_seconds())
        if not 1 <= duration <= _MAX_LEASE_SECONDS:
            raise PublisherAuthorizationError("authorization lease lifetime is invalid")
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
            issuer_actor_id=self._issuer_actor_id,
            issuer_system_id=self._issuer_system_id,
            issuer_key_id=self._key_id,
        )
        signature = _authorization_signature(
            key_id=self._key_id,
            secret=self._secret,
            unsigned_json=_canonical(unsigned),
        )
        return PublisherAuthorizationLease.from_mapping(
            {**unsigned, "signature_sha256": signature}
        )


class PublisherAuthorizationVerifier:
    def __init__(
        self, trusted_keys: Mapping[str, TrustedAuthorizationIssuerKey]
    ) -> None:
        if not isinstance(trusted_keys, Mapping) or not trusted_keys:
            raise PublisherAuthorizationError(
                "authorization verifier requires a non-empty trusted keyring"
            )
        keys: dict[str, TrustedAuthorizationIssuerKey] = {}
        for key_id, trusted in trusted_keys.items():
            canonical_id = _identifier(key_id, name="trusted authorization key ID")
            if not isinstance(trusted, TrustedAuthorizationIssuerKey):
                raise PublisherAuthorizationError(
                    "trusted authorization keyring entry is invalid"
                )
            keys[canonical_id] = trusted
        self._trusted_keys = keys

    def verify(
        self,
        *,
        lease: PublisherAuthorizationLease,
        task: DevelopmentTask,
        publisher_verifier: PublisherRequestVerifier,
        semantic_verifier: SemanticReviewVerifier,
        control_plane_root: Path,
        at_utc: str,
    ) -> PublisherAuthorizationLease:
        if not isinstance(lease, PublisherAuthorizationLease):
            raise PublisherAuthorizationError(
                "authorization verification requires a lease"
            )
        trusted = self._trusted_keys.get(lease.issuer_key_id)
        if trusted is None:
            raise PublisherAuthorizationError("authorization issuer key is not trusted")
        if trusted.issuer_actor_id != lease.issuer_actor_id:
            raise PublisherAuthorizationError(
                "authorization issuer key is bound to another actor"
            )
        expected = _authorization_signature(
            key_id=lease.issuer_key_id,
            secret=trusted.secret,
            unsigned_json=_canonical(lease.unsigned_dict()),
        )
        if not hmac.compare_digest(expected, lease.signature_sha256):
            raise PublisherAuthorizationError("authorization lease signature is invalid")
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
            raise PublisherAuthorizationError("authorization lease is not currently valid")
        return lease


@dataclass(frozen=True, slots=True)
class PublisherReplayLedgerEntry:
    lease: PublisherAuthorizationLease
    lease_sha256: str
    signed_request_sha256: str
    request_sha256: str
    invocation_nonce: str
    remote_repository_sha256: str
    credential_policy_sha256: str
    ledger_id: str
    consumed_at_utc: str
    consumer_actor_id: str
    outcome: str = "consumed_once"
    one_time: bool = True
    maximum_uses: int = 1
    schema: str = PUBLISHER_REPLAY_LEDGER_ENTRY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PUBLISHER_REPLAY_LEDGER_ENTRY_SCHEMA:
            raise PublisherAuthorizationError("unsupported publisher replay ledger schema")
        if not isinstance(self.lease, PublisherAuthorizationLease):
            raise PublisherAuthorizationError("replay ledger lease is invalid")
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
            or self.remote_repository_sha256 != self.lease.remote_repository_sha256
            or self.credential_policy_sha256 != self.lease.credential_policy_sha256
            or consumer != request.publisher_actor_id
        ):
            raise PublisherAuthorizationError("replay ledger entry identities are inconsistent")
        if (
            self.outcome != "consumed_once"
            or self.one_time is not True
            or self.maximum_uses != 1
        ):
            raise PublisherAuthorizationError("replay ledger outcome is invalid")

    @classmethod
    def from_lease(
        cls,
        *,
        lease: PublisherAuthorizationLease,
        ledger_id: str,
        consumed_at_utc: str,
    ) -> "PublisherReplayLedgerEntry":
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
    def from_mapping(cls, value: Any) -> "PublisherReplayLedgerEntry":
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
        data = _strict(value, name="publisher replay ledger entry", fields=fields)
        return cls(
            schema=data["schema"],
            lease=PublisherAuthorizationLease.from_mapping(data["lease"]),
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

    def verify_against(self, lease: PublisherAuthorizationLease) -> None:
        if not isinstance(lease, PublisherAuthorizationLease) or lease.sha256 != self.lease_sha256:
            raise PublisherAuthorizationError("replay ledger entry is bound to another lease")
        if self.lease.canonical_json() != lease.canonical_json():
            raise PublisherAuthorizationError("replay ledger embedded lease differs")
        consumed = _utc(self.consumed_at_utc, name="nonce consumption time")
        issued = _utc(lease.issued_at_utc, name="lease issue time")
        expires = _utc(lease.expires_at_utc, name="lease expiry time")
        if consumed < issued or consumed >= expires:
            raise PublisherAuthorizationError("nonce was consumed outside the lease window")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "lease": self.lease.to_dict(),
            "lease_sha256": self.lease_sha256,
            "signed_request_sha256": self.signed_request_sha256,
            "request_sha256": self.request_sha256,
            "invocation_nonce": self.invocation_nonce,
            "remote_repository_sha256": self.remote_repository_sha256,
            "credential_policy_sha256": self.credential_policy_sha256,
            "ledger_id": self.ledger_id,
            "consumed_at_utc": self.consumed_at_utc,
            "consumer_actor_id": self.consumer_actor_id,
            "outcome": self.outcome,
            "one_time": self.one_time,
            "maximum_uses": self.maximum_uses,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_bytes(self.canonical_json().encode("utf-8"))


class PublisherReplayLedger:
    """Directory-backed immutable nonce ledger using atomic create-once entries."""

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

    def _path(self, invocation_nonce: str) -> Path:
        nonce = _hex(invocation_nonce, name="invocation nonce")
        return self._root / f"{nonce}.json"

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
        path = self._path(lease.invocation_nonce)
        payload = entry.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PublisherAuthorizationError("replay ledger entry exceeds its byte bound")
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise PublisherAuthorizationError(
                "invocation nonce has already been consumed"
            ) from exc
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            raise
        return entry

    def load(self, invocation_nonce: str) -> PublisherReplayLedgerEntry:
        entry = _load_canonical(
            self._path(invocation_nonce),
            PublisherReplayLedgerEntry.from_mapping,
            name="publisher replay ledger entry",
        )
        if entry.ledger_id != self._ledger_id:
            raise PublisherAuthorizationError("replay ledger entry belongs to another ledger")
        return entry


@dataclass(frozen=True, slots=True)
class PublisherPreflightReceipt:
    lease: PublisherAuthorizationLease
    lease_sha256: str
    replay_entry: PublisherReplayLedgerEntry
    replay_entry_sha256: str
    signed_request_sha256: str
    request_sha256: str
    readiness_sha256: str
    task_sha256: str
    invocation_nonce: str
    remote_repository_sha256: str
    credential_policy_sha256: str
    checked_at_utc: str
    authorized_operations: tuple[str, ...]
    lease_valid: bool = True
    nonce_consumed: bool = True
    remote_identity_matches: bool = True
    credential_policy_matches: bool = True
    exact_draft_only_scope: bool = True
    credential_material_present: bool = False
    write_adapter_present: bool = False
    repository_write_performed: bool = False
    network_write_performed: bool = False
    merge_authority: str = "human"
    schema: str = PUBLISHER_PREFLIGHT_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PUBLISHER_PREFLIGHT_RECEIPT_SCHEMA:
            raise PublisherAuthorizationError("unsupported publisher preflight receipt schema")
        if not isinstance(self.lease, PublisherAuthorizationLease):
            raise PublisherAuthorizationError("preflight lease is invalid")
        if not isinstance(self.replay_entry, PublisherReplayLedgerEntry):
            raise PublisherAuthorizationError("preflight replay entry is invalid")
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
        consumed = _utc(self.replay_entry.consumed_at_utc, name="nonce consumption time")
        expires = _utc(self.lease.expires_at_utc, name="lease expiry time")
        if checked < consumed or checked >= expires:
            raise PublisherAuthorizationError("preflight check is outside the consumed lease window")
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
            or self.remote_repository_sha256 != self.lease.remote_repository_sha256
            or self.credential_policy_sha256 != self.lease.credential_policy_sha256
            or self.authorized_operations != request.requested_operations
        ):
            raise PublisherAuthorizationError("preflight receipt identities are inconsistent")
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
            raise PublisherAuthorizationError("preflight receipt authority boundary is invalid")

    @classmethod
    def from_consumed_lease(
        cls,
        *,
        lease: PublisherAuthorizationLease,
        replay_entry: PublisherReplayLedgerEntry,
        task: DevelopmentTask,
        authorization_verifier: PublisherAuthorizationVerifier,
        publisher_verifier: PublisherRequestVerifier,
        semantic_verifier: SemanticReviewVerifier,
        control_plane_root: Path,
        checked_at_utc: str,
    ) -> "PublisherPreflightReceipt":
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
            authorized_operations=lease.signed_request.request.requested_operations,
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "PublisherPreflightReceipt":
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
        data = _strict(value, name="publisher preflight receipt", fields=fields)
        operations = data["authorized_operations"]
        if not isinstance(operations, list):
            raise PublisherAuthorizationError("preflight operations must be an array")
        return cls(
            schema=data["schema"],
            lease=PublisherAuthorizationLease.from_mapping(data["lease"]),
            lease_sha256=data["lease_sha256"],
            replay_entry=PublisherReplayLedgerEntry.from_mapping(data["replay_entry"]),
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
        authorization_verifier: PublisherAuthorizationVerifier,
        publisher_verifier: PublisherRequestVerifier,
        semantic_verifier: SemanticReviewVerifier,
        control_plane_root: Path,
    ) -> None:
        authorization_verifier.verify(
            lease=self.lease,
            task=task,
            publisher_verifier=publisher_verifier,
            semantic_verifier=semantic_verifier,
            control_plane_root=Path(control_plane_root),
            at_utc=self.checked_at_utc,
        )
        self.replay_entry.verify_against(self.lease)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "lease": self.lease.to_dict(),
            "lease_sha256": self.lease_sha256,
            "replay_entry": self.replay_entry.to_dict(),
            "replay_entry_sha256": self.replay_entry_sha256,
            "signed_request_sha256": self.signed_request_sha256,
            "request_sha256": self.request_sha256,
            "readiness_sha256": self.readiness_sha256,
            "task_sha256": self.task_sha256,
            "invocation_nonce": self.invocation_nonce,
            "remote_repository_sha256": self.remote_repository_sha256,
            "credential_policy_sha256": self.credential_policy_sha256,
            "checked_at_utc": self.checked_at_utc,
            "authorized_operations": list(self.authorized_operations),
            "lease_valid": self.lease_valid,
            "nonce_consumed": self.nonce_consumed,
            "remote_identity_matches": self.remote_identity_matches,
            "credential_policy_matches": self.credential_policy_matches,
            "exact_draft_only_scope": self.exact_draft_only_scope,
            "credential_material_present": self.credential_material_present,
            "write_adapter_present": self.write_adapter_present,
            "repository_write_performed": self.repository_write_performed,
            "network_write_performed": self.network_write_performed,
            "merge_authority": self.merge_authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_bytes(self.canonical_json().encode("utf-8"))


class PublisherPreflightGate:
    @staticmethod
    def valid(
        *,
        receipt: PublisherPreflightReceipt,
        task: DevelopmentTask,
        authorization_verifier: PublisherAuthorizationVerifier,
        publisher_verifier: PublisherRequestVerifier,
        semantic_verifier: SemanticReviewVerifier,
        control_plane_root: Path,
    ) -> bool:
        if not isinstance(receipt, PublisherPreflightReceipt):
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
class PublisherPostconditionReceipt:
    preflight: PublisherPreflightReceipt
    preflight_sha256: str
    lease_sha256: str
    replay_entry_sha256: str
    request_sha256: str
    invocation_nonce: str
    remote_repository_sha256: str
    credential_policy_sha256: str
    observed_at_utc: str
    execution_state: str = "not_executed"
    postconditions_verified: bool = False
    repository_state_observed: bool = False
    network_state_observed: bool = False
    repository_write_performed: bool = False
    network_write_performed: bool = False
    commit_created: bool = False
    branch_created: bool = False
    branch_pushed: bool = False
    pull_request_created: bool = False
    ready_for_review: bool = False
    reviewers_requested: bool = False
    merged: bool = False
    released: bool = False
    deployed: bool = False
    merge_authority: str = "human"
    schema: str = PUBLISHER_POSTCONDITION_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PUBLISHER_POSTCONDITION_RECEIPT_SCHEMA:
            raise PublisherAuthorizationError(
                "unsupported publisher postcondition receipt schema"
            )
        if not isinstance(self.preflight, PublisherPreflightReceipt):
            raise PublisherAuthorizationError("postcondition preflight is invalid")
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
        observed = _utc(self.observed_at_utc, name="postcondition observation time")
        checked = _utc(self.preflight.checked_at_utc, name="preflight check time")
        expires = _utc(self.preflight.lease.expires_at_utc, name="lease expiry time")
        if observed < checked or observed >= expires:
            raise PublisherAuthorizationError(
                "postcondition observation is outside the lease window"
            )
        if (
            self.preflight_sha256 != self.preflight.sha256
            or self.lease_sha256 != self.preflight.lease_sha256
            or self.replay_entry_sha256 != self.preflight.replay_entry_sha256
            or self.request_sha256 != self.preflight.request_sha256
            or self.invocation_nonce != self.preflight.invocation_nonce
            or self.remote_repository_sha256 != self.preflight.remote_repository_sha256
            or self.credential_policy_sha256 != self.preflight.credential_policy_sha256
        ):
            raise PublisherAuthorizationError(
                "postcondition receipt identities are inconsistent"
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
                "postcondition receipt claims unavailable execution or observation"
            )

    @classmethod
    def from_preflight_without_execution(
        cls,
        *,
        preflight: PublisherPreflightReceipt,
        observed_at_utc: str,
    ) -> "PublisherPostconditionReceipt":
        if not isinstance(preflight, PublisherPreflightReceipt):
            raise PublisherAuthorizationError(
                "postcondition receipt requires preflight evidence"
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
    def from_mapping(cls, value: Any) -> "PublisherPostconditionReceipt":
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
        data = _strict(value, name="publisher postcondition receipt", fields=fields)
        return cls(
            schema=data["schema"],
            preflight=PublisherPreflightReceipt.from_mapping(data["preflight"]),
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
        authorization_verifier: PublisherAuthorizationVerifier,
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "preflight": self.preflight.to_dict(),
            "preflight_sha256": self.preflight_sha256,
            "lease_sha256": self.lease_sha256,
            "replay_entry_sha256": self.replay_entry_sha256,
            "request_sha256": self.request_sha256,
            "invocation_nonce": self.invocation_nonce,
            "remote_repository_sha256": self.remote_repository_sha256,
            "credential_policy_sha256": self.credential_policy_sha256,
            "observed_at_utc": self.observed_at_utc,
            "execution_state": self.execution_state,
            "postconditions_verified": self.postconditions_verified,
            "repository_state_observed": self.repository_state_observed,
            "network_state_observed": self.network_state_observed,
            "repository_write_performed": self.repository_write_performed,
            "network_write_performed": self.network_write_performed,
            "commit_created": self.commit_created,
            "branch_created": self.branch_created,
            "branch_pushed": self.branch_pushed,
            "pull_request_created": self.pull_request_created,
            "ready_for_review": self.ready_for_review,
            "reviewers_requested": self.reviewers_requested,
            "merged": self.merged,
            "released": self.released,
            "deployed": self.deployed,
            "merge_authority": self.merge_authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_bytes(self.canonical_json().encode("utf-8"))


class PublisherPostconditionGate:
    @staticmethod
    def valid(
        *,
        receipt: PublisherPostconditionReceipt,
        task: DevelopmentTask,
        authorization_verifier: PublisherAuthorizationVerifier,
        publisher_verifier: PublisherRequestVerifier,
        semantic_verifier: SemanticReviewVerifier,
        control_plane_root: Path,
    ) -> bool:
        if not isinstance(receipt, PublisherPostconditionReceipt):
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


_T = TypeVar("_T")


def _load_canonical(path: Path, parser: Callable[[Any], _T], *, name: str) -> _T:
    raw_path = Path(path)
    if not raw_path.is_absolute() or _has_linkish_component(raw_path) or not raw_path.is_file():
        raise PublisherAuthorizationError(f"{name} must be an absolute regular file")
    raw = raw_path.read_bytes()
    if not 2 <= len(raw) <= _MAX_ARTIFACT_BYTES:
        raise PublisherAuthorizationError(f"{name} size is invalid")
    try:
        value = parser(json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublisherAuthorizationError(f"{name} JSON is invalid") from exc
    canonical_json = getattr(value, "canonical_json", None)
    if canonical_json is None or raw != canonical_json().encode("utf-8"):
        raise PublisherAuthorizationError(f"{name} is not canonical JSON")
    return value


def _write_canonical(path: Path, value: Any, *, name: str, prefix: str) -> str:
    canonical_json = getattr(value, "canonical_json", None)
    if canonical_json is None:
        raise PublisherAuthorizationError(f"{name} output is invalid")
    output = Path(path)
    if (
        not output.is_absolute()
        or output.exists()
        or _has_linkish_component(output.parent)
        or not output.parent.is_dir()
    ):
        raise PublisherAuthorizationError(f"{name} output path is unsafe or already exists")
    payload = canonical_json().encode("utf-8")
    if len(payload) > _MAX_ARTIFACT_BYTES:
        raise PublisherAuthorizationError(f"{name} exceeds its byte bound")
    descriptor, temporary_name = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=output.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, output)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return _sha256_bytes(payload)


def load_publisher_authorization_lease(path: Path) -> PublisherAuthorizationLease:
    return _load_canonical(
        path,
        PublisherAuthorizationLease.from_mapping,
        name="publisher authorization lease",
    )


def write_publisher_authorization_lease(
    path: Path, lease: PublisherAuthorizationLease
) -> str:
    if not isinstance(lease, PublisherAuthorizationLease):
        raise PublisherAuthorizationError("publisher authorization lease output is invalid")
    return _write_canonical(
        path,
        lease,
        name="publisher authorization lease",
        prefix=".publisher-authorization-",
    )


def load_publisher_replay_ledger_entry(path: Path) -> PublisherReplayLedgerEntry:
    return _load_canonical(
        path,
        PublisherReplayLedgerEntry.from_mapping,
        name="publisher replay ledger entry",
    )


def write_publisher_replay_ledger_entry(
    path: Path, entry: PublisherReplayLedgerEntry
) -> str:
    if not isinstance(entry, PublisherReplayLedgerEntry):
        raise PublisherAuthorizationError("publisher replay ledger entry output is invalid")
    return _write_canonical(
        path,
        entry,
        name="publisher replay ledger entry",
        prefix=".publisher-replay-entry-",
    )


def load_publisher_preflight_receipt(path: Path) -> PublisherPreflightReceipt:
    return _load_canonical(
        path,
        PublisherPreflightReceipt.from_mapping,
        name="publisher preflight receipt",
    )


def write_publisher_preflight_receipt(
    path: Path, receipt: PublisherPreflightReceipt
) -> str:
    if not isinstance(receipt, PublisherPreflightReceipt):
        raise PublisherAuthorizationError("publisher preflight receipt output is invalid")
    return _write_canonical(
        path,
        receipt,
        name="publisher preflight receipt",
        prefix=".publisher-preflight-",
    )


def load_publisher_postcondition_receipt(path: Path) -> PublisherPostconditionReceipt:
    return _load_canonical(
        path,
        PublisherPostconditionReceipt.from_mapping,
        name="publisher postcondition receipt",
    )


def write_publisher_postcondition_receipt(
    path: Path, receipt: PublisherPostconditionReceipt
) -> str:
    if not isinstance(receipt, PublisherPostconditionReceipt):
        raise PublisherAuthorizationError(
            "publisher postcondition receipt output is invalid"
        )
    return _write_canonical(
        path,
        receipt,
        name="publisher postcondition receipt",
        prefix=".publisher-postcondition-",
    )
