"""C30-P separately default-off episode review runtime lifecycle.

The lifecycle owns one process-local C30-J mailbox and one C30-N claim service.
It exposes them through app.state before C19 session construction, then clears
and closes them deterministically on shutdown.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import wraps

from .episode_review_claim import TrustedEpisodeReviewClaimService
from .episode_review_mailbox import EpisodeExperienceReviewMailbox
from .episode_review_observability import EpisodeReviewObservability


EPISODE_REVIEW_RUNTIME_FLAG = (
    "KALIV_CONSCIOUSNESS_EPISODE_REVIEW_RUNTIME_ENABLED"
)
DEFAULT_EPISODE_REVIEW_MAILBOX_CAPACITY = 8


class EpisodeReviewRuntimeError(RuntimeError):
    pass


@dataclass
class EpisodeReviewRuntime:
    mailbox: EpisodeExperienceReviewMailbox
    service: TrustedEpisodeReviewClaimService
    observability: EpisodeReviewObservability | None = None
    closed: bool = False

    def close(self) -> None:
        if self.closed:
            return
        self.service.close()
        self.mailbox.close()
        self.closed = True


def episode_review_runtime_enabled() -> bool:
    """Only exact string 1 enables the process-local C30-P runtime."""
    return os.getenv(EPISODE_REVIEW_RUNTIME_FLAG, "0") == "1"


def production_episode_review_runtime_factory(
    _app,
) -> EpisodeReviewRuntime | None:
    """Create no review state unless the independent runtime opt-in is exact."""
    if not episode_review_runtime_enabled():
        return None

    mailbox = EpisodeExperienceReviewMailbox(
        capacity=DEFAULT_EPISODE_REVIEW_MAILBOX_CAPACITY
    )
    observability = EpisodeReviewObservability()
    service = TrustedEpisodeReviewClaimService(
        mailbox=mailbox,
        observability=observability,
    )
    return EpisodeReviewRuntime(
        mailbox=mailbox,
        service=service,
        observability=observability,
    )


def compose_episode_review_lifespan(
    inner_lifespan,
    runtime_factory=production_episode_review_runtime_factory,
):
    """Expose C30-P state inside C19 construction without owning outer lifecycle."""
    if not callable(inner_lifespan):
        raise TypeError("inner lifespan must be callable")
    if not callable(runtime_factory):
        raise TypeError("runtime_factory must be callable")

    authority_owner = getattr(inner_lifespan, "__wrapped__", inner_lifespan)

    @wraps(inner_lifespan)
    @asynccontextmanager
    async def composed(app):
        async with inner_lifespan(app):
            runtime = runtime_factory(app)
            if runtime is not None and not isinstance(
                runtime,
                EpisodeReviewRuntime,
            ):
                raise TypeError(
                    "runtime_factory must return EpisodeReviewRuntime or None"
                )

            installed_state_names: list[str] = []
            if runtime is not None:
                app.state.consciousness_episode_review_runtime = runtime
                installed_state_names.append(
                    "consciousness_episode_review_runtime"
                )
                app.state.consciousness_episode_review_mailbox = (
                    runtime.mailbox
                )
                installed_state_names.append(
                    "consciousness_episode_review_mailbox"
                )
                app.state.consciousness_episode_review_service = (
                    runtime.service
                )
                installed_state_names.append(
                    "consciousness_episode_review_service"
                )
                if runtime.observability is not None:
                    app.state.consciousness_episode_review_observability = (
                        runtime.observability
                    )
                    installed_state_names.append(
                        "consciousness_episode_review_observability"
                    )

            try:
                yield
            finally:
                for name in reversed(installed_state_names):
                    delattr(app.state, name)
                if runtime is not None:
                    runtime.close()

    composed.__wrapped__ = authority_owner
    return composed
