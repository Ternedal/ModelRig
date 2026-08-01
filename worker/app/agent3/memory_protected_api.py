from __future__ import annotations

import hashlib
import hmac
import json
import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, TypeVar

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .memory import MemoryConflict, MemoryNotFound, MemoryRecord, MemoryStoreError
from .memory_protected_reader import (
    MemoryReadAccess,
    ProtectedMemoryReader,
)
from .memory_protected_writer import (
    MemoryWriteAccess,
    ProtectedMemoryWriter,
)


MAX_PROTECTED_MEMORY_API_BODY_BYTES = 64 * 1024
_SHA256_HEX_LENGTH = hashlib.sha256().digest_size * 2


class ProtectedMemoryApiAuthorizationError(MemoryStoreError):
    """A request did not carry an exact, fresh authorization grant."""


class ProtectedMemoryApiRequestError(MemoryStoreError):
    """A protected-memory request was malformed or exceeded its bounded surface."""


class ProtectedMemoryApiAction(str, Enum):
    STATUS = "status"
    READ_METADATA = "read_metadata"
    WRITE_PRIVATE = "write_private"


@dataclass(frozen=True)
class ProtectedMemoryApiGrant:
    """Full request-bound proof produced by the authenticated gateway boundary.

    This is deliberately not a boolean. A caller must bind the principal,
    exact action, request id, HTTP method, worker path, raw query and bounded
    request-body digest to a short validity window. The router independently
    validates every binding and never accepts a string in place of an action.
    """

    principal: str
    action: ProtectedMemoryApiAction
    request_id: str
    method: str
    path: str
    query: str
    body_sha256: str
    issued_at: float
    expires_at: float


ProtectedMemoryApiAuthorizer = Callable[
    [Request, ProtectedMemoryApiAction], ProtectedMemoryApiGrant
]
Clock = Callable[[], float]
ModelT = TypeVar("ModelT", bound=BaseModel)


class _StrictProtectedMemoryWriteReq(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class CreateProtectedMemoryReq(_StrictProtectedMemoryWriteReq):
    subject: str = Field(min_length=1, max_length=200)
    predicate: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=20_000)
    kind: str = Field(
        default="fact",
        pattern="^(fact|preference|project|relationship|routine|constraint|note)$",
    )
    # Secret values are deliberately local-management-only. Public and
    # operational values belong to the unprotected rows and are not created by
    # this private-value boundary.
    sensitivity: str = Field(default="private", pattern="^private$")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    expires_at: float | None = None


class CorrectProtectedMemoryReq(_StrictProtectedMemoryWriteReq):
    expected_updated_at: float = Field(ge=0.0)
    value: str = Field(min_length=1, max_length=20_000)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    expires_at: float | None = None


def _request_id(request: Request) -> str:
    raw = request.headers.get("X-Request-ID", "")
    if not isinstance(raw, str):
        raise ProtectedMemoryApiAuthorizationError("request id is missing")
    value = raw.strip()
    if not value or value != raw or len(value) > 200:
        raise ProtectedMemoryApiAuthorizationError(
            "a canonical X-Request-ID is required"
        )
    return value


def _binding_text(
    name: str,
    value: object,
    *,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ProtectedMemoryApiAuthorizationError(
            f"protected memory grant {name} is invalid"
        )
    cleaned = value.strip()
    if (
        (not allow_empty and not cleaned)
        or (value and cleaned != value)
        or len(value) > maximum
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        raise ProtectedMemoryApiAuthorizationError(
            f"protected memory grant {name} is invalid"
        )
    return value


def _body_digest(value: object) -> str:
    digest = _binding_text(
        "body digest",
        value,
        maximum=_SHA256_HEX_LENGTH,
    )
    if len(digest) != _SHA256_HEX_LENGTH or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant body digest is invalid"
        )
    return digest


def _authorize(
    request: Request,
    action: ProtectedMemoryApiAction,
    authorizer: ProtectedMemoryApiAuthorizer,
    clock: Clock,
) -> ProtectedMemoryApiGrant:
    request_id = _request_id(request)
    try:
        grant = authorizer(request, action)
    except ProtectedMemoryApiAuthorizationError:
        raise
    except Exception as exc:
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory authorization failed closed"
        ) from exc
    if not isinstance(grant, ProtectedMemoryApiGrant):
        raise ProtectedMemoryApiAuthorizationError(
            "authorizer did not return an explicit protected-memory grant"
        )
    if not isinstance(grant.action, ProtectedMemoryApiAction) or grant.action is not action:
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant action mismatch"
        )
    if not isinstance(grant.principal, str):
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant principal is invalid"
        )
    principal = grant.principal.strip()
    if not principal or principal != grant.principal or len(principal) > 200:
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant principal is invalid"
        )
    if grant.request_id != request_id:
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant request mismatch"
        )

    method = _binding_text("method", grant.method, maximum=16)
    path = _binding_text("path", grant.path, maximum=1_000)
    query = _binding_text(
        "query",
        grant.query,
        maximum=4_096,
        allow_empty=True,
    )
    body_sha256 = _body_digest(grant.body_sha256)
    if method != method.upper() or method != request.method.upper():
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant method mismatch"
        )
    if path != request.url.path:
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant path mismatch"
        )
    if query != request.url.query:
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant query mismatch"
        )
    actual_body_sha256 = getattr(
        request.state,
        "agent3_memory_body_sha256",
        None,
    )
    if not hmac.compare_digest(
        _body_digest(actual_body_sha256),
        body_sha256,
    ):
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant body mismatch"
        )

    if (
        isinstance(grant.issued_at, bool)
        or isinstance(grant.expires_at, bool)
    ):
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant timestamps are invalid"
        )
    try:
        issued_at = float(grant.issued_at)
        expires_at = float(grant.expires_at)
        raw_now = clock()
        if isinstance(raw_now, bool):
            raise TypeError("clock returned a boolean")
        now = float(raw_now)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant timestamps are invalid"
        ) from exc
    if not all(math.isfinite(value) for value in (issued_at, expires_at, now)):
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant timestamps are invalid"
        )
    if expires_at <= issued_at:
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant window is invalid"
        )
    if issued_at > now + 5.0:
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant is future-dated"
        )
    if issued_at < now - 120.0 or expires_at <= now:
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant is expired"
        )
    if expires_at - issued_at > 120.0:
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant lifetime is too long"
        )
    return grant


def _query_value(
    request: Request,
    name: str,
    *,
    default: str | None = None,
    required: bool = False,
) -> str | None:
    values = request.query_params.getlist(name)
    if len(values) > 1:
        raise ProtectedMemoryApiRequestError(
            "protected memory query parameter is repeated"
        )
    if not values:
        if required:
            raise ProtectedMemoryApiRequestError(
                "protected memory query parameter is required"
            )
        return default
    return values[0]


def _int_query(
    request: Request,
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = _query_value(request, name)
    if raw is None:
        return default
    if not raw or raw.strip() != raw or not raw.isascii() or not raw.isdecimal():
        raise ProtectedMemoryApiRequestError(
            "protected memory integer query parameter is invalid"
        )
    try:
        value = int(raw, 10)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ProtectedMemoryApiRequestError(
            "protected memory integer query parameter is invalid"
        ) from exc
    if not minimum <= value <= maximum:
        raise ProtectedMemoryApiRequestError(
            "protected memory integer query parameter is outside the allowed range"
        )
    return value


def _bool_query(
    request: Request,
    name: str,
    *,
    default: bool,
) -> bool:
    raw = _query_value(request, name)
    if raw is None:
        return default
    normalized = raw.casefold()
    if normalized in {"1", "true", "on", "yes"}:
        return True
    if normalized in {"0", "false", "off", "no"}:
        return False
    raise ProtectedMemoryApiRequestError(
        "protected memory boolean query parameter is invalid"
    )


def _required_finite_float_query(
    request: Request,
    name: str,
    *,
    minimum: float,
) -> float:
    raw = _query_value(request, name, required=True)
    assert raw is not None
    if not raw or raw.strip() != raw:
        raise ProtectedMemoryApiRequestError(
            "protected memory numeric query parameter is invalid"
        )
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ProtectedMemoryApiRequestError(
            "protected memory numeric query parameter is invalid"
        ) from exc
    if not math.isfinite(value) or value < minimum:
        raise ProtectedMemoryApiRequestError(
            "protected memory numeric query parameter is invalid"
        )
    return value


async def _validated_body(
    request: Request,
    model_type: type[ModelT],
    grant: ProtectedMemoryApiGrant,
) -> ModelT:
    try:
        raw = await request.body()
    except Exception as exc:
        raise ProtectedMemoryApiRequestError(
            "protected memory request body could not be read"
        ) from exc
    if not raw or len(raw) > MAX_PROTECTED_MEMORY_API_BODY_BYTES:
        raise ProtectedMemoryApiRequestError(
            "protected memory request body is outside the allowed size"
        )
    if not hmac.compare_digest(
        hashlib.sha256(raw).hexdigest(),
        grant.body_sha256,
    ):
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant body mismatch"
        )
    try:
        decoded = json.loads(raw)
        return model_type.model_validate(decoded)
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, TypeError) as exc:
        raise ProtectedMemoryApiRequestError(
            "protected memory request body is invalid"
        ) from exc


def _metadata_payload(record: MemoryRecord) -> dict[str, Any]:
    payload = record.to_dict(include_value=False)
    # Be explicit even if MemoryRecord changes: a remote response from this
    # boundary must never carry value or provenance plaintext.
    payload["value"] = "[redacted]" if record.lifecycle_status != "deleted" else ""
    payload["source_ref"] = None
    return payload


def _request_provenance(grant: ProtectedMemoryApiGrant) -> str:
    return f"memory-api:{grant.principal}:{grant.request_id}"


def _raise(exc: Exception) -> None:
    # Public error bodies are deliberately fixed. Internal exception text may
    # contain identifiers or future implementation details and must not become
    # an accidental disclosure surface.
    if isinstance(exc, ProtectedMemoryApiAuthorizationError):
        raise HTTPException(
            status_code=403,
            detail="protected memory authorization denied",
        ) from exc
    if isinstance(exc, MemoryNotFound):
        raise HTTPException(status_code=404, detail="memory not found") from exc
    if isinstance(exc, MemoryConflict):
        raise HTTPException(status_code=409, detail="memory conflict") from exc
    if isinstance(exc, MemoryStoreError):
        raise HTTPException(
            status_code=422,
            detail="protected memory request rejected",
        ) from exc
    raise exc


def build_protected_memory_router(
    reader: ProtectedMemoryReader,
    writer: ProtectedMemoryWriter,
    *,
    authorizer: ProtectedMemoryApiAuthorizer,
    clock: Clock = time.time,
) -> APIRouter:
    """Build a dormant metadata-only API over an already migrated store.

    The caller must inject a real gateway authorizer. There is no permissive
    default, no startup wiring and no secret-value route. Reads use
    ``METADATA_ONLY``; writes are private-only, compare-and-swap protected and
    return redacted records.
    """

    if not callable(authorizer):
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory API requires an explicit authorizer"
        )
    if not callable(clock):
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory API requires an explicit clock"
        )

    router = APIRouter(
        prefix="/experimental/agent3/memory",
        tags=["experimental-agent3-memory"],
    )

    def grant(
        request: Request,
        action: ProtectedMemoryApiAction,
    ) -> ProtectedMemoryApiGrant:
        return _authorize(request, action, authorizer, clock)

    def visible(record: MemoryRecord) -> MemoryRecord:
        # Secret rows are local-management-only. Returning even their metadata
        # from the remote replacement surface would make the redaction policy
        # depend on knowing an opaque id, so treat them as absent.
        if record.sensitivity == "secret":
            raise MemoryNotFound("memory not found")
        return record

    @router.get("/status")
    def status(request: Request) -> dict[str, Any]:
        try:
            grant(request, ProtectedMemoryApiAction.STATUS)
            return {"protected_memory": reader.status.to_dict()}
        except MemoryStoreError as exc:
            _raise(exc)

    @router.get("")
    def list_memories(request: Request) -> dict[str, Any]:
        try:
            grant(request, ProtectedMemoryApiAction.READ_METADATA)
            subject = _query_value(request, "subject")
            predicate = _query_value(request, "predicate")
            review_status = _query_value(request, "review_status")
            lifecycle_status = _query_value(
                request,
                "lifecycle_status",
                default="active",
            )
            include_expired = _bool_query(
                request,
                "include_expired",
                default=False,
            )
            limit = _int_query(
                request,
                "limit",
                default=100,
                minimum=1,
                maximum=500,
            )
            records = reader.list(
                access=MemoryReadAccess.METADATA_ONLY,
                subject=subject,
                predicate=predicate,
                review_status=review_status,
                lifecycle_status=lifecycle_status,
                include_expired=include_expired,
                include_secret=False,
                limit=limit,
            )
            return {"memories": [_metadata_payload(record) for record in records]}
        except MemoryStoreError as exc:
            _raise(exc)

    @router.post("")
    async def create_memory(request: Request) -> dict[str, Any]:
        try:
            authorized = grant(request, ProtectedMemoryApiAction.WRITE_PRIVATE)
            req = await _validated_body(
                request,
                CreateProtectedMemoryReq,
                authorized,
            )
            record = writer.create(
                access=MemoryWriteAccess.LOCAL_MANAGEMENT,
                subject=req.subject,
                predicate=req.predicate,
                value=req.value,
                kind=req.kind,
                sensitivity="private",
                source_type="user_explicit",
                source_ref=_request_provenance(authorized),
                confidence=req.confidence,
                review_status="confirmed",
                expires_at=req.expires_at,
            )
            return {"memory": _metadata_payload(record)}
        except MemoryStoreError as exc:
            _raise(exc)

    # Static route must be registered before /{memory_id}.
    @router.get("/search")
    def search_memories(request: Request) -> dict[str, Any]:
        try:
            grant(request, ProtectedMemoryApiAction.READ_METADATA)
            q = _query_value(request, "q", required=True)
            assert q is not None
            limit = _int_query(
                request,
                "limit",
                default=50,
                minimum=1,
                maximum=200,
            )
            records = reader.search_metadata(
                q,
                access=MemoryReadAccess.METADATA_ONLY,
                confirmed_only=True,
                include_secret=False,
                limit=limit,
            )
            return {"memories": [_metadata_payload(record) for record in records]}
        except MemoryStoreError as exc:
            _raise(exc)

    @router.get("/{memory_id}")
    def get_memory(memory_id: str, request: Request) -> dict[str, Any]:
        try:
            grant(request, ProtectedMemoryApiAction.READ_METADATA)
            record = visible(
                reader.get(
                    memory_id,
                    access=MemoryReadAccess.METADATA_ONLY,
                    include_deleted=True,
                )
            )
            return {"memory": _metadata_payload(record)}
        except MemoryStoreError as exc:
            _raise(exc)

    @router.get("/{memory_id}/history")
    def memory_history(memory_id: str, request: Request) -> dict[str, Any]:
        try:
            grant(request, ProtectedMemoryApiAction.READ_METADATA)
            current = visible(
                reader.get(
                    memory_id,
                    access=MemoryReadAccess.METADATA_ONLY,
                    include_deleted=True,
                )
            )
            records = reader.history(
                current.subject,
                current.predicate,
                access=MemoryReadAccess.METADATA_ONLY,
                include_secret=False,
            )
            return {"memories": [_metadata_payload(record) for record in records]}
        except MemoryStoreError as exc:
            _raise(exc)

    @router.post("/{memory_id}/correct")
    async def correct_memory(
        memory_id: str,
        request: Request,
    ) -> dict[str, Any]:
        try:
            authorized = grant(request, ProtectedMemoryApiAction.WRITE_PRIVATE)
            req = await _validated_body(
                request,
                CorrectProtectedMemoryReq,
                authorized,
            )
            current = visible(
                reader.get(
                    memory_id,
                    access=MemoryReadAccess.METADATA_ONLY,
                )
            )
            if current.sensitivity != "private":
                raise ProtectedMemoryApiRequestError(
                    "only private protected memories can be corrected"
                )
            record = writer.correct(
                memory_id,
                access=MemoryWriteAccess.LOCAL_MANAGEMENT,
                expected_updated_at=req.expected_updated_at,
                value=req.value,
                source_ref=_request_provenance(authorized),
                sensitivity="private",
                confidence=req.confidence,
                expires_at=req.expires_at,
            )
            return {"memory": _metadata_payload(record)}
        except MemoryStoreError as exc:
            _raise(exc)

    @router.delete("/{memory_id}")
    def delete_memory(
        memory_id: str,
        request: Request,
    ) -> dict[str, Any]:
        try:
            grant(request, ProtectedMemoryApiAction.WRITE_PRIVATE)
            expected_updated_at = _required_finite_float_query(
                request,
                "expected_updated_at",
                minimum=0.0,
            )
            current = visible(
                reader.get(
                    memory_id,
                    access=MemoryReadAccess.METADATA_ONLY,
                    include_deleted=True,
                )
            )
            if current.sensitivity != "private":
                raise ProtectedMemoryApiRequestError(
                    "only private protected memories can be deleted"
                )
            record = writer.delete(
                memory_id,
                access=MemoryWriteAccess.LOCAL_MANAGEMENT,
                expected_updated_at=expected_updated_at,
            )
            return {"memory": _metadata_payload(record)}
        except MemoryStoreError as exc:
            _raise(exc)

    return router
