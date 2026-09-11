from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from functools import wraps
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request

from .context_api import LoopbackPolicy, build_memory4_context_router
from .context_service import MemoryContextForTurnService
from .semantic import HybridMemoryRetriever, SemanticMemoryConfig
from .storage import SharedMemoryReader


MEMORY4_CONTEXT_FLAG = "KALIV_MEMORY4_CONTEXT_ENABLED"
MEMORY4_SEMANTIC_FLAG = "KALIV_MEMORY4_SEMANTIC_ENABLED"
_MEMORY4_DB_DEFAULT = "./kaliv-agent3-memory.db"
_MEMORY4_DB_ENV = "KALIV_AGENT3_MEMORY_DB"
_MOUNTED_STATE = "memory4_context_mounted"
_SUBSTRATE_STATE = "memory4_context_substrate_reader"
_SERVICE_STATE = "memory4_context_service"


def memory4_context_enabled() -> bool:
    return os.getenv(MEMORY4_CONTEXT_FLAG, "").strip() == "1"


def memory4_semantic_enabled() -> bool:
    return os.getenv(MEMORY4_SEMANTIC_FLAG, "").strip() == "1"


def close_memory4_context(app: FastAPI) -> None:
    """Close process-owned R04 substrate state; safe to call repeatedly."""
    reader = getattr(app.state, _SUBSTRATE_STATE, None)
    if reader is not None:
        close = getattr(reader, "close", None)
        if callable(close):
            close()
    setattr(app.state, _SUBSTRATE_STATE, None)
    setattr(app.state, _SERVICE_STATE, None)
    setattr(app.state, _MOUNTED_STATE, False)


def compose_memory4_context_lifespan(
    inner_lifespan,
    *,
    extra_cleanup: Callable[[FastAPI], None] | None = None,
):
    """Wrap the worker lifespan so Memory 4 resources close after inner shutdown.

    Entrypoint owns the final process lifespan. Registering a legacy FastAPI
    ``shutdown`` event during mount is insufficient because entrypoint later
    assigns the scheduler lifespan explicitly. Composition here makes cleanup
    part of that exact production lifecycle instead of relying on handler merge
    behaviour inside Starlette/FastAPI.

    W04 may supply one additional process-owned cleanup callback. Keeping that
    callback inside this existing wrapper avoids creating a competing lifespan
    layer. ``functools.wraps`` still exposes ``__wrapped__`` as the exact inner
    scheduler lifespan, preserving the existing lifecycle contract.
    """
    if not callable(inner_lifespan):
        raise TypeError("inner lifespan must be callable")
    if extra_cleanup is not None and not callable(extra_cleanup):
        raise TypeError("extra cleanup must be callable")

    @wraps(inner_lifespan)
    @asynccontextmanager
    async def composed(app: FastAPI):
        try:
            async with inner_lifespan(app):
                yield
        finally:
            # The W04 writer must still close if the R04 reader cleanup raises.
            try:
                close_memory4_context(app)
            finally:
                if extra_cleanup is not None:
                    extra_cleanup(app)

    return composed


def mount_memory4_context(
    app: FastAPI,
    *,
    protected_provider_factory: Callable[[], Any] | None = None,
    loopback_allowed: LoopbackPolicy | None = None,
) -> bool:
    """Mount the independent, read-only R04 surface after explicit opt-in.

    This composition deliberately does not call ``mount_agent3`` and does not
    inspect ``KALIV_AGENT3_ENABLED``. It reuses the same durable memory file and
    protection format, but owns a separate query-only reader and HTTP route.
    Normal chat remains untouched until R05.

    The caller that owns process lifecycle must also own cleanup. Production
    entrypoint does that by composing its scheduler lifespan with
    :func:`compose_memory4_context_lifespan`.
    """
    if not memory4_context_enabled():
        return False
    if getattr(app.state, _MOUNTED_STATE, False):
        return True

    # Everything storage-specific is imported only after explicit opt-in. A
    # normal worker boot therefore does not open the memory DB or protection
    # provider merely because this module is imported by the entrypoint.
    from .. import paths as _paths
    from ..agent3.memory_context import MemoryContextCompiler
    from ..agent3.memory_legacy_reader import LegacyMemoryReader
    from ..agent3.memory_protected_gateway import memory_store_mode
    from ..agent3.memory_protected_reader import MemoryReadAccess, ProtectedMemoryReader
    from ..agent3.memory_protection import (
        MemoryProtectionCodec,
        WindowsDpapiMemoryProtectionProvider,
    )

    memory_path = Path(
        _paths.peek_resolve(_MEMORY4_DB_DEFAULT, env=_MEMORY4_DB_ENV)
    )
    mode = memory_store_mode()
    substrate: Any = None
    route_count = len(app.router.routes)
    try:
        if mode == "legacy":
            substrate = LegacyMemoryReader(memory_path)
            read_context = substrate.context_records
        elif mode == "protected":
            factory = protected_provider_factory or WindowsDpapiMemoryProtectionProvider
            if not callable(factory):
                raise RuntimeError("protected memory provider factory must be callable")
            substrate = ProtectedMemoryReader(
                memory_path,
                MemoryProtectionCodec(factory()),
            )

            def read_context(**kwargs):
                return substrate.context_records(
                    access=MemoryReadAccess.LOCAL_CONTEXT,
                    **kwargs,
                )

        else:  # memory_store_mode is fail-closed, keep this defensive boundary.
            raise RuntimeError("unsupported Memory 4 storage mode")

        shared_reader = SharedMemoryReader(mode=mode, read_context=read_context)
        semantic = memory4_semantic_enabled()
        embed = None
        if semantic:
            from . import embed_memory_text_local

            embed = embed_memory_text_local
        retriever = HybridMemoryRetriever(
            embed=embed,
            config=SemanticMemoryConfig(enabled=semantic),
        )
        service = MemoryContextForTurnService(
            reader=shared_reader,
            retriever=retriever,
            compiler=MemoryContextCompiler(),
        )
        router_kwargs = {}
        if loopback_allowed is not None:
            if not callable(loopback_allowed):
                raise RuntimeError("Memory 4 loopback policy must be callable")
            router_kwargs["loopback_allowed"] = loopback_allowed
        app.include_router(build_memory4_context_router(service, **router_kwargs))

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
