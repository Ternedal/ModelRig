from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .memory import MemoryConflict, MemoryNotFound, MemoryRecord, MemoryStoreError
from .memory_protected_reader import (
    MemoryReadAccess,
    ProtectedMemoryReader,
)
from .memory_protected_writer import (
    MemoryWriteAccess,
    ProtectedMemoryWriter,
)


class ProtectedMemoryApiAuthorizationError(MemoryStoreError):
    """A request did not carry an exact, fresh authorization grant."""


class ProtectedMemoryApiAction(str, Enum):
    STATUS = "status"
    READ_METADATA = "read_metadata"
    WRITE_PRIVATE = "write_private"


@dataclass(frozen=True)
class ProtectedMemoryApiGrant:
    """Request-bound proof produced by the authenticated gateway boundary.

    This is deliberately not a boolean. A caller must bind the principal, exact
    action and request id to a short validity window. The router validates the
    returned grant again and never accepts a string in place of an enum.
    """

    principal: str
    action: ProtectedMemoryApiAction
    request_id: str
    issued_at: float
    expires_at: float


ProtectedMemoryApiAuthorizer = Callable[
    [Request, ProtectedMemoryApiAction], ProtectedMemoryApiGrant
]
Clock = Callable[[], float]


class CreateProtectedMemoryReq(BaseModel):
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


class CorrectProtectedMemoryReq(BaseModel):
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
    if isinstance(grant.issued_at, bool) or isinstance(grant.expires_at, bool):
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant timestamps are invalid"
        )
    try:
        issued_at = float(grant.issued_at)
        expires_at = float(grant.expires_at)
        now = float(clock())
    except (TypeError, ValueError, OverflowError) as exc:
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant timestamps are invalid"
        ) from exc
    if not all(value == value and abs(value) != float("inf") for value in (
        issued_at,
        expires_at,
        now,
    )):
        raise ProtectedMemoryApiAuthorizationError(
            "protected memory grant timestamps are invalid"
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


def _metadata_payload(record: MemoryRecord) -> dict[str, Any]:
    payload = record.to_dict(include_value=False)
    # Be explicit even if MemoryRecord changes: a remote response from this
    # boundary must never carry value or provenance plaintext.
    payload["value"] = "[redacted]" if record.lifecycle_status != "deleted" else ""
    payload["source_ref"] = None
    return payload


def _raise(exc: Exception) -> None:
    if isinstance(exc, ProtectedMemoryApiAuthorizationError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, MemoryNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, MemoryConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, MemoryStoreError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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

    def grant(request: Request, action: ProtectedMemoryApiAction) -> None:
        _authorize(request, action, authorizer, clock)

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
    def list_memories(
        request: Request,
        subject: str | None = None,
        predicate: str | None = None,
        review_status: str | None = None,
        lifecycle_status: str | None = "active",
        include_expired: bool = False,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        try:
            grant(request, ProtectedMemoryApiAction.READ_METADATA)
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
    def create_memory(
        req: CreateProtectedMemoryReq,
        request: Request,
    ) -> dict[str, Any]:
        try:
            grant(request, ProtectedMemoryApiAction.WRITE_PRIVATE)
            request_id = _request_id(request)
            record = writer.create(
                access=MemoryWriteAccess.LOCAL_MANAGEMENT,
                subject=req.subject,
                predicate=req.predicate,
                value=req.value,
                kind=req.kind,
                sensitivity="private",
                source_type="user_explicit",
                source_ref=f"memory-api:{request_id}",
                confidence=req.confidence,
                review_status="confirmed",
                expires_at=req.expires_at,
            )
            return {"memory": _metadata_payload(record)}
        except MemoryStoreError as exc:
            _raise(exc)

    # Static route must be registered before /{memory_id}.
    @router.get("/search")
    def search_memories(
        request: Request,
        q: str = Query(min_length=1, max_length=300),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        try:
            grant(request, ProtectedMemoryApiAction.READ_METADATA)
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
    def correct_memory(
        memory_id: str,
        req: CorrectProtectedMemoryReq,
        request: Request,
    ) -> dict[str, Any]:
        try:
            grant(request, ProtectedMemoryApiAction.WRITE_PRIVATE)
            current = visible(
                reader.get(
                    memory_id,
                    access=MemoryReadAccess.METADATA_ONLY,
                )
            )
            if current.sensitivity != "private":
                raise MemoryStoreError(
                    "only private protected memories can be corrected through this API"
                )
            record = writer.correct(
                memory_id,
                access=MemoryWriteAccess.LOCAL_MANAGEMENT,
                expected_updated_at=req.expected_updated_at,
                value=req.value,
                source_ref=f"memory-api:{_request_id(request)}",
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
        expected_updated_at: float = Query(ge=0.0),
    ) -> dict[str, Any]:
        try:
            grant(request, ProtectedMemoryApiAction.WRITE_PRIVATE)
            current = visible(
                reader.get(
                    memory_id,
                    access=MemoryReadAccess.METADATA_ONLY,
                    include_deleted=True,
                )
            )
            if current.sensitivity != "private":
                raise MemoryStoreError(
                    "only private protected memories can be deleted through this API"
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
