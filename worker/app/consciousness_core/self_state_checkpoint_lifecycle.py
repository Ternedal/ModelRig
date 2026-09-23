"""C27-D default-off graceful-shutdown SelfState checkpoint.

The lifecycle seam adds no cadence. It invokes the explicit C27-C checkpoint
coordinator once during graceful shutdown, after outer autonomous-cognition
submission has stopped and before the inner C19 session closes.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from functools import wraps
from typing import Callable

from .self_state import SelfStateStore
from .self_state_checkpoint_runtime import (
    ExplicitSelfStateCheckpointCoordinator,
    RuntimeSelfStateCheckpointResult,
)
from .session_lifecycle import ProductionCognitiveSession


SELF_STATE_CHECKPOINT_FLAG = (
    "KALIV_CONSCIOUSNESS_SELF_STATE_CHECKPOINT_ENABLED"
)


class ShutdownSelfStateCheckpointError(RuntimeError):
    pass


def shutdown_self_state_checkpoint_enabled() -> bool:
    """Only exact string 1 grants graceful-shutdown persistence."""
    return (
        os.getenv(
            "KALIV_CONSCIOUSNESS_SELF_STATE_CHECKPOINT_ENABLED",
            "0",
        )
        == "1"
    )


def production_shutdown_checkpoint_factory(
    app,
    *,
    enabled_fn: Callable[[], bool] = shutdown_self_state_checkpoint_enabled,
    store_factory: Callable[[], SelfStateStore] = SelfStateStore,
    coordinator_factory=ExplicitSelfStateCheckpointCoordinator,
) -> ExplicitSelfStateCheckpointCoordinator | None:
    """Construct no persistence object unless the exact gate and C19 are live."""
    try:
        enabled = bool(enabled_fn())
    except Exception as exc:
        raise ShutdownSelfStateCheckpointError(
            "SelfState checkpoint feature flag check failed"
        ) from exc
    if not enabled:
        return None

    session = getattr(app.state, "consciousness_session", None)
    if session is None:
        return None
    if not isinstance(session, ProductionCognitiveSession):
        raise ShutdownSelfStateCheckpointError(
            "consciousness_session app state has unexpected type"
        )
    if session.closed:
        raise ShutdownSelfStateCheckpointError(
            "cannot configure checkpoint for closed cognitive session"
        )

    try:
        store = store_factory()
    except Exception as exc:
        raise ShutdownSelfStateCheckpointError(
            "could not construct SelfStateStore"
        ) from exc
    if not isinstance(store, SelfStateStore):
        raise TypeError("store_factory must return SelfStateStore")

    try:
        coordinator = coordinator_factory(
            session=session,
            store=store,
        )
    except Exception as exc:
        raise ShutdownSelfStateCheckpointError(
            "could not construct SelfState checkpoint coordinator"
        ) from exc
    if not isinstance(
        coordinator,
        ExplicitSelfStateCheckpointCoordinator,
    ):
        raise TypeError(
            "coordinator_factory must return "
            "ExplicitSelfStateCheckpointCoordinator"
        )
    return coordinator


def compose_shutdown_self_state_checkpoint_lifespan(
    inner_lifespan,
    coordinator_factory=production_shutdown_checkpoint_factory,
):
    """Checkpoint exactly once after serving, before inner C19 teardown."""
    if not callable(inner_lifespan):
        raise TypeError("inner lifespan must be callable")
    if not callable(coordinator_factory):
        raise TypeError("coordinator_factory must be callable")

    authority_owner = getattr(inner_lifespan, "__wrapped__", inner_lifespan)

    @wraps(inner_lifespan)
    @asynccontextmanager
    async def composed(app):
        async with inner_lifespan(app):
            coordinator = coordinator_factory(app)
            if coordinator is not None and not isinstance(
                coordinator,
                ExplicitSelfStateCheckpointCoordinator,
            ):
                raise TypeError(
                    "coordinator_factory must return "
                    "ExplicitSelfStateCheckpointCoordinator or None"
                )
            try:
                yield
            finally:
                if coordinator is not None:
                    try:
                        result = coordinator.checkpoint_once()
                    except Exception as exc:
                        raise ShutdownSelfStateCheckpointError(
                            "graceful-shutdown SelfState checkpoint failed"
                        ) from exc
                    if not isinstance(
                        result,
                        RuntimeSelfStateCheckpointResult,
                    ):
                        raise ShutdownSelfStateCheckpointError(
                            "checkpoint coordinator returned invalid result"
                        )

    composed.__wrapped__ = authority_owner
    return composed
