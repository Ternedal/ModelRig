#!/usr/bin/env python3
"""C25-C scheduler-owned autonomous cognition cadence tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_autonomous_scheduler.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core.autonomous_scheduler import (  # noqa: E402
    AUTONOMOUS_SCHEDULER_FLAG,
    ScheduledAutonomousCognitionBridge,
    autonomous_scheduler_enabled,
    compose_autonomous_scheduler_lifespan,
    production_autonomous_scheduler_bridge_factory,
)
from app.consciousness_core.autonomous_tick import (  # noqa: E402
    AUTONOMOUS_COGNITION_FLAG,
    AutonomousCognitionTickAdapter,
    AutonomousCognitionTickReceipt,
)
from app.schedule_runner import TickResult  # noqa: E402
from app.schedule_service import SchedulerService  # noqa: E402


def tick_result() -> TickResult:
    return TickResult(
        enabled=True,
        paused=False,
        claimed=0,
        completed=0,
        blocked=0,
        failed=0,
        job_ids=(),
    )


class Runner:
    def __init__(self):
        self.calls = 0

    def feature_enabled(self):
        return True

    def disable_unschedulable(self):
        return []

    def recover_interrupted(self):
        return {"executed": [], "abandoned": [], "unknown": []}

    def run_once(self):
        self.calls += 1
        return tick_result()


class StubAdapter(AutonomousCognitionTickAdapter):
    def __init__(self, *, delay: float = 0.0):
        self.delay = delay
        self.calls = 0
        self.thread_ids = []
        self.cancelled = False

    async def tick_once(self):
        self.calls += 1
        self.thread_ids.append(threading.get_ident())
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return AutonomousCognitionTickReceipt(
            schema="kaliv-consciousness-core/autonomous-cognition-tick/v1",
            outcome="IDLE",
            reason="no_pending_events",
            clock_sample_id="clock-" + "1" * 32,
            evaluated_event_ids=[],
            selected_event_id=None,
            trigger_decision_id=None,
            not_before_monotonic_ms=None,
            cognitive_profile_ref=None,
            supervisor_decision=None,
            supervisor_selected_event_ids=[],
            thought_engine_calls=0,
            accounting_steps_before=0,
            accounting_steps_after=0,
            accounting_updated=False,
            automatic_repeat=False,
            internal_thread_created=False,
            internal_timer_created=False,
            self_state_store_write_applied=False,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )


class FakeSchedulerRuntime:
    def __init__(self, events):
        self.events = events
        self.hook = None

    def set_post_tick_hook(self, hook):
        self.hook = hook
        self.events.append("hook:set" if hook is not None else "hook:clear")
        return True


class AutonomousSchedulerTests(unittest.TestCase):
    def test_exact_scheduler_flag_contract(self):
        old = os.environ.get(AUTONOMOUS_SCHEDULER_FLAG)
        try:
            os.environ.pop(AUTONOMOUS_SCHEDULER_FLAG, None)
            self.assertFalse(autonomous_scheduler_enabled())
            for value in ("true", "on", "yes", "01", " 1 "):
                os.environ[AUTONOMOUS_SCHEDULER_FLAG] = value
                self.assertFalse(autonomous_scheduler_enabled(), value)
            os.environ[AUTONOMOUS_SCHEDULER_FLAG] = "1"
            self.assertTrue(autonomous_scheduler_enabled())
        finally:
            if old is None:
                os.environ.pop(AUTONOMOUS_SCHEDULER_FLAG, None)
            else:
                os.environ[AUTONOMOUS_SCHEDULER_FLAG] = old

    def test_production_factory_flag_off_touches_no_runtime(self):
        class ExplodingRuntime:
            def status(self):
                raise AssertionError("flag-off factory touched scheduler runtime")

        app = SimpleNamespace(
            state=SimpleNamespace(
                scheduler_runtime=ExplodingRuntime(),
            )
        )
        old_sched = os.environ.get(AUTONOMOUS_SCHEDULER_FLAG)
        old_auto = os.environ.get(AUTONOMOUS_COGNITION_FLAG)
        try:
            os.environ.pop(AUTONOMOUS_SCHEDULER_FLAG, None)
            os.environ[AUTONOMOUS_COGNITION_FLAG] = "1"
            self.assertIsNone(
                production_autonomous_scheduler_bridge_factory(app)
            )
        finally:
            if old_sched is None:
                os.environ.pop(AUTONOMOUS_SCHEDULER_FLAG, None)
            else:
                os.environ[AUTONOMOUS_SCHEDULER_FLAG] = old_sched
            if old_auto is None:
                os.environ.pop(AUTONOMOUS_COGNITION_FLAG, None)
            else:
                os.environ[AUTONOMOUS_COGNITION_FLAG] = old_auto

    def test_caller_driven_flag_must_also_be_enabled(self):
        class ExplodingRuntime:
            def status(self):
                raise AssertionError(
                    "C25-B flag-off factory touched scheduler runtime"
                )

        app = SimpleNamespace(
            state=SimpleNamespace(
                scheduler_runtime=ExplodingRuntime(),
            )
        )
        old_sched = os.environ.get(AUTONOMOUS_SCHEDULER_FLAG)
        old_auto = os.environ.get(AUTONOMOUS_COGNITION_FLAG)
        try:
            os.environ[AUTONOMOUS_SCHEDULER_FLAG] = "1"
            os.environ.pop(AUTONOMOUS_COGNITION_FLAG, None)
            self.assertIsNone(
                production_autonomous_scheduler_bridge_factory(app)
            )
        finally:
            if old_sched is None:
                os.environ.pop(AUTONOMOUS_SCHEDULER_FLAG, None)
            else:
                os.environ[AUTONOMOUS_SCHEDULER_FLAG] = old_sched
            if old_auto is None:
                os.environ.pop(AUTONOMOUS_COGNITION_FLAG, None)
            else:
                os.environ[AUTONOMOUS_COGNITION_FLAG] = old_auto

    def test_scheduler_service_hook_uses_existing_thread(self):
        runner = Runner()
        called = threading.Event()
        hook_threads = []

        def hook(_result):
            hook_threads.append(threading.current_thread().name)
            called.set()

        service = SchedulerService(
            runner,
            poll_s=0.01,
            post_tick_hook=hook,
        )
        self.assertTrue(service.start())
        try:
            self.assertTrue(called.wait(1.0))
        finally:
            self.assertTrue(service.stop(timeout=1.0))

        self.assertGreaterEqual(runner.calls, 1)
        self.assertTrue(hook_threads)
        self.assertTrue(
            all(name == "kaliv-scheduler" for name in hook_threads)
        )

    def test_scheduler_hook_failure_does_not_rewrite_runner_success(self):
        runner = Runner()
        called = threading.Event()

        def broken(_result):
            called.set()
            raise RuntimeError("optional observer failed")

        service = SchedulerService(
            runner,
            poll_s=0.01,
            post_tick_hook=broken,
        )
        self.assertTrue(service.start())
        self.assertTrue(called.wait(1.0))
        self.assertTrue(service.stop(timeout=1.0))
        status = service.status()
        self.assertGreaterEqual(status.ticks, 1)
        self.assertEqual(status.failures, 0)

    def test_hook_can_be_installed_and_cleared_after_start(self):
        runner = Runner()
        service = SchedulerService(runner, poll_s=0.01)
        self.assertTrue(service.start())
        try:
            hit = threading.Event()
            service.set_post_tick_hook(lambda _result: hit.set())
            self.assertTrue(hit.wait(1.0))
            service.set_post_tick_hook(None)
        finally:
            self.assertTrue(service.stop(timeout=1.0))

    def test_bridge_runs_coroutine_on_owner_loop_not_scheduler_thread(self):
        async def scenario():
            owner_thread = threading.get_ident()
            adapter = StubAdapter()
            bridge = ScheduledAutonomousCognitionBridge(
                adapter=adapter,
                owner_loop=asyncio.get_running_loop(),
                timeout_s=1.0,
            )
            bridge.mark_installed()
            caller_threads = []

            def call():
                caller_threads.append(threading.get_ident())
                bridge.on_scheduler_tick(tick_result())

            await asyncio.to_thread(call)
            status = bridge.status()
            self.assertEqual(adapter.calls, 1)
            self.assertEqual(adapter.thread_ids, [owner_thread])
            self.assertNotEqual(caller_threads[0], owner_thread)
            self.assertEqual(status.completed_count, 1)
            self.assertEqual(status.last_outcome, "IDLE")
            self.assertFalse(status.active)
            self.assertFalse(status.internal_thread_created)
            self.assertFalse(status.internal_timer_created)
            await bridge.aclose()

        asyncio.run(scenario())

    def test_timeout_cancels_inflight_tick_without_retry(self):
        async def scenario():
            adapter = StubAdapter(delay=10.0)
            bridge = ScheduledAutonomousCognitionBridge(
                adapter=adapter,
                owner_loop=asyncio.get_running_loop(),
                timeout_s=0.02,
            )
            bridge.mark_installed()
            await asyncio.to_thread(
                bridge.on_scheduler_tick,
                tick_result(),
            )
            await asyncio.sleep(0.02)
            status = bridge.status()
            self.assertEqual(adapter.calls, 1)
            self.assertTrue(adapter.cancelled)
            self.assertEqual(status.timeout_count, 1)
            self.assertEqual(status.completed_count, 0)
            self.assertEqual(status.failure_count, 0)
            await bridge.aclose()

        asyncio.run(scenario())

    def test_aclose_cancels_active_tick_before_session_teardown(self):
        async def scenario():
            adapter = StubAdapter(delay=10.0)
            bridge = ScheduledAutonomousCognitionBridge(
                adapter=adapter,
                owner_loop=asyncio.get_running_loop(),
                timeout_s=30.0,
            )
            bridge.mark_installed()

            started = asyncio.Event()

            original_tick = adapter.tick_once

            async def tracked_tick():
                started.set()
                return await original_tick()

            adapter.tick_once = tracked_tick  # type: ignore[method-assign]

            thread = threading.Thread(
                target=bridge.on_scheduler_tick,
                args=(tick_result(),),
                daemon=True,
            )
            thread.start()
            await asyncio.wait_for(started.wait(), timeout=1.0)
            await bridge.aclose()
            thread.join(1.0)
            self.assertFalse(thread.is_alive())
            self.assertTrue(adapter.cancelled)
            self.assertTrue(bridge.status().closed)

        asyncio.run(scenario())

    def test_lifespan_installs_after_inner_and_clears_before_inner_exit(self):
        async def scenario():
            events = []
            runtime = FakeSchedulerRuntime(events)
            app = SimpleNamespace(state=SimpleNamespace())
            adapter = StubAdapter()
            bridge_box = {}

            @asynccontextmanager
            async def inner(inner_app):
                events.append("inner:enter")
                inner_app.state.scheduler_runtime = runtime
                inner_app.state.consciousness_session = object()
                try:
                    yield
                finally:
                    self.assertIsNone(runtime.hook)
                    current = bridge_box["bridge"]
                    self.assertTrue(current.status().closed)
                    events.append("inner:exit")

            def bridge_factory(inner_app):
                self.assertTrue(
                    hasattr(inner_app.state, "consciousness_session")
                )
                bridge = ScheduledAutonomousCognitionBridge(
                    adapter=adapter,
                    owner_loop=asyncio.get_running_loop(),
                    timeout_s=1.0,
                )
                bridge_box["bridge"] = bridge
                return bridge

            composed = compose_autonomous_scheduler_lifespan(
                inner,
                bridge_factory=bridge_factory,
            )
            async with composed(app):
                events.append("outer:body")
                self.assertIsNotNone(runtime.hook)
                self.assertTrue(
                    hasattr(
                        app.state,
                        "consciousness_autonomous_scheduler",
                    )
                )

            self.assertEqual(
                events,
                [
                    "inner:enter",
                    "hook:set",
                    "outer:body",
                    "hook:clear",
                    "inner:exit",
                ],
            )
            self.assertFalse(
                hasattr(
                    app.state,
                    "consciousness_autonomous_scheduler",
                )
            )

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
