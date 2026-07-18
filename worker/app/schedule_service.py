"""Lifecycle wrapper for the dormant scheduler runner.

This module still does not wire itself into FastAPI or worker startup. It only
provides the small, testable service object that a later lifespan hook may own.
Calling :meth:`SchedulerService.start` while ``KALIV_SCHEDULER`` is off creates
no thread and performs no claim.
"""
from __future__ import annotations

import math
import os
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .schedule_runner import SchedulerRunner, TickResult

DEFAULT_POLL_S = 15.0
MIN_POLL_S = 5.0
MAX_POLL_S = 3600.0


def poll_seconds(raw: str | None = None) -> float:
    """Return the bounded scheduler poll interval.

    Environment configuration is deliberately conservative: malformed values
    fall back to 15 seconds, and a production setting cannot turn the service
    into a busy loop. Tests may pass an explicit shorter interval directly to
    :class:`SchedulerService`; the environment parser never permits that.
    """
    value = os.getenv("KALIV_SCHEDULER_POLL_S", "") if raw is None else raw
    if not str(value).strip():
        return DEFAULT_POLL_S
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return DEFAULT_POLL_S
    if not math.isfinite(parsed):
        return DEFAULT_POLL_S
    return max(MIN_POLL_S, min(parsed, MAX_POLL_S))


@dataclass(frozen=True)
class ServiceStatus:
    configured: bool
    running: bool
    ticks: int
    failures: int
    started_at: float | None
    stopped_at: float | None
    last_tick_at: float | None
    last_result: TickResult | None
    last_error: str | None


class SchedulerService:
    """Run bounded scheduler ticks on one interruptible daemon thread."""

    def __init__(
        self,
        runner: SchedulerRunner,
        *,
        poll_s: float | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        interval = poll_seconds() if poll_s is None else float(poll_s)
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("poll_s skal være et positivt, endeligt tal")
        self.runner = runner
        self.poll_s = interval
        self.clock = clock
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._ticks = 0
        self._failures = 0
        self._started_at: float | None = None
        self._stopped_at: float | None = None
        self._last_tick_at: float | None = None
        self._last_result: TickResult | None = None
        self._last_error: str | None = None

    def start(self) -> bool:
        """Start once when configured; return False without side effects when off."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return True
            if not self.runner.feature_enabled():
                return False
            # Migrate before the loop can claim anything (F-710): a grant for a
            # tool that may no longer run unattended is disabled here, so it
            # never wakes to be refused on every cadence. Idempotent.
            migrated = self.runner.disable_unschedulable()
            if migrated:
                logging.getLogger(__name__).info(
                    "scheduler: disabled %d unschedulable grant(s) at startup: %s",
                    len(migrated), ", ".join(migrated))
            self._stop.clear()
            self._started_at = self.clock()
            self._stopped_at = None
            thread = threading.Thread(
                target=self._loop,
                name="kaliv-scheduler",
                daemon=True,
            )
            self._thread = thread
            thread.start()
            return True

    def stop(self, timeout: float = 5.0) -> bool:
        """Interrupt the wait and join the service thread.

        Returns True when stopped (including when it was never started). The
        runner's stores are externally owned and are intentionally not closed
        here; lifecycle ownership must not be guessed by a background thread.
        """
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            return False
        thread.join(max(0.0, timeout))
        stopped = not thread.is_alive()
        if stopped:
            with self._lock:
                self._stopped_at = self.clock()
        return stopped

    def status(self) -> ServiceStatus:
        with self._lock:
            thread = self._thread
            return ServiceStatus(
                configured=bool(self.runner.feature_enabled()),
                running=bool(thread and thread.is_alive()),
                ticks=self._ticks,
                failures=self._failures,
                started_at=self._started_at,
                stopped_at=self._stopped_at,
                last_tick_at=self._last_tick_at,
                last_result=self._last_result,
                last_error=self._last_error,
            )

    def _loop(self) -> None:
        while not self._stop.is_set():
            tick_at = self.clock()
            try:
                result = self.runner.run_once()
            except Exception as exc:
                with self._lock:
                    self._ticks += 1
                    self._failures += 1
                    self._last_tick_at = tick_at
                    self._last_result = None
                    self._last_error = (
                        f"{type(exc).__name__}: {exc}"[:500]
                    )
            else:
                with self._lock:
                    self._ticks += 1
                    self._last_tick_at = tick_at
                    self._last_result = result
                    self._last_error = None

            # Event.wait(), not sleep(): shutdown must interrupt a 60-minute
            # interval immediately rather than making process exit wait for it.
            if self._stop.wait(self.poll_s):
                break

        with self._lock:
            self._stopped_at = self.clock()
