from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .memory import MemoryConflict, MemoryNotFound, MemoryRecord, MemoryStore, MemoryStoreError


class CreateMemoryReq(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    predicate: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=20_000)
    kind: str = Field(default="fact", pattern="^(fact|preference|project|relationship|routine|constraint|note)$")
    # Secret memory is storage-supported but not remotely writable until
    # encryption-at-rest and a dedicated secret reveal flow exist.
    sensitivity: str = Field(default="private", pattern="^(public|operational|private)$")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    expires_at: float | None = None


class CorrectMemoryReq(BaseModel):
    value: str = Field(min_length=1, max_length=20_000)
    sensitivity: str | None = Field(default=None, pattern="^(public|operational|private)$")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    expires_at: float | None = None


def _source_ref(request: Request) -> str:
    request_id = request.headers.get("X-Request-ID", "unknown")[:200]
    return f"memory-api:{request_id}"


def _payload(record: MemoryRecord) -> dict[str, Any]:
    # Existing local secret rows may predate the API. Never reveal their value or
    # source provenance through this remote surface.
    return record.to_dict(include_value=record.sensitivity != "secret")


def _raise(exc: Exception) -> None:
    if isinstance(exc, MemoryNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, MemoryConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, MemoryStoreError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


def build_memory_router(store: MemoryStore) -> APIRouter:
    router = APIRouter(prefix="/experimental/agent3/memory", tags=["experimental-agent3-memory"])

    @router.get("")
    def list_memories(
        subject: str | None = None,
        predicate: str | None = None,
        review_status: str | None = None,
        lifecycle_status: str | None = "active",
        include_expired: bool = False,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        try:
            records = store.list(
                subject=subject,
                predicate=predicate,
                review_status=review_status,
                lifecycle_status=lifecycle_status,
                include_expired=include_expired,
                include_secret=False,
                limit=limit,
            )
        except MemoryStoreError as exc:
            _raise(exc)
        return {"memories": [_payload(record) for record in records]}

    @router.post("")
    def create_memory(req: CreateMemoryReq, request: Request) -> dict[str, Any]:
        try:
            record = store.create(
                subject=req.subject,
                predicate=req.predicate,
                value=req.value,
                kind=req.kind,
                sensitivity=req.sensitivity,
                source_type="user_explicit",
                source_ref=_source_ref(request),
                confidence=req.confidence,
                review_status="confirmed",
                expires_at=req.expires_at,
            )
        except MemoryStoreError as exc:
            _raise(exc)
        return {"memory": _payload(record)}

    # Static routes must be registered before /{memory_id}.
    @router.get("/search")
    def search_memories(
        q: str = Query(min_length=1, max_length=300),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        try:
            records = store.search(q, confirmed_only=True, include_secret=False, limit=limit)
        except MemoryStoreError as exc:
            _raise(exc)
        return {"memories": [_payload(record) for record in records]}

    @router.get("/{memory_id}")
    def get_memory(memory_id: str) -> dict[str, Any]:
        try:
            record = store.get(memory_id, include_deleted=True)
        except MemoryStoreError as exc:
            _raise(exc)
        return {"memory": _payload(record)}

    @router.get("/{memory_id}/history")
    def memory_history(memory_id: str) -> dict[str, Any]:
        try:
            current = store.get(memory_id, include_deleted=True)
            records = store.history(current.subject, current.predicate)
        except MemoryStoreError as exc:
            _raise(exc)
        return {"memories": [_payload(record) for record in records]}

    @router.post("/{memory_id}/confirm")
    def confirm_memory(memory_id: str) -> dict[str, Any]:
        try:
            record = store.confirm(memory_id)
        except MemoryStoreError as exc:
            _raise(exc)
        return {"memory": _payload(record)}

    @router.post("/{memory_id}/reject")
    def reject_memory(memory_id: str) -> dict[str, Any]:
        try:
            record = store.reject(memory_id)
        except MemoryStoreError as exc:
            _raise(exc)
        return {"memory": _payload(record)}

    @router.post("/{memory_id}/correct")
    def correct_memory(memory_id: str, req: CorrectMemoryReq, request: Request) -> dict[str, Any]:
        try:
            current = store.get(memory_id)
            if current.sensitivity == "secret":
                raise MemoryStoreError("secret memories cannot be corrected through the remote API")
            record = store.correct(
                memory_id,
                value=req.value,
                sensitivity=req.sensitivity,
                confidence=req.confidence,
                source_ref=_source_ref(request),
                expires_at=req.expires_at,
            )
        except MemoryStoreError as exc:
            _raise(exc)
        return {"memory": _payload(record)}

    @router.delete("/{memory_id}")
    def delete_memory(memory_id: str) -> dict[str, Any]:
        try:
            record = store.delete(memory_id)
        except MemoryStoreError as exc:
            _raise(exc)
        return {"memory": _payload(record)}

    return router
