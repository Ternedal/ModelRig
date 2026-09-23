"""C27-G default-off production policy-checkpoint service.

This lifecycle seam owns one process-local C27-F adapter on app.state. It does
not invoke checkpointing automatically.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from functools import wraps
from typing import Callable

from .policy_checkpoint import PolicyDrivenSelfStateCheckpointAdapter
from .self_state import SelfStateStore
from .session_lifecycle import ProductionCognitiveSession


POLICY_CHECKPOINT_SERVICE_FLAG = (
    "KALIV_CONSCIOUSNESS_POLICY_CHECKPOINT_ENABLED"
)
_POLICY_CHECKPOINT_STATE = "consciousness_policy_checkpoint"


class PolicyCheckpointServiceError(RuntimeError):
    pass


def policy_checkpoint_service_enabled() -> bool:
    """Only exact string 1 enables the production C27-F service."""
    return (
        os.getenv(
            "KALIV_CONSCIOUSNESS_POLICY_CHECKPOINT_ENABLED",
            "0",
        )
        == "1"
    )


def production_policy_checkpoint_service_factory(
    app,
    *,
    enabled_fn: Callable[[], bool] = policy_checkpoint_service_enabled,
    store_factory: Callable[[], SelfStateStore] = SelfStateStore,
    adapter_factory=PolicyDrivenSelfStateCheckpointAdapter,
) -> PolicyDrivenSelfStateCheckpointAdapter | None:
    """Construct one process-owned adapter only when C19 is already live."""
    try:
        enabled = bool(enabled_fn())
    except Exception as exc:
        raise PolicyCheckpointServiceError(
            "policy-checkpoint feature flag check failed"
        ) from exc
    if not enabled:
        return None

    session = getattr(app.state, "consciousness_session", None)
    if session is None:
        return None
    if not isinstance(session, ProductionCognitiveSession):
        raise PolicyCheckpointServiceError(
            "consciousness_session app state has unexpected type"
        )
    if session.closed:
        raise PolicyCheckpointServiceError(
            "cannot configure policy checkpoint for closed session"
        )

    try:
        store = store_factory()
    except Exception as exc:
        raise PolicyCheckpointServiceError(
            "could not construct policy checkpoint SelfStateStore"
        ) from exc
    if not isinstance(store, SelfStateStore):
        raise TypeError("store_factory must return SelfStateStore")

    try:
        adapter = adapter_factory(
            session=session,
            store=store,
        )
    except Exception as exc:
        raise PolicyCheckpointServiceError(
            "could not construct policy checkpoint adapter"
        ) from exc
    if not isinstance(adapter, PolicyDrivenSelfStateCheckpointAdapter):
        raise TypeError(
            "adapter_factory must return PolicyDrivenSelfStateCheckpointAdapter"
        )
    return adapter


def compose_policy_checkpoint_service_lifespan(
    inner_lifespan,
    service_factory=production_policy_checkpoint_service_factory,
):
    """Expose C27-F while C19 is live; invoke nothing automatically."""
    if not callable(inner_lifespan):
        raise TypeError("inner lifespan must be callable")
    if not callable(service_factory):
        raise TypeError("service_factory must be callable")

    authority_owner = getattr(inner_lifespan, "__wrapped__", inner_lifespan)

    @wraps(inner_lifespan)
    @asynccontextmanager
    async def composed(app):
        async with inner_lifespan(app):
            service = service_factory(app)
            if service is not None and not isinstance(
                service,
                PolicyDrivenSelfStateCheckpointAdapter,
            ):
                raise TypeError(
                    "service_factory must return "
                    "PolicyDrivenSelfStateCheckpointAdapter or None"
                )
            if service is not None:
                setattr(app.state, _POLICY_CHECKPOINT_STATE, service)
            try:
                yield
            finally:
                if service is not None:
                    try:
                        delattr(app.state, _POLICY_CHECKPOINT_STATE)
                    except AttributeError:
                        pass

    composed.__wrapped__ = authority_owner
    return composed
