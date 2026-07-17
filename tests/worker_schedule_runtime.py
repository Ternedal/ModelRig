"""Scheduler process ownership: inert import, startup and ordered shutdown.

Run: PYTHONPATH=worker python3 tests/worker_schedule_runtime.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.schedule_runtime import (  # noqa: E402
    SchedulerRuntime,
    scheduler_lifespan,
)

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


class Resource:
    def __init__(self, name, events):
        self.name = name
        self.events = events
        self.closed = False

    def close(self):
        self.events.append(f"{self.name}:close")
        self.closed = True


class FakeService:
    def __init__(self, events, *, starts=True, stops=None):
        self.events = events
        self.starts = starts
        self.stops = list(stops or [True])
        self.running = False

    def start(self):
        self.events.append("service:start")
        self.running = bool(self.starts)
        return self.running

    def stop(self, timeout=5.0):
        self.events.append("service:stop")
        result = self.stops.pop(0) if len(self.stops) > 1 else self.stops[0]
        if result:
            self.running = False
        return result

    def status(self):
        return SimpleNamespace(running=self.running)


def runtime_with(events, *, enabled=True, service=None, job_factory=None):
    schedules = Resource("schedules", events)
    jobs = Resource("jobs", events)
    gate = object()
    service = service or FakeService(events)

    def make_schedules():
        events.append("schedules:create")
        return schedules

    def make_jobs():
        events.append("jobs:create")
        if job_factory is not None:
            return job_factory()
        return jobs

    def make_gate():
        events.append("gate:get")
        return gate

    def make_runner(s, j, g):
        events.append("runner:create")
        check((s, j, g) == (schedules, jobs, gate), "runner receives the owned stores and real gate")
        return object()

    def make_service(_runner):
        events.append("service:create")
        return service

    return SchedulerRuntime(
        enabled_fn=lambda: enabled,
        schedule_factory=make_schedules,
        job_factory=make_jobs,
        gate_factory=make_gate,
        runner_factory=make_runner,
        service_factory=make_service,
    ), schedules, jobs, service


# --- import + flag OFF are genuinely dormant ---------------------------------

check("app.tools" not in sys.modules, "importing schedule_runtime does not import ToolGate or open its audit DB")
called = []


def bomb():
    called.append("factory")
    raise AssertionError("factory must not run while scheduler is off")


off = SchedulerRuntime(
    enabled_fn=lambda: False,
    schedule_factory=bomb,
    job_factory=bomb,
    gate_factory=bomb,
    runner_factory=lambda *_: bomb(),
    service_factory=lambda *_: bomb(),
)
check(not off.start(), "flag OFF refuses startup")
check(not called and "app.tools" not in sys.modules, "flag OFF opens no resources and keeps ToolGate lazy")
check(not off.status().configured and not off.status().resources_open, "dormant status tells the truth")
check(off.close(), "closing a never-started runtime is harmless")


# --- enabled startup is ordered, idempotent and fully owned -------------------

events = []
runtime, schedules, jobs, service = runtime_with(events)
check(runtime.start(), "enabled runtime starts")
check(events[:6] == [
    "schedules:create", "jobs:create", "gate:get", "runner:create",
    "service:create", "service:start",
], "stores, gate, runner and service are constructed in dependency order")
first_events = list(events)
check(runtime.start(), "start is idempotent")
check(events == first_events, "idempotent start creates no duplicate stores or service")
state = runtime.status()
check(state.configured and state.running and state.resources_open and state.last_error is None,
      "running status exposes configured, live owned resources")
check(runtime.close(), "runtime shuts down cleanly")
check(events[-3:] == ["service:stop", "jobs:close", "schedules:close"],
      "shutdown stops the thread before closing jobs then schedules")
check(jobs.closed and schedules.closed, "both owned SQLite-style resources are closed")
after_close = list(events)
check(runtime.close() and events == after_close, "shutdown is idempotent")


# --- partial startup failures clean up everything already opened --------------

partial_events = []


def broken_jobs():
    raise RuntimeError("jobs database locked")


partial, partial_schedules, _, _ = runtime_with(
    partial_events, job_factory=broken_jobs
)
check(not partial.start(), "partial startup failure is fail-closed")
check(partial_schedules.closed, "a schedule store opened before failure is closed")
partial_state = partial.status()
check(not partial_state.running and not partial_state.resources_open,
      "partial failure leaves no pretend-running resources")
check("RuntimeError: jobs database locked" in (partial_state.last_error or ""),
      "partial failure keeps the bounded real reason")


# --- a flag race at service.start also cleans all constructed resources -------

race_events = []
race_service = FakeService(race_events, starts=False)
race, race_schedules, race_jobs, _ = runtime_with(race_events, service=race_service)
check(not race.start(), "service refusing start is treated as a flag race, not success")
check(race_jobs.closed and race_schedules.closed, "flag-race startup closes both stores")
check(not race.status().resources_open, "flag-race startup retains no resources")


# --- never close databases underneath a service that failed to stop -----------

stop_events = []
stubborn_service = FakeService(stop_events, stops=[False, True])
stubborn, stubborn_schedules, stubborn_jobs, _ = runtime_with(
    stop_events, service=stubborn_service
)
check(stubborn.start(), "stubborn service starts for shutdown test")
check(not stubborn.close(timeout=0.01), "shutdown reports an unjoined service")
check(not stubborn_jobs.closed and not stubborn_schedules.closed,
      "stores stay open while their service may still use them")
check(stubborn.status().resources_open, "failed shutdown remains observable and retryable")
check(stubborn.close(timeout=0.5), "a later shutdown retry may complete")
check(stubborn_jobs.closed and stubborn_schedules.closed, "successful retry closes the stores")


# --- production entrypoint owns the lifespan; raw route app remains testable --

old_flag = os.environ.pop("KALIV_SCHEDULER", None)
try:
    from app import entrypoint  # noqa: E402

    check(entrypoint.fastapi_app.router.lifespan_context is scheduler_lifespan,
          "documented production entrypoint installs the scheduler lifespan")

    async def exercise_off_lifespan():
        async with scheduler_lifespan(entrypoint.fastapi_app):
            live = entrypoint.fastapi_app.state.scheduler_runtime.status()
            check(not live.configured and not live.resources_open,
                  "production lifespan remains resource-free while flag is OFF")
        check(not entrypoint.fastapi_app.state.scheduler_runtime.status().resources_open,
              "production lifespan shutdown leaves no scheduler resources")

    asyncio.run(exercise_off_lifespan())
finally:
    if old_flag is not None:
        os.environ["KALIV_SCHEDULER"] = old_flag


print(f"\n===== SCHEDULE RUNTIME: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
