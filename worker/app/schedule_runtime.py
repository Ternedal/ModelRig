"""Own the dormant scheduler resources for one worker process.

Importing this module is side-effect free: while ``KALIV_SCHEDULER`` is off it
opens no scheduler/job/audit database and creates no thread.  The expensive
imports and persistent stores are constructed only inside :meth:`start` after
the feature flag has been checked.  FastAPI owns one instance through the
lifespan hook at the bottom of the file.
"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Callable

from .scheduler import enabled as scheduler_enabled

_logger = logging.getLogger("modelrig.worker.scheduler")


@dataclass(frozen=True)
class RuntimeStatus:
    configured: bool
    running: bool
    resources_open: bool
    last_error: str | None


class SchedulerRuntime:
    """Create, start and close exactly one scheduler service and its stores.

    Factories are injectable so lifecycle behaviour can be proven without
    touching SQLite or starting a real scheduler thread.  Defaults stay lazy on
    purpose: importing the worker while the flag is off must remain inert.
    """

    def __init__(
        self,
        *,
        enabled_fn: Callable[[], bool] = scheduler_enabled,
        schedule_factory: Callable[[], Any] | None = None,
        job_factory: Callable[[], Any] | None = None,
        gate_factory: Callable[[], Any] | None = None,
        runner_factory: Callable[[Any, Any, Any], Any] | None = None,
        service_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        self._enabled_fn = enabled_fn
        self._schedule_factory = schedule_factory
        self._job_factory = job_factory
        self._gate_factory = gate_factory
        self._runner_factory = runner_factory
        self._service_factory = service_factory
        self._lock = threading.RLock()
        self._schedules: Any | None = None
        self._jobs: Any | None = None
        self._service: Any | None = None
        self._started = False
        self._last_error: str | None = None

    def start(self) -> bool:
        """Start once when explicitly configured; otherwise do nothing at all."""
        with self._lock:
            if self._started:
                return True
            try:
                configured = bool(self._enabled_fn())
            except Exception as exc:
                self._last_error = (
                    f"feature flag check failed: {type(exc).__name__}: {exc}"[:500]
                )
                return False
            if not configured:
                self._last_error = None
                return False

            schedules = jobs = service = None
            try:
                schedule_factory, job_factory, gate_factory, runner_factory, service_factory = (
                    self._factories()
                )
                schedules = schedule_factory()
                jobs = job_factory()
                gate = gate_factory()
                runner = runner_factory(schedules, jobs, gate)
                service = service_factory(runner)
                if not service.start():
                    self._cleanup(service, jobs, schedules)
                    self._last_error = (
                        "scheduler flag changed before the service could start"
                    )
                    return False
            except Exception as exc:
                self._cleanup(service, jobs, schedules)
                self._last_error = f"{type(exc).__name__}: {exc}"[:500]
                return False

            self._schedules = schedules
            self._jobs = jobs
            self._service = service
            self._started = True
            self._last_error = None
            return True

    def close(self, timeout: float = 5.0) -> bool:
        """Stop the thread before closing its stores; safe to call repeatedly."""
        with self._lock:
            if self._service is None and self._jobs is None and self._schedules is None:
                self._started = False
                return True

            if self._service is not None:
                try:
                    stopped = bool(self._service.stop(timeout=timeout))
                except Exception as exc:
                    self._last_error = (
                        f"scheduler stop failed: {type(exc).__name__}: {exc}"[:500]
                    )
                    return False
                if not stopped:
                    # Never close SQLite underneath a thread that may still use it.
                    self._last_error = "scheduler thread did not stop before timeout"
                    return False
                self._service = None
                self._started = False

            errors: list[str] = []
            for name, attr in (("jobs", "_jobs"), ("schedules", "_schedules")):
                resource = getattr(self, attr)
                if resource is None:
                    continue
                close = getattr(resource, "close", None)
                if close is None:
                    setattr(self, attr, None)
                    continue
                try:
                    close()
                except Exception as exc:
                    # Keep the failing resource referenced so shutdown can be
                    # retried and status cannot claim everything is closed.
                    errors.append(f"{name}: {type(exc).__name__}: {exc}")
                else:
                    setattr(self, attr, None)

            self._last_error = "; ".join(errors)[:500] or None
            return not errors

    def status(self) -> RuntimeStatus:
        with self._lock:
            try:
                configured = bool(self._enabled_fn())
            except Exception as exc:
                configured = False
                self._last_error = (
                    f"feature flag check failed: {type(exc).__name__}: {exc}"[:500]
                )

            running = self._started
            if self._service is not None:
                try:
                    running = bool(self._service.status().running)
                except Exception:
                    running = self._started
            return RuntimeStatus(
                configured=configured,
                running=running,
                resources_open=any(
                    resource is not None
                    for resource in (self._service, self._jobs, self._schedules)
                ),
                last_error=self._last_error,
            )

    def _factories(self):
        if all(
            factory is not None
            for factory in (
                self._schedule_factory,
                self._job_factory,
                self._gate_factory,
                self._runner_factory,
                self._service_factory,
            )
        ):
            return (
                self._schedule_factory,
                self._job_factory,
                self._gate_factory,
                self._runner_factory,
                self._service_factory,
            )

        # Lazy imports are the dormant guarantee.  In particular tools.GATE owns
        # the audit database, so importing it before the flag check would make
        # "off" create persistent state anyway.
        from . import tools
        from .jobs import JobStore
        from .schedule_runner import SchedulerRunner
        from .schedule_service import SchedulerService
        from .scheduler import ScheduleStore

        return (
            self._schedule_factory or ScheduleStore,
            self._job_factory or JobStore,
            self._gate_factory or (lambda: tools.GATE),
            self._runner_factory or SchedulerRunner,
            self._service_factory or SchedulerService,
        )

    @staticmethod
    def _cleanup(service: Any, jobs: Any, schedules: Any) -> None:
        """Best-effort cleanup for partial startup, always in dependency order."""
        if service is not None:
            try:
                service.stop(timeout=1.0)
            except Exception:
                pass
        for resource in (jobs, schedules):
            close = getattr(resource, "close", None)
            if close is not None:
                try:
                    close()
                except Exception:
                    pass


def _ensure_scheduler_logging() -> None:
    """Make the scheduler's operational INFO lines actually reach the log.

    The production launch configures only the request logger; the ROOT logger
    has no handler at all, so everything below WARNING vanished (WARNINGs only
    surfaced through Python's lastResort handler). The startup recovery
    summary ("recovered N executed / M abandoned / K unknown") and the lease
    lifecycle lines are exactly what the runbook tells the operator to READ --
    found by the sandbox rehearsal, where a clean-crash recovery ran perfectly
    and said nothing. Scoped to the two scheduler modules: level INFO plus one
    shared stderr handler, attached only when no real root handler exists, and
    idempotent across restarts of the lifespan.
    """
    root_has_handlers = bool(logging.getLogger().handlers)
    handler: logging.Handler | None = None
    if not root_has_handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handler._kaliv_scheduler_handler = True  # type: ignore[attr-defined]
    for name in ("app.schedule_service", "app.schedule_runner"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.INFO)
        if handler is not None and not any(
                getattr(h, "_kaliv_scheduler_handler", False)
                for h in lg.handlers):
            lg.addHandler(handler)
            lg.propagate = False


@asynccontextmanager
async def scheduler_lifespan(app):
    """FastAPI lifecycle integration; optional failure never exposes a route."""
    _ensure_scheduler_logging()
    runtime = SchedulerRuntime()
    app.state.scheduler_runtime = runtime
    started = runtime.start()
    state = runtime.status()
    if state.configured and not started:
        _logger.error("scheduler configured but not started: %s", state.last_error)
    try:
        yield
    finally:
        if not runtime.close():
            _logger.error("scheduler shutdown incomplete: %s", runtime.status().last_error)
