from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from functools import wraps
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from .extraction import CompletedMemoryTurn, MemoryCandidate
from .write_api import LoopbackPolicy, build_memory4_write_router
from .write_service import MemoryCompletedTurnWriteService


MEMORY4_WRITE_FLAG = "KALIV_MEMORY4_WRITE_ENABLED"
MEMORY4_WRITE_INDEXED_PROTECTED_FLAG = "KALIV_MEMORY4_WRITE_INDEXED_PROTECTED"
_MEMORY4_DB_DEFAULT = "./kaliv-agent3-memory.db"
_MEMORY4_DB_ENV = "KALIV_AGENT3_MEMORY_DB"
_MOUNTED_STATE = "memory4_write_mounted"
_SUBSTRATE_STATE = "memory4_write_substrate"
_SERVICE_STATE = "memory4_write_service"

ExtractCandidates = Callable[[CompletedMemoryTurn], Any]


def memory4_write_enabled() -> bool:
    return os.getenv(MEMORY4_WRITE_FLAG, "").strip() == "1"


def memory4_write_indexed_protected_enabled() -> bool:
    return os.getenv(MEMORY4_WRITE_INDEXED_PROTECTED_FLAG, "").strip() == "1"


def close_memory4_write(app: FastAPI) -> None:
    substrate = getattr(app.state, _SUBSTRATE_STATE, None)
    if substrate is not None:
        close = getattr(substrate, "close", None)
        if callable(close):
            close()
    setattr(app.state, _SUBSTRATE_STATE, None)
    setattr(app.state, _SERVICE_STATE, None)
    setattr(app.state, _MOUNTED_STATE, False)


def compose_memory4_write_lifespan(inner_lifespan):
    if not callable(inner_lifespan):
        raise TypeError("inner lifespan must be callable")
    authority_owner = getattr(inner_lifespan, "__wrapped__", inner_lifespan)

    @wraps(inner_lifespan)
    @asynccontextmanager
    async def composed(app: FastAPI):
        try:
            async with inner_lifespan(app):
                yield
        finally:
            close_memory4_write(app)

    composed.__wrapped__ = authority_owner
    return composed


def mount_memory4_write(
    app: FastAPI,
    *,
    extract_candidates: ExtractCandidates | None = None,
    protected_provider_factory: Callable[[], Any] | None = None,
    loopback_allowed: LoopbackPolicy | None = None,
) -> bool:
    if not memory4_write_enabled():
        return False
    if getattr(app.state, _MOUNTED_STATE, False):
        return True

    from .. import paths as _paths
    from ..agent3.memory import MemoryStore
    from ..agent3.memory_protected_gateway import memory_store_mode
    from ..agent3.memory_protected_writer import MemoryWriteAccess, ProtectedMemoryWriter
    from ..agent3.memory_protection import (
        MemoryProtectionCodec,
        WindowsDpapiMemoryProtectionProvider,
    )
    from ..agent3.memory_turn_commit import (
        commit_indexed_protected_candidates,
        commit_legacy_candidates,
        commit_protected_candidates,
    )

    memory_path = Path(_paths.peek_resolve(_MEMORY4_DB_DEFAULT, env=_MEMORY4_DB_ENV))
    mode = memory_store_mode()
    indexed_protected = memory4_write_indexed_protected_enabled()
    substrate: Any = None
    route_count = len(app.router.routes)
    try:
        extractor = extract_candidates
        if extractor is None:
            from . import extract_memory_candidates_local

            extractor = extract_memory_candidates_local
        if not callable(extractor):
            raise RuntimeError("Memory 4 completed-turn extractor must be callable")

        if mode == "legacy":
            if indexed_protected:
                raise RuntimeError(
                    "indexed protected W04-A mode requires protected memory storage"
                )
            substrate = MemoryStore(str(memory_path))

            def commit(candidates: tuple[MemoryCandidate, ...]):
                return commit_legacy_candidates(substrate, candidates)

        elif mode == "protected":
            factory = protected_provider_factory or WindowsDpapiMemoryProtectionProvider
            if not callable(factory):
                raise RuntimeError("protected memory provider factory must be callable")
            substrate = ProtectedMemoryWriter(
                memory_path,
                MemoryProtectionCodec(factory()),
            )
            if indexed_protected:

                def commit(candidates: tuple[MemoryCandidate, ...]):
                    return commit_indexed_protected_candidates(
                        substrate,
                        candidates,
                        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
                    )

            else:

                def commit(candidates: tuple[MemoryCandidate, ...]):
                    return commit_protected_candidates(
                        substrate,
                        candidates,
                        access=MemoryWriteAccess.LOCAL_MANAGEMENT,
                    )

        else:
            raise RuntimeError("unsupported Memory 4 storage mode")

        service = MemoryCompletedTurnWriteService(extract=extractor, commit=commit)
        router_kwargs = {}
        if loopback_allowed is not None:
            if not callable(loopback_allowed):
                raise RuntimeError("Memory 4 write loopback policy must be callable")
            router_kwargs["loopback_allowed"] = loopback_allowed
        app.include_router(build_memory4_write_router(service, **router_kwargs))

        setattr(app.state, _SUBSTRATE_STATE, substrate)
        setattr(app.state, _SERVICE_STATE, service)
        setattr(app.state, _MOUNTED_STATE, True)
        return True
    except Exception:
        if len(app.router.routes) > route_count:
            del app.router.routes[route_count:]
            app.openapi_schema = None
        if substrate is not None:
            close = getattr(substrate, "close", None)
            if callable(close):
                close()
        setattr(app.state, _SUBSTRATE_STATE, None)
        setattr(app.state, _SERVICE_STATE, None)
        setattr(app.state, _MOUNTED_STATE, False)
        raise
