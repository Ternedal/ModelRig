"""Authenticated publisher intent and deterministic dry-run evidence only.

This module deliberately contains no Git transport, GitHub client, network write,
branch mutation, pull-request mutation, merge, release or deployment adapter.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Mapping, TypeVar

from .contract import DevelopmentTask, MergeAuthority
from .draft_pr_readiness import (
    AuthenticatedDraftPrReadinessProposal,
    DraftPrReadinessError,
)
from .durable_publication import DurablePublicationError, create_once_file
from .semantic_review import SemanticReviewVerifier

PUBLISHER_REQUEST_SCHEMA = "kaliv-development-publisher-request/v1"
SIGNED_PUBLISHER_REQUEST_SCHEMA = "kaliv-development-signed-publisher-request/v1"
PUBLISHER_DRY_RUN_RECEIPT_SCHEMA = "kaliv-development-publisher-dry-run-receipt/v1"

_PUBLISHER_POLICY_DOMAIN = b"kaliv-publisher-dry-run-policy/v1\0"
_PUBLISHER_SIGNATURE_DOMAIN = b"kaliv-signed-publisher-request/v1\0"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ACTOR_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
_MAX_SECRET_BYTES = 4096

PUBLISHER_DRY_RUN_POLICY = (
    "Accept only one complete Slice 10I readiness artifact that still verifies against the exact task, trusted semantic reviewer and current execution authority.",
    "Require a separately authenticated publisher actor who differs from the developer and semantic reviewer.",
    "Bind one explicit invocation nonce, the exact readiness artifact and a fixed ordered set of draft-only publication operations.",
    "Describe commit, branch, push and draft pull-request intent deterministically without executing Git, network or GitHub writes.",
    "Keep ready-for-review, reviewer requests, merge, release, settings, deployment and runtime activation outside the request and receipt.",
    "Fail closed on any task, readiness, signature, actor, policy, operation-plan or canonical-byte mismatch.",
)


class PublisherDryRunError(ValueError):
    """Publisher intent or dry-run evidence is malformed or unauthenticated."""


class PublisherOperationKind(StrEnum):
    VERIFY_READINESS = "verify_exact_readiness"
    MATERIALIZE_COMMIT = "materialize_exact_candidate_commit"
    CREATE_BRANCH = "create_proposed_branch"
    PUSH_BRANCH = "push_proposed_branch"
    CREATE_DRAFT_PR = "create_draft_pull_request"


_REQUESTED_OPERATIONS = tuple(item.value for item in PublisherOperationKind)


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
        raise PublisherDryRunError(f"{name} fields mismatch")
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
        raise PublisherDryRunError(f"{name} is invalid")
    return value


def _hex(value: Any, *, name: str, pattern: re.Pattern[str] = _HEX64) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PublisherDryRunError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR_ID.fullmatch(value) is None:
        raise PublisherDryRunError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise PublisherDryRunError(f"{name} is invalid")
    return value


def _secret(value: Any) -> bytes:
    if not isinstance(value, bytes) or not 32 <= len(value) <= _MAX_SECRET_BYTES:
        raise PublisherDryRunError("publisher signing secret must contain 32..4096 bytes")
    return value


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


def publisher_dry_run_policy_sha256() -> str:
    payload = json.dumps(
        list(PUBLISHER_DRY_RUN_POLICY),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(_PUBLISHER_POLICY_DOMAIN + payload)


def _request_signature(*, key_id: str, secret: bytes, request_json: str) -> str:
    payload = (
        _PUBLISHER_SIGNATURE_DOMAIN
        + key_id.encode("utf-8")
        + b"\0"
        + request_json.encode("utf-8")
    )
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def _commit_message(task: DevelopmentTask) -> str:
    goal = " ".join(task.goal.split())
    message = f"devcontrol({task.task_id.lower()}): {goal}"
    if len(message.encode("utf-8")) > 240:
        message = f"devcontrol({task.task_id.lower()}): apply authenticated candidate"
    return _clean_text(message, name="planned commit message", maximum=240, one_line=True)


@dataclass(frozen=True, slots=True)
class PublisherRequest:
    readiness: AuthenticatedDraftPrReadinessProposal
    readiness_sha256: str
    task_sha256: str
    repository: str
    base_sha: str
    base_branch: str
    head_branch: str
    staged_patch_sha256: str
    staged_patch_bytes: int
    title_sha256: str
    body_sha256: str
    publisher_actor_id: str
    publisher_system_id: str
    invocation_nonce: str
    requested_operations: tuple[str, ...]
    publisher_policy_sha256: str
    human_invoked: bool = True
    dry_run_only: bool = True
    draft_only: bool = True
    merge_authority: str = "human"
    schema: str = PUBLISHER_REQUEST_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PUBLISHER_REQUEST_SCHEMA:
            raise PublisherDryRunError("unsupported publisher request schema")
        if not isinstance(self.readiness, AuthenticatedDraftPrReadinessProposal):
            raise PublisherDryRunError("publisher request readiness artifact is invalid")
        for name, value in (
            ("readiness hash", self.readiness_sha256),
            ("task hash", self.task_sha256),
            ("staged patch hash", self.staged_patch_sha256),
            ("title hash", self.title_sha256),
            ("body hash", self.body_sha256),
            ("publisher policy hash", self.publisher_policy_sha256),
            ("invocation nonce", self.invocation_nonce),
        ):
            _hex(value, name=name)
        _hex(self.base_sha, name="base SHA", pattern=_HEX40)
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PublisherDryRunError("publisher request repository is invalid")
        _clean_text(self.base_branch, name="base branch", maximum=200, one_line=True)
        _clean_text(self.head_branch, name="head branch", maximum=200, one_line=True)
        publisher = _actor(self.publisher_actor_id, name="publisher actor")
        _identifier(self.publisher_system_id, name="publisher system")
        if (
            isinstance(self.staged_patch_bytes, bool)
            or not isinstance(self.staged_patch_bytes, int)
            or self.staged_patch_bytes <= 0
        ):
            raise PublisherDryRunError("publisher request patch byte count is invalid")
        if self.requested_operations != _REQUESTED_OPERATIONS:
            raise PublisherDryRunError("publisher request operations are not the fixed draft-only set")
        if (
            self.human_invoked is not True
            or self.dry_run_only is not True
            or self.draft_only is not True
            or self.merge_authority != "human"
        ):
            raise PublisherDryRunError("publisher request authority boundary is invalid")
        readiness = self.readiness
        if self.readiness_sha256 != readiness.sha256:
            raise PublisherDryRunError("publisher request readiness hash is inconsistent")
        if (
            self.task_sha256 != readiness.task_sha256
            or self.repository != readiness.repository
            or self.base_sha != readiness.base_sha
            or self.base_branch != readiness.base_branch
            or self.head_branch != readiness.head_branch
            or self.staged_patch_sha256 != readiness.staged_patch_sha256
            or self.staged_patch_bytes != readiness.staged_patch_bytes
            or self.title_sha256 != _sha256_bytes(readiness.title.encode("utf-8"))
            or self.body_sha256 != _sha256_bytes(readiness.body.encode("utf-8"))
        ):
            raise PublisherDryRunError("publisher request identities are inconsistent")
        developer = readiness.semantic_review_request.developer_actor_id
        reviewer = readiness.reviewer_actor_id
        if publisher in {developer, reviewer}:
            raise PublisherDryRunError("publisher actor must be separate from developer and reviewer")
        if self.publisher_policy_sha256 != publisher_dry_run_policy_sha256():
            raise PublisherDryRunError("publisher dry-run policy is unsupported")

    @classmethod
    def from_readiness(
        cls,
        *,
        readiness: AuthenticatedDraftPrReadinessProposal,
        task: DevelopmentTask,
        semantic_verifier: SemanticReviewVerifier,
        control_plane_root: Path,
        publisher_actor_id: str,
        publisher_system_id: str,
        invocation_nonce: str,
    ) -> "PublisherRequest":
        if not isinstance(readiness, AuthenticatedDraftPrReadinessProposal):
            raise PublisherDryRunError("publisher request requires a readiness artifact")
        if not isinstance(task, DevelopmentTask):
            raise PublisherDryRunError("publisher request requires a validated task")
        if task.merge_authority is not MergeAuthority.HUMAN:
            raise PublisherDryRunError("merge authority must remain human")
        try:
            readiness.verify(
                task=task,
                verifier=semantic_verifier,
                control_plane_root=Path(control_plane_root),
            )
        except DraftPrReadinessError as exc:
            raise PublisherDryRunError(f"readiness verification failed: {exc}") from exc
        return cls(
            readiness=readiness,
            readiness_sha256=readiness.sha256,
            task_sha256=readiness.task_sha256,
            repository=readiness.repository,
            base_sha=readiness.base_sha,
            base_branch=readiness.base_branch,
            head_branch=readiness.head_branch,
            staged_patch_sha256=readiness.staged_patch_sha256,
            staged_patch_bytes=readiness.staged_patch_bytes,
            title_sha256=_sha256_bytes(readiness.title.encode("utf-8")),
            body_sha256=_sha256_bytes(readiness.body.encode("utf-8")),
            publisher_actor_id=publisher_actor_id,
            publisher_system_id=publisher_system_id,
            invocation_nonce=invocation_nonce,
            requested_operations=_REQUESTED_OPERATIONS,
            publisher_policy_sha256=publisher_dry_run_policy_sha256(),
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "PublisherRequest":
        fields = {
            "schema", "readiness", "readiness_sha256", "task_sha256",
            "repository", "base_sha", "base_branch", "head_branch",
            "staged_patch_sha256", "staged_patch_bytes", "title_sha256",
            "body_sha256", "publisher_actor_id", "publisher_system_id",
            "invocation_nonce", "requested_operations", "publisher_policy_sha256",
            "human_invoked", "dry_run_only", "draft_only", "merge_authority",
        }
        data = _strict(value, name="publisher request", fields=fields)
        operations = data["requested_operations"]
        if not isinstance(operations, list):
            raise PublisherDryRunError("publisher request operations must be an array")
        return cls(
            schema=data["schema"],
            readiness=AuthenticatedDraftPrReadinessProposal.from_mapping(data["readiness"]),
            readiness_sha256=data["readiness_sha256"],
            task_sha256=data["task_sha256"],
            repository=data["repository"],
            base_sha=data["base_sha"],
            base_branch=data["base_branch"],
            head_branch=data["head_branch"],
            staged_patch_sha256=data["staged_patch_sha256"],
            staged_patch_bytes=data["staged_patch_bytes"],
            title_sha256=data["title_sha256"],
            body_sha256=data["body_sha256"],
            publisher_actor_id=data["publisher_actor_id"],
            publisher_system_id=data["publisher_system_id"],
            invocation_nonce=data["invocation_nonce"],
            requested_operations=tuple(operations),
            publisher_policy_sha256=data["publisher_policy_sha256"],
            human_invoked=data["human_invoked"],
            dry_run_only=data["dry_run_only"],
            draft_only=data["draft_only"],
            merge_authority=data["merge_authority"],
        )

    def verify(
        self,
        *,
        task: DevelopmentTask,
        semantic_verifier: SemanticReviewVerifier,
        control_plane_root: Path,
    ) -> None:
        if not isinstance(task, DevelopmentTask):
            raise PublisherDryRunError("publisher request verification requires a task")
        if task.canonical_json() != self.readiness.task.canonical_json():
            raise PublisherDryRunError("publisher request is bound to another task")
        try:
            self.readiness.verify(
                task=task,
                verifier=semantic_verifier,
                control_plane_root=Path(control_plane_root),
            )
        except DraftPrReadinessError as exc:
            raise PublisherDryRunError(f"readiness verification failed: {exc}") from exc
        if self.readiness_sha256 != self.readiness.sha256:
            raise PublisherDryRunError("publisher request readiness no longer matches")
        if self.publisher_policy_sha256 != publisher_dry_run_policy_sha256():
            raise PublisherDryRunError("publisher request policy no longer matches")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "readiness": self.readiness.to_dict(),
            "readiness_sha256": self.readiness_sha256,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "base_branch": self.base_branch,
            "head_branch": self.head_branch,
            "staged_patch_sha256": self.staged_patch_sha256,
            "staged_patch_bytes": self.staged_patch_bytes,
            "title_sha256": self.title_sha256,
            "body_sha256": self.body_sha256,
            "publisher_actor_id": self.publisher_actor_id,
            "publisher_system_id": self.publisher_system_id,
            "invocation_nonce": self.invocation_nonce,
            "requested_operations": list(self.requested_operations),
            "publisher_policy_sha256": self.publisher_policy_sha256,
            "human_invoked": self.human_invoked,
            "dry_run_only": self.dry_run_only,
            "draft_only": self.draft_only,
            "merge_authority": self.merge_authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_bytes(self.canonical_json().encode("utf-8"))


@dataclass(frozen=True, slots=True)
class SignedPublisherRequest:
    request: PublisherRequest
    request_sha256: str
    key_id: str
    algorithm: str
    signature_sha256: str
    schema: str = SIGNED_PUBLISHER_REQUEST_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SIGNED_PUBLISHER_REQUEST_SCHEMA:
            raise PublisherDryRunError("unsupported signed publisher request schema")
        if not isinstance(self.request, PublisherRequest):
            raise PublisherDryRunError("signed publisher request payload is invalid")
        _hex(self.request_sha256, name="signed publisher request hash")
        _identifier(self.key_id, name="publisher key ID")
        if self.algorithm != "hmac-sha256":
            raise PublisherDryRunError("publisher signature algorithm is unsupported")
        _hex(self.signature_sha256, name="publisher request signature")
        if self.request_sha256 != self.request.sha256:
            raise PublisherDryRunError("signed publisher request hash is inconsistent")

    @classmethod
    def from_mapping(cls, value: Any) -> "SignedPublisherRequest":
        data = _strict(
            value,
            name="signed publisher request",
            fields={"schema", "request", "request_sha256", "key_id", "algorithm", "signature_sha256"},
        )
        return cls(
            schema=data["schema"],
            request=PublisherRequest.from_mapping(data["request"]),
            request_sha256=data["request_sha256"],
            key_id=data["key_id"],
            algorithm=data["algorithm"],
            signature_sha256=data["signature_sha256"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "request": self.request.to_dict(),
            "request_sha256": self.request_sha256,
            "key_id": self.key_id,
            "algorithm": self.algorithm,
            "signature_sha256": self.signature_sha256,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_bytes(self.canonical_json().encode("utf-8"))


@dataclass(frozen=True, slots=True)
class TrustedPublisherKey:
    publisher_actor_id: str
    secret: bytes

    def __post_init__(self) -> None:
        _actor(self.publisher_actor_id, name="trusted publisher actor")
        _secret(self.secret)


class HmacPublisherRequestSigner:
    def __init__(self, *, key_id: str, publisher_actor_id: str, secret: bytes) -> None:
        self._key_id = _identifier(key_id, name="publisher key ID")
        self._publisher_actor_id = _actor(publisher_actor_id, name="publisher actor")
        self._secret = _secret(secret)

    def sign(self, request: PublisherRequest) -> SignedPublisherRequest:
        if not isinstance(request, PublisherRequest):
            raise PublisherDryRunError("publisher signer requires a publisher request")
        if request.publisher_actor_id != self._publisher_actor_id:
            raise PublisherDryRunError("publisher signing key is bound to another actor")
        return SignedPublisherRequest(
            request=request,
            request_sha256=request.sha256,
            key_id=self._key_id,
            algorithm="hmac-sha256",
            signature_sha256=_request_signature(
                key_id=self._key_id,
                secret=self._secret,
                request_json=request.canonical_json(),
            ),
        )


class PublisherRequestVerifier:
    def __init__(self, trusted_keys: Mapping[str, TrustedPublisherKey]) -> None:
        if not isinstance(trusted_keys, Mapping) or not trusted_keys:
            raise PublisherDryRunError("publisher verifier requires a non-empty trusted keyring")
        keys: dict[str, TrustedPublisherKey] = {}
        for key_id, trusted in trusted_keys.items():
            canonical_id = _identifier(key_id, name="trusted publisher key ID")
            if not isinstance(trusted, TrustedPublisherKey):
                raise PublisherDryRunError("trusted publisher keyring entry is invalid")
            keys[canonical_id] = trusted
        self._trusted_keys = keys

    def verify(
        self,
        *,
        signed_request: SignedPublisherRequest,
        task: DevelopmentTask,
        semantic_verifier: SemanticReviewVerifier,
        control_plane_root: Path,
    ) -> PublisherRequest:
        if not isinstance(signed_request, SignedPublisherRequest):
            raise PublisherDryRunError("publisher verification requires a signed request")
        trusted = self._trusted_keys.get(signed_request.key_id)
        if trusted is None:
            raise PublisherDryRunError("publisher key is not trusted")
        request = signed_request.request
        if trusted.publisher_actor_id != request.publisher_actor_id:
            raise PublisherDryRunError("publisher key is bound to another actor")
        expected = _request_signature(
            key_id=signed_request.key_id,
            secret=trusted.secret,
            request_json=request.canonical_json(),
        )
        if not hmac.compare_digest(expected, signed_request.signature_sha256):
            raise PublisherDryRunError("publisher request signature is invalid")
        request.verify(
            task=task,
            semantic_verifier=semantic_verifier,
            control_plane_root=Path(control_plane_root),
        )
        return request


@dataclass(frozen=True, slots=True)
class PublisherOperationParameter:
    name: str
    value: str

    def __post_init__(self) -> None:
        _identifier(self.name, name="operation parameter name")
        _clean_text(self.value, name="operation parameter value", maximum=120_000)

    @classmethod
    def from_mapping(cls, value: Any) -> "PublisherOperationParameter":
        data = _strict(value, name="publisher operation parameter", fields={"name", "value"})
        return cls(name=data["name"], value=data["value"])

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "value": self.value}


@dataclass(frozen=True, slots=True)
class PublisherDryRunOperation:
    sequence: int
    operation: PublisherOperationKind
    parameters: tuple[PublisherOperationParameter, ...]
    repository_write_required: bool
    network_write_required: bool
    status: str = "planned_not_executed"

    def __post_init__(self) -> None:
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or not 1 <= self.sequence <= 5:
            raise PublisherDryRunError("publisher operation sequence is invalid")
        if not isinstance(self.operation, PublisherOperationKind):
            raise PublisherDryRunError("publisher operation kind is invalid")
        if (
            not isinstance(self.parameters, tuple)
            or not self.parameters
            or any(not isinstance(item, PublisherOperationParameter) for item in self.parameters)
        ):
            raise PublisherDryRunError("publisher operation parameters are invalid")
        names = tuple(item.name for item in self.parameters)
        if len(names) != len(set(names)):
            raise PublisherDryRunError("publisher operation parameter names must be unique")
        if not isinstance(self.repository_write_required, bool) or not isinstance(self.network_write_required, bool):
            raise PublisherDryRunError("publisher operation write flags are invalid")
        if self.status != "planned_not_executed":
            raise PublisherDryRunError("publisher operation must remain unexecuted")

    @classmethod
    def from_mapping(cls, value: Any) -> "PublisherDryRunOperation":
        data = _strict(
            value,
            name="publisher dry-run operation",
            fields={"sequence", "operation", "parameters", "repository_write_required", "network_write_required", "status"},
        )
        parameters = data["parameters"]
        if not isinstance(parameters, list):
            raise PublisherDryRunError("publisher operation parameters must be an array")
        try:
            kind = PublisherOperationKind(data["operation"])
        except (TypeError, ValueError) as exc:
            raise PublisherDryRunError("publisher operation kind is unsupported") from exc
        return cls(
            sequence=data["sequence"],
            operation=kind,
            parameters=tuple(PublisherOperationParameter.from_mapping(item) for item in parameters),
            repository_write_required=data["repository_write_required"],
            network_write_required=data["network_write_required"],
            status=data["status"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "operation": self.operation.value,
            "parameters": [item.to_dict() for item in self.parameters],
            "repository_write_required": self.repository_write_required,
            "network_write_required": self.network_write_required,
            "status": self.status,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_bytes(self.canonical_json().encode("utf-8"))


def _parameters(**values: str) -> tuple[PublisherOperationParameter, ...]:
    return tuple(PublisherOperationParameter(name=name, value=value) for name, value in values.items())


def _expected_operations(request: PublisherRequest) -> tuple[PublisherDryRunOperation, ...]:
    readiness = request.readiness
    task = readiness.task
    verify = PublisherDryRunOperation(
        sequence=1,
        operation=PublisherOperationKind.VERIFY_READINESS,
        parameters=_parameters(
            readiness_sha256=request.readiness_sha256,
            task_sha256=request.task_sha256,
            execution_authority_sha256=readiness.execution_authority_sha256,
            semantic_review_request_sha256=readiness.semantic_review_request_sha256,
            signed_semantic_review_verdict_sha256=readiness.signed_semantic_review_verdict_sha256,
        ),
        repository_write_required=False,
        network_write_required=False,
    )
    commit = PublisherDryRunOperation(
        sequence=2,
        operation=PublisherOperationKind.MATERIALIZE_COMMIT,
        parameters=_parameters(
            repository=request.repository,
            parent_sha=request.base_sha,
            staged_patch_sha256=request.staged_patch_sha256,
            staged_patch_bytes=str(request.staged_patch_bytes),
            commit_message=_commit_message(task),
            author_actor_id=request.publisher_actor_id,
        ),
        repository_write_required=True,
        network_write_required=False,
    )
    branch = PublisherDryRunOperation(
        sequence=3,
        operation=PublisherOperationKind.CREATE_BRANCH,
        parameters=_parameters(
            repository=request.repository,
            head_branch=request.head_branch,
            parent_sha=request.base_sha,
            commit_plan_sha256=commit.sha256,
        ),
        repository_write_required=True,
        network_write_required=False,
    )
    push = PublisherDryRunOperation(
        sequence=4,
        operation=PublisherOperationKind.PUSH_BRANCH,
        parameters=_parameters(
            repository=request.repository,
            head_branch=request.head_branch,
            branch_plan_sha256=branch.sha256,
        ),
        repository_write_required=True,
        network_write_required=True,
    )
    draft_pr = PublisherDryRunOperation(
        sequence=5,
        operation=PublisherOperationKind.CREATE_DRAFT_PR,
        parameters=_parameters(
            repository=request.repository,
            base_branch=request.base_branch,
            head_branch=request.head_branch,
            title=readiness.title,
            body_sha256=request.body_sha256,
            draft="true",
            merge_authority="human",
            push_plan_sha256=push.sha256,
        ),
        repository_write_required=True,
        network_write_required=True,
    )
    return (verify, commit, branch, push, draft_pr)


@dataclass(frozen=True, slots=True)
class PublisherDryRunReceipt:
    signed_request: SignedPublisherRequest
    signed_request_sha256: str
    request_sha256: str
    readiness_sha256: str
    task_sha256: str
    repository: str
    base_sha: str
    head_branch: str
    staged_patch_sha256: str
    publisher_actor_id: str
    publisher_key_id: str
    operations: tuple[PublisherDryRunOperation, ...]
    publisher_policy_sha256: str
    dry_run: bool = True
    executed: bool = False
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
    schema: str = PUBLISHER_DRY_RUN_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PUBLISHER_DRY_RUN_RECEIPT_SCHEMA:
            raise PublisherDryRunError("unsupported publisher dry-run receipt schema")
        if not isinstance(self.signed_request, SignedPublisherRequest):
            raise PublisherDryRunError("publisher dry-run signed request is invalid")
        for name, value in (
            ("signed publisher request hash", self.signed_request_sha256),
            ("publisher request hash", self.request_sha256),
            ("readiness hash", self.readiness_sha256),
            ("task hash", self.task_sha256),
            ("staged patch hash", self.staged_patch_sha256),
            ("publisher policy hash", self.publisher_policy_sha256),
        ):
            _hex(value, name=name)
        _hex(self.base_sha, name="base SHA", pattern=_HEX40)
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PublisherDryRunError("publisher dry-run repository is invalid")
        _clean_text(self.head_branch, name="publisher dry-run head branch", maximum=200, one_line=True)
        _actor(self.publisher_actor_id, name="publisher actor")
        _identifier(self.publisher_key_id, name="publisher key ID")
        if not isinstance(self.operations, tuple) or len(self.operations) != 5:
            raise PublisherDryRunError("publisher dry-run operation plan is incomplete")
        if any(not isinstance(item, PublisherDryRunOperation) for item in self.operations):
            raise PublisherDryRunError("publisher dry-run operation plan is invalid")
        request = self.signed_request.request
        if (
            self.signed_request_sha256 != self.signed_request.sha256
            or self.request_sha256 != request.sha256
            or self.readiness_sha256 != request.readiness_sha256
            or self.task_sha256 != request.task_sha256
            or self.repository != request.repository
            or self.base_sha != request.base_sha
            or self.head_branch != request.head_branch
            or self.staged_patch_sha256 != request.staged_patch_sha256
            or self.publisher_actor_id != request.publisher_actor_id
            or self.publisher_key_id != self.signed_request.key_id
            or self.publisher_policy_sha256 != request.publisher_policy_sha256
        ):
            raise PublisherDryRunError("publisher dry-run receipt identities are inconsistent")
        if self.operations != _expected_operations(request):
            raise PublisherDryRunError("publisher dry-run operation plan is not deterministic")
        if (
            self.dry_run is not True
            or self.executed is not False
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
            raise PublisherDryRunError("publisher dry-run receipt claims forbidden execution")
        if self.publisher_policy_sha256 != publisher_dry_run_policy_sha256():
            raise PublisherDryRunError("publisher dry-run receipt policy is unsupported")

    @classmethod
    def from_signed_request(
        cls,
        *,
        signed_request: SignedPublisherRequest,
        task: DevelopmentTask,
        publisher_verifier: PublisherRequestVerifier,
        semantic_verifier: SemanticReviewVerifier,
        control_plane_root: Path,
    ) -> "PublisherDryRunReceipt":
        if not isinstance(publisher_verifier, PublisherRequestVerifier):
            raise PublisherDryRunError("dry-run receipt requires a publisher verifier")
        request = publisher_verifier.verify(
            signed_request=signed_request,
            task=task,
            semantic_verifier=semantic_verifier,
            control_plane_root=Path(control_plane_root),
        )
        return cls(
            signed_request=signed_request,
            signed_request_sha256=signed_request.sha256,
            request_sha256=request.sha256,
            readiness_sha256=request.readiness_sha256,
            task_sha256=request.task_sha256,
            repository=request.repository,
            base_sha=request.base_sha,
            head_branch=request.head_branch,
            staged_patch_sha256=request.staged_patch_sha256,
            publisher_actor_id=request.publisher_actor_id,
            publisher_key_id=signed_request.key_id,
            operations=_expected_operations(request),
            publisher_policy_sha256=request.publisher_policy_sha256,
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "PublisherDryRunReceipt":
        fields = {
            "schema", "signed_request", "signed_request_sha256", "request_sha256",
            "readiness_sha256", "task_sha256", "repository", "base_sha",
            "head_branch", "staged_patch_sha256", "publisher_actor_id",
            "publisher_key_id", "operations", "publisher_policy_sha256",
            "dry_run", "executed", "repository_write_performed",
            "network_write_performed", "commit_created", "branch_created",
            "branch_pushed", "pull_request_created", "ready_for_review",
            "reviewers_requested", "merged", "released", "deployed",
            "merge_authority",
        }
        data = _strict(value, name="publisher dry-run receipt", fields=fields)
        operations = data["operations"]
        if not isinstance(operations, list):
            raise PublisherDryRunError("publisher dry-run operations must be an array")
        return cls(
            schema=data["schema"],
            signed_request=SignedPublisherRequest.from_mapping(data["signed_request"]),
            signed_request_sha256=data["signed_request_sha256"],
            request_sha256=data["request_sha256"],
            readiness_sha256=data["readiness_sha256"],
            task_sha256=data["task_sha256"],
            repository=data["repository"],
            base_sha=data["base_sha"],
            head_branch=data["head_branch"],
            staged_patch_sha256=data["staged_patch_sha256"],
            publisher_actor_id=data["publisher_actor_id"],
            publisher_key_id=data["publisher_key_id"],
            operations=tuple(PublisherDryRunOperation.from_mapping(item) for item in operations),
            publisher_policy_sha256=data["publisher_policy_sha256"],
            dry_run=data["dry_run"],
            executed=data["executed"],
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
        publisher_verifier: PublisherRequestVerifier,
        semantic_verifier: SemanticReviewVerifier,
        control_plane_root: Path,
    ) -> None:
        request = publisher_verifier.verify(
            signed_request=self.signed_request,
            task=task,
            semantic_verifier=semantic_verifier,
            control_plane_root=Path(control_plane_root),
        )
        if self.operations != _expected_operations(request):
            raise PublisherDryRunError("publisher dry-run operation plan no longer matches")
        if self.publisher_policy_sha256 != publisher_dry_run_policy_sha256():
            raise PublisherDryRunError("publisher dry-run policy no longer matches")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "signed_request": self.signed_request.to_dict(),
            "signed_request_sha256": self.signed_request_sha256,
            "request_sha256": self.request_sha256,
            "readiness_sha256": self.readiness_sha256,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "head_branch": self.head_branch,
            "staged_patch_sha256": self.staged_patch_sha256,
            "publisher_actor_id": self.publisher_actor_id,
            "publisher_key_id": self.publisher_key_id,
            "operations": [item.to_dict() for item in self.operations],
            "publisher_policy_sha256": self.publisher_policy_sha256,
            "dry_run": self.dry_run,
            "executed": self.executed,
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


class PublisherDryRunGate:
    @staticmethod
    def valid(
        *,
        receipt: PublisherDryRunReceipt,
        task: DevelopmentTask,
        publisher_verifier: PublisherRequestVerifier,
        semantic_verifier: SemanticReviewVerifier,
        control_plane_root: Path,
    ) -> bool:
        if not isinstance(receipt, PublisherDryRunReceipt):
            return False
        try:
            receipt.verify(
                task=task,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=Path(control_plane_root),
            )
        except PublisherDryRunError:
            return False
        return True


_T = TypeVar("_T")


def _load_canonical(path: Path, parser: Callable[[Any], _T], *, name: str) -> _T:
    raw_path = Path(path)
    if not raw_path.is_absolute() or _has_linkish_component(raw_path) or not raw_path.is_file():
        raise PublisherDryRunError(f"{name} must be an absolute regular file")
    raw = raw_path.read_bytes()
    if not 2 <= len(raw) <= _MAX_ARTIFACT_BYTES:
        raise PublisherDryRunError(f"{name} size is invalid")
    try:
        value = parser(json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublisherDryRunError(f"{name} JSON is invalid") from exc
    canonical_json = getattr(value, "canonical_json", None)
    if canonical_json is None or raw != canonical_json().encode("utf-8"):
        raise PublisherDryRunError(f"{name} is not canonical JSON")
    return value


def _write_canonical(path: Path, value: Any, *, name: str) -> str:
    canonical_json = getattr(value, "canonical_json", None)
    if canonical_json is None:
        raise PublisherDryRunError(f"{name} output is invalid")
    output = Path(path)
    if (
        not output.is_absolute()
        or output.exists()
        or output.is_symlink()
        or _has_linkish_component(output.parent)
        or not output.parent.is_dir()
    ):
        raise PublisherDryRunError(f"{name} output path is unsafe or already exists")
    payload = canonical_json().encode("utf-8")
    if len(payload) > _MAX_ARTIFACT_BYTES:
        raise PublisherDryRunError(f"{name} exceeds its byte bound")
    try:
        create_once_file(output, payload)
    except (FileExistsError, DurablePublicationError) as exc:
        raise PublisherDryRunError(f"{name} could not be durably published") from exc
    return _sha256_bytes(payload)


def load_publisher_request(path: Path) -> PublisherRequest:
    return _load_canonical(path, PublisherRequest.from_mapping, name="publisher request")


def write_publisher_request(path: Path, request: PublisherRequest) -> str:
    if not isinstance(request, PublisherRequest):
        raise PublisherDryRunError("publisher request output is invalid")
    return _write_canonical(path, request, name="publisher request")


def load_signed_publisher_request(path: Path) -> SignedPublisherRequest:
    return _load_canonical(path, SignedPublisherRequest.from_mapping, name="signed publisher request")


def write_signed_publisher_request(path: Path, signed_request: SignedPublisherRequest) -> str:
    if not isinstance(signed_request, SignedPublisherRequest):
        raise PublisherDryRunError("signed publisher request output is invalid")
    return _write_canonical(path, signed_request, name="signed publisher request")


def load_publisher_dry_run_receipt(path: Path) -> PublisherDryRunReceipt:
    return _load_canonical(path, PublisherDryRunReceipt.from_mapping, name="publisher dry-run receipt")


def write_publisher_dry_run_receipt(path: Path, receipt: PublisherDryRunReceipt) -> str:
    if not isinstance(receipt, PublisherDryRunReceipt):
        raise PublisherDryRunError("publisher dry-run receipt output is invalid")
    return _write_canonical(path, receipt, name="publisher dry-run receipt")