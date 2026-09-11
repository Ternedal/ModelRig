from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request

from .candidate_api import LoopbackPolicy, build_memory4_candidate_router
from .candidates import MemoryCandidateExtractor, extract_memory_candidates_local


MEMORY4_CANDIDATES_FLAG = "KALIV_MEMORY4_CANDIDATES_ENABLED"
_MOUNTED_STATE = "memory4_candidates_mounted"
_EXTRACTOR_STATE = "memory4_candidate_extractor"


def memory4_candidates_enabled() -> bool:
    return os.getenv(MEMORY4_CANDIDATES_FLAG, "").strip() == "1"


def mount_memory4_candidates(
    app: FastAPI,
    *,
    extract_fn: Callable[[str], Awaitable[str]] | None = None,
    loopback_allowed: LoopbackPolicy | None = None,
) -> bool:
    """Mount W01 only after explicit opt-in.

    W01 owns no database and no durable-memory writer. Its production extractor
    lazily enters the existing local Ollama client only when the loopback route
    is called. Flag-off startup therefore opens no DB/model/network resource and
    registers no route.
    """
    if not memory4_candidates_enabled():
        return False
    if getattr(app.state, _MOUNTED_STATE, False):
        return True

    route_count = len(app.router.routes)
    try:
        extractor = MemoryCandidateExtractor(extract_fn or extract_memory_candidates_local)
        router_kwargs: dict[str, Any] = {}
        if loopback_allowed is not None:
            if not callable(loopback_allowed):
                raise RuntimeError("Memory 4 candidate loopback policy must be callable")
            router_kwargs["loopback_allowed"] = loopback_allowed
        app.include_router(build_memory4_candidate_router(extractor, **router_kwargs))
        setattr(app.state, _EXTRACTOR_STATE, extractor)
        setattr(app.state, _MOUNTED_STATE, True)
        return True
    except Exception:
        if len(app.router.routes) > route_count:
            del app.router.routes[route_count:]
            app.openapi_schema = None
        setattr(app.state, _EXTRACTOR_STATE, None)
        setattr(app.state, _MOUNTED_STATE, False)
        raise
