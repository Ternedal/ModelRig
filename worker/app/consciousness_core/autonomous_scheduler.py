"""C25-C scheduler-owned cadence bridge for autonomous cognition.

This module creates no thread, timer or polling loop. It reuses the existing
SchedulerService thread as the cadence source and submits at most one C25-B
tick coroutine back to the FastAPI owner event loop.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import os
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import wraps
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .autonomous_tick import (
    AutonomousCognitionTickAdapter,
    AutonomousCognitionTickReceipt,
    autonomous_cognition_enabled,
)
from .policy_checkpoint import (
    PolicyDrivenCheckpointResult,
    PolicyDrivenSelfStateCheckpointAdapter,
)
from .session_lifecycle import ProductionCognitiveSession


AUTONOMOUS_SCHEDULER_FLAG = (
    "KALIV_CONSCIOUSNESS_AUTONOMOUS_SCHEDULER_ENABLED"
)
AUTONOMOUS_CHECKPOINT_FLAG = (
    "KALIV_CONSCIOUSNESS_AUTONOMOUS_CHECKPOINT_ENABLED"
)
_DEFAULT_BRIDGE_TIMEOUT_S = 30.0


class AutonomousSchedulerBridgeError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class AutonomousSchedulerBridgeStatus(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/autonomous-scheduler-status/v1"
    ]
    installed: bool
    closed: bool
    callback_count: int = Field(ge=0, strict=True)
    completed_count: int = Field(ge=0, strict=True)
    timeout_count: int = Field(ge=0, strict=True)
    failure_count: int = Field(ge=0, strict=True)
    overlap_rejections: int = Field(ge=0, strict=True)
    active: bool
    last_outcome: (
        Literal["DISABLED", "IDLE", "DEFER", "WAIT", "RUN"] | None
    )
    last_error: str | None
    checkpoint_enabled: bool = False
    checkpoint_evaluation_count: int = Field(ge=0, strict=True, default=0)
    checkpoint_commit_count: int = Field(ge=0, strict=True, default=0)
    checkpoint_failure_count: int = Field(ge=0, strict=True, default=0)
    last_checkpoint_outcome: (
        Literal["IDLE", "HOLD", "COMMITTED"] | None
    ) = None
    last_checkpoint_error: str | None = None
    internal_thread_created: Literal[False]
    internal_timer_created: Literal[False]
    retry_authority: Literal[False]
    execution_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    production_activation: Literal[False]


def autonomous_scheduler_enabled() -> bool:
    return (
        os.getenv(
            "KALIV_CONSCIOUSNESS_AUTONOMOUS_SCHEDULER_ENABLED",
            "0",
        )
        == "1"
    )


def autonomous_checkpoint_enabled() -> bool:
    """Only exact string 1 couples C25-C to the C27-G service."""
    return (
        os.getenv(
            "KALIV_CONSCIOUSNESS_AUTONOMOUS_CHECKPOINT_ENABLED",
            "0",
        )
        == "1"
    )


@dataclass(frozen=True)
class _OwnerLoopTickResult:
    receipt: AutonomousCognitionTickReceipt | None
    checkpoint_results: tuple[PolicyDrivenCheckpointResult, ...]
    checkpoint_error_stage: Literal["pre", "post"] | None
    checkpoint_error_type: str | None


class ScheduledAutonomousCognitionBridge:
    """Scheduler-thread callback -> owner-loop C25-B coroutine bridge."""

    def __init__(
        self,
        *,
        adapter: AutonomousCognitionTickAdapter,
        owner_loop: asyncio.AbstractEventLoop,
        timeout_s: float = _DEFAULT_BRIDGE_TIMEOUT_S,
        checkpoint_adapter: PolicyDrivenSelfStateCheckpointAdapter | None = None,
    ) -> None:
        if not isinstance(adapter, AutonomousCognitionTickAdapter):
            raise TypeError("adapter must be AutonomousCognitionTickAdapter")
        if not isinstance(owner_loop, asyncio.AbstractEventLoop):
            raise TypeError("owner_loop must be an asyncio event loop")
        if timeout_s <= 0 or timeout_s > 120:
            raise ValueError("timeout_s must be in (0, 120]")
        if checkpoint_adapter is not None and not isinstance(
            checkpoint_adapter,
            PolicyDrivenSelfStateCheckpointAdapter,
        ):
            raise TypeError(
                "checkpoint_adapter must be "
                "PolicyDrivenSelfStateCheckpointAdapter or None"
            )

        self._adapter = adapter
        self._checkpoint_adapter = checkpoint_adapter
        self._loop = owner_loop
        self._timeout_s = float(timeout_s)
        self._lock = threading.RLock()
        self._future: concurrent.futures.Future | None = None
        self._installed = False
        self._closed = False
        self._callback_count = 0
        self._completed_count = 0
        self._timeout_count = 0
        self._failure_count = 0
        self._overlap_rejections = 0
        self._last_outcome: str | None = None
        self._last_error: str | None = None
        self._checkpoint_evaluation_count = 0
        self._checkpoint_commit_count = 0
        self._checkpoint_failure_count = 0
        self._last_checkpoint_outcome: str | None = None
        self._last_checkpoint_error: str | None = None

    async def _owner_loop_tick(self) -> _OwnerLoopTickResult:
        checkpoint_results: list[PolicyDrivenCheckpointResult] = []

        if self._checkpoint_adapter is not None:
            try:
                before = self._checkpoint_adapter.maybe_checkpoint_once()
            except Exception as exc:
                return _OwnerLoopTickResult(
                    receipt=None,
                    checkpoint_results=tuple(checkpoint_results),
                    checkpoint_error_stage="pre",
                    checkpoint_error_type=type(exc).__name__,
                )
            if not isinstance(before, PolicyDrivenCheckpointResult):
                return _OwnerLoopTickResult(
                    receipt=None,
                    checkpoint_results=tuple(checkpoint_results),
                    checkpoint_error_stage="pre",
                    checkpoint_error_type="InvalidCheckpointResult",
                )
            checkpoint_results.append(before)

        receipt = await self._adapter.tick_once()

        if (
            self._checkpoint_adapter is not None
            and receipt.outcome == "RUN"
        ):
            try:
                after = self._checkpoint_adapter.maybe_checkpoint_once()
            except Exception as exc:
                return _OwnerLoopTickResult(
                    receipt=receipt,
                    checkpoint_results=tuple(checkpoint_results),
                    checkpoint_error_stage="post",
                    checkpoint_error_type=type(exc).__name__,
                )
            if not isinstance(after, PolicyDrivenCheckpointResult):
                return _OwnerLoopTickResult(
                    receipt=receipt,
                    checkpoint_results=tuple(checkpoint_results),
                    checkpoint_error_stage="post",
                    checkpoint_error_type="InvalidCheckpointResult",
                )
            checkpoint_results.append(after)

        return _OwnerLoopTickResult(
            receipt=receipt,
            checkpoint_results=tuple(checkpoint_results),
            checkpoint_error_stage=None,
            checkpoint_error_type=None,
        )

    def mark_installed(self) -> None:
        with self._lock:
            if self._closed:
                raise AutonomousSchedulerBridgeError(
                    "cannot install closed autonomous scheduler bridge"
                )
            self._installed = True

    def on_scheduler_tick(self, _schedule_result) -> None:
        """Run on the existing scheduler thread after a successful tick."""
        with self._lock:
            self._callback_count += 1
            if self._closed:
                return
            if self._future is not None and not self._future.done():
                self._overlap_rejections += 1
                return
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._owner_loop_tick(),
                    self._loop,
                )
            except Exception as exc:
                self._failure_count += 1
                self._last_error = (
                    f"submit failed: {type(exc).__name__}"[:256]
                )
                return
            self._future = future

        try:
            receipt = future.result(timeout=self._timeout_s)
        except concurrent.futures.TimeoutError:
            future.cancel()
            with self._lock:
                self._timeout_count += 1
                self._last_error = "autonomous cognition tick timed out"
        except concurrent.futures.CancelledError:
            with self._lock:
                if not self._closed:
                    self._failure_count += 1
                    self._last_error = "autonomous cognition tick cancelled"
        except Exception as exc:
            with self._lock:
                self._failure_count += 1
                # Provider/session exception text is deliberately not retained.
                self._last_error = (
                    f"autonomous cognition tick failed: "
                    f"{type(exc).__name__}"[:256]
                )
        else:
            owner_result = receipt
            if not isinstance(owner_result, _OwnerLoopTickResult):
                with self._lock:
                    self._failure_count += 1
                    self._last_error = (
                        "autonomous cognition owner-loop returned invalid result"
                    )
            else:
                with self._lock:
                    evaluations = len(owner_result.checkpoint_results)
                    if owner_result.checkpoint_error_stage is not None:
                        evaluations += 1
                    self._checkpoint_evaluation_count += evaluations
                    self._checkpoint_commit_count += sum(
                        1
                        for item in owner_result.checkpoint_results
                        if item.outcome == "COMMITTED"
                    )
                    if owner_result.checkpoint_results:
                        self._last_checkpoint_outcome = (
                            owner_result.checkpoint_results[-1].outcome
                        )
                    if owner_result.checkpoint_error_stage is None:
                        if owner_result.checkpoint_results:
                            self._last_checkpoint_error = None
                    else:
                        self._checkpoint_failure_count += 1
                        self._failure_count += 1
                        self._last_checkpoint_error = (
                            f"{owner_result.checkpoint_error_stage}-tick "
                            f"SelfState checkpoint failed: "
                            f"{owner_result.checkpoint_error_type}"
                        )[:256]

                    tick_receipt = owner_result.receipt
                    if tick_receipt is None:
                        self._last_error = self._last_checkpoint_error
                    elif not isinstance(
                        tick_receipt,
                        AutonomousCognitionTickReceipt,
                    ):
                        self._failure_count += 1
                        self._last_error = (
                            "autonomous cognition tick returned invalid receipt"
                        )
                    else:
                        self._completed_count += 1
                        self._last_outcome = tick_receipt.outcome
                        self._last_error = self._last_checkpoint_error
        finally:
            with self._lock:
                if self._future is future:
                    self._future = None

    async def aclose(self) -> None:
        """Stop accepting ticks and cancel an in-flight owner-loop coroutine."""
        with self._lock:
            self._closed = True
            self._installed = False
            future = self._future
        if future is not None and not future.done():
            future.cancel()
            try:
                await asyncio.wrap_future(future)
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        await asyncio.sleep(0)

    def status(self) -> AutonomousSchedulerBridgeStatus:
        with self._lock:
            future = self._future
            return AutonomousSchedulerBridgeStatus(
                schema=(
                    "kaliv-consciousness-core/"
                    "autonomous-scheduler-status/v1"
                ),
                installed=self._installed,
                closed=self._closed,
                callback_count=self._callback_count,
                completed_count=self._completed_count,
                timeout_count=self._timeout_count,
                failure_count=self._failure_count,
                overlap_rejections=self._overlap_rejections,
                active=bool(future is not None and not future.done()),
                last_outcome=self._last_outcome,
                last_error=self._last_error,
                checkpoint_enabled=self._checkpoint_adapter is not None,
                checkpoint_evaluation_count=(
                    self._checkpoint_evaluation_count
                ),
                checkpoint_commit_count=self._checkpoint_commit_count,
                checkpoint_failure_count=self._checkpoint_failure_count,
                last_checkpoint_outcome=self._last_checkpoint_outcome,
                last_checkpoint_error=self._last_checkpoint_error,
                internal_thread_created=False,
                internal_timer_created=False,
                retry_authority=False,
                execution_authority=False,
                durable_memory_write_authority=False,
                production_activation=False,
            )


def production_autonomous_scheduler_bridge_factory(
    app,
    *,
    timeout_s: float = _DEFAULT_BRIDGE_TIMEOUT_S,
) -> ScheduledAutonomousCognitionBridge | None:
    """Build only after all production owners already exist."""
    if not autonomous_scheduler_enabled():
        return None
    if not autonomous_cognition_enabled():
        return None

    runtime = getattr(app.state, "scheduler_runtime", None)
    if runtime is None:
        return None
    try:
        status = runtime.status()
    except Exception:
        return None
    if not bool(getattr(status, "running", False)):
        return None

    session = getattr(app.state, "consciousness_session", None)
    if not isinstance(session, ProductionCognitiveSession) or session.closed:
        return None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError as exc:
        raise AutonomousSchedulerBridgeError(
            "autonomous scheduler bridge requires owner event loop"
        ) from exc

    adapter = AutonomousCognitionTickAdapter(
        session=session,
        clock=session.trusted_clock,
    )

    checkpoint_adapter = None
    if autonomous_checkpoint_enabled():
        checkpoint_adapter = getattr(
            app.state,
            "consciousness_policy_checkpoint",
            None,
        )
        if not isinstance(
            checkpoint_adapter,
            PolicyDrivenSelfStateCheckpointAdapter,
        ):
            raise AutonomousSchedulerBridgeError(
                "autonomous checkpoint coupling requires live "
                "C27-G policy checkpoint service"
            )

    return ScheduledAutonomousCognitionBridge(
        adapter=adapter,
        owner_loop=loop,
        timeout_s=timeout_s,
        checkpoint_adapter=checkpoint_adapter,
    )


def compose_autonomous_scheduler_lifespan(
    inner_lifespan,
    bridge_factory=production_autonomous_scheduler_bridge_factory,
):
    """Register C25-C only after C19 session startup; clear it before teardown."""
    if not callable(inner_lifespan):
        raise TypeError("inner lifespan must be callable")
    if not callable(bridge_factory):
        raise TypeError("bridge_factory must be callable")

    authority_owner = getattr(inner_lifespan, "__wrapped__", inner_lifespan)

    @wraps(inner_lifespan)
    @asynccontextmanager
    async def composed(app):
        async with inner_lifespan(app):
            bridge = bridge_factory(app)
            runtime = getattr(app.state, "scheduler_runtime", None)
            installed = False
            if bridge is not None:
                if not isinstance(
                    bridge,
                    ScheduledAutonomousCognitionBridge,
                ):
                    raise TypeError(
                        "bridge_factory must return "
                        "ScheduledAutonomousCognitionBridge or None"
                    )
                if runtime is None:
                    raise AutonomousSchedulerBridgeError(
                        "scheduler runtime disappeared during composition"
                    )
                try:
                    installed = bool(
                        runtime.set_post_tick_hook(
                            bridge.on_scheduler_tick
                        )
                    )
                except Exception as exc:
                    await bridge.aclose()
                    raise AutonomousSchedulerBridgeError(
                        "could not install autonomous scheduler hook"
                    ) from exc
                if not installed:
                    await bridge.aclose()
                    bridge = None
                else:
                    bridge.mark_installed()
                    app.state.consciousness_autonomous_scheduler = bridge

            try:
                yield
            finally:
                if bridge is not None:
                    try:
                        runtime.set_post_tick_hook(None)
                    finally:
                        await bridge.aclose()
                        try:
                            delattr(
                                app.state,
                                "consciousness_autonomous_scheduler",
                            )
                        except AttributeError:
                            pass

    composed.__wrapped__ = authority_owner
    return composed
