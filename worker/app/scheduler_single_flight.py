"""Explicit bounded concurrency for scheduler ticks (T-018).

The scheduler uses single-flight by design: at most one tick may execute in one
worker process and overlapping callers are rejected before they can claim an
occurrence. Queue capacity is deliberately zero, so pressure cannot create an
unbounded collection of waiting tasks. The same counters are exposed through
the existing operator-only scheduler status endpoint.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable

_logger = logging.getLogger("app.schedule_runner")


@dataclass(frozen=True)
class SingleFlightStatus:
    max_concurrency: int
    queue_capacity: int
    active: int
    accepted: int
    overlap_rejections: int


class SingleFlightGate:
    """Non-blocking concurrency gate with capacity one and no waiting queue."""

    MAX_CONCURRENCY = 1
    QUEUE_CAPACITY = 0

    def __init__(self) -> None:
        self._execution = threading.Lock()
        self._state = threading.Lock()
        self._active = 0
        self._accepted = 0
        self._overlap_rejections = 0

    def try_enter(self) -> bool:
        if not self._execution.acquire(blocking=False):
            with self._state:
                self._overlap_rejections += 1
            return False
        with self._state:
            self._active = 1
            self._accepted += 1
        return True

    def leave(self) -> None:
        with self._state:
            self._active = 0
        self._execution.release()

    def status(self) -> SingleFlightStatus:
        with self._state:
            return SingleFlightStatus(
                max_concurrency=self.MAX_CONCURRENCY,
                queue_capacity=self.QUEUE_CAPACITY,
                active=self._active,
                accepted=self._accepted,
                overlap_rejections=self._overlap_rejections,
            )


def install_single_flight(runner_cls: type, tick_result_cls: Callable[..., Any]) -> None:
    """Install the fail-fast single-flight contract on ``SchedulerRunner`` once."""

    if getattr(runner_cls, "_kaliv_single_flight_installed", False):
        return

    original_init = runner_cls.__init__
    original_run_once = runner_cls.run_once

    def guarded_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._single_flight_gate = SingleFlightGate()

    def guarded_run_once(self, *args, **kwargs):
        gate: SingleFlightGate = self._single_flight_gate
        if not gate.try_enter():
            status = gate.status()
            _logger.warning(
                "scheduler: overlapping tick rejected before claim "
                "(policy=single-flight max_concurrency=%d queue_capacity=%d "
                "overlap_rejections=%d owner_id=%s)",
                status.max_concurrency,
                status.queue_capacity,
                status.overlap_rejections,
                getattr(self, "owner_id", "unknown"),
            )
            try:
                enabled = bool(self.feature_enabled())
            except Exception:
                enabled = False
            paused = enabled and not bool(getattr(self.gate, "enabled", False))
            return tick_result_cls(enabled, paused, 0, 0, 0, 0)
        try:
            return original_run_once(self, *args, **kwargs)
        finally:
            gate.leave()

    def single_flight_status(self) -> SingleFlightStatus:
        return self._single_flight_gate.status()

    runner_cls.__init__ = guarded_init
    runner_cls.run_once = guarded_run_once
    runner_cls.single_flight_status = single_flight_status
    runner_cls.MAX_CONCURRENCY = SingleFlightGate.MAX_CONCURRENCY
    runner_cls.QUEUE_CAPACITY = SingleFlightGate.QUEUE_CAPACITY
    runner_cls._kaliv_single_flight_installed = True
