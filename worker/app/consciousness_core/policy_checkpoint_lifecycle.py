"""C27-G production policy-checkpoint service with C29-C liveness coupling.

The process-local service remains default-off. C29-C adds a second exact opt-in
that wraps C27-F so an actual COMMITTED checkpoint records one C29-B witness.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from functools import wraps
from typing import Callable

from .. import paths as _paths
from .liveness import RuntimeLivenessStore
from .policy_checkpoint import PolicyDrivenSelfStateCheckpointAdapter
from .policy_checkpoint_liveness import (
    LivenessCoupledPolicyCheckpointAdapter,
)
from .self_state import SelfStateStore
from .session_lifecycle import ProductionCognitiveSession


POLICY_CHECKPOINT_SERVICE_FLAG = (
    "KALIV_CONSCIOUSNESS_POLICY_CHECKPOINT_ENABLED"
)
CHECKPOINT_LIVENESS_FLAG = (
    "KALIV_CONSCIOUSNESS_CHECKPOINT_LIVENESS_ENABLED"
)
CHECKPOINT_LIVENESS_STATE_ENV = (
    "KALIV_CONSCIOUSNESS_LIVENESS_STATE"
)
_CHECKPOINT_LIVENESS_STATE_DEFAULT = (
    "./kaliv-consciousness-liveness.json"
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


def checkpoint_liveness_enabled() -> bool:
    """Only exact string 1 couples successful C27-F commits to C29-B."""
    return (
        os.getenv(
            "KALIV_CONSCIOUSNESS_CHECKPOINT_LIVENESS_ENABLED",
            "0",
        )
        == "1"
    )


def production_runtime_liveness_store_factory() -> RuntimeLivenessStore:
    """Resolve the bounded C29-A store path without reading or writing it."""
    resolved = _paths.resolve(
        _CHECKPOINT_LIVENESS_STATE_DEFAULT,
        env=CHECKPOINT_LIVENESS_STATE_ENV,
    )
    return RuntimeLivenessStore(resolved)


def production_policy_checkpoint_service_factory(
    app,
    *,
    enabled_fn: Callable[[], bool] = policy_checkpoint_service_enabled,
    store_factory: Callable[[], SelfStateStore] = SelfStateStore,
    adapter_factory=PolicyDrivenSelfStateCheckpointAdapter,
    liveness_enabled_fn: Callable[[], bool] = checkpoint_liveness_enabled,
    liveness_store_factory: Callable[
        [], RuntimeLivenessStore
    ] = production_runtime_liveness_store_factory,
    liveness_adapter_factory=LivenessCoupledPolicyCheckpointAdapter,
) -> PolicyDrivenSelfStateCheckpointAdapter | None:
    """Construct the process-owned C27-F service only while C19 is live."""
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
        use_liveness = bool(liveness_enabled_fn())
    except Exception as exc:
        raise PolicyCheckpointServiceError(
            "checkpoint-liveness feature flag check failed"
        ) from exc

    if use_liveness:
        try:
            liveness_store = liveness_store_factory()
        except Exception as exc:
            raise PolicyCheckpointServiceError(
                "could not construct runtime liveness store"
            ) from exc
        if not isinstance(liveness_store, RuntimeLivenessStore):
            raise TypeError(
                "liveness_store_factory must return RuntimeLivenessStore"
            )
        try:
            adapter = liveness_adapter_factory(
                session=session,
                store=store,
                liveness_store=liveness_store,
            )
        except Exception as exc:
            raise PolicyCheckpointServiceError(
                "could not construct liveness-coupled checkpoint adapter"
            ) from exc
        if not isinstance(
            adapter,
            LivenessCoupledPolicyCheckpointAdapter,
        ):
            raise TypeError(
                "liveness_adapter_factory must return "
                "LivenessCoupledPolicyCheckpointAdapter"
            )
    else:
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
            "adapter factory must return "
            "PolicyDrivenSelfStateCheckpointAdapter"
        )
    return adapter


def compose_policy_checkpoint_service_lifespan(
    inner_lifespan,
    service_factory=production_policy_checkpoint_service_factory,
):
    """Expose C27-F/C29-C while C19 is live; invoke nothing automatically."""
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
