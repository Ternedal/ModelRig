from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .memory import MemoryStore
from .memory_api import build_memory_router
from .memory_protected_api import build_protected_memory_router
from .memory_protected_gateway import (
    GatewayProtectedMemoryAuthorizer,
    MEMORY_REQUEST_BODY_MAX_BYTES,
    MEMORY_STORE_ATTESTATION_HEADER,
    MEMORY_STORE_ATTESTATION_VALUE,
    ProtectedMemoryGrantReplayLedger,
    memory_store_mode,
    protected_memory_grant_db,
    protected_memory_secret,
)
from .memory_protected_reader import ProtectedMemoryReader
from .memory_protected_writer import ProtectedMemoryWriter
from .memory_protection import (
    MemoryProtectionCodec,
    MemoryProtectionProvider,
    WindowsDpapiMemoryProtectionProvider,
)


PROTECTED_MEMORY_MOUNT_CONTRACT = "kaliv-agent3-protected-memory-mount/v1"
AUTOMATIC_MIGRATION = False
PROTECTED_TO_LEGACY_FALLBACK = False
_PROTECTED_MEMORY_PREFIX = "/experimental/agent3/memory"
ProviderFactory = Callable[[], MemoryProtectionProvider]


@dataclass(frozen=True)
class Agent3MemorySurface:
    mode: str
    legacy_store: MemoryStore | None
    protected_reader: ProtectedMemoryReader | None
    protected_writer: ProtectedMemoryWriter | None
    planner_memory_store: MemoryStore | None
    grant_db_path: Path | None


def _is_protected_memory_path(path: str) -> bool:
    return path == _PROTECTED_MEMORY_PREFIX or path.startswith(
        _PROTECTED_MEMORY_PREFIX + "/"
    )


def _install_protected_request_boundary(app: FastAPI) -> None:
    if getattr(app.state, "agent3_protected_memory_boundary_installed", False):
        return

    @app.middleware("http")
    async def protected_memory_request_boundary(request: Request, call_next):
        if not _is_protected_memory_path(request.url.path):
            return await call_next(request)
        try:
            body = await request.body()
        except Exception:
            response = JSONResponse(
                status_code=400,
                content={"detail": "protected memory request body could not be read"},
            )
            response.headers[
                MEMORY_STORE_ATTESTATION_HEADER
            ] = MEMORY_STORE_ATTESTATION_VALUE
            return response
        if len(body) > MEMORY_REQUEST_BODY_MAX_BYTES:
            response = JSONResponse(
                status_code=413,
                content={"detail": "protected memory request body is too large"},
            )
            response.headers[
                MEMORY_STORE_ATTESTATION_HEADER
            ] = MEMORY_STORE_ATTESTATION_VALUE
            return response
        request.state.agent3_memory_body_sha256 = hashlib.sha256(body).hexdigest()
        response = await call_next(request)
        response.headers[MEMORY_STORE_ATTESTATION_HEADER] = (
            MEMORY_STORE_ATTESTATION_VALUE
        )
        return response

    app.state.agent3_protected_memory_boundary_installed = True


def mount_memory_surface(
    app: FastAPI,
    *,
    memory_path: str | Path,
    grant_db_path: str | Path,
    protected_provider_factory: ProviderFactory = WindowsDpapiMemoryProtectionProvider,
) -> Agent3MemorySurface:
    """Mount exactly one memory surface with no migration or fallback.

    Empty/``legacy`` preserves the historical plaintext routes and planner
    source. Exact ``protected`` validates the shared grant material, completed
    migration, provider/key scope and separate durable replay ledger before the
    protected router becomes visible. A protected failure is propagated; this
    function never catches it to instantiate ``MemoryStore``.
    """

    mode = memory_store_mode()
    memory = Path(memory_path)

    if mode == "legacy":
        store = MemoryStore(str(memory))
        app.include_router(build_memory_router(store))
        return Agent3MemorySurface(
            mode="legacy",
            legacy_store=store,
            protected_reader=None,
            protected_writer=None,
            planner_memory_store=store,
            grant_db_path=None,
        )

    # Validate configuration before touching the protection provider. The
    # signing material is shared with the authenticated Go gateway, while the
    # replay ledger must be a separate path from the protected memory store.
    signing_material = protected_memory_secret()
    replay_path = protected_memory_grant_db(grant_db_path)
    if replay_path.resolve(strict=False) == memory.resolve(strict=False):
        raise RuntimeError(
            "protected memory grant ledger must be separate from the memory database"
        )
    if not callable(protected_provider_factory):
        raise RuntimeError("protected memory provider factory must be callable")

    provider = protected_provider_factory()
    codec = MemoryProtectionCodec(provider)
    reader: ProtectedMemoryReader | None = None
    writer: ProtectedMemoryWriter | None = None
    try:
        # Reader and writer independently require a completed migration and a
        # matching provider/key scope. No migrator is imported or invoked here.
        reader = ProtectedMemoryReader(memory, codec)
        writer = ProtectedMemoryWriter(memory, codec)
        authorizer = GatewayProtectedMemoryAuthorizer(
            signing_material,
            replay_ledger=ProtectedMemoryGrantReplayLedger(replay_path),
        )
        _install_protected_request_boundary(app)
        app.include_router(
            build_protected_memory_router(
                reader,
                writer,
                authorizer=authorizer,
            )
        )
    except Exception:
        if writer is not None:
            writer.close()
        if reader is not None:
            reader.close()
        raise

    return Agent3MemorySurface(
        mode="protected",
        legacy_store=None,
        protected_reader=reader,
        protected_writer=writer,
        # The legacy planner compiler expects plaintext MemoryStore rows. A
        # separate bounded local protected compiler is required before this can
        # become non-None.
        planner_memory_store=None,
        grant_db_path=replay_path,
    )
