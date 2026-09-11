from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request

from .extraction import CompletedMemoryTurn, MemoryCandidate
from .write_api import LoopbackPolicy, build_memory4_write_router
from .write_service import DurableCandidateWrite, MemoryCompletedTurnWriteService


MEMORY4_WRITE_FLAG = "KALIV_MEMORY4_WRITE_ENABLED"
_MEMORY4_DB_DEFAULT = "./kaliv-agent3-memory.db"
_MEMORY4_DB_ENV = "KALIV_AGENT3_MEMORY_DB"
_MOUNTED_STATE = "memory4_write_mounted"
_SUBSTRATE_STATE = "memory4_write_substrate_writer"
_SERVICE_STATE = "memory4_write_service"

ExtractCandidates = Callable[
    [CompletedMemoryTurn],
    Awaitable[tuple[MemoryCandidate, ...]],
]


def memory4_write_enabled() -> bool:
    return os.getenv(MEMORY4_WRITE_FLAG, "").strip() == "1"


def close_memory4_write(app: FastAPI) -> None:
    """Close process-owned W04 writer state; safe to call repeatedly."""
    substrate = getattr(app.state, _SUBSTRATE_STATE, None)
    if substrate is not None:
        close = getattr(substrate, "close", None)
        if callable(close):
            close()
    setattr(app.state, _SUBSTRATE_STATE, None)
    setattr(app.state, _SERVICE_STATE, None)
    setattr(app.state, _MOUNTED_STATE, False)


def mount_memory4_write(
    app: FastAPI,
    *,
    protected_provider_factory: Callable[[], Any] | None = None,
    loopback_allowed: LoopbackPolicy | None = None,
    extract_candidates: ExtractCandidates | None = None,
) -> bool:
    """Mount W04-A only after its independent explicit opt-in.

    The write surface is independent from Memory 4 read/chat flags and from Agent
    3 activation. Flag-off startup returns before importing/opening any durable
    writer or protection provider. Indexed-protected storage is intentionally not
    exposed by W04-A; the surface therefore cannot create, migrate or repair the
    #1218 blind-index sidecar.
    """
    if not memory4_write_enabled():
        return False
    if getattr(app.state, _MOUNTED_STATE, False):
        return True

    # Storage and the local extractor are imported only after exact opt-in.
    from .. import paths as _paths
    from ..agent3.memory import MemoryStore
    from ..agent3.memory_protected_gateway import memory_store_mode
    from ..agent3.memory_protected_writer import MemoryWriteAccess, ProtectedMemoryWriter
    from ..agent3.memory_protection import (
        MemoryProtectionCodec,
        WindowsDpapiMemoryProtectionProvider,
    )
    from ..agent3.memory_turn_commit import (
        commit_legacy_candidates,
        commit_protected_candidates,
    )

    if extract_candidates is None:
        from . import extract_memory_candidates_local

        extract = extract_memory_candidates_local
    else:
        if not callable(extract_candidates):
            raise RuntimeError("Memory 4 completed-turn extractor must be callable")
        extract = extract_candidates

    memory_path = Path(_paths.resolve(_MEMORY4_DB_DEFAULT, env=_MEMORY4_DB_ENV))
    mode = memory_store_mode()
    substrate: Any = None
    route_count = len(app.router.routes)
    try:
        if mode == "legacy":
            substrate = MemoryStore(str(memory_path))

            def commit(candidates: tuple[MemoryCandidate, ...]) -> DurableCandidateWrite:
                return commit_legacy_candidates(substrate, candidates)

        elif mode == "protected":
            factory = protected_provider_factory or WindowsDpapiMemoryProtectionProvider
            if not callable(factory):
                raise RuntimeError("protected memory provider factory must be callable")
            substrate = ProtectedMemoryWriter(
                memory_path,
                MemoryProtectionCodec(factory()),
            )

            def commit(candidates: tuple[MemoryCandidate, ...]) -> DurableCandidateWrite:
                return commit_protected_candidates(
                    substrate,
                    candidates,
                    access=MemoryWriteAccess.LOCAL_MANAGEMENT,
                )

        else:  # memory_store_mode itself is fail-closed; keep a defensive guard.
            raise RuntimeError("unsupported Memory 4 storage mode")

        service = MemoryCompletedTurnWriteService(extract=extract, commit=commit)
        router_kwargs: dict[str, Any] = {}
        if loopback_allowed is not None:
            if not callable(loopback_allowed):
                raise RuntimeError("Memory 4 loopback policy must be callable")
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
